"""말단이 올리는 것을 받아 탐지·신선도를 채운다 — 그리고 축을 섞지 않는다.

implements: AI-O-04, AI-C-18
관련: AI-C-06, AI-C-04, 원칙 #15 (최종 가용성은 여기서 정하지 않는다)
tests: 공지 해독 · 중계 노드도 들은 것으로 세는 것 · action 을 중계 노드에 붙이지
       않는 것 · 해독 실패를 사유로 세는 것 · 발행 경로가 없는 것

## 2026-11-05 실기기에서 드러난 공백

`tools/view_service/fleet.py::Discovery` 의 docstring 이 "게이트웨이가 capability
공지를 받아 채운다" 고 적어 두었는데 **받는 쪽이 없었다.** 로봇은 pi7 의 브로커로
몇 초마다 말하고 있었고(`zoneA/robot/go1-001/{state,status,heartbeat}` + retained
`terminal/go1-001/uplink`), 화면만 영원히 offline 이었다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mission_runtime.integration.device_telemetry_source import (  # noqa: E402
    REASON_NO_DEVICE_ID,
    REASON_UNDECODABLE,
    TELEMETRY_TOPICS,
    UPLINK_TOPIC,
    DeviceTelemetrySource,
)


class FakeTransport:
    """구독만 받는다. **발행 메서드를 일부러 두지 않는다** — 이 경로가 명령을
    내지 않는다는 것을 자료형으로 못 박는다(AI-C-19)."""

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def subscribe(self, topic, handler):
        self.handlers.setdefault(topic, []).append(handler)

    def deliver(self, topic: str, payload: bytes) -> None:
        for pattern, hs in self.handlers.items():
            if _matches(pattern, topic):
                for h in hs:
                    h(payload)


def _matches(pattern: str, topic: str) -> bool:
    p, t = pattern.split("/"), topic.split("/")
    if len(p) != len(t):
        return False
    return all(a == "+" or a == b for a, b in zip(p, t))


class FakeSerializer:
    """실기기 와이어와 **같은 모양**을 돌려준다(실측에서 베꼈다)."""

    def __init__(self, body=None, fail=False):
        self.body, self.fail = body, fail

    def decode(self, payload, schema_hint=None):
        if self.fail:
            raise ValueError("not capability")
        return {"message_type": "capability", "payload": self.body}


class Sink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def note(self, device_id, actions, *, at=None):
        self.calls.append((device_id, tuple(actions)))


#: 실기기가 실제로 공지한 것(2026-11-05, go1-001). 숫자를 줄이지 않고 그대로 쓴다.
GO1_BODY = {
    "device_id": "go1-001",
    "actions": ["abort", "abort_mission", "assign_mission", "diag", "move_forward",
                "move_relative", "ping", "scan_continue", "scan_mission", "sdk_auto",
                "sdk_start", "sdk_stop", "stream", "stream_start", "stream_stop",
                "teleop", "turn"],
    "declaration_scope": "actions_only",
    "undeclared_items": ["version", "input_schema", "output_schema", "basis",
                         "execution_conditions", "cancellable", "idempotent",
                         "invocation", "scope", "performance"],
}

#: 실기기의 텔레메트리 봉투. **로봇과 그것을 싣고 있는 노드를 한 자리에 담는다.**
GO1_STATE = {
    "schema_version": "1.1", "source_id": "go1-001", "node_id": "pi7",
    "zone_id": "zoneA", "channel": "state", "battery_pct": 50.0,
}


def _source(**kw):
    transport = FakeTransport()
    sink = Sink()
    src = DeviceTelemetrySource(transport=transport, sink=sink, **kw)
    src.start()
    return src, transport, sink


# ── 공지 ────────────────────────────────────────────────────────────────────

def test_a_capability_announcement_reaches_discovery():
    src, tr, sink = _source(serializer=FakeSerializer(GO1_BODY))

    tr.deliver("terminal/go1-001/uplink", b"<protobuf>")

    assert sink.calls and sink.calls[0][0] == "go1-001"
    assert len(sink.calls[0][1]) == 17
    assert src.observations["go1-001"].actions[0] == "abort"


def test_the_items_the_wire_could_not_carry_are_kept(src_body=GO1_BODY):
    """**비어 있던 항목을 그대로 들고 간다**(AI-C-18 의 세 값).

    와이어가 싣지 못하는 것과 장치가 "없다" 고 말한 것은 다른 사실이다. 실기기
    공지는 action 이름만 싣고 나머지 열 항목은 비어 있다 — 그 사실이 산출에 남아야
    `cancel_supported` 를 `False` 로 접는 옛 결함이 돌아오지 않는다.
    """
    src, tr, _ = _source(serializer=FakeSerializer(src_body))

    tr.deliver("terminal/go1-001/uplink", b"<protobuf>")

    assert "cancellable" in src.observations["go1-001"].undeclared_items
    assert len(src.observations["go1-001"].undeclared_items) == 10


def test_an_undecodable_uplink_is_counted_not_swallowed():
    """조용히 버리면 와이어가 바뀐 것을 아무도 모른다."""
    src, tr, sink = _source(serializer=FakeSerializer(fail=True))

    tr.deliver("terminal/go1-001/uplink", b"<garbage>")

    assert src.dropped == {REASON_UNDECODABLE: 1}
    assert sink.calls == []


def test_without_a_serializer_the_announcement_is_counted_and_nothing_invented():
    """해독기가 없는 배치에서도 돌되 action 을 지어내지 않는다(AI-C-05)."""
    src, tr, sink = _source()

    tr.deliver("terminal/go1-001/uplink", b"<protobuf>")

    assert src.dropped == {REASON_UNDECODABLE: 1}
    assert sink.calls == []


# ── 신선도, 그리고 로봇과 온디바이스를 분리하지 않는 것 ─────────────────────

def test_hearing_the_robot_also_counts_as_hearing_the_node_it_rides_on():
    """**둘을 분리해 관리하지 않는다**(사용자 결정 2026-11-05).

    와이어가 로봇과 그것을 싣고 있는 온디바이스를 한 봉투에 담는다
    (`source_id: go1-001` · `node_id: pi7`). 로봇 소리만 기록하면 pi7 은 영원히
    offline 인데, 그 메시지가 **pi7 을 통해 왔다**는 것이 pi7 이 살아 있다는
    관측이다 — 선언보다 강한 근거다.
    """
    src, tr, sink = _source()

    tr.deliver("zoneA/robot/go1-001/state", json.dumps(GO1_STATE).encode())

    assert set(src.observations) == {"go1-001", "pi7"}
    assert src.observations["pi7"].last_heard is not None
    assert "relayed" in src.observations["pi7"].channels
    assert {c[0] for c in sink.calls} == {"go1-001", "pi7"}


def test_the_robots_actions_are_not_pinned_on_the_node_it_rides_on():
    """**이것이 위 시험의 짝이다.** pi7 에 로봇 action 을 붙이면 "pi7 이 걸을 수
    있다" 가 되고, 그것은 관측이 아니라 거짓이다."""
    src, tr, sink = _source(serializer=FakeSerializer(GO1_BODY))

    tr.deliver("terminal/go1-001/uplink", b"<protobuf>")
    tr.deliver("zoneA/robot/go1-001/state", json.dumps(GO1_STATE).encode())

    assert src.observations["pi7"].actions == ()
    for device_id, actions in sink.calls:
        if device_id == "pi7":
            assert actions == ()


