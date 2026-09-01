"""Language-neutral wire adapters for hardware/backend/visualization integration."""

from perception_framework.integration.wire import (
    DetectionObservation,
    MessageContext,
    RiskReason,
    ai_failure_message,
    capability_status_message,
    detection_message,
    frame_reference_to_wire,
    model_deployment_record_message,
    model_deployment_result_message,
    observations_from_perception,
    publish_message,
    risk_judgment_message,
)

__all__ = [
    "DetectionObservation",
    "MessageContext",
    "RiskReason",
    "ai_failure_message",
    "capability_status_message",
    "detection_message",
    "frame_reference_to_wire",
    "model_deployment_record_message",
    "model_deployment_result_message",
    "observations_from_perception",
    "publish_message",
    "risk_judgment_message",
]
