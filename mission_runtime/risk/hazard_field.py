"""Turns obstacle evidence into the named risk inputs a probe point needs.

implements: AI-R-02 (위험도·근거·권고 산정), AI-S-03 (근거 충분도)
관련: AI-C-19 (경계), AI-C-13 (교체 가능한 정책), AI-C-02 (로봇 로컬)

`risk/path_evaluation.py` 의 `HazardLookup` 자리를 채운다. 그 쪽은 경로 후보의
탐침점마다 이 함수를 불러 **이름 붙은 입력 묶음**을 받고, 점수는 기존
`risk/scoring.py::RuleBasedRiskScorer` 가 낸다 — 채점기를 새로 만들지 않는다.

근거가 없으면 `{}` 다
---------------------
반경 안에 아무 장애물 근거가 없으면 빈 묶음을 돌려준다. `{"proximity": 0.0}` 을
돌려주면 평가기는 그것을 **"확인했고 위험이 없었다"** 로 읽어 근거 충분도를
1.0 으로 올린다. 보지 않은 것과 봤는데 없는 것은 다른 사실이다(AI-S-03).

같은 이유로 `ttc` 는 접근 속도가 있을 때만 키가 생긴다. 없는 칸을 채우지 않으면
`RuleBasedRiskScorer` 가 가중치 합으로 충분도를 스스로 낮춘다 — 모자란 근거가
수치에 **자동으로** 드러나는 구조다.

본 곳과 안 본 곳
----------------
**"근처에 장애물이 없다"와 "그 방향을 안 봤다"를 반드시 갈라야 한다.** 둘을 같은
`{}` 로 두면 다음이 실제로 일어난다 — 장애물 옆을 스치는 후보만 근거가 생기고,
멀리 비켜 가는 안전한 후보는 "덜 봤다"로 걸러져 **장애물 쪽 경로가 선택된다**.
이 묶음을 처음 끝까지 돌렸을 때 바로 그렇게 골랐다.

그래서 `ScanCoverage` 가 필요하다. 스캔이 실제로 담은 방위 구간과 유효 거리를
들고 있고, 그 안의 빈 점은 **관측된 빈 곳**이라 근거가 된다. 구간 밖은 여전히
`{}` 다. 커버리지를 **모르면** 후보끼리 비교할 수 없다 — `comparable` 이 거짓이고
`scored_candidates()` 가 사유와 함께 거절한다. 모르는 채로 1 위를 고르는 것이
이 결함의 정체였다.

자리를 못 찾은 근거
-------------------
깊이가 없어 좌표를 못 낸 장애물은 어떤 탐침점에도 기여할 수 없다. 그렇다고 그
장애물을 위험으로 만들어 내지도 않는다 — 대신 `unlocatable` 로 세어 둔다.
그것이 없으면 "장애물이 없는 프레임"과 "장애물은 봤지만 전부 자리를 못 찾은
프레임"이 같은 모양이 된다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from perception.obstacle_evidence import ObstacleEvidence
from perception.obstacle_taxonomy import ObstacleTaxonomy

#: `RuleBasedRiskScorer` 가중치. 네 키가 다 있을 때만 충분도 1.0 이므로
#: "ttc 가 없다"는 사실이 근거 충분도에 그대로 나타난다(AI-S-03).
HAZARD_WEIGHTS = {
    "proximity": 0.35,
    "group_priority": 0.25,
    "standoff_deficit": 0.25,
    "ttc": 0.15,
}


#: 커버리지를 선언하지 않은 장(場)이 내는 거절 사유.
REASON_COVERAGE_UNKNOWN = "scan_coverage_undeclared"
#: 탐침점이 스캔 구간 밖이라 아무 말도 할 수 없는 경우.
REASON_OUTSIDE_COVERAGE = "outside_scan_coverage"


@dataclass(frozen=True)
class ScanCoverage:
    """스캔이 **실제로 본** 방위 구간과 유효 거리.

    로봇 로컬 기준(+y 전방 · 0° = 스캔 시작 방향, 시계방향 +)이고 전역이 아니다.
    `max_range_m` 은 "이 거리까지는 봤다"는 뜻이고 그 밖은 보지 않은 것이다 —
    유효 거리를 무한으로 두면 카메라가 못 보는 먼 곳까지 "비었다"고 주장하게 된다.
    """

    sectors: tuple[tuple[float, float], ...]
    max_range_m: float

    @classmethod
    def from_frames(cls, rotations_deg, *, fov_deg: float,
                    max_range_m: float) -> "ScanCoverage":
        """프레임의 회전각과 화각으로 구간을 만든다. 프레임이 없으면 구간도 없다."""
        half = float(fov_deg) / 2.0
        sectors = tuple((float(r) - half, float(r) + half) for r in rotations_deg)
        return cls(sectors=sectors, max_range_m=float(max_range_m))

    @property
    def is_declared(self) -> bool:
        return bool(self.sectors) and self.max_range_m > 0

    def covers(self, point: tuple[float, float]) -> bool:
        """그 점을 실제로 본 적이 있는가."""
        px, py = point
        distance = math.hypot(px, py)
        if distance > self.max_range_m:
            return False
        if distance < 1e-9:
            return self.is_declared          # 로봇 자리는 어느 구간에나 든다
        bearing = math.degrees(math.atan2(px, py)) % 360.0
        for lo, hi in self.sectors:
            if _bearing_in(bearing, lo, hi):
                return True
        return False


@dataclass
class HazardField:
    """한 스캔의 장애물 근거를 탐침점 질의로 바꾼다."""

    evidences: list[ObstacleEvidence]
    taxonomy: ObstacleTaxonomy
    #: 이 스캔이 본 범위. **None 은 "모른다"** 이고 "전부 봤다"가 아니다.
    coverage: ScanCoverage | None = None
    #: 탐침점이 장애물에서 이 반경(m) 안일 때만 그 장애물이 기여한다. 로봇 반폭 +
    #: 근거 위치 오차를 합친 값이며 **하드웨어와 합의할 값**이다. 선언으로 둔다.
    influence_radius_m: float = 0.60
    #: TTC 를 0..1 로 눕히는 지평(s). 이 값보다 멀면 기여가 0 이다.
    ttc_horizon_s: float = 4.0

    located: list[ObstacleEvidence] = field(default_factory=list, init=False)
    unlocatable: list[ObstacleEvidence] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.located = [e for e in self.evidences
                        if e.local_xy_m is not None and e.distance_m is not None]
        self.unlocatable = [e for e in self.evidences if e.local_xy_m is None]

    # ── HazardLookup ────────────────────────────────────────────────────────

    def lookup(self, point: tuple[float, float]) -> dict[str, float]:
        """`HazardLookup` 시그니처. 근거가 없으면 `{}` — 0 을 지어내지 않는다."""
        worst, distance = self._worst_near(point)
        if worst is None:
            # 장애물은 없다. 그 방향을 **봤는지**가 남은 질문이다.
            if self.coverage is not None and self.coverage.covers(point):
                # 봤고 비어 있었다 — 이것은 근거다. 장애물이 없으니 `ttc` 는
                # 여전히 넣지 않는다(충돌할 대상이 없으면 TTC 가 없다). 그래서
                # 비어 있는 점과 장애물 옆 점이 **같은 충분도**로 비교된다.
                return {"proximity": 0.0, "group_priority": 0.0, "standoff_deficit": 0.0}
            return {}

        inputs: dict[str, float] = {
            # 얼마나 바짝 지나가는가(반경 안에서 0..1).
            "proximity": _unit(1.0 - distance / self.influence_radius_m),
            # 사람이 상자보다 먼저다. 그 순서는 taxonomy 선언이 정한다.
            "group_priority": self.taxonomy.priority_norm(worst.group),
        }
        # 정지 임계값 대비 얼마나 가까운 장애물인가.
        if worst.distance_m is not None and worst.near_threshold_m > 0:
            inputs["standoff_deficit"] = _unit(
                1.0 - worst.distance_m / worst.near_threshold_m)
        # TTC 는 접근 속도가 있을 때만 존재한다 — 없으면 **키 자체를 넣지 않는다**.
        if worst.ttc_s is not None and self.ttc_horizon_s > 0:
            inputs["ttc"] = _unit(1.0 - worst.ttc_s / self.ttc_horizon_s)
        return inputs

    def worst_evidence_near(self, point: tuple[float, float]) -> ObstacleEvidence | None:
        """그 점의 위험을 **무엇이** 만들었는가. 운영자에게 사유로 보여줄 근거다."""
        return self._worst_near(point)[0]

    # ── 결손 사실 ────────────────────────────────────────────────────────────

    @property
    def comparable(self) -> bool:
        """후보끼리 **비교해도 되는 장인가**. 커버리지를 모르면 거짓이다."""
        return self.coverage is not None and self.coverage.is_declared

    @property
    def unlocatable_count(self) -> int:
        """봤지만 자리를 못 찾은 장애물 수. 0 과 "장애물이 없었다"는 다르다."""
        return len(self.unlocatable)

    @property
    def unlocatable_reasons(self) -> dict[str, int]:
        """왜 자리를 못 찾았는지 사유별 집계 — 다음에 무엇을 고칠지가 여기서 나온다."""
        out: dict[str, int] = {}
        for e in self.unlocatable:
            key = e.distance_reason or "unknown"
            out[key] = out.get(key, 0) + 1
        return out

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _worst_near(self, point):
        px, py = point
        near = []
        for e in self.located:
            ex, ey = e.local_xy_m
            d = math.hypot(px - ex, py - ey)
            if d <= self.influence_radius_m:
                near.append((d, e))
        if not near:
            return None, None
        # 우선순위가 높은 쪽이 먼저, 같으면 가까운 쪽. 같은 입력에 같은 답이
        # 나오도록 마지막에 id 로 끊는다(AI-C-13: 임의 선택을 하지 않는다).
        d, worst = min(near, key=lambda c: (-self.taxonomy.priority_norm(c[1].group),
                                            c[0], c[1].evidence_id))
        return worst, d


def scored_candidates(candidates, field: HazardField, scorer):
    """후보를 채점한다 — **비교할 수 없는 장이면 거절한다**.

    `(평가 목록, 거절 사유)`. 커버리지를 모르는 장으로 채점하면 장애물 옆을
    지나는 후보만 근거를 얻어 그 쪽이 선택된다. 이 함수를 거치면 그 조합이
    조용히 성립하지 않는다 — 호출자가 직접 조립하면 여전히 성립하므로, 조립을
    여기 한 곳에 둔다.
    """
    from risk.path_evaluation import PathCandidate, PathCandidateRiskEvaluator

    if not field.comparable:
        return [], REASON_COVERAGE_UNKNOWN

    evaluator = PathCandidateRiskEvaluator(scorer, field.lookup)
    out = []
    for c in candidates:
        probe = getattr(c, "hazard_probe_points", None)
        out.append(evaluator.evaluate(
            c if probe is not None and isinstance(c, PathCandidate)
            else PathCandidate(c.candidate_id, probe or ())))
    return out, None


def _bearing_in(bearing: float, lo: float, hi: float) -> bool:
    """0°/360° 를 넘어가는 구간도 받는다."""
    lo %= 360.0
    hi %= 360.0
    if lo <= hi:
        return lo <= bearing <= hi
    return bearing >= lo or bearing <= hi


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
