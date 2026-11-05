"""학습 후보 → 검증 → 승인 → 배정 → 단계적 적용. **끊기지 않는지**가 전부다.

implements: AI-L-05, AI-L-06, AI-L-07, AI-L-08, AI-L-09, AI-L-10, AI-B-01
tests: 승격 거절 사유, 미측정 지연·메모리, 계보가 가리키는 것과 올라가는 것의 일치,
       실제 운영 스트림 모양에서 시작하는 한 줄기
"""

from __future__ import annotations

import json

import pytest

from mission_runtime.continual.lineage import LearningLineage, LearningState
from mission_runtime.continual.operational_stream import read_run
from mission_runtime.continual.parameter_evaluation import (
    ConfirmedAcceptanceScorer,
    EvaluationGate,
    GateResult,
    ParameterEvaluator,
)
from mission_runtime.continual.stream_ingest import (
    ThresholdLearningProvider,
    parameter_set_from_class_features,
)
from mission_runtime.continual.stream_learning import (
    CandidateBatch,
    CandidateOrigin,
    ContinualLearner,
    InputConditions,
    ParameterSet,
    StreamSample,
)
from mission_runtime.execution.control import LocalControlSupervisor
from mission_runtime.runtime.clusters import ClusterBinding, PlacementRequest
from mission_runtime.runtime.learned_version import (
    ASSET_KIND_PARAMETERS,
    REASON_DEVICE_MISMATCH,
    REASON_GATE_NOT_PASSED,
    REASON_NOT_APPROVED,
    REASON_PROMOTED,
    REASON_REPORT_MISMATCH,
    SCOPE_LATENCY,
    SCOPE_MEMORY,
    SCOPE_RESOLUTION,
    LearnedVersionRegistrar,
    condition_tokens,
    deployment_request,
    parameter_asset,
    promote,
)
from mission_runtime.runtime.mlops_pipeline import (
    Deployable,
    DeploymentPhase,
    MlopsPipeline,
    PromotionScope,
)
from mission_runtime.runtime.model_assignment import (
    REASON_SCOPE_HARDWARE,
    REASON_UNMEASURED_NOT_ELIGIBLE,
    DeviceProfile,
    MissionRequirement,
    PinnedVersion,
)

KIND = "perception.detect_ovd"
DEVICE_ID = "robot1"
RUN = "20261001_123152"

CONDITIONS = InputConditions(device_id=DEVICE_ID, camera_id="robot1-cam0",
                             resolution=(1920, 1080),
                             extra=(("model", "yoloe"),))
DEVICE = DeviceProfile(DEVICE_ID, hw_tags=frozenset({"compute.gpu", "tier.edge"}),
                       input_conditions=frozenset({"resolution.1920x1080"}),
                       memory_mb=4096.0)


# --- helpers ----------------------------------------------------------------


def _confirmed(index: int, label: str, similarity: float,
               conditions: InputConditions = CONDITIONS) -> StreamSample:
    """사람이 확인한 표본 1건. 확인 자체는 운영자 경로(twin)의 일이다(AI-L-03)."""
    return StreamSample(
        sample_id=f"s{index}", conditions=conditions, label=label,
        feature=(similarity,), origin=CandidateOrigin.HUMAN_CONFIRMED,
        frame_ref=f"{DEVICE_ID}/{RUN}/frames/{index:09d}.jpg",
        confidence=similarity, similarity=similarity,
    )


def _base(threshold: float = 0.50, label: str = "door") -> ParameterSet:
    return ParameterSet(
        parameters={label: {"prompts": [f"a photo of a {label}"],
                            "threshold": threshold, "gates": {}}},
        conditions=CONDITIONS, produced_by="curated")


def _trained(samples, *, base: ParameterSet | None = None) -> ParameterSet:
    provider = ThresholdLearningProvider(min_samples=3, quantile=0.0, max_step=0.2)
    outcome = provider.train(CandidateBatch(CONDITIONS, tuple(samples)),
                             base=base or _base())
    assert outcome.produced, outcome.reason
    return outcome.parameters


def _evaluator() -> ParameterEvaluator:
    return ParameterEvaluator(ConfirmedAcceptanceScorer())


