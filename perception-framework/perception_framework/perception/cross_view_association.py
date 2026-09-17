"""Global-trajectory-first cross-view matching (AI-S-02).

implements: AI-S-02

reproduces (decision shape only, not the neural architecture): GMT, CVPR 2026
(docs/obsidian/papers/gmt.md). GMT's verified core claim (gmt.md §3
"Global-first" 재정식화, confirmed against the original paper text: "instead
of assigning trajectories independently for each view, GMT directly encodes
the same historical targets across different views as global trajectories
... 2) The unnecessary cross-view matching is avoided by directly
determining which global trajectory the new targets belong to") is a
*problem reformulation*, not a specific network: traditional multi-camera
tracking runs single-camera tracking first and only uses other cameras to
patch missed matches afterwards (pairwise, per-view, after the fact); GMT
instead builds one aggregated multi-view trajectory representation per
physical object FIRST, then matches every new single-view observation
directly against that aggregate.

This module reproduces exactly that reformulation as a decision rule:
`GlobalTrajectoryAssociator` keeps one rolling aggregate (mean position,
mean appearance embedding, both over the last `max_history` contributing
observations from ANY camera) per known object and matches new
`ObservedTrack`s against those aggregates — never against another
camera's individual raw track pairwise. It does NOT reproduce GMT's actual
mechanism for computing that aggregate and its match scores: no
CFCE (VFCE metric-learning projection + RPCE relative-position graph with
distance-based neighbor filtering) and no GTA (DETR encoder-decoder +
learned trajectory/target cross-attention + Hungarian assignment + a
memory bank for long-occlusion recovery). Matching here is a fixed
similarity threshold on hand-computed features (position distance,
cosine similarity of a pre-existing appearance embedding), the same
"reproduce interface/decision shape, not paper accuracy" discipline
`simulation/pose_graph_alignment.py` documents for CoAlign — no detector,
no DETR, no learned metric space is implemented or claimed.

Gating is intentionally a hard AND over whichever signals both the
observation and the trajectory's aggregate actually carry (skip a signal
entirely if either side lacks it, but never let one bad signal be
outvoted by an unrelated good one): `MultiObservationAssociator`
(association.py) accepts a link once *any* `min_basis_count`-many signals
individually clear their own threshold, which is the right posture for
"is this the same object across two independent, possibly signal-poor
observations". This module's decision is different in kind: the whole
point under test here (gmt.md's demonstrated advantage) is that averaging
several views' evidence makes ONE signal (appearance) more trustworthy on
its own than any single view's raw reading of it — softly averaging in a
low-confidence position or appearance failure would mask exactly the
robustness gain being reproduced, so every signal present on both sides
must individually clear its threshold or the whole comparison is
rejected. A trajectory with no comparable signal at all against the new
observation can never be judged a match (there is nothing to aggregate
confidence from), so it is skipped rather than guessed.
"""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass

from perception_framework.perception.association import ObservedTrack


