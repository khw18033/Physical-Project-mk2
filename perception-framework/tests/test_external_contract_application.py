"""implements: AI-B-01, AI-B-03, AI-C-01, AI-C-06, AI-C-07"""

import json
import sqlite3
import subprocess
import threading
import time

from jsonschema import Draft202012Validator

from perception_framework.contracts.physical_command import (
    CancelCommandRequest, Capability, Command, ExecutionStatus,
)
from perception_framework.edge.bridge import EdgeTransportBridge, TopicRoute
from perception_framework.execution.command_execution import CommandExecutionSupervisor
from perception_framework.execution.hardware_adapter import HardwareAdapterHandler
from perception_framework.providers.fakes import InMemoryTransportProvider
from perception_framework.providers.physical_command_protobuf import PhysicalCommandProtobufSerializerProvider
from perception_framework.providers.mqtt import MqttTransportProvider
from perception_framework.providers.kafka import KafkaTransportProvider
from perception_framework.providers.k3s import K3sControlProvider
from perception_framework.common.data_plane import DataKind


def test_physical_command_json_schema_accepts_contract(tmp_path):
    schema_path = __import__("pathlib").Path(__file__).parents[1] / "contracts/ai/physical-command.schema.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator(schema).validate({"message_type": "command", "payload": {
        "command_id": "c1", "target": "r1", "action": "stop", "parameters": {}}})


def test_protobuf_binding_round_trips_typed_command():
    serializer = PhysicalCommandProtobufSerializerProvider()
    command = Command("c1", "robot-1", "stop", {"hard": True}, "trace-1", 2000000000.0)
    decoded = serializer.decode(serializer.encode(command))
    assert decoded["message_type"] == "command"
    assert decoded["payload"]["command_id"] == "c1"
    assert decoded["payload"]["parameters"] == {"hard": True}


def test_async_cancel_is_real_and_state_survives_restart(tmp_path):
    started = threading.Event()
    release = threading.Event()

    def handler(_command):
        started.set()
        release.wait(2)
        return True, {"late": True}, None

    state = tmp_path / "commands.sqlite"
    supervisor = CommandExecutionSupervisor(handler, state_path=state)
    supervisor.submit_async(Command("c1", "robot", "move"))
    assert started.wait(1)
    assert supervisor.cancel(CancelCommandRequest("c1")).accepted
    release.set()
    assert supervisor.wait("c1", 2).status is ExecutionStatus.CANCELED
    supervisor.close()

    restored = CommandExecutionSupervisor(state_path=state)
    assert restored.get_result("c1").status is ExecutionStatus.CANCELED
    duplicate = restored.submit(Command("c1", "robot", "move"))
    assert duplicate.accepted
    assert restored.get_result("c1").status is ExecutionStatus.CANCELED
    restored.close()


def test_restart_aborts_orphaned_nonterminal_execution(tmp_path):
    state = tmp_path / "commands.sqlite"
    supervisor = CommandExecutionSupervisor(state_path=state)
    supervisor.submit(Command("c1", "robot", "move"))
    supervisor.close()
    db = sqlite3.connect(state)
    db.execute("UPDATE command_state SET status = 'EXECUTING', result = NULL WHERE command_id = 'c1'")
    db.commit()
    db.close()

    restored = CommandExecutionSupervisor(state_path=state)
    result = restored.get_result("c1")
    assert result.status is ExecutionStatus.ABORTED
    assert result.failure.code == "RECOVERED_AFTER_RESTART"
    restored.close()


def test_hardware_provider_boundary_checks_capability():
    class Provider:
        def capabilities(self):
            return (Capability("stop", "1", "schema:p", "schema:r", True),)
        def execute(self, command):
            return True, {"target": command.target}, None
        def cancel(self, command_id):
            return True

    handler = HardwareAdapterHandler(Provider())
    assert handler(Command("c1", "r1", "stop"))[0] is True
    assert handler(Command("c2", "r1", "fly"))[0] is False


def test_capability_maps_required_resources_to_compatibility_profile():
    profile = Capability("move", "1", "schema:p", "schema:r", required_resources=("arm64",)).compatibility_profile()
    assert profile.required_runtime_tags == ("arm64",)


def test_bridge_persists_and_replays_control_when_link_recovers(tmp_path):
    device = InMemoryTransportProvider(connected=False)
    server = InMemoryTransportProvider()
    bridge = EdgeTransportBridge(device, server,
        [TopicRoute("edge/control", "server/control", DataKind.CONTROL_COMMAND)],
        outbox_path=str(tmp_path / "outbox.sqlite"))
    bridge.start()
    bridge._downlink_handler(bridge._routes[0])(b"stop")
    assert bridge.pending_count() == 1
    assert bridge.stats.queued == 1
    assert bridge.stats.dropped == {}
    device.set_connected(True)
    assert bridge.flush_pending() == 1
    assert device.published[-1][1] == b"stop"
    bridge.close()


def test_mqtt5_command_sets_request_response_and_expiry_properties():
    class Client:
        def publish(self, topic, payload, **kwargs):
            self.call = (topic, payload, kwargs)

    provider = MqttTransportProvider.__new__(MqttTransportProvider)
    provider._client = Client()
    provider.publish_command("command", b"x", response_topic="result/c1",
        correlation_data=b"c1", message_expiry_interval=5)
    properties = provider._client.call[2]["properties"]
    assert properties.ResponseTopic == "result/c1"
    assert properties.CorrelationData == b"c1"
    assert properties.MessageExpiryInterval == 5


def test_kafka_security_settings_are_explicit_configuration():
    provider = KafkaTransportProvider("broker:9093", security_protocol="SASL_SSL",
        sasl_mechanism="SCRAM-SHA-512", sasl_username="robot", sasl_password="secret")
    assert provider._security["security_protocol"] == "SASL_SSL"
    assert provider._security["sasl_mechanism"] == "SCRAM-SHA-512"


def test_k3s_requires_digest_before_contacting_cluster():
    provider = K3sControlProvider(kubectl="does-not-exist")
    result = provider.request("start", "worker", {
        "image": "registry.example/worker:latest", "require_image_digest": True})
    assert not result.accepted
    assert result.rejection_reason == "image_digest_required"


def test_k3s_renders_security_and_identity_into_workload():
    class Provider(K3sControlProvider):
        def __init__(self):
            super().__init__()
            self.applied = None

        def _run(self, args, timeout=None, stdin=None):
            if args[:2] == ["get", "deployment"]:
                return subprocess.CompletedProcess(args, 1, "", "not found")
            if "--dry-run=client" in args:
                manifest = {"spec": {"template": {"spec": {"containers": [{"name": "worker"}]}}}}
                return subprocess.CompletedProcess(args, 0, json.dumps(manifest), "")
            if args[0] == "apply":
                self.applied = json.loads(stdin)
                return subprocess.CompletedProcess(args, 0, "", "")
            raise AssertionError(args)

    provider = Provider()
    result = provider.request("start", "worker", {
        "image": "registry.example/worker@sha256:" + "a" * 64,
        "require_image_digest": True,
        "service_account": "worker-runtime",
        "image_pull_secrets": ["registry-auth"],
        "security_context": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
        },
    })
    assert result.accepted
    pod = provider.applied["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "worker-runtime"
    assert pod["imagePullSecrets"] == [{"name": "registry-auth"}]
    assert pod["containers"][0]["securityContext"]["runAsNonRoot"] is True
