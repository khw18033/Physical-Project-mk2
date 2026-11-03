"""Runs the devices the console discovers and commands.

implements: AI-C-18 (장치가 스스로 capability 를 알린다), AI-C-20 (물리 명령 의미 계약)
관련: AI-C-10 (탐색), AI-C-19 (명령 발급은 백엔드 몫이고 AI 는 요청만 한다)

## 왜 이 파일이 있는가

콘솔이 "구역에 어떤 로봇이 있는지"를 선언에서 읽으면 그것은 탐지가 아니다. 실제
탐지는 장치가 접속 직후 자기 명령 어휘를 스스로 알리고(`Capability`), 그것을
`PhysicalCommandGateway` 가 받아 레지스트리에 등록하는 경로다. 하드웨어가 없는
자리에서도 **그 경로 자체**는 진짜여야 하므로, 여기서 장치 쪽을 세운다.

장치 쪽은 전부 이미 있는 구현을 조립한 것이다 — 새 계약을 만들지 않았다.

    FakeRobotBackend        providers/fakes.py      물리 효과를 행으로 남기는 백엔드
    TerminalRobotAdapter    execution/robot_adapter.py  수락·실행·취소·긴급정지
    PhysicalCommand*        providers/physical_command_protobuf.py  정본 wire 형식

없던 것은 **전송과 어댑터를 잇는 루프** 하나뿐이다. 게이트웨이는
`terminal/<id>/downlink` 로 명령을 내고 `terminal/<id>/uplink` 로 상태를 받는데,
그 사이에서 디코드해 어댑터에 넘기고 결과를 되돌려 보내는 쪽이 저장소에 없었다
(`services/` 의 장치 에이전트는 다른 경로를 쓴다). 그 루프가 `SimulatedDevice` 다.

## 전달 성공과 수락·완료를 구분한다

`issue()` 는 세 가지를 **따로** 돌려준다 — 전달했다, 수락/거부됐다, 끝났다.
전달 ACK 를 완료로 읽으면 중복 실행과 상태 오판이 생긴다(AI-C-20).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from mission_runtime.contracts.physical_command import (
    TERMINAL_STATUSES,
    CancelCommandRequest,
    Command,
    CommandStatus,
)
from mission_runtime.execution.physical_command_gateway import (
    PhysicalCommandGateway,
    downlink_topic,
    uplink_topic,
)
from mission_runtime.execution.robot_adapter import TerminalRobotAdapter
from mission_runtime.providers.fakes import FakeRobotBackend, InMemoryTransportProvider
from mission_runtime.providers.physical_command_protobuf import (
    PhysicalCommandProtobufSerializerProvider,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry

#: 역할별 명령 어휘 — **마지막 수단**이다.
#:
#: 2026-11-03: 이 표가 1순위였을 때 한 가지가 깨져 있었다. 새 역할(`fixed_manipulator`,
#: `rail_crawler` …)의 장치는 이 표에 없어서 아예 **세워지지 않았고**, 자원과 기능은
#: 화면에 보이는데 `presence` 가 영원히 `declared` 로 남고 명령은
#: `device_not_attached` 로 거절됐다. 출하된 `mt4` 가 그 상태였다. 역할 **이름**으로
#: 분기하는 표가 확장의 문턱이 된 것이고, 그것은 절대 준수 원칙 #3(이름 기준 분기
#: 금지)과 #7(확장은 코드 변경이 아니라 등록)이 같이 금지하는 모양이다.
#:
#: 그래서 어휘의 정본은 **장치 자신의 선언**이다 — 조인 선언의 `declared_actions`
#: (AI-C-18) 이고, 설정 행으로 들어와 `vocabularies_from_config()` 가 읽는다. 이 표는
#: 아무것도 선언하지 않은 옛 노드를 위한 되돌림 값으로만 남는다.
ROLE_ACTIONS: dict[str, tuple[str, ...]] = {
    "ugv": ("move_forward", "turn", "stop", "scan_mission", "return_home"),
    "uav": ("takeoff", "goto_waypoint", "land", "stop", "return_home"),
    "fixed_camera": ("set_yaw", "capture_still"),
    "edge": (),
    "server": (),
}


def vocabularies_from_config(path: str | Path) -> dict[str, tuple[str, ...]]:
    """설정 행에 선언된 명령 어휘를 읽는다. 이것이 어휘의 정본이다.

    `registry/onboarding.py::node_config_entry()` 가 조인 선언의 `declared_actions` 를
    이 칸으로 옮기므로, 장치를 들고 오는 쪽이 설정 한 줄을 더하면 끝이고 이 파일을
    고칠 일이 없다. 선언하지 않은 노드는 비어서 돌아오고 호출자가 역할 표로 되돌린다.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        node["node_id"]: tuple(node["declared_actions"])
        for node in raw.get("nodes", ())
        if node.get("declared_actions")
    }

