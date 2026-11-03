"""implements: AI-S-02, AI-S-06, AI-L-01, AI-L-03
관련: AI-C-02, AI-C-19
covers: 여러 장치의 관측이 한 객체 레코드로 모이는 것, 같은 프레임에서 나온 두 결과가
        독립 확인으로 세지지 않는 것, 틀린 값을 끌고 간 장치를 추적이 지목하는 것,
        사람의 수정이 레코드만 바꾸고 모델은 바꾸지 않는 것, 좌표가 구역을 벗어나지
        않는 것.

융합 수식을 가짜로 바꿔치기하지 않는다. 여기 있는 시험은 전부 실제
`RecordResolver` · `GlobalTrajectoryAssociator` · `CandidateStore` · `LearningLineage`
를 돌린다 — 수식을 모형으로 덮으면 "두 장치가 합쳐졌다"는 통과해도 실제로 어디에
놓이는지는 아무도 확인하지 않은 상태가 된다.
"""

from __future__ import annotations

import math
import sys
from dataclasses import fields
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSOLE_DIR = PROJECT_ROOT / "tools" / "fms_console"
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

import twin  # noqa: E402
from twin import (  # noqa: E402
    CANDIDATE_REASON_POSITION_CORRECTION,
    COORDINATE_FRAME_ZONE,
    CUE_RANGE_M,
    CUE_SEMANTIC_CLASS,
    FRAME_ZONE_LOCAL,
    RANKING_CLASS_FLIP_THEN_WEIGHT,
    RANKING_LEAVE_ONE_OUT_POSITION,
    REASON_SOLE_SPATIAL_CONTRIBUTOR,
    TRACE_ABOUT_CLASS,
    TRACE_ABOUT_POSITION,
    ClassHypothesis,
    ContributedEvidence,
    ContributorInfluence,
    CorrectionRecord,
    DeviceDetection,
    DevicePlacement,
    FusedRecord,
    RecordTrace,
    TwinFusionService,
    ZoneView,
)

from mission_runtime.continual.lineage import LearningState
from mission_runtime.continual.stream_learning import (
    CandidateOrigin,
    ContinualLearner,
    PrototypeLearningProvider,
)
from mission_runtime.perception.object_record import UNKNOWN_CLASS

ZONE = "z1"

#: 세 장치가 구역 로컬 평면의 (5, 0) 을 서로 다른 쪽에서 본다. 배치를 마주보게 두면
#: 같은 물리 점이 세 장치에서 모두 (5, 0) 으로 떨어지므로, 융합이 틀렸을 때 그것이
#: 투영의 잘못인지 융합의 잘못인지 헷갈리지 않는다.
PLACEMENTS = (
    DevicePlacement("cam-a", ZONE, (0.0, 0.0, 0.0), camera_id="a"),
    DevicePlacement("cam-b", ZONE, (10.0, 0.0, 180.0), camera_id="b"),
    DevicePlacement("cam-d", ZONE, (5.0, 8.0, 270.0), camera_id="d"),
)

CENTRED_BBOX = (0.5, 0.4, 0.5, 0.6)


def service(*device_ids: str) -> TwinFusionService:
    """요청한 장치만 등록한 서비스. 등록은 기여가 아니다."""
    instance = TwinFusionService()
    wanted = set(device_ids) or {p.device_id for p in PLACEMENTS}
    for placement in PLACEMENTS:
        if placement.device_id in wanted:
            instance.register_device(placement)
    return instance


def detection(detection_id: str, device_id: str, *, range_m: float | None,
              label: str | None = None, confidence: float = 0.5,
              frame_ref: str | None = None, track: int = 1,
              observed_at: float = 1.0, provider_id: str = "detector",
              feature: tuple[float, ...] = ()) -> DeviceDetection:
    return DeviceDetection(
        detection_id=detection_id, device_id=device_id, track_local_id=track,
        frame_ref=frame_ref or f"frame-{device_id}-{detection_id}",
        observed_at=observed_at, bbox=CENTRED_BBOX, label=label,
        confidence=confidence, range_m=range_m, provider_id=provider_id,
        feature=feature)


