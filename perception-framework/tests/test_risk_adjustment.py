"""implements: AI-R-04"""

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.risk.adjustment import ObservationLevelAdjuster


def reg(kind, priority, cost_units):
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=f"{kind}-p",
        version="1",
        compatibility=CompatibilityProfile(priority=priority, cost=ResourceCost(compute_units=cost_units)),
        requirement=CapabilityRequirement(),
    )


def test_high_risk_requests_highest_available_level_first():
    registry = CapabilityRegistry()
    registry.register_local(reg("risk.rule_based", priority=1, cost_units=1))
    registry.register_local(reg("risk.timeseries_model", priority=1, cost_units=1))
    adjuster = ObservationLevelAdjuster(registry, ["risk.rule_based", "risk.timeseries_model"])

    result = adjuster.request_level(
        risk_level=0.9,
        evidence_sufficiency=0.9,
        risk_threshold=0.7,
        evidence_threshold=0.5,
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=10),
    )

    assert result.provider.capability_kind == "risk.timeseries_model"


def test_low_risk_and_sufficient_evidence_requests_cheapest_level_first():
    registry = CapabilityRegistry()
    registry.register_local(reg("risk.rule_based", priority=1, cost_units=1))
    registry.register_local(reg("risk.timeseries_model", priority=1, cost_units=1))
    adjuster = ObservationLevelAdjuster(registry, ["risk.rule_based", "risk.timeseries_model"])

    result = adjuster.request_level(
        risk_level=0.1,
        evidence_sufficiency=0.9,
        risk_threshold=0.7,
        evidence_threshold=0.5,
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=10),
    )

    assert result.provider.capability_kind == "risk.rule_based"


def test_never_requests_a_level_with_no_registered_provider():
    registry = CapabilityRegistry()
    registry.register_local(reg("risk.rule_based", priority=1, cost_units=1))
    adjuster = ObservationLevelAdjuster(registry, ["risk.rule_based", "risk.timeseries_model"])

    result = adjuster.request_level(
        risk_level=0.9,
        evidence_sufficiency=0.9,
        risk_threshold=0.7,
        evidence_threshold=0.5,
        node_tags=set(),
        budget=ResourceBudget(compute_units=10, memory_mb=10),
    )

    # "risk.timeseries_model" doesn't exist -> falls back to the one that does.
    assert result.provider.capability_kind == "risk.rule_based"