def _approved(cites: str, lineage_id: str = "lin-1") -> LearningLineage:
    """승인까지 간 계보. **그 후보의 버전을 근거로 들고** 간다.

    `cites` 가 인자인 것이 요점이다 — 계보가 그 후보를 근거로 든 적이 없으면
    `promote()` 가 거절한다. 전에 이 보조 함수가 "ev" 라는 고정 문자열만 들던 동안
    그 거절은 시험에 걸리지 않았고, 실제 경로(`TrainingDesk._open_lineage`)는 늘
    파라미터 버전을 근거로 든다(AI-L-08).
    """
    lineage = LearningLineage(lineage_id, actor="op", evidence_ref=cites,
                              reason="repeated_unknown_object")
    while lineage.state is not LearningState.APPROVED:
        lineage.advance(actor="op", evidence_ref=cites, reason="stage")
    return lineage


def _pipeline(**kw) -> MlopsPipeline:
    return MlopsPipeline(
        [ClusterBinding("zone-edge", LocalControlSupervisor(),
                        frozenset({"zone-edge"}))], **kw)


DEPLOYABLE = Deployable(
    deployable_id="detector", capability_kind=KIND,
    placement=PlacementRequest(required_tags=frozenset({"zone-edge"})),
    control_params={"image": "registry.internal:5000/mr@sha256:" + "0" * 64})


# --- 검증 게이트가 실제 자료 모양에서 돈다 (AI-L-05) -----------------------


def test_the_threshold_scorer_makes_the_gate_runnable_on_stream_shaped_candidates():
    """`PrototypeScorer` 로는 이 모양의 후보가 구조적으로 통과할 수 없었다.

    특징 벡터가 없으므로 prototype 이 없고, prototype 이 없으면 언제나 `None` 이라
    정확도가 0이 된다.
    """
    from mission_runtime.continual.parameter_evaluation import PrototypeScorer

    candidate = _trained([_confirmed(i, "door", 0.6 + i / 100) for i in range(5)])
    held = [_confirmed(90, "door", 0.72)]

    blind = ParameterEvaluator(PrototypeScorer()).evaluate(
        candidate, new_samples=held, retained_samples=[], base=_base())
    assert blind.new.ratio == 0.0 and blind.result is GateResult.FAIL

    usable = _evaluator().evaluate(candidate, new_samples=held,
                                   retained_samples=[], base=_base())
    assert usable.new.ratio == 1.0 and usable.result is GateResult.PASS


def test_a_raised_threshold_shows_up_as_regression_not_as_improvement():
    """회귀 축은 그대로 뜻이 있다 — 전에 받아들이던 관측을 잃으면 보인다."""
    strict = ParameterSet(parameters={"door": {"prompts": ["x"], "threshold": 0.9}},
                          conditions=CONDITIONS)
    retained = [_confirmed(i, "door", 0.6) for i in range(4)]
    report = _evaluator().evaluate(
        strict, new_samples=[_confirmed(90, "door", 0.95)],
        retained_samples=retained, base=_base(0.5))
    assert report.baseline.ratio == 1.0
    assert report.retained.ratio == 0.0
    assert report.regression == pytest.approx(1.0)
    assert report.result is GateResult.FAIL


def test_an_unthresholded_label_is_not_counted_as_correct():
    """임계를 재지 않은 라벨은 통과도 탈락도 아니다 — 미측정이다."""
    scorer = ConfirmedAcceptanceScorer()
    params = ParameterSet(parameters={"door": {"prompts": ["x"], "threshold": None}},
                          conditions=CONDITIONS)
    assert scorer.predict(params, _confirmed(1, "door", 0.99)) is None
    assert scorer.predict(_base(), _confirmed(1, "window", 0.99)) is None
    no_score = StreamSample("s", CONDITIONS, "door", (0.1,),
                            CandidateOrigin.HUMAN_CONFIRMED)
    assert scorer.predict(_base(), no_score) is None


# --- 승격 거절 (AI-B-01, AI-L-05/06) ---------------------------------------


def test_a_candidate_that_did_not_pass_the_gate_is_not_promoted():
    candidate = _trained([_confirmed(i, "door", 0.6) for i in range(4)])
    failing = _evaluator().evaluate(candidate, new_samples=[], retained_samples=[],
                                    base=_base())
    assert failing.result is GateResult.NOT_MEASURED
    result = promote(candidate, failing, model_id="door-detector",
                     capability_kind=KIND, device=DEVICE)
    assert not result.promoted
    assert result.reason.startswith(REASON_GATE_NOT_PASSED)
    assert GateResult.NOT_MEASURED.value in result.reason


