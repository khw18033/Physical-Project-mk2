"""Resource-driven reconfiguration loop: observe -> re-resolve -> record.

implements: AI-B-06, AI-C-13, AI-O-01, AI-O-02

AI-B-06: "운영 중 자원 부족, 과열, 지연 증가, 실행 노드 또는 기능 제공자 소실이
발생하면 현재 사용 가능한 실행 후보를 다시 평가해 ... 대체 후보가 없으면 우선순위가
낮은 선택 기능부터 축소하고 핵심 기능은 유지해야 한다."

The reconfigurer owns no policy of its own about *what* a capability is —
it only turns an observed resource snapshot into a new budget, asks the
application to re-resolve, and reports the transitions as individual
events (AI-O-02) with the latency each transition took (AI-O-01).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from perception_framework.contracts.capability import CapabilityState
from perception_framework.contracts.profile import ResourceBudget
from perception_framework.runtime.application import ZoneApplication


@dataclass(frozen=True)
class ResourceSnapshot:
    """What the observability layer currently measures on this node.

    Deliberately expressed as utilisation ratios plus totals rather than
    vendor counters, so the same struct describes a laptop, an edge box or
    a terminal board (AI-B-01).
    """

    # Utilisation caused by everything *other* than the capabilities this
    # application is deciding about — i.e. the headroom left for them.
    # Measuring it this way keeps the budget meaningful when the app's own
    # capabilities are stopped and restarted during reconfiguration.
    cpu_utilisation: float  # 0.0 ~ 1.0
    memory_utilisation: float  # 0.0 ~ 1.0
    total_compute_units: float
    total_memory_mb: float
    max_latency_ms: float | None = None

    def to_budget(self) -> ResourceBudget:
        """Remaining headroom, never negative."""
        return ResourceBudget(
            compute_units=max(0.0, self.total_compute_units * (1.0 - self.cpu_utilisation)),
            memory_mb=max(0.0, self.total_memory_mb * (1.0 - self.memory_utilisation)),
            max_latency_ms=self.max_latency_ms,
        )


@dataclass(frozen=True)
class StateTransition:
    kind: str
    before: CapabilityState
    after: CapabilityState
    at: float
    latency_ms: float

    @property
    def is_degradation(self) -> bool:
        order = {CapabilityState.ACTIVE: 2, CapabilityState.DEGRADED: 1, CapabilityState.DISABLED: 0}
        return order[self.after] < order[self.before]


class ResourceAdaptiveReconfigurer:
    """Re-resolves the application whenever the observed resources move."""

    def __init__(self, application: ZoneApplication, observability=None) -> None:
        self._app = application
        self._observability = observability
        self.transitions: list[StateTransition] = []

    def apply_snapshot(self, snapshot: ResourceSnapshot) -> dict[str, CapabilityState]:
        started = time.time()
        before = {kind: self._app.state_of(kind) for kind in self._app.active_kinds}

        resolutions = self._app.resolve(snapshot.to_budget())

        latency_ms = (time.time() - started) * 1000
        for kind, resolution in resolutions.items():
            previous = before.get(kind, CapabilityState.DISABLED)
            if previous is resolution.state:
                continue
            transition = StateTransition(kind, previous, resolution.state, started, latency_ms)
            self.transitions.append(transition)
            self._report(transition, resolution.reason)

        return {kind: res.state for kind, res in resolutions.items()}

    def _report(self, transition: StateTransition, reason: str) -> None:
        """A capability going DISABLED is an individual event, not a number
        inside a metric summary (원칙 #14, AI-O-02)."""
        if self._observability is None:
            return
        severity = "warning" if transition.is_degradation else "info"
        if transition.after is CapabilityState.DISABLED:
            severity = "error"
        try:
            self._observability.record_event(
                "capability_state_changed",
                severity,
                {
                    "capability_kind": transition.kind,
                    "before": transition.before.value,
                    "after": transition.after.value,
                    "reason": reason,
                },
            )
        except Exception:
            # 관측 실패가 재구성 자체를 막아서는 안 된다 (AI-O-01).
            return

    # --- indicators (문서 §18 지표) ----------------------------------------
    def degradation_count(self) -> int:
        return sum(1 for t in self.transitions if t.is_degradation)

    def recovery_count(self) -> int:
        return sum(1 for t in self.transitions if not t.is_degradation)

    def max_transition_latency_ms(self) -> float:
        return max((t.latency_ms for t in self.transitions), default=0.0)
