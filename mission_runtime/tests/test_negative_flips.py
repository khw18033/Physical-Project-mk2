"""집계 회귀가 통과시키는 후보 — 표본 단위로 보면 전에 되던 것이 깨져 있다.

왜 따로 필요했는가
------------------
`EvaluationReport.regression` 은 `baseline.ratio - retained.ratio` 다. 그래서
기준이 맞혔던 것 **5개를 깨고** 틀렸던 것 5개를 고친 후보는 회귀가 **0 이고
통과한다.** 집계만 보면 "변화 없음" 이지만 운영에서는 전에 되던 것 5개가 안 되기
시작하고, 그 5개를 쓰던 사람만 그것을 안다.

문헌 근거: Yan et al., *Positive-Congruent Training*(CVPR 2021)은 재학습한
ResNet-50 이 정확도를 약 12% 올리면서 표본의 3.56% 를 negative flip 으로 깼다고
보고한다(영상 분류·ImageNet). **집계 개선과 개별 파괴는 함께 일어난다.**

조사 출처: `docs/research/hitl-data-and-weight-management.md` §9.2.

implements: AI-L-05 (학습 결과 검증·기존 지식 보존)
tests: aggregate-zero regression still fails, flips are counted separately,
       unmeasured is not "no flips", the default allowance does not invent slack
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from continual.parameter_evaluation import (  # noqa: E402
    REASON_TOO_MANY_NEGATIVE_FLIPS,
    EvaluationGate,
    FlipCount,
    GateResult,
    ParameterEvaluator,
)
from continual.stream_learning import (  # noqa: E402
    CandidateOrigin,
    InputConditions,
    ParameterSet,
    StreamSample,
)

CONDITIONS = InputConditions(device_id="pi4", camera_id="pi4_front", resolution="464x400")


class _ScriptedScorer:
    """어느 표본을 맞히는지 선언으로 받는다 — 뒤집힘을 직접 짜 넣을 수 있게."""

    def predict(self, parameters: ParameterSet, sample: StreamSample) -> str | None:
        return sample.label if sample.sample_id in parameters.parameters["_right"] else None


def _parameters(right) -> ParameterSet:
    return ParameterSet(parameters={"_right": sorted(right)}, conditions=CONDITIONS,
                        base_version=None, sample_ids=(), produced_by="scripted")


def _samples(count: int):
    return [StreamSample(sample_id=f"s{i}", conditions=CONDITIONS, label="chair",
                         feature=(1.0,), origin=CandidateOrigin.HUMAN_CONFIRMED)
            for i in range(count)]


def _evaluate(base_right, candidate_right, *, count=20, gate=None):
    samples = _samples(count)
    return ParameterEvaluator(scorer=_ScriptedScorer()).evaluate(
        _parameters(candidate_right),
        new_samples=samples, retained_samples=samples,
        base=_parameters(base_right),
        gate=gate or EvaluationGate(min_new_accuracy=0.4, max_regression=0.02))


# ── 핵심: 상쇄된 파괴를 잡는다 ──────────────────────────────────────────────

def test_a_candidate_that_breaks_five_and_fixes_five_no_longer_passes():
    """**이 시험이 이 파일의 요점이다.** 집계로는 통과하던 후보다."""
    report = _evaluate({f"s{i}" for i in range(10)},
                       {f"s{i}" for i in range(5, 15)})

    assert report.regression == 0.0, "집계는 변화 없음이라고 말한다"
    assert report.flips.negative == 5 and report.flips.positive == 5
    assert report.result is GateResult.FAIL
    assert report.reason == REASON_TOO_MANY_NEGATIVE_FLIPS


def test_the_two_directions_are_counted_separately_so_they_cannot_cancel():
    """차이만 들고 다니면 그것이 바로 집계 회귀이고 이 축의 목적이 사라진다."""
    report = _evaluate({f"s{i}" for i in range(10)},
                       {f"s{i}" for i in range(5, 15)})

    assert report.flips.as_dict()["negative"] == 5
    assert report.flips.as_dict()["positive"] == 5
    assert report.flips.negative_ratio == 0.25


def test_a_candidate_that_only_improves_still_passes():
    """깨지 않고 고치기만 한 후보를 막으면 학습이 아무것도 못 한다."""
    report = _evaluate({f"s{i}" for i in range(10)},
                       {f"s{i}" for i in range(15)})

    assert report.flips.negative == 0 and report.flips.positive == 5
    assert report.result is GateResult.PASS
    assert report.reason is None


def test_one_broken_sample_is_enough_to_fail_by_default():
    """기본 허용치가 0 인 이유 — 허용치의 근거를 **우리 자료에서 재지 않았다.**

    인용한 3.56% 는 ImageNet 분류 수치다. 근거 없이 느슨한 기본값을 두는 것은
    근거 없이 파괴를 허용하는 것이다.
    """
    report = _evaluate({f"s{i}" for i in range(10)},
                       {f"s{i}" for i in range(1, 11)})

    assert report.flips.negative == 1
    assert report.result is GateResult.FAIL


def test_a_declared_allowance_is_honoured_when_someone_measures_one():
    """배치가 근거를 갖고 허용치를 선언하면 그 범위까지는 통과한다."""
    report = _evaluate({f"s{i}" for i in range(10)},
                       {f"s{i}" for i in range(1, 11)},
                       gate=EvaluationGate(min_new_accuracy=0.4, max_regression=0.02,
                                           max_negative_flip_ratio=0.1))

    assert report.flips.negative_ratio == 0.05
    assert report.result is GateResult.PASS


# ── 미측정은 "안 깨졌다" 가 아니다 ─────────────────────────────────────────

def test_without_a_base_version_the_flips_are_unmeasured_not_zero():
    """비교할 기준이 없으면 뒤집힘을 셀 수 없다. 0 으로 적으면 통과 근거가 된다."""
    samples = _samples(5)
    report = ParameterEvaluator(scorer=_ScriptedScorer()).evaluate(
        _parameters({s.sample_id for s in samples}),
        new_samples=samples, retained_samples=samples, base=None,
        gate=EvaluationGate(min_new_accuracy=0.4))

    assert not report.flips.measured
    assert report.flips.negative_ratio is None, "0.0 이면 '안 깨졌다' 로 읽힌다"
    assert report.result is GateResult.PASS, "기준이 없는 첫 후보는 이 축으로 막지 않는다"


def test_an_empty_retained_set_leaves_the_flip_axis_unmeasured():
    samples = _samples(4)
    report = ParameterEvaluator(scorer=_ScriptedScorer()).evaluate(
        _parameters({"s0"}), new_samples=samples, retained_samples=[],
        base=_parameters({"s0"}), gate=EvaluationGate(min_new_accuracy=0.2))

    assert report.flips == FlipCount()
    assert report.flips.negative_ratio is None


def test_the_flip_count_carries_the_sample_it_was_measured_on():
    """비율만 들고 다니면 표본 수가 사라진다 — 1/4 과 25/100 은 다른 근거다."""
    report = _evaluate({f"s{i}" for i in range(10)},
                       {f"s{i}" for i in range(5, 15)}, count=20)

    assert report.flips.total == 20


# ── 기존 축과 섞이지 않는다 ────────────────────────────────────────────────

def test_the_aggregate_regression_axis_still_fails_on_its_own():
    """두 축이 서로를 대체하지 않는다 — 집계로만 보이는 하락도 있다."""
    report = _evaluate({f"s{i}" for i in range(10)},
                       {f"s{i}" for i in range(3)})

    assert report.regression is not None and report.regression > 0.02
    assert report.result is GateResult.FAIL
    assert report.reason != REASON_TOO_MANY_NEGATIVE_FLIPS, (
        "집계가 먼저 막는다 — 사유가 뒤집힘으로 바뀌면 원인이 흐려진다")


def test_a_negative_allowance_is_refused_at_declaration_time():
    with pytest.raises(ValueError):
        EvaluationGate(max_negative_flip_ratio=-0.1)
    with pytest.raises(ValueError):
        EvaluationGate(max_negative_flip_ratio=1.5)
