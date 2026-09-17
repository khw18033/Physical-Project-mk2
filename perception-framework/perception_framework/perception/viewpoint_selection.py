"""Ranks already-worthwhile re-observation candidates by travel cost, so the
one visited next is the one with the best gain-to-cost ratio rather than
simply the highest-gain or lowest-cost candidate (AI-S-05, AI-S-03).

implements: AI-S-05, AI-S-03

Primary source: `docs/obsidian/papers/scout.md` (SCOUT, ICRA 2026 workshop).
SCOUT's Uncertainty-Guided Traversal planner scores each candidate viewpoint
`v` as a *ratio*, not a subtraction of travel cost:

    S_final(v) = (w_cert * S_cert(v) + w_cov * S_cov(v)) / S_travel(v)

(certainty-gain and coverage-gain terms weighted and summed, then divided by
an A*-computed travel cost). This module reproduces that ratio's decision
shape only -- not SCOUT's Grounding-DINO/SAM/CLIP open-vocabulary stack, its
Bayesian label-posterior fusion, or its Gazebo-measured numbers, same
"reproduce the observable decision shape, not paper accuracy" discipline
`perception/reobservation_policy.py` already applies to
`perceive-what-matters.md`.

Informational context only, NOT reproduced: `docs/obsidian/papers/roam.md`
(ROAM, T-RO 2025) frames viewpoint choice as being steered by map
uncertainty / mutual information within a fully distributed
consensus-constrained Riemannian optimization across a robot team --
real manifold-optimization machinery (exponential maps, geodesic distances,
1-hop consensus gradients over SE(3) trajectory manifolds) that this module
does not attempt to reproduce. Only ROAM's high-level framing -- that
uncertainty/information-gain should drive exploration -- is borrowed as
connective narrative; this project already implements that framing more
simply via `perception/coverage.py` (`BlindSpot.uncertainty`,
`observed_fraction`) and `reobservation_policy.py` (the net-reward gate).

Explicitly distinguish from `reobservation_policy.py`: that module asks "is
this blind spot worth requesting re-observation at all" -- a net-reward gate
(`expected_gain - cost > 0`) evaluated per blind spot *independently*, with
no notion of travel cost at all. This module asks a different question that
only makes sense once several blind spots have already cleared that gate:
"given these already-worthwhile candidates and a travel cost to reach each,
which one should be visited first?" It is a ranking *among* candidates, not
a per-candidate accept/reject gate, and it never re-decides whether a
candidate was worth requesting in the first place -- that job stays in
`reobservation_policy.py` and is not duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ViewpointCandidate:
    """One already-worthwhile blind spot, plus what it would cost to reach.

    `certainty_gain` and `coverage_gain` are typically sourced from
    `perception.coverage.BlindSpot` (e.g. `uncertainty` and
    `1 - observed_fraction`) or from a `reobservation_policy
    .ReobservationCandidate.expected_gain` that already cleared the
    worth-requesting gate -- this module does not recompute either.
    `travel_cost` is caller-supplied for the same reason
    `reobservation_policy.rank`'s `cost_fn` is required rather than
    defaulted: it depends on this deployment's actual re-observation
    mechanism and must never be invented here (AI-B-01).
    """

    region_id: str
    certainty_gain: float
    coverage_gain: float
    travel_cost: float


@dataclass(frozen=True)
class ViewpointRanking:
    """One candidate's SCOUT-ratio score, in ranked order."""

    region_id: str
    score: float


class ViewpointSelectionPolicy:
    """Ranks `ViewpointCandidate`s by SCOUT's gain-to-cost ratio.

    `certainty_weight` and `coverage_weight` are not normalized to sum to 1
    (SCOUT's w_cert + w_cov = 1 constraint is a paper-specific convenience,
    not a semantic requirement) -- callers may pass any non-negative
    weights that reflect their deployment's relative priorities.
    """

    def __init__(self, *, certainty_weight: float = 1.0, coverage_weight: float = 1.0) -> None:
        self._certainty_weight = certainty_weight
        self._coverage_weight = coverage_weight

    def rank(self, candidates: Sequence[ViewpointCandidate]) -> list[ViewpointRanking]:
        """score = (certainty_weight*certainty_gain + coverage_weight*coverage_gain)
        / travel_cost, sorted descending by score (ties broken by region_id
        for determinism, same convention as `reobservation_policy.rank`).

        Raises ValueError if any candidate's `travel_cost` is <= 0: a
        candidate with no meaningful cost to reach it is a caller error
        (e.g. the current viewpoint itself, or an unset default), not a
        degraded state to silently paper over -- unlike an *empty*
        candidate set, which `best()` treats as normal (AI-C-05).
        """
        rankings = []
        for c in candidates:
            if c.travel_cost <= 0.0:
                raise ValueError(
                    f"travel_cost must be > 0 for region_id={c.region_id!r}, "
                    f"got {c.travel_cost!r}"
                )
            score = (
                self._certainty_weight * c.certainty_gain
                + self._coverage_weight * c.coverage_gain
            ) / c.travel_cost
            rankings.append(ViewpointRanking(c.region_id, score))
        return sorted(rankings, key=lambda r: (-r.score, r.region_id))

    def best(self, candidates: Sequence[ViewpointCandidate]) -> ViewpointRanking | None:
        """Convenience: `rank(candidates)[0]`, or None if `candidates` is
        empty. An empty candidate set here means every blind spot either
        had no candidates to begin with or was already filtered out
        upstream (e.g. none cleared `reobservation_policy`'s worth-
        requesting gate) -- a normal degraded state, not an error
        (AI-C-05: 선택 조건이나 선택 센서·하드웨어·서비스가 없어지면 가능한
        기본 또는 축소 모드로 전환)."""
        ranked = self.rank(candidates)
        return ranked[0] if ranked else None
