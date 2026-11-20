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
    """보정 추정 1건. 아직 프로파일이 아니다.

    `dist_coeffs` 가 None 인 것은 **"이 방법이 왜곡을 추정하지 않았다"** 는 뜻이고
    "왜곡이 없다" 가 아니다 — 0 벡터로 채우면 그 구분이 사라지고, 사라진 자리에서
    광각 렌즈의 왜곡이 "측정해 보니 없었다" 로 읽힌다(AI-B-01: 미측정 항목은 구분한다).
    보정판 없는 자기보정(`edge/auto_calibration.py`)이 그 경우다.
    `reprojection_error_rms` 도 같은 규칙을 따른다: 재지 않은 축은 NaN 이고 0 이 아니다.
    """

    camera_matrix: np.ndarray
    dist_coeffs: np.ndarray | None
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