#: 명령 하나가 끝나기를 기다리는 한계. 끝나지 않아도 예외가 아니라 "아직 진행 중"이다.
RESULT_WAIT_S = 3.0


class WireSafeRobotBackend(FakeRobotBackend):
    """`FakeRobotBackend` 그대로 쓰되 **결과만** wire 에 실리는 모양으로 낸다.

    정본 proto 의 `CommandResult.result` 는 `map<string,double>` 이라 숫자만
    실린다. 시험용 fake 는 `{"action": "move_forward"}` 처럼 문자열을 돌려주는데,
    그것은 시험 안에서는 문제가 없지만 이 데모는 실제 wire 로 내보내므로 인코딩에서
    막힌다. 그래서 수락·멱등·취소·긴급정지 같은 **계약 동작은 전부 물려받고**
    결과 payload 만 숫자로 바꾼다 — fake 를 고치면 그 시험들의 의미가 바뀐다.
    """

    def execute(self, action: str, parameters: dict, *, command_id: str):
        started = time.monotonic()
        succeeded, _result, failure = super().execute(
            action, parameters, command_id=command_id)
        if not succeeded:
            return succeeded, None, failure
        return True, {"elapsed_ms": round((time.monotonic() - started) * 1000.0, 3)}, None


@dataclass
class SimulatedDevice:
    """한 대의 장치. 정본 wire 로 명령을 받고 같은 wire 로 상태를 돌려준다."""

    device_id: str
    transport: Any
    actions: tuple[str, ...]
    _adapter: TerminalRobotAdapter = field(init=False)
    _backend: FakeRobotBackend = field(init=False)
    _wire: Any = field(init=False)

    def __post_init__(self) -> None:
        self._wire = PhysicalCommandProtobufSerializerProvider()
        self._backend = WireSafeRobotBackend(actions=self.actions, fully_declared=True)
        self._adapter = TerminalRobotAdapter(self._backend, device_id=self.device_id)

    # -- 수신 ------------------------------------------------------------

    def start(self) -> None:
        self.transport.subscribe(downlink_topic(self.device_id), self._on_downlink)

    def announce(self) -> None:
        """접속 직후 자기 어휘를 알린다. 이것이 탐지의 근거다(AI-C-18)."""
        for capability in self._adapter.capabilities():
            self.transport.publish(
                uplink_topic(self.device_id),
                self._wire.encode({"message_type": "capability", "payload": {
                    "device_id": self.device_id,
                    "name": capability.name,
                    "version": capability.version,
                    "parameter_schema": capability.parameter_schema,
                    "result_schema": capability.result_schema,
                    "cancel_supported": capability.cancel_supported,
                }}),
            )

    def _on_downlink(self, payload: bytes, *_rest: Any) -> None:
        try:
            envelope = self._wire.decode(payload)
        except Exception:
            return  # 디코드 실패는 이 장치의 문제가 아니다 — 조용히 버린다
        kind = envelope.get("message_type")
        body = envelope.get("payload", {})
        if kind == "command":
            self._handle_command(body)
        elif kind == "cancel_request":
            self._handle_cancel(body)

    def _handle_command(self, body: dict) -> None:
        command = Command(
            command_id=body.get("command_id", ""),
            target=body.get("target", self.device_id),
            action=body.get("action", ""),
            parameters=dict(body.get("parameters") or {}),
        )
        # 비동기로 수락한다 — 그래야 ACCEPTED/EXECUTING 이라는 **실행 중** 순간이
        # 실제로 존재하고, 수락과 완료가 같은 사건으로 뭉개지지 않는다(AI-C-20 §3).
        acceptance = self._adapter.submit_async(command)
        self._publish(acceptance)
        # 거부에는 실행 상태도 결과도 따라오지 않는다(AI-C-20 §4).
        if not getattr(acceptance, "accepted", False):
            return
        self._publish_status(command.command_id)
        result = self._adapter.wait(command.command_id, RESULT_WAIT_S)
        if result is not None:
            self._publish(result)

    def _handle_cancel(self, body: dict) -> None:
        command_id = body.get("command_id", "")
        response = self._adapter.cancel(CancelCommandRequest(command_id=command_id))
        # 취소 요청의 수락과 실제 CANCELED 도달은 다른 사건이다(AI-C-20).
        self._publish(response)
        self._publish_status(command_id)
        result = self._adapter.wait(command_id, RESULT_WAIT_S)
        if result is not None:
            self._publish(result)

    def _publish_status(self, command_id: str) -> None:
        """진행 중 상태만 상태 메시지로 낸다.

        `CommandStatus` 는 종료 상태를 싣지 못한다(계약이 거부한다) — 종료는
        `CommandResult` 하나로만 말해야 하고, 둘을 겹쳐 보내면 "끝났다"가 두 번
        서로 다른 모양으로 온다.
        """
        status = self._adapter.get_status(command_id)
        if status is None or status in TERMINAL_STATUSES:
            return
        self._publish(CommandStatus(command_id=command_id, status=status,
                                    observed_at=time.time()))

    def _publish(self, message: Any) -> None:
        self.transport.publish(uplink_topic(self.device_id), self._wire.encode(message))

    # -- 조회 ------------------------------------------------------------

    @property
    def physical_executions(self) -> list[tuple[str, dict, str]]:
        """실제로 물리 실행이 일어난 행. 같은 command_id 가 두 번 나오면 멱등 위반이다."""
        return self._backend.executed


