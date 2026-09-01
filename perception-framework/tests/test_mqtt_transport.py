"""implements: AI-C-06, AI-C-04, AI-C-12, AI-C-14
covers: real MQTT broker round-trip, identical contract to the in-memory
        fake, transport outage degrades instead of crashing

Integration tests skip automatically when no broker is reachable, so the
suite still runs offline (개발·CI 환경에서 브로커 없이도 동작).
"""

import importlib.util
import socket
import time

import pytest

from perception_framework.common.data_plane import DataKind, DataPlaneViolation
from perception_framework.providers.adapters import TransportProvider
from perception_framework.providers.fakes import InMemoryTransportProvider

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883


def broker_reachable() -> bool:
    try:
        with socket.create_connection((BROKER_HOST, BROKER_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def paho_installed() -> bool:
    """The MQTT client is an optional extra (`pip install -e ".[mqtt]"`).

    Its absence must disable only this provider, never the framework
    (AI-C-11, AI-C-12) — so these tests skip instead of failing.
    """
    return importlib.util.find_spec("paho") is not None


needs_paho = pytest.mark.skipif(not paho_installed(), reason="paho-mqtt extra not installed")
needs_broker = pytest.mark.skipif(
    not (paho_installed() and broker_reachable()), reason="no MQTT broker on 127.0.0.1:1883"
)


def mqtt_provider(**kwargs):
    from perception_framework.providers.mqtt import MqttTransportProvider

    return MqttTransportProvider(BROKER_HOST, BROKER_PORT, **kwargs)


@needs_paho
def test_real_provider_satisfies_the_same_protocol_as_the_fake():
    from perception_framework.providers.mqtt import MqttTransportProvider

    assert isinstance(InMemoryTransportProvider(), TransportProvider)
    assert isinstance(MqttTransportProvider.__new__(MqttTransportProvider), TransportProvider)


def test_only_the_mqtt_module_imports_the_client_library():
    """AI-C-06: AI 로직은 MQTT·Kafka API를 직접 호출하지 않는다."""
    import subprocess
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "perception_framework"
    hit = subprocess.run(
        ["grep", "-rln", "--include=*.py", "paho", str(package)], capture_output=True, text=True
    )
    files = [f for f in hit.stdout.split() if f]

    assert [Path(f).name for f in files] == ["mqtt.py"]


@needs_broker
def test_publish_subscribe_round_trip_through_a_real_broker():
    received = []
    subscriber = mqtt_provider(client_id="test-sub")
    publisher = mqtt_provider(client_id="test-pub")
    assert subscriber.connect() and publisher.connect()
    try:
        subscriber.subscribe("aiftest/task/perception", received.append)
        time.sleep(0.2)  # let SUBACK land

        publisher.publish("aiftest/task/perception", b'{"objects":[]}')

        deadline = time.time() + 3.0
        while not received and time.time() < deadline:
            time.sleep(0.05)
    finally:
        subscriber.close()
        publisher.close()

    assert received == [b'{"objects":[]}']


@needs_broker
def test_upper_layer_code_is_identical_across_fake_and_real_transport():
    """The same publisher function is handed each provider in turn."""

    def report_risk(transport, payload: bytes) -> None:
        # No MQTT/Kafka vocabulary here — this is what upper layers look like.
        transport.publish("aiftest/task/risk", payload, qos="at_least_once")

    fake = InMemoryTransportProvider()
    report_risk(fake, b"risk-1")
    assert fake.published[0][0] == "aiftest/task/risk"

    real = mqtt_provider(client_id="test-swap")
    assert real.connect()
    try:
        report_risk(real, b"risk-1")  # same call, real broker
        assert real.is_connected()
    finally:
        real.close()


@needs_broker
def test_control_command_is_published_with_guaranteed_delivery_policy():
    received = []
    subscriber = mqtt_provider(client_id="test-ctl-sub")
    publisher = mqtt_provider(client_id="test-ctl-pub")
    assert subscriber.connect() and publisher.connect()
    try:
        subscriber.subscribe("aiftest/control/+", received.append)
        time.sleep(0.2)

        publisher.publish_task_data("aiftest/control/start", b"cmd", DataKind.CONTROL_COMMAND)

        deadline = time.time() + 3.0
        while not received and time.time() < deadline:
            time.sleep(0.05)
    finally:
        subscriber.close()
        publisher.close()

    assert received == [b"cmd"]


@needs_broker
def test_media_payload_is_refused_on_the_task_transport():
    publisher = mqtt_provider(client_id="test-media")
    assert publisher.connect()
    try:
        with pytest.raises(DataPlaneViolation):
            publisher.publish_task_data("aiftest/task/frame", b"\x00" * 16, DataKind.VIDEO_FRAME)
    finally:
        publisher.close()


@needs_paho
def test_unreachable_broker_degrades_instead_of_raising():
    # 전송 장애가 상위 기능을 죽여서는 안 된다 (AI-C-11).
    provider = mqtt_provider(client_id="test-down")
    provider = type(provider)("127.0.0.1", 1, client_id="test-down")  # port 1: nothing listening

    assert provider.connect(timeout_s=0.5) is False
    provider.publish("aiftest/task/x", b"payload")  # must not raise
    provider.subscribe("aiftest/task/x", lambda p: None)  # must not raise
    assert provider.is_connected() is False
    provider.close()
