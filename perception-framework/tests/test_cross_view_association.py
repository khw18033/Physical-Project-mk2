"""implements: AI-S-02
reproduces (decision shape only): GMT, CVPR 2026 (docs/obsidian/papers/gmt.md)
tests: cross-view aggregation merges same-object evidence into one global
       trajectory; a noisy single contributing view fails to match a new
       observation on its own but the trajectory's rolling AGGREGATE across
       views succeeds on the same new observation (GMT's actual claimed
       advantage of matching against a global trajectory instead of
       per-view pairwise matching); a genuinely new object starts a new
       trajectory instead of false-positive matching an existing one.

Synthetic-data reproduction: no VisionTrack/WildTrack footage or embedding
model is used. Appearance embeddings here are small hand-built vectors
standing in for whatever ReID embedding a real appearance provider would
emit (AI-S-02 already treats the embedding's origin as opaque); the only
property that matters for this test is that they behave like *noisy
directional* features -- cosine similarity between two views of the same
object degrades with per-camera noise, exactly like a real embedding would.
"""
from __future__ import annotations

from perception_framework.perception.association import ObservedTrack
from perception_framework.perception.cross_view_association import (
    GlobalTrajectoryAssociator, GlobalTrajectoryMatch,
)

# -- shared synthetic scene: two physical objects, three established cameras --
#
# Object 1's true appearance direction and object 2's are deliberately far
# apart (near-orthogonal) so a correct implementation should never confuse
# them; ground positions are far apart (40m) versus the 2.0m default gate.

OBJECT_1_POSITION = (10.0, 20.0)
OBJECT_2_POSITION = (50.0, 60.0)
OBJECT_3_POSITION = (100.0, 5.0)  # an unrelated third object, introduced later


def test_three_cameras_merge_each_objects_evidence_into_one_global_trajectory():
    """GMT's core aggregation claim: independent per-view observations of
    the SAME physical object, taken across cameras A/B/C with realistic
    small per-camera appearance noise, must all resolve to one global
    trajectory per object -- not one trajectory per (camera, object) pair,
    which is what the traditional per-view-first baseline would produce.
    """
    associator = GlobalTrajectoryAssociator()

    # Camera A sees both objects first -- two brand-new global trajectories.
    obs_a1 = ObservedTrack("cam_A", 1, global_position=(10.05, 19.98),
                            appearance_embedding=(0.95, 0.10, 0.05, 0.02))
    obs_a2 = ObservedTrack("cam_A", 2, global_position=(50.03, 60.10),
                            appearance_embedding=(0.04, 0.02, 0.94, 0.06))

    match_a1 = associator.associate(obs_a1)
    assert match_a1.trajectory_id is None
    traj_1 = associator.start_trajectory(obs_a1)

    match_a2 = associator.associate(obs_a2)
    assert match_a2.trajectory_id is None
    traj_2 = associator.start_trajectory(obs_a2)

    assert traj_1 != traj_2

    # Camera B and camera C each independently observe both objects with
    # their own small (but nonzero) appearance/position noise. Every one of
    # these six observations must match its object's EXISTING trajectory,
    # not spawn a new one.
    camera_b_and_c_observations = [
        ("cam_B", 1, (10.20, 19.85), (0.92, -0.08, 0.03, 0.05), traj_1),
        ("cam_B", 2, (49.90, 60.22), (0.02, -0.05, 0.97, -0.02), traj_2),
        ("cam_C", 1, (9.88, 20.12), (0.90, 0.06, -0.04, 0.07), traj_1),
        ("cam_C", 2, (50.15, 59.88), (-0.03, 0.08, 0.93, 0.09), traj_2),
    ]

    for source_id, local_id, position, embedding, expected_trajectory in camera_b_and_c_observations:
        obs = ObservedTrack(source_id, local_id, global_position=position, appearance_embedding=embedding)
        match = associator.associate(obs)
        assert match.trajectory_id == expected_trajectory, (
            f"{source_id} local track {local_id} should have merged into "
            f"{expected_trajectory}, got {match.trajectory_id} ({match.reason})"
        )
        associator.update_trajectory(match.trajectory_id, obs)


# -- the concrete "why build the aggregate first" contrast --
#
# Trajectory 1 (object 1) is built from camera A (clean), camera B (clean),
# then camera C -- whose appearance reading of this particular object is
# badly noisy (e.g. partial occlusion / bad lighting angle from C's
# viewpoint). Camera D then reports a clean new observation of the same
# physical object. Position agrees closely in every case (well inside the
# 2.0m gate), so position never explains the outcome below -- only the
# appearance signal does, isolating exactly the effect gmt.md documents as
# the paper's verified contribution.

CAM_A_OBS = ObservedTrack("cam_A", 1, global_position=(10.05, 19.98),
                           appearance_embedding=(0.95, 0.10, 0.05, 0.02))