def _cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _mean_position(positions: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not positions:
        return None
    n = len(positions)
    return (sum(p[0] for p in positions) / n, sum(p[1] for p in positions) / n)


def _mean_embedding(embeddings: list[tuple[float, ...]]) -> tuple[float, ...] | None:
    if not embeddings:
        return None
    dim = len(embeddings[0])
    n = len(embeddings)
    return tuple(sum(e[i] for e in embeddings) / n for i in range(dim))


@dataclass(frozen=True)
class GlobalTrajectoryMatch:
    """Result of comparing one new single-view observation against every
    known global trajectory's aggregate. `trajectory_id=None` means no
    aggregate cleared both gates -- the caller (AI-S-02 integration point,
    e.g. multisource.py) should treat this as "start a new trajectory",
    the same graceful-no-match posture `SelectionResult(provider=None)`
    uses in selection/selector.py rather than raising.
    """

    trajectory_id: str | None
    score: float
    reason: str


class _TrajectoryAggregate:
    """Rolling aggregate for one global trajectory: the mean position and
    mean appearance embedding over up to `max_history` most recent
    contributing observations, regardless of which camera contributed
    them. This -- an aggregate built across cameras before any new
    observation arrives -- is the exact object GMT's GTA module encodes
    (as `Γ`, gmt.md §3) before matching; here it is a plain running mean
    rather than a learned encoder.
    """

    def __init__(self, max_history: int) -> None:
        self._positions: deque[tuple[float, float]] = deque(maxlen=max_history)
        self._embeddings: deque[tuple[float, ...]] = deque(maxlen=max_history)

    def add(self, observation: ObservedTrack) -> None:
        if observation.global_position is not None:
            self._positions.append(observation.global_position)
        if observation.appearance_embedding is not None:
            self._embeddings.append(observation.appearance_embedding)

    @property
    def position(self) -> tuple[float, float] | None:
        return _mean_position(list(self._positions))

    @property
    def embedding(self) -> tuple[float, ...] | None:
        return _mean_embedding(list(self._embeddings))


class GlobalTrajectoryAssociator:
    """Maintains one aggregated feature per known physical object (a
    "global trajectory") built from every camera that has contributed to
    it, and matches new single-camera `ObservedTrack`s against those
    aggregates directly -- never against other cameras' raw per-view
    tracks pairwise. That pairwise/after-the-fact design is exactly the
    two-stage (single-camera tracking, then inter-camera patching)
    baseline GMT's paper replaces (gmt.md §2, §3).

    `position_threshold_m` and `appearance_threshold` are real gates, not
    scoring inputs alone: a candidate trajectory is rejected outright the
    moment any signal both sides carry fails its own threshold (see
    module docstring for why this is a hard AND rather than
    `association.py`'s softer `min_basis_count` posture).
    """

    def __init__(
        self,
        *,
        position_threshold_m: float = 2.0,
        appearance_threshold: float = 0.3,
        max_history: int = 5,
    ) -> None:
        self._position_threshold_m = position_threshold_m
        self._appearance_threshold = appearance_threshold
        self._max_history = max_history
        self._trajectories: dict[str, _TrajectoryAggregate] = {}
        self._id_source = itertools.count(1)

    def associate(self, observation: ObservedTrack) -> GlobalTrajectoryMatch:
        best_id: str | None = None
        best_score = -1.0
        best_reason = "no existing global trajectory shared a comparable signal"

        for trajectory_id, aggregate in self._trajectories.items():
            signal_scores: list[float] = []
            signals_used: list[str] = []
            rejected_signal: str | None = None

            agg_position = aggregate.position
            if observation.global_position is not None and agg_position is not None:
                dist = _euclidean(observation.global_position, agg_position)
                if dist > self._position_threshold_m:
                    rejected_signal = f"position {dist:.2f}m > {self._position_threshold_m}m gate"
                else:
                    signals_used.append("position")
                    signal_scores.append(1.0 - dist / self._position_threshold_m)

            agg_embedding = aggregate.embedding
            if rejected_signal is None and observation.appearance_embedding is not None and agg_embedding is not None:
                sim = _cosine_similarity(observation.appearance_embedding, agg_embedding)
                if sim < self._appearance_threshold:
                    rejected_signal = f"appearance similarity {sim:.3f} < {self._appearance_threshold} gate"
                else:
                    signals_used.append("appearance")
                    signal_scores.append(sim)

            if rejected_signal is not None:
                if best_id is None:
                    best_reason = f"{trajectory_id} rejected: {rejected_signal}"
                continue
            if not signals_used:
                continue

            score = sum(signal_scores) / len(signal_scores)
            if score > best_score:
                best_id = trajectory_id
                best_score = score
                best_reason = f"matched on {tuple(signals_used)} against aggregate, score={score:.3f}"

        if best_id is None:
            return GlobalTrajectoryMatch(trajectory_id=None, score=0.0, reason=best_reason)
        return GlobalTrajectoryMatch(trajectory_id=best_id, score=best_score, reason=best_reason)

    def start_trajectory(self, observation: ObservedTrack) -> str:
        trajectory_id = f"gtraj-{next(self._id_source)}"
        aggregate = _TrajectoryAggregate(self._max_history)
        aggregate.add(observation)
        self._trajectories[trajectory_id] = aggregate
        return trajectory_id

    def update_trajectory(self, trajectory_id: str, observation: ObservedTrack) -> None:
        self._trajectories[trajectory_id].add(observation)
