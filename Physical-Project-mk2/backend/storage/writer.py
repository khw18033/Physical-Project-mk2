"""계측 저장의 목적 인터페이스와 레코드 정의.

상위(소비자)는 `TelemetryWriter.write(record)` 하나만 안다 — Timescale 같은 저장 제품
클라이언트를 직접 부르지 않는다(CLAUDE.md 원칙 1, 제약 4). **Phase 2에서 이 인터페이스 뒤의
구현만 TSDB로 갈아끼웠고 호출부(ingest·소비자)는 그대로다** — 그러라고 갈라 둔 지점이다.

구현은 둘이다: `tsdb_writer.TimescaleTelemetryWriter`(운영 저장)와 아래 `JsonlTelemetryWriter`
(관측용 흔적). 기본 구성은 `default_writer()` 참조.

`TelemetryRecord`는 백엔드 내부 타입이며 파트 경계로 노출하지 않는다 — 경계의 기준은
`contracts/common/message.schema.json`이다(원칙 9).

## 시각이 셋인 이유

| 시각 | 누가 찍나 | 용도 |
|---|---|---|
| `timestamp`(본문 안) | **말단 노드** | 하이퍼테이블 시간축. 정렬·조회·되감기의 기준 |
| `ingest_at` | **ingest**(`bridge.py`) — Kafka 헤더로 전달 | 서버 도달 시각. `lag_s`의 재료 |
| `received_at` | **저장 소비자**(이 파일의 기본값) | 소비 시각 |

⚠ **`received_at`은 "서버 수신 시각"이 아니다.** 이 값은 저장 소비자가 `TelemetryRecord`를
만드는 순간에 생성되므로, 재기동하거나 오프셋을 리셋하면 **같은 메시지에 다른 값이 찍힌다.**
Phase 1 문서가 이것을 "서버 수신 시각"으로 서술한 것은 틀렸고, 그 자리를 채우려고 `ingest_at`을
신설했다. 지연 측정(`lag_s`)에는 반드시 `ingest_at`을 쓴다.

implements: BE-S-01, BE-S-07(lag_s가 지연 상한의 측정 재료)
tests: tests/test_storage_record.py(파생 값 단위) · tests/test_pipeline.py(sink 도달)
"""

from __future__ import annotations

import abc
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from backend import settings

