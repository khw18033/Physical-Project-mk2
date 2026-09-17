"""Shared helpers used by every DEVS atomic model in `simulator/devs/`.

implements: AI-B-01, AI-B-04, AI-B-07, AI-B-09
"""

from __future__ import annotations

import tokenize
from pathlib import Path

from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import CompatibilityProfile, ResourceCost
from perception_framework.registry.capability_registry import ProviderRegistration
from perception_framework.runtime.application import CapabilitySpec

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "perception_framework"
DEFAULT_CORE_DIRS = ("perception", "decision", "risk", "runtime", "execution", "registry", "selection", "contracts")


def core_source_mentions(token: str, dirs: tuple[str, ...] = DEFAULT_CORE_DIRS) -> list[str]:
    """Occurrences of `token` in *executable* core code (comments/strings
    excluded). Enforces 원칙 #1/#3/#7, AI-B-09: adding hardware, a provider
    or a domain must never require a core-code edit."""
    hits = []
    for directory in dirs:
        for path in (PACKAGE_DIR / directory).rglob("*.py"):
            with open(path, "rb") as handle:
                for tok in tokenize.tokenize(handle.readline):
                    if tok.type in (tokenize.COMMENT, tokenize.STRING):
                        continue
                    if token in tok.string:
                        hits.append(f"{directory}/{path.name}:{tok.start[0]}: {tok.string}")
    return hits


class HealthBoard:
    """Mutable health state for providers a scenario wants to kill/revive,
    keyed by the scenario's own `health_ref` name (AI-B-07: a provider's own
    health probe failing/crashing must never break the registry)."""

    def __init__(self) -> None:
        self._state: dict[str, str] = {}

    def set(self, ref: str, alive: bool = True, raises: bool = False) -> None:
        self._state[ref] = "raise" if raises else ("alive" if alive else "dead")

    def probe(self, ref: str):
        def _check() -> bool:
            mode = self._state.get(ref, "alive")
            if mode == "raise":
                raise RuntimeError(f"probe for {ref!r} crashed (scenario-injected)")
            return mode == "alive"

        return _check


def build_registration(entry: dict, health_board: HealthBoard) -> ProviderRegistration:
    """`latency_ms`, when present, is a *measured* value (real inference/
    round-trip timing from an actual run, never invented — AI-B-01) fed into
    `ResourceCost.max_latency_ms`. This is not new selector logic: `budget.
    can_afford(cost)` already compares it (`contracts/profile.py`), so a
    scenario whose `budget.max_latency_ms` is tighter than a provider's real
    measured latency makes that provider genuinely incompatible under
    `CapabilitySelector`, the same way a compute/memory shortfall already
    does. `measured_accuracy`, when present, is carried through unchanged so
    a scenario's `accuracy_floor` expectation can check it — this framework
    has no accuracy/quality field in `CompatibilityProfile` yet (traceability.
    md already flags AI-B-01's "검증" field as partial), so this is recorded
    as passthrough metadata on the registration, not a selector input.
    """
    health_check = health_board.probe(entry["health_ref"]) if "health_ref" in entry else None
    reg = ProviderRegistration(
        capability_kind=entry["kind"],
        provider_id=entry["provider_id"],
        version=entry.get("version", "1"),
        compatibility=CompatibilityProfile(
            required_hw_tags=tuple(entry.get("hw_tags", ())),
            preferred_hw_tags=tuple(entry.get("preferred_hw_tags", ())),
            priority=entry.get("priority", 50),
            cost=ResourceCost(
                compute_units=entry.get("compute", 1.0),
                memory_mb=entry.get("memory", 64.0),
                max_latency_ms=entry.get("latency_ms"),
            ),
        ),
        requirement=CapabilityRequirement(),
        health_check=health_check,
    )
    if "measured_accuracy" in entry:
        reg.measured_accuracy = entry["measured_accuracy"]  # passthrough metadata, see docstring
    return reg


def build_spec(entry: dict) -> CapabilitySpec:
    return CapabilitySpec(
        kind=entry["kind"],
        is_core=entry.get("core", False),
        degrade_rank=entry.get("rank", 0),
        requirement=CapabilityRequirement(required=tuple(entry.get("requires", ()))),
    )
