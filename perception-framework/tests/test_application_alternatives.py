"""implements: AI-C-13, AI-O-02, AI-C-05

`ZoneApplication.resolve()` carries the selector's per-candidate outcomes
through to `CapabilityResolution.alternatives` (P1, 2026-09-17) so a consumer
of the resolution table sees what was considered, not only what won.
"""
from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import CompatibilityProfile, DeploymentProfile, ResourceBudget, ResourceCost
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.runtime.application import CapabilitySpec, ZoneApplication
from perception_framework.selection.selector import CandidateOutcome


def _reg(kind, pid, *, priority, units, hw=()):
    return ProviderRegistration(
        capability_kind=kind, provider_id=pid, version="1",
        compatibility=CompatibilityProfile(required_hw_tags=hw, priority=priority,
                                           cost=ResourceCost(compute_units=units)),
        requirement=CapabilityRequirement(),
    )


def _app(registry, kinds):
    profile = DeploymentProfile(domain_id="t", active_capability_kinds=tuple(k for k, _ in kinds))
    return ZoneApplication(profile, registry, [CapabilitySpec(k, is_core=core) for k, core in kinds])


def test_resolution_carries_alternatives_for_a_selected_kind():
    registry = CapabilityRegistry()
    registry.register_local(_reg("perception.classify", "gpu", priority=1, units=2, hw=("compute.gpu",)))
    registry.register_local(_reg("perception.classify", "cpu", priority=5, units=2))
    app = _app(registry, [("perception.classify", True)])

    res = app.resolve(ResourceBudget(compute_units=10, memory_mb=1024))["perception.classify"]

    assert res.provider.provider_id == "cpu"
    assert res.alternatives == (CandidateOutcome("gpu", "required_hw_tag_missing:compute.gpu"),)


def test_resolution_carries_alternatives_when_nothing_could_be_placed():
    registry = CapabilityRegistry()
    registry.register_local(_reg("perception.depth", "heavy", priority=1, units=100))
    app = _app(registry, [("perception.depth", False)])

    res = app.resolve(ResourceBudget(compute_units=5, memory_mb=1024))["perception.depth"]

    assert res.provider is None
    assert res.reason == "no_compatible_provider_within_budget"
    assert res.alternatives == (CandidateOutcome("heavy", "over_budget"),)


def test_kind_decided_before_selection_has_no_alternatives():
    app = ZoneApplication(
        DeploymentProfile(domain_id="t", active_capability_kinds=("a",)),
        CapabilityRegistry(),
        [CapabilitySpec("a", requirement=CapabilityRequirement(required=("x",)))],
    )
    res = app.resolve(ResourceBudget(1, 1))["a"]

    assert res.reason == "missing_required:x"
    assert res.alternatives == ()
