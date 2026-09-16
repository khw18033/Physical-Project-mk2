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

저장 축(Phase 2). 접속 정보는 전부 여기서만 읽고, 저장 제품 클라이언트는 목적 인터페이스
(`TelemetryWriter.write()` · `RegistryWriter.observe()`) 뒤에서만 만든다(원칙 1).

| 환경변수 | 기본값 | 누가 쓰나 |
|---|---|---|
| `MK2_MYSQL_HOST` / `MK2_MYSQL_PORT` | `127.0.0.1` / `7858` | 감사·레지스트리·임무 실행 기록 |
| `MK2_MYSQL_DB` / `MK2_MYSQL_USER` | `mk2` / `mk2_app` | 〃 |
| `MK2_MYSQL_PASSWORD` | **기본값 없음(필수)** | 〃 — 없으면 기동을 실패시킨다 |
| `MK2_TSDB_HOST` / `MK2_TSDB_PORT` | `127.0.0.1` / `7859` | 계측 시계열 |
| `MK2_TSDB_DB` / `MK2_TSDB_USER` | `mk2` / `mk2_app` | 〃 |
| `MK2_TSDB_PASSWORD` | **기본값 없음(필수)** | 〃 |
| `MK2_STORE_TZ` | `UTC` | 저장 시각 기준. 접속 시 세션 타임존으로 명시한다 |
| `MK2_TELEMETRY_WRITERS` | `tsdb,jsonl` | 저장 소비자가 쓸 구현 목록. `tsdb`=운영 저장, `jsonl`=관측용 흔적 |
| `MK2_REGISTRY` | `mysql` | 레지스트리 관측 축 쓰기. `none`이면 끈다(명시적으로만) |

**비밀번호에 기본값을 두지 않는 이유:** 기본값이 있으면 환경변수를 빠뜨린 채 기동해서
"왜 인증이 안 되지"를 한참 뒤에 알게 된다. 없으면 기동 시점에 이름을 대며 죽는다.

관측(Phase 3). OTel SDK 호출은 `backend/observability.py` 뒤에만 있고, ingest·저장 소비자·WS는
목적 인터페이스(`count`·`gauge`·`observe`·`log_handler`)만 안다(원칙 1).

| 환경변수 | 기본값 | 누가 쓰나 |
|---|---|---|
| `MK2_OTEL_ENDPOINT` | `http://127.0.0.1:4316` | 관측 발신 대상(서버 Collector). **빈 문자열이면 계측 전체 no-op** — 업무 경로는 그대로 돈다(제약 20) |
| `MK2_OTEL_EXPORT_INTERVAL` | `15` (초) | metric export 주기. HW `otel_metrics.py`와 같은 값. 검증 중에는 낮춰 즉시 확인 |
| `MK2_OTEL_SERVICE_NAME` | 프로세스별(`be-ingest`·`be-storage`·`be-gateway`) | `service.name`. 비우면 프로세스 기본값 |

**관측이 업무의 전제조건이 아니다.** SDK 미설치·엔드포인트 미설정·Collector 장애 어느 경우에도
백엔드는 계측 없이 계속 돈다 — 비밀번호와 달리 여기서는 기동을 실패시키지 않는다.

**세션 타임존을 접속 시 명시하는 이유:** MySQL 은 `system_tz=KST` 이고 컨테이너 `TZ` 설정에
따라 실효값이 달라진다. 컨테이너 설정이 바뀌면 과거 데이터 해석이 통째로 흔들리므로
컨테이너 값에 기대지 않고 접속마다 못 박는다(MySQL `SET time_zone='+00:00'`,
PostgreSQL `SET TIME ZONE 'UTC'`).

ingest와 발행자가 같은 브로커를 서로 다른 이름으로 가리키는 이유: ingest는 브로커와 같은
머신(서버)에 있어 `localhost`이고, 발행자는 말단/엣지 위치라 서버 주소로 붙는다. 실제 배치와
같은 방향이며, 그래서 발행자↔브로커 네트워크 경로가 함께 검증된다.

토픽 규약(Phase 1 확정): 채널별 3토픽 `mk2.telemetry.<채널>`. 점 구분 소문자이며 언더스코어를
섞지 않는다(Kafka 메트릭 이름 변환 충돌 회피). 장치별 토픽이 아니다 — `zone_id`·`source_id`는
봉투 안에 있고 토픽 이름에 넣지 않는다.

