"""implements: AI-B-12
tests: 6-state transitions, dependency/parallel structure, re-execution lineage,
       deterministic focus rule, read-only snapshots, domain neutrality
"""

from __future__ import annotations

import pytest

from mission_runtime.execution.task_graph import (
    FOCUS_REASON_ATTENTION,
    FOCUS_REASON_LATEST_EXECUTING,
    FOCUS_REASON_NO_CANDIDATE,
    FOCUS_REASON_PINNED,
    GraphInvalid,
    NodeState,
    OFF_DEVICE,
    TaskGraph,
    TaskNode,
    TransitionRejected,
)


def _graph() -> TaskGraph:
    """두 갈래가 병렬로 돌고 하나가 둘의 결과에 의존하는 최소 구조."""
    return TaskGraph(
        mission_id="m-1",
        nodes=(
            TaskNode("n1", "첫 단계", state=NodeState.SUCCEEDED, service_id="svc-a",
                     accelerator_id="acc-0", state_changed_at=10.0),
            TaskNode("n2", "병렬 A", order_after=("n1",), parallel_group="g1",
                     service_id="svc-b", accelerator_id="acc-1"),
            TaskNode("n3", "병렬 B", order_after=("n1",), parallel_group="g1",
                     service_id="svc-c", accelerator_id="acc-2"),
            TaskNode("n4", "합류", depends_on=("n2", "n3"), service_id="svc-a",
                     accelerator_id="acc-0"),
        ),
    )


# -- 구조 --------------------------------------------------------------------


def test_order_and_dependency_edges_stay_distinct():
    """실행 순서(실선)와 의존 관계(점선)를 섞지 않는다 (문서 §4.2)."""
    g = _graph()
    assert g.node("n2").order_after == ("n1",)
    assert g.node("n2").depends_on == ()
    assert g.node("n4").depends_on == ("n2", "n3")
    assert g.node("n4").order_after == ()
    # 선행 노드 조회는 둘을 합쳐 보되 중복은 한 번만 센다.
    merged = TaskNode("x", "t", order_after=("n1",), depends_on=("n1",))
    assert merged.predecessors == ("n1",)


def test_parallel_group_is_reported_as_a_group():
    assert _graph().parallel_groups() == {"g1": ("n2", "n3")}


def test_unknown_predecessor_is_rejected():
    with pytest.raises(GraphInvalid, match="unknown nodes"):
        TaskGraph("m", (TaskNode("a", "t", depends_on=("ghost",)),))


def test_cycle_is_rejected_with_the_path():
    with pytest.raises(GraphInvalid, match="cycle"):
        TaskGraph(
            "m",
            (
                TaskNode("a", "t", depends_on=("b",)),
                TaskNode("b", "t", depends_on=("a",)),
            ),
        )


def test_duplicate_node_ids_are_rejected():
    with pytest.raises(GraphInvalid, match="duplicate"):
        TaskGraph("m", (TaskNode("a", "t"), TaskNode("a", "t2")))


def test_self_dependency_is_rejected():
    with pytest.raises(GraphInvalid, match="itself"):
        TaskNode("a", "t", depends_on=("a",))


def test_graph_takes_any_shape_without_a_node_count_limit():
    """문서 §4.2 시나리오 일반성: 노드 수·깊이에 전제를 두지 않는다."""
    chain = tuple(
        TaskNode(f"n{i}", f"단계 {i}", order_after=() if i == 0 else (f"n{i-1}",))
        for i in range(200)
    )
    g = TaskGraph("deep", chain)
    assert g.state_counts().total == 200


# -- 상태 --------------------------------------------------------------------


def test_six_states_are_exactly_the_documented_set():
    assert {s.value for s in NodeState} == {
        "PENDING", "BLOCKED", "EXECUTING", "SUCCEEDED", "FAILED", "EXTERNAL_REQUESTED",
    }


def test_state_counts_are_derived_so_they_cannot_disagree_with_the_graph():
    """문서 §4.1: 집계는 그래프 상태의 집계이며 항상 일치해야 한다."""
    g = _graph()
    counts = g.state_counts()
    assert counts.total == 4
    assert counts.by_state["SUCCEEDED"] == 1
    assert counts.by_state["PENDING"] == 3
    g2 = g.transition("n2", NodeState.EXECUTING, at=20.0)
    assert g2.state_counts().by_state["EXECUTING"] == 1
    assert sum(g2.state_counts().by_state.values()) == g2.state_counts().total


def test_attention_count_covers_failed_and_external_request():
    g = _graph().transition("n2", NodeState.EXECUTING, at=1.0)
    g = g.transition("n2", NodeState.FAILED, at=2.0)
    assert g.state_counts().attention == 1
    g = g.transition("n2", NodeState.EXTERNAL_REQUESTED, at=3.0, external_request_id="req-1")
    assert g.state_counts().attention == 1
    assert g.node("n2").state.needs_attention


