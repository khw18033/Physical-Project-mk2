"""Shared fixtures for the framework-property scenarios.

These scenarios do not measure model accuracy. They ask the five questions
the requirements actually care about:

  ① 새로운 것을 꽂아도 핵심 코드를 안 고치는가?      (AI-B-09, AI-C-04/10/12/15)
  ② 일부 기능이 없어져도 나머지가 계속 도는가?        (AI-C-05/11, AI-B-07)
  ③ 실행 환경이 바뀌면 자동으로 재구성되는가?        (AI-B-01/04/06, AI-C-13)
  ④ 로봇·감시·하천이 동일 프레임워크로 돌아가는가?    (AI-C-15)
  ⑤ 전송·관측·제어 계층이 서로 섞이지 않는가?        (AI-C-06/14, AI-O-04)
"""

from pathlib import Path

import pytest

from ai_framework.contracts.capability import CapabilityRequirement
from ai_framework.contracts.profile import (
    CompatibilityProfile,
    DeploymentProfile,
    ResourceBudget,
    ResourceCost,
)
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from ai_framework.runtime.application import CapabilitySpec, ZoneApplication

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "ai_framework"
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
    """Occurrences of `token` in *executable* core code.

    Enforces the project's central claim: adding hardware, a provider or a
    domain must not require editing core code (원칙 #1/#3/#7, AI-B-09).
    Comments and docstrings may name examples — what must never happen is
    a device/domain name reaching an identifier, literal or branch, so the
    check tokenizes comments and strings away.
    """
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
