"""implements: AI-B-03

Verifies the physical command lifecycle contract itself
(perception_framework.contracts.physical_command) and the reference
CommandExecutionSupervisor: acceptance vs execution vs terminal result
are distinct, retries are idempotent, conflicting payloads are rejected,
expired deadlines never execute, and cancel wins over a late success.
"""

from __future__ import annotations

import time

import pytest

from perception_framework.contracts.physical_command import (
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
from perception_framework.execution.command_execution import CommandExecutionSupervisor


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
    """Models the completion-vs-cancel race (docs/obsidian/
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
