"""Object-correspondence-driven pose graph correction — a mock of the
*backend/digital-twin's* pose re-alignment, standing in for real SLAM/pose
graph infrastructure the same way `digital_twin.py`'s
`GlobalCoordinateService` stands in for the real global transform.

implements (as a *stand-in* for): DT-03, BE-C-04
reproduces (decision rule only, not the neural pipeline): CoAlign, ICRA 2023
  (docs/obsidian/papers/coalign.md) — its "Agent-Object Pose Graph
  Optimization" module. That module was verified against the original
  paper to be a learned-parameter-free classical least-squares solver
  (g2o + Levenberg-Marquardt over agent-object correspondence residuals),
  which is exactly why it is reproducible here without adopting CoAlign's
  detection backbone (PointPillars) or feature-fusion network at all —
  this module never touches detection, only the poses several agents
  report about themselves.

CoAlign's problem: when several observation agents (fixed cameras, a
patrol robot, ...) each report a *noisy* pose for themselves, naively
placing their local detections into a shared frame using that noisy pose
produces inconsistent/duplicated ("ghost") objects. The fix does not touch
detection quality at all — it only asks "if two agents both claim to see
the same object, where would each agent's own pose have to be for those
two claims to agree?", and solves a small least-squares problem over that
question for every agent except a trusted anchor (a well-calibrated fixed
camera, AI-E-02) whose pose is held fixed as the shared frame's reference —
without at least one anchor the solution is only defined up to an
arbitrary rigid transform of the whole graph.

This module never decides global position on its own initiative for AI
code (AI-C-02: "전역 좌표 변환은 백엔드 디지털 트윈이 담당해야 한다") — it
belongs next to `digital_twin.py` for the same reason that module does,
and consumes object correspondences AI-S-02 (perception/association.py)
would have already proposed rather than re-deciding identity itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class AgentPoseEstimate:
    """One agent's current pose estimate in the shared ground-plane frame.

    An (x, z, yaw) ground-plane pose, matching `digital_twin.py`'s
    `CameraPose` simplification (rotation about the ground normal only).
    `trusted_anchor=True` marks a pose this module must never move — e.g.
    a fixed camera already carrying a validated AI-E-02 calibration
    profile. At least one anchor is required, or the solved graph is only
    correct up to an arbitrary rigid transform of the whole scene.
    """

    agent_id: str
    x_m: float
    z_m: float
    yaw_rad: float
    trusted_anchor: bool = False


@dataclass(frozen=True)
class ObjectSighting:
    """One agent's own local measurement of one candidate shared object.

    `local_x_m`/`local_z_m` are in the agent's own local ground-plane frame
    — exactly what a `perception.detect` provider already outputs before
    any global placement (AI-C-02), so nothing here requires a different
    detector output shape than the rest of the framework already produces.

    `object_id` is *not* asserted to be ground truth identity — it is
    whatever candidate correspondence AI-S-02 already proposed. A wrong
    correspondence here is a data-quality problem this module inherits,
    not one it tries to solve; CoAlign treats correspondence and pose
    correction as two separate steps for the same reason.
    """

    agent_id: str
    object_id: str
    local_x_m: float
    local_z_m: float


def to_world(pose: AgentPoseEstimate, local_x_m: float, local_z_m: float) -> tuple[float, float]:
    """Places one local measurement into the shared frame using `pose`."""
    c, s = math.cos(pose.yaw_rad), math.sin(pose.yaw_rad)
    x = pose.x_m + c * local_x_m - s * local_z_m
    z = pose.z_m + s * local_x_m + c * local_z_m
    return x, z


def _group_by_object(sightings: list[ObjectSighting]) -> dict[str, list[ObjectSighting]]:
    grouped: dict[str, list[ObjectSighting]] = {}
    for s in sightings:
        grouped.setdefault(s.object_id, []).append(s)
    return grouped


def _residual_vector(poses: dict[str, AgentPoseEstimate],
                      grouped: dict[str, list[ObjectSighting]]) -> np.ndarray:
    """Consistency residual: for every object seen by >=2 agents, how far
    apart the agents' own placements of it land in the shared frame — the
    exact quantity CoAlign's pose graph optimization drives to zero.
    """
    residuals: list[float] = []
    for object_sightings in grouped.values():
        if len(object_sightings) < 2:
            continue
        worlds = [to_world(poses[s.agent_id], s.local_x_m, s.local_z_m) for s in object_sightings]
        ref_x, ref_z = worlds[0]
        for x, z in worlds[1:]:
            residuals.append(x - ref_x)
            residuals.append(z - ref_z)
    return np.array(residuals, dtype=float)


def _pack(poses: dict[str, AgentPoseEstimate], free_ids: list[str]) -> np.ndarray:
    return np.array(
        [v for aid in free_ids for v in (poses[aid].x_m, poses[aid].z_m, poses[aid].yaw_rad)],
        dtype=float,
    )


def _unpack(vec: np.ndarray, poses: dict[str, AgentPoseEstimate],
            free_ids: list[str]) -> dict[str, AgentPoseEstimate]:
    updated = dict(poses)
    for i, aid in enumerate(free_ids):
        x, z, yaw = vec[3 * i], vec[3 * i + 1], vec[3 * i + 2]
        updated[aid] = replace(poses[aid], x_m=float(x), z_m=float(z), yaw_rad=float(yaw))
    return updated


def _numerical_jacobian(residual_fn, x: np.ndarray, r0: np.ndarray, eps: float) -> np.ndarray:
    J = np.zeros((r0.size, x.size))
    for j in range(x.size):
        dx = np.zeros_like(x)
        dx[j] = eps
        r1 = residual_fn(x + dx)
        J[:, j] = (r1 - r0) / eps
    return J


def optimize_poses(
    initial_poses: dict[str, AgentPoseEstimate],
    sightings: list[ObjectSighting],
    *,
    iterations: int = 30,
    damping: float = 1e-3,
    jacobian_eps: float = 1e-6,
) -> dict[str, AgentPoseEstimate]:
    """Levenberg-Marquardt-damped Gauss-Newton over agent-object
    correspondence residuals — a dependency-light (numpy only) stand-in
    for CoAlign's g2o solver; same decision rule (minimize cross-agent
    consistency error), not the same library (원칙 #1 — no SLAM backend
    made a core dependency for this).

    Poses with `trusted_anchor=True` are never moved. If nothing is free
    to move (no non-anchor agents), no agent is anchored at all (the
    result would only be correct up to an arbitrary rigid transform, so it
    is refused rather than silently guessed), or there are no cross-agent
    correspondences to begin with, the input is returned unchanged rather
    than raising or drifting — a missing optional correction must degrade
    to "use the reported poses as-is", not fail (AI-C-05 posture, applied
    to this DT-side stand-in).
    """
    poses = dict(initial_poses)
    has_anchor = any(p.trusted_anchor for p in poses.values())
    free_ids = [aid for aid, p in poses.items() if not p.trusted_anchor]
    grouped = _group_by_object(sightings)
    if not has_anchor or not free_ids or not any(len(v) >= 2 for v in grouped.values()):
        return poses

    def residual_fn(vec: np.ndarray) -> np.ndarray:
        return _residual_vector(_unpack(vec, poses, free_ids), grouped)

    x = _pack(poses, free_ids)
    for _ in range(iterations):
        r = residual_fn(x)
        if r.size == 0:
            break
        J = _numerical_jacobian(residual_fn, x, r, jacobian_eps)
        JTJ = J.T @ J + damping * np.eye(x.size)
        JTr = J.T @ r
        try:
            dx = np.linalg.solve(JTJ, JTr)
        except np.linalg.LinAlgError:
            break
        x = x - dx
        if np.linalg.norm(dx) < 1e-9:
            break

    return _unpack(x, poses, free_ids)


# -- robust variant: resists a handful of false cross-agent correspondences --
#
# reproduces (decision rule only): Hydra-Multi, arXiv:2304.13487
# (docs/obsidian/papers/hydra-multi.md) — its "align-optimize-reconcile"
# multi-robot merge step, which the paper credits to Graduated
# Non-Convexity (GNC; Yang et al.) for robustness against bad loop
# closures. This module reproduces only that one property — a handful of
# false correspondences must not drag every agent's corrected pose off —
# via a fixed-schedule iteratively-reweighted least squares using a
# redescending (Cauchy/Lorentzian-style) weight `w = c^2 / (c^2 + r^2)`,
# NOT GNC's own annealed-mu schedule or Hydra-Multi's hierarchical loop
# closure detection (descriptor matching + RANSAC/TEASER++) or its 5-layer
# scene graph structure — none of that infrastructure exists in this
# framework, and none of it is claimed here. Named `optimize_poses_robust`,
# not `..._gnc`, for that reason.

def _correspondence_pairs(
    grouped: dict[str, list[ObjectSighting]],
) -> list[tuple[str, ObjectSighting, ObjectSighting]]:
    """Every object's sightings compared against its own first sighting —
    the same pairing `_residual_vector` uses — returned as identifiable
    units so a robust weight can be attached to each individually.
    """
    pairs: list[tuple[str, ObjectSighting, ObjectSighting]] = []
    for object_id, object_sightings in grouped.items():
        if len(object_sightings) < 2:
            continue
        ref = object_sightings[0]
        for other in object_sightings[1:]:
            pairs.append((object_id, ref, other))
    return pairs


def _weighted_residual_vector(
    poses: dict[str, AgentPoseEstimate],
    pairs: list[tuple[str, ObjectSighting, ObjectSighting]],
    weights: list[float],
) -> np.ndarray:
    residuals: list[float] = []
    for (_object_id, ref, other), w in zip(pairs, weights):
        rx, rz = to_world(poses[ref.agent_id], ref.local_x_m, ref.local_z_m)
        ox, oz = to_world(poses[other.agent_id], other.local_x_m, other.local_z_m)
        sw = math.sqrt(max(w, 0.0))
        residuals.append(sw * (ox - rx))
        residuals.append(sw * (oz - rz))
    return np.array(residuals, dtype=float)


def optimize_poses_robust(
    initial_poses: dict[str, AgentPoseEstimate],
    sightings: list[ObjectSighting],
    *,
    outlier_scale_m: float,
    reweight_rounds: int = 6,
    iterations_per_round: int = 20,
    damping: float = 1e-3,
    jacobian_eps: float = 1e-6,
) -> dict[str, AgentPoseEstimate]:
    """Like `optimize_poses`, but down-weights individual object
    correspondences whose residual stays large after the current best
    fit — e.g. a false cross-agent object match ("this is the same
    person" when it is not) — instead of trusting every correspondence
    equally. `outlier_scale_m` is the residual magnitude (in meters)
    beyond which a correspondence starts losing influence; it must be
    supplied by the caller, not guessed, the same way `ReobservationPolicy`
    requires an explicit cost rather than inventing one (AI-B-01).
    """
    poses = dict(initial_poses)
    has_anchor = any(p.trusted_anchor for p in poses.values())
    free_ids = [aid for aid, p in poses.items() if not p.trusted_anchor]
    grouped = _group_by_object(sightings)
    pairs = _correspondence_pairs(grouped)
    if not has_anchor or not free_ids or not pairs:
        return poses

    weights = [1.0] * len(pairs)
    x = _pack(poses, free_ids)
    c2 = outlier_scale_m ** 2

    for _round in range(reweight_rounds):
        def residual_fn(vec: np.ndarray, w=weights) -> np.ndarray:
            return _weighted_residual_vector(_unpack(vec, poses, free_ids), pairs, w)

        for _ in range(iterations_per_round):
            r = residual_fn(x)
            if r.size == 0:
                break
            J = _numerical_jacobian(residual_fn, x, r, jacobian_eps)
            JTJ = J.T @ J + damping * np.eye(x.size)
            JTr = J.T @ r
            try:
                dx = np.linalg.solve(JTJ, JTr)
            except np.linalg.LinAlgError:
                break
            x = x - dx
            if np.linalg.norm(dx) < 1e-9:
                break

        # Recompute each correspondence's *unweighted* residual at the
        # current fit, then re-derive its weight from that — a
        # correspondence that still disagrees badly loses influence for
        # the next round.
        current_poses = _unpack(x, poses, free_ids)
        new_weights = []
        for object_id, ref, other in pairs:
            rx, rz = to_world(current_poses[ref.agent_id], ref.local_x_m, ref.local_z_m)
            ox, oz = to_world(current_poses[other.agent_id], other.local_x_m, other.local_z_m)
            r2 = (ox - rx) ** 2 + (oz - rz) ** 2
            new_weights.append(c2 / (c2 + r2))
        weights = new_weights

    return _unpack(x, poses, free_ids)
