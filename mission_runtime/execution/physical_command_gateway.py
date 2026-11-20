"""Edge-side half of the physical command wire contract.

implements: AI-C-20, AI-C-06, AI-C-10, AI-C-05
tests: tests/test_physical_command_gateway.py

This is the code that actually speaks `specs/
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

Wire alignment (2026-09-19, interface-spec §8): the canonical bytes are now
HW 파트의 `package physical` 규약이다. 이 모듈은 그 변경을 거의 느끼지 않는다 —
바뀐 것은 직렬화기 한 곳이고, 여기로 올라오는 payload 는 여전히 우리 어휘다.
단 두 가지는 이 층에서도 보인다: (1) 장치가 보고한 시각이 와이어에 없어
`accepted_at`/`observed_at`/`completed_at` 이 **엣지 수신 시각**이고 payload 의
`time_source` 가 그렇다고 말한다, (2) `Capability` 선언이 action 이름까지만
실려 와서 `_on_capability` 가 덜 선언된 Capability 를 만든다(§8-3 P3~P7).

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

from mission_runtime.contracts.capability_contract import DeclarationBasis
from mission_runtime.contracts.physical_command import (
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
from mission_runtime.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def _basis_from(raw: Any) -> DeclarationBasis | None:
    """선언된 단위·좌표·시간 기준을 계약 객체로. 없으면 **만들지 않는다** —
    빈 객체를 만들면 "기준을 선언했다" 가 되어 미선언과 구분되지 않는다."""
    if raw is None:
        return None
    if isinstance(raw, DeclarationBasis):
        return raw
    if not isinstance(raw, dict):
        return None
    return DeclarationBasis(
        units={str(k): str(v) for k, v in (raw.get("units") or {}).items()},
        reference_frame=raw.get("reference_frame"),
        time_basis=raw.get("time_basis"),
    )


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

    def declared_cancel_support(self, device_id: str, action: str) -> bool | None:
        """그 장치가 그 action 의 **취소 가능 여부를 선언했는가, 뭐라고 했는가**.

        세 답이다: True / False / None(그 action 을 모르거나 아무도 선언하지
        않았다). 호출자가 None 을 False 로 접으면 안 되는 이유는 하나다 — 지금
        와이어(spec §8-3 P7)로 온 선언은 **전부** None 이고, 접는 순간 모든
        장치가 "취소를 거부하는 장치" 가 된다. 이 게이트웨이는 답만 주고
        취소를 보낼지는 정하지 않는다(AI-C-19).
        """
        for capability in self._capabilities.get(device_id, ()):
            if capability.name == action:
                return capability.cancel_supported
        return None

    def undeclared_declaration_items(self, device_id: str) -> dict[str, tuple[str, ...]]:
        """action -> 그 선언이 적지 않은 AI-C-18 항목들. 운영 화면과 협의
        문서가 "무엇이 아직 안 오는가" 를 셀 때 보는 자리다."""
        return {capability.name: capability.undeclared_items()
                for capability in self._capabilities.get(device_id, ())}

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
        except Exception:
            # A malformed *or contract-violating* wire message from one device
            # must never take down the gateway or any other device's tracking
            # (AI-C-05). The serializer rejects e.g. a terminal state sent as
            # CommandStatus (spec §4) by raising - that rejection is contained
            # here rather than propagating into the transport callback.
            return

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
        """Register everything one announcement declares.

        현재 와이어(spec §8-3 P7)는 action **이름 목록**만 싣는다. 그래서 한
        announcement 이 여러 Capability 가 되고, version/schema/자원 조건은
        `None`/빈 값으로 남는다 — 없는 선언을 placeholder 로 지어내지 않는다
        (AI-C-18). 선언이 풍부해지면 이 함수만 늘어난다.
        """
        declared = body.get("actions")
        if declared is None:  # 선언 항목이 풍부한 미래 와이어 / 내부 호출 경로
            declared = [body["name"]]
            basis = body.get("basis")
            scope = body.get("scope_tags")
            capabilities = [Capability(
                name=body["name"], version=body.get("version"),
                parameter_schema=body.get("parameter_schema"),
                result_schema=body.get("result_schema"),
                # **기본값을 주지 않는다.** `.get(..., False)` 였던 자리다 — 선언하지
                # 않은 장치가 "취소를 거부한다" 로 읽혔다(AI-C-18 "모든 항목이 항상
                # 존재한다고 가정해서는 안 된다"). 없으면 None 으로 남긴다.
                cancel_supported=body.get("cancel_supported"),
                required_resources=tuple(body.get("required_resources", ())),
                optional_resources=tuple(body.get("optional_resources", ())),
                idempotent=body.get("idempotent"),
                invocation=body.get("invocation"),
                basis=_basis_from(basis),
                # None 과 `()` 가 다르다 — 범위를 선언하지 않은 것과 "제약 없음"을
                # 선언한 것은 같은 값이 아니다.
                scope_tags=None if scope is None else tuple(scope),
                execution_profile_ref=body.get("execution_profile_ref"),
            )]
        else:
            capabilities = [Capability(name=str(action)) for action in declared]

        with self._lock:
            # 같은 action 을 다시 알리면 **덮어쓴다**. 누적하면 장치가 재접속해 다시
            # 알릴 때마다 어휘가 불어나고(한 번 끊겼다 붙은 로봇의 `move` 가 두 개가
            # 된다), 그 목록으로 명령 가능 여부를 판정하는 쪽이 같은 action 을 여러
            # 번 보게 된다. 이름이 그 장치 안에서 action 의 신원이므로 이름 기준으로
            # 바꿔 넣는 것이 옳다 — 나중에 온 선언이 더 풍부할 수 있고(version·schema가
            # 채워진 선언) 그때 빈 선언이 이기면 안 된다.
            known = {existing.name: existing
                     for existing in self._capabilities.get(device_id, ())}
            for capability in capabilities:
                known[capability.name] = capability
            self._capabilities[device_id] = list(known.values())
        if self._registry is None:
            return
        for capability in capabilities:
            self._registry.register_local(ProviderRegistration(
                capability_kind=f"{self._capability_kind_prefix}.{capability.name}",
                provider_id=device_id,
                version=capability.version or "",
                compatibility=capability.compatibility_profile(),
                supported_inputs=(capability.parameter_schema,) if capability.parameter_schema else (),
                supported_outputs=(capability.result_schema,) if capability.result_schema else (),
                # 선언의 **성질** 칸들을 레지스트리까지 들려 보낸다. 이것이 없으면
                # 선언이 이 게이트웨이 안에만 남고, 기능을 고르는 쪽은 취소 가능
                # 여부·멱등성·동기성을 선언에서 알 수 없다(AI-C-18 "상위 기능은
                # 필요한 capability 와 조건을 기준으로 탐색·사용").
                declaration=capability.to_declaration(),
            ))