implements: BE-T-01, BE-T-02, BE-T-03, BE-S-02(관측 환경변수)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple

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


def entity_type_of_mqtt_topic(mqtt_topic: str) -> Optional[str]:
    """`{zone}/{etype}/{eid}/{channel}` 의 **2번째 칸**을 개체 타입으로 본다.

    구독 패턴이 `+/+/+/{channel}` 4칸이므로 `parts[1]`이 etype이다. 4칸이 아니면 이
    규약의 토픽이 아니므로 `None`을 돌려주고, 호출부는 타입별 본문 검증을 건너뛴다.

    **etype은 여기서만 알 수 있다.** Kafka 토픽은 `mk2.telemetry.<채널>`이라 채널만
    담고 etype을 담지 않는다(Phase 1 확정 규약이라 바꾸지 않는다). 그래서 ingest가
    파싱한 값을 Kafka 헤더로 실어 저장 층에 넘긴다 — 저장 층이 레지스트리를 조회해
    타입을 알아내려 하면 닭-달걀이 된다(대장에 없는 새 노드가 첫 메시지부터 막힌다).

    토픽 의존은 새로 느는 것이 아니다. `channel_of_mqtt_topic()`이 이미 토픽을 쪼개고
    있고, 4칸 구조와 etype 어휘 4종은 `docs/be/hw-envelope-conformance.md` §2-1·2-3에서
    이미 확정으로 회신해 두었다.
    """
    parts = mqtt_topic.split("/")
    if len(parts) != 4:
        return None
    return parts[1] or None


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


# ── 저장 축 접속 정보 (Phase 2) ─────────────────────────────────────────────
# 여기 있는 것은 "어디에 붙나"뿐이다. 어떤 제품인지는 저장 구현이 알고, 상위 로직은
# 목적 인터페이스만 안다(원칙 1). 그래서 이 파일에 psycopg·PyMySQL import 가 없다.


class MissingSetting(RuntimeError):
    """필수 환경변수가 없다.

    기본값을 만들어 넘어가지 않고 기동을 실패시킨다 — 비밀번호에 기본값이 있으면
    환경변수를 빠뜨린 채 떠서 한참 뒤에 인증 실패로 발견된다.
    """


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise MissingSetting(
            f"환경변수 {name} 가 없다. 서버의 /home/dg/capstone-db/.env 를 읽어 주입한다"
            f"(예: `set -a; . ~/capstone-db/.env; set +a`)."
        )
    return value


def store_tz() -> str:
    """저장 시각 기준. 접속 시 세션 타임존으로 명시한다(컨테이너 TZ 에 기대지 않는다)."""
    return os.environ.get("MK2_STORE_TZ", "UTC")


def utc_now_iso() -> str:
    """**백엔드가 찍는 시각의 표준 형태** — UTC, 마이크로초.

    ingest(`ingest_at`)와 저장 소비자(`received_at`)가 같은 형태로 찍어야 두 값을 그대로
    빼서 지연을 얻을 수 있다. 그래서 각자 만들지 않고 여기 한 곳에 둔다.

    - **로컬 오프셋이 아니라 UTC로 찍는 이유:** 저장 기준이 UTC이고, 서버 시간대 설정이
      바뀌어도 값의 해석이 흔들리지 않아야 한다.
    - **마이크로초까지 두는 이유:** 말단 `timestamp`가 초 해상도라(HW `iso_now()`),
      `lag_s`의 정밀도가 이쪽에 달려 있다.
    """
    from datetime import datetime, timezone  # 지역 import — settings 는 표준 라이브러리만 쓴다

    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# MySQL — 감사 · 레지스트리 · 임무 실행 기록
# 드라이버는 PyMySQL(순수 파이썬). 서버 Python 3.14 에서 mysqlclient(C 확장)는 빌드에
# 실패했고 PyMySQL 1.2.0 은 설치된다(2026-09-10 서버 실측).


def mysql_host() -> str:
    return os.environ.get("MK2_MYSQL_HOST", "127.0.0.1")


