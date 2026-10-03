"""비행 컴퓨터(Pi 5) 자체 상태 — 상태판의 「Pi」 칸과 패스 시작 점검이 쓴다.

Pi 5 는 뜨거우면 스스로 CPU 를 늦춘다(스로틀링) — 50 Hz 비행 제어 주기가 흔들린다. SD 가 차면 기록이 끊긴다.
값을 못 읽는 환경(노트북 · 시험)에서는 그 칸만 None 이다.

  cpu_temp_c       /sys/class/thermal/thermal_zone0/temp
  throttled        vcgencmd get_throttled 의 비트 — now: 지금 늦추는 중 · since_boot: 부팅 뒤 한 번이라도
  load1            1 분 평균 부하 / 코어 수 (1.0 = 전부 바쁨)
  disk_free_gb     비행 기록 폴더가 있는 디스크의 남은 용량
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

TEMP_WARN_C, TEMP_BAD_C = 70.0, 80.0           # Pi 5 는 85 °C 부근에서 늦추기 시작한다
DISK_WARN_GB, DISK_BAD_GB = 5.0, 1.0


def _cpu_temp() -> float | None:
    try:
        return round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0, 1)
    except (OSError, ValueError):
        return None


def _throttled() -> dict | None:
    """비트: 0 저전압 · 1 클럭 제한 · 2 지금 늦춤 · 3 온도 한계 / 16~19 = 부팅 뒤 한 번이라도."""
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1).stdout
        v = int(out.strip().split("=")[1], 16)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None
    return {"raw": hex(v), "undervolt": bool(v & 0x1), "now": bool(v & 0x6), "temp_limit": bool(v & 0x8),
            "since_boot": bool(v & 0xF0000)}


def snapshot(log_dir: str | os.PathLike | None = None) -> dict:
    target = Path(log_dir) if log_dir and Path(log_dir).exists() else Path("/")
    du = shutil.disk_usage(target)
    try:
        load1 = round(os.getloadavg()[0] / (os.cpu_count() or 1), 2)
    except OSError:
        load1 = None
    s = {"cpu_temp_c": _cpu_temp(), "throttled": _throttled(), "load1": load1,
         "disk_free_gb": round(du.free / 1e9, 1), "disk_path": str(target), "time": time.time()}
    s["level"] = level(s)
    return s


def level(s: dict) -> str:
    """ok · warn · bad — 상태판 칩 색과 패스 시작 점검이 같이 쓴다."""
    t, th, disk = s.get("cpu_temp_c"), s.get("throttled") or {}, s.get("disk_free_gb")
    if (t is not None and t >= TEMP_BAD_C) or th.get("now") or th.get("undervolt") or (disk is not None and disk < DISK_BAD_GB):
        return "bad"
    if (t is not None and t >= TEMP_WARN_C) or th.get("since_boot") or (disk is not None and disk < DISK_WARN_GB):
        return "warn"
    return "ok"


class PiHealth:
    """1 초에 한 번만 다시 읽는다 — fcx 는 5 Hz 로 나가지만 vcgencmd 를 매번 부를 까닭은 없다."""

    def __init__(self, log_dir: str | os.PathLike | None = None, period_s: float = 1.0) -> None:
        self.log_dir = log_dir or os.environ.get("SAR_LOG_DIR")
        self.period_s = period_s
        self._at = 0.0
        self._last: dict | None = None

    def get(self) -> dict:
        now = time.monotonic()
        if self._last is None or now - self._at >= self.period_s:
            self._last, self._at = snapshot(self.log_dir), now
        return self._last
