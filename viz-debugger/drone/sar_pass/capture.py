"""레이더 캡처 켜기/끄기 — `CAP_ON` 파일 하나.

cansar.service 가 이 파일이 있는 동안 캡처한다. **안 지워지면 계속 캡처된다** — 그래서 지우는 길을
여러 겹으로 둔다.

1. 패스 끝(감속 직전)에 지운다 — 정상 경로.
2. 임무 코드의 `finally` 에서 지운다 — 중단 · RTL · 예외.
3. 프로세스가 내려갈 때 지운다 — `atexit` 과 SIGTERM/SIGINT (systemd stop, Ctrl-C).
4. 켠 채로 너무 오래 있으면 지운다 — 감시 시한(`max_on_s`). 임무 루프가 멎어도 막힌다.

## 레이더의 확인 신호 (CAP_ACK) — cansar 쪽과 맞추는 약속

CAP_ON 은 「켜 달라」는 요청일 뿐이다. 레이더가 **실제로 언제 기록을 시작했는지**는 cansar 만 안다.
cansar 가 파일을 몇 초마다 보느냐에 따라 1 s 늦으면 4 m/s 에서 4 m 가 어긋난다. 그래서 확인 파일을 둔다.

  cansar 가 실제로 기록을 시작하면  →  ACK 파일에 그 순간의 `time.time()` 을 적는다 (한 줄, 소수 초)
  cansar 가 실제로 기록을 멈추면    →  ACK 파일을 지운다

    # cansar 쪽 — 이 두 줄이면 된다
    Path("/home/physical/CAP_ACK").write_text(f"{time.time():.6f}")   # 기록 시작 직후
    Path("/home/physical/CAP_ACK").unlink(missing_ok=True)             # 기록 멈춘 직후

ACK 경로를 안 주면(`ack_path=None`) 확인은 「모름」으로 남고 지금까지와 똑같이 돈다.
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
    def __init__(self, path: Path = DEFAULT_CAP_PATH, install_handlers: bool = True,
                 ack_path: Path | None = None) -> None:
        self.path = Path(path)
        self.ack_path = None if ack_path is None else Path(ack_path)
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

    # ── 레이더 확인 ─────────────────────────────────────────────────────────
    def read_ack(self) -> float | None:
        """레이더가 적은 실제 시작 시각. 파일이 없으면 None. 내용이 숫자가 아니면 파일이 생긴 시각."""
        if self.ack_path is None:
            return None
        try:
            text = self.ack_path.read_text().strip()
        except (FileNotFoundError, OSError):
            return None
        try:
            return float(text)
        except ValueError:
            try:
                return self.ack_path.stat().st_mtime
            except OSError:
                return None

    def clear_stale_ack(self) -> bool:
        """지난 비행이 남긴 ACK 는 지운다 — 남아 있으면 새 패스의 확인으로 잘못 읽힌다."""
        if self.ack_path is not None and self.ack_path.exists():
            try:
                self.ack_path.unlink(missing_ok=True)
                return True
            except OSError:
                pass
        return False

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
