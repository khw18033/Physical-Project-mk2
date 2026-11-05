"""승격 사슬이 **판정을 새로 만들지 않고** 순서만 잡는지 고정한다.

implements: AI-S-03, AI-S-05, AI-E-04, AI-C-05, AI-C-19
tests: full chain ACTIVE, each optional stage absent degrades **with a reason** and
       never raises, insufficient evidence is not promoted, the information request
       carries its four fields and no command, frame refs survive every stage,
       two results on one `(source_group, frame_ref)` are one observation,
       the loop runs only when the refresh ledger asks

왜 이 파일이 "사유" 를 그렇게 자주 보는가: 축소가 사유 없이 일어나면 운영자는 무엇을
들여야 ACTIVE 가 되는지 알 수 없고, 그 상태는 "선언된 비활성" 과 "세우는 코드 없음" 을
구분하지 못한다(`tests/test_module_wiring.py` 가 생긴 이유와 같은 뿌리).
"""

from __future__ import annotations

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.contracts.evidence_contract import MissionContract, RequiredEvidence
from mission_runtime.contracts.profile import CompatibilityProfile, ResourceBudget
from mission_runtime.decision.info_request import DecisionSupportRequester
from mission_runtime.perception.auxiliary import AuxiliaryExecutionOrchestrator
from mission_runtime.perception.info_selection import AdditionalInfoSelector
from mission_runtime.perception.object_record import (
    CONFIRMING_GROUPS,
    Lifecycle,
    ObjectRecord,
)
from mission_runtime.perception.uncertainty import UncertaintyEvaluator
from mission_runtime.providers.fakes import StubAIRuntimeProvider
from mission_runtime.registry.capability_registry import (
    CapabilityRegistry,
    ProviderRegistration,
)
from mission_runtime.risk.adjustment import ObservationLevelAdjuster
from mission_runtime.runtime import perception_loop as pl

BUDGET = ResourceBudget(compute_units=10, memory_mb=10)

#: 운영 목적이 요구하는 근거. `semantic_class` 의 경계만 "독립 소스 수" 이고 나머지는
#: 존재 여부다 — 신뢰도 하나로 확정하지 않는다는 AI-S-03 의 축이 거기 있다.
CONTRACT = MissionContract(
    mission_id="test_purpose",
    required=(
        RequiredEvidence(kind="existence", necessity="required"),
        RequiredEvidence(kind="semantic_class", tolerance=float(CONFIRMING_GROUPS),
                         necessity="required"),
        RequiredEvidence(kind="distance", necessity="required"),
        RequiredEvidence(kind="cause_hypothesis", necessity="required"),
    ),
)


def registry(*kinds: str) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for kind in kinds:
        reg.register_local(ProviderRegistration(
            capability_kind=kind, provider_id=f"{kind}-p", version="1",
            compatibility=CompatibilityProfile()))
    return reg


def runtimes(*kinds: str) -> dict[str, StubAIRuntimeProvider]:
    return {f"{kind}-p": StubAIRuntimeProvider((kind,), lambda k, x: {"ran": k})
            for kind in kinds}


def record(*, groups: int, semantic: str = "chair",
           lifecycle: Lifecycle = Lifecycle.PROVISIONAL) -> ObjectRecord:
    return ObjectRecord(
        object_id="zoneA-track-1", revision=1, geometry=(0.0, 0.0, 1.0, 1.0),
        geometry_kind="region", frame_id="zone", semantic_class=semantic,
        lifecycle=lifecycle, observed_at=100.0, confidence=0.91,
        supporting_groups=groups, available_groups=groups)


def item(*, groups: int = 2, origins=None, track=7,
         semantic: str = "chair",
         lifecycle: Lifecycle = Lifecycle.PROVISIONAL) -> pl.RecordInput:
    """레코드 하나와 그 근거의 출처. `origins` 를 비우면 **지지 소스 수와 같은 수**의
    서로 다른 관측을 만든다 — 둘이 어긋난 픽스처는 현실에 없는 상태를 시험한다."""
    units = origins if origins is not None else tuple(
        (f"cam-{index}", "f1") for index in range(max(groups, 1)))
    return pl.RecordInput(
        record=record(groups=groups, semantic=semantic, lifecycle=lifecycle),
        origins=units, frame_ref="f1", coordinate_frame="ZONE", track_identity=track)


