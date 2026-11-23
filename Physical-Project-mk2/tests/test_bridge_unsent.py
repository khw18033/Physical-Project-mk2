"""브릿지 끊김 버티기 — 생산자 설정(환경변수) · 미전송 파일 · 대기열이 가득 찰 때 비우고 계속 · 종료 때 남은 것.

**Kafka·MQTT 없이 돈다.** 실제 Kafka 클라이언트(`confluent_kafka.Producer`)를 쓰되 아무도 듣지 않는 주소
(`127.0.0.1:1`)를 가리키므로, 보낸 것은 전부 대기열에 머문다 — 실측 8번 작업 B 의 "서버에 못 닿는 엣지"와 같은 처지다.
MQTT 는 접속하지 않고 `handle()` 을 바로 부른다.

**핵심 음성 대조:**

- 환경변수가 없으면 생산자 설정은 2026-11 이전과 같은 두 줄뿐이다(서버는 아무것도 바뀌지 않는다).
- 전달이 성공하면 미전송 파일에 아무것도 쓰지 않는다.
- 대기열이 가득 차기 전에는 미전송 파일이 생기지 않는다 — 가득 찬 **다음 건**에서 비운다.
- 대기열이 가득 차도 `handle()` 이 예외를 내지 않는다(전에는 BufferError 가 MQTT 콜백 밖으로 새어 브릿지가 죽었다).

implements: BE-T-02 (끊김 버티기 — 미전송 기록·대기열 비우기)
tests: 설정 기본·매핑·공백·잘못된 값 · 실제 Producer 가 엣지 설정을 받음 · 성공은 기록 안 함 · 한계 넘김 기록(헤더 포함) ·
       가득 차면 비우고 계속 · 비워도 못 넣으면 지금 건만 · 종료 때 남은 것 · 파일을 못 써도 죽지 않음
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List

import pytest

import publisher
from backend import settings
from backend.ingest import bridge

PRODUCER_VARS = (
    "MK2_KAFKA_MESSAGE_TIMEOUT_MS",
    "MK2_KAFKA_CONNECT_TIMEOUT_MS",
    "MK2_KAFKA_QUEUE_MAX_MESSAGES",
    "MK2_KAFKA_IDEMPOTENCE",
)
NOBODY = "127.0.0.1:1"   # 아무도 듣지 않는 주소 — 보낸 것은 대기열에 머문다
TOPIC = publisher.topic_for("state")   # zoneA/sensor/wl-001/state


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path) -> Path:
    for name in PRODUCER_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MK2_UNSENT_PATH", str(tmp_path / "unsent.jsonl"))
    return tmp_path


@pytest.fixture
def unsent(tmp_path) -> Path:
    return tmp_path / "unsent.jsonl"


@pytest.fixture
def counts(monkeypatch) -> List[tuple]:
    """A층 계측 호출을 가로채 센다(관측 어댑터 없이)."""
    seen: List[tuple] = []

    def _count(name: str, **labels: Any) -> None:
        seen.append((name, labels.get("outcome")))

    monkeypatch.setattr(bridge.obs, "count", _count)
    return seen


@pytest.fixture
def make_bridge(monkeypatch):
    """아무도 듣지 않는 Kafka 를 가리키는 브릿지. librdkafka 의 접속 실패 줄(stderr)만 끈다."""
    monkeypatch.setenv("MK2_KAFKA_BOOTSTRAP", NOBODY)
    original = bridge.producer_config

    def _quiet(client_id: str):
        config = original(client_id)
        config["log_level"] = 0
        return config

    monkeypatch.setattr(bridge, "producer_config", _quiet)
    made = []

    def _make() -> bridge.IngestBridge:
        made.append(bridge.IngestBridge(client_id="mk2-ingest-unit-test"))
        return made[-1]

    yield _make
    for b in made:
        if not isinstance(b.producer, _FullForever):
            b.producer.purge(in_queue=True, in_flight=True)   # 남은 것을 다음 테스트로 끌고 가지 않는다
            b.producer.poll(0)


def _payload(seq: int) -> bytes:
    message = publisher.make_message("state", source_id="wl-001", sequence_id=seq, session_id="a1b2c3d4e5f6")
    return json.dumps(message).encode("utf-8")


def _lines(path: Path) -> List[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _seq(record: dict) -> int:
    return json.loads(record["raw"])["sequence_id"]


class _ShortFlush:
    """종료 처리의 flush(10) 를 0.5초로 줄인다(나머지는 실제 Producer 그대로)."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def flush(self, timeout: float = -1) -> int:
        return self._inner.flush(0.5)

    def __len__(self) -> int:
        return len(self._inner)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class _FullForever:
    """비워도 계속 가득 찬 대기열(실제로는 전송 중인 것만으로 상한에 닿은 경우)."""

    def __init__(self) -> None:
        self.purge_calls: List[tuple] = []

    def produce(self, *args, **kwargs) -> None:
        raise BufferError("Local: Queue full")

    def purge(self, in_queue: bool = True, in_flight: bool = True, blocking: bool = True) -> None:
        self.purge_calls.append((in_queue, in_flight))

    def poll(self, timeout: float = 0) -> int:
        time.sleep(timeout)   # 실제 Producer 처럼 이벤트가 없으면 기다렸다 돌아온다
        return 0

    def __len__(self) -> int:
        return 5


