"""implements: AI-C-20, AI-C-06, AI-C-10, AI-C-11
covers: terminal/<device-id>/{downlink,uplink} wire round-trip, async
        result tracking, rejection without a following CommandResult,
        Capability -> CapabilityRegistry bridging, malformed-uplink
        isolation, real-broker interop identical to the in-memory fake

Integration test skips automatically when no broker is reachable, so the
suite still runs offline (same pattern as test_mqtt_transport.py).
"""

import importlib.util
import socket
import time

import pytest

from perception_framework.contracts.physical_command import (
    CancelCommandRequest,
    CancelCommandResponse,
    Capability,
    Command,
    CommandAcceptance,
    CommandResult,
    ExecutionStatus,
    Rejection,
)
from perception_framework.execution.physical_command_gateway import (
    PhysicalCommandGateway,
    downlink_topic,
    uplink_topic,
)
from perception_framework.providers.fakes import InMemoryTransportProvider
from perception_framework.providers.physical_command_protobuf import (
    PhysicalCommandProtobufSerializerProvider,
)
from perception_framework.registry.capability_registry import CapabilityRegistry


def _gateway(transport=None, registry=None):
    return PhysicalCommandGateway(
        transport or InMemoryTransportProvider(),
        PhysicalCommandProtobufSerializerProvider(),
        registry=registry,
    )


def _device_reply(transport, device_id, obj):
    """Stand in for the device side: encode+publish one uplink message,
    exactly as a real device would (this repo never implements that side,
    interface-spec §... — only its shape is reused here for the test)."""
    payload = PhysicalCommandProtobufSerializerProvider().encode(obj)
    transport.publish(uplink_topic(device_id), payload)


def test_topics_follow_the_interface_spec_convention():
    assert downlink_topic("robot1") == "terminal/robot1/downlink"
    assert uplink_topic("robot1") == "terminal/robot1/uplink"


def test_send_command_publishes_encoded_bytes_to_downlink():
    transport = InMemoryTransportProvider()
    gateway = _gateway(transport)
    command = Command("c-1", "robot1", "navigate.relative", {"distance": 1.0})

    gateway.send_command("robot1", command)

    assert len(transport.published) == 1
    topic, payload, _qos = transport.published[0]
    assert topic == "terminal/robot1/downlink"
    decoded = PhysicalCommandProtobufSerializerProvider().decode(payload)
    assert decoded["message_type"] == "command"
    assert decoded["payload"]["command_id"] == "c-1"


def test_success_flow_reaches_wait_for_result():
    transport = InMemoryTransportProvider()
    gateway = _gateway(transport)
    gateway.attach("robot1")

    gateway.send_command("robot1", Command("c-1", "robot1", "navigate.relative", {"distance": 1.0}))
    _device_reply(transport, "robot1", CommandAcceptance("c-1", True, 100.0))
    assert gateway.get_acceptance("c-1").accepted is True
    assert gateway.wait_for_result("c-1", timeout=0.01) is None  # not terminal yet

    _device_reply(
        transport, "robot1",
        CommandResult("c-1", ExecutionStatus.SUCCEEDED, 101.0, result={"distance_moved": 1.0}),
    )

    result = gateway.wait_for_result("c-1", timeout=1.0)
    assert result is not None
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.result == {"distance_moved": 1.0}


def test_rejection_is_terminal_without_a_command_result():
    transport = InMemoryTransportProvider()
    gateway = _gateway(transport)
    gateway.attach("robot1")

    gateway.send_command("robot1", Command("c-2", "robot1", "fly", {}))
    from perception_framework.contracts.physical_command import RejectionCode

    _device_reply(
        transport, "robot1",
        CommandAcceptance("c-2", False, 100.0, Rejection(RejectionCode.UNIMPLEMENTED, "action not supported")),
    )

    acceptance = gateway.get_acceptance("c-2")
    assert acceptance.accepted is False
    assert acceptance.rejection.code == "UNIMPLEMENTED"
    assert gateway.wait_for_result("c-2", timeout=1.0) is None


def test_cancel_flow():
    transport = InMemoryTransportProvider()
    gateway = _gateway(transport)
    gateway.attach("robot1")

    gateway.send_command("robot1", Command("c-3", "robot1", "navigate.relative", {}))
    _device_reply(transport, "robot1", CommandAcceptance("c-3", True, 100.0))

    gateway.send_cancel("robot1", CancelCommandRequest("c-3"))
    downlink_topics = [topic for topic, _payload, _qos in transport.published]
    assert downlink_topics.count("terminal/robot1/downlink") == 2

    _device_reply(transport, "robot1", CancelCommandResponse("c-3", True))
    assert gateway.get_cancel_response("c-3").accepted is True

    _device_reply(transport, "robot1", CommandResult("c-3", ExecutionStatus.CANCELED, 105.0))
    result = gateway.wait_for_result("c-3", timeout=1.0)
    assert result.status == ExecutionStatus.CANCELED


