"""계측 저장의 TimescaleDB 구현 — `TelemetryWriter.write()` 뒤에 들어가는 몸통.

**저장 제품이 드러나는 곳은 여기 하나뿐이다.** 상위(저장 소비자·ingest)는 목적 인터페이스
`TelemetryWriter.write(record)`만 알고 psycopg를 부르지 않는다(원칙 1). 제품을 바꾸면 이
파일만 바뀐다 — 그러라고 Phase 1에서 인터페이스를 갈라 두었다.

## 저장 규칙

1. **원본 그대로 넣는다.** 칼럼은 인덱스를 위한 *추출*이고, 원본 메시지 전체는 `payload`
   (JSONB)에 통째로 들어간다. 없는 값을 채워 넣지 않는다 — 채우면 저장된 것이 원본이 아니게
   되고, "생산자가 안 보낸 것"과 "백엔드가 채운 것"을 나중에 구분할 수 없다.
2. **시간축은 발행 시각(`ts`)이다.** 지연 도착 데이터가 원래 측정 시각 자리에 꽂혀야 한다.
   `received_at` 축으로는 이것이 원천적으로 불가능하다.
3. **유일 키는 스트림 좌표다.** 저장 소비자는 `auto.offset.reset=earliest` + 자동 커밋이라
   구조적으로 재소비한다. 업무 내용 키(`sequence_id`)로는 막을 수 없다 — 로봇은 항상 0,
   `status`에는 없고, 증강 분석은 순번을 대상끼리 공유한다. 그래서
   `INSERT ... ON CONFLICT DO NOTHING`으로 도착 좌표에서 중복을 흡수한다.
4. **세션 타임존을 접속마다 명시한다.** 컨테이너 `TZ` 설정에 기대지 않는다 — 설정이 바뀌면
   과거 데이터 해석이 통째로 흔들린다.

A층 계측(Phase 3): 적재 성공/실패를 `be.storage.write{outcome=ok|fail}`로 센다 — Phase 2가 "세는
계측이 없어 누적을 눈으로 세야 한다"고 남긴 값이다. 어댑터의 목적 인터페이스만 부른다.

implements: BE-S-01 (시계열·상태 이력 저장), BE-S-07 (lag_s 보관), BE-S-02 (A층 — be.storage.write)
tests: tests/test_pipeline.py — TSDB 적재·시각 순 조회·재소비 중복 흡수 ·
       tests/test_observability_pipeline.py — be_storage_write_total 도달
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend import observability as obs
from backend import settings
from backend.storage.writer import TelemetryRecord, TelemetryWriter, parse_iso

LOG = logging.getLogger("mk2.storage.tsdb")

TABLE = "telemetry"
COMPONENT = "storage"

INSERT_SQL = """
INSERT INTO telemetry (
    ts, channel, entity_type,
    source_id, node_id, zone_id, entity_id, session_id, sequence_id,
    schema_version, origin_kind,
    ingest_at, received_at, lag_s, clock_skew, replayed,
    reason, device_status,
    stream_topic, stream_partition, stream_offset,
    payload
) VALUES (
    %(ts)s, %(channel)s, %(entity_type)s,
    %(source_id)s, %(node_id)s, %(zone_id)s, %(entity_id)s, %(session_id)s, %(sequence_id)s,
    %(schema_version)s, %(origin_kind)s,
    %(ingest_at)s, %(received_at)s, %(lag_s)s, %(clock_skew)s, %(replayed)s,
    %(reason)s, %(device_status)s,
    %(stream_topic)s, %(stream_partition)s, %(stream_offset)s,
    %(payload)s
)
ON CONFLICT DO NOTHING
"""


def record_to_params(record: TelemetryRecord) -> dict:
    """`TelemetryRecord` → INSERT 파라미터. **여기서 값을 만들어 내지 않는다.**

    없는 값은 `None`으로 두어 칼럼이 NULL이 된다. 그것이 "생산자가 안 보냈다"는 사실이며,
    조회 층이 규격대로 채우는 것은 읽기의 몫이다(`backend/storage/normalize.py`).
    """
    from psycopg.types.json import Jsonb  # 지역 import — 이 파일만 저장 제품을 안다

    message = record.message
    return {
        "ts": parse_iso(record.ts),
        "channel": record.channel,
        "entity_type": record.entity_type,
        "source_id": message.get("source_id"),
        "node_id": message.get("node_id"),
        "zone_id": message.get("zone_id"),
        # 실노드는 보내지 않는다(F9). NULL 인 것이 정상이며, 가짜 발행자만 옵션으로 채운다.
        "entity_id": message.get("entity_id"),
        # 하드웨어 적용 전에는 NULL. 그동안 순번 열의 경계는 status 의 birth 로 폴백한다.
        "session_id": message.get("session_id"),
        # status 에는 없고(F4) 로봇 state 는 항상 0 이다(F1). 유일 키로 쓰지 않는 이유.
        "sequence_id": message.get("sequence_id"),
        "schema_version": message.get("schema_version"),
        # 실노드는 보내지 않는다(F9). 미기재는 조회 시 real 로 해석한다.
        "origin_kind": message.get("origin_kind"),
        "ingest_at": parse_iso(record.ingest_at),
        "received_at": parse_iso(record.received_at),
        "lag_s": record.lag_s,
        "clock_skew": record.clock_skew,
        "replayed": record.replayed,
        # 본문 공통 코어. 증강 분석에는 둘 다 없으므로 NULL 이 정상이다(F6).
        "reason": message.get("reason"),
        "device_status": message.get("device_status"),
        "stream_topic": record.stream_topic,
        "stream_partition": record.stream_partition,
        "stream_offset": record.stream_offset,
        # 원본 메시지 전체(공통 헤더 포함). 칼럼은 추출이고 이것이 원본이다.
        "payload": Jsonb(message),
    }


class TimescaleTelemetryWriter(TelemetryWriter):
    """계측 1건을 `telemetry` 하이퍼테이블에 넣는다.

    접속은 게으르게(첫 write 때) 열고 오래 유지한다. 끊기면 **한 번만** 다시 열어 보고,
    그래도 안 되면 그 사실을 남긴다.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        dbname: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self._host = host or settings.tsdb_host()
        self._port = port or settings.tsdb_port()
        self._dbname = dbname or settings.tsdb_db()
        self._user = user or settings.tsdb_user()
        # 비밀번호는 기본값이 없다 — 없으면 여기서 MissingSetting 으로 죽는다.
        # 기본값을 두면 환경변수를 빠뜨린 채 떠서 한참 뒤에 인증 실패로 발견된다.
        self._password = password if password is not None else settings.tsdb_password()
        self._conn: Any = None
        self._write_failures = 0

    # ── 접속 ─────────────────────────────────────────────────────────────
    def _connect(self) -> Any:
        import psycopg  # 지역 import — 이 파일만 저장 제품을 안다

        conn = psycopg.connect(
            host=self._host,
            port=self._port,
            dbname=self._dbname,
            user=self._user,
            password=self._password,
            autocommit=True,          # 계측 1건이 곧 1트랜잭션. 모아서 실패하면 무엇이 빠졌는지 모른다
            application_name="mk2-storage",
        )
        # ⚠ 컨테이너 TZ 에 기대지 않는다. 접속마다 못 박는다(결정 3-D).
        conn.execute("SET TIME ZONE '{}'".format(settings.store_tz()))
        LOG.info(
            "TimescaleDB 접속: %s:%s/%s user=%s tz=%s",
            self._host, self._port, self._dbname, self._user, settings.store_tz(),
        )
        return conn

    def connection(self) -> Any:
        if self._conn is None or getattr(self._conn, "closed", False):
            self._conn = self._connect()
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not getattr(self._conn, "closed", False):
            self._conn.close()
        self._conn = None

    # ── 쓰기 ─────────────────────────────────────────────────────────────
    def write(self, record: TelemetryRecord) -> None:
        import psycopg

        params = record_to_params(record)
        try:
            self.connection().execute(INSERT_SQL, params)
        except psycopg.OperationalError as exc:
            # 접속이 끊긴 경우. 한 번만 다시 열어 본다.
            LOG.warning("TimescaleDB 접속이 끊겼다 — 재접속 후 1회 재시도: %s", exc)
            self.close()
            try:
                self.connection().execute(INSERT_SQL, params)
            except Exception as retry_exc:  # noqa: BLE001 - 재시도 실패는 그대로 남긴다
                self._fail(record, retry_exc)
                return
        except Exception as exc:  # noqa: BLE001 - 데이터 오류는 파이프라인을 죽이지 않는다
            self._fail(record, exc)
            return

        obs.count("be.storage.write", component=COMPONENT, channel=record.channel, outcome="ok")
        LOG.debug(
            "tsdb: %s/%s ts=%s offset=%s",
            record.channel, record.entity_type, record.ts, record.stream_offset,
        )

    def _fail(self, record: TelemetryRecord, exc: BaseException) -> None:
        """적재 실패를 **크게 남기고 파이프라인은 계속 돌린다.**

        한 건 때문에 소비자를 죽이면 그 뒤의 모든 계측이 멈춘다 — 관측 시스템에서는 그쪽이
        더 나쁘다. 대신 **스트림 좌표를 함께 남겨** 나중에 그 지점부터 다시 읽을 수 있게 한다
        (조용히 버리는 것과 다르다).

        실패 건수는 A층 `be.storage.write{outcome="fail"}`로도 센다(Phase 3) — 로그의 누적값과
        같은 사실을 관측 평면에서 `rate()`로 볼 수 있다.
        """
        self._write_failures += 1
        obs.count("be.storage.write", component=COMPONENT, channel=record.channel, outcome="fail")
        LOG.error(
            "TimescaleDB 적재 실패(누적 %d건) — 이 좌표에서 다시 읽을 수 있다: "
            "topic=%s partition=%s offset=%s source_id=%s ts=%s / %s: %s",
            self._write_failures,
            record.stream_topic,
            record.stream_partition,
            record.stream_offset,
            record.message.get("source_id"),
            record.ts,
            type(exc).__name__,
            exc,
        )
