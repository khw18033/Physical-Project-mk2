"""WS echo — Kafka 텔레메트리를 연결된 WebSocket 클라이언트에 그대로 push.

다중 소비자 팬아웃(§6-1)의 두 번째 축이다. **컨슈머 그룹 `mk2-ws`**로 저장 sink 그룹
(`mk2-storage`)과 오프셋이 독립이라, 같은 메시지를 둘이 각자 읽는다.

Phase 1 범위는 echo다 — **인증·구독 관리·재접속 캐시·명령 번역은 하지 않는다**(Phase 5/7).
Kafka 소비는 블로킹이라 별도 스레드에서 돌리고, asyncio 큐로 넘겨 브로드캐스트한다.

A층 계측(Phase 3, BE-S-02): push 건수(`be.gateway.push`)와 접속 수(`be.gateway.clients`, +1/-1)만
센다 — Phase 3 범위는 계측까지이고 본구현(구독·인증·캐시)은 Phase 5/7이다.

implements: BE-T-03, BE-T-02, BE-S-02(A층 — be.gateway.*)
tests: tests/test_pipeline.py — 발행값이 WS 클라이언트에 도달(팬아웃 ②) ·
       tests/test_observability_pipeline.py — be_gateway_push_total·be_gateway_clients 도달
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import threading
from typing import Any, Dict, Optional, Set

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

LOG = logging.getLogger("mk2.gateway")

CONSUMER_GROUP = "mk2-ws"
COMPONENT = "gateway"


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


async def _broadcast(queue: "asyncio.Queue[Dict[str, Any]]", clients: Set[Any]) -> None:
    while True:
        item = await queue.get()
        if not clients:
            continue
        payload = json.dumps(item, ensure_ascii=False)
        for client in list(clients):
            try:
                await client.send(payload)
            except Exception as exc:  # 끊긴 클라이언트는 조용히 정리한다
                LOG.info("클라이언트 전송 실패(정리): %s", exc)
                clients.discard(client)
                continue
            obs.count("be.gateway.push", component=COMPONENT, channel=item["channel"])


async def serve(host: Optional[str] = None, port: Optional[int] = None, group_id: str = CONSUMER_GROUP) -> None:
    host = host or settings.ws_host()
    port = port if port is not None else settings.ws_port()
    clients: Set[Any] = set()
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stop = threading.Event()

    async def handler(websocket, path=None):
        """접속 1건의 수명. websockets 13(legacy)·14+(신 asyncio) 양쪽에서 돈다.

        - 신 API는 핸들러를 **인자 1개**로 부르므로 `path`에 기본값을 둔다.
        - 종료 대기는 `wait_closed()` 대신 **수신 반복**으로 한다(양쪽 API 공통).
          Phase 1 echo는 단방향 push라 클라이언트가 보낸 것은 버린다(구독 관리는 Phase 5/7).
        """
        clients.add(websocket)
        obs.updown("be.gateway.clients", +1, component=COMPONENT)
        LOG.info("WS 클라이언트 접속 (현재 %s명)", len(clients))
        try:
            async for _ in websocket:
                pass
        except Exception as exc:
            LOG.info("WS 클라이언트 연결 종료(사유: %s)", exc)
        finally:
            clients.discard(websocket)
            obs.updown("be.gateway.clients", -1, component=COMPONENT)
            LOG.info("WS 클라이언트 종료 (현재 %s명)", len(clients))

    # ⚠ SIGTERM(systemd stop/restart)을 잡는다. 기본 동작은 즉시 종료라 소비 스레드의 `consumer.close()`
    #    (LeaveGroup)가 안 불리고, 재기동한 인스턴스는 세션 타임아웃(45초)까지 파티션을 못 받는다
    #    (저장 소비자에서 2026-09-16 실측). 메인 태스크를 취소해 아래 finally 가 돌게 한다.
    main_task = asyncio.current_task()
    try:
        loop.add_signal_handler(signal.SIGTERM, lambda: main_task.cancel() if main_task else None)
    except (NotImplementedError, RuntimeError):  # pragma: no cover — Windows 등 미지원 환경
        pass

    thread = threading.Thread(target=_consume_loop, args=(loop, queue, stop, group_id), daemon=True)
    thread.start()
    try:
        async with ws_serve(handler, host, port):
            LOG.info("READY — WS echo 서빙: ws://%s:%s (인증 없음, Phase 1 echo)", host, port)
            await _broadcast(queue, clients)
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
    # 관측 어댑터 — 비활성이면 한 줄 로그 뒤 no-op. 로그 핸들러는 루트에 추가(stdout 은 그대로).
    obs.setup("be-gateway")
    handler = obs.log_handler()
    if handler is not None:
        logging.getLogger().addHandler(handler)
    try:
        asyncio.run(serve())
    except (KeyboardInterrupt, asyncio.CancelledError):
        # SIGINT 는 KeyboardInterrupt, SIGTERM 은 serve() 안의 핸들러가 메인 태스크를 취소한다.
        LOG.info("종료 신호 — WS 게이트웨이를 닫았다(그룹 이탈)")
    finally:
        obs.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
