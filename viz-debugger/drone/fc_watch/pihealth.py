"""비행 컴퓨터(Pi 5) 자체 상태 — 상태판의 「Pi」 칸과 패스 시작 점검이 쓴다.

Pi 5 는 뜨거우면 스스로 CPU 를 늦춘다(스로틀링) — 50 Hz 비행 제어 주기가 흔들린다. SD 가 차면 기록이 끊긴다.
값을 못 읽는 환경(노트북 · 시험)에서는 그 칸만 None 이다.

  cpu_temp_c       /sys/class/thermal/thermal_zone0/temp
  throttled        vcgencmd get_throttled 의 비트 — now: 지금 늦추는 중 · since_boot: 부팅 뒤 한 번이라도
  load1            1 분 평균 부하 / 코어 수 (1.0 = 전부 바쁨)
  disk_free_gb     비행 기록 폴더가 있는 디스크의 남은 용량
  wifi             지상국 핫스팟 WiFi — 주파수(MHz) · 신호 세기(dBm). 레이더가 5.8 GHz 라 WiFi 가 5.65~5.95 GHz 에
                   붙으면 서로 간섭한다(영상 줄무늬 · WiFi 끊김) → 핫스팟은 2.4 GHz 로 고정한다
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

TEMP_WARN_C, TEMP_BAD_C = 70.0, 80.0           # Pi 5 는 85 °C 부근에서 늦추기 시작한다
DISK_WARN_GB, DISK_BAD_GB = 5.0, 1.0
RADAR_BAND_MHZ = (5650, 5950)                  # 레이더(5.8 GHz) 둘레 — 여기 WiFi 는 막는다
WIFI_WEAK_DBM = -75                            # 이보다 약하면 패스 중 끊기기 쉽다


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


def _eth(iface: str | None = None) -> dict | None:
    """유선(SDR) 포트 — 연결 속도(Mb/s) · 수신 오류 · 버려진 패킷. 이더넷이 없으면 None."""
    base = Path("/sys/class/net")
    names = [iface] if iface else sorted(n.name for n in base.glob("e*")) if base.is_dir() else []
    for n in names:
        d = base / n
        try:
            if (d / "operstate").read_text().strip() != "up":
                return {"iface": n, "up": False, "speed_mbps": None, "rx_errors": None, "rx_dropped": None}
            speed = int((d / "speed").read_text().strip())
            st = d / "statistics"
            return {"iface": n, "up": True, "speed_mbps": speed, "rx_errors": int((st / "rx_errors").read_text()),
                    "rx_dropped": int((st / "rx_dropped").read_text())}
        except (OSError, ValueError):
            continue
    return None


def _wifi(iface: str | None = None) -> dict | None:
    """WiFi 연결 — iw 로 주파수 · 신호, /proc/net/wireless 로 신호(iw 가 없을 때). 무선이 없으면 None."""
    iface = iface or os.environ.get("SAR_WIFI_IFACE", "wlan0")
    if not Path(f"/sys/class/net/{iface}/wireless").exists():
        return None
    freq = signal = None
    ssid = None
    try:
        out = subprocess.run(["iw", "dev", iface, "link"], capture_output=True, text=True, timeout=1).stdout
        if "Not connected" in out:
            return {"iface": iface, "connected": False, "freq_mhz": None, "signal_dbm": None, "ssid": None}
        for line in out.splitlines():
            k, _, v = line.strip().partition(":")
            if k == "freq":
                freq = int(float(v.split()[0]))
            elif k == "signal":
                signal = int(float(v.split()[0]))
            elif k == "SSID":
                ssid = v.strip()
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    if signal is None:
        try:
            for line in Path("/proc/net/wireless").read_text().splitlines()[2:]:
                parts = line.split()
                if parts and parts[0].rstrip(":") == iface:
                    signal = int(float(parts[3].rstrip(".")))
        except (OSError, ValueError, IndexError):
            pass
    return {"iface": iface, "connected": freq is not None or signal is not None, "freq_mhz": freq, "signal_dbm": signal, "ssid": ssid}


def wifi_problem(w: dict | None) -> tuple[str, str] | None:
    """(level, 까닭) — 레이더 대역이면 bad, 다른 5 GHz · 약한 신호 · 끊김은 warn."""
    if not w:
        return None
    if not w.get("connected"):
        return "warn", "WiFi 연결 없음 — 지상국과 이야기할 수 없다(비행 · 기록은 계속된다)"
    f, sig = w.get("freq_mhz"), w.get("signal_dbm")
    if f is not None and RADAR_BAND_MHZ[0] <= f <= RADAR_BAND_MHZ[1]:
        return "bad", f"WiFi 가 {f} MHz — 레이더(5.8 GHz)와 겹친다. 핫스팟을 2.4 GHz 로 바꾼다"
    if f is not None and f >= 4900:
        return "warn", f"WiFi 가 5 GHz({f} MHz) — 레이더와 가깝다. 핫스팟을 2.4 GHz 로 고정하는 게 안전하다"
    if sig is not None and sig < WIFI_WEAK_DBM:
        return "warn", f"WiFi 신호 약함({sig} dBm) — 패스 중 끊기기 쉽다. 핫스팟을 가까이 · 높이"
    return None


def snapshot(log_dir: str | os.PathLike | None = None) -> dict:
    target = Path(log_dir) if log_dir and Path(log_dir).exists() else Path("/")
    du = shutil.disk_usage(target)
    try:
        load1 = round(os.getloadavg()[0] / (os.cpu_count() or 1), 2)
    except OSError:
        load1 = None
    s = {"cpu_temp_c": _cpu_temp(), "throttled": _throttled(), "load1": load1,
         "disk_free_gb": round(du.free / 1e9, 1), "disk_path": str(target), "time": time.time(),
         "eth": _eth(os.environ.get("SAR_SDR_IFACE")) if os.environ.get("SAR_SDR_HOST") else None,
         "wifi": _wifi()}
    s["level"] = level(s)
    return s


def level(s: dict) -> str:
    """ok · warn · bad — 상태판 칩 색과 패스 시작 점검이 같이 쓴다."""
    t, th, disk = s.get("cpu_temp_c"), s.get("throttled") or {}, s.get("disk_free_gb")
    if (t is not None and t >= TEMP_BAD_C) or th.get("now") or th.get("undervolt") or (disk is not None and disk < DISK_BAD_GB):
        return "bad"
    wp = wifi_problem(s.get("wifi"))
    if wp and wp[0] == "bad":
        return "bad"
    if wp:
        return "warn"
    eth = s.get("eth") or {}
    if eth and (not eth.get("up") or (eth.get("speed_mbps") or 0) < 1000):
        return "warn"                                   # SDR 유선이 끊겼거나 기가비트가 아니다(케이블 · 포트)
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
