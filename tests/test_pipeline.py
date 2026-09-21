"""Phase 1 얇은 파이프라인 회귀 — 발행자 → ingest → Kafka → 저장 sink / WS.

검증 방침(계획 §5): Phase 1부터 pytest로 "가짜 발행자 → 파이프라인 → 예상 저장/중계"를 건다.
**음성 대조를 반드시 포함한다** — 검증이 무력하지 않은지(무효 입력을 실제로 거부하는지) 본다
(CLAUDE.md §3).

전제:
- `ingest`·저장 sink·WS echo가 **먼저 떠 있어야** 한다(구독이 먼저, 발행이 나중).
- Mosquitto·Kafka 가동은 전제다(둘은 Phase 1 파이프라인의 필수 요소라 skip 대상이 아니다).
- 접속 정보는 환경변수로 준다(`tests/conftest.py` 표 참조).

implements: BE-C-01, BE-T-01, BE-T-02, BE-T-03, BE-S-01
tests: 공통 규격 fixture 양성/음성, `session_id` 선택 필드(양성 2 + 음성 1),
       브릿지 왕복, 공통 헤더(1단) 불합격 격리, **본문(2단) 불합격 격리**, sink 도달, WS 도달
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


def test_session_id_optional() -> None:
    """규격 1.1 — `session_id`가 **있는 메시지와 없는 메시지가 둘 다** 통과한다.

    선택 필드이므로 보내는 생산자와 안 보내는 생산자가 공존하는 것이 정상 상태다
    (하드웨어는 아직 보내지 않는다). 규격 버전이 1.1로 올랐다고 `"1.0"`을 선언하는
    실노드가 격리되면 그 순간 전량이 사라지므로, 옛 표기가 통과하는 것까지 함께 본다.

    음성 대조도 붙인다 — 빈 문자열이 통과하면 `minLength: 1`이 무력한 것이다.
    """
    from backend.ingest.envelope import EnvelopeInvalid, validate_envelope
    from backend import settings

    examples = settings.contracts_dir() / "examples"
    without = json.loads((examples / "envelope-valid.json").read_text(encoding="utf-8"))
    with_session = json.loads((examples / "envelope-valid-session.json").read_text(encoding="utf-8"))

    assert "session_id" not in without, "이 fixture는 session_id가 없는 쪽이어야 한다"
    assert with_session["session_id"], "이 fixture는 session_id가 있는 쪽이어야 한다"

    validate_envelope(without)       # 양성 ① — 없이도 통과
    validate_envelope(with_session)  # 양성 ② — 있어도 통과

    # 혼재 기간: 옛 버전 표기(1.0)도 통과해야 한다.
    validate_envelope(dict(with_session, schema_version="1.0"))

    # 음성: 빈 문자열은 거부되어야 한다.
    with pytest.raises(EnvelopeInvalid) as excinfo:
        validate_envelope(dict(with_session, session_id=""))
    assert "session_id" in str(excinfo.value)


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


def test_ws_delivery_vz_wire(broker, ws_url, timeout_s) -> None:
    """팬아웃 ②-b — **구독을 보낸 클라이언트**는 VZ 와이어 계약으로 받는다.

    위 `test_ws_delivery` 와 **같은 경로를 같은 소켓 계층으로** 지나되, 접속 직후 `subscribe` 를
    한 줄 보낸다는 것만 다르다. 그러면 같은 발행이 `{channel, topic, key, message}` 가 아니라
    `{type:"data", sub, envelope}` 로 온다 — **이중 형식이 진짜 소켓에서도 갈리는지**가 판정이다
    (실측대비 v2 §3-1-1. 소켓 없는 단위 검증은 `tests/test_ws_state_wire.py`).

    선택자는 **VZ 가 실제로 보내는 모양 그대로**다 — `{entity:'*', node:<구역>, channel:'*'}`
    (`viz-debugger/src/tabs/data/index.ts`). ⚠ `node` 축에 **구역 식별자**가 온다. VZ 주석의 규약이고
    서버가 그것을 받도록 맞췄다 — 이 조건이 깨지면 **연결은 되고 화면만 비는** 실패가 된다.
    """
    try:
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:  # pragma: no cover — websockets 12 이하
        from websockets import connect as ws_connect  # type: ignore[attr-defined]

    source_id = publisher.unique_source_id()
    payload = publisher.make_state_message(source_id=source_id, sequence_id=4)
    selector = {"entity": "*", "node": payload["zone_id"], "channel": "*"}

    async def run() -> Optional[Dict[str, Any]]:
        async with ws_connect(ws_url, open_timeout=10) as client:
            await client.send(json.dumps(
                {"type": "subscribe", "id": "sub-1", "selector": selector, "scope": "all"}))
            # ⚠ 구독은 서버의 수신 루프가 **비동기로** 처리한다(접속처럼 즉시가 아니다).
            #    반영 전에 발행하면 그 한 건을 놓치므로 잠깐 기다렸다 발행한다.
            await asyncio.sleep(0.5)
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
                # 🔴 구독한 소켓에는 지금 형식이 섞여 오면 안 된다(이중 형식이 갈리는 자리).
                assert data.get("type") == "data", f"구독했는데 지금 형식이 왔다: {sorted(data)}"
                if data["envelope"]["payload"].get("source_id") == source_id:
                    return data
        return None

    received = asyncio.run(run())
    assert received is not None, f"WS({ws_url})로 VZ 형식이 도달하지 않았다"
    assert received["sub"] == "sub-1", "VZ 가 붙인 구독 ID 를 그대로 돌려줘야 찾을 수 있다"
    env = received["envelope"]
    assert set(env) == {"zone", "node", "entity", "channel", "ts", "seq",
                        "payload", "quality", "aggregation", "scope", "coordinate_frame"}
    assert env["channel"] == "state"
    assert env["zone"] == payload["zone_id"]
    assert env["node"] == payload["node_id"]
    assert env["entity"] == source_id          # entity_id 가 없으면 source_id 가 개체를 가리킨다
    assert env["ts"] == payload["timestamp"]
    assert env["seq"] == payload["sequence_id"]
    assert env["payload"] == payload           # 봉투를 통째로 싣는다(걷어내지 않는다)
    assert env["scope"] == "all"               # 구독 요청의 값을 되돌려준다
    # 잠정값 셋 — 진짜 값이 아니다(Phase 5 에서 바뀐다). 바뀌면 여기가 먼저 걸린다.
    assert (env["quality"], env["aggregation"], env["coordinate_frame"]) == ("good", "raw", None)


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


def test_payload_invalid_quarantined(kafka_reader, broker, quarantine_path, timeout_s) -> None:
    """★음성 — **본문(2단) 불합격도 토픽에 나타나지 않고 격리된다.**

    위 `test_invalid_quarantined`가 보는 것은 1단(공통 헤더)이다. Phase 2가 새로 켠 것은
    2단(채널 본문)이고, **그 둘은 다른 검증기다** — 1단만 보면 "본문 검증이 실제로 무는가"를
    말할 수 없다. 저장 층이 값의 존재를 가정할 수 있으려면 필수 누락은 막혀야 한다.

    본문 규격은 타입별이므로 **토픽 2번째 칸(etype)이 맞아야** 의도한 검증기가 걸린다.
    로봇 본문 fixture를 sensor 토픽으로 쏘면 다른 스키마에 걸려 이 테스트가 다른 것을 본다.
    """
    kind = "payload-missing-device-status"
    etype = publisher.INVALID_ETYPE[kind]
    reader = kafka_reader([STATE_TOPIC])
    offset = _size(quarantine_path)
    source_id = publisher.unique_source_id(prefix="wl-bad-payload")
    payload = publisher.load_invalid(kind, source_id=source_id)

    # 공통 헤더는 통과해야 한다 — 1단에서 걸리면 2단을 확인하지 못한 것이다.
    from backend.ingest.envelope import validate_envelope

    validate_envelope(payload)

    publisher.publish(
        publisher.topic_for("state", etype=etype, eid=source_id),
        payload, host=broker["host"], port=broker["port"],
    )

    record = _wait_for_record(
        quarantine_path,
        offset,
        lambda rec: source_id in rec.get("raw", ""),
        timeout=timeout_s,
    )
    assert record is not None, f"본문 불합격이 격리 기록({quarantine_path})에 남지 않았다"
    assert "device_status" in record["reason"], f"격리 사유가 기대와 다르다: {record['reason']}"
    assert "본문" in record["reason"], f"1단이 아니라 2단에서 걸려야 한다: {record['reason']}"
    assert record["topic"] == f"zoneA/{etype}/{source_id}/state"

    absence_window = max(5.0, timeout_s / 2)
    leaked = reader.wait_for(
        lambda m: source_id in m.value().decode("utf-8", errors="replace"),
        timeout=absence_window,
    )
    assert leaked is None, f"본문 불합격 메시지가 {STATE_TOPIC} 로 새어 나갔다"
