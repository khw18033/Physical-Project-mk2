"""구독 상태는 **넷으로 갈린다**, 그리고 못 붙으면 다시 시도한다.

implements: AI-C-05, AI-O-04, AI-O-06
tests: four states stay distinct, unreachable retries and recovers, missing
       dependency stops retrying, live is separate from heard, a dropped link
       keeps what it heard
"""
from __future__ import annotations

import threading
import time

from integration.broker_link import (
    STATE_CONNECTED,
    STATE_DEPENDENCY_MISSING,
    STATE_NOT_REQUESTED,
    STATE_UNREACHABLE,
    BrokerLink,
)


class _Transport:
    def __init__(self, connected: bool = True) -> None:
        self._connected = connected
        self.closed = False

    def is_connected(self) -> bool:
        return self._connected

    def drop(self) -> None:
        self._connected = False

    def close(self) -> None:
        self.closed = True


class _Source:
    def __init__(self) -> None:
        self.observations = {"go1-001": object()}
        self.dropped = {"undecodable": 2}

    def note_for_screen(self) -> str:
        return "장치 공지 1건"

    def declared_interval_s(self, device_id: str):      # noqa: ARG002
        return 5.0


def test_no_broker_is_a_normal_deployment_not_a_failure():
    link = BrokerLink(target=None)
    snap = link.snapshot()
    assert snap["state"] == STATE_NOT_REQUESTED
    assert snap["subscribed"] is False
    assert "선언뿐" in snap["note"]
    # 주지 않았는데 시도 횟수가 쌓이면 안 된다.
    assert snap["attempts"] == 0
    # 들은 것이 없으므로 들은 칸 자체가 없다 — 빈 목록으로 채우지 않는다.
    assert "heard_devices" not in snap


def test_unreachable_does_not_read_as_not_subscribed():
    """이것이 이 모듈이 생긴 이유다 — 둘이 같은 칸에 있었다."""
    link = BrokerLink(target="10.0.0.1:1883", connect=lambda: None,
                      retry_interval_s=0.05)
    assert link.start() is False
    snap = link.snapshot()
    assert snap["state"] == STATE_UNREACHABLE
    assert snap["subscribed"] is False
    assert "붙지 못했다" in snap["note"]
    # **구독하지 않기로 한 것처럼 읽히면 안 된다.**
    assert "선언뿐" not in snap["note"]
    assert snap["attempts"] >= 1
    assert snap["target"] == "10.0.0.1:1883"
    assert snap["retry_interval_s"] == 0.05
    link.close()


def test_the_error_name_survives_so_name_failure_differs_from_refusal():
    def boom():
        raise OSError("Name or service not known")

    link = BrokerLink(target="pi9:1883", connect=boom, retry_interval_s=0.05)
    link.start()
    snap = link.snapshot()
    assert snap["state"] == STATE_UNREACHABLE
    assert "Name or service not known" in snap["last_error"]
    link.close()


def test_a_link_that_failed_once_recovers_when_the_broker_returns():
    """충전하러 내려간 로봇이 돌아오는 것은 예외가 아니다."""
    gate = threading.Event()

    def connect():
        if not gate.is_set():
            return None
        return _Transport(), _Source()

    link = BrokerLink(target="pi7:1883", connect=connect, retry_interval_s=0.05)
    assert link.start() is False
    assert link.state == STATE_UNREACHABLE

    gate.set()                      # 브로커가 돌아왔다
    deadline = time.time() + 5
    while time.time() < deadline and link.state != STATE_CONNECTED:
        time.sleep(0.02)

    assert link.state == STATE_CONNECTED, "돌아온 브로커에 다시 붙지 않았다"
    snap = link.snapshot()
    assert snap["subscribed"] is True
    assert snap["live"] is True
    assert snap["heard_devices"] == ["go1-001"]
    assert snap["connected_since"] is not None
    assert snap["attempts"] >= 2
    # 붙은 뒤에는 실패 사유를 남겨 두지 않는다 — 과거 실패가 현재 상태로 읽힌다.
    assert snap.get("last_error") is None
    link.close()


def test_a_missing_dependency_stops_retrying_and_says_which_one():
    calls = []

    def connect():
        calls.append(1)
        raise ImportError("no paho", name="paho")

    link = BrokerLink(target="pi7:1883", connect=connect, retry_interval_s=0.01)
    assert link.start() is False
    snap = link.snapshot()
    assert snap["state"] == STATE_DEPENDENCY_MISSING
    assert "paho" in snap["note"]
    time.sleep(0.12)
    # 설치되지 않은 것은 다시 시도해도 설치되지 않는다.
    assert len(calls) == 1
    link.close()


def test_live_and_heard_are_different_facts():
    transport, source = _Transport(), _Source()
    link = BrokerLink(target="pi7:1883", connect=lambda: (transport, source))
    assert link.start() is True
    assert link.snapshot()["live"] is True

    transport.drop()                # 링크가 끊겼다
    snap = link.snapshot()
    assert snap["live"] is False
    # 끊겼어도 **들은 것은 사실로 남는다.**
    assert snap["heard_devices"] == ["go1-001"]
    assert snap["dropped"] == {"undecodable": 2}
    assert "끊겨 있다" in snap["note"]
    # 그리고 그것이 "지금 붙어 있다" 로 읽히지 않아야 한다.
    assert "구독 중 (발행하지 않는다)" not in snap["note"]
    link.close()


def test_live_is_none_when_the_transport_cannot_say():
    class _Mute:
        pass

    link = BrokerLink(target="pi7:1883", connect=lambda: (_Mute(), _Source()))
    link.start()
    # 모르는 것은 `None` 이다 — 거짓이 아니다(미측정 ≠ 0 ≠ 미달).
    assert link.snapshot()["live"] is None
    link.close()


def test_a_second_attempt_does_not_reconnect_an_open_link():
    calls = []

    def connect():
        calls.append(1)
        return _Transport(), _Source()

    link = BrokerLink(target="pi7:1883", connect=connect)
    link.start()
    assert link.attempt() is True
    assert len(calls) == 1, "이미 붙어 있는데 다시 붙었다 — 구독이 중복된다"
    link.close()


def test_close_closes_the_transport_and_stops_the_retry_thread():
    transport = _Transport()
    link = BrokerLink(target="pi7:1883", connect=lambda: (transport, _Source()))
    link.start()
    link.close()
    assert transport.closed is True