def sole_record(instance: TwinFusionService) -> FusedRecord:
    records = instance.records(ZONE)
    assert len(records) == 1, [r.object_id for r in records]
    return records[0]


def by_device(trace: RecordTrace) -> dict[str, ContributorInfluence]:
    return {c.device_id: c for c in trace.contributors}


# --- (A) 여러 장치가 본 것을 한 장으로 ---------------------------------------


def test_two_devices_seeing_one_object_yield_one_record_with_two_contributors():
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.6))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris",
                                        confidence=0.6))

    record = sole_record(instance)
    assert record.contributor_device_ids == ("cam-a", "cam-b")
    assert record.supporting_device_count == 2
    assert record.evidence_sufficient is True
    assert record.semantic_class == "debris"
    assert record.fused_position == pytest.approx((5.0, 0.0), abs=1e-6)


def test_every_evidence_row_keeps_its_full_provenance():
    """출처가 빠지면 나중에 범인을 가리킬 수 없다 — 그래서 네 축을 모두 요구한다."""
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        provider_id="yolo-ish"))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris",
                                        provider_id="depth-ish"))

    rows = instance.evidence_rows(sole_record(instance).object_id)
    assert len(rows) == 2
    for row in rows:
        assert row.device_id          # 누가 만들었나
        assert row.frame_ref          # 어느 원본 관측에서
        assert row.observed_at        # 언제 본 것인가
        assert row.provider_id        # 어느 제공자가 낸 값인가
        assert row.evidence_id


def test_two_reports_from_the_same_frame_do_not_count_as_independent():
    """같은 프레임을 두 번 읽은 것은 두 번 본 것이 아니다(AI-S-06).

    두 번째 결과가 거리 50 m 를 주장하는데도 융합 위치가 끌려가지 않아야 한다 — 끌려
    가면 중복 전달만으로 위치를 움직일 수 있다는 뜻이다.
    """
    instance = service("cam-a")
    frame = "frame-a-1"
    instance.ingest_detection(detection("e1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.9, frame_ref=frame,
                                        provider_id="detector"))
    instance.ingest_detection(detection("e2", "cam-a", range_m=50.0, label="debris",
                                        confidence=0.9, frame_ref=frame,
                                        provider_id="classifier", observed_at=1.1))

    record = sole_record(instance)
    assert record.supporting_device_count == 1
    assert record.fused_position == pytest.approx((5.0, 0.0), abs=1e-6)

    rows = {row.evidence_id: row for row in instance.evidence_rows(record.object_id)}
    assert rows["e1"].independent is True
    assert rows["e1"].depends_on is None
    assert rows["e2"].independent is False
    assert rows["e2"].depends_on == "e1"

    contributor = by_device(instance.trace(record.object_id))["cam-a"]
    assert contributor.independent_contributions == 1
    assert contributor.dependent_rows == 1


def test_a_device_with_no_detection_contributes_nothing():
    """등록만 된 장치는 무기여다 — 반대 근거가 아니다(AI-C-05)."""
    instance = service("cam-a", "cam-b", "cam-d")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.6))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris",
                                        confidence=0.6))

    record = sole_record(instance)
    assert "cam-d" not in record.contributor_device_ids
    assert record.supporting_device_count == 2
    assert record.fused_position == pytest.approx((5.0, 0.0), abs=1e-6)
    assert "cam-d" not in by_device(instance.trace(record.object_id))

    silent = {d.device_id: d for d in instance.zone_view(ZONE).devices}["cam-d"]
    assert silent.observation_count == 0
    assert silent.objects_contributed == ()


def test_losing_a_device_does_not_rewrite_what_it_already_backed():
    """사라짐은 표가 아니다. 가용성에서 빠져도 이미 밝힌 클래스 입장은 남는다."""
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.6))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris",
                                        confidence=0.6))
    object_id = sole_record(instance).object_id

    instance.set_device_available("cam-b", False)
    instance.ingest_detection(detection("d3", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.6, frame_ref="frame-a-2",
                                        observed_at=2.0))

    assert instance.record(object_id).semantic_class == "debris"