def test_duplicate_resend_leaves_the_last_reported_acceptance_intact():
    transport = InMemoryTransportProvider()
    gateway = _gateway(transport)
    gateway.attach("robot1")

    gateway.send_command("robot1", Command("c-4", "robot1", "navigate.relative", {}))
    gateway.send_command("robot1", Command("c-4", "robot1", "navigate.relative", {}))  # retransmit
    _device_reply(transport, "robot1", CommandAcceptance("c-4", True, 100.0))

    assert gateway.get_acceptance("c-4").accepted is True


def test_capability_announcement_registers_into_the_capability_registry():
    transport = InMemoryTransportProvider()
    registry = CapabilityRegistry()
    gateway = _gateway(transport, registry=registry)
    gateway.attach("robot1")

    _device_reply(
        transport, "robot1",
        Capability(
            name="navigate.relative", version="1.0",
            parameter_schema="schema://navigate-relative-params",
            result_schema="schema://navigate-relative-result",
            cancel_supported=True, required_resources=("mobility.base",),
        ),
    )

    providers = registry.available_providers("hardware.action.navigate.relative")
    assert len(providers) == 1
    assert providers[0].provider_id == "robot1"
    assert providers[0].compatibility.required_runtime_tags == ("mobility.base",)
    assert gateway.known_capabilities("robot1")[0].name == "navigate.relative"


def test_unregister_device_drops_its_capabilities_only():
    transport = InMemoryTransportProvider()
    registry = CapabilityRegistry()
    gateway = _gateway(transport, registry=registry)
    gateway.attach("robot1")
    gateway.attach("robot2")

    for device_id in ("robot1", "robot2"):
        _device_reply(
            transport, device_id,
            Capability(name="navigate.relative", version="1.0",
                       parameter_schema="s://p", result_schema="s://r"),
        )

    gateway.unregister_device("robot1")

    remaining = registry.available_providers("hardware.action.navigate.relative")
    assert [p.provider_id for p in remaining] == ["robot2"]


def test_malformed_uplink_from_one_device_does_not_affect_another():
    transport = InMemoryTransportProvider()
    gateway = _gateway(transport)
    gateway.attach("robot1")
    gateway.attach("robot2")

    transport.publish(uplink_topic("robot1"), b"not a valid protobuf envelope")
    _device_reply(transport, "robot2", CommandAcceptance("c-5", True, 100.0))

    assert gateway.get_acceptance("c-5").accepted is True


def test_no_registry_means_capability_announcements_are_simply_not_registered():
    transport = InMemoryTransportProvider()
    gateway = _gateway(transport, registry=None)
    gateway.attach("robot1")

    _device_reply(
        transport, "robot1",
        Capability(name="navigate.relative", version="1.0", parameter_schema="s://p", result_schema="s://r"),
    )

    assert gateway.known_capabilities("robot1")[0].name == "navigate.relative"


# -- real broker interop -------------------------------------------------

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883


def broker_reachable() -> bool:
    try:
        with socket.create_connection((BROKER_HOST, BROKER_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def paho_installed() -> bool:
    return importlib.util.find_spec("paho") is not None


needs_broker = pytest.mark.skipif(
    not (paho_installed() and broker_reachable()), reason="no MQTT broker on 127.0.0.1:1883"
)


@needs_broker
def test_real_mqtt_broker_round_trip():
    from perception_framework.providers.mqtt import MqttTransportProvider

    edge = MqttTransportProvider(BROKER_HOST, BROKER_PORT, client_id="gw-test-edge")
    device = MqttTransportProvider(BROKER_HOST, BROKER_PORT, client_id="gw-test-device")
    assert edge.connect(timeout_s=5.0), "edge-side client failed to connect to the broker"
    assert device.connect(timeout_s=5.0), "device-side client failed to connect to the broker"
    try:
        gateway = _gateway(edge)
        gateway.attach("gw-test-robot")

        received: list[bytes] = []
        device.subscribe(downlink_topic("gw-test-robot"), received.append)
        time.sleep(0.3)  # broker subscribe ack

        gateway.send_command("gw-test-robot", Command("c-real-1", "gw-test-robot", "navigate.relative", {}))

        deadline = time.time() + 5.0
        while not received and time.time() < deadline:
            time.sleep(0.05)
        assert received, "downlink command never reached the device-side subscriber"

        device.publish(
            uplink_topic("gw-test-robot"),
            PhysicalCommandProtobufSerializerProvider().encode(CommandAcceptance("c-real-1", True, time.time())),
        )

        deadline = time.time() + 5.0
        while gateway.get_acceptance("c-real-1") is None and time.time() < deadline:
            time.sleep(0.05)
        acceptance = gateway.get_acceptance("c-real-1")
        assert acceptance is not None and acceptance.accepted is True
    finally:
        edge.close()
        device.close()
