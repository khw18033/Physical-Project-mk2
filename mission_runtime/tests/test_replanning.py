"""implements: AI-B-12 (재실행은 원 노드를 덮지 않는다), AI-B-14 (끼워 넣는 단계의
            capability 접지)
관련: AI-B-13 (거부된 단계는 외부 개발 요청의 재료), AI-C-01 (변화 어휘의 정본은
      데이터 사전), AI-C-05 (재계획이 없는 배치도 정상)
tests: blocked route leg splices a detour and links it in, the base revision is
       untouched afterwards, an ungroundable insertion is refused with its reason
       and the requested capability name, no cycle under repeated replans,
       the visit order follows the graph, the four no-change outcomes,
       the change vocabulary is the dictionary's
"""

import json

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from mission_runtime.execution.task_graph import GraphInvalid
from mission_runtime.planning.replanning import (
    ANCHOR_AT_END,
    ANCHOR_AFTER_SUBJECT,
    ANCHOR_BEFORE_SUBJECT,
    ANCHOR_SUPERSEDE_SUBJECT,
    BASELINE_CHANGE_KINDS,
    CHANGE_CAPABILITY_LOST,
    CHANGE_ROUTE_LEG_BLOCKED,
    CHANGE_STEP_FAILED,
    INSERTION_REFUSAL_REASONS_USED,
    LINEAGE_KEPT,
    LINEAGE_NEW,
    LINEAGE_SUPERSEDED,
    MATCH_BOUND_CAPABILITY,
    MATCH_SUBTASK_ID,
    MATCH_VISIT_TARGET,
    REASON_ALL_REFUSED,
    REASON_NO_ANCHOR,
    REASON_NO_REPLANNER,
    REASON_NO_RULE,
    REASON_NO_SITUATION_CHANGE,
    REASON_REPLANNED,
    REASON_UNKNOWN_CHANGE_KIND,
    REFUSE_DUPLICATE_ACTION,
    REFUSE_NO_PROVIDER,
    REFUSE_UNKNOWN_CAPABILITY,
    REPLAN_REASONS_USED,
    ROLE_DECISION,
    ROLE_TASK,
    TARGET_ANCHOR,
    TARGET_END,
    Branch,
    GraphEdge,
    GraphNode,
    GraphRevision,
    InsertedStep,
    ReplanRule,
    ReplanRuleBook,
    Replanner,
    SituationChange,
    default_change_vocabulary,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry, ProviderRegistration

BUDGET = ResourceBudget(compute_units=100.0, memory_mb=4096.0)

#: 구역 인프라가 공급하는 kind. 로봇이 못 내는 단계가 구역 덕분에 되는 경우를
#: `runs_on == ("zone",)` 로 구분해 보여 주는 자리다.
ZONE_KINDS = frozenset({"zone.fixed_camera"})


# ---------------------------------------------------------------------------
# 재료 — 선언된 그래프는 콘솔 payload 모양 그대로 들어온다
# ---------------------------------------------------------------------------


def provider(kind, provider_id, *, hw_tags=()):
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version="1",
        compatibility=CompatibilityProfile(
            required_hw_tags=tuple(hw_tags),
            cost=ResourceCost(compute_units=1.0),
        ),
        requirement=CapabilityRequirement(),
    )


def registry():
    reg = CapabilityRegistry()
    reg.register_local(provider("mobility", "wheel-base"))
    reg.register_local(provider("navigation.reroute", "grid-reroute"))
    reg.register_local(provider("perception.route_check", "clearance-check"))
    reg.register_local(provider("camera", "onboard-rgb"))
    # 메뉴에는 있으나 이 노드의 태그로는 해소되지 않는 kind — `no_provider` 거부의
    # 재료다(어휘에 있다는 것과 지금 쓸 수 있다는 것은 다른 사실이다).
    reg.register_local(provider("sensing.subsurface", "gpr", hw_tags=("gpr",)))
    return reg


