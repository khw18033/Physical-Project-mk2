"""흉내 레이더(cansar) — CAP_ON 을 몇 초마다 보고, 처리 지연 뒤 CAP_ACK 를 쓰고 지운다. **시험 전용.**

실제 cansar 의 동작을 모른다. 「파일을 주기적으로 본다」는 가정만 흉내 내어 지연이 생기는 모양을 만든다.
"""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path


class FakeCansarTick:
    """시뮬레이터 시계용 — SimClock._tick 에 붙인다(시간을 스스로 밀지 않는다)."""

    def __init__(self, clock, cap: Path, ack: Path | None, poll_s: float = 0.5, proc_s: float = 0.1, seed: int = 0,  # noqa: ANN001
                 events: Path | None = None) -> None:
        """events 를 주면 CAP_ACK 대신 레이더 팀처럼 events.csv 에 start · stop 줄을 쓴다."""
        self.clock, self.cap, self.ack, self.events = clock, cap, ack, events
        if events is not None and not events.exists():
            events.parent.mkdir(parents=True, exist_ok=True)
            events.write_text("event,pi_epoch,sdr_uptime\n")
        self.poll_s, self.proc_s = poll_s, proc_s
        self.rng = random.Random(seed)
        self._next_poll = clock.now() + self.rng.random() * poll_s
        self._pending: tuple[str, float] | None = None
        self.recording = False

    def __call__(self, _dt: float) -> None:
        now = self.clock.now()
        if self._pending is not None and now >= self._pending[1]:
            kind, _ = self._pending
            self._pending = None
            if self.events is not None:
                with self.events.open("a") as f:
                    f.write(f"{kind},{now:.6f},{now - 1.7e9:.6f}\n")
            if kind == "start":
                self.recording = True
                if self.ack is not None:
                    self.ack.write_text(f"{now:.6f}")
            else:
                self.recording = False
                if self.ack is not None:
                    self.ack.unlink(missing_ok=True)
        if now >= self._next_poll:
            self._next_poll = now + self.poll_s
            on = self.cap.exists()
            if on and not self.recording and self._pending is None:
                self._pending = ("start", now + self.proc_s)
            elif not on and self.recording and self._pending is None:
                self._pending = ("stop", now + self.proc_s)


async def run_fake_cansar(cap: Path, ack: Path, poll_s: float = 0.5, proc_s: float = 0.1) -> None:
    """실제 시간용 (PX4 SITL)."""
    recording = False
    try:
        while True:
            await asyncio.sleep(poll_s)
            on = cap.exists()
            if on and not recording:
                await asyncio.sleep(proc_s)
                ack.write_text(f"{time.time():.6f}")
                recording = True
            elif not on and recording:
                await asyncio.sleep(proc_s)
                ack.unlink(missing_ok=True)
                recording = False
    except asyncio.CancelledError:
        ack.unlink(missing_ok=True)
