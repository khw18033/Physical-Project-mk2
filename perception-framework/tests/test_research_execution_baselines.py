"""implements: AI-B-01, AI-B-04, AI-B-06, AI-B-08, AI-O-01, AI-C-04, AI-C-09, AI-C-12, AI-C-13"""

import pytest

from perception_framework.selection.research_execution_baselines import (
    ApproxDetSlaPolicy,
    ApproximationProfile,
    CallableLatencyPredictor,
    DaccOffloadPolicy,
    E4Profile,
    E4ProfilePolicy,
    LatencyPredictor,
    OctopinfPlacementPolicy,
)


def _profile(profile_id: str, quality: float, latency: float) -> ApproximationProfile:
    return ApproximationProfile(profile_id, 1.0, 100, 1.0, 1, 1.0, quality, {"latency": latency})


def test_latency_predictor_adapter_contract_and_validation():
    predictor = CallableLatencyPredictor(lambda features, context: features["ops"] / context["rate"])
    assert isinstance(predictor, LatencyPredictor)
    assert predictor.predict_ms({"ops": 20}, {"rate": 4}) == 5
    with pytest.raises(ValueError):
        CallableLatencyPredictor(lambda _f, _c: -1).predict_ms({}, {})


def test_approxdet_selects_quality_within_sla_and_has_fallback():
    predictor = CallableLatencyPredictor(lambda features, _context: features["latency"])
    profiles = [_profile("fast", .6, 5), _profile("balanced", .8, 10), _profile("best", .9, 30)]
    decision = ApproxDetSlaPolicy(predictor).select(profiles, context={"system_load": .4}, max_latency_ms=12)
    assert (decision.profile.profile_id, decision.sla_met) == ("balanced", True)
    fallback = ApproxDetSlaPolicy(predictor).select(profiles, context={"system_load": .9}, max_latency_ms=12, max_load=.8)
    assert (fallback.profile.profile_id, fallback.sla_met, fallback.reason) == ("fast", False, "minimum_latency_fallback")


def test_dacc_uses_content_and_network_and_degrades_locally():
    policy = DaccOffloadPolicy()
    remote = policy.decide(content_complexity=.8, local_latency_ms=80, remote_compute_ms=20,
                           payload_mib=1, bandwidth_mib_s=100, round_trip_ms=5, max_latency_ms=100)
    assert remote.execution_site == "remote"
    local = policy.decide(content_complexity=.8, local_latency_ms=80, remote_compute_ms=20,
                          payload_mib=1, bandwidth_mib_s=100, round_trip_ms=5, max_latency_ms=100,
                          remote_available=False)
    assert (local.execution_site, local.reason) == ("local", "remote_unavailable")


def test_octopinf_maximizes_batch_under_sla_and_memory():
    decision = OctopinfPlacementPolicy().decide(queue_depth=8, per_item_ms=2, batch_sizes=[1, 2, 4, 8],
                                                 max_latency_ms=8, available_memory_mib=40,
                                                 memory_per_item_mib=10, transfer_ms=3)
    assert decision.batch_size == 4
    assert decision.colocate is True
    assert decision.reason == "largest_batch_within_sla"
    with pytest.raises(ValueError):
        OctopinfPlacementPolicy().decide(queue_depth=1, per_item_ms=1, batch_sizes=[4], max_latency_ms=5,
                                         available_memory_mib=1, memory_per_item_mib=1, transfer_ms=1)


def test_e4_selects_low_energy_feasible_profile_and_reports_failure():
    profiles = [
        E4Profile("early-low", 1, 1, .70, 5, 2),
        E4Profile("middle-low", 2, 1, .85, 9, 4),
        E4Profile("deep-high", 3, 3, .95, 18, 12),
    ]
    selected = E4ProfilePolicy().select(profiles, min_quality=.8, max_latency_ms=10, max_energy_mj=5)
    assert (selected.profile.profile_id, selected.constraints_met) == ("middle-low", True)
    failed = E4ProfilePolicy().select(profiles, min_quality=.99, max_latency_ms=3, max_energy_mj=1)
    assert failed.constraints_met is False
    assert failed.reason == "least_normalized_constraint_violation"
