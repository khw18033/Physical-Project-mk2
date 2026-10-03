"""RTCM3 프레임 — 베이스 수신기가 내보내는 바이트 흐름에서 완전한 프레임만 골라낸다.

프레임 = 0xD3 · 6비트 0 · 10비트 길이 · 본문(길이 바이트) · CRC-24Q(3바이트).
CRC 가 맞는 것만 넘긴다 — 시리얼 잡음이나 NMEA 같은 다른 출력이 섞여도 FC 에 쓰레기를 넣지 않는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

PREAMBLE = 0xD3
MAX_PAYLOAD = 1023


def _crc24q_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
        table.append(crc & 0xFFFFFF)
    return table


_TABLE = _crc24q_table()


def crc24q(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFF) ^ _TABLE[(crc >> 16) ^ b]
    return crc


def make_frame(payload: bytes) -> bytes:
    """본문 → 완전한 프레임 (시험과 흉내용)."""
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("RTCM3 본문은 1023 바이트를 넘을 수 없다")
    head = bytes([PREAMBLE, (len(payload) >> 8) & 0x03, len(payload) & 0xFF])
    crc = crc24q(head + payload)
    return head + payload + crc.to_bytes(3, "big")


def message_type(frame: bytes) -> int | None:
    """본문 앞 12비트 = 메시지 번호 (1005 · 1077 · 1087 …)."""
    if len(frame) < 6:
        return None
    return (frame[3] << 4) | (frame[4] >> 4)


class Framer:
    """바이트를 조각조각 넣으면 완전한 프레임을 내놓는다. 깨진 것은 버리고 센다."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.bad_crc = 0
        self.skipped = 0

    def feed(self, chunk: bytes) -> Iterator[bytes]:
        self.buf += chunk
        while True:
            start = self.buf.find(bytes([PREAMBLE]))
            if start < 0:
                self.skipped += len(self.buf)
                self.buf.clear()
                return
            if start:
                self.skipped += start
                del self.buf[:start]
            if len(self.buf) < 3:
                return
            if self.buf[1] & 0xFC:          # 예약 6비트는 0 이어야 한다 — 아니면 우연한 0xD3
                self.skipped += 1
                del self.buf[0]
                continue
            length = ((self.buf[1] & 0x03) << 8) | self.buf[2]
            total = 3 + length + 3
            if len(self.buf) < total:
                return
            frame = bytes(self.buf[:total])
            if crc24q(frame[:-3]) == int.from_bytes(frame[-3:], "big"):
                del self.buf[:total]
                yield frame
            else:
                self.bad_crc += 1
                del self.buf[0]             # 한 바이트 밀고 다시 찾는다


# ── 1005 / 1006: 기지국 위치 (화면에 「어느 베이스의 보정인가」를 적는다) ─────────


class _Bits:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def u(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.data[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def s(self, n: int) -> int:
        v = self.u(n)
        return v - (1 << n) if v & (1 << (n - 1)) else v


@dataclass(frozen=True)
class BaseStation:
    station_id: int
    x: float
    y: float
    z: float

    @property
    def lla(self) -> tuple[float, float, float]:
        return ecef_to_lla(self.x, self.y, self.z)


def parse_base_station(frame: bytes) -> BaseStation | None:
    """1005/1006 → 기지국 ECEF. 다른 메시지면 None."""
    mt = message_type(frame)
    if mt not in (1005, 1006):
        return None
    b = _Bits(frame[3:-3])
    b.u(12)                     # 메시지 번호
    station = b.u(12)
    b.u(6 + 1 + 1 + 1 + 1)      # ITRF 연도 · GPS/GLO/GAL · 기준국 표시
    x = b.s(38) * 1e-4
    b.u(1 + 1)                  # 단일 수신기 · 예약
    y = b.s(38) * 1e-4
    b.u(2)                      # 1/4 주기 표시
    z = b.s(38) * 1e-4
    return BaseStation(station, x, y, z)


def ecef_to_lla(x: float, y: float, z: float) -> tuple[float, float, float]:
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(6):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - e2 * n / (n + alt)))
    n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    alt = p / math.cos(lat) - n
    return math.degrees(lat), math.degrees(lon), alt


def lla_to_ecef(lat: float, lon: float, alt: float) -> tuple[float, float, float]:
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    la, lo = math.radians(lat), math.radians(lon)
    n = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return ((n + alt) * math.cos(la) * math.cos(lo), (n + alt) * math.cos(la) * math.sin(lo),
            (n * (1 - e2) + alt) * math.sin(la))


def make_1005(station_id: int, lat: float, lon: float, alt: float) -> bytes:
    """시험·흉내용 1005 프레임."""
    x, y, z = lla_to_ecef(lat, lon, alt)
    fields = [(1005, 12), (station_id, 12), (0, 6), (1, 1), (0, 1), (0, 1), (0, 1),
              (round(x * 1e4) & ((1 << 38) - 1), 38), (0, 1), (0, 1),
              (round(y * 1e4) & ((1 << 38) - 1), 38), (0, 2),
              (round(z * 1e4) & ((1 << 38) - 1), 38)]
    bits = "".join(format(v, f"0{n}b") for v, n in fields)
    bits += "0" * (-len(bits) % 8)
    return make_frame(int(bits, 2).to_bytes(len(bits) // 8, "big"))
