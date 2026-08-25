"""Subtask regeneration trigger (AI-D-04).

Regeneration must fire only when a subtask's precondition has actually
broken — path blocked, target lost, evidence expired — never for a mere
observation update. Emergency collision avoidance stays with the
on-device safety feature (AI-N-01); this module only ever distinguishes
a zone-local subtask regeneration from a request to change the *main
mission* itself, which must go to the backend (AI-D-04: "긴급 충돌
회피는 온디바이스 안전 기능이 담당하고 메인 임무 자체의 변경은 백엔드에
요청해야 한다").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegenerationScope(str, Enum):
    NONE = "NONE"
    ZONE_SUBTASK = "ZONE_SUBTASK"
    MISSION_BACKEND = "MISSION_BACKEND"


_BLOCKING_EVENT_KINDS = {"path_blocked", "target_lost", "evidence_expired"}
_MISSION_LEVEL_EVENT_KINDS = {"mission_conflict", "zone_permanently_unreachable"}


@dataclass(frozen=True)
class RegenerationDecision:
    scope: RegenerationScope
    reason: str


class RegenerationEvaluator:
    def evaluate(self, event_kind: str) -> RegenerationDecision:
        if event_kind in _MISSION_LEVEL_EVENT_KINDS:
            return RegenerationDecision(RegenerationScope.MISSION_BACKEND, reason=event_kind)
        if event_kind in _BLOCKING_EVENT_KINDS:
            return RegenerationDecision(RegenerationScope.ZONE_SUBTASK, reason=event_kind)
        return RegenerationDecision(RegenerationScope.NONE, reason="observation_only")
