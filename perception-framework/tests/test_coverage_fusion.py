"""implements: AI-S-03, AI-B-04, AI-C-10
tests: source-id collision across terminals, blind spots survive fusion,
       edge-only placement, network-arrival-shaped registration
"""

from perception_framework.contracts.profile import ResourceBudget
from perception_framework.edge.coverage_fusion import CAPABILITY_KIND, EdgeCoverageFusionService, qualify
from perception_framework.perception.coverage import BlindSpotCause, CoverageObservation, SourceStatus
from perception_framework.registry.capability_registry import CapabilityRegistry
from perception_framework.selection.selector import CapabilitySelector


def obs(oid, source, fraction, at=1.0, conf=0.8):
    return CoverageObservation(oid, source, "frame-0", at, fraction, conf)


def test_two_terminals_naming_a_camera_the_same_way_do_not_collide():
    svc = EdgeCoverageFusionService()
    svc.assign_source("zone_a", "terminal-1", "cam0")
    svc.assign_source("zone_a", "terminal-2", "cam0")

    svc.ingest_from_terminal("terminal-1", "zone_a", obs("o1", "cam0", 0.5))
    svc.ingest_from_terminal("terminal-2", "zone_a", obs("o1", "cam0", 0.4))

    # Both contributed -- if the qualification collided, the second ingest
    # would have looked like a duplicate observation_id and been dropped.
    element = svc.coverage("zone_a")
    assert element.independent_support == 2
    assert element.sources == (qualify("terminal-1", "cam0"), qualify("terminal-2", "cam0"))


def test_duplicate_observation_id_from_the_same_terminal_is_still_deduped():
    svc = EdgeCoverageFusionService()
    svc.assign_source("zone_a", "terminal-1", "cam0")
    first = svc.ingest_from_terminal("terminal-1", "zone_a", obs("o1", "cam0", 0.5))
    again = svc.ingest_from_terminal("terminal-1", "zone_a", obs("o1", "cam0", 0.5))
    assert again is None
    assert svc.coverage("zone_a").observed_fraction == first.observed_fraction


def test_fusion_answers_coverage_a_single_terminal_could_not():
    """The point of edge fusion: neither terminal alone covers the zone, but
    their combined reports do."""
    svc = EdgeCoverageFusionService()
    svc.assign_source("zone_a", "terminal-1", "cam0")
    svc.assign_source("zone_a", "terminal-2", "cam0")

    svc.ingest_from_terminal("terminal-1", "zone_a", obs("o1", "cam0", 0.5))
    svc.ingest_from_terminal("terminal-2", "zone_a", obs("o1", "cam0", 0.5))

    assert svc.blind_spots(now=1.0, source_status={
        qualify("terminal-1", "cam0"): SourceStatus(qualify("terminal-1", "cam0"), last_observed_at=1.0),
        qualify("terminal-2", "cam0"): SourceStatus(qualify("terminal-2", "cam0"), last_observed_at=1.0),
    }) == []


def test_blind_spot_carries_the_qualified_source_after_assignment():
    svc = EdgeCoverageFusionService()
    svc.assign_source("zone_a", "terminal-1", "cam0")
    spots = svc.blind_spots(now=1.0, source_status={})
    # A source *is* assigned (through the qualified id), so this must not
    # be reported as NO_SOURCE -- that cause is reserved for a region with
    # no assignment at all (see tests/test_coverage.py).
    assert len(spots) == 1 and spots[0].cause is not BlindSpotCause.NO_SOURCE
    assert spots[0].sources == (qualify("terminal-1", "cam0"),)


def test_register_only_selectable_at_the_edge():
    registry = CapabilityRegistry()
    svc = EdgeCoverageFusionService()
    svc.register(registry, provider_id="edge-1-coverage")

    selector = CapabilitySelector(registry)
    budget = ResourceBudget(compute_units=100.0, memory_mb=8192.0)

    on_device = selector.select(CAPABILITY_KIND, {"cpu", "mobile"}, budget)
    assert on_device.provider is None
    assert on_device.reason == "no_compatible_provider_within_budget"

    at_edge = selector.select(CAPABILITY_KIND, {"cpu", "gpu", "edge_node"}, budget)
    assert at_edge.provider is not None
    assert at_edge.provider.provider_id == "edge-1-coverage"
