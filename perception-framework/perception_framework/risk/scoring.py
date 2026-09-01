"""Risk score and evidence-sufficiency estimation from only the sensors,
video, or events actually available right now (AI-R-02).

implements: AI-R-02

Missing inputs must never be fabricated or interpolated for a confirmed
judgment (AI-R-02: "존재하지 않는 입력을 임의 생성하거나 보간해 확정
판단에 사용해서는 안 된다"). `RiskScore.evidence_sufficiency` is reported
separately from `level` for exactly this reason — a high level computed
from partial evidence must not look identical to one backed by full
evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class RiskScore:
    level: float  # 0..1
    evidence_sufficiency: float  # 0..1, independent of level
    inputs_used: tuple[str, ...]
    #: Spread between the inputs that produced `level`, when this deployment
    #: has an agreement evaluator. `None` means the deployment cannot judge
    #: agreement, which AI-S-03 treats as a normal reduced configuration
    #: ("다중 소스 일치도 평가 기능이 있을 때만 추가로 적용") — it must not be
    #: reported as agreement, and it must not be confused with sufficiency.
    #: Sufficiency answers "did the inputs arrive"; this answers "do they say
    #: the same thing". Four inputs at 0.6 and inputs at 1.0/0.0/1.0/0.4 both
    #: have full coverage, and only this field separates them.
    source_disagreement: float | None = None


def spread_disagreement(values: list[float]) -> float:
    """Max-minus-min over the contributing inputs. 0 = full agreement."""
    return max(values) - min(values) if len(values) > 1 else 0.0


class Aggregation(Protocol):
    """How per-input severities combine into one level.

    Made replaceable because no single rule is right for every deployment,
    and because the choice changes which hazards are detectable at all.
    """

    def __call__(self, values: list[float], weights: list[float]) -> float: ...


def weighted_mean(values: list[float], weights: list[float]) -> float:
    """Average of the inputs, weighted.

    Note the failure mode before choosing this for a hazard deployment: a
    local extreme is diluted by calm inputs, so adding observation points
    *lowers* sensitivity. On the 2022-08-08 Seoul rainfall record, four
    stations each reached individual severity 1.0 at different hours and the
    weighted mean peaked at 0.957 — below an alert threshold of 0.98. It is
    appropriate where the inputs measure the same quantity at the same place.
    """
    total = sum(weights) or 1.0
    return sum(w * v for w, v in zip(weights, values)) / total


def maximum(values: list[float], weights: list[float]) -> float:
    """Worst input decides. Any single input reaching severity is enough."""
    return max(values) if values else 0.0


def k_of_n(k: int) -> Aggregation:
    """The k-th highest input decides — one noisy sensor cannot alarm alone.

    Between `maximum` (k=1) and consensus, for deployments that want
    corroboration without letting calm inputs dilute a real local extreme.
    """
    def aggregate(values: list[float], weights: list[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values, reverse=True)
        return ordered[min(k, len(ordered)) - 1]
    return aggregate


class RuleBasedRiskScorer:
    """Weighted-threshold rule over whatever named inputs are present.

    Deliberately the cheapest option in the framework: when this meets
    required performance, a heavier time-series/statistical model must
    not be run (절대 준수 원칙 #5, AI-C-13).
    """

    def __init__(self, weights: dict[str, float], *,
                 aggregation: Aggregation = weighted_mean,
                 disagreement: Callable[[list[float]], float] | None = None) -> None:
        self._weights = weights
        self._aggregate = aggregation
        #: Optional per AI-S-03. Absent means agreement is simply not judged.
        self._disagreement = disagreement

    def score(self, available_inputs: dict[str, float]) -> RiskScore:
        used = [k for k in self._weights if k in available_inputs]
        if not used:
            return RiskScore(level=0.0, evidence_sufficiency=0.0, inputs_used=())

        values = [available_inputs[k] for k in used]
        weights = [self._weights[k] for k in used]
        level = self._aggregate(values, weights)
        sufficiency = sum(weights) / sum(self._weights.values())
        return RiskScore(
            level=level,
            evidence_sufficiency=sufficiency,
            inputs_used=tuple(used),
            source_disagreement=(self._disagreement(values)
                                 if self._disagreement is not None else None),
        )
