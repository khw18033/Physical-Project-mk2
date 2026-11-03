"""implements: AI-B-12, AI-B-03, AI-C-19
tests: per-zone plans in the declared order, order derived from adjacency,
       a zone that cannot be entered stops the run with a reason and leaves the
       rest unexecuted, a re-run keeps the earlier attempt, optional loss is a
       reduction not a stop, cached steps survive loss of contact
"""

from pathlib import Path

from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.contracts.profile import CompatibilityProfile, ResourceCost
from mission_runtime.execution.mission import MissionItemOutcome
from mission_runtime.ondevice.mission_cache import (
    CachedItemState,
    MissionAutonomy,
    MissionCache,
)
from mission_runtime.planning.decomposition import (
    StepTemplate,
    TaskTemplate,
    TaskTemplateLibrary,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from mission_runtime.tools.fms_console.handover import ZoneRadioMap, ZoneTransitRuntime
from mission_runtime.tools.fms_console.mission import (
    MISSION_COMPLETED,
    MISSION_NOT_STARTED,
    MISSION_STOPPED,
    STOP_PLAN_BLOCKED,
    STOP_SAFETY_SUSPENDED,
    STOP_STEP_FAILED,
    STOP_ZONE_NOT_ENTERED,
    ZoneMissionRunner,
    derive_zone_order,
    plan_states,
)
from mission_runtime.tools.fms_console.subtasks import load_goal_kinds

PROFILE = Path(__file__).resolve().parents[1] / "profiles" / "domains.example.json"
GOAL_KINDS = Path(__file__).resolve().parents[1] / "profiles" / "goal_kinds.example.json"

#: 같은 AP 를 공유하는 두 구역(rec-straight/rec-steep)과 다른 AP 의 한 구역.
#: 무선 전환이 필요한 경계와 그렇지 않은 경계를 한 임무 안에 모두 담는다.
ROUTE = ("rec-straight", "rec-steep", "rec-meander")

#: `m2_close_inspection` 이 요구하는 kind. 선택(`locomotion.rough_terrain`,
#: `perception.depth`)은 일부러 비워 축소 경로를 함께 본다.
CLOSE_INSPECTION_REQUIRED = ("locomotion.ground", "observation.mobile")


def provider(kind: str) -> ProviderRegistration:
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=f"provider-{kind}",
        version="1",
        compatibility=CompatibilityProfile(cost=ResourceCost(compute_units=1.0, memory_mb=64.0)),
        requirement=CapabilityRequirement(),
    )


def registry_with(*kinds: str) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for kind in kinds:
        registry.register_local(provider(kind))
    return registry


def runner_with(
    *kinds: str,
    confirm=None,
    cache: MissionCache | None = None,
    execute=None,
    autonomy=None,
    library: TaskTemplateLibrary | None = None,
) -> ZoneMissionRunner:
    radio = ZoneRadioMap.from_profile(PROFILE, "river")
    transit = ZoneTransitRuntime(radio=radio, cache=cache)
    if confirm is not None:
        transit.confirm_zone_fn = confirm
    if library is None:
        library, _facts = load_goal_kinds(GOAL_KINDS)
    return ZoneMissionRunner(
        transit=transit,
        library=library,
        registry=registry_with(*kinds),
        # 현장 사실은 콘솔이 주는 데이터다. 모르는 사실은 참으로 가정되지 않는다.
        known_facts_fn=lambda zone_id: {"zone_reachable": True},
        execute_fn=execute,
        autonomy_fn=autonomy,
        cache=cache,
    )


# --- 순서: 선언한 대로, 또는 맞닿음에서 유도 --------------------------------------


def test_a_multi_zone_mission_yields_one_plan_per_zone_in_the_declared_order():
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    legs = runner.plan(mission_id="m-1", goal_kind="m2_close_inspection", zone_order=ROUTE)
    assert tuple(leg.zone_id for leg in legs) == ROUTE
    assert tuple(leg.order_index for leg in legs) == (0, 1, 2)
    # 구역마다 분해가 한 번씩 돌았고 계획 id 가 구역별로 다르다.
    assert len({leg.plan.plan_id for leg in legs}) == 3
    for leg in legs:
        assert [s.action for s in leg.plan.subtasks] == [
            "move_to_subject", "observe_close", "record_findings"]
        assert all(s.zone_id == leg.zone_id for s in leg.plan.subtasks)
    # 첫 구역은 접속이고, 같은 AP 경계는 무선 전환이 아니다.
    assert [leg.radio_handover_required for leg in legs] == [True, False, True]


