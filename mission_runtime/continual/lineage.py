"""Auditable AI-L-01~08 learning/apply lineage state machine.

implements: AI-L-01, AI-L-02, AI-L-03, AI-L-04, AI-L-05, AI-L-06, AI-L-07, AI-L-08
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LearningState(str, Enum):
    CANDIDATE = "candidate"
    QUARANTINED = "quarantined"
    REVIEWED = "reviewed"
    STRATEGY_SELECTED = "strategy_selected"
    VALIDATED = "validated"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    VERIFIED = "verified"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class LineageEvent:
    sequence: int
    requirement_id: str
    state: LearningState
    actor: str
    evidence_ref: str
    reason: str


_TRANSITIONS: dict[LearningState, tuple[LearningState, str]] = {
    LearningState.CANDIDATE: (LearningState.QUARANTINED, "AI-L-02"),
    LearningState.QUARANTINED: (LearningState.REVIEWED, "AI-L-03"),
    LearningState.REVIEWED: (LearningState.STRATEGY_SELECTED, "AI-L-04"),
    LearningState.STRATEGY_SELECTED: (LearningState.VALIDATED, "AI-L-05"),
    LearningState.VALIDATED: (LearningState.APPROVAL_PENDING, "AI-L-06"),
    LearningState.APPROVAL_PENDING: (LearningState.APPROVED, "AI-L-06"),
    LearningState.APPROVED: (LearningState.DEPLOYED, "AI-L-07"),
    LearningState.DEPLOYED: (LearningState.VERIFIED, "AI-L-08"),
}


class LearningLineage:
    """Append-only lifecycle; all transitions require evidence and an actor."""

    def __init__(self, lineage_id: str, *, actor: str, evidence_ref: str, reason: str) -> None:
        self.lineage_id = lineage_id
        self._events = [LineageEvent(1, "AI-L-01", LearningState.CANDIDATE, actor, evidence_ref, reason)]

    @property
    def state(self) -> LearningState:
        return self._events[-1].state

    @property
    def events(self) -> tuple[LineageEvent, ...]:
        return tuple(self._events)

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        """Every reference this lineage has actually cited, in order.

        Append-only, so a reference that was cited once cannot later be removed
        to make a record look consistent (AI-L-03: 되돌림도 삭제가 아니라 기록이다).
        """
        return tuple(event.evidence_ref for event in self._events)

    def cites(self, evidence_ref: str) -> bool:
        """Did this lineage ever cite that reference as evidence?

        이것이 "그 계보가 그 물건에 대한 것인가" 를 **기록에서 유도하는** 유일한
        방법이다. 첫 사건의 `evidence_ref` 를 주인으로 읽으면 안 된다 — AI-L-01 의
        첫 근거는 학습이 필요해진 **운영 사건**일 수도 있고(`tools/fms_console/
        twin.py` 가 그렇게 연다) 산출된 파라미터 버전일 수도 있어서, 한쪽으로
        정하면 다른 쪽이 조용히 틀린다. 반면 "든 적이 있는가" 는 어느 쪽이든
        맞고, 다른 후보의 계보는 이 후보의 버전을 든 적이 없다(AI-L-08).
        """
        return bool(evidence_ref) and evidence_ref in self.evidence_refs

    def advance(self, *, actor: str, evidence_ref: str, reason: str) -> LineageEvent:
        if self.state not in _TRANSITIONS:
            raise ValueError(f"cannot advance terminal state {self.state.value}")
        next_state, requirement_id = _TRANSITIONS[self.state]
        return self._append(next_state, requirement_id, actor, evidence_ref, reason)

    def rollback(self, *, actor: str, evidence_ref: str, reason: str) -> LineageEvent:
        if self.state not in (LearningState.DEPLOYED, LearningState.VERIFIED):
            raise ValueError("rollback is only valid after deployment")
        return self._append(LearningState.ROLLED_BACK, "AI-L-07", actor, evidence_ref, reason)

    def _append(
        self,
        state: LearningState,
        requirement_id: str,
        actor: str,
        evidence_ref: str,
        reason: str,
    ) -> LineageEvent:
        if not actor or not evidence_ref or not reason:
            raise ValueError("actor, evidence_ref and reason are mandatory")
        event = LineageEvent(len(self._events) + 1, requirement_id, state, actor, evidence_ref, reason)
        self._events.append(event)
        return event
