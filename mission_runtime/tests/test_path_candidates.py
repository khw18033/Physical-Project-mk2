"""주행 경로 후보 — 만들고, 기존 채점기에 넣고, 고른다.

2026-11-04 에 주행 경로 계획이 AI 몫이 되면서 생긴 묶음이다. 그 전까지 후보는
`path_candidates_external.json` 에서만 왔고 `risk/path_evaluation.py` 에는
`rank()` 도 `select()` 도 **일부러** 없었다.

여기서 고정하는 것 넷.

1. 낸 후보가 **기존 채점기에 그대로** 들어간다. 새 자료형을 만들지 않았다.
2. 목표가 없으면 후보도 없다. 아무 데로나 가는 길을 만들지 않는다.
3. **갈리지 않으면 고르지 않는다** — 그리고 "덜 봤다"와 "봤는데 비슷하다"는
   다른 사유다.
4. 좌표는 로봇 로컬이고 전역이라고 주장하지 않는다.

implements: AI-B-14, AI-R-02, AI-S-03, AI-C-02, AI-C-19
tests: shape compatibility, no goal, vertex preservation, tie refusal,
       insufficiency refusal
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from planning.path_candidates import (  # noqa: E402
    REASON_INSUFFICIENT,
    REASON_UNDER_OBSERVED,
    REASON_NO_CANDIDATE,
    REASON_NO_GOAL,
    REASON_TOO_CLOSE,
    choose,
    generate,
    plan_payload,
)
from risk.path_evaluation import PathCandidate  # noqa: E402


@dataclass
class FakeEval:
    """`PathCandidateEvaluation` 중 고르는 데 쓰는 칸들만.

    `observed_fraction` 기본값이 1.0 인 이유: 이 아래 시험들이 보려는 것은
    **위험과 충분도로 갈리는지**이고 관측 비율은 그 축이 아니다. 기본값을 1.0 으로
    두면 그 시험들은 전부 관측된 경로를 다루게 되어 뜻이 그대로 남는다. 비율
    관문 자체는 아래 전용 시험이 본다 — 그리고 **이 칸을 아예 두지 않으면**
    `choose` 가 미측정으로 읽고 거절하는데, 그것이 맞는 동작이다.
    """

    candidate_id: str
    max_risk: float
    evidence_sufficiency: float
    observed_fraction: float | None = 1.0


# ── 기존 계약과의 맞물림 ────────────────────────────────────────────────────

def test_a_generated_candidate_feeds_the_existing_evaluator_unchanged():
    """새 자료형을 만들지 않았다는 것이 요점이다."""
    for made in generate((0.0, 4.0)):
        candidate = PathCandidate(candidate_id=made.candidate_id,
                                  hazard_probe_points=made.hazard_probe_points)
        assert candidate.candidate_id == made.candidate_id
        assert len(candidate.hazard_probe_points) >= 2


def test_the_external_json_shape_is_preserved():
    """`path_candidates_external.json` 과 같은 모양이라 기존 도구가 그대로 돈다."""
    made = generate((0.0, 4.0))[0].as_external()

    assert set(made) == {"candidate_id", "description", "hazard_probe_points"}
    assert all(len(p) == 2 for p in made["hazard_probe_points"])


# ── 만들기 ──────────────────────────────────────────────────────────────────

def test_without_a_goal_there_is_no_candidate():
    """아무 데로나 가는 길을 만들지 않는다."""
    assert generate(None) == []

    payload = plan_payload(None)
    assert payload["candidates"] == [] and payload["reason"] == REASON_NO_GOAL


def test_the_direct_candidate_runs_from_the_robot_to_the_goal():
    direct = next(c for c in generate((3.0, 4.0)) if c.candidate_id == "direct")

    assert direct.hazard_probe_points[0] == (0.0, 0.0)
    assert direct.hazard_probe_points[-1] == (3.0, 4.0)


def test_a_detour_keeps_its_corner_as_a_probe_point():
    """꼭짓점을 빼먹으면 모서리를 스치는 장애물이 채점에서 사라진다."""
    detour = next(c for c in generate((0.0, 4.0)) if c.family == "lateral")
    offset = detour.params["offset_m"]

    corner = (round(offset, 2), 2.0)
    assert corner in detour.hazard_probe_points, detour.hazard_probe_points


def test_a_positive_offset_goes_to_the_robots_right():
    """**부호가 뒤집히면 장애물 쪽으로 튼다.**

    실제로 한 번 뒤집혀 있었다. 로봇 로컬은 전방 +y · 오른쪽 +x 이므로 목표가
    정면일 때 `lateral_right` 는 +x 로 가야 한다. 이 시험이 그 한 줄을 지킨다.
    """
    made = {c.candidate_id: c for c in generate((0.0, 4.0))}

    def mid_x(cid):
        pts = made[cid].hazard_probe_points
        return pts[len(pts) // 2][0]

    assert mid_x("lateral_right_1p2") > 0, "right 는 +x 여야 한다"
    assert mid_x("lateral_left_1p2") < 0, "left 는 -x 여야 한다"


def test_the_detour_steers_away_from_a_hazard_not_into_it():
    """부호가 뒤집혔는지를 **결과로** 본다 — 장애물 반대쪽이 덜 위험해야 한다."""
    hazard = (1.0, 2.0)                       # 로봇 앞 오른쪽

    def closest(cid):
        pts = {c.candidate_id: c for c in generate((0.0, 4.0))}[cid].hazard_probe_points
        return min(math.dist(p, hazard) for p in pts)

    assert closest("lateral_left_1p2") > closest("lateral_right_1p2"), (
        "오른쪽에 장애물이 있으면 왼쪽 우회가 더 멀어야 한다")


def test_a_detour_is_longer_than_the_direct_line():
    """우회가 직선보다 짧으면 기하가 틀린 것이다."""
    def length(points):
        return sum(math.dist(a, b) for a, b in zip(points, points[1:]))

    made = {c.candidate_id: c for c in generate((0.0, 4.0))}
    straight = length(made["direct"].hazard_probe_points)
    for cid, c in made.items():
        if c.family == "lateral":
            assert length(c.hazard_probe_points) > straight, cid


def test_waypoints_are_taken_not_invented():
    """선언된 자리만 거친다. 없으면 `via` 후보도 없다."""
    assert not any(c.family == "via" for c in generate((0.0, 4.0)))

    viad = [c for c in generate((0.0, 4.0), waypoints={"door-503": (1.0, 2.0)})
            if c.family == "via"]
    assert len(viad) == 1 and (1.0, 2.0) in viad[0].hazard_probe_points


def test_coordinates_are_robot_local_and_never_claim_global():
    payload = plan_payload((0.0, 4.0))

    assert payload["frame"] == "robot-local" and payload["unit"] == "meter"
    assert "global" not in payload["frame"]


def test_this_one_says_it_is_a_driving_path():
    """`visit_route` 는 `is_driving_path: false` 다. 둘을 구분해 적는다."""
    assert plan_payload((0.0, 4.0))["is_driving_path"] is True
    assert plan_payload((0.0, 4.0))["kind"] == "driving_path_candidates"


# ── 고르기 ──────────────────────────────────────────────────────────────────

def test_a_clear_winner_is_chosen():
    choice = choose([FakeEval("a", 0.10, 0.9), FakeEval("b", 0.60, 0.9)])

    assert choice.decided and choice.candidate_id == "a"
    assert choice.runner_up == "b" and choice.margin == 0.5


def test_candidates_too_close_are_not_separated_so_nothing_is_chosen():
    """순위만 보여 주면 운영자는 1위를 정답으로 읽는다."""
    choice = choose([FakeEval("a", 0.30, 0.9), FakeEval("b", 0.32, 0.9)])

    assert not choice.decided
    assert choice.reason == REASON_TOO_CLOSE
    assert choice.runner_up == "b", "무엇과 안 갈렸는지 남긴다"


def test_insufficient_evidence_is_a_different_refusal_from_a_tie():
    """"덜 봤다"와 "봤는데 비슷하다"는 다음에 할 일이 다르다."""
    choice = choose([FakeEval("a", 0.10, 0.1), FakeEval("b", 0.90, 0.1)])

    assert not choice.decided and choice.reason == REASON_INSUFFICIENT


def test_a_path_that_leaves_the_scan_is_not_the_safest_path():
    """**스캔 밖으로 나가는 경로가 가장 안전해 보이던 결함**(2026-11-04).

    탐침 10 점 중 1 점만 관측된 경로는 그 1 점이 로봇 앞의 본 자리라서 위험 0 이고,
    충분도는 '점수가 나온 점들의 평균' 이라 1.0 이다 — 전부 관측된 경로와 **구분이
    되지 않았다.** 안전 판단에서 절대 고르면 안 되는 후보가 가장 확실한 후보로
    보인다는 뜻이었다.
    """
    barely = FakeEval("into-the-unknown", max_risk=0.0, evidence_sufficiency=1.0,
                      observed_fraction=0.10)

    choice = choose([barely])

    assert not choice.decided
    # 충분도 부족과 **다른 사유**다 — 이쪽은 그 방향을 더 스캔해야 하고,
    # 충분도 부족은 같은 자리를 더 좋은 근거로 다시 봐야 한다.
    assert choice.reason == REASON_UNDER_OBSERVED
    assert choice.reason != REASON_INSUFFICIENT


def test_an_unknown_observed_fraction_is_not_read_as_satisfying_the_floor():
    """미측정을 충족으로 읽으면 관문이 없는 것과 같다(AI-S-03)."""
    choice = choose([FakeEval("a", 0.0, 1.0, observed_fraction=None)])

    assert not choice.decided and choice.reason == REASON_UNDER_OBSERVED


def test_a_well_observed_path_still_gets_chosen():
    """관문을 더했다고 깨끗한 길에서 멈추면 안 된다 — 한 번 그렇게 멈췄다."""
    choice = choose([FakeEval("a", 0.0, 1.0, observed_fraction=1.0)])

    assert choice.decided and choice.candidate_id == "a"


def test_no_candidate_at_all_is_said_so():
    assert choose([]).reason == REASON_NO_CANDIDATE


def test_a_lone_usable_candidate_is_chosen_without_a_margin():
    choice = choose([FakeEval("a", 0.4, 0.9), FakeEval("b", 0.1, 0.2)])

    assert choice.candidate_id == "a", "근거가 모자란 b 는 후보에서 빠진다"
    assert choice.margin is None


def test_the_choice_is_deterministic_on_ties_in_risk():
    """같은 입력에 같은 답. 순서로 임의 선택하지 않는다."""
    first = choose([FakeEval("b", 0.1, 0.9), FakeEval("a", 0.1, 0.9)])
    second = choose([FakeEval("a", 0.1, 0.9), FakeEval("b", 0.1, 0.9)])

    assert first.reason == second.reason == REASON_TOO_CLOSE
