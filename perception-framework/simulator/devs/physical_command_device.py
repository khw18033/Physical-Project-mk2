"""DEVS atomic model simulating the DEVICE side of `terminal/<device-id>/
{downlink,uplink}` — the counterpart `execution/physical_command_gateway.py`
talks to on the other side of the MQTT boundary (`interface-spec/spec/
physical-command-interface.md`).

implements: AI-C-20
tests: simulator scenarios under simulator/scenarios/physical-command-*.json

This is the first physical-command scenario coverage with a *real*
simulated time axis: `execution/physical_command_gateway.py`'s own tests
(`tests/test_physical_command_gateway.py`) use an in-memory transport that
answers instantly, so they cannot represent "the device is still deciding
when the command's deadline expires" or "cancel arrives while genuinely
mid-execution, not simultaneously with completion" - those need a device
that actually takes simulated time to act, which is what this model is for.

Deadline expiry itself is scenario-declared (`command["already_expired"]`)
rather than compared against a live clock inside this model: reading "now"
reliably inside a DEVS transition method is not straightforward (see
`simulator/devs/README.md`), and the scenario author already controls the
stimulus timeline, so deciding "this command's deadline has already
passed" ahead of time is not a loss of fidelity.
"""

from __future__ import annotations

from pyjevsim.behavior_model import BehaviorModel
from pyjevsim.definition import Infinite
from pyjevsim.system_message import SysMessage

_DEFAULT_STOP_DELAY = 0.2


class PhysicalCommandDeviceNode(BehaviorModel):
    def __init__(self, name: str, *, capabilities: list[dict], accept_delay: float = 0.1,
                 exec_time: float = 1.0, stop_delay: float = _DEFAULT_STOP_DELAY) -> None:
        super().__init__(name)
        self.insert_input_port("downlink")
        self.insert_output_port("uplink")
        self.init_state("IDLE")
        self.insert_state("IDLE", Infinite)

        self._capabilities = {c["name"] for c in capabilities}
        self._accept_delay = accept_delay
        self._exec_time = exec_time
        self._stop_delay = stop_delay

        self._active_command: dict | None = None
        self._next_output: tuple[str, dict] | None = None
        # Responses that must go out but must not disturb whatever the main
        # state machine is already timing (e.g. a cancel for a command_id
        # that is not the one currently executing) - flushed opportunistically
        # alongside the next output() call rather than forcing one.
        self._extra_outputs: list[dict] = []

        self.trace: list[dict] = []

    def _goto(self, name: str, deadline: float) -> None:
        """`BehaviorModel.update_state()` only edits the deadline *table* -
        it does not move `_cur_state` (confirmed against pyjevsim's own
        examples/banksim, which always sets `_cur_state` directly). This
        wrapper does both, since every call site here means "transition
        now", never "adjust a state's deadline while not in it"."""
        self._cur_state = name
        self.update_state(name, deadline)

    # -- DEVS transitions ---------------------------------------------------

    def ext_trans(self, port, msg) -> None:
        for item in msg.retrieve():
            self.trace.append({"direction": "in", "port": port, "payload": item})
            message_type = item.get("message_type")
            if message_type == "command":
                self._on_command(item["payload"])
            elif message_type == "cancel_request":
                self._on_cancel(item["payload"])

    def output(self, md) -> None:
        envelope = None
        if self._cur_state == "EMIT" and self._next_output is not None:
            message_type, payload = self._next_output
            envelope = {"message_type": message_type, "payload": payload}
        elif self._cur_state == "EXECUTING":
            payload = {"command_id": self._active_command["command_id"], "status": "SUCCEEDED"}
            envelope = {"message_type": "result", "payload": payload}
            self._next_output = ("result", payload)
        elif self._cur_state == "STOPPING":
            payload = {"command_id": self._active_command["command_id"], "status": "CANCELED"}
            envelope = {"message_type": "result", "payload": payload}
            self._next_output = ("result", payload)

        for pending in [envelope, *self._extra_outputs]:
            if pending is None:
                continue
            msg = SysMessage(self.get_name(), "uplink")
            msg.insert(pending)
            md.insert_message(msg)
            self.trace.append({"direction": "out", "port": "uplink", "payload": pending})
        self._extra_outputs = []

    def int_trans(self) -> None:
        if self._cur_state == "EMIT":
            if self._next_output is None:
                # Nothing but a defensive extra_output was flushed (e.g. an
                # unmatched cancel while otherwise idle) - no state to advance.
                self._goto("IDLE", Infinite)
            else:
                message_type, payload = self._next_output
                if message_type == "acceptance" and payload["accepted"]:
                    self._goto("EXECUTING", self._exec_time)
                elif message_type == "cancel_response" and payload["accepted"]:
                    self._goto("STOPPING", self._stop_delay)
                else:
                    self._goto("IDLE", Infinite)
        elif self._cur_state in ("EXECUTING", "STOPPING"):
            self._active_command = None
            self._goto("IDLE", Infinite)
        self._next_output = None

    # -- command handling -----------------------------------------------

    def _on_command(self, command: dict) -> None:
        action = command["action"]
        if action not in self._capabilities:
            self._next_output = ("acceptance", {
                "command_id": command["command_id"], "accepted": False,
                "rejection": {"code": "UNIMPLEMENTED", "message": f"unsupported_action:{action}"},
            })
            self._goto("EMIT", 0)
            return
        if command.get("already_expired"):
            self._next_output = ("acceptance", {
                "command_id": command["command_id"], "accepted": False,
                "rejection": {"code": "FAILED_PRECONDITION", "message": "deadline already passed"},
            })
            self._goto("EMIT", 0)
            return
        if self._active_command is not None and self._active_command["command_id"] == command["command_id"]:
            # Idempotent retransmit while already in flight: re-affirm
            # acceptance, do not restart execution (AI-C-20 §5-1).
            self._extra_outputs.append({
                "message_type": "acceptance",
                "payload": {"command_id": command["command_id"], "accepted": True},
            })
            return
        self._active_command = command
        self._next_output = ("acceptance", {"command_id": command["command_id"], "accepted": True})
        self._goto("EMIT", 0)

    def _on_cancel(self, request: dict) -> None:
        matches = self._active_command is not None and self._active_command["command_id"] == request["command_id"]
        executing_now = matches and self._cur_state == "EXECUTING"
        if executing_now:
            self._next_output = ("cancel_response", {"command_id": request["command_id"], "accepted": True})
            self._goto("EMIT", 0)
        else:
            reason = "already_terminal" if matches else "unknown_command_id"
            self._extra_outputs.append({
                "message_type": "cancel_response",
                "payload": {"command_id": request["command_id"], "accepted": False, "reason": reason},
            })
            if self._cur_state == "IDLE":
                # Nothing else is going to make this model imminent on its
                # own - force a flush instead of leaving the response queued
                # forever. Does not disturb EXECUTING/STOPPING's own timer
                # when one of those is already in progress for a different
                # command_id.
                self._next_output = None
                self._goto("EMIT", 0)
