"""implements: AI-S-01, AI-S-04, AI-L-01, AI-L-02, AI-L-05"""

import pytest

from perception_framework.perception.research_baselines import (
    AttributeDistribution,
    CategoryPropagation,
    FomoAttributeEvidence,
    energy_margin_loss,
    energy_score,
    hauf_unknown_score,
    mahalanobis_objectness,
    select_vsas_attributes,
)
from perception_framework.perception.tracking import BYTE_TRACK_FEATURE_PROFILE, ByteTracker, Detection


def test_bytetrack_fixture_exposes_exact_supported_subset():
    assert BYTE_TRACK_FEATURE_PROFILE.two_stage_score_association
    assert BYTE_TRACK_FEATURE_PROFILE.low_score_track_recovery
    assert not BYTE_TRACK_FEATURE_PROFILE.kalman_motion_prediction
    assert not BYTE_TRACK_FEATURE_PROFILE.hungarian_assignment


def test_bytetrack_low_confidence_box_recovers_but_does_not_spawn():
    tracker = ByteTracker(high_thresh=0.6, low_thresh=0.1)
    assert tracker.update([Detection((0, 0, 10, 10), score=0.2)]) == []
    first = tracker.update([Detection((0, 0, 10, 10), score=0.9)])[0]
    recovered = tracker.update([Detection((1, 1, 11, 11), score=0.2)])[0]
    assert recovered.track_id == first.track_id


def test_fomo_unknown_score_requires_both_ood_and_attribute_evidence():
    strong = FomoAttributeEvidence((0.2, 0.1), (0.8, 0.3)).score()
    known_like = FomoAttributeEvidence((0.95, 0.05), (0.8, 0.3)).score()
    no_attribute = FomoAttributeEvidence((0.2, 0.1), (0.05, 0.02)).score()
    assert strong == pytest.approx(0.64)
    assert strong > known_like and strong > no_attribute


def test_vsas_prefers_attribute_shared_across_annotated_and_unannotated_regions():
    candidates = [
        AttributeDistribution("shared texture", (4, 6), (5, 5)),
        AttributeDistribution("known-only logo", (9, 1), (1, 9)),
    ]
    assert select_vsas_attributes(candidates, 1) == ("shared texture",)


def test_hauf_rises_with_attribute_and_known_class_uncertainty():
    uncertain = hauf_unknown_score(0.9, (0.5, 0.5))
    confident = hauf_unknown_score(0.1, (0.99, 0.01))
    assert uncertain > confident


def test_owobj_objectness_and_energy_primitives_are_deterministic():
    assert mahalanobis_objectness((0, 0), (0, 0), (1, 1)) == pytest.approx(1.0)
    assert mahalanobis_objectness((2, 2), (0, 0), (1, 1)) < 0.1
    assert energy_score((1000, 999)) < 0
    assert energy_margin_loss(-3.0, -1.0, 1.0) == pytest.approx(3.0)
    assert energy_margin_loss(-1.0, -3.0, 1.0) == 0.0


def test_ovtr_category_evidence_follows_track_and_resists_one_frame_noise():
    propagation = CategoryPropagation(decay=0.8)
    propagation.update(7, {"car": 0.9, "bus": 0.1})
    result = propagation.update(7, {"car": 0.2, "bus": 0.8})
    other_track = propagation.update(8, {"car": 0.2, "bus": 0.8})
    assert result["car"] > result["bus"]
    assert other_track["bus"] > other_track["car"]


@pytest.mark.parametrize(
    "call",
    [
        lambda: FomoAttributeEvidence((), (0.5,)).score(),
        lambda: hauf_unknown_score(0.5, (1.0,)),
        lambda: mahalanobis_objectness((1,), (1,), (0,)),
        lambda: CategoryPropagation(decay=2).update(1, {"x": 0.5}),
    ],
)
def test_invalid_fixture_inputs_fail_closed(call):
    with pytest.raises(ValueError):
        call()
