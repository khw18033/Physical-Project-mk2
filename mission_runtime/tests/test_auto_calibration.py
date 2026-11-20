"""implements: AI-E-02

조사 문서 `docs/research/automatic-camera-calibration.md` 가 §2 에서 남긴 첫 번째
구멍(보정판 없는 현장의 내부 파라미터)의 시험이다.

**전부 합성 자료다.** 실제 카메라도 실제 보정판 사진도 쓰지 않는다 — 알려진 K 로
`K R K⁻¹` 호모그래피를 만들거나 3D 점을 두 뷰에 투영해 대응을 만들고, 추정기가 그
알려진 값을 되찾는지를 본다. 그래야 "틀렸다" 가 추정기의 문제인지 자산의 문제인지
갈린다. 실제 자산으로 가정이 깨지는 것을 본 기록은 문서 §5.4 에 있다.

시험이 고정하는 것은 숫자 하나가 아니라 **거부가 일어나는지**다: 순수 회전 가정이
깨지면 직교성 잔차가 올라가고 검증기가 막아 이전 프로파일이 유지된다.
"""

import math

import cv2
import numpy as np
import pytest

from mission_runtime.edge.auto_calibration import (
    DEFAULT_SENSOR_FOV_PRIORS,
    MAX_ROTATION_RESIDUAL,
    INTRINSICS_EVIDENCE_KINDS,
    IntrinsicsCandidate,
    IntrinsicsMethodRegistry,
    IntrinsicsValidator,
    PlanarTargetEvidence,
    PlanarTargetIntrinsics,
    PointCorrespondences,
    PureRotationEvidence,
    RayCorrespondenceEvidence,
    RayCorrespondenceIntrinsics,
    RotationHomographyIntrinsics,
    SensorFovPrior,
    ViewPairHomography,
    default_method_registry,
    homography_from_correspondences,
)
from mission_runtime.edge.anycalib_style_recovery import RayCorrespondence
from mission_runtime.edge.calibration_profile import (
    ApplicabilityScope,
    CalibrationProfileStore,
)

_IMAGE_SIZE = (640, 480)


def _k(focal: float, size=_IMAGE_SIZE) -> np.ndarray:
    return np.array(
        [[focal, 0.0, size[0] / 2.0], [0.0, focal, size[1] / 2.0], [0.0, 0.0, 1.0]]
    )


def _rotation_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])


