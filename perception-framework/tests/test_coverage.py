"""implements: AI-E-05, AI-C-02, AI-C-10, AI-C-11, AI-S-03
tests: three-valued observation state, blind-spot cause separation, source loss
       is not counter-evidence (and the paths where coverage *does* change),
       uncertainty reported apart from confidence, anchor referenced not defined
"""
import pytest

from perception_framework.contracts.capability import CapabilityState
from perception_framework.perception.coverage import (
    DEFAULT_STALE_AFTER, FULL_OBSERVATION, REQUIREMENT, BlindSpot, BlindSpotCause,
    CoverageEstimator, CoverageObservation, ObservationState, SourceStatus,
)
from perception_framework.perception.environment_map import Anchor, BASE_UNCERTAINTY


def obs(oid, source, fraction, at=1.0, conf=0.8, anchor=None):
    return CoverageObservation(oid, source, "frame-0", at, fraction, conf, anchor)


def estimator_with_anchor():
    c = CoverageEstimator()
    c.declare_anchor(Anchor("cam_fixed_1", (3.0, 0.0, 2.5)))
    return c


# -- three-valued observation state ---------------------------------------

def test_region_with_no_observation_is_unobserved():
    c = CoverageEstimator()
    c.assign_source("zone_a", "fixed_cam")
    assert c.state_of("zone_a") is ObservationState.UNOBSERVED
    assert c.coverage("zone_a").observed_fraction == 0.0


def test_partial_pass_is_neither_unobserved_nor_observed():
    """The middle state must be reachable — a terminal fills a zone gradually."""
    c = CoverageEstimator()
    c.ingest("zone_a", obs("o1", "robot_cam", 0.4))
    assert c.state_of("zone_a") is ObservationState.PARTIALLY_OBSERVED

    # ...and the counter-case: enough accumulation does promote it.
    c.ingest("zone_a", obs("o2", "robot_cam", 0.6))
    assert c.state_of("zone_a") is ObservationState.OBSERVED
    assert c.coverage("zone_a").observed_fraction >= FULL_OBSERVATION


def test_coverage_accumulates_and_never_regresses():
    c = CoverageEstimator()
    first = c.ingest("zone_a", obs("o1", "robot_cam", 0.5))
    second = c.ingest("zone_a", obs("o2", "robot_cam", 0.2))
    assert second.observed_fraction > first.observed_fraction

    # A source disappearing contributes nothing; it is not counter-evidence.
    skipped = c.ingest("zone_a", obs("o3", "gone_cam", 0.9),
                       available_sources={"robot_cam"})
    assert skipped is None
    assert c.state_of("zone_a") is ObservationState.PARTIALLY_OBSERVED
    assert c.coverage("zone_a").observed_fraction == second.observed_fraction


# -- source loss is not counter-evidence, and what *does* change -----------

def test_losing_every_source_does_not_unobserve_but_does_go_stale():
    """The claim and its inverse in one place.

    Coverage must survive source loss (AI-C-11), but surviving is not the same
    as staying current: the same region must fall to STALE once its last good
    observation ages out. Without the second half the first is untestable.
    """
    c = CoverageEstimator()
    c.assign_source("zone_a", "fixed_cam")
    c.ingest("zone_a", obs("o1", "fixed_cam", 1.0, at=10.0))
    assert c.state_of("zone_a") is ObservationState.OBSERVED

    dead = {"fixed_cam": SourceStatus("fixed_cam", available=False)}
    # Still OBSERVED — the observation happened and losing the camera does not
    # unmake it.
    assert c.state_of("zone_a") is ObservationState.OBSERVED
    # But it is no longer usable *now*, and that is reported as a blind spot.
    fresh = c.classify("zone_a", now=11.0, source_status=dead)
    assert fresh is not None and fresh.cause is BlindSpotCause.SOURCE_FAILURE
    assert fresh.state is ObservationState.OBSERVED

    # And with the source healthy again, age alone is enough to invalidate.
    alive = {"fixed_cam": SourceStatus("fixed_cam", available=True)}
    assert c.classify("zone_a", now=11.0, source_status=alive) is None
    aged = c.classify("zone_a", now=10.0 + DEFAULT_STALE_AFTER + 1, source_status=alive)
    assert aged is not None and aged.cause is BlindSpotCause.STALE


