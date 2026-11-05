"""implements: AI-E-02

조사 문서가 §2 에서 남긴 **두 번째 구멍**(외부 파라미터)의 시험이다. 전부 합성 자료다 —
알려진 카메라 자리에서 알려진 앵커로의 방위를 계산하고, 잡음을 섞어 추정기가 그 자리를
되찾는지와 **낸 정확도가 실제 오차와 같은 자리수인지**를 본다.

이 파일이 고정하는 가장 중요한 성질은 추정 정확도의 숫자가 아니라 `accuracy_basis` 의
세 값이 섞이지 않는 것이다: 잰 것 / 선언을 전파한 것 / 모르는 것. 모르는 것이 0 으로
새 나가면 사람이 줄자로 잰 값을 이긴다(AI-C-02).
"""

import math

import numpy as np
import pytest

from mission_runtime.edge.calibration_extrinsics import (
    ACCURACY_BASES,
    DANGER_CIRCLE_MARGIN_FLOOR,
    AnchorBearing,
    AnchorBearingExtrinsics,
    bearing_from_pixel,
)

_TRUE_X, _TRUE_Y, _TRUE_YAW = 2.0, -1.5, 35.0

#: 잘 퍼진 배치. 위험원에서 충분히 떨어져 있다.
_SPREAD = [(0.0, 0.0), (12.0, 1.0), (11.0, 9.0), (-1.0, 7.0), (6.0, -3.0), (3.0, 11.0)]
#: 공선 배치. 문서 §9.4 는 이것을 퇴화로 적었지만 2D 방위 교회법에서는 **잘 조건화된다**.
_COLLINEAR = [(0.0, 0.0), (4.0, 0.0), (8.0, 0.0), (12.0, 0.0)]
#: 카메라가 외접원에 2% 근접한 배치 — **이것이 실제 퇴화다**(위험원).
_DANGER_CIRCLE = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0), (0.0, 8.0)]


def _anchors(layout, *, noise_deg: float = 0.0, seed: int = 0) -> list[AnchorBearing]:
    rng = np.random.default_rng(seed)
    out = []
    for i, (x, y) in enumerate(layout):
        world_azimuth = math.degrees(math.atan2(y - _TRUE_Y, x - _TRUE_X))
        bearing = math.radians(_TRUE_YAW - world_azimuth)
        if noise_deg:
            bearing += math.radians(rng.normal(0.0, noise_deg))
        out.append(AnchorBearing(f"anchor_{i}", x, y, bearing, frame_ref=f"frame_{i}"))
    return out


# -- 픽셀에서 방위로 가는 부호 규약 --------------------------------------------


def test_bearing_sign_convention_right_of_the_axis_is_clockwise():
    assert bearing_from_pixel(320.0, 320.0, 500.0) == 0.0
    assert bearing_from_pixel(420.0, 320.0, 500.0) < 0.0   # 오른쪽 = 시계방향 = 음
    assert bearing_from_pixel(220.0, 320.0, 500.0) > 0.0


def test_bearing_needs_a_positive_focal_length():
    with pytest.raises(ValueError):
        bearing_from_pixel(320.0, 320.0, 0.0)


def test_pixels_feed_the_solver_through_the_declared_convention():
    """내부 파라미터가 없으면 외부 파라미터도 없다 — 이 시험이 그 의존을 고정한다.

    여기 쓰는 앵커들은 전부 **화각 안**에 있다. 광축 뒤의 앵커는 픽셀을 갖지 못하므로
    (tan 이 접힌다) 방위로는 표현되지만 픽셀로는 표현되지 않는다 — 그것이 영상 기반
    외부 파라미터가 요구하는 조건이고, 측량된 앵커가 많아도 **보이는** 앵커가 3개
    미만이면 이 경로는 입력이 없다.
    """
    focal, cx = 500.0, 320.0
    in_view = [(12.0, 1.0), (11.0, 9.0), (14.0, 4.0), (9.0, 10.0), (16.0, 0.0)]
    anchors = []
    for i, (x, y) in enumerate(in_view):
        world_azimuth = math.degrees(math.atan2(y - _TRUE_Y, x - _TRUE_X))
        bearing = math.radians(_TRUE_YAW - world_azimuth)
        assert abs(math.degrees(bearing)) < 32.0  # fx=500, W=640 -> 수평 화각 약 65도
        pixel_u = cx - focal * math.tan(bearing)
        assert 0.0 < pixel_u < 640.0
        anchors.append(
            AnchorBearing(f"a{i}", x, y, bearing_from_pixel(pixel_u, cx, focal))
        )

    estimate = AnchorBearingExtrinsics().estimate(anchors)

    assert estimate.local_x_m == pytest.approx(_TRUE_X, abs=1e-6)
    assert estimate.local_y_m == pytest.approx(_TRUE_Y, abs=1e-6)
    assert estimate.yaw_deg == pytest.approx(_TRUE_YAW, abs=1e-6)


