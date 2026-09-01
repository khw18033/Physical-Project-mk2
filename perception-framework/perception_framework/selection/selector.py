"""Provider selection: compatibility filter + minimal-resource + degrade order.

implements: AI-B-01, AI-B-04, AI-B-06, AI-C-13, AI-C-16

Selection never assumes a specific provider exists. When nothing is
compatible with the current node tags/budget, callers get an explicit
`SelectionResult(provider=None, reason=...)` instead of an exception —
a missing optional capability must degrade the caller, not crash it
(AI-C-11; 구현 시 금지 사항: 특정 모델이 없으면 시스템을 시작하지 못하게
만들지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from perception_framework.contracts.profile import ResourceBudget
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration


@dataclass(frozen=True)
class SelectionResult:
    provider: ProviderRegistration | None
    reason: str


class CapabilitySelector:
    """Picks the lowest-cost, highest-priority compatible provider."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        placement_filter: Callable[[ProviderRegistration], str | None] | None = None,
    ) -> None:
        """`placement_filter` returns `None` for a placeable provider, or a
        reason string for one that must not be placed in this deployment.

        It runs *before* compatibility/budget filtering so a deployment
        boundary — e.g. a closed network refusing a provider that declared
        outbound reach (AI-C-16) — is applied ahead of placement instead of
        surfacing as a runtime failure. The selector never learns what the
        boundary is about; it only passes the reason through.
        """
        self._registry = registry
        self._placement_filter = placement_filter

    def select(
        self,
        capability_kind: str,
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> SelectionResult:
        candidates = self._registry.available_providers(capability_kind)
        if not candidates:
            return SelectionResult(None, reason="no_provider_registered")

        if self._placement_filter is not None:
            rejections = {c.provider_id: self._placement_filter(c) for c in candidates}
            permitted = [c for c in candidates if rejections[c.provider_id] is None]
            if not permitted:
                # Only this capability kind loses its candidates; unrelated
                # kinds are untouched (AI-C-11, AI-C-16).
                first_reason = next(r for r in rejections.values() if r is not None)
                return SelectionResult(None, reason=first_reason)
            candidates = permitted

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
