"""Edge-side half of the physical command wire contract.

implements: AI-C-20, AI-C-06, AI-C-10, AI-C-11
tests: tests/test_physical_command_gateway.py

This is the code that actually speaks `interface-spec/spec/
physical-command-interface.md`: it publishes `Command`/
`CancelCommandRequest` to `terminal/<device-id>/downlink` and turns bytes
arriving on `terminal/<device-id>/uplink` back into the typed contract
objects from `contracts/physical_command.py`. What a device does with a
downlink message, or how it produces an uplink one, is entirely the
device side's own business and out of scope here — only our half exists
in this repo (절대 준수 원칙 #3, AI-C-19).

Two things this module adds on top of the existing contract that did not
exist before:

1. An async-capable command tracker. `CommandExecutionSupervisor`
   (execution/command_execution.py) assumes its `ActionHandler` runs
   synchronously in this same process. Here, "the handler" is a device on
   the other side of a network link that may answer seconds or minutes
   later, or not at all — so state is recorded as uplink messages arrive
   and callers `wait_for_result`/poll instead of the call itself blocking
   on execution.
2. A bridge from an announced `Capability` (physical_command.py) into
   `CapabilityRegistry` (registry/capability_registry.py) — two "capability"
   vocabularies that otherwise never meet. Registration is the only thing
   this module does with that registry; it never asks the registry to
   decide a device's overall availability (that stays the backend's job,
   AI-O-04, 절대 준수 원칙 #15) — a device's capabilities are simply
   unregistered on request via `unregister_device`, for a caller that
   already has that verdict from elsewhere.

No MQTT/Kafka/Protobuf import here: `transport` only needs to satisfy the
`TransportProvider` Protocol (adapters.py) and `serializer` only needs an
`encode`/`decode` pair understanding the physical command envelope shape
(providers/physical_command_protobuf.py today; a JSON stand-in could sit
behind the same shape later without this module changing, AI-C-07).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from perception_framework.contracts.physical_command import (
    CancelCommandRequest,
    CancelCommandResponse,
    Capability,
    Command,
    CommandAcceptance,
    CommandResult,
    CommandStatus,
    ExecutionStatus,
    Failure,
    Rejection,
)
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def downlink_topic(device_id: str) -> str:
    return f"terminal/{device_id}/downlink"


def uplink_topic(device_id: str) -> str:
    return f"terminal/{device_id}/uplink"


@dataclass
class _TrackedCommand:
    acceptance: CommandAcceptance | None = None
    status: ExecutionStatus | None = None
    result: CommandResult | None = None
    cancel_response: CancelCommandResponse | None = None
    terminal: threading.Event = field(default_factory=threading.Event)


class PhysicalCommandGateway:
    """Send physical commands to, and track their outcome from, devices
    reachable only through `terminal/<device-id>/{downlink,uplink}`."""

    def __init__(
        self,
        transport: Any,
        serializer: Any,
        *,
        registry: CapabilityRegistry | None = None,
        capability_kind_prefix: str = "hardware.action",
    ) -> None:
        self._transport = transport
        self._serializer = serializer
        self._registry = registry
        self._capability_kind_prefix = capability_kind_prefix
        self._lock = threading.RLock()
        self._commands: dict[str, _TrackedCommand] = {}
        self._attached: set[str] = set()
        self._capabilities: dict[str, list[Capability]] = {}

    # -- outbound (edge -> device) -----------------------------------

    def attach(self, device_id: str) -> None:
        """Start listening to one device's uplink. Idempotent per device —
        a caller does not need to track which devices it already attached."""
        with self._lock:
            if device_id in self._attached:
                return
            self._attached.add(device_id)

        def _handler(payload: bytes, _device_id: str = device_id) -> None:
            self._on_uplink(_device_id, payload)

        self._transport.subscribe(uplink_topic(device_id), _handler)

    def send_command(self, device_id: str, command: Command) -> None:
        self._record(command.command_id)
        self._transport.publish(downlink_topic(device_id), self._serializer.encode(command))

    def send_cancel(self, device_id: str, request: CancelCommandRequest) -> None:
        self._transport.publish(downlink_topic(device_id), self._serializer.encode(request))

    # -- inbound state (device -> edge), async ------------------------

    def get_acceptance(self, command_id: str) -> CommandAcceptance | None:
        record = self._commands.get(command_id)
        return record.acceptance if record else None

    def get_status(self, command_id: str) -> ExecutionStatus | None:
        record = self._commands.get(command_id)
        return record.status if record else None

    def get_result(self, command_id: str) -> CommandResult | None:
        record = self._commands.get(command_id)
        return record.result if record else None

    def get_cancel_response(self, command_id: str) -> CancelCommandResponse | None:
        record = self._commands.get(command_id)
        return record.cancel_response if record else None

    def wait_for_result(self, command_id: str, timeout: float | None = None) -> CommandResult | None:
        """Block until a terminal outcome is known: either a `CommandResult`
        arrived, or the command was rejected (no `CommandResult` ever
        follows a rejection — interface-spec §4). Returns None on timeout
        or on an unknown command_id."""
        record = self._commands.get(command_id)
        if record is None:
            return None
        record.terminal.wait(timeout)
        return record.result

    def known_capabilities(self, device_id: str) -> tuple[Capability, ...]:
        return tuple(self._capabilities.get(device_id, ()))

    def unregister_device(self, device_id: str) -> None:
        """Drop this device's capabilities from the local registry. Call
        this only once availability information from elsewhere (AI-O-04)
        says the device is gone — this gateway never decides that itself."""
        if self._registry is None:
            return
        for capability in self._capabilities.pop(device_id, ()):
            self._registry.unregister_local(f"{self._capability_kind_prefix}.{capability.name}", device_id)

    # -- dispatch -------------------------------------------------------

    def _record(self, command_id: str) -> _TrackedCommand:
        with self._lock:
            record = self._commands.get(command_id)
            if record is None:
                record = _TrackedCommand()
                self._commands[command_id] = record
            return record

    def _on_uplink(self, device_id: str, payload: bytes) -> None:
        try:
            envelope = self._serializer.decode(payload)
            message_type = envelope.get("message_type")
            body = envelope.get("payload", {})
        except Exception:
            # A malformed wire message from one device must never take
            # down the gateway or any other device's tracking (AI-C-11).
            return

        handler: Callable[[dict], None] | None = {
            "acceptance": self._on_acceptance,
            "status": self._on_status,
            "result": self._on_result,
            "cancel_response": self._on_cancel_response,
        }.get(message_type)
        if handler is not None:
            handler(body)
        elif message_type == "capability":
            self._on_capability(device_id, body)
        # command/cancel_request are downlink-only shapes; a device that
        # sends one on uplink is a protocol violation this gateway simply
        # ignores rather than crashing over.

    def _on_acceptance(self, body: dict) -> None:
        rejection = None
        if "rejection" in body:
            rejection = Rejection(code=body["rejection"]["code"], message=body["rejection"]["message"])
        acceptance = CommandAcceptance(
            command_id=body["command_id"], accepted=body["accepted"],
            accepted_at=body["accepted_at"], rejection=rejection,
        )
        record = self._record(acceptance.command_id)
        with self._lock:
            record.acceptance = acceptance
            if not acceptance.accepted:
                # No CommandResult ever follows a rejection - the lifecycle
                # ends here (interface-spec §4).
                record.terminal.set()

    def _on_status(self, body: dict) -> None:
        status = CommandStatus(
            command_id=body["command_id"], status=ExecutionStatus(body["status"]),
            observed_at=body["observed_at"],
        )
        record = self._record(status.command_id)
        with self._lock:
            record.status = status.status

    def _on_result(self, body: dict) -> None:
        failure = Failure(**body["failure"]) if "failure" in body else None
        result = CommandResult(
            command_id=body["command_id"], status=ExecutionStatus(body["status"]),
            completed_at=body["completed_at"], result=body.get("result"), failure=failure,
        )
        record = self._record(result.command_id)
        with self._lock:
            record.result = result
            record.status = result.status
            record.terminal.set()

    def _on_cancel_response(self, body: dict) -> None:
        response = CancelCommandResponse(
            command_id=body["command_id"], accepted=body["accepted"], reason=body.get("reason"),
        )
        record = self._record(response.command_id)
        with self._lock:
            record.cancel_response = response

    def _on_capability(self, device_id: str, body: dict) -> None:
        capability = Capability(
            name=body["name"], version=body["version"],
            parameter_schema=body["parameter_schema"], result_schema=body["result_schema"],
            cancel_supported=body.get("cancel_supported", False),
            required_resources=tuple(body.get("required_resources", ())),
        )
        with self._lock:
            self._capabilities.setdefault(device_id, []).append(capability)
        if self._registry is None:
            return
        self._registry.register_local(ProviderRegistration(
            capability_kind=f"{self._capability_kind_prefix}.{capability.name}",
            provider_id=device_id,
            version=capability.version,
            compatibility=capability.compatibility_profile(),
            supported_inputs=(capability.parameter_schema,),
            supported_outputs=(capability.result_schema,),
        ))
