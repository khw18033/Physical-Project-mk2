"""임무 실행 기록 append 경로 — 되감기의 근거가 되는 사건 열.

**append-only 사건 열이다.** 상태를 단일 값으로 뭉쳐 저장하지 않고 기록 열에서 표시값을
파생시킨다 — 그래야 임의 시점 복원(되감기)이 성립한다. 실패한 임무와 사람 개입도 지우지
않는다(BE-S-08 *"수정·삭제하지 않으며"*).

**수정·삭제는 코드가 아니라 DB 권한이 막는다.** `mk2_app` 에는 `mission_event` 에 대해
`SELECT, INSERT` 만 있다. 코드 규율로 약속하면 언젠가 누군가 깬다.

## 감사와 왜 다른 테이블인가

둘 다 사건이지만 **조회 패턴이 다르다.**

| | 답하는 질문 | 조회 방식 |
|---|---|---|
| 감사(`audit_log`) | 누가 시켰나 | 대상·기간·조작자로 **검색** |
| 실행 기록(`mission_event`) | 임무가 어디까지 갔나 | 시점을 지정해 그 시점 상태를 **복원** |

## 이번 Phase의 범위 — 골격과 append 경로까지

**실제 생산자는 가시화·엣지이고 그 배선은 Phase 6/7이다.** 지금 이 함수를 부르는 것은
테스트뿐이다. 구체 필드·실패 단계 어휘·보존 기간·되감기 질의는 소비자(가시화) 회신 뒤에
정한다 — BE-S-08 원문이 *"상세 계약은 본 요구사항의 범위가 아니며 실제 소비 시점에
구체화한다"* 이다.

**감사(`audit_log`)에는 쓰기 경로를 만들지 않는다.** 테이블만 서 있고, actor 토큰 주입과
명령 사슬 배선은 Phase 6이다(인증이 감사의 선행조건이다).

implements: BE-S-08 (임무 실행 추적 기록 저장·시점 복원)
tests: tests/test_mission_event.py(파라미터 정규화 단위) · 서버 검증(멱등·권한)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from backend import settings
from backend.storage.registry import to_mysql_utc
from backend.storage.writer import parse_iso

LOG = logging.getLogger("mk2.storage.mission")

MYSQL_DUPLICATE_ENTRY = 1062

INSERT_EVENT = """
INSERT INTO mission_event
    (occurred_at, layer, node_ref, parent_ref, attempt, event_type,
     actor_kind, actor_id, mission_id, target_entity_id, origin_kind,
     correlation_id, event_key, detail, record_version)
VALUES (%(occurred_at)s, %(layer)s, %(node_ref)s, %(parent_ref)s, %(attempt)s, %(event_type)s,
        %(actor_kind)s, %(actor_id)s, %(mission_id)s, %(target_entity_id)s, %(origin_kind)s,
        %(correlation_id)s, %(event_key)s, %(detail)s, %(record_version)s)
