"""Reference on-device unit: a real perception loop under the unit contract.

implements: AI-B-02, AI-B-05, AI-B-10, AI-N-01, AI-C-05

This is the *deployable* side of `providers/ondevice_ssh.py`: the smallest
thing that is still a real function rather than a sleep loop, so that an
end-to-end deploy proves a function runs, not merely that files copied.

It exists to demonstrate three contract points, all of which the control
provider reads back:

1. **Readiness is declared by the unit, not inferred by the supervisor.**
   `PF_READY_FILE` is touched only after the first frame is actually
   processed. A started-but-not-yet-working unit is `ALIVE` + `NOT_READY`,
   which is precisely the distinction AI-B-05 forbids collapsing
   ("프로세스의 시작·liveness·readiness와 실제 장치의 운용 상태·안전 상태를
   구분해야 하며 하나를 다른 상태의 근거로 대체해서는 안 된다").
2. **Optional dependencies degrade the unit, never block it.** Without
   OpenCV the loop keeps running on a pure-numpy gradient and says so in
   `mode`; without numpy it still runs and reports `mode="minimal"`. 특정
   모델·런타임이 없다고 기능이 시작조차 못 하게 만들지 않는다 (구현 시 금지
   사항, AI-C-05).
3. **Local observation stays local.** The unit writes its own heartbeat file
   next to itself. No broker, no collector, no orchestrator agent — the
   controlling side reads state over the same request-scoped SSH it already
   uses (AI-B-10, 절대 준수 원칙 #12).

No domain appears anywhere in here (절대 준수 원칙 #3): the loop detects
regions of change in a frame and counts them. What those regions *mean* is
the edge's business, not the terminal's.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

UNIT_DIR = Path(os.environ.get("PF_UNIT_DIR", ".")).expanduser()
UNIT_ID = os.environ.get("PF_UNIT_ID", "unnamed")
READY_FILE = Path(os.environ.get("PF_READY_FILE", UNIT_DIR / "run" / "ready"))
HEARTBEAT_FILE = UNIT_DIR / "run" / "heartbeat.json"

_running = True


def _stop(signum, frame):  # noqa: ARG001 - signal handler signature
    global _running
    _running = False


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def load_config() -> dict:
    """Config travels *inside* the artifact, so version == code + config.

    A missing/corrupt config falls back to defaults rather than refusing to
    start: the unit's job is to keep the terminal's local function alive
    (AI-N-01).
    """
    defaults = {
        "unit_kind": "perception.edge_proposal",
        "target_hz": 5.0,
        "frame_width": 640,
        "frame_height": 480,
        "canny_low": 60,
        "canny_high": 160,
        "min_area_px": 120,
        "heartbeat_every_n": 25,
    }
    try:
        defaults.update(json.loads((Path(__file__).parent / "unit.config.json").read_text()))
    except Exception:
        pass
    return defaults


def read_device_state() -> dict:
    """Thermal/throttle state as seen from inside the unit.

    Reported alongside the unit's own numbers because a silently
    frequency-capped board looks like a slow model unless the two are read
    together — but they stay separate *fields*, never one verdict (AI-B-05).
    """
    state: dict = {"temperature_c": None, "throttled": None}
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        state["temperature_c"] = round(int(raw) / 1000.0, 1)
    except Exception:
        pass
    try:
        import subprocess

        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and "=" in out.stdout:
            state["throttled"] = out.stdout.strip().split("=", 1)[1]
    except Exception:
        pass
    return state


def build_pipeline(config: dict):
    """Pick the best available implementation. Returns `(mode, step_fn)`."""
    width, height = int(config["frame_width"]), int(config["frame_height"])

    try:
        import cv2
        import numpy as np

        def step(tick: int) -> int:
            frame = np.zeros((height, width), dtype=np.uint8)
            # A moving bright block: deterministic input, real pixel work.
            x = (tick * 7) % max(width - 80, 1)
            y = (tick * 3) % max(height - 80, 1)
            frame[y:y + 80, x:x + 80] = 255
            frame[100:140, 300:360] = 200
            edges = cv2.Canny(frame, int(config["canny_low"]), int(config["canny_high"]))
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            return sum(1 for c in contours if cv2.contourArea(c) >= float(config["min_area_px"]))

        return f"opencv:{cv2.__version__}", step
    except Exception:
        pass

    try:
        import numpy as np

        def step(tick: int) -> int:
            frame = np.zeros((height, width), dtype=np.uint8)
            x = (tick * 7) % max(width - 80, 1)
            frame[40:120, x:x + 80] = 255
            gradient = np.abs(np.diff(frame.astype(np.int16), axis=1))
            return int((gradient > 50).sum() > 0)

        return f"numpy:{np.__version__}", step
    except Exception:
        pass

    def step(tick: int) -> int:  # pure-stdlib floor: still a running unit
        return 1 if (tick // 5) % 2 == 0 else 0

    return "minimal", step


def main() -> int:
    config = load_config()
    mode, step = build_pipeline(config)
    period = 1.0 / max(float(config["target_hz"]), 0.1)
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)

    tick = 0
    processed = 0
    latencies: list[float] = []
    started_at = time.time()

    while _running:
        loop_start = time.perf_counter()
        try:
            regions = step(tick)
            processed += 1
        except Exception as error:  # one bad frame is not a dead unit
            regions = -1
            print(f"[{UNIT_ID}] frame error: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        latencies.append((time.perf_counter() - loop_start) * 1000.0)
        latencies = latencies[-200:]

        if processed == 1:
            # Readiness only after real work completed once.
            READY_FILE.parent.mkdir(parents=True, exist_ok=True)
            READY_FILE.touch()
            print(f"[{UNIT_ID}] ready, mode={mode}", flush=True)

        if tick % int(config["heartbeat_every_n"]) == 0:
            ordered = sorted(latencies)
            payload = {
                "unit_id": UNIT_ID,
                "unit_kind": config["unit_kind"],
                "mode": mode,
                "pid": os.getpid(),
                "uptime_s": round(time.time() - started_at, 1),
                "frames_processed": processed,
                "regions_last": regions,
                "latency_ms_p50": round(ordered[len(ordered) // 2], 2) if ordered else None,
                "latency_ms_p95": round(ordered[int(len(ordered) * 0.95) - 1], 2) if len(ordered) > 1 else None,
                "target_hz": config["target_hz"],
                "device": read_device_state(),
                "at": time.time(),
            }
            tmp = HEARTBEAT_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(HEARTBEAT_FILE)  # atomic: a reader never sees half a file

        tick += 1
        slack = period - (time.perf_counter() - loop_start)
        if slack > 0:
            time.sleep(slack)

    try:
        READY_FILE.unlink()
    except OSError:
        pass
    print(f"[{UNIT_ID}] stopped after {processed} frames", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