#: 이 묶음이 쓰는 증거 종류 → capability kind 매핑. **배포 선언을 쓰지 않고 여기서
#: 준다**(2026-11-05 추가).
#:
#: 이 시험들이 보는 것은 **루프의 단계 구성과 축소 사유**이고 어느 capability 가
#: 무엇을 만드는지는 그 축이 아니다. 전에는 매핑이 코드 상수여서 주지 않아도 돌았는데
#: 그 상수의 이름이 배포 선언 어휘와 하나도 맞지 않았다(`detection` vs
#: `perception.detect`) — 매핑이 선언으로 나간 뒤 그 사실이 드러났다. 단위 시험이
#: 배포 선언의 변경에 흔들리지 않도록 자기 어휘를 자기가 들고 있게 한다.
KIND_PROVIDERS = {
    "existence": ("detection",),
    "semantic_class": ("detection", "open_vocabulary_detection"),
    "region_2d": ("detection", "open_vocabulary_detection"),
    "distance": ("range_sensing",),
    # **매핑은 있고 그것을 내는 provider 가 이 배치에 없다** — 이것이
    # `unobtainable` 이고, 아래 "nobody can produce" 시험이 보는 상태다. 매핑을
    # 아예 두지 않으면 `provider_mapping_undeclared` 가 되어 **다른 사실**이 된다
    # (고칠 곳이 현장이 아니라 선언이다). 두 상태를 섞지 않으려고 여기 적어 둔다.
    "cause_hypothesis": ("case_retrieval", "vision_language"),
}


def full_loop(**overrides) -> pl.PerceptionLoop:
    """모든 단계가 있는 조립. ACTIVE 의 기준선이다."""
    reg = registry("detection", "open_vocabulary_detection", "range_sensing")
    kwargs = dict(
        kind_providers=dict(KIND_PROVIDERS),
        evaluator=UncertaintyEvaluator(min_evidence_count=CONFIRMING_GROUPS),
        contract=CONTRACT,
        info_selector=AdditionalInfoSelector(reg),
        request_planner=DecisionSupportRequester(reg),
        auxiliary=AuxiliaryExecutionOrchestrator(
            reg, runtimes("detection", "open_vocabulary_detection", "range_sensing")),
        level_adjuster=ObservationLevelAdjuster(
            reg, ["detection", "open_vocabulary_detection"]),
        budget=BUDGET,
        physical_action_kinds=frozenset({"range_sensing"}),
    )
    kwargs.update(overrides)
    return pl.PerceptionLoop(**kwargs)


# ---------------------------------------------------------------------------
# 사슬 전체
# ---------------------------------------------------------------------------


def test_the_full_chain_is_active_and_runs_every_stage():
    loop = full_loop()

    result = loop.run([item(groups=1)])

    assert result.capability_state is CapabilityState.ACTIVE
    assert result.degraded_stage_reasons == {}
    outcome = result.object_records[0]
    # 계약이 요구한 셋 중 둘이 비어 있으므로 승격하지 않는다.
    assert outcome.promotion_state == pl.PROMOTION_UNCONFIRMED
    # 세는 쪽(uncertainty)과 승격을 정하는 쪽(StopRule)이 **따로** 답을 남긴다.
    assert outcome.evidence_assessment is not None
    assert outcome.stop_decision is None
    # 돌릴 수 있는 보조는 돌았고, 물리 행동이 필요한 것은 돌지 않았다.
    assert "range_sensing" not in outcome.auxiliary_kinds_run
    assert outcome.auxiliary_kinds_run
    assert outcome.requested_observation_level in {
        "detection", "open_vocabulary_detection"}


