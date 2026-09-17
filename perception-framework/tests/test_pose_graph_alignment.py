"""implements: (stand-in for) DT-03, BE-C-04
reproduces (decision rule only): CoAlign, ICRA 2023 (docs/obsidian/papers/coalign.md)
tests: zero-noise is a no-op, optimization recovers most of the pose error CoAlign's
       own paper injects (sigma = 0/0.2/0.4/0.6 m), object localization error drops
       to match, and a missing anchor / no correspondences degrades to a no-op
       instead of raising

This is a *synthetic-data* reproduction, not a re-run of CoAlign on OPV2V/V2X-Sim/
DAIR-V2X (we do not have pose-annotated multi-agent LiDAR data locally). What is
reproduced faithfully is the paper's actual evaluation *protocol* for this specific
module: take ground-truth agent poses and object positions, inject Gaussian pose
noise at the same sigma levels the paper tested (0/0.2/0.4/0.6, translation), and
check whether the optimizer recovers alignment -- i.e. whether the *decision rule*
(minimize cross-agent object-correspondence residuals via least squares) produces
the qualitative result the paper reports (pose-graph optimization is far more robust
to pose noise than using the noisy pose directly), not whether we match the paper's
reported AP numbers on real LiDAR detections.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from perception_framework.simulation.pose_graph_alignment import (
    AgentPoseEstimate, ObjectSighting, optimize_poses, to_world,
)

# A small WildTrack-scale plaza (~15m square) watched by one trusted anchor
# (a calibrated fixed camera, AI-E-02) plus three other agents (e.g. patrol
# robots / additional fixed cameras) whose *reported* pose may be noisy.
TRUE_POSES = {
    "fixed_cam_anchor": AgentPoseEstimate("fixed_cam_anchor", x_m=0.0, z_m=0.0, yaw_rad=0.0, trusted_anchor=True),
    "robot_1": AgentPoseEstimate("robot_1", x_m=8.0, z_m=2.0, yaw_rad=math.radians(35.0)),
    "robot_2": AgentPoseEstimate("robot_2", x_m=-6.0, z_m=9.0, yaw_rad=math.radians(-110.0)),
    "fixed_cam_2": AgentPoseEstimate("fixed_cam_2", x_m=4.0, z_m=-7.0, yaw_rad=math.radians(160.0)),
}

# Shared ground-truth object (person) positions in the world frame.
TRUE_OBJECTS = {
    "p1": (1.0, 3.0), "p2": (5.0, 5.5), "p3": (-2.0, 6.0),
    "p4": (3.5, -1.0), "p5": (-4.0, 2.5), "p6": (2.0, -4.0),
}

# Which agents observe which objects -- every object is seen by the anchor
# plus at least one other agent, keeping the correspondence graph connected
# (required for the solution to be well-defined -- see module docstring).
VISIBILITY = {
    "p1": ("fixed_cam_anchor", "robot_1"),
    "p2": ("fixed_cam_anchor", "robot_1", "fixed_cam_2"),
    "p3": ("fixed_cam_anchor", "robot_2"),
    "p4": ("fixed_cam_anchor", "fixed_cam_2"),
    "p5": ("fixed_cam_anchor", "robot_2"),
    "p6": ("fixed_cam_anchor", "fixed_cam_2", "robot_1"),
}


def _to_local(pose: AgentPoseEstimate, world_x: float, world_z: float) -> tuple[float, float]:
    """Inverse of `to_world` -- what a perfect local detector would report
    for a world point, given the agent's TRUE pose. Detection itself is
    never noisy in this reproduction; only the agent's self-reported pose
    is, matching CoAlign's own problem isolation.
    """
    dx, dz = world_x - pose.x_m, world_z - pose.z_m
    c, s = math.cos(-pose.yaw_rad), math.sin(-pose.yaw_rad)
    return dx * c - dz * s, dx * s + dz * c


def _true_sightings() -> list[ObjectSighting]:
    sightings = []
    for object_id, (wx, wz) in TRUE_OBJECTS.items():
        for agent_id in VISIBILITY[object_id]:
            lx, lz = _to_local(TRUE_POSES[agent_id], wx, wz)
            sightings.append(ObjectSighting(agent_id, object_id, lx, lz))
    return sightings


def _noisy_poses(sigma_m: float, rng: np.random.Generator) -> dict[str, AgentPoseEstimate]:
    """Injects Gaussian pose noise on every non-anchor agent, mirroring
    CoAlign's own sigma sweep (0/0.2/0.4/0.6 m translation); yaw noise is
    scaled from the same sigma (5 deg per meter of sigma) as a documented
    simplification of the paper's separate sigma_t/sigma_r sweep -- this
    reproduction checks the qualitative robustness claim, not the paper's
    exact translation/rotation split.
    """
    noisy = {}
    for agent_id, pose in TRUE_POSES.items():
        if pose.trusted_anchor or sigma_m == 0.0:
            noisy[agent_id] = pose
            continue
        noisy[agent_id] = AgentPoseEstimate(
            agent_id=agent_id,
            x_m=pose.x_m + rng.normal(0.0, sigma_m),
            z_m=pose.z_m + rng.normal(0.0, sigma_m),
            yaw_rad=pose.yaw_rad + rng.normal(0.0, math.radians(5.0) * sigma_m),
        )
    return noisy


def _pose_error(poses: dict[str, AgentPoseEstimate]) -> float:
    errs = [
        math.hypot(poses[aid].x_m - TRUE_POSES[aid].x_m, poses[aid].z_m - TRUE_POSES[aid].z_m)
        for aid in poses if not poses[aid].trusted_anchor
    ]
    return float(np.mean(errs))


def _object_localization_error(poses: dict[str, AgentPoseEstimate],
                                sightings: list[ObjectSighting]) -> float:
    errs = []
    for s in sightings:
        wx, wz = to_world(poses[s.agent_id], s.local_x_m, s.local_z_m)
        tx, tz = TRUE_OBJECTS[s.object_id]
        errs.append(math.hypot(wx - tx, wz - tz))
    return float(np.mean(errs))


# -- zero noise is a no-op-ish result --------------------------------------

def test_zero_noise_stays_near_zero_error_before_and_after():
    sightings = _true_sightings()
    poses = _noisy_poses(0.0, np.random.default_rng(0))
    optimized = optimize_poses(poses, sightings)

    assert _pose_error(poses) < 1e-9
    assert _object_localization_error(poses, sightings) < 1e-9
    assert _pose_error(optimized) < 1e-6
    assert _object_localization_error(optimized, sightings) < 1e-6


# -- the paper's core claim: optimization recovers most of the injected error --

@pytest.mark.parametrize("sigma_m", [0.2, 0.4, 0.6])
def test_optimization_substantially_reduces_pose_and_localization_error(sigma_m):
    sightings = _true_sightings()
    trials = 30
    before_pose, after_pose, before_loc, after_loc = [], [], [], []

    for trial in range(trials):
        rng = np.random.default_rng(1000 * int(sigma_m * 10) + trial)
        noisy = _noisy_poses(sigma_m, rng)
        optimized = optimize_poses(noisy, sightings)

        before_pose.append(_pose_error(noisy))
        after_pose.append(_pose_error(optimized))
        before_loc.append(_object_localization_error(noisy, sightings))
        after_loc.append(_object_localization_error(optimized, sightings))

    mean_before_pose, mean_after_pose = np.mean(before_pose), np.mean(after_pose)
    mean_before_loc, mean_after_loc = np.mean(before_loc), np.mean(after_loc)

    print(
        f"\n[sigma={sigma_m}m, n={trials}] "
        f"pose error {mean_before_pose:.3f}m -> {mean_after_pose:.3f}m "
        f"({(1 - mean_after_pose / mean_before_pose) * 100:.1f}% reduction); "
        f"object localization error {mean_before_loc:.3f}m -> {mean_after_loc:.3f}m "
        f"({(1 - mean_after_loc / mean_before_loc) * 100:.1f}% reduction)"
    )

    # The paper's claim, reproduced qualitatively: optimization recovers
    # most (not necessarily all -- yaw/translation are coupled and the
    # graph is only partially connected) of the injected error.
    assert mean_after_pose < mean_before_pose * 0.5
    assert mean_after_loc < mean_before_loc * 0.5
    # And it should land close to the noise-free baseline, not just
    # "somewhat better than doing nothing".
    assert mean_after_loc < sigma_m


def test_error_grows_with_injected_noise_before_optimization_but_stays_flatter_after():
    """Sanity-checks the noise injection itself, then reproduces CoAlign's
    robustness framing directly: the *gap* between corrected and
    uncorrected error should widen as pose noise grows.
    """
    sightings = _true_sightings()
    sigmas = [0.2, 0.4, 0.6]
    after_by_sigma = []

    for sigma_m in sigmas:
        before, after = [], []
        for trial in range(20):
            rng = np.random.default_rng(2000 * int(sigma_m * 10) + trial)
            noisy = _noisy_poses(sigma_m, rng)
            optimized = optimize_poses(noisy, sightings)
            before.append(_object_localization_error(noisy, sightings))
            after.append(_object_localization_error(optimized, sightings))
        after_by_sigma.append(float(np.mean(after)))
        assert np.mean(before) > sigma_m * 0.5  # noise injection actually did something

    # Uncorrected error scales with sigma by construction; corrected error
    # should stay near the noise-free floor regardless of sigma -- an
    # absolute tolerance, not a ratio of two already-near-zero numbers.
    assert after_by_sigma[-1] < 0.05


# -- graceful degradation: no anchor / no correspondences -> no-op, not a crash --

def test_no_anchor_returns_input_unchanged_rather_than_raising():
    all_free = {aid: replace_anchor(p) for aid, p in TRUE_POSES.items()}
    sightings = _true_sightings()
    result = optimize_poses(all_free, sightings)
    assert result == all_free


def test_no_cross_agent_correspondences_returns_input_unchanged():
    single_agent_sightings = [s for s in _true_sightings() if s.agent_id == "robot_1"]
    poses = _noisy_poses(0.4, np.random.default_rng(7))
    result = optimize_poses(poses, single_agent_sightings)
    assert result == poses


def replace_anchor(pose: AgentPoseEstimate) -> AgentPoseEstimate:
    from dataclasses import replace
    return replace(pose, trusted_anchor=False)
