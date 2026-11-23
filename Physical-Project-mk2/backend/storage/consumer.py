"""저장 sink 소비자 — Kafka 3토픽 구독 → `store(...)` 호출.

다중 소비자 팬아웃(아키텍처 §6-1)의 한 축이다. **컨슈머 그룹 `mk2-storage`**를 쓰며, WS
게이트웨이 그룹(`mk2-ws`)과 오프셋이 독립이다 — 같은 메시지를 둘이 각자 읽는 이 독립성이
Kafka를 고른 이유다.

Kafka 클라이언트는 이 소비자(경계) 안에만 있고, 저장 로직은 `TelemetryWriter` 뒤에 있다.

이 소비자가 메시지에서 꺼내는 것은 셋이다.

1. **value** — 하드웨어가 보낸 원본 JSON 바이트. 그대로 파싱만 한다.
2. **헤더** — ingest 가 실어 보낸 `ingest_at`·`entity_type`. Kafka 토픽이 채널만 담고
   개체 타입을 담지 않아서, MQTT 토픽을 볼 수 있는 ingest 가 넘겨주는 값이다.
3. **스트림 좌표** — 토픽·파티션·오프셋. 유일 키의 재료다.

⚠ **이 소비자는 구조적으로 재소비한다.** `auto.offset.reset=earliest` + 자동 커밋이라
재기동·오프셋 리셋에서 같은 메시지를 다시 읽는다. 그래서 저장 층은 스트림 좌표를 유일 키로
두고 `INSERT ... ON CONFLICT DO NOTHING` 으로 넣는다 — 유일 키가 없으면 재기동마다 중복 행이
쌓인다.

A층 계측(Phase 3, BE-S-02·BE-S-07): 소비 건수와 **구간 지연 `be.pipeline.lag`** 를 여기서 센다.
지연의 출처는 `TelemetryRecord.lag_s`(= `ingest_at - ts`)이며 새로 계산하지 않는다. OTel 히스토그램은
음수를 받지 않으므로 절대값을 넣고 부호를 `outcome`(`ok`/`clock_skew`) 라벨로 보존한다 — 음수
표본을 버리지 않기 위해서다. 라벨에 `source_id`는 넣지 않는다(A층).

C층 파생(결정 5-a)도 여기다 — `writer.write()` 다음 줄에서 `derive.derive(record)` 한 줄. 새 소비자·새
컨슈머 그룹을 만들지 않는다(레지스트리와 같은 방식). 저장 성공 여부와 무관하게 파생하고, 파생 실패는
파생 쪽이 삼킨다.

⚠ **SIGTERM 을 잡아 그룹을 깨끗이 떠난다.** `systemctl restart`는 SIGTERM 인데 파이썬 기본 동작은 즉시
종료라 `consumer.close()`(LeaveGroup)가 안 불린다. 그러면 코디네이터가 죽은 멤버를 `session.timeout.ms`
(librdkafka 기본 45초)까지 살아 있다고 보고, 새 인스턴스는 그동안 **파티션을 못 받는다** — 2026-09-16
실측: 재기동 5초 뒤 할당 없음, 78초 뒤에야 저장 재개. 신호를 받을 수 없는 죽음(`kill -9`·OOM)에는 효과가
없고 그것은 Kafka 설계상 정상이다.

implements: BE-S-01, BE-T-02, BE-S-02(A층 — be.storage.consumed·be.pipeline.lag / C층 파생 지점), BE-S-07(lag 측정 수단)
tests: tests/test_pipeline.py — sink 기록 도달(팬아웃 ①) ·
       tests/test_observability_pipeline.py — be_storage_consumed_total·be_pipeline_lag_seconds·be_telemetry_* 도달
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from typing import Optional

from confluent_kafka import Consumer, KafkaError

from backend import observability as obs
from backend import settings
from backend.storage import derive
from backend.storage.registry import RegistryWriter, default_registry_writer
from backend.storage.writer import TelemetryRecord, TelemetryWriter, default_writer

LOG = logging.getLogger("mk2.storage.consumer")

CONSUMER_GROUP = "mk2-storage"
COMPONENT = "storage"   # A층 라벨. 이 프로세스가 내는 be.storage.*·be.registry.*·be.pipeline.* 전부 이 값

# 종료 요청. SIGTERM/SIGINT 핸들러가 세우고 소비 루프가 1초마다 본다(poll 타임아웃과 같은 주기).
_STOP = threading.Event()


def request_stop(signum=None, frame=None) -> None:
    LOG.info("종료 신호(%s) — 그룹을 떠나고 소비자를 닫는다", signum)
    _STOP.set()


def observe_lag(record: TelemetryRecord) -> None:
    """`record.lag_s`를 `be.pipeline.lag` 히스토그램에 올린다. `None`(헤더 없는 옛 메시지)이면 아무 일도 없다.

    음수(말단 시계가 앞선 `clock_skew`)는 SDK 히스토그램이 받지 않으므로 **절대값 + outcome 라벨**로
    넘긴다. 버리지 않는다 — 부호 있는 합이 필요하면 조회에서 `ok` 합에서 `clock_skew` 합을 뺀다.
    """
    lag = record.lag_s
    if lag is None:
        return
    obs.observe(
        "be.pipeline.lag", abs(lag),
        component=COMPONENT, channel=record.channel,
        outcome="clock_skew" if lag < 0 else "ok",
    )


def decode_headers(msg) -> dict:
    """Kafka 헤더를 문자열 dict로. 헤더가 없으면 빈 dict.

    ⚠ **헤더가 없는 것이 오류가 아니다.** Phase 1에 쌓인 메시지에는 헤더가 없고(retention
    7일), 오프셋을 리셋하거나 새 컨슈머 그룹으로 읽으면 그것들이 다시 온다. 그때
    `ingest_at`·`entity_type`·`lag_s`가 **NULL인 것이 정상**이며 소비자가 죽으면 안 된다.
    """
    decoded = {}
    for key, value in (msg.headers() or []):
        if isinstance(value, (bytes, bytearray)):
            try:
                decoded[key] = value.decode("utf-8")
            except UnicodeDecodeError:
                decoded[key] = None
        else:
            decoded[key] = value
    return decoded


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


def run(
    writer: Optional[TelemetryWriter] = None,
    group_id: str = CONSUMER_GROUP,
    registry: Optional[RegistryWriter] = None,
) -> None:
    writer = writer or default_writer()
    registry = registry or default_registry_writer()
    _STOP.clear()
    consumer = build_consumer(group_id)
    topics = settings.telemetry_topics()
    consumer.subscribe(topics)
    LOG.info("저장 sink 기동: group=%s topics=%s bootstrap=%s", group_id, topics, settings.kafka_bootstrap())
    try:
        while not _STOP.is_set():
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
            headers = decode_headers(msg)
            record = TelemetryRecord(
                channel=msg.topic().rsplit(".", 1)[-1],
                topic=msg.topic(),
                message=message,
                key=msg.key().decode("utf-8") if msg.key() else None,
                # ingest 가 실어 보낸 값. 없으면 None(옛 메시지) — 그것도 정상이다.
                ingest_at=headers.get("ingest_at"),
                entity_type=headers.get("entity_type"),
                # 스트림 좌표 — 재소비 중복을 막는 유일 키가 된다.
                stream_partition=msg.partition(),
                stream_offset=msg.offset(),
            )
            # ── A층: 소비 1건 + 구간 지연 ────────────────────────────────
            obs.count("be.storage.consumed", component=COMPONENT, channel=record.channel)
            observe_lag(record)

            writer.write(record)

            # ── C층: 업무 값의 관측 표현 ─────────────────────────────
            # 저장 성공 여부와 무관하게 파생한다(결정 5-a). 예외는 derive 쪽이 삼킨다.
            # 원본은 위 writer 가 넣은 TSDB 이고 이 신호는 사본이다 — 파생이 원본을 대체하지 않는다.
            derive.derive(record)

            # ── 레지스트리 관측 축 ────────────────────────────────────
            # **새 소비자·새 컨슈머 그룹을 만들지 않고 이미 도는 경로에 호출 한 줄을 더한다.**
            # 같은 메시지를 또 읽으려고 그룹을 늘리면 Kafka 쪽 부담만 늘고 얻는 것이 없다.
            #
            # 이 자리는 MySQL 을 모른다 — `RegistryWriter.observe()` 라는 목적 인터페이스만
            # 안다(원칙 1). `TelemetryWriter` 가 이 일을 겸하게 만들지 않는 이유는 이름과
            # 책임이 어긋나고, 계측 저장을 갈아끼울 때 레지스트리가 딸려 오기 때문이다.
            #
            # `registration` 이 없는 status(LWT 등)는 observe() 안에서 그냥 지나간다.
            if record.channel == "status":
                registry.observe(record)
    except KeyboardInterrupt:
        LOG.info("종료 신호 — 소비자를 닫는다")
    finally:
        # close() 가 LeaveGroup 을 보낸다 — 재기동한 인스턴스가 세션 타임아웃(45초)을 안 기다린다.
        consumer.close()
        registry.close()
        LOG.info("소비자 종료 완료(그룹 이탈)")


def main() -> int:
    parser = argparse.ArgumentParser(description="MK2 저장 sink 소비자")
    parser.add_argument(
        "--group",
        default=CONSUMER_GROUP,
        help=(
            f"컨슈머 그룹. 기본 {CONSUMER_GROUP}. "
            "다른 이름을 주면 오프셋이 독립이라 **토픽을 처음부터 다시 읽는다** — "
            "헤더가 없는 옛 메시지를 소비해도 죽지 않는지 확인할 때 쓴다. "
            "그때는 MK2_SINK_PATH 로 기록 위치도 함께 바꿔 기존 sink 를 오염시키지 않는다."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    # 관측 어댑터 — 비활성이면 한 줄 로그 뒤 no-op. 로그 핸들러는 루트에 추가(stdout 은 그대로).
    obs.setup("be-storage")
    handler = obs.log_handler()
    if handler is not None:
        logging.getLogger().addHandler(handler)
    # systemd stop/restart(SIGTERM)에서도 그룹을 깨끗이 떠나도록 — 기본 동작은 즉시 종료다.
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        run(group_id=args.group)
    finally:
        obs.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
