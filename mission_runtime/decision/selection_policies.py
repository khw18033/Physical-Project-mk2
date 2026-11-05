"""provider 선택 규칙들 — **같은 인터페이스의 다른 정책**이다.

implements: AI-C-13, AI-B-06, AI-S-05
근거: internal/docs-dev/obsidian/ideas/evidence-driven-orchestration-plan.md §3 S3

AI-C-13: "선택 방법은 특정 점수식, 규칙 또는 학습 알고리즘을 프레임워크의 필수 방식으로
고정하지 않고 교체 가능하게 유지해야 하며, 후보 방법은 동일 조건에서 비교할 수 있어야
한다." 그래서 비교군을 **별도 구현이 아니라 정책으로** 둔다 — 같은 루프·같은 provider
pool·같은 비용표를 쓰므로 공정성 논란이 줄고, ablation "No evidence feedback"이
`StaticPlanPolicy`로 자연스럽게 퇴화한다.

각 정책이 대응하는 선례는 docstring에 적는다. 이름을 빌린 것이지 그 논문의 구현을
재현했다는 뜻이 **아니다** — 재현이 필요하면 원 구현을 돌려야 한다(계획 §5-2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mission_runtime.decision.info_request import EvidenceNeed
from mission_runtime.decision.orchestrator import Budget, ProviderChoice
from mission_runtime.perception.object_record import ObjectRecord

#: capability kind → (provider_id, 비용 ms). 실측값을 넣는다(AI-B-01).
CostTable = dict[str, tuple[str, float]]


def _candidates(need: EvidenceNeed, costs: CostTable, budget: Budget | None = None):
    """이 결손을 채울 수 있는 (kind, provider, cost) — **이미 부른 것은 뺀다.**

    같은 provider를 다시 불러도 새 근거가 나오지 않는다. 걸러내지 않으면 정책이
    가장 싼 것을 반복해 고르고, 루프는 no_progress로 멈춘다(2026-09-22 실측).
    지지 소스 수를 세는 계약에서는 특히 치명적이다 — 같은 소스를 두 번 세면
    '독립'이라는 말이 무의미해진다(AI-S-03).
    """
    used = budget.called if budget is not None else set()
    return [(k, *costs[k]) for k in need.candidate_capability_kinds
            if k in costs and costs[k][0] not in used]


@dataclass
class StaticPlanPolicy:
    """미리 정한 순서대로 전부 부른다 — **피드백을 쓰지 않는다.**

    선례: RoboKudo형 task→pipeline 구성. 목표 annotation에서 dependency를 역구성해
    파이프라인을 만들고 끝까지 돌린다.

    이 정책이 곧 ablation "No evidence feedback"이다. 루프는 돌지만 현재 레코드를
    보지 않으므로, 결과적으로 정적 파이프라인과 같아진다.
    """

    plan: tuple[str, ...]
    costs: CostTable
    name: str = "static"
    _cursor: int = field(default=0, repr=False)

    def next(self, needs, record: ObjectRecord, budget: Budget) -> ProviderChoice | None:
        while self._cursor < len(self.plan):
            kind = self.plan[self._cursor]
            self._cursor += 1
            if kind in self.costs and self.costs[kind][0] not in budget.called:
                pid, cost = self.costs[kind]
                # for_kind는 "이 호출이 무엇을 위한 것인가"의 기록일 뿐,
                # 선택에는 쓰지 않는다 — 그것이 이 정책의 정의다.
                return ProviderChoice(kind, pid, needs[0].evidence_id if needs else "", cost)
        return None


@dataclass
class GreedyCostPolicy:
    """미충족 결손 중 **가장 싸게 채울 수 있는 것**부터.

    선례: Ghosh et al., 비용을 보고 런타임에 모델을 고르는 계열. 다만 그쪽은 같은
    정보를 주는 대안 중 선택이고, 여기서는 **서로 다른 정보를 주는 상보 provider**
    중 선택이다.

    필수 결손을 선택 결손보다 먼저 본다 — `gap()`이 이미 그 순서로 준다(AI-S-07).
    """

    costs: CostTable
    name: str = "greedy_cost"

    def next(self, needs, record: ObjectRecord, budget: Budget) -> ProviderChoice | None:
        best = None
        for need in needs:
            for kind, pid, cost in _candidates(need, self.costs, budget):
                if not budget.allows(cost):
                    continue
                if best is None or cost < best[3]:
                    best = (kind, pid, need.evidence_id, cost)
            if best is not None:
                break          # 필수가 앞이므로 첫 결손에서 찾으면 그것으로 정한다
        return ProviderChoice(*best) if best else None


@dataclass
class ExpectedGainPolicy:
    """**기대 충족 이득 / 비용**이 가장 큰 것부터.

    선례: CODEI(T-RO 2025)가 task 요구와 인지 성능을 함께 보고 ILP로 조합을 고르는
    것을, 런타임 그리디 근사로 옮긴 것이다. ILP는 설계 시점에 전역 최적을 풀지만
    여기서는 매 회차 한 걸음만 고른다.

    `success`는 그 provider가 그 종류를 충족시킬 확률의 **추정**이다. 실측 전에는
    측정값이 아니므로 기본값을 쓰고, 측정되면 실행 프로파일에서 온다(AI-B-01).
    충돌(`conflicting`) 결손에는 가중치를 준다 — 상충은 방치하면 틀린 확정이 된다.
    """

    costs: CostTable
    success: dict[str, float] = field(default_factory=dict)
    default_success: float = 0.7
    conflict_weight: float = 1.5
    name: str = "expected_gain"

    def next(self, needs, record: ObjectRecord, budget: Budget) -> ProviderChoice | None:
        best, best_score = None, 0.0
        for need in needs:
            w = self.conflict_weight if need.conflicting else 1.0
            for kind, pid, cost in _candidates(need, self.costs, budget):
                if not budget.allows(cost) or cost <= 0:
                    continue
                s = self.success.get(kind, self.default_success)
                score = (s * w) / cost
                if score > best_score:
                    best, best_score = (kind, pid, need.evidence_id, cost), score
        return ProviderChoice(*best) if best else None
