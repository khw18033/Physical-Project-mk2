"""Versioned calibration profile generation, validation and deployment (AI-E-03).

implements: AI-E-03

A new profile is only ever activated once it passes validation
(`CalibrationEstimate.stable`); a failed/unstable estimate is kept in
history for traceability but must leave the previously active, valid
profile untouched (AI-E-03: "검증 실패 시 기존 정상 프로파일을 유지해야
한다").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from perception_framework.edge.calibration import CalibrationEstimate


@dataclass(frozen=True)
class CalibrationProfile:
    version: int
    camera_matrix: object
    dist_coeffs: object
    reprojection_error_rms: float
    created_at: str
    valid: bool


class CalibrationProfileStore:
    def __init__(self) -> None:
        self._active: CalibrationProfile | None = None
        self._history: list[CalibrationProfile] = []
        self._next_version = 1

    @property
    def active(self) -> CalibrationProfile | None:
        return self._active

    @property
    def history(self) -> list[CalibrationProfile]:
        return list(self._history)

    def submit(self, estimate: CalibrationEstimate) -> CalibrationProfile:
        profile = CalibrationProfile(
            version=self._next_version,
            camera_matrix=estimate.camera_matrix,
            dist_coeffs=estimate.dist_coeffs,
            reprojection_error_rms=estimate.reprojection_error_rms,
            created_at=datetime.now(timezone.utc).isoformat(),
            valid=estimate.stable,
        )
        self._next_version += 1
        self._history.append(profile)
        if profile.valid:
            self._active = profile
        return profile
