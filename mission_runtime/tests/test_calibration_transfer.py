"""implements: AI-E-02

조사 문서 §7.1 — "입력 조건이 바뀌었다" 는 **한 가지 사건이 아니라 두 가지**다.
이 파일이 고정하는 중심 성질은 하나다: **해상도만 보고는 resize 인지 crop 인지 알 수
없으므로, 선언이 없으면 환산하지 않는다.** 틀린 환산보다 "적용 불가" 가 안전하다.
"""

import math

import numpy as np
import pytest

from mission_runtime.edge.calibration import CalibrationEstimate
from mission_runtime.edge.calibration_profile import (
    ApplicabilityScope,
    CalibrationProfileStore,
)
from mission_runtime.edge.calibration_transfer import (
    INPUT_CHANGE_VERDICTS,
    InputTransform,
    classify_input_change,
    transfer_profile,
)

_K = np.array([[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]])
_DIST = np.array([0.05, -0.03, 0.0, 0.0, 0.0])


def _profile(scope: ApplicabilityScope | None = None, *, rms: float = 0.4):
    store = CalibrationProfileStore(camera_id="cam_a")
    return store.submit(
        CalibrationEstimate(_K.copy(), _DIST.copy(), rms, True),
        validated=True,
        validated_by=("reprojection_rms_within_budget", "fov_matches_declared_sensor"),
        applicability=ApplicabilityScope("cam_a", (640, 480)) if scope is None else scope,
        method_id="planar_target",
        quality={"reprojection_rms_px": rms, "view_count": 12.0},
        extrinsic=(2.0, -1.5, 35.0),
        extrinsic_accuracy_m=0.12,
    )


# -- 핵심: 선언이 없으면 환산하지 않는다 ---------------------------------------


def test_the_same_new_size_can_be_a_resize_or_a_crop_so_an_undeclared_change_is_refused():
    """1920x1080 -> 960x540 은 축소일 수도 중앙 crop 일 수도 있다. 해상도는 같다."""
    profile = _profile()
    half = ApplicabilityScope("cam_a", (320, 240))

    undeclared = transfer_profile(profile, half)

    assert undeclared.verdict == "requires_reestimation"
    assert undeclared.reasons == ("transform_not_declared",)
    assert undeclared.profile is None


def test_a_declared_resize_rescales_the_intrinsics_and_keeps_the_distortion():
    """순수 resize 는 환산 가능하다. 왜곡 계수는 해상도 무관(문서 §7.1)."""
    profile = _profile()

    result = transfer_profile(
        profile, ApplicabilityScope("cam_a", (320, 240)), InputTransform("resize")
    )

    assert result.verdict == "convertible_resize"
    matrix = np.asarray(result.profile.camera_matrix)
    assert matrix[0, 0] == pytest.approx(400.0)
    assert matrix[1, 1] == pytest.approx(400.0)
    assert matrix[0, 2] == pytest.approx(160.0)
    assert matrix[1, 2] == pytest.approx(120.0)
    np.testing.assert_allclose(np.asarray(result.profile.dist_coeffs), _DIST)


def test_a_declared_crop_shifts_only_the_principal_point():
    """crop 은 주점을 offset 만큼 옮기고 초점거리는 그대로다(문서 §7.1)."""
    profile = _profile()

    result = transfer_profile(
        profile, ApplicabilityScope("cam_a", (320, 240)),
        InputTransform("crop", crop_offset_px=(160, 120)),
    )

    assert result.verdict == "convertible_crop"
    matrix = np.asarray(result.profile.camera_matrix)
    assert matrix[0, 0] == pytest.approx(800.0)   # 초점거리는 바뀌지 않는다
    assert matrix[0, 2] == pytest.approx(160.0)
    assert matrix[1, 2] == pytest.approx(120.0)


def test_a_crop_window_outside_the_source_frame_is_refused():
    result = transfer_profile(
        _profile(), ApplicabilityScope("cam_a", (320, 240)),
        InputTransform("crop", crop_offset_px=(500, 400)),
    )

    assert result.reasons == ("crop_outside_source_frame",)
    assert result.profile is None


def test_a_crop_without_a_declared_offset_is_refused():
    result = transfer_profile(
        _profile(), ApplicabilityScope("cam_a", (320, 240)), InputTransform("crop")
    )

    assert result.verdict == "requires_reestimation"
    assert result.reasons == ("transform_not_declared",)


# -- zoom 과 장착은 언제나 재추정이다 ------------------------------------------


def test_a_zoom_token_change_is_always_a_reestimation():
    """광학 zoom 은 초점거리를 바꾸고 디지털 zoom 의 offset 은 토큰이 말해 주지 않는다."""
    result = transfer_profile(
        _profile(),
        ApplicabilityScope("cam_a", (640, 480), zoom_token="2x"),
        InputTransform("resize"),
    )

    assert result.verdict == "requires_reestimation"
    assert "zoom_token_changed" in result.reasons


def test_a_mount_change_is_a_reestimation_because_it_invalidates_the_extrinsic():
    result = transfer_profile(
        _profile(ApplicabilityScope("cam_a", (640, 480), mount_token="bracket_a")),
        ApplicabilityScope("cam_a", (640, 480), mount_token="bracket_b"),
    )

    assert result.verdict == "requires_reestimation"
    assert "mount_token_changed" in result.reasons


def test_a_sensor_readout_change_is_not_a_plain_rescale():
    """binning/windowing 이 바뀐 경우는 단순 배율이 아니다(문서 §7.1)."""
    result = transfer_profile(
        _profile(), ApplicabilityScope("cam_a", (320, 240)),
        InputTransform("resize", sensor_readout_changed=True),
    )

    assert result.verdict == "requires_reestimation"
    assert "sensor_readout_changed" in result.reasons


