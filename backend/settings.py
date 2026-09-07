"""배포 프로파일 설정 — 접속 주소와 토픽 이름 규약(환경변수 단일 출처).

상위 로직은 여기서 얻은 "목적 수준 값"만 쓰고, 브로커·저장 제품의 클라이언트를 직접 만들지
않는다(CLAUDE.md 원칙 1). 접속 정보는 코드에 박지 않고 환경변수로 주입한다 — 배포 대상이
바뀌어도 코드가 바뀌지 않아야 하기 때문이다. **백엔드 모듈과 tests가 같은 이 표를 참조한다**
(두 벌이 되면 조용히 갈라진다).

| 환경변수 | 기본값 | 누가 쓰나 |
|---|---|---|
| `MK2_MQTT_HOST` / `MK2_MQTT_PORT` | `localhost` / `1883` | ingest — **서버 안에서** Mosquitto에 붙는다 |
| `MK2_BROKER_HOST` / `MK2_BROKER_PORT` | `210.110.250.33` / `1883` | 발행자(tests·실노드) — **브로커 바깥에서** 서버 Mosquitto에 붙는다 |
| `MK2_KAFKA_BOOTSTRAP` | `localhost:9092` | ingest·저장 sink·WS — Kafka는 서버 localhost 전용 |
| `MK2_WS_HOST` / `MK2_WS_PORT` | `127.0.0.1` / `8765` | WS echo 서버가 바인딩할 주소 |
| `MK2_WS_URL` | `ws://127.0.0.1:8765` | WS 클라이언트(tests·콘솔)가 붙을 주소 |
| `MK2_QUARANTINE_PATH` | `backend/ingest/quarantine.jsonl` | 봉투 불합격 격리 기록(런타임 산출물) |
| `MK2_SINK_PATH` | `backend/storage/telemetry_sink.jsonl` | 저장 placeholder 기록(런타임 산출물) |
| `MK2_CONTRACTS_DIR` | `contracts/common` | 봉투 계약(JSON Schema) 위치 |

ingest와 발행자가 같은 브로커를 서로 다른 이름으로 가리키는 이유: ingest는 브로커와 같은
머신(서버)에 있어 `localhost`이고, 발행자는 말단/엣지 위치라 서버 주소로 붙는다. 실제 배치와
같은 방향이며, 그래서 발행자↔브로커 네트워크 경로가 함께 검증된다.

토픽 규약(Phase 1 확정): 채널별 3토픽 `mk2.telemetry.<채널>`. 점 구분 소문자이며 언더스코어를
섞지 않는다(Kafka 메트릭 이름 변환 충돌 회피). 장치별 토픽이 아니다 — `zone_id`·`source_id`는
봉투 안에 있고 토픽 이름에 넣지 않는다.

implements: BE-T-01, BE-T-02, BE-T-03
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

# 말단이 발행하는 텔레메트리 채널. 명령(terminal/*)은 여기에 없다 — 다른 프로토콜이며 Phase 6.
TELEMETRY_CHANNELS: Tuple[str, ...] = ("state", "status", "heartbeat")

TOPIC_PREFIX = "mk2.telemetry."


def repo_root() -> Path:
    """저장소 루트. `backend/settings.py` 기준 한 단계 위."""
    return Path(__file__).resolve().parents[1]


def topic_for_channel(channel: str) -> str:
    """MQTT 채널 → Kafka 토픽. 계약에 없는 채널은 만들지 않는다."""
    if channel not in TELEMETRY_CHANNELS:
        raise ValueError(f"텔레메트리 채널이 아니다: {channel!r}")
    return TOPIC_PREFIX + channel


def telemetry_topics() -> List[str]:
    return [topic_for_channel(ch) for ch in TELEMETRY_CHANNELS]


def channel_of_mqtt_topic(mqtt_topic: str) -> str:
    """`{zone}/{etype}/{eid}/{channel}` 의 말단 세그먼트를 채널로 본다."""
    return mqtt_topic.rsplit("/", 1)[-1]


# ── 접속 정보 (환경변수 주입) ───────────────────────────────────────────────
# ingest·sink·WS는 서버에서 돌므로 기본값이 서버 localhost다. 발행자(tests·실노드)는 브로커
# 바깥에서 붙으므로 서버 주소를 기본값으로 둔다.

DEFAULT_BROKER_HOST = "210.110.250.33"  # 서버 Mosquitto (익명, 1883)


def mqtt_host() -> str:
    """ingest가 붙을 브로커 — 서버 안에서 돌므로 localhost."""
    return os.environ.get("MK2_MQTT_HOST", "localhost")


def mqtt_port() -> int:
    return int(os.environ.get("MK2_MQTT_PORT", "1883"))


def broker_host() -> str:
    """발행자가 붙을 브로커 — 말단/엣지 위치라 서버 주소."""
    return os.environ.get("MK2_BROKER_HOST", DEFAULT_BROKER_HOST)


def broker_port() -> int:
    return int(os.environ.get("MK2_BROKER_PORT", "1883"))


def kafka_bootstrap() -> str:
    return os.environ.get("MK2_KAFKA_BOOTSTRAP", "localhost:9092")


def ws_host() -> str:
    """WS echo 서버 바인딩 주소. 기본은 서버 localhost — 외부 노출을 만들지 않는다."""
    return os.environ.get("MK2_WS_HOST", "127.0.0.1")


def ws_port() -> int:
    return int(os.environ.get("MK2_WS_PORT", "8765"))


def ws_url() -> str:
    """WS 클라이언트(tests·콘솔)가 붙을 주소.

    기본 바인딩(127.0.0.1)과 표기를 맞춘다 — `localhost`는 환경에 따라 IPv6(::1)로 먼저
    풀려 127.0.0.1 전용 바인딩과 어긋날 수 있다.
    """
    return os.environ.get("MK2_WS_URL", "ws://127.0.0.1:{}".format(ws_port()))


def quarantine_path() -> Path:
    """봉투 검증 불합격 메시지 격리 파일(런타임 산출물, gitignore)."""
    return Path(os.environ.get("MK2_QUARANTINE_PATH", str(repo_root() / "backend" / "ingest" / "quarantine.jsonl")))


def sink_path() -> Path:
    """Phase 1 저장 placeholder 기록 파일(런타임 산출물, gitignore). Phase 2에서 TSDB로 교체."""
    return Path(os.environ.get("MK2_SINK_PATH", str(repo_root() / "backend" / "storage" / "telemetry_sink.jsonl")))


def contracts_dir() -> Path:
    """공통 계약(JSON Schema) 디렉터리. 파트 경계의 정본."""
    return Path(os.environ.get("MK2_CONTRACTS_DIR", str(repo_root() / "contracts" / "common")))
