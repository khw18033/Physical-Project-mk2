"""Distinguishes task-transport signal from observability signal so the
backend can integrate them into final device availability — this module
never recomputes that final verdict itself (AI-O-04, 절대 준수 원칙 #15).

implements: AI-O-04

It exposes exactly the distinction the requirement calls for: "업무
전송은 가능하지만 관측 지표가 누락된 경우"와 "관측 지표는 존재하지만
업무 세션이 끊긴 경우"를 구분할 수 있어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SignalStatus(str, Enum):
    TASK_TRANSPORT_ONLY = "TASK_TRANSPORT_ONLY"  # 업무 전송 가능, 관측 지표 누락
    OBSERVABILITY_ONLY = "OBSERVABILITY_ONLY"  # 관측 지표 존재, 업무 세션 끊김
    BOTH_PRESENT = "BOTH_PRESENT"
    NEITHER_PRESENT = "NEITHER_PRESENT"


@dataclass(frozen=True)
class AvailabilitySignals:
    task_transport_alive: bool
    observability_alive: bool

    @property
    def status(self) -> SignalStatus:
        if self.task_transport_alive and self.observability_alive:
            return SignalStatus.BOTH_PRESENT
        if self.task_transport_alive:
            return SignalStatus.TASK_TRANSPORT_ONLY
        if self.observability_alive:
            return SignalStatus.OBSERVABILITY_ONLY
        return SignalStatus.NEITHER_PRESENT


class RemoteFeatureGate:
    """Consumes the backend's already-integrated availability verdict to
    decide whether a remote-hosted optional capability may be selected —
    never re-derives that verdict from the raw signals itself (AI-C-10:
    "장치의 최종 가용성을 별도로 중복 판정해서는 안 된다").
    """

    def may_select_remote_capability(self, backend_integrated_available: bool) -> bool:
        return backend_integrated_available
