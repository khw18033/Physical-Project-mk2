"""implements: AI-S-01, AI-S-03, AI-S-04, AI-C-11
tests: progressive refinement, equal-support class retention, capability loss
       does not rewrite state, optional source absence degrades only
"""
from perception_framework.contracts.capability import CapabilityState
from perception_framework.perception.object_record import (
    REQUIREMENT, Evidence, Lifecycle, ProgressiveRecordBuilder, UNKNOWN_CLASS,
)


def ev(eid, group, t, kind, conf, region=None, label=None):
    return Evidence(eid, "frame-0", group, t, t, kind, conf, region, label)


def test_record_available_before_all_providers_finish():
    b = ProgressiveRecordBuilder()
    first = b.ingest("o1", ev("a", "det_a", 0.195, "region", 0.8, (0, 0, 10, 10), "cup"))
    assert first is not None and first.revision == 1
    assert first.semantic_class == "cup"


def test_mask_refines_geometry_only_when_spatially_consistent():
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.8, (0, 0, 10, 10), "cup"))
    b.ingest("o1", ev("far", "seg", 0.2, "mask", 0.9, (100, 100, 110, 110)))
    assert b.records["o1"].geometry_kind == "region"
    b.ingest("o1", ev("near", "seg", 0.3, "mask", 0.9, (1, 1, 9, 9)))
    assert b.records["o1"].geometry_kind == "mask"


def test_equal_group_support_retains_established_class():
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.8, (0, 0, 10, 10), "cup"))
    b.ingest("o1", ev("b", "det_b", 0.2, "region", 0.95, (0, 0, 10, 10), "bowl"))
    assert b.records["o1"].semantic_class == "cup"


def test_strictly_greater_support_replaces_class():
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.9, (0, 0, 10, 10), "cup"))
    b.ingest("o1", ev("b", "det_b", 0.2, "region", 0.5, (0, 0, 10, 10), "bowl"))
    b.ingest("o1", ev("c", "det_c", 0.3, "region", 0.5, (0, 0, 10, 10), "bowl"))
    assert b.records["o1"].semantic_class == "bowl"


def test_capability_loss_does_not_rewrite_or_demote_the_record():
    """A source going away is missing evidence, not counter-evidence."""
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.8, (0, 0, 10, 10), "cup"))
    b.ingest("o1", ev("b", "det_b", 0.2, "region", 0.7, (0, 0, 10, 10), "cup"))
    before = b.records["o1"]
    assert before.lifecycle is Lifecycle.CONFIRMED

    revision = b.ingest("o1", ev("c", "det_b", 0.3, "region", 0.7, (0, 0, 10, 10), "bowl"),
                        available_groups={"det_a"})
    after = b.records["o1"]
    assert revision is None                       # no spurious update
    assert after.semantic_class == "cup"
    assert after.lifecycle is Lifecycle.CONFIRMED  # no false demotion


def test_a_vanished_supporter_is_not_a_vote_for_the_challenger():
    """The case the earlier capability-loss test never exercised.

    Two groups back `person` and then go away. A single surviving group says
    `chair`. Counting only currently-arriving evidence would leave `person`
    with zero support and let one vote flip an established, confirmed record —
    a state change caused by a disappearance rather than by an observation.
    """
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.8, (0, 0, 10, 10), "person"))
    b.ingest("o1", ev("b", "det_b", 0.2, "region", 0.8, (0, 0, 10, 10), "person"))
    assert b.records["o1"].semantic_class == "person"

    revision = b.ingest("o1", ev("c", "det_c", 0.3, "region", 0.9, (0, 0, 10, 10), "chair"),
                        available_groups={"det_c"})
    assert revision is None
    assert b.records["o1"].semantic_class == "person"
    assert b.records["o1"].lifecycle is Lifecycle.CONFIRMED


def test_a_supporter_that_actually_changes_its_reading_does_move_the_class():
    """The other half: real evidence change must still take effect.

    Otherwise the fix above would just freeze the class forever.
    """
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.8, (0, 0, 10, 10), "person"))
    b.ingest("o1", ev("b", "det_b", 0.2, "region", 0.8, (0, 0, 10, 10), "person"))
    b.ingest("o1", ev("c", "det_c", 0.3, "region", 0.9, (0, 0, 10, 10), "chair"))
    # det_a re-observes and now reads chair: two standing votes for chair.
    b.ingest("o1", ev("d", "det_a", 0.4, "region", 0.9, (0, 0, 10, 10), "chair"))
    assert b.records["o1"].semantic_class == "chair"


def test_evidence_sufficiency_is_reported_apart_from_confidence():
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.99, (0, 0, 10, 10), "cup"))
    record = b.records["o1"]
    assert record.confidence == 0.99
    assert record.supporting_groups == 1
    assert record.evidence_sufficient is False


def test_unnamed_evidence_leaves_class_unknown():
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("m", "seg", 0.1, "mask", 0.9, (0, 0, 10, 10)))
    assert b.records["o1"].semantic_class == UNKNOWN_CLASS


def test_duplicate_delivery_is_ignored():
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.8, (0, 0, 10, 10), "cup"))
    assert b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.8, (0, 0, 10, 10), "cup")) is None


def test_missing_optional_source_degrades_but_does_not_disable():
    assert REQUIREMENT.evaluate({"perception.detect"}) is CapabilityState.DEGRADED
    assert REQUIREMENT.evaluate(set()) is CapabilityState.DISABLED


def test_lifecycle_ages_to_stale_then_expired():
    b = ProgressiveRecordBuilder()
    b.ingest("o1", ev("a", "det_a", 0.1, "region", 0.8, (0, 0, 10, 10), "cup"))
    for _ in range(3):
        b.close_observation(set())
    assert b.records["o1"].lifecycle is Lifecycle.STALE
    for _ in range(2):
        b.close_observation(set())
    assert b.records["o1"].lifecycle is Lifecycle.EXPIRED
