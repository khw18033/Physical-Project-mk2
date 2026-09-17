"""Requests decision-supporting information only from sources that
actually exist right now, and proceeds with a stated gap when none do.

implements: AI-S-05

이 모듈은 원래 구 요구사항 AI-D-03("추가 정보 요청")을 구현했었다. AI-D 계열
(서브태스크 생성·검증)은 최신 요구사항 시트에서 전부 제거되어 가시화 파트로
이관됐고, AI-D-03의 실질 기능만 신규 AI-S-05("추가 정보 판단·선택·요청")로
흡수됐다(CLAUDE.md, docs/ai/requirement-traceability.md 참고) — 코드는 그대로
유효하므로 옮기지 않고 요구사항 ID만 정정한다.

AI-S-05: "미확인, 근거 부족·충돌 또는 위험 분석 등에서 현재 업무가 요구하는
정보와 객체·환경 레코드에 확보된 근거를 비교해 부족한 정보의 종류를 식별하고,
현재 사용 가능한 관측·분석 capability 중 적합한 후보를 선택·요청할 수 있어야
한다 ... 이용 가능한 후보가 없으면 확인 가능한 범위까지만 판단하면서 부족한
근거를 남겨야 한다."

Consumes a caller-supplied `missing_evidence` list and reuses the
same registry/selector machinery as `perception/info_selection.py`, so
"what can I ask for" is answered by the capability registry rather than by
a hardcoded list of cameras, trackers or digital-twin services. A caller
that has an `EvidenceGap` from `perception/purpose_requirements.py`
(AI-S-07) can turn its `missing_required` fields into `EvidenceNeed`s here
to close the "목적별 요구 근거 → 부족분 → 요청" loop; this module does not
import that one to keep perception/decision layering one-directional.
"""

from __future__ import annotations

from dataclasses import dataclass

from perception_framework.contracts.profile import ResourceBudget
from perception_framework.registry.capability_registry import CapabilityRegistry
from perception_framework.selection.selector import CapabilitySelector


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
