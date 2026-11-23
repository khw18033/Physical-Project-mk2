"""유실·역전 검출 조회 회귀 — TimescaleDB 필요(없으면 **이 파일만 skip**).

**검출은 저장이 아니라 조회에서 한다.** 적재 시점에 "유실"이라고 못 박으면 7분 뒤 도착해
갭을 메울 데이터와 정면 충돌한다. 그래서 원본만 넣고 갭은 `LAG()` 윈도우 함수로 계산한다.

이 파일이 지키는 경계 — **갭이 곧 유실이 아니다:**

| 무엇 | 기대 |
|---|---|
| 센서 `state` 순번 구멍 | 갭이며 **유실 후보**(QoS 1 + spool) |
| 세션 경계의 순번 리셋 | **갭이 아니다** — 구간이 갈렸을 뿐 |
| `session_id` 없는 혼재 기간 | `status`의 `birth`로 경계를 잡는다(폴백) |
| `status` | **검출 대상에서 빠진다** — 순번이 없다 |
| `heartbeat` 구멍 | 갭이지만 **유실로 단정하지 않는다**(QoS 0 · spool 안 탐 · 로봇은 임무 중 끔) |
| 로봇 `state` 순번 정체 | 갭이 아니라 `seq_stalled` — 생산자 결함이지 유실이 아니다 |

⚠ **테스트 행이 `telemetry` 에 남는다.** `mk2_app` 에는 DELETE 권한이 없기 때문이며, 그것이
의도다(계측 원본을 지울 경로를 만들지 않는다). 행은 `gap-<난수>` 로 표시되므로 관리자 계정
으로 언제든 지울 수 있다:

    docker exec capstone_timescaledb psql -U postgres -d mk2 \\
        -c "DELETE FROM telemetry WHERE source_id LIKE 'gap-%';"

implements: BE-S-01
tests: 갭 검출, 세션 경계, birth 폴백, status 제외(음성), heartbeat 비유실, 로봇 정체
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

BASE_TS = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

def _topic_for(source_id: str) -> str:
    """이 테스트 행들의 스트림 토픽.

    ⚠ 스트림 좌표(ts, stream_topic, stream_partition, stream_offset)가 유일 키다. 테스트마다
    같은 ts·offset 을 쓰므로 **토픽 이름에 source_id 를 넣어** 좌표를 갈라야 한다. 안 그러면
    두 번째 테스트의 행이 `ON CONFLICT DO NOTHING` 에 조용히 흡수돼 "데이터가 없어서 통과"하는
    가짜 성공이 난다. 실제 토픽(`mk2.telemetry.*`)과도 이름이 겹치지 않는다.
    """
    return "mk2.test.{}".format(source_id)

INSERT_ROW = """
INSERT INTO telemetry (
    ts, channel, entity_type, source_id, node_id, zone_id, session_id, sequence_id,
    schema_version, reason, replayed, stream_topic, stream_partition, stream_offset, payload
) VALUES (%(ts)s, %(channel)s, %(entity_type)s, %(source_id)s, %(node_id)s, %(zone_id)s,
          %(session_id)s, %(sequence_id)s, '1.1', %(reason)s, %(replayed)s,
          %(stream_topic)s, 0, %(stream_offset)s, %(payload)s)
