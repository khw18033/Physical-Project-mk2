"""implements: AI-B-12 (인수인계도 회차로 보존한다), AI-B-05 (중단되면 원래 자리에
            남는다), AI-B-06, AI-C-05 (넘길 이유가 없는 배치도 정상),
            AI-C-19 (가용성을 재판정하지 않고 발령하지 않는다),
            AI-C-20 (전달·수락·완료를 구분한다), AI-N-03
tests: 두 종류가 서로 다른 답을 낸다, 요청만으로는 담당이 바뀌지 않는다, 바톤이
       비면 넘기지 않는다, 갈리지 않으면 고르지 않는다, 거절 사유 셋이 구분된다,
       미측정은 0 이 아니다, 가용성 None 은 False 가 아니다, 같은 사유의 재전달은
       회차를 올리지 않는다, 중단은 재시도를 막지 않는다, 선언 없는 재개는 모른다고
       말한다, 장부가 "왜 다른 로봇이 하고 있는가"에 답한다
"""

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.contracts.profile import ResourceCost
from mission_runtime.execution.mission_handover import (
    ACCEPTED_IDENTITY_VERDICTS,
    CANDIDATE_REJECTION_REASONS,
    HANDOVER_PHASES,
    HANDOVER_REASONS,
    HANDOVER_TRIGGERS,
    KIND_ASSIGNEE,
    KIND_CUSTODY,
    PHASE_ABANDONED,
    PHASE_ACCEPTED,
    PHASE_COMPLETED,
    PHASE_OFFERED,
    REASON_ALREADY_HANDED_OVER,
    REASON_BATON_INCOMPLETE,
    REASON_CUSTODIAN_UNCHANGED,
    REASON_EVIDENCE_INSUFFICIENT,
    REASON_HANDED,
    REASON_IDENTITY_UNRESOLVED,
    REASON_NO_CANDIDATE,
    REASON_NO_CUSTODIAN_DECLARED,
    REASON_NO_TRIGGER,
    REASON_NOT_SEPARATED,
    REJECT_AVAILABILITY_NOT_RECEIVED,
    REJECT_BACKEND_UNAVAILABLE,
    REJECT_BATTERY_UNKNOWN,
    REJECT_BELOW_RESERVE,
    REJECT_CAPABILITY_SHORTFALL,
    REJECT_IS_CURRENT_ASSIGNEE,
    RESTART,
    RESUME,
    RESUMPTION_UNDECLARED,
    TRIGGER_BACKEND_UNAVAILABLE,
    TRIGGER_BELOW_RESERVE,
    TRIGGER_CAPABILITY_LOST,
    TRIGGER_FAULT_DECLARED,
    TRIGGER_LINK_LOCAL_ONLY,
    TRIGGER_OPERATOR_REQUESTED,
    TRIGGER_ZONE_CONFIRMED,
    BatonEntry,
    HandoverPhaseRejected,
    MissionHandoverLedger,
    MissionHandoverPlanner,
    ResumptionPolicy,
    RobotCondition,
    StateBaton,
    baton_from_revision,
    baton_from_task_graph,
    triggers_for,
)
from mission_runtime.execution.task_graph import NodeState, TaskGraph, TaskNode
from mission_runtime.ondevice.link_handover import LinkPosture
from mission_runtime.ondevice.zone_handover import ZoneEntry
from mission_runtime.perception.device_identity import Verdict
from mission_runtime.planning.replanning import GraphNode, GraphRevision

MISSION = "m-1"
NEED = CapabilityRequirement(required=("perception.detect",), optional=("perception.reid",))
FULL = frozenset({"perception.detect", "perception.reid"})
PARTIAL = frozenset({"perception.detect"})


# -- 재료 ------------------------------------------------------------------


def a_graph(*, executing: str | None = "n2", device: str | None = "go1-a") -> TaskGraph:
    def state(nid: str) -> NodeState:
        if nid == executing:
            return NodeState.EXECUTING
        return NodeState.SUCCEEDED if nid == "n1" else NodeState.PENDING

    return TaskGraph(
        mission_id=MISSION,
        nodes=(
            TaskNode("n1", "둘러본다", state("n1"), node_kind="observe",
                     target_device_id=device),
            TaskNode("n2", "집어 옮긴다", state("n2"), node_kind="manipulate",
                     order_after=("n1",), target_device_id=device),
            TaskNode("n3", "보고한다", state("n3"), node_kind="report",
                     order_after=("n2",), target_device_id=device),
        ),
    )