def test_telemetry_does_not_overwrite_the_announced_actions():
    """텔레메트리는 "무엇을 할 수 있다" 를 말하지 않는다. 빈 목록으로 덮으면 공지를
    받은 장치가 아무것도 못 하는 장치가 된다."""
    src, tr, sink = _source(serializer=FakeSerializer(GO1_BODY))

    tr.deliver("terminal/go1-001/uplink", b"<protobuf>")
    tr.deliver("zoneA/robot/go1-001/heartbeat",
               json.dumps({**GO1_STATE, "channel": "heartbeat"}).encode())

    assert len(src.observations["go1-001"].actions) == 17
    assert sink.calls[-1] == ("go1-001", tuple(GO1_BODY["actions"]))


def test_an_envelope_without_a_source_id_is_counted():
    """실기기에 실제로 그런 봉투가 있었다(`terminal/go1-sim/sim/state` — 시뮬레이터
    흔적). 조용히 무시하지 않고 센다."""
    src, tr, sink = _source()

    tr.deliver("zoneA/robot/x/state", json.dumps({"channel": "state"}).encode())

    assert src.dropped == {REASON_NO_DEVICE_ID: 1}
    assert sink.calls == []


def test_a_non_json_telemetry_payload_is_counted():
    src, tr, _ = _source()

    tr.deliver("zoneA/robot/go1-001/state", b"\x00\x01not json")

    assert src.dropped == {REASON_UNDECODABLE: 1}


# ── 경계 ────────────────────────────────────────────────────────────────────

