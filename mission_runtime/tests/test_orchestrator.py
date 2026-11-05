"""증거 주도 오케스트레이션 루프.

implements: AI-S-05, AI-S-07, AI-C-13, AI-C-05, AI-B-06
tests: stops with a reason (never silently), early stop on sufficiency, budget
       exhaustion, unobtainable degradation, no-progress guard, policy swap
       changes calls but not the contract, static policy ignores feedback

근거: internal/docs-dev/obsidian/ideas/evidence-driven-orchestration-plan.md §3 S3
"""

from __future__ import annotations

from dataclasses import replace

from mission_runtime.contracts.evidence_contract import (
    MissionContract,
    RequiredEvidence,
)
from mission_runtime.decision.orchestrator import (
    STOP_REASONS,
    Budget,
    ProviderChoice,
    orchestrate,
)
from mission_runtime.decision.selection_policies import (
    ExpectedGainPolicy,
    GreedyCostPolicy,
    StaticPlanPolicy,
)
from mission_runtime.perception.object_record import ObjectRecord

COSTS = {
    "detection": ("yoloe_pf", 15.0),
    "open_vocabulary_detection": ("yolo_world", 16.0),
    "semantic_verification": ("clip_torch", 169.0),
    "segmentation": ("gdino_tiny", 453.0),
}

#: 이 묶음이 쓰는 증거 종류 → capability kind 매핑. **배포 선언을 쓰지 않고 여기서
#: 준다**(2026-11-05 — `tests/test_sufficiency_fcr.py` 와 같은 이유).
#:
#: 이 시험들이 보는 것은 **조율 루프의 동작**(정책 교체·예산 소진·단계 기록)이고
#: 어느 capability 가 무엇을 만드는지는 그 축이 아니다. 전에는 매핑이 코드 상수여서
#: 여기서 주지 않아도 돌았는데, 그 상수의 이름이 배포 선언 어휘와 하나도 맞지
#: 않았다 — 즉 **아무 배치도 쓰지 않는 어휘**로 돌고 있었다. 매핑이 선언으로 나간 뒤
#: 그 사실이 드러났고, 단위 시험이 배포 선언의 변경에 흔들리지 않도록 자기 어휘를
#: 자기가 들고 있게 한다.
KIND_PROVIDERS = {
    "semantic_class": ("detection", "open_vocabulary_detection",
                       "semantic_verification"),
    "region_2d": ("detection", "open_vocabulary_detection"),
    "mask": ("segmentation",),
    "distance": ("depth", "range_sensing"),
}
AVAILABLE = frozenset(k for v in KIND_PROVIDERS.values() for k in v)


def _contract(**over) -> MissionContract:
    spec = dict(mission_id="nav", required=(
        RequiredEvidence("semantic_class", tolerance=2),
        RequiredEvidence("region_2d", tolerance=0.4),
    ))
    spec.update(over)
    return MissionContract(**spec)


def _executor(gain_per_call: int = 1):
    """호출마다 지지 소스가 늘고 박스가 생기는 가짜 provider."""
    def run(choice: ProviderChoice, rec: ObjectRecord) -> ObjectRecord:
        return replace(rec,
                       geometry=rec.geometry or (0.0, 0.0, 10.0, 10.0),
                       confidence=max(rec.confidence, 0.8),
                       semantic_class="chair",
                       supporting_groups=rec.supporting_groups + gain_per_call)
    return run


def _stuck(choice: ProviderChoice, rec: ObjectRecord) -> ObjectRecord:
    """아무것도 바꾸지 못하는 provider."""
    return rec