def a_baton(**kwargs) -> StateBaton:
    return baton_from_task_graph(a_graph(**kwargs), versions={"config_version": "7"})


def a_planner(**kwargs) -> MissionHandoverPlanner:
    kwargs.setdefault("custodian_by_zone", {"zone-b": "edge-b", "zone-a": "edge-a"})
    return MissionHandoverPlanner(**kwargs)


def entered(zone: str = "zone-b", previous: str | None = "zone-a") -> ZoneEntry:
    return ZoneEntry(zone_id=zone, previous_zone=previous,
                     requires_config_refresh=True, reason="confirmed")


def robot(rid: str, **kwargs) -> RobotCondition:
    kwargs.setdefault("backend_available", True)
    kwargs.setdefault("capability_kinds", FULL)
    return RobotCondition(robot_id=rid, **kwargs)


# -- 1. 두 종류는 다른 질문이다 --------------------------------------------


def test_custody_does_not_change_the_executor_so_it_never_asks_about_resumption():
    """구역이 바뀌어 담당 엣지가 바뀌는 것은 **같은 로봇이 같은 일을 계속**하는 것이다.

    반쯤 끝난 n2 가 그대로 돌고 있으므로 "이어서 할까 다시 할까"를 물을 일이 없다.
    """
    decision = a_planner().plan_custody(a_baton(), zone_entry=entered(),
                                        current_custodian="edge-a")
    assert decision.decided and decision.target_id == "edge-b"
    assert decision.kind == KIND_CUSTODY
    assert decision.executor_changes is False
    assert decision.resumption == ()
    assert decision.needs_resumption_decision == ()


def test_assignee_changes_the_executor_so_it_always_asks_about_resumption():
    """로봇이 바뀌면 넘겨받은 쪽은 중간 상태를 들고 있지 않다 — 그래서 반드시 묻는다."""
    planner = a_planner(resumption_policy=ResumptionPolicy(
        by_work_kind={"manipulate": RESTART}))
    decision = planner.plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False),
        candidates=[robot("go1-b")],
    )
    assert decision.decided and decision.target_id == "go1-b"
    assert decision.executor_changes is True
    assert decision.restart_node_ids == ("n2",)
    assert decision.resume_node_ids == ()


# -- 2. 요청과 사실 (AI-C-20) ----------------------------------------------


def test_offering_a_handover_does_not_move_the_custodian_yet():
    """담당은 COMPLETED 에서만 바뀐다. 요청과 사실을 같은 칸에 담지 않는다."""
    ledger = MissionHandoverLedger()
    planner = a_planner(ledger=ledger)
    decision = planner.plan_custody(a_baton(), zone_entry=entered(),
                                    current_custodian="edge-a")
    record = ledger.offer(decision, at=100.0)
    assert record.phase == PHASE_OFFERED
    assert ledger.current_custodian(MISSION) is None

    ledger.accept(MISSION, record.handover_index, at=101.0)
    assert ledger.current_custodian(MISSION) is None

    ledger.complete(MISSION, record.handover_index, at=102.0)
    assert ledger.current_custodian(MISSION) == "edge-b"


def test_an_abandoned_handover_leaves_the_custodian_where_it_was():
    """AI-B-05 — 넘기기 실패는 마지막 정상 상태를 유지한다."""
    ledger = MissionHandoverLedger()
    decision = a_planner(ledger=ledger).plan_custody(
        a_baton(), zone_entry=entered(), current_custodian="edge-a")
    record = ledger.offer(decision, at=1.0)
    ledger.abandon(MISSION, record.handover_index, reason="receiver_timeout", at=2.0)
    assert ledger.current_custodian(MISSION) is None
    # 기록은 **지워지지 않는다** — 요청과 중단이 둘 다 남아야 왜 안 넘어갔는지 안다.
    phases = [r.phase for r in ledger.records(MISSION)]
    assert phases == [PHASE_OFFERED, PHASE_ABANDONED]


def test_phase_transitions_outside_the_table_are_rejected():
    ledger = MissionHandoverLedger()
    decision = a_planner(ledger=ledger).plan_custody(
        a_baton(), zone_entry=entered(), current_custodian="edge-a")
    record = ledger.offer(decision)
    with pytest.raises(HandoverPhaseRejected):
        ledger.complete(MISSION, record.handover_index)  # OFFERED -> COMPLETED 는 없다
    ledger.accept(MISSION, record.handover_index)
    ledger.complete(MISSION, record.handover_index)
    with pytest.raises(HandoverPhaseRejected):
        ledger.accept(MISSION, record.handover_index)  # COMPLETED 는 종단이다


