"""Separates model confidence from evidence sufficiency (AI-S-03).

implements: AI-S-03

A result must never be promoted to a confirmed state just because raw
model confidence is high if the amount of independent evidence backing
it is below what is required (AI-S-03: "충분한 근거가 없는 결과를 확정
상태로 승격해서는 안 된다"). Confidence calibration is applied only when
a calibration provider is actually supplied; otherwise raw confidence
and the evidence-sufficiency flag are reported side by side, uncombined.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class EvidenceLevel(str, Enum):
    INSUFFICIENT = "INSUFFICIENT"
    SUFFICIENT = "SUFFICIENT"


@dataclass(frozen=True)
class UncertaintyAssessment:
    raw_confidence: float
    calibrated_confidence: float | None
    evidence_count: int
    evidence_level: EvidenceLevel
    confirmed: bool


class UncertaintyEvaluator:
    def __init__(self, *, min_evidence_count: int = 2, confirm_threshold: float = 0.6) -> None:
        self._min_evidence_count = min_evidence_count
        self._confirm_threshold = confirm_threshold

    def evaluate(
        self,
        raw_confidence: float,
        evidence_count: int,
        calibrate_fn: Callable[[float], float] | None = None,
    ) -> UncertaintyAssessment:
        calibrated = calibrate_fn(raw_confidence) if calibrate_fn is not None else None
        effective_confidence = calibrated if calibrated is not None else raw_confidence

        evidence_level = (
            EvidenceLevel.SUFFICIENT if evidence_count >= self._min_evidence_count else EvidenceLevel.INSUFFICIENT
        )
        confirmed = evidence_level is EvidenceLevel.SUFFICIENT and effective_confidence >= self._confirm_threshold

        return UncertaintyAssessment(
            raw_confidence=raw_confidence,
            calibrated_confidence=calibrated,
            evidence_count=evidence_count,
            evidence_level=evidence_level,
            confirmed=confirmed,
        )