def test_without_spatial_capability_each_source_keeps_its_own_track():
    """시간·공간·외형은 선택 근거다. 하나도 없으면 연계만 비활성화된다(AI-S-02)."""
    instance = service("cam-a", "cam-b")
    instance.set_available_capability_kinds(())
    assert instance.usable_evidence() == ()

    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris"))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris"))

    records = instance.records(ZONE)
    assert len(records) == 2
    assert all(len(r.contributor_device_ids) == 1 for r in records)


def test_a_detection_without_range_is_never_guessed_into_a_position():
    """없는 거리를 지어내지 않는다.

    방위만 아는 결과는 비교할 공간 신호가 없으므로 다른 장치의 집계와 맞출 수 없고,
    따라서 그 장치만의 레코드로 남는다. 가까워 보인다는 이유로 붙이면 그것은 연계가
    아니라 추측이고, 추측이 한 객체의 위치를 끌어가게 된다.
    """
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.6))
    instance.ingest_detection(detection("d2", "cam-b", range_m=None, label="debris",
                                        confidence=0.9))

    records = {r.contributor_device_ids: r for r in instance.records(ZONE)}
    assert set(records) == {("cam-a",), ("cam-b",)}
    # 거리를 낸 장치의 위치는 방위만 아는 결과에 끌려가지 않는다.
    assert records[("cam-a",)].fused_position == pytest.approx((5.0, 0.0), abs=1e-6)
    assert records[("cam-b",)].fused_position is None

    bearing_only = records[("cam-b",)]
    assert bearing_only.semantic_class == "debris"      # 의미는 그대로 쌓인다
    contributor = by_device(instance.trace(bearing_only.object_id))["cam-b"]
    assert contributor.independent_contributions == 0
    assert contributor.reason == twin.REASON_NO_SPATIAL_EVIDENCE


def test_redelivering_the_same_detection_adds_nothing():
    instance = service("cam-a")
    first = instance.ingest_detection(detection("d1", "cam-a", range_m=5.0,
                                                label="debris"))
    again = instance.ingest_detection(detection("d1", "cam-a", range_m=5.0,
                                                label="debris"))

    assert again.object_id == first.object_id
    assert len(instance.evidence_rows(first.object_id)) == 1


# --- (B) 추적: 누가 값을 끌고 갔는가 ------------------------------------------


def disagreeing_pair() -> TwinFusionService:
    """두 장치가 같은 객체를 다른 자리에 놓는다. cam-b 가 더 확신하고 더 멀리 끈다."""
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.5))
    instance.ingest_detection(detection("d2", "cam-b", range_m=3.5, label="debris",
                                        confidence=0.9))
    return instance


def test_trace_names_the_contributor_that_actually_moved_the_value():
    instance = disagreeing_pair()
    record = sole_record(instance)
    # 신뢰도 가중 평균: (0.5*5.0 + 0.9*6.5) / 1.4
    assert record.fused_position == pytest.approx((5.9642857, 0.0), abs=1e-5)

    trace = instance.trace(record.object_id, about=TRACE_ABOUT_POSITION)
    assert trace.ranking_rule == RANKING_LEAVE_ONE_OUT_POSITION
    assert trace.contributors[0].device_id == "cam-b"

    influences = by_device(trace)
    # 반사실: cam-b 를 빼면 (5.0, 0) 으로, cam-a 를 빼면 (6.5, 0) 으로 간다.
    assert influences["cam-b"].position_influence_m == pytest.approx(0.9642857, abs=1e-5)
    assert influences["cam-a"].position_influence_m == pytest.approx(0.5357143, abs=1e-5)
    assert influences["cam-b"].position_influence_m > influences["cam-a"].position_influence_m
    assert influences["cam-b"].claimed_position == pytest.approx((6.5, 0.0), abs=1e-6)
    assert influences["cam-b"].evidence_ids == ("d2",)


