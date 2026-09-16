"""저장 레코드의 시각 3종과 파생 값 — **인프라 없이 도는** 단위 확인.

Kafka·저장소 없이 돈다. 실제 적재(TSDB에 들어가고 ts 순으로 조회되는가)는
`tests/test_pipeline.py`가 서버에서 확인한다 — 여기서는 **레코드가 값을 어떻게 계산하는지**만
본다. 계산이 틀리면 그 위의 모든 조회가 조용히 틀린다.

지키는 경계:

- `lag_s`는 **`ingest_at` 기준**이다. `received_at`(소비 시각)으로 재면 재기동할 때마다
  같은 메시지의 지연이 달라진다.
- 음수 `lag_s`는 **버리지 않고** `clock_skew` 플래그를 세운다.
- 헤더가 없는 옛 메시지는 **NULL로 조용히 지나간다** — 소비자가 죽으면 안 된다.

implements: BE-S-01, BE-S-07
tests: lag_s 계산, clock_skew 보존, 헤더 없는 옛 메시지, replayed, 스트림 좌표
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest

from backend import settings
from backend.storage.writer import TelemetryRecord, parse_iso


def _message(timestamp: str, **extra: Any) -> Dict[str, Any]:
    message = {
        "schema_version": "1.1",
        "source_id": "wl-001",
        "node_id": "pi7",
        "zone_id": "zoneA",
        "timestamp": timestamp,
        "channel": "state",
    }
    message.update(extra)
    return message


def _record(ts: str, ingest_at: str | None, **kwargs: Any) -> TelemetryRecord:
    return TelemetryRecord(
        channel="state",
        topic="mk2.telemetry.state",
        message=_message(ts, **kwargs.pop("body", {})),
        key="wl-001",
        ingest_at=ingest_at,
        entity_type=kwargs.pop("entity_type", "sensor"),
        stream_partition=kwargs.pop("stream_partition", 0),
        stream_offset=kwargs.pop("stream_offset", 42),
    )


# ── 백엔드가 찍는 시각의 형태 ──────────────────────────────────────────────


def test_utc_now_iso_shape() -> None:
    """`ingest_at`·`received_at`이 **같은 형태**(UTC·마이크로초)여야 그대로 뺄 수 있다."""
    value = settings.utc_now_iso()
    moment = datetime.fromisoformat(value)
    assert moment.tzinfo is not None and moment.utcoffset() == timedelta(0), "UTC여야 한다"
    assert moment.microsecond or "." in value, "마이크로초 자리가 있어야 한다"

    record = TelemetryRecord(channel="state", topic="mk2.telemetry.state", message={})
    assert datetime.fromisoformat(record.received_at).utcoffset() == timedelta(0)


def test_parse_iso_rejects_naive() -> None:
    """오프셋 없는 시각은 `None` — 로컬로 가정하면 조용히 틀린 lag가 나온다."""
    assert parse_iso("2026-09-10T09:00:00+09:00") is not None
    assert parse_iso("2026-09-10T09:00:00") is None, "오프셋이 없으면 단정하지 않는다"
    assert parse_iso("") is None
    assert parse_iso(None) is None
    assert parse_iso("말이 안 되는 값") is None


# ── lag_s — 지연의 측정 재료(BE-S-07) ──────────────────────────────────────


def test_lag_s_uses_ingest_at_not_received_at() -> None:
    """`lag_s`는 `ingest_at - ts`다.

    `received_at`(소비 시각)으로 재면 재기동·오프셋 리셋마다 같은 메시지의 지연이 달라진다.
    """
    record = _record(
        ts="2026-09-10T09:00:00+09:00",
        ingest_at="2026-09-10T00:00:02.500000+00:00",  # 09:00:02.5 KST = ts + 2.5초
    )
    assert record.lag_s == pytest.approx(2.5)
    assert record.clock_skew is False


def test_lag_s_across_offsets() -> None:
    """서로 다른 오프셋 표기여도 같은 순간이면 지연이 0이다(시각은 순간이지 표기가 아니다)."""
    record = _record(
        ts="2026-09-10T09:00:00+09:00",
        ingest_at="2026-09-10T00:00:00.000000+00:00",
    )
    assert record.lag_s == pytest.approx(0.0)


def test_late_arrival_has_large_positive_lag() -> None:
    """지연 도착(두절 후 재전송)은 큰 양수 `lag_s`로 나타난다."""
    record = _record(
        ts="2026-09-10T09:00:00+09:00",
        ingest_at="2026-09-10T00:07:00.000000+00:00",  # 7분 뒤 도착
        body={"replayed": True},
    )
    assert record.lag_s == pytest.approx(420.0)
    assert record.replayed is True
    assert record.clock_skew is False


# ── clock_skew — 버리지 않고 플래그만 세운다 ───────────────────────────────


def test_clock_skew_kept_not_dropped() -> None:
    """말단 시계가 앞선 경우(음수 lag)도 **그대로 남는다**.

    버리면 재난 데이터가 사라지고, 조용히 보정하면 저장된 것이 원본이 아니게 된다.
    """
    record = _record(
        ts="2026-09-10T09:00:30+09:00",
        ingest_at="2026-09-10T00:00:00.000000+00:00",  # ts 보다 30초 이르다
    )
    assert record.lag_s == pytest.approx(-30.0)
    assert record.clock_skew is True

    dumped = record.as_dict()
    assert dumped["clock_skew"] is True
    assert dumped["lag_s"] == pytest.approx(-30.0)
    assert dumped["message"]["timestamp"] == "2026-09-10T09:00:30+09:00", "원본이 보정되면 안 된다"


# ── 헤더 없는 옛 메시지 — NULL로 조용히 지나간다 ───────────────────────────


def test_old_message_without_headers_does_not_crash() -> None:
    """Phase 1에 쌓인 헤더 없는 메시지를 소비해도 **예외 없이 NULL**로 지나간다.

    오프셋을 리셋하거나 새 컨슈머 그룹으로 읽으면 실제로 이런 메시지가 온다.
    """
    record = TelemetryRecord(
        channel="state",
        topic="mk2.telemetry.state",
        message=_message("2026-09-10T09:00:00+09:00"),
        key="wl-001",
        # ingest_at·entity_type 없음, 스트림 좌표도 없음 — 옛 경로 그대로
    )
    assert record.ingest_at is None
    assert record.entity_type is None
    assert record.lag_s is None
    assert record.clock_skew is False   # 모르는 것을 True 로 단정하지 않는다
    assert record.replayed is False
    assert record.as_dict()["lag_s"] is None


# ── 스트림 좌표 — 유일 키의 재료 ───────────────────────────────────────────


def test_stream_coordinates() -> None:
    """토픽·파티션·오프셋이 그대로 실려 나온다. `stream_topic`은 `topic`의 별칭이다."""
    record = _record(
        ts="2026-09-10T09:00:00+09:00",
        ingest_at="2026-09-10T00:00:01.000000+00:00",
        stream_partition=0,
        stream_offset=1234,
    )
    assert record.stream_topic == "mk2.telemetry.state" == record.topic
    assert (record.stream_partition, record.stream_offset) == (0, 1234)

    dumped = record.as_dict()
    assert dumped["stream_partition"] == 0 and dumped["stream_offset"] == 1234
    assert dumped["entity_type"] == "sensor"


def test_replayed_reads_body_flag_only() -> None:
    """`replayed`는 본문 표식을 그대로 읽을 뿐, 지연으로 추론하지 않는다.

    큰 `lag_s`가 곧 재전송은 아니다 — 브릿지·Kafka 적체로도 지연은 생긴다. 반대로 재전송인데
    표식이 없을 수도 있다(`status`·`heartbeat`는 spool을 타지 않는다). 둘은 다른 신호다.
    """
    late_without_flag = _record(
        ts="2026-09-10T09:00:00+09:00",
        ingest_at="2026-09-10T00:10:00.000000+00:00",
    )
    assert late_without_flag.lag_s == pytest.approx(600.0)
    assert late_without_flag.replayed is False, "지연이 크다고 재전송으로 단정하지 않는다"
