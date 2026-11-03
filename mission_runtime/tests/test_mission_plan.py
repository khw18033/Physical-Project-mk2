"""implements: AI-B-12
tests: external plan consumed without re-deriving it, lossless status carry,
       branch/repeat kept out of the DAG, parallel groups derived, unmapped
       fields reported rather than dropped
"""

from __future__ import annotations

import pytest

from mission_runtime.execution.mission_plan import (
    SKIPPED_STATUSES,
    STATUS_MAP,
    PlanInvalid,
    task_graph_from_plan,
)
from mission_runtime.execution.task_graph import NodeState


def _task(task_id, status="pending", deps=(), **kw):
    base = {
        "task_id": task_id,
        "title": f"{task_id} 제목",
        "deps": list(deps),
        "status": status,
        "attempt": 1,
        "derived_from": None,
        "action_items": [],
        "evaluation": None,
    }
    base.update(kw)
    return base


def _plan(**kw):
    base = {
        "mission_id": "MSN-1",
        "utterance": {
            "audio_ref": None, "text": "현장을 점검해라", "engine": "script",
            "confidence": 1.0,
        },
        "milestones": [
            {
                "milestone_id": "MS-A", "title": "접근", "order": 0, "status": "done",
                "assigned_targets": ["dev-1"],
                "tasks": [_task("T-1", "done", node_kind="sense", target="dev-1")],
            },
            {
                "milestone_id": "MS-B", "title": "점검", "order": 1, "status": "running",
                "assigned_targets": ["dev-1"],
                "tasks": [
                    _task("T-2", "running", node_kind="act", target="dev-1"),
                    _task("T-3", "pending", node_kind="act", target="dev-1"),
                    _task("T-4", "pending", deps=["T-2", "T-3"], node_kind="verify"),
                ],
            },
        ],
    }
    base.update(kw)
    return base


# -- 소비 경계 ---------------------------------------------------------------


def test_plan_is_consumed_not_regenerated():
    """분해 결과를 그대로 받는다 — 노드 집합이 입력의 태스크 집합과 같다."""
    result = task_graph_from_plan(_plan())
    assert result.mission_id == "MSN-1"
    assert [n.node_id for n in result.graph.nodes] == ["T-1", "T-2", "T-3", "T-4"]
    assert result.utterance_text == "현장을 점검해라"


def test_module_does_not_decompose_anything_itself():
    """계획 생성 어휘(마일스톤 생성·템플릿·LLM)가 코드에 없다."""
    import io
    import tokenize
    from pathlib import Path

    import mission_runtime.execution.mission_plan as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("decompose", "template", "generate_plan", "llm", "prompt")
    leaked = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
            continue
        low = token.string.lower()
        leaked += [(n, token.start[0]) for n in banned if n in low]
    assert not leaked, f"plan generation leaked in: {leaked}"


def test_input_is_not_mutated():
    plan = _plan()
    before = repr(plan)
    task_graph_from_plan(plan)
    assert repr(plan) == before


def test_same_input_gives_the_same_graph():
    a = task_graph_from_plan(_plan()).graph
    b = task_graph_from_plan(_plan()).graph
    assert [n.node_id for n in a.nodes] == [n.node_id for n in b.nodes]
    assert a.parallel_groups() == b.parallel_groups()


# -- 상태 환산과 보존 --------------------------------------------------------


def test_status_is_converted_and_the_original_is_kept():
    """환산은 하되 원본을 잃지 않는다(AI-B-12)."""
    result = task_graph_from_plan(_plan())
    t1 = result.graph.node("T-1")
    assert t1.state is NodeState.SUCCEEDED
    assert t1.source_status == "done"
    assert result.graph.node("T-2").state is NodeState.EXECUTING
    assert result.graph.node("T-2").source_status == "running"


@pytest.mark.parametrize("status,expected", [
    ("pending", NodeState.PENDING),
    ("running", NodeState.EXECUTING),
    ("rerunning", NodeState.EXECUTING),
    ("awaiting_evaluation", NodeState.EXECUTING),
    ("done", NodeState.SUCCEEDED),
    ("failed", NodeState.FAILED),
])
def test_every_mapped_status(status, expected):
    plan = _plan(milestones=[{
        "milestone_id": "MS", "order": 0, "status": "running", "tasks": [_task("T", status)],
        "assigned_targets": [],
    }])
    node = task_graph_from_plan(plan).graph.node("T")
    assert node.state is expected
    assert node.source_status == status


