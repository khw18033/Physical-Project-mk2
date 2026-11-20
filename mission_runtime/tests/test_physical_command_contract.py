"""implements: AI-B-03

Verifies the physical command lifecycle contract itself
(mission_runtime.contracts.physical_command) and the reference
CommandExecutionSupervisor: acceptance vs execution vs terminal result
are distinct, retries are idempotent, conflicting payloads are rejected,
expired deadlines never execute, and cancel wins over a late success.
"""

from __future__ import annotations

import time

import pytest

from mission_runtime.contracts.capability_contract import DeclarationBasis
from mission_runtime.contracts.physical_command import (
    CancelCommandRequest,
    Capability,
    Command,
    CommandAcceptance,
    CommandResult,
    ExecutionStatus,
    Rejection,
    RejectionCode,
    payload_fingerprint,
)
from mission_runtime.contracts.profile import ResourceBudget
from mission_runtime.execution.command_execution import CommandExecutionSupervisor


# --- contract dataclasses themselves -----------------------------------


def test_execution_status_has_no_rejected_member():
    # rejection is not a state-machine state (CommandAcceptance.accepted=False instead)
    assert "REJECTED" not in ExecutionStatus.__members__


def test_command_result_rejects_non_terminal_status():
    with pytest.raises(ValueError):
        CommandResult(command_id="cmd-1", status=ExecutionStatus.EXECUTING, completed_at=time.time())


def test_command_acceptance_requires_rejection_iff_not_accepted():
    with pytest.raises(ValueError):
        CommandAcceptance(command_id="cmd-1", accepted=False, accepted_at=time.time())

    with pytest.raises(ValueError):
        CommandAcceptance(
            command_id="cmd-1",
            accepted=True,
            accepted_at=time.time(),
            rejection=Rejection(RejectionCode.INVALID_ARGUMENT, "x"),
        )


def test_payload_fingerprint_ignores_correlation_id_and_deadline():
    base = Command(command_id="c1", target="t", action="a", parameters={"k": 1})
    varied = Command(
        command_id="c1", target="t", action="a", parameters={"k": 1},
        correlation_id="different-trace", deadline=123.0,
    )
    assert payload_fingerprint(base) == payload_fingerprint(varied)


def test_payload_fingerprint_changes_with_parameters():
    a = Command(command_id="c1", target="t", action="a", parameters={"k": 1})
    b = Command(command_id="c1", target="t", action="a", parameters={"k": 2})
    assert payload_fingerprint(a) != payload_fingerprint(b)


def test_capability_declares_required_resources_and_cancel_support():
    cap = Capability(
        name="generic.action",
        version="1.0",
        parameter_schema="schema://params/1.0",
        result_schema="schema://result/1.0",
        cancel_supported=True,
        required_resources=("resource.a",),
    )
    assert cap.cancel_supported is True
    assert "resource.a" in cap.required_resources


# --- CommandExecutionSupervisor -----------------------------------------


def test_accepted_command_runs_to_succeeded_with_result_payload():
    supervisor = CommandExecutionSupervisor(handler=lambda c: (True, {"moved": True}, None))
    command = Command(command_id="cmd-1", target="node-1", action="do", parameters={"x": 1})

    acceptance = supervisor.submit(command)

    assert acceptance.accepted is True
    assert acceptance.rejection is None
    result = supervisor.get_result("cmd-1")
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.result == {"moved": True}


def test_failed_execution_is_reported_as_aborted_with_failure_reason():
    supervisor = CommandExecutionSupervisor(handler=lambda c: (False, None, "sdk timeout"))
    command = Command(command_id="cmd-1", target="node-1", action="do")

    supervisor.submit(command)
    result = supervisor.get_result("cmd-1")

    assert result.status == ExecutionStatus.ABORTED
    assert result.failure.message == "sdk timeout"


def test_same_command_id_and_payload_is_a_retry_not_a_reexecution():
    calls: list[str] = []

    def handler(command: Command):
        calls.append(command.command_id)
        return True, {"n": len(calls)}, None

    supervisor = CommandExecutionSupervisor(handler=handler)
    command = Command(command_id="cmd-1", target="node-1", action="do", parameters={"k": "v"})

    first = supervisor.submit(command)
    second = supervisor.submit(command)

    assert first == second
    assert len(calls) == 1  # no duplicate physical execution on retry


