"""implements: AI-E-02

조사 문서 §6 — 파노라마에 pinhole 을 씌우지 않는다.

이 파일이 고정하는 두 성질.
1. 360 소스는 pinhole 보정의 대상이 **아니고**, 그 사실이 `ApplicabilityScope.projection`
   으로 막혀 조용히 사라지지 않는다.
2. 유도된 원근 뷰의 내부 파라미터는 **구성값이고 측정값이 아니다.** 그 뷰가 내는
   픽셀↔광선 대응이 기존 선형해 자리(`anycalib_style_recovery`)에 실제로 연결된다.
"""

import math

import numpy as np
import pytest

from mission_runtime.edge.anycalib_style_recovery import RayFieldIntrinsicsRecovery
from mission_runtime.edge.calibration_profile import ApplicabilityScope
from mission_runtime.edge.equirect_views import (
    EQUIRECT_REFUSAL_REASONS,
    PanoramaSource,
    PerspectiveViewSpec,
    derived_view_scope,
    perspective_sweep_plan,
    refuse_pinhole_calibration,
    render_perspective_view,
    view_ray_correspondences,
)

_PANO = PanoramaSource("sensor.camera.360", 4096, 2048)


# -- 거절 ---------------------------------------------------------------------


def test_a_stitched_panorama_is_refused_for_pinhole_calibration_with_reasons():
    reasons = refuse_pinhole_calibration(_PANO)

    assert "equirectangular_has_no_pinhole_intrinsics" in reasons
    assert "per_lens_frames_unavailable" in reasons
    assert "stitching_accuracy_unmeasured" in reasons
    assert set(reasons) <= set(EQUIRECT_REFUSAL_REASONS)


def test_an_ordinary_pinhole_source_passes_the_same_guard():
    """호출자가 "360 이면" 하는 분기를 쓰지 않게 해야 한다(원칙 #3)."""
    ordinary = PanoramaSource("cam_a", 640, 480, projection="pinhole")

    assert refuse_pinhole_calibration(ordinary) == ()


def test_per_lens_access_removes_only_that_reason_not_the_first_one():
    """렌즈별 원본이 열려도 **등장방형 자체**에는 여전히 pinhole 이 없다."""
    reasons = refuse_pinhole_calibration(
        PanoramaSource("cam360", 4096, 2048, per_lens_access=True,
                       stitching_accuracy_deg=0.2)
    )

    assert reasons == ("equirectangular_has_no_pinhole_intrinsics",)


def test_unmeasured_stitching_accuracy_is_none_and_not_zero():
    assert _PANO.stitching_accuracy_deg is None


def test_a_pinhole_profile_scope_does_not_cover_an_equirectangular_source():
    """§6 이 "`ApplicabilityScope` 가 카메라를 식별해야 한다" 고 남긴 자리."""
    pinhole_profile_scope = ApplicabilityScope("sensor.camera.360", (4096, 2048))
    live_source_scope = ApplicabilityScope(
        "sensor.camera.360", (4096, 2048), projection="equirectangular"
    )

    assert pinhole_profile_scope.covers(live_source_scope) is False
    assert pinhole_profile_scope.as_dict()["projection"] == "pinhole"


def test_a_panorama_needs_a_positive_size():
    with pytest.raises(ValueError):
        PanoramaSource("cam360", 0, 2048)


def test_the_angular_grid_of_the_panorama_is_reported():
    assert _PANO.horizontal_degrees_per_px == pytest.approx(360.0 / 4096)
    assert _PANO.vertical_degrees_per_px == pytest.approx(180.0 / 2048)


# -- 유도 계획 ----------------------------------------------------------------


def test_the_default_sweep_plan_matches_the_demo_tool_24_views_of_90_degrees():
    plan = perspective_sweep_plan()

    assert len(plan) == 24
    assert [spec.yaw_deg for spec in plan[:3]] == [0.0, 15.0, 30.0]
    assert all(spec.hfov_deg == 90.0 for spec in plan)
    assert plan[5].view_id == "e2p_05"


