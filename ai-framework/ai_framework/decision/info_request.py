"""Requests decision-supporting information only from sources that
actually exist right now, and proceeds with a stated gap when none do.

implements: AI-D-03

AI-D-03: "의사결정에 필요한 근거가 부족하거나 서로 충돌하면 현재 실제로 사용할 수
있는 정보원 중 필요한 항목만 선택해 요청해야 한다 ... 특정 정보원이 항상 존재한다고
가정해서는 안 된다. 추가 정보가 없으면 확인 가능한 범위까지만 판단하고 부족한 근거를
명시해야 한다."

Consumes `SubtaskValidator`'s `missing_evidence` (AI-D-02) and reuses the
same registry/selector machinery as AI-S-05, so "what can I ask for" is
answered by the capability registry rather than by a hardcoded list of
cameras, trackers or digital-twin services.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_framework.contracts.profile import ResourceBudget
from ai_framework.registry.capability_registry import CapabilityRegistry
from ai_framework.selection.selector import CapabilitySelector


@dataclass(frozen=True)
class EvidenceNeed:
    """One missing or contested precondition, and which capability kinds
    could supply it. Several kinds may satisfy the same need; only the
    ones currently usable are ever requested.
    """

    evidence_id: str
    candidate_capability_kinds: tuple[str, ...]
    conflicting: bool = False


@dataclass(frozen=True)
class SupportRequest:
    evidence_id: str
    capability_kind: str
    provider_id: str


@dataclass(frozen=True)
class SupportPlan:
    """What will be asked for, and what stays unresolved.

    `unresolved` is not an error state — it is the explicit "부족한 근거
    명시" the requirement demands, so the caller can still decide within
    the confirmable range instead of stalling.
    """

    requests: tuple[SupportRequest, ...]
    unresolved: tuple[str, ...]

    @property
    def fully_supported(self) -> bool:
        return not self.unresolved


class DecisionSupportRequester:
    def __init__(self, registry: CapabilityRegistry) -> None:
        self._selector = CapabilitySelector(registry)

    def plan(
        self,
        needs: list[EvidenceNeed],
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> SupportPlan:
        requests: list[SupportRequest] = []
        unresolved: list[str] = []

        for need in needs:
            chosen = None
            for kind in need.candidate_capability_kinds:
                result = self._selector.select(kind, node_tags, budget)
                if result.provider is not None:
                    chosen = (kind, result.provider.provider_id)
                    break  # 필요한 항목만 요청 — 첫 사용 가능 정보원에서 멈춘다
            if chosen is None:
                unresolved.append(need.evidence_id)
                continue
            requests.append(SupportRequest(need.evidence_id, chosen[0], chosen[1]))

        return SupportPlan(tuple(requests), tuple(unresolved))

    def plan_for_validation_gaps(
        self,
        missing_evidence: tuple[str, ...],
        sources_by_evidence: dict[str, tuple[str, ...]],
        node_tags: set[str],
        budget: ResourceBudget,
    ) -> SupportPlan:
        """Convenience path from AI-D-02's output straight into a plan.

        Evidence with no declared source at all is reported as unresolved
        rather than guessed at (금지 사항: 없는 기능을 요청하지 않는다).
        """
        needs = [
            EvidenceNeed(evidence_id=ev, candidate_capability_kinds=sources_by_evidence.get(ev, ()))
            for ev in missing_evidence
        ]
        return self.plan(needs, node_tags, budget)
