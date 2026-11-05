"""implements: AI-E-02

2026-11-04: 머리말이 `AI-E-02` 을 달고 있었다. CLAUDE.md §5 가 비어 있는 과거 번호는
**재사용하지 않는다**고 적은 그 번호이고, 대상 모듈(`edge/calibration_profile.py`)은
이미 AI-E-02 로 정정돼 있었다 — 시험만 남아 있어 같이 옮긴다. 보정 lifecycle 의
요구사항 ID 는 AI-E-02 하나다.
"""

import numpy as np

from mission_runtime.edge.calibration import CalibrationEstimate
from mission_runtime.edge.calibration_profile import CalibrationProfileStore


def make_estimate(rms: float, stable: bool) -> CalibrationEstimate:
    return CalibrationEstimate(
        camera_matrix=np.eye(3), dist_coeffs=np.zeros(5), reprojection_error_rms=rms, stable=stable
    )


def test_stable_estimate_becomes_the_active_profile():
    store = CalibrationProfileStore()

    profile = store.submit(make_estimate(rms=0.2, stable=True))

    assert store.active is profile
    assert profile.version == 1


def test_unstable_estimate_after_a_valid_profile_does_not_replace_it():
    store = CalibrationProfileStore()
    good = store.submit(make_estimate(rms=0.2, stable=True))

    store.submit(make_estimate(rms=5.0, stable=False))

    assert store.active is good
    assert len(store.history) == 2  # both are recorded for traceability


def test_first_ever_unstable_estimate_leaves_no_active_profile():
    store = CalibrationProfileStore()

    store.submit(make_estimate(rms=5.0, stable=False))

    assert store.active is None