def test_the_order_can_be_derived_from_zone_adjacency():
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    order = derive_zone_order(runner.fleet, "rec-straight")
    assert order[0] == "rec-straight"
    assert set(order) == set(runner.transit.radio.zone_ids())
    # 같은 입력이면 같은 순서여야 한다 — 아니면 "계획대로 됐는가"를 두 번 물을 수 없다.
    assert derive_zone_order(runner.fleet, "rec-straight") == order


def test_a_derived_order_can_be_narrowed_to_the_zones_the_mission_wants():
    """이미 있는 구역은 임무의 한 구간이 아니다 — 거쳐 가되 결과에서는 빠진다."""
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    order = derive_zone_order(runner.fleet, "rec-straight", ["rec-meander", "rec-steep"])
    assert order == ("rec-meander", "rec-steep")
    # 요청했지만 길이 없는 구역은 결과에서 빠지고, 빠진 사실은 비교로 드러난다.
    assert derive_zone_order(runner.fleet, "rec-straight", ["N4-1F-W"]) == ()


def test_a_run_without_any_zone_ends_cleanly_instead_of_raising():
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=())
    assert run.terminal.startswith(MISSION_NOT_STARTED)
    assert run.completed is False
    assert run.legs == () and run.attempts == ()


# --- 정상 경로 -----------------------------------------------------------------


def test_a_mission_that_crosses_three_zones_completes_in_order():
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE)
    assert run.terminal == MISSION_COMPLETED
    assert run.completed is True
    assert tuple(a.zone_id for a in run.attempts) == ROUTE
    assert all(a.entered and a.completed for a in run.attempts)
    assert run.unexecuted_zones == ()
    assert runner.transit.zone_id == "rec-meander"
    # 중간 구역은 같은 AP 라 재접속·구성 재적용이 없었다.
    middle = run.attempts[1].crossing
    assert middle.radio_handover_required is False
    assert middle.crossing.config_refresh_required is False


def test_an_optional_capability_gap_is_a_reduction_not_a_stop():
    """AI-C-05: 선택 결손은 DEGRADED 까지만 내려가고 임무를 멈추지 않는다."""
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE)
    states = {s.action: s.state for s in run.legs[0].plan.subtasks}
    assert states["move_to_subject"] is CapabilityState.DEGRADED     # rough_terrain 없음
    assert states["observe_close"] is CapabilityState.DEGRADED       # depth 없음
    assert run.completed is True
    assert plan_states(run.legs) == {z: CapabilityState.ACTIVE.value for z in ROUTE}


def test_an_unverifiable_precondition_is_not_assumed_true():
    """콘솔이 모르는 사실을 참으로 채우면 실행 전에 드러날 실패가 숨는다."""
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    runner.known_facts_fn = None          # 선언된 사실만 쓰게 한다
    legs = runner.plan(mission_id="m-1", goal_kind="m2_close_inspection", zone_order=ROUTE)
    blocked = legs[0].plan.blocked_subtasks
    assert [s.action for s in blocked] == ["move_to_subject"]
    assert blocked[0].unverified_preconditions == ("zone_reachable",)


# --- 들어가지 못한 구역 ---------------------------------------------------------


