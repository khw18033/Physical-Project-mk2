"""Scenario 6 — 업무 평면 정상 / 관측 평면 장애 (그 반대도)
Scenario 7 — 같은 시점에 만든 4종 데이터가 각자 다른 경로로 나가는가

tests for: AI-O-04, AI-C-14, AI-C-06, AI-C-08, AI-C-10
question: ⑤ 전송·관측·제어 계층이 서로 섞이지 않는가?
"""

import json

import pytest

from ai_framework.common.data_plane import DataKind, DataPlane, DataPlaneViolation, assert_routable, policy_for
from ai_framework.providers.fakes import (
    InMemoryObservabilityProvider,
    InMemoryTransportProvider,
    SyntheticMediaSourceProvider,
)
from ai_framework.simulation.backend import (
    BackendAvailabilityIntegrator,
    DeviceAvailability,
    ObservabilityHealth,
)
from ai_framework.simulation.terminals import VirtualRobotTerminal

# --- Scenario 6 — plane mismatch ------------------------------------------


def test_s6_metric_loss_alone_never_marks_a_device_unavailable():
    """MQTT 정상 + OTel 죽음 -> AVAILABLE / observability DEGRADED."""
    backend = BackendAvailabilityIntegrator()
    backend.report("virtual_robot_01", task_transport_alive=True, observability_alive=False)

    verdict = backend.verdict("virtual_robot_01")

    assert verdict.availability is DeviceAvailability.AVAILABLE
    assert verdict.observability is ObservabilityHealth.DEGRADED


def test_s6_metric_present_but_task_session_lost_means_unavailable():
    """'metric이 나오니까 살아 있다'가 아니라 '업무 명령을 주고받을 수 있는가'."""
    backend = BackendAvailabilityIntegrator()
    backend.report("virtual_robot_01", task_transport_alive=False, observability_alive=True)

    verdict = backend.verdict("virtual_robot_01")

    assert verdict.availability is DeviceAvailability.UNAVAILABLE
    assert verdict.observability is ObservabilityHealth.HEALTHY


def test_s6_unknown_device_defaults_to_unavailable():
    assert BackendAvailabilityIntegrator().is_available("never-seen") is False


def test_s6_ai_side_only_consumes_the_single_integrated_boolean():
    """AI-C-10: AI는 원신호로 재판정하지 않고 통합 결과만 소비한다."""
    from ai_framework.observability.availability import RemoteFeatureGate

    backend = BackendAvailabilityIntegrator()
    backend.report("edge-B", task_transport_alive=False, observability_alive=True)
    gate = RemoteFeatureGate()

    assert gate.may_select_remote_capability(backend.is_available("edge-B")) is False


# --- Scenario 7 — data path separation ------------------------------------


@pytest.fixture
def wired_robot():
    task_transport = InMemoryTransportProvider()
    observability = InMemoryObservabilityProvider()
    media = SyntheticMediaSourceProvider("cam-1", frames=[b"frame-bytes"] * 3)
    robot = VirtualRobotTerminal(
        "virtual_robot_01", task_transport, observability=observability, media_source=media
    )
    robot.start()
    return robot, task_transport, observability, media


def test_s7_four_data_kinds_produced_together_take_four_different_paths(wired_robot):
    robot, task_transport, observability, _ = wired_robot

    robot.publish_observation("robot_position", [1.0, 2.0])  # 업무 -> MQTT -> Bridge -> Kafka
    robot.report_metric("cpu_usage", 42.0)  # 관측 -> OTLP
    robot.report_event("critical_error", "critical", {"code": "E17"})  # 관측 사건 -> log/alert
    assert robot.send_media_frame() is True  # 미디어 -> 별도 경로

    task_topics = [topic for topic, _, _ in task_transport.published]
    assert task_topics == [robot.task_topic]
    payload = json.loads(task_transport.published[0][1].decode())
    assert payload["name"] == "robot_position"

    assert [name for name, _, _ in observability.metrics] == ["cpu_usage"]
    assert [e.name for e in observability.events] == ["critical_error"]
    assert robot.sent_media_frames == 1


def test_s7_no_video_pixels_ever_appear_on_the_task_transport(wired_robot):
    robot, task_transport, _, _ = wired_robot
    robot.publish_observation("robot_position", [1.0, 2.0])
    robot.send_media_frame()

    published_bytes = b"".join(payload for _, payload, _ in task_transport.published)

    assert b"frame-bytes" not in published_bytes


def test_s7_publishing_a_media_kind_on_the_task_plane_is_refused(wired_robot):
    robot, _, _, _ = wired_robot

    with pytest.raises(DataPlaneViolation):
        robot.publish_observation("camera_frame", "pixels", kind=DataKind.VIDEO_FRAME)


def test_s7_metric_kinds_cannot_be_routed_onto_the_business_plane():
    with pytest.raises(DataPlaneViolation):
        assert_routable(DataKind.METRIC, DataPlane.TASK)


def test_s7_wrong_plane_routing_count_is_zero_across_every_declared_kind():
    """지표: Wrong-plane routing count = 0."""
    violations = 0
    for kind in DataKind:
        expected = policy_for(kind).plane
        for plane in DataPlane:
            try:
                assert_routable(kind, plane)
            except DataPlaneViolation:
                continue
            if plane is not expected:
                violations += 1

    assert violations == 0


def test_s7_media_absence_disables_only_the_media_path(wired_robot):
    robot, task_transport, observability, media = wired_robot
    media.set_available(False)

    assert robot.send_media_frame() is False
    # 나머지 두 평면은 그대로 동작한다 (AI-C-08, AI-C-11).
    robot.publish_observation("robot_position", [3.0, 4.0])
    robot.report_metric("cpu_usage", 10.0)
    assert task_transport.published and observability.metrics
