"""Cross-part JSON contract validation for hardware/backend/visualization."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


CONTRACT_DIR = Path(__file__).parents[2] / "contracts" / "ai"
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


def test_detection_contract_rejects_numeric_frame_reference():
    message = json.loads((EXAMPLE_DIR / "detections.json").read_text(encoding="utf-8"))
    message["payload"]["frame_ref"] = 1042

    with pytest.raises(Exception):
        contract_validator().validate(message)


def test_detection_contract_rejects_ambiguous_bbox_array():
    message = json.loads((EXAMPLE_DIR / "detections.json").read_text(encoding="utf-8"))
    message["payload"]["detections"][0]["bbox"] = [120, 80, 210, 290]

    with pytest.raises(Exception):
        contract_validator().validate(message)


def test_channel_and_payload_schema_must_match():
    message = json.loads((EXAMPLE_DIR / "risk-state.json").read_text(encoding="utf-8"))
    message["channel"] = "ai_failure"

    with pytest.raises(Exception):
        contract_validator().validate(message)


def test_unknown_top_level_fields_are_rejected():
    message = json.loads((EXAMPLE_DIR / "capability-status.json").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(message)
    mutated["topic"] = "mqtt/internal/topic"

    with pytest.raises(Exception):
        contract_validator().validate(mutated)
