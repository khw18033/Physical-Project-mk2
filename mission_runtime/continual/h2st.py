"""H2ST-style task identity decisions using exact two-sample tests.

implements: AI-L-01

This is a small, deterministic feature-level validation component, not the
paper's learned source-target classifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class H2STDecision:
    """Result of the cascading hypothesis tests."""

    in_distribution: bool
    task_id: str | None
    p_values: tuple[tuple[str, float], ...]


class HierarchicalTwoSampleDetector:
    """Cascades task references and early-exits on the first non-rejection.

    ``alpha`` is a statistical significance level, not a tuned OOD score
    threshold. Exact label permutations make results deterministic.
    """

    def __init__(self, *, alpha: float = 0.05, max_exact_partitions: int = 50_000) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be between zero and one")
        self.alpha = alpha
        self.max_exact_partitions = max_exact_partitions
        self._tasks: list[tuple[str, np.ndarray]] = []

    def add_task(self, task_id: str, reference_features: Iterable[Iterable[float]]) -> None:
        features = _feature_matrix(reference_features)
        if any(existing == task_id for existing, _ in self._tasks):
            raise ValueError(f"duplicate task_id: {task_id}")
        self._tasks.append((task_id, features))

    def decide(self, target_features: Iterable[Iterable[float]]) -> H2STDecision:
        target = _feature_matrix(target_features)
        tested: list[tuple[str, float]] = []
        for task_id, source in self._tasks:
            if source.shape[1] != target.shape[1]:
                raise ValueError("source and target feature dimensions differ")
            p_value = _exact_permutation_p_value(source, target, self.max_exact_partitions)
            tested.append((task_id, p_value))
            if p_value >= self.alpha:
                return H2STDecision(True, task_id, tuple(tested))
        return H2STDecision(False, None, tuple(tested))


def _feature_matrix(values: Iterable[Iterable[float]]) -> np.ndarray:
    matrix = np.asarray(tuple(tuple(row) for row in values), dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] == 0:
        raise ValueError("features must be a non-empty 2-D sample with at least two rows")
    if not np.isfinite(matrix).all():
        raise ValueError("features must contain finite values")
    return matrix


def _statistic(left: np.ndarray, right: np.ndarray) -> float:
    """Squared distance between means, scaled by pooled feature variance."""

    pooled = np.vstack((left, right))
    variance = np.var(pooled, axis=0) + 1e-12
    return float(np.sum((np.mean(left, axis=0) - np.mean(right, axis=0)) ** 2 / variance))


def _exact_permutation_p_value(source: np.ndarray, target: np.ndarray, limit: int) -> float:
    pooled = np.vstack((source, target))
    source_size = len(source)
    partition_count = comb(len(pooled), source_size)
    if partition_count > limit:
        raise ValueError(
            f"exact test needs {partition_count} partitions; reduce the validation fixture"
        )
    observed = _statistic(source, target)
    extreme = 0
    indices = range(len(pooled))
    for selected in combinations(indices, source_size):
        selected_set = set(selected)
        left = pooled[list(selected)]
        right = pooled[[index for index in indices if index not in selected_set]]
        extreme += _statistic(left, right) >= observed - 1e-12
    return extreme / partition_count
