"""implements: AI-L-09, AI-L-05, AI-L-10
tests: per-device candidate grouping, unconfirmed data never trains, parameter
       versions derived from content, two-axis evaluation gate, assignment
       bounded by verified scope
"""

from __future__ import annotations

import pytest

from mission_runtime.continual.parameter_evaluation import (
    REASON_LABEL_LOST,
    REASON_NEW_BELOW_MIN,
    REASON_NO_EVALUATION_SET,
    REASON_REGRESSION_TOO_LARGE,
    Accuracy,
    EvaluationGate,
    GateResult,
    ParameterEvaluator,
    PrototypeScorer,
)
from mission_runtime.continual.stream_learning import (
    REASON_DIMENSION_MISMATCH,
    REASON_NO_CONFIRMED_SAMPLES,
    REASON_PROVIDER_FAILED,
    REASON_TOO_FEW_SAMPLES,
    CandidateBatch,
    CandidateOrigin,
    CandidateStore,
    ContinualLearner,
    InputConditions,
    ParameterSet,
    PrototypeLearningProvider,
    StreamSample,
    TrainingOutcome,
)
from mission_runtime.runtime.model_assignment import (
    REASON_ASSIGNED,
    REASON_LATENCY_ABOVE_BUDGET,
    REASON_MEMORY_ABOVE_DEVICE,
    REASON_NO_CANDIDATE,
    REASON_QUALITY_BELOW_REQUIREMENT,
    REASON_SCOPE_CONDITION,
    REASON_SCOPE_HARDWARE,
    REASON_UNMEASURED_NOT_ELIGIBLE,
    DeviceProfile,
    HighestQualityWithinBudget,
    LowestLatency,
    MissionRequirement,
    ModelAssigner,
    ModelVersion,
)

COND_A = InputConditions(device_id="dev-a", camera_id="dev-a_front",
                         resolution=(640, 480), accelerator_id="acc-npu-1")
COND_B = InputConditions(device_id="dev-b", camera_id="dev-b_front",
                         resolution=(1280, 720), accelerator_id="acc-cpu")


def _sample(sid, label, feature, *, conditions=COND_A, confirmed=True):
    return StreamSample(
        sample_id=sid, conditions=conditions, label=label, feature=tuple(feature),
        origin=(CandidateOrigin.HUMAN_CONFIRMED if confirmed
                else CandidateOrigin.AUTO_INFERENCE),
        frame_ref=f"frame:{sid}",
    )


def _door_samples(conditions=COND_A, n=4, confirmed=True, base=(1.0, 0.0, 0.0)):
    return [
        _sample(f"d{i}", "door", (base[0], base[1] + 0.01 * i, base[2]),
                conditions=conditions, confirmed=confirmed)
        for i in range(n)
    ]


# -- 후보 보관: 기기·입력 조건별 ---------------------------------------------


def test_candidates_are_grouped_by_device_and_input_conditions():
    """같은 라벨이라도 카메라·해상도·가속기가 다르면 다른 묶음이다(AI-L-09)."""
    store = CandidateStore()
    store.extend(_door_samples(COND_A) + _door_samples(COND_B))
    assert len(store.groups()) == 2
    assert store.batch_for(COND_A).conditions.device_id == "dev-a"
    assert store.batch_for(COND_B).conditions.resolution == (1280, 720)


def test_group_key_separates_the_same_device_on_a_different_accelerator():
    other = InputConditions(device_id="dev-a", camera_id="dev-a_front",
                            resolution=(640, 480), accelerator_id="acc-cpu")
    assert other.group_key != COND_A.group_key


def test_store_keeps_only_the_most_recent_samples_per_group():
    store = CandidateStore(per_group_limit=3)
    store.extend([_sample(f"s{i}", "door", (1.0, 0.0, 0.0)) for i in range(10)])
    ids = [s.sample_id for s in store.batch_for(COND_A).samples]
    assert ids == ["s7", "s8", "s9"]


def test_store_limit_must_be_positive():
    with pytest.raises(ValueError, match="per_group_limit"):
        CandidateStore(per_group_limit=0)


def test_unknown_group_lookup_raises():
    with pytest.raises(KeyError):
        CandidateStore().batch_for(COND_A)