def test_reduced_view_keeps_regions_with_remaining_support_only():
    c = CoverageEstimator()
    c.ingest("zone_a", obs("o1", "fixed_cam", 0.5))
    c.ingest("zone_a", obs("o2", "robot_cam", 0.4))
    c.ingest("zone_b", obs("o3", "robot_cam", 0.7))

    kept = {e.region_id for e in c.reduced_view({"fixed_cam"})}
    assert kept == {"zone_a"}                     # zone_b lost all support

    # Dropped from the view, not deleted: it returns with its source.
    back = {e.region_id for e in c.reduced_view({"fixed_cam", "robot_cam"})}
    assert back == {"zone_a", "zone_b"}


# -- blind-spot causes -----------------------------------------------------

def test_unassigned_region_is_no_source_but_an_assigned_one_is_not():
    c = CoverageEstimator()
    c.assign_source("zone_b", "fixed_cam")
    c.elements.setdefault("zone_a", c.coverage("zone_a"))

    a = c.classify("zone_a", now=1.0, source_status={})
    assert a is not None and a.cause is BlindSpotCause.NO_SOURCE

    status = {"fixed_cam": SourceStatus("fixed_cam", available=True)}
    b = c.classify("zone_b", now=1.0, source_status=status)
    assert b is not None and b.cause is not BlindSpotCause.NO_SOURCE


def test_occlusion_and_failure_are_distinguished():
    c = CoverageEstimator()
    c.assign_source("zone_a", "fixed_cam")
    c.ingest("zone_a", obs("o1", "fixed_cam", 1.0, at=5.0))

    occluded = {"fixed_cam": SourceStatus("fixed_cam", available=True, occluded=True)}
    failed = {"fixed_cam": SourceStatus("fixed_cam", available=False, occluded=True)}

    assert c.classify("zone_a", 6.0, occluded).cause is BlindSpotCause.OCCLUDED
    # Same occluded flag, different availability verdict — a device the backend
    # calls unusable is not merely blocked.
    assert c.classify("zone_a", 6.0, failed).cause is BlindSpotCause.SOURCE_FAILURE


def test_one_healthy_unoccluded_source_clears_the_occlusion_verdict():
    c = CoverageEstimator()
    c.assign_source("zone_a", "cam_a")
    c.assign_source("zone_a", "cam_b")
    c.ingest("zone_a", obs("o1", "cam_a", 0.5, at=5.0))

    both_blocked = {
        "cam_a": SourceStatus("cam_a", available=True, occluded=True),
        "cam_b": SourceStatus("cam_b", available=True, occluded=True),
    }
    assert c.classify("zone_a", 6.0, both_blocked).cause is BlindSpotCause.OCCLUDED

    one_clear = {
        "cam_a": SourceStatus("cam_a", available=True, occluded=True),
        "cam_b": SourceStatus("cam_b", available=True, occluded=False),
    }
    # Still a blind spot (only half covered), but no longer *because* of
    # occlusion — one source is looking and simply has not filled it in.
    spot = c.classify("zone_a", 6.0, one_clear)
    assert spot is not None and spot.cause is not BlindSpotCause.OCCLUDED


def test_fully_observed_and_fresh_region_is_not_a_blind_spot():
    c = CoverageEstimator()
    c.assign_source("zone_a", "fixed_cam")
    c.ingest("zone_a", obs("o1", "fixed_cam", 1.0, at=5.0))
    status = {"fixed_cam": SourceStatus("fixed_cam", available=True)}

    assert c.classify("zone_a", 6.0, status) is None
    assert c.blind_spots(6.0, status) == []

    # Whereas a partially observed one is, at the same instant.
    c.assign_source("zone_b", "fixed_cam")
    c.ingest("zone_b", obs("o2", "fixed_cam", 0.3, at=5.0))
    ids = {s.region_id for s in c.blind_spots(6.0, status)}
    assert ids == {"zone_b"}


