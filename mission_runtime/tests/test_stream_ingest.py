"""implements: AI-L-09
tests: the two mandatory protocol rules (duplicate frames discard the whole scan,
       rotation_deg is the only direction source), curated parameters loaded as
       the baseline, threshold adaptation bounded and floored
"""

from __future__ import annotations

import pytest

from mission_runtime.continual.stream_ingest import (
    GATES_KEY,
    OUTCOME_SUCCEEDED,
    PROMPTS_KEY,
    REASON_DUPLICATE_FRAME,
    REASON_DUPLICATE_ROTATION,
    REASON_INCOMPLETE,
    REASON_NOT_SUCCEEDED,
    REASON_REPEATED_DIGEST,
    THRESHOLD_KEY,
    CandidateOrigin,
    FrameEnvelope,
    FrameObservation,
    ScanAssembler,
    ScanOutcome,
    ThresholdLearningProvider,
    candidates_from_scan,
    parameter_set_from_class_features,
)
from mission_runtime.continual.stream_learning import (
    REASON_NO_CONFIRMED_SAMPLES,
    REASON_TOO_FEW_SAMPLES,
    CandidateBatch,
    InputConditions,
    StreamSample,
)

SCAN = "scan-0001"


def _frames(n=8, *, duplicate_at=None, digests=None, rotations=None):
    out = []
    for i in range(n):
        out.append(FrameEnvelope(
            device_id="go1-001", camera_id="go1-001_front", scan_id=SCAN,
            shot_index=i,
            rotation_deg=(rotations[i] if rotations else i * 45.0),
            digest=(digests[i] if digests else f"sha1-{i:02d}"),
            duplicate_of_prev=(i == duplicate_at),
            resolution=(640, 480), accelerator_id="acc-npu-1", received_at=100.0 + i,
        ))
    return out


def _closed(frames, *, outcome=OUTCOME_SUCCEEDED, expected=None, sent=None):
    assembler = ScanAssembler()
    assembler.add_frames(frames)
    return assembler.close(ScanOutcome(
        scan_id=SCAN, outcome=outcome,
        expected_frames=expected if expected is not None else len(frames),
        frames_sent=sent if sent is not None else len(frames),
    ))


# -- 규약 규칙 1: 중복 프레임이 있으면 판 전체를 버린다 ----------------------


def test_a_single_duplicate_frame_discards_the_whole_scan():
    """한 장만 빼면 남은 프레임의 방향 짝이 어긋난 채로 남는다."""
    verdict = _closed(_frames(duplicate_at=3))
    assert verdict.accepted is False
    assert verdict.reason == REASON_DUPLICATE_FRAME


def test_a_repeated_digest_is_caught_even_without_the_flag():
    """로봇은 직전 한 장과만 견주므로 건너뛴 중복은 우리가 잡는다."""
    digests = [f"sha1-{i:02d}" for i in range(8)]
    digests[5] = digests[1]            # 건너뛴 중복
    verdict = _closed(_frames(digests=digests))
    assert verdict.accepted is False
    assert verdict.reason == REASON_REPEATED_DIGEST


def test_a_discarded_scan_produces_no_candidates_at_all():
    verdict = _closed(_frames(duplicate_at=0))
    observations = [
        FrameObservation(f, "door", CandidateOrigin.HUMAN_CONFIRMED, similarity=0.4)
        for f in _frames()
    ]
    assert candidates_from_scan(verdict, observations) == ()


def test_a_clean_scan_is_accepted():
    verdict = _closed(_frames())
    assert verdict.accepted is True
    assert verdict.reason is None
    assert len(verdict.frames) == 8


# -- 규약 규칙 2: 방향은 rotation_deg 로만 정한다 ----------------------------


def test_yaw_is_not_read_anywhere_in_the_module():
    """판마다 기준점이 옮겨지므로 yaw 로 방향을 정하면 안 된다.

    docstring 은 그 금지를 설명하려고 그 이름을 인용해야 하므로 **코드 토큰만** 본다.
    """
    import io
    import tokenize
    from pathlib import Path

    import mission_runtime.continual.stream_ingest as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    leaked = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
            continue
        if "yaw" in token.string.lower():
            leaked.append((token.string, token.start[0]))
    assert not leaked, f"yaw leaked into code: {leaked}"


def test_rotation_is_part_of_the_input_conditions():
    frame = _frames(1)[0]
    assert ("rotation_deg", "0") in frame.conditions.extra


def test_two_frames_claiming_the_same_direction_discard_the_scan():
    rotations = [i * 45.0 for i in range(8)]
    rotations[4] = rotations[2]
    verdict = _closed(_frames(rotations=rotations))
    assert verdict.reason == REASON_DUPLICATE_ROTATION


# -- 판 경계 ----------------------------------------------------------------


def test_an_aborted_scan_is_not_used():
    verdict = _closed(_frames(5), outcome="ABORTED", expected=8, sent=5)
    assert verdict.reason == REASON_NOT_SUCCEEDED


