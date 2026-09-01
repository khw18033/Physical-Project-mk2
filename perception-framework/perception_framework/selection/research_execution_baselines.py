"""Deterministic functional baselines inspired by execution research.

implements: AI-B-01, AI-B-04, AI-B-06, AI-B-08, AI-O-01, AI-C-04,
AI-C-09, AI-C-12, AI-C-13

These policies reproduce *interfaces and decision shapes*, not the papers'
reported accuracy or performance.  They are deliberately vendor-neutral and
side-effect free so an experiment can freeze inputs and audit every decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable


FeatureMap = Mapping[str, float]


@runtime_checkable
class LatencyPredictor(Protocol):
    """nn-Meter-style adapter boundary for a hardware latency predictor."""

    def predict_ms(self, model_features: FeatureMap, context: FeatureMap) -> float:
        """Return a finite, non-negative latency estimate in milliseconds."""


@dataclass(frozen=True)
class CallableLatencyPredictor:
    """Adapt a pure prediction callable without importing an ML runtime."""

    predictor: Callable[[FeatureMap, FeatureMap], float]

    def predict_ms(self, model_features: FeatureMap, context: FeatureMap) -> float:
        value = float(self.predictor(model_features, context))
        if value < 0 or value != value or value == float("inf"):
            raise ValueError("latency prediction must be finite and non-negative")
        return value


@dataclass(frozen=True)
class ApproximationProfile:
    """ApproxDet-style five-knob configuration and its quality estimate."""

    profile_id: str
    resolution_scale: float
    proposal_count: int
    tracker_scale: float
    detector_interval: int
    model_scale: float
    expected_quality: float
    model_features: FeatureMap

    def __post_init__(self) -> None:
        if not self.profile_id or self.proposal_count <= 0 or self.detector_interval <= 0:
            raise ValueError("profile id and positive discrete knobs are required")
        if min(self.resolution_scale, self.tracker_scale, self.model_scale) <= 0:
            raise ValueError("scale knobs must be positive")


@dataclass(frozen=True)
class ApproxDetDecision:
    profile: ApproximationProfile
    predicted_latency_ms: float
    sla_met: bool
    reason: str


class ApproxDetSlaPolicy:
    """Choose highest estimated quality satisfying latency and optional load SLA."""

    def __init__(self, predictor: LatencyPredictor) -> None:
        self._predictor = predictor

    def select(
        self,
        profiles: Sequence[ApproximationProfile],
        *,
        context: FeatureMap,
        max_latency_ms: float,
        max_load: float | None = None,
    ) -> ApproxDetDecision:
        if not profiles or max_latency_ms < 0:
            raise ValueError("profiles and a non-negative latency SLA are required")
        estimates = [(p, self._predictor.predict_ms(p.model_features, context)) for p in profiles]
        load_ok = max_load is None or float(context.get("system_load", 0.0)) <= max_load
        feasible = [(p, latency) for p, latency in estimates if latency <= max_latency_ms and load_ok]
        if feasible:
            profile, latency = max(feasible, key=lambda item: (item[0].expected_quality, -item[1], item[0].profile_id))
            return ApproxDetDecision(profile, latency, True, "highest_quality_within_sla")
        profile, latency = min(estimates, key=lambda item: (item[1], -item[0].expected_quality, item[0].profile_id))
        return ApproxDetDecision(profile, latency, False, "minimum_latency_fallback")


@dataclass(frozen=True)
class DaccDecision:
    execution_site: str
    estimated_latency_ms: float
    reason: str


class DaccOffloadPolicy:
    """DACC-style content-aware local/offload decision with explicit estimates."""

    def decide(
        self,
        *,
        content_complexity: float,
        local_latency_ms: float,
        remote_compute_ms: float,
        payload_mib: float,
        bandwidth_mib_s: float,
        round_trip_ms: float,
        max_latency_ms: float,
        remote_available: bool = True,
    ) -> DaccDecision:
        values = (content_complexity, local_latency_ms, remote_compute_ms, payload_mib,
                  bandwidth_mib_s, round_trip_ms, max_latency_ms)
        if any(v < 0 for v in values) or content_complexity > 1:
            raise ValueError("inputs must be non-negative and complexity must be in [0, 1]")
        local = local_latency_ms * (1.0 + content_complexity)
        if not remote_available or bandwidth_mib_s == 0:
            return DaccDecision("local", local, "remote_unavailable")
        remote = round_trip_ms + remote_compute_ms * (1.0 + 0.25 * content_complexity) + payload_mib / bandwidth_mib_s * 1000.0
        candidates = [("local", local), ("remote", remote)]
        feasible = [item for item in candidates if item[1] <= max_latency_ms]
        site, latency = min(feasible or candidates, key=lambda item: (item[1], item[0]))
        reason = "lowest_latency_within_sla" if feasible else "lowest_latency_fallback"
        return DaccDecision(site, latency, reason)


@dataclass(frozen=True)
class OctopinfDecision:
    batch_size: int
    colocate: bool
    predicted_latency_ms: float
    reason: str


class OctopinfPlacementPolicy:
    """OCTOPINF-style deterministic batching and co-location baseline."""

    def decide(
        self,
        *,
        queue_depth: int,
        per_item_ms: float,
        batch_sizes: Sequence[int],
        max_latency_ms: float,
        available_memory_mib: float,
        memory_per_item_mib: float,
        transfer_ms: float,
    ) -> OctopinfDecision:
        if queue_depth < 0 or not batch_sizes or any(v < 0 for v in (per_item_ms, max_latency_ms, available_memory_mib, memory_per_item_mib, transfer_ms)):
            raise ValueError("non-negative inputs and at least one batch size are required")
        candidates: list[tuple[int, bool, float]] = []
        for batch in sorted(set(batch_sizes)):
            if batch <= 0 or batch * memory_per_item_mib > available_memory_mib:
                continue
            effective = min(batch, max(1, queue_depth))
            compute = per_item_ms * effective * (0.7 + 0.3 / effective)
            for colocate in (True, False):
                candidates.append((batch, colocate, compute + (0.0 if colocate else transfer_ms)))
        if not candidates:
            raise ValueError("no batch fits the available memory")
        feasible = [item for item in candidates if item[2] <= max_latency_ms]
        # Within SLA maximize throughput (batch), then minimize latency and transfer.
        if feasible:
            batch, colocate, latency = min(feasible, key=lambda item: (-item[0], item[2], not item[1]))
            return OctopinfDecision(batch, colocate, latency, "largest_batch_within_sla")
        batch, colocate, latency = min(candidates, key=lambda item: (item[2], -item[0], not item[1]))
        return OctopinfDecision(batch, colocate, latency, "minimum_latency_fallback")


@dataclass(frozen=True)
class E4Profile:
    profile_id: str
    exit_depth: int
    dvfs_level: int
    expected_quality: float
    latency_ms: float
    energy_mj: float


@dataclass(frozen=True)
class E4Decision:
    profile: E4Profile
    constraints_met: bool
    reason: str


class E4ProfilePolicy:
    """E4-style early-exit/DVFS profile selection from offline measurements."""

    def select(
        self,
        profiles: Sequence[E4Profile],
        *,
        min_quality: float,
        max_latency_ms: float,
        max_energy_mj: float,
    ) -> E4Decision:
        if not profiles or min(min_quality, max_latency_ms, max_energy_mj) < 0:
            raise ValueError("profiles and non-negative constraints are required")
        feasible = [p for p in profiles if p.expected_quality >= min_quality and p.latency_ms <= max_latency_ms and p.energy_mj <= max_energy_mj]
        if feasible:
            chosen = min(feasible, key=lambda p: (p.energy_mj, p.latency_ms, -p.expected_quality, p.profile_id))
            return E4Decision(chosen, True, "minimum_energy_within_constraints")
        # Stable least-violation score; caller can observe constraints_met=False.
        def violation(p: E4Profile) -> tuple[float, float, float, str]:
            quality_gap = max(0.0, min_quality - p.expected_quality) / max(min_quality, 1e-9)
            latency_gap = max(0.0, p.latency_ms - max_latency_ms) / max(max_latency_ms, 1e-9)
            energy_gap = max(0.0, p.energy_mj - max_energy_mj) / max(max_energy_mj, 1e-9)
            return (quality_gap + latency_gap + energy_gap, p.energy_mj, p.latency_ms, p.profile_id)

        return E4Decision(min(profiles, key=violation), False, "least_normalized_constraint_violation")