def test_awaiting_evaluation_is_not_terminal():
    """판정 대기는 끝난 것이 아니다 — 종단으로 접으면 재판정이 불가능해진다."""
    plan = _plan(milestones=[{
        "milestone_id": "MS", "order": 0, "status": "running",
        "tasks": [_task("T", "awaiting_evaluation")], "assigned_targets": [],
    }])
    node = task_graph_from_plan(plan).graph.node("T")
    assert node.state.is_terminal is False


def test_unknown_status_is_rejected_rather_than_folded_into_pending():
    plan = _plan(milestones=[{
        "milestone_id": "MS", "order": 0, "status": "running",
        "tasks": [_task("T", "some_new_status")], "assigned_targets": [],
    }])
    with pytest.raises(PlanInvalid, match="unknown status"):
        task_graph_from_plan(plan)


@pytest.mark.parametrize("status", sorted(SKIPPED_STATUSES))
def test_branch_not_taken_is_reported_separately_not_as_pending_or_failed(status):
    """선택되지 않은 갈래를 PENDING 으로 두면 영원히 기다리는 노드가 되고,
    FAILED 로 두면 실패하지 않은 것을 실패로 센다."""
    plan = _plan(milestones=[{
        "milestone_id": "MS", "order": 0, "status": "running",
        "tasks": [_task("T-live", "running"), _task("T-skip", status)],
        "assigned_targets": [],
    }])
    result = task_graph_from_plan(plan)
    assert [n.node_id for n in result.graph.nodes] == ["T-live"]
    assert result.skipped_node_ids == (("T-skip", status),)
    counts = result.graph.state_counts()
    assert counts.by_state["PENDING"] == 0
    assert counts.by_state["FAILED"] == 0


def test_status_map_covers_the_six_display_states_without_inventing_any():
    assert set(STATUS_MAP.values()) <= set(NodeState)


# -- 관계 환산 ---------------------------------------------------------------


def test_result_dependencies_come_through_as_declared():
    g = task_graph_from_plan(_plan()).graph
    assert g.node("T-4").depends_on == ("T-2", "T-3")


def test_milestone_order_becomes_execution_order_from_terminal_tasks():
    """입력 계약이 "앞 마일스톤 뒤에 이어진다"고 정한 것을 실선 간선으로 받는다."""
    g = task_graph_from_plan(_plan()).graph
    assert g.node("T-2").order_after == ("T-1",)
    assert g.node("T-3").order_after == ("T-1",)
    # 명시된 결과 의존이 있는 태스크에는 순서를 덧씌우지 않는다.
    assert g.node("T-4").order_after == ()


def test_parallel_group_is_derived_from_identical_predecessors():
    """병렬은 선언이 아니라 "제약이 없어서 남는 것"이다 — 그래서 파생한다."""
    groups = task_graph_from_plan(_plan()).graph.parallel_groups()
    assert len(groups) == 1
    (members,) = groups.values()
    assert set(members) == {"T-2", "T-3"}


def test_a_single_task_is_not_a_parallel_group():
    plan = _plan(milestones=[{
        "milestone_id": "MS", "order": 0, "status": "running",
        "tasks": [_task("T-only", "running")], "assigned_targets": [],
    }])
    assert task_graph_from_plan(plan).graph.parallel_groups() == {}


def test_branch_and_repeat_become_reference_edges_outside_the_dag():
    """되풀이를 deps 에 넣으면 순환이 되어 깊이 계산이 무한 재귀한다."""
    plan = _plan()
    plan["milestones"].append({
        "milestone_id": "MS-C", "title": "재탐색", "order": 2, "status": "pending",
        "assigned_targets": [], "tasks": [_task("T-5", "pending")],
        "branch": {"from": "MS-B", "when": "fail"},
        "repeat_of": {"to": "MS-B", "when": "fail"},
    })
    result = task_graph_from_plan(plan)
    kinds = {e.kind for e in result.graph.reference_edges}
    assert kinds == {"branch", "repeat"}
    branch = next(e for e in result.graph.reference_edges if e.kind == "branch")
    repeat = next(e for e in result.graph.reference_edges if e.kind == "repeat")
    assert (branch.from_node_id, branch.to_node_id, branch.when) == ("T-4", "T-5", "fail")
    assert (repeat.from_node_id, repeat.to_node_id, repeat.when) == ("T-5", "T-2", "fail")
    # 참조 간선은 선행 관계가 아니다.
    assert "T-5" not in result.graph.node("T-2").predecessors
    assert result.graph.node("T-5").depends_on == ()


