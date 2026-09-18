"""관측 어댑터 라벨 가드 — 인프라·OTel SDK 없이 도는 단위 확인.

**음성 대조가 본체다.** "지표가 나온다"만 보면 나중에 누가 `session_id`를 라벨에 넣어도 아무도
모른다. 가드는 **조용히 버리지 않고 `ValueError`로 막아야** 하고, 그것이 어댑터가 활성이든
no-op 이든 똑같이 나야 한다(코드 결함은 관측 스택 유무와 무관하게 드러나야 한다).

- N1: 금지 라벨(`session_id`·`internal_seq`·`sequence_id`·`timestamp`·`ts`·`frame_id`·
  `capture_timestamp` + Phase 4 확장 8종 `frame_ref`·`correlation_id`·`command_id`·`mission_id`·
  `node_ref`·`client_request_id`·`plan_id`·`event_key`)이 어느 계기에도 못 붙는다.
  `sorted(obs.FORBIDDEN_LABELS)`를 parametrize 하므로 목록이 늘면 수집 수가 저절로 는다(제약 24).
- N1-b(Phase 4): `frame_ref`·`correlation_id`·`command_id` 셋이 **실제로** `ValueError`로 막힌다 —
  VZ 통지가 "막는다"고 적었는데 코드에 없던 것. 그리고 `node_id`(물리 노드)는 **허용**된다(음성의 반대 축).
- N2: A층 계기(`be.ingest.*` 등)에 `source_id`·`zone_id`·`entity_type`이 못 붙는다.
- 양성: 허용 라벨(`component`·`channel`·`outcome`·`stage`)은 통과하고, C층(`be.telemetry.*`)에는
  `source_id`·`zone_id`·`entity_type`·`channel`이 붙는다.
- no-op: `MK2_OTEL_ENDPOINT=""`이면 SDK 없이도 `setup()`·계측 호출이 예외 없이 지나간다(제약 20).

implements: BE-S-02 (라벨 규약 — 결정 4-b)
tests: 금지 라벨 거부(음성) · A층 source_id 거부(음성) · 허용 라벨 통과(양성) · no-op 규율
"""

from __future__ import annotations

import logging

import pytest

from backend import observability as obs


@pytest.fixture(autouse=True)
def _noop_adapter(monkeypatch):
    """SDK·Collector 없이 돌리기 위해 어댑터를 no-op 으로 둔다. 가드는 no-op 에서도 걸려야 한다."""
    monkeypatch.setenv("MK2_OTEL_ENDPOINT", "")
    obs.reset_for_tests()
    obs.setup("be-test")
    assert not obs.enabled(), "엔드포인트가 비었는데 활성이면 no-op 규율이 깨진 것이다"
    yield
    obs.reset_for_tests()


# ── N1: 금지 라벨 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", sorted(obs.FORBIDDEN_LABELS))
def test_forbidden_label_rejected_on_a_layer(bad: str) -> None:
    """금지 라벨 하나하나가 A층 계기에서 `ValueError`로 막힌다 — 조용히 버리지 않는다."""
    with pytest.raises(ValueError) as excinfo:
        obs.count("be.ingest.received", component="ingest", channel="state", **{bad: "x"})
    assert bad in str(excinfo.value)


@pytest.mark.parametrize("bad", ["session_id", "sequence_id", "internal_seq", "timestamp"])
def test_forbidden_label_rejected_on_c_layer(bad: str) -> None:
    """C층은 `source_id`를 허용하지만 금지 라벨은 똑같이 막는다 — 두 층의 기준이 다른 곳은 장치 식별뿐이다."""
    with pytest.raises(ValueError):
        obs.gauge(
            "be.telemetry.water_level_m", 2.53,
            source_id="wl-001", zone_id="zoneA", entity_type="sensor", channel="state", **{bad: "x"},
        )


def test_forbidden_label_rejected_on_every_instrument_kind() -> None:
    """count·updown·gauge·observe 네 진입점 전부 같은 가드를 지난다."""
    with pytest.raises(ValueError):
        obs.count("be.kafka.produce", component="ingest", channel="state", outcome="ok", session_id="s")
    with pytest.raises(ValueError):
        obs.updown("be.gateway.clients", 1, component="gateway", ts="now")
    with pytest.raises(ValueError):
        obs.gauge("be.telemetry.uptime_s", 1.0, source_id="a", zone_id="z", entity_type="sensor", channel="status", frame_id="f")
    with pytest.raises(ValueError):
        obs.observe("be.pipeline.lag", 1.0, component="storage", channel="state", capture_timestamp=1)


# ── N1-b (Phase 4): 통지가 약속한 셋이 실제로 막히고, node_id 는 허용된다 ───────


PHASE4_FORBIDDEN = ("frame_ref", "correlation_id", "command_id",
                    "mission_id", "node_ref", "client_request_id", "plan_id", "event_key")


def test_phase4_labels_are_in_forbidden_set() -> None:
    """VZ 통지·회신에 적힌 8종이 전부 목록에 있고, `node_id`는 없다 — 목록 자체를 못 박는다."""
    assert set(PHASE4_FORBIDDEN) <= obs.FORBIDDEN_LABELS
    assert "node_id" not in obs.FORBIDDEN_LABELS


@pytest.mark.parametrize("bad", ["frame_ref", "correlation_id", "command_id"])
def test_notified_labels_actually_blocked_on_media_instrument(bad: str) -> None:
    """`vz-observability-namespace.md` §2가 "막는다"고 적은 셋 — 미디어 계기(`be.gateway.media_*`)에서 실제로 `ValueError`.

    Phase 3 코드에는 `frame_id`만 있고 `frame_ref`가 없었다(없는 방어를 근거로 쓰지 않는다 — 제약 6).
    """
    with pytest.raises(ValueError) as excinfo:
        obs.count("be.gateway.media_frames", component="gateway", outcome="sent", **{bad: "x"})
    assert bad in str(excinfo.value)


