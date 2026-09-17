"""Closed-form pinhole-intrinsics recovery from known pixel<->ray
correspondences (AI-E-02).

implements: AI-E-02

Design reference: docs/obsidian/papers/anycalib.md (AnyCalib, ICCV 2025,
Tirado-Garín & Civera). AnyCalib's actual novel contribution is a *learned*
neural network that regresses a per-pixel "FoV field" (a tangent-plane
coordinate on S^2 that is bijective to a per-pixel ray direction) from a
single RGB image. This module does **not** reproduce that learned
regression -- there is no training data or network here, and this module
never invents ray directions from an image.

What this module reproduces is the downstream step the paper documents as
closed-form: given a set of pixel<->ray-direction correspondences (in the
real AnyCalib system these rays come out of the trained FoV-field
predictor; here they are always a caller-supplied input), solve for
pinhole intrinsics (fx, fy, cx, cy) by linear least squares. For a ray
direction (rx, ry, rz) observed at pixel (u, v), the pinhole projection

    u = fx * (rx / rz) + cx
    v = fy * (ry / rz) + cy

is linear in (fx, cx) and, independently, in (fy, cy) once (rx/rz, ry/rz)
are known -- exactly the "Eqs. 8 and 9 become linear with respect to the
remaining intrinsics" step anycalib.md attributes to the paper. That is
real, well-defined algebra, legitimate to implement and test on purely
synthetic (pixel, ray) data.

This is an alternative *provider* for the same AI-E-02 calibration
capability that perception_framework/edge/calibration.py already defines
via `CameraCalibrator` (checkerboard correspondences + cv2.calibrateCamera).
Per this project's principle that calibration methods are pluggable and
never fixed to a single algorithm, the two modules share the same
"estimate -> quality-checked result, unstable fits are not deployed"
shape but differ in method and required input. A real deployment would
obtain ray directions from a trained FoV-field predictor (out of scope
here) or another calibration source upstream of this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RayCorrespondence:
    """One observed pixel and its associated ray direction.

    The ray direction (ray_x, ray_y, ray_z) need not be unit length --
    only the ratios ray_x/ray_z and ray_y/ray_z matter to the pinhole
    projection equations solved by `RayFieldIntrinsicsRecovery`. ray_z is
    the forward/depth component and must be nonzero.
    """

    pixel_u: float
    pixel_v: float
    ray_x: float
    ray_y: float
    ray_z: float


@dataclass(frozen=True)
class IntrinsicsEstimate:
    fx: float
    fy: float
    cx: float
    cy: float
    residual_rms: float
    stable: bool


class RayFieldIntrinsicsRecovery:
    """Recovers pinhole intrinsics from caller-supplied ray correspondences.

    This is a downstream-only, non-learned provider: it never derives ray
    directions from image content itself (that step -- AnyCalib's FoV-field
    network -- is explicitly out of scope, see module docstring).
    """

    def __init__(self, *, max_acceptable_rms: float = 1.0) -> None:
        self._max_acceptable_rms = max_acceptable_rms

    def estimate(
        self, correspondences: list[RayCorrespondence]
    ) -> IntrinsicsEstimate:
        """Solve u = fx*(rx/rz) + cx, v = fy*(ry/rz) + cy by linear
        least squares.

        The two equations decouple: (fx, cx) depend only on the u-column
        and the rx/rz ratios, (fy, cy) only on the v-column and the ry/rz
        ratios. Each is a standard 2-parameter linear least-squares fit.
        Requires at least 2 correspondences -- fewer than that leaves the
        2x2 normal-equations system rank-deficient/undetermined, so this
        raises ValueError rather than silently returning a degenerate or
        numpy-error result.
        """
        n = len(correspondences)
        if n < 2:
            raise ValueError(
                "RayFieldIntrinsicsRecovery.estimate requires at least 2 "
                f"pixel-ray correspondences to fit (fx, cx) and (fy, cy), got {n}"
            )

        pixel_u = np.array([c.pixel_u for c in correspondences], dtype=float)
        pixel_v = np.array([c.pixel_v for c in correspondences], dtype=float)
        ray_x = np.array([c.ray_x for c in correspondences], dtype=float)
        ray_y = np.array([c.ray_y for c in correspondences], dtype=float)
        ray_z = np.array([c.ray_z for c in correspondences], dtype=float)

        if np.any(np.abs(ray_z) < 1e-12):
            raise ValueError(
                "RayFieldIntrinsicsRecovery.estimate requires nonzero ray_z "
                "(forward/depth component) for every correspondence"
            )

        a = ray_x / ray_z
        b = ray_y / ray_z

        # u = fx * a + cx  ->  [a, 1] @ [fx, cx]^T = u
        design_u = np.column_stack([a, np.ones(n)])
        (fx, cx), _, _, _ = np.linalg.lstsq(design_u, pixel_u, rcond=None)

        # v = fy * b + cy  ->  [b, 1] @ [fy, cy]^T = v
        design_v = np.column_stack([b, np.ones(n)])
        (fy, cy), _, _, _ = np.linalg.lstsq(design_v, pixel_v, rcond=None)

        u_pred = fx * a + cx
        v_pred = fy * b + cy
        residual_rms = math.sqrt(
            float(np.mean((pixel_u - u_pred) ** 2 + (pixel_v - v_pred) ** 2))
        )

        return IntrinsicsEstimate(
            fx=float(fx),
            fy=float(fy),
            cx=float(cx),
            cy=float(cy),
            residual_rms=residual_rms,
            stable=residual_rms <= self._max_acceptable_rms,
        )
