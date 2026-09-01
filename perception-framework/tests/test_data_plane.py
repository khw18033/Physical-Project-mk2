"""implements: AI-C-14
covers: plane classification, control-data policy, media/observability separation
"""

import pytest

from perception_framework.common.data_plane import (
    DataKind,
    DataPlane,
    DataPlaneViolation,
    assert_routable,
    is_control_data,
    policy_for,
)


def test_every_kind_has_exactly_one_plane():
    for kind in DataKind:
        assert isinstance(policy_for(kind).plane, DataPlane)


@pytest.mark.parametrize(
    "kind,plane",
    [
        (DataKind.PERCEPTION_RESULT, DataPlane.TASK),
        (DataKind.RISK_VERDICT, DataPlane.TASK),
        (DataKind.CONTROL_COMMAND, DataPlane.TASK),
        (DataKind.METRIC, DataPlane.OBSERVABILITY),
        (DataKind.TRACE, DataPlane.OBSERVABILITY),
        (DataKind.VIDEO_FRAME, DataPlane.MEDIA),
    ],
)
def test_plane_assignment(kind, plane):
    assert policy_for(kind).plane is plane


def test_control_data_stays_on_task_plane_but_gets_stricter_policy():
    # 물리 제어 명령은 업무 데이터에 포함하되 전달 보장·순서·결과 회신·책임 추적이
    # 필요한 제어 데이터로 별도 정책을 적용한다 (AI-C-14).
    command = policy_for(DataKind.CONTROL_COMMAND)
    perception = policy_for(DataKind.PERCEPTION_RESULT)

    assert command.plane is perception.plane is DataPlane.TASK
    assert command.delivery_guaranteed and command.ordered
    assert command.result_expected and command.audit_tracked
    assert not perception.delivery_guaranteed
    assert is_control_data(DataKind.CONTROL_COMMAND)
    assert not is_control_data(DataKind.PERCEPTION_RESULT)


def test_video_pixels_cannot_be_routed_over_task_or_observability_planes():
    # 금지 사항: 영상 픽셀을 MQTT/Kafka/OTLP 업무·관측 메시지에 직접 싣지 않는다.
    with pytest.raises(DataPlaneViolation):
        assert_routable(DataKind.VIDEO_FRAME, DataPlane.TASK)
    with pytest.raises(DataPlaneViolation):
        assert_routable(DataKind.VIDEO_SEGMENT, DataPlane.OBSERVABILITY)

    assert_routable(DataKind.VIDEO_FRAME, DataPlane.MEDIA)  # does not raise


def test_device_liveness_and_fatal_signals_are_not_summarizable():
    # 원칙 #14: 장치 생사·치명 오류는 일반 metric 요약에 섞지 않는다.
    assert not policy_for(DataKind.HEARTBEAT).summarizable
    assert not policy_for(DataKind.LOG).summarizable
    assert policy_for(DataKind.METRIC).summarizable
