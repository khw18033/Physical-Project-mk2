"""Canonical Protobuf binding for the physical-command core contract.

implements: AI-C-07, AI-C-20, AI-C-04
tests: tests/test_physical_command_wire_alignment.py,
       tests/test_physical_command_gateway.py

이 모듈은 **와이어 경계 한 곳**이다. 의미 계약은
`contracts/physical_command.py` 가 소유하고 상위 인지·판단 코드는 여기서
생성된 protobuf 클래스를 업무 모델로 쓰지 않는다(AI-C-07). 그래서 HW 쪽
필드 이름(`deadline_unix_ms`, `state`, `device_id`, `actions`)은 이 파일
밖으로 나가지 않는다 — 나가는 것은 우리 어휘(`deadline`, `status`,
`command_id`, `name`)로 채운 dict 뿐이다.

## 2026-09-19 와이어 정렬 (spec §8)

와이어 형식을 HW 파트 `schema/physical_command.proto`(package `physical`)에
맞췄다. 생성된 descriptor 바이트가 HW 가 배포 중인 `physical_command_pb2.py`
와 동일함을 확인했고, 가시화 파트의 `protocol.js` 도 같은 번호를 쓴다.
정렬 전에는 enum 값 1이 우리 쪽 `ACCEPTED`, HW 쪽 `SUCCEEDED` 여서
**수락과 완료가 오류 없이 뒤바뀌었다** — AI-C-20 이 구분하라고 못 박은 지점.

HW 와이어는 진행 상태와 종료 상태를 **다른 타입**으로 나눈다:

    ACCEPTED / EXECUTING / CANCELING  -> CommandStatus.state (문자열 어휘)
    SUCCEEDED / ABORTED / CANCELED    -> CommandResult.status (TerminalStatus enum 1/2/3)

우리 `ExecutionStatus` 는 이 둘을 한 enum 으로 들고 있으므로 대응표를
아래 `_TERMINAL_TO_WIRE` / `_INFLIGHT_TO_WIRE` 에 **명시적으로** 둔다.
숫자를 우연히 맞히는 일이 없도록 두 표 모두 회귀 테스트가 숫자로 고정한다.

## 이 와이어가 싣지 못하는 것 (spec §8-3, 협의 대상)

아래 정보는 HW 와이어에 자리가 없다. **조용히 버리지 않는다** — 버릴 때마다
`wire_gaps` 카운터에 남기고(관측 가능), 물리 동작의 의미가 바뀌는 경우
(숫자가 아닌 parameters/result 값)에는 아예 `ValueError` 로 막는다.

    command.correlation_id            traceparent 형식이 아닐 때만 (아래 참고)
    command.parameters (비숫자)       map<string,double> — 문자열·불리언 불가 → 에러
    acceptance.accepted_at            HW 필드 3 은 rejection
    status.observed_at                HW 필드 3 은 detail
    result.completed_at               HW 필드 3 은 result map
    result.result (비숫자)            map<string,double> → 에러
    cancel_response.reason            HW 에 필드 없음
    capability.<선언 항목 전부>       HW Capability 는 device_id/actions 뿐이라
                                      AI-C-18 항목을 하나도 싣지 못한다(§8-3 P7).
                                      버린 값은 `capability.<field>`, 애초에 비어 있던
                                      칸은 `capability.undeclared.<item>` 로 **항목마다**
                                      센다. 받는 쪽 payload 에도 `undeclared_items` 로
                                      이름이 실려 '그렇다고 선언했다' 와 '못 왔다' 가
                                      구분된다.

시각 3종은 와이어에 없으므로 `decode()` 가 **수신 시각**으로 채우고
`time_source="edge_receipt"` 를 함께 넣는다. 장치가 그 동작을 실제로 한
시각이 아니라 우리가 그 바이트를 받은 시각이라는 뜻이다(AI-C-03).

## correlation_id 와 traceparent (2026-11-02)

정본 proto 가 `Command.traceparent = 6` 을 정했다(옛 §8-3 P1 의 해소). 우리
`correlation_id` 가 **유효한 W3C traceparent 일 때만** 그 칸에 싣고, 아니면
싣지 않고 gap 으로 남긴다. 아무 문자열이나 넣으면 받는 쪽이 그것으로 trace 를
이으려다 조용히 깨진다. 업무 책임 추적은 여전히 `command_id` 가 한다(AI-B-03).
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import fields as dataclass_fields, is_dataclass
from enum import Enum
from typing import Any, Callable

from mission_runtime.contracts.physical_command import (
    TERMINAL_STATUSES,
    Capability as _Capability,
    ExecutionStatus,
)
from mission_runtime.contracts.proto import physical_command_pb2 as pb


# -- 의미 상태 <-> 와이어 표현 (AI-C-20) ------------------------------------
# 값은 HW schema/physical_command.proto 의 TerminalStatus 그대로다. 절대
# 재정렬하지 않는다 — 이 표가 바로 2026-09-19 이전에 깨져 있던 자리다.
_TERMINAL_TO_WIRE: dict[ExecutionStatus, int] = {
    ExecutionStatus.SUCCEEDED: pb.SUCCEEDED,  # 1
    ExecutionStatus.ABORTED: pb.ABORTED,      # 2
    ExecutionStatus.CANCELED: pb.CANCELED,    # 3
}
_WIRE_TO_TERMINAL: dict[int, ExecutionStatus] = {v: k for k, v in _TERMINAL_TO_WIRE.items()}

# 진행 중 상태는 enum 이 아니라 CommandStatus.state 의 문자열 어휘다.
_INFLIGHT_TO_WIRE: dict[ExecutionStatus, str] = {
    ExecutionStatus.ACCEPTED: "ACCEPTED",
    ExecutionStatus.EXECUTING: "EXECUTING",
    ExecutionStatus.CANCELING: "CANCELING",
}
_WIRE_TO_INFLIGHT: dict[str, ExecutionStatus] = {v: k for k, v in _INFLIGHT_TO_WIRE.items()}

_MESSAGE_TYPES = (
    "command", "cancel_request", "acceptance", "status", "result",
    "cancel_response", "capability",
)
_CLASS_TYPES = {
    "Command": "command",
    "CommandAcceptance": "acceptance",
    "CommandResult": "result",
    "CommandStatus": "status",
    "CancelCommandRequest": "cancel_request",
    "CancelCommandResponse": "cancel_response",
    "Capability": "capability",
}

#: `decode()` 가 채운 시각이 장치 보고가 아니라 엣지 수신 시각임을 나타낸다.
TIME_SOURCE_EDGE_RECEIPT = "edge_receipt"

#: 이 와이어로 온 Capability 선언이 **어디까지 담고 있는가**. 닫힌 어휘이고,
#: 와이어가 넓어지는 날 값이 하나 더 생긴다(그것이 spec §8-3 P7 의 해소다).
DECLARATION_SCOPE_ACTIONS_ONLY = "actions_only"
CAPABILITY_DECLARATION_SCOPES: tuple[str, ...] = (DECLARATION_SCOPE_ACTIONS_ONLY,)

#: 이 와이어가 Capability 선언에서 **싣지 못하는** 칸들. 목록을 손으로 적지 않고
#: 의미 계약의 필드에서 뽑는다 — 새 선언 항목을 계약에 더하고 여기를 잊으면
#: 그 항목만 조용히 사라진다.
_CAPABILITY_WIRE_FIELDS = frozenset({"name", "device_id", "actions"})
_CAPABILITY_WIRELESS_FIELDS: tuple[str, ...] = tuple(
    f.name for f in dataclass_fields(_Capability) if f.name not in _CAPABILITY_WIRE_FIELDS
)

#: 그래서 이 와이어로 온 선언은 **항상** 아래 AI-C-18 항목을 적지 못한 상태다.
#: `Capability(name=...)` 하나를 만들어 물어보면 그 목록이 나온다 — 두 번 적지
#: 않으려고 계약에 직접 묻는다.
CAPABILITY_DECLARATION_ITEMS_LOST_ON_WIRE: tuple[str, ...] = _Capability(
    name="_probe"
).undeclared_items()


#: W3C Trace Context `traceparent` — version(2) "-" trace-id(32) "-" span-id(16)
#: "-" flags(2), 모두 소문자 16진수. 전부 0 인 trace-id/span-id 는 규격이 무효로
#: 정의한다. 우리가 이 검사를 하는 이유는 하나다 — 받는 쪽이 이 칸으로 trace 를
#: 잇기 때문에 형식이 틀리면 조용히 깨진다.
_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def is_w3c_traceparent(value: str) -> bool:
    match = _TRACEPARENT.match(value)
    if match is None:
        return False
    _, trace_id, span_id, _ = value.split("-")
    return set(trace_id) != {"0"} and set(span_id) != {"0"}


def _value(item: Any) -> Any:
    return item.value if isinstance(item, Enum) else item


def _as_payload(obj: Any) -> dict[str, Any]:
    """dataclass/dict 를 우리 어휘의 평평한 dict 로. 값 변환은 하지 않는다."""
    if is_dataclass(obj):
        data = {}
        for key, item in vars(obj).items():
            if is_dataclass(item):
                data[key] = _as_payload(item)
            else:
                data[key] = _value(item)
        return data
    if isinstance(obj, dict):
        return dict(obj)
    raise TypeError("physical command protobuf requires a contract dataclass or envelope dict")


class PhysicalCommandProtobufSerializerProvider:
    """Serialize one physical lifecycle message in a typed oneof envelope.

    와이어 규약: HW `package physical` (spec §8). `wire_gaps` 는 이 인스턴스가
    지금까지 버린 정보의 카운터이고, `on_gap` 을 주면 AI-O-02 사건 기록으로
    바로 흘릴 수 있다.
    """

    format_id = "physical_command_protobuf_v1"
    human_readable = False
    #: 어떤 규약의 바이트를 만드는지 — 디버깅·협의 때 이 문자열을 인용한다.
    wire_package = "physical"
    wire_source = "hardware/schema/physical_command.proto (정본, 2026-11-02 · traceparent 포함)"

    def __init__(self, on_gap: Callable[[str, Any], None] | None = None) -> None:
        self.wire_gaps: Counter[str] = Counter()
        self._on_gap = on_gap

    # -- 정보 손실 기록 -------------------------------------------------
    def _gap(self, field: str, value: Any) -> None:
        """와이어에 자리가 없어 싣지 못한 값 1건. 조용히 사라지지 않게 한다."""
        self.wire_gaps[field] += 1
        if self._on_gap is not None:
            self._on_gap(field, value)

    def _drop_if_set(self, field: str, value: Any, *, empty: Any = None) -> None:
        if value != empty and value is not None:
            self._gap(field, value)

    # -- encode ---------------------------------------------------------

    def encode(self, obj: Any) -> bytes:
        if is_dataclass(obj):
            message_type = _CLASS_TYPES.get(type(obj).__name__)
            payload = _as_payload(obj)
        elif isinstance(obj, dict):
            message_type = obj.get("message_type")
            payload = _as_payload(obj.get("payload", {}))
        else:
            raise TypeError("physical command protobuf requires a contract dataclass or envelope dict")
        if message_type not in _MESSAGE_TYPES:
            raise ValueError(f"unsupported physical message type: {message_type}")

        envelope = pb.PhysicalCommandEnvelope()
        getattr(self, f"_encode_{message_type}")(getattr(envelope, message_type), payload)
        return envelope.SerializeToString(deterministic=True)

    def _numeric_map(self, target, values: Any, where: str) -> None:
        """`map<string,double>` 채우기.

        결측은 키를 아예 넣지 않는다(0/-1/"" 로 채우지 않는다 — 전부 0 인
        텔레메트리로 배터리 경보가 오발동한 2026-09-10 사고의 규칙).
        숫자가 아닌 값은 **버리지 않고 막는다**: 조용히 떨어뜨리면 장치가
        받는 명령의 의미가 달라진다(AI-C-20).
        """
        if not values:
            return
        if not isinstance(values, dict):
            raise TypeError(f"{where} must be a mapping")
        for key, item in values.items():
            if item is None:
                self._gap(f"{where}.<null-value>", key)
                continue
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
                raise ValueError(
                    f"{where}['{key}']={item!r}: HW 와이어의 map<string,double> 는 유한한 숫자만 "
                    "싣는다. 문자열·불리언·중첩 값은 이 규약으로 전달할 수 없다 — "
                    "spec §8-3 P2(협의 대상) 참고."
                )
            target[str(key)] = float(item)

    def _encode_command(self, msg, payload: dict) -> None:
        msg.command_id = payload["command_id"]
        msg.target = payload["target"]
        msg.action = payload["action"]
        self._numeric_map(msg.parameters, payload.get("parameters"), "command.parameters")
        deadline = payload.get("deadline")
        if deadline is not None:
            msg.deadline_unix_ms = int(round(float(deadline) * 1000.0))
        correlation_id = payload.get("correlation_id")
        if correlation_id is not None and is_w3c_traceparent(str(correlation_id)):
            msg.traceparent = str(correlation_id)
        else:
            # 형식이 맞지 않는 상관 ID 는 traceparent 칸에 넣지 않는다 — 넣으면
            # 받는 쪽의 trace 조립이 조용히 깨진다. 싣지 못한 사실만 남긴다.
            self._drop_if_set("command.correlation_id", correlation_id)

    def _encode_cancel_request(self, msg, payload: dict) -> None:
        msg.command_id = payload["command_id"]

    def _encode_acceptance(self, msg, payload: dict) -> None:
        msg.command_id = payload["command_id"]
        msg.accepted = bool(payload["accepted"])
        rejection = payload.get("rejection")
        if rejection:
            msg.rejection.code = str(_value(rejection["code"]))
            msg.rejection.message = str(rejection.get("message", ""))
        # 장치가 수락한 시각을 실을 자리가 없다(HW 필드 3 = rejection).
        self._drop_if_set("acceptance.accepted_at", payload.get("accepted_at"))

    def _encode_status(self, msg, payload: dict) -> None:
        status = ExecutionStatus(_value(payload["status"]))
        if status in TERMINAL_STATUSES:
            raise ValueError(
                f"CommandStatus 에 종료 상태({status.value})를 실을 수 없다 — "
                "종료는 CommandResult 로만 보고한다(spec §4)."
            )
        msg.command_id = payload["command_id"]
        msg.state = _INFLIGHT_TO_WIRE[status]
        detail = payload.get("detail")
        if detail:
            msg.detail = str(detail)
        self._drop_if_set("status.observed_at", payload.get("observed_at"))

    def _encode_result(self, msg, payload: dict) -> None:
        status = ExecutionStatus(_value(payload["status"]))
        if status not in _TERMINAL_TO_WIRE:
            raise ValueError(
                f"CommandResult.status 는 종료 상태여야 한다(got {status.value}) — spec §4."
            )
        msg.command_id = payload["command_id"]
        msg.status = _TERMINAL_TO_WIRE[status]
        self._numeric_map(msg.result, payload.get("result"), "result.result")
        failure = payload.get("failure")
        if failure:
            msg.failure.code = str(_value(failure["code"]))
            msg.failure.message = str(failure.get("message", ""))
        self._drop_if_set("result.completed_at", payload.get("completed_at"))

    def _encode_cancel_response(self, msg, payload: dict) -> None:
        msg.command_id = payload["command_id"]
        msg.accepted = bool(payload["accepted"])
        self._drop_if_set("cancel_response.reason", payload.get("reason"))

    def _encode_capability(self, msg, payload: dict) -> None:
        """우리 Capability(AI-C-18 선언) -> HW Capability(device_id + actions).

        HW 와이어는 action **이름 목록**만 싣는다. 나머지 선언 항목은 자리가
        없어 전부 gap 으로 기록된다(spec §8-3 P7).
        """
        msg.device_id = str(payload.get("device_id", "") or "")
        actions = payload.get("actions")
        if actions is None:
            actions = [payload["name"]] if payload.get("name") else []
        msg.actions.extend(str(a) for a in actions)
        for field_name in _CAPABILITY_WIRELESS_FIELDS:
            value = payload.get(field_name)
            # None(미선언)은 잃을 것이 없다. False·빈 묶음은 **선언된 값**이므로
            # 센다 — "취소 불가" 를 선언한 장치의 그 선언이 조용히 사라지면 받는
            # 쪽은 미선언과 구분할 수 없다.
            if value is None:
                continue
            if isinstance(value, (tuple, list, dict)) and not value:
                continue
            self._gap(f"capability.{field_name}", value)

    # -- decode ---------------------------------------------------------

    def decode(self, payload: bytes, schema_hint: str | None = None) -> dict[str, Any]:
        envelope = pb.PhysicalCommandEnvelope()
        envelope.ParseFromString(payload)
        field = envelope.WhichOneof("body")
        if field is None:
            raise ValueError("physical command protobuf envelope has no body")
        received_at = time.time()
        body = getattr(self, f"_decode_{field}")(getattr(envelope, field), received_at)
        return {"message_type": field, "payload": body}

    def _decode_command(self, msg, _received_at: float) -> dict[str, Any]:
        body: dict[str, Any] = {
            "command_id": msg.command_id, "target": msg.target, "action": msg.action,
            "parameters": {key: value for key, value in msg.parameters.items()},
        }
        if msg.deadline_unix_ms:
            body["deadline"] = msg.deadline_unix_ms / 1000.0
        # 빈 traceparent 는 "없음"이고 그때는 칸을 만들지 않는다 — 빈 문자열을
        # 상관 ID 로 올리면 trace 가 없는 명령과 구분되지 않는다.
        if msg.traceparent:
            body["correlation_id"] = msg.traceparent
        return body

    def _decode_cancel_request(self, msg, _received_at: float) -> dict[str, Any]:
        return {"command_id": msg.command_id}

    def _decode_acceptance(self, msg, received_at: float) -> dict[str, Any]:
        body: dict[str, Any] = {
            "command_id": msg.command_id, "accepted": msg.accepted,
            "accepted_at": received_at, "time_source": TIME_SOURCE_EDGE_RECEIPT,
        }
        if msg.HasField("rejection"):
            body["rejection"] = {"code": msg.rejection.code, "message": msg.rejection.message}
        elif not msg.accepted:
            raise ValueError("거부인데 rejection 이 없다 — 사유 없는 거부는 계약 위반(spec §3)")
        return body

    def _decode_status(self, msg, received_at: float) -> dict[str, Any]:
        state = msg.state.strip().upper()
        if state not in _WIRE_TO_INFLIGHT:
            raise ValueError(
                f"CommandStatus.state='{msg.state}' 는 진행 중 상태 어휘가 아니다 "
                f"(허용: {sorted(_WIRE_TO_INFLIGHT)}) — spec §4."
            )
        body: dict[str, Any] = {
            "command_id": msg.command_id, "status": _WIRE_TO_INFLIGHT[state].value,
            "observed_at": received_at, "time_source": TIME_SOURCE_EDGE_RECEIPT,
        }
        if msg.detail:
            # 우리 의미 모델에는 아직 이 자리가 없다. 정보를 여기서 버리지는
            # 않고 payload 로 넘긴다(소비하려면 AI-C-01 사전 등록이 먼저다).
            body["detail"] = msg.detail
        return body

    def _decode_result(self, msg, received_at: float) -> dict[str, Any]:
        if msg.status not in _WIRE_TO_TERMINAL:
            raise ValueError(
                f"CommandResult.status={msg.status} 는 종료 상태가 아니다 — spec §4."
            )
        body: dict[str, Any] = {
            "command_id": msg.command_id, "status": _WIRE_TO_TERMINAL[msg.status].value,
            "completed_at": received_at, "time_source": TIME_SOURCE_EDGE_RECEIPT,
        }
        if len(msg.result):
            body["result"] = {key: value for key, value in msg.result.items()}
        if msg.HasField("failure"):
            body["failure"] = {"code": msg.failure.code, "message": msg.failure.message}
        return body

    def _decode_cancel_response(self, msg, _received_at: float) -> dict[str, Any]:
        # reason 은 와이어에 없다 — 없는 사유를 지어내지 않는다.
        return {"command_id": msg.command_id, "accepted": msg.accepted}

    def _decode_capability(self, msg, _received_at: float) -> dict[str, Any]:
        for item in CAPABILITY_DECLARATION_ITEMS_LOST_ON_WIRE:
            # 받는 쪽에서도 **항목 단위로** 센다. 보내는 쪽의 `wire_gaps` 는
            # 우리가 버린 것을 세지만, 장치가 보내 온 선언에서 비어 있는 칸은
            # 이쪽에서만 보인다 — 그 수가 곧 spec §8-3 P7 의 크기다.
            self._gap(f"capability.undeclared.{item}", None)
        return {
            "device_id": msg.device_id,
            "actions": list(msg.actions),
            # 이 선언이 action 이름까지만 담고 있다는 사실 자체를 남긴다
            # (AI-C-18: 모든 항목이 항상 존재한다고 가정하지 않는다).
            "declaration_scope": DECLARATION_SCOPE_ACTIONS_ONLY,
            # 어느 항목이 비어 있는지를 이름으로 남긴다. 소비자는 이 목록을 보고
            # "장치가 그렇다고 선언했다" 와 "와이어에 자리가 없어 못 왔다" 를
            # 구분한다. 빈 칸을 기본값으로 채워 보내지 않는 것이 전제다.
            "undeclared_items": list(CAPABILITY_DECLARATION_ITEMS_LOST_ON_WIRE),
        }
