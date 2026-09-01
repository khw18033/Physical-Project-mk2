"""implements: AI-S-03"""

from perception_framework.perception.uncertainty import EvidenceLevel, UncertaintyEvaluator


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