def test_a_report_about_another_candidate_is_refused():
    """성적표와 물건이 짝이 맞지 않으면 품질 수치가 다른 물건의 것이 된다."""
    one = _trained([_confirmed(i, "door", 0.6 + i / 100) for i in range(5)])
    other = _trained([_confirmed(i, "door", 0.8 + i / 100) for i in range(5)])
    assert one.version != other.version
    report = _evaluator().evaluate(other, new_samples=[_confirmed(90, "door", 0.9)],
                                   retained_samples=[], base=_base())
    assert report.result is GateResult.PASS
    result = promote(one, report, model_id="door-detector", capability_kind=KIND,
                     device=DEVICE)
    assert not result.promoted
    assert result.reason.startswith(REASON_REPORT_MISMATCH)


def test_a_candidate_is_not_scoped_to_a_device_it_never_ran_on():
    """AI-B-01: 다른 구성에서 측정한 성능을 같다고 가정하지 않는다."""
    candidate = _trained([_confirmed(i, "door", 0.6 + i / 100) for i in range(5)])
    report = _evaluator().evaluate(candidate, new_samples=[_confirmed(90, "door", 0.9)],
                                   retained_samples=[], base=_base())
    elsewhere = DeviceProfile("drone", hw_tags=frozenset({"compute.npu"}))
    result = promote(candidate, report, model_id="door-detector", capability_kind=KIND,
                     device=elsewhere)
    assert not result.promoted
    assert result.reason == f"{REASON_DEVICE_MISMATCH}:{DEVICE_ID}"


def test_an_unapproved_candidate_is_not_registered():
    candidate = _trained([_confirmed(i, "door", 0.6 + i / 100) for i in range(5)])
    report = _evaluator().evaluate(candidate, new_samples=[_confirmed(90, "door", 0.9)],
                                   retained_samples=[], base=_base())
    pending = LearningLineage("lin-x", actor="op", evidence_ref="ev", reason="candidate")
    result = promote(candidate, report, model_id="door-detector", capability_kind=KIND,
                     device=DEVICE, lineage=pending)
    assert not result.promoted
    assert result.reason.startswith(REASON_NOT_APPROVED)


# --- 미측정은 0이 아니다 (AI-B-01, AI-O-05) --------------------------------


def _passing():
    candidate = _trained([_confirmed(i, "door", 0.6 + i / 100) for i in range(5)])
    report = _evaluator().evaluate(candidate, new_samples=[_confirmed(90, "door", 0.9)],
                                   retained_samples=[], base=_base())
    assert report.result is GateResult.PASS
    return candidate, report


def test_a_promoted_version_leaves_latency_and_memory_unmeasured_and_says_so():
    """파라미터 갱신은 정확도만 잰다. 재지 않은 것을 숫자로 채우지 않는다."""
    candidate, report = _passing()
    result = promote(candidate, report, model_id="door-detector",
                     capability_kind=KIND, device=DEVICE)
    assert result.promoted and result.reason == REASON_PROMOTED
    version = result.version
    assert version.quality == pytest.approx(report.new.ratio)
    assert version.latency_ms is None and version.memory_mb is None
    assert not version.fully_measured
    assert SCOPE_LATENCY in result.unverified_scope
    assert SCOPE_MEMORY in result.unverified_scope


def test_an_unmeasured_promoted_version_is_not_eligible_by_default():
    """이것은 고장이 아니라 요구사항이다 — 0으로 채워 적격으로 만들지 않는다."""
    candidate, report = _passing()
    result = promote(candidate, report, model_id="door-detector",
                     capability_kind=KIND, device=DEVICE)
    pipeline = _pipeline()
    LearnedVersionRegistrar(pipeline).register(result)

    strict = pipeline.assigner.assign(DEVICE, MissionRequirement("m", KIND))
    assert strict.assigned is None
    assert strict.rejected[0].reason == REASON_UNMEASURED_NOT_ELIGIBLE

    accepted = pipeline.assigner.assign(
        DEVICE, MissionRequirement("m", KIND, allow_unmeasured=True))
    assert accepted.assigned.version == candidate.version


def test_measured_latency_is_carried_only_when_actually_given():
    candidate, report = _passing()
    measured = promote(candidate, report, model_id="door-detector",
                       capability_kind=KIND, device=DEVICE,
                       measured_latency_ms=41.0, measured_memory_mb=1400.0)
    assert measured.version.fully_measured
    assert SCOPE_LATENCY not in measured.unverified_scope
    assert SCOPE_MEMORY not in measured.unverified_scope


