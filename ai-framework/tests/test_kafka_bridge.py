"""tests for: AI-C-06, AI-C-14, AI-B-10, AI-O-03
covers: real Kafka round-trip, MQTT<->Kafka bridge, edge runs no Kafka
        server, bridge survives a downed link, short-term replay reference

Every integration test skips when the corresponding broker is absent, so
the suite still runs offline.
"""

import importlib.util
import socket
import time
import uuid

import pytest

from ai_framework.common.data_plane import DataKind
from ai_framework.edge.bridge import EdgeTransportBridge, TopicRoute
from ai_framework.providers.adapters import TransportProvider
from ai_framework.providers.fakes import InMemoryTransportProvider

KAFKA_BOOTSTRAP = "127.0.0.1:9092"
MQTT_HOST, MQTT_PORT = "127.0.0.1", 1883


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _installed(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


needs_kafka_lib = pytest.mark.skipif(not _installed("kafka"), reason="kafka client extra not installed")
needs_kafka = pytest.mark.skipif(
    not (_installed("kafka") and _reachable("127.0.0.1", 9092)), reason="no Kafka broker on :9092"
)
needs_both = pytest.mark.skipif(
    not (
        _installed("kafka")
        and _installed("paho")
        and _reachable("127.0.0.1", 9092)
        and _reachable(MQTT_HOST, MQTT_PORT)
    ),
    reason="needs both an MQTT broker and a Kafka broker",
)


def kafka_provider(**kwargs):
    from ai_framework.providers.kafka import KafkaTransportProvider

    return KafkaTransportProvider(KAFKA_BOOTSTRAP, **kwargs)


def mqtt_provider(**kwargs):
    from ai_framework.providers.mqtt import MqttTransportProvider

    return MqttTransportProvider(MQTT_HOST, MQTT_PORT, **kwargs)


def wait_for(predicate, timeout=15.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# --- transport contract ------------------------------------------------


@needs_kafka_lib
def test_kafka_provider_satisfies_the_same_protocol_as_every_other_transport():
    from ai_framework.providers.kafka import KafkaTransportProvider

    assert isinstance(KafkaTransportProvider.__new__(KafkaTransportProvider), TransportProvider)


def test_only_the_kafka_module_imports_the_kafka_client():
    """AI-C-06: AI 로직은 MQTT·Kafka API를 직접 호출하지 않는다."""
    import subprocess
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "ai_framework"
    hit = subprocess.run(
        ["grep", "-rln", "--include=*.py", "from kafka import", str(package)],
        capture_output=True,
        text=True,
    )

    assert [Path(f).name for f in hit.stdout.split() if f] == ["kafka.py"]


def test_bridge_module_never_names_a_concrete_protocol_in_code():
    """원칙 #2: 상위 로직은 목적 수준의 공통 인터페이스만 사용한다.

    The bridge must be written against TransportProvider only — if it ever
    imports or instantiates a concrete client, this fails.
    """
    import tokenize
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "ai_framework" / "edge" / "bridge.py"
    with open(path, "rb") as fh:
        code_tokens = {
            tok.string.lower()
            for tok in tokenize.tokenize(fh.readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        }

    assert not code_tokens & {"paho", "kafka", "mqtt", "kafkaproducer", "kafkaconsumer"}


# --- real Kafka --------------------------------------------------------


@needs_kafka
def test_publish_subscribe_round_trip_through_a_real_kafka_broker():
    topic = f"aiftest.task.risk.{uuid.uuid4().hex[:8]}"
    received = []

    consumer = kafka_provider(client_id="test-consumer", group_id=f"g-{uuid.uuid4().hex[:8]}")
    producer = kafka_provider(client_id="test-producer")
    assert producer.connect()
    try:
        consumer.subscribe(topic, received.append)
        time.sleep(1.0)  # let the consumer group settle

        producer.publish(topic, b'{"risk":"WATCH"}')

        assert wait_for(lambda: received)
    finally:
        consumer.close()
        producer.close()

    assert received == [b'{"risk":"WATCH"}']


@needs_kafka
def test_guaranteed_delivery_yields_a_short_term_replay_reference():
    """AI-O-03 + 원칙 #17: Kafka offset은 단기 재현용 포인터일 뿐이다."""
    topic = f"aiftest.task.verdict.{uuid.uuid4().hex[:8]}"
    producer = kafka_provider(client_id="test-replay")
    assert producer.connect()
    try:
        producer.publish_task_data(topic, b"verdict", DataKind.RISK_VERDICT)
        reference = producer.last_replay_reference
    finally:
        producer.close()

    assert reference is not None
    assert reference.topic == topic
    assert reference.offset >= 0


@needs_kafka
def test_media_payload_is_refused_on_the_backbone_transport():
    from ai_framework.common.data_plane import DataPlaneViolation

    producer = kafka_provider(client_id="test-media")
    assert producer.connect()
    try:
        with pytest.raises(DataPlaneViolation):
            producer.publish_task_data("aiftest.task.frame", b"\x00" * 8, DataKind.VIDEO_FRAME)
    finally:
        producer.close()


@needs_kafka_lib
def test_unreachable_kafka_degrades_instead_of_raising():
    from ai_framework.providers.kafka import KafkaTransportProvider

    provider = KafkaTransportProvider("127.0.0.1:1", client_id="test-down")

    assert provider.connect(timeout_s=1.0) is False
    provider.publish("aiftest.task.x", b"payload")  # must not raise
    provider.subscribe("aiftest.task.x", lambda p: None)  # must not raise
    assert provider.is_connected() is False
    provider.close()


# --- bridge, transport-agnostic ---------------------------------------


def test_bridge_works_with_two_fakes_and_counts_both_directions():
    device, server = InMemoryTransportProvider(), InMemoryTransportProvider()
    bridge = EdgeTransportBridge(
        device, server, [TopicRoute("dev/task", "srv.task", DataKind.PERCEPTION_RESULT)]
    )
    bridge.start()

    device.publish("dev/task", b"observation")  # 말단 -> 서버
    server.publish("srv.task", b"command-echo")  # 서버 -> 말단

    assert bridge.stats.uplink == 1
    assert bridge.stats.downlink == 1


def test_bridge_drops_and_keeps_running_when_the_server_link_is_down():
    device, server = InMemoryTransportProvider(), InMemoryTransportProvider(connected=False)
    bridge = EdgeTransportBridge(
        device, server, [TopicRoute("dev/task", "srv.task", DataKind.PERCEPTION_RESULT)]
    )
    bridge.start()

    device.publish("dev/task", b"observation")

    # 백본 단절이 엣지 동작을 중단시키지 않는다 (AI-C-11).
    assert bridge.stats.uplink == 0
    assert bridge.stats.dropped == {"server_link_down": 1}


def test_control_route_uses_guaranteed_delivery_qos():
    device, server = InMemoryTransportProvider(), InMemoryTransportProvider()
    bridge = EdgeTransportBridge(
        device, server, [TopicRoute("dev/ctl", "srv.ctl", DataKind.CONTROL_COMMAND)]
    )
    bridge.start()

    server.publish("srv.ctl", b"start")  # 서버 -> 엣지 -> 말단 제어 명령

    forwarded_qos = device.published[-1][2]
    assert forwarded_qos == "at_least_once"


def test_observability_and_media_kinds_are_rejected_as_bridge_routes():
    # 관측 데이터와 영상은 이 경로를 쓰지 않는다 (원칙 #10, AI-C-14).
    for kind in (DataKind.METRIC, DataKind.VIDEO_FRAME):
        with pytest.raises(ValueError):
            TopicRoute("dev/x", "srv.x", kind)


@needs_both
def test_real_bridge_forwards_device_mqtt_message_to_server_kafka():
    """말단 MQTT -> 엣지 Bridge -> 서버 Kafka, with no Kafka server on the edge."""
    suffix = uuid.uuid4().hex[:8]
    device_topic = f"aiftest/dev/{suffix}"
    server_topic = f"aiftest.srv.{suffix}"
    arrived = []

    edge_device_side = mqtt_provider(client_id=f"bridge-dev-{suffix}")
    edge_server_side = kafka_provider(client_id=f"bridge-srv-{suffix}")
    server_consumer = kafka_provider(client_id=f"srv-consumer-{suffix}", group_id=f"g-{suffix}")
    device = mqtt_provider(client_id=f"device-{suffix}")

    assert edge_device_side.connect() and edge_server_side.connect() and device.connect()
    try:
        server_consumer.subscribe(server_topic, arrived.append)
        time.sleep(1.0)

        bridge = EdgeTransportBridge(
            edge_device_side,
            edge_server_side,
            [TopicRoute(device_topic, server_topic, DataKind.PERCEPTION_RESULT)],
        )
        bridge.start()
        time.sleep(0.3)

        device.publish(device_topic, b'{"objects":1}')

        assert wait_for(lambda: arrived), "message did not cross the bridge"
        assert bridge.stats.uplink >= 1
    finally:
        server_consumer.close()
        edge_device_side.close()
        edge_server_side.close()
        device.close()

    assert arrived[0] == b'{"objects":1}'


def test_bridge_does_not_loop_its_own_forwarded_messages():
    """Regression: both sides subscribe to topics the bridge publishes to,
    so an unguarded bridge forwards its own output forever."""
    device, server = InMemoryTransportProvider(), InMemoryTransportProvider()
    bridge = EdgeTransportBridge(
        device, server, [TopicRoute("dev/task", "srv.task", DataKind.PERCEPTION_RESULT)]
    )
    bridge.start()

    device.publish("dev/task", b"observation")

    assert bridge.stats.uplink == 1
    assert bridge.stats.downlink == 0  # must not bounce back to the device


def test_a_genuine_retransmission_is_still_forwarded():
    device, server = InMemoryTransportProvider(), InMemoryTransportProvider()
    bridge = EdgeTransportBridge(
        device, server, [TopicRoute("dev/task", "srv.task", DataKind.PERCEPTION_RESULT)]
    )
    bridge.start()

    device.publish("dev/task", b"same-payload")
    device.publish("dev/task", b"same-payload")

    assert bridge.stats.uplink == 2


@needs_kafka
def test_connected_state_survives_bootstrap_socket_closing():
    """Regression: `bootstrap_connected()` flips to False on a healthy
    producer once metadata is cached, which made the edge bridge drop every
    uplink message as 'server_link_down'."""
    producer = kafka_provider(client_id=f"conn-{uuid.uuid4().hex[:6]}")
    assert producer.connect()
    try:
        topic = f"aiftest.conn.{uuid.uuid4().hex[:8]}"
        for _ in range(3):
            producer.publish(topic, b"x")
            assert producer.is_connected() is True
    finally:
        producer.close()
