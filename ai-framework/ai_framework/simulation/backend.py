"""Mock of the *backend's* integrated device-availability verdict.

implements: (mock for) BE-side integration consumed by AI-O-04, AI-C-10

원칙 #15 / AI-C-10: 장치 최종 가용성은 백엔드가 업무 전송 상태와 관측 상태를
통합해 판정하며, AI가 이를 중복 구현하지 않는다. 그래서 이 규칙은 프레임워크
핵심이 아니라 `simulation` 아래의 **백엔드 대역(mock)** 으로만 존재한다. 실제
백엔드가 준비되면 이 클래스를 지우고 그 API를 붙이면 되고, AI 코드는 바뀌지
않는다.

판정 규칙은 전송 아키텍처 6-5를 그대로 따른다: 두 신호가 다르면 **업무 세션을
1차 기준**으로 삼는다 — "metric이 나오니까 살아 있다"가 아니라 "실제로 업무
명령을 주고받을 수 있는가"가 기준이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ai_framework.observability.availability import AvailabilitySignals, SignalStatus


class DeviceAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ObservabilityHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class AvailabilityVerdict:
    device_id: str
    availability: DeviceAvailability
    observability: ObservabilityHealth
    signal_status: SignalStatus


class BackendAvailabilityIntegrator:
    """Stands in for the backend's single integration point."""

    def __init__(self) -> None:
        self._signals: dict[str, AvailabilitySignals] = {}

    def report(self, device_id: str, *, task_transport_alive: bool, observability_alive: bool) -> None:
        self._signals[device_id] = AvailabilitySignals(task_transport_alive, observability_alive)

    def verdict(self, device_id: str) -> AvailabilityVerdict:
        signals = self._signals.get(device_id, AvailabilitySignals(False, False))
        availability = (
            DeviceAvailability.AVAILABLE
            if signals.task_transport_alive
            else DeviceAvailability.UNAVAILABLE
        )
        observability = (
            ObservabilityHealth.HEALTHY if signals.observability_alive else ObservabilityHealth.DEGRADED
        )
        return AvailabilityVerdict(device_id, availability, observability, signals.status)

    def is_available(self, device_id: str) -> bool:
        """The single boolean AI is allowed to consume (AI-C-10)."""
        return self.verdict(device_id).availability is DeviceAvailability.AVAILABLE
