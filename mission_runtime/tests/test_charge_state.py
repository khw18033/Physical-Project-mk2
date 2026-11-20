"""충전 상태는 **관측이다** — 충전소 노드가 없는 배치에서 운영자가 아는 사실.

implements: AI-O-04 (실행 가용성 신호 연계), AI-C-18 (선언 규약의 세 값),
            AI-O-05 (미측정 ≠ 0), AI-C-19 (판정은 우리 몫이 아니다)
tests: 말한 것만 옮긴다 · `null` 은 0% 도 "충전 안 함" 도 아니다 · 범위 밖은 세고
       고치지 않는다 · 배터리 칸 없는 채널이 값을 지우지 않는다 · 화면 계약에 실린다
"""
from __future__ import annotations

import json

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.integration.device_telemetry_source import (
    REASON_CHARGE_OUT_OF_RANGE,
    DeviceTelemetrySource,
)
from mission_runtime.tools.view_service.fleet import Discovery


class FakeTransport:
    """구독만 받는다. 발행 경로가 없는 것이 이 모듈의 경계다."""

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def subscribe(self, topic: str, handler) -> None:
        self.handlers.setdefault(topic, []).append(handler)

    def deliver(self, body: dict) -> None:
        """한 메시지는 **맞는 구독 하나에만** 간다.

        세 핸들러에 모두 넘기면 한 번 온 메시지가 세 번 센 것이 되고, 그러면
        "조용히 버리지 않고 센다" 는 계수기가 거짓이 된다 — 실제 브로커는
        `+/+/+/state` 와 `+/+/+/status` 중 토픽에 맞는 하나에만 보낸다.
        """
        payload = json.dumps(body).encode("utf-8")
        channel = str(body.get("channel") or "state")
        for topic, handlers in self.handlers.items():
            if "uplink" in topic or not topic.endswith(channel):
                continue
            handlers[0](payload)
            return


def source(**over) -> tuple[FakeTransport, DeviceTelemetrySource]:
    transport = FakeTransport()
    made = DeviceTelemetrySource(transport=transport, clock=lambda: 1000.0, **over)
    made.start()
    return transport, made


def telemetry(**over) -> dict:
    body = {"source_id": "go1-001", "node_id": "pi7", "zone_id": "zoneA",
            "channel": "state"}
    body.update(over)
    return body


# --------------------------------------------------------------- 옮긴다

def test_what_the_device_says_is_carried_through_verbatim():
    """**장치는 이미 말하고 있었다** — 듣는 쪽이 없었을 뿐이다(2026-11-05 와 같은 모양).

    `third_party/data_stream/360camera_work/stream_to_server.py` 가 매 보고마다
    싣는 모양 그대로다.
    """
    transport, made = source()
    transport.deliver(telemetry(battery={"level_pct": 61.0, "charging": True}))

    obs = made.observations["go1-001"]
    assert obs.battery_level_pct == 61.0
    assert obs.charging is True
    assert obs.charge_observed_at == 1000.0


def test_the_alternate_field_name_is_read_too_because_we_do_not_pick_names():
    """`check_v2.py` 는 `battery.pct` 를 본다. 이름은 종류마다 다르다(AI-C-18)."""
    transport, made = source()
    transport.deliver(telemetry(battery={"pct": 42.0}))
    assert made.observations["go1-001"].battery_level_pct == 42.0


def test_zero_percent_is_a_measurement_not_a_silence():
    """0% 를 "말하지 않았다" 로 접으면 **다 떨어진 장치가 멀쩡해 보인다.**"""
    transport, made = source()
    transport.deliver(telemetry(battery={"level_pct": 0.0, "charging": False}))

    obs = made.observations["go1-001"]
    assert obs.battery_level_pct == 0.0
    assert obs.charging is False


def test_a_device_that_says_nothing_about_charge_stays_unmeasured():
    """미측정 ≠ 0(AI-O-05). 로봇 상태 채널에는 배터리 칸이 아예 없다."""
    transport, made = source()
    transport.deliver(telemetry())

    obs = made.observations["go1-001"]
    assert obs.battery_level_pct is None and obs.charging is None
    assert obs.charge_observed_at is None
    assert obs.last_heard == 1000.0, "들은 것은 들은 것이다"


