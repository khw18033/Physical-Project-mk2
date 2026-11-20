"""배정 정책 비교군의 계약 — `runtime/assignment_policies.py`.

implements: AI-C-13, AI-L-10, AI-B-06, AI-B-01
tests: 같은 추적을 넷이 그대로 먹는다 · 동점이면 고르지 않는다 · 미측정은 0 이 아니다 ·
       static 은 바꿔치지 않는다 · 열화는 즉시 내려가고 복구는 연속으로만 · 기억이 새지 않는다
"""
from __future__ import annotations

import pytest

from mission_runtime.runtime.assignment_policies import (
    REASON_ALL_DEGRADED,
    REASON_NO_ELIGIBLE,
    REASON_PINNED_ABSENT,
    REASON_TIE,
    AdaptivePolicy,
    FirstFeasible,
    ResourceAware,
    StaticAssignment,
    compare_policies,
)
from mission_runtime.runtime.model_assignment import MissionRequirement, ModelVersion

KIND = "perception.detect"


def version(ref: str, quality=0.8, latency=100.0, memory=512.0) -> ModelVersion:
    model_id, _, ver = ref.partition("@")
    return ModelVersion(model_id=model_id, version=ver or "v1", capability_kind=KIND,
                        quality=quality, latency_ms=latency, memory_mb=memory)


@pytest.fixture
def requirement() -> MissionRequirement:
    return MissionRequirement(mission_id="M-1", capability_kind=KIND)


# --------------------------------------------------------------- 공통

def test_every_policy_answers_the_same_shape(requirement):
    """비교가 성립하려면 **답의 모양이 같아야** 한다."""
    pool = [version("a@v1"), version("b@v1", quality=0.9)]
    for policy in (StaticAssignment({KIND: "a@v1"}), FirstFeasible(),
                   ResourceAware(), AdaptivePolicy()):
        decision = policy.decide(pool, requirement)
        assert decision.reason, f"{policy} 가 사유를 안 냈다"
        assert isinstance(decision.considered, int)


def test_an_empty_pool_is_refused_with_a_reason_not_an_exception(requirement):
    for policy in (FirstFeasible(), ResourceAware(), AdaptivePolicy()):
        decision = policy.decide([], requirement)
        assert decision.chose is False
        assert decision.reason in (REASON_NO_ELIGIBLE, REASON_TIE)


# --------------------------------------------------------------- static

def test_static_does_not_substitute_when_its_version_is_gone(requirement):
    """**그게 static 의 뜻이다.** 바꿔치면 비교군으로서 쓸모가 없다."""
    policy = StaticAssignment({KIND: "pinned@v9"})
    decision = policy.decide([version("other@v1")], requirement)
    assert decision.chose is False
    assert decision.reason == REASON_PINNED_ABSENT


def test_static_picks_its_version_even_if_a_better_one_exists(requirement):
    policy = StaticAssignment({KIND: "slow@v1"})
    pool = [version("fast@v1", quality=0.99, latency=10.0), version("slow@v1")]
    assert policy.decide(pool, requirement).version.reference == "slow@v1"


# --------------------------------------------------------------- first feasible

def test_first_feasible_follows_the_input_order(requirement):
    """순서에 기대는 성질 **자체가 비교 대상**이다."""
    policy = FirstFeasible()
    pool = [version("a@v1", quality=0.1), version("b@v1", quality=0.99)]
    assert policy.decide(pool, requirement).version.reference == "a@v1"
    assert policy.decide(list(reversed(pool)), requirement).version.reference == "b@v1"


# --------------------------------------------------------------- resource aware

def test_resource_aware_prefers_quality_but_pays_for_latency(requirement):
    policy = ResourceAware(quality_weight=1.0, latency_weight=0.5, memory_weight=0.0)
    pool = [version("slow@v1", quality=0.90, latency=1000.0),
            version("quick@v1", quality=0.85, latency=10.0)]
    assert policy.decide(pool, requirement).version.reference == "quick@v1"


def test_an_unmeasured_candidate_does_not_win_by_being_unmeasured(requirement):
    """0 으로 채우면 **재지 않은 것이 가장 빠른 후보**가 되어 이긴다(AI-B-01)."""
    policy = ResourceAware()
    unmeasured = ModelVersion(model_id="ghost", version="v1", capability_kind=KIND,
                              quality=0.99, latency_ms=None, memory_mb=None)
    decision = policy.decide([unmeasured, version("real@v1")], requirement)
    assert decision.version.reference == "real@v1"


def test_only_unmeasured_candidates_means_no_choice(requirement):
    policy = ResourceAware()
    unmeasured = ModelVersion(model_id="ghost", version="v1", capability_kind=KIND)
    assert policy.decide([unmeasured], requirement).reason == REASON_NO_ELIGIBLE


def test_a_tie_is_not_broken_arbitrarily(requirement):
    """**갈리지 않으면 고르지 않는다.** 임의로 깨면 왜 골랐는지 답할 수 없다."""
    policy = ResourceAware()
    pool = [version("a@v1"), version("b@v1")]            # 모든 수가 같다
    decision = policy.decide(pool, requirement)
    assert decision.chose is False
    assert decision.reason == REASON_TIE
    assert len(decision.scores) == 2, "점수표는 남겨 운영자가 확인할 수 있어야 한다"


