"""WS 게이트웨이 — 상태 push(`/state`) + 미디어 중계(`/media` 뷰어 분기 · `/ingest` 엣지 입구).

파일명·유닛명(`mk2-ws-echo`)은 Phase 1 그대로다(범위 확대 금지 — 단계 §6-16). 하는 일은 셋이다:

1. **`/state`(8765)** — Kafka 3토픽(컨슈머 그룹 `mk2-ws`, 저장 그룹과 오프셋 독립)을 붙은 클라이언트에
   내보낸다. **이중 형식이다**(2026-09-21, 실측대비 v2 §3-1-1 — 실측대비를 위한 임시 구현):
     · 구독을 **안 보낸** 클라이언트(회귀 시험·`console.html`·스크립트 뷰어) → `{channel, topic, key, message}`
       **Phase 1 echo 그대로.**
     · 구독을 **보낸** 클라이언트(VZ 앱) → `{type:"data", sub, envelope}`. `sub` 가 VZ 가 붙인 ID 라
       구독 메시지를 읽어야만 만들 수 있다 — 변환은 `vz_wire.py`, 구독표는 `state_session`.
   **재접속 캐시(VZ-I-02)·`hello`·명령 번역은 여전히 Phase 5/7** 이다. 지금 형식 가지를 지우면 정식이 된다.
   루트 경로 `/`는 `/state`로 취급한다(Phase 1 호환).
2. **`/media?source_id=…`(8765)** — 뷰어 영상. 붙는 것이 켜기, 끊는 것이 끄기(결정 4-b — 제어 메시지 없음).
   소켓 하나당 소스 하나. 뷰어 소켓마다 **송신 큐 + 전용 writer 태스크**를 둔다 — 중계 코어(`media.py`)는
   `send`를 부르지 않고 큐에 넣을지 버릴지만 판단하고, writer 가 `await send()`로 한 장씩 비운다. 느린
   뷰어 하나가 이벤트 루프도 다른 뷰어도 막지 않는다(§1-5-2 head-of-line, 음성 대조 M7).
3. **`/ingest?source_id=…`(8766, 별도 서버·같은 프로세스)** — 엣지가 클라이언트로 붙어 방식 B 를 올린다.
   헤더만 검증(필수·타입)하고 그 `source_id`를 구독 중인 `/media` 소켓에 분기한다. **엣지 입구에서는
   버리지 않는다.** 같은 `source_id`로 둘이 붙으면 나중 것을 close 4409 로 거부한다.
   `MK2_MEDIA_INGEST_PORT=0`이면 열지 않는다(단계 8 되돌림이 이 한 줄).

**인증** — URL 쿼리 토큰(`MK2_WS_TOKEN` / `MK2_EDGE_TOKEN`), `hmac.compare_digest`. 불일치·부재는 close **4401**.
loopback 바인딩이면 토큰 없이 열고(로그 한 줄), loopback 이 아닌데 토큰이 비어 있으면 **기동 시점에 죽는다**
(`settings.require_token()`). 토큰이 로그에 남지 않게 경로를 찍을 때 `token=` 값을 마스킹하고, `websockets`
로거는 WARNING 으로 고정한다(요청 줄은 DEBUG 에서만 찍히지만 기대지 않는다).

**경로·쿼리는 `websocket.request.path`에서 읽는다.** websockets 14+ 의 asyncio 구현은 핸들러를 인자 1개로
부르므로 `path` 인자는 항상 `None`이다(`_request_path()` — 13 이하에서만 두 번째 인자로 물러선다).

**소켓 옵션 셋을 기본값에 맡기지 않는다**(서버 설치본 17.1 실측: `max_size` 1MB · `write_limit` 32KB ·
`compression` deflate). `compression=None`(이미 압축된 JPEG/H.264 를 다시 압축하지 않는다 — `/state` JSON 은
작아 손해가 없다) · 8766 `max_size` = 2 × `MK2_MEDIA_MAX_FRAME_BYTES`(라이브러리 백스톱)이고 **우리 상한
판정은 코드에서** — 넘는 프레임은 연결을 끊지 않고 프레임만 버리고 기록한다(음성 대조 M9) ·
`write_limit`은 `process_request`에서 **경로별로** 준다 — `/media`·`/ingest` = `MK2_MEDIA_WRITE_LIMIT`(8KB),
`/state` = 32KB. 그리고 **`/media` 소켓의 커널 송신 버퍼를 `MK2_MEDIA_SNDBUF`(실효 128KB)로 못 박는다** — 자동조정을
두면 최대 4MB 가 회계 밖에 쌓여 링크가 멈춰도 drop-old 가 발동하지 않는다(사용자 결정 A, 2026-09-19).
지연 바운드 = **`T_drop + write_limit + sndbuf`**.

A층 계측(전부 `be.gateway.*`, 라벨에 `source_id`·`frame_ref`·시각 없음): `push{channel}` · `clients{endpoint}` ·
`media_ingress` · `media_rejected{stage}` · `media_frames{outcome}` · `media_gop_cut` · `media_coldstart`(히스토그램).
라벨 이름을 `channel`로 쓰지 않는다 — `be.gateway.push`의 `channel`은 업무 채널 뜻이다.

implements: BE-T-03, BE-T-02, BE-T-07(미디어 중계·drop-old·토큰), BE-S-02(A층 — be.gateway.*)
tests: tests/test_vz_wire.py — 계약 축 매칭·봉투 변환·구독표(소켓 없이) ·
       tests/test_pipeline.py — 발행값이 /state 클라이언트에 도달(팬아웃 ②) ·
       tests/test_observability_pipeline.py — be_gateway_push_total·be_gateway_clients 도달 ·
       tests/test_media_relay.py — 송신 fixture → /ingest → /media 도착 · 토큰 4401 · frame_ref 바이트 동일 · 느린 뷰어 드롭
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import re
import signal
import socket
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from confluent_kafka import Consumer, KafkaError

# websockets 13에서 새 asyncio 구현이 들어왔고 14부터 그것이 기본이다. 최상위 별칭
# (`websockets.serve`)은 버전에 따라 legacy/신 구현을 오가므로, 구현 모듈을 직접 가리켜
# 버전 간 흔들림을 없앤다. 13 미만으로 내려갈 때만 최상위 별칭으로 물러선다.
try:
    from websockets.asyncio.server import serve as ws_serve
except ImportError:  # pragma: no cover — websockets 12 이하
    from websockets import serve as ws_serve  # type: ignore[attr-defined]

from backend import observability as obs
from backend import settings
from backend.gateway import media, vz_wire

LOG = logging.getLogger("mk2.gateway")

CONSUMER_GROUP = "mk2-ws"
COMPONENT = "gateway"

# close 코드 — 4000번대는 애플리케이션 정의(RFC 6455 §7.4.2)
CLOSE_UNAUTHORIZED = 4401
CLOSE_BAD_REQUEST = 4400
CLOSE_NOT_FOUND = 4404
CLOSE_CONFLICT = 4409

STATE_WRITE_LIMIT = 32 * 1024   # `/state` 는 라이브러리 기본값 그대로(작은 JSON)

_TOKEN_RE = re.compile(r"(token=)[^&\s]*")


def mask_token(path: str) -> str:
    """접속 로그에 경로를 남길 때 `token=` 값을 가린다 — journalctl·Loki 에 토큰이 평문으로 쌓이지 않게."""
    return _TOKEN_RE.sub(r"\1***", path)


def _request_path(websocket: Any, path_arg: Optional[str]) -> str:
    """websockets 14+ 는 `websocket.request.path`(쿼리 포함), 13 이하는 핸들러 두 번째 인자."""
    request = getattr(websocket, "request", None)
    path = getattr(request, "path", None) if request is not None else None
    return path or path_arg or "/"


def split_route(path: str):
    """`/media?source_id=x&token=y` → (`/media`, {"source_id": "x", "token": "y"}). 값은 첫 항목만."""
    parts = urlsplit(path)
    query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
    route = parts.path or "/"
    return route, query


def token_matches(given: Optional[str], expected: str) -> bool:
    """`expected`가 비어 있으면(= loopback 전용 기동) 검사하지 않는다. 있으면 상수 시간 비교, 부재는 실패."""
    if not expected:
        return True
    if not given:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def build_consumer(group_id: str = CONSUMER_GROUP) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap(),
            "group.id": group_id,
            # 화면은 실시간 push라 최신부터 읽는다(저장 그룹과 정책이 다르며, 오프셋도 독립).
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }
    )


def _consume_loop(loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue[Dict[str, Any]]", stop: threading.Event,
                  group_id: str) -> None:
    consumer = build_consumer(group_id)
    topics = settings.telemetry_topics()
    consumer.subscribe(topics)
    LOG.info("WS Kafka 소비 시작: group=%s topics=%s", group_id, topics)
    try:
        while not stop.is_set():
            msg = consumer.poll(0.5)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                LOG.error("Kafka 소비 오류: %s", msg.error())
                continue
            try:
                message = json.loads(msg.value().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                LOG.error("토픽 %s의 메시지를 해석하지 못했다: %s", msg.topic(), exc)
                continue
            envelope = {
                "channel": msg.topic().rsplit(".", 1)[-1],
                "topic": msg.topic(),
                "key": msg.key().decode("utf-8") if msg.key() else None,
                "message": message,
            }
            loop.call_soon_threadsafe(queue.put_nowait, envelope)
    finally:
        consumer.close()
        LOG.info("WS Kafka 소비 종료")


async def _broadcast(queue: "asyncio.Queue[Dict[str, Any]]",
                     clients: Dict[Any, Dict[str, Dict[str, Any]]]) -> None:
    """`/state` 로 내보낸다 — **이중 형식**(실측대비 v2 §3-1-1 (c)).

    - 구독표가 **빈** 클라이언트 → `{channel, topic, key, message}` **지금 형식 그대로**(Phase 1 echo).
      회귀 시험(`test_pipeline.py` 가 `channel`·`message` 두 칸을 단언한다)과 `console.html` 이 그 가지다.
    - 구독표가 **찬** 클라이언트(VZ 앱) → `{type:"data", sub, envelope}`. 선택자에 맞는 구독마다 한 번씩.

    ⚠ **직렬화가 클라이언트별이 됐다.** 전에는 한 번 만든 문자열을 전원에게 보냈는데 `sub` id 가 달라
    구독한 클라이언트마다 따로 만든다. `/state` 클라이언트가 관제 화면 한둘이면 문제 없지만 알고 바꾼다.

    계측은 **메시지 1건 × 클라이언트 1명 = 1** 이다 — 구독 둘이 맞아 두 번 보내도 1 로 센다(Phase 1 의 뜻 유지).
    """
    while True:
        item = await queue.get()
        if not clients:
            continue
        channel = item["channel"]
        message = item.get("message") or {}
        raw_payload = None            # 지금 형식은 한 번만 만든다(구독 없는 클라이언트가 여럿이어도)
        for client, subs in list(clients.items()):
            try:
                if not subs:
                    if raw_payload is None:
                        raw_payload = json.dumps(item, ensure_ascii=False)
                    await client.send(raw_payload)
                else:
                    sent = False
                    for sub_id, sub in list(subs.items()):
                        if not vz_wire.selector_matches(sub["selector"], message, channel):
                            continue
                        await client.send(json.dumps(
                            vz_wire.data_message(sub_id, channel, message, sub["scope"]), ensure_ascii=False))
                        sent = True
                    if not sent:
                        continue      # 이 클라이언트의 구독 어디에도 안 맞는다 — 계측하지 않는다
            except Exception as exc:  # 끊긴 클라이언트는 조용히 정리한다
                LOG.info("클라이언트 전송 실패(정리): %s", exc)
                clients.pop(client, None)
                continue
            obs.count("be.gateway.push", component=COMPONENT, channel=channel)


class _ViewerConn:
    """뷰어 소켓 하나 = 슬롯(큐·회계·상태 기계, `media.py`) + 깨우기 이벤트 + writer 태스크."""

    def __init__(self, websocket: Any, slot: media.ViewerSlot) -> None:
        self.websocket = websocket
        self.slot = slot
        self.wake = asyncio.Event()
        self.task: Optional[asyncio.Task] = None

    async def writer(self) -> None:
        """큐를 한 장씩 비운다. `send`가 막히면 이 태스크만 막힌다 — 중계 코어·다른 뷰어·`/state`는 계속 돈다."""
        slot = self.slot
        while not slot.closed:
            self.wake.clear()                  # take() 전에 지운다 — append→set 이 그 사이 끼어도 깨움을 잃지 않는다
            blob = slot.take(time.monotonic())
            if blob is None:
                await self.wake.wait()
                continue
            await self.websocket.send(blob)   # 재직렬화 없음 — 엣지가 보낸 바이트 그대로(frame_ref 무개정)
            coldstart = slot.on_drained(len(blob), time.monotonic())
            obs.count("be.gateway.media_frames", component=COMPONENT, outcome="sent")
            if coldstart is not None:
                obs.observe("be.gateway.media_coldstart", coldstart, component=COMPONENT, outcome="ok")


class Gateway:
    """한 프로세스의 게이트웨이 상태 — `/state` 클라이언트 **구독표** + 미디어 라우팅(`media.Relay`)."""

    def __init__(self) -> None:
        # 소켓 → 구독표 `{sub_id: {selector, scope}}`. Phase 1 은 집합이었는데 구독을 읽기 시작하면서
        # 사전이 됐다(실측대비 v2 §3-1-1 (a)). **구독표가 빈 클라이언트는 지금 형식 그대로 받는다** —
        # 회귀 시험·확인용 뷰어가 그 가지로 간다(`_broadcast` 의 이중 형식).
        self.state_clients: Dict[Any, Dict[str, Dict[str, Any]]] = {}
        self.relay = media.Relay(media.DropOldConfig(
            drop_window_s=settings.media_drop_window_s(),
            buffer_max_bytes=settings.media_buffer_max_bytes(),
        ))
        self.viewers: Dict[media.ViewerSlot, _ViewerConn] = {}
        self.ws_token = settings.ws_token()
        self.edge_token = settings.edge_token()
        self.max_frame_bytes = settings.media_max_frame_bytes()
        # 헤더 검증기(+$ref 레지스트리)는 기동 시 미리 만든다 — 첫 프레임에서 만들면 그 100ms 남짓 동안
        # 프레임이 소켓에 쌓였다가 한꺼번에 처리되어 뷰어 회계가 「비울 기회 없이」 찬 것으로 보인다(2026-09-19 실측).
        self.header_validator = media.header_validator()

    # ── 공통 ────────────────────────────────────────────────────────────────

    async def _reject(self, websocket: Any, code: int, reason: str, *, endpoint: str, stage: Optional[str] = None) -> None:
        LOG.info("접속 거부(%s): %s — %s", endpoint, code, reason)
        if stage is not None:
            obs.count("be.gateway.media_rejected", component=COMPONENT, stage=stage)
        await websocket.close(code, reason)

    # ── /state ──────────────────────────────────────────────────────────────

    async def state_session(self, websocket: Any, query: Dict[str, str]) -> None:
        if not token_matches(query.get("token"), self.ws_token):
            await self._reject(websocket, CLOSE_UNAUTHORIZED, "token", endpoint="state")
            return
        subs: Dict[str, Dict[str, Any]] = {}
        self.state_clients[websocket] = subs
        obs.updown("be.gateway.clients", +1, component=COMPONENT, endpoint="state")
        LOG.info("/state 접속 (현재 %s명)", len(self.state_clients))
        try:
            # 구독 메시지를 읽는다(실측대비 v2 §3-1-1 (b)). Phase 1 은 받은 것을 버렸는데, VZ 가
            # `case 'data'` 에서 **자기가 붙인 구독 ID** 로 찾으므로 그 ID 를 알아야 한다.
            # 구독을 보내지 않는 클라이언트는 구독표가 빈 채로 남아 `_broadcast` 가 지금 형식으로 보낸다.
            # ⚠ 토큰·인증은 접속 시점에 이미 끝났다 — 여기서 다시 보지 않는다.
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue           # 제어 메시지가 아니면 조용히 버린다(Phase 1 동작 그대로)
                kind = vz_wire.apply_subscription(subs, msg)
                if kind is not None:
                    LOG.info("/state %s id=%s (구독 %s건)", kind, msg.get("id"), len(subs))
        except Exception as exc:
            LOG.info("/state 연결 종료(사유: %s)", exc)
        finally:
            self.state_clients.pop(websocket, None)
            obs.updown("be.gateway.clients", -1, component=COMPONENT, endpoint="state")
            LOG.info("/state 종료 (현재 %s명)", len(self.state_clients))

    # ── /media ──────────────────────────────────────────────────────────────

    async def media_session(self, websocket: Any, query: Dict[str, str]) -> None:
        if not token_matches(query.get("token"), self.ws_token):
            await self._reject(websocket, CLOSE_UNAUTHORIZED, "token", endpoint="media", stage="auth")
            return
        source_id = (query.get("source_id") or "").strip()
        if not source_id:
            await self._reject(websocket, CLOSE_BAD_REQUEST, "source_id required", endpoint="media", stage="auth")
            return
        slot = self.relay.subscribe(source_id)      # 붙는 것이 켜기. WAIT_IDR 로 시작 — 첫 전송은 반드시 keyframe
        conn = _ViewerConn(websocket, slot)
        self.viewers[slot] = conn
        conn.task = asyncio.create_task(conn.writer())
        obs.updown("be.gateway.clients", +1, component=COMPONENT, endpoint="media")
        LOG.info("/media 접속 source_id=%s (이 소스 뷰어 %s명)", source_id, self.relay.viewer_count(source_id))
        try:
            async for _ in websocket:      # 뷰어가 보내는 것은 없다(제어 메시지 없음)
                pass
        except Exception as exc:
            LOG.info("/media 연결 종료(사유: %s)", exc)
        finally:
            self.relay.unsubscribe(slot)   # 끊는 것이 끄기
            self.viewers.pop(slot, None)
            if conn.task is not None:
                conn.task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await conn.task
            obs.updown("be.gateway.clients", -1, component=COMPONENT, endpoint="media")
            LOG.info("/media 종료 source_id=%s %s", source_id, slot.summary())

    # ── /ingest ─────────────────────────────────────────────────────────────

    async def ingest_session(self, websocket: Any, query: Dict[str, str]) -> None:
        if not token_matches(query.get("token"), self.edge_token):
            await self._reject(websocket, CLOSE_UNAUTHORIZED, "token", endpoint="ingest", stage="auth")
            return
        source_id = (query.get("source_id") or "").strip()
        if not source_id:
            await self._reject(websocket, CLOSE_BAD_REQUEST, "source_id required", endpoint="ingest", stage="auth")
            return
        if not self.relay.claim_ingest(source_id, websocket):
            await self._reject(websocket, CLOSE_CONFLICT, "source_id already ingesting", endpoint="ingest", stage="auth")
            return
        obs.updown("be.gateway.clients", +1, component=COMPONENT, endpoint="ingest")
        LOG.info("/ingest 접속 source_id=%s", source_id)
        received = 0
        try:
            async for blob in websocket:
                received += 1
                if isinstance(blob, str):
                    obs.count("be.gateway.media_rejected", component=COMPONENT, stage="header")
                    LOG.info("/ingest source_id=%s 텍스트 프레임 거부(기록만)", source_id)
                    continue
                if len(blob) > self.max_frame_bytes:
                    # 연결을 끊지 않는다 — 프레임만 버리고 기록(순번 불연속과 같은 취급, M9)
                    obs.count("be.gateway.media_rejected", component=COMPONENT, stage="header")
                    LOG.info("/ingest source_id=%s 과대 프레임 %s바이트 > %s 버림(연결 유지)", source_id, len(blob), self.max_frame_bytes)
                    continue
                try:
                    frame = media.decode_frame(blob, validator=self.header_validator)
                    self.relay.check_source(source_id, frame)
                except media.FrameRejected as exc:
                    obs.count("be.gateway.media_rejected", component=COMPONENT, stage=exc.stage)
                    LOG.info("/ingest source_id=%s 헤더 거부(stage=%s): %s", source_id, exc.stage, exc.reason)
                    continue
                obs.count("be.gateway.media_ingress", component=COMPONENT)
                note = self.relay.note_sequence(source_id, frame)
                if note:
                    LOG.info("/ingest source_id=%s %s", source_id, note)
                # 뷰어마다 독립 판정. 뷰어가 없으면 fan_out 이 빈 목록 = 버린다.
                for slot, decision, gop_cut in self.relay.fan_out(source_id, frame, time.monotonic()):
                    if decision is media.Decision.SEND:
                        conn = self.viewers.get(slot)
                        if conn is not None:
                            conn.wake.set()
                    else:
                        obs.count("be.gateway.media_frames", component=COMPONENT, outcome="dropped")
                    if gop_cut:
                        obs.count("be.gateway.media_gop_cut", component=COMPONENT)
                # 프레임 하나마다 writer 태스크에 차례를 준다. `async for` 는 소켓에 데이터가 쌓여 있으면 await 없이
                # 연속으로 돌아, 그 사이 writer 가 한 번도 못 비운 채 `buffered` 만 불어 「링크가 느리다」로 오판한다.
                await asyncio.sleep(0)
        except Exception as exc:
            LOG.info("/ingest 연결 종료(사유: %s)", exc)
        finally:
            self.relay.release_ingest(source_id, websocket)
            obs.updown("be.gateway.clients", -1, component=COMPONENT, endpoint="ingest")
            LOG.info("/ingest 종료 source_id=%s 수신 %s장", source_id, received)

    # ── 라우팅 ──────────────────────────────────────────────────────────────

    async def viewer_handler(self, websocket: Any, path: Optional[str] = None) -> None:
        """8765 — `/`·`/state` → 상태 push, `/media` → 영상. 그 외는 4404."""
        raw_path = _request_path(websocket, path)
        route, query = split_route(raw_path)
        LOG.info("접속 %s", mask_token(raw_path))
        if route in ("/", "/state"):
            await self.state_session(websocket, query)
        elif route == "/media":
            await self.media_session(websocket, query)
        else:
            await self._reject(websocket, CLOSE_NOT_FOUND, "unknown path", endpoint="viewer")

    async def ingest_handler(self, websocket: Any, path: Optional[str] = None) -> None:
        """8766 — `/ingest` 만. 그 외는 4404."""
        raw_path = _request_path(websocket, path)
        route, query = split_route(raw_path)
        LOG.info("엣지 접속 %s", mask_token(raw_path))
        if route == "/ingest":
            await self.ingest_session(websocket, query)
        else:
            await self._reject(websocket, CLOSE_NOT_FOUND, "unknown path", endpoint="ingest")


def _tune_write_limit(media_limit: int, sndbuf: int = 0):
    """`process_request` — 핸드셰이크 전에 **경로별** 버퍼 상한을 준다(asyncio·socket 공개 API).

    - 전송 버퍼(`set_write_buffer_limits`): `/media`·`/ingest`는 `MK2_MEDIA_WRITE_LIMIT`(작게 — `buffered` 회계 밖
      바이트를 줄인다), `/state`는 32KB.
    - 커널 송신 버퍼(`SO_SNDBUF`, `MK2_MEDIA_SNDBUF`): **`/media` 만.** 커널 자동조정을 두면 loopback·고속 링크에서
      cwnd 10 × MSS 64KB 로 ~1.4MB(상한 4MB)까지 자라, 뷰어 링크가 멈춰도 `send()`가 안 막혀 drop-old 가 발동하지
      않는다(2026-09-18 서버 실측 — 5초 정지분이 드롭 0). 값을 못 박아 세 번째 버퍼를 회계 안으로 들인다:
      지연 바운드 = `T_drop + write_limit + sndbuf`(사용자 결정 A, 2026-09-19). `0`이면 손대지 않는다.
    반환 `None` = 핸드셰이크 계속. 실패해도 접속을 막지 않는다(기본값으로 진행하고 한 번 경고).
    """
    warned = {"write": False, "sndbuf": False}

    def process_request(connection: Any, request: Any):
        route, _ = split_route(getattr(request, "path", "/") or "/")
        high = media_limit if route in ("/media", "/ingest") else STATE_WRITE_LIMIT
        try:
            connection.transport.set_write_buffer_limits(high=high)
        except Exception as exc:  # noqa: BLE001
            if not warned["write"]:
                warned["write"] = True
                LOG.warning("전송 버퍼 상한을 경로별로 주지 못했다(%s: %s) — 서버 기본값으로 진행", type(exc).__name__, exc)
        if route == "/media" and sndbuf > 0:
            try:
                sock = connection.transport.get_extra_info("socket")
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf)
            except Exception as exc:  # noqa: BLE001
                if not warned["sndbuf"]:
                    warned["sndbuf"] = True
                    LOG.warning("/media 소켓 SO_SNDBUF=%s 를 주지 못했다(%s: %s) — 커널 자동조정으로 진행", sndbuf, type(exc).__name__, exc)
        return None

    return process_request


async def serve(host: Optional[List[str]] = None, port: Optional[int] = None, group_id: str = CONSUMER_GROUP,
                ingest_host: Optional[str] = None, ingest_port: Optional[int] = None) -> None:
    hosts = host or settings.ws_host()
    port = port if port is not None else settings.ws_port()
    ingest_host = ingest_host or settings.media_ingest_host()
    ingest_port = ingest_port if ingest_port is not None else settings.media_ingest_port()

    # 토큰 규율 — loopback 이 아닌데 비어 있으면 여기서 이름을 대며 죽는다(조용히 폴백하지 않는다).
    ws_token = settings.require_token("MK2_WS_TOKEN", settings.ws_token(), hosts)
    edge_token = settings.require_token("MK2_EDGE_TOKEN", settings.edge_token(), [ingest_host]) if ingest_port else ""

    gateway = Gateway()
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stop = threading.Event()

    # ⚠ SIGTERM(systemd stop/restart)을 잡는다. 기본 동작은 즉시 종료라 소비 스레드의 `consumer.close()`
    #    (LeaveGroup)가 안 불리고, 재기동한 인스턴스는 세션 타임아웃(45초)까지 파티션을 못 받는다
    #    (저장 소비자에서 2026-09-16 실측). 메인 태스크를 취소해 아래 finally 가 돌게 한다.
    main_task = asyncio.current_task()
    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: main_task.cancel() if main_task else None)
    except (NotImplementedError, RuntimeError):  # pragma: no cover — Windows 등 미지원 환경
        pass

    media_write_limit = settings.media_write_limit()
    media_sndbuf = settings.media_sndbuf()
    max_frame = settings.media_max_frame_bytes()
    thread = threading.Thread(target=_consume_loop, args=(loop, queue, stop, group_id), daemon=True)
    thread.start()
    try:
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(ws_serve(
                gateway.viewer_handler, hosts, port,
                compression=None,                       # 이미 압축된 프레임을 다시 압축하지 않는다
                max_size=2 ** 20,                       # 뷰어 → 서버 방향은 작다(제어 메시지 없음). 라이브러리 기본값을 명시
                write_limit=media_write_limit,          # 기본은 미디어 값. /state 는 process_request 가 32KB 로 올린다
                process_request=_tune_write_limit(media_write_limit, media_sndbuf),
            ))
            LOG.info(
                "READY — WS 게이트웨이: ws://%s:%s (/state·/media, 토큰 %s, media write_limit=%s sndbuf=%s)",
                ",".join(hosts), port, "있음" if ws_token else "없음(loopback 전용 기동)", media_write_limit, media_sndbuf,
            )
            if ingest_port:
                await stack.enter_async_context(ws_serve(
                    gateway.ingest_handler, ingest_host, ingest_port,
                    compression=None,
                    max_size=2 * max_frame,             # 라이브러리 백스톱. 우리 상한(max_frame)은 ingest_session 이 프레임 단위로 버린다
                    write_limit=media_write_limit,
                    process_request=_tune_write_limit(media_write_limit),
                ))
                LOG.info(
                    "READY — 엣지 입구: ws://%s:%s/ingest (토큰 %s, max_frame=%s, write_limit=%s)",
                    ingest_host, ingest_port, "있음" if edge_token else "없음(loopback 전용 기동)", max_frame, media_write_limit,
                )
            else:
                LOG.info("엣지 입구 닫힘 — MK2_MEDIA_INGEST_PORT=0")
            await _broadcast(queue, gateway.state_clients)
    finally:
        stop.set()
        # 소비 스레드가 poll(0.5) 한 바퀴 뒤 consumer.close() 로 그룹을 떠난다. 종료 중이라 루프를 잠깐 막아도 된다.
        thread.join(timeout=5)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    # websockets 자체 로그는 WARNING 이상만 — 요청 줄(쿼리 토큰 포함)은 DEBUG 에서 찍히지만 기대지 않는다.
    logging.getLogger("websockets").setLevel(logging.WARNING)
    # 관측 어댑터 — 비활성이면 한 줄 로그 뒤 no-op. 로그 핸들러는 루트에 추가(stdout 은 그대로).
    obs.setup("be-gateway")
    handler = obs.log_handler()
    if handler is not None:
        logging.getLogger().addHandler(handler)
    try:
        asyncio.run(serve())
    except settings.MissingSetting as exc:
        LOG.error("기동 실패: %s", exc)
        return 2
    except (KeyboardInterrupt, asyncio.CancelledError):
        # SIGINT 는 KeyboardInterrupt, SIGTERM 은 serve() 안의 핸들러가 메인 태스크를 취소한다.
        LOG.info("종료 신호 — WS 게이트웨이를 닫았다(그룹 이탈)")
    finally:
        obs.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
