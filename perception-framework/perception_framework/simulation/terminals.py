"""Virtual terminals (말단) driven entirely by replay data.

implements: AI-B-10, AI-C-06, AI-C-14, AI-B-03, AI-O-04

A virtual terminal keeps exactly what the requirement allows a 말단 to
have: a task transport client, an observability client and (optionally) a
media sender. No broker, collector or orchestrator is instantiated here
(원칙 #12, AI-B-10).

Commands are not "done when delivered": the terminal returns RECEIVED and
then a final SUCCESS/REJECTED/FAILED business result with a reason, which
is what AI-B-03/원칙 #16 require. Transport-level timing stays out of that
result and belongs to the trace path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from perception_framework.common.data_plane import DataKind, DataPlane, assert_routable
from perception_framework.common.timing import FrameReferenceFactory
from perception_framework.providers.serialization import SerializationPolicy


class CommandOutcome(str, Enum):
    RECEIVED = "RECEIVED"
    SUCCESS = "SUCCESS"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CommandResult:
    """Business result of one command — never mixed with transport timing."""

    command_id: str
    command: str
    outcome: CommandOutcome
    reason: str | None = None


@dataclass
class TerminalState:
    """Whatever this terminal reports about itself. Free-form on purpose:
    a robot reports battery/position, a river station reports level —
    the framework does not enumerate device kinds (원칙 #1)."""

    values: dict = field(default_factory=dict)

    def get(self, key: str, default=None):
        return self.values.get(key, default)


Precondition = Callable[[TerminalState, dict], str | None]
"""Returns a rejection reason, or None when the command may run."""


class VirtualTerminal:
    """A device simulator speaking only through injected providers."""

    def __init__(
        self,
        terminal_id: str,
        transport,
        *,
        observability=None,
        media_source=None,
        state: TerminalState | None = None,
        preconditions: dict[str, Precondition] | None = None,
        topic_prefix: str = "terminal",
        serializer=None,
    ) -> None:
        self.terminal_id = terminal_id
        self._transport = transport
        self._observability = observability
        self._media = media_source
        self.state = state or TerminalState()
        self._preconditions = dict(preconditions or {})
        self._prefix = topic_prefix
        # AI-C-07: the terminal produces message *meaning*; the wire format
        # is chosen by deployment policy for the 말단<->엣지 boundary, not
        # hardcoded here. Any SerializerProvider may be injected instead.
        self._serializer = serializer or SerializationPolicy.default().serializer_for(
            "terminal_to_edge"
        )
        self._frames = FrameReferenceFactory(terminal_id)
        self.command_log: list[CommandResult] = []
        self.sent_media_frames = 0
        self.online = True

    # --- topics ------------------------------------------------------------
    @property
    def task_topic(self) -> str:
        return f"{self._prefix}/{self.terminal_id}/task"

    @property
    def command_topic(self) -> str:
        return f"{self._prefix}/{self.terminal_id}/command"

    @property
    def result_topic(self) -> str:
        return f"{self._prefix}/{self.terminal_id}/result"

    @property
    def heartbeat_topic(self) -> str:
        return f"{self._prefix}/{self.terminal_id}/heartbeat"

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._transport.subscribe(self.command_topic, self._on_command)

    def go_offline(self) -> None:
        """Simulate a network partition or device death. The terminal stops
        answering, exactly as a lost MQTT session would look (AI-O-04)."""
        self.online = False

    def go_online(self) -> None:
        self.online = True

    # --- task plane --------------------------------------------------------
    def publish_observation(self, name: str, value, *, kind: DataKind = DataKind.PERCEPTION_RESULT) -> None:
        assert_routable(kind, DataPlane.TASK)
        reference = self._frames.next_reference(f"{name}-{int(time.time()*1000)}")
        payload = self._serializer.encode(
            {
                "terminal_id": self.terminal_id,
                "name": name,
                "value": value,
                "frame_id": reference.frame_id,
                "observed_at": reference.observed_at,
                "local_sequence": reference.local_sequence,
            }
        )
        self._transport.publish(self.task_topic, payload, qos="at_most_once")

    def publish_heartbeat(self) -> None:
        if not self.online:
            return
        self._transport.publish(self.heartbeat_topic, b"alive", qos="at_most_once")

    # --- observability plane ----------------------------------------------
    def report_metric(self, name: str, value: float) -> None:
        if self._observability is None:
            return
        self._observability.record_metric(name, value, {"terminal_id": self.terminal_id})

    def report_event(self, name: str, severity: str, payload: dict | None = None) -> None:
        if self._observability is None:
            return
        self._observability.record_event(name, severity, {"terminal_id": self.terminal_id, **(payload or {})})

    # --- media plane -------------------------------------------------------
    def send_media_frame(self) -> bool:
        """Pixels go out through the media provider only — never through the
        task transport (금지 사항, AI-C-14)."""
        if self._media is None or not self._media.is_available():
            return False
        frame = self._media.read_frame()
        if frame is None:
            return False
        self.sent_media_frames += 1
        return True

    # --- control plane -----------------------------------------------------
    def _on_command(self, payload: bytes) -> None:
        if not self.online:
            return  # partitioned terminals simply never answer
        try:
            message = self._serializer.decode(payload)
        except Exception:
            self._reply(CommandResult("unknown", "unknown", CommandOutcome.FAILED, "undecodable_command"))
            return

        command = message.get("command", "")
        command_id = message.get("command_id", "unknown")
        params = message.get("params", {}) or {}

        self._reply(CommandResult(command_id, command, CommandOutcome.RECEIVED))

        precondition = self._preconditions.get(command)
        if precondition is not None:
            reason = precondition(self.state, params)
            if reason:
                # 전달은 성공했지만 실행은 거부 — 둘은 다른 사건이다 (AI-B-03).
                self._reply(CommandResult(command_id, command, CommandOutcome.REJECTED, reason))
                return

        try:
            self._execute(command, params)
        except Exception as exc:
            self._reply(CommandResult(command_id, command, CommandOutcome.FAILED, type(exc).__name__))
            return

        self._reply(CommandResult(command_id, command, CommandOutcome.SUCCESS))

    def _execute(self, command: str, params: dict) -> None:
        """Actuator simulator. Subclasses override; default records intent."""
        self.state.values.setdefault("executed_commands", []).append(command)

    def _reply(self, result: CommandResult) -> None:
        self.command_log.append(result)
        payload = self._serializer.encode(
            {
                "terminal_id": self.terminal_id,
                "command_id": result.command_id,
                "command": result.command,
                "outcome": result.outcome.value,
                "reason": result.reason,
            }
        )
        self._transport.publish(self.result_topic, payload, qos="at_least_once")


def battery_precondition(minimum_pct: float) -> Precondition:
    """Example precondition: refuse to move on a nearly empty battery.

    Lives here, not in core code — a device's physical limits are the
    device adapter's business (AI-C-04).
    """

    def check(state: TerminalState, params: dict) -> str | None:
        level = state.get("battery_pct")
        if level is None:
            return "battery_level_unknown"
        if level < minimum_pct:
            return "insufficient_battery"
        return None

    return check


class VirtualRobotTerminal(VirtualTerminal):
    """Mobile terminal: camera replay + scripted position + battery."""

    def __init__(self, terminal_id: str, transport, *, battery_pct: float = 80.0, **kwargs) -> None:
        state = kwargs.pop("state", None) or TerminalState({"battery_pct": battery_pct, "position": (0.0, 0.0)})
        preconditions = kwargs.pop("preconditions", None) or {"START_TASK": battery_precondition(10.0)}
        super().__init__(terminal_id, transport, state=state, preconditions=preconditions, **kwargs)

    def _execute(self, command: str, params: dict) -> None:
        super()._execute(command, params)
        if command == "START_TASK":
            self.state.values["position"] = tuple(params.get("target", (1.0, 1.0)))


class VirtualRiverTerminal(VirtualTerminal):
    """Fixed terminal: water level / rainfall replay + flood-wall actuator."""

    def __init__(self, terminal_id: str, transport, *, sources: dict | None = None, **kwargs) -> None:
        state = kwargs.pop("state", None) or TerminalState({"flood_wall": "OPEN"})
        super().__init__(terminal_id, transport, state=state, **kwargs)
        self._sources = dict(sources or {})

    def pump_once(self) -> dict:
        """Publish one reading from every attached replay source."""
        emitted = {}
        for name, source in self._sources.items():
            reading = source.read()
            if reading is None:
                continue
            self.publish_observation(name, reading.value)
            emitted[name] = reading.value
        return emitted

    def _execute(self, command: str, params: dict) -> None:
        super()._execute(command, params)
        if command == "CLOSE_FLOOD_WALL":
            self.state.values["flood_wall"] = "CLOSED"
