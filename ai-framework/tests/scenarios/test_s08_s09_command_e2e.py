"""Scenario 8 — 명령 End-to-End 성공 (Backend→Kafka→Bridge→MQTT→말단→회신)
Scenario 9 — 실행 조건 위반으로 인한 거부

tests for: AI-B-03, AI-C-06, AI-C-14, AI-O-01
question: ⑤ 전송·관측·제어 계층이 서로 섞이지 않는가?
핵심: 전송 성공 != 실행 성공. 업무 결과와 기술 trace는 별도로 유지된다 (원칙 #16).
"""

import json
import socket
import time
import uuid

import pytest

from ai_framework.common.data_plane import DataKind
from ai_framework.edge.bridge import EdgeTransportBridge, TopicRoute
from ai_framework.providers.fakes import InMemoryObservabilityProvider, InMemoryTransportProvider
from ai_framework.simulation.terminals import CommandOutcome, VirtualRobotTerminal


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


needs_brokers = pytest.mark.skipif(
    not (_reachable("127.0.0.1", 1883) and _reachable("127.0.0.1", 9092)),
    reason="needs both an MQTT broker and a Kafka broker",
)


def command_payload(command: str, **params) -> bytes:
    return json.dumps(
        {"command_id": f"cmd-{uuid.uuid4().hex[:6]}", "command": command, "params": params}
    ).encode()


def wired_stack(*, battery_pct=80.0):
    """Server transport -> edge bridge -> device transport -> terminal."""
    server = InMemoryTransportProvider()
    device = InMemoryTransportProvider()
    robot = VirtualRobotTerminal("virtual_robot_01", device, battery_pct=battery_pct)
    robot.start()
    bridge = EdgeTransportBridge(
        device,
        server,
        [
            TopicRoute(robot.command_topic, "srv.robot.command", DataKind.CONTROL_COMMAND),
            TopicRoute(robot.result_topic, "srv.robot.result", DataKind.CONTROL_RESULT),
        ],
    )
    bridge.start()
    return server, device, robot, bridge


def test_s8_command_travels_server_to_terminal_and_the_result_comes_back():
    server, _, robot, bridge = wired_stack()
    results = []
    server.subscribe("srv.robot.result", results.append)

    server.publish("srv.robot.command", command_payload("START_TASK", target=[3.0, 4.0]))

    outcomes = [r.outcome for r in robot.command_log]
    assert outcomes == [CommandOutcome.RECEIVED, CommandOutcome.SUCCESS]
    assert robot.state.get("position") == (3.0, 4.0)
    # 결과가 서버까지 되돌아왔다.
    returned = [json.loads(p.decode())["outcome"] for p in results]
    assert "SUCCESS" in returned
    assert bridge.stats.downlink >= 1 and bridge.stats.uplink >= 1


def test_s9_command_is_rejected_on_a_precondition_violation_but_delivery_succeeded():
    server, _, robot, bridge = wired_stack(battery_pct=2.0)
    results = []
    server.subscribe("srv.robot.result", results.append)

    server.publish("srv.robot.command", command_payload("START_TASK", target=[3.0, 4.0]))

    outcomes = [(r.outcome, r.reason) for r in robot.command_log]
    assert outcomes == [
        (CommandOutcome.RECEIVED, None),
        (CommandOutcome.REJECTED, "insufficient_battery"),
    ]
    # 전송은 성공했다 — 전송 실패와 실행 거부는 다른 사건이다 (AI-B-03).
    assert bridge.stats.downlink >= 1
    assert bridge.stats.dropped == {}
    assert robot.state.get("position") == (0.0, 0.0)  # 실행되지 않았다
    assert any(json.loads(p.decode())["reason"] == "insufficient_battery" for p in results)


def test_s9_rejection_reason_is_business_data_not_a_transport_error():
    _, _, robot, _ = wired_stack(battery_pct=2.0)
    robot._on_command(command_payload("START_TASK"))

    rejection = robot.command_log[-1]

    assert rejection.outcome is CommandOutcome.REJECTED
    assert rejection.reason == "insufficient_battery"
    assert isinstance(rejection.reason, str)


