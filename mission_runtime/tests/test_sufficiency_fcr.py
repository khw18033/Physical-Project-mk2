"""정지 규칙과 틀린 확정의 회계(FCR).

implements: AI-S-03, AI-S-04, AI-O-02, AI-C-13
tests: confidence stops earlier but confirms on a single source, sufficiency
       requires independent corroboration, raising the threshold cannot fix
       high-confidence errors, FCR is reported with coverage, unscored
       confirmations are not counted as wrong

근거: internal/docs-dev/obsidian/ideas/evidence-driven-orchestration-plan.md §3 S4, §7-2
"""

from __future__ import annotations

from dataclasses import replace

from mission_runtime.contracts.evidence_contract import (
    MissionContract,
    RequiredEvidence,
)
from mission_runtime.decision.orchestrator import Budget, orchestrate
from mission_runtime.decision.selection_policies import GreedyCostPolicy
from mission_runtime.decision.sufficiency import (
    ConfidenceRule,
    FCRLedger,
    NeverStopRule,
    StopDecision,
    SufficiencyRule,
)
from mission_runtime.perception.object_record import ObjectRecord

COSTS = {
    "detection": ("yoloe_pf", 15.0),
    "open_vocabulary_detection": ("yolo_world", 16.0),
    "semantic_verification": ("clip_torch", 169.0),
}

#: 이 묶음이 쓰는 증거 종류 → capability kind 매핑. **배포 선언을 쓰지 않고 여기서
#: 준다**(2026-11-05).
#:
#: 이유: 이 시험들이 보는 것은 **정지 규칙의 동작**(confidence vs sufficiency)이고
#: 어느 capability 가 무엇을 만드는지는 그 축이 아니다. 전에는 매핑이 코드 상수여서
#: 여기서 주지 않아도 돌았는데, 그 상수의 이름이 배포 선언 어휘와 하나도 맞지
#: 않았다(`detection` vs `perception.detect`) — 즉 이 시험들은 **아무 배치도 쓰지 않는
#: 어휘**로 돌고 있었다. 매핑이 선언으로 나간 뒤 그 사실이 드러났다.
#:
#: 고치는 방향은 이름을 배포 어휘로 바꾸는 것이 **아니다**: 그러면 이 단위 시험이
#: 배포 선언의 변경에 흔들린다. 기능 비교 시험은 자기 어휘를 자기가 들고 있어야
#: 한다(AI-B-01 의 "같은 조건에서 비교" 가 성립하려면 그 조건이 고정되어야 한다).
KIND_PROVIDERS = {
    "semantic_class": ("detection", "open_vocabulary_detection",
                       "semantic_verification"),
    "region_2d": ("detection", "open_vocabulary_detection"),
}
AVAILABLE = frozenset(k for v in KIND_PROVIDERS.values() for k in v)


def _contract() -> MissionContract:
    return MissionContract("m", (
        RequiredEvidence("semantic_class", tolerance=2),
        RequiredEvidence("region_2d", tolerance=0.4),
    ))


def _executor(label: str, conf: float):
    def run(choice, rec: ObjectRecord) -> ObjectRecord:
        return replace(rec, geometry=(0.0, 0.0, 10.0, 10.0), confidence=conf,
                       semantic_class=label,
                       supporting_groups=rec.supporting_groups + 1)
    return run


def test_confidence_stops_on_one_source_sufficiency_does_not():
    """같은 입력에서 두 규칙이 다르게 멈춘다 — 이것이 비교의 축이다."""
    args = (_contract(), ObjectRecord("o"), GreedyCostPolicy(COSTS),
            _executor("flipchart", 0.94), )
    fast = orchestrate(*args, Budget(), available_kinds=AVAILABLE, kind_providers=KIND_PROVIDERS,
                     stop_rule=ConfidenceRule(0.5))
    slow = orchestrate(_contract(), ObjectRecord("o"), GreedyCostPolicy(COSTS),
                       _executor("flipchart", 0.94), Budget(),
                       available_kinds=AVAILABLE, kind_providers=KIND_PROVIDERS,
                       stop_rule=SufficiencyRule())

    assert fast.calls == 1 and fast.decision.confirmed
    assert fast.decision.supporting_groups == 1, "한 소스로 확정했다"
    assert slow.calls == 2 and slow.decision.supporting_groups == 2
    assert slow.cost_ms > fast.cost_ms, "충분도가 더 비싸다 — 그 대가가 FCR로 회수돼야 한다"


