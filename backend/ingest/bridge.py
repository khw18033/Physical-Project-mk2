"""MQTT 구독 → 봉투 검증 → Kafka produce 브릿지.

아키텍처 §4-2대로 브릿지는 "두 개의 TCP 연결"일 뿐이지만, 이 경계에서 **봉투 검증·격리·
라우팅**을 해야 하므로 Kafka Connect·브로커 네이티브 브릿지가 아니라 파이썬으로 직접 구현한다.

- 구독은 `+/+/+/{state,status,heartbeat}` 세 패턴뿐이다. `{zone}/{etype}/{eid}/{channel}` 구조
  에서 etype(sensor·robot·actuator·analysis)에 무관하게 텔레메트리를 잡고, 명령 경로
  (`terminal/#`, protobuf)는 자연히 제외된다 — 명령은 Phase 6이다.
- 합격 메시지는 **원본 JSON 바이트 그대로** produce 한다(생산자가 계약에 맞으므로 정규화하지
  않는다). 파티션 키는 봉투의 `source_id`.
- 불합격은 정상 토픽으로 재발행하지 않고 격리 파일에 기록한다(fail-closed).

MQTT 수신 특성(주의):
- **구독이 먼저, 발행이 나중.** 클린 세션이라 구독 전에 발행된 메시지는 받지 못한다.
  구독이 완료되면 `READY` 로그를 찍으므로, 그 뒤에 발행한다.
- `status`는 retained라 **구독 즉시 마지막 1건이 밀려온다.** 정상이며 다른 메시지와 똑같이
  검증→produce 한다.
- `heartbeat`는 QoS 0이라 유실될 수 있다(개수로 완료 판정하지 않는다).
- LWT(death)도 `status` 채널로 온다. Phase 1은 흘려보내기만 하고 가용성 판정은 하지 않는다
  (판정은 Phase 5, 단일 지점).

implements: BE-T-01, BE-T-02, BE-C-01
tests: tests/test_pipeline.py — 봉투 검증 격리(음성), MQTT→Kafka 브릿지 왕복(양성)
"""

from __future__ import annotations

import logging
import signal
import sys
from typing import Any

import paho.mqtt.client as mqtt
from confluent_kafka import Producer

from backend import settings
from backend.ingest.envelope import EnvelopeInvalid, parse_and_validate, quarantine, validator

LOG = logging.getLogger("mk2.ingest")

# 노드는 client_id=entity_id로 붙는다. 겹치면 "session taken over" 플래핑이 나므로
# ingest는 노드와 겹치지 않는 고유 id를 쓴다.
DEFAULT_CLIENT_ID = "mk2-ingest"

SUBSCRIPTIONS = [(f"+/+/+/{channel}", 1) for channel in settings.TELEMETRY_CHANNELS]


def _on_delivery(err: Any, msg: Any) -> None:
    if err is not None:
        LOG.error("Kafka produce 실패: topic=%s err=%s", msg.topic() if msg else "?", err)


class IngestBridge:
    def __init__(self, client_id: str = DEFAULT_CLIENT_ID) -> None:
        self.client_id = client_id
        # 계약 로드와 포맷 검사기 확인을 기동 시점에 끝낸다(검증이 무력한 채로 뜨지 않게).
        validator()
        self.producer = Producer({"bootstrap.servers": settings.kafka_bootstrap(), "client.id": client_id})
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._subscribed = 0

    # ── MQTT 콜백 ────────────────────────────────────────────────────────
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        # paho VERSION2는 ReasonCode 객체를 준다 — 정수 비교가 아니라 값으로 본다.
        if getattr(reason_code, "value", reason_code) != 0:
            LOG.error("MQTT 접속 실패: %s", reason_code)
            return
        LOG.info("MQTT 접속: %s:%s (client_id=%s)", settings.mqtt_host(), settings.mqtt_port(), self.client_id)
        client.subscribe(SUBSCRIPTIONS)

    def _on_subscribe(self, client, userdata, mid, reason_code_list, properties=None):
        self._subscribed += len(reason_code_list)
        LOG.info(
            "READY — 구독 완료 %s (구독이 먼저, 발행이 나중. retained status 1건이 즉시 올 수 있다)",
            [pattern for pattern, _ in SUBSCRIPTIONS],
        )

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        LOG.warning("MQTT 연결 끊김: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        self.handle(msg.topic, msg.payload)

    # ── 처리 ─────────────────────────────────────────────────────────────
    def handle(self, topic: str, payload: bytes) -> bool:
        """수신 1건 처리. 합격 produce면 True, 격리면 False."""
        try:
            message = parse_and_validate(payload)
        except EnvelopeInvalid as exc:
            quarantine(topic=topic, reason=exc.reason, raw=payload)
            LOG.warning("격리(봉투 불합격): topic=%s 사유=%s", topic, exc.reason)
            return False

        channel = settings.channel_of_mqtt_topic(topic)
        try:
            kafka_topic = settings.topic_for_channel(channel)
        except ValueError as exc:
            # 구독 패턴상 여기 오지 않지만, 계약에 없는 채널을 조용히 흘리지 않는다.
            quarantine(topic=topic, reason=str(exc), raw=payload)
            LOG.warning("격리(알 수 없는 채널): topic=%s", topic)
            return False

        self.producer.produce(
            kafka_topic,
            key=message["source_id"].encode("utf-8"),
            value=payload,  # 원본 JSON 바이트 그대로
            on_delivery=_on_delivery,
        )
        self.producer.poll(0)
        LOG.info(
            "produce: %s → %s (source_id=%s, sequence_id=%s)",
            topic,
            kafka_topic,
            message["source_id"],
            message.get("sequence_id"),
        )
        return True

    # ── 수명주기 ─────────────────────────────────────────────────────────
    def run(self) -> None:
        self.client.connect(settings.mqtt_host(), settings.mqtt_port(), keepalive=60)
        try:
            self.client.loop_forever()
        finally:
            remaining = self.producer.flush(10)
            if remaining:
                LOG.error("flush 후에도 미전송 %s건", remaining)

    def stop(self) -> None:
        self.client.disconnect()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    bridge = IngestBridge()

    def _shutdown(signum, frame):
        LOG.info("종료 신호(%s) — 연결을 닫는다", signum)
        bridge.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    LOG.info(
        "ingest 기동: MQTT %s:%s → Kafka %s / 격리파일 %s",
        settings.mqtt_host(),
        settings.mqtt_port(),
        settings.kafka_bootstrap(),
        settings.quarantine_path(),
    )
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