def test_sample_requires_an_id_a_label_and_a_feature():
    for kw in ({"sample_id": ""}, {"label": ""}, {"feature": ()}):
        fields = {"sample_id": "s", "conditions": COND_A, "label": "door",
                  "feature": (1.0,), "origin": CandidateOrigin.HUMAN_CONFIRMED}
        fields.update(kw)
        with pytest.raises(ValueError):
            StreamSample(**fields)


def test_pixels_are_not_part_of_a_candidate():
    """픽셀은 담지 않는다 — 원본은 frame_ref 로 되짚는다."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(StreamSample)}
    for banned in ("image", "pixels", "frame_bytes", "crop", "jpeg"):
        assert banned not in names


# -- 확인되지 않은 데이터는 학습하지 않는다 ----------------------------------


def test_auto_inference_results_never_reach_training():
    """AI-L-02: 미검증 추론 결과를 확정 정답으로 승격하지 않는다."""
    store = CandidateStore()
    store.extend(_door_samples(confirmed=False, n=10))
    batch = store.batch_for(COND_A)
    assert batch.samples and batch.confirmed() == ()

    outcome = PrototypeLearningProvider().train(batch, base=None)
    assert not outcome.produced
    assert outcome.reason == REASON_NO_CONFIRMED_SAMPLES


def test_mixed_batch_trains_only_on_the_confirmed_part():
    store = CandidateStore()
    store.extend(_door_samples(n=4, confirmed=True))
    store.extend([_sample("x1", "window", (0.0, 1.0, 0.0), confirmed=False)])
    outcome = PrototypeLearningProvider(min_samples=1).train(
        store.batch_for(COND_A), base=None
    )
    assert outcome.produced
    assert outcome.parameters.labels() == ("door",)      # window 는 미확인이라 빠진다
    assert all(sid.startswith("d") for sid in outcome.used_sample_ids)


def test_confirmed_flag_covers_human_and_external_labels_only():
    assert _sample("a", "door", (1.0,)).confirmed is True
    assert StreamSample("b", COND_A, "door", (1.0,),
                        CandidateOrigin.EXTERNAL_LABEL).confirmed is True
    assert StreamSample("c", COND_A, "door", (1.0,),
                        CandidateOrigin.AUTO_INFERENCE).confirmed is False


# -- 학습: 프로토타입·임계 갱신 ----------------------------------------------


def test_training_produces_a_prototype_and_a_threshold_per_label():
    outcome = PrototypeLearningProvider(min_samples=2).train(
        CandidateBatch(COND_A, tuple(_door_samples(n=4))), base=None
    )
    assert outcome.produced
    door = outcome.parameters.parameters["door"]
    assert len(door["prototype"]) == 3
    assert 0.0 <= door["threshold"] <= 1.0
    assert door["sample_count"] == 4


def test_threshold_keeps_the_confirmed_samples_above_it():
    """임계가 평균이면 표본 절반이 떨어진다 — 하위 분위를 쓰는 이유다."""
    samples = _door_samples(n=5)
    outcome = PrototypeLearningProvider(min_samples=2, quantile=0.0).train(
        CandidateBatch(COND_A, tuple(samples)), base=None
    )
    scorer = PrototypeScorer()
    assert all(scorer.predict(outcome.parameters, s) == "door" for s in samples)


def test_too_few_confirmed_samples_does_not_produce_parameters():
    outcome = PrototypeLearningProvider(min_samples=5).train(
        CandidateBatch(COND_A, tuple(_door_samples(n=2))), base=None
    )
    assert not outcome.produced
    assert outcome.reason == REASON_TOO_FEW_SAMPLES


def test_feature_dimension_mismatch_is_refused():
    samples = (_sample("a", "door", (1.0, 0.0)), _sample("b", "door", (1.0, 0.0, 0.0)))
    outcome = PrototypeLearningProvider(min_samples=1).train(
        CandidateBatch(COND_A, samples), base=None
    )
    assert outcome.reason == REASON_DIMENSION_MISMATCH


def test_version_is_derived_from_content_so_the_same_input_gives_the_same_version():
    provider = PrototypeLearningProvider(min_samples=2)
    batch = CandidateBatch(COND_A, tuple(_door_samples(n=4)))
    first = provider.train(batch, base=None).parameters
    second = provider.train(batch, base=None).parameters
    assert first.version == second.version
    assert first.version.startswith("sha256-")


def test_different_conditions_give_a_different_version_for_the_same_features():
    provider = PrototypeLearningProvider(min_samples=2)
    a = provider.train(CandidateBatch(COND_A, tuple(_door_samples(COND_A, 4))),
                       base=None).parameters
    b = provider.train(CandidateBatch(COND_B, tuple(_door_samples(COND_B, 4))),
                       base=None).parameters
    assert a.version != b.version


def test_momentum_moves_the_prototype_toward_the_base_instead_of_replacing_it():
    provider = PrototypeLearningProvider(min_samples=2, momentum=0.5)
    base = ParameterSet(
        parameters={"door": {"prototype": [0.0, 1.0, 0.0], "threshold": 0.1}},
        conditions=COND_A,
    )
    outcome = provider.train(CandidateBatch(COND_A, tuple(_door_samples(n=4))), base=base)
    moved = outcome.parameters.parameters["door"]["prototype"]
    assert 0.0 < moved[0] < 1.0          # 기준과 새 평균 사이
    assert outcome.parameters.base_version == base.version


def test_provider_parameters_are_validated():
    for kw in ({"min_samples": 0}, {"quantile": 1.5}, {"momentum": 1.0}):
        with pytest.raises(ValueError):
            PrototypeLearningProvider(**kw)


# -- 루프와 격리 -------------------------------------------------------------


def test_learner_trains_each_group_separately():
    learner = ContinualLearner(provider=PrototypeLearningProvider(min_samples=2))
    learner.ingest_many(_door_samples(COND_A, 4) + _door_samples(COND_B, 4))
    outcomes = learner.train_all()
    assert len(outcomes) == 2
    assert all(o.produced for o in outcomes.values())
    versions = {o.parameters.version for o in outcomes.values()}
    assert len(versions) == 2


def test_a_failing_provider_returns_a_reason_instead_of_breaking_the_caller():
    """학습 장애가 운영 추론을 멈추지 않는다(AI-L-09)."""

    class Exploding:
        name = "exploding"

        def train(self, batch, *, base):
            raise RuntimeError("out of memory")

    learner = ContinualLearner(provider=Exploding())
    learner.ingest_many(_door_samples(n=4))
    outcome = learner.train_group(COND_A)
    assert not outcome.produced
    assert outcome.reason.startswith(REASON_PROVIDER_FAILED)


def test_learner_has_no_way_to_apply_a_parameter_set_to_production():
    """적용은 검증·승인·단계적 적용을 거친다 — 이 클래스가 그 경계를 넘지 않는다."""
    names = [n for n in dir(ContinualLearner) if not n.startswith("_")]
    for banned in ("deploy", "activate", "apply", "publish", "rollout"):
        assert not any(banned in n for n in names), f"control surface leaked: {banned}"
    assert "adopt" in names      # 다음 학습의 기준을 바꾸는 것은 적용이 아니다


def test_adopting_an_empty_outcome_is_refused():
    learner = ContinualLearner(provider=PrototypeLearningProvider())
    with pytest.raises(ValueError, match="cannot become the base"):
        learner.adopt(TrainingOutcome(None, REASON_NO_CONFIRMED_SAMPLES))


def test_adopt_makes_the_next_round_build_on_that_version():
    learner = ContinualLearner(provider=PrototypeLearningProvider(min_samples=2))
    learner.ingest_many(_door_samples(n=4))
    first = learner.train_group(COND_A)
    learner.adopt(first)
    assert learner.base_version(COND_A) == first.parameters.version
    second = learner.train_group(COND_A)
    assert second.parameters.base_version == first.parameters.version


# -- 검증 게이트: 두 축 ------------------------------------------------------


def _params(labels, *, conditions=COND_A):
    return ParameterSet(
        parameters={
            label: {"prototype": list(vector), "threshold": 0.5}
            for label, vector in labels.items()
        },
        conditions=conditions,
    )


DOOR = (1.0, 0.0, 0.0)
WINDOW = (0.0, 1.0, 0.0)


def test_gate_passes_when_new_is_good_and_nothing_regressed():
    candidate = _params({"door": DOOR, "window": WINDOW})
    base = _params({"door": DOOR, "window": WINDOW})
    report = ParameterEvaluator().evaluate(
        candidate,
        new_samples=[_sample("n1", "door", DOOR), _sample("n2", "window", WINDOW)],
        retained_samples=[_sample("r1", "door", DOOR)],
        base=base,
    )
    assert report.result is GateResult.PASS
    assert report.new.ratio == 1.0
    assert report.regression == 0.0


def test_gate_fails_when_the_new_set_is_below_the_minimum():
    candidate = _params({"door": DOOR})
    report = ParameterEvaluator().evaluate(
        candidate,
        new_samples=[_sample("n1", "window", WINDOW)],   # 분류 못 한다
        retained_samples=[],
        gate=EvaluationGate(min_new_accuracy=0.7),
    )
    assert report.result is GateResult.FAIL
    assert report.reason == REASON_NEW_BELOW_MIN


def test_gate_fails_on_regression_even_when_the_new_set_improved():
    """한 수치로 합치면 이런 후보가 통과한다 — 그래서 두 축을 따로 본다."""
    candidate = _params({"door": DOOR})                  # window 를 잃었다
    base = _params({"door": DOOR, "window": WINDOW})
    report = ParameterEvaluator().evaluate(
        candidate,
        new_samples=[_sample("n1", "door", DOOR)],
        retained_samples=[_sample("r1", "window", WINDOW)],
        base=base,
        gate=EvaluationGate(forbid_label_loss=False, max_regression=0.0),
    )
    assert report.result is GateResult.FAIL
    assert report.reason == REASON_REGRESSION_TOO_LARGE
    assert report.regression == 1.0


def test_gate_fails_when_a_previously_known_label_disappears():
    candidate = _params({"door": DOOR})
    base = _params({"door": DOOR, "window": WINDOW})
    report = ParameterEvaluator().evaluate(
        candidate,
        new_samples=[_sample("n1", "door", DOOR)],
        retained_samples=[_sample("r1", "door", DOOR)],
        base=base,
    )
    assert report.result is GateResult.FAIL
    assert report.reason == REASON_LABEL_LOST
    assert report.lost_labels == ("window",)


def test_an_unmeasured_candidate_is_not_a_pass():
    """측정이 없는데 통과시키면 게이트가 아무것도 막지 못한다."""
    report = ParameterEvaluator().evaluate(
        _params({"door": DOOR}), new_samples=[], retained_samples=[],
    )
    assert report.result is GateResult.NOT_MEASURED
    assert report.reason == REASON_NO_EVALUATION_SET
    assert report.new.measured is False
    assert report.new.ratio is None


def test_regression_is_none_when_either_side_was_not_measured():
    report = ParameterEvaluator().evaluate(
        _params({"door": DOOR}),
        new_samples=[_sample("n1", "door", DOOR)],
        retained_samples=[],            # 기존 집합이 없다
        base=_params({"door": DOOR}),
    )
    assert report.regression is None
    assert report.result is GateResult.PASS      # 새 축은 쟀고 회귀는 쟬 수 없었다


def test_accuracy_keeps_the_sample_count_not_just_the_ratio():
    assert Accuracy(3, 4).ratio == 0.75
    assert Accuracy(0, 0).ratio is None


def test_scorer_returns_none_instead_of_forcing_the_nearest_label():
    """임계를 넘는 것이 없으면 기존 클래스에 강제 매핑하지 않는다(AI-S-04)."""
    params = _params({"door": DOOR})
    far = _sample("x", "door", (0.0, 0.0, 1.0))
    assert PrototypeScorer().predict(params, far) is None


def test_gate_bounds_are_validated():
    for kw in ({"min_new_accuracy": 1.5}, {"max_regression": -0.1}):
        with pytest.raises(ValueError):
            EvaluationGate(**kw)


# -- 모델 배정 (AI-L-10) -----------------------------------------------------


EDGE = DeviceProfile(device_id="dev-a", hw_tags=frozenset({"compute.npu", "arch.arm64"}),
                     input_conditions=frozenset({"res.640x480"}), memory_mb=1024.0)


def _version(version, **kw):
    base = dict(model_id="detector", version=version, capability_kind="perception.detect",
                verified_hw_tags=frozenset({"compute.npu"}),
                verified_input_conditions=frozenset({"res.640x480"}),
                quality=0.8, latency_ms=30.0, memory_mb=256.0)
    base.update(kw)
    return ModelVersion(**base)


def _assigner(*versions):
    a = ModelAssigner()
    for v in versions:
        a.register(v)
    return a


def test_assignment_picks_the_best_eligible_version_and_says_why():
    assigner = _assigner(_version("1.0", quality=0.75), _version("1.1", quality=0.9))
    result = assigner.assign(EDGE, MissionRequirement("m-1", "perception.detect"))
    assert result.assigned.version == "1.1"
    assert result.reason == REASON_ASSIGNED
    assert ("detector@1.0", REASON_ASSIGNED) in [(r.version_reference, r.reason)
                                                 for r in result.rejected]


def test_a_version_verified_elsewhere_is_not_eligible_here():
    """AI-B-01: 다른 조합에서 잰 성능을 같다고 가정하지 않는다."""
    assigner = _assigner(_version("2.0", verified_hw_tags=frozenset({"compute.gpu"}),
                                  quality=0.99))
    result = assigner.assign(EDGE, MissionRequirement("m-1", "perception.detect"))
    assert result.assigned is None
    assert result.reason == REASON_NO_CANDIDATE
    assert result.rejected[0].reason == REASON_SCOPE_HARDWARE


def test_a_version_verified_for_other_input_conditions_is_not_eligible():
    assigner = _assigner(_version("2.0",
                                  verified_input_conditions=frozenset({"res.1280x720"})))
    result = assigner.assign(EDGE, MissionRequirement("m-1", "perception.detect"))
    assert result.rejected[0].reason == REASON_SCOPE_CONDITION


def test_an_unmeasured_version_is_not_eligible_by_default():
    assigner = _assigner(_version("2.0", latency_ms=None))
    result = assigner.assign(EDGE, MissionRequirement("m-1", "perception.detect"))
    assert result.rejected[0].reason == REASON_UNMEASURED_NOT_ELIGIBLE
    allowed = assigner.assign(
        EDGE, MissionRequirement("m-1", "perception.detect", allow_unmeasured=True)
    )
    assert allowed.is_assigned


def test_mission_quality_and_latency_requirements_filter_candidates():
    assigner = _assigner(_version("1.0", quality=0.6, latency_ms=10.0),
                         _version("1.1", quality=0.95, latency_ms=90.0))
    strict_quality = assigner.assign(
        EDGE, MissionRequirement("m-1", "perception.detect", min_quality=0.9)
    )
    assert strict_quality.assigned.version == "1.1"
    assert any(r.reason == REASON_QUALITY_BELOW_REQUIREMENT
               for r in strict_quality.rejected)

    strict_latency = assigner.assign(
        EDGE, MissionRequirement("m-1", "perception.detect", max_latency_ms=20.0)
    )
    assert strict_latency.assigned.version == "1.0"
    assert any(r.reason == REASON_LATENCY_ABOVE_BUDGET
               for r in strict_latency.rejected)


def test_a_version_larger_than_the_device_memory_is_refused():
    assigner = _assigner(_version("1.0", memory_mb=4096.0))
    result = assigner.assign(EDGE, MissionRequirement("m-1", "perception.detect"))
    assert result.rejected[0].reason == REASON_MEMORY_ABOVE_DEVICE


def test_the_same_device_gets_a_different_version_for_a_different_mission():
    """같은 장치라도 임무가 바뀌면 배정이 바뀐다."""
    assigner = _assigner(_version("fast", quality=0.7, latency_ms=8.0),
                         _version("accurate", quality=0.95, latency_ms=70.0))
    safety = assigner.assign(
        EDGE, MissionRequirement("m-safety", "perception.detect", max_latency_ms=10.0)
    )
    survey = assigner.assign(
        EDGE, MissionRequirement("m-survey", "perception.detect", min_quality=0.9)
    )
    assert safety.assigned.version == "fast"
    assert survey.assigned.version == "accurate"


def test_policy_is_replaceable_and_deterministic():
    versions = (_version("a", quality=0.9, latency_ms=50.0),
                _version("b", quality=0.9, latency_ms=20.0))
    quality_first = ModelAssigner(policy=HighestQualityWithinBudget())
    latency_first = ModelAssigner(policy=LowestLatency())
    for v in versions:
        quality_first.register(v)
        latency_first.register(v)
    requirement = MissionRequirement("m-1", "perception.detect")
    assert quality_first.assign(EDGE, requirement).assigned.version == "b"   # 동률 → 지연
    assert latency_first.assign(EDGE, requirement).assigned.version == "b"
    # 같은 입력이면 항상 같은 결과다.
    assert (quality_first.assign(EDGE, requirement).assigned.reference
            == quality_first.assign(EDGE, requirement).assigned.reference)


def test_reassignment_covers_every_device():
    assigner = _assigner(_version("1.0"))
    other = DeviceProfile(device_id="dev-b", hw_tags=frozenset({"compute.cpu"}))
    results = assigner.reassign_all(
        [EDGE, other], MissionRequirement("m-1", "perception.detect")
    )
    assert results["dev-a"].is_assigned
    assert results["dev-b"].reason == REASON_NO_CANDIDATE


def test_registering_the_same_reference_replaces_it():
    assigner = _assigner(_version("1.0", quality=0.5))
    assigner.register(_version("1.0", quality=0.9))
    assert len(assigner.versions) == 1
    assert assigner.versions[0].quality == 0.9


def test_assignment_modules_name_no_vendor_or_model_product():
    import io
    import tokenize
    from pathlib import Path

    import mission_runtime.runtime.model_assignment as assign_mod
    import mission_runtime.continual.stream_learning as learn_mod

    banned = ("yolo", "clip", "dinov2", "nvidia", "cuda", "coral", "mobilint", "deepx")
    for mod in (assign_mod, learn_mod):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        leaked = []
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING,
                              tokenize.NL, tokenize.NEWLINE):
                continue
            low = token.string.lower()
            leaked += [(n, token.start[0]) for n in banned if n in low]
        assert not leaked, f"{mod.__name__}: {leaked}"


# -- 확인된 음성 (2026-11-04) -------------------------------------------------
# 문헌 조사(docs/research/hitl-data-and-weight-management.md §9.3)가 짚은 공백의
# 양면을 고친 자리다. 사람이 "여기 아무것도 없다" 로 지운 상자가 **양성 후보**로
# 들어오고 있었고, 동시에 임계를 교정할 음성은 없다고 적혀 있었다 — 같은 자료가
# 틀린 문으로 들어온 것이었다.

def _polarity_conditions():
    from mission_runtime.continual.stream_learning import InputConditions

    return InputConditions(device_id="pi4", camera_id="pi4_front", resolution="464x400")


def _polar_sample(sample_id, label, feature, *, negative=False):
    from mission_runtime.continual.stream_learning import (
        CandidateOrigin,
        SamplePolarity,
        StreamSample,
    )

    return StreamSample(
        sample_id=sample_id, conditions=_polarity_conditions(), label=label, feature=feature,
        origin=CandidateOrigin.HUMAN_CONFIRMED,
        polarity=SamplePolarity.NEGATIVE if negative else SamplePolarity.POSITIVE)


def test_a_confirmed_negative_never_becomes_a_class_of_its_own():
    """**재현된 결함이다.** 음성 세 건이 임계 0.0 짜리 클래스를 만들었다.

    `(0,0,0,0)` 특징의 코사인 유사도는 0.0 이고, 그 분위도 0.0 이라 그 클래스는
    **무엇이든 받아들인다.** 사람이 "아무것도 없다" 를 세 번 말한 것만으로
    분류기가 전부 통과시키는 문을 얻었다.
    """
    from mission_runtime.continual.stream_learning import (
        CandidateBatch,
        PrototypeLearningProvider,
    )

    batch = CandidateBatch(_polarity_conditions(), tuple(
        [_polar_sample(f"p{i}", "chair", (10.0, 20.0, 50.0, 80.0 + i)) for i in range(3)]
        + [_polar_sample(f"n{i}", "chair", (0.0, 0.0, 0.0, 0.0), negative=True)
           for i in range(3)]))

    outcome = PrototypeLearningProvider(min_samples=3).train(batch, base=None)

    assert outcome.parameters is not None
    assert "absent" not in outcome.parameters.parameters
    assert set(outcome.parameters.parameters) == {"chair"}
    assert all(body["threshold"] > 0.0
               for body in outcome.parameters.parameters.values()), (
        "임계 0.0 은 모든 것을 받아들인다")


def test_a_negative_does_not_enter_the_prototype_average():
    """음성을 섞으면 "그 라벨이 아니다" 로 확인된 표본이 그 라벨의 평균이 된다."""
    from mission_runtime.continual.stream_learning import (
        CandidateBatch,
        PrototypeLearningProvider,
    )

    positives = [_polar_sample(f"p{i}", "chair", (10.0, 10.0, 10.0, 10.0)) for i in range(3)]
    far_away = [_polar_sample("n0", "chair", (900.0, 900.0, 900.0, 900.0), negative=True)]

    without = PrototypeLearningProvider(min_samples=3).train(
        CandidateBatch(_polarity_conditions(), tuple(positives)), base=None)
    with_negative = PrototypeLearningProvider(min_samples=3).train(
        CandidateBatch(_polarity_conditions(), tuple(positives + far_away)), base=None)

    assert (without.parameters.parameters["chair"]["prototype"]
            == with_negative.parameters.parameters["chair"]["prototype"])


def test_a_confirmed_negative_calibrates_the_threshold_instead_of_being_discarded():
    """버리면 임계를 교정할 자료가 사라진다 — `ConfirmedAcceptanceScorer` 가
    docstring 에 "확인된 음성 표본이 먼저 있어야 한다" 고 적어 둔 그 자료다."""
    from mission_runtime.continual.stream_learning import (
        CandidateBatch,
        PrototypeLearningProvider,
    )

    batch = CandidateBatch(_polarity_conditions(), tuple(
        [_polar_sample(f"p{i}", "chair", (10.0, 20.0, 50.0, 80.0 + i)) for i in range(3)]
        + [_polar_sample("n0", "chair", (300.0, 10.0, 320.0, 30.0), negative=True),
           _polar_sample("n1", "chair", (280.0, 12.0, 300.0, 34.0), negative=True)]))

    body = PrototypeLearningProvider(min_samples=3).train(
        batch, base=None).parameters.parameters["chair"]

    assert body["negative_sample_count"] == 2
    assert body["threshold_separates_negatives"] is True
    assert body["negative_max_similarity"] < body["threshold"]


def test_a_negative_inside_the_threshold_is_reported_rather_than_hidden():
    """음성이 양성 임계 안에 들어오면 **그 특징 공간에서는 둘이 갈리지 않는다.**

    임계를 올려 밀어내면 양성까지 잘린다. 그래서 올리지 않고 그 사실을 적는다 —
    숨기면 임계가 괜찮은 척한다.
    """
    from mission_runtime.continual.stream_learning import (
        CandidateBatch,
        PrototypeLearningProvider,
    )

    # 음성이 양성과 거의 같은 방향이다(코사인이라 크기는 보지 않는다).
    batch = CandidateBatch(_polarity_conditions(), tuple(
        [_polar_sample(f"p{i}", "chair", (10.0, 20.0, 30.0, 40.0 + i * 0.01)) for i in range(3)]
        + [_polar_sample("n0", "chair", (20.0, 40.0, 60.0, 80.0), negative=True)]))

    body = PrototypeLearningProvider(min_samples=3).train(
        batch, base=None).parameters.parameters["chair"]

    assert body["threshold_separates_negatives"] is False
    assert body["negative_sample_count"] == 1


def test_the_batch_separates_the_two_kinds_without_losing_either():
    from mission_runtime.continual.stream_learning import CandidateBatch

    batch = CandidateBatch(_polarity_conditions(), (
        _polar_sample("p0", "chair", (1.0, 1.0)),
        _polar_sample("n0", "chair", (2.0, 2.0), negative=True)))

    assert len(batch.confirmed()) == 2, "음성도 확인된 표본이다"
    assert [s.sample_id for s in batch.confirmed_positives()] == ["p0"]
    assert [s.sample_id for s in batch.confirmed_negatives()] == ["n0"]


def test_an_existing_sample_without_a_declared_polarity_is_positive():
    """기존 호출 경로가 그대로 돌아야 한다 — 기본값이 양성이다."""
    from mission_runtime.continual.stream_learning import SamplePolarity

    assert _polar_sample("p0", "chair", (1.0,)).polarity is SamplePolarity.POSITIVE
