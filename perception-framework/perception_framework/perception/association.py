"""Selective multi-observation association across independent sources (AI-S-02).

implements: AI-S-01, AI-S-02

Complements per-source tracks (AI-S-01): when time, global position and
an appearance descriptor happen to be available for two tracks from
different sources, they may be linked as the same physical object. Any
of these signals may be missing entirely (single camera, no ReID
embedding, no global coordinates, no precise time sync) — this
evaluator only uses whichever signals both observations actually carry,
rather than requiring all of them or refusing to compare at all
(AI-S-02: "복수 카메라, ReID, 전역 좌표, 정밀 시간 동기화는 모두 선택
기능이며 하나라도 없다고 전체 추적을 중단해서는 안 된다").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObservedTrack:
    source_id: str
    track_local_id: int
    observed_at: float | None = None
    global_position: tuple[float, float] | None = None
    appearance_embedding: tuple[float, ...] | None = None


def _cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@dataclass(frozen=True)
class AssociationResult:
    linked: bool
    score: float
    basis: tuple[str, ...]  # which evidence kinds actually contributed


class MultiObservationAssociator:
    def __init__(
        self,
        *,
        time_window_s: float = 0.5,
        position_threshold_m: float = 2.0,
        appearance_threshold: float = 0.7,
        min_basis_count: int = 1,
        link_score_threshold: float = 0.5,
    ) -> None:
        self._time_window_s = time_window_s
        self._position_threshold_m = position_threshold_m
        self._appearance_threshold = appearance_threshold
        self._min_basis_count = min_basis_count
        self._link_score_threshold = link_score_threshold

    def associate(self, a: ObservedTrack, b: ObservedTrack) -> AssociationResult:
        if a.source_id == b.source_id:
            raise ValueError("association is only meaningful across independent sources")

        basis: list[str] = []
        scores: list[float] = []

        if a.observed_at is not None and b.observed_at is not None:
            dt = abs(a.observed_at - b.observed_at)
            if dt <= self._time_window_s:
                basis.append("time")
                scores.append(1.0 - dt / self._time_window_s)

        if a.global_position is not None and b.global_position is not None:
            dx = a.global_position[0] - b.global_position[0]
            dy = a.global_position[1] - b.global_position[1]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= self._position_threshold_m:
                basis.append("space")
                scores.append(1.0 - dist / self._position_threshold_m)

        if a.appearance_embedding is not None and b.appearance_embedding is not None:
            sim = _cosine_similarity(a.appearance_embedding, b.appearance_embedding)
            if sim >= self._appearance_threshold:
                basis.append("appearance")
                scores.append(sim)

        if len(basis) < self._min_basis_count:
            return AssociationResult(linked=False, score=0.0, basis=tuple(basis))

        avg_score = sum(scores) / len(scores)
        return AssociationResult(linked=avg_score >= self._link_score_threshold, score=avg_score, basis=tuple(basis))