def test_evidence_that_meets_the_contract_is_promoted_and_stops_asking():
    loop = full_loop(contract=MissionContract(
        mission_id="minimal",
        required=(
            RequiredEvidence(kind="existence", necessity="required"),
            RequiredEvidence(kind="semantic_class",
                             tolerance=float(CONFIRMING_GROUPS),
                             necessity="required"),
        )))

    outcome = loop.run([item(groups=CONFIRMING_GROUPS)]).object_records[0]

    assert outcome.promotion_state == pl.PROMOTION_CONFIRMED
    assert outcome.promoted
    assert outcome.stop_decision is not None and outcome.stop_decision.confirmed
    # 근거가 모였으면 더 요청하지 않는다(AI-E-04, AI-S-05).
    assert outcome.information_requests == ()
    assert outcome.auxiliary_kinds_run == ()


def test_insufficient_evidence_is_never_promoted_however_confident_the_model_is():
    """한 모델이 0.91 로 확신해도 독립 소스가 하나면 확정이 아니다(AI-S-03)."""
    loop = full_loop()

    outcome = loop.run([item(groups=1, origins=(("cam-a", "f1"),))]).object_records[0]

    assert outcome.confidence == pytest.approx(0.91)
    assert outcome.promotion_state == pl.PROMOTION_UNCONFIRMED
    assert "semantic_class" in outcome.unmet_evidence_kinds


# ---------------------------------------------------------------------------
# 선택 단계 부재는 **사유 있는 축소**이고 예외가 아니다 (AI-C-05)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("absent,reason", [
    ("evaluator", pl.DEGRADE_NO_EVALUATOR),
    ("contract", pl.DEGRADE_NO_CONTRACT),
    ("info_selector", pl.DEGRADE_NO_SELECTOR),
    ("request_planner", pl.DEGRADE_NO_PLANNER),
    ("auxiliary", pl.DEGRADE_NO_AUXILIARY),
    ("level_adjuster", pl.DEGRADE_NO_LEVELS),
])
def test_each_absent_optional_stage_degrades_with_a_reason(absent, reason):
    loop = full_loop(**{absent: None})

    result = loop.run([item(groups=1)])

    assert result.capability_state is CapabilityState.DEGRADED
    assert reason in result.degraded_stage_reasons.values()
    # 축소는 결과이지 실패가 아니다 — 레코드는 그대로 나온다.
    assert len(result.object_records) == 1


def test_an_absent_tracker_leaves_only_per_frame_results_with_a_reason():
    """AI-S-01 의 축소 경로. 추적 id 가 없는 것은 오류가 아니다."""
    loop = full_loop()

    result = loop.run([item(track=None)])

    assert result.capability_state is CapabilityState.DEGRADED
    assert pl.DEGRADE_NO_TRACKER in result.degraded_stage_reasons.values()
    assert result.object_records[0].track_identity is None


def test_the_tracked_identity_is_carried_onto_the_record_when_a_tracker_exists():
    outcome = full_loop().run([item(track=42)]).object_records[0]

    assert outcome.track_identity == 42
    # 구역 레코드 식별자와 **다른 축**이다. 같은 칸에 담지 않는다.
    assert outcome.zone_local_track_id == "zoneA-track-1"


def test_without_an_evaluator_the_records_own_lifecycle_is_the_only_answer():
    loop = full_loop(evaluator=None, contract=None)

    confirmed = loop.run([item(lifecycle=Lifecycle.CONFIRMED)]).object_records[0]
    provisional = loop.run([item(lifecycle=Lifecycle.PROVISIONAL)]).object_records[0]

    assert confirmed.promotion_state == pl.PROMOTION_CONFIRMED
    assert provisional.promotion_state == pl.PROMOTION_UNCONFIRMED
    assert confirmed.evidence_assessment is None


