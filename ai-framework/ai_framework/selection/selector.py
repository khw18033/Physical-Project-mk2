"""Provider selection: compatibility filter + minimal-resource + degrade order.

implements: AI-B-01, AI-B-04, AI-B-06, AI-C-13

Selection never assumes a specific provider exists. When nothing is
compatible with the current node tags/budget, callers get an explicit
`SelectionResult(provider=None, reason=...)` instead of an exception —
a missing optional capability must degrade the caller, not crash it
(AI-C-11; 구현 시 금지 사항: 특정 모델이 없으면 시스템을 시작하지 못하게
만들지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_framework.contracts.profile import ResourceBudget
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


@dataclass(frozen=True)
class SelectionResult:
    provider: ProviderRegistration | None
    reason: str


class CapabilitySelector:
    """Picks the lowest-cost, highest-priority compatible provider."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def select(
        self,
        capability_kind: str,
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> SelectionResult:
        candidates = self._registry.available_providers(capability_kind)
        if not candidates:
            return SelectionResult(None, reason="no_provider_registered")

        compatible = [c for c in candidates if c.compatibility.is_compatible(node_tags, budget)]
        if not compatible:
            return SelectionResult(None, reason="no_compatible_provider_within_budget")

        # Lower priority number wins; then the provider whose *preferred*
        # resources this node actually has (AI-B-04 — preference ranks,
        # it never excludes); then lowest compute cost so resource usage
        # stays minimal by default (AI-C-13, 절대 준수 원칙 #5).
        best = min(
            compatible,
            key=lambda c: (
                c.compatibility.priority,
                c.compatibility.preference_penalty(node_tags),
                c.compatibility.cost.compute_units,
            ),
        )
        return SelectionResult(best, reason="selected")

    def select_with_degrade(
        self,
        capability_kinds_by_priority: list[str],
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> SelectionResult:
        """Try capability kinds in priority order, falling through to the
        next candidate kind when the previous has no usable provider.

        This is the step-down path AI-B-06 requires when a preferred
        provider/resource disappears: the caller supplies kinds ordered
        from richest to most conservative (e.g. ["risk.timeseries_model",
        "risk.rule_based"]) and gets the best one that is actually usable
        right now.
        """
        last_reason = "no_capability_kinds_given"
        for kind in capability_kinds_by_priority:
            result = self.select(kind, node_tags, budget)
            if result.provider is not None:
                return result
            last_reason = result.reason
        return SelectionResult(None, reason=last_reason)
