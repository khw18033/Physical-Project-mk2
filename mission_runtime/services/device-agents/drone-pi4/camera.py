"""pi4 카메라 연속 캡처 — rpicam-vid MJPEG 파이프.

implements: AI-C-08, AI-E-01, AI-B-10, AI-C-05

**왜 rpicam-still이 아닌가**(2026-09-21 실측): `rpicam-still` 1장에 **542 ms**가 걸린다.
`-t 1`로 노출 대기를 없애도 558 ms다 — 시간의 대부분이 **프로세스 기동**이라 줄일 수
없다. 프레임마다 프로세스를 띄우는 구조 자체가 틀렸다.

`rpicam-vid --codec mjpeg -o -`는 한 번 띄워 두고 stdout으로 JPEG를 계속 흘린다.
실측: 두 카메라 동시에 각 8 fps(4초에 32프레임), 온도 64.2도.

**항상 최신 프레임만 쓴다.** 파이프에 쌓인 것을 순서대로 처리하면 RPN이 느린 만큼
화면이 뒤처진다. 이 경로는 실시간 감시이므로 오래된 프레임은 가치가 없다 —
버리고 최신 것만 본다(버린 수는 카운터로 드러낸다, AI-O-02).

카메라 부재는 실패가 아니다(AI-C-05) — `available()`이 False면 호출자가 그 카메라만
빼고 계속 간다.
"""

from __future__ import annotations

import subprocess
import threading
import time

SOI = b"\xff\xd8\xff"
EOI = b"\xff\xd9"


class CameraStream:
    """rpicam-vid 하나를 물고 최신 JPEG 프레임을 들고 있는다."""

    def __init__(self, index: int, width: int, height: int, framerate: int,
                 extra_args: list[str] | None = None):
        self.index = index
        self.width, self.height = width, height
        self.framerate = framerate
        self.extra_args = list(extra_args or [])
        self._latest: bytes | None = None
        self._seq = 0
        self._dropped = 0
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        cmd = ["rpicam-vid", "-n", "--camera", str(self.index), "-t", "0",
               "--codec", "mjpeg", "--width", str(self.width),
               "--height", str(self.height), "--framerate", str(self.framerate),
               *self.extra_args, "-o", "-"]
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, bufsize=0)
        except Exception as exc:
            self._error = repr(exc)[:200]
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """MJPEG 파이프에서 SOI~EOI를 잘라 최신 프레임으로 둔다."""
        buf = bytearray()
        assert self._proc and self._proc.stdout
        while not self._stop.is_set():
            chunk = self._proc.stdout.read(65536)
            if not chunk:
                self._error = "stream ended"
                return
            buf += chunk
            # 버퍼에 프레임이 여러 개 쌓였으면 **마지막 것만** 남긴다.
            while True:
                s = buf.find(SOI)
                if s < 0:
                    break
                e = buf.find(EOI, s + 3)
                if e < 0:
                    if s > 0:
                        del buf[:s]        # 앞의 쓰레기는 버린다
                    break
                frame = bytes(buf[s:e + 2])
                del buf[:e + 2]
                with self._lock:
                    if self._latest is not None:
                        self._dropped += 1
                    self._latest = frame
                    self._seq += 1

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()

    # -- 사용 --------------------------------------------------------------
    def available(self) -> bool:
        return self._error is None and self._latest is not None

    def take(self) -> tuple[bytes | None, int]:
        """최신 프레임을 꺼내고 슬롯을 비운다. (jpeg, seq)"""
        with self._lock:
            f, s = self._latest, self._seq
            self._latest = None
            return f, s

    def stats(self) -> dict:
        return {"camera": self.index, "seq": self._seq, "dropped": self._dropped,
                "error": self._error}


def open_cameras(cfg_cams: list[dict]) -> list[CameraStream]:
    """설정에 적힌 카메라를 모두 연다. 하나가 실패해도 나머지로 진행한다(AI-C-05)."""
    out = []
    for c in cfg_cams:
        s = CameraStream(int(c.get("index", 0)), int(c.get("width", 1280)),
                         int(c.get("height", 720)), int(c.get("framerate", 8)),
                         c.get("extra_args"))
        s.start()
        out.append(s)
    # 첫 프레임이 뜰 때까지 잠깐 기다린다 — 없으면 available()이 False로 남는다.
    deadline = time.time() + 6.0
    while time.time() < deadline and not all(s.available() for s in out):
        time.sleep(0.2)
    return out
