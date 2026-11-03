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
