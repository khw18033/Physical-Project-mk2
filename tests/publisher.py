"""계약에 맞춘 최소 발행 스크립트 (테스트 헬퍼 겸 수동 확인용).

**발행 위치는 컴퓨터다.** 발행자는 MQTT만 쏘고 Kafka를 모르므로, 컴퓨터에서 실행해 서버
Mosquitto로 발행한다 — 실제 배치(발행자=말단/엣지, 브로커=서버)와 같은 방향이라 발행자↔브로커
네트워크 경로까지 함께 검증된다. 그래서 이 파일은 `paho-mqtt`와 표준 라이브러리만 쓴다
(백엔드 패키지·Kafka 의존 없음).

브로커 주소는 하드코딩하지 않고 `backend/settings.py`의 환경변수 표를 그대로 참조한다:
`MK2_BROKER_HOST`(기본 `210.110.250.33`), `MK2_BROKER_PORT`(기본 `1883`). `settings`는
표준 라이브러리만 쓰므로, 이 파일을 컴퓨터에서 돌릴 때 필요한 것은 여전히 `paho-mqtt`뿐이다.

**구독이 먼저, 발행이 나중** — ingest 로그에 `READY` 가 뜬 뒤에 발행한다. 클린 세션 ingest는
구독 전에 발행된 메시지를 받지 못한다.

수동 실행:
    python tests/publisher.py                       # zoneA/sensor/wl-001/state 로 1건
    python tests/publisher.py --count 5 --interval 1
    python tests/publisher.py --invalid missing-zone   # 격리 확인용(음성)

implements: BE-C-01, BE-T-01
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import paho.mqtt.publish as mqtt_publish

# 저장소를 그대로 복사해 쓰는 배치에서도 `backend.settings`를 찾도록(설치 없이 실행 가능).
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend import settings  # noqa: E402  (위 sys.path 보정 뒤에 import)

DEFAULT_ZONE = "zoneA"
DEFAULT_ETYPE = "sensor"
DEFAULT_EID = "wl-001"
DEFAULT_NODE_ID = "pi7"

EXAMPLES_DIR = settings.contracts_dir() / "examples"
INVALID_FIXTURES = {
    "missing-zone": EXAMPLES_DIR / "envelope-invalid-missing-zone.json",
    "timestamp": EXAMPLES_DIR / "envelope-invalid-timestamp.json",
}


def broker_host() -> str:
    return settings.broker_host()


def broker_port() -> int:
    return settings.broker_port()


def iso_now() -> str:
    """RFC3339 콜론 오프셋(+09:00). 계약의 date-time 포맷 정합."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def unique_source_id(prefix: str = "wl-test") -> str:
    """테스트 간 교차 수신을 막기 위한 1회용 논리 식별자."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def topic_for(channel: str, zone: str = DEFAULT_ZONE, etype: str = DEFAULT_ETYPE, eid: str = DEFAULT_EID) -> str:
    """HW 토픽 구조 `{zone}/{etype}/{eid}/{channel}`."""
    return f"{zone}/{etype}/{eid}/{channel}"


def make_state_message(
    source_id: str = DEFAULT_EID,
    node_id: str = DEFAULT_NODE_ID,
    zone_id: str = DEFAULT_ZONE,
    sequence_id: int = 1,
    water_level_m: float = 2.53,
) -> Dict[str, Any]:
    """봉투 필수 5필드 + 선택 필드 + `state` 채널 본문."""
    return {
        "schema_version": "1.0",
        "source_id": source_id,
        "entity_id": source_id,
        "node_id": node_id,
        "zone_id": zone_id,
        "timestamp": iso_now(),
        "sequence_id": sequence_id,
        "origin_kind": "real",
        "channel": "state",
        "water_level_m": water_level_m,
        "unit": "m",
        "alert": False,
        "reason": "periodic",
    }


def load_invalid(kind: str, source_id: Optional[str] = None) -> Dict[str, Any]:
    """음성 대조 fixture를 읽는다. `source_id`만 1회용으로 바꿔 추적 가능하게 한다."""
    payload = json.loads(INVALID_FIXTURES[kind].read_text(encoding="utf-8"))
    if source_id:
        payload["source_id"] = source_id
        if "entity_id" in payload:
            payload["entity_id"] = source_id
    return payload


def publish(
    topic: str,
    payload: Dict[str, Any],
    host: Optional[str] = None,
    port: Optional[int] = None,
    qos: int = 1,
    retain: bool = False,
) -> Dict[str, Any]:
    """서버 Mosquitto로 1건 발행하고, 발행한 payload를 그대로 돌려준다."""
    mqtt_publish.single(
        topic,
        payload=json.dumps(payload, ensure_ascii=False),
        qos=qos,
        retain=retain,
        hostname=host or broker_host(),
        port=port if port is not None else broker_port(),
        client_id=f"mk2-pub-{uuid.uuid4().hex[:8]}",  # 노드 client_id와 겹치지 않게
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="MK2 최소 발행자 (계약 봉투 → 서버 Mosquitto)")
    parser.add_argument("--host", default=broker_host())
    parser.add_argument("--port", type=int, default=broker_port())
    parser.add_argument("--zone", default=DEFAULT_ZONE)
    parser.add_argument("--etype", default=DEFAULT_ETYPE)
    parser.add_argument("--eid", default=DEFAULT_EID)
    parser.add_argument("--channel", default="state", choices=["state", "status", "heartbeat"])
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--invalid", choices=sorted(INVALID_FIXTURES), help="음성 대조 fixture를 발행한다")
    args = parser.parse_args()

    topic = topic_for(args.channel, args.zone, args.etype, args.eid)
    for i in range(args.count):
        if args.invalid:
            payload = load_invalid(args.invalid)
        else:
            payload = make_state_message(source_id=args.eid, zone_id=args.zone, sequence_id=i + 1)
            payload["channel"] = args.channel
        publish(topic, payload, host=args.host, port=args.port)
        print(f"published → {args.host}:{args.port} {topic} :: {json.dumps(payload, ensure_ascii=False)}")
        if i + 1 < args.count:
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
