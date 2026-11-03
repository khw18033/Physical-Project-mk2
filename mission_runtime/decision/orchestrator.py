"""증거 격차를 보고 **다음에 무엇을 실행할지** 정하는 닫힌 루프.

implements: AI-S-05, AI-S-07, AI-C-13, AI-C-05, AI-B-06, AI-C-19
근거: docs/obsidian/ideas/evidence-driven-orchestration-plan.md §3 S3

기존 `decision/info_request.py`는 부족한 근거를 보고 **한 번** 요청 계획을 세운다.
여기서는 그 결과가 레코드에 반영된 뒤 **다시 센다**. ASHiTA가 task 분해와 scene graph
구성을 번갈아 돌리듯, 이 루프는 격차 계산과 provider 실행을 번갈아 돈다
(docs/obsidian/papers/ashita.md).

정지 조건은 넷뿐이고 **전부 이유가 남는다** — "그냥 끝났다"가 없어야 사후에
조기 정지의 대가(FCR)를 셀 수 있다.

    satisfied     정지 규칙이 멈추라고 했다 (기본 규칙 = 계약 충족)
    exhausted     예산을 다 썼다 (AI-B-06: 자원 상태가 실행을 제약한다)
    unobtainable  남은 결손을 만들 provider가 없다 (AI-C-05: 축소지 실패가 아니다)
    no_progress   provider를 돌렸는데 격차가 줄지 않았다
    no_more_evidence  계약은 충족됐는데 정지 규칙이 확정하지 않았다

`unobtainable`과 `no_more_evidence`를 나누는 이유: 전자는 **못 얻은 것**이고 후자는
**다 얻었는데 규칙이 확정을 안 한 것**이다. 섞으면 상한 기준선(`NeverStopRule`)의
결과가 "만들 수 없었다"로 잘못 기록된다(2026-09-22 테스트가 잡았다).
판정 기준은 `verdict.complete`이지 needs의 공백이 아니다 — `gap()`은 만들 수 없는
결손을 애초에 내보내지 않으므로 needs만 보면 두 경우가 같아 보인다.

**AI-C-19**: 이 루프는 관측·분석 provider만 부른다. 물리 행동이 필요한 결손은
요청으로 남기고 발급은 백엔드를 거친다 — 여기서 액추에이터를 움직이지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from mission_runtime.contracts.evidence_contract import (
    MissionContract,
    SufficiencyVerdict,
)
from mission_runtime.decision.evidence_gap import (
    DEFAULT_KIND_PROVIDERS,
    evaluate,
    gap,
)
from mission_runtime.decision.info_request import EvidenceNeed
from mission_runtime.perception.object_record import ObjectRecord

STOP_REASONS: tuple[str, ...] = (
    "satisfied", "exhausted", "unobtainable", "no_progress", "no_more_evidence",
)


@dataclass(frozen=True)
class ProviderChoice:
    """이번 회차에 부를 provider 하나."""

    capability_kind: str
    provider_id: str
    for_kind: str
    expected_cost_ms: float = 0.0


@dataclass
class Budget:
    """남은 자원. 루프가 스스로를 멈추는 유일한 외부 제약이다."""

    max_calls: int = 8
    max_cost_ms: float = float("inf")
    spent_calls: int = 0
    spent_cost_ms: float = 0.0
    #: 이미 부른 provider. **정책이 같은 것을 다시 고르지 않게 하는 유일한 근거**다.
    #: 2026-09-22 VisDrone 재생에서 이것이 없어 greedy가 가장 싼 provider를 두 번
    #: 골랐고, 두 번째 호출이 아무것도 바꾸지 못해 no_progress로 멈췄다. 그 결과
    #: 충분도 규칙이 한 건도 확정하지 못했다 — 규칙이 아니라 정책의 결함이었다.
    called: set = field(default_factory=set)

    def allows(self, cost_ms: float = 0.0) -> bool:
        return (self.spent_calls < self.max_calls
                and self.spent_cost_ms + cost_ms <= self.max_cost_ms)

    def charge(self, cost_ms: float, provider_id: str = "") -> None:
        self.spent_calls += 1
        self.spent_cost_ms += cost_ms
        if provider_id:
            self.called.add(provider_id)


class SelectionPolicy(Protocol):
    """다음 provider를 고르는 규칙. **교체 가능해야 한다**(AI-C-13).

    반환이 None이면 "더 부를 것이 없다"이며 루프는 정지한다.
    """

    name: str

    def next(self, needs: tuple[EvidenceNeed, ...], record: ObjectRecord,
             budget: Budget) -> ProviderChoice | None: ...


@dataclass
class Step:
    """한 회차의 기록. 무엇을 왜 불렀고 격차가 어떻게 변했는가."""

    index: int
    choice: ProviderChoice | None
    needs_before: tuple[str, ...]
    needs_after: tuple[str, ...]
    cost_ms: float
    at: float


@dataclass
class OrchestrationResult:
    """루프의 결과 — 최종 레코드와 **그렇게 멈춘 이유**."""

    record: ObjectRecord
    verdict: SufficiencyVerdict
    stop_reason: str
    steps: tuple[Step, ...] = field(default_factory=tuple)
    budget: Budget | None = None
    #: 왜 멈췄는가의 구조화된 기록. 조기 정지의 대가(FCR)를 사후에 세려면
    #: "무엇을 보고 충분하다고 했는가"가 남아야 한다(S4, AI-O-02).
    decision: "StopDecision | None" = None

    @property
    def calls(self) -> int:
        return sum(1 for s in self.steps if s.choice is not None)

    @property
    def cost_ms(self) -> float:
        return round(sum(s.cost_ms for s in self.steps), 3)

    @property
    def satisfied(self) -> bool:
        return self.stop_reason == "satisfied"


def _escalatable(needs: tuple[EvidenceNeed, ...],
                 table: dict[str, tuple[str, ...]]) -> tuple[EvidenceNeed, ...]:
    """승급 경로가 있는 결손만 남긴다.

    2026-09-22 헤드룸 계산에서 드러난 것 — `region_2d`처럼 더 비싼 대안이 없는 종류는
    **아낄 몫이 구조적으로 0**이다. 그런 종류를 정책에 넘기면 부를 수 없는 것을 놓고
    결정 비용만 쓴다(research/evidence_orchestration/run_headroom.py).
    """
    return tuple(n for n in needs if table.get(n.evidence_id))


def orchestrate(contract: MissionContract, record: ObjectRecord,
                policy: SelectionPolicy,
                execute: Callable[[ProviderChoice, ObjectRecord], ObjectRecord],
                budget: Budget | None = None,
                available_kinds: frozenset[str] | None = None,
                kind_providers: dict[str, tuple[str, ...]] | None = None,
                stop_rule=None,
                clock: Callable[[], float] = time.time) -> OrchestrationResult:
    """계약이 충족되거나 더 할 것이 없을 때까지 provider를 부른다.

    `execute`는 provider를 실제로 돌려 **갱신된 레코드**를 돌려준다. 여기서 직접
    모델을 부르지 않는 이유는 provider 경계를 넘지 않기 위해서다(AI-C-04) — replay
    하네스와 라이브 실행이 같은 루프를 쓸 수 있다.

    `stop_rule`을 갈아 끼우면 **같은 루프에서 비교군이 된다**(S4). 기본값은 계약
    충족이고, `ConfidenceRule`을 주면 cascade 기준선이 된다 — 별도 구현이 아니라
    규칙 하나만 다르므로 비교 조건이 어긋나지 않는다(AI-C-13).
    """
    from mission_runtime.decision.sufficiency import SufficiencyRule
    stop_rule = stop_rule or SufficiencyRule()
    table = kind_providers or DEFAULT_KIND_PROVIDERS
    budget = budget or Budget()
    steps: list[Step] = []
    index = 0

    while True:
        verdict = evaluate(contract, record, available_kinds, table)
        decision = stop_rule.decide(contract, record, verdict, budget.spent_cost_ms)
        if decision is not None:
            return OrchestrationResult(record, verdict, "satisfied", tuple(steps),
                                       budget, decision)

        needs = gap(contract, record, available_kinds, table)
        actionable = _escalatable(needs, table)
        if not actionable:
            # 판정으로 가른다. `gap()`은 `unobtainable`을 애초에 내보내지 않으므로
            # "needs가 비었다"만으로는 '다 얻었다'와 '못 얻는다'가 구분되지 않는다.
            reason = "no_more_evidence" if verdict.complete else "unobtainable"
            return OrchestrationResult(record, verdict, reason, tuple(steps), budget)
        if not budget.allows():
            return OrchestrationResult(record, verdict, "exhausted", tuple(steps), budget)

        choice = policy.next(actionable, record, budget)
        if choice is None or not budget.allows(choice.expected_cost_ms):
            return OrchestrationResult(record, verdict, "exhausted", tuple(steps), budget)

        before = tuple(n.evidence_id for n in needs)
        t0 = clock()
        record = execute(choice, record)
        cost = choice.expected_cost_ms or (clock() - t0) * 1000.0
        budget.charge(cost, choice.provider_id)
        after = tuple(n.evidence_id for n in
                      gap(contract, record, available_kinds, table))
        steps.append(Step(index, choice, before, after, cost, t0))
        index += 1

        if set(after) == set(before):
            # **격차가 줄지 않았다.** 같은 선택을 반복하면 예산만 태운다.
            # 실패 자체는 정보이므로 레코드에는 남기고 루프만 멈춘다(AI-O-02).
            verdict = evaluate(contract, record, available_kinds, table)
            return OrchestrationResult(record, verdict, "no_progress",
                                       tuple(steps), budget)
