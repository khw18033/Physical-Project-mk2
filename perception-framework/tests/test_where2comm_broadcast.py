"""implements: AI-E-04, AI-C-06
reproduces (decision rule only): Where2comm, NeurIPS 2022
(docs/obsidian/papers/where2comm.md)
tests: sparse selection recovers true "object" regions at a fraction of full
       broadcast volume, request-map narrowing behaves as verified from the
       original paper (sender confidence gates first, receiver only narrows),
       and the paper's headline "orders-of-magnitude fewer regions, high
       recall" claim reproduces qualitatively on a synthetic confidence map

No OPV2V/V2X-Sim/DAIR-V2X/CoPerception-UAVs data locally, so this uses a
synthetic per-region confidence map with a small number of true "object"
cells standing in for a real detector's spatial confidence output -- same
posture as the other reproductions in this project: the decision rule is
checked, not the paper's reported AP numbers.
"""
from __future__ import annotations

import random

from perception_framework.selection.research_execution_baselines import Where2commBroadcastPolicy


def _synthetic_confidence_map(n_regions, object_indices, rng, *, object_conf=(0.8, 1.0), bg_conf=(0.0, 0.15)):
    values = []
    object_set = set(object_indices)
    for i in range(n_regions):
        lo, hi = object_conf if i in object_set else bg_conf
        values.append(rng.uniform(lo, hi))
    return values


def test_round0_selects_sender_confidence_top_k_only():
    policy = Where2commBroadcastPolicy()
    conf = [0.1, 0.9, 0.3, 0.95, 0.2]
    result = policy.select_round0(conf, keep_fraction=0.4)
    assert result.communication_volume == 2
    assert set(result.selected_indices) == {1, 3}  # the two highest-confidence regions
    assert result.reason == "sender_confidence_top_k"


def test_broadcast_volume_shrinks_by_the_declared_reduction_factor():
    policy = Where2commBroadcastPolicy()
    conf = [0.5] * 1000
    result = policy.select_round0(conf, keep_fraction=0.01)
    assert result.communication_volume == 10
    assert result.reduction_factor == 100.0


def test_selective_broadcast_recovers_true_object_regions_at_a_fraction_of_volume():
    """The paper's core efficiency claim: sparse selection driven by
    confidence should land almost entirely on the regions that actually
    matter (objects), not spend budget on background.
    """
    rng = random.Random(0)
    n_regions = 2000
    object_indices = rng.sample(range(n_regions), k=20)  # objects are 1% of the space
    conf = _synthetic_confidence_map(n_regions, object_indices, rng)

    policy = Where2commBroadcastPolicy()
    # Ask for only 2x the true object count -- far less than full broadcast.
    result = policy.select_round0(conf, keep_fraction=len(object_indices) * 2 / n_regions)

    recovered = set(result.selected_indices) & set(object_indices)
    recall = len(recovered) / len(object_indices)

    print(
        f"\nregions: {n_regions}, true objects: {len(object_indices)}, "
        f"broadcast volume: {result.communication_volume} "
        f"({result.reduction_factor:.0f}x smaller than full broadcast), "
        f"object recall: {recall:.2f}"
    )

    assert recall >= 0.9
    assert result.reduction_factor > 40  # comfortably "orders of magnitude" smaller


def test_receiver_request_narrows_but_never_overrides_sender_confidence():
    """Verified mechanism check: a region the sender is confident about but
    the receiver already covers well (high receiver confidence too) should
    rank below a region the sender is equally confident about but the
    receiver is missing -- request map narrows among sender-confident
    regions, it does not introduce regions the sender wasn't confident
    about in the first place.
    """
    policy = Where2commBroadcastPolicy()
    sender_conf = [0.9, 0.9, 0.1]  # region 2 sender is not confident about at all
    receiver_conf_needs_help = [0.9, 0.1, 0.9]  # receiver already has region0, lacks region1, has region2

    result = policy.select_round1(sender_conf, receiver_conf_needs_help, keep_fraction=1 / 3)
    # Only region 1 is both sender-confident AND receiver-lacking.
    assert result.selected_indices == (1,)


def test_gating_is_multiplicative_not_receiver_need_alone():
    """Makes the multiplicative gate's consequence explicit with numbers
    that do not favor either factor: region 0 has a much higher receiver
    request (1.0) but a very low sender confidence (0.05, gated=0.05);
    region 1 has a lower request (0.1) but high sender confidence (0.9,
    gated=0.09) -- the product still picks region 1, showing the receiver's
    need alone cannot win against a sender that has little to offer.
    """
    policy = Where2commBroadcastPolicy()
    sender_conf = [0.05, 0.9]
    receiver_conf = [0.0, 0.9]
    result = policy.select_round1(sender_conf, receiver_conf, keep_fraction=0.5)
    assert result.selected_indices == (1,)
