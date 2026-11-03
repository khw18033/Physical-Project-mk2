"""implements: AI-C-08, AI-C-04, AI-C-05

`providers/network_stream_media.py` hides URL/transport/codec behind
`MediaSourceProvider`; vendors are data. No socket is opened here — the
capture is injected.
"""
from mission_runtime.providers.adapters import MediaSourceProvider
from mission_runtime.providers.network_stream_media import (
    REASON_NO_FRAME, REASON_NO_URL, REASON_OPEN_FAILED, NetworkStreamMediaSource,
)


class FakeCapture:
    def __init__(self, frames, opened=True):
        self._frames = list(frames); self._opened = opened; self.released = False
    def isOpened(self): return self._opened
    def read(self):
        if not self._frames: return False, None
        f = self._frames.pop(0); return (f is not None), f
    def release(self): self.released = True


class Frame:
    shape = (1920, 3840, 3)


def test_satisfies_the_media_source_protocol_and_reads_lazily():
    opened = []
    src = NetworkStreamMediaSource("rtsp://cam/live", source_id="insta360-pro2",
                                   capture_factory=lambda url: opened.append(url) or FakeCapture([Frame(), Frame()]))
    assert isinstance(src, MediaSourceProvider)
    assert src.is_available() and opened == []          # available != opened
    assert src.read_frame() is not None and opened == ["rtsp://cam/live"]
    assert src.frames_read == 1 and src.last_error is None


def test_missing_url_is_unavailable_with_a_reason_not_an_exception():
    src = NetworkStreamMediaSource("", source_id="x", capture_factory=lambda u: FakeCapture([]))
    assert not src.is_available() and src.availability_reason() == REASON_NO_URL
    assert src.read_frame() is None and src.last_error == REASON_NO_URL


def test_open_failure_and_dead_stream_are_reported_as_data():
    src = NetworkStreamMediaSource("rtsp://x", source_id="x", capture_factory=lambda u: FakeCapture([], opened=False))
    assert src.read_frame() is None and src.last_error == REASON_OPEN_FAILED

    dead = NetworkStreamMediaSource("rtsp://x", source_id="x", capture_factory=lambda u: FakeCapture([None]))
    assert dead.read_frame() is None and dead.last_error == REASON_NO_FRAME


def test_probe_returns_first_keyframe_or_times_out():
    t = [0.0]
    clock = lambda: t[0]
    def sleep(s): t[0] += s
    ok_src = NetworkStreamMediaSource("rtsp://x", source_id="x",
                                      capture_factory=lambda u: FakeCapture([None, None, Frame()]), clock=clock)
    result = ok_src.probe(timeout_s=5.0, sleep=sleep)
    assert result["ok"] and result["shape"] == [1920, 3840, 3] and result["reason"] == "reachable"

    t[0] = 0.0
    dead = NetworkStreamMediaSource("rtsp://x", source_id="x", capture_factory=lambda u: FakeCapture([]), clock=clock)
    result = dead.probe(timeout_s=1.0, sleep=sleep)
    assert not result["ok"] and result["reason"] == REASON_NO_FRAME and result["elapsed_s"] >= 1.0


def test_close_releases_the_capture():
    cap = FakeCapture([Frame()])
    src = NetworkStreamMediaSource("rtsp://x", source_id="x", capture_factory=lambda u: cap)
    src.read_frame(); src.close()
    assert cap.released


def test_module_has_no_top_level_opencv_dependency():
    import inspect
    import mission_runtime.providers.network_stream_media as m
    top_level = [l for l in inspect.getsource(m).splitlines() if l.startswith("import ") or l.startswith("from ")]
    assert not any("cv2" in l for l in top_level)   # decoder is imported lazily inside functions only
    assert "cv2" not in vars(m)
