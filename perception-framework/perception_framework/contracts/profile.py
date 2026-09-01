"""Execution compatibility, resource budget and deployment profile.

implements: AI-B-01, AI-B-04, AI-C-13, AI-C-15, AI-C-16

These types stay vendor-neutral on purpose: hardware/runtime conditions
are free-form string tags supplied by whoever registers a provider, not
enum members tied to a specific GPU/NPU/runtime vendor. New hardware or
execution modes are added by registering a new tag + profile, never by
editing this module (절대 준수 원칙 #1, #7).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ResourceCost:
    """Estimated resource footprint of running one provider/config.

    Units are intentionally abstract (`compute_units`) rather than tied
    to a specific accelerator's benchmark, since the same capability can
    be satisfied by a CPU model, a GPU model or a remote call.
    """

    compute_units: float = 0.0
    memory_mb: float = 0.0
    max_latency_ms: float | None = None


@dataclass(frozen=True)
class ResourceBudget:
    """A node's remaining resource budget at selection time (AI-B-06, AI-C-13)."""

    compute_units: float
    memory_mb: float
    max_latency_ms: float | None = None

    def can_afford(self, cost: ResourceCost) -> bool:
        if cost.compute_units > self.compute_units:
            return False
        if cost.memory_mb > self.memory_mb:
            return False
        if (
            cost.max_latency_ms is not None
            and self.max_latency_ms is not None
            and cost.max_latency_ms > self.max_latency_ms
        ):
            return False
        return True


@dataclass(frozen=True)
class CompatibilityProfile:
    """Declares where/how a provider is allowed to run (AI-B-01).

    `required_hw_tags` / `required_runtime_tags` must all be present on
    the executing node for the provider to be eligible at all.
    `preferred_hw_tags` are informative only: their absence must not
    exclude the provider, only lower its effective attractiveness to a
    selector that chooses to weigh preference (AI-B-04: "선호 자원이 없으면
    호환 가능한 일반 자원으로 대체").
    """

    required_hw_tags: tuple[str, ...] = ()
    preferred_hw_tags: tuple[str, ...] = ()
    required_runtime_tags: tuple[str, ...] = ()
    cost: ResourceCost = field(default_factory=ResourceCost)
    priority: int = 100  # lower = tried first / kept longest when degrading (AI-C-13, AI-B-06)

    # --- outbound reach declaration (AI-C-16) ---------------------------
    # Free-form "external reach targets" this provider needs in order to
    # work: a URL, a host:port, a bare hostname, a service name — whatever
    # the deployment uses to name a destination. Deliberately NOT an enum
    # of protocols/vendors (절대 준수 원칙 #1); the closed-network check is
    # performed by a policy that knows which locations this deployment
    # considers internal, not by this dataclass.
    #
    # Default is the empty tuple, i.e. "needs no external connection",
    # so every existing registration keeps its meaning unchanged.
    external_endpoints: tuple[str, ...] = ()
    # AI-C-16: "외부 AI 서비스나 외부 API를 사용하는 기능은 항상 선택 기능으로
    # 선언하고, 사용할 수 없으면 해당 기능만 비활성화". A provider that keeps
    # this True is simply dropped from the candidate set when its reach is
    # unavailable; one that sets it False is declaring that it cannot
    # degrade, which a closed-network profile must reject *before* placement
    # rather than discover as a runtime failure.
    external_optional: bool = True

    def is_compatible(self, node_tags: set[str], budget: ResourceBudget) -> bool:
        if not set(self.required_hw_tags).issubset(node_tags):
            return False
        if not set(self.required_runtime_tags).issubset(node_tags):
            return False
        return budget.can_afford(self.cost)

    def unmet_preferences(self, node_tags: set[str]) -> tuple[str, ...]:
        """Preferred-but-absent tags. Never affects eligibility — only
        ranking among already-compatible candidates (AI-B-04).
        """
        return tuple(tag for tag in self.preferred_hw_tags if tag not in node_tags)

    def preference_penalty(self, node_tags: set[str]) -> int:
        """How many preferred resources this node cannot offer.

        Used as a ranking term so that, given two compatible providers of
        equal priority, the one whose preferred resources are actually
        present wins — and so that a provider that prefers an accelerator
        still runs on a plain CPU node instead of being excluded
        (AI-B-04: "선호 자원이 없으면 호환 가능한 일반 자원으로 대체").
        """
        return len(self.unmet_preferences(node_tags))

    def requires_external_connection(self) -> bool:
        """Whether this provider declared any outbound reach at all.

        Registration information alone must reveal this, so a closed-network
        deployment can detect it before placement (AI-C-16).
        """
        return bool(self.external_endpoints)


@dataclass(frozen=True)
class DeploymentProfile:
    """Binds one domain deployment to adapters/capabilities/rules — data only.

    implements: AI-C-15

    A new domain (robot autonomy support, facility surveillance, river
    risk management, ...) must be expressible entirely as data here:
    which capability kinds are active, which rule set applies, and what
    node tags describe the target execution environment. Core
    perception/decision/risk code must never branch on `domain_id`
    (절대 준수 원칙 #3) — it only ever asks the registry/selector whether a
    capability kind is currently available.
    """

    domain_id: str
    active_capability_kinds: tuple[str, ...]
    rule_set_id: str | None = None
    node_tags: tuple[str, ...] = ()
    # AI-C-16: is this deployment a closed network (폐쇄망)? Defaults to True
    # because 절대 준수 원칙 #18 makes the closed network the operating
    # premise; a development/connected deployment opts out explicitly. It
    # changes nothing for providers that declare no external endpoints,
    # which is the default.
    closed_network: bool = True
    # Locations this deployment counts as inside the closed network. Free-form
    # host names and/or suffixes supplied as deployment data — never compiled
    # into core code.
    internal_endpoints: tuple[str, ...] = ()