def test_the_source_subscribes_and_never_publishes():
    """**발행 경로가 없다.** 물리 명령 발급은 AI 소유가 아니다(AI-C-19)."""
    src, tr, _ = _source()

    assert UPLINK_TOPIC in tr.handlers
    for topic in TELEMETRY_TOPICS:
        assert topic in tr.handlers
    # 가짜 전송에 publish 가 없는데도 돌았다 = 발행을 부르지 않는다.
    assert not hasattr(tr, "publish")


def test_it_does_not_decide_final_availability():
    """원칙 #15 — 여기서 내는 것은 "언제 들었나" 이고 online/offline 이 아니다."""
    src, tr, _ = _source()

    tr.deliver("zoneA/robot/go1-001/state", json.dumps(GO1_STATE).encode())
    obs = src.observations["go1-001"]

    assert not hasattr(obs, "availability")
    assert not hasattr(obs, "online")
    assert obs.last_heard is not None


def test_an_empty_source_says_so_with_a_reason():
    """빈 상태도 사유로 말한다 — 침묵은 "아무 일 없음" 과 구분되지 않는다."""
    src, _, _ = _source()

    assert "아직 아무것도" in src.note_for_screen()

    src.dropped["x"] = 3
    assert "해독하지 못함" in src.note_for_screen()


def test_the_payload_values_are_not_reinterpreted():
    """배터리·자세의 주인은 그것을 내는 쪽이다. 여기서 다시 읽으면 주인이 둘이 된다."""
    src, tr, _ = _source()

    tr.deliver("zoneA/robot/go1-001/state", json.dumps(GO1_STATE).encode())
    obs = src.observations["go1-001"]

    for banned in ("battery", "battery_pct", "pose", "speed"):
        assert not hasattr(obs, banned)


# ── 장치가 말한 주기 (2026-11-05 실기기) ────────────────────────────────────

def test_a_device_that_states_its_own_interval_is_believed():
    """**고정 임계 하나가 두 장치를 정반대로 틀리게 한다.**

    실측: go1-001 은 5 초마다, wl-001 은 60 초마다 보고한다. 60 초 고정이면 움직이는
    로봇이 죽고도 1 분 동안 online 이고(보고 12 회 놓침), 수위계는 멀쩡한데 늘 stale
    경계에 선다. 장치가 자기 주기를 말하므로 그것을 읽는다 — 우리가 고르지 않는다.
    """
    src, tr, _ = _source()

    tr.deliver("zoneA/robot/go1-001/status", json.dumps(
        {**GO1_STATE, "channel": "status", "state_interval_s": 5.0}).encode())
    tr.deliver("zoneA/sensor/wl-001/status", json.dumps(
        {"source_id": "wl-001", "node_id": "pi7", "zone_id": "zoneA",
         "channel": "status", "report_interval_s": 60.0}).encode())

    assert src.declared_interval_s("go1-001") == 5.0
    assert src.declared_interval_s("wl-001") == 60.0


def test_a_relay_node_takes_the_shortest_interval_it_carries():
    """중계 노드는 자기 주기를 말하지 않는다. 그 소리가 지나오는 동안 중계도 살아
    있으므로, **가장 자주 오는 것**이 중계의 신선도를 정한다."""
    src, tr, _ = _source()

    tr.deliver("zoneA/robot/go1-001/status", json.dumps(
        {**GO1_STATE, "channel": "status", "state_interval_s": 5.0}).encode())
    tr.deliver("zoneA/sensor/wl-001/status", json.dumps(
        {"source_id": "wl-001", "node_id": "pi7", "zone_id": "zoneA",
         "channel": "status", "report_interval_s": 60.0}).encode())

    assert src.declared_interval_s("pi7") == 5.0


def test_an_unstated_interval_is_none_not_a_guess():
    """**모르는 것은 `None` 이고 기본값이 아니다.** 대체값을 쓸지는 소비자가 정하고,
    그때 그 사실이 산출에 남는다(`stale_threshold_basis`)."""
    src, tr, _ = _source()

    tr.deliver("zoneA/robot/go1-001/state", json.dumps(GO1_STATE).encode())

    assert src.declared_interval_s("go1-001") is None
    assert src.declared_interval_s("아무도-모르는-장치") is None


def test_a_zero_or_negative_interval_is_refused():
    """0 초 주기는 선언이 아니라 오류다 — 받으면 임계가 바닥으로 내려간다."""
    src, tr, _ = _source()

    tr.deliver("zoneA/robot/go1-001/status", json.dumps(
        {**GO1_STATE, "channel": "status", "state_interval_s": 0}).encode())

    assert src.declared_interval_s("go1-001") is None
