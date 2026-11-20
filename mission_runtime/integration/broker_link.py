"""우리가 **지금 듣고 있는가**를 소유한다 — 셋을 한 칸에 담지 않고.

implements: AI-C-05, AI-O-04, AI-O-06
tests: tests/test_broker_link.py

## 왜 생겼나 (2026-11-05 실측)

게이트웨이는 `--broker` 를 받아 한 번 붙어 보고, 실패하면 `telemetry=None` 으로
남았다. 그러면 `/registry` 는 이렇게 말한다 —

    {"subscribed": false, "note": "브로커를 구독하지 않는다 — 장치는 선언뿐이다"}

**이것은 거짓이다.** 브로커를 주었고 구독하려 했고 못 붙은 것이지, 구독하지 않기로
한 것이 아니다. 시작 로그는 둘을 구분해 적고 있었는데(`구독 중` / `붙지 못했다`)
화면으로 나가는 칸에서 합쳐졌다 — 로그에만 있는 구분은 운영 중에 없는 구분이다.

그리고 **다시 시도하지 않았다.** 로봇 배터리를 충전하려고 내리면 구역 브로커가
함께 꺼진다(같은 기계에 있다). 돌아왔을 때 게이트웨이는 계속 못 듣는다. 충전은
예외가 아니라 정상 운용이므로, 한 번 실패하고 영구히 귀를 닫는 것은 틀렸다
(AI-C-05 — 선택 결손은 사유와 함께 축소하고, 돌아오면 복구한다).

## 네 상태는 서로 다른 사실이다

    not_requested        브로커를 주지 않았다. 선언만으로 돈다 — 정상 배치다.
    dependency_missing   선택 의존성이 없다(paho 등). 그 조각만 꺼진다.
    unreachable          주었고, 붙으려 했고, **못 붙었다**. 시도 횟수가 남는다.
    connected            붙어서 구독 중이다.

`connected` 와 **지금 이 순간 링크가 살아 있는가**도 다른 사실이다. 한 번 붙은
뒤 끊긴 상태에서도 우리가 들은 것(`heard_devices`)은 사실로 남아야 하고, 그것을
"지금 붙어 있다"로 읽히게 두면 안 된다. 그래서 `live` 를 따로 낸다.

## 하지 않는 것

**발행하지 않는다.** 이 모듈이 여는 전송은 구독 전용이고, 장치 가용성을
재판정하지 않는다(원칙 #15) — 공지는 `Discovery` 가 주인이다. 명령을 낼 수 있는
쪽도 그대로 제어 경계다(AI-C-19).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

#: 브로커를 주지 않았다 — 선언만으로 도는 정상 배치다.
STATE_NOT_REQUESTED = "not_requested"
#: 선택 의존성이 없다. 그 조각만 꺼진다(AI-C-05).
STATE_DEPENDENCY_MISSING = "dependency_missing"
#: 주었고 붙으려 했고 못 붙었다. **구독하지 않기로 한 것과 다르다.**
STATE_UNREACHABLE = "unreachable"
#: 붙어서 구독 중이다.
STATE_CONNECTED = "connected"

#: 다시 붙어 보는 간격. 충전·재부팅이 끝나는 시간대를 생각해 잡은 값이고
#: **측정값이 아니다** — 운영에서 재야 하면 `retry_interval_s` 로 바꾼다.
DEFAULT_RETRY_INTERVAL_S = 15.0


@dataclass
class BrokerLink:
    """브로커 구독의 **상태를 소유하는** 자리. 붙기를 계속 시도한다.

    `connect` 는 성공하면 `(transport, source)` 를, 실패하면 `None` 을 돌려주는
    콜러블이다. 의존성이 없으면 `ImportError` 를 그대로 올리면 된다 — 이 자리가
    `dependency_missing` 으로 받는다. 전송 기술을 여기서 알지 않기 위한 경계다
    (AI-C-04).
    """

    target: str | None
    connect: Callable[[], tuple[Any, Any] | None] | None = None
    retry_interval_s: float = DEFAULT_RETRY_INTERVAL_S
    clock: Callable[[], float] = time.time

    transport: Any | None = field(default=None, init=False)
    source: Any | None = field(default=None, init=False)
    attempts: int = field(default=0, init=False)
    last_attempt_at: float | None = field(default=None, init=False)
    connected_since: float | None = field(default=None, init=False)
    #: 못 붙은 마지막 사유. 예외 이름까지 남긴다 — "못 붙었다" 만으로는
    #: 이름이 안 풀린 것과 거절당한 것을 구분할 수 없다.
    last_error: str | None = field(default=None, init=False)
    _dependency: str | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    # ── 상태 ───────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        if self.target is None or self.connect is None:
            return STATE_NOT_REQUESTED
        if self._dependency is not None:
            return STATE_DEPENDENCY_MISSING
        return STATE_CONNECTED if self.source is not None else STATE_UNREACHABLE

    @property
    def live(self) -> bool | None:
        """**지금** 링크가 살아 있는가. 모르면 `None` — 0 이나 거짓이 아니다.

        한 번도 붙지 않았으면 물을 것이 없고(`None`), 전송이 자기 상태를 말하지
        않으면 역시 모른다. 붙은 적 있고 지금 끊겼으면 `False` 이고, 그때도 우리가
        **들은 것은 사실로 남는다**.
        """
        if self.source is None:
            return None
        probe = getattr(self.transport, "is_connected", None)
        if probe is None:
            return None
        try:
            return bool(probe())
        except Exception:                                       # noqa: BLE001
            return None

    def note(self) -> str:
        """사람이 읽는 한 줄. **상태마다 다른 말을 한다.**"""
        if self.state == STATE_NOT_REQUESTED:
            return "브로커를 주지 않았다 — 장치는 선언뿐이고 신선도가 비어 있다"
        if self.state == STATE_DEPENDENCY_MISSING:
            return f"브로커 구독 불가 — {self._dependency} 없음"
        if self.state == STATE_UNREACHABLE:
            tail = f" — {self.last_error}" if self.last_error else ""
            return (f"브로커 {self.target} 에 붙지 못했다 "
                    f"(시도 {self.attempts}회, {self.retry_interval_s:.0f}초마다 "
                    f"다시 붙어 본다){tail}")
        live = self.live
        if live is False:
            return (f"브로커 {self.target} 구독을 걸었으나 **지금 끊겨 있다** — "
                    "들은 것은 남아 있고 다시 붙으면 이어진다")
        return f"브로커 {self.target} 구독 중 (발행하지 않는다)"

    def snapshot(self) -> dict:
        """화면이 **아무 때나** 물을 수 있는 칸. 네 상태가 각각 보인다."""
        out: dict = {
            "state": self.state,
            # 기존 소비자를 위해 남긴다. `state == connected` 에서 유도되는 값이고
            # 따로 정해지지 않는다 — 한 사실에 주인은 하나다.
            "subscribed": self.state == STATE_CONNECTED,
            "target": self.target,
            "note": self.note(),
            "attempts": self.attempts,
            "last_attempt_at": self.last_attempt_at,
            "connected_since": self.connected_since,
        }
        if self.state == STATE_UNREACHABLE:
            out["last_error"] = self.last_error
            out["retry_interval_s"] = self.retry_interval_s
        if self.source is not None:
            # **지금 붙어 있는가와 들은 것은 다른 사실이다.**
            out["live"] = self.live
            out["heard_devices"] = sorted(getattr(self.source, "observations", {}))
            out["dropped"] = dict(getattr(self.source, "dropped", {}))
            source_note = getattr(self.source, "note_for_screen", None)
            if callable(source_note):
                out["heard_note"] = source_note()
        return out

    # ── 붙기 ───────────────────────────────────────────────────────────────

    def attempt(self) -> bool:
        """한 번 붙어 본다. 이미 붙어 있으면 아무것도 하지 않는다."""
        if self.target is None or self.connect is None:
            return False
        with self._lock:
            if self.source is not None:
                return True
            self.attempts += 1
            self.last_attempt_at = self.clock()
            try:
                result = self.connect()
            except ImportError as error:
                # 선택 의존성 결손은 **그 조각만** 끈다(AI-C-05). 다시 시도해도
                # 설치되지 않으므로 재시도를 멈춘다 — 의미 없는 반복을 하지 않는다.
                self._dependency = error.name or str(error)
                self._stop.set()
                return False
            except Exception as error:                          # noqa: BLE001
                self.last_error = f"{type(error).__name__}: {error}"
                return False
            if result is None:
                # **이번 시도**를 설명해야 한다. 지난 시도의 예외 메시지를 붙들고
                # 있으면 사유가 현재 상태와 어긋난다.
                self.last_error = "연결이 성립하지 않았다"
                return False
            self.transport, self.source = result
            self.connected_since = self.clock()
            self.last_error = None
            return True

    def start(self) -> bool:
        """한 번 시도하고, 실패하면 **뒤에서 계속 시도한다.**

        돌려주는 값은 첫 시도의 성공 여부다. 실패해도 게이트웨이는 그대로 뜬다 —
        선택 기능 결손이 기동을 막아서는 안 된다(AI-C-05).
        """
        ok = self.attempt()
        if ok or self._stop.is_set() or self.target is None:
            return ok
        self._thread = threading.Thread(target=self._retry_loop, daemon=True,
                                        name="broker-link-retry")
        self._thread.start()
        return False

    def _retry_loop(self) -> None:
        while not self._stop.wait(self.retry_interval_s):
            if self.attempt():
                return

    def close(self) -> None:
        self._stop.set()
        transport = self.transport
        if transport is not None:
            closer = getattr(transport, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:                               # noqa: BLE001
                    pass