# -- 추정 ---------------------------------------------------------------------


def test_clean_bearings_recover_the_camera_pose_exactly():
    estimate = AnchorBearingExtrinsics().estimate(_anchors(_SPREAD))

    assert estimate.pose[0] == pytest.approx(_TRUE_X, abs=1e-6)
    assert estimate.pose[1] == pytest.approx(_TRUE_Y, abs=1e-6)
    assert estimate.pose[2] == pytest.approx(_TRUE_YAW, abs=1e-6)
    assert estimate.frame_refs == tuple(f"frame_{i}" for i in range(len(_SPREAD)))


@pytest.mark.parametrize("noise_deg,position_tolerance_m", [(0.3, 0.3), (1.0, 0.8)])
def test_noisy_bearings_stay_close_and_do_not_diverge(noise_deg, position_tolerance_m):
    """격자 다중 시작 + LM 이 필요한 이유 — 단일 시작 GN 은 0.3° 에서도 발산했다."""
    estimate = AnchorBearingExtrinsics().estimate(
        _anchors(_SPREAD, noise_deg=noise_deg, seed=1)
    )

    error = math.hypot(estimate.local_x_m - _TRUE_X, estimate.local_y_m - _TRUE_Y)
    assert error < position_tolerance_m
    assert estimate.usable is True


def test_the_same_input_gives_the_same_answer():
    """거부 사유를 재현할 수 있어야 하므로 결정적이어야 한다."""
    anchors = _anchors(_SPREAD, noise_deg=0.5, seed=7)
    first = AnchorBearingExtrinsics().estimate(anchors)
    second = AnchorBearingExtrinsics().estimate(anchors)

    assert first.pose == second.pose
    assert first.position_accuracy_m == second.position_accuracy_m


# -- 정확도의 출처가 셋으로 갈린다 ---------------------------------------------


def test_four_or_more_anchors_with_residual_measure_the_accuracy():
    estimate = AnchorBearingExtrinsics().estimate(
        _anchors(_SPREAD, noise_deg=0.5, seed=2)
    )

    assert estimate.accuracy_basis == "residual_measured"
    assert estimate.accuracy_known is True
    assert estimate.position_accuracy_m is not None and estimate.position_accuracy_m > 0.0
    assert estimate.yaw_accuracy_deg is not None


def test_the_reported_accuracy_tracks_the_real_error_in_order_of_magnitude():
    """공분산이 **쓸모 있는** 값인지 본다 — 오차의 자리수를 맞혀야 한다."""
    ratios = []
    for seed in range(12):
        estimate = AnchorBearingExtrinsics().estimate(
            _anchors(_SPREAD, noise_deg=0.5, seed=100 + seed)
        )
        assert estimate.position_accuracy_m is not None
        error = math.hypot(estimate.local_x_m - _TRUE_X, estimate.local_y_m - _TRUE_Y)
        ratios.append(error / estimate.position_accuracy_m)

    median_ratio = float(np.median(ratios))
    assert 0.1 < median_ratio < 3.0


def test_exactly_three_anchors_cannot_measure_noise_from_residuals():
    """미지수 3개 · 방정식 3개 — 잔차가 구조적으로 0 이라 잴 것이 없다."""
    estimate = AnchorBearingExtrinsics().estimate(_anchors(_SPREAD[:3]))

    assert estimate.accuracy_basis != "residual_measured"


def test_three_anchors_with_a_declared_bearing_sigma_propagate_not_measure():
    estimate = AnchorBearingExtrinsics().estimate(
        _anchors(_SPREAD[:3]), declared_bearing_sigma_rad=math.radians(0.3)
    )

    assert estimate.accuracy_basis == "declared_bearing_noise"
    assert estimate.position_accuracy_m is not None


def test_without_any_noise_source_the_accuracy_is_none_and_never_zero():
    """합성 무잡음 적합은 "오차 0" 이 아니라 **미측정**이다(AI-C-02)."""
    estimate = AnchorBearingExtrinsics().estimate(_anchors(_SPREAD))

    assert estimate.accuracy_basis == "unmeasured"
    assert estimate.position_accuracy_m is None
    assert estimate.yaw_accuracy_deg is None
    assert estimate.accuracy_known is False
    assert "accuracy_unmeasured" in estimate.reasons
    assert "position_accuracy_m" not in estimate.quality


