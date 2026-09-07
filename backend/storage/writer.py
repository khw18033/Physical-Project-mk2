"""계측 저장의 목적 인터페이스와 Phase 1 placeholder 구현.

상위(소비자)는 `TelemetryWriter.write(record)` 하나만 안다 — Influx·Timescale 같은 저장 제품
클라이언트를 직접 부르지 않는다(CLAUDE.md 원칙 1, 제약 4). **Phase 2에서 이 인터페이스 뒤의
구현만 TSDB로 교체하고, 호출부(ingest·소비자)는 손대지 않는다.**

`TelemetryRecord`는 백엔드 내부 타입이며 파트 경계로 노출하지 않는다 — 경계의 정본은
`contracts/common/message.schema.json`이다(원칙 9).

implements: BE-S-01 (Phase 1 = placeholder. 실제 TSDB 제품·스키마·retention은 Phase 2)
tests: tests/test_pipeline.py — 발행값이 sink 기록에 나타나는지(팬아웃 ①)
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


@dataclass
class TelemetryRecord:
    """검증을 통과한 봉투+본문과, 어느 채널/토픽에서 왔는지."""

    channel: str
    topic: str
    message: Dict[str, Any]
    key: Optional[str] = None
    received_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "received_at": self.received_at,
            "channel": self.channel,
            "topic": self.topic,
            "key": self.key,
            "message": self.message,
        }


class TelemetryWriter(abc.ABC):
    """계측 저장의 목적 수준 인터페이스."""

    @abc.abstractmethod
    def write(self, record: TelemetryRecord) -> None:
        """계측 1건을 저장한다. 저장 제품은 구현이 정한다."""


class JsonlTelemetryWriter(TelemetryWriter):
    """Phase 1 placeholder — "받았다"를 파일 append + 로그로 보이는 것까지.

    Phase 2에서 이 클래스가 TSDB writer로 교체된다(시각 기준 정렬·지연 도착 정합 포함).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or settings.sink_path()

    def write(self, record: TelemetryRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
        LOG.info(
            "store: channel=%s source_id=%s sequence_id=%s → %s",
            record.channel,
            record.message.get("source_id"),
            record.message.get("sequence_id"),
            self.path,
        )


def default_writer() -> TelemetryWriter:
    return JsonlTelemetryWriter()
