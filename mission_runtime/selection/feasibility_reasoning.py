"""Allocator-agnostic robot/task feasibility filtering — a shared
`ReasonerOutput` that multiple, independently-implemented allocation
algorithms consume without re-deriving feasibility themselves.

implements: AI-C-18, AI-B-04

reproduces (decision shape only, not the reasoning technology):
docs/obsidian/papers/semantic-feasibility-reasoning.md — In et al.,
"Semantic Feasibility Reasoning for Heterogeneous Multi-Robot Task
Allocation," Electronics 15(16):3562, 2026. That paper's verified
contribution is a rule-based feasibility reasoner (robot/task capability
matching + a "loaded-state height" recomputation rule for stacked/carried
items) that produces one shared `ReasonerOutput` object consumed
identically by multiple independent allocators (validated there with
Hungarian/MILP/greedy/genetic-algorithm allocators all sharing one
reasoner output). This module reproduces exactly that decision shape —
capability filtering separated from allocation, behind one plain-Python
`ReasonerOutput` contract — in plain Python `if`/`and` checks. It does
NOT reproduce the paper's actual implementation technology: no OWL
ontology, no Owlready2, no SWRL rules, no Pellet reasoner and no such
dependency is added here. Same posture as `simulation/pose_graph_alignment.py`
reproducing CoAlign's g2o pose-graph solver as plain numpy Gauss-Newton:
the *decision rule* is reproducible and worth keeping identical; the
*reasoning engine* it was originally expressed in is not a framework
dependency (절대 준수 원칙 #1, #2 — no ontology-reasoning runtime is a
core dependency of feasibility filtering).

Loaded-state height rule (paper §3, "Loaded-state reachability" — the
verified note gives the two cases but not which handling-method flag
selects each; the mapping used here is fixed and documented so the
choice is auditable rather than implicit):

  - `requires_manipulation=True`  -> effective_height = max(robot.max_height_m, item_height_m)
    The paper's `MANIPULATE` handling method: the robot's own body/arm
    reach has to clear the item to act on it (e.g. reaching above or
    around the item to pick it up), so the item does not simply add to
    the robot's stack height — whichever of the two is taller sets the
    clearance that must fit under `task.required_height_m`.
  - `requires_manipulation=False` -> effective_height = robot.max_height_m + item_height_m
    Any other handling method (the paper's non-MANIPULATE case, e.g. a
    mobile base just carrying/transporting a box on top of itself): the
    item's height stacks on top of the robot's own height, so the two
    add.

This module never invents a height from `item_weight_kg` — the caller
must supply `TaskRequirement.item_height_m` directly, exactly as the
paper's ABox carries item height as its own declared attribute rather
than deriving it from mass.

A `FeasibilityReasoner` never raises for empty `robots`/`tasks` lists —
absence of candidates is a normal degrade condition (AI-C-05: 선택 기능
결손은 DEGRADED까지만 내려가고 예외로 확산되지 않는다), not a fatal error, so
an empty `ReasonerOutput` is the correct answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RobotCapability:
    """One robot's declared capability envelope (AI-C-18 style: plain
    attributes, no vendor/model identity baked in)."""

    robot_id: str
    max_height_m: float
    can_manipulate: bool
    max_payload_kg: float


@dataclass(frozen=True)
class TaskRequirement:
    """One task's requirement envelope. `item_height_m` is the height of
    the item involved (if any) — used only to recompute the loaded-state
    effective height, never derived from `item_weight_kg`."""

    task_id: str
    required_height_m: float
    requires_manipulation: bool
    item_weight_kg: float
    item_height_m: float = 0.0


@dataclass(frozen=True)
class ReasonerOutput:
    """The one shared feasibility contract every allocator consumes.

    `task_feasibility` and `robot_reachable_tasks` are exact inverses of
    each other over the same feasibility relation — kept as two views
    because different allocators iterate from different sides (some
    walk tasks looking for a robot, others walk robots looking for
    work), matching the paper's TaskFeasibility/RobotReachability split.
    """

    task_feasibility: dict[str, tuple[str, ...]]
    robot_reachable_tasks: dict[str, tuple[str, ...]]


def _effective_height_m(robot: RobotCapability, task: TaskRequirement) -> float:
    """Loaded-state height recomputation — see module docstring for which
    branch applies and why."""
    if task.requires_manipulation:
        return max(robot.max_height_m, task.item_height_m)
    return robot.max_height_m + task.item_height_m


def _is_feasible(robot: RobotCapability, task: TaskRequirement) -> bool:
    if robot.max_payload_kg < task.item_weight_kg:
        return False
    if task.requires_manipulation and not robot.can_manipulate:
        return False
    return _effective_height_m(robot, task) >= task.required_height_m


class FeasibilityReasoner:
    """Rule-based capability + loaded-state-height feasibility filter.

    Produces one `ReasonerOutput` shared by every allocator downstream —
    the reasoner is the only place feasibility is decided; allocators
    never re-derive it (see `AllocatorProtocol` below).
    """

    def reason(
        self,
        robots: list[RobotCapability],
        tasks: list[TaskRequirement],
    ) -> ReasonerOutput:
        """Never raises for empty `robots`/`tasks` — an empty output is
        the correct, non-exceptional answer (AI-C-05)."""
        task_feasibility: dict[str, tuple[str, ...]] = {}
        robot_reachable: dict[str, list[str]] = {robot.robot_id: [] for robot in robots}

        for task in tasks:
            eligible: list[str] = []
            for robot in robots:
                if _is_feasible(robot, task):
                    eligible.append(robot.robot_id)
                    robot_reachable[robot.robot_id].append(task.task_id)
            task_feasibility[task.task_id] = tuple(eligible)

        robot_reachable_tasks = {robot_id: tuple(task_ids) for robot_id, task_ids in robot_reachable.items()}
        return ReasonerOutput(task_feasibility=task_feasibility, robot_reachable_tasks=robot_reachable_tasks)


class AllocatorProtocol(Protocol):
    """Any allocation algorithm satisfying this contract may consume a
    `ReasonerOutput` — Hungarian, MILP, genetic, greedy or otherwise.
    The two allocators below are simple reference implementations, not
    the only permitted ones (AI-B-01: 선택 방식은 교체 가능해야 한다)."""

    def allocate(self, reasoner_output: ReasonerOutput) -> dict[str, str]:
        """Returns task_id -> assigned robot_id for whichever tasks this
        allocator managed to assign. A task absent from the result was
        left unassigned (e.g. no feasible robot, or all feasible robots
        already taken) — never raises for that case."""
        ...


class GreedyFirstFitAllocator:
    """Assigns each task, in `task_id` order, to the first still-available
    feasible robot. Consumes only `ReasonerOutput.task_feasibility` —
    never sees the raw robots/tasks the reasoner started from."""

    def allocate(self, reasoner_output: ReasonerOutput) -> dict[str, str]:
        assignment: dict[str, str] = {}
        taken: set[str] = set()
        for task_id in sorted(reasoner_output.task_feasibility.keys()):
            for robot_id in reasoner_output.task_feasibility[task_id]:
                if robot_id not in taken:
                    assignment[task_id] = robot_id
                    taken.add(robot_id)
                    break
        return assignment


class LoadBalancedAllocator:
    """Assigns each task, in `task_id` order, to whichever *feasible*
    robot currently holds the fewest assignments so far (ties broken by
    robot_id for determinism). Consumes only `ReasonerOutput` — same
    input as `GreedyFirstFitAllocator`, deliberately different policy,
    to demonstrate the reasoner output is genuinely allocator-agnostic."""

    def allocate(self, reasoner_output: ReasonerOutput) -> dict[str, str]:
        assignment: dict[str, str] = {}
        load: dict[str, int] = {robot_id: 0 for robot_id in reasoner_output.robot_reachable_tasks}
        for task_id in sorted(reasoner_output.task_feasibility.keys()):
            candidates = reasoner_output.task_feasibility[task_id]
            if not candidates:
                continue
            chosen = min(candidates, key=lambda robot_id: (load.get(robot_id, 0), robot_id))
            assignment[task_id] = chosen
            load[chosen] = load.get(chosen, 0) + 1
        return assignment
