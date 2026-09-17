"""implements: AI-E-04, AI-C-02, AI-C-19, AI-C-20

The pure geometry/bearing functions are tested without any ML model —
`UniDepthCameraProvider` (the only part that needs the real UniDepth model)
is exercised only for its `is_available()` degrade path (AI-C-11: optional
capability, absence is not an error).
"""
import math

import pytest

from perception_framework.contracts.physical_command import Command
from perception_framework.edge.self_localization import (
    ApparentSizeObservation,
    BearingObservation,
    LandmarkGeometry,
    UniDepthCameraProvider,
    backtrace_robot_position_from_target,
    bearing_offset_deg,
    build_navigation_command,
    circular_mean_deg,
    estimate_distance_from_apparent_size,
    estimate_robot_position,
    plan_navigation,
    plan_navigation_target_only,
    refined_target_bearing_deg,
    turn_signed_deg,
)

FX, CX = 120.1980, 161.1234
FRAME_W = 320.0


def test_box_centered_on_principal_point_has_zero_offset():
    box = (CX - 10, 0, CX + 10, 20)

    assert bearing_offset_deg(box, FRAME_W, FX, CX) == pytest.approx(0.0, abs=1e-9)


def test_box_right_of_center_gives_positive_offset():
    box = (CX + 10, 0, CX + 30, 20)  # entirely to the right of the principal point

    offset = bearing_offset_deg(box, FRAME_W, FX, CX)

    assert offset > 0.0


def test_box_filling_most_of_the_frame_is_untrustworthy():
    # A box occupying >60% of the frame width -- its center is not a reliable
    # proxy for bearing (e.g. a landmark photographed at very close range).
    box = (0.0, 0.0, 0.9 * FRAME_W, 50.0)

    assert bearing_offset_deg(box, FRAME_W, FX, CX) is None


def test_circular_mean_handles_wrap_around_the_0_360_boundary():
    # 350 and 10 degrees are 20 degrees apart across the boundary, not 340.
    mean = circular_mean_deg([350.0, 10.0])

    assert mean == pytest.approx(0.0, abs=1e-6) or mean == pytest.approx(360.0, abs=1e-6)


def test_refined_bearing_skips_unreliable_observations_but_keeps_the_reliable_one():
    observations = [
        BearingObservation(90.0, (0.0, 0.0, 0.9 * FRAME_W, 50.0), FRAME_W),  # too large, skipped
        BearingObservation(270.0, (CX - 10, 0, CX + 10, 20), FRAME_W),       # centered, offset 0
    ]

    result = refined_target_bearing_deg(observations, FX, CX)

    assert result is not None
    assert result.refined_target_rotation_deg == pytest.approx(270.0, abs=1e-6)
    assert result.per_observation[0][1] is None
    assert result.spread_deg is None  # only one usable observation


def test_refined_bearing_returns_none_when_every_observation_is_unreliable():
    observations = [BearingObservation(90.0, (0.0, 0.0, 0.9 * FRAME_W, 50.0), FRAME_W)]

    assert refined_target_bearing_deg(observations, FX, CX) is None


def test_regression_two_45_degree_frames_do_not_collapse_to_a_45_multiple_turn():
    """2026-09-16 실측으로 발견된 회귀 방지 테스트. 8방향 스캔은 45도 간격
    뿐이라 "탐지=화면 정중앙" 가정을 쓰면 회전 지시각이 항상 45의 배수로만
    나오는 구조적 결함이 있었다(사용자 지적: "60~70도 정도로 나와야 함").
    이 두 관측(270도 프레임에서 중앙보다 오른쪽, 315도 프레임에서 왼쪽)은
    실제 시연 데이터에서 가져온 값이며, 보정 후 회전각이 45의 배수가 아닌
    연속값(약 74도)으로 나와야 한다."""
    observations = [
        BearingObservation(270.0, (172.5, 0, 192.5, 10), FRAME_W),
        BearingObservation(315.0, (98.1, 0, 118.1, 10), FRAME_W),
    ]

    result = refined_target_bearing_deg(observations, FX, CX)
    turn = turn_signed_deg(result.refined_target_rotation_deg, current_heading_deg=0.0)

    assert result.refined_target_rotation_deg not in (270.0, 315.0, 0.0, 45.0, 90.0, 135.0, 180.0, 225.0)
    assert 60.0 < abs(turn) < 90.0, f"turn={turn} degrees should not collapse back to a 45-multiple"
    assert result.spread_deg is not None and result.spread_deg > 0.0


@pytest.mark.parametrize(
    "target_deg,current_deg,expected",
    [
        (90.0, 0.0, 90.0),
        (0.0, 90.0, -90.0),
        (350.0, 10.0, -20.0),   # shortest path across the 0/360 boundary
        (10.0, 350.0, 20.0),
    ],
)
def test_turn_signed_deg_takes_the_shortest_path(target_deg, current_deg, expected):
    assert turn_signed_deg(target_deg, current_deg) == pytest.approx(expected)


def test_estimate_robot_position_places_robot_beyond_the_landmark_surface():
    # A square landmark centered at the origin, target straight ahead on +x.
    landmark = LandmarkGeometry(center_cm=(0.0, 0.0), half_width_cm=10.0, half_height_cm=10.0)
    target = (1000.0, 0.0)

    robot = estimate_robot_position(landmark, target, landmark_distance_cm=30.0)

    # Surface exit at x=10 (half_width), plus 30cm further along +x.
    assert robot == pytest.approx((40.0, 0.0))


