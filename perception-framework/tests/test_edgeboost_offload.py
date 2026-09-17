"""implements: AI-E-04, AI-S-05
reproduces (decision rule only): EdgeBoost, Computer Networks 2025
(docs/obsidian/papers/edgeboost.md)
tests: temperature scaling monotonicity, margin-threshold offload
       monotonicity, and the paper's core claim (offloading only
       low-margin predictions recovers most of the accuracy gap to a
       "strong model" while offloading far fewer than 100% of examples)

No CIFAR-100/MobileNetV3/EfficientNetV2 available locally, so -- same
posture as the CoAlign reproduction -- this uses synthetic logits with a
controlled "easy vs. hard" example split standing in for a real weak local
model's actual confusion pattern, and checks the *qualitative* claim, not
the paper's reported accuracy numbers.
"""
from __future__ import annotations

import math
import random

import pytest

from perception_framework.selection.research_execution_baselines import EdgeBoostOffloadPolicy


def test_calibrate_is_a_valid_probability_distribution():
    policy = EdgeBoostOffloadPolicy()
    probs = policy.calibrate([2.0, 0.5, -1.0])
    assert abs(sum(probs) - 1.0) < 1e-9
    assert all(p >= 0 for p in probs)


def test_higher_temperature_flattens_the_distribution_and_lowers_margin():
    logits = [4.0, 1.0, 0.5]
    sharp = EdgeBoostOffloadPolicy(temperature=0.5).decide(logits, margin_threshold=0.0)
    normal = EdgeBoostOffloadPolicy(temperature=1.0).decide(logits, margin_threshold=0.0)
    flat = EdgeBoostOffloadPolicy(temperature=5.0).decide(logits, margin_threshold=0.0)
    assert sharp.margin > normal.margin > flat.margin


def test_confident_peaked_logits_stay_local_ambiguous_ones_offload():
    policy = EdgeBoostOffloadPolicy()
    confident = policy.decide([5.0, 0.1, 0.1], margin_threshold=0.3)
    assert not confident.offload and confident.reason == "margin_within_local_budget"

    ambiguous = policy.decide([1.0, 0.95, 0.1], margin_threshold=0.3)
    assert ambiguous.offload and ambiguous.reason == "low_confidence_margin"


@pytest.mark.parametrize("threshold_pair", [(0.1, 0.5), (0.3, 0.7), (0.05, 0.9)])
def test_offload_rate_is_monotone_nondecreasing_in_threshold(threshold_pair):
    """A higher confidence bar can only ever offload the same examples or
    more -- never fewer. This is the tradeoff knob EdgeBoost's system tunes
    to trade communication for accuracy.
    """
    low_t, high_t = threshold_pair
    policy = EdgeBoostOffloadPolicy()
    rng = random.Random(0)
    batch = [[rng.uniform(-2, 5) for _ in range(5)] for _ in range(200)]

    offload_low = sum(policy.decide(l, margin_threshold=low_t).offload for l in batch)
    offload_high = sum(policy.decide(l, margin_threshold=high_t).offload for l in batch)
    assert offload_high >= offload_low


# -- the paper's core claim: selective offload recovers most of the accuracy
#    gap to a strong model while offloading far fewer than 100% of traffic --

def _synthetic_batch(n, *, hard_fraction, rng):
    """`n` examples, each (true_label, local_logits, local_is_correct).

    Easy examples: local model is confident and correct (peaked logits on
    the true class). Hard examples: local model is uncertain (near-tied
    top-2) and wrong more often than not -- standing in for a real weak
    on-device model's actual failure mode on genuinely ambiguous inputs.
    """
    batch = []
    for _ in range(n):
        is_hard = rng.random() < hard_fraction
        true_label = 0
        if not is_hard:
            logits = [4.0 + rng.uniform(-0.5, 0.5), 0.2, 0.1]
            local_correct = True
        else:
            # Near-tied top-2, and wrong more often than right on this subset.
            logits = [1.0 + rng.uniform(-0.2, 0.2), 0.95 + rng.uniform(-0.2, 0.2), 0.1]
            local_correct = rng.random() < 0.35
        batch.append((true_label, logits, local_correct))
    return batch


def test_selective_offload_recovers_most_of_the_accuracy_gap_at_a_fraction_of_full_offload():
    rng = random.Random(42)
    policy = EdgeBoostOffloadPolicy()
    batch = _synthetic_batch(500, hard_fraction=0.3, rng=rng)
    # A "strong model" (cloud/edge-strong) is treated as always correct on
    # whatever gets sent to it -- the same idealization the CoAlign
    # reproduction used for locally-perfect detection, documented rather
    # than hidden.
    threshold = 0.3

    local_only_correct = sum(1 for _, _, correct in batch if correct)
    edgeboost_correct = 0
    offloaded = 0
    for _, logits, local_correct in batch:
        decision = policy.decide(logits, margin_threshold=threshold)
        if decision.offload:
            offloaded += 1
            edgeboost_correct += 1  # strong model assumed correct
        else:
            edgeboost_correct += int(local_correct)

    n = len(batch)
    local_only_acc = local_only_correct / n
    edgeboost_acc = edgeboost_correct / n
    offload_rate = offloaded / n

    print(
        f"\nlocal-only accuracy: {local_only_acc:.3f}, "
        f"EdgeBoost accuracy: {edgeboost_acc:.3f}, "
        f"offload rate: {offload_rate:.3f} (vs. 1.0 for cloud-only)"
    )

    # Core claim: selective offload measurably improves on local-only...
    assert edgeboost_acc > local_only_acc
    # ...while touching only a fraction of traffic, not everything.
    assert offload_rate < 0.6
    # ...and gets close to "always correct" (the cloud-only ceiling) despite that.
    assert edgeboost_acc > 0.9