def console_payload() -> dict:
    """`tools/fms_console/subtasks.py::SubtaskGraphBuilder.build` 가 내는 모양.

    재계획이 콘솔 계약을 **덧붙이기만** 한다는 것을 시험이 붙잡으려면 들어오는 쪽도
    그 모양이어야 한다. `unverified_preconditions`·`unmet_inputs` 처럼 재계획이
    해석하지 않는 칸을 일부러 넣어 둔다 — 삼켜지면 화면이 설명을 잃는다.
    """
    def node(subtask_id, action, index, kind, provider_id):
        return {
            "subtask_id": subtask_id,
            "action": action,
            "order_index": index,
            "state": CapabilityState.ACTIVE.value,
            "executable": True,
            "runs_on": ["robot"],
            "bindings": [{"capability_kind": kind, "provider_id": provider_id,
                          "source": "registry", "optional": False}],
            "missing_required": [],
            "missing_optional": [],
            "unverified_preconditions": [],
            "violated_forbidden": [],
            "unmet_inputs": [],
            "cost": {"compute_units": 1.0, "memory_mb": 64.0},
        }

    return {
        "plan_id": "goal-7:PATROL_ZONE:1.0.0",
        "goal_id": "goal-7",
        "goal_kind": "PATROL_ZONE",
        "zone_id": "zone-a",
        "robot_id": "robot-1",
        "generator": "template-capability-decomposer",
        "template_version": "1.0.0",
        "reason": "fully_executable",
        "executor": {"executor_id": "robot-1", "state": "ACTIVE", "reason": "selected"},
        "nodes": [
            node("s0", "LOCATE_SELF", 0, "mobility", "wheel-base"),
            node("s1", "TRAVERSE_LEG", 1, "mobility", "wheel-base"),
            node("s2", "OBSERVE", 2, "camera", "onboard-rgb"),
        ],
        "edges": [
            {"from": "s0", "to": "s1", "item": "pose"},
            {"from": "s1", "to": "s2", "item": "arrival"},
        ],
        "escalation_capabilities": [],
    }


#: subtask_id → 그 단계가 가는 자리. 선언 템플릿의 `params` 에 있는 값을 호출자가
#: 옮겨 주는 자리이고, 재계획이 추측해 채우지 않는다.
PLACES = {"s0": "zone-a", "s1": "passage-ab", "s2": "zone-b"}


def base_graph() -> GraphRevision:
    return GraphRevision.from_payload(console_payload(), visit_targets=PLACES)


def detour_rule(*, extra_steps=()) -> ReplanRule:
    """막힌 구간 → 우회 + "경로가 열렸는가" 판정. 분기는 **선언된 결과**다."""
    return ReplanRule(
        rule_id="detour-around-blocked-leg",
        change_kind=CHANGE_ROUTE_LEG_BLOCKED,
        match_on=MATCH_VISIT_TARGET,
        anchor_mode=ANCHOR_BEFORE_SUBJECT,
        steps=(
            InsertedStep(
                action="TRAVERSE_DETOUR",
                requirement=CapabilityRequirement(required=("navigation.reroute",)),
                visit_target_param="detour_via",
                cost=ResourceCost(compute_units=2.0, memory_mb=32.0),
            ),
            InsertedStep(
                action="CHECK_ROUTE",
                requirement=CapabilityRequirement(required=("perception.route_check",)),
                role=ROLE_DECISION,
                question="경로가 열렸는가",
                branches=(
                    Branch("opened", "route_open", TARGET_ANCHOR),
                    Branch("still_blocked", "route_blocked", TARGET_END),
                ),
            ),
        ) + tuple(extra_steps),
    )


def zone_observation_rule() -> ReplanRule:
    """필수 capability 소실 → 그 노드를 밀어내고 구역 공급으로 대체한다.

    대체 단계에는 `visit_target` 이 없다 — 고정 카메라가 보므로 **갈 자리가 없다**.
    그래서 방문 순서에서 자리 하나가 빠지는 것이 이 규칙의 관측 가능한 결과다.
    """
    return ReplanRule(
        rule_id="observe-from-zone-instead",
        change_kind=CHANGE_CAPABILITY_LOST,
        match_on=MATCH_BOUND_CAPABILITY,
        anchor_mode=ANCHOR_SUPERSEDE_SUBJECT,
        steps=(
            InsertedStep(
                action="OBSERVE_FROM_ZONE",
                requirement=CapabilityRequirement(required=("zone.fixed_camera",)),
            ),
        ),
    )


def retry_rule() -> ReplanRule:
    """실패한 단계 → 회차를 올린 **새 노드**. 원 노드는 밀려남으로 남는다."""
    return ReplanRule(
        rule_id="retry-failed-step",
        change_kind=CHANGE_STEP_FAILED,
        match_on=MATCH_SUBTASK_ID,
        anchor_mode=ANCHOR_SUPERSEDE_SUBJECT,
        steps=(),
        re_execute_subject=True,
    )


def rulebook(*rules) -> ReplanRuleBook:
    book = ReplanRuleBook()
    for rule in rules or (detour_rule(), zone_observation_rule(), retry_rule()):
        book.register(rule)
    return book


