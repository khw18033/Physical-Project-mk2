"""tests for: AI-B-01, AI-B-04, AI-B-06, AI-C-13"""

from ai_framework.contracts.capability import CapabilityRequirement
from ai_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from ai_framework.selection.selector import CapabilitySelector


def reg_of(kind, provider_id, priority, cost_units, hw=()):
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version="1",
        compatibility=CompatibilityProfile(
            required_hw_tags=hw,
            priority=priority,
            cost=ResourceCost(compute_units=cost_units),
        ),
        requirement=CapabilityRequirement(),
    )


def test_select_returns_none_without_exception_when_nothing_registered():
    registry = CapabilityRegistry()
    selector = CapabilitySelector(registry)

    result = selector.select("perception.distance", node_tags=set(), budget=ResourceBudget(1, 1))

    assert result.provider is None
    assert result.reason == "no_provider_registered"


def test_select_excludes_provider_whose_required_hw_tag_is_absent():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "gpu-model", priority=10, cost_units=8, hw=("gpu",)))
    registry.register_local(reg_of("perception.classify", "cpu-model", priority=50, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select(
        "perception.classify", node_tags=set(), budget=ResourceBudget(compute_units=10, memory_mb=1024)
    )

    # gpu-model has higher priority (lower number) but this node has no
    # "gpu" tag, so the compatible cpu-model must be chosen instead.
    assert result.provider.provider_id == "cpu-model"


def test_select_prefers_lower_priority_number_among_compatible_providers():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "gpu-model", priority=10, cost_units=8, hw=("gpu",)))
    registry.register_local(reg_of("perception.classify", "cpu-model", priority=50, cost_units=2))
    selector = CapabilitySelector(registry)

    result = selector.select(
        "perception.classify", node_tags={"gpu"}, budget=ResourceBudget(compute_units=10, memory_mb=1024)
    )

    assert result.provider.provider_id == "gpu-model"


def test_select_excludes_provider_over_budget():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("perception.classify", "heavy", priority=1, cost_units=100))
    selector = CapabilitySelector(registry)

    result = selector.select(
        "perception.classify", node_tags=set(), budget=ResourceBudget(compute_units=5, memory_mb=1024)
    )

    assert result.provider is None
    assert result.reason == "no_compatible_provider_within_budget"


def test_degrade_falls_through_ordered_capability_kinds():
    registry = CapabilityRegistry()
    registry.register_local(reg_of("risk.timeseries_model", "heavy-model", priority=1, cost_units=100))
    registry.register_local(reg_of("risk.rule_based", "cheap-rules", priority=1, cost_units=1))
    selector = CapabilitySelector(registry)

    result = selector.select_with_degrade(
        ["risk.timeseries_model", "risk.rule_based"],
        node_tags=set(),
        budget=ResourceBudget(compute_units=5, memory_mb=64),
    )

    # The richer capability kind is over budget; selector falls through
    # to the next, more conservative kind instead of returning nothing
    # (AI-B-06 단계적 축소).
    assert result.provider.provider_id == "cheap-rules"


def test_degrade_returns_none_when_every_kind_is_unusable():
    registry = CapabilityRegistry()
    selector = CapabilitySelector(registry)

    result = selector.select_with_degrade(
        ["risk.timeseries_model", "risk.rule_based"], node_tags=set(), budget=ResourceBudget(1, 1)
    )

    assert result.provider is None