def test_a_zone_that_cannot_be_entered_stops_the_run_and_leaves_the_rest_alone():
    runner = runner_with(
        *CLOSE_INSPECTION_REQUIRED,
        confirm=lambda zone_id, at: zone_id != "rec-steep",
    )
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE)

    assert run.completed is False
    assert run.terminal.startswith(f"{MISSION_STOPPED}:1:rec-steep:{STOP_ZONE_NOT_ENTERED}")
    assert run.stopped_at_zone == "rec-steep"
    assert run.stopped_at_index == 1
    assert run.stop_reason.startswith(STOP_ZONE_NOT_ENTERED)
    # 남은 구역을 앞으로 당기거나 조용히 빼지 않는다.
    assert run.unexecuted_zones == ("rec-meander",)
    assert tuple(a.zone_id for a in run.attempts) == ("rec-straight", "rec-steep")
    assert run.executed_zones == ("rec-straight",)
    # 계획 자체는 세 구역 모두 그대로 남아 있다 — 멈춘 것은 실행이다.
    assert tuple(leg.zone_id for leg in run.legs) == ROUTE
    # 요청했지만 사실이 되지 못한 전환이 성공처럼 보이지 않는다.
    failed = run.attempts[1].crossing
    assert failed.requested and not failed.confirmed and failed.failed
    assert runner.transit.zone_id == "rec-straight"


def test_a_rerun_keeps_the_earlier_attempt():
    runner = runner_with(
        *CLOSE_INSPECTION_REQUIRED,
        confirm=lambda zone_id, at: zone_id != "rec-steep",
    )
    first = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE, at=0.0)
    assert first.stopped_at_zone == "rec-steep"

    runner.transit.confirm_zone_fn = lambda zone_id, at: True
    second = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE, at=100.0)
    assert second.terminal == MISSION_COMPLETED

    attempts = runner.attempts_for("rec-steep")
    assert [a.attempt for a in attempts] == [1, 2]
    assert [a.entered for a in attempts] == [False, True]
    # 1회차의 사유가 2회차에 덮이지 않았다.
    assert attempts[0].reason.startswith(STOP_ZONE_NOT_ENTERED)
    assert attempts[1].completed is True
    # 1회차에 이미 끝낸 첫 구역도 회차가 따로 남는다.
    straight = runner.attempts_for("rec-straight")
    assert [a.attempt for a in straight] == [1, 2]
    assert all(a.completed for a in straight)


def test_already_being_in_the_first_zone_is_not_a_fake_crossing():
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    runner.transit.cross_to("rec-straight", at=0.0)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection",
                     zones=("rec-straight",), at=10.0)
    assert run.completed is True
    assert run.attempts[0].crossing is None      # 이미 있었으므로 전환이 없었다
    assert runner.transit.policy.zone_changes == 1


# --- 수행 불가와 실패 -----------------------------------------------------------


def blocked_library() -> TaskTemplateLibrary:
    """모든 단계가 없는 kind 를 요구하는 템플릿. 수행 불가 판정을 보기 위한 것."""
    library, _facts = load_goal_kinds(GOAL_KINDS)
    library.register(TaskTemplate(
        goal_kind="all_steps_need_a_missing_kind",
        version="1",
        steps=(
            StepTemplate("reach", CapabilityRequirement(required=("locomotion.aerial",))),
            StepTemplate("look", CapabilityRequirement(required=("observation.aerial",))),
        ),
    ))
    return library


def test_a_plan_with_no_executable_step_stops_with_the_missing_kinds_named():
    """AI-B-13: 무엇이 없어서 막혔는지가 외부 개발 요청의 입력이다."""
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED, library=blocked_library())
    run = runner.run(mission_id="m-1", goal_kind="all_steps_need_a_missing_kind", zones=ROUTE)
    assert run.completed is False
    assert run.stopped_at_index == 0
    assert run.stop_reason.startswith(STOP_PLAN_BLOCKED)
    assert "locomotion.aerial" in run.stop_reason
    assert run.legs[0].blocked_capabilities == ("locomotion.aerial", "observation.aerial")
    # 들어간 것은 사실이다. 못 한 것은 실행이다 — 두 축을 합치지 않는다.
    assert run.attempts[0].entered is True
    assert run.unexecuted_zones == ("rec-steep", "rec-meander")
    assert plan_states(run.legs)["rec-straight"] == CapabilityState.DISABLED.value


