"""언제 멈출 것인가 — 그리고 **틀리게 멈춘 대가를 센다.**

implements: AI-S-03, AI-S-04, AI-O-02, AI-C-13
근거: internal/docs-dev/obsidian/ideas/evidence-driven-orchestration-plan.md §3 S4, §7-2

조기 정지가 자원을 아끼는 메커니즘이고, 그 대가는 **틀린 확정**이다. 그래서 정지
규칙과 그 회계를 한 모듈에 둔다 — 아끼기만 하고 대가를 세지 않으면 비교가 성립하지
않는다.

**두 규칙이 경쟁한다.**

    ConfidenceRule    한 모델의 conf ≥ τ 이면 멈춘다
    SufficiencyRule   계약이 요구한 근거가 모이면 멈춘다 (독립 소스 수로 센다)

AI-S-03이 "모델이 제공하는 신뢰도와 현재 업무가 요구하는 근거가 실제로 확보되었는지를
구분해 평가"하라고 한 지점이 정확히 여기다. 둘은 다른 것을 재고, **신뢰도로 멈추면
임계를 올려도 못 고치는 오류가 남는다** — 2026-09-21 실측: YOLOE가 백팩을
`computer chair 0.83`, 캐비닛을 `flipchart 0.94`로 불렀다. 0.94 위에 임계를 두면
맞는 것도 전부 버린다. 독립 두 소스의 합의로만 걸렸다.

FCR = 틀린 확정 / 전체 확정. **동일 자원 지점에서 비교해야** 의미가 있다 —
적게 확정하면 FCR은 자동으로 낮아지므로, 확정 수(coverage)와 함께 본다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from mission_runtime.contracts.evidence_contract import (
    MissionContract,
    SufficiencyVerdict,
)
from mission_runtime.perception.object_record import ObjectRecord


@dataclass(frozen=True)
class StopDecision:
    """왜 멈췄는가 — **사후에 대가를 셀 수 있을 만큼** 남긴다.

    `basis`가 핵심이다. "무엇을 보고 충분하다고 했는가"가 없으면 나중에 그 판단이
    틀렸을 때 원인을 되짚을 수 없다(AI-O-02: 구조화된 사건 기록).
    """

    rule: str
    confirmed: bool
    basis: str
    claimed_class: str | None = None
    supporting_groups: int = 0
    confidence: float = 0.0
    cost_ms: float = 0.0
    unmet: tuple[str, ...] = ()


class StopRule(Protocol):
    """정지 규칙. **교체 가능해야 비교가 성립한다**(AI-C-13)."""

    name: str

    def decide(self, contract: MissionContract, record: ObjectRecord,
               verdict: SufficiencyVerdict, cost_ms: float) -> StopDecision | None: ...


@dataclass
class SufficiencyRule:
    """계약이 요구한 근거가 모이면 멈춘다 — **제안 규칙**.

    의미 충족은 신뢰도가 아니라 **독립 소스 수**로 센다(`evidence_gap._quality`).
    그래서 한 모델이 0.94로 틀려도 혼자서는 확정에 이르지 못한다.
    """

    name: str = "sufficiency"

    def decide(self, contract, record, verdict, cost_ms) -> StopDecision | None:
        if not verdict.complete:
            return None
        return StopDecision(
            rule=self.name, confirmed=True,
            basis=f"계약 {contract.mission_id}#{contract.revision} 충족 "
                  f"(독립 소스 {record.supporting_groups})",
            claimed_class=record.semantic_class,
            supporting_groups=record.supporting_groups,
            confidence=record.confidence, cost_ms=cost_ms)


@dataclass
class ConfidenceRule:
    """한 모델의 conf가 임계를 넘으면 멈춘다 — **비교군(cascade)**.

    계약을 보지 않는다. 그것이 이 규칙의 정의이자 결함이다.
    """

    threshold: float = 0.5
    name: str = "confidence"

    def decide(self, contract, record, verdict, cost_ms) -> StopDecision | None:
        if record.confidence < self.threshold:
            return None
        return StopDecision(
            rule=self.name, confirmed=True,
            basis=f"conf {record.confidence:.2f} ≥ {self.threshold}",
            claimed_class=record.semantic_class,
            supporting_groups=record.supporting_groups,
            confidence=record.confidence, cost_ms=cost_ms,
            unmet=verdict.unmet_kinds)


@dataclass
class NeverStopRule:
    """예산이 다할 때까지 전부 부른다 — **상한 기준선**."""

    name: str = "all_providers"

    def decide(self, contract, record, verdict, cost_ms) -> StopDecision | None:
        return None


@dataclass
class Confirmation:
    """한 객체에 대한 확정 1건과 대조용 정답 자리."""

    object_id: str
    decision: StopDecision
    truth_class: str | None = None

    @property
    def scored(self) -> bool:
        return self.truth_class is not None

    @property
    def wrong(self) -> bool:
        """**정답을 모르면 틀렸다고 세지 않는다.** 미채점으로 남긴다."""
        return self.scored and self.decision.claimed_class != self.truth_class


@dataclass
class FCRLedger:
    """확정 장부 — FCR과 coverage를 **함께** 낸다.

    FCR만 보면 안 되는 이유: 아무것도 확정하지 않으면 FCR이 0이다. 적게 확정해서
    얻은 낮은 FCR은 성능이 아니므로, 항상 coverage·비용과 나란히 보고한다(§7-2).
    """

    rule: str
    items: list[Confirmation] = field(default_factory=list)

    def add(self, object_id: str, decision: StopDecision,
            truth_class: str | None = None) -> None:
        if decision.confirmed:
            self.items.append(Confirmation(object_id, decision, truth_class))

    def settle(self, truths: dict[str, str]) -> None:
        """나중에 정답이 들어오면 채운다(replay·라벨 지연 대응)."""
        self.items = [
            Confirmation(c.object_id, c.decision,
                         c.truth_class if c.truth_class is not None
                         else truths.get(c.object_id))
            for c in self.items
        ]

    @property
    def confirmed(self) -> int:
        return len(self.items)

    @property
    def scored(self) -> int:
        return sum(1 for c in self.items if c.scored)

    @property
    def wrong(self) -> int:
        return sum(1 for c in self.items if c.wrong)

    @property
    def fcr(self) -> float | None:
        """틀린 확정 / **채점된** 확정. 채점할 것이 없으면 None이다."""
        return (self.wrong / self.scored) if self.scored else None

    @property
    def cost_ms(self) -> float:
        return round(sum(c.decision.cost_ms for c in self.items), 3)

    def report(self, total_objects: int | None = None) -> dict:
        n = total_objects or self.confirmed
        return {
            "rule": self.rule,
            "confirmed": self.confirmed,
            "coverage": round(self.confirmed / n, 4) if n else 0.0,
            "scored": self.scored,
            "wrong": self.wrong,
            "fcr": None if self.fcr is None else round(self.fcr, 4),
            "cost_ms": self.cost_ms,
            "cost_ms_per_confirmation": (
                round(self.cost_ms / self.confirmed, 2) if self.confirmed else 0.0),
        }