def test_plan_navigation_forward_distance_already_subtracts_standoff():
    plan = plan_navigation(
        robot_position_cm=(0.0, 0.0),
        target_position_cm=(100.0, 0.0),
        target_bearing_deg=0.0,
        current_heading_deg=0.0,
        standoff_cm=20.0,
    )

    assert plan.distance_to_target_cm == pytest.approx(100.0)
    assert plan.forward_distance_m == pytest.approx(0.80)  # (100-20)cm -> 0.80m
    assert plan.turn_deg == pytest.approx(0.0)


def test_build_navigation_command_matches_the_robot_team_field_convention():
    """이관메모_260914.md §5-4에서 로봇 팀과 이미 합의된 필드 모양 —
    turn.deg/move_forward.distance_m, standoff는 distance_m에 이미 반영됨."""
    plan = plan_navigation(
        robot_position_cm=(0.0, 0.0),
        target_position_cm=(0.0, -100.0),
        target_bearing_deg=270.0,
        current_heading_deg=0.0,
        standoff_cm=80.0,
    )

    command = build_navigation_command(plan, command_id="cmd-1", target="go1-001")

    assert isinstance(command, Command)
    assert command.action == "navigate_to_standoff"
    assert command.parameters["turn"]["deg"] == pytest.approx(plan.turn_deg)
    assert command.parameters["move_forward"]["distance_m"] == pytest.approx(plan.forward_distance_m)
    assert command.parameters["standoff_cm"] == 80.0


def test_apparent_size_distance_matches_the_calibration_source_measurement():
    """2026-09-16 실제 로봇 리허설 반영 회귀 테스트: K값은 단상 기반 위치추정이
    성공한 데이터셋 8장 판(로봇-문 실측 715.4cm)에서 역산됐다 -- 그 원본
    측정치를 다시 넣으면 같은 거리가 나와야 한다."""
    observations = [
        ApparentSizeObservation((100.0, 90.0, 120.17, 144.06), frame_width_px=237.0, frame_height_px=241.0),
        ApparentSizeObservation((100.0, 90.0, 119.90, 128.6), frame_width_px=237.0, frame_height_px=241.0),
    ]

    distance = estimate_distance_from_apparent_size(observations)

    assert distance == pytest.approx(715.4, rel=0.02)


def test_apparent_size_distance_discards_edge_clipped_dimensions():
    # width touches the left edge (x1=0) -- must be discarded, leaving only height.
    observations = [ApparentSizeObservation((0.0, 10.0, 20.0, 64.06), frame_width_px=237.0, frame_height_px=241.0)]

    distance = estimate_distance_from_apparent_size(observations)

    from perception_framework.edge.self_localization import DOOR_SIZE_K_HEIGHT

    assert distance == pytest.approx(DOOR_SIZE_K_HEIGHT / 54.06, rel=1e-6)


def test_apparent_size_distance_returns_none_when_every_estimate_is_implausible():
    # A tiny box implies an absurd distance, outside PLAUSIBLE_DOOR_DISTANCE_CM.
    observations = [ApparentSizeObservation((10.0, 10.0, 10.5, 10.5), frame_width_px=237.0, frame_height_px=241.0)]

    assert estimate_distance_from_apparent_size(observations) is None


def test_plan_navigation_target_only_needs_no_robot_position():
    """이관메모 B단계: 단상이 안 보여도 목표 자신의 관측만으로 회전각+거리가
    나와야 한다."""
    plan = plan_navigation_target_only(
        distance_to_target_cm=715.4,
        target_bearing_deg=285.4,
        current_heading_deg=0.0,
        standoff_cm=100.0,
    )

    assert plan.turn_deg == pytest.approx(turn_signed_deg(285.4, 0.0))
    assert plan.forward_distance_m == pytest.approx((715.4 - 100.0) / 100.0)


def test_backtrace_position_is_consistent_with_the_forward_bearing():
    """역산된 "가정 위치"에서 다시 목표를 바라보면 같은 절대 방위각이 나와야
    한다(자기모순이 없는 역산인지 확인) -- 이 위치 자체는 실측이 아니라는
    점은 함수 docstring에 명시돼 있다."""
    door_position_cm = (922.8, 327.8)
    robot_guess = backtrace_robot_position_from_target(
        door_position_cm, refined_target_rotation_deg=285.4, distance_cm=715.4, assumed_current_heading_deg=0.0,
    )

    dx = door_position_cm[0] - robot_guess[0]
    dy = door_position_cm[1] - robot_guess[1]
    recovered_bearing = math.degrees(math.atan2(dy, dx)) % 360.0

    assert recovered_bearing == pytest.approx(285.4, abs=1e-6)
    assert math.hypot(dx, dy) == pytest.approx(715.4, abs=1e-6)


def test_unidepth_provider_reports_unavailable_without_raising_when_not_installed():
    provider = UniDepthCameraProvider()

    # This environment may or may not have `unidepth` installed; either way
    # the check itself must never raise (AI-C-11 degrade, not crash).
    assert provider.is_available() in (True, False)