def test_a_failed_step_stops_the_run_at_that_zone():
    def execute(leg, subtask):
        if leg.zone_id == "rec-steep" and subtask.action == "observe_close":
            return MissionItemOutcome.FAILED
        return MissionItemOutcome.SUCCEEDED

    runner = runner_with(*CLOSE_INSPECTION_REQUIRED, execute=execute)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE)
    assert run.completed is False
    assert run.stopped_at_zone == "rec-steep"
    assert run.stop_reason.startswith(STOP_STEP_FAILED)
    assert "observe_close" in run.stop_reason
    assert run.unexecuted_zones == ("rec-meander",)
    outcomes = dict(run.attempts[1].outcomes)
    assert outcomes["rec-steep:move_to_subject:0"] == "SUCCEEDED"
    # 실패한 단계 뒤의 단계는 실행되지 않았다.
    assert "rec-steep:record_findings:2" not in outcomes


def test_an_unavailable_step_is_distinguished_from_a_failed_one():
    """AI-O-02: 정상적인 축소 운용과 핵심 기능 실패는 후속 조치가 다르다."""
    def execute(leg, subtask):
        if subtask.action == "record_findings":
            return MissionItemOutcome.UNAVAILABLE
        return MissionItemOutcome.SUCCEEDED

    runner = runner_with(*CLOSE_INSPECTION_REQUIRED, execute=execute)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE)
    assert run.completed is True
    assert all(a.sacrificed for a in run.attempts)
    assert run.attempts[0].reason.startswith("zone_completed_degraded")


# --- 계획은 한 번만 유도된다 -----------------------------------------------------


def test_the_plan_is_derived_before_execution_and_reused_as_given():
    runner = runner_with(
        *CLOSE_INSPECTION_REQUIRED,
        confirm=lambda zone_id, at: zone_id != "rec-meander",
    )
    legs = runner.plan(mission_id="m-1", goal_kind="m2_close_inspection", zone_order=ROUTE)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection",
                     zones=ROUTE, legs=legs)
    assert run.legs == legs                   # 실행이 계획을 바꾸지 않았다
    assert run.stopped_at_zone == "rec-meander"
    assert tuple(leg.plan.plan_id for leg in run.legs) == tuple(
        leg.plan.plan_id for leg in legs)


# --- 링크 없는 동안의 수행 (AI-N-02, AI-C-19) -------------------------------------


def test_the_per_zone_steps_are_cached_with_their_origin_command():
    cache = MissionCache()
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED, cache=cache)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE,
                     origin_command_id="cmd-7", approved_by="operator-1")
    assert run.delivery is not None and run.delivery.accepted
    assert cache.active_mission.origin_command_id == "cmd-7"
    assert cache.active_mission.approved_by == "operator-1"
    # 구역 세 개 × 단계 세 개가 순서대로 들어 있다.
    items = [item.item_id for item in cache.active_mission.items]
    assert items[:3] == [f"rec-straight:{a}:{i}" for i, a in enumerate(
        ("move_to_subject", "observe_close", "record_findings"))]
    assert len(items) == 9
    assert all(p.state is CachedItemState.DONE for p in cache.progress())


def test_autonomy_is_conservative_unless_the_issuer_says_otherwise():
    """AI-C-19: "말하지 않았다"를 "해도 된다"로 읽으면 AI 가 자율 범위를 넓힌다."""
    cache = MissionCache()
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED, cache=cache)
    runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE,
               origin_command_id="cmd-7")
    assert all(item.autonomy is MissionAutonomy.REQUIRES_FRESH_COMMAND
               for item in cache.active_mission.items)
    assert cache.resumable_without_link() == ()


def test_an_issuer_granted_step_stays_resumable_while_out_of_contact():
    cache = MissionCache()

    def autonomy(leg, subtask):
        if subtask.action == "observe_close":
            return MissionAutonomy.AUTONOMOUS_WHEN_CACHED
        return MissionAutonomy.REQUIRES_FRESH_COMMAND

    runner = runner_with(
        *CLOSE_INSPECTION_REQUIRED, cache=cache, autonomy=autonomy,
        execute=lambda leg, subtask: MissionItemOutcome.SUCCEEDED,
    )
    runner.run(mission_id="m-1", goal_kind="m2_close_inspection",
               zones=("rec-straight",), origin_command_id="cmd-7")
    # 링크를 잃는다 — 그래도 캐시는 발급자가 허가한 항목을 그대로 말한다.
    for tick in range(1, 6):
        runner.transit.observe_unmeasured(at=float(tick))
    state = runner.transit.cache_state()
    assert state["out_of_contact"] is True
    assert state["mission_id"] == "m-1"
    assert state["blocked_pending_command"] == []     # 이미 전부 끝났다
    assert state["completed"]


