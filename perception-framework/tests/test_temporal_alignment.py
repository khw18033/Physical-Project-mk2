"""implements: AI-S-01, AI-C-03
reproduces (decision rule only): LRCP, WACV 2025 (docs/obsidian/papers/lrcp.md);
TraF-Align, CVPR 2025 (docs/obsidian/papers/traf-align.md)
tests: motion-compensated position tracks a moving object more accurately
       than the stale (uncompensated) position across latency, the gap
       between them widens with latency (matching LRCP's own reported
       robustness-vs-baseline curve shape), and graceful fallback when
       compensation is unavailable or untrusted; separately, the discrete
       candidate kernel (TraF-Align) reduces to the same center point at
       kernel_radius=0, shares compensate_for_latency's fallback center
       when velocity is missing, recovers from a sharp turn that breaks
       constant-velocity extrapolation when the kernel is wide enough to
       reach the true position, and honestly fails to recover when the
       kernel is too narrow to reach it

No V2X-Sim/DAIR-V2X BEV feature caches available locally, so this uses a
synthetic constant-velocity object crossing a scene with noisy velocity
estimates -- same posture as the other reproductions here: the qualitative
decision rule ("compensate using estimated motion beats not compensating,
by a growing margin as latency grows") is checked, not the paper's
reported AP@0.7 numbers. The discrete-kernel tests reuse the same
synthetic-scenario posture for TraF-Align's decision shape (candidate grid
+ caller-supplied score_fn beats a single extrapolated point under a sharp
turn, within the kernel's reach).
"""
from __future__ import annotations

import math
import random

from perception_framework.perception.temporal_alignment import (
    DEFAULT_MAX_COMPENSATED_LATENCY_S, compensate_for_latency,
    compensate_with_discrete_kernel,
)


def _true_position_at(t, *, start=(0.0, 0.0), velocity=(2.0, -1.0)):
    return (start[0] + velocity[0] * t, start[1] + velocity[1] * t)


