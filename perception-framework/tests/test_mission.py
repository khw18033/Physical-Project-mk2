"""implements: AI-C-05, AI-C-11, AI-C-13
tests: optional-item loss keeps mission SUCCESS, required-item loss fails the
mission, sacrificed optional items are recorded, domain neutrality of the spec

각 테스트는 주장과 그 주장이 깨지는 반대 케이스를 함께 확인한다.
"""

from __future__ import annotations

import pytest

from perception_framework.contracts.capability import CapabilityState
from perception_framework.execution.mission import (
    MissionItem,
    MissionItemOutcome,
    MissionSpec,
    MissionStatus,
)

OK = MissionItemOutcome.SUCCEEDED
FAIL = MissionItemOutcome.FAILED
GONE = MissionItemOutcome.UNAVAILABLE


def _spec() -> MissionSpec:
    """The scenario from the requirement discussion, expressed by the caller."""
    return MissionSpec(
        "m1",
        [
            MissionItem("observe.area_a", required=True),
            MissionItem("observe.area_b", required=True),
            MissionItem("confirm.hazard", required=True),
            MissionItem("segment.high_res", required=False),
            MissionItem("describe.detail", required=False),
        ],
    )


def test_optional_failures_do_not_fail_the_mission():
    """AI-C-05: 선택 항목 실패는 임무 실패가 아니다."""
    verdict = _spec().evaluate(
        {
            "observe.area_a": OK,
            "observe.area_b": OK,
            "confirm.hazard": OK,
            "segment.high_res": FAIL,
            "describe.detail": GONE,
        }
    )
    assert verdict.status is MissionStatus.SUCCESS
    assert verdict.succeeded
    assert verdict.optional_quality is CapabilityState.DISABLED


def test_required_failure_fails_the_mission():
    """반대 케이스: 필수 항목이 실패하면 optional 이 모두 성공해도 실패한다."""
    verdict = _spec().evaluate(
        {
            "observe.area_a": OK,
            "observe.area_b": FAIL,
            "confirm.hazard": OK,
            "segment.high_res": OK,
            "describe.detail": OK,
        }
    )
    assert verdict.status is MissionStatus.FAILED
    assert not verdict.succeeded
    assert verdict.failed_required == ("observe.area_b",)
    assert verdict.optional_quality is CapabilityState.ACTIVE


def test_verdict_records_what_was_sacrificed():
    """단순 SUCCESS/FAIL 이 아니라 무엇을 포기했는지 남아야 한다."""
    verdict = _spec().evaluate(
        {
            "observe.area_a": OK,
            "observe.area_b": OK,
            "confirm.hazard": OK,
            "segment.high_res": OK,
            "describe.detail": FAIL,
        }
    )
    assert verdict.status is MissionStatus.SUCCESS
    assert verdict.optional_quality is CapabilityState.DEGRADED
    assert verdict.satisfied_optional == ("segment.high_res",)
    assert verdict.sacrificed_optional == ("describe.detail",)
    assert verdict.is_reduced
    assert "describe.detail" in verdict.summary()


def test_full_success_is_not_marked_reduced():
    """반대 케이스: 아무것도 포기하지 않았으면 축소 표시가 붙지 않는다."""
    verdict = _spec().evaluate(
        {
            "observe.area_a": OK,
            "observe.area_b": OK,
            "confirm.hazard": OK,
            "segment.high_res": OK,
            "describe.detail": OK,
        }
    )
    assert verdict.optional_quality is CapabilityState.ACTIVE
    assert verdict.sacrificed_optional == ()
    assert not verdict.is_reduced


def test_unreported_required_item_is_not_run_not_failed():
    """실행되지 않음과 실행 후 실패를 구분한다(AI-O-02)."""
    verdict = _spec().evaluate({"observe.area_a": OK, "observe.area_b": OK})
    assert verdict.status is MissionStatus.NOT_RUN
    assert verdict.missing_required == ("confirm.hazard",)
    assert verdict.failed_required == ()


def test_unreported_optional_item_is_sacrificed_not_blocking():
    """반대 케이스: 미보고 optional 은 임무를 막지 않고 포기 항목이 된다."""
    verdict = _spec().evaluate(
        {"observe.area_a": OK, "observe.area_b": OK, "confirm.hazard": OK}
    )
    assert verdict.status is MissionStatus.SUCCESS
    assert set(verdict.sacrificed_optional) == {"segment.high_res", "describe.detail"}
    assert verdict.optional_quality is CapabilityState.DISABLED


def test_unavailable_required_item_fails_like_a_failure():
    """필수 capability 부재는 축소가 아니라 임무 실패다(AI-C-11)."""
    verdict = _spec().evaluate(
        {"observe.area_a": OK, "observe.area_b": OK, "confirm.hazard": GONE}
    )
    assert verdict.status is MissionStatus.FAILED
    assert verdict.failed_required == ("confirm.hazard",)


def test_mission_without_optional_items_reports_active_quality():
    spec = MissionSpec("m2", [MissionItem("observe.area_a")])
    verdict = spec.evaluate({"observe.area_a": OK})
    assert verdict.status is MissionStatus.SUCCESS
    assert verdict.optional_quality is CapabilityState.ACTIVE
    assert verdict.summary() == "SUCCESS (optional ACTIVE)"


def test_undeclared_outcome_is_rejected():
    """오탈자로 성공을 얻어내지 못하도록 미선언 항목 결과는 거부한다."""
    with pytest.raises(ValueError):
        _spec().evaluate({"observe.area_a": OK, "observe.area_c": OK})


def test_spec_rejects_duplicate_and_all_optional_declarations():
    with pytest.raises(ValueError):
        MissionSpec("dup", [MissionItem("a"), MissionItem("a")])
    with pytest.raises(ValueError):
        MissionSpec("opt", [MissionItem("a", required=False)])


def test_same_module_serves_unrelated_domains_without_branching():
    """§2-3: 도메인 이름으로 분기하지 않는다 — 선언만 다르다."""
    river = MissionSpec(
        "river",
        [MissionItem("gauge.level"), MissionItem("forecast.window", required=False)],
    )
    robot = MissionSpec(
        "robot",
        [MissionItem("safety.local"), MissionItem("reid.match", required=False)],
    )
    a = river.evaluate({"gauge.level": OK, "forecast.window": FAIL})
    b = robot.evaluate({"safety.local": OK, "reid.match": FAIL})
    assert a.status is b.status is MissionStatus.SUCCESS
    assert a.optional_quality is b.optional_quality is CapabilityState.DISABLED
