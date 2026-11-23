"""레지스트리·감사·실행 기록(MySQL) 회귀 — MySQL 필요(없으면 **이 파일만 skip**).

단계 7·8의 검증은 사람이 손으로 돌린 일회성 스크립트였다. 이 파일은 그것을 **다시 돌릴 수
있는 회귀**로 굳힌다. 레지스트리는 목적 인터페이스 `RegistryWriter.observe()` 로,
실행 기록은 `append_mission_event()` 로 넣는다 — 테스트가 SQL 로 직접 UPSERT 하면 가드가
도는지가 아니라 DB 가 도는지만 확인하게 된다.

| 완료 판정 | 무엇 |
|---|---|
| 6 ★음성 | `mk2_app` 으로 DDL·선언 축 DELETE 가 **거부**된다 |
| 19 | `registration` 이 실린 `status` 로 관측 축이 채워진다 |
| 20 ★음성 | **과거 시각 `status` 가 최신값을 덮지 않는다** |
| 21 | `(zone, mac, ip)` 변경 시 이력이 1행 늘어난다 |
| 22 ★음성 | **빈 `mac`·`ip` 가 기존 값을 지우지 않는다** |
| 23 | **선언만 있고 관측이 없는 미배포 대상이 조회에 나온다** |
| 24·26 ★음성 | `mission_event`·`audit_log` 의 UPDATE·DELETE 가 **권한으로** 막힌다 |
| 25 | 같은 `event_key` 를 두 번 append 해도 1행이다 |
| 26 | `subject_kind` 가 `command`·`model` 인 두 행이 같은 감사 테이블에 들어간다 |

⚠ **테스트 행이 남는다.** `mk2_app` 에는 DELETE 권한이 없기 때문이며 그것이 의도다(완료 판정
6·24가 그것을 확인한다). 행은 `reg-t-*` / `m-test-*` / `audit-test-*` 로 표시되므로 관리자
계정으로 언제든 지울 수 있다:

    docker exec -i capstone_mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" mk2' <<'SQL'
    DELETE FROM registry_identity_history WHERE entity_id LIKE 'reg-t-%';
    DELETE FROM registry_entity_observed  WHERE entity_id LIKE 'reg-t-%';
    DELETE FROM registry_node_observed    WHERE node_id   LIKE 'pi-t-%';
    DELETE FROM mission_event             WHERE mission_id LIKE 'm-test-%';
    DELETE FROM audit_log                 WHERE actor_id   LIKE 'audit-test-%';
    SQL

implements: BE-Q-03(레지스트리), BE-C-02(식별자 계층), BE-S-05(감사 스키마), BE-S-08(실행 기록)
tests: 관측 축 upsert, 시각 가드(음성), 신원 이력, 빈 값 가드(음성), 미배포 대상 조회,
       append 멱등, append-only 권한(음성), 감사 대상 일반화, DDL 거부(음성)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from backend.storage.writer import TelemetryRecord

BASE_TS = datetime(2026, 9, 2, 0, 0, 0, tzinfo=timezone.utc)

MAC_A = "b8:27:eb:aa:bb:cc"
MAC_B = "b8:27:eb:dd:ee:ff"
IP_A = "192.168.50.31"
IP_B = "192.168.50.77"


# ── 공통 도구 ───────────────────────────────────────────────────────────────


@pytest.fixture
def ids(mysql_conn) -> Dict[str, str]:
    """이번 테스트만의 개체·노드 식별자. 대장은 키가 하나뿐이라 테스트끼리 갈라야 한다."""
    token = uuid.uuid4().hex[:8]
    return {"entity": "reg-t-{}".format(token), "node": "pi-t-{}".format(token)}


@pytest.fixture
def registry(mysql_conn):
    """운영 경로 그대로의 레지스트리 writer.

    `mysql_conn` 에 의존하는 이유는 **skip 을 한 곳에서만 판정**하기 위해서다.
    """
    from backend.storage.registry import MySqlRegistryWriter

    writer = MySqlRegistryWriter()
    yield writer
    writer.close()


def _status(
    entity_id: str,
    node_id: str,
    *,
    shift: float = 0.0,
    zone_id: str = "zoneA",
    mac: Optional[str] = MAC_A,
    ip: Optional[str] = IP_A,
    event: str = "birth",
    fw_version: str = "0.3.0",
    with_registration: bool = True,
) -> TelemetryRecord:
    """실노드가 보내는 `status` 와 같은 모양의 레코드.

    `with_registration=False` 는 LWT 다 — 본문에 `registration` 이 없다(`node.py:92`).
    """
    ts = BASE_TS + timedelta(seconds=shift)
    message: Dict[str, Any] = {
        "schema_version": "1.1",
        "source_id": entity_id,
        "node_id": node_id,
        "zone_id": zone_id,
        "timestamp": ts.isoformat(),
        "session_id": uuid.uuid4().hex[:12],
        "channel": "status",
        "event": event,
        "status": "online" if event != "death" else "offline",
        "device_status": "ok",
    }
    if with_registration:
        message["registration"] = {
            "entity_id": entity_id,
            "node_id": node_id,
            "zone_id": zone_id,
            "entity_type": "sensor",
            "device_type": "water_level",
            "fw_version": fw_version,
            "mac": mac,
            "ip": ip,
        }
    return TelemetryRecord(
        channel="status",
        topic="mk2.telemetry.status",
        message=message,
        key=entity_id,
        ingest_at=(ts + timedelta(seconds=0.5)).isoformat(),
        entity_type="sensor",
        stream_partition=0,
        stream_offset=int(shift),
    )


def _observe(writer, record: TelemetryRecord) -> None:
    """`observe()` 는 실패를 삼키고 로그만 남긴다(계측 저장을 막지 않기 위해서다).

    그래서 테스트에서 그냥 부르면 실패가 "행이 없다"로만 보여 원인을 알 수 없다. 누적 실패
    수를 함께 봐서 **왜 실패했는지가 드러나게** 한다.
    """
    before = writer._failures  # noqa: SLF001 - 실패 원인을 테스트에서 드러내기 위한 의도적 접근
    writer.observe(record)
    assert writer._failures == before, (  # noqa: SLF001
        "레지스트리 갱신이 실패했다 — 위 로그의 '레지스트리 갱신 실패' 줄을 본다"
    )


def _rows(conn, sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
    import pymysql

    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, args)
        return list(cur.fetchall())


def _one(conn, sql: str, args: tuple = ()) -> Optional[Dict[str, Any]]:
    rows = _rows(conn, sql, args)
    return rows[0] if rows else None


def _entity(conn, entity_id: str) -> Optional[Dict[str, Any]]:
    return _one(conn, "SELECT * FROM registry_entity_observed WHERE entity_id = %s", (entity_id,))


def _node(conn, node_id: str) -> Optional[Dict[str, Any]]:
    return _one(conn, "SELECT * FROM registry_node_observed WHERE node_id = %s", (node_id,))


def _history(conn, entity_id: str) -> List[Dict[str, Any]]:
    return _rows(
        conn,
        "SELECT * FROM registry_identity_history WHERE entity_id = %s ORDER BY id",
        (entity_id,),
    )


def _naive(moment: datetime) -> datetime:
    """MySQL `DATETIME(6)` 이 돌려주는 형태(naive UTC)로 맞춘다."""
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _assert_denied(conn, label: str, statement: str) -> None:
    """★음성 공통 — 권한으로 막히는지 본다.

    ⚠ 모든 문장에 **아무 행도 고르지 않는 조건**을 붙였다. 혹시 권한이 잘못 열려 있어도
    데이터가 지워지지 않게 하기 위해서다. 그 경우 이 확인은 실패하지만 기록은 살아 있다.
    """
    with conn.cursor() as cur:
        with pytest.raises(Exception) as caught:
            cur.execute(statement)
    message = str(caught.value)
    assert "denied" in message.lower(), f"{label} 가 권한이 아닌 다른 이유로 실패했다: {message}"
    assert "1142" in message, f"{label} 의 오류가 권한 거부(1142)가 아니다: {message}"


# ── 19. registration 이 실린 status 로 관측 축이 채워진다 ────────────────────


def test_registry_upsert_from_status(mysql_conn, registry, ids) -> None:
    """`status` 하나로 개체·노드 관측 축이 함께 선다.

    대장의 키는 **공통 헤더의 `source_id`** 다. `registration.entity_id` 가 아니다 — 봉투가
    필수로 보장하는 값이 `source_id` 뿐이고, 실노드는 `entity_id` 를 보내지 않는다(F9).
    """
    _observe(registry, _status(ids["entity"], ids["node"]))

    entity = _entity(mysql_conn, ids["entity"])
    node = _node(mysql_conn, ids["node"])

    assert entity is not None, "관측 축에 개체 행이 생겨야 한다"
    assert entity["zone_id"] == "zoneA" and entity["node_id"] == ids["node"]
    assert entity["entity_type"] == "sensor" and entity["device_type"] == "water_level"
    assert entity["last_event"] == "birth"
    assert entity["last_session_id"], "1.1 경로 — session_id 가 대장에 남는다"
    assert entity["first_seen"] == _naive(BASE_TS) == entity["last_seen"]

    assert node is not None, "관측 축에 노드 행이 생겨야 한다"
    assert (node["mac"], node["ip"], node["fw_version"]) == (MAC_A, IP_A, "0.3.0")

    # registration 이 없는 status(LWT)는 **아무 일도 하지 않고 지나간다** — 예외를 내지 않는다.
    # 급사 신호가 대장 쓰기 실패로 둔갑하면 안 된다.
    _observe(registry, _status(ids["entity"], ids["node"], shift=60, event="death",
                               with_registration=False))
    assert _entity(mysql_conn, ids["entity"])["last_seen"] == _naive(BASE_TS), (
        "registration 없는 status 는 대장을 건드리지 않는다"
    )


# ── 20. ★음성 — 과거 시각 status 가 최신값을 덮지 않는다 ─────────────────────


def test_registry_time_guard(mysql_conn, registry, ids) -> None:
    """★음성 — **재기동할 때마다 대장이 과거로 되돌아가면 안 된다.**

    `status` 는 retained 라 ingest 가 재기동할 때마다 브로커가 마지막 1건을 다시 밀어주고,
    저장 소비자는 `earliest` 라 재기동 시 옛 `status` 를 다시 읽는다. 게다가 `status` 에는
    `sequence_id` 가 없어 순번으로 신구를 가릴 수 없다(F4).
    **실측(2026-09-10): 재기동 뒤 47분 전 `ts` 를 가진 retained status 가 그대로 다시 흘렀다.**
    """
    _observe(registry, _status(ids["entity"], ids["node"], shift=600, zone_id="zoneB"))
    before = _entity(mysql_conn, ids["entity"])
    history_before = len(_history(mysql_conn, ids["entity"]))

    # 10분 **전** 시각의 status 를 다른 구역으로 보낸다 — 덮이면 안 된다.
    _observe(registry, _status(ids["entity"], ids["node"], shift=0, zone_id="zoneA",
                               event="summary"))

    after = _entity(mysql_conn, ids["entity"])
    assert after["zone_id"] == "zoneB", "★ 과거 status 가 최신 구역을 덮었다"
    assert after["last_seen"] == before["last_seen"], "last_seen 이 과거로 되돌아갔다"
    assert after["last_event"] == before["last_event"]
    assert len(_history(mysql_conn, ids["entity"])) == history_before, (
        "덮지 않았는데 이력만 늘면 그것도 오염이다"
    )


# ── 21. (zone, mac, ip) 변경 시 이력이 1행 늘어난다 ──────────────────────────


def test_registry_identity_history(mysql_conn, registry, ids) -> None:
    """이력 판정 조합은 하드웨어 `Identity.fingerprint()` 와 같은 `(zone_id, mac, ip)` 다.

    생산자의 재등록 판정 기준과 저장의 이력 기준이 어긋나면, 하드웨어는 "바뀌었다"는데
    대장에는 아무 흔적이 없는 상태가 된다.
    """
    _observe(registry, _status(ids["entity"], ids["node"], shift=0, zone_id="zoneA"))
    assert [h["change_reason"] for h in _history(mysql_conn, ids["entity"])] == ["first_seen"], (
        "처음 보는 개체는 초기 상태를 1행 남긴다 — 이력만으로 임의 시점 신원을 복원하려면 필요하다"
    )

    # 구역이 바뀌었다 → 1행 는다
    _observe(registry, _status(ids["entity"], ids["node"], shift=10, zone_id="zoneB",
                               event="summary"))
    assert [h["change_reason"] for h in _history(mysql_conn, ids["entity"])] == \
        ["first_seen", "zone_id"]

    # 같은 값이 다시 왔다 → 늘지 않는다 (이게 없으면 10초마다 이력이 쌓인다)
    _observe(registry, _status(ids["entity"], ids["node"], shift=20, zone_id="zoneB",
                               event="summary"))
    assert len(_history(mysql_conn, ids["entity"])) == 2, "같은 신원은 이력을 늘리지 않는다"

    # MAC 이 바뀌었다 → 1행 는다
    _observe(registry, _status(ids["entity"], ids["node"], shift=30, zone_id="zoneB",
                               mac=MAC_B, event="summary"))
    history = _history(mysql_conn, ids["entity"])
    assert len(history) == 3 and history[-1]["change_reason"] == "mac"
    assert history[-1]["mac"] == MAC_B and history[-1]["changed_at"] == _naive(
        BASE_TS + timedelta(seconds=30)
    )


# ── 22. ★음성 — 빈 mac·ip 가 기존 값을 지우지 않는다 ─────────────────────────


def test_registry_empty_mac_ip_not_overwrite(mysql_conn, registry, ids) -> None:
    """★음성 — 증강 분석이 `Identity(..., "", "", "analysis")` 로 빈 값을 보낸다(F7).

    빈 값으로 덮으면 멀쩡한 도달 정보가 지워진다. "안 보냈다"가 "지워라"가 되면 안 된다.
    """
    _observe(registry, _status(ids["entity"], ids["node"], shift=0))
    assert (_node(mysql_conn, ids["node"])["mac"], _node(mysql_conn, ids["node"])["ip"]) == \
        (MAC_A, IP_A)
    history_before = len(_history(mysql_conn, ids["entity"]))

    # 빈 문자열이 실린 최신 status — 시각 가드는 통과하지만 값은 덮이면 안 된다.
    _observe(registry, _status(ids["entity"], ids["node"], shift=30, mac="", ip="",
                               event="summary"))

    node = _node(mysql_conn, ids["node"])
    assert node["mac"] == MAC_A, "★ 빈 mac 이 기존 값을 지웠다"
    assert node["ip"] == IP_A, "★ 빈 ip 가 기존 값을 지웠다"
    assert node["last_seen"] == _naive(BASE_TS + timedelta(seconds=30)), (
        "값은 지키되 last_seen 은 갱신된다 — 도달 자체는 최신이다"
    )
    assert len(_history(mysql_conn, ids["entity"])) == history_before, (
        "빈 값이 '변경'으로 기록되면 이력이 오염된다"
    )


# ── 23. 선언만 있고 관측이 없는 미배포 대상이 조회에 나온다 ──────────────────


def test_registry_declared_visible_without_telemetry(mysql_conn, registry, ids, sql_query) -> None:
    """**BE-Q-03의 핵심** — 값을 한 번도 보낸 적 없는 대상이 목록에 있어야 한다.

    텔레메트리에서 자동으로 대장을 채우면 미배포 대상은 영원히 화면에 나타나지 않는다.
    그래서 기준(FROM)이 선언 축이고 관측 축을 LEFT JOIN 으로 얹는다 — 반대로 짜면 미배포
    대상이 결과에서 사라진다. 이 테스트는 **그 방향이 뒤집히지 않았는지**를 본다.
    """
    # 관측만 있고 선언에 없는 개체를 하나 만든다(방향 확인의 대조군).
    _observe(registry, _status(ids["entity"], ids["node"]))

    declared_rows = _rows(mysql_conn, sql_query("registry-declared-vs-observed.sql",
                                                "declared_with_observed"))
    observed_only = _rows(mysql_conn, sql_query("registry-declared-vs-observed.sql",
                                                "observed_not_declared"))
    declared_total = _one(mysql_conn, "SELECT COUNT(*) AS n FROM registry_entity_declared")["n"]

    # ① 선언된 개체는 관측 여부와 무관하게 **하나도 빠지지 않는다.**
    assert len(declared_rows) == declared_total, (
        "선언 축의 행 수와 조회 결과 행 수가 다르다 — LEFT JOIN 방향이 뒤집혔을 수 있다"
    )
    # ② 방향이 반대가 아님을 대조군으로 확인한다.
    assert ids["entity"] not in {r["entity_id"] for r in declared_rows}, (
        "선언되지 않은 개체가 선언 기준 조회에 나오면 기준이 관측 축이라는 뜻이다"
    )
    assert ids["entity"] in {r["entity_id"] for r in observed_only}, (
        "관측됐는데 선언에 없는 개체는 대장 누락으로 드러나야 한다"
    )

    # ③ 미배포(관측 없음) 대상이 실제로 목록에 나오는가.
    unobserved = [r for r in declared_rows if not r["observed"]]
    if not unobserved:
        pytest.skip(
            "선언 축에 '관측 없는' 개체가 없어 완료 판정 23을 실물로 볼 수 없다 — "
            "docs/be/queries/registry-declared-vs-observed.sql 부록의 시드(wl-002)를 "
            "관리자 계정으로 넣은 뒤 다시 돌린다"
        )
    for row in unobserved:
        assert row["last_seen"] is None and row["observed_node_id"] is None
        assert row["display_name"], "화면에 표시할 이름이 있어야 목록으로 쓸 수 있다"
        expected = "미배포(정상)" if row["declared_deployed"] == 0 else "배포됐다는데 값이 없다"
        assert row["status_note"] == expected, (
            "관측이 없는 이유(미배포인가 이상인가)가 구분돼 나와야 한다"
        )
    assert any(r["declared_deployed"] == 0 for r in unobserved), (
        "미배포 대상이 목록에 나오는 것이 BE-Q-03의 핵심이다"
    )


# ── 12. 세션 타임존을 바꿔도 같은 순간을 가리킨다 (MySQL 쪽 절반) ────────────


def test_utc_storage_session_tz_invariant(mysql_conn, registry, ids) -> None:
    """`DATETIME(6)` 에 **UTC 값**을 넣으므로 세션 타임존이 바뀌어도 값이 흔들리지 않는다.

    MySQL `TIMESTAMP` 는 세션 타임존으로 자동 변환돼 클라이언트마다 다르게 읽힌다. 이 서버는
    `system_tz=KST` 라 그 차이가 9시간이다. 그래서 `TIMESTAMP` 를 쓰지 않는다 — 표시 시각
    변환은 조회하는 쪽의 몫이다. (TSDB `TIMESTAMPTZ` 쪽 절반은 `test_tsdb_storage.py` 의
    같은 이름 테스트에 있다 — 그쪽은 표현이 달라져도 **같은 순간**임을 본다.)
    """
    _observe(registry, _status(ids["entity"], ids["node"]))
    utc_row = _entity(mysql_conn, ids["entity"])
    assert utc_row["last_seen"] == _naive(BASE_TS), "저장 값이 UTC 그대로여야 한다"

    with mysql_conn.cursor() as cur:
        cur.execute("SET time_zone = '+09:00'")
        cur.execute("SELECT @@session.time_zone")
        assert cur.fetchone()[0] == "+09:00", (
            "세션 타임존이 실제로 바뀌지 않았으면 이 테스트는 아무것도 확인하지 못한다"
        )
    try:
        kst_row = _entity(mysql_conn, ids["entity"])
        assert kst_row["last_seen"] == utc_row["last_seen"], (
            "★ DATETIME 값이 세션 타임존을 따라 움직였다 — TIMESTAMP 타입을 쓴 것은 아닌지 본다"
        )
        assert kst_row["first_seen"] == utc_row["first_seen"]
        history = _history(mysql_conn, ids["entity"])
        assert history and history[0]["changed_at"] == _naive(BASE_TS)
    finally:
        # 세션 fixture 를 공유하므로 반드시 되돌린다 — 안 그러면 뒤 테스트가 오염된다.
        with mysql_conn.cursor() as cur:
            cur.execute("SET time_zone = '+00:00'")


# ── 25. 같은 event_key 를 두 번 append 해도 1행 ──────────────────────────────


def test_mission_event_idempotent(mysql_conn) -> None:
    """재삽입 멱등 — 생산자(가시화·엣지)가 Phase 6에 붙을 때 같은 사건을 두 번 보낼 수 있다.

    `event_key` 가 `None` 이면 그냥 들어간다 — MySQL 의 UNIQUE 는 NULL 을 여럿 허용하므로
    키 없는 사건이 이 울타리와 충돌하지 않는다. 키를 줄지 말지는 생산자가 정한다.

    ⚠ 중복을 `INSERT IGNORE` 로 처리하지 않는다. 그러면 값 잘림 같은 다른 오류까지 함께 삼켜
    조용히 틀린 행이 들어간다.
    """
    from backend.storage.mission import append_mission_event

    token = uuid.uuid4().hex[:8]
    mission_id = "m-test-{}".format(token)
    event_key = "evt-test-{}".format(token)
    occurred = BASE_TS

    first = append_mission_event(occurred_at=occurred, layer="task", node_ref="t-001",
                                 event_type="started", parent_ref="m-001", attempt=1,
                                 actor_kind="ai", actor_id="planner-1", mission_id=mission_id,
                                 target_entity_id="rb-01", origin_kind="simulation",
                                 event_key=event_key, detail={"note": "첫 삽입"},
                                 record_version="1")
    again = append_mission_event(occurred_at=occurred, layer="task", node_ref="t-001",
                                 event_type="started", actor_kind="ai", mission_id=mission_id,
                                 event_key=event_key, detail={"note": "재삽입"})

    assert again == first, "재삽입은 새 행이 아니라 기존 seq 를 돌려준다"
    keyed = _rows(mysql_conn, "SELECT * FROM mission_event WHERE event_key = %s", (event_key,))
    assert len(keyed) == 1, "★ 같은 event_key 가 두 행이 되면 안 된다"
    assert keyed[0]["detail"] and "첫 삽입" in keyed[0]["detail"], "재삽입이 기존 행을 덮지 않는다"
    assert keyed[0]["occurred_at"] == _naive(occurred), "UTC naive 로 저장된다"
    assert keyed[0]["layer"] == "task" and keyed[0]["attempt"] == 1

    # 키 없는 사건은 둘 다 들어간다. (actor_kind 는 NOT NULL — 키가 없어도 주체는 있어야 한다)
    a = append_mission_event(occurred_at=occurred, layer="milestone", node_ref="m-001",
                             event_type="planned", actor_kind="human", mission_id=mission_id)
    b = append_mission_event(occurred_at=occurred, layer="milestone", node_ref="m-001",
                             event_type="planned", actor_kind="human", mission_id=mission_id)
    assert a != b, "키 없는 사건은 서로 다른 행이다"
    total = _one(mysql_conn, "SELECT COUNT(*) AS n FROM mission_event WHERE mission_id = %s",
                 (mission_id,))["n"]
    assert total == 3, f"키 있는 1 + 키 없는 2 = 3행이어야 한다: {total}"

    # 서버가 부여하는 순번은 **단조 증가하지만 연속이 아니다** — 실패한 INSERT 도 채번을 쓴다.
    # 가시화가 "순번이 연속"이라고 가정하면 이 구멍을 유실로 오해한다(§9-2 문의 항목).
    assert b > a, "seq 는 단조 증가한다"


# ── 24·26의 근거. ★음성 — append-only 를 권한이 지킨다 ──────────────────────


def test_mission_event_update_denied(mysql_conn) -> None:
    """★음성 — **코드 규율이 아니라 DB 권한이 지킨다.**

    BE-S-08 이 *"수정·삭제하지 않으며"* 를 요구하고, 원칙 5가 감사의 무결성을 요구한다.
    코드로 약속하면 언젠가 누군가 깬다. `mk2_app` 에는 두 테이블에 `SELECT, INSERT` 만 있다.
    """
    _assert_denied(mysql_conn, "mission_event UPDATE",
                   "UPDATE mission_event SET event_type = event_type WHERE seq = -1")
    _assert_denied(mysql_conn, "mission_event DELETE",
                   "DELETE FROM mission_event WHERE seq = -1")
    _assert_denied(mysql_conn, "audit_log UPDATE",
                   "UPDATE audit_log SET result = result WHERE id = -1")
    _assert_denied(mysql_conn, "audit_log DELETE",
                   "DELETE FROM audit_log WHERE id = -1")


# ── 26. 감사 대상 일반화 ────────────────────────────────────────────────────


def test_audit_subject_generalized(mysql_conn) -> None:
    """명령과 모델 승인이 **같은 감사 테이블**에 들어간다.

    AI-L-06 이 *"승인 주체·시간·대상 버전과 적용 범위의 authoritative 기록"* 을, VZ-U-08 이
    *"승인 대상이 모델·정책·지식"* 을 요구한다. 성격은 감사와 같다(누가·언제·무엇을·어떤
    결과로). `command_id` 전용으로 좁게 만들면 나중에 넣을 자리가 없다.

    ⚠ **이것은 쓰기 경로 확인이 아니라 스키마 확인이다.** 감사 쓰기 경로·actor 토큰 주입은
    Phase 6이다(인증이 감사의 선행조건이다) — §6 울타리.
    """
    actor_id = "audit-test-{}".format(uuid.uuid4().hex[:8])
    insert = (
        "INSERT INTO audit_log (occurred_at, recorded_at, subject_kind, subject_id, action,"
        " target_entity_id, zone_id, actor_kind, actor_id, origin_kind, result, detail,"
        " record_version)"
        " VALUES (%s, UTC_TIMESTAMP(6), %s, %s, %s, 'gate-01', 'zoneA', 'user', %s,"
        " 'simulation', 'success', %s, '1')"
    )
    with mysql_conn.cursor() as cur:
        cur.execute(insert, (_naive(BASE_TS), "command", "cmd-2026-0910-0001", "actuate",
                             actor_id, '{"note":"phase2 step10"}'))
        cur.execute(insert, (_naive(BASE_TS), "model", "yolo-v8n-2026-09", "approve_model",
                             actor_id, '{"note":"phase2 step10"}'))

    rows = _rows(mysql_conn, "SELECT * FROM audit_log WHERE actor_id = %s ORDER BY id", (actor_id,))

    assert len(rows) == 2
    assert {r["subject_kind"] for r in rows} == {"command", "model"}, (
        "두 종류가 같은 테이블에 들어가야 자리가 확보된 것이다"
    )
    assert rows[0]["occurred_at"] == _naive(BASE_TS), "시각은 UTC naive 로 저장된다"
    assert all(r["recorded_at"] is not None for r in rows), "기록 시각은 서버가 넣는다"


# ── 6. ★음성 — 스키마·선언 축을 앱이 바꿀 수 없다 ───────────────────────────


def test_ddl_denied(mysql_conn) -> None:
    """★음성 — `mk2_app` 에는 `CREATE`·`ALTER`·`DROP` 이 없다.

    **코드가 스키마를 바꿀 수 없어야 한다**(제약 14). 스키마 적용은 사람이 관리자 계정으로
    1회 한다. 선언 축(`registry_*_declared`·`registry_zone`)도 사람이 넣는 값이라 앱은 읽기만
    한다 — 미배포 대상 목록을 앱이 지울 수 있으면 대장의 의미가 없다.

    ⚠ `DROP TABLE` 로 시험하지 않는다 — 권한이 잘못 열려 있으면 실제 테이블이 사라진다.
    대신 **부여된 권한 목록 자체**를 확인한다. 문장 하나가 아니라 권한 표면 전체를 보는 쪽이
    증거로 더 강하다.
    """
    _assert_denied(mysql_conn, "CREATE TABLE", "CREATE TABLE mk2_should_not_exist (id INT)")
    _assert_denied(mysql_conn, "선언 축 DELETE",
                   "DELETE FROM registry_entity_declared WHERE entity_id = '__none__'")
    _assert_denied(mysql_conn, "선언 축 UPDATE",
                   "UPDATE registry_zone SET display_name = display_name WHERE zone_id = '__none__'")

    # 거부가 실제로 아무것도 만들지 않았는지 확인한다(오류만 보고 넘어가지 않는다).
    made = _one(
        mysql_conn,
        "SELECT COUNT(*) AS n FROM information_schema.TABLES"
        " WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'mk2_should_not_exist'",
        ("mk2",),
    )["n"]
    assert made == 0, "거부됐는데 테이블이 생겼다면 위 확인이 무의미하다"

    # 권한 목록에 DDL 이 아예 없어야 한다.
    with mysql_conn.cursor() as cur:
        cur.execute("SHOW GRANTS FOR CURRENT_USER()")
        grants = " | ".join(row[0] for row in cur.fetchall())
    for forbidden in ("CREATE", "ALTER", "DROP", "ALL PRIVILEGES", "GRANT OPTION"):
        assert forbidden not in grants, f"앱 계정에 {forbidden} 가 있다: {grants}"
    # append-only 두 테이블에는 SELECT, INSERT 만 있어야 한다.
    for table in ("audit_log", "mission_event"):
        line = next((g for g in grants.split(" | ") if f"`{table}`" in g), None)
        assert line is not None, f"{table} 권한 줄이 없다: {grants}"
        assert "SELECT, INSERT ON" in line, f"{table} 에 SELECT, INSERT 외의 권한이 있다: {line}"