def test_same_command_id_different_payload_is_rejected_as_conflict():
    supervisor = CommandExecutionSupervisor()
    first = supervisor.submit(Command(command_id="cmd-1", target="t", action="a", parameters={"k": "v"}))
    second = supervisor.submit(
        Command(command_id="cmd-1", target="t", action="a", parameters={"k": "different"})
    )

    assert first.accepted is True
    assert second.accepted is False
    assert second.rejection.code == RejectionCode.ALREADY_EXISTS


def test_command_past_its_deadline_is_rejected_and_never_executed():
    calls: list[str] = []
    supervisor = CommandExecutionSupervisor(handler=lambda c: (calls.append(c.command_id), (True, None, None))[1])
    past_deadline = time.time() - 10
    command = Command(command_id="cmd-1", target="t", action="a", deadline=past_deadline)

    acceptance = supervisor.submit(command)

    assert acceptance.accepted is False
    assert acceptance.rejection.code == RejectionCode.FAILED_PRECONDITION
    assert calls == []


def test_cancel_of_unknown_command_id_is_rejected():
    supervisor = CommandExecutionSupervisor()

    response = supervisor.cancel(CancelCommandRequest("never-submitted"))

    assert response.accepted is False
    assert response.reason == "unknown_command_id"


def test_cancel_of_already_terminal_command_is_rejected():
    supervisor = CommandExecutionSupervisor(handler=lambda c: (True, None, None))
    supervisor.submit(Command(command_id="cmd-1", target="t", action="a"))

    response = supervisor.cancel(CancelCommandRequest("cmd-1"))

    assert response.accepted is False
    assert "already_terminal" in response.reason


def test_cancel_during_execution_wins_over_a_late_success():
    """Models the completion-vs-cancel race (internal/docs-dev/obsidian/
    protocol-contract-reference.md §4.2): a cancel request arrives while
    the handler is still in flight. CancelCommandResponse.accepted=True
    must mean only "cancel procedure entered" - the status is CANCELING,
    not yet CANCELED - and the terminal result must end up CANCELED even
    though the handler itself reports success.
    """

    state: dict = {}

    def handler(command: Command):
        response = state["supervisor"].cancel(CancelCommandRequest(command.command_id))
        # right after cancel() returns, execution has not resolved yet
        assert state["supervisor"].get_status(command.command_id) == ExecutionStatus.CANCELING
        state["cancel_response"] = response
        return True, {"would_have_succeeded": True}, None

    supervisor = CommandExecutionSupervisor(handler=handler)
    state["supervisor"] = supervisor

    supervisor.submit(Command(command_id="cmd-1", target="t", action="a"))

    assert state["cancel_response"].accepted is True
    result = supervisor.get_result("cmd-1")
    assert result.status == ExecutionStatus.CANCELED
    assert result.result is None  # the handler's success payload is discarded


# --- AI-C-18 선언 항목: 모른다 ≠ 안 된다 ------------------------------------
# 2026-11-04. `cancel_supported` 는 `bool = False` 였다. 선언하지 않은 장치와
# 취소를 지원하지 않는다고 **선언한** 장치가 같은 값이었다. 지금 와이어는 이
# 항목을 하나도 싣지 못하므로(spec §8-3 P7) 들어오는 모든 선언이 그 거짓에
# 걸려 있었다 — 모든 장치가 "취소를 거부하는 장치" 로 읽혔다.


def test_unstated_cancel_support_is_unknown_and_not_a_refusal():
    silent = Capability(name="hardware.action.stop")
    refuses = Capability(name="hardware.action.stop", cancel_supported=False)
    supports = Capability(name="hardware.action.stop", cancel_supported=True)

    assert silent.cancel_supported is None
    assert silent.cancel_support_known is False
    assert refuses.cancel_supported is False and refuses.cancel_support_known is True
    assert supports.cancel_supported is True and supports.cancel_support_known is True
    # 세 선언이 세 값으로 구분된다 — 둘로 접히면 AI-C-20 의 취소 수락/CANCELED
    # 도달 구분이 전제를 잃는다.
    assert len({silent.cancel_supported, refuses.cancel_supported,
                supports.cancel_supported}) == 3