LOG = logging.getLogger("mk2.storage")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """ISO-8601 문자열 → aware datetime. 못 읽으면 `None`.

    오프셋이 없는 값은 **어느 시각인지 단정할 수 없으므로** `None`으로 돌린다 — 로컬
    시간대로 가정하면 조용히 틀린 `lag_s`가 나온다. 공통 헤더 검증이 RFC3339를 강제하므로
    정상 경로에서는 오지 않지만, 헤더 없는 옛 메시지를 방어한다.
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo is not None else None


@dataclass
class TelemetryRecord:
    """검증을 통과한 공통 헤더+본문과, 어느 채널/스트림 좌표에서 왔는지."""

    channel: str
    topic: str
    message: Dict[str, Any]
    key: Optional[str] = None
    # 저장 소비자가 이 객체를 만든 시각(= 소비 시각). 위 표 참조.
    # ingest 의 `ingest_at` 과 **같은 형태**(UTC·마이크로초)여야 두 값을 그대로 뺄 수 있다.
    received_at: str = field(default_factory=settings.utc_now_iso)

    # ── Kafka 헤더로 실려 오는 것 ────────────────────────────────────────
    # 헤더가 없으면(Phase 1에 쌓인 옛 메시지) 둘 다 None 이며, **그것이 정상이다.**
    # 옛 메시지를 소비해도 죽지 않아야 한다.
    ingest_at: Optional[str] = None
    entity_type: Optional[str] = None

    # ── 스트림 좌표 — 재소비 중복을 막는 유일 키 ────────────────────────
    # 저장 소비자는 auto.offset.reset=earliest + 자동 커밋이라 구조적으로 재소비한다.
    # 업무 내용 키(sequence_id)로는 막을 수 없다 — 로봇은 항상 0, status 에는 없고,
    # 증강 분석은 순번을 대상끼리 공유한다. 재소비는 도착 계층의 현상이므로 도착 좌표로 잡는다.
    stream_partition: Optional[int] = None
    stream_offset: Optional[int] = None

    # ── 원본에서 뽑아 쓰는 값들(계산은 여기서 한 번만) ──────────────────

    @property
    def stream_topic(self) -> str:
        """Kafka 토픽. `topic`과 같은 값이며 저장 칼럼 이름에 맞춘 별칭이다."""
        return self.topic

    @property
    def ts(self) -> Optional[str]:
        """공통 헤더 `timestamp` — 말단이 찍은 발행 시각. 저장의 시간축."""
        return self.message.get("timestamp")

    @property
    def lag_s(self) -> Optional[float]:
        """`ingest_at - ts`(초). 헤더가 없는 옛 메시지는 `None`.

        저장 시점에 계산해 칼럼으로 둔다 — 매 조회마다 빼지 않아도 되고,
        BE-S-07(재난 모드 지연 상한)의 측정 재료가 그대로 생긴다.
        """
        ts = parse_iso(self.ts)
        ingest = parse_iso(self.ingest_at)
        if ts is None or ingest is None:
            return None
        return (ingest - ts).total_seconds()

    @property
    def clock_skew(self) -> bool:
        """말단 시계가 서버보다 앞선 경우(`lag_s < 0`).

        **버리지 않고 그대로 저장하되 플래그만 세운다.** 버리면 재난 데이터가 사라지고,
        조용히 보정하면 저장된 것이 원본이 아니게 된다. 임계는 통합 시험 후 확정한다.
        """
        lag = self.lag_s
        return lag is not None and lag < 0

    @property
    def replayed(self) -> bool:
        """본문의 `replayed` 표식을 그대로 보관한다.

        **지연 도착 판정의 유일한 근거로 쓰지 않는다** — `status`·`heartbeat`는 spool을
        타지 않아 지연돼도 이 표식이 없고, 다운샘플로 솎인 표본은 아예 사라진다.
        판정은 `lag_s`로 하고 이 값은 "생산자가 스스로 재전송이라고 말한 것"이라는 보조 증거다.
        """
        return bool(self.message.get("replayed"))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "received_at": self.received_at,
            "ingest_at": self.ingest_at,
            "lag_s": self.lag_s,
            "clock_skew": self.clock_skew,
            "replayed": self.replayed,
            "channel": self.channel,
            "entity_type": self.entity_type,
            "topic": self.topic,
            "stream_partition": self.stream_partition,
            "stream_offset": self.stream_offset,
            "key": self.key,
            "message": self.message,
        }


class TelemetryWriter(abc.ABC):
    """계측 저장의 목적 수준 인터페이스."""

    @abc.abstractmethod
    def write(self, record: TelemetryRecord) -> None:
        """계측 1건을 저장한다. 저장 제품은 구현이 정한다."""


class JsonlTelemetryWriter(TelemetryWriter):
    """**관측용 흔적** — 파이프라인이 무엇을 받았는지 파일 한 줄과 로그로 보여 준다.

    Phase 1에서는 이것이 저장의 전부였지만 이제는 아니다. **계측의 원본은 TimescaleDB**이고
    (`tsdb_writer.py`), 이 파일은 남는다:

    - 인프라 없이 도는 테스트가 쓴다.
    - 파이프라인을 손으로 확인할 때 눈으로 보는 자리다(`tail -f`).
    - Phase 1부터의 회귀 테스트가 읽는 자리다.

    ⚠ **운영 저장으로 쓰지 않는다.** 조회·되감기·학습 재료는 TSDB에서 가져온다.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or settings.sink_path()

    def write(self, record: TelemetryRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
        LOG.info(
            "store: channel=%s etype=%s source_id=%s sequence_id=%s lag_s=%s%s → %s",
            record.channel,
            record.entity_type,
            record.message.get("source_id"),
            record.message.get("sequence_id"),
            "?" if record.lag_s is None else format(record.lag_s, ".3f"),
            " [clock_skew]" if record.clock_skew else (" [replayed]" if record.replayed else ""),
            self.path,
        )


class FanoutTelemetryWriter(TelemetryWriter):
    """같은 레코드를 여러 저장소에 넣는다.

    한 곳이 실패해도 나머지는 계속 쓴다 — 관측용 흔적(JSONL)이 막혔다고 운영 저장(TSDB)까지
    멈추면 안 되고, 그 반대도 마찬가지다. 실패는 각 구현이 자기 방식으로 기록한다.
    """

    def __init__(self, writers) -> None:
        self.writers = list(writers)

    def write(self, record: TelemetryRecord) -> None:
        for writer in self.writers:
            try:
                writer.write(record)
            except Exception as exc:  # noqa: BLE001 - 한 저장소의 실패가 다른 곳을 막지 않는다
                LOG.error(
                    "저장 실패(%s) — 나머지 저장소는 계속 쓴다: %s: %s",
                    type(writer).__name__, type(exc).__name__, exc,
                )


def build_writer(name: str) -> TelemetryWriter:
    """이름 하나 → 저장 구현 하나. 이름은 `MK2_TELEMETRY_WRITERS`가 준다."""
    if name == "tsdb":
        # 지역 import — 순환 참조 회피 + psycopg 가 필요한 경로에서만 로드된다.
        from backend.storage.tsdb_writer import TimescaleTelemetryWriter

        return TimescaleTelemetryWriter()
    if name == "jsonl":
        return JsonlTelemetryWriter()
    raise ValueError(
        f"알 수 없는 저장 구현: {name!r} (쓸 수 있는 값: tsdb, jsonl). "
        "MK2_TELEMETRY_WRITERS 를 확인한다."
    )


def default_writer() -> TelemetryWriter:
    """저장 소비자가 쓰는 기본 구성.

    기본은 **TSDB + JSONL 둘 다**다.

    - **TSDB가 운영 저장이다.** 계측의 원본은 여기 있고, 조회·되감기·학습 재료가 여기서 나온다.
    - **JSONL은 저장이 아니라 관측용 흔적이다.** 파이프라인이 무엇을 받았는지 눈으로 보는
      자리이고, Phase 1부터의 회귀 테스트가 읽는 자리다. 지우지 않는 이유가 그것이다.

    ⚠ **TSDB가 없을 때 조용히 JSONL로 떨어지지 않는다.** 그러면 데이터가 파일로 가는데
    아무도 모른 채 며칠이 지난다. 접속 정보가 없으면 기동 시점에 이름을 대며 죽는다.
    구성을 바꿔야 하면 `MK2_TELEMETRY_WRITERS`로 **명시적으로** 바꾼다(예: `jsonl`).
    """
    names = settings.telemetry_writers()
    writers = [build_writer(name) for name in names]
    if len(writers) == 1:
        return writers[0]
    return FanoutTelemetryWriter(writers)