CAM_B_OBS = ObservedTrack("cam_B", 1, global_position=(10.20, 19.85),
                           appearance_embedding=(0.92, -0.08, 0.03, 0.05))
CAM_C_NOISY_OBS = ObservedTrack("cam_C", 1, global_position=(9.95, 20.05),
                                 appearance_embedding=(0.10, 0.90, 0.30, 0.20))
CAM_D_NEW_OBS = ObservedTrack("cam_D", 1, global_position=(10.10, 19.90),
                               appearance_embedding=(0.96, 0.09, -0.02, 0.03))


def test_naive_matching_against_only_the_latest_contributing_observation_fails():
    """The baseline GMT's paper replaces: treat the most recently
    contributing camera's raw per-view track as *the* representation of
    the trajectory (no aggregation across the other views that already
    contributed). Camera C's single noisy reading of this object is, on
    its own, too different from camera D's clean reading to pass the
    appearance gate -- so this naive approach fails to link them, even
    though they are the same physical object.
    """
    naive = GlobalTrajectoryAssociator()
    # Only the latest contributing observation is kept -- never folded
    # with A's or B's earlier evidence, which is exactly what makes this
    # "naive": camera A and camera B's contributions are simply discarded.
    naive.start_trajectory(CAM_C_NOISY_OBS)

    match = naive.associate(CAM_D_NEW_OBS)

    print(f"\n[naive: latest-observation-only] cam_D vs cam_C alone -> "
          f"trajectory_id={match.trajectory_id}, score={match.score:.3f} ({match.reason})")

    assert match.trajectory_id is None, (
        "matching against camera C's single noisy observation alone should "
        "fail the appearance gate -- if this assertion fails, the synthetic "
        "noise is not actually large enough to demonstrate the claim"
    )


def test_aggregate_matching_against_the_global_trajectory_succeeds():
    """GMT's actual reproduced claim: fold camera A, B and C's
    contributions (same three observations as above) into one rolling
    aggregate FIRST, then match camera D's new observation against that
    aggregate. Camera C's noise is now only one of three contributions to
    the mean appearance embedding, so it is largely averaged out -- the
    same new observation that failed to match camera C alone now matches
    the aggregate comfortably above threshold.
    """
    associator = GlobalTrajectoryAssociator()
    trajectory_id = associator.start_trajectory(CAM_A_OBS)
    associator.update_trajectory(trajectory_id, CAM_B_OBS)
    associator.update_trajectory(trajectory_id, CAM_C_NOISY_OBS)

    match = associator.associate(CAM_D_NEW_OBS)

    print(f"[aggregate: A+B+C global trajectory] cam_D vs aggregate -> "
          f"trajectory_id={match.trajectory_id}, score={match.score:.3f} ({match.reason})")

    assert match.trajectory_id == trajectory_id, (
        f"matching against the A+B+C aggregate should succeed where matching "
        f"against C alone failed; got {match}"
    )
    assert match.score >= 0.3  # the default appearance_threshold, cleared with margin


def test_new_unrelated_object_starts_a_new_trajectory_not_a_false_positive():
    """A genuinely new physical object -- far away in position AND with an
    appearance embedding pointing in a different direction from every
    existing trajectory -- must not be absorbed into an existing global
    trajectory. `associate` should report no match so the caller starts a
    fresh trajectory (AI-S-02: unrelated observations must not be forced
    into an existing identity).
    """
    associator = GlobalTrajectoryAssociator()
    traj_1 = associator.start_trajectory(CAM_A_OBS)
    associator.update_trajectory(traj_1, CAM_B_OBS)
    traj_2 = associator.start_trajectory(
        ObservedTrack("cam_A", 2, global_position=OBJECT_2_POSITION,
                       appearance_embedding=(0.04, 0.02, 0.94, 0.06))
    )

    unrelated_obs = ObservedTrack(
        "cam_D", 2, global_position=OBJECT_3_POSITION,
        appearance_embedding=(-0.5, 0.3, -0.2, 0.9),
    )

    match = associator.associate(unrelated_obs)

    assert match.trajectory_id is None
    assert match.trajectory_id not in (traj_1, traj_2)

    new_traj = associator.start_trajectory(unrelated_obs)
    assert new_traj not in (traj_1, traj_2)


def test_associate_result_is_the_documented_dataclass_shape():
    """Sanity-checks the public contract callers depend on: `associate`
    always returns a `GlobalTrajectoryMatch`, and an associator with no
    trajectories yet always reports no match rather than raising.
    """
    associator = GlobalTrajectoryAssociator()
    match = associator.associate(CAM_A_OBS)
    assert isinstance(match, GlobalTrajectoryMatch)
    assert match.trajectory_id is None
    assert match.score == 0.0
    assert isinstance(match.reason, str) and match.reason
