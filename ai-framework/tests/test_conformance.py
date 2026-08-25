"""tests for: AI-B-09"""

from ai_framework.contracts.capability import CapabilityRequirement
from ai_framework.contracts.profile import CompatibilityProfile
from ai_framework.execution.conformance import check_provider_conformance
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


def test_well_formed_provider_passes():
    registry = CapabilityRegistry()
    reg = ProviderRegistration(
        capability_kind="perception.classify",
        provider_id="new-model",
        version="1.0",
        compatibility=CompatibilityProfile(),
        requirement=CapabilityRequirement(),
    )

    report = check_provider_conformance(reg, registry)

    assert report.passed is True
    assert report.failures == ()


def test_missing_required_fields_are_reported():
    registry = CapabilityRegistry()
    reg = ProviderRegistration(capability_kind="", provider_id="", version="")

    report = check_provider_conformance(reg, registry)

    assert report.passed is False
    assert "missing_capability_kind" in report.failures
    assert "missing_provider_id" in report.failures
    assert "missing_version" in report.failures


def test_flaky_health_check_does_not_break_the_conformance_check_itself():
    # ProviderRegistration.is_healthy() already swallows probe exceptions
    # by design (AI-B-07) -- the conformance check must not itself raise
    # even so, and the provider must come out treated as unhealthy.
    registry = CapabilityRegistry()

    def boom():
        raise RuntimeError("bad probe")

    reg = ProviderRegistration(
        capability_kind="perception.classify", provider_id="flaky", version="1.0", health_check=boom
    )

    report = check_provider_conformance(reg, registry)  # must not raise

    assert report.passed is True
    assert reg.is_healthy() is False


def test_registering_new_provider_does_not_disturb_unrelated_capability_kinds():
    registry = CapabilityRegistry()
    registry.register_local(
        ProviderRegistration(capability_kind="perception.track", provider_id="existing", version="1.0")
    )
    reg = ProviderRegistration(capability_kind="perception.classify", provider_id="new-model", version="1.0")

    report = check_provider_conformance(reg, registry)

    assert report.passed is True
    assert len(registry.available_providers("perception.track")) == 1


def test_conformance_check_leaves_the_candidate_provider_unregistered_afterward():
    registry = CapabilityRegistry()
    reg = ProviderRegistration(capability_kind="perception.classify", provider_id="new-model", version="1.0")

    check_provider_conformance(reg, registry)

    assert registry.available_providers("perception.classify") == []