def test_the_same_input_gives_the_same_answer(requirement):
    policy = ResourceAware()
    pool = [version("a@v1", quality=0.9), version("b@v1", quality=0.8)]
    first = policy.decide(pool, requirement)
    second = policy.decide(pool, requirement)
    assert first.version.reference == second.version.reference


# --------------------------------------------------------------- adaptive

def test_degradation_is_immediate_because_availability_comes_first(requirement):
    policy = AdaptivePolicy()
    # 평시에 heavy 가 이기도록 품질 차를 지연 벌점보다 크게 둔다 — 그래야 열화 뒤의
    # 전환이 **정책 때문**이지 후보군 때문이 아니다.
    pool = [version("heavy@v1", quality=0.99, latency=120.0),
            version("light@v1", quality=0.40, latency=100.0)]
    assert policy.decide(pool, requirement).version.reference == "heavy@v1"

    policy.observe(KIND, ok=False)
    assert policy.is_degraded(KIND) is True
    assert policy.decide(pool, requirement).version.reference == "light@v1"


def test_recovery_needs_a_streak_so_the_assignment_does_not_flap(requirement):
    """경계에서 진동하는 배정은 **그 자체가 장애**다(AI-B-06)."""
    policy = AdaptivePolicy(recover_after=3)
    policy.observe(KIND, ok=False)

    policy.observe(KIND, ok=True)
    assert policy.is_degraded(KIND) is True, "한 번 좋아졌다고 올라가지 않는다"
    policy.observe(KIND, ok=True)
    assert policy.is_degraded(KIND) is True
    policy.observe(KIND, ok=True)
    assert policy.is_degraded(KIND) is False


def test_one_failure_resets_the_streak(requirement):
    policy = AdaptivePolicy(recover_after=3)
    policy.observe(KIND, ok=False)
    policy.observe(KIND, ok=True)
    policy.observe(KIND, ok=True)
    policy.observe(KIND, ok=False)                        # 다시 떨어뜨린다
    policy.observe(KIND, ok=True)
    assert policy.is_degraded(KIND) is True


def test_a_degraded_policy_with_nothing_measurable_refuses(requirement):
    policy = AdaptivePolicy()
    policy.observe(KIND, ok=False)
    ghost = ModelVersion(model_id="ghost", version="v1", capability_kind=KIND)
    assert policy.decide([ghost], requirement).reason == REASON_ALL_DEGRADED


# --------------------------------------------------------------- 비교

def test_the_four_policies_run_the_same_trace(requirement):
    """AI-C-13 의 "동일 조건" — 입력을 정책이 바꾸지 못한다."""
    trace = [
        ([version("a@v1", quality=0.9, latency=50.0),
          version("b@v1", quality=0.7, latency=20.0)], requirement),
        ([version("a@v1"), version("b@v1")], requirement),          # 동점
        ([], requirement),                                           # 빈 후보
    ]
    runs = {run.policy: run for run in compare_policies(
        [StaticAssignment({KIND: "a@v1"}), FirstFeasible(),
         ResourceAware(), AdaptivePolicy()], trace)}

    assert set(runs) == {"static", "first_feasible", "resource_aware", "adaptive"}
    for run in runs.values():
        assert run.decided == 3
        assert run.chose + run.refused == 3

    # 동점과 빈 후보에서 갈린다 — 그게 비교의 내용이다
    assert runs["first_feasible"].chose == 2                 # 동점도 첫 번째를 집는다
    assert runs["resource_aware"].chose == 1                 # 동점은 거절한다
    assert REASON_TIE in runs["resource_aware"].refusal_reasons


def test_comparison_does_not_rank_the_policies(requirement):
    """어느 축이 중요한지는 **배치가 정한다** — 여기서 순위를 매기면 그 선택이 숨는다."""
    runs = compare_policies([FirstFeasible(), ResourceAware()],
                            [([version("a@v1")], requirement)])
    assert not hasattr(runs[0], "rank")
    assert not hasattr(runs[0], "winner")


def test_a_comparison_run_does_not_carry_memory_into_the_next(requirement):
    """적응 정책은 상태를 든다 — 실험마다 새로 만들지 않으면 **앞 실행이 샌다**."""
    pool = [version("heavy@v1", quality=0.99, latency=120.0),
            version("light@v1", quality=0.40, latency=100.0)]
    first = AdaptivePolicy()
    first.observe(KIND, ok=False)
    assert first.is_degraded(KIND) is True

    fresh = AdaptivePolicy()
    assert fresh.is_degraded(KIND) is False
    assert fresh.decide(pool, requirement).version.reference == "heavy@v1"


def test_decisiveness_is_reported_but_not_called_good(requirement):
    """고른 비율이 높다고 좋은 게 아니다 — 아무거나 고르면 1.0 이다."""
    runs = compare_policies([FirstFeasible()], [([version("a@v1")], requirement)])
    assert runs[0].decisiveness == 1.0
