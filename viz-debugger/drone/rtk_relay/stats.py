"""보정 흐름 통계 — 「수신 중인가 · 끊겼나 · 어느 베이스인가」. 노트북과 Pi 양쪽이 같은 것을 쓴다."""

from __future__ import annotations

import time
from collections import Counter, deque

from .rtcm3 import BaseStation, message_type, parse_base_station

# 이만큼 아무것도 안 오면 「끊김」. 베이스는 보통 1 Hz 로 낸다.
STALE_S = 3.0


class RtcmStats:
    def __init__(self, clock=time.time) -> None:  # noqa: ANN001
        self.clock = clock
        self.started = clock()
        self.frames = 0
        self.bytes = 0
        self.types: Counter[int] = Counter()
        self.base: BaseStation | None = None
        self.last_at: float | None = None
        self._recent: deque[tuple[float, int]] = deque()

    def note(self, frame: bytes) -> None:
        now = self.clock()
        self.frames += 1
        self.bytes += len(frame)
        mt = message_type(frame)
        if mt is not None:
            self.types[mt] += 1
        base = parse_base_station(frame)
        if base is not None:
            self.base = base
        self.last_at = now
        self._recent.append((now, len(frame)))
        while self._recent and now - self._recent[0][0] > 10.0:
            self._recent.popleft()

    def age_s(self) -> float | None:
        return None if self.last_at is None else self.clock() - self.last_at

    def receiving(self) -> bool:
        age = self.age_s()
        return age is not None and age <= STALE_S

    def snapshot(self) -> dict:
        now = self.clock()
        window = min(10.0, max(1e-6, now - self.started))
        recent_bytes = sum(n for _t, n in self._recent)
        lla = self.base.lla if self.base is not None else None
        age = self.age_s()
        return {
            "receiving": self.receiving(),
            "age_s": None if age is None else round(age, 2),
            "frames": self.frames,
            "bytes": self.bytes,
            "rate_bps": round(recent_bytes / window, 1),
            "frames_per_s": round(len(self._recent) / window, 2),
            "types": {str(k): v for k, v in sorted(self.types.items())},
            "base": None if self.base is None else {
                "station_id": self.base.station_id,
                "lat": round(lla[0], 8), "lon": round(lla[1], 8), "alt_m": round(lla[2], 3),
            },
        }

    def line(self) -> str:
        s = self.snapshot()
        state = "수신 중" if s["receiving"] else ("끊김" if s["age_s"] is not None else "아직 없음")
        base = s["base"]
        where = f" · 베이스 #{base['station_id']} {base['lat']:.6f},{base['lon']:.6f}" if base else " · 베이스 위치(1005/1006) 아직 없음"
        types = ",".join(s["types"]) or "-"
        return f"보정 {state} · {s['rate_bps']:.0f} B/s · 메시지 {types}{where}"
