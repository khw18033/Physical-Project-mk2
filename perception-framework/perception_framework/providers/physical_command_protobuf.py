"""Canonical Protobuf binding for the physical-command core contract."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from google.protobuf.json_format import MessageToDict, ParseDict

from perception_framework.contracts.proto import physical_command_pb2 as pb


_MESSAGE_TYPES = {
    "command": "command",
    "acceptance": "acceptance",
    "status": "status",
    "result": "result",
    "cancel_request": "cancel_request",
    "cancel_response": "cancel_response",
    "capability": "capability",
}
_CLASS_TYPES = {
    "Command": "command",
    "CommandAcceptance": "acceptance",
    "CommandResult": "result",
    "CommandStatus": "status",
    "CancelCommandRequest": "cancel_request",
    "CancelCommandResponse": "cancel_response",
    "Capability": "capability",
}


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items() if item is not None}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class PhysicalCommandProtobufSerializerProvider:
    """Serialize one physical lifecycle message in a typed oneof envelope."""

    format_id = "physical_command_protobuf_v1"
    human_readable = False

    def encode(self, obj: Any) -> bytes:
        if is_dataclass(obj):
            message_type = _CLASS_TYPES.get(type(obj).__name__)
            payload = _plain(obj)
        elif isinstance(obj, dict):
            message_type = obj.get("message_type")
            payload = _plain(obj.get("payload", {}))
        else:
            raise TypeError("physical command protobuf requires a contract dataclass or envelope dict")
        field = _MESSAGE_TYPES.get(str(message_type))
        if field is None:
            raise ValueError(f"unsupported physical message type: {message_type}")
        envelope = pb.PhysicalCommandEnvelope()
        ParseDict(payload, getattr(envelope, field), ignore_unknown_fields=False)
        return envelope.SerializeToString(deterministic=True)

    def decode(self, payload: bytes, schema_hint: str | None = None) -> dict[str, Any]:
        envelope = pb.PhysicalCommandEnvelope()
        envelope.ParseFromString(payload)
        field = envelope.WhichOneof("body")
        if field is None:
            raise ValueError("physical command protobuf envelope has no body")
        value = MessageToDict(
            getattr(envelope, field), preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
        )
        return {"message_type": field, "payload": value}
