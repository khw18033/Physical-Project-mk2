"""레지스트리 관측 축 쓰기 — "무엇이 있는가"를 대장에 반영한다.

계측(TSDB)과 **성격이 다른 저장**이다. 계측은 "값이 시간에 따라 어떻게 변했나"이고
레지스트리는 "무엇이 있는가"다. 그래서 저장소도 테이블도 나뉜다(원칙 4).

## 왜 축이 둘인가 — 선언 축과 관측 축

BE-Q-03·VZ-I-03이 *"**존재해야 할** Entity 목록 ... **값을 발행하지 않는 미배포 대상도 이
목록으로 화면에 표시**"* 를 요구한다.

- **선언 축**(`registry_*_declared`·`registry_zone`) — 사람이 넣는다. **미배포 대상이
  여기 있다.** 텔레메트리에서 자동으로 채우면 미배포 대상이 영원히 나타나지 않는다.
  또한 원점 배치·Zone 트리·표시 이름은 `registration()`이 주지 않는 값이다.
- **관측 축**(`registry_*_observed`·`registry_identity_history`) — 이 모듈이 채운다.
  실제로 값을 보내온 것만 여기 있다.

## 이 모듈이 지키는 가드 셋

셋 다 없으면 대장이 조용히 틀린 상태가 된다.

1. **시각 가드** — 들어온 공통 헤더 `timestamp`가 저장된 `last_seen`보다 **이후일 때만**
   갱신한다. `status`는 retained라 ingest가 재기동할 때마다 브로커가 마지막 1건을 다시
   밀어주고, 저장 소비자는 `earliest`라 재기동 시 옛 `status`를 다시 읽는다. 게다가
   `status`에는 `sequence_id`가 없어 순번으로 신구를 가릴 수 없다.
   **실측(2026-09-10): 재기동 뒤 47분 전 `ts`를 가진 retained status가 그대로 다시 흘렀다.**
   가드가 없으면 재기동할 때마다 대장이 과거로 되돌아간다.
2. **빈 문자열 가드** — `mac`·`ip`가 빈 문자열이면 갱신하지 않는다. 증강 분석이
   `Identity(dev, node_id, ZONE, "", "", "analysis")`로 빈 값을 보낸다. 빈 값으로 덮으면
   멀쩡한 도달 정보가 지워진다.
3. **이력 기록 조건** — `(zone_id, mac, ip)`가 이전과 다를 때만 이력에 1행 추가한다.
   **이 셋은 하드웨어 `Identity.fingerprint()`와 같은 조합**이다 — 생산자의 재등록 판정
   기준과 저장의 이력 기준이 어긋나지 않게 한다.

A층 계측(Phase 3): 대장 갱신 성공/실패를 `be.registry.observe{outcome=ok|fail}`로 센다 — Phase 2가
"레지스트리 갱신 실패 건수도 세는 계측이 없다"고 남긴 값이다. `registration`이 없는 status(LWT)처럼
대상이 아니어서 지나간 것은 세지 않는다(성공도 실패도 아니다).

implements: BE-Q-03(레지스트리), BE-C-02(식별자 계층), BE-T-04(장치 등록), BE-S-02(A층 — be.registry.observe)
tests: tests/test_registry_guards.py(가드 판정 단위) · tests/test_pipeline.py(관통)
"""

from __future__ import annotations

import abc
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from backend import observability as obs
from backend import settings
from backend.storage.writer import TelemetryRecord, parse_iso

LOG = logging.getLogger("mk2.storage.registry")
COMPONENT = "storage"

# 이력을 남길지 판정하는 조합. HW `Identity.fingerprint()`와 같아야 한다.
FINGERPRINT_FIELDS: Tuple[str, ...] = ("zone_id", "mac", "ip")


# ── 순수 판정 함수 (인프라 없이 시험할 수 있게 밖으로 뺀다) ─────────────────