def test_an_unknown_resolution_is_reported_rather_than_claimed_as_unconstrained():
    """빈 조건 집합은 배정에서 '조건 무관' 으로 읽힌다 — 모르는 것이 더 넓은 주장이다."""
    conditions = InputConditions(device_id=DEVICE_ID, camera_id="cam0",
                                 resolution=None, extra=(("model", "yoloe"),))
    assert condition_tokens(conditions) == frozenset()
    samples = [_confirmed(i, "door", 0.6 + i / 100, conditions) for i in range(5)]
    provider = ThresholdLearningProvider(min_samples=3, quantile=0.0, max_step=0.2)
    base = ParameterSet(parameters={"door": {"prompts": ["x"], "threshold": 0.5}},
                        conditions=conditions)
    candidate = provider.train(CandidateBatch(conditions, tuple(samples)),
                               base=base).parameters
    report = _evaluator().evaluate(
        candidate, new_samples=[_confirmed(90, "door", 0.9, conditions)],
        retained_samples=[], base=base)
    result = promote(candidate, report, model_id="d", capability_kind=KIND,
                     device=DeviceProfile(DEVICE_ID))
    assert result.promoted
    assert result.version.verified_input_conditions == frozenset()
    assert SCOPE_RESOLUTION in result.unverified_scope
    assert "hardware_tags_undeclared" in result.unverified_scope


def test_the_verified_scope_keeps_a_version_off_the_wrong_hardware():
    candidate, report = _passing()
    result = promote(candidate, report, model_id="door-detector",
                     capability_kind=KIND, device=DEVICE,
                     measured_latency_ms=41.0, measured_memory_mb=1400.0)
    pipeline = _pipeline()
    LearnedVersionRegistrar(pipeline).register(result)
    cpu_only = DeviceProfile(DEVICE_ID, hw_tags=frozenset({"compute.cpu"}),
                             input_conditions=frozenset({"resolution.1920x1080"}),
                             memory_mb=4096.0)
    assignment = pipeline.assigner.assign(cpu_only, MissionRequirement("m", KIND))
    assert assignment.assigned is None
    assert assignment.rejected[0].reason == REASON_SCOPE_HARDWARE


# --- 계보가 가리키는 것과 올라가는 것이 같다 (AI-L-08) ---------------------


def test_what_the_lineage_approved_is_what_actually_gets_placed():
    """메운 공백 그 자체.

    등록이 없으면 "후보 sha256-abc 를 승인했다" 는 계보를 들고 손으로 적은 다른
    버전이 올라갈 수 있었고, 그러면 AI-L-08 의 역추적이 그 자리에서 거짓을 말한다.
    """
    candidate, report = _passing()
    lineage = _approved(candidate.version)
    pipeline = _pipeline()
    registrar = LearnedVersionRegistrar(pipeline)
    promotion = registrar.promote_and_register(
        candidate, report, model_id="door-detector", capability_kind=KIND,
        device=DEVICE, lineage=lineage, measured_latency_ms=41.0,
        measured_memory_mb=1400.0)
    assert promotion.promoted

    pipeline.assigner.policy = PinnedVersion(promotion.reference)
    status = pipeline.submit(DEPLOYABLE, DEVICE, MissionRequirement("m", KIND),
                             lineage=lineage, actor="op", evidence_ref=candidate.version)

    assert status.phase is DeploymentPhase.PLACED
    # 올라간 버전의 신원이 계보의 근거와 같은 문자열이다.
    assert status.version_reference == f"door-detector@{candidate.version}"
    assert candidate.version in status.version_reference
    assert lineage.events[0].reason == "repeated_unknown_object"
    assert any(candidate.version in event.evidence_ref for event in lineage.events)


def test_the_placed_version_starts_in_verification_scope_and_widens_one_step():
    """AI-L-07: 승인된 것이 곧 전체 운영이 아니다."""
    candidate, report = _passing()
    lineage = _approved(candidate.version)
    pipeline = _pipeline()
    promotion = LearnedVersionRegistrar(pipeline).promote_and_register(
        candidate, report, model_id="door-detector", capability_kind=KIND,
        device=DEVICE, lineage=lineage, measured_latency_ms=41.0,
        measured_memory_mb=1400.0)
    pipeline.assigner.policy = PinnedVersion(promotion.reference)
    status = pipeline.submit(DEPLOYABLE, DEVICE, MissionRequirement("m", KIND),
                             lineage=lineage, actor="op", evidence_ref="ev")
    assert status.scope is PromotionScope.VERIFICATION

    widened = pipeline.widen(status.deployment_id, actor="op", evidence_ref="ev")
    assert widened.scope is not PromotionScope.VERIFICATION
    rolled = pipeline.rollback(status.deployment_id, actor="op", evidence_ref="ev",
                              reason="regression_seen")
    assert rolled.lineage_state is LearningState.ROLLED_BACK


