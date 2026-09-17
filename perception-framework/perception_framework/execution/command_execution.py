"""Idempotent command execution supervisor built on the physical command
lifecycle contract (AI-B-03).

implements: AI-B-03, AI-C-06 (계약만; 실제 전송·오케스트레이터 기술은
어댑터가 감춘다 — 이 모듈은 MQTT/Kafka/K3s를 import하지 않는다)
tests: tests/test_physical_command_contract.py

This is a reference/local supervisor - the in-process default until a
provider that fronts a real robot/hardware adapter is wired in behind
the same `submit`/`cancel`/`get_status`/`get_result` shape, analogous to
how `LocalControlSupervisor` in `execution/control.py` stands in for a
real orchestrator. It does not decide *what* command_id issuance policy
the backend uses; it only implements the lifecycle contract once a
Command arrives (docs/ai/design/external-technology-decisions.md §10 notes
that the issuance-authority question still needs backend agreement).
"""

from __future__ import annotations

import time
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from perception_framework.contracts.physical_command import (
    CancelCommandRequest,
    CancelCommandResponse,
    Command,
    CommandAcceptance,
    CommandResult,
    ExecutionStatus,
    Failure,
    Rejection,
    RejectionCode,
    TERMINAL_STATUSES,
    payload_fingerprint,
)

# Returns (succeeded, result_payload, failure_message). Called synchronously
# by this reference supervisor while status is EXECUTING; a handler that
# wants to react to a concurrent cancel request can call the supervisor's
# `cancel()` itself or check `get_status()` mid-flight - the supervisor
# always lets CANCELING win over a late success once the handler returns.
ActionHandler = Callable[[Command], tuple[bool, dict | None, str | None]]


def _default_handler(_command: Command) -> tuple[bool, dict | None, str | None]:
    return True, None, None


@dataclass
class _Record:
    fingerprint: str
    acceptance: CommandAcceptance
    status: ExecutionStatus
    result: CommandResult | None = None