def test_a_scan_with_missing_frames_is_not_used():
    """규약: frames_sent 와 expected_frames 를 견주라고 적혀 있다."""
    verdict = _closed(_frames(6), expected=8, sent=6)
    assert verdict.reason == REASON_INCOMPLETE


def test_closing_an_unknown_scan_yields_an_empty_incomplete_verdict():
    verdict = ScanAssembler().close(ScanOutcome(SCAN, OUTCOME_SUCCEEDED, 8, 8))
    assert verdict.accepted is False
    assert verdict.frames == ()


def test_frames_are_ordered_by_shot_index_regardless_of_arrival_order():
    frames = _frames()
    assembler = ScanAssembler()
    assembler.add_frames(list(reversed(frames)))
    verdict = assembler.close(ScanOutcome(SCAN, OUTCOME_SUCCEEDED, 8, 8))
    assert [f.shot_index for f in verdict.frames] == list(range(8))


def test_envelope_validates_its_identifiers():
    with pytest.raises(ValueError, match="must not be empty"):
        FrameEnvelope(device_id="", camera_id="c", scan_id="s", shot_index=0,
                      rotation_deg=0.0)
    with pytest.raises(ValueError, match="shot_index"):
        FrameEnvelope(device_id="d", camera_id="c", scan_id="s", shot_index=-1,
                      rotation_deg=0.0)


# -- 후보 생성 ---------------------------------------------------------------


def test_candidates_carry_the_frame_reference_and_no_pixels():
    verdict = _closed(_frames())
    observations = [
        FrameObservation(f, "door", CandidateOrigin.HUMAN_CONFIRMED, similarity=0.4)
        for f in verdict.frames
    ]
    samples = candidates_from_scan(verdict, observations)
    assert len(samples) == 8
    assert all(s.frame_ref.startswith("go1-001_front#scan-0001:") for s in samples)
    assert all(s.similarity == 0.4 for s in samples)
    assert all(isinstance(s, StreamSample) for s in samples)


def test_observations_from_frames_outside_the_scan_are_ignored():
    verdict = _closed(_frames())
    stranger = FrameEnvelope(device_id="go1-001", camera_id="go1-001_front",
                             scan_id="other-scan", shot_index=0, rotation_deg=0.0)
    samples = candidates_from_scan(
        verdict,
        [FrameObservation(stranger, "door", CandidateOrigin.HUMAN_CONFIRMED,
                          similarity=0.4)],
    )
    assert samples == ()


def test_candidate_conditions_separate_devices_and_directions():
    verdict = _closed(_frames())
    samples = candidates_from_scan(
        verdict,
        [FrameObservation(f, "door", CandidateOrigin.HUMAN_CONFIRMED, similarity=0.3)
         for f in verdict.frames],
    )
    groups = {s.conditions.group_key for s in samples}
    assert len(groups) == 8          # 방향마다 다른 조건 묶음이다


# -- 데모의 조정된 파라미터를 기준으로 받아들인다 ---------------------------


CURATED = {
    "_meta": {"purpose": "클래스별 참조 특징", "model": "clip-vit-base-patch32"},
    "door": {
        "features": ["handle", "door frame", "rectangular panel", "hinge"],
        "target_sim_threshold": 0.25,
        "target_sim_threshold_rationale": "260914 sweep 결과",
        "min_aspect_ratio_h_over_w": 1.4,
        "shape_gate": {"positive_prompts": ["a door"], "tolerance": 0.05},
        "saturation_gate": {"min_saturation": 30},
    },
    "pedestal": {
        "features": ["pedestal", "stand", "column", "base"],
        "target_sim_threshold": 0.3,
        "min_aspect_ratio_h_over_w": 1.1,
    },
}

COND = InputConditions(device_id="go1-001", camera_id="go1-001_front",
                       resolution=(640, 480), accelerator_id="acc-npu-1")


def test_curated_prompts_are_kept_as_prompts_not_turned_into_vectors():
    """그 파일의 `features` 는 텍스트 프롬프트다 — 벡터인 척 바꾸지 않는다."""
    params = parameter_set_from_class_features(CURATED, conditions=COND)
    door = params.parameters["door"]
    assert door[PROMPTS_KEY] == ["handle", "door frame", "rectangular panel", "hinge"]
    assert door[THRESHOLD_KEY] == 0.25
    assert params.labels() == ("door", "pedestal")


def test_gates_are_preserved_whole_without_being_interpreted():
    params = parameter_set_from_class_features(CURATED, conditions=COND)
    gates = params.parameters["door"][GATES_KEY]
    assert gates["min_aspect_ratio_h_over_w"] == 1.4
    assert gates["shape_gate"]["min_saturation" if False else "tolerance"] == 0.05
    assert gates["saturation_gate"]["min_saturation"] == 30


def test_rationale_text_is_not_carried_into_the_parameters():
    """근거 문장은 사람이 읽는 것이고 파라미터가 아니다."""
    params = parameter_set_from_class_features(CURATED, conditions=COND)
    assert not any("rationale" in key
                   for key in params.parameters["door"][GATES_KEY])


