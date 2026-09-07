"""Phase 1 회귀 테스트의 공통 설정 — 접속 정보와 Kafka 임시 소비자.

접속 정보의 정본은 `backend/settings.py`의 환경변수 표다. 여기서 기본값을 다시 적지 않고
그대로 참조한다(두 벌이 되면 조용히 갈라진다). 테스트 전용 값만 여기서 읽는다:
`MK2_TEST_TIMEOUT`(기본 20초 — 도달 대기 상한).

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
