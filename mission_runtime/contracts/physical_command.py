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
See docs/technology-boundaries.md §3 for the full design
record and internal/docs-dev/obsidian/papers/ros2-actions.md, internal/docs-dev/obsidian/papers/
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

# AI-C-18 선언 항목 토큰과 값 어휘의 정본은 `capability_contract` 다. 여기서
# 베껴 두면 두 곳이 갈리므로 읽어 온다. 역방향 import 는 없다 — 그 모듈은
# 물리 명령을 모른다.
from mission_runtime.contracts.capability_contract import (
    INVOCATION_MODES,
    ITEM_BASIS,
    ITEM_CANCELLABLE,
    ITEM_EXECUTION_CONDITIONS,
    ITEM_IDEMPOTENT,
    ITEM_INPUT_SCHEMA,
    ITEM_INVOCATION,
    ITEM_OUTPUT_SCHEMA,
    ITEM_PERFORMANCE,
    ITEM_SCOPE,
    ITEM_VERSION,
    Capability as CapabilityDeclaration,
    DeclarationBasis,
)


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
    a parallel error taxonomy (docs/technology-boundaries.md §3)."""

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
    backend already issues for command audit (비공개 설계 노트
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
    report - see the 3-way ACK split in 비공개 설계 노트
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
    docs/technology-boundaries.md §3."""

    command_id: str
    accepted: bool
    reason: str | None = None


