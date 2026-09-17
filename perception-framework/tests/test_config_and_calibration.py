"""implements: AI-B-05, AI-B-07, AI-C-02, AI-E-02, AI-E-03, AI-N-02
"""
import numpy as np
import pytest

from perception_framework.common.coordinates import CoordinateFrame, SpatialValue, to_camera_local
from perception_framework.edge.calibration import CameraCalibrator
from perception_framework.ondevice.config_apply import ConfigApplier, ConfigUpdate
from perception_framework.simulation.sources import VideoFileMediaSource, write_synthetic_video

# --- Scenario 10 — config delta update -------------------------------------


def known_good_validator(config: dict) -> bool:
    """Rejects a calibration entry explicitly marked invalid."""
    calibration = config.get("calibration", {})
    return bool(calibration.get("valid", True))


def test_s10_first_entry_receives_the_full_configuration():
    applier = ConfigApplier(validate_fn=known_good_validator)

    applied = applier.apply(
        ConfigUpdate(
            version=1,
            full=True,
            items={"profile": "v1", "map": "v1", "calibration": {"v": 1, "valid": True}, "rules": "v1"},
        )
    )

    assert applied is True
    assert set(applier.active_config) == {"profile", "map", "calibration", "rules"}
    assert applier.active_version == 1


def test_s10_a_delta_only_changes_the_named_item():
    applier = ConfigApplier(validate_fn=known_good_validator)
    applier.apply(
        ConfigUpdate(1, True, {"profile": "v1", "map": "v1", "calibration": {"v": 1, "valid": True}, "rules": "v1"})
    )

    applier.apply(ConfigUpdate(2, False, {"calibration": {"v": 2, "valid": True}}))

    config = applier.active_config
    assert config["calibration"]["v"] == 2
    # map / rules / profile 은 재전송되지 않았고 그대로다.
    assert (config["map"], config["rules"], config["profile"]) == ("v1", "v1", "v1")
    assert applier.active_version == 2


def test_s10_invalid_new_version_is_rejected_and_the_previous_one_stays_active():
    applier = ConfigApplier(validate_fn=known_good_validator)
    applier.apply(ConfigUpdate(1, True, {"calibration": {"v": 1, "valid": True}}))
    applier.apply(ConfigUpdate(2, False, {"calibration": {"v": 2, "valid": True}}))

    applied = applier.apply(ConfigUpdate(3, False, {"calibration": {"v": 3, "valid": False}}))

    assert applied is False
    assert applier.active_config["calibration"]["v"] == 2  # v2 계속 사용
    assert applier.active_version == 2


def test_s10_a_delta_without_any_baseline_is_refused():
    applier = ConfigApplier(validate_fn=known_good_validator)

    assert applier.apply(ConfigUpdate(5, False, {"calibration": {"v": 5}})) is False
    assert applier.active_version is None


# --- Scenario 11 — new virtual camera, automatic calibration ---------------


def synthetic_checkerboard_views(camera_matrix, distortion, *, views=12, seed=0):
    """Generate corner observations for a known camera without any hardware."""
    import cv2

    rng = np.random.default_rng(seed)
    grid = np.zeros((6 * 9, 3), np.float32)
    grid[:, :2] = np.mgrid[0:6, 0:9].T.reshape(-1, 2) * 0.03
    grid[:, 0] -= grid[:, 0].mean()
    grid[:, 1] -= grid[:, 1].mean()

    object_points, image_points = [], []
    for _ in range(views):
        rvec = rng.uniform(-0.2, 0.2, size=3)
        tvec = np.array([rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(0.5, 0.9)])
        projected, _ = cv2.projectPoints(grid, rvec, tvec, camera_matrix, distortion)
        object_points.append(grid)
        image_points.append(projected.reshape(-1, 2).astype(np.float32))
    return object_points, image_points


@pytest.mark.parametrize(
    "fx,fy",
    [(800.0, 800.0), (450.0, 450.0)],  # camera_B, fisheye_C: 서로 다른 내부 파라미터
)
def test_s11_a_newly_connected_camera_gets_its_own_calibration_profile(fx, fy):
    camera_matrix = np.array([[fx, 0, 320.0], [0, fy, 240.0], [0, 0, 1.0]])
    distortion = np.array([-0.1, 0.05, 0.0, 0.0, 0.0])
    object_points, image_points = synthetic_checkerboard_views(camera_matrix, distortion)

    estimate = CameraCalibrator(max_acceptable_rms=1.0).estimate(object_points, image_points, (640, 480))

    assert estimate.stable is True
    assert abs(estimate.camera_matrix[0, 0] - fx) < 1.0


def test_s11_unstable_estimate_is_not_deployed_but_image_space_perception_continues():
    """자동 추정이 불안정하면 보정값을 배포하지 않고 영상 좌표 인지를 유지한다 (AI-E-02)."""
    rng = np.random.default_rng(1)
    object_points, image_points = synthetic_checkerboard_views(
        np.array([[800.0, 0, 320.0], [0, 800.0, 240.0], [0, 0, 1.0]]), np.zeros(5)
    )
    noisy = [points + rng.normal(0, 25, size=points.shape).astype(np.float32) for points in image_points]

    estimate = CameraCalibrator(max_acceptable_rms=0.5).estimate(object_points, noisy, (640, 480))

    assert estimate.stable is False
    # 보정이 없어도 영상 좌표 결과는 그대로 유지된다 (AI-C-02).
    raw = SpatialValue((100.0, 200.0), CoordinateFrame.IMAGE, "camera_C")
    kept = to_camera_local(raw, calibration_profile=None)
    assert kept.frame is CoordinateFrame.IMAGE


def test_s11_video_file_camera_is_consumed_through_the_common_media_contract(tmp_path):
    """카메라 URL·codec·파일 경로는 어댑터 안에 숨고, 소비자는 프레임만 본다."""
    path = write_synthetic_video(tmp_path / "camera_C.mp4", frames=6)
    source = VideoFileMediaSource("camera_C", path)
    try:
        assert source.is_available() is True
        frame = source.read_frame()
    finally:
        source.release()

    assert frame is not None
    assert frame.shape[0] > 0 and frame.shape[1] > 0


def test_s11_missing_video_file_disables_only_the_video_source(tmp_path):
    source = VideoFileMediaSource("camera_missing", tmp_path / "nope.mp4")

    assert source.is_available() is False
    assert source.read_frame() is None  # 예외가 아니라 '없음'
