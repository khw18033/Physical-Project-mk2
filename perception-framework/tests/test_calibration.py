"""implements: AI-E-02

Uses purely synthetic correspondences (no camera, no real checkerboard
photo): a known camera matrix/distortion projects a virtual checkerboard
into several virtual poses via cv2.projectPoints, and the calibrator
must recover intrinsics close to the originals from those points alone.
"""

import cv2
import numpy as np

from perception_framework.edge.calibration import CameraCalibrator

_K_TRUE = np.array([[800.0, 0.0, 320.0], [0.0, 800.0, 240.0], [0.0, 0.0, 1.0]])
_DIST_TRUE = np.array([0.05, -0.03, 0.0, 0.0, 0.0])
_IMAGE_SIZE = (640, 480)


def _synthetic_views(n_views: int, noise_std: float = 0.0, seed: int = 0):
    rng = np.random.default_rng(seed)
    board_size = (6, 9)
    square = 0.03
    objp = np.zeros((board_size[0] * board_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0 : board_size[0], 0 : board_size[1]].T.reshape(-1, 2) * square
    objp[:, 0] -= objp[:, 0].mean()
    objp[:, 1] -= objp[:, 1].mean()

    object_points, image_points = [], []
    for _ in range(n_views):
        rvec = rng.uniform(-0.2, 0.2, size=3)
        tvec = np.array([rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(0.5, 0.9)])
        imgp, _ = cv2.projectPoints(objp, rvec, tvec, _K_TRUE, _DIST_TRUE)
        imgp = imgp.reshape(-1, 2).astype(np.float32)
        if noise_std > 0:
            imgp = imgp + rng.normal(0, noise_std, imgp.shape).astype(np.float32)
        object_points.append(objp)
        image_points.append(imgp)
    return object_points, image_points


def test_calibration_recovers_known_intrinsics_from_clean_synthetic_views():
    object_points, image_points = _synthetic_views(n_views=12)
    calibrator = CameraCalibrator(max_acceptable_rms=1.0)

    estimate = calibrator.estimate(object_points, image_points, _IMAGE_SIZE)

    assert estimate.stable is True
    assert estimate.reprojection_error_rms < 0.1
    assert abs(estimate.camera_matrix[0, 0] - _K_TRUE[0, 0]) < 5.0  # fx within 5px-equivalent
    assert abs(estimate.camera_matrix[1, 1] - _K_TRUE[1, 1]) < 5.0  # fy


def test_noisy_correspondences_are_flagged_unstable_and_not_deployable():
    object_points, image_points = _synthetic_views(n_views=12, noise_std=3.0)
    calibrator = CameraCalibrator(max_acceptable_rms=1.0)

    estimate = calibrator.estimate(object_points, image_points, _IMAGE_SIZE)

    assert estimate.stable is False
