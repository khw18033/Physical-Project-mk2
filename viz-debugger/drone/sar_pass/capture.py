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

## CAP_ON 의 내용 (2026-10-04 더함 — 있는지만 보는 쪽은 그대로 동작)

    {"pass": 3, "flight": "flight_1791000000", "line_heading_deg": 45.0, "time": 1791000123.456789}

레이더가 읽어 자기 기록(passes.csv · meta_N.txt)에 `pass` · `flight` 를 같이 적어 주면 드론 쪽 패스와 레이더 캡처를
시각 짐작 없이 정확히 짝지을 수 있다.
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
                 ack_path: Path | None = None, events_root: Path | None = None, now_fn=None) -> None:  # noqa: ANN001
        self.path = Path(path)
        self.ack_path = None if ack_path is None else Path(ack_path)
        # CAP_ACK 가 없을 때의 대신 — 레이더 기록 프로그램(cansar.service)이 기록을 시작 · 멈출 때 쓰는 events.csv
        self.events_root = None if events_root is None else Path(events_root)
        self._ev_cache: tuple[float, float | None] = (-1e18, None)
        self._now = now_fn or time.time                 # 시험(시뮬레이터 시계)에서 바꿔 끼운다
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
    def on(self, max_on_s: float | None = None, info: dict | None = None) -> None:
        """켠다. info(패스 번호 · 비행 이름 등)를 주면 파일 **안에** JSON 한 줄로 적는다 — 레이더는 지금처럼 있는지만 봐도 되고,
        읽으면 자기 기록(passes.csv · meta)에 우리 패스 번호를 같이 남길 수 있다(짝짓기가 정확해진다)."""
        with self._lock:
            now = self._now()
            if info:
                import json
                tmp = self.path.with_name(self.path.name + ".tmp")
                tmp.write_text(json.dumps({**info, "time": round(now, 6)}, ensure_ascii=False) + "\n")
                os.replace(tmp, self.path)              # 생기는 순간 내용이 다 들어 있다
            else:
                self.path.touch()
            self.on_since = now
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
        """레이더가 적은 실제 시작 시각. 파일이 없으면 None. 내용이 숫자가 아니면 파일이 생긴 시각.
        ACK 경로가 없고 events_root 가 있으면 events.csv 의 마지막 start(뒤에 stop 이 없을 때)를 대신 쓴다."""
        if self.ack_path is None:
            return self._ack_from_events()
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

    def _ack_from_events(self) -> float | None:
        """<events_root>/*/events.csv 중 가장 최근 파일의 마지막 start · stop. 0.5 초에 한 번만 읽는다(제어 주기에서 부른다).

        start 가 이번 CAP_ON 보다 2 초 넘게 앞서면 지난 캡처의 것이라 버린다. 우회일 뿐이라 패스 판정에는 쓰지 않고
        (mission 은 ack_path 가 있을 때만 「확인 없음」으로 무효 처리) 레이더 지연을 재 다음 패스를 미리 켜는 데만 쓴다."""
        if self.events_root is None:
            return None
        now = self._now()
        at, val = self._ev_cache
        if now - at < 0.5:
            return val
        val = None
        try:
            files = sorted(self.events_root.glob("*/events.csv"), key=lambda q: q.stat().st_mtime)
            if files:
                last_start, after = None, False
                for line in files[-1].read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
                    parts = line.split(",")
                    if len(parts) >= 2 and parts[0] == "start":
                        last_start, after = float(parts[1]), False
                    elif len(parts) >= 2 and parts[0] == "stop" and last_start is not None:
                        after = True
                if last_start is not None and not after and self.on_since is not None and last_start >= self.on_since - 2.0:
                    val = last_start
        except (OSError, ValueError):
            val = None
        self._ev_cache = (now, val)
        return val

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