def test_disallowed_transition_is_rejected_not_silently_applied():
    g = _graph()
    with pytest.raises(TransitionRejected, match="not allowed"):
        g.transition("n2", NodeState.SUCCEEDED, at=1.0)  # PENDING -> SUCCEEDED 없음
    with pytest.raises(TransitionRejected):
        g.transition("n1", NodeState.EXECUTING, at=1.0)  # SUCCEEDED 는 종단


def test_same_state_transition_is_rejected():
    """관측 변화가 없는데 전이 시각을 갈아끼우지 않는다."""
    with pytest.raises(TransitionRejected):
        _graph().transition("n2", NodeState.PENDING, at=5.0)


def test_external_request_state_requires_a_request_identifier():
    """AI-C-19: 발급은 백엔드가 하고 우리는 받아 싣는다 — 그래서 비울 수 없다."""
    g = _graph().transition("n2", NodeState.EXECUTING, at=1.0)
    with pytest.raises(TransitionRejected, match="external_request_id"):
        g.transition("n2", NodeState.EXTERNAL_REQUESTED, at=2.0)
    ok = g.transition("n2", NodeState.EXTERNAL_REQUESTED, at=2.0, external_request_id="req-7")
    assert ok.node("n2").external_request_id == "req-7"


def test_ready_only_when_predecessors_succeeded():
    g = _graph()
    assert g.ready("n2") is True          # n1 완료
    assert g.ready("n4") is False         # n2·n3 미완
    g = g.transition("n2", NodeState.EXECUTING, at=1.0)
    g = g.transition("n2", NodeState.FAILED, at=2.0)
    assert g.ready("n4") is False         # 실패는 완료가 아니다


# -- 조회 전용 ---------------------------------------------------------------


def test_transition_returns_a_new_graph_and_leaves_the_snapshot_untouched():
    """문서 §1.1·§5 조회 전용: 화면이 든 스냅샷은 제자리에서 바뀌지 않는다."""
    g = _graph()
    g2 = g.transition("n2", NodeState.EXECUTING, at=9.0)
    assert g.node("n2").state is NodeState.PENDING
    assert g2.node("n2").state is NodeState.EXECUTING
    assert g is not g2


def test_nodes_are_frozen():
    with pytest.raises(Exception):
        _graph().node("n2").state = NodeState.EXECUTING  # type: ignore[misc]


# -- 기준 노드 ---------------------------------------------------------------


def test_auto_follow_picks_the_most_recent_executing_node():
    g = _graph()
    g = g.transition("n2", NodeState.EXECUTING, at=20.0)
    g = g.transition("n3", NodeState.EXECUTING, at=30.0)
    focus = g.focus()
    assert (focus.node_id, focus.pinned, focus.reason) == (
        "n3", False, FOCUS_REASON_LATEST_EXECUTING,
    )


def test_auto_follow_prefers_attention_over_a_newer_executing_node():
    """문서 §4.2: 실패·주의와 외부 요청은 다른 상태보다 우선 인지."""
    g = _graph()
    g = g.transition("n2", NodeState.EXECUTING, at=20.0)
    g = g.transition("n2", NodeState.FAILED, at=21.0)
    g = g.transition("n3", NodeState.EXECUTING, at=99.0)
    assert g.focus().reason == FOCUS_REASON_ATTENTION
    assert g.focus().node_id == "n2"


def test_parallel_tie_is_broken_deterministically_by_node_id():
    """동률이면 같은 입력에 항상 같은 노드 — 화면이 깜빡이지 않으려면 결정적이어야."""
    g = _graph()
    g = g.transition("n3", NodeState.EXECUTING, at=50.0)
    g = g.transition("n2", NodeState.EXECUTING, at=50.0)
    assert g.focus().node_id == "n2"
    assert g.focus().node_id == TaskGraph(g.mission_id, g.nodes).focus().node_id


def test_pin_overrides_auto_follow_and_unpin_returns_to_it():
    g = _graph().transition("n2", NodeState.EXECUTING, at=20.0)
    pinned = g.pin("n4")
    assert (pinned.focus().node_id, pinned.focus().pinned) == ("n4", True)
    assert pinned.focus().reason == FOCUS_REASON_PINNED
    released = pinned.pin(None)
    assert released.focus().node_id == "n2"
    assert released.focus().pinned is False


def test_pinning_an_unknown_node_is_rejected():
    with pytest.raises(GraphInvalid, match="pinned node"):
        _graph().pin("ghost")


def test_focus_reports_no_candidate_instead_of_guessing():
    g = _graph()
    assert g.focus().node_id is None
    assert g.focus().reason == FOCUS_REASON_NO_CANDIDATE


# -- 재실행 ------------------------------------------------------------------


