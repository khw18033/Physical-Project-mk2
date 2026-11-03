"""implements: AI-S-03
covers: model confidence and evidence sufficiency stay apart, and the amount of
        evidence is counted in **origin units** so that re-reading one frame
        does not manufacture support
"""

import pytest

from mission_runtime.perception.object_record import Evidence
from mission_runtime.perception.uncertainty import (
    EvidenceLevel,
    EvidenceOrigin,
    UncertaintyEvaluator,
)


def test_high_confidence_with_insufficient_evidence_is_not_confirmed():
    evaluator = UncertaintyEvaluator(min_evidence_count=2, confirm_threshold=0.6)

    result = evaluator.evaluate(raw_confidence=0.95, evidence_count=1)

    assert result.evidence_level == EvidenceLevel.INSUFFICIENT
    assert result.confirmed is False


def test_confident_and_sufficient_evidence_is_confirmed():
    evaluator = UncertaintyEvaluator(min_evidence_count=2, confirm_threshold=0.6)

    result = evaluator.evaluate(raw_confidence=0.8, evidence_count=3)

    assert result.evidence_level == EvidenceLevel.SUFFICIENT
    assert result.confirmed is True


def test_without_calibration_provider_raw_confidence_is_used_uncombined():
    evaluator = UncertaintyEvaluator(min_evidence_count=1, confirm_threshold=0.5)

    result = evaluator.evaluate(raw_confidence=0.7, evidence_count=1)

    assert result.calibrated_confidence is None
    assert result.confirmed is True


def test_calibration_provider_when_available_can_change_the_verdict():
    evaluator = UncertaintyEvaluator(min_evidence_count=1, confirm_threshold=0.6)

    result = evaluator.evaluate(raw_confidence=0.7, evidence_count=1, calibrate_fn=lambda c: c * 0.5)

    assert result.calibrated_confidence == 0.35
    assert result.confirmed is False


# --- 근거의 수는 출처의 수다 (AI-S-03: "출처, 최신성, 일관성, 누락 상태") ------


def test_three_reads_of_one_frame_are_one_source():
    """같은 프레임을 세 번 읽은 것은 **한 번 본 것**이다.

    세 번으로 세면 중복 관측이 근거 충분도를 만들어 내고, 그러면 한 소스만으로도
    확정에 도달한다 — AI-S-03 이 막으려는 바로 그 승격이다.
    """
    evaluator = UncertaintyEvaluator(min_evidence_count=2, confirm_threshold=0.6)

    result = evaluator.evaluate(
        raw_confidence=0.95,
        evidence_origins=[("det_a", "frame-1")] * 3)

    assert result.evidence_count == 1
    assert result.duplicate_count == 2
    assert result.counted_units == (("det_a", "frame-1"),)
    assert result.evidence_level is EvidenceLevel.INSUFFICIENT
    assert result.confirmed is False


def test_two_providers_reading_the_same_frame_do_not_confirm_each_other():
    """탐지기와 분류기가 같은 프레임을 각각 읽은 것도 한 번 본 것이다(AI-S-06)."""
    evaluator = UncertaintyEvaluator(min_evidence_count=2, confirm_threshold=0.6)
    frame = "cam-a:frame-7"

    result = evaluator.evaluate(
        raw_confidence=0.9,
        evidence_origins=[EvidenceOrigin("cam-a", frame), EvidenceOrigin("cam-a", frame)])

    assert result.evidence_count == 1
    assert result.confirmed is False


def test_two_different_observations_do_confirm():
    """중복만 접는다 — 서로 다른 원본 관측은 그대로 두 지지다."""
    evaluator = UncertaintyEvaluator(min_evidence_count=2, confirm_threshold=0.6)

    result = evaluator.evaluate(
        raw_confidence=0.9,
        evidence_origins=[("det_a", "frame-1"), ("det_b", "frame-2")])

    assert result.evidence_count == 2
    assert result.duplicate_count == 0
    assert result.confirmed is True


def test_an_object_record_evidence_row_can_be_passed_straight_in():
    """`Evidence` · `SpatialObservation` · `GroundedEvidence` 가 같은 두 칸을 들고
    있어서 어휘를 새로 짓지 않아도 된다."""
    evaluator = UncertaintyEvaluator(min_evidence_count=2, confirm_threshold=0.6)
    rows = [
        Evidence("e1", "frame-0", "det_a", 1.0, 1.0, "region", 0.9),
        Evidence("e2", "frame-0", "det_a", 1.1, 1.1, "semantic", 0.9, label="cup"),
    ]

    result = evaluator.evaluate(raw_confidence=0.9, evidence_origins=rows)

    assert result.counted_units == (("det_a", "frame-0"),)
    assert result.confirmed is False


def test_the_int_path_keeps_working_but_promises_less():
    """정수는 출처를 들고 있지 않아 중복을 접을 수 없다. 그 사실을 숨기지 않는다."""
    evaluator = UncertaintyEvaluator(min_evidence_count=2, confirm_threshold=0.6)

    weak = evaluator.evaluate(raw_confidence=0.95, evidence_count=3)
    declared = evaluator.evaluate(raw_confidence=0.95,
                                  evidence_origins=[("det_a", "frame-1")] * 3)

    assert weak.origin_units_declared is False
    assert weak.counted_units == () and weak.duplicate_count == 0
    assert weak.confirmed is True        # 호출자가 말한 3 을 그대로 쓴다
    assert declared.origin_units_declared is True
    assert declared.confirmed is False   # 같은 세 건이 출처로는 하나다


def test_the_evidence_must_be_declared_exactly_once():
    evaluator = UncertaintyEvaluator()

    with pytest.raises(ValueError, match="exactly once"):
        evaluator.evaluate(raw_confidence=0.9)
    with pytest.raises(ValueError, match="exactly once"):
        evaluator.evaluate(raw_confidence=0.9, evidence_count=2,
                           evidence_origins=[("a", "f")])


def test_an_origin_without_countable_units_is_refused_rather_than_counted_as_one():
    """세는 단위를 모르는 채 1 로 세면 중복이 지지가 된다."""
    evaluator = UncertaintyEvaluator()

    with pytest.raises(TypeError, match="source_group"):
        evaluator.evaluate(raw_confidence=0.9, evidence_origins=["just-a-string"])
