"""Synthetic reproduction of P2IOD's parameter-fusion qualitative claim.

implements: AI-L-04, AI-L-05

docs/obsidian/papers/p2iod.md §5 ablation (Table 3, VOC 5+5+5+5): adding the
parameterized-prompt structure alone drops old-class AP50 from 73.3 to 70.7
(catastrophic forgetting), and adding parameterized-prompt fusion on top
recovers it to 74.0. This test does not reproduce those numbers (no real
detector or dataset is involved) -- it reproduces the same QUALITATIVE shape
with a synthetic toy proxy: naive overwrite hurts an "old-task score" the
most, naive blind averaging hurts it less, and `fuse_task_vectors` (the real
decision rule from perception_framework/continual/p2iod.py) protects it best
while still capturing a "new-task score" far above doing nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from perception_framework.continual.p2iod import fuse_task_vectors


def _old_task_score(fused: np.ndarray, prior: np.ndarray) -> float:
    """Fraction of parameters where `fused` still favors the same toy class as `prior`.

    Each entry's sign encodes which of two toy old-task classes that parameter
    favors (positive = class A, negative = class B). If fusion flips an
    entry's sign, that parameter now argues for the wrong old-task class --
    a cheap, sign-only proxy for "old-class AP retained" that needs no real
    detector or dataset.
    """
    return float(np.mean(np.sign(fused) == np.sign(prior)))


def _new_task_score(fused: np.ndarray, new_task_target: np.ndarray) -> float:
    """Cosine similarity of `fused` to the fully-updated new-task target vector."""
    denom = np.linalg.norm(fused) * np.linalg.norm(new_task_target)
    if denom == 0:
        return 0.0
    return float(np.dot(fused, new_task_target) / denom)


def _build_synthetic_scenario() -> tuple[np.ndarray, np.ndarray]:
    """20-dim toy old-task vector plus a partially-conflicting new-task delta.

    prior[0:10] = +1 (favors toy class A), prior[10:20] = -1 (favors toy class
    B) -- a plausible stand-in for "each parameter's sign records which old
    class it supports". new_task_delta mixes:
      - 2 "critical" (largest-magnitude) entries, sign-consistent with prior
        (the new task's most important update, which happens to reinforce
        old knowledge here);
      - 5 "conflict-strong" entries whose sign disagrees with prior and whose
        magnitude is large enough to flip the sign even after naive averaging
        (simulates severe prompts-pool confusion from co-occurring objects);
      - 5 "conflict-weak" entries that disagree in sign but are only large
        enough to flip a naive full overwrite, not a naive average;
      - 8 small sign-consistent entries (ordinary reinforcing updates).
    """
    prior = np.array([1.0] * 10 + [-1.0] * 10)
    delta = np.zeros(20)

    delta[0:2] = 5.0  # critical, consistent
    delta[2:5] = -3.0  # conflict-strong (class-A side)
    delta[10:12] = 3.0  # conflict-strong (class-B side)
    delta[5:7] = -1.5  # conflict-weak (class-A side)
    delta[12:15] = 1.5  # conflict-weak (class-B side)
    delta[7:10] = 0.3  # small consistent (class-A side)
    delta[15:20] = -0.3  # small consistent (class-B side)

    return prior, delta


def test_fusion_rule_preserves_old_task_more_than_naive_strategies() -> None:
    prior, delta = _build_synthetic_scenario()
    fully_updated = prior + delta  # what a naive full overwrite would produce

    naive_overwrite = fully_updated
    naive_average = prior + 0.5 * delta  # blind averaging everywhere, no sign gating

    result = fuse_task_vectors(prior, delta, top_k_fraction=0.1, sparsity_threshold=None)
    real_fusion = result.fused_params

    old_unfused = _old_task_score(prior, prior)  # baseline: no update applied at all
    old_overwrite = _old_task_score(naive_overwrite, prior)
    old_average = _old_task_score(naive_average, prior)
    old_fusion = _old_task_score(real_fusion, prior)

    new_unfused = _new_task_score(prior, fully_updated)
    new_overwrite = _new_task_score(naive_overwrite, fully_updated)
    new_average = _new_task_score(naive_average, fully_updated)
    new_fusion = _new_task_score(real_fusion, fully_updated)

    print("\nstrategy          old-task score   new-task score")
    print(f"unfused (no-op)   {old_unfused:>13.3f}   {new_unfused:>13.3f}")
    print(f"naive overwrite   {old_overwrite:>13.3f}   {new_overwrite:>13.3f}")
    print(f"naive average     {old_average:>13.3f}   {new_average:>13.3f}")
    print(f"fuse_task_vectors {old_fusion:>13.3f}   {new_fusion:>13.3f}")

    # Qualitative pattern from the paper's ablation: naive fusion degrades the
    # old task the most; the real decision rule ends up closest to the
    # unfused baseline (here: fully recovers it), strictly beating both naive
    # strategies -- while naive averaging sits between the two extremes.
    assert old_overwrite < old_average < old_fusion
    assert old_fusion == pytest.approx(old_unfused)

    # The real rule is not "do nothing": it captures far more of the new
    # task's target direction than the unfused baseline, even though it
    # protects old knowledge more (and so trails the naive strategies, which
    # sacrifice old-task knowledge to chase the new task fully).
    assert new_fusion > new_unfused
    assert new_unfused < new_average < new_overwrite

    # Sanity on the returned bookkeeping counts.
    assert result.critical_preserved == 2
    assert result.kept_from_prior == 10  # the 5+5 conflicting (non-critical) entries
    assert result.averaged_sign_consistent == 8  # the 3+5 sign-consistent entries
    assert result.sparsity_applied == 0


def test_top_k_zero_and_no_sparsity_reduces_to_pure_sign_gated_averaging() -> None:
    prior = np.array([1.0, -1.0, 0.0])
    delta = np.array([0.5, -0.5, 3.0])  # all three are sign-consistent (0 treated as consistent)

    result = fuse_task_vectors(prior, delta, top_k_fraction=0.0, sparsity_threshold=None)

    expected = np.array([0.5 * (1.0 + 1.5), 0.5 * (-1.0 + -1.5), 0.5 * (0.0 + 3.0)])
    assert result.fused_params == pytest.approx(expected)
    assert result.critical_preserved == 0
    assert result.averaged_sign_consistent == 3
    assert result.kept_from_prior == 0
    assert result.sparsity_applied == 0

    # A genuine sign conflict with top_k_fraction=0 still falls through to
    # "keep prior" -- there is no critical carve-out to rescue it.
    conflict = fuse_task_vectors(np.array([1.0]), np.array([-5.0]), top_k_fraction=0.0)
    assert conflict.fused_params == pytest.approx(np.array([1.0]))
    assert conflict.kept_from_prior == 1
    assert conflict.critical_preserved == 0


def test_sparsity_threshold_zeroes_small_non_critical_entries() -> None:
    prior = np.array([0.01, 1.0, -0.02])
    delta = np.array([0.02, 5.0, 0.01])  # index 1 is critical (largest magnitude)

    result = fuse_task_vectors(prior, delta, top_k_fraction=1 / 3, sparsity_threshold=0.5)

    assert result.critical_preserved == 1
    assert result.fused_params[1] == pytest.approx(6.0)  # critical entry untouched by sparsity
    assert result.fused_params[0] == 0.0
    assert result.fused_params[2] == 0.0
    assert result.sparsity_applied == 2


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        fuse_task_vectors(np.array([1.0, 2.0]), np.array([1.0]))
    with pytest.raises(ValueError):
        fuse_task_vectors(np.array([1.0]), np.array([1.0]), top_k_fraction=1.5)
    with pytest.raises(ValueError):
        fuse_task_vectors(np.array([[1.0]]), np.array([[1.0]]))
