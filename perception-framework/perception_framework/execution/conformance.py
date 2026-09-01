"""Generic conformance checks for a new provider registration before it
is treated as fully validated (AI-B-09).

implements: AI-B-09

The goal is explicitly not to grade a provider's model accuracy — it is
to confirm the provider satisfies the common interface and the
resource/failure isolation rules the rest of the framework depends on
(AI-B-09: "검증 목적은 기존 모델보다 정확도를 높이는 것이 아니라 새
구성요소가 공통 인터페이스와 자원·장애 격리 규칙을 만족하는지 확인하는
것이다").
"""

from __future__ import annotations

from dataclasses import dataclass

from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


@dataclass(frozen=True)
class ConformanceReport:
    passed: bool
    failures: tuple[str, ...]


def check_provider_conformance(reg: ProviderRegistration, registry: CapabilityRegistry) -> ConformanceReport:
    failures: list[str] = []

    if not reg.capability_kind:
        failures.append("missing_capability_kind")
    if not reg.provider_id:
        failures.append("missing_provider_id")
    if not reg.version:
        failures.append("missing_version")

    # Registering/unregistering this provider must not disturb any other
    # capability kind already present (failure isolation, AI-C-11).
    other_kinds = registry.known_capability_kinds() - {reg.capability_kind}
    before = {kind: len(registry.available_providers(kind)) for kind in other_kinds}
    registry.register_local(reg)
    registry.unregister_local(reg.capability_kind, reg.provider_id)
    after = {kind: len(registry.available_providers(kind)) for kind in other_kinds}
    if before != after:
        failures.append("registration_disturbed_unrelated_capability_kinds")

    return ConformanceReport(passed=not failures, failures=tuple(failures))
