"""Wire-format providers and the boundary policy that chooses between them.

implements: AI-C-07, AI-C-04, AI-C-12, AI-C-15, AI-C-16

AI-C-07은 "업무 데이터의 내부 구조와 네트워크 전송용 직렬화 형식을 분리하고
공통 직렬화 인터페이스를 통해 변환"할 것과 "특정 바이너리 또는 텍스트 형식이
프레임워크의 필수조건이 되어서는 안 된다"를 요구한다. 그 요구는 provider가
하나뿐이면 검증할 수 없으므로 이 모듈은 두 번째 실제 wire format을 제공한다.

또한 AI-C-07은 경계별 우선순위를 규정한다: "기계 간 통신에서는 크기·처리속도·
스키마 안정성을, 사람이 확인하는 경계에서는 가독성을 우선". 그 선택은 업무
로직이 아니라 배포 설정(`SerializationPolicy`)이 내린다. 상위 코드는 여전히
`SerializerProvider` Protocol만 본다 — 어떤 형식이 실제로 쓰이는지 모른다.

새 형식(Protobuf, MessagePack, CBOR ...)은 `register_serializer()` 한 줄로
추가하며 이 모듈 밖의 코드는 고치지 않는다 (AI-C-04, AI-C-12).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Callable

from perception_framework.providers.adapters import SerializerProvider
from perception_framework.providers.fakes import JsonSerializerProvider

# --------------------------------------------------------------------------
# Compact binary wire format (stdlib only — 폐쇄망 조달 제약, AI-C-16)
# --------------------------------------------------------------------------
#
# Self-describing tag-length-value encoding. Every value is one tag byte
# followed by that tag's body. Lengths and integers use LEB128 varints so
# small values cost 1 byte instead of JSON's decimal text + separators.
#
#   0x00 null            (no body)
#   0x01 false           (no body)
#   0x02 true            (no body)
#   0x03 int             zigzag varint
#   0x04 float           8-byte IEEE-754 little endian
#   0x05 str             varint byte length + UTF-8 bytes
#   0x06 bytes           varint byte length + raw bytes
#   0x07 list            varint item count + items
#   0x08 dict            varint pair count + (str key, value) pairs

_T_NULL = 0x00
_T_FALSE = 0x01
_T_TRUE = 0x02
_T_INT = 0x03
_T_FLOAT = 0x04
_T_STR = 0x05
_T_BYTES = 0x06
_T_LIST = 0x07
_T_DICT = 0x08

_DOUBLE = struct.Struct("<d")


def _put_uvarint(out: bytearray, value: int) -> None:
    if value < 0:
        raise ValueError("uvarint is unsigned")
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return


def _get_uvarint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 63) if value >= 0 else ((-value) << 1) - 1


def _unzigzag(value: int) -> int:
    return (value >> 1) if not value & 1 else -((value + 1) >> 1)


class CompactBinarySerializerProvider:
    """SerializerProvider producing a compact tag-length-value binary wire
    format, using only the standard library (AI-C-07, AI-C-16).

    Contract parity with `JsonSerializerProvider` is deliberate: dict keys
    are coerced to `str` and unrepresentable objects fall back to `str(obj)`,
    exactly like `json.dumps(..., default=str)`. Two providers that disagree
    about what a message *means* would not be interchangeable, and AI-C-07's
    substitutability claim would be false.
    """

    format_id = "compact_binary_v1"
    human_readable = False

    def encode(self, obj: Any) -> bytes:
        out = bytearray()
        self._encode_into(out, obj)
        return bytes(out)

    def _encode_into(self, out: bytearray, obj: Any) -> None:
        if obj is None:
            out.append(_T_NULL)
        elif obj is True:
            out.append(_T_TRUE)
        elif obj is False:
            out.append(_T_FALSE)
        elif isinstance(obj, int):
            out.append(_T_INT)
            _put_uvarint(out, _zigzag(obj))
        elif isinstance(obj, float):
            out.append(_T_FLOAT)
            out += _DOUBLE.pack(obj)
        elif isinstance(obj, str):
            raw = obj.encode("utf-8")
            out.append(_T_STR)
            _put_uvarint(out, len(raw))
            out += raw
        elif isinstance(obj, (bytes, bytearray)):
            out.append(_T_BYTES)
            _put_uvarint(out, len(obj))
            out += bytes(obj)
        elif isinstance(obj, (list, tuple)):
            out.append(_T_LIST)
            _put_uvarint(out, len(obj))
            for item in obj:
                self._encode_into(out, item)
        elif isinstance(obj, dict):
            out.append(_T_DICT)
            _put_uvarint(out, len(obj))
            for key, value in obj.items():
                raw = str(key).encode("utf-8")
                _put_uvarint(out, len(raw))
                out += raw
                self._encode_into(out, value)
        else:
            # Same lossy fallback as json.dumps(default=str), on purpose.
            self._encode_into(out, str(obj))

    def decode(self, payload: bytes, schema_hint: str | None = None) -> Any:
        value, pos = self._decode_at(bytes(payload), 0)
        if pos != len(payload):
            raise ValueError("trailing bytes after decoded value")
        return value

    def _decode_at(self, buf: bytes, pos: int) -> tuple[Any, int]:
        if pos >= len(buf):
            raise ValueError("truncated payload")
        tag = buf[pos]
        pos += 1
        if tag == _T_NULL:
            return None, pos
        if tag == _T_TRUE:
            return True, pos
        if tag == _T_FALSE:
            return False, pos
        if tag == _T_INT:
            raw, pos = _get_uvarint(buf, pos)
            return _unzigzag(raw), pos
        if tag == _T_FLOAT:
            end = pos + 8
            if end > len(buf):
                raise ValueError("truncated float")
            return _DOUBLE.unpack_from(buf, pos)[0], end
        if tag in (_T_STR, _T_BYTES):
            length, pos = _get_uvarint(buf, pos)
            end = pos + length
            if end > len(buf):
                raise ValueError("truncated string/bytes")
            chunk = buf[pos:end]
            return (chunk.decode("utf-8") if tag == _T_STR else chunk), end
        if tag == _T_LIST:
            count, pos = _get_uvarint(buf, pos)
            items = []
            for _ in range(count):
                item, pos = self._decode_at(buf, pos)
                items.append(item)
            return items, pos
        if tag == _T_DICT:
            count, pos = _get_uvarint(buf, pos)
            result: dict[str, Any] = {}
            for _ in range(count):
                klen, pos = _get_uvarint(buf, pos)
                end = pos + klen
                if end > len(buf):
                    raise ValueError("truncated dict key")
                key = buf[pos:end].decode("utf-8")
                value, pos = self._decode_at(buf, end)
                result[key] = value
            return result, pos
        raise ValueError(f"unknown wire tag 0x{tag:02x}")


# --------------------------------------------------------------------------
# Registry + boundary policy
# --------------------------------------------------------------------------

_REGISTRY: dict[str, Callable[[], SerializerProvider]] = {
    "json": JsonSerializerProvider,
    "compact_binary_v1": CompactBinarySerializerProvider,
}


def register_serializer(format_id: str, factory: Callable[[], SerializerProvider]) -> None:
    """Add a wire format without touching business logic (AI-C-04, AI-C-12).

    A Protobuf/MessagePack/CBOR provider is registered here and selected by
    deployment configuration; no perception/decision/risk module changes.
    """
    _REGISTRY[format_id] = factory


def available_formats() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def build_serializer(format_id: str) -> SerializerProvider:
    try:
        return _REGISTRY[format_id]()
    except KeyError:
        raise KeyError(
            f"unknown serializer format '{format_id}'; registered: {available_formats()}"
        ) from None


# Boundary names are transport-technology-neutral on purpose: they describe
# *who reads the bytes*, not which broker carries them (AI-C-07, AI-C-14).
MACHINE_BOUNDARIES = ("terminal_to_edge", "edge_to_server", "control")
HUMAN_BOUNDARIES = ("operator_view", "diagnostics", "config")


@dataclass(frozen=True)
class SerializationPolicy:
    """Maps a communication boundary to a wire format (AI-C-07).

    The policy — not the caller — decides format. Business logic asks for a
    boundary by name and receives *a* `SerializerProvider`; it never names
    JSON or a binary format, so changing this mapping in a deployment
    profile changes no business code (절대 준수 원칙 #1, #2).
    """

    by_boundary: dict[str, str]
    default_format: str = "json"

    def format_for(self, boundary: str) -> str:
        return self.by_boundary.get(boundary, self.default_format)

    def serializer_for(self, boundary: str) -> SerializerProvider:
        return build_serializer(self.format_for(boundary))

    @staticmethod
    def default() -> "SerializationPolicy":
        """AI-C-07's stated priorities as the out-of-the-box mapping:
        machine-to-machine boundaries get the compact binary format,
        human-facing boundaries get JSON (가독성).

        Measured trade-off (experiments/runs/serializer-comparison.json,
        seeds 0-19, 200 iters/message): the binary format costs 0.79-0.88x
        the bytes of JSON but 1.5-2.4x the encode time and 2.5-6.8x the
        decode time, because CPython's `json` is a C extension while this
        format is pure Python. So the default favours bandwidth, which is
        the scarce resource on the 말단<->엣지 link; a CPU-bound node should
        override the mapping to "json" in its profile. That override is
        exactly the deployment decision AI-C-07 requires to be
        configuration rather than code.
        """
        mapping = {b: "compact_binary_v1" for b in MACHINE_BOUNDARIES}
        mapping.update({b: "json" for b in HUMAN_BOUNDARIES})
        return SerializationPolicy(by_boundary=mapping, default_format="json")

    @staticmethod
    def from_config(config: dict | None) -> "SerializationPolicy":
        """Build from a deployment profile fragment, e.g.

            {"default_format": "json",
             "by_boundary": {"edge_to_server": "compact_binary_v1"}}

        An empty/absent fragment yields the default policy, so a deployment
        that never mentions serialization still runs (AI-C-05).
        """
        if not config:
            return SerializationPolicy.default()
        base = dict(SerializationPolicy.default().by_boundary)
        base.update(config.get("by_boundary", {}) or {})
        unknown = sorted(set(base.values()) - set(_REGISTRY))
        if unknown:
            raise KeyError(f"serialization policy names unregistered formats: {unknown}")
        return SerializationPolicy(
            by_boundary=base,
            default_format=config.get("default_format", "json"),
        )


def load_policy_from_profile(path) -> SerializationPolicy:
    """Read the optional `"serialization"` fragment of a deployment profile
    file (AI-C-07, AI-C-15). Profiles without one get the default policy.
    """
    import json as _json
    from pathlib import Path as _Path

    raw = _json.loads(_Path(path).read_text(encoding="utf-8"))
    return SerializationPolicy.from_config(raw.get("serialization"))