def test_a_safety_suspension_stops_the_run_before_the_next_zone():
    cache = MissionCache()
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED, cache=cache)

    def execute(leg, subtask):
        if leg.zone_id == "rec-straight" and subtask.action == "record_findings":
            cache.suspend_for_safety("obstacle_within_stopping_distance")
        return MissionItemOutcome.SUCCEEDED

    runner.execute_fn = execute
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE,
                     origin_command_id="cmd-7")
    assert run.completed is False
    assert run.stop_reason.startswith(STOP_SAFETY_SUSPENDED)
    assert run.stopped_at_zone == "rec-steep"
    assert run.unexecuted_zones == ("rec-meander",)
    # 첫 구역은 끝까지 수행됐다 — 정지가 과거를 지우지 않는다.
    assert run.attempts[0].completed is True


def test_a_mission_with_nothing_executable_is_not_delivered_to_the_cache():
    """필수 1개 이상이라는 캐시의 선언 규칙을 가짜 항목으로 우회하지 않는다."""
    cache = MissionCache()
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED, cache=cache,
                         library=blocked_library())
    run = runner.run(mission_id="m-1", goal_kind="all_steps_need_a_missing_kind",
                     zones=ROUTE, origin_command_id="cmd-7")
    assert run.delivery is None
    assert cache.active_mission is None
    assert run.completed is False


# --- 책임 경계 (AI-C-19) --------------------------------------------------------


def test_the_runner_only_executes_through_the_injected_execution_boundary():
    calls: list[tuple[str, str]] = []

    def execute(leg, subtask):
        calls.append((leg.zone_id, subtask.action))
        return MissionItemOutcome.SUCCEEDED

    runner = runner_with(*CLOSE_INSPECTION_REQUIRED, execute=execute)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE)
    assert run.completed is True
    # 실행 가능한 단계만, 선언된 구역 순서대로, 각각 한 번씩.
    assert calls == [
        (zone, action)
        for zone in ROUTE
        for action in ("move_to_subject", "observe_close", "record_findings")
    ]


def test_the_status_view_is_read_only_and_keeps_the_signals_apart():
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE)
    status = runner.status()
    assert status["signal"] == "zone_mission"
    assert status["transit"]["signal"] == "zone_transit"
    assert status["run"]["terminal"] == MISSION_COMPLETED
    assert len(status["history"]) == 3
    # 조회가 실행 상태를 바꾸지 않는다(AI-O-06).
    assert runner.status() == status


def test_the_whole_run_is_json_shaped_for_the_console():
    import json

    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    run = runner.run(mission_id="m-1", goal_kind="m2_close_inspection", zones=ROUTE)
    body = json.loads(json.dumps(run.as_dict()))
    assert body["zone_order"] == list(ROUTE)
    assert [leg["zone_id"] for leg in body["legs"]] == list(ROUTE)
    assert body["attempts"][1]["crossing"]["radio_handover_required"] is False


def test_the_same_inputs_produce_the_same_run():
    def once():
        runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
        return runner.run(mission_id="m-1", goal_kind="m2_close_inspection",
                          zones=ROUTE).as_dict()

    assert once() == once()


def test_an_unknown_goal_kind_is_a_reduced_scope_condition_not_a_crash():
    runner = runner_with(*CLOSE_INSPECTION_REQUIRED)
    run = runner.run(mission_id="m-1", goal_kind="not_deployed_here", zones=ROUTE)
    assert run.completed is False
    assert run.stop_reason is not None
    assert run.stopped_at_index == 0
    assert run.legs[0].plan.subtasks == ()
    assert run.legs[0].plan.reason == "no_template_for_goal_kind"
