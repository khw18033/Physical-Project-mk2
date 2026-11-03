"""Latency-aware motion compensation before cross-source matching.

implements: AI-S-01, AI-C-03
reproduces (decision rule only, not the transformer pipeline): LRCP, WACV 2025
(docs/obsidian/papers/lrcp.md)

LRCP's actual mechanism — predicting a flow field from cached BEV features
and using it to shift a deformable-attention decoder's *sampling
locations*, never to resynthesize a corrected feature map (verified from
the full paper text; an ablation there shows explicit warping performs
*worse* than this "shift where you look, don't rewrite what you have"
approach) — is tied tightly to a transformer feature-fusion pipeline this
framework does not have.

What is reproducible without that pipeline is the same underlying decision
rule: given a stale observation and its own estimated motion, correct
*where it is expected to be now* before matching it against something
current, rather than matching at the stale position directly (LRCP's own
"no compensation" baseline, which its paper shows is measurably worse) or
discarding the observation as simply too old.

This reuses whatever velocity estimate an already-tracked object carries
(AI-S-01, `perception/tracking.py`) as the "flow" — one tracked object's
ordinary motion history stands in for LRCP's learned per-cell flow
prediction. `frame_ref`/timing fields belong to AI-C-03's frame-reference
contract, not reinvented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MotionCompensatedPosition:
    """Where an object is expected to be *now*, and whether that expectation
    used motion compensation or fell back to the stale position as-is.
    """

    x: float
    y: float
    latency_s: float
    compensated: bool
    reason: str


#: Beyond this, extrapolating a constant-velocity estimate is judged more
#: likely to *introduce* error than remove it (LRCP itself is evaluated up
#: to 500ms; this framework does not assume the same holds indefinitely).
#: A missing/expired velocity must degrade to "use the stale position",
#: never fail (AI-C-11 posture).
DEFAULT_MAX_COMPENSATED_LATENCY_S = 0.5


def compensate_for_latency(
    last_position: tuple[float, float],
    velocity: tuple[float, float] | None,
    latency_s: float,
    *,
    max_compensated_latency_s: float = DEFAULT_MAX_COMPENSATED_LATENCY_S,
) -> MotionCompensatedPosition:
    """Predicts a stale observation's current position from its own last
    known velocity, or returns the stale position unchanged when
    compensation is not available or not trusted at this latency.
    """
    x, y = last_position
    if latency_s <= 0:
        return MotionCompensatedPosition(x, y, latency_s, False, "no_latency")
    if velocity is None:
        return MotionCompensatedPosition(x, y, latency_s, False, "no_velocity_estimate")
    if latency_s > max_compensated_latency_s:
        return MotionCompensatedPosition(x, y, latency_s, False, "latency_beyond_trusted_window")

    vx, vy = velocity
    return MotionCompensatedPosition(x + vx * latency_s, y + vy * latency_s, latency_s, True, "motion_compensated")


# -- Alternative strategy: discrete candidate kernel (TraF-Align's decision shape) --
#
# reproduces (decision rule only, not the transformer pipeline): TraF-Align,
# CVPR 2025 (docs/obsidian/papers/traf-align.md)
#
# TraF-Align's verified mechanism is NOT a single continuous flow vector
# like LRCP's `compensate_for_latency` above. It predicts a per-pixel
# position/orientation field and an `OffsetGenerator` that emits
# `kernel x kernel x heads` discrete integer-pixel candidate offsets per
# location, then has a transformer attend over exactly those gathered
# candidates rather than committing to one continuous extrapolated point
# (docs/obsidian/papers/traf-align.md §3 "Offset Generator"). This
# framework has no BEV feature map or attention transformer to reproduce
# that gather/attend step over, but the *decision shape* it stands for is
# reproducible without them: instead of trusting one extrapolated point,
# generate a small discrete grid of candidates around it and let something
# that can actually see current evidence (`score_fn`) pick among them.
#
# This is deliberately positioned as an ALTERNATIVE to
# `compensate_for_latency`, not a replacement -- the two dataclasses and
# functions above are LRCP's reproduction and are left untouched. Callers
# choose one strategy or the other (or both) per AI-B-01's "different
# execution configurations are different, compare, do not silently
# assume one subsumes the other" posture.


@dataclass(frozen=True)
class DiscreteCandidatePosition:
    """The best-scoring position out of a discrete candidate grid, and why
    it was picked."""

    x: float
    y: float
    score: float
    reason: str


def compensate_with_discrete_kernel(
    last_position: tuple[float, float],
    velocity: tuple[float, float] | None,
    latency_s: float,
    score_fn: Callable[[float, float], float],
    *,
    kernel_radius: int = 1,
    kernel_spacing: float = 0.5,
) -> DiscreteCandidatePosition:
    """Reproduces TraF-Align's verified decision shape
    (docs/obsidian/papers/traf-align.md): instead of committing to ONE
    continuous velocity-extrapolated point (LRCP's `compensate_for_latency`
    above), generate a small discrete grid of CANDIDATE positions centered
    on that same extrapolated point, then let the caller's `score_fn(x, y)`
    -- e.g. a real matching/attention score against current detections in
    a real deployment -- pick the best-scoring candidate.

    This module never invents what "best" means; `score_fn` must be
    supplied by the caller (same "no invented cost/quality numbers" rule as
    `perception/reobservation_policy.py`'s `cost_fn` and
    `simulation/pose_graph_alignment.py`'s required `outlier_scale_m`).

    The center of the grid -- and its zero-latency/no-velocity fallback
    behavior -- is computed by calling `compensate_for_latency` directly,
    not by duplicating its fallback logic here. This keeps the two
    functions consistent: whenever `compensate_for_latency` would fall
    back to the stale position (no latency, no velocity estimate, latency
    beyond the trusted window), this function builds its discrete grid
    around that same stale position instead of diverging on edge-case
    behavior.

    `kernel_radius=0` never raises -- it degenerates to evaluating only the
    single center point, still returned as a valid `DiscreteCandidatePosition`.
    """
    center = compensate_for_latency(last_position, velocity, latency_s)
    cx, cy = center.x, center.y

    best: DiscreteCandidatePosition | None = None
    for i in range(-kernel_radius, kernel_radius + 1):
        for j in range(-kernel_radius, kernel_radius + 1):
            x = cx + i * kernel_spacing
            y = cy + j * kernel_spacing
            score = score_fn(x, y)
            if best is None or score > best.score:
                reason = "discrete_kernel_center" if (i == 0 and j == 0) else "discrete_kernel_candidate"
                best = DiscreteCandidatePosition(x, y, score, reason)

    assert best is not None  # a (2*kernel_radius+1)^2 grid always has >= 1 point
    return best
