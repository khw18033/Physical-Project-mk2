"""implements: AI-C-16, AI-C-11, AI-B-04
covers: egress declared in registration information, closed-network
        profile filters egress providers before placement, connected
        profile keeps them, unrelated capabilities unaffected by the
        exclusion, non-optional egress rejected explicitly
"""

import pytest

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import (
    CompatibilityProfile,
    DeploymentProfile,
    ResourceBudget,
    ResourceCost,
)
from perception_framework.contracts.profile_loader import profile_from_dict
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.runtime.airgap import AirgapViolation, EgressGate
from perception_framework.runtime.application import CapabilitySpec, ZoneApplication
from perception_framework.selection.selector import CapabilitySelector

BUDGET = ResourceBudget(compute_units=100, memory_mb=4096)


def reg_of(kind, provider_id, *, endpoints=(), optional=True, cost=1.0, priority=100):
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version="1",
        compatibility=CompatibilityProfile(
            priority=priority,
            cost=ResourceCost(compute_units=cost),
            external_endpoints=tuple(endpoints),
            external_optional=optional,
        ),
        requirement=CapabilityRequirement(),
    )


def registry_with(*regs):
    registry = CapabilityRegistry()
    for reg in regs:
        registry.register_local(reg)
    return registry


# --- registration information reveals the requirement (AI-C-16) -----------
def test_default_registration_declares_no_external_connection():
    """Backward compatibility: an existing registration means 'no egress'."""
    profile = CompatibilityProfile()
    assert profile.external_endpoints == ()
    assert profile.requires_external_connection() is False


def test_registration_reveals_declared_external_reach():
    reg = reg_of("perception.vlm", "remote-vlm", endpoints=("https://vlm.public.example/v1",))
    assert reg.compatibility.requires_external_connection() is True


# --- pre-placement filtering ---------------------------------------------
def test_closed_network_does_not_select_provider_requiring_egress():
    gate = EgressGate(closed_network=True, internal_endpoints=frozenset({".internal.example"}))
    registry = registry_with(
        reg_of("perception.vlm", "remote-vlm", endpoints=("https://vlm.public.example/v1",))
    )
    selector = CapabilitySelector(registry, placement_filter=gate.rejection_reason)

    result = selector.select("perception.vlm", node_tags=set(), budget=BUDGET)

    assert result.provider is None
    assert result.reason == "external_connection_unavailable_in_closed_network"


def test_connected_profile_selects_the_same_provider():
    gate = EgressGate(closed_network=False)
    registry = registry_with(
        reg_of("perception.vlm", "remote-vlm", endpoints=("https://vlm.public.example/v1",))
    )
    selector = CapabilitySelector(registry, placement_filter=gate.rejection_reason)

    result = selector.select("perception.vlm", node_tags=set(), budget=BUDGET)

    assert result.provider is not None
    assert result.provider.provider_id == "remote-vlm"


def test_endpoint_inside_the_closed_network_is_allowed():
    gate = EgressGate(closed_network=True, internal_endpoints=frozenset({".internal.example"}))
    registry = registry_with(
        reg_of("perception.vlm", "zone-vlm", endpoints=("https://vlm.edge.internal.example/v1",))
    )
    selector = CapabilitySelector(registry, placement_filter=gate.rejection_reason)

    assert selector.select("perception.vlm", set(), BUDGET).provider is not None


def test_egress_provider_is_dropped_but_a_local_peer_still_wins_the_same_kind():
    gate = EgressGate(closed_network=True)
    registry = registry_with(
        reg_of("perception.vlm", "remote-vlm", endpoints=("https://vlm.public.example",), priority=10),
        reg_of("perception.vlm", "local-vlm", priority=50),
    )
    selector = CapabilitySelector(registry, placement_filter=gate.rejection_reason)

    result = selector.select("perception.vlm", set(), BUDGET)

    assert result.provider.provider_id == "local-vlm"