def test_unstated_idempotency_is_unknown_and_not_non_idempotent():
    """같은 command_id 재전달은 프레임워크가 막지만(`payload_fingerprint`),
    **다른 command_id 로 같은 입력을 다시 보내도 되는가**는 action 의 성질이고
    장치만 답할 수 있다 — "좌표 X 로 가라" 와 "1m 전진" 은 다르다."""
    silent = Capability(name="move_forward")
    not_idempotent = Capability(name="move_forward", idempotent=False)

    assert silent.idempotent is None and silent.idempotency_known is False
    assert not_idempotent.idempotent is False and not_idempotent.idempotency_known is True


def test_fully_declared_now_means_every_ai_c_18_item():
    """version·schema 셋만 채운 선언은 더 이상 "다 선언됐다" 가 아니다."""
    partial = Capability(name="move", version="1",
                         parameter_schema="p", result_schema="r")
    assert partial.is_fully_declared() is False
    assert set(partial.undeclared_items()) == {
        "basis", "execution_conditions", "cancellable", "idempotent",
        "invocation", "scope", "performance"}

    full = Capability(
        name="move", version="1", parameter_schema="p", result_schema="r",
        required_resources=("robot.base",), cancel_supported=True, idempotent=True,
        invocation="synchronous", basis=DeclarationBasis(reference_frame="device-local"),
        scope_tags=("zone.a",), execution_profile_ref="profile://move/1",
    )
    assert full.undeclared_items() == () and full.is_fully_declared() is True


def test_an_unstated_item_is_never_reported_as_declared():
    """빈 묶음은 "조건 없음" 이 아니라 "적지 않음" 이다 — 보수적으로 틀리는
    쪽은 없는 선언을 지어내지 않는 쪽이다."""
    assert "execution_conditions" in Capability(name="stop").undeclared_items()
    assert "execution_conditions" not in Capability(
        name="stop", optional_resources=("accel.npu",)).undeclared_items()


def test_optional_resources_rank_but_never_exclude():
    """선택 실행 조건의 결손은 자격을 바꾸지 않고 순위만 바꾼다(AI-B-04/AI-C-05)."""
    cap = Capability(name="detect", required_resources=("sensor.camera",),
                     optional_resources=("accel.npu",))
    profile = cap.compatibility_profile()
    assert profile.required_runtime_tags == ("sensor.camera",)
    assert profile.unmet_preferences({"sensor.camera"}) == ("accel.npu",)
    assert profile.is_compatible({"sensor.camera"}, ResourceBudget(10.0, 1024)) is True


def test_to_declaration_carries_every_behavioural_item_without_loss():
    """`docs/technology-boundaries.md` §10-2 가 보류 사유로 적어 둔 "손실 없는
    변환을 만들 수 없다" 가 이것으로 해소된다. 성질은 Capability 계층으로 가고
    버전·실측 참조는 가지 않는다 — 그 계층의 주인(Implementation /
    ExecutionProfile)과 겹치면 같은 사실에 주인이 둘이 된다."""
    cap = Capability(
        name="navigate.relative", version="2", parameter_schema="p", result_schema="r",
        cancel_supported=False, required_resources=("mobility.base",),
        optional_resources=("accel.npu",), idempotent=True, invocation="asynchronous",
        basis=DeclarationBasis(units={"distance_m": "m"}, reference_frame="device-local",
                               time_basis="backend_ntp"),
        scope_tags=("zone.a",), execution_profile_ref="profile://nav/1",
    )
    general = cap.to_declaration()

    assert general.kind == "navigate.relative"
    assert general.input_schema == "p" and general.output_schema == "r"
    assert general.cancellable is False          # 미선언으로 퇴화하지 않는다
    assert general.idempotent is True
    assert general.invocation == "asynchronous"
    assert general.basis == cap.basis
    assert general.scope_tags == ("zone.a",)
    assert general.preconditions == ("mobility.base",)
    assert general.optional_preconditions == ("accel.npu",)
    assert general.undeclared_items() == ()


def test_a_silent_declaration_stays_silent_through_the_conversion():
    general = Capability(name="stop").to_declaration()
    assert general.cancellable is None and general.idempotent is None
    assert general.scope_tags is None and general.basis is None
