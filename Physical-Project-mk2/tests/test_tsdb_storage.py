"""계측 저장(TimescaleDB) 회귀 — TSDB 필요(없으면 **이 파일만 skip**).

단계 6까지의 검증은 사람이 손으로 돌린 일회성 스크립트였다. 이 파일은 그것을 **다시 돌릴 수
있는 회귀**로 굳힌다. 저장 제품을 직접 부르지 않고 **목적 인터페이스 `TelemetryWriter.write()`
를 통해** 넣는다 — 테스트가 psycopg 로 직접 INSERT 하면 "저장 경로가 도는가"가 아니라
"DB 가 도는가"만 확인하게 된다(읽기만 조회로 확인한다).

이 파일이 지키는 경계:

| 완료 판정 | 무엇 |
|---|---|
| 6 ★음성 | `mk2_app` 으로 DDL·UPDATE·DELETE 가 **거부**된다 — 계측 원본을 덮어쓸 경로가 없다 |
| 7 | 발행값이 `telemetry` 에 도달하고 **`ts`(발행 시각) 순으로** 조회된다 |
| 8 | **지연 도착이 원래 측정 시각 자리에 꽂힌다** — 도착 순서와 정렬 순서가 다르다 |
| 9 | `replayed=true` 가 보관되고 `lag_s` 가 계산된다 |
| 10 | 음수 `lag_s` 가 **버려지지 않고** `clock_skew=true` 로 저장된다 |
| 11 | 같은 스트림 좌표를 두 번 써도 **행이 하나**다 |
| 12 | 세션 타임존을 바꿔도 **같은 순간**을 가리킨다 |

⚠ **테스트 행이 `telemetry` 에 남는다.** `mk2_app` 에는 DELETE 권한이 없기 때문이며 그것이
의도다(계측 원본을 지울 경로를 만들지 않는다 — 완료 판정 6이 그것을 확인한다). 행은
`st-<난수>` 로 표시되므로 관리자 계정으로 언제든 지울 수 있다:

    docker exec capstone_timescaledb psql -U postgres -d mk2 \\
        -c "DELETE FROM telemetry WHERE source_id LIKE 'st-%';"

implements: BE-S-01 (시계열 저장), BE-S-07 (lag_s 보관)
tests: 적재·시각 순 조회, 지연 도착 정렬, replayed·lag, clock_skew 보존, 재소비 중복 흡수,
       세션 타임존 불변, 권한 음성 대조
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from backend.storage.writer import TelemetryRecord

# 실제 파이프라인 데이터와 섞이지 않도록 과거의 고정 시각을 쓴다(갭 검출 테스트와 같은 방침).
BASE_TS = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def source_id(tsdb_conn) -> str:
    """이번 테스트만의 `source_id`. 스트림 좌표를 테스트끼리 갈라 주는 근거다."""
    return "st-{}".format(uuid.uuid4().hex[:8])


@pytest.fixture
def tsdb_writer(tsdb_conn):
    """운영 경로 그대로의 계측 writer.

    `tsdb_conn` 에 의존하는 이유는 **skip 을 한 곳에서만 판정**하기 위해서다 — 접속 정보나
    서버가 없으면 fixture 가 먼저 skip 하므로 여기서 다시 판정하지 않는다.
    """
    from backend.storage.tsdb_writer import TimescaleTelemetryWriter

    writer = TimescaleTelemetryWriter()
    yield writer
    writer.close()


def _record(
    source_id: str,
    *,
    offset: int,
    ts_shift: float = 0.0,
    lag_s: float = 0.5,
    channel: str = "state",
    entity_type: str = "sensor",
    sequence_id: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> TelemetryRecord:
    """저장 소비자가 만드는 것과 같은 모양의 레코드.

    `ts_shift` 는 발행 시각을 기준에서 얼마나 옮길지, `lag_s` 는 그 메시지가 서버에 몇 초 뒤에
    닿았는지다. **`ingest_at = ts + lag_s`** 로 두면 저장 층이 계산하는 `lag_s` 가 그대로
    이 값이어야 한다(음수면 말단 시계가 앞선 것이다).
    """
    ts = BASE_TS + timedelta(seconds=ts_shift)
    ingest_at = ts + timedelta(seconds=lag_s)
    message: Dict[str, Any] = {
        "schema_version": "1.1",
        "source_id": source_id,
        "node_id": "pi-test",
        "zone_id": "zoneA",
        "timestamp": ts.isoformat(),
        "channel": channel,
        "reason": "periodic",
        "device_status": "ok",
    }
    if sequence_id is not None:
        message["sequence_id"] = sequence_id
    message.update(extra or {})

    return TelemetryRecord(
        channel=channel,
        # ⚠ 스트림 좌표(ts, stream_topic, partition, offset)가 유일 키다. 토픽 이름에
        #   source_id 를 넣어 테스트끼리 좌표를 가른다. 안 그러면 두 번째 테스트의 행이
        #   ON CONFLICT DO NOTHING 에 조용히 흡수돼 "데이터가 없어서 통과"하는 가짜 성공이 난다.
        topic="mk2.test.{}".format(source_id),
        message=message,
        key=source_id,
        ingest_at=ingest_at.isoformat(),
        entity_type=entity_type,
        stream_partition=0,
        stream_offset=offset,
    )


def _rows(conn, source_id: str, order_by: str = "ts") -> List[Dict[str, Any]]:
    cur = conn.execute(
        "SELECT ts, channel, entity_type, source_id, node_id, zone_id, sequence_id,"
        "       schema_version, ingest_at, received_at, lag_s, clock_skew, replayed,"
        "       reason, device_status, stream_topic, stream_partition, stream_offset, payload"
        "  FROM telemetry WHERE source_id = %s ORDER BY " + order_by,
        (source_id,),
    )
    columns = [d.name for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


# ── 7. 적재와 시각 순 조회 ──────────────────────────────────────────────────


def test_tsdb_write_and_order(tsdb_conn, tsdb_writer, source_id) -> None:
    """`TelemetryWriter.write()` 로 넣은 값이 `telemetry` 에 들어가고 `ts` 순으로 나온다.

    호출부는 저장 제품을 모른다 — 이 테스트가 부르는 것도 목적 인터페이스 하나뿐이다.
    """
    for index, shift in enumerate([0, 2, 1]):          # 발행 순서와 시각 순서를 일부러 어긋나게
        tsdb_writer.write(_record(source_id, offset=index, ts_shift=shift, sequence_id=index + 1))

    rows = _rows(tsdb_conn, source_id)

    assert len(rows) == 3, f"세 건이 전부 적재돼야 한다: {rows}"
    assert [r["ts"] for r in rows] == sorted(r["ts"] for r in rows), "ts 오름차순으로 나와야 한다"
    assert [r["sequence_id"] for r in rows] == [1, 3, 2], "정렬 기준은 도착이 아니라 발행 시각이다"
    # 칼럼은 추출이고 원본은 payload 에 통째로 있다.
    assert rows[0]["payload"]["source_id"] == source_id
    assert rows[0]["entity_type"] == "sensor" and rows[0]["channel"] == "state"


# ── 8. 지연 도착이 원래 측정 시각 자리에 꽂힌다 (plan Phase 2 DoD 핵심) ────────


def test_late_arrival_ordered_by_timestamp(tsdb_conn, tsdb_writer, source_id) -> None:
    """**도착 순서와 저장 정렬 순서가 다르다.**

    시간축이 `received_at` 이었다면 원천적으로 불가능한 일이다. 7분 전에 측정돼 지금 도착한
    데이터는 7분 전 자리에 꽂혀야 하고, 그래야 되감기와 구간 조회가 성립한다.
    """
    arrivals = [
        # (도착 순서, 발행 시각 이동, 순번)
        (0, 300.0, 1),      # 기준
        (1, 0.0, 2),        # ★ 5분 **전**에 측정된 것이 두 번째로 도착했다
        (2, 600.0, 3),      # 5분 뒤 시각
    ]
    for offset, shift, seq in arrivals:
        tsdb_writer.write(_record(source_id, offset=offset, ts_shift=shift, sequence_id=seq))

    by_ts = [r["sequence_id"] for r in _rows(tsdb_conn, source_id, order_by="ts")]
    by_arrival = [r["sequence_id"] for r in _rows(tsdb_conn, source_id, order_by="stream_offset")]

    assert by_arrival == [1, 2, 3], "도착 순서는 오프셋 순이다"
    assert by_ts == [2, 1, 3], "정렬은 발행 시각 순이어야 한다 — 지연 도착이 과거 자리에 꽂힌다"
    assert by_ts != by_arrival, "둘이 같으면 이 테스트는 아무것도 확인하지 못한다"


# ── 9. replayed 보관과 lag_s 계산 ────────────────────────────────────────────


def test_replayed_and_lag(tsdb_conn, tsdb_writer, source_id) -> None:
    """`replayed` 는 본문 표식 그대로 보관하고, `lag_s` 는 `ingest_at - ts` 로 계산한다.

    `replayed` 를 지연 판정의 **유일한 근거로 쓰지 않는다** — `status`·`heartbeat` 는 spool 을
    타지 않아 지연돼도 표식이 없다. 판정은 `lag_s` 로 하고 표식은 보조 증거다.
    """
    tsdb_writer.write(_record(source_id, offset=0, lag_s=7.5, sequence_id=1,
                              extra={"replayed": True}))
    tsdb_writer.write(_record(source_id, offset=1, ts_shift=1, lag_s=0.25, sequence_id=2))

    rows = _rows(tsdb_conn, source_id)

    assert rows[0]["replayed"] is True, "재전송 표식이 보관돼야 한다"
    assert abs(rows[0]["lag_s"] - 7.5) < 0.001, f"lag_s = ingest_at - ts: {rows[0]['lag_s']}"
    # 표식이 없는 쪽은 False 여야 한다 — 전부 True 로 찍히면 위 확인이 무의미하다.
    assert rows[1]["replayed"] is False
    assert abs(rows[1]["lag_s"] - 0.25) < 0.001
    assert rows[0]["clock_skew"] is False and rows[1]["clock_skew"] is False


# ── 10. 음수 lag 는 버리지 않고 플래그만 세운다 ──────────────────────────────


def test_clock_skew_kept_not_dropped(tsdb_conn, tsdb_writer, source_id) -> None:
    """말단 시계가 서버보다 앞선 데이터도 **그대로 저장된다.**

    버리면 재난 데이터가 사라지고, 조용히 보정하면 저장된 것이 원본이 아니게 된다. 그래서
    값은 그대로 두고 플래그만 세운다. (`tests/test_storage_record.py` 에 같은 이름의 단위
    테스트가 있다 — 그쪽은 파생값 계산, 이쪽은 **실제로 저장되는가**를 본다.)
    """
    tsdb_writer.write(_record(source_id, offset=0, lag_s=-30.0, sequence_id=1))
    tsdb_writer.write(_record(source_id, offset=1, ts_shift=1, lag_s=0.5, sequence_id=2))

    rows = _rows(tsdb_conn, source_id)

    assert len(rows) == 2, "★ 음수 lag 행이 버려지면 안 된다 — 여기가 이 테스트의 핵심이다"
    skewed = next(r for r in rows if r["sequence_id"] == 1)
    assert skewed["clock_skew"] is True
    assert skewed["lag_s"] < 0, f"음수 lag 가 그대로 보관돼야 한다: {skewed['lag_s']}"
    assert abs(skewed["lag_s"] + 30.0) < 0.001, "값을 보정하지 않는다"
    normal = next(r for r in rows if r["sequence_id"] == 2)
    assert normal["clock_skew"] is False, "정상 건까지 플래그가 서면 구분이 무의미하다"


# ── 11. 재소비 중복을 스트림 좌표가 흡수한다 ────────────────────────────────


def test_stream_offset_dedup(tsdb_conn, tsdb_writer, source_id) -> None:
    """**같은 Kafka 메시지를 두 번 소비해도 행이 하나다.**

    저장 소비자는 `auto.offset.reset=earliest` + 자동 커밋이라 구조적으로 재소비한다. 업무
    내용 키(`sequence_id`)로는 막을 수 없다 — 로봇은 항상 0, `status` 에는 없고, 증강 분석은
    순번을 대상끼리 공유한다. 재소비는 **도착 계층**의 현상이므로 도착 좌표로 잡는다.
    """
    record = _record(source_id, offset=0, sequence_id=1)
    tsdb_writer.write(record)
    tsdb_writer.write(record)                     # 같은 좌표 — 흡수돼야 한다

    assert len(_rows(tsdb_conn, source_id)) == 1, "같은 스트림 좌표는 한 행이다"

    # 좌표가 다르면 별개 행이어야 한다 — 유일 키가 과하게 막지 않는지 반대편도 확인한다.
    tsdb_writer.write(_record(source_id, offset=1, sequence_id=2))
    rows = _rows(tsdb_conn, source_id, order_by="stream_offset")
    assert len(rows) == 2, "오프셋이 다르면 다른 메시지다 — 이것까지 막으면 데이터가 사라진다"
    assert [r["stream_offset"] for r in rows] == [0, 1]


# ── 12. 세션 타임존을 바꿔도 같은 순간을 가리킨다 ────────────────────────────


def test_utc_storage_session_tz_invariant(tsdb_conn, tsdb_writer, source_id) -> None:
    """`TIMESTAMPTZ` 는 **표현이 달라져도 같은 시각**이다.

    이 서버는 `system_tz=KST` 이고 컨테이너 `TZ` 설정에 따라 실효값이 흔들린다. 그래서 저장
    타입을 `TIMESTAMPTZ` 로 두고 접속마다 세션 타임존을 못 박는다 — 설정이 바뀌어도 과거
    데이터의 해석이 흔들리지 않는다는 것이 이 테스트가 확인하는 것이다.
    """
    tsdb_writer.write(_record(source_id, offset=0, sequence_id=1))

    utc_row = _rows(tsdb_conn, source_id)[0]
    try:
        tsdb_conn.execute("SET TIME ZONE 'Asia/Seoul'")
        kst_row = _rows(tsdb_conn, source_id)[0]
        assert tsdb_conn.execute("SHOW timezone").fetchone()[0] == "Asia/Seoul", (
            "세션 타임존이 실제로 바뀌지 않았으면 이 테스트는 아무것도 확인하지 못한다"
        )
        # 표현(utcoffset)은 달라지고, 가리키는 순간은 같아야 한다.
        assert kst_row["ts"].utcoffset() != utc_row["ts"].utcoffset(), "표현은 달라져야 한다"
        assert kst_row["ts"] == utc_row["ts"], "★ 같은 순간이어야 한다"
        assert kst_row["ingest_at"] == utc_row["ingest_at"]
        assert kst_row["ts"] == BASE_TS, "저장된 값 자체가 발행 시각 그대로다"
    finally:
        # 세션 fixture 를 공유하므로 반드시 되돌린다 — 안 그러면 뒤 테스트가 오염된다.
        tsdb_conn.execute("SET TIME ZONE 'UTC'")


# ── 6. ★음성 — 계측 원본을 덮어쓸 경로가 없다 ───────────────────────────────


def test_ddl_denied(tsdb_conn) -> None:
    """★음성 — `mk2_app` 은 스키마를 바꿀 수 없고 계측을 고치거나 지울 수 없다.

    **코드 규율이 아니라 DB 권한이 지킨다.** 코드로 약속하면 언젠가 누군가 깬다. 삽입이
    `ON CONFLICT DO NOTHING` 이라 UPDATE 권한이 필요 없고, 없는 편이 원본을 덮어쓸 경로 자체를
    없앤다.

    ⚠ `WHERE false` 를 붙인 이유는 **혹시 권한이 잘못 열려 있어도 데이터가 지워지지 않게**
    하기 위해서다. 그 경우 이 테스트는 실패하지만 계측은 살아 있다.
    """
    denied = [
        ("CREATE TABLE", "CREATE TABLE mk2_should_not_exist (id INT)"),
        ("UPDATE telemetry", "UPDATE telemetry SET reason = reason WHERE false"),
        ("DELETE telemetry", "DELETE FROM telemetry WHERE false"),
    ]
    for label, statement in denied:
        with pytest.raises(Exception) as caught:
            tsdb_conn.execute(statement)
        assert "permission denied" in str(caught.value).lower(), (
            f"{label} 가 권한이 아닌 다른 이유로 실패했다: {caught.value}"
        )

    # 거부가 실제로 아무것도 만들지 않았는지 확인한다(오류만 보고 넘어가지 않는다).
    exists = tsdb_conn.execute(
        "SELECT to_regclass('public.mk2_should_not_exist') IS NOT NULL"
    ).fetchone()[0]
    assert exists is False, "거부됐는데 테이블이 생겼다면 위 확인이 무의미하다"

    # 문장 하나가 아니라 **권한 표면 전체**를 본다. 삽입이 `ON CONFLICT DO NOTHING` 이라
    # UPDATE 권한이 필요 없고, 없는 편이 원본을 덮어쓸 경로 자체를 없앤다.
    from backend import settings

    role = settings.tsdb_user()
    # `::name` 캐스팅은 필수다 — 파라미터 타입이 정해지지 않으면 PostgreSQL 이
    # has_table_privilege(name,…)/(oid,…) 중 어느 것인지 고르지 못해 함수 모호성 오류가 난다.
    granted = dict(
        tsdb_conn.execute(
            "SELECT p, has_table_privilege(%s::name, 'telemetry', p)"
            "  FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) AS p",
            (role,),
        ).fetchall()
    )
    assert granted["SELECT"] is True and granted["INSERT"] is True, f"쓰기·읽기는 돼야 한다: {granted}"
    assert granted["UPDATE"] is False and granted["DELETE"] is False, (
        f"계측 원본을 고치거나 지울 권한이 있다: {granted}"
    )
    assert granted["TRUNCATE"] is False, f"계측을 통째로 비울 권한이 있다: {granted}"
    assert tsdb_conn.execute(
        "SELECT has_schema_privilege(%s::name, 'public', 'CREATE')", (role,)
    ).fetchone()[0] is False, "앱 계정이 스키마를 만들 수 있다"
    assert tsdb_conn.execute(
        "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname = %s::name",
        (role,),
    ).fetchone()[0] is False, "앱 계정이 슈퍼유저·생성 권한을 갖고 있다"
