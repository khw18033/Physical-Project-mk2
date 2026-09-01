"""Replay sources: CSV/scripted series and video-file frames.

implements: AI-C-04, AI-C-08

Replaces physical sensors and cameras with deterministic, offline data so
identical tests run on any machine. A video file is consumed through the
same `MediaSourceProvider` contract a real RTSP camera would use, so no
consumer can tell them apart (AI-C-08).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


@dataclass(frozen=True)
class Reading:
    """One sensor observation, with the measurement time carried along."""

    name: str
    value: float
    observed_at: float


class ScriptedSeriesSource:
    """Emits a predetermined sequence of readings, then reports exhaustion."""

    def __init__(self, name: str, values: Iterable[float], *, start_at: float = 0.0, step_s: float = 1.0):
        self._name = name
        self._values = list(values)
        self._start_at = start_at
        self._step_s = step_s
        self._index = 0
        self._available = True

    def read(self) -> Reading | None:
        if not self._available or self._index >= len(self._values):
            return None
        reading = Reading(
            name=self._name,
            value=self._values[self._index],
            observed_at=self._start_at + self._index * self._step_s,
        )
        self._index += 1
        return reading

    def readings(self) -> Iterator[Reading]:
        while True:
            reading = self.read()
            if reading is None:
                return
            yield reading

    def is_available(self) -> bool:
        return self._available

    def set_available(self, value: bool) -> None:
        """Test hook: the sensor disappears mid-run."""
        self._available = value


class CsvReplaySource(ScriptedSeriesSource):
    """Same contract, values loaded from a CSV column.

    Used for river water level / rainfall style series where a recorded
    file replaces the physical gauge.
    """

    def __init__(self, path: str | Path, column: str, *, name: str | None = None, step_s: float = 1.0):
        rows = list(csv.DictReader(Path(path).read_text(encoding="utf-8").splitlines()))
        if rows and column not in rows[0]:
            raise KeyError(f"column {column!r} not in {list(rows[0])}")
        super().__init__(name or column, [float(r[column]) for r in rows], step_s=step_s)


class VideoFileMediaSource:
    """MediaSourceProvider reading frames from a video file (AI-C-08).

    The file path, codec and decoder stay hidden here; perception only ever
    sees frames. If the file is missing or OpenCV cannot open it, the
    source reports unavailable rather than raising — an absent video source
    disables only video-based capabilities (AI-C-08, AI-C-11).
    """

    def __init__(self, source_id: str, path: str | Path, *, loop: bool = False) -> None:
        self._source_id = source_id
        self._path = str(path)
        self._loop = loop
        self._capture = None
        self._opened = False

    def _ensure_open(self) -> bool:
        if self._opened:
            return self._capture is not None
        self._opened = True
        try:
            import cv2

            capture = cv2.VideoCapture(self._path)
            self._capture = capture if capture.isOpened() else None
        except Exception:
            self._capture = None
        return self._capture is not None

    def read_frame(self) -> Any | None:
        if not self._ensure_open():
            return None
        ok, frame = self._capture.read()
        if not ok and self._loop:
            try:
                import cv2

                self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._capture.read()
            except Exception:
                return None
        return frame if ok else None

    def is_available(self) -> bool:
        return self._ensure_open()

    def source_id(self) -> str:
        return self._source_id

    def release(self) -> None:
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
        self._capture = None
        self._opened = False


def write_synthetic_video(
    path: str | Path,
    *,
    frames: int = 12,
    size: tuple[int, int] = (160, 120),
    fps: int = 10,
    seed: int = 0,
) -> Path:
    """Generate a small deterministic video file for camera replay tests.

    Used instead of shipping binary fixtures; content is a moving square,
    which is enough for a detector-shaped provider to produce boxes.
    """
    import cv2
    import numpy as np

    path = Path(path)
    width, height = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    rng = np.random.default_rng(seed)
    try:
        for index in range(frames):
            frame = (rng.integers(0, 40, size=(height, width, 3))).astype("uint8")
            x = 10 + (index * 7) % max(1, width - 30)
            y = height // 2
            frame[y - 10 : y + 10, x : x + 20] = 240
            writer.write(frame)
    finally:
        writer.release()
    return path