def test_an_undecided_decision_cannot_be_offered():
    """운영 중의 거절은 사유로 끝난다. 장부에 올리는 것은 배선 오류다."""
    ledger = MissionHandoverLedger()
    decision = a_planner(ledger=ledger).plan_custody(a_baton())
    assert not decision.decided and decision.reason == REASON_NO_TRIGGER
    with pytest.raises(ValueError):
        ledger.offer(decision)


# -- 3. 넘길 상태가 비면 넘기지 않는다 --------------------------------------


def test_a_baton_without_execution_state_refuses_the_handover_and_names_the_nodes():
    """"끊기지 않는다"를 **검사**한다. 진행 상태가 빈 노드가 있으면 거절이다."""
    revision = GraphRevision(
        graph_id=MISSION, revision=3,
        nodes=(GraphNode("s1", "move", 0, cost=ResourceCost()),
               GraphNode("s2", "scan", 1, cost=ResourceCost())),
    )
    baton = baton_from_revision(revision, execution_states={"s1": "SUCCEEDED"})
    assert baton.missing_execution_state == ("s2",)
    assert baton.complete is False

    decision = a_planner().plan_custody(baton, zone_entry=entered(),
                                        current_custodian="edge-a")
    assert not decision.decided
    assert decision.reason == REASON_BATON_INCOMPLETE
    assert "s2" in decision.unmeasured


def test_a_capability_state_is_not_an_execution_state():
    """서브태스크 개정의 `state` 는 ACTIVE/DEGRADED/DISABLED 다 — 진행이 아니다.

    그 축을 진행으로 읽으면 "쓸 수 있다"가 "끝났다"로 읽힌다. 그래서 개정에서 뜬
    바톤은 진행 상태를 **빈 칸으로** 두고, 그 칸은 PENDING 이 아니다.
    """
    revision = GraphRevision(
        graph_id=MISSION, revision=1,
        nodes=(GraphNode("s1", "move", 0, state="ACTIVE", cost=ResourceCost()),),
    )
    baton = baton_from_revision(revision)
    assert baton.entries[0].execution_state is None
    assert baton.entries[0].execution_state != NodeState.PENDING.value


def test_a_superseded_subtask_is_not_live_work_and_leaves_the_baton():
    revision = GraphRevision(
        graph_id=MISSION, revision=2,
        nodes=(GraphNode("s1", "move", 0, node_lineage="superseded", cost=ResourceCost()),
               GraphNode("s1#a2", "move", 1, cost=ResourceCost())),
    )
    baton = baton_from_revision(revision, execution_states={"s1#a2": "EXECUTING"})
    assert [e.node_id for e in baton.entries] == ["s1#a2"]
    assert baton.complete


def test_the_baton_digest_is_deterministic_and_moves_with_the_state():
    first = a_baton()
    assert first.digest() == a_baton().digest()
    assert first.digest() != a_baton(executing="n3").digest()


def test_a_baton_does_not_pick_a_device_when_the_nodes_disagree():
    """고르면 그것이 개체 판정이 된다 — 그 판정은 우리 것이 아니다(AI-C-19)."""
    graph = TaskGraph(mission_id=MISSION, nodes=(
        TaskNode("n1", "a", NodeState.SUCCEEDED, target_device_id="go1-a"),
        TaskNode("n2", "b", NodeState.PENDING, target_device_id="go1-b"),
    ))
    assert baton_from_task_graph(graph).device_id is None


# -- 4. custody: 담당을 지어내지 않는다 -------------------------------------


def test_a_zone_without_a_declared_custodian_is_refused_not_guessed():
    decision = a_planner().plan_custody(a_baton(), zone_entry=entered(zone="zone-z"),
                                        current_custodian="edge-a")
    assert decision.reason == REASON_NO_CUSTODIAN_DECLARED
    assert decision.target_id is None


def test_a_deployment_that_declares_no_custodian_map_simply_does_not_hand_over():
    """AI-C-05 — 선언이 비어 있는 배치도 정상이고 예외가 아니다."""
    decision = MissionHandoverPlanner().plan_custody(
        a_baton(), zone_entry=entered(), current_custodian="edge-a")
    assert decision.reason == REASON_NO_CUSTODIAN_DECLARED


