"""Shared fixtures/helpers for the small number of tests that still need a
hand-built `ZoneApplication` (real-infra integration tests that don't fit
`simulator/scenarios/*.json` — see `simulator/README.md` for what does).
"""

from pathlib import Path

import pytest

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import (
    CompatibilityProfile,
    DeploymentProfile,
    ResourceBudget,
    ResourceCost,
)
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.runtime.application import CapabilitySpec, ZoneApplication

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "perception_framework"
CORE_DIRS = ["perception", "decision", "risk", "runtime", "execution", "registry", "selection", "contracts"]


def registration(
    kind: str,
    provider_id: str,
    *,
    priority: int = 50,
    compute: float = 1.0,
    memory: float = 64.0,
    hw_tags: tuple = (),
    preferred: tuple = (),
    requirement: CapabilityRequirement | None = None,
    health_check=None,
    version: str = "1",
) -> ProviderRegistration:
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version=version,
        compatibility=CompatibilityProfile(
            required_hw_tags=hw_tags,
            preferred_hw_tags=preferred,
            priority=priority,
            cost=ResourceCost(compute_units=compute, memory_mb=memory),
        ),
        requirement=requirement or CapabilityRequirement(),
        health_check=health_check,
    )


def profile_of(domain_id: str, kinds, *, node_tags=("cpu",), rule_set_id=None) -> DeploymentProfile:
    return DeploymentProfile(
        domain_id=domain_id,
        active_capability_kinds=tuple(kinds),
        rule_set_id=rule_set_id,
        node_tags=tuple(node_tags),
    )


def spec(kind: str, *, core: bool = False, rank: int = 0, requirement=None) -> CapabilitySpec:
    return CapabilitySpec(
        kind=kind,
        is_core=core,
        degrade_rank=rank,
        requirement=requirement or CapabilityRequirement(),
    )


def build_app(profile, registry, specs, node_tags=None) -> ZoneApplication:
    return ZoneApplication(profile, registry, specs, node_tags=node_tags)


def core_source_mentions(token: str) -> list[str]:
    """Occurrences of `token` in *executable* core code (AI-B-09, 원칙 #1/#3/#7)."""
    import tokenize

    hits = []
    for directory in CORE_DIRS:
        for path in (PACKAGE_DIR / directory).rglob("*.py"):
            with open(path, "rb") as handle:
                for tok in tokenize.tokenize(handle.readline):
                    if tok.type in (tokenize.COMMENT, tokenize.STRING):
                        continue
                    if token in tok.string:
                        hits.append(f"{directory}/{path.name}:{tok.start[0]}: {tok.string}")
    return hits


@pytest.fixture
def registry() -> CapabilityRegistry:
    return CapabilityRegistry()


@pytest.fixture
def ample_budget() -> ResourceBudget:
    return ResourceBudget(compute_units=100.0, memory_mb=8192.0)
