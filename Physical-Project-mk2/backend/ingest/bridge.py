"""MQTT 구독 → 2단 검증(공통 헤더 → 채널 본문) → Kafka produce 브릿지.

아키텍처 §4-2대로 브릿지는 "두 개의 TCP 연결"일 뿐이지만, 이 경계에서 **검증·격리·라우팅**을
해야 하므로 Kafka Connect·브로커 네이티브 브릿지가 아니라 파이썬으로 직접 구현한다.

- 구독은 `+/+/+/{state,status,heartbeat}` 세 패턴뿐이다. `{zone}/{etype}/{eid}/{channel}` 구조
  에서 etype(sensor·robot·actuator·analysis)에 무관하게 텔레메트리를 잡고, 명령 경로
  (`terminal/#`, protobuf)는 자연히 제외된다 — 명령은 Phase 6이다.
- **개체 타입(etype)은 이 자리에서만 알 수 있다.** Kafka 토픽은 채널만 담고 etype을 담지
  않으므로, 타입별 본문 규격을 고르는 일도 저장 층이 아니라 여기서 한다.
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

끊김 버티기(실측 재개 8번 작업 B 뒤 — 2026-11-12, BE-T-02):
- Kafka 에 못 닿는 동안 합격 메시지는 생산자의 **메모리 대기열**에서 기다리다가, 길이 돌아오면 나간다.
- 기다리는 한계(`MK2_KAFKA_MESSAGE_TIMEOUT_MS`, 없으면 라이브러리 기본 5분)를 넘긴 것은 버려진다 →
  **미전송 파일**(`MK2_UNSENT_PATH`)에 받은 원본 그대로 한 줄. 8번 작업 B 에서 정확히 300초에 버려졌다.
- 대기열이 가득 차면(`produce()` 의 BufferError) **기다리던 것(전송 중인 것은 빼고)을 미전송 파일로 비우고**
  지금 건을 다시 넣은 뒤 계속한다. 비운 뒤에도 못 넣으면 지금 건만 미전송 파일로.
  이전에는 이 예외가 MQTT 콜백 밖으로 새어 **브릿지가 죽었다**(paho 는 콜백 예외를 다시 던진다 —
  서버는 systemd 가 5초 뒤 되살리지만 엣지는 되살릴 것이 없다).
- 종료 때 flush 로도 남은 것도 미전송 파일로.
- 미전송 파일은 **검증은 합격한** 메시지다(격리 파일과 다르다). 다시 흘려 넣는 도구는 아직 없다.
- 생산자 설정 값은 환경변수로만 받고 **엣지에서만 준다**(`backend/settings.py`) — 서버는 라이브러리 기본값 그대로다.
  환경변수 이름을 Kafka 설정 이름으로 옮기는 자리는 `producer_config()` 하나다.

A층 계측(Phase 3, BE-S-02): 수신·거부(단계별)·produce 결과를 `backend/observability.py`의 목적
인터페이스로 센다. 이 파일은 `opentelemetry`를 import 하지 않는다(원칙 1). 라벨은 `component`·
`channel`·`stage`·`outcome`뿐이고 `source_id`는 넣지 않는다(장치 수만큼 시계열이 곱해진다).
재기동마다 retained `status`가 다시 흘러 `be.ingest.received`가 그 건수만큼 튀는 것은 정상이다.
미전송 파일로 간 것(버려짐·비움·대기열에 못 넣음)은 모두 `be.kafka.produce{outcome=fail}` 로 센다.

implements: BE-T-01, BE-T-02, BE-C-01, BE-S-02(A층 — be.ingest.*·be.kafka.*)
tests: tests/test_pipeline.py — 봉투 검증 격리(음성), MQTT→Kafka 브릿지 왕복(양성) ·
       tests/test_observability_pipeline.py — be_ingest_*·be_kafka_* 가 Prometheus 에 도달, 음성 fixture 후 rejected 증가 ·
       tests/test_bridge_unsent.py — 생산자 설정·미전송 파일·대기열 비우기·종료 때 남은 것(Kafka·MQTT 없이)
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt
from confluent_kafka import KafkaError, Producer

from backend import observability as obs
from backend import settings
from backend.ingest.envelope import (
    MessageInvalid,
    parse_and_validate,
    quarantine,
    validate_payload,
    validator,
)

LOG = logging.getLogger("mk2.ingest")

# 노드는 client_id=entity_id로 붙는다. 겹치면 "session taken over" 플래핑이 나므로
# ingest는 노드와 겹치지 않는 고유 id를 쓴다.
DEFAULT_CLIENT_ID = "mk2-ingest"

SUBSCRIPTIONS = [(f"+/+/+/{channel}", 1) for channel in settings.TELEMETRY_CHANNELS]

COMPONENT = "ingest"   # A층 라벨. service.name(be-ingest)은 Prometheus 에서 exported_job 으로 밀려나므로 이걸로 가른다

Headers = List[Tuple[str, bytes]]

# 비우기(purge)로 버린 것 — 메시지마다 오류 로그를 찍지 않는다(대기열 상한만큼 줄이 쏟아진다). 비운 쪽이 건수를 한 줄로 찍는다.
_PURGE_CODES = (KafkaError._PURGE_QUEUE, KafkaError._PURGE_INFLIGHT)
# 미전송 파일 쓰기는 MQTT 콜백 스레드·poll 스레드 양쪽에서 온다.
_UNSENT_LOCK = threading.Lock()


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def record_unsent(
    *,
    reason: str,
    detail: str,
    topic: Optional[str],
    key: Any,
    value: Any,
    headers: Optional[Headers],
    path: Optional[Path] = None,
) -> None:
    """보내지 못하고 버린 메시지 1건을 미전송 파일에 한 줄로 남긴다(검증은 합격한 것).

    `raw` 는 받은 원본 JSON 그대로다. `headers` 는 브릿지가 붙인 Kafka 헤더(ingest_at = 엣지 도달 시각, entity_type).
    기록 시각은 이 기기의 로컬 시각이다. **파일을 못 써도 브릿지는 죽지 않는다** — 오류 로그만 남긴다.
    """
    target = path or settings.unsent_path()
    record = {
        "recorded_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "reason": reason,
        "detail": detail,
        "topic": topic,
        "key": _text(key),
        "headers": {name: _text(raw) for name, raw in (headers or [])},
        "raw": _text(value),
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    try:
        with _UNSENT_LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fp:
                fp.write(line)
    except OSError as exc:
        LOG.error("미전송 파일 기록 실패(%s): %s — 이 1건은 기록 없이 사라진다", target, exc)


def _on_delivery(err: Any, msg: Any, headers: Optional[Headers] = None) -> None:
    """전달 결과 1건. `headers` 는 produce 때 붙인 것 — 전달 결과의 msg.headers() 는 비어 온다(confluent-kafka 2.15 확인)."""
    # 채널은 콜백 인자로 안 넘어온다 — 토픽 규약 `mk2.telemetry.<채널>` 에서 꺼낸다.
    channel = msg.topic().rsplit(".", 1)[-1] if msg is not None else "unknown"
    if err is None:
        obs.count("be.kafka.produce", component=COMPONENT, channel=channel, outcome="ok")
        return
    obs.count("be.kafka.produce", component=COMPONENT, channel=channel, outcome="fail")
    purged = err.code() in _PURGE_CODES
    if not purged:
        LOG.error("Kafka produce 실패: topic=%s err=%s", msg.topic() if msg else "?", err)
    if msg is not None:
        record_unsent(
            reason=err.name(),
            detail=err.str(),
            topic=msg.topic(),
            key=msg.key(),
            value=msg.value(),
            headers=headers,
        )


def _delivery_for(headers: Headers) -> Callable[[Any, Any], None]:
    """메시지마다 자기 헤더를 기억하는 전달 콜백(미전송 파일에 ingest_at 을 남기려고)."""
    return lambda err, msg: _on_delivery(err, msg, headers)


def producer_config(client_id: str) -> Dict[str, Any]:
    """Kafka 생산자 설정. **환경변수가 없으면 2026-11 이전과 같은 두 줄뿐이다**(라이브러리 기본값 그대로).

    환경변수 이름 → Kafka 설정 이름을 옮기는 자리는 여기 하나다(원칙 1). 값의 범위는 라이브러리가 기동 때 검사한다
    (예: 접속 한계는 1000 이상 — 아니면 Producer 생성에서 죽는다).
    """
    config: Dict[str, Any] = {"bootstrap.servers": settings.kafka_bootstrap(), "client.id": client_id}
    message_timeout = settings.kafka_message_timeout_ms()
    if message_timeout is not None:
        config["message.timeout.ms"] = message_timeout
    connect_timeout = settings.kafka_connect_timeout_ms()
    if connect_timeout is not None:
        config["socket.connection.setup.timeout.ms"] = connect_timeout
    queue_max = settings.kafka_queue_max_messages()
    if queue_max is not None:
        config["queue.buffering.max.messages"] = queue_max
    if settings.kafka_idempotence():
        config["enable.idempotence"] = True
    return config


class IngestBridge:
    def __init__(self, client_id: str = DEFAULT_CLIENT_ID) -> None:
        self.client_id = client_id
        # 계약 로드와 포맷 검사기 확인을 기동 시점에 끝낸다(검증이 무력한 채로 뜨지 않게).
        validator()
        self.producer = Producer(producer_config(client_id))
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._subscribed = 0
        # ⚠ 전달 콜백(_on_delivery)은 producer.poll() 을 부를 때만 실행된다. produce() 직후의 poll(0) 은
        #    아직 ack 가 안 와서 **직전 메시지**의 콜백만 처리하므로, 조용한 파이프라인에서는 마지막 1건의
        #    결과(특히 실패)가 다음 메시지까지 무기한 미뤄진다 — 2026-09-16 실측: received 28 / produce 27.
        #    그래서 1초 주기로 poll 하는 스레드를 따로 둔다(Producer 는 스레드 안전). A층 be.kafka.produce 의 정확성 조건.
        self._stop = threading.Event()
        self._poll_thread = threading.Thread(target=self._poll_loop, name="mk2-ingest-poll", daemon=True)

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
        """수신 1건 처리. 검증 합격이면 True(대기열에 못 넣어 미전송 파일로 갔어도), 격리면 False.

        검증은 **공통 헤더 → 본문** 2단이다. 두 단을 이 자리에서 나눠 부르는 이유는
        본문 규격을 고르려면 **MQTT 토픽**(채널·개체 타입)이 필요한데 그것을 아는 곳이
        여기뿐이기 때문이다.
        """
        # 서버 도달 시각은 **검증 전에** 찍는다. 검증에 걸린 시간이 지연에 섞이면
        # lag_s 가 네트워크 지연이 아니라 우리 처리 시간을 재게 된다.
        ingest_at = settings.utc_now_iso()
        # 채널은 토픽 마지막 칸이라 검증 전에도 안다 — 거부 계측의 channel 라벨에 쓴다.
        channel = settings.channel_of_mqtt_topic(topic)

        # ── 1단: 공통 헤더 ──────────────────────────────────────────────
        try:
            message = parse_and_validate(payload)
        except MessageInvalid as exc:
            quarantine(topic=topic, reason=exc.reason, raw=payload)
            LOG.warning("격리(공통 헤더 불합격): topic=%s 사유=%s", topic, exc.reason)
            obs.count("be.ingest.rejected", component=COMPONENT, channel=channel, stage="envelope")
            return False

        entity_type = settings.entity_type_of_mqtt_topic(topic)
        try:
            kafka_topic = settings.topic_for_channel(channel)
        except ValueError as exc:
            # 구독 패턴상 여기 오지 않지만, 규격에 없는 채널을 조용히 흘리지 않는다.
            quarantine(topic=topic, reason=str(exc), raw=payload)
            LOG.warning("격리(알 수 없는 채널): topic=%s", topic)
            obs.count("be.ingest.rejected", component=COMPONENT, channel=channel, stage="unknown_channel")
            return False

        # ── 2단: 채널 본문 ──────────────────────────────────────────────
        # 모르는 개체 타입은 여기서 통과한다(검증을 건너뛰고 기록만) — 새 노드 타입이
        # 첫 메시지부터 격리되면 파이프라인이 그 자리에서 막힌다.
        try:
            validate_payload(channel, entity_type, message)
        except MessageInvalid as exc:
            quarantine(topic=topic, reason=exc.reason, raw=payload)
            LOG.warning("격리(본문 불합격): topic=%s 사유=%s", topic, exc.reason)
            obs.count("be.ingest.rejected", component=COMPONENT, channel=channel, stage="payload")
            return False

        # 2단 검증 통과 = 수신 1건. produce 직전에 센다(produce 결과는 _on_delivery 가 따로 센다).
        obs.count("be.ingest.received", component=COMPONENT, channel=channel)

        # ── produce — value 는 원본 바이트, 부가 정보는 Kafka 헤더로 ─────
        #
        # **본문에 넣지 않는 이유:** Phase 1이 확정한 "Kafka value 는 하드웨어가 보낸 원본
        # JSON 바이트 그대로"를 깨지 않기 위해서다. 재직렬화하면 필드 순서·수치 표현이
        # 달라져 원본이 사라진다. 헤더는 value 바깥이라 원본을 건드리지 않는다.
        #
        # entity_type 을 굳이 실어 보내는 이유: Kafka 토픽은 `mk2.telemetry.<채널>`이라
        # **채널만 담고 개체 타입을 담지 않는다**(Phase 1 확정 규약이라 바꾸지 않는다).
        # 저장 소비자는 MQTT 토픽을 보지 못하므로, 여기서 파싱한 값을 넘겨줘야 한다.
        # 저장 층이 레지스트리를 조회해 타입을 알아내려 하면 닭-달걀이 된다 — 대장에 없는
        # 새 노드가 첫 메시지부터 막힌다.
        headers: Headers = [("ingest_at", ingest_at.encode("utf-8"))]
        if entity_type:
            headers.append(("entity_type", entity_type.encode("utf-8")))

        queued = self._produce(
            kafka_topic,
            key=message["source_id"].encode("utf-8"),
            value=payload,  # 원본 JSON 바이트 그대로 — 변경 금지
            headers=headers,
            channel=channel,
        )
        if queued:
            LOG.info(
                "produce: %s → %s (source_id=%s, sequence_id=%s, etype=%s, ingest_at=%s)",
                topic,
                kafka_topic,
                message["source_id"],
                message.get("sequence_id"),
                entity_type,
                ingest_at,
            )
        return True

    def _produce(self, topic: str, *, key: bytes, value: bytes, headers: Headers, channel: str) -> bool:
        """대기열에 넣으면 True. **대기열이 가득 차도 예외를 밖으로 내지 않는다**(MQTT 콜백 밖으로 새면 브릿지가 죽는다).

        가득 차면: 기다리던 것(전송 중인 것은 빼고)을 비운다 → 그것들은 전달 콜백을 거쳐 미전송 파일로 간다
        → 지금 건을 다시 넣는다. 1초 안에 못 넣으면 지금 건만 미전송 파일로(False).
        """
        try:
            self.producer.produce(topic, key=key, value=value, headers=headers, on_delivery=_delivery_for(headers))
        except BufferError:
            waiting = len(self.producer)   # 결과가 아직 안 난 것(전송 중 포함)
            self.producer.purge(in_queue=True, in_flight=False)
            LOG.warning(
                "대기열 가득 참(%s건) — 기다리던 것을 미전송 파일로 비우고 계속한다(전송 중인 것은 둔다): %s",
                waiting,
                settings.unsent_path(),
            )
            if not self._produce_after_purge(topic, key=key, value=value, headers=headers):
                LOG.error("비운 뒤에도 대기열에 넣지 못함 — 지금 건을 미전송 파일로: topic=%s", topic)
                record_unsent(
                    reason="QUEUE_FULL",
                    detail="purge 뒤 1초 안에 대기열에 넣지 못함",
                    topic=topic,
                    key=key,
                    value=value,
                    headers=headers,
                )
                obs.count("be.kafka.produce", component=COMPONENT, channel=channel, outcome="fail")
                return False
        self.producer.poll(0)
        return True

    def _produce_after_purge(self, topic: str, *, key: bytes, value: bytes, headers: Headers) -> bool:
        """비운 직후 다시 넣기. 비운 것은 전달 콜백(_PURGE_QUEUE)이 돌아야 대기열 수에서 빠지는데, 그 콜백을 poll 스레드가
        먼저 잡으면 poll(0) 한 번 뒤에도 아직 가득 찬 채다(모의 브로커 예행 2026-11-13 — 한 건이 괜히 버려졌다).
        그래서 1초 안에서 콜백을 돌리며 다시 넣어 본다."""
        deadline = time.monotonic() + 1.0
        while True:
            self.producer.poll(0.05)
            try:
                self.producer.produce(topic, key=key, value=value, headers=headers, on_delivery=_delivery_for(headers))
                return True
            except BufferError:
                if time.monotonic() >= deadline:
                    return False

    # ── 수명주기 ─────────────────────────────────────────────────────────
    def _poll_loop(self) -> None:
        """전달 콜백을 1초 안에 처리한다. poll(1.0) 은 이벤트가 없으면 최대 1초 기다렸다 돌아온다."""
        while not self._stop.is_set():
            try:
                self.producer.poll(1.0)
            except Exception as exc:  # noqa: BLE001 - 콜백 처리 실패가 브릿지를 죽이지 않는다
                LOG.warning("producer.poll 실패(계속): %s: %s", type(exc).__name__, exc)
                self._stop.wait(1.0)

    def _drain_on_exit(self) -> None:
        """종료 때 남은 것을 보낸다. 10초 안에 못 보낸 것은 비워서 미전송 파일로 남긴다(전송 중인 것까지)."""
        remaining = self.producer.flush(10)   # flush 도 콜백을 처리한다 — 마지막 건의 outcome 이 여기서 세진다
        if remaining:
            LOG.error("flush 후에도 미전송 %s건 — 미전송 파일로 남기고 끝낸다: %s", remaining, settings.unsent_path())
            self.producer.purge(in_queue=True, in_flight=True)
            self.producer.poll(0)

    def run(self) -> None:
        self.client.connect(settings.mqtt_host(), settings.mqtt_port(), keepalive=60)
        self._poll_thread.start()
        try:
            self.client.loop_forever()
        finally:
            self._stop.set()
            self._poll_thread.join(timeout=3)
            self._drain_on_exit()

    def stop(self) -> None:
        self.client.disconnect()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    # 관측 어댑터 — 비활성(MK2_OTEL_ENDPOINT 비움·SDK 없음)이면 한 줄 로그 뒤 no-op.
    # 로그 핸들러는 루트 로거에 **추가**한다. stdout(journald)은 그대로 두어 운영자용으로 병존한다(4-c).
    obs.setup("be-ingest")
    handler = obs.log_handler()
    if handler is not None:
        logging.getLogger().addHandler(handler)
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
    overrides = {
        name: value
        for name, value in producer_config(bridge.client_id).items()
        if name not in ("bootstrap.servers", "client.id")
    }
    LOG.info("Kafka 생산자: %s / 미전송파일 %s", overrides or "라이브러리 기본값", settings.unsent_path())
    try:
        bridge.run()
    finally:
        obs.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
