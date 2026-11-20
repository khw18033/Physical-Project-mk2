"""정량 목표 판정의 계약 — `observability/slo.py`.

implements: AI-O-01, AI-O-05, AI-B-01, AI-C-13
tests: 미측정은 미달이 아니다 · 세지 않은 것은 0 건이 아니다 · 표본이 모자라면 재지
       않았다고 말한다 · P95 는 꼬리를 보여 준다 · 비교는 한쪽이 비면 거절한다
"""
from __future__ import annotations

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.observability.slo import (
    AT_LEAST,
    AT_MOST,
    MET,
    MISSED,
    SLO_TARGETS,
    SloRecorder,
    SloTarget,
    UNMEASURED,
    compare,
    percentile,
)


def test_an_unmeasured_target_is_not_a_missed_one():
    """**이 모듈의 요점.** 재지 않은 것에 빨간 줄을 세우면 고칠 것이 없는데 고치려 든다."""
    recorder = SloRecorder()
    verdicts = {v.name: v for v in recorder.verdicts()}

    assert all(v.state == UNMEASURED for v in verdicts.values())
    assert all(v.measured is None for v in verdicts.values())
    assert recorder.summary() == {MET: 0, MISSED: 0, UNMEASURED: len(SLO_TARGETS)}


def test_a_count_that_was_never_counted_is_not_zero():
    """「중복 실행 0 건」은 **센 적이 있어야** 주장할 수 있다."""
    recorder = SloRecorder()
    duplicate = next(t for t in SLO_TARGETS if t.name == "duplicate_executions")

    assert recorder.verdict(duplicate).state == UNMEASURED

    recorder.start_counting("duplicate_executions")        # 이제 셌다
    assert recorder.verdict(duplicate).state == MET
    assert recorder.verdict(duplicate).measured == 0.0

    recorder.count("duplicate_executions")
    assert recorder.verdict(duplicate).state == MISSED


def test_too_few_samples_says_so_instead_of_guessing():
    recorder = SloRecorder()
    target = next(t for t in SLO_TARGETS if t.name == "assignment_latency")
    for _ in range(target.min_samples - 1):
        recorder.observe("assignment_latency", 10.0)

    verdict = recorder.verdict(target)
    assert verdict.state == UNMEASURED
    assert "최소" in verdict.reason
    assert verdict.samples == target.min_samples - 1


def test_a_target_is_met_or_missed_once_there_are_enough_samples():
    recorder = SloRecorder()
    target = next(t for t in SLO_TARGETS if t.name == "assignment_latency")
    for _ in range(target.min_samples):
        recorder.observe("assignment_latency", 100.0)
    assert recorder.verdict(target).state == MET

    slow = SloRecorder()
    for _ in range(target.min_samples):
        slow.observe("assignment_latency", 900.0)
    assert slow.verdict(target).state == MISSED


def test_p95_shows_the_tail_that_the_average_hides():
    """운영자가 겪는 것은 평균이 아니라 꼬리다."""
    # 느린 쪽이 6% 여야 P95(100 표본에서 94.05 번째)가 **꼬리 안**에 든다.
    # 5% 로 두면 경계에 걸려 평균과 같은 값이 나온다 — 이 시험이 아무것도 안 가른다.
    samples = [10.0] * 94 + [5000.0] * 6
    average = sum(samples) / len(samples)
    assert average < 500.0                                  # 평균은 목표를 통과한다
    assert percentile(samples, 0.95) > 500.0                # 꼬리는 통과하지 못한다


def test_percentile_of_nothing_is_none_not_zero():
    assert percentile([], 0.95) is None
    assert percentile([7.0], 0.95) == 7.0


def test_a_rate_needs_both_numerator_and_denominator():
    recorder = SloRecorder()
    target = next(t for t in SLO_TARGETS if t.name == "mission_success_rate")
    for _ in range(target.min_samples):
        recorder.record_outcome("mission_success_rate", ok=True)
    assert recorder.verdict(target).state == MET

    mixed = SloRecorder()
    for index in range(10):
        mixed.record_outcome("mission_success_rate", ok=index < 5)
    assert mixed.verdict(target).measured == pytest.approx(0.5)
    assert mixed.verdict(target).state == MISSED


def test_direction_decides_which_side_is_good():
    recorder = SloRecorder()
    smaller = SloTarget("latency", "p50", AT_MOST, 10.0, "ms", min_samples=1)
    bigger = SloTarget("latency", "p50", AT_LEAST, 10.0, "ms", min_samples=1)
    recorder.observe("latency", 5.0)
    assert recorder.verdict(smaller).state == MET
    assert recorder.verdict(bigger).state == MISSED


# --------------------------------------------------------------- 비교

def test_comparison_refuses_when_one_side_never_measured():
    """한쪽이 비었는데 「좋아졌다」고 말하면 그건 측정이 아니라 희망이다."""
    before, after = SloRecorder(), SloRecorder()
    for _ in range(5):
        after.observe("assignment_latency", 100.0)

    rows = {row[dd.SLO_ID]: row for row in compare(before, after)}
    assert rows["assignment_latency"]["change"] is None
    assert "견줄 수 없다" in rows["assignment_latency"]["reason"]


def test_comparison_marks_a_regression_only_when_the_verdict_flips():
    before, after = SloRecorder(), SloRecorder()
    for _ in range(5):
        before.observe("assignment_latency", 100.0)
        after.observe("assignment_latency", 900.0)

    row = next(r for r in compare(before, after)
               if r[dd.SLO_ID] == "assignment_latency")
    assert row["change"] == pytest.approx(800.0)
    assert row["regressed"] is True


def test_rows_carry_no_presentation_decisions():
    """색·픽셀·폰트는 응답에 없다 — 표현은 가시화 몫이다(AI-C-19)."""
    recorder = SloRecorder()
    for row in recorder.as_rows():
        assert set(row) == {dd.SLO_ID, dd.SLO_VERDICT, "measured", "target",
                            "unit", "samples", "reason"}
        assert not any(key in row for key in ("color", "colour", "css"))


def test_every_declared_target_states_its_unit_and_that_it_is_a_proposal():
    """목표값은 **제안이고 실측이 아니다.** 그 사실이 선언에 남아야 한다."""
    for target in SLO_TARGETS:
        assert target.unit
        assert target.direction in (AT_MOST, AT_LEAST)
        assert target.statistic in ("p95", "p50", "rate", "count")
