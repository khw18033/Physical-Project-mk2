"""운영자가 그림에 모델을 돌려 보고 고르는 경로 — **그 시도가 말할 수 있는 것까지만.**

이 묶음이 막는 셋.

1. **시도는 측정이 아니다.** 그림 몇 장의 지연은 표본 몇 개이고 실행 프로파일의
   지연이 아니다. 그것이 프로파일로 들어가면 AI-B-01 의 재측정 구조가 무너진다.
2. **정답이 없으면 우열을 말할 수 없다.** 한쪽이 10개, 다른 쪽이 6개를 찾았을 때
   사람은 10개를 "더 잘 찾는다" 로 읽는다. 그 10개에 거짓 양성이 섞여 있어도
   정답 없는 프레임에서는 알 수 없다. 그래서 설명과 채점을 다른 종류로 둔다.
3. **다른 그림에서 나온 수를 견주지 않는다.**

implements: AI-B-09, AI-L-06, AI-B-01, AI-C-08, AI-S-03
tests: trial is never a measurement, descriptive vs scored, frame-set refusal,
       prompt axis makes a vocabulary change a different configuration
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contracts.profile import ExecutionConfiguration, prompt_ref_for  # noqa: E402
from runtime.model_trial import (  # noqa: E402
    COMPARISON_DESCRIPTIVE,
    COMPARISON_SCORED,
    REASON_FRAME_SETS_DIFFER,
    REASON_NOT_A_MEASUREMENT,
    REASON_SINGLE_RUN,
    TrialDetection,
    TrialFrame,
    TrialRun,
    compare,
    summarise,
)

FRAME_A, FRAME_B = "frame_000001.jpg", "frame_000020.jpg"


def _config(implementation: str, vocabulary=("person", "chair"), **over) -> ExecutionConfiguration:
    body = dict(capability_kind="perception.detect_ovd", implementation_ref=implementation,
                runtime_ref="ultralytics-8.4.198", input_profile="464x400",
                prompt_ref=prompt_ref_for(vocabulary))
    body.update(over)
    return ExecutionConfiguration(**body)


def _run(implementation: str, detections, *, frames=(FRAME_A,), latency=(12.0,),
         vocabulary=("person", "chair")) -> TrialRun:
    return TrialRun(
        configuration=_config(implementation, vocabulary),
        frames=tuple(TrialFrame(frame_ref=f, media_ref=f"/api/media?frame={f}") for f in frames),
        detections=tuple(detections),
        latency_ms=tuple(latency),
        actor="operator")


def _box(label, x1, y1, x2, y2, score=0.8, frame=FRAME_A, from_vocabulary=True):
    return TrialDetection(label, score, (x1, y1, x2, y2), frame, from_vocabulary)


# ── 시도는 측정이 아니다 ────────────────────────────────────────────────────

def test_a_trial_says_why_it_is_not_a_measurement():
    """다음 사람이 "시도를 프로파일에 넣는 함수" 를 찾았을 때 **사유를 읽고 그만두게**."""
    run = _run("yolov8s-worldv2", [_box("person", 10, 10, 50, 90)])

    excuse = run.why_not_a_measurement()
    assert REASON_NOT_A_MEASUREMENT in excuse
    assert "measure()" in excuse, "어디서 만들어야 하는지를 함께 적는다"
    assert not hasattr(run, "to_measurement_set")


def test_the_latency_carries_its_sample_count_so_nobody_reads_it_as_a_profile():
    run = _run("yolov8s-worldv2", [], frames=(FRAME_A, FRAME_B), latency=(10.0, 30.0))

    assert run.sample_count == 2
    assert run.median_latency_ms == 20.0
    assert summarise(run).latency_sample_count == 2


def test_with_no_latency_sample_the_median_is_absent_not_zero():
    run = _run("yolov8s-worldv2", [], latency=())

    assert run.median_latency_ms is None, "0 이면 '즉시 끝났다' 로 읽힌다"


def test_scores_are_reported_as_a_span_not_an_average():
    """한 평균이 전체를 대표하지 않는다 — 0.11 과 0.75 의 평균은 아무것도 아니다."""
    run = _run("yolov8s-worldv2", [_box("person", 0, 0, 10, 10, score=0.75),
                                   _box("wire", 0, 0, 5, 5, score=0.11)])

    assert run.score_span() == (0.11, 0.75)


# ── 정답이 없으면 우열을 말하지 않는다 ─────────────────────────────────────

def test_without_ground_truth_the_comparison_refuses_to_rank():
    """**이 시험이 이 파일의 요점이다.**"""
    many = _run("loose", [_box("person", 0, 0, 10, 10), _box("chair", 20, 20, 40, 40),
                          _box("wire", 50, 50, 55, 55, score=0.11)])
    few = _run("strict", [_box("person", 0, 0, 10, 10)])

    verdict = compare([many, few])

    assert verdict.kind == COMPARISON_DESCRIPTIVE
    assert verdict.scored == {}, "정답 없이 적중을 세지 않는다"
    assert any("더 많이 찾은 쪽이 더 나은 쪽이 아니다" in c for c in verdict.caveats)
    assert any("라벨" in c for c in verdict.caveats), "우열을 가리는 길을 알려 준다"


def test_the_descriptive_comparison_still_says_what_each_one_found():
    """우열을 말하지 않는 것이 아무것도 말하지 않는 것은 아니다."""
    many = _run("loose", [_box("person", 0, 0, 10, 10), _box("wire", 50, 50, 55, 55)])
    few = _run("strict", [_box("person", 0, 0, 10, 10)])

    payload = compare([many, few]).as_payload()

    by_impl = {r["implementation_ref"]: r for r in payload["runs"]}
    assert by_impl["loose"]["detection_count"] == 2
    assert by_impl["strict"]["labels"] == {"person": 1}
    assert payload["agreement"][0]["shared_boxes"] == 1, "둘이 함께 잡은 상자"


def test_agreement_is_described_as_shared_boxes_not_as_correctness():
    """둘이 합의했다는 것이 둘이 맞았다는 뜻은 아니다 — 같은 오탐을 공유할 수 있고,
    실제로 그 일이 이 프로젝트에서 위치 추정을 깨뜨린 적이 있다."""
    left = _run("a", [_box("door", 0, 0, 10, 10)])
    right = _run("b", [_box("door", 1, 1, 11, 11)])

    payload = compare([left, right]).as_payload()

    assert payload["agreement"][0]["shared_boxes"] == 1
    assert "correct" not in str(payload["agreement"]).lower()


# ── 정답이 있으면 센다 ──────────────────────────────────────────────────────

def test_with_ground_truth_the_comparison_counts_hits_and_false_positives():
    """정답은 사람 검수에서 온다(AI-L-03) — 그래서 모델 비교가 라벨링에 묶인다."""
    truth = {FRAME_A: [("person", (0.0, 0.0, 10.0, 10.0))]}
    many = _run("loose", [_box("person", 0, 0, 10, 10), _box("wire", 50, 50, 60, 60)])
    few = _run("strict", [_box("person", 0, 0, 10, 10)])

    verdict = compare([many, few], ground_truth=truth)

    assert verdict.kind == COMPARISON_SCORED
    loose = verdict.scored[many.configuration.fingerprint]
    strict = verdict.scored[few.configuration.fingerprint]
    assert loose["hit"] == strict["hit"] == 1
    assert loose["spurious"] == 1 and strict["spurious"] == 0
    assert strict["precision"] == 1.0 and loose["precision"] == 0.5
    assert any("실행 프로파일의 품질이 아니다" in c for c in verdict.caveats)


def test_frames_without_ground_truth_are_excluded_and_that_is_said():
    """정답 없는 프레임을 셈에 넣으면 전부 놓친 것으로 세어진다."""
    truth = {FRAME_A: [("person", (0.0, 0.0, 10.0, 10.0))]}
    run_a = _run("a", [_box("person", 0, 0, 10, 10), _box("chair", 0, 0, 5, 5, frame=FRAME_B)],
                 frames=(FRAME_A, FRAME_B), latency=(10.0, 11.0))
    run_b = _run("b", [_box("person", 0, 0, 10, 10)],
                 frames=(FRAME_A, FRAME_B), latency=(9.0, 12.0))

    verdict = compare([run_a, run_b], ground_truth=truth)

    assert verdict.scored[run_a.configuration.fingerprint]["frames_scored"] == 1
    assert any(FRAME_B in c for c in verdict.caveats)


def test_a_frame_whose_ground_truth_is_empty_does_not_produce_a_zero_recall():
    """정답이 하나도 없으면 비율을 내지 않는다 — 0/0 을 0.0 으로 적으면 "전부 놓쳤다"다."""
    truth = {FRAME_A: [("person", (0.0, 0.0, 10.0, 10.0))]}
    found_nothing = _run("quiet", [])
    found_one = _run("loud", [_box("person", 0, 0, 10, 10)])

    verdict = compare([found_nothing, found_one], ground_truth=truth)

    quiet = verdict.scored[found_nothing.configuration.fingerprint]
    assert quiet["recall"] == 0.0, "정답이 있는데 못 찾았으면 0 이 맞다"
    assert quiet["precision"] is None, "찾은 것이 없으면 정밀도를 말할 수 없다"


# ── 견줄 수 없는 경우 ───────────────────────────────────────────────────────

def test_runs_on_different_frames_are_refused():
    """A 를 1번에, B 를 2번에 돌린 결과를 나란히 두면 그 비교는 아무 뜻이 없다."""
    verdict = compare([_run("a", [], frames=(FRAME_A,)),
                       _run("b", [], frames=(FRAME_B,))])

    assert not verdict.comparable
    assert verdict.reason == REASON_FRAME_SETS_DIFFER


def test_one_run_alone_is_not_a_comparison():
    assert compare([_run("a", [])]).reason == REASON_SINGLE_RUN


# ── 프롬프트가 구성을 가른다 ────────────────────────────────────────────────

def test_changing_the_vocabulary_makes_it_a_different_execution_configuration():
    """**이 축이 없던 동안은 프롬프트를 바꿔도 옛 측정값이 유효한 척했다.**"""
    narrow = _config("yolov8s-worldv2", ("person", "chair"))
    wide = _config("yolov8s-worldv2", ("person", "chair", "wall"))

    assert narrow.fingerprint != wide.fingerprint
    assert narrow.differing_axes(wide) == ("prompt_ref",), (
        "무엇이 달라져서 재측정이 필요한지가 축 이름으로 나와야 한다")


def test_the_same_vocabulary_in_another_order_is_the_same_configuration():
    """아무것도 바뀌지 않았는데 재측정 의무가 생기면 안 된다."""
    assert _config("m", ("person", "chair")).fingerprint == \
        _config("m", ("chair", " PERSON ")).fingerprint


def test_a_prompt_free_model_is_not_the_same_as_an_unset_prompt():
    """"이 모델은 어휘를 받지 않는다" 와 "찾을 것을 아직 안 정했다" 는 다른 상태다."""
    prompt_free = prompt_ref_for((), prompt_free=True)
    unset = prompt_ref_for(())

    assert prompt_free == "prompt_free" and unset == ""
    assert _config("m", prompt_ref=prompt_free).fingerprint != \
        _config("m", prompt_ref=unset).fingerprint


def test_a_label_that_did_not_come_from_the_vocabulary_is_counted():
    """프롬프트 없는 모델의 라벨은 어휘 일치가 아니다 — 그 차이가 보여야 어휘를
    고치는 판단이 선다."""
    run = _run("yoloe-pf", [_box("person", 0, 0, 10, 10, from_vocabulary=False),
                            _box("chair", 20, 20, 40, 40)])

    assert summarise(run).off_vocabulary_count == 1


# ── 픽셀은 상태 계약으로 나가지 않는다 ─────────────────────────────────────

def test_the_payload_carries_frame_references_and_never_pixels():
    """오버레이 그림은 `/api/media` 가 따로 낸다(AI-C-08)."""
    payload = compare([_run("a", [_box("person", 0, 0, 10, 10)]),
                       _run("b", [_box("person", 1, 1, 11, 11)])]).as_payload()
    text = str(payload)

    assert FRAME_A in payload["frame_refs"]
    for forbidden in ("jpeg", "base64", "data:image", "\\xff\\xd8"):
        assert forbidden not in text


# ── 같은 구현의 두 설정이 구분된다 ─────────────────────────────────────────

def test_two_settings_of_the_same_implementation_are_told_apart():
    """**실제로 한 번 구분되지 않았다.**

    운영자가 임계값만 바꿔 돌려 보면 두 줄의 `implementation_ref` 가 같다. 후처리
    축이 요약에 없으면 그 두 줄이 화면에서 똑같이 보이고, "설정을 바꿨을 때의
    변화를 본다" 는 이 기능의 목적이 바로 그 자리에서 사라진다.
    """
    loose = _run("yolov8s-worldv2", [_box("person", 0, 0, 10, 10),
                                     _box("wire", 50, 50, 55, 55, score=0.11)])
    strict = _run("yolov8s-worldv2", [_box("person", 0, 0, 10, 10)])
    loose = TrialRun(configuration=_config("yolov8s-worldv2", postprocess_ref="conf=0.10"),
                     frames=loose.frames, detections=loose.detections,
                     latency_ms=loose.latency_ms)
    strict = TrialRun(configuration=_config("yolov8s-worldv2", postprocess_ref="conf=0.35"),
                      frames=strict.frames, detections=strict.detections,
                      latency_ms=strict.latency_ms)

    payload = compare([loose, strict]).as_payload()

    rows = payload["runs"]
    assert {r["postprocess_ref"] for r in rows} == {"conf=0.10", "conf=0.35"}
    assert len({r["configuration_fingerprint"] for r in rows}) == 2


def test_the_agreement_pair_points_at_two_distinct_rows():
    """구현 이름으로 키를 잡으면 같은 구현의 두 설정이 **자기 자신과 비교한 것처럼**
    보인다. 지문으로 잡으면 `runs[]` 의 같은 칸으로 두 줄을 짚을 수 있다."""
    loose = TrialRun(configuration=_config("m", postprocess_ref="conf=0.10"),
                     frames=(TrialFrame(frame_ref=FRAME_A),),
                     detections=(_box("person", 0, 0, 10, 10),), latency_ms=(1.0,))
    strict = TrialRun(configuration=_config("m", postprocess_ref="conf=0.35"),
                      frames=(TrialFrame(frame_ref=FRAME_A),),
                      detections=(_box("person", 1, 1, 11, 11),), latency_ms=(1.0,))

    payload = compare([loose, strict]).as_payload()
    pair = payload["agreement"][0]["pair"]
    fingerprints = {r["configuration_fingerprint"] for r in payload["runs"]}

    assert len(set(pair)) == 2, "두 쪽이 서로 다른 열쇠여야 한다"
    assert set(pair) <= fingerprints, "그 열쇠로 runs[] 의 두 줄을 짚을 수 있어야 한다"


# ── 상자 좌표는 **여기** 들어오지 않는다 (2026-11-04) ───────────────────────

def test_the_summary_stays_a_summary_and_does_not_carry_the_boxes():
    """상자 좌표는 `tools/fms_console/trial.py` 의 응답에 붙고 **이 계층에는 붙지
    않는다.** 상자마다 따라붙는 하한 상태는 `perception/obstacle_taxonomy.py` 와
    `perception/detection_thresholds.py` 가 답하는데, 이 모듈은 시도의 의미 계약이고
    선언 파일을 모른다 — 여기에 상자+하한을 넣으려면 그 판정자를 계약 계층까지
    내려 보내야 하고, 그러면 판정이 계약 안으로 들어온다.

    그래서 다음 사람이 `RunSummary` 에 상자를 더하려 할 때 읽을 수 있도록 그 경계를
    시험으로 적어 둔다. 상자가 필요하면 책상 쪽 `detections` 를 늘린다.
    """
    summary = summarise(_run("a", [_box("person", 0, 0, 10, 10)]))

    assert not hasattr(summary, "boxes")
    assert not hasattr(summary, "detections")
    # 요약이 말하는 것은 수와 폭이다 — 자리는 말하지 않는다.
    assert summary.detection_count == 1
    payload = compare([_run("a", [_box("person", 0, 0, 10, 10)]),
                       _run("b", [_box("person", 1, 1, 11, 11)])]).as_payload()
    assert "box_xyxy" not in str(payload)


def test_nothing_running_is_not_the_same_as_running_one():
    """**0 과 1 은 다른 사실이다.** 고른 후보가 전부 세워지지 못한 경우를 "하나만
    돌렸다" 로 적으면, 운영자는 자기가 하나만 골랐다고 읽고 왜 아무것도 안 돌았는지
    묻지 않게 된다 — 실제 배치에서 그렇게 보였다(가중치 대신 허브를 보는 두 후보가
    둘 다 거절됐을 때).
    """
    from runtime.model_trial import REASON_NO_RUN

    assert compare([]).reason == REASON_NO_RUN
    assert compare([_run("a", [])]).reason == REASON_SINGLE_RUN
    assert REASON_NO_RUN != REASON_SINGLE_RUN
    # 거절도 같은 모양이다 — 빈 응답을 내지 않는다.
    assert compare([]).as_payload()["runs"] == []
