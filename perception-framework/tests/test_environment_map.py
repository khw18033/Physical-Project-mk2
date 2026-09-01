"""implements: AI-E-05, AI-C-02, AI-C-11
tests: anchor-relative only, uncertainty falls with independent producers,
       producer loss keeps remaining support, no invented absolute position
"""
from perception_framework.contracts.capability import CapabilityState
from perception_framework.perception.environment_map import (
    REQUIREMENT, Anchor, EnvironmentMapEstimator, StructureEvidence,
)


def ev(eid, producer, extent, conf=0.8, anchor=None, kind="obstacle"):
    return StructureEvidence(eid, producer, "frame-0", 0.1, kind, extent, conf, anchor)


def estimator_with_anchor():
    m = EnvironmentMapEstimator()
    m.declare_anchor(Anchor("cam_fixed_1", (3.0, 0.0, 2.5)))
    return m


def test_uncertainty_falls_as_independent_producers_agree():
    m = estimator_with_anchor()
    one = m.ingest("e1", ev("a", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    two = m.ingest("e1", ev("b", "robot_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    assert two.uncertainty < one.uncertainty
    assert two.independent_support == 2


def test_repeated_look_from_one_producer_helps_less_than_a_second_producer():
    same = estimator_with_anchor()
    same.ingest("e1", ev("a", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    repeated = same.ingest("e1", ev("b", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))

    varied = estimator_with_anchor()
    varied.ingest("e1", ev("c", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    independent = varied.ingest("e1", ev("d", "robot_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))

    assert independent.uncertainty < repeated.uncertainty


def test_uncertainty_is_never_reported_as_zero():
    m = estimator_with_anchor()
    element = None
    for i in range(50):
        element = m.ingest("e1", ev(f"x{i}", f"p{i}", (0, 0, 1, 1), anchor="cam_fixed_1"))
    assert element.uncertainty > 0.0


def test_evidence_without_a_usable_anchor_stays_local():
    m = estimator_with_anchor()
    m.ingest("e1", ev("a", "robot_cam", (5, 5, 6, 6), anchor=None))
    assert m.anchored_elements() == []
    assert m.local_elements()[0].anchor_id is None


def test_untrusted_anchor_is_not_used():
    m = EnvironmentMapEstimator()
    m.declare_anchor(Anchor("cam_fixed_1", (3.0, 0.0, 2.5), trusted=False))
    m.ingest("e1", ev("a", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    assert m.local_elements() and not m.anchored_elements()


def test_losing_the_anchor_source_does_not_unanchor_an_existing_estimate():
    m = estimator_with_anchor()
    m.ingest("e1", ev("a", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    m.anchors["cam_fixed_1"] = Anchor("cam_fixed_1", (3.0, 0.0, 2.5), trusted=False)
    element = m.ingest("e1", ev("b", "robot_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    assert element.anchor_id == "cam_fixed_1"


def test_missing_producer_evidence_is_skipped_not_treated_as_disagreement():
    m = estimator_with_anchor()
    before = m.ingest("e1", ev("a", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    result = m.ingest("e1", ev("b", "robot_cam", (9, 9, 10, 10), anchor="cam_fixed_1"),
                      available_producers={"fixed_cam"})
    assert result is None
    assert m.elements["e1"] == before


def test_reduced_view_keeps_elements_that_remaining_producers_support():
    m = estimator_with_anchor()
    m.ingest("e1", ev("a", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    m.ingest("e2", ev("b", "robot_cam", (5, 5, 6, 6), anchor="cam_fixed_1"))
    view = {e.element_id for e in m.reduced_view({"fixed_cam"})}
    assert view == {"e1"}
    assert "e2" in m.elements        # dropped from the view, not deleted


def test_duplicate_evidence_does_not_inflate_support():
    m = estimator_with_anchor()
    m.ingest("e1", ev("a", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1"))
    assert m.ingest("e1", ev("a", "fixed_cam", (0, 0, 1, 1), anchor="cam_fixed_1")) is None
    assert m.elements["e1"].contributions == 1


def test_optional_sources_degrade_but_do_not_disable():
    assert REQUIREMENT.evaluate({"perception.detect"}) is CapabilityState.DEGRADED
    assert REQUIREMENT.evaluate(set()) is CapabilityState.DISABLED