def test_the_promotion_record_keeps_the_training_samples_and_base():
    """역추적의 재료. 어느 표본에서 어느 기준 위에 쌓인 것인가(AI-L-08)."""
    candidate, report = _passing()
    registrar = LearnedVersionRegistrar(_pipeline())
    promotion = registrar.promote_and_register(
        candidate, report, model_id="door-detector", capability_kind=KIND,
        device=DEVICE)
    assert promotion.sample_ids == candidate.sample_ids
    assert promotion.base_version == candidate.base_version
    assert "threshold" in promotion.produced_by
    assert registrar.record_of(promotion.reference) is promotion
    assert registrar.unverified_scopes()[promotion.reference] == \
        promotion.unverified_scope


def test_a_refused_promotion_is_never_registered():
    candidate, report = _passing()
    pipeline = _pipeline()
    registrar = LearnedVersionRegistrar(pipeline)
    refused = registrar.register(
        promote(candidate, report, model_id="d", capability_kind=KIND,
                device=DeviceProfile("drone")))
    assert not refused.promoted
    assert pipeline.assigner.versions == []
    assert registrar.promotions == {}


def test_the_registrar_accepts_an_assigner_as_well_as_a_pipeline():
    """구체 자료형을 요구하지 않는다 — `register_version` 이든 `register` 든 받는다."""
    from mission_runtime.runtime.model_assignment import ModelAssigner

    candidate, report = _passing()
    assigner = ModelAssigner()
    LearnedVersionRegistrar(assigner).promote_and_register(
        candidate, report, model_id="d", capability_kind=KIND, device=DEVICE)
    assert [v.version for v in assigner.versions] == [candidate.version]

    with pytest.raises(TypeError):
        LearnedVersionRegistrar(object()).register(
            promote(candidate, report, model_id="d", capability_kind=KIND,
                    device=DEVICE))


# --- 조달 (AI-C-16) / 무결성 (AI-B-02) ------------------------------------


def test_the_learned_parameters_are_procured_as_an_internal_asset():
    candidate, _ = _passing()
    asset = parameter_asset(candidate, model_id="door-detector")
    assert asset.kind == ASSET_KIND_PARAMETERS
    assert asset.version == candidate.version
    assert asset.asset_id.endswith("door-detector")


def test_the_deployment_request_reuses_the_content_derived_version_as_checksum():
    """같은 내용에 두 개의 신원을 만들지 않는다(AI-B-02)."""
    candidate, report = _passing()
    promotion = promote(candidate, report, model_id="door-detector",
                        capability_kind=KIND, device=DEVICE)
    request = deployment_request(promotion, deployment_id="dep-1",
                                artifact_ref="registry.internal:5000/params/1",
                                target_node_id="edge-1")
    assert request.checksum == candidate.version
    assert request.model_version == candidate.version


def test_a_refused_promotion_cannot_produce_a_deployment_request():
    candidate, report = _passing()
    refused = promote(candidate, report, model_id="d", capability_kind=KIND,
                      device=DeviceProfile("drone"))
    with pytest.raises(ValueError):
        deployment_request(refused, deployment_id="d", artifact_ref="x",
                           target_node_id="y")


# --- 실제 운영 스트림 모양에서 시작하는 한 줄기 ----------------------------


def _write_run(root, stream, rows) -> None:
    run_dir = root / stream / RUN
    (run_dir / "frames").mkdir(parents=True)
    (run_dir / "frames.jsonl").write_text("".join(
        json.dumps({"stream": stream, "n": n,
                    "frame_file": f"{stream}/{RUN}/frames/{n:09d}.jpg",
                    "received_at": "2026-10-14T12:00:00.190+09:00",
                    "sender": {}}) + "\n" for n, _ in rows), encoding="utf-8")
    model_dir = run_dir / "vision" / "yoloe"
    model_dir.mkdir(parents=True)
    (model_dir / "results.jsonl").write_text("".join(
        json.dumps({"stream": stream, "run": RUN, "model": "yoloe", "n": n,
                    "frame_file": f"frames/{n:09d}.jpg",
                    "width": 1920, "height": 1080, "prompt": "text",
                    "frame_ref": {"camera_id": f"{stream}-cam0"},
                    "producer": {"tier": "server"},
                    "timestamp": "2026-10-14T12:00:00.100+09:00",
                    "detections": [{"label": "door", "confidence": conf,
                                    "class_id": 0, "bbox": [1, 2, 3, 4]}]}) + "\n"
        for n, conf in rows), encoding="utf-8")