def test_availability_verdict_is_consumed_not_recomputed():
    """The module must not second-guess the backend (원칙 #15, AI-C-10)."""
    c = CoverageEstimator()
    c.assign_source("zone_a", "fixed_cam")
    c.ingest("zone_a", obs("o1", "fixed_cam", 1.0, at=5.0))

    # A source reporting fresh observations but marked unavailable is still
    # unavailable — the observations do not override the verdict.
    contradictory = {"fixed_cam": SourceStatus("fixed_cam", available=False,
                                               last_observed_at=5.0)}
    assert c.classify("zone_a", 5.5, contradictory).cause is BlindSpotCause.SOURCE_FAILURE

    # And flipping only that input flips the outcome, with nothing else changed.
    assert c.classify("zone_a", 5.5,
                      {"fixed_cam": SourceStatus("fixed_cam", available=True)}) is None


def test_unknown_source_status_does_not_invent_a_failure():
    """Absent status is missing information, not a failure verdict."""
    c = CoverageEstimator()
    c.assign_source("zone_a", "fixed_cam")
    c.ingest("zone_a", obs("o1", "fixed_cam", 0.4, at=5.0))

    spot = c.classify("zone_a", 6.0, source_status={})
    assert spot is not None
    assert spot.cause not in (BlindSpotCause.SOURCE_FAILURE, BlindSpotCause.NO_SOURCE)


# -- uncertainty is separate from confidence (AI-S-03) --------------------

def test_uncertainty_falls_with_independent_sources_but_is_never_zero():
    c = CoverageEstimator()
    one = c.ingest("zone_a", obs("o1", "cam_a", 0.5))
    two = c.ingest("zone_a", obs("o2", "cam_b", 0.5))
    assert two.uncertainty < one.uncertainty
    assert two.uncertainty > 0.0
    assert two.independent_support == 2


def test_repeated_look_from_one_source_helps_less_than_a_second_source():
    same = CoverageEstimator()
    same.ingest("zone_a", obs("o1", "cam_a", 0.5))
    repeated = same.ingest("zone_a", obs("o2", "cam_a", 0.5))

    varied = CoverageEstimator()
    varied.ingest("zone_a", obs("o3", "cam_a", 0.5))
    independent = varied.ingest("zone_a", obs("o4", "cam_b", 0.5))

    assert independent.uncertainty < repeated.uncertainty


def test_high_confidence_does_not_by_itself_lower_uncertainty():
    """Having observed and being certain are different claims."""
    low = CoverageEstimator()
    low.ingest("zone_a", obs("o1", "cam_a", 0.5, conf=0.2))
    high = CoverageEstimator()
    high.ingest("zone_a", obs("o2", "cam_a", 0.5, conf=0.99))

    assert low.coverage("zone_a").uncertainty == high.coverage("zone_a").uncertainty
    assert low.coverage("zone_a").confidence < high.coverage("zone_a").confidence


def test_partial_coverage_is_less_certain_than_full_coverage():
    partial = CoverageEstimator()
    partial.ingest("zone_a", obs("o1", "cam_a", 0.3))
    full = CoverageEstimator()
    full.ingest("zone_a", obs("o2", "cam_a", 1.0))
    assert partial.coverage("zone_a").uncertainty > full.coverage("zone_a").uncertainty
    assert full.coverage("zone_a").uncertainty <= BASE_UNCERTAINTY


# -- coordinate boundary (AI-C-02) ----------------------------------------

