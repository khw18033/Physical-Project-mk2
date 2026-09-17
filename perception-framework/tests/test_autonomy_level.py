"""implements: AI-C-19, AI-S-05, AI-R-02

2026-09-17 LOTUSim-Energy 반영분. 판단 규칙 자체가 실측으로 정당화된 것이
아니므로(모듈 docstring 참고) 여기서 고정하는 것은 "어떤 조건이 더 보수적인
등급으로 가야 하는가"라는 방향성이지 특정 점수가 아니다.
"""
import pytest

from perception_framework.contracts import data_dictionary as dd
from perception_framework.decision.autonomy_level import (
    ActionContext,
    AutonomyLevel,
    DefaultAutonomyPolicy,
    GradedRecommendation,
    grade,
    more_conservative,
)


def test_level_values_match_the_registered_vocabulary():
    spec = dd.spec_for(dd.AUTONOMY_LEVEL)

    for level in AutonomyLevel:
        assert level.value in spec.value_kind


def test_safety_critical_action_is_teleoperated_even_with_sufficient_evidence():
    level = DefaultAutonomyPolicy().level_for(
        ActionContext(evidence_sufficient=True, reversible=True, safety_critical=True)
    )

    assert level is AutonomyLevel.TELEOPERATED


def test_irreversible_action_requires_human_approval():
    level = DefaultAutonomyPolicy().level_for(
        ActionContext(evidence_sufficient=True, reversible=False)
    )

    assert level is AutonomyLevel.SHARED


def test_insufficient_evidence_requires_human_approval():
    """AI-S-03: 근거 충분도가 확보되지 않은 결과를 확정 상태로 승격하지 않는다."""
    level = DefaultAutonomyPolicy().level_for(
        ActionContext(evidence_sufficient=False, reversible=True)
    )

    assert level is AutonomyLevel.SHARED


def test_reversible_well_supported_action_may_run_autonomously():
    level = DefaultAutonomyPolicy().level_for(
        ActionContext(evidence_sufficient=True, reversible=True)
    )

    assert level is AutonomyLevel.AUTONOMOUS


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (AutonomyLevel.AUTONOMOUS, AutonomyLevel.SHARED, AutonomyLevel.SHARED),
        (AutonomyLevel.SHARED, AutonomyLevel.TELEOPERATED, AutonomyLevel.TELEOPERATED),
        (AutonomyLevel.AUTONOMOUS, AutonomyLevel.AUTONOMOUS, AutonomyLevel.AUTONOMOUS),
    ],
)
def test_conflicting_judgements_resolve_to_the_more_conservative_one(a, b, expected):
    assert more_conservative(a, b) is expected
    assert more_conservative(b, a) is expected


def test_graded_recommendation_records_why_the_level_was_chosen():
    graded = grade(
        "단상 재관측 후 위치 재추정",
        ActionContext(evidence_sufficient=False, reversible=True, safety_critical=False),
    )

    assert isinstance(graded, GradedRecommendation)
    assert graded.autonomy_level is AutonomyLevel.SHARED
    assert "insufficient_evidence" in graded.basis
    assert graded.recommendation == "단상 재관측 후 위치 재추정"


def test_autonomous_grade_carries_an_empty_basis_not_a_fabricated_reason():
    graded = grade("경로 갱신", ActionContext(evidence_sufficient=True, reversible=True))

    assert graded.autonomy_level is AutonomyLevel.AUTONOMOUS
    assert graded.basis == ()


def test_policy_is_replaceable_without_touching_the_caller():
    """AI-C-13: 특정 판단 규칙을 프레임워크 필수 방식으로 고정하지 않는다."""

    class AlwaysTeleop:
        def level_for(self, context):
            return AutonomyLevel.TELEOPERATED

    graded = grade("무엇이든", ActionContext(evidence_sufficient=True), policy=AlwaysTeleop())

    assert graded.autonomy_level is AutonomyLevel.TELEOPERATED
