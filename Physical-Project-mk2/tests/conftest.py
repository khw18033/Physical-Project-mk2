"""Phase 1 회귀 테스트의 공통 설정 — 접속 정보와 Kafka 임시 소비자.

접속 정보의 정본은 `backend/settings.py`의 환경변수 표다. 여기서 기본값을 다시 적지 않고
그대로 참조한다(두 벌이 되면 조용히 갈라진다). 테스트 전용 값만 여기서 읽는다:
`MK2_TEST_TIMEOUT`(기본 20초 — 도달 대기 상한), 그리고 Phase 3 관측 저장소 **조회** 주소
`MK2_PROMETHEUS_URL`(기본 `http://localhost:7861`) · `MK2_LOKI_URL`(`http://localhost:3100`) ·
`MK2_TEMPO_URL`(`http://localhost:3200`) — 백엔드는 아직 이 셋을 질의하지 않으므로(질의 프록시 BE-Q-01은
Phase 5/6) settings 가 아니라 여기 둔다. 발신 주소(`MK2_OTEL_ENDPOINT`)는 settings 것을 쓴다.

**실행 위치 주의.** 발행자는 MQTT만 쓰므로 어디서든 서버 Mosquitto로 쏠 수 있지만, 결과가
나타나는 곳(Kafka 토픽·격리 파일·sink 파일·WS)은 파이프라인이 도는 곳에서 보인다. 전부
환경변수로 가리킬 수 있으며, 기본값은 "파이프라인이 도는 서버에서 실행"을 가정한다.

Mosquitto·Kafka 가동은 전제다(둘은 Phase 1 파이프라인의 필수 요소라 skip 대상이 아니다).
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Callable, List, Optional

import pytest

# 설치(`pip install -e .`) 없이 저장소를 복사만 해도 `backend`를 찾도록.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# `tests/publisher.py`를 `import publisher`로 쓸 수 있게 이 디렉터리도 경로에 둔다.
# pytest의 import 모드(prepend/importlib)에 따라 자동 삽입 여부가 달라지므로 여기서 고정한다.
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from backend import settings  # noqa: E402  (위 sys.path 보정 뒤에 import)


@pytest.fixture(scope="session")
def broker() -> dict:
    """발행 대상 Mosquitto (`MK2_BROKER_HOST` / `MK2_BROKER_PORT`)."""
    return {"host": settings.broker_host(), "port": settings.broker_port()}


@pytest.fixture(scope="session")
def kafka_bootstrap() -> str:
    return settings.kafka_bootstrap()


@pytest.fixture(scope="session")
def ws_url() -> str:
    return settings.ws_url()


@pytest.fixture(scope="session")
def quarantine_path() -> Path:
    return settings.quarantine_path()


@pytest.fixture(scope="session")
def sink_path() -> Path:
    return settings.sink_path()


@pytest.fixture(scope="session")
def timeout_s() -> float:
    return float(os.environ.get("MK2_TEST_TIMEOUT", "20"))


# ── 저장소 fixture — 없으면 **그 테스트만 skip** 한다 ───────────────────────
#
# "인프라가 없으면 해당 테스트만 skip하고 나머지는 통과한다"는 저절로 되지 않는다. 접속
# 실패를 그대로 두면 전건이 빨갛게 되어 **무엇이 진짜 실패인지 안 보인다.** 이 격리 자체가
# 요구사항(핵심·선택 분리)의 증거다.
#
# Mosquitto·Kafka 는 예외다 — Phase 1 파이프라인의 필수 요소라 skip 대상이 아니다.


def _skip(reason: str, exc: BaseException) -> None:
    pytest.skip("{} — {}: {}".format(reason, type(exc).__name__, exc))


@pytest.fixture(scope="session")
def tsdb_conn():
    """계측 TSDB 접속(`mk2_app`). 드라이버·접속 정보·서버 중 하나라도 없으면 skip."""
    psycopg = pytest.importorskip("psycopg", reason="psycopg 미설치 — TSDB 테스트를 건너뛴다")
    try:
        password = settings.tsdb_password()
    except Exception as exc:  # noqa: BLE001 - MissingSetting 포함
        _skip("TSDB 접속 정보가 없다(MK2_TSDB_PASSWORD)", exc)
    try:
        conn = psycopg.connect(
            host=settings.tsdb_host(), port=settings.tsdb_port(),
            dbname=settings.tsdb_db(), user=settings.tsdb_user(), password=password,
            autocommit=True, connect_timeout=5,
        )
    except Exception as exc:  # noqa: BLE001
        _skip("TimescaleDB 에 붙지 못했다", exc)
    conn.execute("SET TIME ZONE '{}'".format(settings.store_tz()))
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def mysql_conn():
    """감사·레지스트리·실행 기록 MySQL 접속(`mk2_app`). 없으면 skip."""
    pymysql = pytest.importorskip("pymysql", reason="PyMySQL 미설치 — MySQL 테스트를 건너뛴다")
    try:
        password = settings.mysql_password()
    except Exception as exc:  # noqa: BLE001
        _skip("MySQL 접속 정보가 없다(MK2_MYSQL_PASSWORD)", exc)
    try:
        conn = pymysql.connect(
            host=settings.mysql_host(), port=settings.mysql_port(),
            database=settings.mysql_db(), user=settings.mysql_user(), password=password,
            charset="utf8mb4", autocommit=True, connect_timeout=5,
        )
    except Exception as exc:  # noqa: BLE001
        _skip("MySQL 에 붙지 못했다", exc)
    with conn.cursor() as cur:
        cur.execute("SET time_zone = '+00:00'")
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def sql_query():
    """`docs/be/queries/*.sql` 의 `-- @@QUERY: <이름>` 절을 꺼내 돌려준다.

    **테스트가 SQL을 다시 적지 않는다.** 커밋된 파일이 유일한 기준이고 테스트는 그것이
    실제로 도는지를 본다 — 두 벌이 되면 문서와 동작이 조용히 갈린다(공통 규격을 파이썬에
    다시 선언하지 않는 것과 같은 이유다).
    """
    queries_dir = REPO_ROOT / "docs" / "be" / "queries"

    def _load(filename: str, name: str) -> str:
        text = (queries_dir / filename).read_text(encoding="utf-8")
        marker = "-- @@QUERY: {}".format(name)
        if marker not in text:
            raise KeyError("{} 안에 '{}' 절이 없다".format(filename, name))
        body = text.split(marker, 1)[1]
        # 다음 절이 시작되면 거기서 끊는다.
        body = body.split("\n-- @@QUERY:", 1)[0]
        statement = body.split(";", 1)[0].strip()
        if not statement:
            raise ValueError("'{}' 절이 비어 있다".format(name))
        return statement

    return _load


# ── 관측 저장소 fixture (Phase 3) — 없으면 그 테스트만 skip ─────────────────
#
# 표준 라이브러리 urllib 만 쓴다(`requests` 를 넣지 않는다 — 헬퍼는 `tests/obs_query.py`). 셋 다
# "조회" 용이고, 관측이 업무의 전제조건이 아니듯 이 fixture 도 파이프라인 테스트의 전제조건이
# 아니다 — 관측 스택이 없는 컴퓨터에서는 관측 테스트만 건너뛰고 나머지는 그대로 돈다.

from obs_query import http_get  # noqa: E402  (위 sys.path 보정 뒤에 import)


def _observability_url(env: str, default: str, ready_path: str, what: str) -> str:
    base = os.environ.get(env, default).rstrip("/")
    try:
        body = http_get(base + ready_path, timeout=3.0)
    except Exception as exc:  # noqa: BLE001
        _skip("{} 에 붙지 못했다({})".format(what, base), exc)
    if what == "Loki" and "ready" not in body.lower():
        pytest.skip("{} 가 아직 ready 가 아니다: {}".format(what, body.strip()[:60]))
    return base


@pytest.fixture(scope="session")
def prometheus_url() -> str:
    """서버 Prometheus 조회 주소(`/api/v1/query`). `/-/healthy` 가 안 되면 skip."""
    return _observability_url("MK2_PROMETHEUS_URL", "http://localhost:7861", "/-/healthy", "Prometheus")


@pytest.fixture(scope="session")
def loki_url() -> str:
    """서버 Loki 조회 주소(`/loki/api/v1/query_range`). `/ready` 가 `ready` 가 아니면 skip."""
    return _observability_url("MK2_LOKI_URL", "http://localhost:3100", "/ready", "Loki")


@pytest.fixture(scope="session")
def tempo_url() -> str:
    """서버 Tempo 조회 주소(`/api/search`). `/ready` 가 안 되면 skip."""
    return _observability_url("MK2_TEMPO_URL", "http://localhost:3200", "/ready", "Tempo")


@pytest.fixture(scope="session")
def observe_timeout_s() -> float:
    """관측 도달 대기 상한(초). export 15s + scrape 5s + 여유. `MK2_OBSERVE_TIMEOUT` 로 조정."""
    return float(os.environ.get("MK2_OBSERVE_TIMEOUT", "45"))


# ── 미디어 엣지 입구 fixture (Phase 4) — 8766 에 닿지 않으면 그 테스트만 skip ─────
#
# 단계 8 이 8766 을 닫는데(`MK2_MEDIA_INGEST_PORT=0`) DoD 8-4 는 "되돌린 뒤 pytest 전건 통과"를 요구한다.
# `prometheus_url` 등과 같은 모양으로 — 도달 실패 시 `test_media_relay.py` 만 skip 되게 해서 모순을 푼다.
# 뷰어 입구(8765)는 Phase 1 부터 상주 3개의 일부라 skip 대상이 아니다.


@pytest.fixture(scope="session")
def ingest_url() -> str:
    """엣지 입구 기본 주소(`settings.media_ingest_url()`, 토큰 포함·`source_id` 없음). TCP 로 닿지 않으면 skip."""
    import socket
    from urllib.parse import urlsplit

    base = settings.media_ingest_url()
    parts = urlsplit(base)
    host, port = parts.hostname or "127.0.0.1", parts.port or 8766
    try:
        socket.create_connection((host, port), timeout=3).close()
    except OSError as exc:
        _skip("엣지 입구(8766)에 닿지 않는다 — 미디어 중계 테스트를 건너뛴다({}:{})".format(host, port), exc)
    return base


class KafkaReader:
    """토픽 구독 + 파티션 할당까지 마친 1회용 소비자.

    **할당이 끝난 뒤에 발행**해야 `latest` 정책에서 메시지를 놓치지 않는다(구독이 먼저,
    발행이 나중 — 파이프라인 앞단의 규칙과 같은 이유다).
    저장(`mk2-storage`)·WS(`mk2-ws`) 그룹의 오프셋을 건드리지 않도록 매번 고유 그룹을 쓴다.
    """

    def __init__(self, topics: List[str], bootstrap: str, assignment_timeout: float = 30.0) -> None:
        from confluent_kafka import Consumer  # 지역 import — 계약 단위 테스트는 Kafka 없이도 돈다

        self.consumer = Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": "mk2-test-{}".format(uuid.uuid4().hex[:8]),
                "auto.offset.reset": "latest",
                "enable.auto.commit": False,
            }
        )
        self.consumer.subscribe(topics)
        deadline = time.time() + assignment_timeout
        while time.time() < deadline:
            self.consumer.poll(0.5)
            if self.consumer.assignment():
                return
        raise TimeoutError("Kafka 파티션 할당 실패: topics={} bootstrap={}".format(topics, bootstrap))

    def wait_for(self, predicate: Callable, timeout: float):
        """조건에 맞는 메시지를 기다린다. 없으면 None."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.consumer.poll(0.5)
            if msg is None or msg.error():
                continue
            if predicate(msg):
                return msg
        return None

    def close(self) -> None:
        self.consumer.close()


@pytest.fixture
def kafka_reader(kafka_bootstrap) -> Callable[..., KafkaReader]:
    readers: List[KafkaReader] = []

    def _factory(topics: Optional[List[str]] = None) -> KafkaReader:
        reader = KafkaReader(topics or ["mk2.telemetry.state"], kafka_bootstrap)
        readers.append(reader)
        return reader

    yield _factory
    for reader in readers:
        reader.close()
