"""관측 격리 — **관측 저장소가 죽어도 업무 경로가 계속 돈다** (음성 대조 N3의 자동화 부분).

제약 20: 관측이 업무의 전제조건이 아니다. 관측 SDK 미설치·엔드포인트 미설정·저장소 장애 어느
경우에도 백엔드는 계측 없이 계속 돌아야 한다. 여기서는 세 경우를 **이 프로세스 안에서** 재현한다:

1. **엔드포인트가 죽어 있다**(아무도 듣지 않는 포트) — 어댑터는 활성이지만 exporter 는 실패한다.
   그 상태에서 계측 호출이 **빠르고 예외 없이** 지나가고, 계측 저장(`TelemetryWriter.write()`)이
   **그대로 TSDB 에 들어간다.** 종료도 상한 안에 끝난다(exporter 재시도가 종료를 잡지 않는다).
2. **엔드포인트가 비어 있다**(`MK2_OTEL_ENDPOINT=""`) — no-op 으로 같은 저장이 된다.
3. **C층 파생이 죽어도**(sink 예외) 저장은 이미 끝나 있고 소비 루프는 계속 간다(`derive` 가 삼킨다).

컨테이너를 실제로 세우는 확인(`docker compose stop otel-collector` → 발행 → TSDB 행 증가 → `up -d`)은
docker 권한과 compose 경로가 필요해 **사람이 단계 9 블록에서 손으로 한다** — 그 결과가 완료 판정 43 이다.
이 파일은 그것을 대신하지 않고, 코드 경로가 그 결과를 보장하는 구조인지를 회귀로 고정한다.

인프라: TSDB(`tsdb_conn` fixture — 없으면 이 파일의 저장 확인만 skip). OTel SDK 가 없으면 1은 skip 이고
2·3 은 SDK 없이도 돈다(no-op 규율이 곧 그 경우다).

implements: BE-S-02 (관측 격리 — 관측이 업무의 전제조건이 아니다)
tests: 죽은 엔드포인트에서 계측 호출 지연 상한·저장 지속·종료 상한 · 빈 엔드포인트 no-op 저장 · 파생 예외 격리
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest

from backend import observability as obs
from backend.storage import derive
from backend.storage.writer import TelemetryRecord

# 실제 파이프라인 데이터와 섞이지 않게 과거 고정 시각(다른 저장 테스트와 같은 방침).
BASE_TS = datetime(2026, 9, 3, 0, 0, 0, tzinfo=timezone.utc)
DEAD_ENDPOINT = "http://127.0.0.1:4399"     # 아무도 듣지 않는 포트 — "관측 저장소가 죽었다"


def _record(source_id: str, offset: int) -> TelemetryRecord:
    ts = BASE_TS + timedelta(seconds=offset)
    message: Dict[str, Any] = {
        "schema_version": "1.1", "source_id": source_id, "node_id": "pi-test", "zone_id": "zoneA",
        "timestamp": ts.isoformat(), "channel": "state", "reason": "periodic", "device_status": "ok",
        "water_level_m": 2.53, "unit": "m", "alert": False, "mode": "normal",
    }
    return TelemetryRecord(
        channel="state", topic="mk2.test.{}".format(source_id), message=message, key=source_id,
        ingest_at=(ts + timedelta(seconds=0.5)).isoformat(), entity_type="sensor",
        stream_partition=0, stream_offset=offset,
    )


def _count_rows(conn, source_id: str) -> int:
    cur = conn.execute("SELECT count(*) FROM telemetry WHERE source_id = %s", (source_id,))
    return int(cur.fetchone()[0])


@pytest.fixture
def adapter_reset():
    obs.reset_for_tests()
    yield
    obs.reset_for_tests()


# ── 1. 죽은 엔드포인트 — 활성이지만 exporter 가 실패하는 상태 ───────────────


def test_dead_endpoint_does_not_block_or_raise(monkeypatch, adapter_reset) -> None:
    """exporter 가 실패해도 계측 호출은 빠르고(200회 < 2초) 예외가 없고, 종료도 10초 안에 끝난다."""
    pytest.importorskip("opentelemetry.sdk", reason="OTel SDK 미설치 — 죽은 엔드포인트 시험을 건너뛴다")
    monkeypatch.setenv("MK2_OTEL_ENDPOINT", DEAD_ENDPOINT)
    monkeypatch.setenv("MK2_OTEL_EXPORT_INTERVAL", "1")     # exporter 실패를 빨리 겪게 한다
    obs.setup("be-test-isolation")
    assert obs.enabled(), "SDK 가 있고 엔드포인트가 비어 있지 않으면 활성이어야 한다(실패는 export 시점에 난다)"

    started = time.perf_counter()
    for i in range(200):
        obs.count("be.ingest.received", component="ingest", channel="state")
        obs.observe("be.pipeline.lag", float(i), component="storage", channel="state", outcome="ok")
        obs.gauge("be.telemetry.water_level_m", 2.5, source_id="iso", zone_id="zoneA", entity_type="sensor", channel="state")
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, "계측 호출 600회가 {:.2f}초 — exporter 실패가 호출부를 막고 있다".format(elapsed)

    time.sleep(2.5)                                          # export 주기 2번 이상 실패를 겪은 뒤
    started = time.perf_counter()
    obs.shutdown()
    assert time.perf_counter() - started < 10.0, "종료가 exporter 재시도에 잡혀 있다"


def test_storage_continues_with_dead_endpoint(monkeypatch, adapter_reset, tsdb_conn) -> None:
    """★ N3 (프로세스 안) — 관측이 죽은 상태에서 계측 저장이 그대로 TSDB 에 들어간다."""
    pytest.importorskip("opentelemetry.sdk")
    from backend.storage.tsdb_writer import TimescaleTelemetryWriter

    monkeypatch.setenv("MK2_OTEL_ENDPOINT", DEAD_ENDPOINT)
    obs.setup("be-test-isolation")
    assert obs.enabled()

    source_id = "st-iso-{}".format(uuid.uuid4().hex[:8])
    writer = TimescaleTelemetryWriter()
    try:
        for offset in range(3):
            record = _record(source_id, offset)
            writer.write(record)          # 안에서 be.storage.write{outcome=ok} 를 센다 — 죽은 exporter 로
            derive.derive(record)         # C층 파생도 죽은 exporter 로 — 예외 없이 지나가야 한다
    finally:
        writer.close()
    assert _count_rows(tsdb_conn, source_id) == 3, "관측이 죽었는데 저장이 막혔다 — 원칙(관측은 전제조건이 아니다) 위반"


# ── 2. 빈 엔드포인트 — no-op ────────────────────────────────────────────────


def test_storage_continues_with_empty_endpoint(monkeypatch, adapter_reset, tsdb_conn) -> None:
    """`MK2_OTEL_ENDPOINT=""` 이면 계측 전체가 no-op 이고 저장은 똑같이 된다 (완료 판정 44 의 코드 경로)."""
    from backend.storage.tsdb_writer import TimescaleTelemetryWriter

    monkeypatch.setenv("MK2_OTEL_ENDPOINT", "")
    obs.setup("be-test-isolation")
    assert not obs.enabled() and obs.log_handler() is None

    source_id = "st-iso-{}".format(uuid.uuid4().hex[:8])
    writer = TimescaleTelemetryWriter()
    try:
        record = _record(source_id, 0)
        writer.write(record)
        # no-op 에서도 파생은 돈다 — sink(gauge) 가 라벨 가드만 지나고 아무 데도 안 보낼 뿐이다.
        assert derive.derive(record) == 1
    finally:
        writer.close()
    assert _count_rows(tsdb_conn, source_id) == 1


# ── 3. 파생이 죽어도 소비 루프는 간다 ─────────────────────────────────────────


def test_derive_failure_does_not_escape(adapter_reset) -> None:
    def broken(name: str, value: float, **labels: Any) -> None:
        raise RuntimeError("관측 저장소 응답 없음")

    derive._failed_once.clear()
    record = _record("st-iso-derive", 0)
    assert derive.derive(record, sink=broken) == 0     # 예외가 밖으로 안 나온다
    assert derive.derive(record, sink=broken) == 0     # 두 번째도 조용히
