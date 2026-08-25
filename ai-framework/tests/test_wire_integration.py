"""tests for: AI-C-01/03/06/07, AI-D-01/02, AI-R-03, AI-O-02, HW-R-10, VZ-I-07/08/10"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from ai_framework.common.timing import FrameReference, TimeSyncState
from ai_framework.contracts.capability import CapabilityState
from ai_framework.decision.subtask import Subtask
from ai_framework.decision.validator import ValidationResult
from ai_framework.integration.wire import (
    DetectionObservation,
    MessageContext,
    RiskReason,
    ai_failure_message,
    capability_status_message,
    detection_message,
    model_deployment_result_message,
    observations_from_perception,
    plan_proposal_message,
    publish_message,
    risk_judgment_message,
)
from ai_framework.observability.events import CapabilityStateChange
from ai_framework.perception.detection import PerceptionResult
from ai_framework.providers.fakes import InMemoryTransportProvider, JsonSerializerProvider
from ai_framework.risk.output import RiskJudgment


CONTRACT_DIR = Path(__file__).parents[2] / "contracts" / "ai"


def validator() -> Draft202012Validator:
    registry = Registry()
    schemas = []
    for path in CONTRACT_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas.append(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    message_schema = next(schema for schema in schemas if schema["$id"].endswith("/message.schema.json"))
    return Draft202012Validator(message_schema, registry=registry, format_checker=FormatChecker())


def context(**overrides) -> MessageContext:
    base = dict(
        source_id="ai-edge-a",
        node_id="edge-node-a",
        entity_id="robot-01",
        zone_id="zone-a",
        sequence_id=7,
        correlation_id="mission-42",
        timestamp="2026-08-25T12:00:00Z",
        message_id="message-001",
    )
    base.update(overrides)
    return MessageContext(**base)


def reference() -> FrameReference:
    return FrameReference(
        source_id="camera-01",
        frame_id="frame-42",
        observed_at=1787659199.8,
        local_sequence=42,
        sync_state=TimeSyncState.SYNCED,
    )


def assert_contract(message: dict) -> None:
    validator().validate(message)


def test_detection_adapter_makes_frame_reference_and_bbox_unambiguous():
    observations = observations_from_perception(
        [PerceptionResult(box=(10.0, 20.0, 40.0, 80.0), label="person", confidence=0.9)],
        source_id="camera-01",
    )

    message = detection_message(
        reference(),
        observations,
        context(source_id="camera-01"),
        reference_size=(640, 480),
        inference_delay_ms=200,
        association="unavailable",
        emitted_at="2026-08-25T12:00:00Z",
    )

    assert_contract(message)
    assert message["payload"]["frame_ref"] == {
        "source_id": "camera-01",
        "capture_timestamp": "2026-08-25T11:59:59.800000Z",
        "sequence_id": 42,
        "frame_id": "frame-42",
        "time_sync_state": "SYNCED",
    }
    assert message["payload"]["detections"][0]["bbox"] == {
        "x": 10.0,
        "y": 20.0,
        "width": 30.0,
        "height": 60.0,
    }


def test_detection_adapter_preserves_optional_association_and_source_identity():
    observation = DetectionObservation(
        box_xyxy=(0, 0, 0.5, 0.5),
        label="unknown",
        confidence=0.7,
        track_id=3,
        source_id="camera-02",
        linked_sources=("camera-03",),
        link_confidence=0.8,
    )

    message = detection_message(
        reference(),
        [observation],
        context(source_id="camera-01"),
        reference_size=(640, 480),
        bbox_format="normalized",
        association="enabled",
        emitted_at="2026-08-25T12:00:00Z",
    )

    assert_contract(message)
    item = message["payload"]["detections"][0]
    assert item["track_id"] == "3"
    assert item["source_id"] == "camera-02"
    assert item["link"]["confidence"] == 0.8


def test_risk_adapter_exposes_visualization_score_reasons_and_time():
    judgment = RiskJudgment(
        risk_state="ALERT",
        risk_level=0.87,
        evidence_sufficiency=0.92,
        evidence_used=("water_level",),
        model_version="river-rules-3",
        recommendation="close_gate",
    )

    message = risk_judgment_message(
        judgment,
        context(),
        reasons=[RiskReason("water level", "4.2m", 0.87)],
        decided_at="2026-08-25T12:00:01Z",
    )

    assert_contract(message)
    assert message["payload"]["state"] == "alert"
    assert message["payload"]["score"] == 0.87
    assert message["payload"]["reasons"][0]["contribution"] == 0.87


def test_failure_and_capability_status_are_distinct_contracts():
    change = CapabilityStateChange(
        "perception.detect",
        CapabilityState.ACTIVE,
        CapabilityState.DISABLED,
    )
    status = capability_status_message(
        change,
        context(),
        provider_id="detector-a",
        reason="runtime failed",
        changed_at="2026-08-25T12:00:02Z",
    )
    failure = ai_failure_message(
        context(),
        component="perception.detect",
        error_code="MODEL_EXECUTION_FAILED",
        detail="runtime failed",
        model_version="detector-4",
        input_ref="camera-01/frame-42",
        capability_state_before=change.previous,
        capability_state_after=change.current,
        occurred_at="2026-08-25T12:00:02Z",
        event_id="failure-001",
    )

    assert_contract(status)
    assert_contract(failure)
    assert status["channel"] == "capability_status"
    assert failure["channel"] == "ai_failure"


def test_plan_proposal_carries_generation_and_validation_provenance():
    subtask = Subtask(
        "zone-a:inspect:0",
        "zone-a",
        "inspect",
        0,
        preconditions=("zone_reachable:zone-a",),
    )
    result = ValidationResult(executable=True)

    message = plan_proposal_message(
        [subtask],
        {subtask.subtask_id: result},
        context(),
        plan_id="plan-42-v1",
        mission_id="mission-42",
        generator_name="rule-template-planner",
        generator_version="1.0.0",
        context_version="zone-a-map-12",
        created_at="2026-08-25T12:00:03Z",
    )

    assert_contract(message)
    assert message["payload"]["approval_required"] is True
    assert message["payload"]["validations"][0]["executable"] is True


def test_plan_proposal_refuses_unvalidated_subtasks():
    subtask = Subtask("s1", "zone-a", "inspect", 0)

    with pytest.raises(ValueError, match="missing validation"):
        plan_proposal_message(
            [subtask],
            {},
            context(),
            plan_id="plan-1",
            mission_id="mission-1",
            generator_name="planner",
            generator_version="1",
            context_version="1",
        )


def test_model_deployment_result_covers_hardware_apply_acknowledgement():
    message = model_deployment_result_message(
        context(correlation_id="deployment-42"),
        deployment_id="deployment-42",
        model_id="local-safety-detector",
        model_version="4.1.0",
        artifact_ref="internal://models/local-safety-detector/4.1.0",
        checksum="sha256:abc",
        target_node_id="robot-01-onboard",
        status="APPLIED",
        previous_version="4.0.2",
        occurred_at="2026-08-25T12:00:04Z",
    )

    assert_contract(message)
    assert message["payload"]["target_node_id"] == "robot-01-onboard"
    assert message["payload"]["status"] == "APPLIED"


def test_contract_message_publishes_through_existing_provider_interfaces():
    serializer = JsonSerializerProvider()
    transport = InMemoryTransportProvider()
    received = []
    transport.subscribe("ai/risk/zone-a", received.append)
    message = risk_judgment_message(
        RiskJudgment("WATCH", 0.5, 0.7, ("rain",), "rules-1", "observe"),
        context(),
        decided_at="2026-08-25T12:00:05Z",
    )

    publish_message(message, serializer, transport, "ai/risk/zone-a")

    decoded = serializer.decode(received[0])
    assert decoded["schema_version"] == "1.0"
    assert decoded["channel"] == "risk_state"