@dataclass(frozen=True)
class Capability:
    """Declares one action an executor supports, independent of any
    vendor SDK (docs/technology-boundaries.md §3 —
    design references: VDA 5050 factsheet, W3C WoT ActionAffordance).

    `name` 만 필수다. 나머지 선언 항목은 **선언되지 않았을 수 있다** —
    AI-C-18 이 "모든 항목이 항상 존재한다고 가정해서는 안 된다"고 정한 그대로다.
    실제로 현재 HW 와이어(spec §8-3 P7)는 action 이름 목록만 싣기 때문에
    그 경로로 들어온 선언은 version/schema 가 `None` 이다. 없는 값을
    빈 문자열이나 placeholder 로 지어내지 않기 위해 None 을 허용한다 —
    `is_fully_declared()` 로 "덜 선언된 것"과 "다 선언된 것"을 구분한다.

    ## 2026-11-04: "모른다" 와 "안 된다" 를 가른다

    그 전까지 `cancel_supported` 는 `bool = False` 였다. 선언하지 않은 장치와
    **취소를 지원하지 않는다고 선언한** 장치가 같은 값이 되고, 상위 기능은
    아무도 말하지 않은 것을 "이 장치는 취소를 거부한다" 로 읽었다. 지금 와이어가
    이 항목을 싣지 못하므로(spec §8-3 P7) 들어오는 모든 선언이 그 거짓에 걸렸다.
    세 값(True/False/None)으로 바꾼 이유가 이것이고, AI-C-20 의 "취소 수락과
    CANCELED 도달은 다르다" 는 구분이 이 선언 위에 서 있다.

    같은 이유로 `idempotent` 를 새로 둔다. 같은 `command_id` 재전달을 다시
    실행하지 않는 것은 프레임워크가 보장하지만(`payload_fingerprint`), **다른
    command_id 로 같은 입력을 다시 보내도 되는가**는 action 의 성질이고 장치만
    답할 수 있다 — "좌표 X 로 가라" 와 "1m 전진" 은 같은 입력을 두 번 받았을 때
    물리 결과가 다르다. 이 칸이 없으면 재시도 정책이 그 차이를 모른다.
    """

    name: str
    version: str | None = None
    parameter_schema: str | None = None
    result_schema: str | None = None
    #: 취소 가능 여부. **세 값이다**: True(가능하다고 선언) / False(불가능하다고
    #: 선언) / None(아무도 선언하지 않았다). None 을 False 로 접지 않는다.
    cancel_supported: bool | None = None
    required_resources: tuple[str, ...] = field(default_factory=tuple)
    #: 선택 실행 조건. 없어도 실행은 되고 품질·효율만 떨어진다(AI-C-05).
    optional_resources: tuple[str, ...] = field(default_factory=tuple)
    #: 동일 입력 반복 호출 특성. 여기도 세 값이고 None 은 "멱등하지 않다" 가 아니다.
    idempotent: bool | None = None
    #: 동기·비동기 특성. 값 어휘는 `capability_contract.INVOCATION_MODES`.
    invocation: str | None = None
    #: 단위·좌표·시간 기준(AI-C-02/03). 객체가 없으면 기준을 모르는 것이다.
    basis: DeclarationBasis | None = None
    #: 수행·관측 범위. None 은 미선언이고 `()` 는 "범위 제약 없음" 선언이다.
    scope_tags: tuple[str, ...] | None = None
    #: 이 action 의 품질·지연·자원 **실측** 근거를 가리키는 참조. 실측값 자체는
    #: AI-B-01 의 `ExecutionProfile` 이 소유하므로 여기에 숫자를 베껴 두지 않는다 —
    #: 베끼면 같은 사실에 주인이 둘이 되고, 고정 조건이 달라졌을 때 어느 쪽이
    #: 낡았는지 알 수 없다.
    execution_profile_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("capability name is required")
        for declared in (self.version, self.parameter_schema, self.result_schema,
                         self.invocation, self.execution_profile_ref):
            if declared is not None and not declared:
                raise ValueError("a declared capability field must not be empty")
        if self.invocation is not None and self.invocation not in INVOCATION_MODES:
            raise ValueError(
                f"invocation='{self.invocation}' 은 어휘 밖이다(허용: {INVOCATION_MODES})."
            )

    # -- 선언 완전성 (AI-C-18) --------------------------------------------

    def undeclared_items(self) -> tuple[str, ...]:
        """이 선언이 **적지 않은** AI-C-18 항목들(닫힌 토큰 어휘
        `capability_contract.CAPABILITY_DECLARATION_ITEMS`).

        `ITEM_STATE`(현재 상태)는 여기 들어오지 않는다 — 선언은 "무엇을 할 수
        있는가" 이고 지금 되는가는 health·가용성 계층의 사실이다(AI-O-04,
        절대 준수 원칙 #15). 그 항목의 주인은 `RuntimeInstance` 다.

        기본값을 선언으로 읽지 않는다: 빈 묶음은 "조건 없음" 이 아니라 "적지
        않음" 으로 센다.
        """
        missing: list[str] = []
        if self.version is None:
            missing.append(ITEM_VERSION)
        if self.parameter_schema is None:
            missing.append(ITEM_INPUT_SCHEMA)
        if self.result_schema is None:
            missing.append(ITEM_OUTPUT_SCHEMA)
        if self.basis is None:
            missing.append(ITEM_BASIS)
        if not self.required_resources and not self.optional_resources:
            missing.append(ITEM_EXECUTION_CONDITIONS)
        if self.cancel_supported is None:
            missing.append(ITEM_CANCELLABLE)
        if self.idempotent is None:
            missing.append(ITEM_IDEMPOTENT)
        if self.invocation is None:
            missing.append(ITEM_INVOCATION)
        if self.scope_tags is None:
            missing.append(ITEM_SCOPE)
        if self.execution_profile_ref is None:
            missing.append(ITEM_PERFORMANCE)
        return tuple(missing)

    def is_fully_declared(self) -> bool:
        """AI-C-18 선언 항목이 모두 채워졌는가. 덜 채워진 선언도 유효한
        선언이지만, 선택·검증에서 그 차이를 알아야 하는 쪽이 있다.

        2026-11-04 부터 이 판정은 요구사항이 열거한 항목 **전부**를 본다. 그
        전에는 version/schema 둘만 보아서, 취소 가능 여부와 멱등성을 아무도
        선언하지 않은 장치가 "다 선언됐다" 로 읽혔다.
        """
        return not self.undeclared_items()

    @property
    def cancel_support_known(self) -> bool:
        """취소 가능 여부를 **누군가 선언했는가**. 거짓이면 미선언이고, 그때
        "취소할 수 없다" 로 처리하면 선언하지 않은 것을 거부로 바꾼다."""
        return self.cancel_supported is not None

    @property
    def idempotency_known(self) -> bool:
        """멱등성을 **누군가 선언했는가**. 거짓이면 미선언이다."""
        return self.idempotent is not None

    def compatibility_profile(self):
        """Map action requirements into the existing provider placement contract."""
        from mission_runtime.contracts.profile import CompatibilityProfile

        # 선택 조건은 `preferred_hw_tags` 로 간다. 이름이 hw 지만
        # `is_compatible()` 은 required 태그 둘을 같은 node_tags 집합에 대고
        # 보고 preferred 는 자격을 **바꾸지 않고 순위만** 바꾼다 — 선택 조건의
        # 의미가 정확히 그것이다(AI-B-04 "선호 자원이 없으면 일반 자원으로 대체").
        return CompatibilityProfile(
            required_runtime_tags=self.required_resources,
            preferred_hw_tags=self.optional_resources,
        )

    def to_declaration(self) -> CapabilityDeclaration:
        """action 선언을 일반 구성요소 선언(AI-C-18 5계층)으로 **손실 없이** 옮긴다.

        `docs/technology-boundaries.md` §10-2 가 보류 사유로 적어 둔
        "`idempotent`/`cancel_supported` 같은 action 고유 필드가 이 계층 어디에
        속하는지 정하지 않아 손실 없는 변환을 만들 수 없다" 가 이 메서드로
        해소된다 — 그 항목들은 `Capability` 계층(무엇을 할 수 있는가의 성질)에
        속하고, 버전은 `Implementation`, 실측은 `ExecutionProfile`, 지금 되는가는
        `RuntimeInstance` 다. 그래서 이 변환은 **성질만** 옮기고 version·실측
        참조는 옮기지 않는다(옮기면 그 계층의 주인과 겹친다).
        """
        from mission_runtime.contracts.capability_contract import (
            Capability as _GeneralCapability,
        )

        return _GeneralCapability(
            kind=self.name,
            input_schema=self.parameter_schema,
            output_schema=self.result_schema,
            preconditions=self.required_resources,
            optional_preconditions=self.optional_resources,
            cancellable=self.cancel_supported,
            idempotent=self.idempotent,
            invocation=self.invocation,
            basis=self.basis,
            scope_tags=self.scope_tags,
        )


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