def test_re_execution_creates_a_new_node_and_keeps_the_original():
    """문서 §4.2·§4.8: 원 실패 노드의 이력이 소실되어서는 안 된다."""
    g = _graph()
    g = g.transition("n2", NodeState.EXECUTING, at=10.0)
    g = g.transition("n2", NodeState.FAILED, at=11.0)
    g = g.add_re_execution("n2", node_id="n2-r2", at=12.0)

    original = g.node("n2")
    retry = g.node("n2-r2")
    assert original.state is NodeState.FAILED      # 원 노드 그대로
    assert original.attempt == 1
    assert retry.attempt == 2
    assert retry.origin_node_id == "n2"
    assert retry.is_re_execution and not original.is_re_execution
    assert retry.title == original.title           # 같은 논리 작업
    assert retry.depends_on == original.depends_on


def test_attempts_chain_lists_every_round_oldest_first():
    g = _graph()
    g = g.transition("n2", NodeState.EXECUTING, at=10.0)
    g = g.transition("n2", NodeState.FAILED, at=11.0)
    g = g.add_re_execution("n2", node_id="n2-r2", at=12.0)
    g = g.transition("n2-r2", NodeState.EXECUTING, at=13.0)
    g = g.transition("n2-r2", NodeState.FAILED, at=14.0)
    g = g.add_re_execution("n2-r2", node_id="n2-r3", at=15.0)

    chain = g.attempts_of("n2-r3")
    assert [n.node_id for n in chain] == ["n2", "n2-r2", "n2-r3"]
    assert [n.attempt for n in chain] == [1, 2, 3]
    # 어느 회차에서 물어도 같은 사슬이 나온다.
    assert g.attempts_of("n2") == chain


def test_re_execution_only_from_failed_or_external_request():
    g = _graph().transition("n2", NodeState.EXECUTING, at=1.0)
    with pytest.raises(TransitionRejected, match="FAILED or EXTERNAL_REQUESTED"):
        g.add_re_execution("n2", node_id="n2-r2")


def test_re_execution_after_external_deployment_carries_the_request_id():
    """문서 §4.9 5단계: 배포 적용 후 재실행된 노드가 요청과 이어져야 한다."""
    g = _graph()
    g = g.transition("n2", NodeState.EXECUTING, at=10.0)
    g = g.transition("n2", NodeState.FAILED, at=11.0)
    g = g.transition("n2", NodeState.EXTERNAL_REQUESTED, at=12.0, external_request_id="req-9")
    g = g.add_re_execution("n2", node_id="n2-r2", at=20.0)
    assert g.node("n2-r2").external_request_id == "req-9"


# -- 계층 분리 ---------------------------------------------------------------


def test_service_and_accelerator_are_separate_fields():
    """문서 §4.6: 하나의 '수행 위치' 항목으로 합쳐서는 안 된다."""
    node = _graph().node("n2")
    assert node.service_id == "svc-b"
    assert node.accelerator_id == "acc-1"


def test_off_device_node_marks_its_accelerator_as_outside():
    node = TaskNode("x", "외부 수행", accelerator_id=OFF_DEVICE, service_id=None)
    assert node.accelerator_id == OFF_DEVICE


def test_unassigned_service_and_accelerator_are_none_not_zero_or_empty():
    """모르면 없음으로 둔다 — 빈 문자열을 넣어 '배정됨'처럼 보이게 하지 않는다."""
    node = TaskNode("x", "미배정")
    assert node.service_id is None and node.accelerator_id is None
    assert node.progress_ratio is None


def test_progress_ratio_range_is_validated():
    with pytest.raises(GraphInvalid, match="progress_ratio"):
        TaskNode("x", "t", progress_ratio=1.5)


def test_module_contains_no_domain_or_vendor_name():
    """절대 준수 원칙 #1·#3: 핵심 코드에 도메인·벤더 이름을 두지 않는다.

    검사 대상은 **코드 토큰**(식별자·리터럴)이고 주석·docstring 은 제외한다 —
    docstring 은 "이런 이름을 쓰지 않는다"는 반례로 그 단어를 인용할 수 있어야
    한다. 분기나 값으로 새어 들어오는 것만 막는 것이 목적이다
    (`tests/test_overlay_and_clusters.py` 가 tailscale 에 쓰는 것과 같은 방식).
    """
    import io
    import tokenize
    from pathlib import Path

    import mission_runtime.execution.task_graph as mod

    banned = ("vla", "vlm", "mobilint", "deepx", "모빌린트", "딥엑스", "xdna",
              "하천", "unitree", "go1", "robot", "river")
    source = Path(mod.__file__).read_text(encoding="utf-8")
    leaked: list[tuple[str, int]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
            continue
        low = token.string.lower()
        leaked += [(name, token.start[0]) for name in banned if name in low]
    assert not leaked, f"domain/vendor name leaked into code: {leaked}"