def test_real_stream_data_reaches_a_deployment_only_after_confirmation(tmp_path):
    """실제 하드웨어 자료가 들어왔을 때 학습 경로가 어디서 시작하는가.

    스트림이 쌓는 것은 **자동 추론 후보**뿐이다. 그것만으로는 학습이 돌지 않고,
    사용자 확인(AI-L-03)이 들어온 다음에야 임계가 움직인다. 그 순서를 고정한다 —
    순서가 뒤집히면 미검증 추론이 학습 정답이 된다(AI-L-02).
    """
    rows = [(n, 0.60 + n / 100) for n in range(1, 7)]
    _write_run(tmp_path, DEVICE_ID, rows)
    ingested = read_run(tmp_path / DEVICE_ID / RUN)
    assert len(ingested.samples) == 6
    assert not any(s.confirmed for s in ingested.samples)

    conditions = ingested.samples[0].conditions
    base = parameter_set_from_class_features(
        {"door": {"features": ["a photo of a door"], "target_sim_threshold": 0.50,
                  "shape_rationale": "손으로 적은 근거"}},
        conditions=conditions)
    learner = ContinualLearner(provider=ThresholdLearningProvider(
        min_samples=3, quantile=0.0, max_step=0.2))
    learner.bases[conditions.group_key] = base

    # 1) 확인 없이는 아무것도 나오지 않는다.
    learner.ingest_many(ingested.samples)
    assert not learner.train_group(conditions).produced

    # 2) 운영자 확인이 들어온 다음에야 후보 버전이 나온다.
    confirmed = tuple(
        StreamSample(sample_id=f"{s.sample_id}:confirmed", conditions=s.conditions,
                     label=s.label, feature=s.feature,
                     origin=CandidateOrigin.HUMAN_CONFIRMED, frame_ref=s.frame_ref,
                     confidence=s.confidence, similarity=s.similarity,
                     observed_at=s.observed_at)
        for s in ingested.samples)
    learner.ingest_many(confirmed[:-1])
    outcome = learner.train_group(conditions)
    assert outcome.produced
    candidate = outcome.parameters

    # 3) 검증 — 보류한 한 건으로 잰다. 미측정은 통과가 아니다.
    report = _evaluator().evaluate(candidate, new_samples=[confirmed[-1]],
                                   retained_samples=list(confirmed[:-1]), base=base)
    assert report.result is GateResult.PASS
    assert report.new.measured

    # 4) 승인 — 계보를 전진시키는 것은 운영자의 일이다.
    lineage = _approved(candidate.version, "lin-stream")

    # 5) 배정 후보로 등록되고, 6) 검증 범위에서 배치된다.
    pipeline = _pipeline()
    promotion = LearnedVersionRegistrar(pipeline).promote_and_register(
        candidate, report, model_id="door-detector", capability_kind=KIND,
        device=DEVICE, lineage=lineage)
    assert promotion.promoted
    assert promotion.version.verified_input_conditions == \
        frozenset({"resolution.1920x1080"})

    pipeline.assigner.policy = PinnedVersion(promotion.reference)
    status = pipeline.submit(
        DEPLOYABLE, DEVICE,
        # 지연을 재지 않았으므로 운영자가 그 사실을 명시적으로 받아들여야 한다.
        MissionRequirement("m", KIND, allow_unmeasured=True),
        lineage=lineage, actor="op", evidence_ref=candidate.version)
    assert status.phase is DeploymentPhase.PLACED
    assert status.scope is PromotionScope.VERIFICATION
    assert candidate.version in status.version_reference


def test_the_curated_parameter_file_shape_survives_the_round_trip():
    """사람이 손으로 조정한 근거 문장은 파라미터로 새지 않는다."""
    base = parameter_set_from_class_features(
        {"_meta": {"note": "머리말은 클래스가 아니다"},
         "door": {"features": ["a photo of a door"], "target_sim_threshold": 0.5,
                  "shape_gate": {"min_area": 100}, "shape_rationale": "근거 문장"}},
        conditions=CONDITIONS)
    assert base.labels() == ("door",)
    assert base.parameters["door"]["prompts"] == ["a photo of a door"]
    assert "shape_rationale" not in base.parameters["door"]["gates"]
    assert base.parameters["door"]["gates"]["shape_gate"] == {"min_area": 100}
