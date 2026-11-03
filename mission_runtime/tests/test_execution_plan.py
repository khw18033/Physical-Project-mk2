"""implements: AI-B-03, AI-C-13, AI-O-02, AI-O-03

`runtime/execution_plan.py` ties one request's resolution table and placement
actions to one plan_id (+ optional correlation_id / requester) without deciding
anything itself and without persisting anything (storage is the backend's).
"""
from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.contracts.profile import CompatibilityProfile, ResourceCost
from mission_runtime.registry.capability_registry import ProviderRegistration
from mission_runtime.runtime.application import CapabilityResolution
from mission_runtime.runtime.execution_plan import ExecutionPlanLog, Requester, build_plan
from mission_runtime.runtime.placement import PlacementAction
from mission_runtime.selection.selector import CandidateOutcome


def _reg(kind, pid):
    return ProviderRegistration(capability_kind=kind, provider_id=pid, version="1",
                                compatibility=CompatibilityProfile(cost=ResourceCost(compute_units=1)),
                                requirement=CapabilityRequirement())


def _table():
    return {
        "perception.detect": CapabilityResolution(
            "perception.detect", CapabilityState.ACTIVE, _reg("perception.detect", "rpn"), "selected",
            (CandidateOutcome("rpn-b", "compatible"),),
        ),
        "perception.depth": CapabilityResolution(
            "perception.depth", CapabilityState.DISABLED, None, "no_provider_registered"
        ),
    }


def test_plan_wraps_resolutions_and_actions_under_one_id():
    actions = (PlacementAction("perception.detect", "rpn", "start", True),)
    plan = build_plan("door_detection", _table(), actions,
                      correlation_id="corr-1", requester=Requester("operator", "u1"),
                      node_id="edge-gpu", clock=lambda: 100.0, plan_id="plan-x")

    assert plan.plan_id == "plan-x" and plan.created_at == 100.0
    assert plan.served_kinds == ("perception.detect",)
    assert plan.unserved_kinds == ("perception.depth",)
    d = plan.as_dict()
    assert d["correlation_id"] == "corr-1" and d["requester"] == {"role": "operator", "id": "u1"}
    assert d["resolutions"][0]["provider_id"] == "rpn"
    assert d["resolutions"][0]["alternatives"] == [{"provider_id": "rpn-b", "reason": "compatible"}]
    assert d["resolutions"][1] == {"kind": "perception.depth", "state": "DISABLED", "provider_id": None,
                                   "reason": "no_provider_registered", "alternatives": []}
    assert d["placement_actions"] == [{"kind": "perception.detect", "provider_id": "rpn", "command": "start",
                                       "accepted": True, "rejection_reason": None}]


def test_plan_id_is_generated_and_unique_by_default():
    a = build_plan("f", _table()); b = build_plan("f", _table())
    assert a.plan_id != b.plan_id and a.plan_id.startswith("plan-")


def test_log_keeps_a_window_and_finds_by_correlation():
    log = ExecutionPlanLog(capacity=2)
    p1 = log.record(build_plan("f", _table(), correlation_id="c", plan_id="p1"))
    p2 = log.record(build_plan("f", _table(), correlation_id="c", plan_id="p2"))
    p3 = log.record(build_plan("f", _table(), correlation_id="d", plan_id="p3"))

    assert len(log) == 2 and log.get("p1") is None          # oldest evicted
    assert [p.plan_id for p in log.latest()] == ["p3", "p2"]  # newest first
    assert log.by_correlation("c") == (p2,)
    assert log.by_correlation("zzz") == ()
    assert p1 is not None


def test_as_dict_is_language_neutral_ids_only():
    d = build_plan("f", _table()).as_dict()
    text = str(d)
    assert "가능" not in text and "Available" not in text  # no display strings ever
