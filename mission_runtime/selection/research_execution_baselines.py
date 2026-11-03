"""Deterministic functional baselines inspired by execution research.

implements: AI-B-01, AI-B-04, AI-B-06, AI-B-08, AI-O-01, AI-C-04,
AI-C-09, AI-C-12, AI-C-13

These policies reproduce *interfaces and decision shapes*, not the papers'
reported accuracy or performance.  They are deliberately vendor-neutral and
side-effect free so an experiment can freeze inputs and audit every decision.
"""

from __future__ import annotations

import math
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


@dataclass(frozen=True)
class EdgeBoostDecision:
    offload: bool
    margin: float
    calibrated_probs: tuple[float, ...]
    reason: str


class EdgeBoostOffloadPolicy:
    """EdgeBoost-style (Said & Landsiedel, Computer Networks 2025;
    docs/obsidian/papers/edgeboost.md) selective on-device/edge offload.

    implements: AI-E-04, AI-S-05

    Verified against the paper's own reference implementation
    (`ds-kiel/EdgeBoost` on GitHub) rather than the abstract alone: the
    offload trigger is *not* raw top-1 confidence, calibrated or otherwise
    -- it is the gap between the temperature-scaled top-1 and top-2 class
    probabilities. A model can be "confident" (high top-1) while still
    nearly tied with a second class; margin catches that ambiguity, plain
    top-1 confidence does not.
    """

    def __init__(self, *, temperature: float = 1.0) -> None:
        if temperature <= 0:
            raise ValueError("temperature must be positive")
        self._temperature = temperature

    def calibrate(self, logits: Sequence[float]) -> tuple[float, ...]:
        """Temperature-scaled softmax -- the same calibration family as the
        reference implementation's `torch_uncertainty.TemperatureScaler`.
        Higher temperature flattens the distribution (lower margin for the
        same logits); lower temperature sharpens it.
        """
        if not logits:
            raise ValueError("logits must be non-empty")
        scaled = [v / self._temperature for v in logits]
        peak = max(scaled)
        exps = [math.exp(v - peak) for v in scaled]
        total = sum(exps)
        return tuple(e / total for e in exps)

    def decide(self, logits: Sequence[float], *, margin_threshold: float) -> EdgeBoostDecision:
        probs = self.calibrate(logits)
        ranked = sorted(probs, reverse=True)
        top1 = ranked[0]
        top2 = ranked[1] if len(ranked) > 1 else 0.0
        margin = top1 - top2
        offload = margin < margin_threshold
        reason = "low_confidence_margin" if offload else "margin_within_local_budget"
        return EdgeBoostDecision(offload, margin, probs, reason)


@dataclass(frozen=True)
class Where2commSelection:
    selected_indices: tuple[int, ...]
    total_regions: int
    reason: str

    @property
    def communication_volume(self) -> int:
        return len(self.selected_indices)

    @property
    def reduction_factor(self) -> float:
        """How many times smaller the selected set is than a full broadcast."""
        return self.total_regions / max(1, self.communication_volume)


class Where2commBroadcastPolicy:
    """Where2comm-style (Hu et al., NeurIPS 2022; docs/obsidian/papers/where2comm.md)
    spatially sparse broadcast selection.

    implements: AI-E-04, AI-C-06

    Verified against the full paper text (not the abstract alone): what
    gates a broadcast region is the *sender's own* per-region detection
    confidence, not "does the receiver lack this" -- round 0 selects the
    sender's own top-confidence regions with no receiver input at all.
    Only from round 1 onward does a receiver's request map (1 - its own
    confidence) multiplicatively narrow that same sender-confidence-led
    selection. Framing this as "share whatever the receiver is missing"
    (a natural first reading) is the one specific point the original
    colleague summary got backwards -- this implementation follows the
    verified mechanism, not that framing.
    """

    def _top_k(self, values: Sequence[float], keep_fraction: float) -> tuple[int, ...]:
        if not values:
            return ()
        if not 0.0 < keep_fraction <= 1.0:
            raise ValueError("keep_fraction must be in (0, 1]")
        k = max(1, round(len(values) * keep_fraction))
        ranked = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
        return tuple(sorted(ranked[:k]))

    def select_round0(self, sender_confidence: Sequence[float], *, keep_fraction: float) -> Where2commSelection:
        """First round: gated purely by the sender's own confidence map."""
        indices = self._top_k(sender_confidence, keep_fraction)
        return Where2commSelection(indices, len(sender_confidence), "sender_confidence_top_k")

    def select_round1(
        self,
        sender_confidence: Sequence[float],
        receiver_confidence: Sequence[float],
        *,
        keep_fraction: float,
    ) -> Where2commSelection:
        """Second round: sender confidence times the receiver's request map
        (1 - receiver confidence) -- the receiver only ever *narrows*, it
        never overrides, what the sender was already willing to share.
        """
        if len(sender_confidence) != len(receiver_confidence):
            raise ValueError("sender_confidence and receiver_confidence must be the same length")
        request_map = [1.0 - c for c in receiver_confidence]
        gated = [s * r for s, r in zip(sender_confidence, request_map)]
        indices = self._top_k(gated, keep_fraction)
        return Where2commSelection(indices, len(sender_confidence), "sender_confidence_times_receiver_request")