def test_anchor_is_referenced_only_when_declared_and_trusted():
    c = estimator_with_anchor()
    anchored = c.ingest("zone_a", obs("o1", "cam_a", 0.5, anchor="cam_fixed_1"))
    assert anchored.anchored and anchored.anchor_id == "cam_fixed_1"

    # An undeclared anchor yields no anchored position — nothing is invented.
    loose = c.ingest("zone_b", obs("o2", "cam_a", 0.5, anchor="cam_unknown"))
    assert not loose.anchored and loose.anchor_id is None
    assert {e.region_id for e in c.anchored_regions()} == {"zone_a"}


def test_untrusted_anchor_is_not_used():
    c = CoverageEstimator()
    c.declare_anchor(Anchor("cam_fixed_1", (0.0, 0.0, 0.0), trusted=False))
    element = c.ingest("zone_a", obs("o1", "cam_a", 0.5, anchor="cam_fixed_1"))
    assert not element.anchored


def test_losing_the_anchor_source_does_not_unanchor_existing_coverage():
    c = estimator_with_anchor()
    c.ingest("zone_a", obs("o1", "cam_a", 0.4, anchor="cam_fixed_1"))
    later = c.ingest("zone_a", obs("o2", "cam_b", 0.4, anchor=None))
    assert later.anchor_id == "cam_fixed_1"


# -- capability isolation (AI-C-11) ---------------------------------------

def test_optional_source_absence_degrades_but_never_disables():
    c = CoverageEstimator()
    assert c.capability_state({"perception.detect"}) is CapabilityState.DEGRADED
    assert c.capability_state(
        set(REQUIREMENT.required) | set(REQUIREMENT.optional)) is CapabilityState.ACTIVE
    # Only a *required* kind going missing may disable.
    assert c.capability_state({"perception.segment"}) is CapabilityState.DISABLED


def test_duplicate_delivery_does_not_inflate_coverage():
    c = CoverageEstimator()
    first = c.ingest("zone_a", obs("o1", "cam_a", 0.5))
    again = c.ingest("zone_a", obs("o1", "cam_a", 0.5))
    assert again is None
    assert c.coverage("zone_a").observed_fraction == first.observed_fraction
    # A genuinely distinct observation still counts.
    assert c.ingest("zone_a", obs("o2", "cam_a", 0.2)).observed_fraction > 0.5


def test_fresh_but_incomplete_is_not_reported_as_aged_out():
    """The distinction the E2E run exposed.

    A region covered 0.9 a moment ago is genuinely still partly blind, but it
    is blind because nobody finished it — not because the reading aged. Naming
    that STALE sends an operator hunting a timing fault that is not there.
    """
    est = CoverageEstimator()
    est.declare_anchor(Anchor("cam1", (3.0, 0.0, 2.5)))
    est.assign_source("zone-a", "CAM-01")
    now = 1_000.0
    est.ingest("zone-a", CoverageObservation("o1", "CAM-01", "f0", now, 0.9, 0.8, "cam1"))
    status = {"CAM-01": SourceStatus("CAM-01", available=True, occluded=False,
                                     last_observed_at=now)}

    fresh = est.classify("zone-a", now, status)
    assert fresh is not None and fresh.cause is BlindSpotCause.INCOMPLETE

    # The same region, untouched, once the horizon passes: now it really is stale.
    aged = est.classify("zone-a", now + DEFAULT_STALE_AFTER + 1, status)
    assert aged is not None and aged.cause is BlindSpotCause.STALE


def test_a_finished_region_is_not_a_blind_spot_at_all():
    """The counter-case: completing coverage must clear it, not relabel it."""
    est = CoverageEstimator()
    est.declare_anchor(Anchor("cam1", (3.0, 0.0, 2.5)))
    est.assign_source("zone-a", "CAM-01")
    now = 1_000.0
    for i, fraction in enumerate((0.6, 0.5)):
        est.ingest("zone-a", CoverageObservation(f"o{i}", "CAM-01", "f0", now, fraction, 0.8, "cam1"))
    status = {"CAM-01": SourceStatus("CAM-01", available=True, occluded=False,
                                     last_observed_at=now)}
    assert est.state_of("zone-a") is ObservationState.OBSERVED
    assert est.classify("zone-a", now, status) is None
