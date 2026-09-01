"""Risk analysis state management (AI-R-01).

implements: AI-R-01

The FSM only activates when this deployment actually registers at least
one risk-relevant event kind — no sensor type or domain (river,
facility, ...) is hardcoded here. With no risk input registered at all,
only this analysis feature stays inactive; nothing else in the
framework is affected (AI-R-01: "위험 입력이 없으면 위험 분석 기능만
비활성화하고 다른 기능은 계속 동작해야 한다").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskAnalysisState(str, Enum):
    INACTIVE = "INACTIVE"  # no risk-relevant input registered at all
    NORMAL = "NORMAL"  # 평시
    OBSERVING = "OBSERVING"  # 관찰
    ALERT = "ALERT"  # 경보
    RECOVERY = "RECOVERY"  # 복구


@dataclass(frozen=True)
class RiskEvent:
    kind: str
    severity: float  # 0..1; meaning is rule-defined, not fixed by the framework


class RiskAnalysisFsm:
    """`registered_event_kinds` defines what this deployment even
    considers risk-relevant. An event of an unregistered kind is simply
    ignored, never treated as an error.
    """

    def __init__(
        self,
        registered_event_kinds: set[str],
        *,
        observe_threshold: float = 0.3,
        alert_threshold: float = 0.7,
        recovery_threshold: float = 0.3,
        observe_release: float | None = None,
    ) -> None:
        self._registered_event_kinds = set(registered_event_kinds)
        self._observe_threshold = observe_threshold
        self._alert_threshold = alert_threshold
        self._recovery_threshold = recovery_threshold
        # Leaving OBSERVING requires severity to fall clearly below the level
        # that entered it. Without this the boundary is bare: severity hovering
        # at the threshold flips the state on every event, and each flip raises
        # or lowers the observation level asked of the rest of the system
        # (AI-R-04). ALERT already had this protection via `recovery_threshold`;
        # the observe boundary did not.
        self._observe_release = (observe_release if observe_release is not None
                                 else observe_threshold * 0.9)
        self._state = RiskAnalysisState.NORMAL if registered_event_kinds else RiskAnalysisState.INACTIVE

    @property
    def state(self) -> RiskAnalysisState:
        return self._state

    def process(self, event: RiskEvent) -> RiskAnalysisState:
        if self._state is RiskAnalysisState.INACTIVE:
            return self._state
        if event.kind not in self._registered_event_kinds:
            return self._state

        severity = event.severity
        if severity >= self._alert_threshold:
            self._state = RiskAnalysisState.ALERT
        elif self._state is RiskAnalysisState.ALERT:
            self._state = RiskAnalysisState.RECOVERY if severity < self._recovery_threshold else RiskAnalysisState.ALERT
        elif self._state is RiskAnalysisState.RECOVERY:
            self._state = RiskAnalysisState.NORMAL if severity < self._recovery_threshold else RiskAnalysisState.RECOVERY
        elif severity >= self._observe_threshold:
            self._state = RiskAnalysisState.OBSERVING
        elif self._state is RiskAnalysisState.OBSERVING:
            if severity < self._observe_release:
                self._state = RiskAnalysisState.NORMAL
        else:
            self._state = RiskAnalysisState.NORMAL

        return self._state
