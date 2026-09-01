"""Structured error/anomaly event recording, reported immediately rather
than waiting on a metric aggregation window (AI-O-02).

implements: AI-O-02

A capability going DEGRADED because an *optional* dependency is simply
absent must be distinguished from a genuine failure of a
required/core capability going DISABLED (AI-O-02: "선택 기능이 없는
정상적인 축소 운용과 핵심 기능 실패를 구분하고...").
"""

from __future__ import annotations

from dataclasses import dataclass

from perception_framework.contracts.capability import CapabilityState
from perception_framework.providers.adapters import ObservabilityProvider


@dataclass(frozen=True)
class CapabilityStateChange:
    capability_kind: str
    previous: CapabilityState
    current: CapabilityState


class CapabilityEventReporter:
    def __init__(self, observability: ObservabilityProvider) -> None:
        self._observability = observability

    def report_transition(self, change: CapabilityStateChange) -> None:
        # DISABLED means a *required* condition failed -> genuine
        # failure. DEGRADED/ACTIVE only reflect optional conditions ->
        # normal reduced operation, not a fault.
        severity = "critical" if change.current is CapabilityState.DISABLED else "info"
        self._observability.record_event(
            "capability_state_change",
            severity=severity,
            payload={
                "capability_kind": change.capability_kind,
                "previous": change.previous.value,
                "current": change.current.value,
            },
        )
