"""implements: AI-C-05, AI-B-04, AI-B-09
reproduces (architectural claim, not the training procedure): HEAL, ICLR 2024
(docs/obsidian/papers/heal.md)
tests: a new heterogeneous provider joining a capability kind that already has
       collaborating providers never mutates their registrations, and is
       immediately usable alongside them

HEAL's own core mechanism -- "Backward Alignment" (freeze the shared fusion
network + detection head, train only the new agent's own encoder to match
that fixed back-end) -- is a neural *training procedure* and cannot be
reproduced as a decision rule the way CoAlign's classical solver could; there
is no fusion network to freeze here.

What HEAL's mechanism is *for*, though, is checkable in this framework's own
terms: "a new heterogeneous agent/model joins without requiring the already-
collaborating agents to be retrained or otherwise changed." This framework
never does joint feature-level fusion across providers at all -- each
provider is consumed independently behind the common `ProviderRegistration`
interface (AI-C-04) -- so it should trivially satisfy an even stronger form
of HEAL's claim: existing providers are not merely "not retrained", they are
not touched in any way. This test operationalizes and checks that claim
directly, rather than assuming it.
"""
from __future__ import annotations

import copy

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.selection.selector import CapabilitySelector

BUDGET = ResourceBudget(compute_units=100.0, memory_mb=8192.0)


def _agent(provider_id, hw_tags=("cpu",), priority=50):
    return ProviderRegistration(
        capability_kind="perception.detect",
        provider_id=provider_id,
        version="1",
        compatibility=CompatibilityProfile(
            required_hw_tags=hw_tags, priority=priority, cost=ResourceCost(compute_units=1.0),
        ),
        requirement=CapabilityRequirement(),
    )


def test_existing_agents_are_byte_for_byte_unchanged_when_a_new_heterogeneous_agent_joins():
    registry = CapabilityRegistry()
    homogeneous_a = _agent("lidar-agent-a", hw_tags=("cpu", "lidar"))
    homogeneous_b = _agent("lidar-agent-b", hw_tags=("cpu", "lidar"))
    registry.register_local(homogeneous_a)
    registry.register_local(homogeneous_b)

    # Snapshot before the new, differently-sensored ("heterogeneous") agent
    # joins -- HEAL's scenario is exactly this: agents already collaborating
    # on a shared task, then a new agent with a different sensor/model type
    # arrives.
    snapshot_a = copy.deepcopy(homogeneous_a)
    snapshot_b = copy.deepcopy(homogeneous_b)

    camera_agent_c = _agent("camera-agent-c", hw_tags=("cpu", "camera"))
    registry.register_local(camera_agent_c)

    still_registered_a = registry.available_providers("perception.detect")
    a_after = next(p for p in still_registered_a if p.provider_id == "lidar-agent-a")
    b_after = next(p for p in still_registered_a if p.provider_id == "lidar-agent-b")

    # No implicit "joint retraining" happened to the existing agents' own
    # registration state -- unlike HEAL's fusion network, there is nothing
    # here that *could* need to change.
    assert a_after == snapshot_a
    assert b_after == snapshot_b


def test_new_heterogeneous_agent_is_immediately_selectable_alongside_existing_ones():
    registry = CapabilityRegistry()
    registry.register_local(_agent("lidar-agent-a", hw_tags=("cpu", "lidar"), priority=50))
    registry.register_local(_agent("lidar-agent-b", hw_tags=("cpu", "lidar"), priority=50))
    registry.register_local(_agent("camera-agent-c", hw_tags=("cpu", "camera"), priority=10))

    selector = CapabilitySelector(registry)
    # A node with only a camera can now use the just-joined agent -- no
    # extra registration/alignment step is needed beyond `register_local`.
    result = selector.select("perception.detect", {"cpu", "camera"}, BUDGET)
    assert result.provider is not None and result.provider.provider_id == "camera-agent-c"

    # A node with only lidar still finds its original agents -- adding the
    # heterogeneous agent did not shrink their eligibility either.
    lidar_only = selector.select("perception.detect", {"cpu", "lidar"}, BUDGET)
    assert lidar_only.provider is not None and lidar_only.provider.provider_id in ("lidar-agent-a", "lidar-agent-b")


def test_departure_of_the_new_agent_leaves_the_originals_exactly_as_they_were():
    """The reverse direction of HEAL's claim: a heterogeneous agent leaving
    (AI-B-06 degrade path) must not require re-aligning the survivors either.
    """
    registry = CapabilityRegistry()
    registry.register_local(_agent("lidar-agent-a", hw_tags=("cpu", "lidar")))
    registry.register_local(_agent("camera-agent-c", hw_tags=("cpu", "camera")))
    before = copy.deepcopy(registry.available_providers("perception.detect"))

    registry.unregister_local("perception.detect", "camera-agent-c")

    after = registry.available_providers("perception.detect")
    assert [p.provider_id for p in after] == ["lidar-agent-a"]
    assert after[0] == next(p for p in before if p.provider_id == "lidar-agent-a")
