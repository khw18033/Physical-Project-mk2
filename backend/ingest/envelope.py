"""수신 메시지 2단 검증(공통 헤더 → 채널 본문)과 격리 기록.

파트 경계의 기준은 `contracts/common/`의 JSON Schema이지 파이썬 타입이 아니다(CLAUDE.md
원칙 9). 여기서는 그 규격을 **그대로 로드해** 검증하고, 파이썬 쪽에 필드를 다시 선언하지
않는다 — 두 벌이 되면 조용히 어긋난다.

검증 규약(규격 README "검증"): 검증 실패 메시지는 정상 topic으로 재발행하지 말고 격리·기록한다.
전환/관용 모드는 없다 — 처음부터 fail-closed다.

**2단 검증은 "느슨한 2단"이다.** 세게 거는 곳과 느슨하게 두는 곳이 나뉘며, 그 경계에 이유가
있다:

- **필수 필드 누락은 격리한다.** 저장 층이 값의 존재를 가정할 수 있어야 하기 때문이다.
  공통 헤더만 검증하던 Phase 1과 달라진 지점이 여기다.
- **모르는 필드는 통과시킨다**(`additionalProperties: false`를 쓰지 않는다). 하드웨어가
  필드를 하나 추가하는 순간 전량 격리되는 사고를 만들지 않는다 — `status_extra()`처럼
  노드마다 다른 필드를 반환하도록 설계된 훅이 있어 필드가 느는 것이 정상 동작이다.
- **모르는 개체 타입은 본문 검증을 건너뛰고 통과시킨 뒤 기록한다.** 새 노드 타입이 첫
  메시지부터 격리되면 파이프라인이 그 자리에서 막힌다.
- **본문의 `channel` 필드는 검증하지 않는다.** 라우팅은 토픽 기준이다. 증강 분석이 토픽
  `state`에 본문 `channel: "analysis"`를 보내고 있어 일치를 강제하면 가동 중인 생산자가
  전량 격리된다. 불일치는 기록만 한다.

`date-time` 포맷은 `FormatChecker`가 있어야 실제로 검사된다. 포맷 검사기가 없으면
`"+0900"`(콜론 없는 오프셋) 같은 값이 조용히 통과해 **검증이 무력해진다.** 그래서 검사기
등록 여부를 기동 시점에 assert 한다.

implements: BE-C-01
tests: tests/test_payload_contract.py(규격 단위, 인프라 불필요) ·
       tests/test_pipeline.py(관통 왕복·불합격 격리)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from jsonschema import Draft202012Validator, FormatChecker

from backend import contracts, settings

LOG = logging.getLogger("mk2.ingest.envelope")

ENVELOPE_SCHEMA_FILENAME = "message.schema.json"


class MessageInvalid(Exception):
    """수신 메시지 검증 불합격. `reason`이 격리 기록에 남는 사유다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class EnvelopeInvalid(MessageInvalid):
    """1단 — 공통 헤더 불합격."""


class PayloadInvalid(MessageInvalid):
    """2단 — 채널 본문 불합격.

    `MessageInvalid`를 함께 상속하므로 호출부는 한 번만 잡으면 된다. 그러면서도 격리
    기록의 사유 문자열로 어느 단에서 걸렸는지 구분된다.
    """


_validator: Optional[Draft202012Validator] = None
_payload_validators: Dict[Tuple[str, Optional[str]], Draft202012Validator] = {}


def envelope_schema_path() -> Path:
    return settings.contracts_dir() / ENVELOPE_SCHEMA_FILENAME


def _format_checker() -> FormatChecker:
    format_checker = FormatChecker()
    if "date-time" not in format_checker.checkers:
        # rfc3339-validator 미설치 시 jsonschema가 date-time 검사를 조용히 건너뛴다.
        raise RuntimeError(
            "date-time 포맷 검사기가 없다 — `rfc3339-validator`를 설치해야 공통 헤더 timestamp "
            "검증이 실제로 동작한다(없으면 검증이 무력해진다)."
        )
    return format_checker