def test_influence_is_a_counterfactual_not_the_confidence_share():
    """지분만 보면 많이 보낸 장치가 늘 1등이 된다. 두 축이 다른 값이어야 한다."""
    instance = disagreeing_pair()
    influences = by_device(instance.trace(sole_record(instance).object_id))

    assert influences["cam-b"].contributor_weight == pytest.approx(0.9 / 1.4, abs=1e-6)
    assert influences["cam-b"].position_influence_m != pytest.approx(
        influences["cam-b"].contributor_weight)


def test_the_only_spatial_contributor_ranks_first_with_an_explicit_reason():
    """빼면 공간 근거가 하나도 남지 않는 장치를 변위 0 으로 적으면 꼴찌가 된다."""
    instance = service("cam-a")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris"))

    trace = instance.trace(sole_record(instance).object_id)
    assert trace.contributors[0].device_id == "cam-a"
    assert trace.contributors[0].position_influence_m is None
    assert trace.contributors[0].reason == REASON_SOLE_SPATIAL_CONTRIBUTOR


def test_trace_about_the_class_names_the_contributor_that_flips_it():
    """질문이 다르면 범인도 다르다 — 위치 질문과 클래스 질문의 순위는 같지 않다."""
    instance = service("cam-a", "cam-b", "cam-d")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.6))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris",
                                        confidence=0.6))
    instance.ingest_detection(detection("d3", "cam-d", range_m=8.0, label="person",
                                        confidence=0.99))

    record = sole_record(instance)
    assert record.semantic_class == "debris"          # 2 표가 1 표를 이긴다

    trace = instance.trace(record.object_id, about=TRACE_ABOUT_CLASS)
    assert trace.ranking_rule == RANKING_CLASS_FLIP_THEN_WEIGHT
    assert trace.baseline_semantic_class == "debris"

    influences = by_device(trace)
    assert trace.contributors[0].flips_class_to == "person"
    assert influences["cam-a"].flips_class_to == "person"
    assert influences["cam-b"].flips_class_to == "person"
    # 가장 확신한 장치가 범인이 아니다: cam-d 를 빼도 결론은 그대로다.
    assert influences["cam-d"].flips_class_to is None
    assert influences["cam-d"].class_vote == "person"


def test_the_class_is_kept_as_hypotheses_rather_than_one_confirmed_label():
    instance = service("cam-a", "cam-b", "cam-d")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.6))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris",
                                        confidence=0.6))
    instance.ingest_detection(detection("d3", "cam-d", range_m=8.0, label="person",
                                        confidence=0.99))

    hypotheses = {h.label: h for h in sole_record(instance).class_hypotheses}
    assert hypotheses["debris"].independent_support == 2
    assert hypotheses["person"].independent_support == 1
    assert hypotheses["person"].devices == ("cam-d",)


def test_trace_rejects_a_question_it_does_not_answer():
    instance = disagreeing_pair()
    with pytest.raises(ValueError):
        instance.trace(sole_record(instance).object_id, about="vibes")


# --- (B) 수정: 레코드는 즉시, 모델은 전혀 ------------------------------------


def test_position_correction_changes_the_record_and_files_one_human_candidate():
    instance = disagreeing_pair()
    record = sole_record(instance)

    outcome = instance.apply_position_correction(
        record.object_id, (5.0, 0.0), actor="operator-1", reason="operator_drag")

    assert outcome.record.fused_position == pytest.approx((5.0, 0.0), abs=1e-6)
    # 센서가 그렇게 봤다는 사실은 지우지 않는다 — 남은 불일치가 보여야 한다.
    assert outcome.record.sensor_fused_position == pytest.approx((5.9642857, 0.0),
                                                                 abs=1e-5)
    assert outcome.record.position_disagreement_m == pytest.approx(0.9642857, abs=1e-5)
    assert outcome.record.operator_corrected is True

    # 책임은 추적 1순위 기여자에게 돌아간다.
    assert outcome.correction.device_id == "cam-b"
    assert outcome.correction.actor == "operator-1"

    ledger = instance.learning_candidates()
    assert len(ledger.human_confirmed) == 1
    assert ledger.auto_inference == ()
    filed = ledger.human_confirmed[0]
    assert filed.candidate_origin == CandidateOrigin.HUMAN_CONFIRMED.value
    assert filed.device_id == "cam-b"
    assert filed.reason == CANDIDATE_REASON_POSITION_CORRECTION
    assert filed.learning_candidate_id == outcome.learning_candidate_id
    assert filed.learning_lineage_id == outcome.learning_lineage_id

    lineage = instance.lineage(outcome.learning_lineage_id)
    assert lineage.state is LearningState.CANDIDATE
    assert len(lineage.events) == 1
    assert lineage.events[0].requirement_id == "AI-L-01"
    assert outcome.learning_state == LearningState.CANDIDATE.value


