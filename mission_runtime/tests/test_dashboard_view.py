"""implements: AI-O-06, AI-B-12
tests: single integrated snapshot, derived counts never disagree, per-source
       not-received isolation, node-filtered logs across attempts, severity vs
       kind split, read-only surface
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mission_runtime.execution.external_request import (
    ExternalRequest,
    ExternalRequestLog,
    RequestReason,
)
from mission_runtime.execution.task_graph import NodeState, TaskGraph, TaskNode
from mission_runtime.observability.dashboard_view import (
    REASON_NO_DATA,
    REASON_SOURCE_NOT_RECEIVED,
    ConditionItem,
    DashboardSnapshot,
    EventKind,
    EventRecord,
    MissionSummary,
    NodeVerdict,
    Region,
    Severity,
    SourceState,
    severity_from_wire,
)
from mission_runtime.observability.layered_metrics import (
    AcceleratorInstance,
    BoardResources,
    Direction,
    Indicator,
    LayeredResourceView,
    Measurement,
    ServiceRuntime,
    TargetBaseline,
)

MISSION = "m-1"


def _graph() -> TaskGraph:
    return TaskGraph(
        MISSION,
        (
            TaskNode("n1", "첫 단계", state=NodeState.SUCCEEDED, service_id="svc-a",
                     accelerator_id="acc-cpu", state_changed_at=10.0),
            TaskNode("n2", "본 작업", state=NodeState.EXECUTING, service_id="svc-b",
                     accelerator_id="acc-npu-1", state_changed_at=20.0,
                     started_at=15.0, progress_ratio=0.4,
                     input_command="대상을 확인하고 접근한다", order_after=("n1",)),
            TaskNode("n3", "후속", depends_on=("n2",), service_id="svc-b",
                     accelerator_id="acc-npu-1"),
        ),
    )


def _resources() -> LayeredResourceView:
    return LayeredResourceView(
        accelerators=(
            AcceleratorInstance("acc-cpu", "cpu", utilization=Measurement(0.3, "ratio")),
            AcceleratorInstance("acc-npu-1", "npu", utilization=Measurement(0.9, "ratio")),
            AcceleratorInstance("acc-npu-2", "npu"),
        ),
        services=(
            ServiceRuntime("svc-a", "acc-cpu"),
            ServiceRuntime(
                "svc-b", "acc-npu-1",
                indicators=(
                    Indicator("latency", Measurement(180.0, "ms"),
                              service_id="svc-b", accelerator_id="acc-npu-1",
                              target=TargetBaseline(120.0, Direction.AT_MOST, "ms")),
                    Indicator("throughput", Measurement.not_measured("hz"),
                              service_id="svc-b", accelerator_id="acc-npu-1",
                              target=TargetBaseline(10.0, Direction.AT_LEAST, "hz")),
                ),
            ),
        ),
    )


def _sources(*, l2_received: bool = True) -> tuple[SourceState, ...]:
    return (
        SourceState("board", "L1", last_received_at=100.0,
                    feeds=(Region.MISSION_SUMMARY, Region.RESOURCES, Region.VERDICT)),
        SourceState("svc-b", "L2", last_received_at=100.0 if l2_received else None,
                    feeds=(Region.RESOURCES, Region.INDICATORS, Region.NODE_DETAIL)),
        SourceState("orchestrator", "L3", last_received_at=100.0,
                    feeds=(Region.MISSION_SUMMARY, Region.TASK_GRAPH, Region.EVENTS,
                           Region.NODE_DETAIL, Region.VERDICT, Region.NODE_EVENTS,
                           Region.EXTERNAL_REQUESTS)),
    )


def _snapshot(**kw) -> DashboardSnapshot:
    base = dict(
        mission=MissionSummary(MISSION, utterance="현장을 점검해라", status="RUNNING",
                               accepted_at=0.0),
        graph=_graph(),
        resources=_resources(),
        events=(
            EventRecord(11.0, Severity.INFO, EventKind.EXECUTION, "n1 완료", node_id="n1",
                        attempt=1),
            EventRecord(21.0, Severity.WARN, EventKind.RESOURCE, "지연 임계 초과",
                        node_id="n2", attempt=1),
            EventRecord(22.0, Severity.INFO, EventKind.EXTERNAL_REQUEST, "요청 전송",
                        node_id="n2", attempt=1, external_request_id="req-1"),
        ),
        verdicts=(
            NodeVerdict(
                "n2",
                completion=(ConditionItem("도착", True), ConditionItem("확인", None)),
                failure=(ConditionItem("충돌", False),),
                resource=(ConditionItem("가속기 온도", True),
                          ConditionItem("메모리", False, reason_token="over_budget")),
            ),
        ),
        sources=_sources(),
    )
    base.update(kw)
    return DashboardSnapshot(**base)


# -- 통합 스냅샷 -------------------------------------------------------------


def test_one_snapshot_carries_every_region():
    """문서 §3: 소스별 개별 조회가 아니라 통합된 상태 뷰를 구독한다."""
    snap = _snapshot()
    assert snap.mission.mission_id == MISSION
    assert snap.graph.nodes
    assert snap.resources.accelerators
    assert snap.events
    assert snap.verdicts
    assert len(list(Region)) == 9      # A 는 문서가 범위 외로 둔다


def test_graph_belonging_to_another_mission_is_rejected():
    with pytest.raises(ValueError, match="task graph belongs to another mission"):
        _snapshot(graph=TaskGraph("other", (TaskNode("x", "t"),)))


def test_external_log_of_another_mission_is_rejected():
    with pytest.raises(ValueError, match="belongs to another mission"):
        _snapshot(external_requests=ExternalRequestLog("other"))


# -- 상태 일관성 (문서 §5) ---------------------------------------------------


def test_counts_are_derived_from_the_graph_so_b_and_c_cannot_disagree():
    snap = _snapshot()
    counts = snap.state_counts()
    assert counts.total == len(snap.graph.nodes)
    assert counts.by_state["EXECUTING"] == 1
    assert counts.by_state["SUCCEEDED"] == 1
    moved = _snapshot(graph=_graph().transition("n2", NodeState.FAILED, at=30.0))
    assert moved.state_counts().by_state["FAILED"] == 1
    assert moved.state_counts().attention == 1


def test_node_load_is_keyed_by_accelerator_and_keeps_unassigned_ones():
    """문서 §4.1 "노드 부하": 가속기 기준 축이라 유휴도 남는다."""
    assert _snapshot().node_load() == {
        "acc-cpu": (0, 1),       # n1 완료 → 실행 중 0
        "acc-npu-1": (1, 2),     # n2 실행 중, n2+n3 배정
        "acc-npu-2": (0, 0),     # 미할당이지만 목록에 남는다
    }


def test_placement_keeps_idle_accelerators():
    assert _snapshot().placement()["acc-npu-2"] == ()


# -- 기준 노드 축 ------------------------------------------------------------


def test_focus_drives_the_right_hand_panels():
    snap = _snapshot()
    assert snap.focus().node_id == "n2"
    assert snap.focused_verdict().node_id == "n2"


def test_pin_changes_what_is_shown_without_touching_execution():
    snap = _snapshot()
    pinned = snap.pin("n3")
    assert pinned.focus().node_id == "n3"
    assert pinned.focused_verdict() is None      # n3 판정은 아직 없다
    assert snap.focus().node_id == "n2"          # 원 스냅샷 불변
    # 그래프의 실행 상태는 그대로다 — 고정은 관찰 방식의 변경이다.
    assert pinned.graph.node("n2").state is NodeState.EXECUTING


def test_focused_verdict_is_none_when_no_node_is_in_focus():
    idle = _snapshot(graph=TaskGraph(MISSION, (TaskNode("n1", "대기"),)))
    assert idle.focus().node_id is None
    assert idle.focused_verdict() is None


# -- [G] 판정 ---------------------------------------------------------------


def test_three_condition_axes_stay_separate():
    v = _snapshot().verdicts[0]
    assert [c.item_id for c in v.completion] == ["도착", "확인"]
    assert [c.item_id for c in v.failure] == ["충돌"]
    assert [c.item_id for c in v.resource] == ["가속기 온도", "메모리"]


def test_tally_is_derived_from_items_and_unknown_is_not_counted_as_satisfied():
    """문서 §4.7: 요약 수치만 제공해서는 안 된다 — 집계는 항목에서 파생된다."""
    v = _snapshot().verdicts[0]
    assert v.completion_tally == (1, 2)     # True 1건, 미확인 1건
    assert v.failure_tally == (0, 1)
    assert v.resource_tally == (1, 2)


def test_escalation_links_the_verdict_to_the_request_identifier():
    v = NodeVerdict("n2", escalated_request_id="req-1")
    assert v.escalated is True
    assert NodeVerdict("n2").escalated is False


# -- [D]/[H] 사건 -----------------------------------------------------------


def test_severity_and_kind_are_separate_axes():
    """문서 §4.3 "등급·유형": SDI 는 등급이 아니라 유형이다."""
    assert {s.value for s in Severity} == {"INFO", "WARN", "ERROR"}
    assert "EXTERNAL_REQUEST" in {k.value for k in EventKind}
    sdi = _snapshot().external_request_events()
    assert [e.message for e in sdi] == ["요청 전송"]
    assert sdi[0].severity is Severity.INFO      # SDI 사건에도 등급이 따로 있다


def test_wire_severity_maps_without_merging_the_two_vocabularies():
    assert severity_from_wire("info") is Severity.INFO
    assert severity_from_wire("warning") is Severity.WARN
    assert severity_from_wire("critical") is Severity.ERROR
    with pytest.raises(ValueError, match="unknown wire severity"):
        severity_from_wire("fatal")


def test_recent_events_are_newest_first_and_windowed():
    snap = _snapshot().with_event_window(2)
    recent = snap.recent_events()
    assert [e.at for e in recent] == [22.0, 21.0]


def test_event_window_must_be_positive():
    with pytest.raises(ValueError, match="event_window"):
        _snapshot().with_event_window(0)


def test_node_events_include_every_attempt_of_the_same_logical_task():
    """문서 §4.8: 재실행된 노드는 회차별 이력이 모두 조회 가능해야 한다."""
    graph = _graph().transition("n2", NodeState.FAILED, at=30.0)
    graph = graph.add_re_execution("n2", node_id="n2-r2", at=31.0)
    snap = _snapshot(
        graph=graph,
        events=(
            EventRecord(21.0, Severity.WARN, EventKind.EXECUTION, "1회차 실패",
                        node_id="n2", attempt=1),
            EventRecord(32.0, Severity.INFO, EventKind.EXECUTION, "2회차 시작",
                        node_id="n2-r2", attempt=2),
            EventRecord(33.0, Severity.INFO, EventKind.EXECUTION, "무관한 노드",
                        node_id="n1", attempt=1),
        ),
    )
    both = snap.events_for("n2-r2")
    assert [e.message for e in both] == ["1회차 실패", "2회차 시작"]
    assert [e.attempt for e in both] == [1, 2]
    only_this = snap.events_for("n2-r2", include_attempts=False)
    assert [e.message for e in only_this] == ["2회차 시작"]


def test_node_events_of_an_unknown_node_do_not_raise():
    assert _snapshot().events_for("ghost") == ()


# -- [E]/[E′] ---------------------------------------------------------------


def test_alerts_exclude_not_measured_indicators():
    snap = _snapshot()
    assert [i.name for i in snap.resource_alerts()] == ["latency"]
    assert len(snap.indicators()) == 2


# -- [I] --------------------------------------------------------------------


def test_region_i_is_present_even_with_no_requests():
    """문서 §4.9: 요청이 없어도 구역은 사라지지 않는다."""
    snap = _snapshot(external_requests=ExternalRequestLog(MISSION))
    assert snap.has_external_requests() is False
    assert snap.region_state(Region.EXTERNAL_REQUESTS).available is True


def test_region_i_reports_requests_when_present():
    log = ExternalRequestLog(MISSION, (
        ExternalRequest("req-1", RequestReason.UNSUPPORTED_CAPABILITY, "기능 없음", "n2"),
    ))
    assert _snapshot(external_requests=log).has_external_requests() is True


# -- §3·§5 소스별 미수신 격리 ------------------------------------------------


def test_a_silent_source_disables_only_the_regions_it_feeds():
    """문서 §3 요구 5 / AI-C-05: 나머지 구역은 정상 표시되어야 한다."""
    snap = _snapshot(sources=_sources(l2_received=False))
    indicators = snap.region_state(Region.INDICATORS)
    assert indicators.available is False
    assert indicators.reason_token == REASON_SOURCE_NOT_RECEIVED
    assert indicators.missing_sources == ("svc-b",)
    # 같은 소스를 쓰더라도 다른 소스가 함께 먹이는 구역은 살아 있다.
    assert snap.region_state(Region.RESOURCES).available is True
    assert snap.region_state(Region.NODE_DETAIL).available is True
    assert snap.region_state(Region.TASK_GRAPH).available is True
    assert snap.unavailable_regions() == (Region.INDICATORS,)


def test_last_received_time_is_absent_rather_than_invented():
    source = SourceState("svc-b", "L2", feeds=(Region.INDICATORS,))
    assert source.received is False
    assert source.last_received_at is None
    assert source.is_stale(now=1000.0, ttl_s=5.0) is False   # 미수신은 stale 이 아니다


def test_stale_source_is_distinguished_from_never_received():
    source = SourceState("svc-b", "L2", last_received_at=100.0, feeds=(Region.INDICATORS,))
    assert source.received is True
    assert source.is_stale(now=104.0, ttl_s=5.0) is False
    assert source.is_stale(now=120.0, ttl_s=5.0) is True


def test_empty_graph_marks_region_c_without_data_not_as_a_source_failure():
    snap = _snapshot(graph=TaskGraph(MISSION, ()))
    state = snap.region_state(Region.TASK_GRAPH)
    assert state.available is False
    assert state.reason_token == REASON_NO_DATA


def test_missing_verdicts_mark_region_g_without_data():
    snap = _snapshot(verdicts=())
    assert snap.region_state(Region.VERDICT).reason_token == REASON_NO_DATA


def test_unknown_source_lookup_raises():
    with pytest.raises(KeyError):
        _snapshot().source("ghost")


# -- 조회 전용 ---------------------------------------------------------------


def test_snapshot_exposes_no_control_surface():
    """문서 §1.1·§5: 화면의 어떠한 조작도 실행 상태를 바꾸지 않아야 한다."""
    names = [n for n in dir(DashboardSnapshot) if not n.startswith("_")]
    for banned in ("start", "stop", "restart", "deploy", "cancel", "abort", "apply",
                   "send", "issue", "execute", "rollback", "command"):
        assert not any(banned in n for n in names), f"control surface leaked: {banned}"
    # 남은 공개 메서드는 조회·필터·표시대상 선택뿐이다.
    assert "pin" in names and "with_event_window" in names


def test_mission_elapsed_is_none_when_the_accept_time_is_unknown():
    snap = _snapshot(mission=MissionSummary(MISSION))
    assert snap.mission.elapsed_s(now=500.0) is None
    assert _snapshot().mission.elapsed_s(now=500.0) == 500.0


def test_mission_keeps_the_original_utterance():
    """문서 §4.1: 미션명은 사용자 입력 자연어 명령 원문이다."""
    assert _snapshot().mission.utterance == "현장을 점검해라"


def test_module_carries_no_transport_or_vendor_name_in_code():
    import io
    import tokenize
    from pathlib import Path

    import mission_runtime.observability.dashboard_view as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    banned = ("mqtt", "kafka", "websocket", "sse", "publish", "subscribe_to",
              "vla", "vlm", "xdna", "mobilint", "deepx")
    leaked: list[tuple[str, int]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE):
            continue
        low = token.string.lower()
        for name in banned:
            # 3글자 약어는 부분 일치로 보면 오탐한다 — `dataclasses` 안에 "sse" 가
            # 들어 있다. 짧은 이름은 토큰 전체가 같을 때만 잡는다.
            hit = (low == name) if len(name) < 4 else (name in low)
            if hit:
                leaked.append((name, token.start[0]))
    assert not leaked, f"leaked into code: {leaked}"


# -- 공통 데이터 사전과의 정합 (AI-C-01) -------------------------------------


def test_vocabularies_match_the_common_data_dictionary():
    """어휘를 두 벌로 두면 한쪽만 바뀐다 — 테스트가 그 드리프트를 막는다."""
    from mission_runtime.contracts import data_dictionary as dd
    from mission_runtime.execution.external_request import (
        FinalVerdict,
        RequestReason,
        RequestStage,
    )
    from mission_runtime.execution.task_graph import FOCUS_REASONS as GRAPH_FOCUS_REASONS
    from mission_runtime.observability.dashboard_view import REGION_REASONS
    from mission_runtime.observability.layered_metrics import MeetState

    assert tuple(s.value for s in NodeState) == dd.TASK_NODE_STATES
    assert tuple(s.value for s in RequestStage) == dd.EXTERNAL_REQUEST_STAGES
    assert tuple(r.value for r in RequestReason) == dd.EXTERNAL_REQUEST_REASONS
    assert tuple(v.value for v in FinalVerdict) == dd.EXTERNAL_REQUEST_VERDICTS
    assert tuple(m.value for m in MeetState) == dd.TARGET_MEET_STATES
    assert GRAPH_FOCUS_REASONS == dd.FOCUS_REASONS
    assert REGION_REASONS == dd.REGION_REASONS


def test_task_node_identifier_is_registered_apart_from_the_physical_node_id():
    """같은 이름에 두 뜻을 담지 않는다 — 작업 노드와 물리 노드는 다른 칸이다."""
    from mission_runtime.contracts import data_dictionary as dd

    assert dd.DATA_DICTIONARY["task_node_id"].meaning != dd.DATA_DICTIONARY["node_id"].meaning
    assert "물리" in dd.DATA_DICTIONARY["node_id"].meaning


def test_an_empty_resource_layer_is_no_data_not_available():
    """[E]·[E′] 도 [C]·[G] 와 같은 규칙을 받는다 (문서 §3 요구사항 5).

    자원 계층에 사실이 하나도 없는데 구역을 "표시 가능"으로 적으면 화면은 빈 칸을
    그리면서 **왜 비었는지 말할 근거를 잃는다** — 가속기 선언이 없는 배치와 계측이
    끊긴 배치가 같아 보인다. 구역을 지우지 않는 것과 비었다는 사실을 적는 것은
    함께 가야 한다(AI-C-05).
    """
    bare = DashboardSnapshot(
        mission=MissionSummary(MISSION),
        graph=TaskGraph(mission_id=MISSION, nodes=()),
    )
    resources = bare.region_state(Region.RESOURCES)
    assert resources.available is False
    assert resources.reason_token == REASON_NO_DATA
    indicators = bare.region_state(Region.INDICATORS)
    assert indicators.available is False
    assert indicators.reason_token == REASON_NO_DATA
    # 구역은 사라지지 않는다 — 아홉 개가 그대로 있고 사유만 붙는다.
    assert len(bare.region_states()) == len(tuple(Region))

    # 보드 값 하나만 있어도 [E] 는 비지 않는다 — 보드 메모리·전력은 [E] 가 요구하는
    # L1 계측이다(§4.4). 값이 없는 칸은 "받았다"로 세지 않는다.
    with_board = replace(bare, resources=LayeredResourceView(
        board=BoardResources(memory_utilization=Measurement(0.42, "ratio", 10.0))))
    assert with_board.region_state(Region.RESOURCES).available is True
    assert with_board.resources.is_empty is False
    unit_only = replace(bare, resources=LayeredResourceView(
        board=BoardResources(memory_utilization=Measurement(None, "ratio"))))
    assert unit_only.resources.is_empty is True