def test_moving_inside_the_same_custodian_is_nothing_to_hand():
    decision = a_planner().plan_custody(a_baton(), zone_entry=entered(zone="zone-a"),
                                        current_custodian="edge-a")
    assert decision.reason == REASON_CUSTODIAN_UNCHANGED


def test_an_unresolved_identity_blocks_the_custody_handover():
    """못 가린 개체에 임무 상태를 건네면 그 상태는 다른 로봇의 것이 된다."""
    planner = a_planner()
    for verdict in (Verdict.AMBIGUOUS, Verdict.CONTRADICTED, Verdict.NO_CANDIDATE):
        decision = planner.plan_custody(a_baton(), zone_entry=entered(),
                                        current_custodian="edge-a",
                                        identity_verdict=verdict)
        assert decision.reason == REASON_IDENTITY_UNRESOLVED, verdict
    for verdict in (Verdict.CONFIRMED, Verdict.SOLE_CANDIDATE):
        decision = planner.plan_custody(a_baton(), zone_entry=entered(),
                                        current_custodian="edge-a",
                                        identity_verdict=verdict)
        assert decision.reason == REASON_HANDED, verdict
    assert {v.value for v in (Verdict.CONFIRMED, Verdict.SOLE_CANDIDATE)} == set(
        ACCEPTED_IDENTITY_VERDICTS)


def test_no_confirmed_zone_entry_means_no_trigger():
    """전환 *요청* 으로는 넘기지 않는다 — 일어나지 않은 전환이다."""
    assert a_planner().plan_custody(a_baton()).reason == REASON_NO_TRIGGER


def test_an_unreachable_custodian_is_its_own_trigger():
    decision = a_planner().plan_custody(a_baton(), zone_entry=entered(),
                                        custodian_unreachable=True,
                                        current_custodian="edge-a")
    assert set(decision.trigger) == {TRIGGER_ZONE_CONFIRMED, "custodian_unreachable"}


# -- 5. assignee: 갈리지 않으면 고르지 않는다 -------------------------------


def test_two_equally_fit_robots_are_not_separated_and_both_are_named():
    """`planning/path_candidates.py::choose` 와 같은 규칙이다."""
    decision = a_planner().plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False),
        candidates=[robot("go1-b"), robot("go1-c")],
    )
    assert not decision.decided
    assert decision.reason == REASON_NOT_SEPARATED
    assert decision.tied == ("go1-b", "go1-c")


def test_batteries_close_together_are_not_separated_but_a_clear_gap_is():
    planner = a_planner(reserve_pct=20.0)
    close = planner.plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False, battery_pct=15.0),
        candidates=[robot("go1-b", battery_pct=88.0), robot("go1-c", battery_pct=85.0)],
    )
    assert close.reason == REASON_NOT_SEPARATED
    assert close.margin == pytest.approx(3.0)
    assert close.tied == ("go1-b", "go1-c")

    clear = planner.plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False, battery_pct=15.0),
        candidates=[robot("go1-b", battery_pct=90.0), robot("go1-c", battery_pct=40.0)],
    )
    assert clear.decided and clear.target_id == "go1-b"


def test_a_third_candidate_far_behind_is_not_listed_as_tied():
    """갈리지 않은 것만 묶는다 — 고를 이유가 없는 후보를 목록에 섞지 않는다."""
    decision = a_planner(reserve_pct=20.0).plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False, battery_pct=15.0),
        candidates=[robot("go1-b", battery_pct=90.0), robot("go1-c", battery_pct=85.0),
                    robot("go1-d", battery_pct=30.0)],
    )
    assert decision.reason == REASON_NOT_SEPARATED
    assert decision.tied == ("go1-b", "go1-c")


def test_a_full_capability_robot_beats_a_degraded_one():
    """선택 결손은 축소이고 탈락이 아니다(AI-C-05) — 다만 뒤에 세운다."""
    decision = a_planner().plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False),
        candidates=[robot("go1-b", capability_kinds=PARTIAL), robot("go1-c")],
    )
    assert decision.decided and decision.target_id == "go1-c"


def test_a_degraded_robot_is_still_a_candidate_when_it_is_the_only_one():
    decision = a_planner().plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False),
        candidates=[robot("go1-b", capability_kinds=PARTIAL)],
    )
    assert decision.decided and decision.target_id == "go1-b"