def replanner(book=None) -> Replanner:
    return Replanner(
        rulebook=book if book is not None else rulebook(),
        registry=registry(),
        node_tags=frozenset({"arm64"}),
        budget=BUDGET,
        zone_supplied_kinds=ZONE_KINDS,
    )


def blocked_leg() -> SituationChange:
    return SituationChange(
        change_kind=CHANGE_ROUTE_LEG_BLOCKED,
        subject="passage-ab",
        detail="debris",
        params={"detour_via": "passage-ac"},
    )


def forward_only(graph: GraphRevision) -> None:
    """간선이 전부 전방인지 **독립적으로** 센다 — 모듈의 불변식을 믿지 않는다.

    DFS 로 순환을 직접 찾는다. 이 검사가 통과하면 위상 정렬이 존재한다.
    """
    adjacency: dict[str, list[str]] = {n.subtask_id: [] for n in graph.nodes}
    for edge in graph.edges:
        adjacency[edge.from_id].append(edge.to_id)

    colour: dict[str, int] = {nid: 0 for nid in adjacency}

    def visit(nid: str, trail: tuple[str, ...]) -> None:
        if colour[nid] == 1:
            raise AssertionError(f"cycle: {' -> '.join(trail + (nid,))}")
        if colour[nid] == 2:
            return
        colour[nid] = 1
        for nxt in adjacency[nid]:
            visit(nxt, trail + (nid,))
        colour[nid] = 2

    for nid in sorted(adjacency):
        visit(nid, ())


# ---------------------------------------------------------------------------
# 1. 막힌 구간이 우회 단계를 낳고 그래프에 **이어진다**
# ---------------------------------------------------------------------------


def test_blocked_route_leg_splices_a_detour_and_links_it_into_the_graph():
    result = replanner().replan(base_graph(), [blocked_leg()])

    assert result.changed is True
    assert result.reason == REASON_REPLANNED

    actions = [n.action for n in result.graph.ordered()]
    assert actions == ["LOCATE_SELF", "TRAVERSE_DETOUR", "CHECK_ROUTE",
                       "TRAVERSE_LEG", "OBSERVE"]

    detour = next(n for n in result.graph.nodes if n.action == "TRAVERSE_DETOUR")
    check = next(n for n in result.graph.nodes if n.action == "CHECK_ROUTE")

    # 떠 있는 사슬이 아니다: 앞 노드에서 들어오고 본래 흐름으로 돌아간다.
    pairs = {(e.from_id, e.to_id) for e in result.graph.edges}
    assert ("s0", detour.subtask_id) in pairs
    assert (detour.subtask_id, check.subtask_id) in pairs
    assert (check.subtask_id, "s1") in pairs
    # 선언 그래프의 자료 흐름 간선은 그대로 남는다 — 재계획이 다시 계산하지 않는다.
    assert ("s0", "s1") in pairs and ("s1", "s2") in pairs

    # 끼워 넣은 단계는 접지됐고 어느 provider 가 받치는지 적혀 있다.
    assert detour.state == CapabilityState.ACTIVE.value
    assert [b.provider_id for b in detour.bindings] == ["grid-reroute"]
    assert detour.runs_on == ("robot",)

    # 계보: 왜 생겼는지와 어느 개정에서 갈라졌는지가 남는다.
    assert detour.node_lineage == LINEAGE_NEW and check.node_lineage == LINEAGE_NEW
    assert detour.inserted_by == f"{CHANGE_ROUTE_LEG_BLOCKED}:passage-ab"
    assert result.graph.node("s1").node_lineage == LINEAGE_KEPT
    assert result.graph.revision == 2 and result.graph.parent_revision == 1
    assert [c.change_kind for c in result.graph.applied_changes] == [CHANGE_ROUTE_LEG_BLOCKED]

    forward_only(result.graph)


def test_payload_keeps_the_console_shape_and_round_trips():
    payload = replanner().replan(base_graph(), [blocked_leg()]).as_payload()

    # 콘솔이 이미 소비하는 칸이 그대로 있다.
    assert payload["goal_kind"] == "PATROL_ZONE"
    assert payload["executor"]["executor_id"] == "robot-1"
    for node in payload["nodes"]:
        assert set(node) >= {"subtask_id", "action", "order_index", "state",
                             "executable", "runs_on", "missing_required",
                             "missing_optional"}
    for edge in payload["edges"]:
        assert set(edge) == {"from", "to", "item"}

    # 재계획이 해석하지 않는 칸은 손대지 않고 되돌려 보낸다.
    kept = next(n for n in payload["nodes"] if n["subtask_id"] == "s1")
    assert kept["unverified_preconditions"] == [] and kept["unmet_inputs"] == []

    # 그 payload 를 다시 개정으로 읽을 수 있다 — 다음 재계획의 입력이 된다.
    again = GraphRevision.from_payload(payload)
    assert [n.subtask_id for n in again.ordered()] == [
        n["subtask_id"] for n in payload["nodes"]
    ]
    assert again.visit_places() == tuple(
        p["place_id"] for p in payload[dd.VISIT_ORDER]
    )


