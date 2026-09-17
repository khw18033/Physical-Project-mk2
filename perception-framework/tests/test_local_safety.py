"""implements: AI-N-01"""

from perception_framework.contracts.capability import CapabilityState
from perception_framework.contracts.profile import CompatibilityProfile
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.reference.local_safety import (
    MOBILE_AGENT_OPTIONAL_KINDS,
    LocalSafetyJudge,
    SafetyState,
)


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


def test_default_judge_without_classify_or_track_is_monitored():
    # The *default* judge (full 3-kind scope) cannot tell "never registered
    # by design" apart from "lost to a failure" -- classify/track missing
    # either way reads as a degradation from the full default scope. This
    # pins that generic behavior; test_mobile_agent_profile_reaches_full_
    # awareness_without_classify_or_track below is the actual fix for a
    # deployment that never wants classify/track on-device.
    registry = CapabilityRegistry()
    for kind in ("media.video_input", "perception.distance"):
        add(registry, kind)
    judge = LocalSafetyJudge(registry)

    result = judge.judge()

    assert result.state == SafetyState.MONITORED
    assert result.capability_state == CapabilityState.DEGRADED
    assert result.basis == ("perception.distance",)


def test_mobile_agent_profile_reaches_full_awareness_without_classify_or_track():
    # 2026-09 redesign: a mobile agent moves semantic classify/track to the
    # edge (AI-S-01/06) and never hosts them on-device at all. Scoping the
    # judge to MOBILE_AGENT_OPTIONAL_KINDS means that absence is no longer
    # read as a degradation -- video+distance alone is this deployment's
    # complete on-device picture.
    registry = CapabilityRegistry()
    for kind in ("media.video_input", "perception.distance"):
        add(registry, kind)
    judge = LocalSafetyJudge(registry, expected_optional_kinds=MOBILE_AGENT_OPTIONAL_KINDS)

    result = judge.judge()

    assert result.state == SafetyState.FULL_AWARENESS
    assert result.capability_state == CapabilityState.ACTIVE
    assert result.basis == ("perception.distance",)


def test_mobile_agent_profile_still_drops_to_caution_without_distance():
    # Losing the one optional kind this profile actually expects still
    # degrades normally -- narrowing the scope must not silently hide a
    # real loss of the deployment's own expected capability.
    registry = CapabilityRegistry()
    add(registry, "media.video_input")
    judge = LocalSafetyJudge(registry, expected_optional_kinds=MOBILE_AGENT_OPTIONAL_KINDS)

    result = judge.judge()

    assert result.state == SafetyState.CAUTION
    assert result.capability_state == CapabilityState.DEGRADED