def test_the_step_is_much_smaller_than_the_fov_so_adjacent_views_overlap():
    """겹치지 않으면 뷰 사이 특징 대응이 없고 하류 SfM 이 입력을 갖지 못한다."""
    plan = perspective_sweep_plan(hfov_deg=90.0, step_deg=15.0)
    step = plan[1].yaw_deg - plan[0].yaw_deg

    assert step < plan[0].hfov_deg / 2.0


def test_the_plan_is_data_so_a_different_sweep_is_not_a_code_change():
    plan = perspective_sweep_plan(hfov_deg=60.0, step_deg=30.0, width_px=320,
                                  height_px=240, view_id_prefix="narrow")

    assert len(plan) == 12
    assert plan[0].view_id == "narrow_00"
    assert plan[0].width_px == 320


def test_a_nonpositive_step_is_refused():
    with pytest.raises(ValueError):
        perspective_sweep_plan(step_deg=0.0)


def test_an_impossible_fov_is_refused_at_the_spec():
    with pytest.raises(ValueError):
        PerspectiveViewSpec(0.0, 0.0, 180.0, 640, 640)
    with pytest.raises(ValueError):
        PerspectiveViewSpec(0.0, 0.0, 90.0, 0, 640)


# -- 유도된 내부 파라미터는 구성값이다 ----------------------------------------


def test_the_derived_intrinsics_follow_from_the_chosen_fov_by_definition():
    spec = PerspectiveViewSpec(0.0, 0.0, 90.0, 640, 480)

    assert spec.fx == pytest.approx(320.0)      # (W/2) / tan(45도)
    assert spec.cx == pytest.approx(320.0)
    assert spec.cy == pytest.approx(240.0)
    assert spec.intrinsics_basis == "by_construction"
    assert spec.reference_frame == "panorama_body"


def test_a_narrower_view_gets_a_longer_focal_length():
    wide = PerspectiveViewSpec(0.0, 0.0, 120.0, 640, 640)
    narrow = PerspectiveViewSpec(0.0, 0.0, 40.0, 640, 640)

    assert narrow.fx > wide.fx
    assert narrow.vertical_fov_deg < wide.vertical_fov_deg


def test_recovering_the_derived_intrinsics_from_its_own_rays_is_self_confirmation():
    """**측정이 아니다** — 우리가 고른 값을 되찾는다. 확인하는 것은 자리가 연결되는지다."""
    spec = perspective_sweep_plan()[3]

    estimate = RayFieldIntrinsicsRecovery().estimate(
        view_ray_correspondences(spec, samples=5)
    )

    assert estimate.fx == pytest.approx(spec.fx, rel=1e-9)
    assert estimate.fy == pytest.approx(spec.fy, rel=1e-9)
    assert estimate.cx == pytest.approx(spec.cx, rel=1e-9)
    assert estimate.residual_rms < 1e-9
    assert estimate.stable is True


def test_ray_correspondences_need_at_least_two_samples_per_axis():
    with pytest.raises(ValueError):
        view_ray_correspondences(PerspectiveViewSpec(0.0, 0.0, 90.0, 64, 64), samples=1)