def test_raising_the_threshold_cannot_fix_high_confidence_errors():
    """임계를 올려도 0.94짜리 오답은 못 거른다.

    2026-09-21 실측: YOLOE가 백팩을 `computer chair 0.83`, 캐비닛을
    `flipchart 0.94`로 불렀다. 0.94 위에 임계를 두면 맞는 것까지 전부 버린다.
    이것이 신뢰도 기반 정지의 **구조적** 결함이고 논문 주장의 근거다.
    """
    wrong_but_confident = _executor("flipchart", 0.94)
    for threshold in (0.5, 0.8, 0.9):
        r = orchestrate(_contract(), ObjectRecord("o"), GreedyCostPolicy(COSTS),
                        wrong_but_confident, Budget(), available_kinds=AVAILABLE,
                        kind_providers=KIND_PROVIDERS, stop_rule=ConfidenceRule(threshold))
        assert r.decision.confirmed, f"임계 {threshold}에서도 확정한다"
        assert r.decision.supporting_groups == 1

    # 임계를 0.94 위로 올리면 확정 자체가 사라진다 — 맞는 것도 함께.
    r = orchestrate(_contract(), ObjectRecord("o"), GreedyCostPolicy(COSTS),
                    _executor("chair", 0.93), Budget(), available_kinds=AVAILABLE,
                        kind_providers=KIND_PROVIDERS, stop_rule=ConfidenceRule(0.95))
    assert r.decision is None or not r.decision.confirmed


def test_confidence_stop_records_what_it_skipped():
    """무엇을 못 채우고 멈췄는지 남는다 — 사후 추적의 근거(AI-O-02)."""
    r = orchestrate(_contract(), ObjectRecord("o"), GreedyCostPolicy(COSTS),
                    _executor("flipchart", 0.94), Budget(),
                    available_kinds=AVAILABLE, kind_providers=KIND_PROVIDERS,
                     stop_rule=ConfidenceRule(0.5))
    assert "semantic_class" in r.decision.unmet


def test_never_stop_runs_until_budget_and_confirms_nothing_early():
    r = orchestrate(_contract(), ObjectRecord("o"), GreedyCostPolicy(COSTS),
                    _executor("chair", 0.9), Budget(max_calls=3),
                    available_kinds=AVAILABLE, kind_providers=KIND_PROVIDERS,
                    stop_rule=NeverStopRule())
    # 계약은 충족됐지만 규칙이 확정하지 않았다 — "못 얻었다"와 다른 결말이다.
    assert r.stop_reason in ("exhausted", "no_progress", "no_more_evidence")
    assert r.stop_reason != "unobtainable", "다 얻고도 못 얻었다고 기록하면 안 된다"
    assert r.decision is None


def test_fcr_is_reported_with_coverage_and_cost():
    """FCR만 보면 안 된다 — 적게 확정하면 저절로 낮아진다."""
    led = FCRLedger("confidence")
    led.add("o1", StopDecision("confidence", True, "", "computer chair", 1, 0.83, 15.0), "backpack")
    led.add("o2", StopDecision("confidence", True, "", "flipchart", 1, 0.94, 15.0), "cabinet")
    led.add("o3", StopDecision("confidence", True, "", "chair", 1, 0.88, 15.0), "chair")
    rep = led.report(total_objects=10)
    assert rep["fcr"] == round(2 / 3, 4)
    assert rep["coverage"] == 0.3
    assert rep["cost_ms_per_confirmation"] == 15.0

    shy = FCRLedger("shy")
    shy.add("o3", StopDecision("shy", True, "", "chair", 2, 0.5, 200.0), "chair")
    assert shy.report(total_objects=10)["fcr"] == 0.0
    assert shy.report(total_objects=10)["coverage"] == 0.1, "FCR 0은 coverage와 함께 읽어야 한다"


def test_unscored_confirmations_are_not_counted_as_wrong():
    """정답을 모르면 틀렸다고 세지 않는다 — 없는 근거를 만들지 않는다(AI-S-03)."""
    led = FCRLedger("r")
    led.add("o1", StopDecision("r", True, "", "chair", 2, 0.7, 30.0))       # 정답 없음
    led.add("o2", StopDecision("r", True, "", "chair", 2, 0.7, 30.0), "desk")
    rep = led.report()
    assert rep["confirmed"] == 2 and rep["scored"] == 1
    assert rep["fcr"] == 1.0, "채점된 1건 중 1건이 틀렸다"

    led.settle({"o1": "chair"})
    assert led.report()["scored"] == 2 and led.report()["fcr"] == 0.5


def test_non_confirming_decisions_never_enter_the_ledger():
    led = FCRLedger("r")
    led.add("o1", StopDecision("r", False, "아직 부족"), "chair")
    assert led.confirmed == 0 and led.fcr is None
