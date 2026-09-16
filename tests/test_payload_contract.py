"""채널 본문 규격 회귀 — **인프라 없이 도는** 단위 확인(2단 검증의 2단).

Kafka·Mosquitto·저장소가 없어도 돈다. 관통(발행 → 격리 파일에 나타나고 토픽에는 안 뜬다)은
`tests/test_pipeline.py`가 파이프라인이 뜬 서버에서 확인한다 — 여기서는 **규격 자체가
무엇을 통과시키고 무엇을 막는지**만 본다.

검증이 무력하지 않은지 보는 것이 목적이므로 양성만 세지 않는다. 이 파일이 지키는 경계:

- 필수 누락은 **막는다**(음성)              — 저장 층이 값의 존재를 가정할 수 있어야 한다
- 모르는 필드는 **통과시킨다**              — HW가 필드를 늘리는 것은 정상 동작이다
- 모르는 개체 타입은 **통과시킨다**          — 새 노드가 첫 메시지부터 막히면 안 된다
- 증강 분석 형식은 **격리되지 않는다**       — 가동 중인 생산자다

implements: BE-C-01
tests: 본문 4종 양성, status birth·LWT 양성, 필수 누락 음성, 모르는 필드 통과,
       모르는 etype 통과, analysis 비격리, normalize_payload 키 채움
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

import publisher
from backend import contracts, settings
from backend.ingest.envelope import PayloadInvalid, validate_envelope, validate_payload
from backend.storage.normalize import normalize_payload


def _example(name: str) -> Dict[str, Any]:
    path: Path = settings.contracts_dir() / "examples" / name
    return json.loads(path.read_text(encoding="utf-8"))


# ── 규격 파일이 실제로 있는가 (타입 어휘는 파일에서 유도된다) ────────────────


def test_payload_schemas_present() -> None:
    """`state` 타입 어휘를 파이썬이 아니라 규격 파일에서 얻는다."""
    assert contracts.known_entity_types() == ("actuator", "analysis", "robot", "sensor")
    for channel in ("status", "heartbeat"):
        assert contracts.payload_schema_path(channel, None) is not None, channel


def test_entity_type_of_mqtt_topic() -> None:
    """`{zone}/{etype}/{eid}/{channel}` 의 2번째 칸이 etype다. 4칸이 아니면 None."""
    assert settings.entity_type_of_mqtt_topic("zoneA/sensor/wl-001/state") == "sensor"
    assert settings.entity_type_of_mqtt_topic("zoneA/analysis/wl-001/state") == "analysis"
    # 명령 경로는 3칸이라 이 규약의 토픽이 아니다 — 구독 대상도 아니다.
    assert settings.entity_type_of_mqtt_topic("terminal/wl-001/downlink") is None


# ── 양성: 본문 4종 + status 2종 + heartbeat ────────────────────────────────


@pytest.mark.parametrize(
    "fixture, entity_type",
    [
        ("payload-state-robot-valid.json", "robot"),
        ("payload-state-sensor-valid.json", "sensor"),
        ("payload-state-actuator-valid.json", "actuator"),
        ("payload-state-analysis-valid.json", "analysis"),
    ],
    ids=["robot", "sensor", "actuator", "analysis"],
)
def test_payload_valid(fixture: str, entity_type: str) -> None:
    """4종 본문이 공통 헤더·본문 2단을 모두 통과한다."""
    message = _example(fixture)
    validate_envelope(message)                       # 1단
    validate_payload("state", entity_type, message)  # 2단


def test_payload_status_birth_and_lwt() -> None:
    """`status`의 birth와 **LWT가 둘 다** 통과한다.

    LWT 본문에는 registration도 buffer도 uptime_s도 없다. 필수를 세게 걸면 **가장 중요한
    급사 신호가 격리된다** — 그래서 필수를 event·status 둘로만 잡았다. 이 테스트가 그
    느슨함이 의도된 것임을 못박는다.
    """
    for fixture in ("payload-status-birth-valid.json", "payload-status-lwt-valid.json"):
        message = _example(fixture)
        validate_envelope(message)
        validate_payload("status", "sensor", message)

    lwt = _example("payload-status-lwt-valid.json")
    assert "registration" not in lwt and "buffer" not in lwt, "LWT fixture가 실물과 달라졌다"
    assert "sequence_id" not in lwt, "status에는 순번이 없다(실물 근거)"


def test_payload_heartbeat_passes_with_envelope_only() -> None:
    """`heartbeat`는 본문이 없다 — 공통 헤더만 통과하면 이 채널은 통과한다."""
    message = dict(_example("envelope-valid.json"))
    for body_field in ("water_level_m", "unit", "alert", "reason"):
        message.pop(body_field, None)
    message["channel"] = "heartbeat"
    validate_envelope(message)
    validate_payload("heartbeat", "sensor", message)


# ── 음성: 필수 누락은 실제로 막힌다 ────────────────────────────────────────


def test_payload_invalid_missing_required() -> None:
    """★음성 — `state/robot`의 필수 `device_status`가 없으면 **거부**된다.

    공통 헤더는 통과하는데 본문에서 걸린다는 점이 중요하다. 1단만 있던 Phase 1에서는
    이 메시지가 그대로 흘러갔다.
    """
    message = _example("payload-state-robot-invalid-missing-device-status.json")
    validate_envelope(message)  # 1단은 통과한다
    with pytest.raises(PayloadInvalid) as excinfo:
        validate_payload("state", "robot", message)
    assert "device_status" in str(excinfo.value)


def test_payload_invalid_wrong_type_rejected() -> None:
    """★음성 — 타입이 어긋나도 막힌다(같은 이름 다른 타입 사고 방지).

    로봇의 `position`은 객체이고 액추에이터의 `position`은 문자열이다. 공통 코어에 넣지
    않고 타입별 확장에만 둔 이유가 이것이며, 서로 바꿔 넣으면 걸려야 한다.
    """
    robot = dict(_example("payload-state-robot-valid.json"))
    robot["position"] = "open"  # 액추에이터 형식을 로봇 본문에 넣는다
    with pytest.raises(PayloadInvalid):
        validate_payload("state", "robot", robot)

    actuator = dict(_example("payload-state-actuator-valid.json"))
    actuator["position"] = {"x": 1.0, "y": 2.0, "heading_deg": 3.0}
    with pytest.raises(PayloadInvalid):
        validate_payload("state", "actuator", actuator)


# ── 느슨함이 의도대로 동작하는가 ───────────────────────────────────────────


def test_payload_unknown_field_passes() -> None:
    """모르는 필드는 **통과한다**(느슨한 2단).

    `additionalProperties: false`로 두면 HW가 필드를 하나 추가하는 순간 전량 격리된다.
    """
    message = _example("payload-state-robot-unknown-field.json")
    assert "experimental_torque_nm" in message
    validate_envelope(message)
    validate_payload("state", "robot", message)


def test_unknown_entity_type_passes() -> None:
    """모르는 개체 타입은 본문 검증을 **건너뛰고 통과**한다.

    새 노드 타입이 첫 메시지부터 격리되면 파이프라인이 그 자리에서 막힌다. 규격이 없으면
    검증기도 없다는 것을 함께 확인한다.
    """
    from backend.ingest.envelope import payload_validator

    message = dict(_example("payload-state-sensor-valid.json"))
    assert payload_validator("state", "thermal-camera") is None
    validate_payload("state", "thermal-camera", message)   # 예외가 나면 안 된다
    validate_payload("state", None, message)               # etype을 못 얻은 경우도 같다


def test_analysis_not_quarantined() -> None:
    """증강 분석 형식이 **격리되지 않는다**(가동 중인 생산자다).

    이 생산자는 다른 노드와 셋이 다르다 — 토픽 마지막 칸은 `state`인데 본문 `channel`은
    `"analysis"`이고, `device_status`도 `reason`도 없다. 공통 코어를 강제하거나 본문
    `channel`을 토픽과 대조하면 전량 격리된다.
    """
    message = _example("payload-state-analysis-valid.json")
    assert message["channel"] == "analysis", "토픽은 state인데 본문은 analysis — 실물의 불일치다"
    assert "device_status" not in message and "reason" not in message

    validate_envelope(message)
    validate_payload("state", "analysis", message)  # 토픽 채널은 state다. 그래도 통과한다


# ── 누락값 표현: 읽기 함수가 키를 채운다 ───────────────────────────────────


def test_normalize_payload_fills_keys() -> None:
    """규격의 항목 목록대로 빠진 키가 **키를 유지한 채** 나온다."""
    message = dict(_example("payload-state-sensor-valid.json"))
    del message["mode"]
    del message["water_level_m"]

    out = normalize_payload("state", "sensor", message)

    # 기본형: 명시적 null
    assert "mode" in out and out["mode"] is None
    # 부재 사유 구분이 필요한 항목: {value, state}
    assert out["water_level_m"] == {"value": None, "state": "unavailable"}
    # 규격에 있으나 원본에 없던 선택 항목도 키가 생긴다
    assert "replayed" in out and out["replayed"] is None
    # 원본은 건드리지 않는다
    assert "mode" not in message


def test_normalize_payload_keeps_existing_values() -> None:
    """이미 있는 값은 덮지 않는다 — 명시적 `null`도 '값이 없다'는 정보다."""
    message = _example("payload-state-actuator-valid.json")
    assert message["lock_reason"] is None

    out = normalize_payload("state", "actuator", message)

    assert out["lock_reason"] is None          # null 이 {value,state} 로 바뀌지 않는다
    assert out["progress"] == message["progress"]
    assert out["actuator_state"] == "moving"


def test_normalize_payload_fills_nested_keys() -> None:
    """항목은 있는데 하위 키가 빠진 경우만 한 단계 더 채운다."""
    message = _example("payload-status-birth-valid.json")
    del message["buffer"]["thinned"]

    out = normalize_payload("status", "sensor", message)

    assert out["buffer"]["thinned"] is None
    assert out["buffer"]["pending"] == 0

    # 항목 자체가 없는 것과 하위 키가 없는 것은 다른 사건이다.
    lwt = normalize_payload("status", "sensor", _example("payload-status-lwt-valid.json"))
    assert lwt["buffer"] is None
    assert lwt["registration"] == {"value": None, "state": "unavailable"}


def test_normalize_payload_unknown_type_untouched() -> None:
    """규격이 없는 조합은 손대지 않는다 — 모르는 모양을 우리가 아는 모양으로 채우지 않는다."""
    message = {"whatever": 1}
    assert normalize_payload("state", "thermal-camera", message) == message


# ── 가짜 발행자가 실물과 같은 모양인가 ─────────────────────────────────────
#
# 검증 재료가 실물과 다르면 그 위의 테스트는 "통과했다"만 말할 뿐 아무것도 보장하지 않는다.
# 여기가 그 재료를 지키는 자리다.


def test_publisher_default_matches_real_node() -> None:
    """기본 발행의 **필드 집합이 실노드와 같다** — `entity_id`·`origin_kind`가 없다.

    실노드 `envelope()`에는 이 둘이 아예 없다. 가짜 발행자가 기본으로 채워 보내면
    "가짜로는 통과하는데 실물에서는 항상 NULL"인 칼럼을 끝까지 못 잡는다.
    """
    message = publisher.make_message(channel="state", etype="sensor")

    assert "entity_id" not in message, "실노드는 entity_id를 보내지 않는다"
    assert "origin_kind" not in message, "실노드는 origin_kind를 보내지 않는다"
    assert set(message) >= {"schema_version", "source_id", "node_id", "zone_id", "timestamp"}

    # 옵션으로 켤 수는 있어야 한다(그 경로도 저장 층이 다뤄야 하므로).
    opted_in = publisher.make_message(entity_id="wl-001", origin_kind="simulation")
    assert opted_in["entity_id"] == "wl-001"
    assert opted_in["origin_kind"] == "simulation"


@pytest.mark.parametrize("etype", ["sensor", "robot", "actuator", "analysis"])
def test_publisher_state_bodies_pass_two_stage(etype: str) -> None:
    """발행자가 만드는 4종 `state` 본문이 2단 검증을 통과한다.

    단계 4가 본문 검증을 켜는 순간 기존 발행자가 깨졌던 자리다 — 그 회귀를 여기서 막는다.
    """
    message = publisher.make_message(channel="state", etype=etype)
    validate_envelope(message)
    validate_payload("state", etype, message)


@pytest.mark.parametrize("event", ["birth", "summary", "shutdown", "death"])
def test_publisher_status_bodies_pass_two_stage(event: str) -> None:
    """`status` 4종(정상 종료·급사 포함)이 통과한다."""
    message = publisher.make_message(channel="status", etype="sensor", event=event)
    validate_envelope(message)
    validate_payload("status", "sensor", message)


def test_publisher_heartbeat_body_is_empty() -> None:
    """`heartbeat`는 본문이 `channel` 하나뿐이다 — 예전처럼 state 본문이 실리면 안 된다."""
    message = publisher.make_message(channel="heartbeat", etype="sensor")
    body_only = set(message) - {
        "schema_version", "source_id", "node_id", "zone_id", "timestamp",
        "sequence_id", "session_id",
    }
    assert body_only == {"channel"}, f"하트비트에 본문이 실렸다: {sorted(body_only)}"
    validate_envelope(message)
    validate_payload("heartbeat", "sensor", message)


def test_publisher_lwt_shape_matches_real_lwt() -> None:
    """`--event death`가 실제 LWT와 같은 모양이다 — registration·buffer가 **없다**."""
    message = publisher.make_message(channel="status", etype="sensor", event="death")
    assert message["status"] == "offline"
    assert message["device_status"] == "fault"
    assert message["reason"] == "lwt"
    assert "registration" not in message and "buffer" not in message
    assert "sequence_id" not in message


def test_publisher_analysis_reproduces_defects() -> None:
    """증강 분석 형식이 **결함까지 그대로** 재현된다.

    결함을 고쳐서 흉내 내면 그 결함을 막는 테스트가 실제로는 아무것도 검증하지 못한다.
    """
    state = publisher.make_message(channel="state", etype="analysis")
    assert state["channel"] == "analysis", "토픽은 state인데 본문은 analysis여야 한다"
    assert "device_status" not in state and "reason" not in state
    assert publisher.topic_for("state", etype="analysis").endswith("/state")

    registration = publisher.make_registration("wl-001", "edge-1", "zoneA", "analysis")
    assert registration["mac"] == "" and registration["ip"] == "", "빈 mac·ip가 재현되어야 한다"


def test_publisher_sequence_defaults_match_reality() -> None:
    """순번 기본값이 실물과 같다 — `status`는 없고, 로봇 `state`는 0에서 멈춘다."""
    assert "sequence_id" not in publisher.make_message(channel="status", etype="sensor")
    assert publisher.make_message(channel="state", etype="robot")["sequence_id"] == 0
    assert publisher.default_sequence_step("state", "robot") == 0
    assert publisher.make_message(channel="state", etype="sensor")["sequence_id"] == 1
    assert publisher.default_sequence_step("state", "sensor") == 1

    # 갭 주입을 위해 명시적으로 올릴 수는 있어야 한다.
    assert publisher.make_message(channel="state", etype="robot", sequence_id=7)["sequence_id"] == 7


def test_publisher_timestamp_offset() -> None:
    """`--timestamp` 상대 초가 과거·미래 시각을 만든다(지연 도착과 음수 lag의 재료)."""
    from datetime import datetime

    now = datetime.now().astimezone()
    past = datetime.fromisoformat(publisher.resolve_timestamp("-420"))
    future = datetime.fromisoformat(publisher.resolve_timestamp("+30"))

    assert (now - past).total_seconds() > 400
    assert (future - now).total_seconds() > 20
    # ISO 문자열은 그대로 쓴다.
    assert publisher.resolve_timestamp("2026-08-31T09:00:00+09:00") == "2026-08-31T09:00:00+09:00"


def test_publisher_session_id_toggle() -> None:
    """`session_id` 경로와 `birth` 폴백 경로를 **둘 다** 돌릴 수 있다."""
    assert publisher.make_message()["session_id"] == publisher.SESSION_ID
    assert "session_id" not in publisher.make_message(session_id=None)
    assert publisher.make_message(session_id="fixed-1")["session_id"] == "fixed-1"


def test_publisher_replayed_only_on_state() -> None:
    """`replayed`는 `state`에만 붙는다 — `status`·`heartbeat`는 spool을 타지 않는다."""
    assert publisher.make_message(channel="state", replayed=True)["replayed"] is True
    assert "replayed" not in publisher.make_message(channel="status", replayed=True)
    assert "replayed" not in publisher.make_message(channel="heartbeat", replayed=True)


def test_publisher_invalid_fixtures_are_actually_invalid() -> None:
    """★음성 — 음성 fixture가 정말로 각 단에서 거부되는지 확인한다.

    fixture가 조용히 유효해지면 격리 테스트가 아무것도 검증하지 못한다.
    """
    from backend.ingest.envelope import EnvelopeInvalid

    for kind in ("missing-zone", "timestamp"):
        with pytest.raises(EnvelopeInvalid):
            validate_envelope(publisher.load_invalid(kind))

    payload_bad = publisher.load_invalid("payload-missing-device-status")
    validate_envelope(payload_bad)  # 1단은 통과한다
    with pytest.raises(PayloadInvalid):
        validate_payload("state", publisher.INVALID_ETYPE["payload-missing-device-status"], payload_bad)
