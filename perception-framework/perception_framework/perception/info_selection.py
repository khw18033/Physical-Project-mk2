"""Selects which additional-information capability kinds to invoke when
evidence is insufficient, and stops requesting once it is sufficient
(AI-S-05).

implements: AI-S-05

Reuses `CapabilityRegistry`/`CapabilitySelector` — there is no
assumption that any particular additional source (multi-view, tracking
history, depth, ReID, open-vocabulary perception, VLM, re-observation)
exists; only currently registered, usable candidates are ever scored or
requested (AI-S-05: "없는 기능을 요청해서는 안 된다").
"""

from __future__ import annotations

from dataclasses import dataclass

from perception_framework.contracts.profile import ResourceBudget
from perception_framework.registry.capability_registry import CapabilityRegistry
from perception_framework.selection.selector import CapabilitySelector


@dataclass(frozen=True)
class InfoRequest:
    capability_kind: str
    expected_gain: float


class AdditionalInfoSelector:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self._selector = CapabilitySelector(registry)

    def select_requests(
        self,
        candidate_gains: dict[str, float],
        node_tags: set[str],
        budget: ResourceBudget,
        *,
        required_evidence_level: float,
        current_evidence_level: float,
    ) -> list[InfoRequest]:
        if current_evidence_level >= required_evidence_level:
            return []  # already sufficient -> stop requesting more (연산·네트워크 사용 절약)

        ranked = sorted(candidate_gains.items(), key=lambda kv: kv[1], reverse=True)
        requests: list[InfoRequest] = []
        for kind, gain in ranked:
            result = self._selector.select(kind, node_tags, budget)
            if result.provider is None:
                continue  # not currently usable -> never requested
            requests.append(InfoRequest(kind, gain))
        return requests