def _rotation_z(deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


def _rotation_homography(focal: float, yaw_deg: float, roll_deg: float = 2.0) -> np.ndarray:
    k = _k(focal)
    h = k @ (_rotation_y(yaw_deg) @ _rotation_z(roll_deg)) @ np.linalg.inv(k)
    return h / h[2, 2]


def _two_view_points(
    focal: float, yaw_deg: float, *, baseline_m: float = 0.0,
    noise_px: float = 0.0, count: int = 600, seed: int = 3,
):
    """3D 점을 두 뷰에 투영한다. `baseline_m` > 0 이면 순수 회전 가정이 깨진다."""
    rng = np.random.default_rng(seed)
    k = _k(focal)
    points = np.stack([
        rng.uniform(-6, 6, count), rng.uniform(-4, 4, count), rng.uniform(4, 30, count),
    ], axis=1)
    rotation = _rotation_y(yaw_deg) @ _rotation_z(2.0)
    translation = np.array([baseline_m, 0.0, 0.0])

    projected_a = (k @ points.T).T
    projected_a = projected_a[:, :2] / projected_a[:, 2:3]
    in_b = (rotation.T @ (points - translation).T).T
    projected_b = (k @ in_b.T).T
    projected_b = projected_b[:, :2] / projected_b[:, 2:3]
    if noise_px:
        projected_a = projected_a + rng.normal(0, noise_px, projected_a.shape)
        projected_b = projected_b + rng.normal(0, noise_px, projected_b.shape)
    width, height = _IMAGE_SIZE
    keep = (
        (projected_a[:, 0] > 0) & (projected_a[:, 0] < width)
        & (projected_a[:, 1] > 0) & (projected_a[:, 1] < height)
        & (projected_b[:, 0] > 0) & (projected_b[:, 0] < width)
        & (projected_b[:, 1] > 0) & (projected_b[:, 1] < height)
    )
    return projected_a[keep], projected_b[keep]


# -- 경계: 입력 종류가 방법을 정한다 -------------------------------------------


def test_registry_maps_evidence_kind_to_methods_and_rejects_unknown_kinds():
    registry = default_method_registry()

    assert registry.available_evidence_kinds() == INTRINSICS_EVIDENCE_KINDS
    assert registry.methods_for("pure_rotation_homographies")[0].method_id == (
        "pure_rotation_homography"
    )
    with pytest.raises(ValueError):
        registry.methods_for("magic_fov_oracle")


def test_a_new_method_needs_registration_not_a_core_edit():
    """새 방법은 등록 한 줄이다 — 레지스트리도 검증기도 고치지 않는다(원칙 #7)."""

    class FakeGeoCalibNetwork:
        method_id = "fake_learned_fov_field"
        evidence_kind = "pixel_ray_correspondences"

        def estimate(self, evidence):  # pragma: no cover - 경계만 확인한다
            raise NotImplementedError

    registry = default_method_registry()
    registry.register(FakeGeoCalibNetwork())

    ray_methods = [m.method_id for m in registry.methods_for("pixel_ray_correspondences")]
    assert ray_methods == ["pixel_ray_correspondence", "fake_learned_fov_field"]


def test_evidence_kind_outside_the_vocabulary_is_refused_at_registration():
    class Bogus:
        method_id = "bogus"
        evidence_kind = "vibes"

        def estimate(self, evidence):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(ValueError):
        IntrinsicsMethodRegistry().register(Bogus())


# -- 순수 회전 자기보정 (문서 §5.3) --------------------------------------------


@pytest.mark.parametrize("focal", [320.0, 480.0, 700.0])
@pytest.mark.parametrize("yaw_deg", [8.0, 15.0, 28.0])
def test_pure_rotation_recovers_focal_from_an_exact_homography(focal, yaw_deg):
    evidence = PureRotationEvidence(
        homographies=[
            ViewPairHomography(_rotation_homography(focal, yaw_deg), inlier_count=200)
        ],
        image_size=_IMAGE_SIZE,
    )

    candidate = RotationHomographyIntrinsics().estimate(evidence)

    assert candidate.fx == pytest.approx(focal, rel=1e-3)
    assert candidate.quality["orthogonality_residual"] < 1e-6
    assert candidate.stable is True


def test_pure_rotation_never_claims_a_distortion_it_did_not_estimate():
    """미측정 ≠ 0 — 0 벡터를 넣으면 "왜곡을 재 보니 없었다" 가 된다(AI-B-01)."""
    candidate = RotationHomographyIntrinsics().estimate(
        PureRotationEvidence(
            homographies=[ViewPairHomography(_rotation_homography(600.0, 12.0), 200)],
            image_size=_IMAGE_SIZE,
        )
    )

    assert candidate.dist_coeffs is None
    assert candidate.distortion_model is None
    assert candidate.distortion_estimated is False
    # 보정판 재투영 오차도 재지 않았다 — 0 이 아니라 NaN 으로 나간다.
    assert math.isnan(candidate.as_calibration_estimate().reprojection_error_rms)


def test_pure_rotation_from_real_correspondences_through_ransac():
    points_a, points_b = _two_view_points(700.0, 15.0, noise_px=0.3)
    homography = homography_from_correspondences(
        PointCorrespondences(points_a, points_b, "frame_a", "frame_b")
    )
    assert homography is not None and homography.inlier_count > 100

    candidate = RotationHomographyIntrinsics().estimate(
        PureRotationEvidence([homography], _IMAGE_SIZE)
    )

    assert candidate.fx == pytest.approx(700.0, rel=0.05)
    assert candidate.frame_refs == ("frame_a", "frame_b")


def test_too_few_correspondences_yields_no_homography_rather_than_an_exception():
    assert homography_from_correspondences(
        PointCorrespondences(np.zeros((3, 2)), np.zeros((3, 2)))
    ) is None


def test_translation_breaks_the_rotation_assumption_and_the_validator_rejects_it():
    """문서 §5.4 의 실측을 합성으로 재현한다 — 로봇 몸통 회전은 병진을 섞는다.

    가까운 장면에서 큰 베이스라인이 섞이면 `H = K R K⁻¹` 가 성립하지 않고, 추정기는
    여전히 숫자를 내지만 직교성 잔차가 올라간다. 승격을 막는 것은 추정기가 아니라
    검증기다 — 숨겨진 실패가 아니라 기록된 거부다.
    """
    points_a, points_b = _two_view_points(
        700.0, 15.0, baseline_m=2.0, noise_px=0.3, count=1200
    )
    homography = homography_from_correspondences(
        PointCorrespondences(points_a, points_b), ransac_threshold_px=3.0
    )
    assert homography is not None

    candidate = RotationHomographyIntrinsics().estimate(
        PureRotationEvidence([homography], _IMAGE_SIZE)
    )
    verdict = IntrinsicsValidator().validate(candidate)

    assert candidate.quality["orthogonality_residual"] > MAX_ROTATION_RESIDUAL
    assert verdict.passed is False
    assert "rotation_assumption_violated" in verdict.reasons


def test_rejected_self_calibration_keeps_the_previous_good_profile():
    """AI-E-02 의 fallback: 실패하면 마지막 정상 프로파일을 유지한다."""
    store = CalibrationProfileStore(camera_id="cam_a")
    good = RotationHomographyIntrinsics().estimate(
        PureRotationEvidence(
            [ViewPairHomography(_rotation_homography(600.0, 14.0), 200)], _IMAGE_SIZE
        )
    )
    good_verdict = IntrinsicsValidator().validate(good)
    promoted = store.submit(
        good.as_calibration_estimate(),
        validated=good_verdict.passed,
        validated_by=good_verdict.checks_passed,
        applicability=ApplicabilityScope("cam_a", _IMAGE_SIZE),
        method_id=good.method_id,
        quality=good.quality,
    )
    assert store.active is promoted

    broken = IntrinsicsCandidate(
        fx=600.0, fy=600.0, cx=320.0, cy=240.0, image_size=_IMAGE_SIZE,
        method_id="pure_rotation_homography",
        evidence_kind="pure_rotation_homographies",
        quality={"orthogonality_residual": 0.42, "min_inlier_count": 40.0},
        stable=False,
    )
    broken_verdict = IntrinsicsValidator().validate(broken)
    store.submit(
        broken.as_calibration_estimate(),
        validated=broken_verdict.passed,
        validation_reasons=broken_verdict.reasons,
        method_id=broken.method_id,
    )

    assert store.active is promoted
    assert store.last_rejection is not None
    assert store.last_rejection.kept_version == promoted.version
    assert "rotation_assumption_violated" in store.last_rejection.reasons


def test_assumed_principal_point_is_recorded_not_hidden():
    assumed = RotationHomographyIntrinsics().estimate(
        PureRotationEvidence(
            [ViewPairHomography(_rotation_homography(600.0, 14.0), 200)], _IMAGE_SIZE
        )
    )
    known = RotationHomographyIntrinsics().estimate(
        PureRotationEvidence(
            [ViewPairHomography(_rotation_homography(600.0, 14.0), 200)], _IMAGE_SIZE,
            principal_point=(320.0, 240.0),
        )
    )

    assert assumed.diagnostics["principal_point_assumed"] == 1.0
    assert known.diagnostics["principal_point_assumed"] == 0.0


def test_several_view_pairs_are_fitted_jointly():
    homographies = [
        ViewPairHomography(_rotation_homography(520.0, yaw), inlier_count=150)
        for yaw in (6.0, 13.0, 21.0, 30.0)
    ]
    candidate = RotationHomographyIntrinsics().estimate(
        PureRotationEvidence(homographies, _IMAGE_SIZE)
    )

    assert candidate.fx == pytest.approx(520.0, rel=1e-3)
    assert candidate.quality["view_pair_count"] == 4.0


def test_no_homography_at_all_is_an_input_error_not_a_silent_default():
    with pytest.raises(ValueError):
        RotationHomographyIntrinsics().estimate(
            PureRotationEvidence([], _IMAGE_SIZE)
        )


# -- 선언과 관측의 모순 (문서 §8) ----------------------------------------------


def test_fov_conflicting_with_the_declared_sensor_blocks_promotion():
    """선언된 협각 카메라에서 어안급 화각이 나오면 **모순이고 잡음이 아니다**."""
    narrow = DEFAULT_SENSOR_FOV_PRIORS["sensor.camera.imx708"]
    assert narrow.admits(66.0) and not narrow.admits(120.0)

    # 수평 화각 ≈ 120°: fx = (W/2)/tan(60°)
    wide = IntrinsicsCandidate(
        fx=(640 / 2) / math.tan(math.radians(60.0)),
        fy=(640 / 2) / math.tan(math.radians(60.0)),
        cx=320.0, cy=240.0, image_size=_IMAGE_SIZE,
        method_id="pure_rotation_homography",
        evidence_kind="pure_rotation_homographies",
        quality={"orthogonality_residual": 0.001, "min_inlier_count": 120.0},
    )
    verdict = IntrinsicsValidator().validate(
        wide, declared_sensor_tag="sensor.camera.imx708"
    )

    assert verdict.passed is False
    assert "fov_conflicts_declared_sensor" in verdict.reasons
    assert verdict.compared_with_declared_sensor is True


def test_no_declared_sensor_means_the_comparison_was_not_performed_not_passed():
    candidate = IntrinsicsCandidate(
        fx=500.0, fy=500.0, cx=320.0, cy=240.0, image_size=_IMAGE_SIZE,
        method_id="m", evidence_kind="pure_rotation_homographies",
        quality={"orthogonality_residual": 0.001, "min_inlier_count": 100.0},
    )

    verdict = IntrinsicsValidator().validate(candidate)

    assert verdict.passed is True
    assert verdict.compared_with_declared_sensor is False
    assert "fov_matches_declared_sensor" not in verdict.checks_passed


def test_unknown_sensor_tags_do_not_invent_a_prior():
    verdict = IntrinsicsValidator().validate(
        IntrinsicsCandidate(
            fx=500.0, fy=500.0, cx=320.0, cy=240.0, image_size=_IMAGE_SIZE,
            method_id="m", evidence_kind="pure_rotation_homographies",
            quality={"orthogonality_residual": 0.001, "min_inlier_count": 100.0},
        ),
        declared_sensor_tag="sensor.camera.brand_new_thing",
    )

    assert verdict.compared_with_declared_sensor is False
    assert verdict.passed is True


def test_a_new_camera_is_a_prior_entry_not_a_code_change():
    validator = IntrinsicsValidator(
        fov_priors={
            **DEFAULT_SENSOR_FOV_PRIORS,
            "sensor.camera.future": SensorFovPrior("sensor.camera.future", 40.0),
        }
    )
    narrow = IntrinsicsCandidate(
        fx=(640 / 2) / math.tan(math.radians(20.0)),
        fy=(640 / 2) / math.tan(math.radians(20.0)),
        cx=320.0, cy=240.0, image_size=_IMAGE_SIZE,
        method_id="m", evidence_kind="pure_rotation_homographies",
        quality={"orthogonality_residual": 0.001, "min_inlier_count": 100.0},
    )

    verdict = validator.validate(narrow, declared_sensor_tag="sensor.camera.future")

    assert verdict.passed is True
    assert "fov_matches_declared_sensor" in verdict.checks_passed


def test_physically_impossible_fov_is_refused_even_without_a_declared_sensor():
    """문서 §5.4 가 실측한 다른 실패 모드 — 7° 로 수렴한 퇴화 적합."""
    degenerate = IntrinsicsCandidate(
        fx=(640 / 2) / math.tan(math.radians(1.5)),  # 수평 화각 ≈ 3°
        fy=(640 / 2) / math.tan(math.radians(1.5)),
        cx=320.0, cy=240.0, image_size=_IMAGE_SIZE,
        method_id="m", evidence_kind="pure_rotation_homographies",
        quality={"orthogonality_residual": 0.001, "min_inlier_count": 100.0},
    )

    verdict = IntrinsicsValidator().validate(degenerate)

    assert "fov_physically_implausible" in verdict.reasons


def test_principal_point_outside_the_image_is_refused():
    verdict = IntrinsicsValidator().validate(
        IntrinsicsCandidate(
            fx=500.0, fy=500.0, cx=900.0, cy=240.0, image_size=_IMAGE_SIZE,
            method_id="m", evidence_kind="pure_rotation_homographies",
            quality={"orthogonality_residual": 0.001, "min_inlier_count": 100.0},
        )
    )

    assert "principal_point_outside_image" in verdict.reasons


def test_checks_not_performed_are_absent_from_checks_passed():
    """무엇을 검증하지 않았는지가 목록의 **여집합**으로 드러나야 한다."""
    verdict = IntrinsicsValidator().validate(
        IntrinsicsCandidate(
            fx=500.0, fy=500.0, cx=320.0, cy=240.0, image_size=_IMAGE_SIZE,
            method_id="m", evidence_kind="pixel_ray_correspondences",
            quality={},  # 아무 품질도 재지 않았다
        )
    )

    assert "rotation_assumption_holds" not in verdict.checks_passed
    assert "reprojection_rms_within_budget" not in verdict.checks_passed
    assert "sample_size_sufficient" not in verdict.checks_passed
    assert verdict.passed is True  # 수행하지 않은 검사는 실패가 아니다


# -- 다른 두 방법이 같은 경계에 있다 -------------------------------------------


def test_planar_target_adapter_still_estimates_distortion():
    rng = np.random.default_rng(0)
    board = np.zeros((54, 3), np.float32)
    board[:, :2] = np.mgrid[0:6, 0:9].T.reshape(-1, 2) * 0.03
    board[:, 0] -= board[:, 0].mean()
    board[:, 1] -= board[:, 1].mean()
    k_true = _k(800.0)
    dist_true = np.array([0.05, -0.03, 0.0, 0.0, 0.0])

    object_points, image_points = [], []
    for _ in range(12):
        rvec = rng.uniform(-0.2, 0.2, 3)
        tvec = np.array([rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05),
                         rng.uniform(0.5, 0.9)])
        pts, _ = cv2.projectPoints(board, rvec, tvec, k_true, dist_true)
        object_points.append(board)
        image_points.append(pts.reshape(-1, 2).astype(np.float32))

    candidate = PlanarTargetIntrinsics().estimate(
        PlanarTargetEvidence(object_points, image_points, _IMAGE_SIZE, ("f1",))
    )

    assert candidate.fx == pytest.approx(800.0, abs=5.0)
    assert candidate.distortion_estimated is True
    assert candidate.distortion_model == "brown_conrady"
    assert candidate.quality["reprojection_rms_px"] < 0.1


