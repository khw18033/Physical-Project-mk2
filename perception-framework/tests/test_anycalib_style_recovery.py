"""implements: AI-E-02

Tests for perception_framework.edge.anycalib_style_recovery, the
closed-form pinhole-intrinsics-from-known-rays provider described in
docs/obsidian/papers/anycalib.md. All correspondences here are purely
synthetic (no image, no network): rays are generated directly from a
known ground-truth camera matrix via the inverse of the pinhole equation
this module solves, mirroring how tests/test_calibration.py exercises
CameraCalibrator with synthetic checkerboard correspondences instead of
real photos.
"""

import numpy as np
import pytest

from perception_framework.edge.anycalib_style_recovery import (
    IntrinsicsEstimate,
    RayCorrespondence,
    RayFieldIntrinsicsRecovery,
)

_FX_TRUE = 800.0
_FY_TRUE = 810.0
_CX_TRUE = 320.0
_CY_TRUE = 240.0

_PIXEL_GRID = [
    (0.0, 0.0),
    (640.0, 0.0),
    (0.0, 480.0),
    (640.0, 480.0),
    (320.0, 240.0),
    (100.0, 400.0),
    (500.0, 50.0),
    (300.0, 300.0),
]


def _exact_correspondences(pixels) -> list[RayCorrespondence]:
    """Builds correspondences exactly consistent with the ground-truth
    intrinsics -- the inverse of what `estimate()` solves for: given
    (u, v) and known (fx, fy, cx, cy), the ray ratios are
    rx/rz = (u - cx) / fx, ry/rz = (v - cy) / fy.
    """
    correspondences = []
    for u, v in pixels:
        a = (u - _CX_TRUE) / _FX_TRUE
        b = (v - _CY_TRUE) / _FY_TRUE
        ray = np.array([a, b, 1.0])
        ray = ray / np.linalg.norm(ray)
        correspondences.append(
            RayCorrespondence(pixel_u=u, pixel_v=v, ray_x=ray[0], ray_y=ray[1], ray_z=ray[2])
        )
    return correspondences


def test_perfect_synthetic_recovery_matches_ground_truth_intrinsics():
    correspondences = _exact_correspondences(_PIXEL_GRID)
    recovery = RayFieldIntrinsicsRecovery(max_acceptable_rms=1.0)

    estimate = recovery.estimate(correspondences)

    assert isinstance(estimate, IntrinsicsEstimate)
    assert estimate.fx == pytest.approx(_FX_TRUE, abs=1e-6)
    assert estimate.fy == pytest.approx(_FY_TRUE, abs=1e-6)
    assert estimate.cx == pytest.approx(_CX_TRUE, abs=1e-6)
    assert estimate.cy == pytest.approx(_CY_TRUE, abs=1e-6)
    assert estimate.residual_rms < 1e-9
    assert estimate.stable is True


def _noisy_correspondences(sigma_px: float, n_points: int, seed: int) -> list[RayCorrespondence]:
    rng = np.random.default_rng(seed)
    us = rng.uniform(0.0, 640.0, size=n_points)
    vs = rng.uniform(0.0, 480.0, size=n_points)
    correspondences = _exact_correspondences(list(zip(us, vs)))
    noisy = []
    for c in correspondences:
        noisy.append(
            RayCorrespondence(
                pixel_u=c.pixel_u + rng.normal(0, sigma_px),
                pixel_v=c.pixel_v + rng.normal(0, sigma_px),
                ray_x=c.ray_x,
                ray_y=c.ray_y,
                ray_z=c.ray_z,
            )
        )
    return noisy


def test_noisy_recovery_is_close_but_not_exact_and_residual_reflects_noise_level():
    recovery = RayFieldIntrinsicsRecovery(max_acceptable_rms=1.0)

    low_noise = recovery.estimate(_noisy_correspondences(sigma_px=0.2, n_points=50, seed=1))
    high_noise = recovery.estimate(_noisy_correspondences(sigma_px=2.0, n_points=50, seed=1))

    # Close to ground truth but not exact -- a few pixels of tolerance is
    # reasonable for sigma up to 2px averaged over 50 correspondences via
    # least squares (expected fit error shrinks roughly as sigma/sqrt(n)).
    for estimate in (low_noise, high_noise):
        assert estimate.fx == pytest.approx(_FX_TRUE, abs=5.0)
        assert estimate.fy == pytest.approx(_FY_TRUE, abs=5.0)
        assert estimate.cx == pytest.approx(_CX_TRUE, abs=5.0)
        assert estimate.cy == pytest.approx(_CY_TRUE, abs=5.0)

    assert low_noise.residual_rms > 0.0
    assert high_noise.residual_rms > 0.0
    # More pixel noise must yield a larger reprojection residual -- the
    # residual is a real quality signal, not an invented constant. The
    # expected per-point residual is roughly sigma*sqrt(2) (independent u
    # and v errors combined), so 0.2px noise (~0.28 expected) stays under
    # the default max_acceptable_rms=1.0 while 2.0px noise (~2.83 expected)
    # correctly gets flagged unstable -- `stable` tracks the noise level,
    # it is not a constant True/False.
    assert high_noise.residual_rms > low_noise.residual_rms
    assert low_noise.stable is True
    assert high_noise.stable is False


@pytest.mark.parametrize("correspondences", [[], _exact_correspondences(_PIXEL_GRID)[:1]])
def test_fewer_than_two_correspondences_raises_value_error(correspondences):
    recovery = RayFieldIntrinsicsRecovery()

    with pytest.raises(ValueError, match="at least 2"):
        recovery.estimate(correspondences)


def test_rays_unrelated_to_pixels_are_flagged_unstable_and_not_deployable():
    rng = np.random.default_rng(2)
    n_points = 30
    us = rng.uniform(0.0, 640.0, size=n_points)
    vs = rng.uniform(0.0, 480.0, size=n_points)

    # Random unit rays with no relationship to (u, v) -- deliberately
    # inconsistent with any single pinhole model.
    random_rays = rng.normal(size=(n_points, 3))
    random_rays /= np.linalg.norm(random_rays, axis=1, keepdims=True)

    correspondences = [
        RayCorrespondence(pixel_u=u, pixel_v=v, ray_x=rx, ray_y=ry, ray_z=rz)
        for (u, v), (rx, ry, rz) in zip(zip(us, vs), random_rays)
    ]

    recovery = RayFieldIntrinsicsRecovery(max_acceptable_rms=1.0)
    estimate = recovery.estimate(correspondences)

    assert estimate.residual_rms > 1.0
    assert estimate.stable is False


def test_zero_ray_z_raises_value_error_instead_of_dividing_by_zero():
    correspondences = [
        RayCorrespondence(pixel_u=0.0, pixel_v=0.0, ray_x=0.1, ray_y=0.1, ray_z=0.0),
        RayCorrespondence(pixel_u=10.0, pixel_v=10.0, ray_x=0.2, ray_y=0.2, ray_z=1.0),
    ]
    recovery = RayFieldIntrinsicsRecovery()

    with pytest.raises(ValueError, match="nonzero ray_z"):
        recovery.estimate(correspondences)