def registration_of(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """본문에서 등록 블록을 꺼낸다. 없으면 `None`.

    누락값 규칙에 따라 `{"value": ..., "state": ...}` 형태로 올 수 있으므로 벗겨 본다.
    `state`만 있고 값이 없으면 **등록 정보가 없는 것**이므로 `None`이다 — LWT가 그렇다.
    """
    registration = message.get("registration")
    if isinstance(registration, dict) and "state" in registration and "value" in registration:
        registration = registration.get("value")
    return registration if isinstance(registration, dict) else None


def pick(new: Any, old: Any) -> Any:
    """빈 문자열 가드 — 새 값이 비어 있으면 **기존 값을 지키고**, 아니면 새 값을 쓴다.

    증강 분석이 `mac`·`ip`를 빈 문자열로 보내기 때문에 필요하다. `None`도 같이 막는다 —
    "안 보냈다"가 "지워라"가 되면 안 된다.
    """
    if new is None:
        return old
    if isinstance(new, str) and not new.strip():
        return old
    return new


def is_newer(observed_at: Optional[datetime], last_seen: Optional[datetime]) -> bool:
    """시각 가드 — 관측 시각이 저장된 `last_seen`보다 **뒤일 때만** 참.

    같은 시각도 갱신하지 않는다. `timestamp`가 초 해상도라 같은 값이 여러 번 올 수 있고,
    재전달된 retained 메시지가 그 경우다 — 다시 써도 얻는 것이 없다.
    """
    if observed_at is None:
        return False
    if last_seen is None:
        return True
    return observed_at > last_seen


def changed_fields(previous: Dict[str, Any], incoming: Dict[str, Any]) -> Tuple[str, ...]:
    """이력 기록 조건 — `(zone_id, mac, ip)` 중 실제로 달라진 항목 이름들.

    **빈 문자열 가드를 통과한 뒤의 값끼리 비교한다.** 비교 전에 걸러야 "빈 값이 왔다"가
    "값이 바뀌었다"로 잘못 기록되지 않는다.
    """
    changes = []
    for field in FINGERPRINT_FIELDS:
        new_value = pick(incoming.get(field), previous.get(field))
        if new_value != previous.get(field):
            changes.append(field)
    return tuple(changes)


def to_mysql_utc(moment: Optional[datetime]) -> Optional[datetime]:
    """aware datetime → **naive UTC**. MySQL `DATETIME(6)` 칼럼이 담는 형태다.

    오프셋을 그대로 넘기면 `DATETIME`이 받지 못한다. 그렇다고 로컬 시각으로 넘기면 서버
    시간대 설정에 따라 값이 달라진다. UTC로 바꿔 naive로 넘기는 것이 유일하게 안전하다
    (읽어 올 때도 naive UTC로 돌아오므로 비교가 대칭이다).
    """
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


# ── 인터페이스 ──────────────────────────────────────────────────────────────


class RegistryWriter(abc.ABC):
    """레지스트리 관측 축의 목적 인터페이스.

    저장 소비자는 이것만 안다 — MySQL 클라이언트를 직접 만들지 않는다(원칙 1).
    `TelemetryWriter`가 이 일을 겸하게 만들지 않는 이유는 이름과 책임이 어긋나고, 계측 저장을
    갈아끼울 때 레지스트리가 딸려 오기 때문이다.
    """

    @abc.abstractmethod
    def observe(self, record: TelemetryRecord) -> None:
        """관측된 등록 정보를 대장에 반영한다. 대상이 아니면 **아무 일도 하지 않는다.**"""

    def close(self) -> None:
        """정리할 자원이 있으면 닫는다."""


class NullRegistryWriter(RegistryWriter):
    """아무것도 하지 않는 구현 — MySQL 없이 파이프라인을 돌릴 때 쓴다.

    ⚠ 이것이 **자동 폴백으로 선택되지 않는다.** `MK2_REGISTRY=none`으로 명시해야 한다.
    조용히 이쪽으로 떨어지면 대장이 비어 가는데 아무도 모른다.
    """

    def observe(self, record: TelemetryRecord) -> None:
        return None


# ── MySQL 구현 ──────────────────────────────────────────────────────────────

SELECT_ENTITY = """
SELECT entity_id, entity_type, device_type, node_id, zone_id, schema_version,
       last_session_id, first_seen, last_seen, last_event
FROM registry_entity_observed WHERE entity_id = %s FOR UPDATE
"""

INSERT_ENTITY = """
INSERT INTO registry_entity_observed
    (entity_id, entity_type, device_type, node_id, zone_id, schema_version,
     last_session_id, first_seen, last_seen, last_event, last_recorded_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
"""

UPDATE_ENTITY = """
UPDATE registry_entity_observed
SET entity_type = %s, device_type = %s, node_id = %s, zone_id = %s, schema_version = %s,
    last_session_id = %s, last_seen = %s, last_event = %s, last_recorded_at = UTC_TIMESTAMP(6)
WHERE entity_id = %s
"""

SELECT_NODE = """
SELECT node_id, fw_version, mac, ip, last_seen
FROM registry_node_observed WHERE node_id = %s FOR UPDATE
"""

INSERT_NODE = """
INSERT INTO registry_node_observed (node_id, fw_version, mac, ip, last_seen, last_recorded_at)
VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
"""

UPDATE_NODE = """
UPDATE registry_node_observed
SET fw_version = %s, mac = %s, ip = %s, last_seen = %s, last_recorded_at = UTC_TIMESTAMP(6)
WHERE node_id = %s
"""

INSERT_HISTORY = """
INSERT INTO registry_identity_history
    (entity_id, changed_at, recorded_at, zone_id, node_id, mac, ip, fw_version, change_reason)
VALUES (%s, %s, UTC_TIMESTAMP(6), %s, %s, %s, %s, %s, %s)
"""


class MySqlRegistryWriter(RegistryWriter):
    """관측 축 3개 테이블(개체·노드·이력)을 한 트랜잭션으로 갱신한다.

    읽고-판정하고-쓴다. 조건부 UPSERT SQL 한 방으로 짜지 않은 이유는 **가드가 눈에 보여야
    하기 때문**이다 — 시각 가드와 빈 문자열 가드가 `IF(...)` 안에 숨으면 나중에 아무도
    그것이 거기 있는 줄 모른다. `status`는 노드당 10초에 한 번이라 왕복이 문제되지 않는다.
    """

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
        self._failures = 0

    # ── 접속 ─────────────────────────────────────────────────────────────
    def _connect(self) -> Any:
        import pymysql  # 지역 import — 이 파일만 저장 제품을 안다

        conn = pymysql.connect(
            host=self._host,
            port=self._port,
            database=self._db,
            user=self._user,
            password=self._password,
            charset="utf8mb4",
            autocommit=False,     # 세 테이블을 한 덩어리로 갱신한다
            cursorclass=pymysql.cursors.DictCursor,
        )
        # ⚠ 컨테이너 TZ 에 기대지 않는다. 이 서버는 system_tz=KST 다.
        with conn.cursor() as cur:
            cur.execute("SET time_zone = '+00:00'")
        conn.commit()
        LOG.info(
            "MySQL 레지스트리 접속: %s:%s/%s user=%s (session tz=+00:00)",
            self._host, self._port, self._db, self._user,
        )
        return conn

    def connection(self) -> Any:
        """살아 있는 접속을 돌려준다. 끊겼으면 **우리가 직접** 새로 연다.

        ⚠ **드라이버의 자동 재접속(`ping(reconnect=True)`)을 쓰지 않는다.** 두 가지 이유다.

        1. **세션 설정이 조용히 사라진다.** 재접속은 새 세션이고, PyMySQL 이 되살려 주는 것은
           `connect()` 가 아는 것(charset·autocommit·init_command)뿐이다. 그 뒤에 우리가 실행한
           `SET time_zone = '+00:00'` 은 복원되지 않는다. 이 서버는 `system_tz=KST` 라 세션
           타임존이 풀리면 시각 해석이 흔들릴 자리가 생긴다.
        2. PyMySQL 이 이 인자를 폐기 예고했다(`DeprecationWarning`). 인자가 제거되면 재접속
           경로가 조용히 깨진다.

        `reconnect=False` 를 **명시**하는 것은 기본값이 버전마다 다르기 때문이다.
        """
        if self._conn is None:
            self._conn = self._connect()
        else:
            try:
                self._conn.ping(reconnect=False)   # 살아 있으면 통과, 끊겼으면 예외
            except Exception:  # noqa: BLE001 - 되살릴 수 없으면 새로 연다
                self.close()                       # 반쯤 닫힌 소켓을 남기지 않는다
                self._conn = self._connect()       # 세션 타임존이 여기서 다시 걸린다
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._conn = None

    # ── 쓰기 ─────────────────────────────────────────────────────────────
    def observe(self, record: TelemetryRecord) -> None:
        if record.channel != "status":
            return
        registration = registration_of(record.message)
        if registration is None:
            # registration 이 없는 status(LWT·요약 일부)는 **아무 일도 하지 않고 지나간다.**
            # 예외를 내지 않는다 — 급사 신호가 대장 쓰기 실패로 둔갑하면 안 된다.
            return

        observed_at = to_mysql_utc(parse_iso(record.ts))
        if observed_at is None:
            LOG.warning(
                "레지스트리 갱신 건너뜀 — timestamp를 읽지 못했다: source_id=%s ts=%r",
                record.message.get("source_id"), record.ts,
            )
            return

        try:
            self._apply(record, registration, observed_at)
        except Exception as exc:  # noqa: BLE001 - 대장 갱신 실패가 계측 저장을 막지 않는다
            self._failures += 1
            try:
                self.connection().rollback()
            except Exception:  # noqa: BLE001
                self.close()
            LOG.error(
                "레지스트리 갱신 실패(누적 %d건) — topic=%s offset=%s source_id=%s / %s: %s",
                self._failures, record.stream_topic, record.stream_offset,
                record.message.get("source_id"), type(exc).__name__, exc,
            )
            obs.count("be.registry.observe", component=COMPONENT, outcome="fail")
            return
        # 시각 가드에 걸려 조용히 지나간 것도 "정상 처리"다 — 대장이 과거로 되돌아가지 않았다.
        obs.count("be.registry.observe", component=COMPONENT, outcome="ok")

    def _apply(self, record: TelemetryRecord, registration: Dict[str, Any], observed_at: datetime) -> None:
        message = record.message
        # ⚠ 대장의 키는 **공통 헤더의 source_id** 다. registration.entity_id 가 아니다 —
        #   봉투가 필수로 보장하는 값이 source_id 뿐이고, 실노드는 entity_id 를 보내지 않는다.
        entity_id = message.get("source_id")
        node_id = message.get("node_id")
        zone_id = message.get("zone_id")
        if not entity_id or not node_id or not zone_id:
            LOG.warning("레지스트리 갱신 건너뜀 — 공통 헤더 필수값이 비었다: %r", message.get("source_id"))
            return

        conn = self.connection()
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(SELECT_ENTITY, (entity_id,))
            entity_row = cur.fetchone()
            cur.execute(SELECT_NODE, (node_id,))
            node_row = cur.fetchone()

            entity_fresh = is_newer(observed_at, entity_row["last_seen"] if entity_row else None)
            node_fresh = is_newer(observed_at, node_row["last_seen"] if node_row else None)

            if not entity_fresh and not node_fresh:
                # 시각 가드에 걸렸다 — retained 재전달이거나 재소비다. 과거로 되돌리지 않는다.
                conn.rollback()
                LOG.debug(
                    "레지스트리 시각 가드 — 과거 status 무시: entity_id=%s ts=%s last_seen=%s",
                    entity_id, observed_at, entity_row["last_seen"] if entity_row else None,
                )
                return

            # 이력 판정은 **갱신 전 값**으로 한다.
            previous = {
                "zone_id": entity_row["zone_id"] if entity_row else None,
                "mac": node_row["mac"] if node_row else None,
                "ip": node_row["ip"] if node_row else None,
            }
            incoming = {
                "zone_id": zone_id,
                "mac": registration.get("mac"),
                "ip": registration.get("ip"),
            }
            changes = changed_fields(previous, incoming)

            # ── 개체 관측 축 ──────────────────────────────────────────
            entity_type = pick(registration.get("entity_type"), record.entity_type)
            if entity_fresh:
                if entity_row is None:
                    cur.execute(
                        INSERT_ENTITY,
                        (
                            entity_id,
                            entity_type,
                            registration.get("device_type"),
                            node_id,
                            zone_id,
                            message.get("schema_version"),
                            message.get("session_id"),
                            observed_at,       # first_seen
                            observed_at,       # last_seen
                            message.get("event"),
                        ),
                    )
                else:
                    cur.execute(
                        UPDATE_ENTITY,
                        (
                            pick(entity_type, entity_row["entity_type"]),
                            pick(registration.get("device_type"), entity_row["device_type"]),
                            pick(node_id, entity_row["node_id"]),
                            pick(zone_id, entity_row["zone_id"]),
                            pick(message.get("schema_version"), entity_row["schema_version"]),
                            pick(message.get("session_id"), entity_row["last_session_id"]),
                            observed_at,
                            pick(message.get("event"), entity_row["last_event"]),
                            entity_id,
                        ),
                    )

            # ── 노드 관측 축 (빈 mac·ip 가 기존 값을 지우지 않는다) ────
            if node_fresh:
                if node_row is None:
                    cur.execute(
                        INSERT_NODE,
                        (
                            node_id,
                            pick(registration.get("fw_version"), None),
                            pick(registration.get("mac"), None),
                            pick(registration.get("ip"), None),
                            observed_at,
                        ),
                    )
                else:
                    cur.execute(
                        UPDATE_NODE,
                        (
                            pick(registration.get("fw_version"), node_row["fw_version"]),
                            pick(registration.get("mac"), node_row["mac"]),
                            pick(registration.get("ip"), node_row["ip"]),
                            observed_at,
                            node_id,
                        ),
                    )

            # ── 신원 이력 (append) ────────────────────────────────────
            if changes:
                reason = "first_seen" if entity_row is None else ",".join(changes)
                cur.execute(
                    INSERT_HISTORY,
                    (
                        entity_id,
                        observed_at,
                        zone_id,
                        node_id,
                        pick(registration.get("mac"), previous["mac"]),
                        pick(registration.get("ip"), previous["ip"]),
                        registration.get("fw_version"),
                        reason,
                    ),
                )
                LOG.info("레지스트리 이력 1행 추가: entity_id=%s 사유=%s", entity_id, reason)

        conn.commit()
        LOG.debug("레지스트리 갱신: entity_id=%s node_id=%s ts=%s", entity_id, node_id, observed_at)


def default_registry_writer() -> RegistryWriter:
    """저장 소비자가 쓰는 기본 구성.

    ⚠ **MySQL이 없을 때 조용히 `none`으로 떨어지지 않는다.** 그러면 대장이 비어 가는데
    아무도 모른다. 접속 정보가 없으면 기동 시점에 이름을 대며 죽는다. MySQL 없이 돌려야
    하면 `MK2_REGISTRY=none`으로 **명시적으로** 끈다.
    """
    kind = settings.registry_writer()
    if kind == "none":
        LOG.warning("레지스트리 쓰기가 꺼져 있다(MK2_REGISTRY=none) — 관측 축이 채워지지 않는다")
        return NullRegistryWriter()
    if kind == "mysql":
        return MySqlRegistryWriter()
    raise ValueError(
        f"알 수 없는 레지스트리 구현: {kind!r} (쓸 수 있는 값: mysql, none). MK2_REGISTRY 를 확인한다."
    )