# ── 생산자 설정 ────────────────────────────────────────────────────────────


def test_no_env_keeps_library_defaults():
    """음성 대조 — 환경변수가 없으면 2026-11 이전과 같은 두 줄뿐(서버가 이 경우다)."""
    assert bridge.producer_config("x") == {"bootstrap.servers": settings.kafka_bootstrap(), "client.id": "x"}


def test_env_maps_to_kafka_names(monkeypatch):
    monkeypatch.setenv("MK2_KAFKA_MESSAGE_TIMEOUT_MS", "300000")
    monkeypatch.setenv("MK2_KAFKA_CONNECT_TIMEOUT_MS", "5000")
    monkeypatch.setenv("MK2_KAFKA_QUEUE_MAX_MESSAGES", "50")
    monkeypatch.setenv("MK2_KAFKA_IDEMPOTENCE", "1")
    config = bridge.producer_config("x")
    assert config["message.timeout.ms"] == 300000
    assert config["socket.connection.setup.timeout.ms"] == 5000
    assert config["queue.buffering.max.messages"] == 50
    assert config["enable.idempotence"] is True


def test_blank_env_is_unset(monkeypatch):
    """Windows 에서 `$env:X=""` 는 변수를 지운다 — 그래서 공백 하나로 '비움'을 주는 경우도 없음으로 친다."""
    for name in PRODUCER_VARS:
        monkeypatch.setenv(name, " ")
    assert bridge.producer_config("x") == {"bootstrap.servers": settings.kafka_bootstrap(), "client.id": "x"}


@pytest.mark.parametrize(
    "name, raw",
    [
        ("MK2_KAFKA_MESSAGE_TIMEOUT_MS", "5s"),
        ("MK2_KAFKA_CONNECT_TIMEOUT_MS", "-1"),
        ("MK2_KAFKA_QUEUE_MAX_MESSAGES", "1.5"),
        ("MK2_KAFKA_IDEMPOTENCE", "maybe"),
    ],
)
def test_bad_env_fails_at_startup(monkeypatch, name, raw):
    """잘못된 값은 조용히 기본값으로 물러서지 않고 이름을 대며 죽는다."""
    monkeypatch.setenv(name, raw)
    with pytest.raises(ValueError, match=name):
        bridge.producer_config("x")


def test_real_producer_accepts_edge_config(monkeypatch):
    """엣지에 줄 값 그대로 실제 Kafka 클라이언트가 받는다(설정 이름 오타면 여기서 KafkaException)."""
    monkeypatch.setenv("MK2_KAFKA_BOOTSTRAP", NOBODY)
    monkeypatch.setenv("MK2_KAFKA_MESSAGE_TIMEOUT_MS", "300000")
    monkeypatch.setenv("MK2_KAFKA_CONNECT_TIMEOUT_MS", "5000")
    monkeypatch.setenv("MK2_KAFKA_QUEUE_MAX_MESSAGES", "50")
    monkeypatch.setenv("MK2_KAFKA_IDEMPOTENCE", "1")
    config = bridge.producer_config("x")
    config["log_level"] = 0
    bridge.Producer(config)


# ── 미전송 파일 ────────────────────────────────────────────────────────────


class _Msg:
    def __init__(self, topic: str, key: bytes, value: bytes) -> None:
        self._topic, self._key, self._value = topic, key, value

    def topic(self) -> str:
        return self._topic

    def key(self) -> bytes:
        return self._key

    def value(self) -> bytes:
        return self._value


