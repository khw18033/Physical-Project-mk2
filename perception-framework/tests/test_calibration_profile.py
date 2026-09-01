"""implements: AI-E-03"""

import numpy as np

from perception_framework.edge.calibration import CalibrationEstimate
from perception_framework.edge.calibration_profile import CalibrationProfileStore


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