def test_the_filed_candidate_is_confirmed_and_keeps_the_device_conditions():
    instance = disagreeing_pair()
    record = sole_record(instance)
    instance.apply_position_correction(record.object_id, (5.0, 0.0),
                                       actor="operator-1", reason="operator_drag")

    store = instance.candidate_store
    assert store.total_count() == 1
    assert store.confirmed_count() == 1

    conditions = store.groups()
    assert len(conditions) == 1
    assert conditions[0].device_id == "cam-b"
    assert conditions[0].camera_id == "b"
    assert ("candidate_reason", CANDIDATE_REASON_POSITION_CORRECTION) in conditions[0].extra

    batch = store.batch_for(conditions[0])
    sample = batch.samples[0]
    assert sample.confirmed is True
    # 특징은 "저기가 맞다"가 아니라 "이 카메라가 어느 쪽으로 얼마나 틀어졌다"다.
    bearing_error, range_error = sample.feature
    assert bearing_error == pytest.approx(0.0, abs=1e-6)
    assert range_error == pytest.approx(1.5, abs=1e-6)   # 3.5 m 라 했는데 5.0 m 였다


def test_a_correction_never_mutates_model_state():
    """사람의 수정은 레코드를 바꾸고 모델은 바꾸지 않는다(AI-L-03)."""
    instance = disagreeing_pair()
    record = sole_record(instance)
    outcome = instance.apply_position_correction(
        record.object_id, (5.0, 0.0), actor="operator-1", reason="operator_drag")

    # 후보는 기존 학습 경로가 **나중에** 집어가는 입력으로만 남는다.
    learner = ContinualLearner(provider=PrototypeLearningProvider(),
                              store=instance.candidate_store)
    assert learner.bases == {}
    conditions = instance.candidate_store.groups()[0]
    assert learner.base_version(conditions) is None

    # 계보는 CANDIDATE 에서 멈춰 있다: 검증(AI-L-05)·승인·단계적 적용(AI-L-07)을
    # 이 모듈이 건너뛰지 않았다는 뜻이다.
    assert instance.lineage(outcome.learning_lineage_id).state is LearningState.CANDIDATE

    # 승격 동사를 아예 갖지 않는다. 가지고 있으면 언젠가 호출된다.
    for verb in ("train", "adopt", "promote", "deploy", "apply_parameters",
                 "update_model", "advance"):
        assert not hasattr(instance, verb)


def test_cue_correction_on_the_class_wins_immediately_but_only_files_a_candidate():
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris",
                                        confidence=0.6, feature=(0.2, 0.9)))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris",
                                        confidence=0.6))
    record = sole_record(instance)

    outcome = instance.apply_cue_correction(
        record.object_id, device_id="cam-a", cue_name=CUE_SEMANTIC_CLASS,
        corrected_value="driftwood", actor="operator-1", reason="wrong_label")

    assert outcome.record.semantic_class == "driftwood"
    # 센서가 무엇이라 했는지는 지우지 않는다.
    assert outcome.record.sensor_semantic_class == "debris"
    assert outcome.correction.reported_value == "debris"
    assert outcome.correction.cue_name == CUE_SEMANTIC_CLASS

    hypotheses = {h.label: h for h in outcome.record.class_hypotheses}
    assert hypotheses["driftwood"].operator_confirmed is True
    assert hypotheses["debris"].operator_confirmed is False

    ledger = instance.learning_candidates()
    assert len(ledger.human_confirmed) == 1
    assert ledger.human_confirmed[0].label == "driftwood"
    assert (instance.lineage(outcome.learning_lineage_id).state
            is LearningState.CANDIDATE)

    sample = instance.candidate_store.batch_for(
        instance.candidate_store.groups()[0]).samples[0]
    assert sample.label == "driftwood"
    assert sample.feature == (0.2, 0.9)       # 모델이 실제로 낸 특징을 그대로 쓴다
    assert sample.similarity == pytest.approx(0.6)


