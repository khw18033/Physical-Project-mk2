"""implements: AI-S-03, AI-S-04, AI-C-13"""

import numpy as np
import pytest

from perception_framework.contracts.data_dictionary import UNKNOWN_LIKELIHOOD, UNKNOWNNESS_POLICY_ID
from perception_framework.perception.object_record import Evidence, ProgressiveRecordBuilder
from perception_framework.perception.open_vocabulary import RawVocabScores
from perception_framework.perception.unconfirmed import CandidateStatus, UnconfirmedCandidateRegistry
from perception_framework.perception.unknownness import (
    FomoAttributePolicy,
    OwobjEnergyPolicy,
    OwOvdHaufPolicy,
    UnknownnessScore,
    register_unconfirmed_candidates,
    to_worker_item,
)

BOXES = ((0.0, 0.0, 10.0, 10.0), (20.0, 20.0, 30.0, 30.0))


def _known_raw(probs):
    return RawVocabScores(
        vocab=("a dog", "a cat"),
        boxes=BOXES,
        probs=np.array(probs),
        execution_provider="CPUExecutionProvider",
    )


def _attribute_raw(probs):
    return RawVocabScores(
        vocab=("an object that is furry",),
        boxes=BOXES,
        probs=np.array(probs),
        execution_provider="CPUExecutionProvider",
    )


# --- alignment invariant, shared by every policy ----------------------------


def test_policies_reject_misaligned_boxes():
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    mismatched_attribute = RawVocabScores(
        vocab=("an object that is furry",),
        boxes=((0.0, 0.0, 5.0, 5.0), (20.0, 20.0, 30.0, 30.0)),  # first box differs
        probs=np.array([[0.8], [0.9]]),
        execution_provider="CPUExecutionProvider",
    )
    for policy in (FomoAttributePolicy(), OwOvdHaufPolicy(), OwobjEnergyPolicy(known_energy_reference=-1.0)):
        with pytest.raises(ValueError):
            policy.score(known, mismatched_attribute)


# --- FOMO --------------------------------------------------------------------


def test_fomo_policy_flags_low_known_confidence_high_attribute_similarity_as_unknown():
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    attribute = _attribute_raw([[0.8], [0.9]])

    scores = FomoAttributePolicy().score(known, attribute)

    assert scores[0].p_unknown == pytest.approx((1 - 0.9) * 0.8)
    assert scores[1].p_unknown == pytest.approx((1 - 0.1) * 0.9)
    assert scores[0].p_unknown < scores[1].p_unknown


def test_fomo_policy_is_unknown_respects_threshold():
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    attribute = _attribute_raw([[0.8], [0.9]])
    policy = FomoAttributePolicy(threshold=0.5)

    scores = policy.score(known, attribute)

    assert policy.is_unknown(scores[0]) is False
    assert policy.is_unknown(scores[1]) is True


def test_fomo_policy_reports_best_known_label_per_box():
    known = _known_raw([[0.9, 0.05], [0.2, 0.6]])
    attribute = _attribute_raw([[0.1], [0.1]])

    scores = FomoAttributePolicy().score(known, attribute)

    assert scores[0].best_known_label == "a dog"
    assert scores[1].best_known_label == "a cat"


# --- OW-OVD HAUF ---------------------------------------------------------------


def test_ow_ovd_hauf_policy_produces_bounded_scores():
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    attribute = _attribute_raw([[0.8], [0.9]])

    scores = OwOvdHaufPolicy().score(known, attribute)

    assert all(0.0 <= s.p_unknown <= 1.0 for s in scores)
    assert all(isinstance(s, UnknownnessScore) for s in scores)


# --- OWOBJ ---------------------------------------------------------------------


def test_owobj_policy_separates_low_and_high_known_confidence_by_energy():
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    attribute = _attribute_raw([[0.8], [0.9]])
    policy = OwobjEnergyPolicy(known_energy_reference=-2.0, margin=0.5)

    scores = policy.score(known, attribute)

    # the box with weaker known-class evidence should not separate *less*
    # than the confident box under the same energy margin.
    assert scores[1].p_unknown >= scores[0].p_unknown


# --- policies are interchangeable (AI-C-13) -------------------------------------


# --- glue into object_record.py / UnconfirmedCandidateRegistry (AI-S-04) -------


def test_to_worker_item_matches_the_data_dictionary_field_names():
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    attribute = _attribute_raw([[0.8], [0.9]])
    policy = FomoAttributePolicy(threshold=0.5)
    scores = policy.score(known, attribute)

    unknown_item = to_worker_item(scores[1], policy)
    known_item = to_worker_item(scores[0], policy)

    assert unknown_item["label"] is None
    assert known_item["label"] == "a dog"
    assert UNKNOWN_LIKELIHOOD not in {"label", "region", "confidence", "kind"}  # sanity: distinct key
    assert unknown_item[UNKNOWN_LIKELIHOOD] == pytest.approx(scores[1].p_unknown)
    assert unknown_item[UNKNOWNNESS_POLICY_ID] == policy.policy_id


def test_unknown_flagged_box_never_votes_a_semantic_class_into_the_object_record():
    """The actual AI-S-04 invariant: object_record.py needed zero changes —
    an unlabeled Evidence just never enters the vote (RecordResolver._resolve_class
    already skips `if not e.label`)."""
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    attribute = _attribute_raw([[0.8], [0.9]])
    policy = FomoAttributePolicy(threshold=0.5)
    scores = policy.score(known, attribute)

    builder = ProgressiveRecordBuilder()
    for index, score in enumerate(scores):
        item = to_worker_item(score, policy)
        evidence = Evidence(
            evidence_id=f"frame1:owlvit:{index}",
            frame_ref="frame1",
            source_group="owlvit",
            observed_at=0.0,
            available_at=0.0,
            kind=item["kind"],
            confidence=item["confidence"],
            region=item["region"],
            label=item["label"],
        )
        builder.ingest(f"object{index}", evidence)

    confident_record = builder.records["object0"]
    unknown_record = builder.records["object1"]

    assert confident_record.semantic_class == "a dog"
    assert unknown_record.semantic_class != "a dog" and unknown_record.semantic_class != "a cat"


def test_register_unconfirmed_candidates_only_touches_boxes_flagged_unknown():
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    attribute = _attribute_raw([[0.8], [0.9]])
    policy = FomoAttributePolicy(threshold=0.5)
    scores = policy.score(known, attribute)
    registry = UnconfirmedCandidateRegistry()

    touched = register_unconfirmed_candidates(scores, policy, registry, frame_ref="frame1")

    assert touched == ["frame1:1"]
    candidate = registry.get("frame1:1")
    assert candidate.status == CandidateStatus.UNCONFIRMED
    assert candidate.zero_shot_hints[0].label == "a dog"  # closest guess, never confirmed
    with pytest.raises(KeyError):
        registry.get("frame1:0")  # the confident box was never routed here


def test_all_policies_share_the_same_interface():
    known = _known_raw([[0.9, 0.05], [0.1, 0.1]])
    attribute = _attribute_raw([[0.8], [0.9]])

    for policy in (
        FomoAttributePolicy(),
        OwOvdHaufPolicy(),
        OwobjEnergyPolicy(known_energy_reference=-1.0),
    ):
        scores = policy.score(known, attribute)
        assert len(scores) == len(BOXES)
        assert all(s.policy_id == policy.policy_id for s in scores)
        assert all(isinstance(policy.is_unknown(s), bool) for s in scores)
