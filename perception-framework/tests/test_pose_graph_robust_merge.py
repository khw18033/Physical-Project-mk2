"""implements: (stand-in for) DT-03, BE-C-04
reproduces (decision rule only): Hydra-Multi, arXiv:2304.13487
(docs/obsidian/papers/hydra-multi.md) — the "resist a bad cross-robot
correspondence" property its GNC-based align-optimize-reconcile merge is
credited with, not its hierarchical loop-closure detection, its 5-layer
scene graph, or GNC's own mu-annealing schedule (none of which exist in
this framework; see the module docstring in
`simulation/pose_graph_alignment.py` for the exact scoping).
tests: naive (equally-weighted) pose graph optimization is measurably
       corrupted by a single false cross-agent object correspondence, while
       the robust (iteratively-reweighted) variant recovers close to the
       outlier-free result despite it
"""
from __future__ import annotations

import math

from perception_framework.simulation.pose_graph_alignment import (
    AgentPoseEstimate, ObjectSighting, optimize_poses, optimize_poses_robust,
)

TRUE_POSES = {
    "anchor": AgentPoseEstimate("anchor", x_m=0.0, z_m=0.0, yaw_rad=0.0, trusted_anchor=True),
    "robot_1": AgentPoseEstimate("robot_1", x_m=6.0, z_m=3.0, yaw_rad=math.radians(20.0)),
    "robot_2": AgentPoseEstimate("robot_2", x_m=-5.0, z_m=7.0, yaw_rad=math.radians(-95.0)),
}

TRUE_OBJECTS = {
    "p1": (1.0, 2.0), "p2": (4.0, 4.5), "p3": (-1.5, 5.0),
    "p4": (2.5, -1.0), "p5": (-3.0, 3.0), "p6": (0.5, 6.0),
}

VISIBILITY = {
    "p1": ("anchor", "robot_1"),
    "p2": ("anchor", "robot_1"),
    "p3": ("anchor", "robot_2"),
    "p4": ("anchor", "robot_1", "robot_2"),
    "p5": ("anchor", "robot_2"),
    "p6": ("anchor", "robot_1", "robot_2"),
}


def _to_local(pose: AgentPoseEstimate, world_x: float, world_z: float) -> tuple[float, float]:
    dx, dz = world_x - pose.x_m, world_z - pose.z_m
    c, s = math.cos(-pose.yaw_rad), math.sin(-pose.yaw_rad)
    return dx * c - dz * s, dx * s + dz * c


def _clean_sightings() -> list[ObjectSighting]:
    sightings = []
    for object_id, (wx, wz) in TRUE_OBJECTS.items():
        for agent_id in VISIBILITY[object_id]:
            lx, lz = _to_local(TRUE_POSES[agent_id], wx, wz)
            sightings.append(ObjectSighting(agent_id, object_id, lx, lz))
    return sightings


def _with_one_false_correspondence() -> list[ObjectSighting]:
    """Same sightings, except robot_1's report of "p6" is secretly a
    measurement of an unrelated point far away -- e.g. a wrong loop
    closure / mismatched object identity from AI-S-02, not a pose error.
    """
    sightings = _clean_sightings()
    fake_world_point = (25.0, -20.0)  # nowhere near the true p6 at (0.5, 6.0)
    fixed = []
    for s in sightings:
        if s.agent_id == "robot_1" and s.object_id == "p6":
            lx, lz = _to_local(TRUE_POSES["robot_1"], *fake_world_point)
            fixed.append(ObjectSighting(s.agent_id, s.object_id, lx, lz))
        else:
            fixed.append(s)
    return fixed


def _pose_error(poses: dict[str, AgentPoseEstimate]) -> float:
    errs = [
        math.hypot(poses[aid].x_m - TRUE_POSES[aid].x_m, poses[aid].z_m - TRUE_POSES[aid].z_m)
        for aid in poses if not poses[aid].trusted_anchor
    ]
    return sum(errs) / len(errs)


def test_clean_correspondences_naive_and_robust_both_recover_ground_truth():
    sightings = _clean_sightings()
    naive = optimize_poses(TRUE_POSES, sightings)
    robust = optimize_poses_robust(TRUE_POSES, sightings, outlier_scale_m=1.0)
    assert _pose_error(naive) < 1e-6
    assert _pose_error(robust) < 1e-6


def test_naive_optimization_is_corrupted_by_a_single_false_correspondence():
    sightings = _with_one_false_correspondence()
    naive = optimize_poses(TRUE_POSES, sightings)
    error = _pose_error(naive)
    print(f"\nnaive (equally-weighted) pose error with 1 bad correspondence: {error:.3f}m")
    # Starting exactly at ground truth, the *only* thing pulling the fit
    # away is the one bad correspondence -- if naive optimization were
    # unaffected by outliers this would stay ~0, which is exactly the
    # failure mode Hydra-Multi's GNC-based merge is meant to avoid.
    assert error > 1.0


def test_robust_optimization_recovers_close_to_ground_truth_despite_the_outlier():
    sightings = _with_one_false_correspondence()
    naive = optimize_poses(TRUE_POSES, sightings)
    robust = optimize_poses_robust(TRUE_POSES, sightings, outlier_scale_m=1.0)

    naive_error = _pose_error(naive)
    robust_error = _pose_error(robust)
    print(
        f"\nwith 1 false correspondence out of 8: "
        f"naive error {naive_error:.3f}m vs robust error {robust_error:.3f}m "
        f"({(1 - robust_error / naive_error) * 100:.1f}% recovered)"
    )

    assert robust_error < naive_error * 0.15
    assert robust_error < 0.2


def test_robust_optimization_degrades_to_naive_when_outlier_scale_is_generous():
    """Sanity check on the mechanism itself: if the outlier threshold is
    set wide enough that even the bad correspondence's residual counts as
    "normal", the robust variant should behave like the naive one -- the
    robustness comes specifically from the scale parameter discriminating
    good from bad residuals, not from some other hidden effect.
    """
    sightings = _with_one_false_correspondence()
    naive = optimize_poses(TRUE_POSES, sightings)
    barely_robust = optimize_poses_robust(TRUE_POSES, sightings, outlier_scale_m=1000.0)
    assert abs(_pose_error(barely_robust) - _pose_error(naive)) < 0.5
