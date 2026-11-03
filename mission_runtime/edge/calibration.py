"""Camera auto-calibration from image samples (AI-E-02).

implements: AI-E-02

Never requires a pre-existing calibration profile or a specific board
brand — this reference implementation estimates intrinsics/distortion
purely from correspondences between a known object-point geometry (e.g.
checkerboard corners) and detected image points. When the fit is
unstable, no profile is produced and callers keep using
image-coordinate-only perception (AI-E-02: "자동 추정이 불안정하면
보정값을 배포하지 않고 영상 좌표 기반 인지를 유지해야 한다").
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class CalibrationEstimate:
    camera_matrix: np.ndarray
    dist_coeffs: np.ndarray
    reprojection_error_rms: float
    stable: bool


class CameraCalibrator:
    def __init__(self, *, max_acceptable_rms: float = 1.0) -> None:
        self._max_acceptable_rms = max_acceptable_rms

    def estimate(
        self,
        object_points: list[np.ndarray],
        image_points: list[np.ndarray],
        image_size: tuple[int, int],
    ) -> CalibrationEstimate:
        rms, camera_matrix, dist_coeffs, _, _ = cv2.calibrateCamera(
            object_points, image_points, image_size, None, None
        )
        return CalibrationEstimate(
            camera_matrix=camera_matrix,
            dist_coeffs=dist_coeffs,
            reprojection_error_rms=rms,
            stable=rms <= self._max_acceptable_rms,
        )
