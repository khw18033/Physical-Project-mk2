"""Common execution control interface + local reference supervisor (AI-B-03).

Upper-layer code only ever calls control operations shaped like this;
the current deployment routes them through 서버 Kafka -> 엣지 Bridge ->
말단 MQTT, but no AI code should import those clients directly
(AI-C-06). Command audit (업무상 책임 추적) and technical trace
(지연·처리경로 추적) are kept as two separate logs on purpose (AI-B-03:
"업무상 명령 이력·책임 추적과 기술적 처리 경로·지연 추적은 서로 다른
목적으로 관리해야 하며 하나의 기록으로 합쳐서는 안 된다").
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class TargetStatus(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"


@dataclass(frozen=True)
class ControlResult:
    accepted: bool
    final_status: TargetStatus | None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class AuditEntry:
    command: str
    target_id: str
    requested_by: str
    at: float


@dataclass(frozen=True)
class TraceEntry:
    command: str
    target_id: str
    latency_ms: float
    at: float


class LocalControlSupervisor:
    """Reference ControlProvider implementation managing named
    in-process targets — a fake stand-in until a real orchestrator
    (K3s, systemd, ...) provider is wired in behind the same interface.
    """

    def __init__(self) -> None:
        self._status: dict[str, TargetStatus] = {}
        self.audit_log: list[AuditEntry] = []
        self.trace_log: list[TraceEntry] = []

    def request(
        self,
        command: str,
        target_id: str,
        params: dict | None = None,
        *,
        requested_by: str = "unknown",
    ) -> ControlResult:
        start = time.time()
        self.audit_log.append(AuditEntry(command, target_id, requested_by, start))

        if command == "start":
            self._status[target_id] = TargetStatus.RUNNING
            result = ControlResult(True, TargetStatus.RUNNING)
        elif command == "stop":
            self._status[target_id] = TargetStatus.STOPPED
            result = ControlResult(True, TargetStatus.STOPPED)
        elif command == "restart":
            if target_id not in self._status:
                result = ControlResult(False, None, rejection_reason="unknown_target")
            else:
                self._status[target_id] = TargetStatus.RUNNING
                result = ControlResult(True, TargetStatus.RUNNING)
        else:
            result = ControlResult(False, None, rejection_reason=f"unsupported_command:{command}")

        self.trace_log.append(TraceEntry(command, target_id, (time.time() - start) * 1000, start))
        return result

    def get_status(self, target_id: str) -> TargetStatus:
        return self._status.get(target_id, TargetStatus.STOPPED)
