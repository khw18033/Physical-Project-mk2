"""VDA 5050 어댑터 — **우리 의미 계약이 외부 표준으로 나가는지**의 증거.

implements: AI-C-20 (물리 명령 의미 계약), AI-C-04 (외부 기술·제공자 어댑터),
            AI-B-09 (신규 확장 등록), AI-C-18 (capability 선언)
관련: AI-C-05 (없으면 축소), AI-C-07 (직렬화는 의미와 분리)
tests: tests/test_vda5050_robot.py

## 왜 이걸 만드나

"범용" 은 주장으로는 못 보인다. **다른 사람이 정한 명령 규약**에 우리 계약을
맞춰 보면 드러난다 — 맞으면 경계가 옳았던 것이고, 안 맞으면 어디가 우리 사정에
기대고 있었는지가 그 자리에서 보인다.

VDA 5050 은 AGV·AMR 의 마스터 제어 ↔ 차량 통신 규약이다(독일 자동차공업협회).
우리가 고른 이유는 셋이다 — 공개 규약이고, 명령·상태·즉시동작이 우리 셋과 같은
축이고, **런타임이 아니라 메시지 형식**이라 의존성이 늘지 않는다.

## 어느 층에 붙나 — `RobotControlBackend` 다

`HardwareCommandProvider` 가 아니다. 그쪽은 `Command` 전체와 lifecycle 을 보는
자리이고, 거기에 붙이면 **수락·거부·멱등·기한을 벤더 글루가 다시 구현**하게 된다.
AI-C-20 이 요구하는 것들은 `execution/robot_adapter.py` 가 이미 위에서 강제하므로,
여기는 "행동 이름과 파라미터" 만 본다. 계약 모양의 것이 남아 있지 않아야 벤더
어댑터 작성자가 계약을 **실수로** 틀릴 수 없다.

## 번역하지 못하는 것은 번역하지 않는다

VDA 5050 에 없는 행동은 `None` 을 내고 사유를 남긴다. 억지로 가장 비슷한 것으로
바꾸면 **로봇이 시킨 적 없는 일을 한다.** 지원하지 않는 명령을 실물에 보내지
않는 것이 이 어댑터의 가장 중요한 성질이다.

## 안전 경로는 네트워크를 지나지 않는다

`emergency_stop()` 은 VDA 5050 의 `instantActions` 로 **보낼 수 있지만**, 그것이
유일한 안전 경로여서는 안 된다(AI-C-20). 이 어댑터는 장치 자신의 정지 경로를
주입받고, 없으면 **없다고 말한다** — 있는 척하면 그게 가장 위험하다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from mission_runtime.contracts.capability_contract import Capability

#: VDA 5050 의 주행/동작 어휘 → 우리 행동 이름. **데이터다** — 새 매핑은 한 줄이다.
DEFAULT_ACTION_MAP: dict[str, str] = {
    "move_to": "order",                  # 노드 열로 나간다
    "pick": "pick",
    "drop": "drop",
    "wait": "waitForTrigger",
    "charge": "startCharging",
    "stop_charge": "stopCharging",
    "init_position": "initPosition",
}

#: 주행 명령의 VDA 5050 이름. **이것 하나만 노드 열(order)로 나가고 나머지는 전부
#: 즉시 동작(instantAction)이다.** 목록으로 가르면 새 벤더 어휘가 주행 열에 끼어
#: 앞의 주행이 끝나야 실행된다 — 목록을 고치는 걸 잊으면 조용히 그렇게 된다.
DRIVING_ACTION = "order"

REASON_UNMAPPED = "action_not_in_vda5050_vocabulary"
REASON_NO_TRANSPORT = "no_transport_configured"
REASON_NO_LOCAL_STOP = "no_local_stop_path"
REASON_NOT_READY = "vehicle_not_ready"


@dataclass(frozen=True)
class VehicleState:
    """차량이 보고한 것. **우리가 판정하지 않는다** — 받아 적는다(AI-O-04)."""

    order_id: str | None = None
    last_node_id: str | None = None
    driving: bool = False
    errors: tuple[str, ...] = ()
    battery_charge: float | None = None
    received_at: float | None = None

    @classmethod
    def from_vda(cls, raw: dict[str, Any]) -> "VehicleState":
        battery = (raw.get("batteryState") or {}).get("batteryCharge")
        return cls(
            order_id=raw.get("orderId") or None,
            last_node_id=raw.get("lastNodeId") or None,
            driving=bool(raw.get("driving")),
            errors=tuple(str(e.get("errorType", "unknown"))
                         for e in raw.get("errors") or ()),
            battery_charge=float(battery) if battery is not None else None,
            received_at=time.time())


def to_order(action: str, parameters: dict[str, Any], *, command_id: str,
             order_update_id: int = 0, action_map: dict[str, str] | None = None
             ) -> dict[str, Any] | None:
    """우리 행동 하나 → VDA 5050 메시지. **어휘 밖이면 None 이다.**

    `command_id` 를 `orderId` 로 그대로 쓴다 — 우리 쪽 식별자가 정본이고, 차량이
    돌려주는 `orderId` 로 어느 명령의 상태인지 되짚는다(AI-C-03: 원본 참조).
    """
    mapped = (action_map or DEFAULT_ACTION_MAP).get(action)
    if mapped is None:
        return None

    header = {
        "headerId": order_update_id,
        "timestamp": _iso(time.time()),
        "version": "2.0.0",
        "manufacturer": parameters.get("manufacturer", "unknown"),
        "serialNumber": parameters.get("serial_number", "unknown"),
    }
    if mapped != DRIVING_ACTION:
        return {**header, "actions": [{
            "actionType": mapped,
            "actionId": command_id,
            "blockingType": "HARD",
            "actionParameters": _params(parameters),
        }]}

    nodes = parameters.get("nodes")
    if not nodes:
        # move_to 인데 갈 곳이 없다 — 지어내지 않는다
        return None
    return {**header,
            "orderId": command_id,
            "orderUpdateId": order_update_id,
            "nodes": [_node(n, index) for index, n in enumerate(nodes)],
            "edges": _edges(len(nodes))}


def _node(raw: Any, index: int) -> dict[str, Any]:
    if isinstance(raw, dict):
        node = dict(raw)
        node.setdefault("sequenceId", index * 2)
        node.setdefault("released", True)
        return node
    return {"nodeId": str(raw), "sequenceId": index * 2, "released": True, "actions": []}


def _edges(node_count: int) -> list[dict[str, Any]]:
    return [{"edgeId": f"e{i}", "sequenceId": i * 2 + 1, "released": True,
             "startNodeId": f"n{i}", "endNodeId": f"n{i + 1}", "actions": []}
            for i in range(max(0, node_count - 1))]


def _params(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    skip = {"manufacturer", "serial_number", "nodes"}
    return [{"key": key, "value": value}
            for key, value in sorted(parameters.items()) if key not in skip]


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class Vda5050RobotBackend:
    """`RobotControlBackend` 를 VDA 5050 으로 구현한다.

    전송을 직접 열지 않는다 — 보내는 함수 하나를 주입받는다(AI-C-04). MQTT 든
    무엇이든 이 클래스는 모른다. 그래서 시험이 브로커 없이 전부 돈다.
    """

    manufacturer: str
    serial_number: str
    #: `(topic, payload) -> bool`. 없으면 이 backend 는 **준비되지 않았다**고 말한다.
    publish: Callable[[str, dict[str, Any]], bool] | None = None
    #: 장치 자신의 정지 경로. **네트워크를 지나지 않는다**(AI-C-20).
    local_stop: Callable[[str], bool] | None = None
    action_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ACTION_MAP))
    state: VehicleState = field(default_factory=VehicleState)
    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _header_id: int = 0

    # --- 선언 (AI-C-18) ----------------------------------------------------
    def declared_actions(self) -> tuple[Capability, ...]:
        """어휘에 있는 것만 선언한다. **못 하는 것을 선언하지 않는다.**"""
        return tuple(Capability(kind=action) for action in sorted(self.action_map))

    def readiness(self) -> tuple[bool, str | None]:
        """전제 조건이지 **가용성 판정이 아니다**(AI-O-04)."""
        if self.publish is None:
            return False, REASON_NO_TRANSPORT
        if self.state.errors:
            return False, f"{REASON_NOT_READY}:{self.state.errors[0]}"
        return True, None

    # --- 실행 --------------------------------------------------------------
    def execute(self, action: str, parameters: dict,
                *, command_id: str) -> tuple[bool, dict | None, str | None]:
        ready, why = self.readiness()
        if not ready:
            return False, None, why

        self._header_id += 1
        message = to_order(action, {**parameters,
                                    "manufacturer": self.manufacturer,
                                    "serial_number": self.serial_number},
                           command_id=command_id,
                           order_update_id=self._header_id,
                           action_map=self.action_map)
        if message is None:
            # **번역하지 못하는 것을 비슷한 것으로 바꾸지 않는다**
            return False, None, REASON_UNMAPPED

        topic = self._topic("instantActions" if "actions" in message else "order")
        ok = bool(self.publish(topic, message))
        self.sent.append((topic, message))
        if not ok:
            return False, None, "publish_failed"
        # 보낸 것은 **수락이 아니다** — 상태는 차량이 돌려준다(AI-C-20)
        return True, {"topic": topic, "order_id": message.get("orderId", command_id)}, None

    def request_stop(self, command_id: str) -> bool:
        """정지 절차에 들어갔는지. **멈췄다는 뜻이 아니다**(AI-C-20)."""
        if self.publish is None:
            return False
        message = to_order("stop", {"manufacturer": self.manufacturer,
                                    "serial_number": self.serial_number},
                           command_id=command_id, action_map={"stop": "stop"})
        topic = self._topic("instantActions")
        self.sent.append((topic, message))
        return bool(self.publish(topic, message))

    def emergency_stop(self, reason: str) -> bool:
        """장치 자신의 경로. **없으면 없다고 말한다** — 있는 척이 가장 위험하다."""
        if self.local_stop is None:
            return False
        return bool(self.local_stop(reason))

    def emergency_stop_reason(self) -> str | None:
        return None if self.local_stop is not None else REASON_NO_LOCAL_STOP

    # --- 받기 --------------------------------------------------------------
    def accept_state(self, raw: dict[str, Any] | str) -> VehicleState:
        """차량 상태 메시지. 직렬화는 의미와 **분리**되어 있다(AI-C-07)."""
        payload = json.loads(raw) if isinstance(raw, str) else raw
        self.state = VehicleState.from_vda(payload)
        return self.state

    def _topic(self, kind: str) -> str:
        return f"uagv/v2/{self.manufacturer}/{self.serial_number}/{kind}"
