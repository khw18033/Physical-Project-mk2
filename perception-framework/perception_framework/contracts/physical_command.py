"""Physical/function command lifecycle contract (AI-B-03 extension).

implements: AI-B-03, AI-C-01
tests: tests/test_physical_command_contract.py

This module defines the semantic contract for a command's lifecycle -
submit, accept-or-reject, run to a terminal state, and cancel - without
knowing or caring what the command actually does. `action`/`parameters`
stay opaque so this module never becomes a place to add domain-specific
branches (절대 준수 원칙 #3). Whether "action" ultimately means "start a
deployed AI function" or, behind a future hardware/backend adapter using
the same shape, "move a robot" is out of scope here - see AI-C-19: AI는
물리 명령 발급과 실제 센서·로봇·액추에이터 제어를 직접 소유해서는 안 된다.

Design references (D. Semantic Reference — 설계 원칙만 채택, 런타임
의존성은 만들지 않는다): ROS 2 Action state semantics (ACCEPTED/EXECUTING/
CANCELING/SUCCEEDED/ABORTED/CANCELED, rejected는 별도 필드로 분리) and
Google AIP-155 request idempotency (command_id가 request_id 역할을 겸함).
See docs/ai/design/external-technology-decisions.md §3 for the full design
record and docs/obsidian/papers/ros2-actions.md, docs/obsidian/papers/
aip-155.md for the underlying sources.

Wire encoding (JSON today, Protobuf as an additional canonical binding)
is a separate concern handled by SerializerProvider (AI-C-07) - these
dataclasses are the in-process Core Contract, not a wire format.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum


class ExecutionStatus(str, Enum):
    """Terminal-or-not execution state of an accepted command.

    REJECTED is intentionally absent here - a command that is not
    accepted never enters this state machine at all. Rejection is
    expressed as `CommandAcceptance.accepted = False`, matching the ROS 2
    Action rule that a rejected goal never becomes a state-machine state.
    """

    ACCEPTED = "ACCEPTED"
    EXECUTING = "EXECUTING"
    CANCELING = "CANCELING"
    SUCCEEDED = "SUCCEEDED"
    ABORTED = "ABORTED"
    CANCELED = "CANCELED"


TERMINAL_STATUSES = frozenset(
    {ExecutionStatus.SUCCEEDED, ExecutionStatus.ABORTED, ExecutionStatus.CANCELED}
)


class RejectionCode(str, Enum):
    """Mirrors gRPC status semantics on purpose so adapters do not invent
    a parallel error taxonomy (docs/ai/design/external-technology-decisions.md §3)."""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    FAILED_PRECONDITION = "FAILED_PRECONDITION"
    UNIMPLEMENTED = "UNIMPLEMENTED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    ALREADY_EXISTS = "ALREADY_EXISTS"


@dataclass(frozen=True)
class Command:
    """A request to execute one opaque `action` against one `target`.

    `command_id` is the idempotency identity (AIP-155 request_id role) -
    not a new field this project invented, but the same identifier the
    backend already issues for command audit (docs/ai/design/
    external-technology-decisions.md §3 — command_id vs trace_id).
    `correlation_id` is tracing-only and must never be used for
    idempotency comparison (see `payload_fingerprint`).
    `deadline` is "not after this instant may this command start"
    (epoch seconds), distinct from any transport-level message expiry.
    """

    command_id: str
    target: str
    action: str
    parameters: dict = field(default_factory=dict)
    correlation_id: str | None = None
    deadline: float | None = None

    def __post_init__(self) -> None:
        if not self.command_id or not self.target or not self.action:
            raise ValueError("command_id, target and action are required")
        if not isinstance(self.parameters, dict):
            raise TypeError("parameters must be a dict")
        if self.deadline is not None and not math.isfinite(self.deadline):
            raise ValueError("deadline must be finite")


@dataclass(frozen=True)
class Rejection:
    code: RejectionCode
    message: str


@dataclass(frozen=True)
class CommandAcceptance:
    """Answers exactly one question: did the executor take responsibility
    for this command? This is not a transport ACK and not a completion
    report - see the 3-way ACK split in docs/ai/design/
    external-technology-decisions.md §3.
    """

    command_id: str
    accepted: bool
    accepted_at: float
    rejection: Rejection | None = None

    def __post_init__(self) -> None:
        if self.accepted and self.rejection is not None:
            raise ValueError("an accepted CommandAcceptance must not carry a rejection")
        if not self.accepted and self.rejection is None:
            raise ValueError("a rejected CommandAcceptance must carry a rejection")


@dataclass(frozen=True)
class CommandStatus:
    """An optional in-flight status update, distinct from `CommandResult`:
    this may be sent zero or more times while non-terminal, `CommandResult`
    exactly once when terminal (see interface-spec §3, §4)."""

    command_id: str
    status: ExecutionStatus
    observed_at: float

    def __post_init__(self) -> None:
        if self.status in TERMINAL_STATUSES:
            raise ValueError("CommandStatus must not carry a terminal status; use CommandResult")


@dataclass(frozen=True)
class Failure:
    code: str
    message: str


@dataclass(frozen=True)
class CommandResult:
    """The terminal outcome of one accepted command. Constructing this
    with a non-terminal status is a programming error, not a valid state -
    status/result reporting and in-flight status polling are different
    concerns on purpose (get_status vs get_result in the supervisor)."""

    command_id: str
    status: ExecutionStatus
    completed_at: float
    result: dict | None = None
    failure: Failure | None = None

    def __post_init__(self) -> None:
        if self.status not in TERMINAL_STATUSES:
            raise ValueError(f"CommandResult.status must be a terminal state, got {self.status}")


@dataclass(frozen=True)
class CancelCommandRequest:
    command_id: str


@dataclass(frozen=True)
class CancelCommandResponse:
    """`accepted=True` means "the cancel procedure was entered", not
    "execution has already stopped". The terminal CANCELED state (if any)
    arrives later through CommandResult - see the cancel-race note in
    docs/ai/design/external-technology-decisions.md §3."""

    command_id: str
    accepted: bool
    reason: str | None = None


@dataclass(frozen=True)
class Capability:
    """Declares one action an executor supports, independent of any
    vendor SDK (docs/ai/design/external-technology-decisions.md §3 —
    design references: VDA 5050 factsheet, W3C WoT ActionAffordance)."""

    name: str
    version: str
    parameter_schema: str
    result_schema: str
    cancel_supported: bool = False
    required_resources: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not all((self.name, self.version, self.parameter_schema, self.result_schema)):
            raise ValueError("capability identity and schemas are required")

    def compatibility_profile(self):
        """Map action requirements into the existing provider placement contract."""
        from perception_framework.contracts.profile import CompatibilityProfile

        return CompatibilityProfile(required_runtime_tags=self.required_resources)


def payload_fingerprint(command: Command) -> str:
    """Stable hash of the semantic payload used for idempotency
    comparison: same command_id + same fingerprint = retry (return the
    cached acceptance, never re-execute); same command_id + different
    fingerprint = conflict (AIP-155 request identification).

    `correlation_id` and `deadline` are excluded on purpose - a retried
    command may legitimately carry a fresh correlation_id or an extended
    deadline without being "a different command".
    """

    payload = {"target": command.target, "action": command.action, "parameters": command.parameters}
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
