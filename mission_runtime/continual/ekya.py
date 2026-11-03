"""Ekya-style micro-profile and deterministic resource allocation policy.

implements: AI-L-04, AI-L-06, AI-L-07

Inputs are precomputed profile observations. This module schedules validation
fixtures and never launches training or controls a GPU directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MicroProfile:
    config_id: str
    sampled_fraction: float
    current_accuracy: float
    projected_accuracy: float
    estimated_seconds: float

    @property
    def gain(self) -> float:
        return max(0.0, self.projected_accuracy - self.current_accuracy)

    @property
    def gain_per_second(self) -> float:
        return self.gain / self.estimated_seconds


@dataclass(frozen=True)
class ResourceJob:
    job_id: str
    profiles: tuple[MicroProfile, ...]
    minimum_chunks: int = 0


class ResourceAllocator:
    """Chooses a micro-profile and allocates fixed chunks by marginal utility."""

    def allocate(self, jobs: tuple[ResourceJob, ...], *, total_chunks: int) -> dict[str, tuple[str, int]]:
        if total_chunks < 0 or any(not job.profiles for job in jobs):
            raise ValueError("total_chunks must be non-negative and every job needs a profile")
        if sum(job.minimum_chunks for job in jobs) > total_chunks:
            raise ValueError("minimum allocations exceed available resources")
        chosen = {
            job.job_id: max(job.profiles, key=lambda p: (p.gain_per_second, p.config_id)) for job in jobs
        }
        chunks = {job.job_id: job.minimum_chunks for job in jobs}
        remaining = total_chunks - sum(chunks.values())
        for _ in range(remaining):
            # Diminishing return approximates contention while retaining a fully
            # deterministic, auditable allocation policy.
            winner = max(
                jobs,
                key=lambda job: (
                    chosen[job.job_id].gain_per_second / (chunks[job.job_id] + 1),
                    job.job_id,
                ),
            )
            chunks[winner.job_id] += 1
        return {job.job_id: (chosen[job.job_id].config_id, chunks[job.job_id]) for job in jobs}