def test_a_loop_with_nothing_optional_still_runs_and_says_what_is_missing():
    """모든 선택 단계가 없는 배치도 정상이다 — DISABLED 가 되지 않는다."""
    loop = pl.PerceptionLoop()

    result = loop.run([item(track=None)])

    assert result.capability_state is CapabilityState.DEGRADED
    assert len(result.degraded_stage_reasons) == len(pl.REQUIREMENT.optional)
    assert set(result.degraded_stage_reasons.values()) <= set(
        dd.PERCEPTION_LOOP_DEGRADATIONS)


def test_degradation_can_be_asked_without_any_record():
    """축소는 조립의 성질이다 — 볼 것이 없었던 회차를 ACTIVE 로 적지 않는다."""
    state, reasons = pl.PerceptionLoop().degradation()

    assert state is CapabilityState.DEGRADED
    assert reasons


# ---------------------------------------------------------------------------
# 요청은 명령이 아니다 (AI-C-19)
# ---------------------------------------------------------------------------


def test_the_information_request_carries_its_four_fields_and_no_command():
    loop = full_loop()

    outcome = loop.run([item(groups=1)]).object_records[0]
    requests = outcome.information_requests

    assert requests, "물리 행동이 필요한 결손과 답할 수 없는 결손이 있어야 한다"
    for request in requests:
        body = request.as_dict()
        # 넷: 대상 객체 · 필요한 정보 · 관측 조건 · 사유.
        assert body[dd.OBJECT_ID] == "zoneA-track-1"
        assert body[dd.NEEDED_INFORMATION]
        assert body[dd.OBSERVATION_CONDITIONS]
        assert body[dd.INFORMATION_REQUEST_REASON] in dd.INFORMATION_REQUEST_REASONS
        # 그리고 명령이 아니다 — 발급은 백엔드다(AI-C-20).
        assert dd.COMMAND_ID not in body
        assert not [key for key in body if "command" in key]


def test_a_physical_action_is_requested_rather_than_run():
    loop = full_loop()

    outcome = loop.run([item(groups=1)]).object_records[0]
    physical = [r for r in outcome.information_requests
                if r.information_request_reason == pl.REQUEST_PHYSICAL_ACTION]

    assert physical and "range_sensing" in physical[0].needed_information
    assert "range_sensing" not in outcome.auxiliary_kinds_run


def test_evidence_nobody_can_produce_is_left_as_a_stated_gap():
    """이용 가능한 후보가 없으면 확인 가능한 범위까지만 판단하고 부족분을 남긴다."""
    loop = full_loop()

    outcome = loop.run([item(groups=1)]).object_records[0]
    unresolved = [r for r in outcome.information_requests
                  if r.information_request_reason == pl.REQUEST_NO_PROVIDER_HERE]

    assert unresolved
    assert "cause_hypothesis" in unresolved[0].needed_information


def test_without_a_registry_the_shortfall_is_still_stated_not_swallowed():
    loop = full_loop(info_selector=None, request_planner=None)

    outcome = loop.run([item(groups=1)]).object_records[0]

    assert outcome.information_requests
    assert outcome.information_requests[0].information_request_reason == \
        pl.REQUEST_NO_PROVIDER_HERE
    assert set(outcome.information_requests[0].needed_information) == \
        set(outcome.unmet_evidence_kinds)


# ---------------------------------------------------------------------------
# 프레임 참조와 좌표 (AI-C-03, AI-C-02)
# ---------------------------------------------------------------------------


def test_every_derived_result_keeps_the_original_observation_reference():
    outcome = full_loop().run([item(groups=1)]).object_records[0]

    assert outcome.frame_ref == "f1"
    for request in outcome.information_requests:
        assert request.frame_ref == "f1"
        assert request.observation_conditions[dd.FRAME_REF] == "f1"
    assert all(unit[1] == "f1" for unit in outcome.evidence_assessment.counted_units)


