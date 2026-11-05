"""Risk-scores externally supplied path candidates against currently known
hazards -- a narrow extension of AI-R-02's role, scoped to *evaluation*
only.

implements: AI-R-02

2026-11-04 개정: **주행 경로 계획이 AI 몫이 되었다.** 아래 경계 서술은 그 전의
결정이고 지우지 않고 남긴다 — 왜 이 모듈에 `rank()`/`select()` 가 없는지를
설명하기 때문이다. 후보를 **만들고 고르는** 일은 이제 `planning/path_candidates.py`
가 한다. 이 모듈은 그대로 **채점만** 한다: 만드는 쪽과 채점하는 쪽이 갈려 있어야
"덜 위험해 보이도록 만든 후보" 가 생기지 않는다. 바뀌지 않은 것은 물리 명령
발급이다(AI-C-19).

경계(2026-11-04 이전): 경로 후보 자체는 이 모듈이 만들지 않는다. 후보는 항상
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

from mission_runtime.risk.scoring import RiskScore

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
    """How one candidate scored -- and **how much of it was actually looked at**.

    두 사실이 한 칸에 있었다 (2026-11-04 고침)
    ------------------------------------------
    `evidence_sufficiency` 는 **점수가 나온 점들의** 근거 충분도 평균이다. 그것은
    "본 점의 근거가 좋았다"에 답하고 "충분히 많은 점을 봤다"에는 답하지 않는다.
    두 질문을 한 칸으로 읽으면 탐침 10 점 중 1 점만 관측된 후보가 전부 관측된
    후보와 **똑같이 1.0** 을 내고(실측으로 재현했다), 그 1 점은 로봇 바로 앞의
    본 자리라서 위험 0 이다 — 즉 **스캔 밖으로 나가는 경로가 가장 안전하고 가장
    확실한 경로로 보인다.** 안전 판단에서 고르면 안 되는 바로 그 후보다.

    그래서 관측된 비율을 `observed_fraction` 으로 따로 낸다. `coverage` 가 장
    전체를 거르는 것과 같은 규칙을 후보 단위에서 한 번 더 적용하는 것이다
    (`risk/hazard_field.py` 의 `comparable`).

    `points_evaluated` 는 **점수가 나온 점의 수**이고 어느 분기에서도 같은 뜻이다.
    전에는 '아무 점도 점수가 나오지 않은' 분기에서만 전체 탐침점 수를 담아서, 두
    필드의 합이 탐침점 수와 달라졌다(10 점 후보가 10 + 10 = 20). 그 합으로 비율을
    계산하면 아무것도 못 본 후보가 50 % 로 나온다.
    """

    candidate_id: str
    max_risk: float
    evidence_sufficiency: float
    worst_point: tuple[float, float] | None
    #: 점수가 나온 탐침점의 수. `+ points_missing_evidence == 전체 탐침점 수`.
    points_evaluated: int
    points_missing_evidence: int

    @property
    def points_probed(self) -> int:
        return self.points_evaluated + self.points_missing_evidence

    @property
    def observed_fraction(self) -> float | None:
        """근거가 나온 탐침점의 비율. **탐침점이 없으면 `None`** 이다.

        0.0 이 아닌 이유: 볼 것이 없었던 것과 봤는데 아무 근거도 없던 것은 다른
        사실이고, 0 으로 합치면 "덜 봤다"는 사유를 낼 근거가 사라진다(AI-S-03).
        """
        total = self.points_probed
        return None if total == 0 else self.points_evaluated / total


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
            # 점수가 나온 점이 **하나도 없다**. `points_evaluated` 는 어느
            # 분기에서도 '점수가 나온 점의 수' 라서 여기서는 0 이다 — 전에는 전체
            # 탐침점 수를 담아 두 필드의 합이 탐침점 수를 넘었다.
            return PathCandidateEvaluation(
                candidate_id=candidate.candidate_id,
                max_risk=0.0,
                evidence_sufficiency=0.0,
                worst_point=None,
                points_evaluated=0,
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
