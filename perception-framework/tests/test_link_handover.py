"""implements: AI-N-03, AI-C-11, AI-C-13
tests: predictive reduction, asymmetric restoration, peer switching,
       link state reported separately, no radio/metric names leak
"""
import inspect

from perception_framework.ondevice import link_handover
from perception_framework.ondevice.link_handover import (
    LinkPosture, LinkSample, LinkTransitionPolicy,
)


def decline(policy, values, start=0.0, step=0.5, peer="edge-a", candidates=None):
    last = None
    for i, quality in enumerate(values):
        last = policy.observe(LinkSample(start + i * step, quality, peer), candidates)
    return last


def test_reduction_starts_before_the_link_is_actually_lost():
    policy = LinkTransitionPolicy()
    decision = decline(policy, [0.9, 0.8, 0.65, 0.5])
    assert decision.posture is LinkPosture.REDUCING
    assert decision.quality > policy.floor        # still usable when we act


def test_floor_forces_local_only():
    policy = LinkTransitionPolicy()
    decision = decline(policy, [0.9, 0.7, 0.5, 0.3, 0.2])
    assert decision.posture is LinkPosture.LOCAL_ONLY


def test_stable_link_does_not_reduce():
    policy = LinkTransitionPolicy()
    decision = decline(policy, [0.9, 0.88, 0.91, 0.9, 0.89])
    assert decision.posture is LinkPosture.REMOTE_OK


def test_restoration_is_slower_than_reduction():
    policy = LinkTransitionPolicy()
    decline(policy, [0.9, 0.6, 0.4, 0.2])
    assert policy.posture is LinkPosture.LOCAL_ONLY
    recovering = [0.9] * (policy.restore_hold_samples - 1)
    decision = decline(policy, recovering, start=10.0)
    assert decision.posture is LinkPosture.LOCAL_ONLY   # not yet
    decision = policy.observe(LinkSample(20.0, 0.9, "edge-a"))
    assert decision.posture is LinkPosture.REMOTE_OK


def test_a_disproved_reduction_widens_the_margin_instead_of_repeating():
    policy = LinkTransitionPolicy()
    lead_before = policy.reduction_lead_seconds
    decline(policy, [0.9, 0.7, 0.5])
    assert policy.posture is LinkPosture.REDUCING
    decline(policy, [0.95] * (policy.restore_hold_samples + 1), start=10.0)
    assert policy.posture is LinkPosture.REMOTE_OK
    assert policy.false_reductions == 1
    assert policy.reduction_lead_seconds < lead_before


def test_switch_is_only_suggested_for_a_clearly_better_peer():
    policy = LinkTransitionPolicy()
    marginal = policy.observe(LinkSample(0.0, 0.6, "edge-a"), [("edge-b", 0.65)])
    assert marginal.switch_to is None
    better = policy.observe(LinkSample(0.5, 0.6, "edge-a"), [("edge-b", 0.9)])
    assert better.switch_to == "edge-b"


def test_current_peer_is_never_suggested_as_its_own_replacement():
    policy = LinkTransitionPolicy()
    decision = policy.observe(LinkSample(0.0, 0.6, "edge-a"), [("edge-a", 0.99)])
    assert decision.switch_to is None


def test_link_state_is_reported_as_its_own_signal():
    policy = LinkTransitionPolicy()
    policy.observe(LinkSample(0.0, 0.8, "edge-a"))
    assert policy.status()["signal"] == "link_quality"


def test_no_radio_standard_or_metric_name_is_hardcoded():
    source = inspect.getsource(link_handover).lower()
    body = source.split('"""', 2)[-1]     # module docstring may cite context
    for term in ("rssi", "wifi", "wi-fi", "dbm", "snr", "802.11", "lte", "5g"):
        assert term not in body, f"{term} leaked into the implementation"