def test_cue_correction_on_the_range_refuses_through_the_same_resolver():
    """거리 단서를 고치면 그 장치의 공간 주장이 다시 투영되어 같은 수식으로 융합된다."""
    instance = disagreeing_pair()
    record = sole_record(instance)

    outcome = instance.apply_cue_correction(
        record.object_id, device_id="cam-b", cue_name=CUE_RANGE_M,
        corrected_value=5.0, actor="operator-1", reason="range_was_short")

    assert outcome.correction.reported_value == pytest.approx(3.5)
    assert outcome.correction.corrected_value == pytest.approx(5.0)
    assert outcome.record.fused_position == pytest.approx((5.0, 0.0), abs=1e-6)
    # 장치 근거만의 값은 고쳐지지 않은 그대로 남는다.
    assert outcome.record.sensor_fused_position == pytest.approx((5.9642857, 0.0),
                                                                 abs=1e-5)

    row = {r.evidence_id: r for r in instance.evidence_rows(record.object_id)}["d2"]
    assert outcome.correction.correction_id in row.corrected_by


def test_a_cue_the_device_never_reported_cannot_be_corrected():
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris"))
    record = sole_record(instance)

    with pytest.raises(ValueError):
        instance.apply_cue_correction(record.object_id, device_id="cam-b",
                                      cue_name=CUE_SEMANTIC_CLASS,
                                      corrected_value="x", actor="op", reason="r")
    with pytest.raises(ValueError):
        instance.apply_cue_correction(record.object_id, device_id="cam-a",
                                      cue_name="made_up_cue", corrected_value="x",
                                      actor="op", reason="r")


def test_a_correction_without_an_actor_or_reason_is_refused():
    instance = disagreeing_pair()
    object_id = sole_record(instance).object_id

    with pytest.raises(ValueError):
        instance.apply_position_correction(object_id, (5.0, 0.0), actor="", reason="r")
    with pytest.raises(ValueError):
        instance.apply_position_correction(object_id, (5.0, 0.0), actor="op", reason="")


# --- (B) 학습 후보 원장 -------------------------------------------------------


def test_unresolved_class_files_an_auto_candidate_kept_apart_from_human_ones():
    """여러 장치가 같은 것을 보고도 이름이 안 붙으면 그 사실이 후보 사유다(AI-L-01)."""
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("h1", "cam-a", range_m=5.0, confidence=0.4,
                                        feature=(0.1, 0.2)))
    instance.ingest_detection(detection("h2", "cam-b", range_m=5.0, confidence=0.4,
                                        feature=(0.1, 0.2)))
    instance.ingest_detection(detection("h3", "cam-b", range_m=5.0, confidence=0.4,
                                        frame_ref="frame-b-2", observed_at=2.0,
                                        feature=(0.1, 0.2)))

    record = sole_record(instance)
    assert record.semantic_class == UNKNOWN_CLASS

    ledger = instance.learning_candidates()
    assert ledger.human_confirmed == ()
    assert len(ledger.auto_inference) == 1      # 반복 수신으로 중복 제출하지 않는다
    auto = ledger.auto_inference[0]
    assert auto.candidate_origin == CandidateOrigin.AUTO_INFERENCE.value

    # 미검증 추론은 확정 정답이 아니다(AI-L-02): 학습 입력으로 세어지지 않는다.
    assert instance.candidate_store.total_count() == 1
    assert instance.candidate_store.confirmed_count() == 0

    outcome = instance.apply_cue_correction(
        record.object_id, device_id="cam-a", cue_name=CUE_SEMANTIC_CLASS,
        corrected_value="driftwood", actor="operator-1", reason="named_by_operator")
    ledger = instance.learning_candidates()
    assert len(ledger.human_confirmed) == 1
    assert len(ledger.auto_inference) == 1
    assert ledger.human_confirmed[0].learning_candidate_id == outcome.learning_candidate_id