def test_node_id_is_allowed_on_both_layers() -> None:
    """`node_id`는 물리 노드(pi1·pi7)라 저카디널리티 — A층·C층 어디서도 막지 않는다(VZ DAG 노드는 `node_ref`)."""
    assert obs.check_labels("be.telemetry.uptime_s",
                            {"source_id": "wl-001", "zone_id": "zoneA", "entity_type": "sensor",
                             "channel": "status", "node_id": "pi7"})["node_id"] == "pi7"
    assert obs.check_labels("be.ingest.received", {"component": "ingest", "channel": "state", "node_id": "pi7"})["node_id"] == "pi7"


# ── N2: A층에 source_id 금지 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["be.ingest.received", "be.ingest.rejected", "be.kafka.produce", "be.storage.consumed",
     "be.storage.write", "be.registry.observe", "be.gateway.push", "be.gateway.clients", "be.pipeline.lag"],
)
@pytest.mark.parametrize("device_label", sorted(obs.A_LAYER_FORBIDDEN))
def test_a_layer_rejects_device_labels(name: str, device_label: str) -> None:
    """A층 계기 9종 × 장치 식별 라벨 3종 — 전부 `ValueError`. 장치 수만큼 시계열이 곱해지는 것을 막는다."""
    labels = {"component": "x", device_label: "wl-001"}
    with pytest.raises(ValueError) as excinfo:
        obs.check_labels(name, labels)
    assert device_label in str(excinfo.value)
    assert obs.is_a_layer(name)


# ── 양성 ────────────────────────────────────────────────────────────────────


def test_allowed_labels_pass_on_a_layer() -> None:
    """허용 라벨 4종은 통과한다(예외 없음). no-op 이라 값은 어디에도 안 가지만 가드는 지난다."""
    obs.count("be.ingest.received", component="ingest", channel="state")
    obs.count("be.ingest.rejected", component="ingest", channel="state", stage="payload")
    obs.count("be.kafka.produce", component="ingest", channel="status", outcome="ok")
    obs.updown("be.gateway.clients", -1, component="gateway")
    obs.observe("be.pipeline.lag", 433530.068, component="storage", channel="status", outcome="ok")
    assert obs.check_labels("be.storage.write", {"component": "storage", "channel": "state", "outcome": "fail"}) == {
        "component": "storage", "channel": "state", "outcome": "fail",
    }


def test_c_layer_allows_device_labels() -> None:
    """C층은 장치별이어야 의미가 있다 — `source_id`·`zone_id`·`entity_type`·`channel`이 그대로 통과한다."""
    labels = {"source_id": "wl-001", "zone_id": "zoneA", "entity_type": "sensor", "channel": "state"}
    assert obs.check_labels("be.telemetry.water_level_m", dict(labels)) == labels
    assert not obs.is_a_layer("be.telemetry.water_level_m")
    obs.gauge("be.telemetry.water_level_m", 2.53, **labels)   # 예외 없음


def test_none_label_becomes_unknown() -> None:
    """헤더 없는 옛 메시지의 `entity_type=None`은 `unknown`으로 채운다 — 라벨을 비우거나 건너뛰지 않는다(7-3-a)."""
    cleaned = obs.check_labels(
        "be.telemetry.uptime_s", {"source_id": "wl-001", "zone_id": "zoneA", "entity_type": None, "channel": "status"}
    )
    assert cleaned["entity_type"] == "unknown"


# ── no-op 규율 ──────────────────────────────────────────────────────────────


def test_noop_when_endpoint_empty(caplog) -> None:
    """엔드포인트가 비면 계측 전체가 no-op 이다 — 로그 핸들러도 `None`, 호출도 예외 없음, 기동 로그 한 줄."""
    assert obs.log_handler() is None
    obs.count("be.storage.consumed", component="storage", channel="heartbeat")
    obs.gauge("be.telemetry.battery_pct", 87.5, source_id="r1", zone_id="zoneA", entity_type="robot", channel="state")
    obs.shutdown()   # 두 번 불러도 조용하다
    with caplog.at_level(logging.INFO, logger="mk2.observability"):
        obs.setup("be-test")
    assert any("관측 비활성" in rec.getMessage() for rec in caplog.records)


def test_counter_rejects_negative_and_histogram_drops_negative_quietly(caplog) -> None:
    """counter 에 음수는 코드 결함(`ValueError`). 히스토그램 음수는 SDK 가 버리므로 어댑터가 먼저 막고 한 번만 경고한다."""
    with pytest.raises(ValueError):
        obs.count("be.ingest.received", -1, component="ingest", channel="state")
    with caplog.at_level(logging.WARNING, logger="mk2.observability"):
        obs.observe("be.pipeline.lag", -30.0, component="storage", channel="state", outcome="ok")
        obs.observe("be.pipeline.lag", -31.0, component="storage", channel="state", outcome="ok")
    warnings = [r for r in caplog.records if "음수" in r.getMessage()]
    assert len(warnings) == 1, "같은 계기의 음수 경고는 한 번만 남긴다"


def test_lag_buckets_cover_measured_range() -> None:
    """버킷이 실측 범위(-30 ~ 344,000초 → 절대값)를 덮는다 — 기본 버킷(상한 10초)이면 전부 +Inf 에 몰린다."""
    assert obs.LAG_BUCKETS[0] <= 0.1
    assert obs.LAG_BUCKETS[-1] >= 86400
    assert list(obs.LAG_BUCKETS) == sorted(obs.LAG_BUCKETS)