# ---------------------------------------------------------------------------
# 2. 원 개정을 덮지 않는다 (AI-B-12)
# ---------------------------------------------------------------------------


def test_the_base_revision_is_untouched_after_a_replan():
    base = base_graph()
    before = json.dumps(base.as_payload(), sort_keys=True, ensure_ascii=False)

    result = replanner().replan(base, [blocked_leg()])

    assert result.graph is not base
    assert json.dumps(base.as_payload(), sort_keys=True, ensure_ascii=False) == before
    assert len(base.nodes) == 3 and base.revision == 1
    assert base.visit_places() == ("zone-a", "passage-ab", "zone-b")


def test_a_failed_step_is_re_executed_as_a_new_node_and_the_original_stays():
    result = replanner().replan(base_graph(), [
        SituationChange(CHANGE_STEP_FAILED, subject="s1"),
    ])

    original = result.graph.node("s1")
    retry = next(n for n in result.graph.nodes if n.origin_subtask_id == "s1")

    assert original.node_lineage == LINEAGE_SUPERSEDED
    assert original.attempt_index == 1
    assert retry.attempt_index == 2
    assert retry.action == original.action
    assert retry.subtask_id != original.subtask_id
    # 밀려난 노드는 **지워지지 않는다** — 지우면 왜 다시 계획됐는지를 되짚을 대상이
    # 사라진다.
    assert {n.subtask_id for n in result.graph.nodes} >= {"s0", "s1", "s2"}
    forward_only(result.graph)


def test_the_same_failure_delivered_twice_does_not_stack_another_attempt():
    """회차가 전달 횟수만큼 쌓이면 몇 번 **수행했는지**를 그 숫자에서 읽을 수 없다."""
    planner = replanner()
    once = planner.replan(base_graph(), [SituationChange(CHANGE_STEP_FAILED, "s1")]).graph
    again = planner.replan(once, [SituationChange(CHANGE_STEP_FAILED, "s1")])

    assert again.changed is False
    assert again.graph is once
    assert [r.reason for r in again.rejections] == [REFUSE_DUPLICATE_ACTION]
    assert max(n.attempt_index for n in once.nodes) == 2

    retry = next(n for n in once.nodes if n.origin_subtask_id == "s1")
    # 선언 노드의 재실행도 "왜 생겼는가"를 들고 있다.
    assert retry.inserted_by == f"{CHANGE_STEP_FAILED}:s1"


def test_a_second_replan_reports_lineage_against_the_graph_it_was_given():
    first = replanner().replan(base_graph(), [blocked_leg()]).graph
    second = replanner().replan(first, [SituationChange(CHANGE_STEP_FAILED, "s2")]).graph

    # 1 차에서 생긴 노드는 2 차에서 "그대로 남은 것"이다. 앞 개정의 계보를 그대로
    # 보존하면 개정이 쌓일수록 "이번에 무엇이 달라졌는가"를 못 읽는다.
    detour = next(n for n in second.nodes if n.action == "TRAVERSE_DETOUR")
    assert detour.node_lineage == LINEAGE_KEPT
    assert second.revision == 3 and second.parent_revision == 2
    assert next(n for n in second.nodes if n.origin_subtask_id == "s2").node_lineage == LINEAGE_NEW


# ---------------------------------------------------------------------------
# 3. 접지되지 않는 단계는 조용히 끼워지지 않는다 (AI-B-14 → AI-B-13)
# ---------------------------------------------------------------------------


def test_an_ungroundable_step_is_refused_with_its_reason_and_capability_name():
    rule = detour_rule(extra_steps=(
        InsertedStep(
            action="MAP_VOID_UNDER_PASSAGE",
            requirement=CapabilityRequirement(required=("sensing.ground_radar",)),
        ),
    ))
    result = replanner(rulebook(rule)).replan(base_graph(), [blocked_leg()])

    # 접지된 둘은 들어가고 어휘 밖 하나는 들어가지 않는다.
    assert result.changed is True
    assert "MAP_VOID_UNDER_PASSAGE" not in {n.action for n in result.graph.nodes}

    refusal = next(r for r in result.rejections if r.action == "MAP_VOID_UNDER_PASSAGE")
    assert refusal.reason == REFUSE_UNKNOWN_CAPABILITY
    # **요구한 이름이 보존된다** — 그것이 외부 개발 요청의 재료다(AI-B-13).
    assert refusal.requested_capability == "sensing.ground_radar"
    assert refusal.change_kind == CHANGE_ROUTE_LEG_BLOCKED
    assert result.escalation_capabilities == ("sensing.ground_radar",)
    assert result.as_payload()["escalation_capabilities"] == ["sensing.ground_radar"]


