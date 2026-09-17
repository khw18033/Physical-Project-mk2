"""implements: AI-C-18, AI-B-04

tests: capability-matching feasibility filter, exact task/robot inverse
views, allocator-agnostic ReasonerOutput consumption (two independently
implemented allocators diverging on the same output), zero-feasible-robot
degrade, and the loaded-state height recomputation branch
(`docs/obsidian/papers/semantic-feasibility-reasoning.md`).
"""

from __future__ import annotations

from perception_framework.selection.feasibility_reasoning import (
    FeasibilityReasoner,
    GreedyFirstFitAllocator,
    LoadBalancedAllocator,
    RobotCapability,
    TaskRequirement,
)


def test_feasibility_matches_hand_computed_expectations_and_is_an_exact_inverse():
    robots = [
        RobotCapability(robot_id="r1", max_height_m=1.0, can_manipulate=True, max_payload_kg=10.0),
        RobotCapability(robot_id="r2", max_height_m=2.0, can_manipulate=False, max_payload_kg=5.0),
        RobotCapability(robot_id="r3", max_height_m=0.5, can_manipulate=True, max_payload_kg=20.0),
    ]
    tasks = [
        # r1: max(1.0,1.2)=1.2>=1.0 & manipulate ok & payload ok -> feasible
        # r2: requires_manipulation but can_manipulate=False -> infeasible
        # r3: max(0.5,1.2)=1.2>=1.0 & manipulate ok & payload ok -> feasible
        TaskRequirement(
            task_id="t1", required_height_m=1.0, requires_manipulation=True,
            item_weight_kg=8.0, item_height_m=1.2,
        ),
        # r1: 1.0+1.0=2.0 < 2.5 -> infeasible (height)
        # r2: 2.0+1.0=3.0>=2.5 & payload 5>=3 -> feasible
        # r3: 0.5+1.0=1.5 < 2.5 -> infeasible (height)
        TaskRequirement(
            task_id="t2", required_height_m=2.5, requires_manipulation=False,
            item_weight_kg=3.0, item_height_m=1.0,
        ),
        # payload 25kg exceeds every robot's max_payload_kg -> zero feasible robots
        TaskRequirement(
            task_id="t3", required_height_m=0.5, requires_manipulation=False,
            item_weight_kg=25.0, item_height_m=0.0,
        ),
    ]

    output = FeasibilityReasoner().reason(robots, tasks)

    assert output.task_feasibility == {
        "t1": ("r1", "r3"),
        "t2": ("r2",),
        "t3": (),
    }
    assert output.robot_reachable_tasks == {
        "r1": ("t1",),
        "r2": ("t2",),
        "r3": ("t1",),
    }

    # Exact-inverse check: for every (task, robot) pair asserted feasible
    # from the task side, the same pair must appear from the robot side,
    # and vice versa -- not just matching the hardcoded dicts above.
    for task_id, robot_ids in output.task_feasibility.items():
        for robot_id in robot_ids:
            assert task_id in output.robot_reachable_tasks[robot_id]
    for robot_id, task_ids in output.robot_reachable_tasks.items():
        for task_id in task_ids:
            assert robot_id in output.task_feasibility[task_id]


def test_zero_feasible_robots_task_is_absent_from_assignments_without_raising():
    robots = [
        RobotCapability(robot_id="r1", max_height_m=1.0, can_manipulate=True, max_payload_kg=10.0),
    ]
    tasks = [
        TaskRequirement(
            task_id="impossible", required_height_m=0.5, requires_manipulation=False,
            item_weight_kg=999.0, item_height_m=0.0,
        ),
    ]

    output = FeasibilityReasoner().reason(robots, tasks)
    assert output.task_feasibility["impossible"] == ()
    assert output.robot_reachable_tasks["r1"] == ()

    greedy_result = GreedyFirstFitAllocator().allocate(output)
    balanced_result = LoadBalancedAllocator().allocate(output)
    assert "impossible" not in greedy_result
    assert "impossible" not in balanced_result

    # Also never raises for a genuinely empty robots/tasks list (AI-C-05
    # posture: absence of candidates degrades, it does not except).
    empty_output = FeasibilityReasoner().reason([], [])
    assert empty_output.task_feasibility == {}
    assert empty_output.robot_reachable_tasks == {}
    assert GreedyFirstFitAllocator().allocate(empty_output) == {}
    assert LoadBalancedAllocator().allocate(empty_output) == {}