def test_the_order_is_deterministic_so_separation_does_not_flip_between_runs():
    planner = a_planner(reserve_pct=10.0)
    args = dict(requirement=NEED,
                current=robot("go1-a", backend_available=False, battery_pct=5.0))
    pool = [robot("go1-c", battery_pct=40.0), robot("go1-b", battery_pct=90.0)]
    first = planner.plan_assignee(a_baton(), candidates=pool, **args)
    second = planner.plan_assignee(a_baton(), candidates=list(reversed(pool)), **args)
    assert first.target_id == second.target_id == "go1-b"


# -- 6. 거절 사유 셋은 서로 다른 사실이다 -----------------------------------


def test_no_candidate_and_insufficient_evidence_are_different_refusals():
    """하나는 로봇을 들여야 하고 하나는 재면 갈릴 수 있다."""
    planner = a_planner()
    dead = robot("go1-a", backend_available=False)

    empty = planner.plan_assignee(a_baton(), requirement=NEED, current=dead, candidates=[])
    assert empty.reason == REASON_NO_CANDIDATE

    unknown = planner.plan_assignee(
        a_baton(), requirement=NEED, current=dead,
        candidates=[RobotCondition("go1-b", backend_available=None, capability_kinds=FULL)],
    )
    assert unknown.reason == REASON_EVIDENCE_INSUFFICIENT
    assert [r.reason for r in unknown.rejections] == [REJECT_AVAILABILITY_NOT_RECEIVED]

    unfit = planner.plan_assignee(
        a_baton(), requirement=NEED, current=dead,
        candidates=[robot("go1-b", capability_kinds=frozenset())],
    )
    assert unfit.reason == REASON_NO_CANDIDATE
    assert unfit.rejections[0].reason == REJECT_CAPABILITY_SHORTFALL
    assert unfit.rejections[0].detail == "perception.detect"


def test_every_rejection_reason_is_a_declared_token():
    planner = a_planner(reserve_pct=30.0)
    decision = planner.plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False),
        candidates=[
            robot("go1-a"),                                           # 지금 수행자
            robot("go1-b", backend_available=False),                   # 판정: 불가
            RobotCondition("go1-c", backend_available=None),           # 판정: 미수신
            robot("go1-d", capability_kinds=frozenset()),              # 필수 결손
            robot("go1-e"),                                            # 배터리 미측정
            robot("go1-f", battery_pct=5.0),                           # 예비선 아래
            robot("go1-g", fault_codes=("E42",)),                      # 고장 신고
        ],
    )
    reasons = {r.reason for r in decision.rejections}
    assert reasons <= set(CANDIDATE_REJECTION_REASONS)
    assert {REJECT_IS_CURRENT_ASSIGNEE, REJECT_BACKEND_UNAVAILABLE,
            REJECT_AVAILABILITY_NOT_RECEIVED, REJECT_CAPABILITY_SHORTFALL,
            REJECT_BATTERY_UNKNOWN, REJECT_BELOW_RESERVE} <= reasons
    assert decision.reason == REASON_NO_CANDIDATE


# -- 7. 가용성은 소비하고 재판정하지 않는다 (원칙 #15) -----------------------


def test_an_unreceived_availability_verdict_is_not_a_reason_to_move_the_mission():
    """`None` 을 `False` 로 읽으면 그 순간 우리가 가용성을 판정한 것이 된다."""
    assert triggers_for(RobotCondition("go1-a", backend_available=None,
                                       capability_kinds=FULL),
                        requirement=NEED) == ()
    assert triggers_for(RobotCondition("go1-a", backend_available=False,
                                       capability_kinds=FULL),
                        requirement=NEED) == (TRIGGER_BACKEND_UNAVAILABLE,)


def test_a_degraded_capability_is_not_a_reason_to_move_the_mission():
    """AI-C-05 · 절대 준수 원칙 #4 — 선택 결손은 축소이고 임무 이전이 아니다."""
    degraded = RobotCondition("go1-a", backend_available=True, capability_kinds=PARTIAL)
    assert triggers_for(degraded, requirement=NEED) == ()
    lost = RobotCondition("go1-a", backend_available=True, capability_kinds=frozenset())
    assert triggers_for(lost, requirement=NEED) == (TRIGGER_CAPABILITY_LOST,)