ON CONFLICT DO NOTHING
"""


@pytest.fixture
def gap_source(tsdb_conn):
    """이번 테스트만의 `source_id` 접두사와, 그 범위로 좁힌 조회 환경."""
    prefix = "gap-{}".format(uuid.uuid4().hex[:8])
    tsdb_conn.execute("SELECT set_config('mk2.source_filter', %s, false)", (prefix + "%",))
    return prefix


def _insert(conn, source_id: str, channel: str, seq: Optional[int], offset: int, **kw: Any) -> None:
    from psycopg.types.json import Jsonb

    ts = BASE_TS + timedelta(seconds=offset)
    payload: Dict[str, Any] = {
        "schema_version": "1.1",
        "source_id": source_id,
        "node_id": kw.get("node_id", "pi7"),
        "zone_id": "zoneA",
        "timestamp": ts.isoformat(),
        "channel": channel,
    }
    if seq is not None:
        payload["sequence_id"] = seq
    if kw.get("session_id"):
        payload["session_id"] = kw["session_id"]
    payload.update(kw.get("payload_extra") or {})

    conn.execute(
        INSERT_ROW,
        {
            "ts": ts,
            "channel": channel,
            "entity_type": kw.get("entity_type", "sensor"),
            "source_id": source_id,
            "node_id": kw.get("node_id", "pi7"),
            "zone_id": "zoneA",
            "session_id": kw.get("session_id"),
            "sequence_id": seq,
            "reason": kw.get("reason", "periodic"),
            "replayed": kw.get("replayed", False),
            "stream_topic": _topic_for(source_id),
            "stream_offset": offset,
            "payload": Jsonb(payload),
        },
    )


def _rows(conn, statement: str) -> List[Dict[str, Any]]:
    cur = conn.execute(statement)
    columns = [d.name for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _gaps(conn, sql_query) -> List[Dict[str, Any]]:
    return _rows(conn, sql_query("gap-detection.sql", "gap_scan"))


# ── 27. 갭 조회가 갭을 집어낸다 ────────────────────────────────────────────


def test_gap_detection_query(tsdb_conn, sql_query, gap_source) -> None:
    """센서 `state`의 순번 구멍이 **유실 후보**로 잡힌다(QoS 1 + spool을 타는 채널)."""
    source = gap_source + "-sensor"
    session = "s-fixed-1"
    for offset, seq in enumerate([1, 2, 4, 5]):        # 3번이 빠졌다
        _insert(tsdb_conn, source, "state", seq, offset, session_id=session)

    gaps = [g for g in _gaps(tsdb_conn, sql_query)
            if g["source_id"] == source and g["verdict"] == "gap"]

    assert len(gaps) == 1, f"갭이 정확히 1건이어야 한다: {gaps}"
    hole = gaps[0]
    assert (hole["prev_sequence_id"], hole["sequence_id"]) == (2, 4)
    assert hole["missing_count"] == 1
    assert hole["loss_class"] == "loss_candidate", "센서 state의 갭은 유실 후보다"
    assert hole["session_key"] == session


# ── 28. 세션 경계의 순번 리셋은 갭이 아니다 ────────────────────────────────


def test_session_boundary_not_gap(tsdb_conn, sql_query, gap_source) -> None:
    """`session_id`가 바뀌면 **구간이 갈린다** — 순번이 1로 돌아가도 갭이 아니다.

    이것이 `session_id`를 신설한 이유다. 프로세스가 다시 뜨면 순번이 리셋되는데, 경계를
    모르면 그 리셋이 거대한 역전으로 보인다.
    """
    source = gap_source + "-session"
    for offset, seq in enumerate([1, 2, 3]):
        _insert(tsdb_conn, source, "state", seq, offset, session_id="s-before")
    for offset, seq in enumerate([1, 2, 3], start=10):
        _insert(tsdb_conn, source, "state", seq, offset, session_id="s-after")

    mine = [g for g in _gaps(tsdb_conn, sql_query) if g["source_id"] == source]
    problems = [g for g in mine if g["verdict"] in ("gap", "seq_reset_without_boundary")]

    assert problems == [], f"세션 경계가 갭·역전으로 잡히면 안 된다: {problems}"
    # 구간이 둘로 갈렸는지 확인한다(각 구간의 첫 행은 segment_start 로 나온다).
    starts = {g["session_key"] for g in mine if g["verdict"] == "segment_start"}
    assert starts == {"s-before", "s-after"}


def test_seq_reset_without_boundary_is_flagged_not_counted(tsdb_conn, sql_query, gap_source) -> None:
    """보조 안전망 — 경계 표식 **없이** 순번이 줄면 경보만 남기고 새 구간으로 본다.

    갭으로 세지 않는다. 세면 "3건 유실"처럼 보이는데 실제로는 리셋이다.
    """
    source = gap_source + "-reset"
    session = "s-same"
    for offset, seq in enumerate([1, 2, 3, 1, 2]):     # 같은 세션 안에서 순번이 되돌아간다
        _insert(tsdb_conn, source, "state", seq, offset, session_id=session)

    mine = [g for g in _gaps(tsdb_conn, sql_query) if g["source_id"] == source]
    verdicts = [g["verdict"] for g in mine]

    assert "seq_reset_without_boundary" in verdicts, "경보가 남아야 한다"
    assert "gap" not in verdicts, "리셋을 갭으로 세면 안 된다"
    reset = next(g for g in mine if g["verdict"] == "seq_reset_without_boundary")
    assert reset["loss_class"] is None, "갭이 아니므로 유실 분류가 붙지 않는다"


# ── 29. session_id 가 없을 때 birth 폴백 ───────────────────────────────────


def test_birth_fallback_when_no_session(tsdb_conn, sql_query, gap_source) -> None:
    """혼재 기간 — 하드웨어가 `session_id`를 아직 안 보낼 때 `status`의 `birth`가 경계다.

    `_on_connect`가 항상 `publish_status("birth")`를 부르므로 신뢰할 수 있는 표식이다.
    """
    source = gap_source + "-birth"
    # 1차 기동: birth → 순번 1,2,3 (session_id 없음)
    _insert(tsdb_conn, source, "status", None, 0, payload_extra={"event": "birth", "status": "online"})
    for offset, seq in enumerate([1, 2, 3], start=1):
        _insert(tsdb_conn, source, "state", seq, offset)
    # 2차 기동: birth 다시 → 순번 1,2,3
    _insert(tsdb_conn, source, "status", None, 10, payload_extra={"event": "birth", "status": "online"})
    for offset, seq in enumerate([1, 2, 3], start=11):
        _insert(tsdb_conn, source, "state", seq, offset)

    mine = [g for g in _gaps(tsdb_conn, sql_query) if g["source_id"] == source]
    problems = [g for g in mine if g["verdict"] in ("gap", "seq_reset_without_boundary")]

    assert problems == [], f"birth 폴백이 동작하면 리셋이 문제로 잡히지 않는다: {problems}"
    keys = {g["session_key"] for g in mine}
    assert keys == {"birth#1", "birth#2"}, f"구간이 birth 로 갈려야 한다: {keys}"


# ── 30. ★음성 — status 는 검출 대상에서 빠진다 ────────────────────────────


def test_status_excluded_from_gap(tsdb_conn, sql_query, gap_source) -> None:
    """★음성 — `status`에는 순번이 없다. **순번이 실려 있어도** 검출 대상이 아니다.

    Phase 1의 가짜 발행자가 state 본문을 status 채널로 보내던 시절의 옛 메시지에는 순번이
    붙어 있다. 채널로 명시적으로 제외하지 않으면 그것들이 갭으로 잡힌다.
    """
    source = gap_source + "-status"
    for offset, seq in [(0, 1), (1, 9)]:               # 1 → 9, 세면 7건 갭이다
        _insert(tsdb_conn, source, "status", seq, offset,
                payload_extra={"event": "summary", "status": "online"})

    mine = [g for g in _gaps(tsdb_conn, sql_query) if g["source_id"] == source]
    assert mine == [], f"status 가 검출 결과에 나오면 안 된다: {mine}"

    scope = _rows(tsdb_conn, sql_query("gap-detection.sql", "excluded_summary"))
    labels = {row["detection_scope"] for row in scope}
    assert any("status" in label for label in labels), f"제외 사유가 드러나야 한다: {labels}"


def test_analysis_excluded_from_gap(tsdb_conn, sql_query, gap_source) -> None:
    """★음성 — 증강 분석은 순번을 **대상 간에 공유**한다. 대상별 구멍은 유실이 아니다."""
    source = gap_source + "-analysis"
    for offset, seq in enumerate([3, 11, 27], start=0):   # 전역 카운터라 띄엄띄엄하다
        _insert(tsdb_conn, source, "state", seq, offset, entity_type="analysis")

    mine = [g for g in _gaps(tsdb_conn, sql_query) if g["source_id"] == source]
    assert mine == [], f"analysis 가 검출 결과에 나오면 안 된다: {mine}"


# ── 30. heartbeat 갭은 유실로 분류되지 않는다 ──────────────────────────────


def test_heartbeat_gap_not_classified_as_loss(tsdb_conn, sql_query, gap_source) -> None:
    """하트비트 구멍은 **갭으로는 세되 유실로 단정하지 않는다.**

    QoS 0이고 `allow_spool=False`라 두절 중 버퍼에도 안 쌓인다. 게다가 **로봇은 임무 중
    하트비트를 아예 끈다** — 침묵을 장애로 단정하면 임무 중인 로봇이 전부 장애가 된다.
    """
    source = gap_source + "-hb"
    session = "s-hb"
    for offset, seq in enumerate([1, 2, 5]):
        _insert(tsdb_conn, source, "heartbeat", seq, offset, session_id=session)

    gaps = [g for g in _gaps(tsdb_conn, sql_query)
            if g["source_id"] == source and g["verdict"] == "gap"]

    assert len(gaps) == 1
    assert gaps[0]["missing_count"] == 2
    assert gaps[0]["loss_class"] == "loss_not_implied", "하트비트 갭을 유실로 단정하면 안 된다"


def test_robot_state_stalled_sequence_is_not_a_gap(tsdb_conn, sql_query, gap_source) -> None:
    """로봇 `state`의 순번이 0에 멈춰 있는 것은 **생산자 결함이지 유실이 아니다.**

    `robot_node.py`가 `envelope(seq=self.seq)`를 쓰면서 `self.seq`를 증가시키지 않는다.
    이것을 갭으로 세면 20Hz 데이터가 전부 이상으로 보이고, 반대로 조용히 넘기면 결함이
    드러나지 않는다 — 그래서 `seq_stalled` 로 따로 표시한다.
    """
    source = gap_source + "-robot"
    session = "s-robot"
    for offset in range(4):
        _insert(tsdb_conn, source, "state", 0, offset, entity_type="robot", session_id=session)

    mine = [g for g in _gaps(tsdb_conn, sql_query) if g["source_id"] == source]
    verdicts = {g["verdict"] for g in mine}

    assert "gap" not in verdicts, "순번 정체를 갭으로 세면 안 된다"
    assert "seq_stalled" in verdicts, "결함이 드러나야 한다"
    assert all(g["loss_class"] is None for g in mine)


def test_robot_state_gap_is_not_loss_candidate(tsdb_conn, sql_query, gap_source) -> None:
    """로봇 순번이 고쳐진 뒤에도 — 로봇 `state`는 QoS 0이라 **갭이 유실을 뜻하지 않는다.**"""
    source = gap_source + "-robot2"
    session = "s-robot2"
    for offset, seq in enumerate([1, 2, 7]):
        _insert(tsdb_conn, source, "state", seq, offset, entity_type="robot", session_id=session)

    gaps = [g for g in _gaps(tsdb_conn, sql_query)
            if g["source_id"] == source and g["verdict"] == "gap"]

    assert len(gaps) == 1 and gaps[0]["missing_count"] == 4
    assert gaps[0]["loss_class"] == "loss_not_implied"


# ── 갭을 되짚는 재료가 함께 저장돼 있는가 ──────────────────────────────────


def test_replayed_periodic_marked_as_downsample_candidate(tsdb_conn, sql_query, gap_source) -> None:
    """재전송 구간의 `reason='periodic'`은 **다운샘플로 솎인 것**이지 유실이 아니다.

    이 구분이 없으면 정상 동작을 유실로 오판한다. 조회 결과에 그 힌트가 함께 나와야 한다.
    """
    source = gap_source + "-replay"
    session = "s-replay"
    _insert(tsdb_conn, source, "state", 1, 0, session_id=session)
    _insert(tsdb_conn, source, "state", 5, 1, session_id=session,
            replayed=True, reason="periodic")

    gaps = [g for g in _gaps(tsdb_conn, sql_query)
            if g["source_id"] == source and g["verdict"] == "gap"]

    assert len(gaps) == 1
    assert gaps[0]["replayed"] is True
    assert gaps[0]["reason"] == "periodic"
    assert gaps[0]["note"] is not None, "다운샘플 가능성이 힌트로 나와야 한다"


def test_buffer_cross_check_reads_dropped(tsdb_conn, sql_query, gap_source) -> None:
    """`status`의 `buffer.dropped`가 조회로 대조된다 — 갭의 **원인**을 가르는 재료다.

    노드가 spool 상한 초과로 스스로 버린 건수다. 이 값이 늘어난 구간의 갭은 진짜 손실이지만
    원인이 네트워크가 아니라 버퍼 고갈이다. `thinned`(솎아낸 것)와 구분해서 본다.
    """
    source = gap_source + "-buffer"
    _insert(tsdb_conn, source, "status", None, 0, payload_extra={
        "event": "summary", "status": "online",
        "buffer": {"pending": 0, "dropped": 0, "thinned": 0},
        "publish_failures": 0,
    })
    _insert(tsdb_conn, source, "status", None, 1, payload_extra={
        "event": "summary", "status": "online",
        "buffer": {"pending": 12, "dropped": 37, "thinned": 5},
        "publish_failures": 2,
    })

    rows = [r for r in _rows(tsdb_conn, sql_query("gap-detection.sql", "buffer_cross_check"))
            if r["source_id"] == source]

    assert len(rows) == 2
    assert rows[-1]["buffer_dropped"] == 37
    assert rows[-1]["buffer_thinned"] == 5, "솎아낸 것과 버린 것이 구분돼 나와야 한다"
    assert rows[-1]["publish_failures"] == 2
