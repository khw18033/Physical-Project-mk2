"""`/state` 이중 형식 — 구독표 읽기 · 선택자별 분기 · 지금 형식 보존.

소켓 없이 **가짜 클라이언트**로 실제 `ws_echo._broadcast` · `ws_echo.Gateway.state_session` 을 돌린다
(서버가 떠 있지 않아도 된다 — `test_media_frame.py` 와 같은 결). **음성 대조가 본체다:**

- 🔴 **지금 형식이 안 깨진다** — 구독을 보내지 않는 클라이언트(회귀 시험 `test_pipeline.py`·`console.html`)는
  `{channel, topic, key, message}` 를 그대로 받아야 한다. 이 가지가 깨지면 기존 시험이 같이 죽는다.
- 🔴 **구역 식별자가 어긋나면 0건** — VZ 기본 상수가 `zone-503` 이고 우리 값은 `zoneA` 다.
  실측에서 「연결은 되는데 화면만 빔」의 첫 번째 원인이다.
- **`status` 는 구독자에게 가지 않는다** — VZ `Channel` 어휘에 없다. 비구독자에게는 그대로 간다.

implements: BE-T-03 (가시화 실시간 채널 — 실측대비 최소 어댑터, 실측대비 v2 §3-1-1)
tests: 지금 형식 3 · VZ 형식 6 · 공존 2 · 음성 3 · 구독표 4 · 정리 2
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.gateway import vz_wire, ws_echo

ROBOT = {
    "schema_version": "1.1", "source_id": "go1-001", "entity_id": "go1-001", "node_id": "pi7",
    "zone_id": "zoneA", "timestamp": "2026-09-21T09:00:00+09:00", "sequence_id": 4837,
    "channel": "state", "battery_pct": 87.5,
}
VZ_SEL = {"entity": "*", "node": "zoneA", "channel": "*"}        # VZ src/tabs/data/index.ts:60
VISION_SEL = {"entity": "go1-001", "node": "*", "channel": "*"}  # VZ src/tabs/data/vision.ts:441


def _item(channel: str = "state", message=None):
    """`_consume_loop` 가 만드는 모양 그대로."""
    return {"channel": channel, "topic": "mk2.telemetry." + channel,
            "key": "go1-001", "message": message if message is not None else ROBOT}


def _sub(selector, scope="all"):
    return {"selector": selector, "scope": scope}


class FakeWS:
    """보낸 것을 모아 두는 가짜 소켓. `fail=True` 면 전송이 터진다(정리 경로 시험)."""

    def __init__(self, fail: bool = False) -> None:
        self.sent = []
        self.fail = fail
        self.closed = None

    async def send(self, payload):
        if self.fail:
            raise ConnectionError("closed by peer")
        self.sent.append(json.loads(payload))

    async def close(self, code, reason):
        self.closed = (code, reason)


class FakeIncoming(FakeWS):
    """`state_session` 이 `async for` 로 읽을 제어 메시지 열. 다 읽으면 세션이 끝난다."""

    def __init__(self, msgs=(), on_each=None) -> None:
        super().__init__()
        self._msgs = list(msgs)
        self._on_each = on_each          # 메시지 하나 처리한 **뒤** 불린다(구독표 엿보기용)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._on_each is not None and self._msgs is not None:
            self._on_each()
        if not self._msgs:
            raise StopAsyncIteration
        return self._msgs.pop(0)


def _pump(clients, items):
    """`_broadcast` 를 큐가 빌 때까지 돌리고 멈춘다."""
    async def run():
        queue: asyncio.Queue = asyncio.Queue()
        for it in items:
            queue.put_nowait(it)
        task = asyncio.create_task(ws_echo._broadcast(queue, clients))
        for _ in range(50):                       # 큐가 비고 한 바퀴 더
            await asyncio.sleep(0)
            if queue.empty():
                break
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    asyncio.run(run())


# ── 지금 형식 — 이 가지가 깨지면 기존 회귀 시험이 같이 죽는다 ───────────────

def test_구독을_안_보낸_클라이언트는_지금_형식을_받는다():
    a = FakeWS()
    _pump({a: {}}, [_item()])
    assert len(a.sent) == 1
    got = a.sent[0]
    assert got["channel"] == "state"              # test_pipeline.py 가 단언하는 두 칸
    assert got["message"] == ROBOT
    assert "type" not in got                      # VZ 형식이 새어 나가지 않는다


def test_지금_형식은_토픽과_키도_그대로_싣는다():
    a = FakeWS()
    _pump({a: {}}, [_item()])
    assert a.sent[0]["topic"] == "mk2.telemetry.state"
    assert a.sent[0]["key"] == "go1-001"


def test_지금_형식은_채널을_가리지_않는다():
    """Phase 1 echo 그대로 — `status` 도 간다(VZ 어휘 필터는 구독자에게만 걸린다)."""
    a = FakeWS()
    _pump({a: {}}, [_item("status"), _item("heartbeat")])
    assert [m["channel"] for m in a.sent] == ["status", "heartbeat"]


# ── VZ 형식 ────────────────────────────────────────────────────────────────

def test_구독을_보낸_클라이언트는_data_메시지를_받는다():
    b = FakeWS()
    _pump({b: {"sub-1": _sub(VZ_SEL)}}, [_item()])
    assert len(b.sent) == 1
    m = b.sent[0]
    assert m["type"] == "data"
    assert m["sub"] == "sub-1"                    # VZ 가 붙인 ID 를 그대로 돌려줘야 찾는다
    assert set(m["envelope"]) == {
        "zone", "node", "entity", "channel", "ts", "seq",
        "payload", "quality", "aggregation", "scope", "coordinate_frame",
    }
    assert m["envelope"]["entity"] == "go1-001"
    assert m["envelope"]["payload"] == ROBOT      # 봉투를 통째로 싣는다


def test_구독이_둘_맞으면_둘_다_보낸다():
    """핸들러가 구독마다 따로 있으므로 각각 보낸다."""
    d = FakeWS()
    _pump({d: {"sub-1": _sub(VZ_SEL), "sub-2": _sub(VISION_SEL)}}, [_item()])
    assert len(d.sent) == 2
    assert {m["sub"] for m in d.sent} == {"sub-1", "sub-2"}


def test_구독_범위를_봉투에_되돌려준다():
    d = FakeWS()
    _pump({d: {"sub-1": _sub(VZ_SEL, scope={"zones": ["zoneA"]})}}, [_item()])
    assert d.sent[0]["envelope"]["scope"] == {"zones": ["zoneA"]}


# ── 공존 ───────────────────────────────────────────────────────────────────

def test_두_형식이_한_브로드캐스트에서_공존한다():
    a, b = FakeWS(), FakeWS()
    _pump({a: {}, b: {"sub-1": _sub(VZ_SEL)}}, [_item()])
    assert "type" not in a.sent[0]
    assert b.sent[0]["type"] == "data"


# ── 음성 대조 (본체) ───────────────────────────────────────────────────────

def test_구역_식별자가_어긋나면_아무것도_안_간다():
    """🔴 VZ 기본 상수 `zone-503` ↔ 우리 `zoneA`. 실측에서 첫 번째로 의심할 자리다."""
    c = FakeWS()
    _pump({c: {"sub-1": _sub({"entity": "*", "node": "zone-503", "channel": "*"})}}, [_item()])
    assert c.sent == []


def test_status_는_구독자에게_가지_않는다():
    a, b = FakeWS(), FakeWS()
    _pump({a: {}, b: {"sub-1": _sub(VZ_SEL)}}, [_item("status")])
    assert len(a.sent) == 1        # 비구독자에게는 지금 형식으로 간다
    assert b.sent == []            # 구독자에게는 안 간다(VZ `Channel` 어휘 밖)


def test_깨진_선택자는_전량_푸시로_물러서지_않는다():
    c = FakeWS()
    _pump({c: {"sub-1": _sub("zoneA")}}, [_item()])   # 문자열 선택자
    assert c.sent == []


# ── 정리 ───────────────────────────────────────────────────────────────────

def test_끊긴_클라이언트는_정리되고_나머지는_계속_받는다():
    dead, alive = FakeWS(fail=True), FakeWS()
    clients = {dead: {}, alive: {}}
    _pump(clients, [_item()])
    assert dead not in clients
    assert alive in clients and len(alive.sent) == 1


# ── 구독표 (state_session) ─────────────────────────────────────────────────

def _session(gateway, ws, query=None):
    asyncio.run(ws_echo.Gateway.state_session(gateway, ws, query or {}))


def _bare_gateway(ws_token: str = ""):
    """미디어 계기를 만들지 않는 최소 인스턴스 — `/state` 경로만 본다."""
    g = object.__new__(ws_echo.Gateway)
    g.state_clients = {}
    g.ws_token = ws_token
    return g


def test_구독과_해제가_구독표에_반영된다():
    g = _bare_gateway()
    seen = []
    ws = FakeIncoming(
        [json.dumps({"type": "subscribe", "id": "sub-1", "selector": VZ_SEL, "scope": "all"}),
         json.dumps({"type": "subscribe", "id": "sub-2", "selector": VISION_SEL}),
         json.dumps({"type": "unsubscribe", "id": "sub-1"})],
        on_each=lambda: seen.append(sorted(next(iter(g.state_clients.values()), {}))),
    )
    _session(g, ws)
    # on_each 는 메시지를 꺼내기 **전**에 불리므로 [처리 0건, 1건, 2건, 3건] 의 상태가 찍힌다
    assert seen == [[], ["sub-1"], ["sub-1", "sub-2"], ["sub-2"]]


def test_제어_메시지가_아닌_것은_조용히_버린다():
    """JSON 이 아닌 텍스트·Phase 5/6 메시지(`role`·`video`·`ping`)가 와도 세션이 살아 있어야 한다."""
    g = _bare_gateway()
    ws = FakeIncoming([
        "이건 JSON 이 아니다",
        json.dumps({"type": "video", "entity": "go1-001", "open": True}),
        json.dumps({"type": "role"}),
        json.dumps({"type": "subscribe", "id": "sub-1", "selector": VZ_SEL}),
    ])
    _session(g, ws)
    assert g.state_clients == {}          # 세션이 정상 종료됐다(예외로 끊기지 않았다)


def test_세션이_끝나면_클라이언트가_정리된다():
    g = _bare_gateway()
    _session(g, FakeIncoming([]))
    assert g.state_clients == {}


def test_토큰이_틀리면_4401이고_구독표에_들어가지_않는다():
    g = _bare_gateway(ws_token="SECRET")
    ws = FakeIncoming([])
    _session(g, ws, {"token": "WRONG"})
    assert ws.closed == (4401, "token")
    assert g.state_clients == {}