def test_a_different_camera_is_never_transferable():
    result = transfer_profile(
        _profile(), ApplicabilityScope("cam_b", (640, 480)), InputTransform("resize")
    )

    assert result.reasons == ("camera_id_mismatch",)


def test_a_non_uniform_scale_is_refused_as_a_likely_crop_or_readout_change():
    result = transfer_profile(
        _profile(), ApplicabilityScope("cam_a", (320, 480)), InputTransform("resize")
    )

    assert result.verdict == "requires_reestimation"
    assert "non_uniform_scale" in result.reasons


def test_a_declared_scale_that_contradicts_the_resolutions_is_not_believed():
    result = transfer_profile(
        _profile(), ApplicabilityScope("cam_a", (320, 240)),
        InputTransform("resize", scale=(0.25, 0.25)),
    )

    assert result.reasons == ("declared_scale_inconsistent",)


def test_a_profile_without_a_declared_scope_cannot_be_transferred():
    """범위를 모르는 프로파일을 환산해 주면 "모든 조건에서 검증됐다" 로 읽히기 시작한다."""
    store = CalibrationProfileStore(camera_id="cam_a")
    legacy = store.submit(
        CalibrationEstimate(_K.copy(), _DIST.copy(), 0.4, True), validated=True
    )

    result = transfer_profile(
        legacy, ApplicabilityScope("cam_a", (320, 240)), InputTransform("resize")
    )

    assert result.verdict == "requires_reestimation"
    assert result.profile is None


def test_no_source_profile_is_its_own_reason():
    result = transfer_profile(None, ApplicabilityScope("cam_a", (320, 240)))

    assert result.reasons == ("no_source_profile",)


def test_an_unchanged_scope_returns_the_same_profile_object():
    profile = _profile()

    result = transfer_profile(profile, ApplicabilityScope("cam_a", (640, 480)))

    assert result.verdict == "unchanged"
    assert result.profile is profile


# -- 환산한 값은 재검증된 값이 아니다 ------------------------------------------


def test_a_transferred_profile_does_not_inherit_the_validation_it_never_repeated():
    profile = _profile()
    assert "reprojection_rms_within_budget" in profile.validated_by

    result = transfer_profile(
        profile, ApplicabilityScope("cam_a", (320, 240)), InputTransform("resize")
    )

    assert result.profile.validated_by == ("geometrically_transferred",)
    assert result.profile.method_id == "planar_target+transferred"
    assert result.profile.quality["transferred_from_version"] == float(profile.version)


def test_a_transferred_pixel_quality_gets_a_different_key_so_it_cannot_be_averaged():
    """AI-B-01: 다른 구성에서 측정한 값을 같은 값인 척 재사용하지 않는다."""
    result = transfer_profile(
        _profile(rms=0.4), ApplicabilityScope("cam_a", (320, 240)),
        InputTransform("resize"),
    )

    quality = result.profile.quality
    assert "reprojection_rms_px" not in quality
    assert quality["reprojection_rms_px_transferred"] == pytest.approx(0.2)
    assert result.profile.reprojection_error_rms == pytest.approx(0.2)


def test_a_transferred_profile_keeps_the_extrinsic_because_resizing_does_not_move_the_camera():
    result = transfer_profile(
        _profile(), ApplicabilityScope("cam_a", (320, 240)), InputTransform("resize")
    )

    assert result.profile.extrinsic == (2.0, -1.5, 35.0)
    assert result.profile.extrinsic_accuracy_m == 0.12
    assert result.profile.applies_to(ApplicabilityScope("cam_a", (320, 240)))
    assert not result.profile.applies_to(ApplicabilityScope("cam_a", (640, 480)))


def test_a_transferred_profile_with_an_unmeasured_rms_stays_unmeasured():
    """NaN 이 환산을 거쳐 0 이 되면 "측정한 적 없는 완벽한 보정" 이 생긴다."""
    store = CalibrationProfileStore(camera_id="cam_a")
    profile = store.submit(
        CalibrationEstimate(_K.copy(), None, float("nan"), True),
        validated=True, applicability=ApplicabilityScope("cam_a", (640, 480)),
        method_id="pure_rotation_homography",
    )

    result = transfer_profile(
        profile, ApplicabilityScope("cam_a", (320, 240)), InputTransform("resize")
    )

    assert math.isnan(result.profile.reprojection_error_rms)
    assert "reprojection_rms_px_transferred" not in result.profile.quality
    assert result.profile.dist_coeffs is None  # 미추정 왜곡은 환산해도 미추정이다


# -- 판정 어휘 ----------------------------------------------------------------


def test_every_verdict_is_in_the_registered_vocabulary():
    cases = [
        classify_input_change(ApplicabilityScope("cam_a", (640, 480)),
                              ApplicabilityScope("cam_a", (640, 480)))[0],
        classify_input_change(ApplicabilityScope("cam_a", (640, 480)),
                              ApplicabilityScope("cam_a", (320, 240)),
                              InputTransform("resize"))[0],
        classify_input_change(ApplicabilityScope("cam_a", (640, 480)),
                              ApplicabilityScope("cam_a", (320, 240)),
                              InputTransform("crop", crop_offset_px=(10, 10)))[0],
        classify_input_change(None, ApplicabilityScope("cam_a", (640, 480)))[0],
    ]

    assert set(cases) == set(INPUT_CHANGE_VERDICTS)
