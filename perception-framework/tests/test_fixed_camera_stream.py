"""implements: AI-E-01"""

from perception_framework.contracts.capability import CapabilityState
from perception_framework.contracts.profile import CompatibilityProfile
from perception_framework.providers.fakes import InMemoryTransportProvider, JsonSerializerProvider
from perception_framework.reference.fixed_camera_stream import FixedCameraPerceptionStream
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def add(registry: CapabilityRegistry, kind: str, provider_id: str = "p") -> None:
    registry.register_local(
        ProviderRegistration(
            capability_kind=kind,
            provider_id=provider_id,
            version="1",
            compatibility=CompatibilityProfile(),
        )
    )


def test_no_video_input_publishes_nothing_but_does_not_raise():
    registry = CapabilityRegistry()
    transport = InMemoryTransportProvider()
    stream = FixedCameraPerceptionStream(registry, JsonSerializerProvider(), transport, "topic")

    outcome = stream.publish_if_available({"boxes": []})

    assert outcome.published is False
    assert outcome.capability_state == CapabilityState.DISABLED
    assert outcome.reason == "no_video_input"
    assert transport.published == []


def test_video_only_still_publishes_a_degraded_result():
    # No classification available -- AI-E-01: 보정/추가 분석 없이도 가능한
    # 범위의 결과를 계속 제공해야 한다. Fixed camera has no safety fallback
    # to drop to; it just keeps publishing what it can.
    registry = CapabilityRegistry()
    add(registry, "media.video_input")
    transport = InMemoryTransportProvider()
    stream = FixedCameraPerceptionStream(registry, JsonSerializerProvider(), transport, "topic")

    outcome = stream.publish_if_available({"boxes": []})

    assert outcome.published is True
    assert outcome.capability_state == CapabilityState.DEGRADED
    assert len(transport.published) == 1


def test_video_and_classify_publishes_full_capability_result():
    registry = CapabilityRegistry()
    add(registry, "media.video_input")
    add(registry, "perception.classify")
    transport = InMemoryTransportProvider()
    stream = FixedCameraPerceptionStream(registry, JsonSerializerProvider(), transport, "topic")

    outcome = stream.publish_if_available({"boxes": [{"label": "forklift"}]})

    assert outcome.published is True
    assert outcome.capability_state == CapabilityState.ACTIVE
