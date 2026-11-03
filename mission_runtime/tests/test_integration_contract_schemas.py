"""implements: AI-C-01, AI-C-07, AI-C-06

2026-10-27: 백엔드 통합데이터규약 v2 로 바꾸면서 **계약이 보장하는 것이 달라졌다.**
봉투는 공통 머리만 검사하고 모르는 칸을 통과시킨다(규약 R12) — 그래서 "모르는 최상위
칸을 거부한다"는 보장은 더 이상 없고, 그 반대가 규약이다. 채널별 본문은 봉투가 아니라
**본문 스키마로 따로** 검사한다. 이 파일의 아래 네 시험이 그 변화를 고정한다.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


CONTRACT_DIR = Path(__file__).parents[1] / "schemas" / "ai"
EXAMPLE_DIR = CONTRACT_DIR / "examples"


def contract_validator() -> Draft202012Validator:
    registry = Registry()
    schemas = []
    for path in sorted(CONTRACT_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas.append(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    message_schema = next(schema for schema in schemas if schema["$id"].endswith("/message.schema.json"))
    return Draft202012Validator(message_schema, registry=registry, format_checker=FormatChecker())


@pytest.mark.parametrize(
    "example_path",
    sorted(EXAMPLE_DIR.glob("*.json")),
    ids=lambda path: path.stem,
)
def test_every_shared_example_satisfies_the_message_contract(example_path: Path):
    message = json.loads(example_path.read_text(encoding="utf-8"))

    contract_validator().validate(message)


#: 채널 → 본문 스키마. 봉투가 채널과 본문을 묶지 않으므로 소비자가 이 표로 고른다.
BODY_SCHEMA_BY_CHANNEL = {
    "detections": "detection-result",
    "risk_state": "risk-judgment",
    "ai_failure": "ai-failure",
    "capability_status": "capability-status",
    "model_deployment_result": "model-deployment-result",
    "status_snapshot": "status-snapshot",
}


def body_validator(channel: str) -> Draft202012Validator:
    registry = Registry()
    for path in sorted(CONTRACT_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    name = BODY_SCHEMA_BY_CHANNEL[channel]
    schema = json.loads((CONTRACT_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


@pytest.mark.parametrize(
    "example_path",
    sorted(EXAMPLE_DIR.glob("*.json")),
    ids=lambda path: path.stem,
)
def test_every_example_also_satisfies_its_channel_body_contract(example_path: Path):
    """평탄한 메시지는 봉투와 본문 **두 계약 모두**를 만족해야 한다."""
    message = json.loads(example_path.read_text(encoding="utf-8"))
    body_validator(message["channel"]).validate(message)


def test_detection_body_rejects_a_numeric_frame_reference():
    message = json.loads((EXAMPLE_DIR / "detections.json").read_text(encoding="utf-8"))
    message["frame_ref"] = 1042

    with pytest.raises(Exception):
        body_validator("detections").validate(message)


def test_detection_body_requires_bbox_as_four_numbers_not_an_object():
    """규약 V1: `bbox` 는 [x1,y1,x2,y2] 다. 옛 `{x,y,width,height}` 모양은 거부된다."""
    message = json.loads((EXAMPLE_DIR / "detections.json").read_text(encoding="utf-8"))
    assert message["detections"][0]["bbox"] == [120.0, 64.0, 240.0, 352.0]

    mutated = copy.deepcopy(message)
    mutated["detections"][0]["bbox"] = {"x": 120, "y": 64, "width": 120, "height": 288}
    with pytest.raises(Exception):
        body_validator("detections").validate(mutated)

    short = copy.deepcopy(message)
    short["detections"][0]["bbox"] = [120, 64, 240]
    with pytest.raises(Exception):
        body_validator("detections").validate(short)


def test_a_body_validated_against_the_wrong_channel_schema_fails():
    """봉투가 채널↔본문을 묶지 않으므로 그 대조를 소비자가 해야 한다 —
    표로 고르면 어긋난 짝이 걸린다."""
    risk = json.loads((EXAMPLE_DIR / "risk-state.json").read_text(encoding="utf-8"))
    with pytest.raises(Exception):
        body_validator("detections").validate(risk)


def test_unknown_top_level_fields_pass_because_the_rule_reversed():
    """규약 R12: 모르는 칸은 거부하지 않고 통과시킨다.

    과거 계약은 반대였다(`additionalProperties: false`). 백엔드가 `origin_kind`·
    `sent_at` 같은 칸을 더해 보낼 수 있고 우리 검증기가 그것을 막으면 안 된다.
    """
    message = json.loads((EXAMPLE_DIR / "capability-status.json").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(message)
    mutated["origin_kind"] = "real"
    mutated["sent_at"] = message["timestamp"]

    contract_validator().validate(mutated)      # 예외가 나지 않아야 한다


def test_envelope_still_rejects_a_missing_zone_or_a_wrong_timestamp_shape():
    """관용은 머리 칸에까지 적용되지 않는다 — zone_id 는 필수고 시각 표기는 고정이다."""
    message = json.loads((EXAMPLE_DIR / "capability-status.json").read_text(encoding="utf-8"))

    without_zone = copy.deepcopy(message)
    del without_zone["zone_id"]
    with pytest.raises(Exception):
        contract_validator().validate(without_zone)

    utc_shape = copy.deepcopy(message)
    utc_shape["timestamp"] = "2026-08-25T10:40:00.000Z"
    with pytest.raises(Exception):
        contract_validator().validate(utc_shape)
