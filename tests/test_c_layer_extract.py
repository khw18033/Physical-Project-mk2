"""C층 대상 파싱과 값 꺼내기 — 인프라·OTel SDK 없이 도는 단위 확인.

**대상 목록은 파이썬에 없다.** `contracts/common/payload/*.schema.json`의 `$comment` 힌트가 기준이고,
이 테스트는 파서가 그 기준을 정확히 읽는지를 **숫자로** 못 박는다(지시서 7-1 검산):
27곳에 힌트가 붙어 있고, 항목 경로로 접으면 gauge 9 · counter 3 · log/event 10 = 22.
`status.buffer` 안의 셋은 중첩이라 최상위만 훑으면 놓친다 — 그것을 잡는 것이 이 테스트의 존재 이유다.

값 꺼내기의 음성 대조(N4): `{"value": null, "state": "unavailable"}`·명시적 `null`·LWT의 `buffer` 부재는
**시계열을 만들지 않는다**(0을 넣으면 "값 없음"이 "0"이 된다).

implements: BE-S-02 (C층 — 대상은 규격에서, 계측은 gauge 9 + counter 3)
tests: 힌트 27/22 검산(중첩 포함) · 계기 이름 12종 · {value,state} 벗기기 · null 미기록(음성) · LWT buffer 부재 ·
       counter 힌트를 gauge 로 내는 것 · entity_type None → unknown · 파생 실패가 예외를 안 낸다
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from backend import contracts
from backend import observability as obs
from backend.storage import derive
from backend.storage.writer import TelemetryRecord

import publisher


# ── 파싱 검산 (지시서 7-1) ──────────────────────────────────────────────────


def test_hint_marker_parsing() -> None:
    """마커 뒤의 첫 낱말이 종류다. 설명이 뒤따라도, 마침표가 붙어도 종류만 뽑는다. 마커가 없으면 None."""
    assert contracts.parse_hint("관측 신호 힌트: gauge. 범위(min/max)를 강제하지 않는다") == "gauge"
    assert contracts.parse_hint("관측 신호 힌트: counter") == "counter"
    assert contracts.parse_hint("관측 신호 힌트: log/event. 관측된 어휘는 …") == "log/event"
    assert contracts.parse_hint("additionalProperties 를 false 로 두지 않는다.") is None
    assert contracts.parse_hint(None) is None
    assert contracts.parse_hint("관측 신호 힌트: 이상한값") is None


def test_hints_total_27_and_folded_9_3_10() -> None:
    """**전수 검산.** 27곳 / gauge 9 · counter 3 · log/event 10 = 22. 이 숫자가 안 나오면 파싱이 틀린 것이다."""
    hints = contracts.observation_hints()
    assert len(hints) == 27, sorted((h.channel, h.entity_type, h.path) for h in hints)

    by_kind = contracts.hint_items_by_kind(hints)
    assert len(by_kind["gauge"]) == 9, by_kind["gauge"]
    assert len(by_kind["counter"]) == 3, by_kind["counter"]
    assert len(by_kind["log/event"]) == 10, by_kind["log/event"]
    assert sum(len(v) for v in by_kind.values()) == 22


def test_hints_per_schema_and_duplicates() -> None:
    """규격별 개수(sensor 4 · robot 5 · actuator 6 · analysis 4 · status 8 · heartbeat 0)와 중복 항목."""
    hints = contracts.observation_hints()
    per_schema = {}
    for h in hints:
        per_schema[(h.channel, h.entity_type)] = per_schema.get((h.channel, h.entity_type), 0) + 1
    assert per_schema == {
        ("state", "sensor"): 4, ("state", "robot"): 5, ("state", "actuator"): 6,
        ("state", "analysis"): 4, ("status", None): 8,
    }
    assert contracts.hints_of_schema("heartbeat", None) == ()
    # 접힌 이유: reason 이 3 규격, device_status 가 4 규격에 나온다 → 27 - 2 - 3 = 22
    assert sum(1 for h in hints if h.path == "reason") == 3
    assert sum(1 for h in hints if h.path == "device_status") == 4


def test_nested_buffer_hints_found() -> None:
    """`status.buffer` 안의 셋(pending gauge · dropped counter · thinned counter)이 중첩 경로로 잡힌다."""
    status = {h.path: h.kind for h in contracts.hints_of_schema("status", None)}
    assert status["buffer.pending"] == "gauge"
    assert status["buffer.dropped"] == "counter"
    assert status["buffer.thinned"] == "counter"
    assert status["publish_failures"] == "counter"
    assert status["uptime_s"] == "gauge"
    assert "buffer" not in status, "buffer 객체 자체에는 힌트가 없다 — 안의 항목만 대상이다"


# ── 계기 이름 12종 (지시서 7-2 표) ──────────────────────────────────────────


EXPECTED_INSTRUMENTS = (
    "be.telemetry.water_level_m",
    "be.telemetry.battery_pct",
    "be.telemetry.speed_mps",
    "be.telemetry.progress",
    "be.telemetry.analysis.value",
    "be.telemetry.analysis.trend_m_per_min",
    "be.telemetry.analysis.eta_to_threshold_min",
    "be.telemetry.uptime_s",
    "be.telemetry.buffer.pending",
    "be.telemetry.buffer.dropped",
    "be.telemetry.buffer.thinned",
    "be.telemetry.publish_failures",
)


def test_metric_instruments_are_the_12_from_the_table() -> None:
    """이번 Phase 계측 대상 = gauge 9 + counter 3 = 12. 이름은 지시서 7-2 표 그대로이고 log/event 는 없다."""
    names = derive.all_metric_instruments()
    assert names == tuple(sorted(EXPECTED_INSTRUMENTS))
    assert len(names) == 12
    assert not any(n.endswith("_total") for n in names), "counter 힌트도 절대값이라 _total 을 붙이지 않는다"
    # C층 이름은 A층 접두사가 아니다 — 어댑터의 A층 가드에 걸리지 않고 source_id 를 받는다.
    assert all(not obs.is_a_layer(n) for n in names)


def test_counter_hint_is_recorded_as_gauge() -> None:
    """counter 힌트 3개는 말단의 절대 누적값이라 gauge 계기로 낸다(무상태 원칙) — `$comment`와 계기 종류가 다르다."""
    import inspect

    targets = dict((path, kind) for path, kind, _ in derive.metric_targets("status", None))
    assert targets["buffer.dropped"] == "counter"      # 규격의 힌트는 counter 지만
    assert inspect.signature(derive.derive).parameters["sink"].default is obs.gauge   # 계기는 gauge 다
    calls = _derive_calls(publisher.make_message("status", "sensor", event="birth"), "status", "sensor")
    assert "be.telemetry.buffer.dropped" in {name for name, _, _ in calls}


# ── 값 꺼내기 ───────────────────────────────────────────────────────────────


def _record(message: Dict[str, Any], channel: str, entity_type: Any) -> TelemetryRecord:
    return TelemetryRecord(
        channel=channel, topic=f"mk2.telemetry.{channel}", message=message,
        entity_type=entity_type, ingest_at="2026-09-16T00:00:00+00:00",
        stream_partition=0, stream_offset=1,
    )


def _derive_calls(message: Dict[str, Any], channel: str, entity_type: Any) -> List[Tuple[str, float, Dict[str, Any]]]:
    """sink 를 바꿔 끼워 어댑터 없이 무엇을 냈는지 잡는다. 라벨 가드는 그대로 지나가게 check_labels 를 부른다."""
    calls: List[Tuple[str, float, Dict[str, Any]]] = []

    def sink(name: str, value: float, **labels: Any) -> None:
        calls.append((name, value, obs.check_labels(name, labels)))

    derive.derive(_record(message, channel, entity_type), sink=sink)
    return calls


def test_sensor_state_emits_water_level_with_c_layer_labels() -> None:
    calls = _derive_calls(publisher.make_message("state", "sensor", source_id="wl-009", water_level_m=2.53), "state", "sensor")
    assert calls == [("be.telemetry.water_level_m", 2.53,
                      {"source_id": "wl-009", "zone_id": "zoneA", "entity_type": "sensor", "channel": "state"})]


def test_unwrap_value_state_form() -> None:
    """`{value, state}` 형태는 벗겨서 값을 쓴다."""
    calls = _derive_calls(
        publisher.make_message("state", "sensor", water_level_m={"value": 1.75, "state": "unavailable"}), "state", "sensor"
    )
    assert calls[0][:2] == ("be.telemetry.water_level_m", 1.75)


@pytest.mark.parametrize("absent", [None, {"value": None, "state": "unavailable"}, {"value": None, "state": "unsupported"}])
def test_absent_value_makes_no_series(absent) -> None:
    """★음성 N4 — `null`·`{value:null,state:…}`는 **기록하지 않는다.** 0 이 들어가면 "값 없음"이 "0"이 된다."""
    calls = _derive_calls(publisher.make_message("state", "sensor", water_level_m=absent), "state", "sensor")
    assert calls == [], calls


def test_explicit_null_in_analysis_is_skipped() -> None:
    """`trend_m_per_min`·`eta_to_threshold_min`의 명시적 null(판단 보류)은 건너뛰고 value 만 낸다."""
    message = publisher.make_message("state", "analysis", source_id="wl-001")
    message["trend_m_per_min"] = None
    message["eta_to_threshold_min"] = None
    calls = _derive_calls(message, "state", "analysis")
    assert [c[0] for c in calls] == ["be.telemetry.analysis.value"]
    assert calls[0][2]["entity_type"] == "analysis"


def test_robot_and_actuator_targets() -> None:
    robot = _derive_calls(publisher.make_message("state", "robot"), "state", "robot")
    assert sorted(c[0] for c in robot) == ["be.telemetry.battery_pct", "be.telemetry.speed_mps"]
    actuator = _derive_calls(publisher.make_message("state", "actuator"), "state", "actuator")
    assert [c[0] for c in actuator] == ["be.telemetry.progress"]
    assert actuator[0][1] == 0.0, "0.0 은 값이다 — null 과 다르다"


def test_status_emits_uptime_buffer_and_failures() -> None:
    calls = _derive_calls(publisher.make_message("status", "sensor", event="birth"), "status", "sensor")
    assert sorted(c[0] for c in calls) == [
        "be.telemetry.buffer.dropped", "be.telemetry.buffer.pending", "be.telemetry.buffer.thinned",
        "be.telemetry.publish_failures", "be.telemetry.uptime_s",
    ]


@pytest.mark.parametrize("etype", ["sensor", "robot", "actuator", "analysis"])
def test_status_names_do_not_depend_on_entity_type(etype: str) -> None:
    """★ `status`는 타입 공통 규격이다 — 증강 분석이 보낸 status 도 `be.telemetry.uptime_s`이지
    `be.telemetry.analysis.uptime_s`가 아니다. 타입은 라벨로 갈린다.

    2026-09-16 서버 실측에서 타입만 보고 접두사를 붙여 잘못된 이름 5종이 생겼던 회귀다.
    """
    calls = _derive_calls(publisher.make_message("status", etype, event="birth"), "status", etype)
    assert sorted(c[0] for c in calls) == [
        "be.telemetry.buffer.dropped", "be.telemetry.buffer.pending", "be.telemetry.buffer.thinned",
        "be.telemetry.publish_failures", "be.telemetry.uptime_s",
    ]
    assert all(c[2]["entity_type"] == etype for c in calls)


def test_runtime_names_across_all_types_and_channels_are_exactly_12() -> None:
    """4 타입 × 3 채널을 실제로 파생시켜 나온 이름의 합집합이 표의 12종과 같다 — 타입에 따라 이름이 새지 않는다."""
    seen = set()
    for etype in ["sensor", "robot", "actuator", "analysis"]:
        for channel, kw in [("state", {}), ("status", {"event": "birth"}), ("heartbeat", {})]:
            for name, _, _ in _derive_calls(publisher.make_message(channel, etype, **kw), channel, etype):
                seen.add(name)
    assert seen == set(EXPECTED_INSTRUMENTS), sorted(seen ^ set(EXPECTED_INSTRUMENTS))


def test_lwt_without_buffer_skips_buffer_items() -> None:
    """LWT(death)는 `buffer`·`uptime_s`·`publish_failures`가 아예 없다 — 셋을 건너뛰고 예외도 없다."""
    calls = _derive_calls(publisher.make_message("status", "sensor", event="death"), "status", "sensor")
    assert calls == []


def test_heartbeat_has_no_c_layer() -> None:
    calls = _derive_calls(publisher.make_message("heartbeat", "sensor"), "heartbeat", "sensor")
    assert calls == []


def test_entity_type_none_becomes_unknown_label() -> None:
    """헤더 없는 옛 메시지(entity_type=None): status 는 타입 공통 규격이라 파생되고 라벨은 unknown 이다(7-3-a)."""
    calls = _derive_calls(publisher.make_message("status", "sensor", event="birth"), "status", None)
    assert calls and all(c[2]["entity_type"] == "unknown" for c in calls)
    # state 는 타입별 규격이라 타입을 모르면 대상을 고를 수 없다 — 파생 없음, 예외 없음.
    assert _derive_calls(publisher.make_message("state", "sensor"), "state", None) == []


def test_bool_and_string_are_not_numbers() -> None:
    """bool 은 int 의 하위 타입이지만 수치가 아니다. 문자열도 안 된다."""
    assert derive.extract_value({"progress": True}, "progress") is None
    assert derive.extract_value({"progress": "0.5"}, "progress") is None
    assert derive.extract_value({"progress": 0}, "progress") == 0.0
    assert derive.extract_value({"buffer": None}, "buffer.pending") is None
    assert derive.extract_value({"buffer": {"pending": 3}}, "buffer.pending") == 3.0


def test_derive_swallows_sink_failure(caplog) -> None:
    """파생 실패가 저장·소비를 막지 않는다 — sink 가 죽어도 예외가 밖으로 안 나가고 한 번만 로그."""
    def broken(name: str, value: float, **labels: Any) -> None:
        raise RuntimeError("exporter down")

    record = _record(publisher.make_message("state", "sensor"), "state", "sensor")
    derive._failed_once.clear()
    assert derive.derive(record, sink=broken) == 0
    assert derive.derive(record, sink=broken) == 0
    assert sum(1 for r in caplog.records if "C층 파생 실패" in r.getMessage()) == 1