def mysql_port() -> int:
    return int(os.environ.get("MK2_MYSQL_PORT", "7858"))


def mysql_db() -> str:
    return os.environ.get("MK2_MYSQL_DB", "mk2")


def mysql_user() -> str:
    return os.environ.get("MK2_MYSQL_USER", "mk2_app")


def mysql_password() -> str:
    """기본값 없음 — 없으면 MissingSetting."""
    return _required("MK2_MYSQL_PASSWORD")


# TimescaleDB — 계측 시계열
# 드라이버는 psycopg 3(binary). cp314 휠 설치 확인됨(2026-09-10 서버 실측).


def tsdb_host() -> str:
    return os.environ.get("MK2_TSDB_HOST", "127.0.0.1")


def tsdb_port() -> int:
    return int(os.environ.get("MK2_TSDB_PORT", "7859"))


def tsdb_db() -> str:
    return os.environ.get("MK2_TSDB_DB", "mk2")


def tsdb_user() -> str:
    return os.environ.get("MK2_TSDB_USER", "mk2_app")


def tsdb_password() -> str:
    """기본값 없음 — 없으면 MissingSetting."""
    return _required("MK2_TSDB_PASSWORD")


def telemetry_writers() -> List[str]:
    """저장 소비자가 쓸 저장 구현 목록. 기본은 `tsdb,jsonl` 둘 다.

    - `tsdb` — **운영 저장.** 계측의 원본이며 조회·되감기·학습 재료가 여기서 나온다.
    - `jsonl` — **관측용 흔적.** 파이프라인이 무엇을 받았는지 눈으로 보는 자리이자 Phase 1
      부터의 회귀 테스트가 읽는 자리다.

    ⚠ 이 값을 바꾸는 것은 **명시적 선택**이어야 한다. TSDB 접속이 안 될 때 자동으로 `jsonl`
    로 떨어지게 만들지 않는다 — 데이터가 파일로 가는데 아무도 모른 채 며칠이 지난다.
    """
    raw = os.environ.get("MK2_TELEMETRY_WRITERS", "tsdb,jsonl")
    return [name.strip() for name in raw.split(",") if name.strip()]


def registry_writer() -> str:
    """레지스트리 관측 축을 어디에 쓸지. `mysql`(기본) 또는 `none`.

    ⚠ 위와 같은 이유로 **자동 폴백을 두지 않는다.** MySQL 이 없을 때 조용히 `none` 이 되면
    대장이 비어 가는데 아무도 모른다. 끄려면 명시적으로 `none` 을 준다.
    """
    return os.environ.get("MK2_REGISTRY", "mysql").strip()


# ── 관측 (Phase 3) ──────────────────────────────────────────────────────────
# 저장 축과 규칙이 반대다. 저장은 접속 정보가 없으면 죽고, 관측은 없으면 **조용히 no-op** 이다.
# 관측이 업무의 전제조건이 아니기 때문이다(제약 20 — HW otel_metrics.create() 와 같은 규율).

DEFAULT_OTEL_ENDPOINT = "http://127.0.0.1:4316"   # 서버 Collector(Gateway). 호스트 프로세스가 loopback 으로 붙는다


def otel_endpoint() -> str:
    """관측 발신 대상. **빈 문자열이면 계측 전체 no-op.**

    변수가 아예 없으면 기본값(서버 Collector)이고, `MK2_OTEL_ENDPOINT=` 처럼 비워 두면 끈다 —
    "설정을 빠뜨렸다"와 "일부러 껐다"를 갈라야 N3(관측이 죽어도 업무가 산다) 확인이 성립한다.
    """
    return os.environ.get("MK2_OTEL_ENDPOINT", DEFAULT_OTEL_ENDPOINT).strip()


def otel_export_interval() -> float:
    """metric export 주기(초). HW 와 같은 15초가 기본. 검증 중에는 낮춰 즉시 확인한다."""
    return float(os.environ.get("MK2_OTEL_EXPORT_INTERVAL", "15"))


def otel_service_name(default: str) -> str:
    """`service.name`. 프로세스가 자기 기본값(`be-ingest` 등)을 주고, 환경변수가 있으면 그것이 이긴다."""
    return os.environ.get("MK2_OTEL_SERVICE_NAME", "").strip() or default
