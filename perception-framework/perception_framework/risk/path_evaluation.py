"""Risk-scores externally supplied path candidates against currently known
hazards -- a narrow extension of AI-R-02's role, scoped to *evaluation*
only.

implements: AI-R-02

경계(AI-C-19): 경로 후보 자체는 이 모듈이 만들지 않는다. 후보는 항상
외부(백엔드/제어·경로계획 스택)에서 온 것으로 취급하고, 이 모듈은 이미
AI가 산출한 위험/객체 근거로 각 후보의 위험도와 근거 충분도를 매겨 돌려줄
뿐이다. 여러 후보 중 하나를 고르거나 순위를 매겨 "이게 낫다"고 확정하는
것은 하지 않는다 -- 그건 이미 경로를 확정하는 행위이고 AI-C-19가 AI 소관이
아니라고 못박은 실제 물리 경로 결정에 해당한다. 호출자가 각 평가 결과를
받아 스스로 비교·확정한다.

`RuleBasedRiskScorer`(risk/scoring.py)를 그대로 재사용한다 -- 경로 후보
평가라고 해서 새 위험 산정 알고리즘이 필요한 게 아니라, 같은 위험 산정을
경로 상의 여러 지점에 반복 적용할 뿐이다(AI-C-13: 이미 있는 것보다 무거운
걸 새로 만들지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from perception_framework.risk.scoring import RiskScore

#: Local-coordinate point -> named risk-input values observed near it
#: (e.g. {"proximity": 0.8, "distance_margin_m": 0.4}). A point with no
#: known hazard evidence near it returns {} -- never a fabricated 0.0
#: (AI-R-02: "존재하지 않는 입력을 임의 생성하거나 보간해... 사용해서는
#: 안 된다").
HazardLookup = Callable[[tuple[float, float]], dict[str, float]]


@dataclass(frozen=True)
class PathCandidate:
    """Opaque candidate from an external planner.

    AI never constructs one of these itself (AI-C-19) -- it only reads
    `hazard_probe_points`, whatever local-coordinate samples the caller
    wants risk-scored (e.g. waypoints, or denser samples along a segment).
    Nothing about the path's own geometry/semantics beyond those points is
    interpreted here.
    """

    candidate_id: str
    hazard_probe_points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class PathCandidateEvaluation:
    candidate_id: str
    max_risk: float
    evidence_sufficiency: float
    worst_point: tuple[float, float] | None
    points_evaluated: int
    points_missing_evidence: int


class PathCandidateRiskEvaluator:
    """Scores each candidate by its worst-case probe-point risk.

    Ranking or picking a "best" candidate is deliberately left to the
    caller: returning a ranked list here would already be a path
    selection decision, which AI-C-19 keeps outside AI's authority.
    """

    def __init__(
        self,
        scorer: Callable[[dict[str, float]], RiskScore],
        hazard_lookup: HazardLookup,
    ) -> None:
        self._scorer = scorer
        self._hazard_lookup = hazard_lookup

    def evaluate(self, candidate: PathCandidate) -> PathCandidateEvaluation:
        if not candidate.hazard_probe_points:
            return PathCandidateEvaluation(candidate.candidate_id, 0.0, 0.0, None, 0, 0)

        scored: list[tuple[tuple[float, float], RiskScore]] = []
        missing = 0
        for point in candidate.hazard_probe_points:
            inputs = self._hazard_lookup(point)
            if not inputs:
                missing += 1
                continue
            scored.append((point, self._scorer(inputs)))

        if not scored:
            return PathCandidateEvaluation(
                candidate_id=candidate.candidate_id,
                max_risk=0.0,
                evidence_sufficiency=0.0,
                worst_point=None,
                points_evaluated=len(candidate.hazard_probe_points),
                points_missing_evidence=missing,
            )

        worst_point, worst_score = max(scored, key=lambda ps: ps[1].level)
        avg_sufficiency = sum(s.evidence_sufficiency for _, s in scored) / len(scored)
        return PathCandidateEvaluation(
            candidate_id=candidate.candidate_id,
            max_risk=worst_score.level,
            evidence_sufficiency=avg_sufficiency,
            worst_point=worst_point,
            points_evaluated=len(scored),
            points_missing_evidence=missing,
        )
