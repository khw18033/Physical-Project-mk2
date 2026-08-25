"""tests for: AI-D-03
covers: request only existing sources, partial decision with stated gaps
"""

from ai_framework.contracts.capability import CapabilityRequirement
from ai_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from ai_framework.decision.info_request import DecisionSupportRequester, EvidenceNeed
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def reg(kind, provider_id, cost_units=1):
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version="1",
        compatibility=CompatibilityProfile(cost=ResourceCost(compute_units=cost_units)),
        requirement=CapabilityRequirement(),
    )


BUDGET = ResourceBudget(compute_units=10, memory_mb=512)


def test_only_currently_available_sources_are_requested():
    registry = CapabilityRegistry()
    registry.register_local(reg("perception.track_history", "tracker"))
    requester = DecisionSupportRequester(registry)

    plan = requester.plan(
        [
            EvidenceNeed("target_still_present", ("perception.track_history", "twin.environment")),
            EvidenceNeed("path_clear", ("twin.environment",)),  # no provider registered
        ],
        node_tags=set(),
        budget=BUDGET,
    )

    assert [r.capability_kind for r in plan.requests] == ["perception.track_history"]
    assert plan.unresolved == ("path_clear",)
    assert not plan.fully_supported


def test_missing_source_yields_stated_gap_not_an_exception():
    # 추가 정보가 없으면 확인 가능한 범위까지만 판단하고 부족한 근거를 명시한다 (AI-D-03).
    requester = DecisionSupportRequester(CapabilityRegistry())

    plan = requester.plan(
        [EvidenceNeed("path_clear", ("twin.environment",))], node_tags=set(), budget=BUDGET
    )

    assert plan.requests == ()
    assert plan.unresolved == ("path_clear",)


def test_first_usable_source_stops_the_search():
    registry = CapabilityRegistry()
    registry.register_local(reg("perception.track_history", "tracker"))
    registry.register_local(reg("perception.reobserve", "reobserver"))
    requester = DecisionSupportRequester(registry)

    plan = requester.plan(
        [EvidenceNeed("target_still_present", ("perception.track_history", "perception.reobserve"))],
        node_tags=set(),
        budget=BUDGET,
    )

    # 필요한 항목만 요청 — 둘 다 쓸 수 있어도 하나로 충분하면 하나만 요청한다.
    assert len(plan.requests) == 1
    assert plan.requests[0].provider_id == "tracker"


def test_evidence_without_any_declared_source_is_unresolved():
    registry = CapabilityRegistry()
    requester = DecisionSupportRequester(registry)

    plan = requester.plan_for_validation_gaps(
        missing_evidence=("unknown_precondition",),
        sources_by_evidence={},
        node_tags=set(),
        budget=BUDGET,
    )

    assert plan.unresolved == ("unknown_precondition",)


def test_over_budget_source_is_treated_as_unavailable():
    registry = CapabilityRegistry()
    registry.register_local(reg("vlm.analyze", "heavy-vlm", cost_units=1000))
    requester = DecisionSupportRequester(registry)

    plan = requester.plan(
        [EvidenceNeed("object_class", ("vlm.analyze",))],
        node_tags=set(),
        budget=ResourceBudget(compute_units=2, memory_mb=64),
    )

    assert plan.requests == ()
    assert plan.unresolved == ("object_class",)
