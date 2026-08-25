"""tests for: HW-R-10, AI-B-05, AI-B-07, AI-B-08"""

from ai_framework.integration.wire import MessageContext, model_deployment_record_message
from ai_framework.providers.adapters import ModelDeploymentProvider
from ai_framework.providers.fakes import InMemoryModelDeploymentProvider
from ai_framework.runtime.model_deployment import (
    ModelDeploymentManager,
    ModelDeploymentRequest,
    ModelDeploymentStatus,
)


def request() -> ModelDeploymentRequest:
    return ModelDeploymentRequest(
        deployment_id="deployment-42",
        model_id="local-safety-detector",
        model_version="4.1.0",
        artifact_ref="internal://models/local-safety-detector/4.1.0",
        checksum="sha256:abc",
        target_node_id="robot-01-onboard",
    )


def test_fake_satisfies_the_hardware_neutral_provider_contract():
    assert isinstance(InMemoryModelDeploymentProvider(), ModelDeploymentProvider)


def test_successful_deployment_downloads_validates_then_activates():
    provider = InMemoryModelDeploymentProvider(
        versions={("local-safety-detector", "robot-01-onboard"): "4.0.2"}
    )
    manager = ModelDeploymentManager(provider)

    result = manager.deploy(request())

    assert result.status is ModelDeploymentStatus.APPLIED
    assert result.previous_version == "4.0.2"
    assert [entry.status for entry in manager.history] == [
        ModelDeploymentStatus.REQUESTED,
        ModelDeploymentStatus.DOWNLOADING,
        ModelDeploymentStatus.VALIDATING,
        ModelDeploymentStatus.APPLIED,
    ]
    assert provider.current_version("local-safety-detector", "robot-01-onboard") == "4.1.0"


def test_validation_failure_never_activates_the_bad_artifact():
    provider = InMemoryModelDeploymentProvider(
        versions={("local-safety-detector", "robot-01-onboard"): "4.0.2"},
        fail_at="validate",
    )
    manager = ModelDeploymentManager(provider)

    result = manager.deploy(request())

    assert result.status is ModelDeploymentStatus.FAILED
    assert result.reason == "artifact_validation_failed"
    assert not any(call[0] == "activate" for call in provider.calls)
    assert provider.current_version("local-safety-detector", "robot-01-onboard") == "4.0.2"


def test_activation_failure_restores_the_previous_version():
    provider = InMemoryModelDeploymentProvider(
        versions={("local-safety-detector", "robot-01-onboard"): "4.0.2"},
        fail_at="activate",
    )
    manager = ModelDeploymentManager(provider)

    result = manager.deploy(request())

    assert result.status is ModelDeploymentStatus.ROLLED_BACK
    assert result.reason == "activation_failed_previous_version_restored"
    assert ("rollback", "local-safety-detector", "4.0.2", "robot-01-onboard") in provider.calls


def test_activation_exception_also_restores_the_previous_version():
    class RaisingActivationProvider(InMemoryModelDeploymentProvider):
        def activate(self, model_id, model_version, artifact_ref, target_node_id):
            raise RuntimeError("runtime reload failed")

    provider = RaisingActivationProvider(
        versions={("local-safety-detector", "robot-01-onboard"): "4.0.2"}
    )

    result = ModelDeploymentManager(provider).deploy(request())

    assert result.status is ModelDeploymentStatus.ROLLED_BACK
    assert result.reason == "activation_error:RuntimeError_previous_version_restored"
    assert provider.current_version("local-safety-detector", "robot-01-onboard") == "4.0.2"


def test_deployment_result_converts_directly_to_the_shared_wire_contract():
    result = ModelDeploymentManager(InMemoryModelDeploymentProvider()).deploy(request())
    context = MessageContext(
        source_id="model-manager-a",
        node_id="edge-node-a",
        entity_id="robot-01",
        zone_id="zone-a",
        correlation_id=result.deployment_id,
        timestamp="2026-08-25T12:00:00Z",
        message_id="message-model-1",
    )

    message = model_deployment_record_message(result, context)

    assert message["channel"] == "model_deployment_result"
    assert message["payload"]["status"] == "APPLIED"
    assert message["payload"]["target_node_id"] == "robot-01-onboard"
