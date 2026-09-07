"""저장 sink 소비자 — Kafka 3토픽 구독 → `store(...)` 호출.

다중 소비자 팬아웃(아키텍처 §6-1)의 한 축이다. **컨슈머 그룹 `mk2-storage`**를 쓰며, WS
게이트웨이 그룹(`mk2-ws`)과 오프셋이 독립이다 — 같은 메시지를 둘이 각자 읽는 이 독립성이
Kafka를 고른 이유다.

Kafka 클라이언트는 이 소비자(경계) 안에만 있고, 저장 로직은 `TelemetryWriter` 뒤에 있다.

implements: BE-S-01, BE-T-02
tests: tests/test_pipeline.py — sink 기록 도달(팬아웃 ①)
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Optional

from confluent_kafka import Consumer, KafkaError

from backend import settings
from backend.storage.writer import TelemetryRecord, TelemetryWriter, default_writer

LOG = logging.getLogger("mk2.storage.consumer")

CONSUMER_GROUP = "mk2-storage"


def build_consumer(group_id: str = CONSUMER_GROUP) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap(),
            "group.id": group_id,
            # 저장은 유실을 피해야 하므로 처음부터 읽는다(그룹 오프셋이 있으면 이어서).
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )


def run(writer: Optional[TelemetryWriter] = None, group_id: str = CONSUMER_GROUP) -> None:
    writer = writer or default_writer()
    consumer = build_consumer(group_id)
    topics = settings.telemetry_topics()
    consumer.subscribe(topics)
    LOG.info("저장 sink 기동: group=%s topics=%s bootstrap=%s", group_id, topics, settings.kafka_bootstrap())
    try:
        while True:
            msg = consumer.poll(1.0)
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
                # ingest가 검증을 통과시킨 것만 오므로 정상 경로에선 발생하지 않는다.
                LOG.error("토픽 %s의 메시지를 해석하지 못했다: %s", msg.topic(), exc)
                continue
            record = TelemetryRecord(
                channel=msg.topic().rsplit(".", 1)[-1],
                topic=msg.topic(),
                message=message,
                key=msg.key().decode("utf-8") if msg.key() else None,
            )
            writer.write(record)
    except KeyboardInterrupt:
        LOG.info("종료 신호 — 소비자를 닫는다")
    finally:
        consumer.close()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
