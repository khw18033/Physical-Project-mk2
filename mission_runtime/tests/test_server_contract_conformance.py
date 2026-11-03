"""implements: AI-C-01, AI-C-06, AI-C-07, AI-O-06
covers: 우리 메시지가 **백엔드 정본 계약**을 지키는가. 우리 스키마끼리의 검증은
        양쪽이 같이 틀려 있어도 통과하므로(물리 명령 proto 가 2026-09 에 정확히
        그랬다) 정본 사본으로 직접 검사한다.

통합 저장소의 `scripts/check_contracts.py` 가 CI 에서 같은 검사를 한다. 여기서
먼저 깨지면 그쪽 CI 에서도 깨진다 — 그것을 미리 아는 것이 이 파일의 목적이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

VENDOR_DIR = Path(__file__).parents[1] / "schemas" / "ai" / "vendor" / "server"
EXAMPLE_DIR = Path(__file__).parents[1] / "schemas" / "ai" / "examples"


def _registry() -> Registry:
    registry = Registry()
    for path in sorted(VENDOR_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        # 서버 스키마끼리는 파일명 상대 $ref 로 서로를 가리킨다.
        registry = registry.with_resource(path.name, Resource.from_contents(schema))
        if "$id" in schema:
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def _validator(file_name: str) -> Draft202012Validator:
    schema = json.loads((VENDOR_DIR / file_name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=_registry(), format_checker=FormatChecker())


EXAMPLES = sorted(EXAMPLE_DIR.glob("*.json"))


def test_there_are_examples_to_check():
    assert EXAMPLES


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_example_satisfies_the_backend_envelope(path: Path):
    """공통 머리는 백엔드가 소유한다. 채널이 무엇이든 이 봉투를 지킨다."""
    _validator("message.schema.json").validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def test_our_detections_satisfy_the_backend_canonical_body():
    """서버 정본 `detections.schema.json` 과 **같은 모양**인지 직접 본다.

    2026-11-02 통합 저장소 RFC #42 가 "서버 평평한 형식 ↔ AI 중첩 형식"의 통일을
    물었다. 그 RFC 가 본 것은 우리 9월 스냅샷이고, 10-27 규약 v2 작업으로 우리
    detections 는 이미 평평하다. 이 시험이 그 사실을 고정한다 — 다시 중첩으로
    되돌리면 여기서 깨진다.
    """
    message = json.loads((EXAMPLE_DIR / "detections.json").read_text(encoding="utf-8"))
    _validator("detections.schema.json").validate(message)


def test_the_vendored_copies_are_the_backends_own():
    """사본을 우리 것으로 고쳐 적지 않았다는 확인. 고치면 "정본을 지킨다"가 거짓이 된다."""
    message = json.loads((VENDOR_DIR / "message.schema.json").read_text(encoding="utf-8"))
    assert "khw18033/Physical-Project-mk2" in message["$id"]
    assert set(message["required"]) == {
        "schema_version", "source_id", "node_id", "zone_id", "timestamp"
    }