def test_the_capability_lost_token_is_the_one_replanning_already_uses():
    """같은 사실에 이름이 둘이면 재계획과 인수인계가 다른 사실을 말하는 것처럼 보인다."""
    from mission_runtime.planning.replanning import CHANGE_CAPABILITY_LOST

    assert TRIGGER_CAPABILITY_LOST == CHANGE_CAPABILITY_LOST
    assert TRIGGER_CAPABILITY_LOST in dd.SITUATION_CHANGE_KINDS


# -- 8. 미측정은 0 이 아니다 -------------------------------------------------


def test_an_unknown_battery_is_not_zero_percent():
    unknown = RobotCondition("go1-a", backend_available=True, capability_kinds=FULL)
    assert triggers_for(unknown, requirement=NEED, reserve_pct=20.0) == ()
    empty = RobotCondition("go1-a", backend_available=True, capability_kinds=FULL,
                           battery_pct=0.0)
    assert triggers_for(empty, requirement=NEED, reserve_pct=20.0) == (TRIGGER_BELOW_RESERVE,)


def test_a_deployment_without_a_declared_reserve_never_looks_at_the_battery():
    """임계값을 코드가 지어내지 않는다."""
    low = RobotCondition("go1-a", backend_available=True, capability_kinds=FULL,
                         battery_pct=1.0)
    assert triggers_for(low, requirement=NEED) == ()


def test_what_could_not_be_measured_is_named_in_the_decision():
    decision = a_planner().plan_assignee(
        a_baton(), requirement=NEED,
        current=RobotCondition("go1-a", backend_available=True, capability_kinds=FULL,
                               fault_codes=("E1",)),
        candidates=[robot("go1-b")],
    )
    assert "battery_pct" in decision.unmeasured
    assert dd.LINK_POSTURE in decision.unmeasured
    assert decision.trigger == (TRIGGER_FAULT_DECLARED,)


def test_a_local_only_link_posture_is_a_trigger_and_uses_the_producers_vocabulary():
    """AI-N-03 — 자세 어휘의 정본은 `ondevice/link_handover.py` 다."""
    condition = RobotCondition("go1-a", backend_available=True, capability_kinds=FULL,
                               link_posture=LinkPosture.LOCAL_ONLY.value)
    assert triggers_for(condition, requirement=NEED) == (TRIGGER_LINK_LOCAL_ONLY,)
    ok = RobotCondition("go1-a", backend_available=True, capability_kinds=FULL,
                        link_posture=LinkPosture.REMOTE_OK.value)
    assert triggers_for(ok, requirement=NEED) == ()


# -- 9. 같은 사유의 재전달은 회차를 올리지 않는다 ---------------------------


def test_the_same_trigger_delivered_twice_does_not_stack_another_handover():
    """AI-C-20 이 같은 command_id 의 재전달을 다시 실행하지 않게 한 것과 같은 성질."""
    ledger = MissionHandoverLedger()
    planner = a_planner(ledger=ledger)
    dead = robot("go1-a", backend_available=False)

    first = planner.plan_assignee(a_baton(), requirement=NEED, current=dead,
                                  candidates=[robot("go1-b")])
    ledger.offer(first, at=1.0)
    again = planner.plan_assignee(a_baton(), requirement=NEED, current=dead,
                                  candidates=[robot("go1-b")])
    assert again.reason == REASON_ALREADY_HANDED_OVER
    assert ledger.next_index(MISSION) == 2  # 회차는 하나뿐이다


def test_an_abandoned_handover_does_not_block_a_retry():
    """중단을 재시도 금지로 읽으면 한 번 실패한 임무가 그 로봇에 갇힌다."""
    ledger = MissionHandoverLedger()
    planner = a_planner(ledger=ledger)
    dead = robot("go1-a", backend_available=False)

    first = planner.plan_assignee(a_baton(), requirement=NEED, current=dead,
                                  candidates=[robot("go1-b")])
    record = ledger.offer(first, at=1.0)
    ledger.abandon(MISSION, record.handover_index, reason="receiver_refused", at=2.0)

    retry = planner.plan_assignee(a_baton(), requirement=NEED, current=dead,
                                  candidates=[robot("go1-c")])
    assert retry.decided and retry.target_id == "go1-c"


