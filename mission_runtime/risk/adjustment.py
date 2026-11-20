"""Requests only currently-existing observation/analysis capability
kinds, raising the requested level when risk or evidence-insufficiency
rises and lowering it again once risk falls or evidence becomes
sufficient (AI-S-05, AI-R-02).

implements: AI-S-05, AI-R-02
tests: tests/test_risk_adjustment.py, tests/test_perception_loop.py
흡수된 ID: 구 AI-R-04 — 이 모듈은 원래 그 ID 하나만 적고 있었다. AI-R-04 는
CLAUDE.md §5 에서 AI-R-02 와 신규 AI-C-19 로 흡수되어 **사라진 번호**이고, 폐기된
ID 를 유일한 근거로 적은 모듈은 어느 살아 있는 요구사항의 몫인지 추적되지 않는다.
실체는 AI-S-05 의 추가 정보 요청 사슬에서 "어느 **수준**의 관측·분석을 요청하는가"
이고, 그 수준이 위험도에 따라 오르내리는 쪽이 AI-R-02 다.

Never requests a sensor or model that does not exist right now — it
only ever asks `CapabilitySelector` to pick among capability kinds that
are already registered (AI-S-05: "없는 기능을 요청해서는 안 된다").

**수준을 고르는 것이 명령이 아니다**(AI-C-19). 이 모듈이 내는 것은 요청할 수준의
capability kind 하나이고, 그 수준으로 실제 장치를 움직이는 일은 제어 경계를 거친다.
"""


from __future__ import annotations

from mission_runtime.contracts.profile import ResourceBudget
from mission_runtime.registry.capability_registry import CapabilityRegistry
from mission_runtime.selection.selector import CapabilitySelector, SelectionResult


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
