"""주행 경로 후보를 **만들고 고른다**.

## 경계가 바뀌었다 (2026-11-04)

이 저장소는 오래도록 경로를 만들지 않았다. `risk/path_evaluation.py` 의 머리글이
그 결정을 적고 있다 — "경로 후보 자체는 이 모듈이 만들지 않는다 … 여러 후보 중
하나를 고르거나 순위를 매기는 것은 하지 않는다(AI-C-19)". 그래서 PoC 는 후보를
`path_candidates_external.json` 에서 읽었고, 채점기에는 `rank()` 도 `select()` 도
없다.

**2026-11-04 에 주행 경로 계획이 AI 몫이 되었다.** 이 모듈이 그 빈자리다. 다른
브랜치를 먼저 뒤졌고(mk2 의 HW·khw_VZ·ldg_BE·Junho_drone, physical_demo 의
data_stream·framework·go1_raspi·drone) **만드는 쪽은 어디에도 없었다** — HW 의
`go1_sdk_pc.cpp` 는 받아서 달리고, 가시화의 `approachPlan.ts` 는 받아서 명령으로
바꾸고, 탐지 서비스는 스캔 뒤 한 벌을 낼 뿐이다. 그래서 새로 쓴다.

**바뀌지 않은 것**: 물리 명령 발급과 실제 액추에이터 제어는 여전히 우리 것이
아니다(AI-C-19). 우리는 **경로를 정하고**, 보내는 일은 제어 경계를 거친다.

## 만든 것을 기존 채점기에 그대로 넣는다

`risk/path_evaluation.py` 의 `PathCandidate` 모양 그대로 낸다 — `candidate_id` 와
`hazard_probe_points`. 외부 JSON(`path_candidates_external.json`)과도 같은 모양이라
기존 오버레이·회귀 시험이 그대로 돈다. 새 자료형을 만들지 않는 것이 요점이다.

## 고르는 규칙 — 못 가리면 고르지 않는다

`perception/device_identity.py` 가 개체 식별에서 쓰는 규칙과 **같다**. 위험도가
비슷해 갈리지 않거나 근거가 모자라면 1위를 고르지 않고 사유를 낸다. 순위만
보여 주면 운영자는 1위를 정답으로 읽는다.

implements: AI-B-14, AI-R-02, AI-S-03, AI-C-02, AI-C-19
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

#: 후보 위를 몇 m 간격으로 찍어 채점기에 넘기는가. 촘촘할수록 좁은 틈을 놓치지
#: 않지만 채점 비용이 는다. 외부 JSON 의 간격(약 0.5 m)과 맞춰 둔다.
DEFAULT_PROBE_SPACING_M = 0.5

#: 1위와 2위의 위험도가 이보다 가까우면 **갈리지 않았다**고 본다. 측정으로 정한
#: 값이 아니라 어림이고, 그래서 인자로 바꿀 수 있다.
DEFAULT_RISK_MARGIN = 0.08

#: 근거 충분도가 이보다 낮은 후보는 "덜 위험해 보인다"가 아니라 "덜 봤다"이다.
DEFAULT_MIN_SUFFICIENCY = 0.5

#: 탐침점 중 이 비율보다 적게 관측된 후보는 고르지 않는다.
#:
#: 충분도와 **다른 축**이다. 충분도는 본 점의 근거가 좋았는지를, 이 값은 그 경로를
#: 따라 충분히 많은 자리를 봤는지를 묻는다. 둘을 하나로 두면 스캔 밖으로 나가는
#: 경로가 가장 안전하고 가장 확실한 경로가 된다 — 관측된 몇 점은 로봇 앞의 본
#: 자리뿐이고 거기는 비어 있으니 위험 0 이다.
#:
#: **이 값은 아직 재지 않았다.** 로봇 반폭·제동거리·탐침 간격에서 나와야 하는 값이고
#: `risk/hazard_field.py::influence_radius_m` 과 같이 하드웨어와 합의할 자리다.
#: 지금 값은 "경로의 과반을 봤어야 한다"는 보수적 출발점이며, 실측으로 바꿀 때
#: 바뀌는 것은 이 한 줄이다(AI-B-01: 바뀐 임계값은 다른 실행 구성이다).
DEFAULT_MIN_OBSERVED_FRACTION = 0.5

REASON_NO_GOAL = "no_goal"
REASON_NO_CANDIDATE = "no_candidate"
REASON_TOO_CLOSE = "candidates_not_separated"
REASON_INSUFFICIENT = "evidence_insufficient"
#: 본 점의 근거는 좋았지만 **그 경로를 따라 본 자리가 너무 적다.** 위와 다른
#: 사유인 이유: 할 일이 다르다 — 이쪽은 그 방향을 더 스캔해야 하고, 위쪽은 같은
#: 자리를 더 좋은 근거로 다시 봐야 한다.
REASON_UNDER_OBSERVED = "path_under_observed"
#: 위험으로 갈리지 않아 **다른 축으로** 골랐다는 표시. 위험으로 고른 것과 섞이면
#: 운영자가 "위험이 낮아서 고른 길"로 읽는다.
REASON_TIE_BROKEN_BY_COST = "tie_broken_by_path_length"


@dataclass(frozen=True)
class GeneratedCandidate:
    """후보 하나 + **왜 이 후보를 냈는가**.

    채점기가 읽는 것은 `candidate_id` 와 `hazard_probe_points` 뿐이지만, 화면이
    "왜 이 길인가"에 답하려면 가족과 인자가 남아 있어야 한다.
    """

    candidate_id: str
    hazard_probe_points: tuple[tuple[float, float], ...]
    family: str
    description: str
    params: Mapping[str, float] = field(default_factory=dict)

    def as_external(self) -> dict:
        """외부 JSON(`path_candidates_external.json`)과 같은 모양."""
        return {
            "candidate_id": self.candidate_id,
            "description": self.description,
            "hazard_probe_points": [list(p) for p in self.hazard_probe_points],
        }


def _sample(points: Sequence[tuple[float, float]],
            spacing: float) -> tuple[tuple[float, float], ...]:
    """꺾은선 위를 일정 간격으로 찍는다. 꼭짓점은 **반드시** 포함한다.

    꼭짓점을 빼먹으면 모서리를 스치는 장애물이 채점에서 사라진다.
    """
    if len(points) < 2:
        return tuple(tuple(round(v, 2) for v in p) for p in points)  # type: ignore[misc]
    out: list[tuple[float, float]] = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        steps = max(1, int(seg / spacing))
        for i in range(steps):
            t = i / steps
            out.append((round(x0 + (x1 - x0) * t, 2), round(y0 + (y1 - y0) * t, 2)))
    out.append((round(points[-1][0], 2), round(points[-1][1], 2)))
    # 같은 점이 연달아 나오면 접는다 — 채점이 두 번 돌 이유가 없다.
    folded: list[tuple[float, float]] = []
    for p in out:
        if not folded or folded[-1] != p:
            folded.append(p)
    return tuple(folded)


def generate(goal_local_xy: tuple[float, float] | None,
             *,
             lateral_offsets_m: Iterable[float] = (-1.2, -0.6, 0.6, 1.2),
             waypoints: Mapping[str, tuple[float, float]] | None = None,
             spacing_m: float = DEFAULT_PROBE_SPACING_M) -> list[GeneratedCandidate]:
    """로봇 로컬 (0,0) 에서 목표까지의 후보들.

    좌표는 **로봇 로컬 미터**다(전방 +y, 오른쪽 +x — 외부 JSON 과 같은 규약).
    전역이라고 주장하지 않는다(AI-C-02).

    가족 셋:

    - `direct` — 직선 하나. 기준점이다.
    - `lateral` — 가운데를 옆으로 민 우회. 미는 양이 곧 후보 이름에 남는다.
    - `via` — **선언된 자리**를 거쳐 가는 길(문·복도 교차점 등). 자리를 지어내지
      않고 받은 것만 쓴다.

    목표가 없으면 **빈 목록**이다. 아무 데로나 가는 후보를 만들지 않는다.
    """
    if goal_local_xy is None:
        return []
    gx, gy = float(goal_local_xy[0]), float(goal_local_xy[1])
    out: list[GeneratedCandidate] = [
        GeneratedCandidate(
            candidate_id="direct",
            hazard_probe_points=_sample([(0.0, 0.0), (gx, gy)], spacing_m),
            family="direct", description="목표까지 직선",
            params={"goal_x": gx, "goal_y": gy}),
    ]

    # 직선에 수직인 방향 — 그쪽으로 가운데를 민다.
    #
    # **부호를 틀리면 장애물 쪽으로 튼다.** 로봇 로컬은 전방 +y · 오른쪽 +x 이므로
    # 목표가 정면(0, L)일 때 오른쪽은 (+1, 0) 이어야 한다. (gy, -gx)/L 이 그것이고,
    # (-gy, gx)/L 로 쓰면 이름과 방향이 **거꾸로** 된다. `test_a_positive_offset_
    # goes_to_the_robots_right` 가 이 한 줄을 지킨다.
    length = math.hypot(gx, gy)
    if length > 1e-6:
        nx, ny = gy / length, -gx / length
        for offset in lateral_offsets_m:
            mid = (gx / 2 + nx * offset, gy / 2 + ny * offset)
            side = "left" if offset < 0 else "right"
            out.append(GeneratedCandidate(
                candidate_id=f"lateral_{side}_{abs(offset):.1f}".replace(".", "p"),
                hazard_probe_points=_sample([(0.0, 0.0), mid, (gx, gy)], spacing_m),
                family="lateral",
                description=f"가운데를 {side} 로 {abs(offset):.1f} m 밀어 우회",
                params={"offset_m": float(offset)}))

    for name, point in sorted((waypoints or {}).items()):
        wx, wy = float(point[0]), float(point[1])
        out.append(GeneratedCandidate(
            candidate_id=f"via_{name}",
            hazard_probe_points=_sample([(0.0, 0.0), (wx, wy), (gx, gy)], spacing_m),
            family="via", description=f"선언된 자리 {name} 를 거쳐",
            params={"waypoint_x": wx, "waypoint_y": wy}))
    return out


@dataclass
class Choice:
    """고른 결과 — **고르지 않은 것도 결과다.**"""

    candidate_id: str | None
    reason: str | None
    margin: float | None = None
    considered: int = 0
    runner_up: str | None = None
    #: 위험이 아닌 축으로 골랐으면 그 축의 이름. 위험으로 골랐으면 None.
    tie_break_by: str | None = None

    @property
    def decided(self) -> bool:
        return self.candidate_id is not None

    def as_payload(self) -> dict:
        body: dict = {"candidate_id": self.candidate_id, "decided": self.decided,
                      "considered": self.considered}
        if self.margin is not None:
            body["margin"] = round(self.margin, 4)
        if self.runner_up is not None:
            body["runner_up"] = self.runner_up
        if self.reason is not None:
            body["reason"] = self.reason
        if self.tie_break_by is not None:
            body["tie_break_by"] = self.tie_break_by
        return body


def choose(evaluations: Sequence,
           *,
           risk_margin: float = DEFAULT_RISK_MARGIN,
           min_sufficiency: float = DEFAULT_MIN_SUFFICIENCY,
           min_observed_fraction: float = DEFAULT_MIN_OBSERVED_FRACTION,
           tie_break: Mapping[str, float] | None = None) -> Choice:
    """채점 결과에서 하나를 고른다. **갈리지 않으면 고르지 않는다.**

    `evaluations` 는 `risk.path_evaluation.PathCandidateEvaluation` 들이다.
    여기서 보는 것은 `max_risk`(낮을수록 좋다)와 `evidence_sufficiency` 둘이다.

    거절하는 두 경우 — 둘은 **다른 사유**다.

    - `evidence_insufficient` — 본 자리의 근거가 약하다. 같은 자리를 더 좋은
      근거로 다시 보면 갈릴 수 있다.
    - `path_under_observed` — 근거는 좋은데 **그 경로를 따라 본 자리가 적다.**
      그 방향을 더 스캔해야 한다. 위와 할 일이 다르므로 사유를 가른다.
    - `candidates_not_separated` — 봤는데 비슷하다. 더 봐도 안 갈린다.

    위험이 갈리지 않을 때
    ---------------------
    길이 비어 있으면 후보 여럿이 **똑같이 위험 0** 이다. 그때 거절만 하면 길이
    깨끗할 때 로봇이 멈춘다 — 실제로 처음 돌렸을 때 그렇게 멈췄다. 그래서
    `tie_break` 를 둔다: 위험으로 갈리지 않으면 **선언된 다른 축**으로 고르고,
    `tie_break_by` 에 무엇으로 골랐는지 적는다. 위험으로 고른 것과 길이로 고른
    것이 운영자 화면에서 구분돼야 한다(AI-C-13: 사유를 남긴다).

    기본 축은 경로 길이다. `tie_break=None` 을 주면 옛 동작대로 거절한다.
    """
    if not evaluations:
        return Choice(None, REASON_NO_CANDIDATE, considered=0)

    supported = [e for e in evaluations
                 if getattr(e, "evidence_sufficiency", 0.0) >= min_sufficiency]
    if not supported:
        return Choice(None, REASON_INSUFFICIENT, considered=len(evaluations))

    # **두 번째 관문.** 근거가 좋은 것과 충분히 많은 자리를 본 것은 다른 사실이고,
    # 앞의 것만 보면 스캔 밖으로 나가는 경로가 통과한다(`PathCandidateEvaluation`
    # 의 머리글에 재현 경위가 있다). 비율을 모르는 후보(`None`)는 통과시키지
    # 않는다 — 미측정을 충족으로 읽으면 이 관문이 없는 것과 같다.
    usable = []
    for e in supported:
        fraction = getattr(e, "observed_fraction", None)
        if fraction is not None and fraction >= min_observed_fraction:
            usable.append(e)
    if not usable:
        return Choice(None, REASON_UNDER_OBSERVED, considered=len(evaluations))

    ordered = sorted(usable, key=lambda e: (e.max_risk, e.candidate_id))
    best = ordered[0]
    if len(ordered) == 1:
        return Choice(best.candidate_id, None, considered=len(evaluations))

    second = ordered[1]
    margin = float(second.max_risk) - float(best.max_risk)
    if margin < risk_margin:
        if tie_break:
            # 동률 묶음 안에서만 다른 축으로 고른다. 위험이 **갈린** 후보까지
            # 길이로 다시 줄 세우면 위험 판정이 길이에 덮인다.
            tied = [e for e in ordered
                    if float(e.max_risk) - float(best.max_risk) < risk_margin]
            picked = min(tied, key=lambda e: (tie_break.get(e.candidate_id, float("inf")),
                                              e.candidate_id))
            if tie_break.get(picked.candidate_id) is not None:
                rest = [e for e in tied if e.candidate_id != picked.candidate_id]
                return Choice(picked.candidate_id, None, margin=margin,
                              considered=len(evaluations),
                              runner_up=rest[0].candidate_id if rest else None,
                              tie_break_by=REASON_TIE_BROKEN_BY_COST)
        # 1 위를 고르지 않는다. 두 후보 이름을 함께 남겨 다음에 무엇을 더 보면
        # 갈리는지 말할 수 있게 한다.
        return Choice(None, REASON_TOO_CLOSE, margin=margin,
                      considered=len(evaluations), runner_up=second.candidate_id)
    return Choice(best.candidate_id, None, margin=margin,
                  considered=len(evaluations), runner_up=second.candidate_id)


def path_lengths(candidates) -> dict[str, float]:
    """후보별 경로 길이(m). `choose(tie_break=...)` 에 그대로 넣는다."""
    out: dict[str, float] = {}
    for c in candidates:
        pts = getattr(c, "hazard_probe_points", None) or ()
        out[c.candidate_id] = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    return out


def plan_payload(goal_local_xy: tuple[float, float] | None,
                 evaluations: Sequence = (),
                 *,
                 waypoints: Mapping[str, tuple[float, float]] | None = None,
                 spacing_m: float = DEFAULT_PROBE_SPACING_M) -> dict:
    """화면이 그대로 읽는 한 덩어리. 색·픽셀·폰트는 없다."""
    candidates = generate(goal_local_xy, waypoints=waypoints, spacing_m=spacing_m)
    choice = choose(evaluations) if evaluations else Choice(
        None, REASON_NO_CANDIDATE if not candidates else None,
        considered=len(candidates))
    return {
        "frame": "robot-local",
        "unit": "meter",
        # 이번에는 **주행 경로다.** `visit_route` 의 `is_driving_path: false` 와
        # 구분되는 자리라 분명히 적는다(2026-11-04 경계 개정).
        "kind": "driving_path_candidates",
        "is_driving_path": True,
        "goal_local_xy_m": (None if goal_local_xy is None
                            else [float(goal_local_xy[0]), float(goal_local_xy[1])]),
        "reason": None if goal_local_xy is not None else REASON_NO_GOAL,
        "candidates": [c.as_external() | {"family": c.family, "params": dict(c.params)}
                       for c in candidates],
        "choice": choice.as_payload(),
    }
