"""Gates coverage blind spots into re-observation requests by net reward
(information gain minus cost), so a low-value gap never triggers a request
merely because it exists (AI-S-05, AI-E-04).

implements: AI-S-05, AI-S-03

The gate itself — activate only when gain exceeds cost — reproduces the
*decision rule* of the closest literature match found for this experiment
(`docs/obsidian/papers/perceive-what-matters.md`, ICRA 2026: "module m_j is
activated if and only if rho_kj > 0"), not that paper's learned reward
model, its YOLO/MMPose modules, or its reported numbers — same "reproduce
the observable decision shape, not paper accuracy" discipline this project
already applies in `selection/research_execution_baselines.py`
(see `docs/obsidian/papers/README.md` 그룹 A).

This module only decides *whether a blind spot is worth asking about*; it
hands the ones that clear the gate to `decision.info_request`'s existing
`EvidenceNeed`/`DecisionSupportRequester` machinery to decide *which
capability actually answers it* — capability selection is not duplicated
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from perception_framework.decision.info_request import EvidenceNeed
from perception_framework.perception.coverage import BlindSpot, BlindSpotCause


@dataclass(frozen=True)
class ReobservationCandidate:
    """One blind spot's re-observation reward, before any capability is
    chosen to act on it."""

    region_id: str
    cause: BlindSpotCause
    expected_gain: float
    cost: float

    @property
    def net_reward(self) -> float:
        return self.expected_gain - self.cost

    @property
    def worth_requesting(self) -> bool:
        return self.net_reward > 0.0


def default_gain(spot: BlindSpot) -> float:
    """Reference gain proxy — deliberately simple and swappable, same
    posture as `perception/detection.py`'s `BrightBlobDetector` (a
    reference provider that proves the interface, not an accuracy claim).

    NO_SOURCE/INCOMPLETE: nothing usable has ever accounted for the
    uncovered share, so that share is what re-observing would gain.
    OCCLUDED/SOURCE_FAILURE/STALE: coverage existed and is now stranded, so
    what is at stake is however much of the region that stranded coverage
    used to account for — a region that was fully covered and then failed
    has more to lose than one that was always thin.
    """
    if spot.cause in (BlindSpotCause.NO_SOURCE, BlindSpotCause.INCOMPLETE):
        return max(0.0, 1.0 - spot.observed_fraction)
    return spot.observed_fraction if spot.observed_fraction > 0.0 else 1.0


class ReobservationPolicy:
    """Ranks blind spots by net reward and turns the ones worth acting on
    into `EvidenceNeed`s for `decision.info_request.DecisionSupportRequester`.
    """

    def __init__(self, *, gain_fn: Callable[[BlindSpot], float] = default_gain) -> None:
        self._gain_fn = gain_fn

    def rank(
        self,
        blind_spots: Sequence[BlindSpot],
        cost_fn: Callable[[BlindSpot], float],
    ) -> list[ReobservationCandidate]:
        """`cost_fn` is required, not defaulted: unlike gain (a property of
        the blind spot itself), cost depends on this deployment's actual
        re-observation mechanism (a PTZ turn vs. a robot dispatch vs. a
        static camera that simply cannot help) and must never be invented
        here (AI-B-01: 다른 구성에서 측정한 비용을 그대로 가져다 쓰지 않는다).
        """
        candidates = [
            ReobservationCandidate(spot.region_id, spot.cause, self._gain_fn(spot), cost_fn(spot))
            for spot in blind_spots
        ]
        # Worth-requesting first; within that, highest net reward first;
        # region_id breaks ties so the ordering is deterministic.
        return sorted(candidates, key=lambda c: (not c.worth_requesting, -c.net_reward, c.region_id))

    def to_evidence_needs(
        self,
        candidates: Sequence[ReobservationCandidate],
        candidate_capability_kinds: tuple[str, ...],
    ) -> list[EvidenceNeed]:
        """Only candidates clearing the reward gate become requests.

        This is AI-S-05's "필요한 근거가 확보되면 추가 실행을 중단"/AI-E-04's
        "근거가 확보되면 추가 실행을 중단" applied to blind spots specifically:
        a gap that would cost more to re-check than it is worth is simply
        left as a known, reported gap (`unresolved`, downstream in
        `DecisionSupportRequester.plan`) rather than requested — it is not
        an error, it is the explicit "부족한 근거 명시" the requirement
        demands.
        """
        return [
            EvidenceNeed(
                evidence_id=f"reobserve:{c.region_id}",
                candidate_capability_kinds=candidate_capability_kinds,
            )
            for c in candidates
            if c.worth_requesting
        ]
