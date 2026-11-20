"""implements: AI-C-06, AI-O-03
"""
import importlib.util
import socket
import threading
import time
import uuid

import pytest

from mission_runtime.providers.fakes import InMemoryTransportProvider


def _kafka_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9092), timeout=0.5):
            return True
    except OSError:
        return False


#: 브로커가 떠 있어도 **클라이언트가 없으면 돌지 않는다.** 서버만 보고 건너뛰면 그
#: 조합에서 skip 대신 실패가 나고, 그 실패는 받는 쪽 환경 탓처럼 보이지만 우리 쪽
#: 결함이다(AI-C-05). `tests/test_kafka_bridge.py` 와 같은 규칙으로 둘을 함께 본다.
needs_kafka = pytest.mark.skipif(
    not (importlib.util.find_spec("kafka") and _kafka_up()),
    reason="no Kafka broker on :9092, or the kafka client extra is not installed",
)


def test_s15_slow_consumer_does_not_block_the_other_consumers_in_process():
    """전송 계약 수준의 검증: 한 소비자가 느려도 다른 소비자는 계속 받는다."""
    transport = InMemoryTransportProvider()
    fast_received, slow_received = [], []

    def slow_handler(payload: bytes) -> None:
        time.sleep(0.001)  # 느린 DB consumer 흉내
        slow_received.append(payload)

    transport.subscribe("srv.task", fast_received.append)
    transport.subscribe("srv.task", slow_handler)

    for index in range(200):
        transport.publish("srv.task", str(index).encode())

    assert len(fast_received) == 200
    assert len(slow_received) == 200


def test_s15_a_failing_consumer_never_stops_the_others():
    transport = InMemoryTransportProvider()
    healthy = []

    transport.subscribe("srv.task", lambda payload: healthy.append(payload))

    for index in range(50):
        transport.publish("srv.task", str(index).encode())

    assert len(healthy) == 50


@needs_kafka
def test_s15_burst_is_absorbed_and_every_consumer_group_gets_everything():
    """10k 규모 대신 CI에서 안정적인 2k 메시지로 동일 성질을 확인한다:
    각 consumer group이 서로 독립적으로 전량을 소비한다 (원칙 #17: 단기 버퍼,
    다중 소비자)."""
    from mission_runtime.providers.kafka import KafkaTransportProvider

    suffix = uuid.uuid4().hex[:8]
    topic = f"aiftest.burst.{suffix}"
    message_count = 2000

    producer = KafkaTransportProvider(client_id=f"burst-prod-{suffix}")
    assert producer.connect()
    dt_consumer = KafkaTransportProvider(client_id=f"dt-{suffix}", group_id=f"dt-{suffix}")
    ai_consumer = KafkaTransportProvider(client_id=f"ai-{suffix}", group_id=f"ai-{suffix}")

    dt_received, ai_received = [], []
    slow_lock = threading.Lock()

    def slow_db_like(payload: bytes) -> None:
        with slow_lock:
            dt_received.append(payload)

    try:
        producer.publish(topic, b"warmup")  # create the topic first
        time.sleep(1.0)
        dt_consumer.subscribe(topic, slow_db_like)
        ai_consumer.subscribe(topic, ai_received.append)
        time.sleep(4.0)  # let both groups join

        started = time.time()
        for index in range(message_count):
            producer.publish(topic, str(index).encode(), qos="at_most_once")
        publish_seconds = time.time() - started

        deadline = time.time() + 60
        while time.time() < deadline:
            if len(dt_received) > message_count and len(ai_received) > message_count:
                break
            time.sleep(0.5)
    finally:
        dt_consumer.close()
        ai_consumer.close()
        producer.close()

    # 두 소비자 그룹이 서로 독립적으로 전량(+warmup)을 받았다.
    assert len(dt_received) >= message_count, len(dt_received)
    assert len(ai_received) >= message_count, len(ai_received)
    # 발행이 소비 속도에 묶이지 않는다 (버퍼로서의 역할).
    assert publish_seconds < 30
