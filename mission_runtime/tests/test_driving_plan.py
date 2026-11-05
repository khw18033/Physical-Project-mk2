"""The driving-path chain, assembled in one place.

implements: AI-B-14, AI-R-02, AI-S-03, AI-C-19, AI-C-02
tests: 거절 네 사유가 갈리는지 · 커버리지를 모를 때 후보가 지워지지 않는지 ·
       권한이 권고뿐인지 · 자리를 못 찾은 근거가 세어져 나오는지
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mission_runtime.planning.driving_plan import (  # noqa: E402
    AUTHORITY_ADVISORY,
    plan_drive,
)
from mission_runtime.planning.path_candidates import (  # noqa: E402
    REASON_TIE_BROKEN_BY_COST,
    REASON_UNDER_OBSERVED,
)
from mission_runtime.risk.hazard_field import (  # noqa: E402
    REASON_COVERAGE_UNKNOWN,
    ScanCoverage,
)
from mission_runtime.risk.scoring import RuleBasedRiskScorer  # noqa: E402

#: 실제 묶음과 같은 가중치 — 시험 전용 수를 새로 만들면 여기서만 통하는 결과가 된다.
WEIGHTS = {"proximity": 1.0, "ttc": 1.0}
SCORE = RuleBasedRiskScorer(WEIGHTS).score

GOAL = (0.0, 4.0)
#: 한 바퀴 전부 봤고 6m 까지 유효하다고 선언한 스캔.
FULL_SCAN = ScanCoverage.from_frames(range(0, 360, 45), fov_deg=60.0, max_range_m=6.0)


class _Taxonomy:
    """분류 판정은 이 시험의 대상이 아니다 — 근거가 비어 있으면 호출되지 않는다."""

    def near_threshold_for_speed(self, speed_mps):  # pragma: no cover - 호출되지 않는다
        raise AssertionError("빈 근거에서는 분류를 묻지 않는다")


def test_an_undeclared_coverage_refuses_the_comparison_but_keeps_the_candidates():
    """**"비교를 못 한다" 와 "경로가 없다" 는 다른 사실이다.**

    후보를 지우고 거절만 내면 운영자가 둘을 구분할 수 없고, 커버리지를 선언하면
    풀리는 문제인지 길이 아예 없는 문제인지 알 수 없다.
    """
    plan = plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE, coverage=None)

    assert plan["choice"]["decided"] is False
    assert plan["choice"]["reason"] == REASON_COVERAGE_UNKNOWN
    assert plan["candidates"], "후보는 그대로 남는다"
    assert plan["choice"]["considered"] == len(plan["candidates"])
    assert plan["evidence"]["coverage_declared"] is False


def test_a_declared_empty_scan_picks_a_path_and_says_it_was_length_not_risk():
    """길이 비어 있으면 위험으로는 갈리지 않는다 — 그때 멈추면 깨끗한 바닥에서 선다.

    고른 것은 사실이고, **무엇으로 골랐는지**가 함께 나와야 운영자가 "위험이 낮아서
    고른 길" 로 읽지 않는다(AI-C-13).
    """
    plan = plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE, coverage=FULL_SCAN)

    assert plan["choice"]["decided"] is True
    assert plan["choice"]["tie_break_by"] == REASON_TIE_BROKEN_BY_COST
    assert plan["evidence"]["coverage_declared"] is True


def test_turning_off_the_tie_break_refuses_instead_of_picking_on_risk_alone():
    """차선 기준을 주지 않으면 동률에서 1 위를 고르지 않는다(AI-S-03). 옛 동작이다."""
    plan = plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE, coverage=FULL_SCAN,
                      tie_break_by_length=False)

    assert plan["choice"]["decided"] is False
    assert plan["choice"].get("tie_break_by") is None


def test_a_scan_that_barely_reaches_refuses_with_the_under_observed_reason():
    """유효 거리가 짧으면 목표로 가는 경로의 대부분이 **보지 않은 자리**다.

    그때 나오는 사유는 '근거가 약하다' 가 아니라 '그 경로를 따라 본 자리가 적다'
    여야 한다 — 할 일이 "그 방향을 더 스캔" 으로 달라진다. 이 둘을 한 사유로
    뭉개면 스캔 밖으로 나가는 경로가 가장 안전한 경로로 보인다(2026-11-04 결함).
    """
    near_sighted = ScanCoverage.from_frames(range(0, 360, 45), fov_deg=60.0,
                                            max_range_m=0.5)

    plan = plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE, coverage=near_sighted)

    assert plan["choice"]["decided"] is False
    assert plan["choice"]["reason"] == REASON_UNDER_OBSERVED


def test_the_four_refusals_are_four_different_tokens():
    """사유가 뭉개지면 다음에 무엇을 하면 되는지가 사라진다.

    넷은 할 일이 서로 다르다 — 커버리지를 선언하라 · 그 방향을 더 스캔하라 ·
    목표를 주라 · 더 봐도 안 갈리니 다른 축으로 결정하라.
    """
    near_sighted = ScanCoverage.from_frames(range(0, 360, 45), fov_deg=60.0,
                                            max_range_m=0.5)
    tokens = {
        # 무엇을 봤는지 모른다
        plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE,
                   coverage=None)["choice"]["reason"],
        # 근거는 좋은데 그 경로를 따라 본 자리가 적다
        plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE,
                   coverage=near_sighted)["choice"]["reason"],
        # 목표가 없으니 후보 자체가 없다 — 위의 둘과 다른 사실이다
        plan_drive(None, [], _Taxonomy(), scorer=SCORE,
                   coverage=FULL_SCAN)["choice"]["reason"],
        # 봤는데 비슷하다. 차선 기준을 주지 않으면 여기서 멈춘다
        plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE, coverage=FULL_SCAN,
                   tie_break_by_length=False)["choice"]["reason"],
    }

    assert len(tokens) == 4, f"사유가 겹쳤다: {tokens}"
    assert None not in tokens, "거절에는 반드시 사유가 붙는다"


def test_no_goal_is_a_stated_reason_not_an_exception():
    """목표가 없는 것은 정상 상태다 — 임무가 아직 없는 배치가 그렇다(AI-C-05)."""
    plan = plan_drive(None, [], _Taxonomy(), scorer=SCORE, coverage=FULL_SCAN)

    assert plan["goal_local_xy_m"] is None
    assert plan["reason"] is not None
    assert plan["candidates"] == []


def test_the_plan_says_it_is_advisory_and_that_is_the_only_value():
    """경로를 정하는 것과 움직이라고 명령하는 것은 다른 일이다(AI-C-19).

    값이 하나뿐인 것이 요점이다 — 소비자가 "이것으로 명령을 내도 되는가" 를
    추측하지 않아야 하고, 이 값이 늘어나는 날은 경계가 다시 바뀌는 날이다.
    """
    plan = plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE, coverage=FULL_SCAN)

    assert plan["authority"] == AUTHORITY_ADVISORY


def test_it_is_a_driving_path_and_says_so():
    """`planning/visit_route.py` 는 `is_driving_path: false` 다. 둘을 섞으면 안 된다."""
    plan = plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE, coverage=FULL_SCAN)

    assert plan["is_driving_path"] is True
    assert plan["kind"] == "driving_path_candidates"
    assert plan["frame"] == "robot-local", "로컬 값은 전역 칸에 담지 않는다(AI-C-02)"


def test_no_pixels_and_no_presentation_decisions_leave_this_payload():
    """색·픽셀·폰트는 상태 계약으로 나가지 않는다(AI-C-08, docs/view-contract.md)."""
    plan = plan_drive(GOAL, [], _Taxonomy(), scorer=SCORE, coverage=FULL_SCAN)

    flat = repr(plan).lower()
    for banned in ("color", "colour", "rgb", "#", "pixel", "font"):
        assert banned not in flat, f"표현 결정이 섞였다: {banned}"
