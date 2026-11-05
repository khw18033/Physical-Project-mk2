"""implements: AI-C-20, AI-C-06, AI-C-10, AI-C-05
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

from mission_runtime.contracts.capability_contract import DeclarationBasis
from mission_runtime.contracts.physical_command import (
    CancelCommandRequest,
    CancelCommandResponse,
    Capability,
    Command,
    CommandAcceptance,
    CommandResult,
    ExecutionStatus,
    Rejection,
)
from mission_runtime.execution.physical_command_gateway import (
    PhysicalCommandGateway,
    downlink_topic,
    uplink_topic,
)
from mission_runtime.providers.fakes import InMemoryTransportProvider
from mission_runtime.providers.physical_command_protobuf import (
    PhysicalCommandProtobufSerializerProvider,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry


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
    from mission_runtime.contracts.physical_command import RejectionCode

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
    assert gateway.known_capabilities("robot1")[0].name == "navigate.relative"
    # 정렬의 대가(spec §8-3 P7): HW 와이어 Capability 는 device_id + action
    # 이름 목록뿐이라 required_resources·schema·version 이 건너오지 못한다.
    # 잃었다는 사실을 시험으로 고정해 둔다 — 조용히 사라지면 선택 로직이
    # "자원 조건이 없는 provider"로 오해한다.
    assert providers[0].compatibility.required_runtime_tags == ()
    assert gateway.known_capabilities("robot1")[0].is_fully_declared() is False


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
    from mission_runtime.providers.mqtt import MqttTransportProvider

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


# --- 선언이 레지스트리까지 **읽히는가** (AI-C-18) ---------------------------


def test_a_wire_arrived_declaration_leaves_cancel_support_unknown_not_refused():
    """지금 와이어는 취소 가능 여부를 싣지 못한다(spec §8-3 P7). 그때 답은
    "모른다" 여야 한다 — False 로 접으면 모든 장치가 취소를 거부하는 장치가
    되고, 상위 기능은 보내 보지도 않는다."""
    transport = InMemoryTransportProvider()
    gateway = _gateway(transport)
    gateway.attach("robot1")

    _device_reply(transport, "robot1", Capability(name="stop", cancel_supported=True))

    # 장치는 True 를 선언했지만 와이어가 싣지 못했다. 그 사실이 None 으로 남는다.
    assert gateway.declared_cancel_support("robot1", "stop") is None
    assert gateway.declared_cancel_support("robot1", "never_announced") is None
    missing = gateway.undeclared_declaration_items("robot1")["stop"]
    assert "cancellable" in missing and "idempotent" in missing


def test_a_rich_announcement_reaches_the_registry_and_keeps_every_item():
    """내부 호출 경로(와이어를 거치지 않는)로 온 풍부한 선언은 레지스트리까지
    간다. 이 길이 없으면 선언이 게이트웨이 안에만 남고, 기능을 고르는 쪽은
    취소 가능 여부·멱등성을 선언에서 알 수 없다."""
    registry = CapabilityRegistry()
    gateway = _gateway(registry=registry)
    gateway._on_capability("robot1", {
        "name": "navigate.relative", "version": "1.0",
        "parameter_schema": "schema://p", "result_schema": "schema://r",
        "cancel_supported": False, "required_resources": ["mobility.base"],
        "optional_resources": ["accel.npu"], "idempotent": True,
        "invocation": "asynchronous",
        "basis": {"units": {"distance_m": "m"}, "reference_frame": "device-local",
                  "time_basis": "backend_ntp"},
        "scope_tags": ["zone.a"], "execution_profile_ref": "profile://nav/1",
    })

    declared = gateway.known_capabilities("robot1")[0]
    assert declared.cancel_supported is False and declared.idempotent is True
    assert declared.basis == DeclarationBasis(
        units={"distance_m": "m"}, reference_frame="device-local", time_basis="backend_ntp")
    assert declared.scope_tags == ("zone.a",)
    assert gateway.declared_cancel_support("robot1", "navigate.relative") is False

    reg = registry.available_providers("hardware.action.navigate.relative")[0]
    assert reg.declaration is not None
    assert reg.declaration.cancellable is False
    assert reg.declaration.idempotent is True
    assert reg.declared_items_missing() == ()


def test_an_announcement_without_a_basis_does_not_get_an_empty_one():
    """빈 기준 객체를 만들면 "기준을 선언했다" 가 되어 미선언과 구분되지 않는다."""
    gateway = _gateway()
    gateway._on_capability("robot1", {"name": "stop"})
    assert gateway.known_capabilities("robot1")[0].basis is None


def test_the_registry_splits_declared_support_from_undeclared_support():
    """선택에서 미선언을 거부로 접지도, 충족으로 세지도 않는다 — 둘 다 없는
    선언을 지어내는 것이다(AI-C-18)."""
    registry = CapabilityRegistry()
    gateway = _gateway(registry=registry)
    gateway._on_capability("robot1", {"name": "stop", "cancel_supported": True})
    gateway._on_capability("robot2", {"name": "stop", "cancel_supported": False})
    gateway._on_capability("robot3", {"name": "stop"})

    supports, unknown = registry.providers_declaring(
        "hardware.action.stop", "cancellable")
    assert [r.provider_id for r in supports] == ["robot1"]
    assert [r.provider_id for r in unknown] == ["robot3"]  # robot2 는 어긋난 후보


def test_a_declared_optional_condition_ranks_but_never_excludes_the_provider():
    """선언된 **선택** 실행 조건이 실제 선택까지 닿는지 — 저장만 되고 아무도
    읽지 않으면 그 항목은 선언된 것이 아니다.

    선택 조건의 결손은 자격을 바꾸지 않고 순위만 바꾼다(AI-B-04 "선호 자원이
    없으면 호환 가능한 일반 자원으로 대체", AI-C-05).
    """
    from mission_runtime.contracts.profile import ResourceBudget
    from mission_runtime.selection.selector import CapabilitySelector

    registry = CapabilityRegistry()
    gateway = _gateway(registry=registry)
    gateway._on_capability("robot-npu", {"name": "detect",
                                         "required_resources": ["sensor.camera"],
                                         "optional_resources": ["accel.npu"]})
    gateway._on_capability("robot-plain", {"name": "detect",
                                           "required_resources": ["sensor.camera"]})

    # 선언이 배치 계약까지 옮겨졌는가 — 필수는 자격, 선택은 순위.
    npu_reg = next(r for r in registry.available_providers("hardware.action.detect")
                   if r.provider_id == "robot-npu")
    assert npu_reg.compatibility.required_runtime_tags == ("sensor.camera",)
    assert npu_reg.compatibility.unmet_preferences({"sensor.camera"}) == ("accel.npu",)

    selector = CapabilitySelector(registry)
    without_npu = selector.select("hardware.action.detect",
                                  {"sensor.camera"}, ResourceBudget(10.0, 4096))

    # 선호 자원이 없는 노드에서는 그것을 선언한 쪽이 **뒤로 밀리지만**
    # 배제되지는 않는다 — 등록 순서상 앞에 있었는데도 뒤로 간다.
    assert without_npu.provider.provider_id == "robot-plain"
    assert "robot-npu" in {c.provider_id for c in without_npu.alternatives}
