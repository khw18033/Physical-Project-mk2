"""`MediaSourceProvider` for a network video stream (RTSP / RTMP / HTTP-MJPEG).

implements: AI-C-08, AI-C-04, AI-C-05

AI-C-08: 카메라 URL, 장치 경로, codec, 전송 방식은 미디어 어댑터 내부에 숨기고 인지
기능은 공통 영상 입력만 소비해야 한다. This is that adapter for anything that
publishes a stream over the network — an IP camera, a 360 camera's live
stitched output, an MJPEG relay. The vendor is data (the URL and a
`source_id`), never a class name (구현 시 금지 사항: 특정 도메인 전용 클래스를
복제하지 않는다), so the 2026-09-28 hardware contract's `insta360-live-ingest`
provider is *an instance of this class*, not a module of its own.

What it does not do:
- It does not import `cv2` at module import. A node without OpenCV can still
  import this file; `is_available()` says why the source is off (AI-C-05: 선택
  조건 결손은 그 기능만 비활성화).
- It does not decode into any business message. Pixels stay on the media path
  (절대 준수 원칙 #10); `read_frame()` hands the frame to the caller and nothing
  else sees it.
- It does not control the camera. Fixed cameras have no control path
  (2026-09-28 decision) — a stream is read, never commanded.
"""

from __future__ import annotations

import time
from typing import Any, Callable

REASON_NO_URL = "stream_url_missing"
REASON_NO_DECODER = "decoder_unavailable"
REASON_OPEN_FAILED = "stream_open_failed"
REASON_NO_FRAME = "no_frame"


def _cv2():
    import cv2  # noqa: WPS433 — lazy on purpose (AI-C-05)

    return cv2


class NetworkStreamMediaSource:
    """Read frames from a stream URL; open lazily, report failures as data.

    `capture_factory(url)` must return an object with `isOpened()`, `read()`
    -> `(ok, frame)` and `release()` — OpenCV's `VideoCapture` shape. It is
    injectable so tests never open a socket.
    """

    def __init__(
        self,
        url: str,
        *,
        source_id: str,
        capture_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._url = url
        self._source_id = source_id
        self._factory = capture_factory
        self._clock = clock
        self._capture: Any | None = None
        self.last_error: str | None = None
        self.last_frame_at: float | None = None
        self.frames_read = 0

    # -- MediaSourceProvider ------------------------------------------------
    def source_id(self) -> str:
        return self._source_id

    def is_available(self) -> bool:
        """Configured and decodable on this node — not "streaming right now"
        (that is what `probe()` measures)."""
        return self.availability_reason() is None

    def availability_reason(self) -> str | None:
        if not self._url:
            return REASON_NO_URL
        if self._factory is None:
            try:
                _cv2()
            except Exception as error:  # ImportError and any loader failure
                return f"{REASON_NO_DECODER}:{type(error).__name__}"
        return None

    def read_frame(self) -> Any | None:
        if not self._ensure_open():
            return None
        try:
            ok, frame = self._capture.read()
        except Exception as error:
            self.last_error = f"{REASON_NO_FRAME}:{type(error).__name__}"
            self.close()
            return None
        if not ok or frame is None:
            self.last_error = REASON_NO_FRAME
            return None
        self.last_error = None
        self.last_frame_at = self._clock()
        self.frames_read += 1
        return frame

    # -- probing (hw_smoke L3) ---------------------------------------------
    def probe(self, *, timeout_s: float = 5.0, sleep: Callable[[float], None] = time.sleep) -> dict:
        """Try to get one frame within `timeout_s`. Returns a language-neutral
        dict: `{ok, reason, elapsed_s, shape}` — never raises for a dead stream."""
        started = self._clock()
        reason = self.availability_reason()
        if reason is not None:
            return {"ok": False, "reason": reason, "elapsed_s": 0.0, "shape": None}
        while True:
            frame = self.read_frame()
            elapsed = self._clock() - started
            if frame is not None:
                shape = getattr(frame, "shape", None)
                return {"ok": True, "reason": "reachable", "elapsed_s": elapsed,
                        "shape": None if shape is None else list(shape)}
            if elapsed >= timeout_s:
                return {"ok": False, "reason": self.last_error or REASON_NO_FRAME,
                        "elapsed_s": elapsed, "shape": None}
            sleep(0.2)

    def close(self) -> None:
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
            self._capture = None

    # -- internals ----------------------------------------------------------
    def _ensure_open(self) -> bool:
        if self._capture is not None:
            return True
        reason = self.availability_reason()
        if reason is not None:
            self.last_error = reason
            return False
        factory = self._factory or (lambda url: _cv2().VideoCapture(url))
        try:
            capture = factory(self._url)
        except Exception as error:
            self.last_error = f"{REASON_OPEN_FAILED}:{type(error).__name__}"
            return False
        if capture is None or not capture.isOpened():
            self.last_error = REASON_OPEN_FAILED
            return False
        self._capture = capture
        return True
