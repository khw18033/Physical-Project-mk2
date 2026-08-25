"""Selective auxiliary/boost function execution (AI-E-04).

Executes only currently-registered optional providers, walking
candidates in priority order, and stops immediately once the required
evidence is met instead of running every remaining (possibly costly)
candidate (AI-E-04: "필요한 근거가 확보되면 고비용 보조 기능은 즉시
중단해야 한다"). A missing or unavailable provider for a candidate kind
is skipped, not treated as an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ai_framework.contracts.profile import ResourceBudget
from ai_framework.providers.adapters import AIRuntimeProvider
from ai_framework.registry.capability_registry import CapabilityRegistry
from ai_framework.selection.selector import CapabilitySelector


@dataclass(frozen=True)
class AuxiliaryRunRecord:
    capability_kind: str
    result: object


class AuxiliaryExecutionOrchestrator:
    def __init__(self, registry: CapabilityRegistry, runtime_by_provider_id: dict[str, AIRuntimeProvider]) -> None:
        self._selector = CapabilitySelector(registry)
        self._runtime_by_provider_id = runtime_by_provider_id

    def run_until_sufficient(
        self,
        candidate_kinds_by_priority: list[str],
        inputs: object,
        node_tags: set[str],
        budget: ResourceBudget,
        *,
        evidence_check: Callable[[list[AuxiliaryRunRecord]], bool],
    ) -> list[AuxiliaryRunRecord]:
        records: list[AuxiliaryRunRecord] = []
        for kind in candidate_kinds_by_priority:
            if evidence_check(records):
                break  # already sufficient -> stop before running the next candidate

            result = self._selector.select(kind, node_tags, budget)
            if result.provider is None:
                continue  # no usable provider for this kind -> skipped, not an error

            runtime = self._runtime_by_provider_id.get(result.provider.provider_id)
            if runtime is None or not runtime.is_available():
                continue

            output = runtime.infer(kind, inputs)
            records.append(AuxiliaryRunRecord(kind, output))
        return records