def _error(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def test_zero_latency_is_a_no_op():
    result = compensate_for_latency((1.0, 2.0), (0.5, 0.5), latency_s=0.0)
    assert not result.compensated and (result.x, result.y) == (1.0, 2.0)


def test_missing_velocity_falls_back_to_stale_position():
    result = compensate_for_latency((1.0, 2.0), None, latency_s=0.3)
    assert not result.compensated and result.reason == "no_velocity_estimate"
    assert (result.x, result.y) == (1.0, 2.0)


def test_latency_beyond_trusted_window_falls_back_rather_than_extrapolating_blindly():
    result = compensate_for_latency((0.0, 0.0), (10.0, 10.0), latency_s=2.0)
    assert not result.compensated and result.reason == "latency_beyond_trusted_window"


def test_correct_velocity_perfectly_predicts_a_constant_velocity_object():
    stale = (0.0, 0.0)
    true_velocity = (2.0, -1.0)
    latency = 0.4
    result = compensate_for_latency(stale, true_velocity, latency_s=latency)
    predicted = (result.x, result.y)
    true_now = _true_position_at(latency)
    assert _error(predicted, true_now) < 1e-9


# -- LRCP's own claim: compensation beats no compensation, by a widening margin --

def test_compensation_reduces_error_and_the_advantage_grows_with_latency():
    rng = random.Random(0)
    latencies = [0.1, 0.3, 0.5]
    trials = 100
    gaps = []

    for latency in latencies:
        stale_errors, compensated_errors = [], []
        for _ in range(trials):
            true_velocity = (rng.uniform(-3, 3), rng.uniform(-3, 3))
            # A real tracker's velocity estimate is noisy, not exact.
            noisy_velocity = (
                true_velocity[0] + rng.gauss(0, 0.15),
                true_velocity[1] + rng.gauss(0, 0.15),
            )
            stale_position = (0.0, 0.0)
            true_now = _true_position_at(latency, velocity=true_velocity)

            stale_errors.append(_error(stale_position, true_now))
            compensated = compensate_for_latency(stale_position, noisy_velocity, latency_s=latency)
            compensated_errors.append(_error((compensated.x, compensated.y), true_now))

        mean_stale = sum(stale_errors) / trials
        mean_compensated = sum(compensated_errors) / trials
        gap = mean_stale - mean_compensated
        gaps.append(gap)
        print(
            f"\n[latency={latency}s] stale error {mean_stale:.3f} vs "
            f"compensated error {mean_compensated:.3f} (advantage {gap:.3f})"
        )
        assert mean_compensated < mean_stale

    # The advantage of compensating must grow as latency grows -- a moving
    # object drifts further from its stale position the longer the gap,
    # and compensation tracks that drift while the stale baseline does not.
    assert gaps[-1] > gaps[0]


def test_default_trusted_window_matches_lrcp_evaluation_range():
    # LRCP's own evaluation sweeps latency up to 500-600ms; this
    # framework's default trust boundary should not silently be narrower
    # than what the reproduced mechanism was actually shown to help at.
    assert DEFAULT_MAX_COMPENSATED_LATENCY_S >= 0.5


# -- compensate_with_discrete_kernel: TraF-Align's decision shape -- a
# discrete candidate grid around the extrapolated point, scored by the
# caller, instead of committing to that one continuous point --

def test_zero_kernel_radius_reduces_to_evaluating_the_single_center_point():
    calls = []

    def score_fn(x, y):
        calls.append((x, y))
        return 1.0

    last_position = (1.0, 2.0)
    velocity = (0.5, 0.5)
    latency = 0.3
    center = compensate_for_latency(last_position, velocity, latency_s=latency)

    result = compensate_with_discrete_kernel(
        last_position, velocity, latency_s=latency, score_fn=score_fn, kernel_radius=0,
    )

    # exactly one candidate evaluated, and it is the same center point
    # compensate_for_latency would produce -- no divergence between the
    # two functions' fallback/extrapolation logic.
    assert calls == [(center.x, center.y)]
    assert (result.x, result.y) == (center.x, center.y)
    assert result.score == 1.0
    assert result.reason == "discrete_kernel_center"


def test_discrete_kernel_never_raises_at_zero_radius_even_with_no_velocity():
    # Edge case: kernel_radius=0 with no velocity estimate at all -- still
    # a single-point grid around the stale position, never an exception.
    result = compensate_with_discrete_kernel(
        (5.0, -3.0), None, latency_s=0.4, score_fn=lambda x, y: 0.0, kernel_radius=0,
    )
    assert (result.x, result.y) == (5.0, -3.0)


def test_discrete_kernel_falls_back_to_stale_position_when_velocity_missing():
    # Same no-op posture as compensate_for_latency: missing velocity means
    # the grid is built around the stale position itself, not some
    # invented extrapolation.
    last_position = (3.0, 4.0)
    calls = []

    def score_fn(x, y):
        calls.append((x, y))
        # peaks exactly at the stale position
        return -_error((x, y), last_position)

    center = compensate_for_latency(last_position, None, latency_s=0.3)
    assert center.reason == "no_velocity_estimate"
    assert (center.x, center.y) == last_position

    result = compensate_with_discrete_kernel(
        last_position, None, latency_s=0.3, score_fn=score_fn, kernel_radius=1, kernel_spacing=0.5,
    )

    # the grid was centered on the same fallback point compensate_for_latency uses
    assert last_position in calls
    assert (result.x, result.y) == last_position


# -- The actual point of the exercise: constant-velocity extrapolation can
# miss badly when the object turns; a discrete candidate kernel wide
# enough to reach the true position can recover, but a kernel too narrow
# to reach it does NOT magically fix things either. --

def test_discrete_kernel_recovers_from_a_sharp_turn_that_breaks_constant_velocity():
    # The object was observed moving in +x. During the latency window it
    # makes a sharp turn and actually moves in +y instead -- exactly the
    # case where LRCP-style constant-velocity extrapolation breaks.
    last_position = (0.0, 0.0)
    observed_velocity = (5.0, 0.0)
    latency = 0.4  # within DEFAULT_MAX_COMPENSATED_LATENCY_S, so extrapolation actually fires
    true_turned_position = (0.0, 2.0)

    def score_fn(x, y):
        # Proxy for "how well this candidate matches a real current
        # detection" (a real deployment would use actual matching/
        # attention score here) -- highest exactly at the true position.
        return -_error((x, y), true_turned_position)

    # (a) LRCP-style constant-velocity extrapolation: lands far from the
    # turned position because it assumes the pre-turn motion continued.
    extrapolated = compensate_for_latency(last_position, observed_velocity, latency_s=latency)
    extrapolated_error = _error((extrapolated.x, extrapolated.y), true_turned_position)
    print(f"\n[sharp turn] constant-velocity extrapolation -> {(extrapolated.x, extrapolated.y)}, "
          f"error={extrapolated_error:.3f}")
    assert extrapolated_error > 2.5

    # (b) A kernel wide/coarse enough to include a candidate near the true
    # turned position recovers a substantially better result.
    wide = compensate_with_discrete_kernel(
        last_position, observed_velocity, latency_s=latency, score_fn=score_fn,
        kernel_radius=4, kernel_spacing=0.5,
    )
    wide_error = _error((wide.x, wide.y), true_turned_position)
    print(f"[sharp turn] wide discrete kernel -> {(wide.x, wide.y)}, error={wide_error:.3f}, "
          f"score={wide.score:.3f}")
    assert wide_error < extrapolated_error
    assert wide_error < 0.5

    # (c) Honest limit: the same idea with a kernel too narrow/fine to
    # reach anywhere near the turned position does NOT magically fix
    # things -- its chosen candidate is still far from the truth. This is
    # not a coincidence of one bad parameter choice: kernel_radius=1 with
    # the default spacing simply cannot reach a turn this large.
    narrow = compensate_with_discrete_kernel(
        last_position, observed_velocity, latency_s=latency, score_fn=score_fn,
        kernel_radius=1, kernel_spacing=0.5,
    )
    narrow_error = _error((narrow.x, narrow.y), true_turned_position)
    print(f"[sharp turn] narrow discrete kernel -> {(narrow.x, narrow.y)}, error={narrow_error:.3f}, "
          f"score={narrow.score:.3f}")
    assert narrow_error > 1.5
    assert narrow_error > wide_error