def test_the_view_rays_are_in_the_view_frame_and_the_panorama_frame_separately():
    """로컬 값과 다른 프레임의 값을 같은 칸에 담지 않는다(AI-C-02)."""
    spec = PerspectiveViewSpec(90.0, 0.0, 90.0, 640, 640)

    view_ray = spec.ray_in_view_frame(spec.cx, spec.cy)
    pano_ray = spec.ray_in_panorama_frame(spec.cx, spec.cy)

    assert view_ray == pytest.approx((0.0, 0.0, 1.0))
    # yaw 90도: 뷰의 +z 가 파노라마의 +x 를 가리킨다.
    assert pano_ray == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_pitching_the_view_moves_the_ray_out_of_the_horizontal_plane():
    level = PerspectiveViewSpec(0.0, 0.0, 90.0, 640, 640)
    pitched = PerspectiveViewSpec(0.0, 30.0, 90.0, 640, 640)

    assert level.ray_in_panorama_frame(level.cx, level.cy)[1] == pytest.approx(0.0)
    # +pitch 는 **위**를 본다. 카메라 프레임의 +y 가 아래이므로 위를 보는 광선의 y 는
    # 음이고, 등장방형 위도는 `asin(-y)` 라 +30도(지평선 위)로 샘플링된다.
    assert pitched.ray_in_panorama_frame(pitched.cx, pitched.cy)[1] == pytest.approx(
        -math.sin(math.radians(30.0)), abs=1e-9
    )


# -- 렌더가 같은 규약을 쓴다 ---------------------------------------------------


def _longitude_ramp(height: int = 256, width: int = 512) -> np.ndarray:
    """가로가 경도를 그대로 담은 합성 파노라마. 픽셀값 = 가로 좌표(mod 256)."""
    return (np.indices((height, width))[1] % 256).astype(np.uint8)


def test_rendering_maps_the_view_centre_to_the_declared_longitude():
    pano = _longitude_ramp()
    view = render_perspective_view(pano, PerspectiveViewSpec(0.0, 0.0, 90.0, 64, 64))

    # yaw 0 -> 경도 0 -> 파노라마 가로 256 -> uint8 로 0
    assert int(view[32, 32]) == 0
    # 좌/우 끝은 -45도/+45도 -> 가로 192 / 320
    assert int(view[32, 0]) == 192
    assert int(view[32, 63]) == pytest.approx(63, abs=1)


def test_rendering_a_yawed_view_shifts_the_sampled_longitude():
    pano = _longitude_ramp()
    view = render_perspective_view(pano, PerspectiveViewSpec(90.0, 0.0, 90.0, 64, 64))

    # yaw 90도 -> 경도 +90도 -> 가로 384 -> uint8 로 128
    assert int(view[32, 32]) == 128


def test_rendering_wraps_across_the_seam_instead_of_producing_a_black_band():
    pano = _longitude_ramp()

    view = render_perspective_view(pano, PerspectiveViewSpec(180.0, 0.0, 90.0, 64, 64))

    assert view.shape == (64, 64)
    assert int(view.min()) > 0 or int(view.max()) > 0  # 전부 0(검정)이 아니다


def test_rendering_preserves_colour_channels_and_the_requested_size():
    pano = np.dstack([_longitude_ramp()] * 3)

    view = render_perspective_view(pano, PerspectiveViewSpec(45.0, 10.0, 80.0, 96, 72))

    assert view.shape == (72, 96, 3)


def test_rendering_refuses_something_that_is_not_an_image():
    with pytest.raises(ValueError):
        render_perspective_view(np.zeros(5), PerspectiveViewSpec(0.0, 0.0, 90.0, 8, 8))


# -- 유도된 뷰의 적용 범위 -----------------------------------------------------


def test_each_derived_view_is_its_own_input_condition():
    """같은 360 소스에서 뽑은 두 뷰는 서로 다른 조건이다(문서 §4.4 의 crop 민감성)."""
    plan = perspective_sweep_plan()
    first = derived_view_scope(_PANO, plan[0])
    second = derived_view_scope(_PANO, plan[1])

    assert first.projection == "pinhole"
    assert first.zoom_token == "e2p:e2p_00"
    assert first.covers(second) is False
    assert first.image_size == (plan[0].width_px, plan[0].height_px)


def test_a_view_without_an_id_still_gets_a_distinguishing_token():
    scope = derived_view_scope(_PANO, PerspectiveViewSpec(37.5, -10.0, 70.0, 320, 240))

    assert scope.zoom_token.startswith("e2p:yaw37.5")
    assert "pitch-10" in scope.zoom_token