"""

SELECT_BY_KEY = "SELECT seq FROM mission_event WHERE event_key = %s"


def normalize_occurred_at(value: Any) -> datetime:
    """`occurred_at` 을 MySQL `DATETIME(6)` 이 담는 **naive UTC** 로 맞춘다.

    ISO 문자열과 datetime 을 모두 받는다. 오프셋이 있으면 UTC 로 바꾼 뒤 떼고, 없으면 이미
    UTC 로 본다 — 로컬 시각으로 가정하면 서버 시간대 설정에 따라 값이 달라진다.
    """
    if isinstance(value, datetime):
        return to_mysql_utc(value) if value.tzinfo is not None else value
    if isinstance(value, str):
        parsed = parse_iso(value)
        if parsed is None:
            raise ValueError(
                f"occurred_at 을 읽지 못했다: {value!r} — 오프셋이 있는 ISO-8601 이어야 한다"
            )
        return to_mysql_utc(parsed)
    raise TypeError(f"occurred_at 은 datetime 이거나 ISO-8601 문자열이어야 한다: {type(value).__name__}")


def normalize_detail(value: Any) -> Optional[str]:
    """`detail`(JSON 칼럼)을 문자열로. 이미 문자열이면 그대로 둔다.

    미확정 필드는 전부 여기 들어간다 — 확정되면 칼럼으로 승격한다. 그 편이 지금 칼럼을
    박아 두고 나중에 뜯는 것보다 싸다.
    """
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def build_params(
    *,
    occurred_at: Any,
    layer: str,
    node_ref: str,
    event_type: str,
    actor_kind: str,
    parent_ref: Optional[str] = None,
    attempt: int = 1,
    actor_id: Optional[str] = None,
    mission_id: Optional[str] = None,
    target_entity_id: Optional[str] = None,
    origin_kind: Optional[str] = None,
    correlation_id: Optional[str] = None,
    event_key: Optional[str] = None,
    detail: Any = None,
    record_version: Optional[str] = None,
) -> Dict[str, Any]:
    """INSERT 파라미터를 만든다. **인프라 없이 시험할 수 있게** 밖으로 뺐다.

    `layer` 는 VZ-D-01 의 3계층(`milestone` | `task` | `action_item`)이고 `node_ref` 는 그
    계층의 **DAG 노드** 식별자다 — 물리 대상이 아니다. 물리 대상은 `target_entity_id` 하나로
    충분하고 나머지는 레지스트리 조인으로 얻는다.

    `actor_kind` 는 **필수**다 — VZ-D-02 *"산출 주체(AI·백엔드·사람)를 반드시 포함"*.
    DB 도 NOT NULL 이지만 빈 문자열은 DB 가 못 거르므로 여기서 함께 막는다. 어휘
    (`ai` | `backend` | `human`)는 VZ 회신 전이라 강제하지 않는다.
    """
    if not actor_kind:
        raise ValueError("actor_kind 는 비울 수 없다 — VZ-D-02 '산출 주체를 반드시 포함'")
    return {
        "occurred_at": normalize_occurred_at(occurred_at),
        "layer": layer,
        "node_ref": node_ref,
        "parent_ref": parent_ref,
        "attempt": attempt,
        "event_type": event_type,
        "actor_kind": actor_kind,
        "actor_id": actor_id,
        "mission_id": mission_id,
        "target_entity_id": target_entity_id,
        "origin_kind": origin_kind,
        "correlation_id": correlation_id,
        "event_key": event_key,
        "detail": normalize_detail(detail),
        "record_version": record_version,
    }


class MissionEventWriter:
    """`mission_event` 에 사건을 덧붙인다. 이미 있는 `event_key` 는 다시 넣지 않는다."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self._host = host or settings.mysql_host()
        self._port = port or settings.mysql_port()
        self._db = db or settings.mysql_db()
        self._user = user or settings.mysql_user()
        self._password = password if password is not None else settings.mysql_password()
        self._conn: Any = None

    def _connect(self) -> Any:
        import pymysql

        conn = pymysql.connect(
            host=self._host, port=self._port, database=self._db,
            user=self._user, password=self._password,
            charset="utf8mb4", autocommit=False,
        )
        with conn.cursor() as cur:
            cur.execute("SET time_zone = '+00:00'")
        conn.commit()
        return conn

    def connection(self) -> Any:
        """살아 있는 접속을 돌려준다. 끊겼으면 **우리가 직접** 새로 연다.

        드라이버의 자동 재접속을 쓰지 않는 이유는 `registry.py` 의 같은 함수에 적어 두었다 —
        재접속은 새 세션이라 `SET time_zone = '+00:00'` 이 복원되지 않고, PyMySQL 이 그 인자를
        폐기 예고했다.
        """
        if self._conn is None:
            self._conn = self._connect()
        else:
            try:
                self._conn.ping(reconnect=False)   # 살아 있으면 통과, 끊겼으면 예외
            except Exception:  # noqa: BLE001 - 되살릴 수 없으면 새로 연다
                self.close()
                self._conn = self._connect()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._conn = None

    def append(self, **fields: Any) -> int:
        """사건 1건을 덧붙이고 서버가 부여한 `seq` 를 돌려준다.

        **같은 `event_key` 가 이미 있으면 넣지 않고 기존 `seq` 를 돌려준다**(멱등).
        `event_key` 가 `None` 이면 그냥 들어간다 — MySQL 의 UNIQUE 는 NULL 을 여럿 허용하므로
        키 없는 사건은 이 울타리와 충돌하지 않는다. 생산자가 Phase 6 에 붙을 때 키를 줄지
        말지 스스로 정할 수 있어야 하기 때문이다.

        ⚠ 중복을 `INSERT IGNORE` 로 처리하지 않는다. 그러면 값 잘림 같은 **다른 오류까지 함께
        삼켜** 조용히 틀린 행이 들어간다. 중복 오류(1062)만 골라 잡는다.
        """
        import pymysql

        params = build_params(**fields)
        conn = self.connection()
        conn.begin()
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute(INSERT_EVENT, params)
                    seq = cur.lastrowid
                except pymysql.err.IntegrityError as exc:
                    if not exc.args or exc.args[0] != MYSQL_DUPLICATE_ENTRY:
                        raise
                    if params["event_key"] is None:
                        raise
                    cur.execute(SELECT_BY_KEY, (params["event_key"],))
                    row = cur.fetchone()
                    seq = row[0] if row else None
                    LOG.info(
                        "임무 사건 재삽입 무시(멱등): event_key=%s 기존 seq=%s",
                        params["event_key"], seq,
                    )
            conn.commit()
            return seq
        except Exception:
            conn.rollback()
            raise


_default_writer: Optional[MissionEventWriter] = None


def default_mission_writer() -> MissionEventWriter:
    global _default_writer
    if _default_writer is None:
        _default_writer = MissionEventWriter()
    return _default_writer


def append_mission_event(**fields: Any) -> int:
    """모듈 수준 편의 함수 — 지금은 테스트만 부른다.

    **실제 생산자는 가시화·엣지이고 그 배선은 Phase 6/7이다**(BE-S-08 전달 경로).
    여기까지 만들어 두는 이유는 "저장이 가능한가"를 지금 확인해 두기 위해서다.
    """
    return default_mission_writer().append(**fields)