def test_the_same_trigger_from_a_different_source_is_a_different_fact():
    ledger = MissionHandoverLedger()
    planner = a_planner(ledger=ledger)
    first = planner.plan_assignee(a_baton(), requirement=NEED,
                                  current=robot("go1-a", backend_available=False),
                                  candidates=[robot("go1-b")])
    record = ledger.offer(first, at=1.0)
    ledger.accept(MISSION, record.handover_index, at=2.0)
    ledger.complete(MISSION, record.handover_index, at=3.0)

    # 넘겨받은 로봇이 같은 사유로 또 쓰러진 것은 **다른 사실**이다.
    second = planner.plan_assignee(a_baton(), requirement=NEED,
                                   current=robot("go1-b", backend_available=False),
                                   candidates=[robot("go1-c")])
    assert second.decided and second.target_id == "go1-c"


# -- 10. 반쯤 끝난 일: 선언에서 읽거나 모른다고 말한다 ----------------------


def test_an_undeclared_resumption_says_it_does_not_know_instead_of_guessing():
    """기본값을 "이어서 한다"로 두면 선언을 깜박한 배치가 위험한 쪽으로 돈다."""
    decision = a_planner().plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False),
        candidates=[robot("go1-b")],
    )
    assert decision.needs_resumption_decision == ("n2",)
    assert decision.restart_node_ids == () and decision.resume_node_ids == ()
    assert decision.resumption[0].resumption == RESUMPTION_UNDECLARED


def test_a_declared_resumption_is_read_per_work_kind_and_overridden_per_node():
    policy = ResumptionPolicy(by_work_kind={"manipulate": RESTART, "observe": RESUME},
                              by_node_id={"n2": RESUME})
    assert policy.for_entry(BatonEntry("n2", "EXECUTING", work_kind="manipulate")
                            ).resumption == RESUME
    assert policy.for_entry(BatonEntry("n9", "EXECUTING", work_kind="manipulate")
                            ).resumption == RESTART


def test_only_in_flight_work_is_asked_about():
    """끝난 일과 시작하지 않은 일은 물을 것이 없다."""
    baton = a_baton()
    assert [e.node_id for e in baton.in_flight] == ["n2"]
    assert [e.node_id for e in a_baton(executing=None).in_flight] == []


def test_a_resumption_policy_cannot_declare_unknown():
    """모름은 선언하지 않는 것으로 표현한다 — 선언 칸에 "모름"을 넣지 않는다."""
    with pytest.raises(ValueError):
        ResumptionPolicy(by_work_kind={"manipulate": RESUMPTION_UNDECLARED})


# -- 11. 장부가 "왜 다른 로봇이 하고 있는가"에 답한다 -----------------------


def test_the_ledger_explains_why_another_robot_is_doing_it():
    ledger = MissionHandoverLedger()
    planner = a_planner(ledger=ledger, reserve_pct=20.0)

    first = planner.plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False, battery_pct=80.0),
        candidates=[robot("go1-b", battery_pct=90.0)])
    r1 = ledger.offer(first, at=10.0)
    ledger.accept(MISSION, r1.handover_index, at=11.0)
    ledger.complete(MISSION, r1.handover_index, at=12.0)

    second = planner.plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-b", battery_pct=5.0),
        candidates=[robot("go1-c", battery_pct=70.0)])
    r2 = ledger.offer(second, at=20.0)
    ledger.accept(MISSION, r2.handover_index, at=21.0)
    ledger.complete(MISSION, r2.handover_index, at=22.0)

    chain = ledger.explain(MISSION)
    assert [(c["from_id"], c["to_id"]) for c in chain] == [
        ("go1-a", "go1-b"), ("go1-b", "go1-c")]
    assert chain[0]["handover_trigger"] == [TRIGGER_BACKEND_UNAVAILABLE]
    assert chain[1]["handover_trigger"] == [TRIGGER_BELOW_RESERVE]
    assert ledger.current_assignee(MISSION) == "go1-c"


def test_the_ledger_never_rewrites_a_record():
    ledger = MissionHandoverLedger()
    planner = a_planner(ledger=ledger)
    decision = planner.plan_assignee(a_baton(), requirement=NEED,
                                     current=robot("go1-a", backend_available=False),
                                     candidates=[robot("go1-b")])
    offered = ledger.offer(decision, at=1.0)
    ledger.accept(MISSION, offered.handover_index, at=2.0)
    ledger.complete(MISSION, offered.handover_index, at=3.0)
    records = ledger.records(MISSION)
    assert [r.phase for r in records] == [PHASE_OFFERED, PHASE_ACCEPTED, PHASE_COMPLETED]
    assert records[0] == offered           # 원 기록은 그 객체 그대로다
    assert len({r.handover_index for r in records}) == 1
    assert len({r.baton_digest for r in records}) == 1


