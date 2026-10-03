"""RTCM 프레임 → MAVLink GPS_RTCM_DATA (#233). PX4 가 받아 GPS 모듈에 그대로 흘려 넣는다.

QGroundControl 이 RTK 베이스를 붙였을 때 하는 일과 같다:
- 180 바이트 이하면 한 메시지 (flags = 시퀀스 << 3).
- 넘으면 180 바이트씩 최대 4조각 (flags = 1 | 조각번호 << 1 | 시퀀스 << 3).
- 4조각(720 바이트)을 넘는 프레임은 실을 수 없어 버리고 센다.
시퀀스는 5비트(0~31)이고 원본 프레임마다 하나씩 늘어난다.

다른 MAVLink 프로그램(예: cansar_pi.py)에 붙일 때는 `PymavlinkInjector(그 연결).send_frame(frame)` 한 줄이면 된다.
"""

from __future__ import annotations

from typing import Callable

CHUNK = 180
MAX_FRAGMENTS = 4

SendFn = Callable[[int, int, bytes], None]   # (flags, len, data 180바이트)


class RtcmInjector:
    def __init__(self, send: SendFn) -> None:
        self._send = send
        self.seq = 0
        self.sent_frames = 0
        self.sent_messages = 0
        self.dropped_oversize = 0

    def send_frame(self, frame: bytes) -> bool:
        if len(frame) > CHUNK * MAX_FRAGMENTS:
            self.dropped_oversize += 1
            return False
        seq = self.seq & 0x1F
        self.seq = (self.seq + 1) & 0x1F
        if len(frame) <= CHUNK:
            self._send(seq << 3, len(frame), frame.ljust(CHUNK, b"\0"))
            self.sent_messages += 1
        else:
            for frag, off in enumerate(range(0, len(frame), CHUNK)):
                part = frame[off:off + CHUNK]
                self._send(1 | (frag << 1) | (seq << 3), len(part), part.ljust(CHUNK, b"\0"))
                self.sent_messages += 1
        self.sent_frames += 1
        return True


def reassemble(messages: list[tuple[int, int, bytes]]) -> list[bytes]:
    """시험용 — 보낸 메시지들을 원래 프레임으로 되돌린다."""
    out: list[bytes] = []
    pending: dict[int, list[bytes]] = {}
    for flags, length, data in messages:
        part = bytes(data[:length])
        if not flags & 1:
            out.append(part)
            continue
        seq = flags >> 3
        pending.setdefault(seq, []).append(part)
        if length < CHUNK or len(pending[seq]) == MAX_FRAGMENTS:
            out.append(b"".join(pending.pop(seq)))
    for parts in pending.values():   # 정확히 180 의 배수로 끝난 프레임
        out.append(b"".join(parts))
    return out


class PymavlinkInjector(RtcmInjector):
    """pymavlink 연결(mavutil.mavlink_connection(...))에 바로 붙인다."""

    def __init__(self, master) -> None:  # noqa: ANN001
        def send(flags: int, length: int, data: bytes) -> None:
            master.mav.gps_rtcm_data_send(flags, length, data)

        super().__init__(send)