@dataclass
class FleetRuntime:
    """장치들 + 게이트웨이 + 탐지 결과를 한 묶음으로 들고 있다."""

    transport: Any
    registry: CapabilityRegistry
    #: 탐지 결과를 적을 곳. 콘솔의 FleetModel 이 들고 있는 그 객체다.
    discovery: Any
    devices: dict[str, SimulatedDevice] = field(default_factory=dict)
    _gateway: PhysicalCommandGateway = field(init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def __post_init__(self) -> None:
        self._gateway = PhysicalCommandGateway(
            self.transport,
            PhysicalCommandProtobufSerializerProvider(),
            registry=self.registry,
        )

    # -- 세우기 ----------------------------------------------------------

    def add(self, device_id: str, actions: Iterable[str]) -> SimulatedDevice:
        device = SimulatedDevice(device_id, self.transport, tuple(actions))
        self.devices[device_id] = device
        # 게이트웨이가 먼저 듣고 있어야 공지를 놓치지 않는다.
        self._gateway.attach(device_id)
        device.start()
        return device

    def announce_all(self) -> None:
        """모든 장치가 자기 어휘를 알리고, 그 결과를 탐지로 적는다."""
        for device_id, device in self.devices.items():
            device.announce()
        for device_id in self.devices:
            names = tuple(sorted(
                capability.name for capability in self._gateway.known_capabilities(device_id)))
            if names:
                self.discovery.note(device_id, names)

    def drop(self, device_id: str) -> None:
        """장치가 사라졌다. 탐지에서 지우고 레지스트리에서도 내린다."""
        self.discovery.forget(device_id)
        self._gateway.unregister_device(device_id)
        self.devices.pop(device_id, None)

    # -- 명령 (별도 계약) -------------------------------------------------

    def vocabulary(self, device_id: str) -> tuple[str, ...]:
        """게이트웨이가 **공지로 알게 된** 어휘. 선언 파일에서 읽지 않는다."""
        return tuple(sorted(
            capability.name for capability in self._gateway.known_capabilities(device_id)))

    def issue(self, device_id: str, action: str, parameters: dict) -> dict:
        """명령 한 건. 전달·수락·실행·결과를 각각 따로 돌려준다."""
        if device_id not in self.devices:
            return {"error": "device_not_attached", "device_id": device_id}
        if action not in self.vocabulary(device_id):
            # 알리지 않은 action 을 보내지 않는다 — 어휘는 장치가 정한다.
            return {"error": "action_not_announced", "device_id": device_id,
                    "action": action, "announced": list(self.vocabulary(device_id))}

        # 정본 wire 의 parameters 는 `map<string,double>` 이다 — 숫자만 실린다.
        # 문자열을 몰래 끼워 넣지 않고, 숫자가 아니면 보내기 전에 거절한다.
        numeric: dict[str, float] = {}
        for key, value in (parameters or {}).items():
            try:
                numeric[str(key)] = float(value)
            except (TypeError, ValueError):
                return {"error": "parameter_not_numeric", "parameter": str(key),
                        "value": str(value)}

        command_id = f"fms-{uuid.uuid4().hex[:12]}"
        command = Command(command_id=command_id, target=device_id, action=action,
                          parameters=numeric)
        with self._lock:
            self._gateway.send_command(device_id, command)
            result = self._gateway.wait_for_result(command_id, RESULT_WAIT_S)
            acceptance = self._gateway.get_acceptance(command_id)
            status = self._gateway.get_status(command_id)

        return {
            "command_id": command_id,
            "action": action,
            "delivered": True,
            "acceptance": None if acceptance is None else {
                "accepted": acceptance.accepted,
                # 거부 사유는 수락 결과에만 있다 — 실행 상태에 섞지 않는다(AI-C-20 §4).
                "rejection_code": _name_of(
                    getattr(acceptance.rejection, "code", None) if acceptance.rejection else None),
                "rejection_message": (
                    getattr(acceptance.rejection, "message", None) or None
                    if acceptance.rejection else None),
            },
            # 마지막으로 본 **진행 중** 상태. 종료는 아래 result 가 말한다.
            "status": None if status is None else {"state": _name_of(status)},
            "result": None if result is None else {
                "status": _name_of(result.status),
                "payload": dict(result.result or {}),
                "failure": None if result.failure is None else {
                    "code": result.failure.code, "message": result.failure.message},
            },
            # 결과가 아직 없으면 **실패가 아니라 진행 중**이다.
            "terminal": result is not None,
            "issued_at": time.time(),
        }


def _name_of(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or getattr(value, "value", None) or str(value)


def build_runtime(
    *,
    discovery: Any,
    registry: CapabilityRegistry,
    placements: dict[str, str | None],
    transport: Any | None = None,
    vocabularies: dict[str, tuple[str, ...]] | None = None,
    config_path: str | Path | None = None,
) -> FleetRuntime:
    """선언된 로봇들을 세우고 공지까지 끝낸 런타임을 돌려준다.

    어휘는 세 곳에서 찾되 **순서가 의미**다.

    1. `vocabularies` — 호출자가 직접 준 것(조인 선언에서 바로 온 경우)
    2. `config_path` 의 노드 행에 선언된 `declared_actions`
    3. `ROLE_ACTIONS` — 아무것도 선언하지 않은 옛 노드를 위한 되돌림

    1·2 가 정본이고 3 은 되돌림이다. 이 순서가 뒤집히면 새 역할의 장치가 표에 없다는
    이유로 세워지지 않고, 그것이 2026-11-03 에 발견된 확장 문턱이었다.

    어휘가 끝까지 비는 장치는 세우지 않는다 — 엣지·서버처럼 물리 명령을 받을 대상이
    아니기 때문이고, 그 경우는 누락이 아니라 정상이다.
    """
    declared = dict(vocabularies or {})
    if config_path is not None:
        # 호출자가 직접 준 것이 설정보다 우선한다 — 방금 조인한 장치가 아직 설정에
        # 없을 수 있고, 그때 설정이 이기면 새 장치가 세워지지 않는다.
        for device_id, actions in vocabularies_from_config(config_path).items():
            declared.setdefault(device_id, actions)

    runtime = FleetRuntime(
        transport=transport or InMemoryTransportProvider(),
        registry=registry,
        discovery=discovery,
    )
    for device_id, role in sorted(placements.items()):
        actions = declared.get(device_id) or ROLE_ACTIONS.get(role or "", ())
        if not actions:
            continue
        runtime.add(device_id, actions)
    runtime.announce_all()
    return runtime