def test_two_independent_allocators_diverge_on_the_same_reasoner_output():
    # "A" can manipulate, "B" cannot -- everything else identical, so the
    # only thing that varies feasibility is each task's manipulation need.
    robots = [
        RobotCapability(robot_id="A", max_height_m=5.0, can_manipulate=True, max_payload_kg=100.0),
        RobotCapability(robot_id="B", max_height_m=5.0, can_manipulate=False, max_payload_kg=100.0),
    ]
    tasks = [
        TaskRequirement(task_id="t1", required_height_m=1.0, requires_manipulation=False, item_weight_kg=1.0),
        TaskRequirement(task_id="t2", required_height_m=1.0, requires_manipulation=True, item_weight_kg=1.0),
        TaskRequirement(task_id="t3", required_height_m=1.0, requires_manipulation=False, item_weight_kg=1.0),
    ]

    output = FeasibilityReasoner().reason(robots, tasks)
    assert output.task_feasibility == {
        "t1": ("A", "B"),
        "t2": ("A",),  # only A can manipulate
        "t3": ("A", "B"),
    }

    greedy_result = GreedyFirstFitAllocator().allocate(output)
    balanced_result = LoadBalancedAllocator().allocate(output)

    # Both allocators must only ever use feasible (task, robot) pairs.
    for allocator_name, result in (("greedy", greedy_result), ("load_balanced", balanced_result)):
        for task_id, robot_id in result.items():
            assert robot_id in output.task_feasibility[task_id], (
                f"{allocator_name} assigned infeasible pair ({task_id}, {robot_id})"
            )

    # Greedy exhausts "A" on t1 (first-fit, first candidate in task_id
    # order) and has no other feasible robot left for t2 (only A is
    # feasible for it) -> t2 stays unassigned; t3 falls through to B.
    assert greedy_result == {"t1": "A", "t3": "B"}
    assert "t2" not in greedy_result

    # Load balancing does not remove a robot from the pool after one
    # assignment -- it keeps spreading by current load count, so it can
    # (and does) assign the same robot twice when it is the only feasible
    # candidate, producing a materially different, larger assignment.
    assert balanced_result == {"t1": "A", "t2": "A", "t3": "B"}

    # The two allocators must genuinely disagree, not just format
    # differently -- proving the shared ReasonerOutput is actually
    # allocator-agnostic rather than both allocators happening to agree.
    assert greedy_result != balanced_result


def test_loaded_state_height_branch_is_load_bearing_not_dead_code():
    # Two otherwise-identical robot/task pairs, differing ONLY in
    # requires_manipulation. Robot height 1.0m, item height 0.5m:
    #   - requires_manipulation=True  -> max(1.0, 0.5)  = 1.0 (effective)
    #   - requires_manipulation=False -> 1.0 + 0.5       = 1.5 (effective)
    # required_height_m=1.3 sits strictly between the two, so it is
    # infeasible under the max() branch and feasible under the sum
    # branch -- proving both branches are real and actually taken.
    robot = RobotCapability(robot_id="r1", max_height_m=1.0, can_manipulate=True, max_payload_kg=10.0)

    manipulate_task = TaskRequirement(
        task_id="manipulate", required_height_m=1.3, requires_manipulation=True,
        item_weight_kg=1.0, item_height_m=0.5,
    )
    stack_task = TaskRequirement(
        task_id="stack", required_height_m=1.3, requires_manipulation=False,
        item_weight_kg=1.0, item_height_m=0.5,
    )

    output = FeasibilityReasoner().reason([robot], [manipulate_task, stack_task])

    assert output.task_feasibility["manipulate"] == ()  # max(1.0, 0.5)=1.0 < 1.3
    assert output.task_feasibility["stack"] == ("r1",)  # 1.0 + 0.5 = 1.5 >= 1.3
