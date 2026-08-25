"""Risk score and evidence-sufficiency estimation from only the sensors,
video, or events actually available right now (AI-R-02).

Missing inputs must never be fabricated or interpolated for a confirmed
judgment (AI-R-02: "존재하지 않는 입력을 임의 생성하거나 보간해 확정
판단에 사용해서는 안 된다"). `RiskScore.evidence_sufficiency` is reported
separately from `level` for exactly this reason — a high level computed
from partial evidence must not look identical to one backed by full
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskScore:
    level: float  # 0..1
    evidence_sufficiency: float  # 0..1, independent of level
    inputs_used: tuple[str, ...]


class RuleBasedRiskScorer:
    """Weighted-threshold rule over whatever named inputs are present.

    Deliberately the cheapest option in the framework: when this meets
    required performance, a heavier time-series/statistical model must
    not be run (절대 준수 원칙 #5, AI-C-13).
    """

    def __init__(self, weights: dict[str, float]) -> None:
        self._weights = weights

    def score(self, available_inputs: dict[str, float]) -> RiskScore:
        used = [k for k in self._weights if k in available_inputs]
        if not used:
            return RiskScore(level=0.0, evidence_sufficiency=0.0, inputs_used=())

        total_weight = sum(self._weights[k] for k in used)
        level = sum(self._weights[k] * available_inputs[k] for k in used) / total_weight
        sufficiency = total_weight / sum(self._weights.values())
        return RiskScore(level=level, evidence_sufficiency=sufficiency, inputs_used=tuple(used))
