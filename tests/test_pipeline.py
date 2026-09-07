"""Phase 1 얇은 파이프라인 회귀 — 발행자 → ingest → Kafka → 저장 sink / WS.

검증 방침(계획 §5): Phase 1부터 pytest로 "가짜 발행자 → 파이프라인 → 예상 저장/중계"를 건다.
**음성 대조를 반드시 포함한다** — 검증이 무력하지 않은지(무효 입력을 실제로 거부하는지) 본다
(CLAUDE.md §3).

전제:
- `ingest`·저장 sink·WS echo가 **먼저 떠 있어야** 한다(구독이 먼저, 발행이 나중).
- Mosquitto·Kafka 가동은 전제다(둘은 Phase 1 파이프라인의 필수 요소라 skip 대상이 아니다).
- 접속 정보는 환경변수로 준다(`tests/conftest.py` 표 참조).

implements: BE-C-01, BE-T-01, BE-T-02, BE-T-03, BE-S-01
tests: 계약 fixture 양성/음성, 브릿지 왕복, 불합격 격리, sink 도달, WS 도달
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest

import publisher

STATE_TOPIC = "mk2.telemetry.state"


# ── 파일 기반 확인 헬퍼 (격리·sink 는 파이프라인이 도는 곳의 파일이다) ──────────


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _wait_for_record(path: Path, offset: int, predicate: Callable[[Dict[str, Any]], bool],
                     timeout: float) -> Optional[Dict[str, Any]]:
    """`offset` 이후에 추가된 JSONL 기록 중 조건에 맞는 것을 기다린다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            with path.open("rb") as fp:
                fp.seek(offset)
                for raw_line in fp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if predicate(record):
                        return record
        time.sleep(0.5)
    return None


# ── 계약 검증 자체 (인프라 없이도 도는 단위 확인) ────────────────────────────


def test_contract_fixtures() -> None:
    """계약 fixture 양성/음성 — 봉투 검증기가 실제로 거부하는지 본다."""
    from backend.ingest.envelope import EnvelopeInvalid, validate_envelope
    from backend import settings

    examples = settings.contracts_dir() / "examples"
    valid = json.loads((examples / "envelope-valid.json").read_text(encoding="utf-8"))
    validate_envelope(valid)  # 양성: 예외 없이 통과

    missing_zone = json.loads((examples / "envelope-invalid-missing-zone.json").read_text(encoding="utf-8"))
    with pytest.raises(EnvelopeInvalid) as excinfo:
        validate_envelope(missing_zone)
    assert "zone_id" in str(excinfo.value)

    bad_timestamp = json.loads((examples / "envelope-invalid-timestamp.json").read_text(encoding="utf-8"))
    with pytest.raises(EnvelopeInvalid) as excinfo:
        validate_envelope(bad_timestamp)
    assert "timestamp" in str(excinfo.value)


# ── 관통 (양성) ────────────────────────────────────────────────────────────


def test_valid_roundtrip(kafka_reader, broker, timeout_s) -> None:
    """발행 → `mk2.telemetry.state` 에 key=source_id·동일 value 도착."""
    reader = kafka_reader([STATE_TOPIC])  # 구독·할당이 끝난 뒤에 발행한다
    source_id = publisher.unique_source_id()
    payload = publisher.make_state_message(source_id=source_id, sequence_id=1)
    publisher.publish(publisher.topic_for("state", eid=source_id), payload, host=broker["host"], port=broker["port"])

    msg = reader.wait_for(
        lambda m: json.loads(m.value().decode("utf-8")).get("source_id") == source_id,
        timeout=timeout_s,
    )
    assert msg is not None, f"{STATE_TOPIC} 에 도착하지 않았다 (ingest가 떠 있고 구독했는지 확인)"
    assert msg.key() is not None and msg.key().decode("utf-8") == source_id, "파티션 키가 source_id가 아니다"
    assert json.loads(msg.value().decode("utf-8")) == payload, "value가 발행 원본과 다르다(정규화 금지)"


def test_storage_sink_receives(broker, sink_path, timeout_s) -> None:
    """팬아웃 ① — 저장 그룹(`mk2-storage`)이 `store(...)`로 받아 기록한다."""
    offset = _size(sink_path)
    source_id = publisher.unique_source_id()
    payload = publisher.make_state_message(source_id=source_id, sequence_id=2)
    publisher.publish(publisher.topic_for("state", eid=source_id), payload, host=broker["host"], port=broker["port"])

    record = _wait_for_record(
        sink_path,
        offset,
        lambda rec: rec.get("message", {}).get("source_id") == source_id,
        timeout=timeout_s,
    )
    assert record is not None, f"저장 sink 기록({sink_path})에 나타나지 않았다"
    assert record["channel"] == "state"
    assert record["message"] == payload


def test_ws_delivery(broker, ws_url, timeout_s) -> None:
    """팬아웃 ② — WS 그룹(`mk2-ws`)이 연결된 클라이언트에 push 한다."""
    try:  # 서버 쪽과 같은 이유로 구현 모듈을 직접 가리킨다(websockets 13+)
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:  # pragma: no cover — websockets 12 이하
        from websockets import connect as ws_connect  # type: ignore[attr-defined]

    source_id = publisher.unique_source_id()
    payload = publisher.make_state_message(source_id=source_id, sequence_id=3)

    async def run() -> Optional[Dict[str, Any]]:
        async with ws_connect(ws_url, open_timeout=10) as client:
            # 접속(구독)이 먼저, 발행이 나중.
            publisher.publish(
                publisher.topic_for("state", eid=source_id), payload, host=broker["host"], port=broker["port"]
            )
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(client.recv(), timeout=max(1.0, deadline - time.time()))
                except asyncio.TimeoutError:
                    return None
                data = json.loads(raw)
                if data.get("message", {}).get("source_id") == source_id:
                    return data
        return None

    received = asyncio.run(run())
    assert received is not None, f"WS({ws_url})로 도달하지 않았다"
    assert received["channel"] == "state"
    assert received["key"] == source_id
    assert received["message"] == payload


# ── 음성 대조 (불합격은 토픽에 뜨지 않고 격리된다) ──────────────────────────


@pytest.mark.parametrize(
    "kind, expected_reason",
    [("missing-zone", "zone_id"), ("timestamp", "timestamp")],
)
def test_invalid_quarantined(kind, expected_reason, kafka_reader, broker, quarantine_path, timeout_s) -> None:
    """봉투 불합격은 **정상 토픽으로 재발행되지 않고** 격리 파일에 사유와 함께 남는다."""
    reader = kafka_reader([STATE_TOPIC])
    offset = _size(quarantine_path)
    source_id = publisher.unique_source_id(prefix=f"wl-bad-{kind}")
    payload = publisher.load_invalid(kind, source_id=source_id)
    publisher.publish(publisher.topic_for("state", eid=source_id), payload, host=broker["host"], port=broker["port"])

    record = _wait_for_record(
        quarantine_path,
        offset,
        lambda rec: source_id in rec.get("raw", ""),
        timeout=timeout_s,
    )
    assert record is not None, f"격리 기록({quarantine_path})에 남지 않았다"
    assert expected_reason in record["reason"], f"격리 사유가 기대와 다르다: {record['reason']}"
    assert record["topic"].endswith("/state")

    absence_window = max(5.0, timeout_s / 2)
    leaked = reader.wait_for(
        lambda m: source_id in m.value().decode("utf-8", errors="replace"),
        timeout=absence_window,
    )
    assert leaked is None, f"불합격 메시지가 {STATE_TOPIC} 로 새어 나갔다"