# --- isolation: only the egress capability is disabled (AI-C-11) ----------
def test_excluding_an_egress_provider_does_not_block_unrelated_capabilities():
    gate = EgressGate(closed_network=True)
    registry = registry_with(
        reg_of("perception.vlm", "remote-vlm", endpoints=("https://vlm.public.example",)),
        reg_of("perception.detection", "local-detector"),
        reg_of("risk.rule_based", "local-rules"),
    )
    selector = CapabilitySelector(registry, placement_filter=gate.rejection_reason)

    assert selector.select("perception.vlm", set(), BUDGET).provider is None
    assert selector.select("perception.detection", set(), BUDGET).provider is not None
    assert selector.select("risk.rule_based", set(), BUDGET).provider is not None


def test_zone_application_disables_only_the_egress_capability():
    """The whole assembly keeps running with the external service off."""
    profile = DeploymentProfile(
        domain_id="any",
        active_capability_kinds=("perception.detection", "perception.vlm"),
        closed_network=True,
    )
    registry = registry_with(
        reg_of("perception.detection", "local-detector"),
        reg_of("perception.vlm", "remote-vlm", endpoints=("https://vlm.public.example",)),
    )
    app = ZoneApplication(
        profile,
        registry,
        [
            CapabilitySpec("perception.detection", is_core=True),
            CapabilitySpec("perception.vlm", is_core=False, degrade_rank=1),
        ],
    )

    resolutions = app.resolve(BUDGET)

    assert resolutions["perception.detection"].is_running
    assert not resolutions["perception.vlm"].is_running
    assert resolutions["perception.vlm"].reason == (
        "external_connection_unavailable_in_closed_network"
    )
    assert app.core_kinds_running()


def test_same_deployment_uses_the_external_service_when_not_closed():
    profile = DeploymentProfile(
        domain_id="any",
        active_capability_kinds=("perception.vlm",),
        closed_network=False,
    )
    registry = registry_with(
        reg_of("perception.vlm", "remote-vlm", endpoints=("https://vlm.public.example",))
    )
    app = ZoneApplication(profile, registry, [CapabilitySpec("perception.vlm")])

    assert app.resolve(BUDGET)["perception.vlm"].is_running


# --- non-optional egress is a declaration error, detected before placement -
def test_non_optional_egress_is_reported_as_blocking_not_as_reduction():
    gate = EgressGate(closed_network=True)
    reg = reg_of(
        "perception.vlm", "mandatory-remote",
        endpoints=("https://vlm.public.example",), optional=False,
    )

    verdict = gate.evaluate(reg.provider_id, reg.compatibility)

    assert verdict.placeable is False
    assert verdict.blocking_dependencies == ("https://vlm.public.example",)
    assert gate.rejection_reason(reg) == "external_connection_required_in_closed_network"


def test_assert_declarations_detects_the_violation_before_placement():
    gate = EgressGate(closed_network=True)
    regs = [
        reg_of("perception.detection", "local-detector"),
        reg_of(
            "perception.vlm", "mandatory-remote",
            endpoints=("https://vlm.public.example",), optional=False,
        ),
    ]

    with pytest.raises(AirgapViolation) as excinfo:
        gate.assert_declarations(regs)
    assert "mandatory-remote" in str(excinfo.value)

    # An all-optional registration set passes the same pre-placement check.
    gate.assert_declarations([regs[0]])


# --- profile data --------------------------------------------------------
def test_profile_defaults_to_closed_network_and_loader_round_trips_the_flag():
    default = profile_from_dict({"domain_id": "d", "active_capability_kinds": ["k"]})
    assert default.closed_network is True
    assert default.internal_endpoints == ()

    connected = profile_from_dict(
        {
            "domain_id": "d",
            "active_capability_kinds": ["k"],
            "closed_network": False,
            "internal_endpoints": [".internal.example"],
        }
    )
    assert connected.closed_network is False
    assert connected.internal_endpoints == (".internal.example",)
    assert EgressGate.from_profile(connected).closed_network is False
