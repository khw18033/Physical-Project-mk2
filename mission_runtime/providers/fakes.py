"""Reference (fake) provider implementations satisfying the Protocols in
`adapters.py`. These exist so upper-layer logic can be built and tested
against the common interfaces before any real MQTT/Kafka/RTSP/GPU
backend is wired in. Swapping one of these for a real implementation
must never require touching the caller.

implements: AI-C-04, AI-C-06, AI-C-07, AI-C-08, AI-C-09, AI-C-12, AI-B-08, AI-C-20
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable


class InMemoryTransportProvider:
    """Delivers messages within the same process via direct handler
    invocation. Stands in for MQTT/Kafka in tests (AI-C-06) — same
    publish/subscribe contract, no broker required.
    """

    def __init__(self, *, connected: bool = True) -> None:
        self._connected = connected
        self._subscribers: dict[str, list[Callable[[bytes], None]]] = {}
        self.published: list[tuple[str, bytes, str]] = []

    def publish(self, topic: str, payload: bytes, *, qos: str = "at_least_once") -> None:
        self.published.append((topic, payload, qos))
        if not self._connected:
            return
        for handler in self._subscribers.get(topic, []):
            handler(payload)

    def subscribe(self, topic: str, handler: Callable[[bytes], None]) -> None:
        self._subscribers.setdefault(topic, []).append(handler)

    def is_connected(self) -> bool:
        return self._connected

    def set_connected(self, value: bool) -> None:
        """Test hook: simulate connectivity loss without touching callers."""
        self._connected = value


class JsonSerializerProvider:
    """SerializerProvider backed by JSON, standing in for Protobuf/other
    wire formats behind the same contract (AI-C-07).
    """

    def encode(self, obj: Any) -> bytes:
        return json.dumps(obj, default=str).encode("utf-8")

    def decode(self, payload: bytes, schema_hint: str | None = None) -> Any:
        return json.loads(payload.decode("utf-8"))


class SyntheticMediaSourceProvider:
    """Hands out pre-baked synthetic frames instead of reading from a
    real camera/RTSP stream (AI-C-08).
    """

    def __init__(self, source_id: str, frames: list[Any] | None = None) -> None:
        self._source_id = source_id
        self._frames = list(frames or [])
        self._index = 0
        self._available = True

    def read_frame(self) -> Any | None:
        if not self._available or self._index >= len(self._frames):
            return None
        frame = self._frames[self._index]
        self._index += 1
        return frame

    def is_available(self) -> bool:
        return self._available

    def source_id(self) -> str:
        return self._source_id

    def set_available(self, value: bool) -> None:
        """Test hook: simulate the video source disappearing entirely."""
        self._available = value


class StubAIRuntimeProvider:
    """Returns a canned/callable result instead of running a real model —
    used to prove upper logic never depends on whether inference is
    local or remote (AI-B-08, AI-C-09).
    """

    def __init__(
        self,
        capability_kinds: tuple[str, ...],
        infer_fn: Callable[[str, Any], Any] | None = None,
        *,
        available: bool = True,
    ) -> None:
        self._capability_kinds = set(capability_kinds)
        self._infer_fn = infer_fn or (lambda kind, inputs: {"kind": kind, "echo": inputs})
        self._available = available

    def infer(self, capability_kind: str, inputs: Any) -> Any:
        if capability_kind not in self._capability_kinds:
            raise ValueError(f"unsupported capability_kind: {capability_kind}")
        return self._infer_fn(capability_kind, inputs)

    def is_available(self) -> bool:
        return self._available

    def set_available(self, value: bool) -> None:
        self._available = value


class InMemoryModelDeploymentProvider:
    """Deterministic model installer fake used by the lifecycle coordinator."""

    def __init__(
        self,
        *,
        versions: dict[tuple[str, str], str] | None = None,
        fail_at: str | None = None,
    ) -> None:
        self._versions = dict(versions or {})
        self._fail_at = fail_at
        self.calls: list[tuple] = []

    def current_version(self, model_id: str, target_node_id: str) -> str | None:
        self.calls.append(("current_version", model_id, target_node_id))
        return self._versions.get((model_id, target_node_id))

    def download(self, artifact_ref: str, target_node_id: str) -> bool:
        self.calls.append(("download", artifact_ref, target_node_id))
        return self._fail_at != "download"

    def validate(self, artifact_ref: str, checksum: str, target_node_id: str) -> bool:
        self.calls.append(("validate", artifact_ref, checksum, target_node_id))
        return self._fail_at != "validate"

    def activate(
        self,
        model_id: str,
        model_version: str,
        artifact_ref: str,
        target_node_id: str,
    ) -> bool:
        self.calls.append(("activate", model_id, model_version, artifact_ref, target_node_id))
        if self._fail_at == "activate":
            return False
        self._versions[(model_id, target_node_id)] = model_version
        return True

    def rollback(self, model_id: str, model_version: str, target_node_id: str) -> bool:
        self.calls.append(("rollback", model_id, model_version, target_node_id))
        if self._fail_at == "rollback":
            return False
        self._versions[(model_id, target_node_id)] = model_version
        return True


@dataclass
class RecordedEvent:
    name: str
    severity: str
    payload: dict | None
    at: float


class InMemoryObservabilityProvider:
    """Keeps metrics/events in memory (AI-O-01, AI-O-02).

    Critical events are stored in the same list as everything else but
    are queryable separately (`critical_events`) so a device-death or
    fatal-error event can never be lost inside a metric-summary window
    (구현 시 금지 사항: 일반 metric 요약에 치명 오류를 섞지 않는다).
    """

    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict | None]] = []
        self.events: list[RecordedEvent] = []
        self._raise_on_metric = False

    def record_metric(self, name: str, value: float, tags: dict | None = None) -> None:
        if self._raise_on_metric:
            raise RuntimeError("metric sink unavailable")
        self.metrics.append((name, value, tags))

    def record_event(self, name: str, severity: str, payload: dict | None = None) -> None:
        self.events.append(RecordedEvent(name, severity, payload, time.time()))

    def critical_events(self) -> list[RecordedEvent]:
        return [e for e in self.events if e.severity in ("critical", "fatal")]

    def simulate_collector_down(self, value: bool = True) -> None:
        """Test hook: metric path fails, but record_event (local
        structured event) must remain unaffected (AI-O-02)."""
        self._raise_on_metric = value


class FakeRobotBackend:
    """Records what a robot *would* have been told to do (`RobotControlBackend`).

    Exists so the whole terminal-side command path — acceptance, idempotency,
    cancel, emergency stop, mission resume — is runnable and testable with no
    robot, no SDK and no network present. Every physical effect becomes a row
    in `executed`, so a test asserts on "the robot was told exactly once",
    which is the actual AI-C-20 §5-1 requirement, rather than on a log line.

    `gate` makes execution blocking on demand: set it to a cleared
    `threading.Event` and `execute` waits, which is what lets a test create a
    real cancel-vs-completion race instead of simulating one.
    """

    def __init__(
        self,
        actions=("move", "stop"),
        *,
        ready: bool = True,
        not_ready_reason: str | None = None,
        failing_actions: tuple[str, ...] = (),
        raising_actions: tuple[str, ...] = (),
        stop_supported: bool = True,
        emergency_stop_reachable: bool = True,
        gate: Any | None = None,
        fully_declared: bool = False,
    ) -> None:
        from mission_runtime.contracts.physical_command import Capability

        self._capabilities = tuple(
            action if isinstance(action, Capability) else Capability(
                name=action,
                version="1" if fully_declared else None,
                parameter_schema=f"{action}.params" if fully_declared else None,
                result_schema=f"{action}.result" if fully_declared else None,
                cancel_supported=stop_supported,
            )
            for action in actions
        )
        self.ready = ready
        self.not_ready_reason = not_ready_reason
        self.failing_actions = frozenset(failing_actions)
        self.raising_actions = frozenset(raising_actions)
        self.stop_supported = stop_supported
        self.emergency_stop_reachable = emergency_stop_reachable
        self.gate = gate
        #: (action, parameters, command_id) — one row per *physical* execution.
        self.executed: list[tuple[str, dict, str]] = []
        self.stop_requests: list[str] = []
        self.emergency_stops: list[str] = []
        self.validated: list[tuple[str, dict]] = []

    # -- RobotControlBackend ------------------------------------------------

    def declared_actions(self) -> tuple[Any, ...]:
        return self._capabilities

    def readiness(self) -> tuple[bool, str | None]:
        return self.ready, None if self.ready else (self.not_ready_reason or "not ready")

    def execute(self, action: str, parameters: dict, *, command_id: str):
        self.executed.append((action, dict(parameters), command_id))
        if self.gate is not None:
            self.gate.wait(5.0)
        if action in self.raising_actions:
            raise RuntimeError(f"backend blew up on {action}")
        if action in self.failing_actions:
            return False, None, f"{action}_failed"
        return True, {"action": action}, None

    def request_stop(self, command_id: str) -> bool:
        self.stop_requests.append(command_id)
        return self.stop_supported

    def emergency_stop(self, reason: str) -> bool:
        self.emergency_stops.append(reason)
        return self.emergency_stop_reachable

    # -- optional hook (not part of the Protocol) ---------------------------

    def count_of(self, command_id: str) -> int:
        """How many times a *physical* execution ran for this command_id."""
        return sum(1 for _action, _params, cid in self.executed if cid == command_id)