def test_delivered_writes_nothing(unsent, counts):
    """음성 대조 — 전달 성공은 미전송 파일에 쓰지 않는다."""
    bridge._on_delivery(None, _Msg("mk2.telemetry.state", b"wl-001", _payload(1)))
    assert not unsent.exists()
    assert counts == [("be.kafka.produce", "ok")]


def test_timed_out_is_recorded_with_headers(monkeypatch, make_bridge, unsent, counts):
    """기다리는 한계를 넘긴 것 — 받은 원본 그대로 + ingest_at(엣지 도달 시각)·entity_type 헤더."""
    monkeypatch.setenv("MK2_KAFKA_MESSAGE_TIMEOUT_MS", "1000")
    b = make_bridge()
    payload = _payload(7)
    assert b.handle(TOPIC, payload) is True
    assert b.producer.flush(5) == 0   # 1초 한계로 버려져 대기열이 빈다
    records = _lines(unsent)
    assert len(records) == 1
    record = records[0]
    assert record["reason"] == "_MSG_TIMED_OUT"
    assert record["topic"] == "mk2.telemetry.state"
    assert record["key"] == "wl-001"
    assert record["raw"] == payload.decode("utf-8")
    assert record["headers"]["entity_type"] == "sensor"
    assert record["headers"]["ingest_at"]
    assert ("be.kafka.produce", "fail") in counts


def test_queue_full_purges_waiting_and_continues(monkeypatch, make_bridge, unsent, counts):
    """대기열 3건이 찬 뒤 4번째 — 1~3 을 미전송 파일로 비우고 4 를 넣는다. 예외가 밖으로 나오지 않는다."""
    monkeypatch.setenv("MK2_KAFKA_QUEUE_MAX_MESSAGES", "3")
    b = make_bridge()
    for seq in (1, 2, 3):
        assert b.handle(TOPIC, _payload(seq)) is True
    assert not unsent.exists()   # 음성 대조 — 가득 차기 전에는 아무것도 버리지 않는다
    assert len(b.producer) == 3

    assert b.handle(TOPIC, _payload(4)) is True
    records = _lines(unsent)
    assert [_seq(r) for r in records] == [1, 2, 3]
    assert {r["reason"] for r in records} == {"_PURGE_QUEUE"}
    assert all(r["headers"]["ingest_at"] for r in records)
    assert len(b.producer) == 1   # 4 만 남아 기다린다
    assert counts.count(("be.kafka.produce", "fail")) == 3


def test_queue_full_after_purge_records_current(make_bridge, unsent, counts):
    """비우고 1초 안에 못 넣으면(전송 중인 것만으로 가득) 지금 건만 미전송 파일로 — 그래도 handle 은 True(검증은 합격)."""
    b = make_bridge()
    b.producer.purge(in_queue=True, in_flight=True)
    b.producer = _FullForever()
    payload = _payload(9)
    assert b.handle(TOPIC, payload) is True
    assert b.producer.purge_calls == [(True, False)]   # 전송 중인 것은 비우지 않는다
    records = _lines(unsent)
    assert len(records) == 1
    assert records[0]["reason"] == "QUEUE_FULL"
    assert records[0]["raw"] == payload.decode("utf-8")
    assert records[0]["headers"]["entity_type"] == "sensor"
    assert counts.count(("be.kafka.produce", "fail")) == 1


def test_drain_on_exit_records_leftovers(make_bridge, unsent):
    """종료 때 flush 로도 못 보낸 것은 비워서 미전송 파일로 남긴다."""
    b = make_bridge()
    for seq in (1, 2):
        b.handle(TOPIC, _payload(seq))
    b.producer = _ShortFlush(b.producer)
    b._drain_on_exit()
    records = _lines(unsent)
    assert sorted(_seq(r) for r in records) == [1, 2]
    assert len(b.producer) == 0


def test_unwritable_unsent_does_not_raise(tmp_path, caplog):
    """미전송 파일을 못 써도 브릿지는 죽지 않는다(오류 로그만)."""
    blocked = tmp_path / "is_a_directory"
    blocked.mkdir()
    bridge.record_unsent(
        reason="TEST", detail="", topic="t", key=b"k", value=b"{}", headers=None, path=blocked
    )
    assert "미전송 파일 기록 실패" in caplog.text
