"""Resource sampling on the node actually running the work.

implements: AI-O-01, AI-C-05

Memory, CPU and where available power are read from the running process and
node rather than estimated, because the point of collecting on the target
device is that its numbers differ from a workstation's.

Sampling is optional and self-isolating: if a counter cannot be read on this
platform it is omitted, and a sampler failure never propagates to the work
being measured.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

try:                                    # optional; absent on minimal nodes
    import psutil
except Exception:                       # pragma: no cover - platform dependent
    psutil = None

#: Energy counters exposed by Linux power capping, when the kernel offers them.
_POWERCAP = Path("/sys/class/powercap")


@dataclass
class ResourceSample:
    sampled_at: float
    rss_mib: float | None = None
    cpu_percent: float | None = None
    energy_uj: int | None = None
    temperature_c: float | None = None

    def as_payload(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ResourceSampler:
    """Periodically records what this node can actually measure."""

    interval: float = 1.0
    samples: list[ResourceSample] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _process: object | None = None

    def __post_init__(self) -> None:
        if psutil is not None:
            try:
                self._process = psutil.Process(os.getpid())
            except Exception:
                self._process = None

    # -- reading ---------------------------------------------------------

    def read(self) -> ResourceSample:
        sample = ResourceSample(sampled_at=time.time())
        if self._process is not None:
            try:
                sample.rss_mib = self._process.memory_info().rss / (1024 * 1024)
                sample.cpu_percent = self._process.cpu_percent(interval=None)
            except Exception:
                self._process = None
        sample.energy_uj = self._read_energy()
        sample.temperature_c = self._read_temperature()
        return sample

    def _read_energy(self) -> int | None:
        try:
            for entry in _POWERCAP.glob("*/energy_uj"):
                return int(entry.read_text().strip())
        except Exception:
            pass
        return None

    def _read_temperature(self) -> float | None:
        try:
            for entry in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
                return int(entry.read_text().strip()) / 1000.0
        except Exception:
            pass
        return None

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="resource-sampler")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.samples.append(self.read())
            except Exception:
                return                  # stop sampling, never disturb the work

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> "ResourceSampler":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- read-out --------------------------------------------------------

    def peak_rss_mib(self) -> float | None:
        values = [s.rss_mib for s in self.samples if s.rss_mib is not None]
        return max(values) if values else None

    def energy_consumed_uj(self) -> int | None:
        values = [s.energy_uj for s in self.samples if s.energy_uj is not None]
        # Counters wrap; a negative delta means the window is unusable.
        return values[-1] - values[0] if len(values) >= 2 and values[-1] >= values[0] else None
