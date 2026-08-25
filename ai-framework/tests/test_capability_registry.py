"""tests for: AI-C-10, AI-C-11, AI-B-07"""

from ai_framework.contracts.capability import CapabilityRequirement
from ai_framework.contracts.profile import CompatibilityProfile
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def make_reg(kind, provider_id, priority=100, healthy=True):
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version="1.0",
        compatibility=CompatibilityProfile(priority=priority),
        requirement=CapabilityRequirement(),
        health_check=(lambda: healthy),
    )


def test_register_and_query():
    registry = CapabilityRegistry()
    registry.register_local(make_reg("perception.classify", "yolo-local"))

    providers = registry.available_providers("perception.classify")

    assert len(providers) == 1
    assert providers[0].provider_id == "yolo-local"


def test_missing_capability_returns_empty_not_error():
    registry = CapabilityRegistry()

    assert registry.available_providers("perception.classify") == []
    assert registry.has_capability("perception.classify") is False


def test_unhealthy_provider_is_excluded_but_does_not_raise():
    registry = CapabilityRegistry()
    registry.register_local(make_reg("perception.track", "bytetrack", healthy=False))

    assert registry.available_providers("perception.track") == []


def test_health_check_raising_is_treated_as_unhealthy():
    registry = CapabilityRegistry()

    def boom():
        raise RuntimeError("probe failed")

    registry.register_local(
        ProviderRegistration(
            capability_kind="perception.distance",
            provider_id="stereo",
            version="1.0",
            health_check=boom,
        )
    )

    # A provider's own health probe failing must not crash the registry
    # (AI-B-07) -- it is simply excluded from the available list.
    assert registry.available_providers("perception.distance") == []


def test_remote_snapshot_persists_when_central_registry_goes_silent():
    registry = CapabilityRegistry()
    registry.merge_remote_snapshot(
        {"perception.classify": {"yolo-edge": make_reg("perception.classify", "yolo-edge")}}
    )

    assert len(registry.available_providers("perception.classify")) == 1

    # Central registry stops responding: the node simply never calls
    # merge_remote_snapshot again, but must keep using the last known-good
    # snapshot instead of reporting the capability as gone (AI-C-10).
    assert len(registry.available_providers("perception.classify")) == 1


def test_local_registration_overrides_stale_remote_entry_with_same_id():
    registry = CapabilityRegistry()
    registry.merge_remote_snapshot(
        {"perception.classify": {"model-a": make_reg("perception.classify", "model-a", healthy=False)}}
    )
    registry.register_local(make_reg("perception.classify", "model-a", healthy=True))

    providers = registry.available_providers("perception.classify")

    assert len(providers) == 1
    assert providers[0].is_healthy() is True


def test_unregister_local_removes_provider():
    registry = CapabilityRegistry()
    registry.register_local(make_reg("perception.classify", "yolo-local"))
    registry.unregister_local("perception.classify", "yolo-local")

    assert registry.available_providers("perception.classify") == []
