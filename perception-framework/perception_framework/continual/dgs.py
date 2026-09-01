"""DGS-style dynamic grouping and adapter-state consolidation.

implements: AI-L-04, AI-L-05

The vectors represent adapter state fixtures; no model parameters are trained.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class TaskGroup:
    group_id: str
    task_ids: tuple[str, ...]
    mean: tuple[float, ...]
    variance: tuple[float, ...]
    adapter_state: tuple[float, ...]


class DynamicTaskGrouper:
    """Assigns Gaussian task summaries by symmetric KL divergence."""

    def __init__(self, *, divergence_max: float = 1.0) -> None:
        if divergence_max < 0:
            raise ValueError("divergence_max must be non-negative")
        self.divergence_max = divergence_max
        self.groups: list[TaskGroup] = []

    def assign(
        self,
        task_id: str,
        features: Iterable[Iterable[float]],
        adapter_state: Iterable[float],
        *,
        consolidation_weight: float = 0.5,
    ) -> TaskGroup:
        if not 0 <= consolidation_weight <= 1:
            raise ValueError("consolidation_weight must be in [0, 1]")
        matrix = np.asarray(tuple(tuple(row) for row in features), dtype=float)
        state = np.asarray(tuple(adapter_state), dtype=float)
        if matrix.ndim != 2 or len(matrix) < 2 or state.ndim != 1:
            raise ValueError("features need two rows and adapter_state must be a vector")
        mean = np.mean(matrix, axis=0)
        variance = np.var(matrix, axis=0) + 1e-9
        if len(state) == 0 or not np.isfinite(matrix).all() or not np.isfinite(state).all():
            raise ValueError("task summaries must be finite and non-empty")

        eligible = [
            (self._divergence(mean, variance, group), index)
            for index, group in enumerate(self.groups)
            if len(group.mean) == len(mean) and len(group.adapter_state) == len(state)
        ]
        best = min(eligible, default=None)
        if best is None or best[0] > self.divergence_max:
            group = TaskGroup(
                f"group-{len(self.groups) + 1}", (task_id,), tuple(mean), tuple(variance), tuple(state)
            )
            self.groups.append(group)
            return group

        _, index = best
        current = self.groups[index]
        weight = consolidation_weight
        merged_state = weight * np.asarray(current.adapter_state) + (1 - weight) * state
        count = len(current.task_ids)
        merged_mean = (np.asarray(current.mean) * count + mean) / (count + 1)
        merged_variance = (np.asarray(current.variance) * count + variance) / (count + 1)
        updated = replace(
            current,
            task_ids=current.task_ids + (task_id,),
            mean=tuple(merged_mean),
            variance=tuple(merged_variance),
            adapter_state=tuple(merged_state),
        )
        self.groups[index] = updated
        return updated

    @staticmethod
    def _divergence(mean: np.ndarray, variance: np.ndarray, group: TaskGroup) -> float:
        other_mean = np.asarray(group.mean)
        other_variance = np.asarray(group.variance)

        def kl(m1: np.ndarray, v1: np.ndarray, m2: np.ndarray, v2: np.ndarray) -> float:
            return float(0.5 * np.sum(np.log(v2 / v1) + (v1 + (m1 - m2) ** 2) / v2 - 1))

        return 0.5 * (kl(mean, variance, other_mean, other_variance) + kl(other_mean, other_variance, mean, variance))