def test_ray_correspondence_adapter_keeps_the_seat_for_a_learned_predictor():
    """문서 §4.5 의 후보가 들어올 자리. 광선은 **언제나 상류 입력**이다."""
    focal, cx, cy = 450.0, 320.0, 240.0
    rays = []
    for u, v in ((10.0, 20.0), (600.0, 400.0), (320.0, 240.0), (100.0, 300.0)):
        rays.append(RayCorrespondence(u, v, (u - cx) / focal, (v - cy) / focal, 1.0))

    candidate = RayCorrespondenceIntrinsics().estimate(
        RayCorrespondenceEvidence(rays, _IMAGE_SIZE, ray_source="synthetic")
    )

    assert candidate.fx == pytest.approx(focal, rel=1e-6)
    assert candidate.cx == pytest.approx(cx, rel=1e-6)
    assert candidate.dist_coeffs is None
    assert candidate.quality["correspondence_count"] == 4.0


def test_methods_refuse_evidence_of_the_wrong_kind():
    with pytest.raises(TypeError):
        RotationHomographyIntrinsics().estimate(
            RayCorrespondenceEvidence([], _IMAGE_SIZE)
        )
    with pytest.raises(TypeError):
        PlanarTargetIntrinsics().estimate(
            PureRotationEvidence([], _IMAGE_SIZE)
        )


def test_the_residual_threshold_sits_in_the_measured_gap():
    """실측 분포 사이의 빈 구간에 임계값이 있는지 고정한다(모듈의 측정표 참고).

    유효한 적합의 최대 잔차(0.033)보다 크고 깨진 적합의 최소(0.25)보다 작아야 한다.
    이 수치는 문헌값이 아니라 rot8 실자산 측정값이므로, 특징 매처나 해상도를 바꾸면
    이 시험이 먼저 깨져 다시 재야 한다는 사실을 알린다.
    """
    assert 0.033 < MAX_ROTATION_RESIDUAL < 0.25