def test_reference_edge_to_an_unknown_milestone_is_reported_not_dropped():
    plan = _plan()
    plan["milestones"][1]["branch"] = {"from": "MS-GHOST", "when": "pass"}
    result = task_graph_from_plan(plan)
    assert any("reference_edge" in u for u in result.unmapped)
    assert result.graph.reference_edges == ()


# -- 축 분리 -----------------------------------------------------------------


def test_target_is_a_device_not_an_accelerator_or_service():
    """어느 로봇이 하는가와 어느 연산기에서 도는가는 같은 질문이 아니다."""
    node = task_graph_from_plan(_plan()).graph.node("T-2")
    assert node.target_device_id == "dev-1"
    assert node.accelerator_id is None
    assert node.service_id is None


def test_node_kind_is_carried_verbatim_without_branching():
    g = task_graph_from_plan(_plan()).graph
    assert g.node("T-1").node_kind == "sense"
    assert g.node("T-4").node_kind == "verify"


def test_derived_from_becomes_the_re_execution_origin():
    plan = _plan(milestones=[{
        "milestone_id": "MS", "order": 0, "status": "running", "assigned_targets": [],
        "tasks": [
            _task("T-a", "failed"),
            _task("T-b", "rerunning", attempt=2, derived_from="T-a"),
        ],
    }])
    g = task_graph_from_plan(plan).graph
    assert g.node("T-b").origin_node_id == "T-a"
    assert g.node("T-b").attempt == 2
    assert [n.node_id for n in g.attempts_of("T-b")] == ["T-a", "T-b"]


# -- 버리지 않는다 -----------------------------------------------------------


def test_fields_we_do_not_convert_are_reported():
    """조용히 사라지면 다음 사람이 그 계약을 다시 읽어야 한다."""
    result = task_graph_from_plan(_plan())
    assert any(u.endswith(".evaluation") for u in result.unmapped)
    assert any(u.endswith(".action_items") for u in result.unmapped)
    assert any("assigned_targets" in u for u in result.unmapped)
    assert any(u.startswith("utterance.") for u in result.unmapped)


def test_unmapped_paths_are_deduplicated_and_point_at_the_input():
    result = task_graph_from_plan(_plan())
    assert len(result.unmapped) == len(set(result.unmapped))
    assert all(
        u.startswith(("milestones", "utterance", "reference_edge"))
        for u in result.unmapped
    ), result.unmapped


# -- 입력 검증 ---------------------------------------------------------------


def test_missing_mission_id_is_rejected():
    plan = _plan()
    del plan["mission_id"]
    with pytest.raises(PlanInvalid, match="mission_id"):
        task_graph_from_plan(plan)


def test_missing_milestones_is_rejected():
    plan = _plan()
    del plan["milestones"]
    with pytest.raises(PlanInvalid, match="milestones"):
        task_graph_from_plan(plan)


def test_task_without_status_is_rejected():
    plan = _plan(milestones=[{
        "milestone_id": "MS", "order": 0, "status": "running", "assigned_targets": [],
        "tasks": [{"task_id": "T", "title": "t", "deps": []}],
    }])
    with pytest.raises(PlanInvalid, match="status"):
        task_graph_from_plan(plan)


def test_milestones_are_ordered_by_their_declared_order():
    plan = _plan()
    plan["milestones"][0]["order"] = 5      # MS-A 를 뒤로
    g = task_graph_from_plan(plan).graph
    # 이제 MS-B 가 먼저이므로 T-1 이 MS-B 의 종단을 선행으로 받는다.
    assert g.node("T-1").order_after == ("T-4",)
    assert g.node("T-2").order_after == ()


def test_empty_plan_is_a_valid_empty_graph():
    result = task_graph_from_plan({"mission_id": "MSN-0", "milestones": []})
    assert result.graph.nodes == ()
    assert result.graph.mission_id == "MSN-0"