class CommandExecutionSupervisor:
    """Reference implementation of Command -> CommandAcceptance ->
    ExecutionStatus -> CommandResult, with CancelCommandRequest/Response
    (docs/ai/design/external-technology-decisions.md §3)."""

    def __init__(self, handler: ActionHandler | None = None, *, cancel_handler=None,
                 state_path: str | Path | None = None) -> None:
        self._records: dict[str, _Record] = {}
        self._handler = handler or _default_handler
        self._cancel_handler = cancel_handler
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._db = sqlite3.connect(str(state_path), check_same_thread=False) if state_path else None
        if self._db is not None:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS command_state "
                "(command_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, acceptance TEXT NOT NULL, "
                "status TEXT NOT NULL, result TEXT)"
            )
            self._load()

    def submit(self, command: Command, *, now: float | None = None) -> CommandAcceptance:
        acceptance, should_run = self._accept(command, now=now)
        if should_run:
            self._run(command)
        return acceptance

    def submit_async(self, command: Command, *, now: float | None = None) -> CommandAcceptance:
        """Accept immediately and execute on a worker; enables real concurrent cancel."""
        acceptance, should_run = self._accept(command, now=now)
        if should_run:
            thread = threading.Thread(target=self._run, args=(command,), daemon=True)
            self._threads[command.command_id] = thread
            thread.start()
        return acceptance

    def _accept(self, command: Command, *, now: float | None) -> tuple[CommandAcceptance, bool]:
        now = now if now is not None else time.time()
        fingerprint = payload_fingerprint(command)
        with self._lock:
            existing = self._records.get(command.command_id)
            if existing is not None:
                if existing.fingerprint == fingerprint:
                    return existing.acceptance, False
                rejection = Rejection(RejectionCode.ALREADY_EXISTS,
                    f"command_id {command.command_id!r} already used with a different payload")
                return CommandAcceptance(command.command_id, False, now, rejection), False
            if command.deadline is not None and now > command.deadline:
                rejection = Rejection(RejectionCode.FAILED_PRECONDITION, "deadline already passed")
                return CommandAcceptance(command.command_id, False, now, rejection), False
            acceptance = CommandAcceptance(command.command_id, True, now)
            self._records[command.command_id] = _Record(fingerprint, acceptance, ExecutionStatus.ACCEPTED)
            self._persist(command.command_id)
            return acceptance, True

    def _run(self, command: Command) -> None:
        with self._lock:
            record = self._records[command.command_id]
            record.status = ExecutionStatus.EXECUTING
            self._persist(command.command_id)
        succeeded, payload, failure_message = self._handler(command)
        completed_at = time.time()
        with self._lock:
            if record.status == ExecutionStatus.CANCELING:
                record.status = ExecutionStatus.CANCELED
                record.result = CommandResult(command.command_id, ExecutionStatus.CANCELED, completed_at)
            elif succeeded:
                record.status = ExecutionStatus.SUCCEEDED
                record.result = CommandResult(
                    command.command_id, ExecutionStatus.SUCCEEDED, completed_at, result=payload
                )
            else:
                record.status = ExecutionStatus.ABORTED
                record.result = CommandResult(
                    command.command_id,
                    ExecutionStatus.ABORTED,
                    completed_at,
                    failure=Failure("EXECUTION_FAILED", failure_message or "unspecified failure"),
                )
            self._persist(command.command_id)

    def cancel(self, request: CancelCommandRequest, *, now: float | None = None) -> CancelCommandResponse:
        now = now if now is not None else time.time()
        with self._lock:
            record = self._records.get(request.command_id)
            if record is None:
                return CancelCommandResponse(request.command_id, False, reason="unknown_command_id")
            if record.status in TERMINAL_STATUSES:
                return CancelCommandResponse(request.command_id, False, reason=f"already_terminal:{record.status.value}")
            if self._cancel_handler is not None and not self._cancel_handler(request.command_id):
                return CancelCommandResponse(request.command_id, False, reason="adapter_cancel_rejected")
            record.status = ExecutionStatus.CANCELING
            self._persist(request.command_id)
            return CancelCommandResponse(request.command_id, True)

    def get_status(self, command_id: str) -> ExecutionStatus | None:
        record = self._records.get(command_id)
        return record.status if record else None

    def get_result(self, command_id: str) -> CommandResult | None:
        record = self._records.get(command_id)
        return record.result if record else None

    def wait(self, command_id: str, timeout: float | None = None) -> CommandResult | None:
        thread = self._threads.get(command_id)
        if thread is not None:
            thread.join(timeout)
        return self.get_result(command_id)

    def close(self) -> None:
        for thread in tuple(self._threads.values()):
            thread.join()
        if self._db is not None:
            self._db.close()

    def _persist(self, command_id: str) -> None:
        if self._db is None:
            return
        record = self._records[command_id]
        acceptance = {"command_id": record.acceptance.command_id, "accepted": record.acceptance.accepted,
                      "accepted_at": record.acceptance.accepted_at}
        result = None
        if record.result is not None:
            result = {"command_id": record.result.command_id, "status": record.result.status.value,
                      "completed_at": record.result.completed_at, "result": record.result.result,
                      "failure": ({"code": record.result.failure.code, "message": record.result.failure.message}
                                  if record.result.failure else None)}
        self._db.execute("INSERT OR REPLACE INTO command_state VALUES (?, ?, ?, ?, ?)",
            (command_id, record.fingerprint, json.dumps(acceptance), record.status.value,
             json.dumps(result) if result else None))
        self._db.commit()

    def _load(self) -> None:
        for command_id, fingerprint, acceptance_raw, status_raw, result_raw in self._db.execute(
            "SELECT command_id, fingerprint, acceptance, status, result FROM command_state"
        ):
            value = json.loads(acceptance_raw)
            acceptance = CommandAcceptance(**value)
            result = None
            if result_raw:
                item = json.loads(result_raw)
                failure = Failure(**item["failure"]) if item.get("failure") else None
                result = CommandResult(item["command_id"], ExecutionStatus(item["status"]),
                                       item["completed_at"], item.get("result"), failure)
            status = ExecutionStatus(status_raw)
            # An in-process worker cannot survive a process restart. Preserve
            # deduplication but close the orphaned lifecycle explicitly rather
            # than reporting EXECUTING forever or executing it a second time.
            if status not in TERMINAL_STATUSES:
                status = ExecutionStatus.ABORTED
                result = CommandResult(
                    command_id,
                    status,
                    time.time(),
                    failure=Failure(
                        "RECOVERED_AFTER_RESTART",
                        "execution ownership was lost during process restart",
                    ),
                )
            self._records[command_id] = _Record(fingerprint, acceptance, status, result)
        for command_id in self._records:
            self._persist(command_id)