def test_meta_header_is_not_treated_as_a_class():
    params = parameter_set_from_class_features(CURATED, conditions=COND)
    assert "_meta" not in params.parameters


def test_a_file_without_class_entries_is_rejected():
    with pytest.raises(ValueError, match="no class entries"):
        parameter_set_from_class_features({"_meta": {}}, conditions=COND)


def test_the_curated_set_has_a_content_derived_version():
    a = parameter_set_from_class_features(CURATED, conditions=COND)
    b = parameter_set_from_class_features(CURATED, conditions=COND)
    assert a.version == b.version and a.version.startswith("sha256-")


# -- 임계 조정 ---------------------------------------------------------------


def _samples(label, scores, *, confirmed=True):
    return tuple(
        StreamSample(
            sample_id=f"{label}-{i}", conditions=COND, label=label,
            feature=(score,),
            origin=(CandidateOrigin.HUMAN_CONFIRMED if confirmed
                    else CandidateOrigin.AUTO_INFERENCE),
            similarity=score,
        )
        for i, score in enumerate(scores)
    )


def test_threshold_moves_toward_the_confirmed_distribution():
    base = parameter_set_from_class_features(CURATED, conditions=COND)
    provider = ThresholdLearningProvider(min_samples=3, quantile=0.0, max_step=0.05)
    outcome = provider.train(
        CandidateBatch(COND, _samples("door", [0.40, 0.42, 0.45, 0.50])), base=base
    )
    assert outcome.produced
    moved = outcome.parameters.parameters["door"][THRESHOLD_KEY]
    assert moved == pytest.approx(0.30)        # 0.25 에서 한 걸음(0.05)만
    assert outcome.parameters.base_version == base.version


def test_a_single_batch_cannot_flip_the_threshold():
    """한 묶음이 임계를 뒤집으면 운영이 흔들린다 — 한 걸음 제한이 그 이유다."""
    base = parameter_set_from_class_features(CURATED, conditions=COND)
    provider = ThresholdLearningProvider(min_samples=3, quantile=0.0, max_step=0.02)
    outcome = provider.train(
        CandidateBatch(COND, _samples("door", [0.9, 0.92, 0.95])), base=base
    )
    assert outcome.parameters.parameters["door"][THRESHOLD_KEY] == pytest.approx(0.27)


def test_threshold_never_falls_below_the_floor():
    """임계가 끝없이 내려가면 아무것도 걸러내지 못한다."""
    base = parameter_set_from_class_features(CURATED, conditions=COND)
    provider = ThresholdLearningProvider(min_samples=3, quantile=0.0, floor=0.2,
                                         max_step=1.0)
    outcome = provider.train(
        CandidateBatch(COND, _samples("door", [0.01, 0.02, 0.03])), base=base
    )
    assert outcome.parameters.parameters["door"][THRESHOLD_KEY] == 0.2


def test_prompts_are_never_changed_by_adaptation():
    """프롬프트 변경은 사람이 근거를 적어 바꾸는 일이다."""
    base = parameter_set_from_class_features(CURATED, conditions=COND)
    outcome = ThresholdLearningProvider(min_samples=3, quantile=0.0).train(
        CandidateBatch(COND, _samples("door", [0.4, 0.5, 0.6])), base=base
    )
    assert (outcome.parameters.parameters["door"][PROMPTS_KEY]
            == base.parameters["door"][PROMPTS_KEY])


def test_unconfirmed_similarities_do_not_move_the_threshold():
    base = parameter_set_from_class_features(CURATED, conditions=COND)
    outcome = ThresholdLearningProvider(min_samples=3).train(
        CandidateBatch(COND, _samples("door", [0.9, 0.9, 0.9], confirmed=False)),
        base=base,
    )
    assert not outcome.produced
    assert outcome.reason == REASON_NO_CONFIRMED_SAMPLES


def test_too_few_samples_leaves_the_threshold_alone():
    base = parameter_set_from_class_features(CURATED, conditions=COND)
    outcome = ThresholdLearningProvider(min_samples=10).train(
        CandidateBatch(COND, _samples("door", [0.4, 0.5])), base=base
    )
    assert outcome.reason == REASON_TOO_FEW_SAMPLES


def test_a_label_absent_from_the_base_is_not_added_by_adaptation():
    """임계 조정은 조정일 뿐이다 — 새 클래스를 만들지 않는다."""
    base = parameter_set_from_class_features(CURATED, conditions=COND)
    outcome = ThresholdLearningProvider(min_samples=1, quantile=0.0).train(
        CandidateBatch(COND, _samples("window", [0.5, 0.6])), base=base
    )
    assert not outcome.produced


def test_adaptation_requires_a_base():
    with pytest.raises(ValueError, match="needs the current parameters"):
        ThresholdLearningProvider().train(
            CandidateBatch(COND, _samples("door", [0.4])), base=None
        )


def test_provider_arguments_are_validated():
    for kw in ({"min_samples": 0}, {"quantile": 2.0}, {"floor": -1.0}, {"max_step": 0.0}):
        with pytest.raises(ValueError):
            ThresholdLearningProvider(**kw)
