"""The single application assembly every domain runs on.

implements: AI-C-05, AI-C-11, AI-C-13, AI-C-15, AI-B-06

This is the module that must stay identical whether the deployment is a
robot, a facility or a river (원칙 #3, AI-C-15). It contains no domain
name, no sensor name and no protocol name: it takes a `DeploymentProfile`
plus a `CapabilityRegistry` and resolves, for every capability kind the
profile activates, whether that kind is currently ACTIVE, DEGRADED or
DISABLED — and which provider serves it.

Capability kinds are supplied as data. Core kinds are the ones the
deployment must not lose; optional kinds are dropped first when resources
run short, in ascending priority order (AI-C-13: 요구조건 충족 후 최소 자원
사용 / AI-B-06: 우선순위가 낮은 선택 기능부터 축소).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_framework.contracts.capability import CapabilityRequirement, CapabilityState
from ai_framework.contracts.profile import DeploymentProfile, ResourceBudget
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from ai_framework.selection.selector import CapabilitySelector


@dataclass(frozen=True)
class CapabilitySpec:
    """What one capability kind needs, declared by the deployment.

    `degrade_rank` orders optional capabilities for step-down: the highest
    rank is shed first. Core capabilities are never shed.
    """

    kind: str
    is_core: bool = False
    requirement: CapabilityRequirement = field(default_factory=CapabilityRequirement)
    degrade_rank: int = 0


@dataclass(frozen=True)
class CapabilityResolution:
    kind: str
    state: CapabilityState
    provider: ProviderRegistration | None
    reason: str

    @property
    def is_running(self) -> bool:
        return self.state in (CapabilityState.ACTIVE, CapabilityState.DEGRADED)


class ZoneApplication:
    """Resolves the capability set for one deployment on one node."""

    def __init__(
        self,
        profile: DeploymentProfile,
        registry: CapabilityRegistry,
        specs: list[CapabilitySpec],
        *,
        node_tags: set[str] | None = None,
    ) -> None:
        self._profile = profile
        self._registry = registry
        self._selector = CapabilitySelector(registry)
        self._specs = {spec.kind: spec for spec in specs}
        self._node_tags = set(node_tags or profile.node_tags)
        self._resolutions: dict[str, CapabilityResolution] = {}

    # --- inputs that change at runtime ------------------------------------
    @property
    def node_tags(self) -> set[str]:
        return set(self._node_tags)

    def set_node_tags(self, tags: set[str]) -> None:
        """Execution environment changed (hardware swap, accelerator gained
        or lost). Upper-layer code never learns what changed — it only
        re-resolves (AI-B-01, AI-B-04).
        """
        self._node_tags = set(tags)

    @property
    def active_kinds(self) -> tuple[str, ...]:
        """Capability kinds this deployment uses at all. A kind absent from
        the profile is never installed or run (AI-C-15).
        """
        return tuple(k for k in self._profile.active_capability_kinds if k in self._specs)

    # --- resolution --------------------------------------------------------
    def resolve(self, budget: ResourceBudget) -> dict[str, CapabilityResolution]:
        """Recompute every activated capability's state under this budget.

        Optional capabilities are shed from the highest `degrade_rank` down
        until the remaining set fits; core capabilities are always attempted
        and are reported DISABLED (never silently dropped) if they cannot run.
        """
        remaining = ResourceBudget(
            compute_units=budget.compute_units,
            memory_mb=budget.memory_mb,
            max_latency_ms=budget.max_latency_ms,
        )
        resolutions: dict[str, CapabilityResolution] = {}

        ordered = sorted(
            (self._specs[kind] for kind in self.active_kinds),
            key=lambda s: (not s.is_core, s.degrade_rank),
        )

        core_unplaced = False
        for spec in ordered:
            if core_unplaced and not spec.is_core:
                # A core capability could not be placed at all. Letting an
                # optional capability consume the remaining resources anyway
                # would contradict "핵심 기능은 유지" (AI-B-06): the headroom
                # is reserved for the core function's recovery instead.
                resolutions[spec.kind] = CapabilityResolution(
                    spec.kind, CapabilityState.DISABLED, None, "core_capability_unplaced"
                )
                continue

            resolution = self._resolve_one(spec, remaining)
            resolutions[spec.kind] = resolution
            if spec.is_core and resolution.state is CapabilityState.DISABLED:
                core_unplaced = True
            if resolution.provider is not None:
                cost = resolution.provider.compatibility.cost
                remaining = ResourceBudget(
                    compute_units=remaining.compute_units - cost.compute_units,
                    memory_mb=remaining.memory_mb - cost.memory_mb,
                    max_latency_ms=remaining.max_latency_ms,
                )

        self._resolutions = resolutions
        return dict(resolutions)

    def _resolve_one(self, spec: CapabilitySpec, budget: ResourceBudget) -> CapabilityResolution:
        available_kinds = {
            kind for kind in self._registry.known_capability_kinds() if self._registry.has_capability(kind)
        }
        declared_state = spec.requirement.evaluate(available_kinds)
        if declared_state is CapabilityState.DISABLED:
            missing = [n for n in spec.requirement.required if n not in available_kinds]
            return CapabilityResolution(
                spec.kind, CapabilityState.DISABLED, None, f"missing_required:{','.join(missing)}"
            )

        selection = self._selector.select(spec.kind, self._node_tags, budget)
        if selection.provider is None:
            return CapabilityResolution(spec.kind, CapabilityState.DISABLED, None, selection.reason)

        return CapabilityResolution(spec.kind, declared_state, selection.provider, "selected")

    # --- queries -----------------------------------------------------------
    def state_of(self, kind: str) -> CapabilityState:
        resolution = self._resolutions.get(kind)
        return resolution.state if resolution else CapabilityState.DISABLED

    def running_kinds(self) -> tuple[str, ...]:
        return tuple(k for k, r in self._resolutions.items() if r.is_running)

    def core_kinds_running(self) -> bool:
        return all(
            self._resolutions[spec.kind].is_running
            for spec in self._specs.values()
            if spec.is_core and spec.kind in self._resolutions
        )

    def snapshot(self) -> dict[str, str]:
        return {kind: res.state.value for kind, res in self._resolutions.items()}