@dataclass(frozen=True)
class OctoCrossTransferPlan:
    transfers: dict[tuple[str, str], float]
    resulting_load: dict[str, float]
    overloaded_nodes: tuple[str, ...]
    reason: str


class OctoCrossTransferPolicy:
    """OctoCross-style (Cheng et al., ICSOC 2025; docs/obsidian/papers/octocross.md)
    capacity-feasible cross-camera load transfer.

    implements: AI-B-04, AI-B-06

    Verified against the real paper/repo: OctoCross's actual contribution is
    a learned spatiotemporal-attention *load predictor* plus a graph
    topology -- this class reproduces only the downstream decision (given
    already-predicted loads and a topology, compute a capacity-respecting
    transfer plan via iterative proportional fitting / Sinkhorn-style
    row/column rescaling, the same family of numerical projection the
    paper's own `iterative_transfer_projection` uses on top of its learned
    scores), never the predictor itself. Predicted loads and node
    capacities must always be supplied by the caller -- this matches
    AI-B-01's rule that performance/cost measured under one configuration
    must not be assumed to transfer to another; nothing here invents a
    load number.

    Algorithm: for each overloaded node, the excess above capacity (its
    "row target") is split evenly across its allowed outgoing edges, and
    each under-capacity neighbour's incoming total (its "column target")
    is capped at its own headroom. Column caps and row caps are then
    applied alternately -- each pass can only ever shrink a transfer
    amount, never grow it, so the process is monotone and converges within
    a bounded number of passes; `iterations` is an upper bound on how many
    alternating passes are attempted, not a guarantee that every overload
    is resolved. If the reachable topology's total headroom is genuinely
    insufficient, or an overloaded node has no allowed outgoing edge at
    all, the leftover overload is reported honestly in
    `overloaded_nodes` rather than fabricated away.
    """

    def plan(
        self,
        predicted_load: dict[str, float],
        capacity: dict[str, float],
        allowed_edges: set[tuple[str, str]],
        *,
        iterations: int = 20,
    ) -> OctoCrossTransferPlan:
        if not predicted_load or not capacity:
            raise ValueError("predicted_load and capacity are required")
        if set(predicted_load) != set(capacity):
            raise ValueError("predicted_load and capacity must describe the same set of nodes")
        if any(v < 0 for v in predicted_load.values()) or any(v < 0 for v in capacity.values()):
            raise ValueError("predicted loads and capacities must be non-negative")
        if iterations <= 0:
            raise ValueError("iterations must be positive")

        nodes = tuple(predicted_load)
        for frm, to in allowed_edges:
            if frm not in predicted_load or to not in predicted_load:
                raise ValueError("allowed_edges must only reference known nodes")

        excess = {n: max(0.0, predicted_load[n] - capacity[n]) for n in nodes}
        headroom = {n: max(0.0, capacity[n] - predicted_load[n]) for n in nodes}

        outgoing: dict[str, list[str]] = {}
        for frm, to in allowed_edges:
            if excess[frm] > 0.0 and headroom[to] > 0.0:
                outgoing.setdefault(frm, []).append(to)

        edges = [(frm, to) for frm, targets in outgoing.items() for to in targets]
        if not edges:
            overloaded_nodes = tuple(sorted(n for n in nodes if excess[n] > 1e-9))
            reason = "capacity_feasible" if not overloaded_nodes else "no_reachable_headroom"
            return OctoCrossTransferPlan({}, dict(predicted_load), overloaded_nodes, reason)

        out_count: dict[str, int] = {}
        for frm, _to in edges:
            out_count[frm] = out_count.get(frm, 0) + 1
        weight = {(frm, to): excess[frm] / out_count[frm] for frm, to in edges}

        for _ in range(iterations):
            col_sum: dict[str, float] = {}
            for (_frm, to), w in weight.items():
                col_sum[to] = col_sum.get(to, 0.0) + w
            for edge in weight:
                to = edge[1]
                total = col_sum[to]
                if headroom[to] <= 0.0:
                    weight[edge] = 0.0
                elif total > headroom[to]:
                    weight[edge] *= headroom[to] / total

            row_sum: dict[str, float] = {}
            for (frm, _to), w in weight.items():
                row_sum[frm] = row_sum.get(frm, 0.0) + w
            converged = True
            for edge in weight:
                frm = edge[0]
                total = row_sum[frm]
                if excess[frm] > 0.0 and total > excess[frm]:
                    new_w = weight[edge] * excess[frm] / total
                    if abs(new_w - weight[edge]) > 1e-9:
                        converged = False
                    weight[edge] = new_w
            if converged:
                break

        transfers = {edge: amount for edge, amount in weight.items() if amount > 1e-9}
        resulting_load = dict(predicted_load)
        for (frm, to), amount in transfers.items():
            resulting_load[frm] -= amount
            resulting_load[to] += amount

        overloaded_nodes = tuple(sorted(n for n in nodes if resulting_load[n] > capacity[n] + 1e-9))
        reason = "capacity_feasible" if not overloaded_nodes else "insufficient_reachable_capacity"
        return OctoCrossTransferPlan(transfers, resulting_load, overloaded_nodes, reason)