def test_s8_business_result_and_technical_trace_stay_separate():
    """업무 결과(SUCCESS)와 기술 지표(구간 지연)를 하나로 합치지 않는다."""
    server, _, robot, _ = wired_stack()
    observability = InMemoryObservabilityProvider()

    started = time.time()
    server.publish("srv.robot.command", command_payload("START_TASK"))
    observability.record_metric("command.server_to_edge_ms", (time.time() - started) * 1000)
    observability.record_metric("command.edge_to_terminal_ms", 4.0)

    business = [r.outcome.value for r in robot.command_log]
    technical = [name for name, _, _ in observability.metrics]

    assert business[-1] == "SUCCESS"
    assert technical == ["command.server_to_edge_ms", "command.edge_to_terminal_ms"]
    # 업무 회신 payload 어디에도 지연 수치가 섞여 있지 않다.
    assert all(not hasattr(r, "latency_ms") for r in robot.command_log)


def test_s8_unknown_command_fails_with_a_reason_rather_than_silently():
    _, _, robot, _ = wired_stack()

    robot._on_command(b"not-json")

    assert robot.command_log[-1].outcome is CommandOutcome.FAILED
    assert robot.command_log[-1].reason == "undecodable_command"


def test_s9_command_to_an_offline_terminal_produces_no_business_result():
    server, _, robot, _ = wired_stack()
    robot.go_offline()

    server.publish("srv.robot.command", command_payload("START_TASK"))

    # 회신 없음 = 실행 결과 미확정. 거부(REJECTED)와 명확히 구분된다.
    assert robot.command_log == []


@needs_brokers
def test_s8_command_e2e_over_real_kafka_and_mqtt():
    """같은 시나리오를 실제 브로커 쌍으로 반복 — 상위 코드는 동일하다."""
    from ai_framework.providers.kafka import KafkaTransportProvider
    from ai_framework.providers.mqtt import MqttTransportProvider

    suffix = uuid.uuid4().hex[:8]
    device = MqttTransportProvider("127.0.0.1", 1883, client_id=f"dev-{suffix}")
    edge_device_side = MqttTransportProvider("127.0.0.1", 1883, client_id=f"edge-dev-{suffix}")
    edge_server_side = KafkaTransportProvider("127.0.0.1:9092", client_id=f"edge-srv-{suffix}")
    server = KafkaTransportProvider(
        "127.0.0.1:9092", client_id=f"srv-{suffix}", group_id=f"g-{suffix}"
    )
    assert device.connect() and edge_device_side.connect() and edge_server_side.connect()
    assert server.connect()

    robot = VirtualRobotTerminal(f"virtual_robot_{suffix}", device)
    robot.start()
    results = []
    try:
        # Create the topic before subscribing: a consumer that joins a
        # not-yet-existing topic has no partition metadata to assign.
        edge_server_side.publish(f"srv.robot.result.{suffix}", b'{"outcome":"WARMUP"}')
        time.sleep(1.0)
        server.subscribe(f"srv.robot.result.{suffix}", results.append)
        time.sleep(2.0)

        bridge = EdgeTransportBridge(
            edge_device_side,
            edge_server_side,
            [
                TopicRoute(robot.command_topic, f"srv.robot.command.{suffix}", DataKind.CONTROL_COMMAND),
                TopicRoute(robot.result_topic, f"srv.robot.result.{suffix}", DataKind.CONTROL_RESULT),
            ],
        )
        bridge.start()
        time.sleep(0.5)

        device.publish(robot.command_topic, command_payload("START_TASK", target=[9.0, 9.0]))

        deadline = time.time() + 25
        while time.time() < deadline and not any(
            json.loads(p.decode()).get("outcome") == "SUCCESS" for p in results
        ):
            time.sleep(0.1)
    finally:
        device.close()
        edge_device_side.close()
        edge_server_side.close()
        server.close()

    assert any(json.loads(p.decode()).get("outcome") == "SUCCESS" for p in results)
