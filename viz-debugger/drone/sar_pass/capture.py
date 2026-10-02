"""레이더 캡처 켜기/끄기 — `CAP_ON` 파일 하나.

cansar.service 가 이 파일이 있는 동안 캡처한다. **안 지워지면 계속 캡처된다** — 그래서 지우는 길을
여러 겹으로 둔다.

1. 패스 끝(감속 직전)에 지운다 — 정상 경로.
2. 임무 코드의 `finally` 에서 지운다 — 중단 · RTL · 예외.
3. 프로세스가 내려갈 때 지운다 — `atexit` 과 SIGTERM/SIGINT (systemd stop, Ctrl-C).
4. 켠 채로 너무 오래 있으면 지운다 — 감시 시한(`max_on_s`). 임무 루프가 멎어도 막힌다.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import threading
import time
from pathlib import Path

DEFAULT_CAP_PATH = Path("/home/physical/CAP_ON")  # 절대경로 — root 로 돌아도 같은 파일

log = logging.getLogger("sar_pass.capture")


class CaptureFlag:
    def __init__(self, path: Path = DEFAULT_CAP_PATH, install_handlers: bool = True) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError(f"CAP 경로는 절대경로여야 한다: {self.path}")
        self._lock = threading.Lock()
        self._watchdog: threading.Timer | None = None
        self.on_since: float | None = None
        if install_handlers:
            self._install_handlers()

    # ── 상태 ────────────────────────────────────────────────────────────────
    @property
    def is_on(self) -> bool:
        return self.path.exists()

    # ── 켜기 / 끄기 ─────────────────────────────────────────────────────────
    def on(self, max_on_s: float | None = None) -> None:
        with self._lock:
            self.path.touch()
            self.on_since = time.time()
            self._arm_watchdog(max_on_s)
        log.info("CAP_ON 생성 %s", self.path)

    def off(self, why: str = "") -> bool:
        """지운다. 실제로 있던 것을 지웠으면 True. 몇 번 불러도 안전하다."""
        with self._lock:
            self._cancel_watchdog()
            existed = self.path.exists()
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                log.exception("CAP_ON 삭제 실패 %s", self.path)
                raise
            self.on_since = None
        if existed:
            log.info("CAP_ON 삭제 %s%s", self.path, f" ({why})" if why else "")
        return existed

    # ── 겹겹의 안전장치 ─────────────────────────────────────────────────────
    def _arm_watchdog(self, max_on_s: float | None) -> None:
        self._cancel_watchdog()
        if max_on_s is None or max_on_s <= 0:
            return
        timer = threading.Timer(max_on_s, self._expire)
        timer.daemon = True
        timer.start()
        self._watchdog = timer

    def _cancel_watchdog(self) -> None:
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None

    def _expire(self) -> None:
        log.error("CAP_ON 이 감시 시한을 넘겼다 — 강제로 지운다")
        try:
            self.off("watchdog")
        except OSError:
            pass

    def _install_handlers(self) -> None:
        atexit.register(self._safe_off, "atexit")
        if threading.current_thread() is not threading.main_thread():
            return
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous = signal.getsignal(sig)

            def handler(signum, frame, _previous=previous):  # noqa: ANN001
                self._safe_off(f"signal {signum}")
                if callable(_previous):
                    _previous(signum, frame)
                else:
                    raise SystemExit(128 + signum)

            signal.signal(sig, handler)

    def _safe_off(self, why: str) -> None:
        try:
            self.off(why)
        except Exception:  # noqa: BLE001 — 종료 경로에서는 던지지 않는다
            pass


def ensure_parent(path: Path) -> None:
    os.makedirs(path.parent, exist_ok=True)