def test_a_kind_in_the_menu_that_this_node_cannot_resolve_is_refused_as_no_provider():
    """어휘에 있다는 것과 **지금 이 노드에서 쓸 수 있다**는 것은 다른 사실이다."""
    rule = ReplanRule(
        rule_id="probe-subsurface",
        change_kind=CHANGE_ROUTE_LEG_BLOCKED,
        match_on=MATCH_VISIT_TARGET,
        steps=(InsertedStep(
            action="PROBE_SUBSURFACE",
            requirement=CapabilityRequirement(required=("sensing.subsurface",)),
        ),),
    )
    base = base_graph()
    result = replanner(rulebook(rule)).replan(base, [blocked_leg()])

    assert result.changed is False
    assert result.graph is base
    assert result.reason == REASON_ALL_REFUSED
    assert [(r.reason, r.requested_capability) for r in result.rejections] == [
        (REFUSE_NO_PROVIDER, "sensing.subsurface"),
    ]


def test_every_insertion_is_grounded_in_a_capability_that_has_a_provider():
    menu = replanner().effective_menu()
    graph = replanner().replan(base_graph(), [blocked_leg()]).graph

    for node in graph.nodes:
        if node.node_lineage != LINEAGE_NEW:
            continue
        assert node.bindings, f"{node.subtask_id} was inserted without a binding"
        for binding in node.bindings:
            assert binding.capability_kind in menu
            assert binding.provider_id


# ---------------------------------------------------------------------------
# 4. 순환은 구조적으로 생기지 않는다
# ---------------------------------------------------------------------------


def test_repeated_replans_never_produce_a_cycle():
    graph = base_graph()
    planner = replanner()
    changes = [
        blocked_leg(),
        SituationChange(CHANGE_STEP_FAILED, "s2"),
        SituationChange(CHANGE_ROUTE_LEG_BLOCKED, "passage-ac",
                        params={"detour_via": "passage-ad"}),
        SituationChange(CHANGE_CAPABILITY_LOST, "camera"),
        SituationChange(CHANGE_STEP_FAILED, "s0"),
    ]
    for change in changes:
        graph = planner.replan(graph, [change]).graph
        forward_only(graph)

    assert len(graph.nodes) > 3
    forward_only(graph)


def test_a_backward_edge_is_rejected_so_a_cycle_cannot_be_constructed():
    """순환을 **만들려 해도 만들어지지 않는다**는 쪽을 직접 찍는다.

    불변식은 하나다 — 모든 실행 간선은 `order_index` 가 낮은 쪽에서 높은 쪽으로만
    간다. 되돌아가는 간선 하나가 곧 순환의 재료이므로 개정 생성에서 거절한다.
    """
    nodes = (
        GraphNode(subtask_id="a", action="A", order_index=0),
        GraphNode(subtask_id="b", action="B", order_index=1),
    )
    GraphRevision("g", 1, nodes, edges=(GraphEdge("a", "b"),))  # 전방은 통과

    with pytest.raises(GraphInvalid, match="non-forward"):
        GraphRevision("g", 1, nodes, edges=(GraphEdge("a", "b"), GraphEdge("b", "a")))
    with pytest.raises(GraphInvalid, match="non-forward"):
        GraphRevision("g", 1, nodes, edges=(GraphEdge("a", "a"),))


def test_a_branch_that_loops_backwards_is_not_an_execution_edge():
    """되풀이 분기를 `edges` 에 넣으면 그것이 곧 순환이 된다. 그래서 따로 나간다.

    `execution/task_graph.py::ReferenceEdge` 가 같은 이유로 분리해 둔 것을 그대로
    따른다 — 되돌아가는 관계는 선행 관계가 아니다.
    """
    recheck = ReplanRule(
        rule_id="recheck-after-the-leg",
        change_kind=CHANGE_ROUTE_LEG_BLOCKED,
        match_on=MATCH_VISIT_TARGET,
        anchor_mode=ANCHOR_AFTER_SUBJECT,
        steps=(InsertedStep(
            action="CHECK_ROUTE",
            requirement=CapabilityRequirement(required=("perception.route_check",)),
            role=ROLE_DECISION,
            question="구간을 지났는가",
            branches=(Branch("still_blocked", "route_blocked", TARGET_ANCHOR),),
        ),),
    )
    graph = replanner(rulebook(recheck)).replan(base_graph(), [blocked_leg()]).graph
    payload = graph.as_payload()

    check = next(n for n in graph.nodes if n.action == "CHECK_ROUTE")
    loop = (check.subtask_id, "s1")
    assert loop in {(b["from"], b["to"]) for b in payload["branch_edges"]}
    assert loop not in {(e["from"], e["to"]) for e in payload["edges"]}
    forward_only(graph)

    # 그 분기를 실행 간선으로 적으면 개정이 만들어지지 않는다.
    with pytest.raises(GraphInvalid, match="non-forward"):
        GraphRevision(graph.graph_id, graph.revision, graph.nodes,
                      edges=graph.edges + (GraphEdge(*loop),))


