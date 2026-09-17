"""목적별 요구 근거 -> 부족분 -> 관측 요청 -> 자율 수준까지 한 바퀴가 실제로
닫히는지 검증한다.

implements: AI-S-07, AI-S-05, AI-S-03, AI-C-19

왜 이 테스트가 따로 필요한가: 각 모듈(`perception/purpose_requirements.py`,
`decision/info_request.py`, `decision/autonomy_level.py`)에는 이미 각자의
단위 테스트가 있지만, **셋이 이어져 하나의 고리를 이룬다는 것**을 확인하는
테스트가 없었다. 2026-09-17 LOTUSim-Energy 검토에서 그 논문의 가장 큰 한계로
"이상 발견 -> 다른 이동체 자동 출동"이라는 폐루프를 실험으로 검증하지 않았다는
점을 지적하고, 우리 쪽 차별점을 거기 두기로 했다
(docs/ai/design/lotusim-reflection-plan.md) -- 그렇다면 그 고리가 우리
코드에서는 실제로 닫혀 있어야 하고, 그것을 증명하는 것이 이 파일이다.

`decision/`은 `perception/`을 import하지 않는다(단방향 계층). 이 테스트는
호출부의 입장에서 두 계층을 잇는다 -- 즉 연결은 새 코드가 아니라 호출 순서로
성립한다는 것 자체가 검증 대상이다.
"""
from perception_framework.contracts.capability import CapabilityRequirement
from perception_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from perception_framework.decision.autonomy_level import ActionContext, AutonomyLevel, grade
from perception_framework.decision.info_request import DecisionSupportRequester
from perception_framework.perception.purpose_requirements import (
    PurposeRequirement,
    PurposeRequirementRegistry,
)
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration

BUDGET = ResourceBudget(compute_units=10.0, memory_mb=1024.0)


def _registry_with(*kinds: str) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for kind in kinds:
        registry.register_local(
            ProviderRegistration(
                capability_kind=kind,
                provider_id=f"{kind}-provider",
                version="1",
                compatibility=CompatibilityProfile(cost=ResourceCost(compute_units=1.0)),
                requirement=CapabilityRequirement(),
            )
        )
    return registry


#: 어떤 정보 종류를 어떤 capability로 채울 수 있는지 -- 배포 설정(데이터)이며
#: 코드에 도메인 분기를 넣지 않는다.
SOURCES_BY_FIELD = {
    "distance": ("perception.depth",),
    "semantic_class": ("perception.classify", "perception.detect_ovd"),
    "surface_condition": ("perception.sar_detect",),  # 등록되지 않은 capability
}


def test_gap_becomes_a_request_when_a_capability_can_fill_it():
    purposes = PurposeRequirementRegistry()
    purposes.register(
        PurposeRequirement(
            purpose_id="approach_target",
            required_fields=("distance", "semantic_class"),
        )
    )
    # 지금 레코드에는 분류만 있고 거리가 없다.
    gap = purposes.evaluate("approach_target", available_fields={"semantic_class"})
    assert gap is not None and not gap.sufficient
    assert gap.missing_required == ("distance",)

    requester = DecisionSupportRequester(_registry_with("perception.depth"))
    plan = requester.plan_for_validation_gaps(
        gap.missing_required, SOURCES_BY_FIELD, node_tags=set(), budget=BUDGET
    )

    assert plan.fully_supported
    assert [r.capability_kind for r in plan.requests] == ["perception.depth"]


def test_gap_stays_unresolved_when_no_registered_capability_can_fill_it():
    """AI-S-05: 이용 가능한 후보가 없으면 부족한 근거를 남긴다 -- 없는 기능을
    있는 것처럼 요청하지 않는다."""
    purposes = PurposeRequirementRegistry()
    purposes.register(
        PurposeRequirement(purpose_id="riverbank_check", required_fields=("surface_condition",))
    )
    gap = purposes.evaluate("riverbank_check", available_fields=set())

    requester = DecisionSupportRequester(_registry_with("perception.depth"))
    plan = requester.plan_for_validation_gaps(
        gap.missing_required, SOURCES_BY_FIELD, node_tags=set(), budget=BUDGET
    )

    assert not plan.fully_supported
    assert plan.unresolved == ("surface_condition",)
    assert plan.requests == ()


def test_unresolved_gap_downgrades_the_action_to_human_approval():
    """고리의 마지막 마디: 근거를 못 채웠으면 그 조치는 자동 수행 대상이 아니다."""
    purposes = PurposeRequirementRegistry()
    purposes.register(
        PurposeRequirement(purpose_id="riverbank_check", required_fields=("surface_condition",))
    )
    gap = purposes.evaluate("riverbank_check", available_fields=set())

    requester = DecisionSupportRequester(_registry_with("perception.depth"))
    plan = requester.plan_for_validation_gaps(
        gap.missing_required, SOURCES_BY_FIELD, node_tags=set(), budget=BUDGET
    )

    graded = grade(
        "호안 이상 구간 근접 점검",
        ActionContext(evidence_sufficient=plan.fully_supported, reversible=True),
    )

    assert graded.autonomy_level is AutonomyLevel.SHARED
    assert "insufficient_evidence" in graded.basis


def test_satisfied_purpose_needs_no_request_at_all():
    purposes = PurposeRequirementRegistry()
    purposes.register(
        PurposeRequirement(purpose_id="approach_target", required_fields=("distance",))
    )
    gap = purposes.evaluate("approach_target", available_fields={"distance"})

    assert gap.sufficient
    assert gap.missing_required == ()

    requester = DecisionSupportRequester(_registry_with("perception.depth"))
    plan = requester.plan_for_validation_gaps(
        gap.missing_required, SOURCES_BY_FIELD, node_tags=set(), budget=BUDGET
    )

    # 부족분이 없으면 요청도 없다 -- 필요한 항목만 요청한다(AI-S-05).
    assert plan.requests == ()
    assert plan.fully_supported
