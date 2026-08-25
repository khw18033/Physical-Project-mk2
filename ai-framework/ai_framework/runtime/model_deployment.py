"""Provider-neutral model deployment lifecycle for hardware integration.

implements: HW-R-10, AI-B-05, AI-B-07, AI-B-08, AI-C-16

The coordinator never assumes a Raspberry Pi path, model file format, or
runtime reload command. Those details belong to ModelDeploymentProvider.
It guarantees that validation precedes activation and that an activation
failure attempts to restore the previously active version.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from ai_framework.providers.adapters import ModelDeploymentProvider


class ModelDeploymentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DOWNLOADING = "DOWNLOADING"
    VALIDATING = "VALIDATING"
    APPLIED = "APPLIED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True)
class ModelDeploymentRequest:
    deployment_id: str
    model_id: str
    model_version: str
    artifact_ref: str
    checksum: str
    target_node_id: str


@dataclass(frozen=True)
class ModelDeploymentResult:
    deployment_id: str
    model_id: str
    model_version: str
    artifact_ref: str
    checksum: str
    target_node_id: str
    status: ModelDeploymentStatus
    previous_version: str | None
    reason: str | None
    occurred_at: str


class ModelDeploymentManager:
    def __init__(self, provider: ModelDeploymentProvider) -> None:
        self._provider = provider
        self.history: list[ModelDeploymentResult] = []

    def deploy(self, request: ModelDeploymentRequest) -> ModelDeploymentResult:
        previous = self._provider.current_version(request.model_id, request.target_node_id)
        self._record(request, ModelDeploymentStatus.REQUESTED, previous)

        try:
            self._record(request, ModelDeploymentStatus.DOWNLOADING, previous)
            if not self._provider.download(request.artifact_ref, request.target_node_id):
                return self._record(
                    request,
                    ModelDeploymentStatus.FAILED,
                    previous,
                    "artifact_download_failed",
                )

            self._record(request, ModelDeploymentStatus.VALIDATING, previous)
            if not self._provider.validate(request.artifact_ref, request.checksum, request.target_node_id):
                return self._record(
                    request,
                    ModelDeploymentStatus.FAILED,
                    previous,
                    "artifact_validation_failed",
                )

            try:
                activated = self._provider.activate(
                    request.model_id,
                    request.model_version,
                    request.artifact_ref,
                    request.target_node_id,
                )
            except Exception as exc:
                return self._restore_previous(
                    request,
                    previous,
                    f"activation_error:{type(exc).__name__}",
                )
            if activated:
                return self._record(request, ModelDeploymentStatus.APPLIED, previous)

            return self._restore_previous(request, previous, "activation_failed")
        except Exception as exc:
            return self._record(
                request,
                ModelDeploymentStatus.FAILED,
                previous,
                f"provider_error:{type(exc).__name__}",
            )

    def _restore_previous(
        self,
        request: ModelDeploymentRequest,
        previous_version: str | None,
        failure_reason: str,
    ) -> ModelDeploymentResult:
        if previous_version is None:
            return self._record(
                request,
                ModelDeploymentStatus.FAILED,
                previous_version,
                f"{failure_reason}_no_rollback",
            )

        try:
            restored = self._provider.rollback(
                request.model_id,
                previous_version,
                request.target_node_id,
            )
        except Exception as exc:
            return self._record(
                request,
                ModelDeploymentStatus.FAILED,
                previous_version,
                f"{failure_reason}_rollback_error:{type(exc).__name__}",
            )

        status = ModelDeploymentStatus.ROLLED_BACK if restored else ModelDeploymentStatus.FAILED
        suffix = "previous_version_restored" if restored else "rollback_failed"
        return self._record(
            request,
            status,
            previous_version,
            f"{failure_reason}_{suffix}",
        )

    def _record(
        self,
        request: ModelDeploymentRequest,
        status: ModelDeploymentStatus,
        previous_version: str | None,
        reason: str | None = None,
    ) -> ModelDeploymentResult:
        result = ModelDeploymentResult(
            deployment_id=request.deployment_id,
            model_id=request.model_id,
            model_version=request.model_version,
            artifact_ref=request.artifact_ref,
            checksum=request.checksum,
            target_node_id=request.target_node_id,
            status=status,
            previous_version=previous_version,
            reason=reason,
            occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        self.history.append(result)
        return result
