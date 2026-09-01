"""implements: AI-N-01"""

from perception_framework.contracts.capability import CapabilityState
from perception_framework.contracts.profile import CompatibilityProfile
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.reference.local_safety import LocalSafetyJudge, SafetyState


def add(registry: CapabilityRegistry, kind: str, provider_id: str = "p") -> None:
    registry.register_local(
        ProviderRegistration(
            capability_kind=kind,
            provider_id=provider_id,
            version="1",
            compatibility=CompatibilityProfile(),
        )
    )


def test_no_video_input_falls_back_to_safe_stop_even_with_perception_available():
    registry = CapabilityRegistry()
    add(registry, "perception.classify")  # present, but irrelevant without video
    judge = LocalSafetyJudge(registry)

    result = judge.judge()

    assert result.state == SafetyState.SAFE_STOP
    assert result.capability_state == CapabilityState.DISABLED
    assert result.basis == ()


def test_video_only_gives_caution():
    registry = CapabilityRegistry()
    add(registry, "media.video_input")
    judge = LocalSafetyJudge(registry)

    result = judge.judge()

    assert result.state == SafetyState.CAUTION
    assert result.capability_state == CapabilityState.DEGRADED


def test_all_optional_capabilities_present_gives_full_awareness():
    registry = CapabilityRegistry()
    for kind in ("media.video_input", "perception.classify", "perception.track", "perception.distance"):
        add(registry, kind)
    judge = LocalSafetyJudge(registry)

    result = judge.judge()

    assert result.state == SafetyState.FULL_AWARENESS
    assert result.capability_state == CapabilityState.ACTIVE


def test_losing_one_optional_provider_degrades_the_level_without_crashing():
    registry = CapabilityRegistry()
    for kind in ("media.video_input", "perception.classify", "perception.track", "perception.distance"):
        add(registry, kind)
    judge = LocalSafetyJudge(registry)
    assert judge.judge().state == SafetyState.FULL_AWARENESS

    registry.unregister_local("perception.distance", "p")
    result = judge.judge()

    assert result.state == SafetyState.MONITORED
    assert result.capability_state == CapabilityState.DEGRADED


def test_video_lost_after_running_falls_back_to_safe_stop():
    registry = CapabilityRegistry()
    for kind in ("media.video_input", "perception.classify"):
        add(registry, kind)
    judge = LocalSafetyJudge(registry)
    assert judge.judge().state == SafetyState.MONITORED

    registry.unregister_local("media.video_input", "p")
    result = judge.judge()

    assert result.state == SafetyState.SAFE_STOP
    assert result.capability_state == CapabilityState.DISABLED
