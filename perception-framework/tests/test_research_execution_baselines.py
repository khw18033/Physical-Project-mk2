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
    OctoCrossTransferPolicy,
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


def test_octocross_resolves_feasible_overload_and_conserves_total_load():
    predicted_load = {"cam-a": 150.0, "cam-b": 50.0, "cam-c": 30.0}
    capacity = {"cam-a": 100.0, "cam-b": 100.0, "cam-c": 100.0}
    allowed_edges = {("cam-a", "cam-b"), ("cam-a", "cam-c")}

    plan = OctoCrossTransferPolicy().plan(predicted_load, capacity, allowed_edges)
    print("feasible plan transfers:", plan.transfers)
    print("feasible plan resulting_load:", plan.resulting_load)

    assert plan.overloaded_nodes == ()
    assert plan.reason == "capacity_feasible"
    assert plan.resulting_load["cam-a"] <= capacity["cam-a"] + 1e-9
    assert sum(plan.resulting_load.values()) == pytest.approx(sum(predicted_load.values()))
    assert plan.transfers  # a real transfer plan was produced, not a no-op


def test_octocross_reports_genuinely_infeasible_overload_without_fabricating_success():
    # Total capacity (100 + 30 + 30 = 160) is below total predicted load (240), so
    # the topology cannot possibly absorb the overload -- the policy must say so.
    # (cam-b/cam-c still have some spare headroom, so this is "not enough", not
    # "no reachable headroom at all" -- that disconnected case is tested separately.)
    predicted_load = {"cam-a": 200.0, "cam-b": 20.0, "cam-c": 20.0}
    capacity = {"cam-a": 100.0, "cam-b": 30.0, "cam-c": 30.0}
    allowed_edges = {("cam-a", "cam-b"), ("cam-a", "cam-c")}

    plan = OctoCrossTransferPolicy().plan(predicted_load, capacity, allowed_edges)
    print("infeasible plan transfers:", plan.transfers)
    print("infeasible plan resulting_load:", plan.resulting_load)
    print("infeasible plan overloaded_nodes:", plan.overloaded_nodes)

    assert plan.overloaded_nodes != ()
    assert plan.reason == "insufficient_reachable_capacity"
    # It still does its best: no node ends up over its own capacity plus what is
    # mathematically unavoidable, and total load is still conserved.
    for node in predicted_load:
        assert plan.resulting_load[node] <= max(predicted_load[node], capacity[node]) + 1e-6
    assert sum(plan.resulting_load.values()) == pytest.approx(sum(predicted_load.values()))
    # It did not simply give up -- overload on cam-a is reduced vs. the raw prediction.
    assert plan.resulting_load["cam-a"] < predicted_load["cam-a"]


def test_octocross_leaves_disconnected_overloaded_node_overloaded_without_raising():
    predicted_load = {"cam-a": 150.0, "cam-b": 50.0}
    capacity = {"cam-a": 100.0, "cam-b": 100.0}
    allowed_edges: set[tuple[str, str]] = set()  # cam-a has no outgoing edge at all

    plan = OctoCrossTransferPolicy().plan(predicted_load, capacity, allowed_edges)
    print("disconnected plan transfers:", plan.transfers)
    print("disconnected plan overloaded_nodes:", plan.overloaded_nodes)

    assert plan.overloaded_nodes == ("cam-a",)
    assert plan.reason == "no_reachable_headroom"
    assert plan.transfers == {}
    assert plan.resulting_load == predicted_load
