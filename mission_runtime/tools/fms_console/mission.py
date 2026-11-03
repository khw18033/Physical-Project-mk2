"""implements: AI-B-12, AI-B-03, AI-C-19
tests: tests/test_fms_mission.py

여러 구역에 걸친 임무를 **순서대로** 끌고 가는 실행기.

한 구역 안의 일은 이미 풀려 있다 — `planning/decomposition.py` 가 (목표 종류,
레지스트리, 실행자, 문맥) 에서 결정적으로 같은 서브태스크를 낸다. 여기서 더해지는
질문은 하나뿐이다: **여러 구역을 지나야 하는 임무에서 어디까지 갔고 왜 멈췄는가.**

순서는 한 번 유도하고 보존한다 (AI-B-12)
----------------------------------------
구역 순서와 구역별 계획은 실행을 시작하기 전에 **한 번** 만들어 두고 실행 중에
다시 계산하지 않는다. 들어가지 못한 구역이 나오면 남은 구역을 뒤로 돌리거나
조용히 빼지 않는다 — 어디서 멈췄는지(`stopped_at_index`)와 왜 멈췄는지
(`reason`), 그리고 그래서 실행되지 않은 구역이 무엇인지(`unexecuted_zones`)를
그대로 적는다. 순서를 실행 중에 고치면 "계획대로 됐는가"를 물을 대상이 없어진다.

회차는 덮지 않는다 (AI-B-12)
----------------------------
같은 구역을 다시 시도하면 앞 시도를 지우지 않고 회차를 늘려 함께 남긴다.
`ZoneMissionRunner.history` 가 실행기 수준에서 누적되므로 `run()` 을 다시 불러도
1회차 기록이 남아 있다. 요구사항이 "재실행은 원 노드를 덮지 않고 회차를 구분해
보존해야 한다"고 적은 것이 이 축이다.

세 축을 한 칸에 합치지 않는다 (AI-B-12)
---------------------------------------
"그 구역에 들어갔는가"(전환), "그 단계를 실행할 수 있는가"(기능 가용성),
"결과가 무엇인가"(수행 결과)는 서로 다른 축이다. 그래서 `ZoneAttempt` 는
`entered` / `blocked_capabilities` / `outcomes` 를 따로 들고, 선택 기능 결손은
멈춤이 아니라 축소로 지나간다(AI-C-05 — `UNAVAILABLE` 은 `FAILED` 가 아니다).

AI 는 물리 명령을 내지 않는다 (AI-C-19)
---------------------------------------
이 실행기가 내놓는 것은 계획·순서·전환 판단·사유뿐이다. 실제 전환은
`ZoneTransitRuntime.confirm_zone_fn`(네트워크·실행 provider)이 수행하고, 단계의
실제 수행은 `execute_fn`(하드웨어 어댑터·명령 경로) 뒤에서 일어난다. 둘 다
주입점이고 기본 구현은 시험·시뮬레이터용이다. 항목별 자율 등급도 AI 가 정하지
않는다 — `autonomy_fn` 이 없으면 보수적인 `REQUIRES_FRESH_COMMAND` 가 되고,
"링크 없이 이어서 해도 된다"는 말은 발급자가 명시했을 때만 성립한다.

링크가 없는 동안 (AI-N-02, AI-B-10)
-----------------------------------
구역별 단계는 `MissionCache` 로 내려간다 — 내용과 진행이 디스크에 남아야 링크가
끊기거나 프로세스가 죽었다 살아나도 말단이 "나는 무슨 임무 중인가"를 혼자 답할
수 있다. 그 캐시를 여기서 다시 만들지 않고 그대로 쓰며, 전달에는 그 임무를 실어
나른 물리 명령의 `origin_command_id` 가 반드시 붙는다(출처 없는 임무는 캐시가
거부한다).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.contracts.profile import ResourceBudget
from mission_runtime.execution.mission import MissionItemOutcome
from mission_runtime.ondevice.mission_cache import (
    CachedMissionItem,
    MissionApplyResult,
    MissionAutonomy,
    MissionCache,
    MissionDelivery,
)
from mission_runtime.planning.decomposition import (
    DecompositionContext,
    ExecutorCandidate,
    Subtask,
    SubtaskPlan,
    TaskDecomposer,
    TaskTemplateLibrary,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry
from mission_runtime.tools.fms_console.fleet import REACHABLE_STATES, FleetModel
from mission_runtime.tools.fms_console.handover import (
    CrossingAttempt,
    Position,
    ZoneTransitRuntime,
)
from mission_runtime.tools.fms_console.subtasks import ZONE_SUPPLY_PREFIX

# --- 사유 통제 어휘 ----------------------------------------------------------
# ':' 앞이 토큰, 뒤가 데이터 — `zone_handover.py`·`mission_cache.py` 와 같은 규약.

MISSION_COMPLETED = "mission_completed"
MISSION_STOPPED = "mission_stopped_at_zone"          # + ":<index>:<zone>:<reason>"
MISSION_NOT_STARTED = "mission_not_started"          # + ":<reason>"

STOP_NO_ZONE = "no_zone_declared"
STOP_ZONE_NOT_ENTERED = "zone_not_entered"           # + ":<transit reason>"
STOP_PLAN_BLOCKED = "zone_plan_has_no_executable_step"   # + ":<kinds>"
STOP_NO_EXECUTOR = "zone_has_no_executor"            # + ":<plan reason>"
STOP_STEP_FAILED = "zone_step_failed"                # + ":<subtask_id>"
STOP_SAFETY_SUSPENDED = "local_safety_suspended"     # + ":<reason>"

ZONE_DONE = "zone_completed"
ZONE_DEGRADED = "zone_completed_degraded"            # + ":<sacrificed>"

MISSION_REASONS: tuple[str, ...] = (
    MISSION_COMPLETED,
    MISSION_STOPPED,
    MISSION_NOT_STARTED,
    STOP_NO_ZONE,
    STOP_ZONE_NOT_ENTERED,
    STOP_PLAN_BLOCKED,
    STOP_NO_EXECUTOR,
    STOP_STEP_FAILED,
    STOP_SAFETY_SUSPENDED,
    ZONE_DONE,
    ZONE_DEGRADED,
)


# --- 구역 순서 ---------------------------------------------------------------


def derive_zone_order(
    fleet: FleetModel,
    start_zone: str,
    zones: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """맞닿음에서 방문 순서를 유도한다. 같은 입력이면 같은 순서다.

    맞닿은 구역 폭 우선 탐색이고 동점은 구역 id 순으로 깬다 — 실행기가 결정적이
    아니면 "계획대로 됐는가"를 두 번 물었을 때 답이 달라진다. `zones` 를 주면
    그 구역들만 결과에 남기되 거쳐 가는 구역을 통해 도달한다(길이 없는 구역은
    결과에서 빠지고, 빠진 사실은 호출자가 비교로 안다).
    """
    wanted = set(zones) if zones is not None else None
    order: list[str] = []
    seen = {start_zone}
    queue: deque[str] = deque([start_zone])
    while queue:
        current = queue.popleft()
        if wanted is None or current in wanted or current == start_zone:
            order.append(current)
        for row in fleet.zone_neighbours(current):
            if row["zone_id"] not in seen:
                seen.add(row["zone_id"])
                queue.append(row["zone_id"])
    if wanted is not None and start_zone not in wanted:
        order = [z for z in order if z in wanted]
    return tuple(order)


# --- 산출물 ------------------------------------------------------------------


@dataclass(frozen=True)
class ZoneLeg:
    """임무의 한 구역. 실행 전에 한 번 만들어지고 실행 중에 바뀌지 않는다."""

    order_index: int
    zone_id: str
    plan: SubtaskPlan
    #: 앞 구역에서 이 구역으로 넘어오는 것이 무선 전환인가.
    radio_handover_required: bool
    #: 필수 kind 가 없어 막힌 단계의 kind — 외부 개발 요청 후보다(AI-B-13).
    blocked_capabilities: tuple[str, ...] = ()
    known_facts: Mapping[str, bool] = field(default_factory=dict)

    @property
    def executable_subtasks(self) -> tuple[Subtask, ...]:
        return self.plan.executable_subtasks

    @property
    def runnable(self) -> bool:
        return bool(self.executable_subtasks) and self.plan.executor.executor_id is not None

    def as_dict(self) -> dict:
        return {
            "order_index": self.order_index,
            "zone_id": self.zone_id,
            "plan_id": self.plan.plan_id,
            "template_version": self.plan.template_version,
            "reason": self.plan.reason,
            "radio_handover_required": self.radio_handover_required,
            "blocked_capabilities": list(self.blocked_capabilities),
            "known_facts": dict(self.known_facts),
            "executor": {
                "executor_id": self.plan.executor.executor_id,
                "state": self.plan.executor.state.value,
                "reason": self.plan.executor.reason,
            },
            "subtasks": [
                {
                    "subtask_id": s.subtask_id,
                    "action": s.action,
                    "order_index": s.order_index,
                    "state": s.state.value,
                    "executable": s.executable,
                    "missing_required": list(s.missing_required_capabilities),
                    "missing_optional": list(s.missing_optional_capabilities),
                    "unverified_preconditions": list(s.unverified_preconditions),
                }
                for s in self.plan.subtasks
            ],
        }


@dataclass(frozen=True)
class ZoneAttempt:
    """한 구역을 한 번 시도한 기록. 다음 회차가 이것을 덮지 않는다."""

    zone_id: str
    order_index: int
    attempt: int
    at: float
    entered: bool
    completed: bool
    reason: str
    crossing: CrossingAttempt | None = None
    outcomes: tuple[tuple[str, str], ...] = ()
    sacrificed: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "zone_id": self.zone_id,
            "order_index": self.order_index,
            "attempt": self.attempt,
            "at": self.at,
            "entered": self.entered,
            "completed": self.completed,
            "reason": self.reason,
            "crossing": self.crossing.as_dict() if self.crossing else None,
            "outcomes": [{"subtask_id": k, "outcome": v} for k, v in self.outcomes],
            "sacrificed": list(self.sacrificed),
        }


@dataclass(frozen=True)
class MissionRun:
    """임무 한 번의 끝. 끝나는 모양은 셋뿐이다 — 완료, 어디서 멈춤, 시작 못 함."""

    mission_id: str
    goal_kind: str
    zone_order: tuple[str, ...]
    legs: tuple[ZoneLeg, ...]
    attempts: tuple[ZoneAttempt, ...]
    terminal: str
    completed: bool
    stopped_at_zone: str | None = None
    stopped_at_index: int | None = None
    stop_reason: str | None = None
    unexecuted_zones: tuple[str, ...] = ()
    delivery: MissionApplyResult | None = None

    @property
    def executed_zones(self) -> tuple[str, ...]:
        return tuple(a.zone_id for a in self.attempts if a.completed)

    def as_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "goal_kind": self.goal_kind,
            "zone_order": list(self.zone_order),
            "terminal": self.terminal,
            "completed": self.completed,
            "stopped_at_zone": self.stopped_at_zone,
            "stopped_at_index": self.stopped_at_index,
            "stop_reason": self.stop_reason,
            "executed_zones": list(self.executed_zones),
            "unexecuted_zones": list(self.unexecuted_zones),
            "legs": [leg.as_dict() for leg in self.legs],
            "attempts": [a.as_dict() for a in self.attempts],
            "delivery": (
                {"accepted": self.delivery.accepted, "reason": self.delivery.reason,
                 "version": self.delivery.version}
                if self.delivery is not None else None
            ),
        }


# --- 실행기 ------------------------------------------------------------------


@dataclass
class ZoneMissionRunner:
    """구역을 건너며 임무를 끌고 간다. 분해도 전환 판단도 다시 쓰지 않는다."""

    transit: ZoneTransitRuntime
    library: TaskTemplateLibrary
    registry: CapabilityRegistry
    budget: ResourceBudget = ResourceBudget(compute_units=100.0, memory_mb=8192.0)
    node_tags: frozenset[str] = frozenset()
    #: 그 구역에서 실행자 후보가 무엇인가. 기본은 구역 인프라가 공급하는 kind.
    executor_candidates_fn: Callable[[str], list[ExecutorCandidate]] | None = None
    #: 분해기가 볼 세계 사실. 모르는 사실은 참으로 가정되지 않는다.
    known_facts_fn: Callable[[str], Mapping[str, bool]] | None = None
    #: 단계를 실제로 수행하는 쪽(AI-C-19: 물리 실행은 AI 밖이다).
    execute_fn: Callable[[ZoneLeg, Subtask], MissionItemOutcome] | None = None
    #: 항목별 자율 등급은 발급자가 정한다. 기본은 보수적인 쪽.
    autonomy_fn: Callable[[ZoneLeg, Subtask], MissionAutonomy] | None = None
    cache: MissionCache | None = None
    step_seconds: float = 1.0

    #: 실행기 수준 누적 이력. `run()` 을 다시 불러도 앞 회차가 남는다(AI-B-12).
    history: list[ZoneAttempt] = field(default_factory=list)
    _last_run: MissionRun | None = None

    # --- 조회 ---------------------------------------------------------------

    @property
    def fleet(self) -> FleetModel:
        return self.transit.radio.fleet

    @property
    def last_run(self) -> MissionRun | None:
        return self._last_run

    def attempts_for(self, zone_id: str) -> tuple[ZoneAttempt, ...]:
        return tuple(a for a in self.history if a.zone_id == zone_id)

    # --- 계획 (한 번만) -------------------------------------------------------

    def zone_facts(self, zone_id: str) -> dict[str, bool]:
        """콘솔이 실제로 **아는** 사실만 낸다. 모르는 것은 넣지 않는다.

        `calibration_valid` 나 `operator_present` 를 여기서 채우지 않는 이유는
        분해기의 계약이다 — 없는 사실은 참으로 가정되지 않고, 그것을 요구하는
        단계는 "확인 불가"로 남아 왜 막혔는지가 그대로 드러난다.
        """
        if self.known_facts_fn is not None:
            return dict(self.known_facts_fn(zone_id))
        zone = self.fleet.zone(zone_id)
        return {
            "zone_reachable": self.fleet.zone_state(zone_id) in REACHABLE_STATES,
            "edge_available": bool(zone.get("edge_node")),
        }

    def zone_candidates(self, zone_id: str) -> list[ExecutorCandidate]:
        if self.executor_candidates_fn is not None:
            return list(self.executor_candidates_fn(zone_id))
        return [ExecutorCandidate(
            executor_id=f"{ZONE_SUPPLY_PREFIX}:{zone_id}",
            capability_kinds=frozenset(self.fleet.infrastructure_kinds(zone_id)),
        )]

    def plan(
        self,
        *,
        mission_id: str,
        goal_kind: str,
        zone_order: Sequence[str],
        start_zone: str | None = None,
    ) -> tuple[ZoneLeg, ...]:
        """구역별 계획을 선언된 순서 그대로 만든다. 구역마다 분해 한 번."""
        decomposer = TaskDecomposer(self.registry, self.library)
        previous = start_zone if start_zone is not None else self.transit.zone_id
        legs: list[ZoneLeg] = []
        for index, zone_id in enumerate(zone_order):
            facts = self.zone_facts(zone_id)
            context = DecompositionContext(
                goal_id=f"{mission_id}#{index}",
                goal_kind=goal_kind,
                zone_id=zone_id,
                node_tags=frozenset(self.node_tags),
                budget=self.budget,
                known_facts=facts,
            )
            plan = decomposer.decompose(context, self.zone_candidates(zone_id))
            legs.append(ZoneLeg(
                order_index=index,
                zone_id=zone_id,
                plan=plan,
                radio_handover_required=self.transit.radio.radio_handover_required(
                    previous, zone_id),
                blocked_capabilities=tuple(sorted({
                    kind for s in plan.subtasks for kind in s.missing_required_capabilities
                })),
                known_facts=facts,
            ))
            previous = zone_id
        return tuple(legs)

    # --- 캐시 전달 (AI-N-02, AI-C-19) ----------------------------------------

    def deliver(
        self,
        legs: Sequence[ZoneLeg],
        *,
        mission_id: str,
        origin_command_id: str,
        version: int = 1,
        approved_by: str | None = None,
        deadline: float | None = None,
        issued_at: float | None = None,
    ) -> MissionApplyResult | None:
        """구역별 단계를 말단 캐시로 내린다. 출처 없는 임무는 캐시가 거부한다.

        `required` 는 "지금 실행 가능한 단계"에 붙는다 — 막힌 단계를 필수로
        적으면 임무가 처음부터 실패로 판정되고, 빼 버리면 무엇이 희생됐는지가
        사라진다. 선택 항목으로 남기면 `MissionVerdict` 가 그것을 희생된 선택
        기능으로 적는다(AI-C-05).
        """
        if self.cache is None:
            return None
        items: list[CachedMissionItem] = []
        order = 0
        for leg in legs:
            for subtask in leg.plan.subtasks:
                autonomy = (
                    self.autonomy_fn(leg, subtask) if self.autonomy_fn is not None
                    else MissionAutonomy.REQUIRES_FRESH_COMMAND
                )
                items.append(CachedMissionItem(
                    item_id=subtask.subtask_id,
                    required=subtask.executable,
                    autonomy=autonomy,
                    order_index=order,
                    action=subtask.action,
                    parameters={"zone_id": leg.zone_id, "leg": leg.order_index},
                    description=f"{leg.zone_id}:{subtask.action}",
                ))
                order += 1
        if not any(item.required for item in items):
            # 실행 가능한 단계가 하나도 없으면 내릴 임무가 없다. 캐시의 선언
            # 규칙(필수 1개 이상)을 우회하려고 가짜 필수를 만들지 않는다.
            return None
        return self.cache.apply(MissionDelivery(
            mission_id=mission_id,
            version=version,
            full=True,
            items=tuple(items),
            origin_command_id=origin_command_id,
            approved_by=approved_by,
            issued_at=issued_at,
            deadline=deadline,
        ))

    # --- 실행 ---------------------------------------------------------------

    def run(
        self,
        *,
        mission_id: str,
        goal_kind: str,
        zones: Sequence[str] | None = None,
        start_zone: str | None = None,
        origin_command_id: str | None = None,
        version: int = 1,
        approved_by: str | None = None,
        deadline: float | None = None,
        at: float = 0.0,
        legs: Sequence[ZoneLeg] | None = None,
    ) -> MissionRun:
        """구역을 순서대로 지난다. 끝은 완료이거나 "N번째 구역에서 왜 멈췄는가"다.

        `zones` 가 없으면 맞닿음에서 순서를 유도한다. 주면 그 순서를 그대로
        지킨다 — 실행 중에 순서를 고치지 않는 것이 AI-B-12 의 요구다.
        """
        origin = start_zone if start_zone is not None else self.transit.zone_id
        if zones is None:
            if origin is None:
                return self._not_started(mission_id, goal_kind, STOP_NO_ZONE)
            zone_order = derive_zone_order(self.fleet, origin)
        else:
            zone_order = tuple(zones)
        if not zone_order:
            return self._not_started(mission_id, goal_kind, STOP_NO_ZONE)

        plan_legs = tuple(legs) if legs is not None else self.plan(
            mission_id=mission_id, goal_kind=goal_kind, zone_order=zone_order,
            start_zone=start_zone,
        )
        delivery = None
        if self.cache is not None and origin_command_id:
            delivery = self.deliver(
                plan_legs, mission_id=mission_id, origin_command_id=origin_command_id,
                version=version, approved_by=approved_by, deadline=deadline, issued_at=at,
            )

        attempts: list[ZoneAttempt] = []
        clock = at
        stop: tuple[int, str, str] | None = None

        for leg in plan_legs:
            if self.cache is not None and self.cache.safety_suspended:
                # 로컬 안전 정지 위에 대고 계속하라고 말하지 않는다(AI-C-20).
                snapshot = self.cache.snapshot(now=clock)
                reason = f"{STOP_SAFETY_SUSPENDED}:{snapshot.safety_suspension_reason or ''}"
                stop = (leg.order_index, leg.zone_id, reason)
                attempts.append(self._record(ZoneAttempt(
                    zone_id=leg.zone_id, order_index=leg.order_index,
                    attempt=self._next_attempt(leg.zone_id), at=clock,
                    entered=False, completed=False, reason=reason)))
                break

            crossing, clock = self._enter(leg, clock)
            if crossing is not None and not crossing.confirmed:
                reason = f"{STOP_ZONE_NOT_ENTERED}:{crossing.reason}"
                stop = (leg.order_index, leg.zone_id, reason)
                attempts.append(self._record(ZoneAttempt(
                    zone_id=leg.zone_id, order_index=leg.order_index,
                    attempt=self._next_attempt(leg.zone_id), at=clock,
                    entered=False, completed=False, reason=reason, crossing=crossing)))
                break

            if leg.plan.executor.executor_id is None:
                reason = f"{STOP_NO_EXECUTOR}:{leg.plan.executor.reason}"
            elif not leg.executable_subtasks:
                reason = f"{STOP_PLAN_BLOCKED}:{','.join(leg.blocked_capabilities)}"
            else:
                reason = ""
            if reason:
                stop = (leg.order_index, leg.zone_id, reason)
                attempts.append(self._record(ZoneAttempt(
                    zone_id=leg.zone_id, order_index=leg.order_index,
                    attempt=self._next_attempt(leg.zone_id), at=clock,
                    entered=True, completed=False, reason=reason, crossing=crossing)))
                break

            attempt, clock, failure = self._execute(leg, clock, crossing)
            attempts.append(self._record(attempt))
            if failure is not None:
                stop = (leg.order_index, leg.zone_id, failure)
                break

        if stop is None:
            return self._finish(mission_id, goal_kind, zone_order, plan_legs,
                                tuple(attempts), delivery)
        index, zone_id, reason = stop
        run = MissionRun(
            mission_id=mission_id, goal_kind=goal_kind, zone_order=zone_order,
            legs=plan_legs, attempts=tuple(attempts),
            terminal=f"{MISSION_STOPPED}:{index}:{zone_id}:{reason}",
            completed=False, stopped_at_zone=zone_id, stopped_at_index=index,
            stop_reason=reason,
            unexecuted_zones=tuple(leg.zone_id for leg in plan_legs
                                   if leg.order_index > index),
            delivery=delivery,
        )
        self._last_run = run
        return run

    # --- 단계 ---------------------------------------------------------------

    def _enter(self, leg: ZoneLeg, clock: float) -> tuple[CrossingAttempt | None, float]:
        """그 구역에 들어간다. 이미 거기 있으면 전환을 흉내 내지 않는다."""
        if self.transit.zone_id == leg.zone_id:
            return None, clock
        position = self._position_for(leg.zone_id)
        attempt = self.transit.cross_to(
            leg.zone_id, at=clock, position=position, step_seconds=self.step_seconds)
        spent = max(1, len(attempt.decisions)) * self.step_seconds
        return attempt, clock + spent

    def _position_for(self, zone_id: str) -> Position:
        """그 구역에서 로봇이 있을 자리. 기준은 구역 중심이다(로컬 좌표, AI-C-02)."""
        return self.transit.radio.zone_centre(zone_id)

    def _execute(
        self, leg: ZoneLeg, clock: float, crossing: CrossingAttempt | None
    ) -> tuple[ZoneAttempt, float, str | None]:
        outcomes: list[tuple[str, str]] = []
        sacrificed: list[str] = []
        failure: str | None = None

        for subtask in leg.plan.subtasks:
            if not subtask.executable:
                # 선택 결손·막힌 단계는 멈춤이 아니라 축소다(AI-C-05). "해 봤더니
                # 실패"가 아니라 "시도조차 못 함"이므로 UNAVAILABLE 이다.
                outcomes.append((subtask.subtask_id, MissionItemOutcome.UNAVAILABLE.value))
                sacrificed.append(subtask.subtask_id)
                self._note(subtask.subtask_id, MissionItemOutcome.UNAVAILABLE)
                continue
            if self.cache is not None and self.cache.active_mission is not None \
                    and self.cache.active_mission.item(subtask.subtask_id) is not None:
                self.cache.begin(subtask.subtask_id)
            outcome = (
                self.execute_fn(leg, subtask) if self.execute_fn is not None
                else MissionItemOutcome.SUCCEEDED
            )
            clock += self.step_seconds
            outcomes.append((subtask.subtask_id, outcome.value))
            self._note(subtask.subtask_id, outcome)
            if outcome is MissionItemOutcome.FAILED:
                failure = f"{STOP_STEP_FAILED}:{subtask.subtask_id}"
                break
            if outcome is MissionItemOutcome.UNAVAILABLE:
                sacrificed.append(subtask.subtask_id)

        if failure is not None:
            reason = failure
        elif sacrificed:
            reason = f"{ZONE_DEGRADED}:{','.join(sacrificed)}"
        else:
            reason = ZONE_DONE
        return (
            ZoneAttempt(
                zone_id=leg.zone_id, order_index=leg.order_index,
                attempt=self._next_attempt(leg.zone_id), at=clock,
                entered=True, completed=failure is None, reason=reason,
                crossing=crossing, outcomes=tuple(outcomes),
                sacrificed=tuple(sacrificed),
            ),
            clock,
            failure,
        )

    def _note(self, item_id: str, outcome: MissionItemOutcome) -> None:
        if self.cache is None or self.cache.active_mission is None:
            return
        if self.cache.active_mission.item(item_id) is None:
            return
        self.cache.complete(item_id, outcome)

    def _next_attempt(self, zone_id: str) -> int:
        return len(self.attempts_for(zone_id)) + 1

    def _record(self, attempt: ZoneAttempt) -> ZoneAttempt:
        self.history.append(attempt)
        return attempt

    def _not_started(self, mission_id: str, goal_kind: str, reason: str) -> MissionRun:
        run = MissionRun(
            mission_id=mission_id, goal_kind=goal_kind, zone_order=(), legs=(),
            attempts=(), terminal=f"{MISSION_NOT_STARTED}:{reason}", completed=False,
            stop_reason=reason,
        )
        self._last_run = run
        return run

    def _finish(self, mission_id, goal_kind, zone_order, legs, attempts,
                delivery) -> MissionRun:
        run = MissionRun(
            mission_id=mission_id, goal_kind=goal_kind, zone_order=zone_order,
            legs=legs, attempts=attempts, terminal=MISSION_COMPLETED, completed=True,
            delivery=delivery,
        )
        self._last_run = run
        return run

    # --- 상태 ---------------------------------------------------------------

    def status(self, *, now: float | None = None) -> dict:
        """운영 화면이 읽는 조회 전용 스냅샷. 이 경로로 실행을 바꾸지 않는다(AI-O-06)."""
        run = self._last_run
        return {
            "signal": "zone_mission",
            "run": run.as_dict() if run else None,
            "history": [a.as_dict() for a in self.history],
            "transit": self.transit.status(now=now),
        }


def plan_states(legs: Sequence[ZoneLeg]) -> dict[str, str]:
    """구역별 계획 상태 한 줄 요약 — 화면의 구역 목록에 붙는 값."""
    out: dict[str, str] = {}
    for leg in legs:
        if not leg.runnable:
            out[leg.zone_id] = CapabilityState.DISABLED.value
        elif leg.plan.blocked_subtasks:
            out[leg.zone_id] = CapabilityState.DEGRADED.value
        else:
            out[leg.zone_id] = CapabilityState.ACTIVE.value
    return out


__all__: tuple[str, ...] = (
    "MISSION_COMPLETED",
    "MISSION_NOT_STARTED",
    "MISSION_REASONS",
    "MISSION_STOPPED",
    "MissionRun",
    "STOP_PLAN_BLOCKED",
    "STOP_SAFETY_SUSPENDED",
    "STOP_STEP_FAILED",
    "STOP_ZONE_NOT_ENTERED",
    "ZoneAttempt",
    "ZoneLeg",
    "ZoneMissionRunner",
    "derive_zone_order",
    "plan_states",
)