# ---------------------------------------------------------------------------
# 5. 분기 — 선언된 결과이고 BPMN 런타임이 아니다
# ---------------------------------------------------------------------------


def test_a_decision_node_carries_its_question_and_named_branches():
    graph = replanner().replan(base_graph(), [blocked_leg()]).graph
    check = next(n for n in graph.nodes if n.action == "CHECK_ROUTE")

    assert check.node_role == ROLE_DECISION
    assert check.decision is not None
    assert check.decision.question == "경로가 열렸는가"
    assert [(b.name, b.condition) for b in check.decision.branches] == [
        ("opened", "route_open"), ("still_blocked", "route_blocked"),
    ]
    # 작업 노드는 판정이 아니다 — 역할이 섞이지 않는다.
    assert next(n for n in graph.nodes if n.action == "TRAVERSE_DETOUR").node_role == ROLE_TASK

    payload = graph.as_payload()
    branches = {b[dd.BRANCH_NAME]: b for b in payload["branch_edges"]}
    assert branches["opened"]["to"] == "s1"          # 원래 가려던 그 단계로 돌아간다
    assert branches["still_blocked"]["to"] is None   # 여기서 끝난다(화면이 종료로 그린다)
    assert branches["still_blocked"][dd.BRANCH_CONDITION] == "route_blocked"

    node_payload = next(n for n in payload["nodes"] if n["action"] == "CHECK_ROUTE")
    assert node_payload["decision"][dd.DECISION_QUESTION] == "경로가 열렸는가"
    assert node_payload[dd.NODE_ROLE] == ROLE_DECISION


def test_start_and_end_are_derived_from_edges_not_injected_as_nodes():
    graph = replanner().replan(base_graph(), [blocked_leg()]).graph
    payload = graph.as_payload()

    assert payload["entry_nodes"] == ["s0"]
    assert payload["terminal_nodes"] == ["s2"]
    assert all(n[dd.NODE_ROLE] in (ROLE_TASK, ROLE_DECISION) for n in payload["nodes"])


def test_a_branch_pointing_nowhere_is_rejected_at_registration_not_at_runtime():
    """배선 오류는 등록에서 터진다 — 상황 처리 중에 조용히 빈 그래프가 나오면
    무엇이 틀렸는지 아무도 모른다."""
    book = ReplanRuleBook()
    with pytest.raises(ValueError, match="neither a declared step nor a target token"):
        book.register(ReplanRule(
            rule_id="dangling",
            change_kind=CHANGE_ROUTE_LEG_BLOCKED,
            steps=(InsertedStep(
                action="CHECK",
                requirement=CapabilityRequirement(required=("perception.route_check",)),
                branches=(Branch("yes", "ok", "NO_SUCH_STEP"),),
            ),),
        ))


# ---------------------------------------------------------------------------
# 6. 경로는 그래프를 따라간다
# ---------------------------------------------------------------------------


def test_the_visit_order_gains_the_detour_place_and_says_so():
    base = base_graph()
    result = replanner().replan(base, [blocked_leg()])

    assert base.visit_places() == ("zone-a", "passage-ab", "zone-b")
    assert result.graph.visit_places() == ("zone-a", "passage-ac", "passage-ab", "zone-b")
    assert result.graph.visit_order_changed is True
    assert result.graph.visit_order_delta() == {"added": ("passage-ac",), "removed": ()}

    payload = result.graph.as_payload()
    assert [p["place_id"] for p in payload[dd.VISIT_ORDER]] == [
        "zone-a", "passage-ac", "passage-ab", "zone-b",
    ]
    # 자리의 식별자와 순서뿐이다 — 좌표도 픽셀도 나가지 않는다(AI-C-19).
    assert all(set(p) == {"place_id", "subtask_id", "order_index"}
               for p in payload[dd.VISIT_ORDER])
    assert payload["previous_visit_order"] == ["zone-a", "passage-ab", "zone-b"]