# --- 좌표 경계 ----------------------------------------------------------------


PUBLIC_SHAPES = (FusedRecord, RecordTrace, ContributorInfluence, ContributedEvidence,
                 ClassHypothesis, CorrectionRecord, ZoneView)


def test_coordinates_never_leave_the_local_frame():
    instance = service("cam-a", "cam-b")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris"))
    instance.ingest_detection(detection("d2", "cam-b", range_m=5.0, label="debris"))
    record = sole_record(instance)

    assert record.frame_id == FRAME_ZONE_LOCAL == "zone"
    assert record.coordinate_frame == COORDINATE_FRAME_ZONE == "ZONE"
    assert record.coordinate_frame != "GLOBAL"
    for row in instance.evidence_rows(record.object_id):
        assert row.frame_id == FRAME_ZONE_LOCAL

    view = instance.zone_view(ZONE)
    assert view.frame_id == FRAME_ZONE_LOCAL
    assert view.coordinate_frame == COORDINATE_FRAME_ZONE

    trace = instance.trace(record.object_id)
    assert trace.coordinate_frame == COORDINATE_FRAME_ZONE


def test_no_public_name_offers_a_global_pose():
    """전역 좌표와 authoritative 트윈 상태는 백엔드 몫이다(AI-C-02, AI-C-19).

    낼 수 있는 칸이 없으면 실수로 내보낼 수도 없다.
    """
    for shape in PUBLIC_SHAPES:
        for member in fields(shape):
            assert "global" not in member.name, (shape.__name__, member.name)

    public = [name for name in dir(TwinFusionService) if not name.startswith("_")]
    assert public, "the service must expose something"
    for name in public:
        assert "global" not in name


def test_the_zone_view_places_objects_on_the_zone_structure_layer():
    """같은 구역 평면 위에 객체와 구조가 함께 놓인다 — 자료는 서로 섞이지 않는다."""
    from mission_runtime.perception.environment_map import StructureEvidence

    instance = service("cam-a")
    instance.ingest_detection(detection("d1", "cam-a", range_m=5.0, label="debris"))
    instance.ingest_structure(ZONE, "bank-1", StructureEvidence(
        evidence_id="s1", producer="cam-a", frame_ref="frame-a-1", observed_at=1.0,
        kind="obstacle", extent=(4.0, -1.0, 6.0, 1.0), confidence=0.8,
        frame_id=FRAME_ZONE_LOCAL))

    view = instance.zone_view(ZONE)
    assert len(view.records) == 1
    assert len(view.map_elements) == 1
    assert view.map_elements[0].kind == "obstacle"
    # 구조 근거가 객체 레코드의 지지 장치 수를 늘리지 않는다.
    assert view.records[0].supporting_device_count == 1


def test_bearing_and_projection_stay_a_declared_placement_computation():
    """투영은 선언된 배치와 화각만 쓴다 — 보정 프로파일은 입력이지 책임이 아니다."""
    placement = PLACEMENTS[0]
    left = twin.bearing_from_image(placement, (0.0, 0.4, 0.0, 0.6))
    centre = twin.bearing_from_image(placement, CENTRED_BBOX)
    right = twin.bearing_from_image(placement, (1.0, 0.4, 1.0, 0.6))

    assert centre == pytest.approx(0.0)
    assert left == pytest.approx(-placement.horizontal_fov_deg / 2)
    assert right == pytest.approx(placement.horizontal_fov_deg / 2)
    assert twin.place_at(placement, 90.0, 3.0) == pytest.approx((0.0, 3.0), abs=1e-9)
    assert math.isclose(
        math.dist((0.0, 0.0), twin.place_at(placement, 33.0, 7.0)), 7.0, abs_tol=1e-9)


def test_an_unregistered_device_cannot_contribute():
    instance = service("cam-a")
    with pytest.raises(ValueError):
        instance.ingest_detection(detection("d1", "cam-zz", range_m=5.0))
