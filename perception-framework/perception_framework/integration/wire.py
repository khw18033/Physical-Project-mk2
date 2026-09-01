"""Adapters from AI domain objects to the repository-wide JSON contracts.

implements: AI-C-01, AI-C-07, AI-C-14

The domain modules remain independent of backend and visualization naming.
Only this module knows the structures in ``contracts/ai``. This keeps a
TypeScript/UI field change from leaking into perception or risk
logic while still giving every other part one stable wire representation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence
from uuid import uuid4

from perception_framework.common.timing import FrameReference
from perception_framework.contracts.capability import CapabilityState
from perception_framework.observability.events import CapabilityStateChange
from perception_framework.perception.detection import PerceptionResult
from perception_framework.risk.output import RiskJudgment
from perception_framework.runtime.model_deployment import ModelDeploymentResult


SCHEMA_VERSION = "1.0"
AI_CHANNELS = frozenset(
    {
        "detections",
        "risk_state",
        "ai_failure",
        "capability_status",
        "model_deployment_result",
    }
)


def _timestamp(value: datetime | float | str | None = None) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        instant = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, datetime):
        instant = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        instant = instant.astimezone(timezone.utc)
    else:
        instant = datetime.now(timezone.utc)
    return instant.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MessageContext:
    """Cross-part identity and ordering fields owned by the backend contract."""

    source_id: str
    node_id: str
    entity_id: str
    zone_id: str | None = None
    sequence_id: int = 0
    correlation_id: str | None = None
    timestamp: datetime | float | str | None = None
    message_id: str | None = None


@dataclass(frozen=True)
class DetectionObservation:
    """One detection in the AI-native x1/y1/x2/y2 representation."""

    box_xyxy: tuple[float, float, float, float]
    label: str
    confidence: float
    track_id: str | int | None = None
    class_confidence: float | None = None
    approach: str | None = None
    trail: tuple[tuple[float, float], ...] = ()
    source_id: str | None = None
    linked_sources: tuple[str, ...] = ()
    link_confidence: float | None = None


@dataclass(frozen=True)
class RiskReason:
    label: str
    value: str
    contribution: float = 0.0


def build_message(
    context: MessageContext,
    channel: str,
    payload: dict,
    *,
    coordinate_frame: str | None = None,
) -> dict:
    if channel not in AI_CHANNELS:
        raise ValueError(f"unsupported AI channel: {channel}")
    if context.sequence_id < 0:
        raise ValueError("sequence_id must be non-negative")
    for field_name in ("source_id", "node_id", "entity_id"):
        if not getattr(context, field_name):
            raise ValueError(f"{field_name} must not be empty")

    return {
        "schema_version": SCHEMA_VERSION,
        "message_id": context.message_id or str(uuid4()),
        "source_id": context.source_id,
        "node_id": context.node_id,
        "zone_id": context.zone_id,
        "entity_id": context.entity_id,
        "channel": channel,
        "timestamp": _timestamp(context.timestamp),
        "sequence_id": context.sequence_id,
        "correlation_id": context.correlation_id,
        "coordinate_frame": coordinate_frame,
        "payload": payload,
    }


def frame_reference_to_wire(reference: FrameReference) -> dict:
    return {
        "source_id": reference.source_id,
        "capture_timestamp": _timestamp(reference.observed_at),
        "sequence_id": reference.local_sequence,
        "frame_id": reference.frame_id,
        "time_sync_state": reference.sync_state.value,
    }


def observations_from_perception(
    results: Iterable[PerceptionResult],
    *,
    source_id: str,
) -> list[DetectionObservation]:
    return [
        DetectionObservation(
            box_xyxy=result.box,
            label=result.label,
            confidence=result.confidence,
            source_id=source_id,
        )
        for result in results
    ]


def _box_to_wire(box_xyxy: tuple[float, float, float, float]) -> dict:
    x1, y1, x2, y2 = box_xyxy
    if x2 < x1 or y2 < y1:
        raise ValueError(f"invalid xyxy box: {box_xyxy}")
    return {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}


def _observation_to_wire(observation: DetectionObservation, default_source_id: str) -> dict:
    if not 0 <= observation.confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    if observation.class_confidence is not None and not 0 <= observation.class_confidence <= 1:
        raise ValueError("class_confidence must be between 0 and 1")
    if observation.approach not in (None, "closing", "steady", "receding"):
        raise ValueError(f"unsupported approach: {observation.approach}")
    if observation.link_confidence is not None and not observation.linked_sources:
        raise ValueError("link_confidence requires linked_sources")

    link = None
    if observation.linked_sources:
        confidence = observation.link_confidence
        if confidence is None or not 0 <= confidence <= 1:
            raise ValueError("linked detections require link_confidence between 0 and 1")
        link = {
            "linked_sources": list(observation.linked_sources),
            "confidence": confidence,
        }

    return {
        "track_id": None if observation.track_id is None else str(observation.track_id),
        "label": observation.label,
        "confidence": observation.confidence,
        "class_confidence": observation.class_confidence,
        "bbox": _box_to_wire(observation.box_xyxy),
        "approach": observation.approach,
        "trail": [{"x": x, "y": y} for x, y in observation.trail],
        "source_id": observation.source_id or default_source_id,
        "link": link,
    }


def detection_message(
    reference: FrameReference,
    observations: Sequence[DetectionObservation],
    context: MessageContext,
    *,
    reference_size: tuple[int, int],
    tier: str = "edge",
    kind: str = "precise",
    optional: bool = True,
    label: str = "",
    bbox_format: str = "absolute",
    association: str = "unavailable",
    inference_delay_ms: float = 0.0,
    emitted_at: datetime | float | str | None = None,
    corridor_xywh: tuple[float, float, float, float] | None = None,
) -> dict:
    if tier not in ("device", "edge", "server"):
        raise ValueError(f"unsupported detection tier: {tier}")
    if kind not in ("safety_minimal", "precise", "derived"):
        raise ValueError(f"unsupported detection kind: {kind}")
    if bbox_format not in ("absolute", "normalized"):
        raise ValueError(f"unsupported bbox format: {bbox_format}")
    if association not in ("enabled", "unavailable"):
        raise ValueError(f"unsupported association state: {association}")
    width, height = reference_size
    if width <= 0 or height <= 0:
        raise ValueError("reference_size must contain positive dimensions")

    corridor = None
    if corridor_xywh is not None:
        x, y, box_width, box_height = corridor_xywh
        if box_width < 0 or box_height < 0:
            raise ValueError("corridor width and height must be non-negative")
        corridor = {"x": x, "y": y, "width": box_width, "height": box_height}

    payload = {
        "frame_ref": frame_reference_to_wire(reference),
        "emitted_at": _timestamp(emitted_at),
        "inference_delay_ms": inference_delay_ms,
        "origin": {"tier": tier, "kind": kind, "optional": optional, "label": label},
        "bbox_space": {
            "format": bbox_format,
            "origin": "top-left",
            "reference": {"width": width, "height": height},
        },
        "association": association,
        "corridor": corridor,
        "detections": [
            _observation_to_wire(observation, reference.source_id) for observation in observations
        ],
    }
    return build_message(context, "detections", payload, coordinate_frame="IMAGE")


def risk_judgment_message(
    judgment: RiskJudgment,
    context: MessageContext,
    *,
    reasons: Sequence[RiskReason] | None = None,
    decided_at: datetime | float | str | None = None,
) -> dict:
    state = judgment.risk_state.lower()
    if state not in ("normal", "watch", "alert", "recovery"):
        raise ValueError(f"unsupported risk state: {judgment.risk_state}")
    reason_items = list(reasons or ())
    if not reason_items:
        reason_items = [RiskReason(label=item, value="used", contribution=0.0) for item in judgment.evidence_used]

    payload = {
        "state": state,
        "score": judgment.risk_level,
        "evidence_sufficiency": judgment.evidence_sufficiency,
        "evidence_used": list(judgment.evidence_used),
        "reasons": [
            {"label": reason.label, "value": reason.value, "contribution": reason.contribution}
            for reason in reason_items
        ],
        "recommendation": judgment.recommendation,
        "model_version": judgment.model_version,
        "decided_at": _timestamp(decided_at),
    }
    return build_message(context, "risk_state", payload)


def ai_failure_message(
    context: MessageContext,
    *,
    component: str,
    error_code: str,
    detail: str,
    severity: str = "critical",
    model_version: str | None = None,
    input_ref: str | None = None,
    trace_id: str | None = None,
    capability_state_before: CapabilityState | None = None,
    capability_state_after: CapabilityState | None = None,
    occurred_at: datetime | float | str | None = None,
    event_id: str | None = None,
) -> dict:
    if severity not in ("info", "warning", "critical"):
        raise ValueError(f"unsupported failure severity: {severity}")
    payload = {
        "event_id": event_id or str(uuid4()),
        "component": component,
        "model_version": model_version,
        "input_ref": input_ref,
        "error_code": error_code,
        "detail": detail,
        "severity": severity,
        "capability_state_before": capability_state_before.value if capability_state_before else None,
        "capability_state_after": capability_state_after.value if capability_state_after else None,
        "trace_id": trace_id,
        "occurred_at": _timestamp(occurred_at),
    }
    return build_message(context, "ai_failure", payload)


def capability_status_message(
    change: CapabilityStateChange,
    context: MessageContext,
    *,
    reason: str | None = None,
    provider_id: str | None = None,
    cluster_id: str | None = None,
    changed_at: datetime | float | str | None = None,
) -> dict:
    payload = {
        "capability_kind": change.capability_kind,
        "provider_id": provider_id,
        "state": change.current.value,
        "reason": reason,
        "cluster_id": cluster_id,
        "changed_at": _timestamp(changed_at),
    }
    return build_message(context, "capability_status", payload)


def model_deployment_result_message(
    context: MessageContext,
    *,
    deployment_id: str,
    model_id: str,
    model_version: str,
    artifact_ref: str,
    checksum: str,
    target_node_id: str,
    status: str,
    previous_version: str | None = None,
    reason: str | None = None,
    occurred_at: datetime | float | str | None = None,
) -> dict:
    allowed = {"REQUESTED", "DOWNLOADING", "VALIDATING", "APPLIED", "FAILED", "ROLLED_BACK"}
    if status not in allowed:
        raise ValueError(f"unsupported model deployment status: {status}")
    payload = {
        "deployment_id": deployment_id,
        "model_id": model_id,
        "model_version": model_version,
        "artifact_ref": artifact_ref,
        "checksum": checksum,
        "target_node_id": target_node_id,
        "status": status,
        "previous_version": previous_version,
        "reason": reason,
        "occurred_at": _timestamp(occurred_at),
    }
    return build_message(context, "model_deployment_result", payload)


def model_deployment_record_message(result: ModelDeploymentResult, context: MessageContext) -> dict:
    """Convert the lifecycle manager's final/intermediate record without field duplication."""

    return model_deployment_result_message(
        context,
        deployment_id=result.deployment_id,
        model_id=result.model_id,
        model_version=result.model_version,
        artifact_ref=result.artifact_ref,
        checksum=result.checksum,
        target_node_id=result.target_node_id,
        status=result.status.value,
        previous_version=result.previous_version,
        reason=result.reason,
        occurred_at=result.occurred_at,
    )


def publish_message(message: dict, serializer, transport, topic: str) -> None:
    """Publish one already-built contract message through provider interfaces."""

    transport.publish(topic, serializer.encode(message))