def test_a_superseded_node_drops_out_of_the_visit_order():
    """구역 고정 카메라가 보게 되면 **갈 자리가 없다** — 순서에서 자리가 빠진다."""
    result = replanner().replan(base_graph(), [
        SituationChange(CHANGE_CAPABILITY_LOST, subject="camera"),
    ])

    substitute = next(n for n in result.graph.nodes if n.action == "OBSERVE_FROM_ZONE")
    assert substitute.runs_on == ("zone",)
    assert result.graph.node("s2").node_lineage == LINEAGE_SUPERSEDED
    assert result.graph.visit_places() == ("zone-a", "passage-ab")
    assert result.graph.visit_order_delta() == {"added": (), "removed": ("zone-b",)}


def test_the_first_revision_claims_no_visit_order_change():
    """비교 대상이 없는 것을 "바뀌었다"로 적으면 아무것도 안 한 그래프가 변경으로
    읽힌다."""
    base = base_graph()
    assert base.parent_revision is None
    assert base.visit_order_changed is False
    assert base.visit_order_delta() == {"added": (), "removed": ()}


def test_a_node_without_a_declared_place_is_not_guessed_into_the_route():
    graph = GraphRevision.from_payload(console_payload())  # 자리 선언 없이 읽는다

    assert graph.visit_places() == ()
    result = replanner().replan(graph, [blocked_leg()])
    # 자리로 맞출 수 없으니 붙일 데가 없다 — 추측해 끼우지 않는다.
    assert result.changed is False
    assert result.reason == REASON_NO_ANCHOR


# ---------------------------------------------------------------------------
# 7. 없는 것이 정상인 경우 (AI-C-05)
# ---------------------------------------------------------------------------


def test_a_deployment_without_replanning_keeps_the_declared_plan():
    base = base_graph()
    result = Replanner(rulebook=None).replan(base, [blocked_leg()])

    assert result.changed is False
    assert result.graph is base          # 같은 객체 — 새 그래프를 만들지도 않는다
    assert result.reason == REASON_NO_REPLANNER
    assert result.rejections == ()


def test_no_change_no_rule_and_an_unknown_change_kind_all_end_as_reasons():
    base = base_graph()
    planner = replanner()

    assert planner.replan(base, []).reason == REASON_NO_SITUATION_CHANGE

    unknown = planner.replan(base, [SituationChange("meteor_strike", "zone-a")])
    assert unknown.graph is base and unknown.reason == REASON_UNKNOWN_CHANGE_KIND

    empty_book = ReplanRuleBook()
    silent = Replanner(rulebook=empty_book, registry=registry()).replan(base, [blocked_leg()])
    assert silent.graph is base and silent.reason == REASON_NO_RULE

    nowhere = planner.replan(base, [
        SituationChange(CHANGE_ROUTE_LEG_BLOCKED, "passage-zz", params={"detour_via": "x"}),
    ])
    assert nowhere.graph is base and nowhere.reason == REASON_NO_ANCHOR


def test_one_unanswerable_change_does_not_block_the_others():
    result = replanner().replan(base_graph(), [
        SituationChange("meteor_strike", "zone-a"),                      # 어휘 밖
        SituationChange(CHANGE_ROUTE_LEG_BLOCKED, "passage-zz"),         # 붙일 자리 없음
        blocked_leg(),                                                   # 이건 된다
    ])

    assert result.changed is True
    assert "TRAVERSE_DETOUR" in {n.action for n in result.graph.nodes}
    assert result.graph.revision == 2    # 호출 하나 = 개정 하나


def test_a_replanner_without_a_registry_grounds_nothing_and_says_why():
    """레지스트리가 없는 배치에서도 예외가 아니라 사유다."""
    planner = Replanner(rulebook=rulebook(), registry=None)
    result = planner.replan(base_graph(), [blocked_leg()])

    assert result.changed is False
    assert result.reason == REASON_ALL_REFUSED
    assert {r.requested_capability for r in result.rejections} == {
        "navigation.reroute", "perception.route_check",
    }
    assert {r.reason for r in result.rejections} == {REFUSE_UNKNOWN_CAPABILITY}