def test_a_heartbeat_without_the_battery_block_does_not_erase_the_last_reading():
    """덮으면 **1 초마다 값이 생기고 사라지는 화면**이 된다."""
    transport, made = source()
    transport.deliver(telemetry(battery={"level_pct": 61.0, "charging": True}))
    transport.deliver(telemetry(channel="heartbeat"))

    obs = made.observations["go1-001"]
    assert obs.battery_level_pct == 61.0 and obs.charging is True


def test_a_level_outside_the_range_is_counted_not_quietly_fixed():
    """고치면 **센서 고장이 정상값으로 보인다**(모듈 없으면 1000 이 오는 선례와 같다)."""
    transport, made = source()
    transport.deliver(telemetry(battery={"level_pct": 1000.0}))

    assert made.observations["go1-001"].battery_level_pct is None
    assert made.dropped[REASON_CHARGE_OUT_OF_RANGE] == 1


def test_a_non_numeric_level_is_counted_too():
    transport, made = source()
    transport.deliver(telemetry(battery={"level_pct": "꽉"}))
    assert made.dropped[REASON_CHARGE_OUT_OF_RANGE] == 1


def test_a_charging_flag_alone_is_enough_to_be_an_observation():
    """잔량을 모르면서 충전 중인 것은 **정상**이다 — 둘은 다른 칸이다."""
    transport, made = source()
    transport.deliver(telemetry(battery={"charging": True}))

    obs = made.observations["go1-001"]
    assert obs.charging is True and obs.battery_level_pct is None


def test_no_threshold_and_no_verdict_live_in_this_module():
    """해석의 주인이 둘이 되는 것을 막는 규칙은 그대로다(AI-C-19)."""
    import inspect

    from mission_runtime.integration import device_telemetry_source

    source_text = inspect.getsource(device_telemetry_source)
    for word in ("low_battery", "battery_low", "needs_charge", "critical"):
        assert word not in source_text, f"판정이 들어왔다: {word}"


# --------------------------------------------------------------- 화면으로

def test_the_sink_is_told_so_the_view_can_show_it():
    transport, made = source(sink=Discovery())
    transport.deliver(telemetry(battery={"level_pct": 61.0, "charging": True}))

    reading = made.sink.charge_of("go1-001", now=1003.0)
    assert reading["level_pct"] == 61.0
    assert reading[dd.CHARGING] is True
    assert reading["observed_age_s"] == 3.0


def test_a_sink_that_does_not_know_about_charge_keeps_working():
    """선택 기능의 결손은 정상이다(AI-C-05) — 옛 sink 는 그대로 돈다."""

    class OldSink:
        def __init__(self) -> None:
            self.noted: list[str] = []

        def note(self, device_id, actions, *, at=None) -> None:
            self.noted.append(device_id)

    transport, made = source(sink=OldSink())
    transport.deliver(telemetry(battery={"level_pct": 61.0}))
    assert "go1-001" in made.sink.noted


def test_a_device_never_heard_from_has_no_reading_rather_than_zero():
    """`null` 과 0% 를 같게 적으면 **아직 안 들은 장치가 다 떨어진 것처럼 보인다.**"""
    assert Discovery().charge_of("go1-001") is None


def test_forgetting_a_device_drops_its_charge_reading_too():
    discovery = Discovery()
    discovery.note(device_id="go1-001", actions=("move_to",))
    discovery.note_charge("go1-001", level_pct=61.0, charging=False, at=1000.0)
    discovery.forget("go1-001")
    assert discovery.charge_of("go1-001") is None


def test_the_age_is_a_separate_axis_from_last_seen():
    """장치가 말을 계속 하면서 배터리 칸만 빼고 보낼 수 있다 — 그때 30 분 전 값을
    지금 값처럼 보여 주면 "충전 중" 이라는 말이 거짓이 된다."""
    discovery = Discovery()
    discovery.note_charge("go1-001", level_pct=61.0, charging=True, at=1000.0)
    discovery.note(device_id="go1-001", actions=(), at=2800.0)

    assert discovery.age_s("go1-001", now=2800.0) == 0.0
    assert discovery.charge_of("go1-001", now=2800.0)["observed_age_s"] == 1800.0
