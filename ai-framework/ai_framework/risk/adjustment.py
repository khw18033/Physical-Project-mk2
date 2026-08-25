"""Requests only currently-existing observation/analysis capability
kinds, raising the requested level when risk or evidence-insufficiency
rises and lowering it again once risk falls or evidence becomes
sufficient (AI-R-04).

Never requests a sensor or model that does not exist right now — it
only ever asks `CapabilitySelector` to pick among capability kinds that
are already registered (AI-R-04: "존재하지 않는 센서나 실행할 수 없는
모델을 요청해서는 안 된다").
"""

from __future__ import annotations

from ai_framework.contracts.profile import ResourceBudget
from ai_framework.registry.capability_registry import CapabilityRegistry
from ai_framework.selection.selector import CapabilitySelector, SelectionResult


class ObservationLevelAdjuster:
    def __init__(self, registry: CapabilityRegistry, levels_low_to_high: list[str]) -> None:
        """`levels_low_to_high` e.g. ["risk.rule_based", "risk.timeseries_model"]."""
        self._selector = CapabilitySelector(registry)
        self._levels = levels_low_to_high

    def request_level(
        self,
        *,
        risk_level: float,
        evidence_sufficiency: float,
        risk_threshold: float,
        evidence_threshold: float,
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> SelectionResult:
        needs_high_level = risk_level >= risk_threshold or evidence_sufficiency < evidence_threshold
        ordered = list(reversed(self._levels)) if needs_high_level else list(self._levels)
        return self._selector.select_with_degrade(ordered, node_tags, budget)