def test_custody_and_assignee_counts_share_the_missions_handover_numbering():
    """회차는 임무의 인수인계 횟수다 — 종류별로 번호를 따로 매기면 "몇 번째"가
    둘이 되고 두 숫자는 곧 어긋난다."""
    ledger = MissionHandoverLedger()
    planner = a_planner(ledger=ledger)
    custody = planner.plan_custody(a_baton(), zone_entry=entered(),
                                   current_custodian="edge-a")
    first = ledger.offer(custody, at=1.0)
    assignee = planner.plan_assignee(a_baton(), requirement=NEED,
                                     current=robot("go1-a", backend_available=False),
                                     candidates=[robot("go1-b")])
    second = ledger.offer(assignee, at=2.0)
    assert (first.handover_index, second.handover_index) == (1, 2)


# -- 12. 조회 전용 payload --------------------------------------------------


def test_the_payload_is_read_only_and_carries_the_reason_not_just_the_target():
    decision = a_planner().plan_assignee(
        a_baton(), requirement=NEED,
        current=robot("go1-a", backend_available=False),
        candidates=[robot("go1-b"), robot("go1-c")])
    payload = decision.as_payload()
    assert payload["decided"] is False
    assert payload["handover_reason"] == REASON_NOT_SEPARATED
    assert payload["tied"] == ["go1-b", "go1-c"]
    assert payload[dd.MISSION_ID] == MISSION
    assert payload["state_baton"]["complete"] is True
    # 픽셀도 색도 좌표도 없다(AI-C-19, AI-C-08).
    assert not {"color", "pixel", "x", "y"} & set(payload)


def test_the_ledger_payload_answers_who_holds_it_and_why():
    ledger = MissionHandoverLedger()
    planner = a_planner(ledger=ledger)
    record = ledger.offer(planner.plan_custody(a_baton(), zone_entry=entered(),
                                               current_custodian="edge-a"), at=1.0)
    ledger.accept(MISSION, record.handover_index, at=2.0)
    ledger.complete(MISSION, record.handover_index, at=3.0)
    payload = ledger.as_payload(MISSION)
    assert payload["custodian_node_id"] == "edge-b"
    assert payload["assignee_id"] is None
    assert payload["handover_count"] == 1
    assert len(payload["records"]) == 3


def test_the_declared_vocabularies_have_no_overlap_and_no_strays():
    """사유·단계·촉발이 서로 다른 축이다. 한 축에 섞으면 화면이 구분을 잃는다."""
    assert len(set(HANDOVER_REASONS)) == len(HANDOVER_REASONS)
    assert len(set(HANDOVER_TRIGGERS)) == len(HANDOVER_TRIGGERS)
    assert len(set(HANDOVER_PHASES)) == len(HANDOVER_PHASES)
    assert not set(HANDOVER_REASONS) & set(HANDOVER_PHASES)
    assert TRIGGER_OPERATOR_REQUESTED in HANDOVER_TRIGGERS
    assert set(CANDIDATE_REJECTION_REASONS) & set(HANDOVER_REASONS) == set()
    # 촉발과 탈락이 **의도적으로** 나누는 한 이름: 같은 사실("고장을 신고했다")이
    # 수행 중인 로봇에게는 넘길 사유이고 후보에게는 탈락 사유다. 이름을 갈라 두면
    # 같은 신고가 두 사실처럼 읽힌다(AI-C-01).
    assert set(CANDIDATE_REJECTION_REASONS) & set(HANDOVER_TRIGGERS) == {
        TRIGGER_FAULT_DECLARED}


def test_both_kinds_are_the_only_two_and_a_decision_knows_which_it_is():
    custody = a_planner().plan_custody(a_baton(), zone_entry=entered(),
                                       current_custodian="edge-a")
    assignee = a_planner().plan_assignee(a_baton(), requirement=NEED,
                                         current=robot("go1-a", backend_available=False),
                                         candidates=[robot("go1-b")])
    assert (custody.kind, assignee.kind) == (KIND_CUSTODY, KIND_ASSIGNEE)
    assert custody.executor_changes is False and assignee.executor_changes is True