def test_every_stop_has_a_reason():
    """'그냥 끝났다'가 없어야 조기 정지의 대가를 사후에 셀 수 있다."""
    r = orchestrate(_contract(), ObjectRecord("o"),
                    GreedyCostPolicy(COSTS), _executor(), Budget(), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    assert r.stop_reason in STOP_REASONS


def test_stops_early_once_the_contract_is_met():
    """충족되면 남은 provider를 부르지 않는다 — 절감의 메커니즘이다."""
    r = orchestrate(_contract(), ObjectRecord("o"),
                    GreedyCostPolicy(COSTS), _executor(gain_per_call=2), Budget(), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    assert r.satisfied and r.calls == 1, (r.stop_reason, r.calls)

    slower = orchestrate(_contract(), ObjectRecord("o"),
                         GreedyCostPolicy(COSTS), _executor(gain_per_call=1), Budget(), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    assert slower.satisfied and slower.calls == 2      # 지지 2개를 채우는 데 두 번


def test_budget_exhaustion_stops_without_claiming_success():
    r = orchestrate(_contract(), ObjectRecord("o"),
                    GreedyCostPolicy(COSTS), _executor(), Budget(max_calls=1), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    assert r.stop_reason == "exhausted"
    assert not r.satisfied and not r.verdict.complete
    assert r.verdict.unmet_kinds, "부족한 근거를 남겨야 한다(AI-S-05)"


def test_cost_budget_is_respected():
    r = orchestrate(_contract(required=(RequiredEvidence("mask", tolerance=0.9),)),
                    ObjectRecord("o"), GreedyCostPolicy(COSTS), _executor(),
                    Budget(max_cost_ms=100.0), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    # segmentation(453ms)뿐인데 예산이 100ms — 부르지 못하고 멈춘다
    assert r.stop_reason == "exhausted" and r.calls == 0


def test_unobtainable_is_a_degradation_not_a_loop():
    """만들 수 없는 증거로 무한히 돌지 않는다(AI-C-05)."""
    r = orchestrate(_contract(required=(RequiredEvidence("distance", tolerance=0.5),)),
                    ObjectRecord("o"), GreedyCostPolicy(COSTS), _executor(),
                    # `distance` 를 낼 종류(depth·range_sensing)가 **가용 목록에
                    # 없다** — 표에는 있으므로 "모른다" 가 아니라 "만들 수 없다" 다.
                    Budget(), available_kinds=frozenset({"detection"}),
                    kind_providers=KIND_PROVIDERS)
    assert r.stop_reason == "unobtainable" and r.calls == 0
    assert not r.verdict.complete          # 숨기지 않는다


def test_no_progress_guard_stops_burning_budget():
    r = orchestrate(_contract(), ObjectRecord("o"),
                    GreedyCostPolicy(COSTS), _stuck, Budget(max_calls=8), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    assert r.stop_reason == "no_progress"
    assert r.calls == 1, "한 번 해보고 멈춘다"


def test_static_policy_ignores_feedback():
    """ablation 'No evidence feedback' — 격차를 보지 않고 계획대로만 부른다.

    제거하면 RoboKudo형 정적 파이프라인이 된다는 것이 논문의 핵심 ablation이다.
    """
    plan = StaticPlanPolicy(("detection", "semantic_verification", "segmentation"), COSTS)
    r = orchestrate(_contract(), ObjectRecord("o"), plan, _executor(gain_per_call=2),
                    Budget(), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    # 첫 호출로 이미 충족되므로 루프는 멈춘다 — 정책이 계획을 다 쓰지 못한다.
    assert r.satisfied and r.calls == 1
    assert plan._cursor == 1


def test_policy_swap_changes_calls_not_the_contract():
    """같은 계약·같은 provider pool에서 정책만 갈아 끼운다(AI-C-13 비교 조건)."""
    results = {}
    for policy in (GreedyCostPolicy(COSTS), ExpectedGainPolicy(COSTS)):
        r = orchestrate(_contract(), ObjectRecord("o"), policy,
                        _executor(gain_per_call=2), Budget(), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
        results[policy.name] = (r.satisfied, r.cost_ms)
    assert all(ok for ok, _ in results.values())
    # 두 정책 모두 가장 싼 detection을 먼저 고른다 — 같은 비용이어야 한다.
    assert len({c for _, c in results.values()}) == 1, results


def test_steps_record_what_changed():
    r = orchestrate(_contract(), ObjectRecord("o"),
                    GreedyCostPolicy(COSTS), _executor(), Budget(), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    assert r.steps, "회차 기록이 남아야 한다"
    first = r.steps[0]
    assert "semantic_class" in first.needs_before
    assert set(first.needs_after) < set(first.needs_before) or not first.needs_after


def test_policy_never_reselects_a_provider_it_already_called():
    """같은 provider를 두 번 고르면 지지 수가 거짓으로 늘고 루프가 헛돈다.

    2026-09-22 VisDrone 재생에서 실제로 이 일이 일어났다 — greedy가 가장 싼
    provider를 반복해 골랐고, 두 번째 호출이 아무것도 바꾸지 못해 충분도 규칙이
    한 건도 확정하지 못했다. 규칙이 아니라 정책의 결함이었다.
    """
    calls = []

    def recording(choice: ProviderChoice, rec: ObjectRecord) -> ObjectRecord:
        calls.append(choice.provider_id)
        return _executor(gain_per_call=1)(choice, rec)

    orchestrate(_contract(), ObjectRecord("o"), GreedyCostPolicy(COSTS),
                recording, Budget(max_calls=4), available_kinds=AVAILABLE,
                    kind_providers=KIND_PROVIDERS)
    assert len(calls) == len(set(calls)), calls