def test_the_same_change_delivered_twice_does_not_insert_the_same_step_twice():
    """재전달이 그래프를 두 번 늘리면 같은 상황에서 우회가 끝없이 쌓인다."""
    planner = replanner()
    once = planner.replan(base_graph(), [blocked_leg()]).graph
    twice = planner.replan(once, [blocked_leg()])

    assert twice.changed is False
    assert twice.graph is once
    assert twice.reason == REASON_ALL_REFUSED
    assert {r.reason for r in twice.rejections} == {REFUSE_DUPLICATE_ACTION}

    # 다른 자리에서 다시 막힌 것은 다른 사실이다 — 그건 끼워진다.
    elsewhere = planner.replan(once, [
        SituationChange(CHANGE_ROUTE_LEG_BLOCKED, "passage-ac",
                        params={"detour_via": "passage-ad"}),
    ])
    assert elsewhere.changed is True
    assert [n.action for n in elsewhere.graph.ordered()].count("TRAVERSE_DETOUR") == 2
    forward_only(elsewhere.graph)


def test_the_same_inputs_give_the_same_graph():
    """시계도 난수도 쓰지 않는다 — 승인 화면이 같은 상황에서 같은 계획을 봐야 한다."""
    first = replanner().replan(base_graph(), [blocked_leg()]).as_payload()
    second = replanner().replan(base_graph(), [blocked_leg()]).as_payload()

    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == \
        json.dumps(second, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 8. 어휘의 정본은 데이터 사전이다 (AI-C-01)
# ---------------------------------------------------------------------------


def test_the_change_vocabulary_is_the_dictionarys():
    assert default_change_vocabulary().as_tuple() == tuple(sorted(dd.SITUATION_CHANGE_KINDS))
    assert set(BASELINE_CHANGE_KINDS) <= set(dd.SITUATION_CHANGE_KINDS)
    for kind in BASELINE_CHANGE_KINDS:
        assert kind in default_change_vocabulary()


def test_every_reason_and_value_token_is_in_the_dictionary_vocabulary():
    assert set(REPLAN_REASONS_USED) <= set(dd.REPLAN_REASONS)
    assert set(INSERTION_REFUSAL_REASONS_USED) <= set(dd.INSERTION_REFUSAL_REASONS)
    assert {LINEAGE_KEPT, LINEAGE_NEW, LINEAGE_SUPERSEDED} <= set(dd.NODE_LINEAGES)
    assert {ROLE_TASK, ROLE_DECISION} <= set(dd.NODE_ROLES)


def test_the_new_payload_names_are_registered_with_meaning_and_plane():
    for name in (dd.CHANGE_KIND, dd.CHANGE_SUBJECT, dd.GRAPH_REVISION,
                 dd.PARENT_GRAPH_REVISION, dd.NODE_LINEAGE, dd.NODE_ROLE,
                 dd.INSERTED_BY, dd.VISIT_TARGET, dd.VISIT_ORDER, dd.BRANCH_NAME,
                 dd.BRANCH_CONDITION, dd.DECISION_QUESTION, dd.REPLAN_REASON,
                 dd.INSERTION_REFUSAL_REASON, dd.REQUESTED_CAPABILITY,
                 dd.ATTEMPT_INDEX, dd.ORIGIN_SUBTASK_ID):
        spec = dd.spec_for(name)
        assert spec.meaning and spec.produced_by and spec.consumed_by


def test_a_new_change_kind_is_data_plus_a_rule_not_a_core_code_edit():
    """새 변화 종류를 넣는 일이 이 모듈을 고치는 일이어서는 안 된다
    (절대 준수 원칙 #1·#3·#7)."""
    vocabulary = default_change_vocabulary()
    vocabulary.register("water_level_rising", "수위가 올라 그 자리를 못 쓴다")
    book = ReplanRuleBook(vocabulary)
    book.register(ReplanRule(
        rule_id="withdraw-and-watch-from-above",
        change_kind="water_level_rising",
        match_on=MATCH_VISIT_TARGET,
        anchor_mode=ANCHOR_AT_END,
        steps=(InsertedStep(
            action="WATCH_FROM_ZONE",
            requirement=CapabilityRequirement(required=("zone.fixed_camera",)),
        ),),
    ))

    result = replanner(book).replan(base_graph(), [
        SituationChange("water_level_rising", "passage-ab"),
    ])

    assert result.changed is True
    assert result.graph.ordered()[-1].action == "WATCH_FROM_ZONE"
    forward_only(result.graph)


def test_a_rule_for_an_unregistered_change_kind_is_rejected_at_registration():
    book = ReplanRuleBook()
    with pytest.raises(ValueError, match="not in the vocabulary"):
        book.register(ReplanRule(
            rule_id="unregistered",
            change_kind="meteor_strike",
            steps=(InsertedStep(
                action="DUCK",
                requirement=CapabilityRequirement(required=("mobility",)),
            ),),
        ))