def test_the_local_frame_travels_and_no_global_value_is_invented():
    """datum 이 없는 현장은 정상 배치다 — 전역 칸이 생기지 않는다(AI-C-02)."""
    result = full_loop().run([item(groups=1)])
    body = result.as_dict()

    assert result.object_records[0].coordinate_frame == "ZONE"
    assert dd.GLOBAL_POSITION not in body
    for row in body[dd.OBJECT_RECORDS]:
        assert dd.GLOBAL_POSITION not in row
        assert row[dd.COORDINATE_FRAME] == "ZONE"


def test_the_snapshot_uses_only_dictionary_names():
    body = full_loop().run([item(groups=1)]).as_dict()

    assert dd.unknown_fields(body) == ()
    assert dd.unknown_fields(body[dd.OBJECT_RECORDS][0]) == ()
    assert dd.unknown_fields(body[dd.INFORMATION_REQUESTS][0]) == ()


# ---------------------------------------------------------------------------
# 한 번 본 것을 두 번 세지 않는다 (AI-S-03, AI-S-06)
# ---------------------------------------------------------------------------


def test_two_results_on_one_source_and_frame_are_one_observation():
    loop = full_loop()

    folded = loop.run([item(groups=1, origins=(
        ("cam-a", "f1"), ("cam-a", "f1"), ("cam-b", "f1")))]).object_records[0]

    assessment = folded.evidence_assessment
    assert assessment.evidence_count == 2          # cam-a, cam-b — 세 번이 아니다
    assert assessment.duplicate_count == 1         # 접었다는 사실이 남는다
    assert assessment.origin_units_declared is True


def test_the_same_source_across_two_frames_is_two_observations():
    loop = full_loop()

    outcome = loop.run([item(groups=1, origins=(
        ("cam-a", "f1"), ("cam-a", "f2")))]).object_records[0]

    assert outcome.evidence_assessment.evidence_count == 2
    assert outcome.evidence_assessment.duplicate_count == 0


def test_the_loop_does_not_fold_the_origins_itself():
    """접는 규칙의 주인은 `perception/uncertainty.py` 하나다.

    평가자가 없으면 접힌 수를 아무도 내지 않는다 — 루프가 몰래 세지 않는다는 뜻이다.
    """
    outcome = full_loop(evaluator=None).run([item(origins=(
        ("cam-a", "f1"), ("cam-a", "f1")))]).object_records[0]

    assert outcome.evidence_assessment is None


# ---------------------------------------------------------------------------
# 반영은 요청으로만 (AI-C-13, AI-O-01)
# ---------------------------------------------------------------------------


def test_the_loop_runs_only_when_the_refresh_ledger_asks():
    from mission_runtime.runtime.refresh import RefreshLedger, Trigger, scope_of

    clock = [1000.0]
    ledger = RefreshLedger(clock=lambda: clock[0])
    loop = full_loop()
    seen: list[pl.LoopResult] = []
    work = loop.as_refresh_work([item(groups=1)], sink=seen.append)
    scope = scope_of("zone", "N4-1F-W")

    first = ledger.request(scope, Trigger.OPERATOR_VIEW, work=work)
    second = ledger.request(scope, Trigger.OPERATOR_VIEW, work=work)

    assert first.performed and first.record.items == ("zoneA-track-1",)
    # 억제되면 **호출되지 않는다** — 돌려 놓고 버리면 아무것도 아끼지 못한다.
    assert not second.performed
    assert len(seen) == 1


def test_a_failing_stage_does_not_stop_the_refresh_ledger():
    """선택 기능 장애가 화면 전체를 멈추지 않는다(AI-C-05)."""
    from mission_runtime.runtime.refresh import RefreshLedger, Trigger, scope_of

    class Exploding:
        def plan(self, *args, **kwargs):
            raise RuntimeError("provider gone")

    ledger = RefreshLedger()
    loop = full_loop(request_planner=Exploding())
    work = loop.as_refresh_work([item(groups=1)], sink=lambda _: None)

    decision = ledger.request(scope_of("zone", "Z"), Trigger.OPERATOR_VIEW, work=work)

    assert not decision.performed
    assert decision.reason.startswith("refresh_failed")