def test_measured_noise_beats_a_declared_one():
    """관측이 선언을 이긴다(AI-S-08) — 선언을 크게 줘도 잰 값을 쓴다."""
    anchors = _anchors(_SPREAD, noise_deg=0.5, seed=4)

    with_declaration = AnchorBearingExtrinsics().estimate(
        anchors, declared_bearing_sigma_rad=math.radians(30.0)
    )
    without = AnchorBearingExtrinsics().estimate(anchors)

    assert with_declaration.accuracy_basis == "residual_measured"
    assert with_declaration.position_accuracy_m == without.position_accuracy_m


def test_every_basis_value_is_in_the_registered_vocabulary():
    cases = [
        AnchorBearingExtrinsics().estimate(_anchors(_SPREAD, noise_deg=0.5, seed=5)),
        AnchorBearingExtrinsics().estimate(
            _anchors(_SPREAD[:3]), declared_bearing_sigma_rad=math.radians(0.2)),
        AnchorBearingExtrinsics().estimate(_anchors(_SPREAD)),
        AnchorBearingExtrinsics().estimate(_anchors(_SPREAD[:2])),
    ]

    assert {case.accuracy_basis for case in cases} <= set(ACCURACY_BASES)


# -- 퇴화 ---------------------------------------------------------------------


def test_fewer_than_three_anchors_is_refused_without_inventing_a_pose():
    estimate = AnchorBearingExtrinsics().estimate(_anchors(_SPREAD[:2]))

    assert estimate.usable is False
    assert "too_few_anchors" in estimate.reasons
    assert math.isnan(estimate.local_x_m)
    assert estimate.position_accuracy_m is None


def test_duplicate_anchor_ids_are_refused_rather_than_double_counted():
    anchors = _anchors(_SPREAD[:4])
    anchors[1] = AnchorBearing(
        anchors[0].anchor_id, anchors[1].local_x_m, anchors[1].local_y_m,
        anchors[1].bearing_rad,
    )

    estimate = AnchorBearingExtrinsics().estimate(anchors)

    assert "duplicate_anchor_id" in estimate.reasons
    assert estimate.usable is False


def test_the_danger_circle_not_collinearity_is_the_degenerate_case():
    """문서 §9.4 의 서술과 **다른 결론**이다 — 실측이 그 서술을 뒤집었다.

    공선 앵커는 외접원이 직선이라 카메라가 그 직선 위에 없으면 오히려 잘 조건화된다.
    실제 퇴화는 카메라가 앵커 셋의 외접원 위에 있을 때이고, 그것은 고전 측량에서
    `위험원` 으로 불린다. 그래서 공선 검사가 아니라 위험원 근접도를 쓴다.
    """
    collinear = AnchorBearingExtrinsics().estimate(
        _anchors(_COLLINEAR, noise_deg=0.3, seed=6)
    )
    on_circle = AnchorBearingExtrinsics().estimate(
        _anchors(_DANGER_CIRCLE, noise_deg=0.3, seed=6)
    )

    assert collinear.danger_circle_margin == pytest.approx(1.0)
    assert collinear.usable is True
    assert math.hypot(collinear.local_x_m - _TRUE_X, collinear.local_y_m - _TRUE_Y) < 0.1

    assert on_circle.danger_circle_margin is not None
    assert on_circle.danger_circle_margin < DANGER_CIRCLE_MARGIN_FLOOR
    assert "anchor_geometry_degenerate" in on_circle.reasons
    assert on_circle.usable is False


def test_a_degenerate_geometry_still_reports_its_estimate_for_the_operator():
    """거부해도 값은 남는다 — 왜 거부됐는지 보려면 값이 있어야 한다."""
    estimate = AnchorBearingExtrinsics().estimate(
        _anchors(_DANGER_CIRCLE, noise_deg=0.3, seed=6)
    )

    assert math.isfinite(estimate.local_x_m)
    assert estimate.usable is False
    assert estimate.quality["danger_circle_margin"] < DANGER_CIRCLE_MARGIN_FLOOR


def test_bearings_that_no_pose_explains_are_refused():
    anchors = _anchors(_SPREAD)
    anchors[2] = AnchorBearing(
        anchors[2].anchor_id, anchors[2].local_x_m, anchors[2].local_y_m,
        anchors[2].bearing_rad + math.radians(50.0),
    )

    estimate = AnchorBearingExtrinsics().estimate(anchors)

    assert "bearing_residual_exceeded" in estimate.reasons
    assert estimate.usable is False


def test_the_output_is_zone_local_and_says_so():
    """AI-C-02: 로컬 값과 전역 값을 같은 칸에 담지 않는다."""
    estimate = AnchorBearingExtrinsics().estimate(_anchors(_SPREAD))
    pose = estimate.pose

    assert len(pose) == 3  # (x_m, y_m, yaw_deg) — 구역 로컬. 전역 칸이 없다.
    assert not hasattr(estimate, "global_x_m")
    assert not hasattr(estimate, "latitude")
