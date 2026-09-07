"""공통 봉투 strict 검증과 격리 기록.

파트 경계의 기준은 `contracts/common/message.schema.json`(JSON Schema)이지 파이썬 타입이
아니다(CLAUDE.md 원칙 9). 여기서는 그 계약을 **그대로 로드해** 검증하고, 파이썬 쪽에 봉투
필드를 다시 선언하지 않는다 — 두 벌이 되면 조용히 어긋난다.

검증 규약(계약 README "검증"): 검증 실패 메시지는 정상 topic으로 재발행하지 말고 격리·기록한다.
전환/관용 모드는 없다 — 처음부터 fail-closed다.

`date-time` 포맷은 `FormatChecker`가 있어야 실제로 검사된다. 포맷 검사기가 없으면
`"+0900"`(콜론 없는 오프셋) 같은 값이 조용히 통과해 **검증이 무력해진다.** 그래서 검사기
등록 여부를 기동 시점에 assert 한다.

implements: BE-C-01
tests: tests/test_pipeline.py — 계약 fixture 양성/음성, 관통 왕복, 불합격 격리
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from jsonschema import Draft202012Validator, FormatChecker

from backend import settings

ENVELOPE_SCHEMA_FILENAME = "message.schema.json"


class EnvelopeInvalid(Exception):
    """봉투 계약 불합격. `reason`이 격리 기록에 남는 사유다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_validator: Optional[Draft202012Validator] = None


def envelope_schema_path() -> Path:
    return settings.contracts_dir() / ENVELOPE_SCHEMA_FILENAME


def build_validator() -> Draft202012Validator:
    """계약 파일을 읽어 strict 검증기를 만든다(포맷 검사 포함)."""
    format_checker = FormatChecker()
    if "date-time" not in format_checker.checkers:
        # rfc3339-validator 미설치 시 jsonschema가 date-time 검사를 조용히 건너뛴다.
        raise RuntimeError(
            "date-time 포맷 검사기가 없다 — `rfc3339-validator`를 설치해야 봉투 timestamp 검증이 "
            "실제로 동작한다(없으면 검증이 무력해진다)."
        )
    schema = json.loads(envelope_schema_path().read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=format_checker)


def validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        _validator = build_validator()
    return _validator


def _describe(errors) -> str:
    parts = []
    for err in errors:
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        parts.append(f"{where}: {err.message}")
    return " | ".join(parts)


def validate_envelope(message: Any) -> None:
    """봉투만 검증한다. 채널 본문(payload) 스키마는 아직 없으므로 통과시킨다(Phase 1 범위)."""
    errors = sorted(validator().iter_errors(message), key=lambda e: list(e.absolute_path))
    if errors:
        raise EnvelopeInvalid(_describe(errors))


def parse_and_validate(raw: bytes) -> Dict[str, Any]:
    """수신 바이트 → JSON 파싱 → 봉투 strict 검증. 불합격이면 EnvelopeInvalid."""
    try:
        message = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise EnvelopeInvalid(f"UTF-8 디코드 실패: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EnvelopeInvalid(f"JSON 파싱 실패: {exc}") from exc
    validate_envelope(message)
    return message


def quarantine(topic: str, reason: str, raw: bytes, path: Optional[Path] = None) -> None:
    """불합격 메시지를 격리 파일에 한 줄로 남긴다. Kafka로는 내보내지 않는다.

    수신시각은 서버 시각으로 백엔드가 붙인다(발행자 시각과 구분).
    """
    target = path or settings.quarantine_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "received_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "topic": topic,
        "reason": reason,
        "raw": raw.decode("utf-8", errors="replace"),
    }
    with target.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