def build_validator() -> Draft202012Validator:
    """공통 헤더 규격 파일을 읽어 strict 검증기를 만든다(포맷 검사 포함)."""
    schema = json.loads(envelope_schema_path().read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=_format_checker())


def validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        _validator = build_validator()
    return _validator


def payload_validator(channel: str, entity_type: Optional[str]) -> Optional[Draft202012Validator]:
    """채널 본문 검증기. 해당 조합의 규격이 없으면 `None`(= 검증 건너뜀)."""
    key = (channel, entity_type)
    if key in _payload_validators:
        return _payload_validators[key]
    schema = contracts.load_payload_schema(channel, entity_type)
    if schema is None:
        return None
    built = Draft202012Validator(schema, format_checker=_format_checker())
    _payload_validators[key] = built
    return built


def _describe(errors) -> str:
    parts = []
    for err in errors:
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        parts.append(f"{where}: {err.message}")
    return " | ".join(parts)


def validate_envelope(message: Any) -> None:
    """1단 — 공통 헤더를 검증한다. 불합격이면 `EnvelopeInvalid`."""
    errors = sorted(validator().iter_errors(message), key=lambda e: list(e.absolute_path))
    if errors:
        raise EnvelopeInvalid(_describe(errors))


def validate_payload(channel: str, entity_type: Optional[str], message: Any) -> None:
    """2단 — 채널 본문을 검증한다. 불합격이면 `PayloadInvalid`.

    검증 대상은 **공통 헤더와 본문이 합쳐진 완전한 메시지**다. 본문 규격은 본문 항목만
    선언하고 `additionalProperties`를 막지 않으므로 공통 헤더 필드는 그대로 통과한다.

    규격이 없는 조합(모르는 개체 타입 등)은 **통과시키고 기록만** 한다 — 새 노드 타입이
    첫 메시지부터 격리되면 안 되기 때문이다.
    """
    checker = payload_validator(channel, entity_type)
    if checker is None:
        LOG.info(
            "본문 검증 건너뜀(해당 규격 없음): channel=%s entity_type=%s source_id=%s "
            "— 규격이 있는 타입: %s",
            channel,
            entity_type,
            _source_id(message),
            ", ".join(contracts.known_entity_types()) or "(없음)",
        )
        return

    errors = sorted(checker.iter_errors(message), key=lambda e: list(e.absolute_path))
    if errors:
        raise PayloadInvalid("본문({}/{}) {}".format(channel, entity_type or "-", _describe(errors)))

    # 본문의 channel 필드는 검증하지 않는다 — 불일치는 기록만 한다(증강 분석이 실제로 그렇다).
    declared = message.get("channel") if isinstance(message, dict) else None
    if isinstance(declared, str) and declared != channel:
        LOG.info(
            "본문 channel 불일치(기록만, 라우팅은 토픽 기준): 토픽 채널=%s 본문 channel=%s source_id=%s",
            channel,
            declared,
            _source_id(message),
        )


def _source_id(message: Any) -> Any:
    return message.get("source_id") if isinstance(message, dict) else None


def parse_and_validate(raw: bytes, topic: Optional[str] = None) -> Dict[str, Any]:
    """수신 바이트 → JSON 파싱 → **공통 헤더 → 본문** 순으로 검증한다.

    `topic`을 주면 2단(본문)까지 본다. 채널·개체 타입은 MQTT 토픽에서만 알 수 있기
    때문이다. 불합격이면 `EnvelopeInvalid` 또는 `PayloadInvalid`(둘 다 `MessageInvalid`).
    """
    try:
        message = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise EnvelopeInvalid(f"UTF-8 디코드 실패: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EnvelopeInvalid(f"JSON 파싱 실패: {exc}") from exc
    validate_envelope(message)
    if topic is not None:
        validate_payload(
            settings.channel_of_mqtt_topic(topic),
            settings.entity_type_of_mqtt_topic(topic),
            message,
        )
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
