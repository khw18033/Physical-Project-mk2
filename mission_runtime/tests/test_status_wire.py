"""implements: AI-O-06, AI-O-05, AI-B-12, AI-B-13, AI-L-10, AI-C-01, AI-C-06
covers: 통합 상태 스냅샷 한 장이 와이어로 나갈 때 **기능정의서가 금지한 모양으로
        나가지 않는다**는 것. 자료구조가 옳아도 직렬화에서 0 과 미측정이 섞이거나
        집계를 함께 실어 구역끼리 어긋나면 화면은 요구를 지킬 수 없다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard_example import EXAMPLE_PATH, T0, example_message, example_snapshot
from mission_runtime.execution.task_graph import NodeState, TaskGraph, TaskNode
from mission_runtime.integration.status_wire import (
    OFF_DEVICE,
    STATUS_SNAPSHOT_CHANNEL,
    status_snapshot_payload,
)
from mission_runtime.integration.wire import AI_CHANNELS, MessageContext
from mission_runtime.observability.dashboard_view import (
    DashboardSnapshot,
    MissionSummary,
    Region,
    SourceState,
)


def _context() -> MessageContext:
    return MessageContext(source_id="orchestrator", node_id="ai-sbc-01",
                          zone_id="zoneA", sequence_id=1, timestamp=T0)


def _payload() -> dict:
    return status_snapshot_payload(example_snapshot(), now=T0 + 60.0)


def _walk(node, path=""):
    """(경로, 값) 전부. 중첩된 곳의 위반을 눈으로 찾지 않기 위한 도우미."""
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


# -- 1. 채널 하나 -------------------------------------------------------

def test_the_whole_view_is_one_channel():
    """구역마다 채널을 쪼개지 않는다(§3 "하나의 통합 상태 뷰를 구독")."""
    assert STATUS_SNAPSHOT_CHANNEL in AI_CHANNELS
    assert STATUS_SNAPSHOT_CHANNEL == "status_snapshot"


def test_every_region_has_a_place_in_one_payload():
    """B~I 아홉 구역이 한 본문에서 다 나온다 — 구역별 조회가 필요 없어야 한다."""
    payload = _payload()
    assert {state["region_id"] for state in payload["regions"]} == {
        region.value for region in Region
    }


# -- 2. 세면 나오는 값은 싣지 않는다 (R9 · §4.1 · §5) -------------------

@pytest.mark.parametrize("forbidden", [
    "state_counts", "node_states", "node_load", "elapsed_s", "elapsed_sec",
    "completion_tally", "failure_tally", "resource_tally", "total_nodes",
    "series_range",
])
def test_derived_values_are_not_on_the_wire(forbidden):
    """집계를 함께 실으면 반드시 어긋나는 날이 온다 — 한쪽만 갱신된 스냅샷이 나갈 때다.

    기능정의서 §4.1 은 상태별 노드 수가 "그래프의 노드 상태를 집계한 값이며 그래프와
    **항상 일치**해야 한다"고 요구한다. 보내지 않고 화면이 세면 어긋날 자리가 없다.
    """
    keys = {path.rsplit("/", 1)[-1] for path, _ in _walk(_payload())}
    assert forbidden not in keys


def test_the_screen_can_count_the_states_itself():
    """싣지 않는 대신 셀 수 있어야 한다 — 노드마다 상태가 있다."""
    payload = _payload()
    counted = {}
    for node in payload["task_nodes"]:
        counted[node["task_node_state"]] = counted.get(node["task_node_state"], 0) + 1
    counts = example_snapshot().graph.state_counts()
    assert counted == {state: n for state, n in counts.by_state.items() if n}
    assert sum(counted.values()) == counts.total


# -- 3. 측정 없음과 0 (§4.4 · §4.5) ------------------------------------

def test_an_unmeasured_indicator_has_no_value_key_at_all():
    """0 이 아니라 **칸이 없다**. 0 을 넣으면 화면이 "미달"로 그린다."""
    payload = _payload()
    indicators = [i for service in payload["services"] for i in service.get("indicators", ())]
    unmeasured = [i for i in indicators if i["target_meet_state"] == "NOT_MEASURED"]
    assert unmeasured, "미측정 지표가 있는 예제여야 이 시험이 의미가 있다"
    for indicator in unmeasured:
        assert "value" not in indicator["measurement"]
        assert indicator["measurement"]["unit"]


def test_no_null_is_ever_written():
    """규약 R8 — 모르는 값은 null 이 아니라 칸을 뺀다. 중첩 어디에도 없다."""
    nulls = [path for path, value in _walk(_payload()) if value is None]
    assert nulls == []


def test_a_zero_measurement_keeps_its_value():
    """반대 방향도 고정한다 — "쟀더니 0"은 값이 0 으로 실린다."""
    payload = _payload()
    idle = next(a for a in payload["accelerators"] if a["accelerator_instance_id"] == "ext-npu-3")
    assert idle["utilization"]["value"] == 0.0


# -- 4. 가속기 목록의 완전성 (§4.1 · §4.4) ------------------------------

def test_an_idle_accelerator_is_not_omitted():
    """배치된 서비스가 없는 가속기를 생략하면 자원 여유를 판단할 수 없다."""
    payload = _payload()
    ids = {a["accelerator_instance_id"] for a in payload["accelerators"]}
    placed = {s.get("accelerator_instance_id") for s in payload["services"]}
    assert "ext-npu-3" in ids and "ext-npu-3" not in placed


def test_service_and_accelerator_stay_in_separate_fields():
    """§4.6: "하나의 수행 위치 항목으로 합쳐서는 안 된다"."""
    payload = _payload()
    node = next(n for n in payload["task_nodes"] if n["task_node_id"] == "T-A3")
    assert node["service_id"] == "vlm"
    assert node["accelerator_instance_id"] == "ext-npu-2"
    assert not any("location" in key for key in node)


def test_a_node_that_does_not_run_on_device_says_so():
    """§4.6 — 온디바이스 외부임을 명시한다. 빈 값으로 두면 "모른다"와 섞인다."""
    payload = _payload()
    node = next(n for n in payload["task_nodes"] if n["task_node_id"] == "T-C1")
    assert node["accelerator_instance_id"] == OFF_DEVICE


# -- 5. 재실행 (§4.2 · §4.8) -------------------------------------------

def test_a_re_execution_does_not_overwrite_the_original():
    """두 회차가 함께 실린다. 원 실패 노드의 이력이 소실되어서는 안 된다."""
    payload = _payload()
    by_id = {n["task_node_id"]: n for n in payload["task_nodes"]}
    assert by_id["T-A2"]["task_attempt"] == 1
    assert by_id["T-A2#2"]["task_attempt"] == 2
    assert by_id["T-A2#2"]["origin_task_node_id"] == "T-A2"


def test_events_keep_the_attempt_so_logs_do_not_merge():
    """§4.8 — 재실행이 이전 회차의 로그를 덮어써서는 안 된다."""
    payload = _payload()
    attempts = {e.get("task_attempt") for e in payload["events"] if e.get("task_node_id")}
    assert attempts == {1, 2, 3}
    # 같은 논리 작업의 회차별 사건이 서로 다른 노드 id 로 남는다 — 화면이 한 노드를
    # 골랐을 때 회차 전체를 모을 수 있고, 뒤 회차가 앞 회차를 덮지도 않는다.
    by_node = {e["task_node_id"]: e["task_attempt"]
               for e in payload["events"] if e.get("task_node_id")}
    assert by_node["T-A2#2"] == 2 and by_node["T-A2#3"] == 3


# -- 6. 외부 기능 요청 (§4.9) ------------------------------------------

def test_the_server_interior_is_not_on_the_wire():
    """3단계는 "진행 중 여부만" 표시 대상이다. 담당·빌드·진척 칸을 만들지 않는다."""
    payload = _payload()
    request = payload["external_requests"][0]
    assert request["external_request_stage"] == "SERVER_WORKING"
    assert request["server_work_is_opaque"] is True
    keys = {path.rsplit("/", 1)[-1] for path, _ in _walk(request)}
    assert not keys & {"assignee", "build_status", "progress_percent", "developer",
                       "server_log", "ticket_status"}


def test_a_missing_deployment_is_a_flag_not_a_null_version():
    payload = _payload()
    request = payload["external_requests"][0]
    assert request["deployment_received"] is False
    assert "deployment_version" not in request


def test_the_stage_times_include_the_judgement_moment():
    """1단계의 **판정 시각**도 §4.9 의 표시 항목이다."""
    payload = _payload()
    stages = [t["external_request_stage"] for t in payload["external_requests"][0]["stage_times"]]
    assert stages == ["JUDGED", "SENT", "SERVER_WORKING"]


def test_the_escalation_is_linked_from_the_verdict():
    """§4.7 — 판정 결과와 후속 조치가 끊기지 않고 연결되어야 한다."""
    payload = _payload()
    verdict = next(v for v in payload["verdicts"] if v["task_node_id"] == "T-C1")
    request_ids = {r["external_request_id"] for r in payload["external_requests"]}
    assert verdict["escalated_request_id"] in request_ids


def test_a_mission_with_no_request_still_has_the_region():
    """§4.9 — 요청이 없어도 구역이 사라지지 않는다. 빈 배열이 정상 메시지다."""
    snapshot = DashboardSnapshot(
        mission=MissionSummary(mission_id="M-1"),
        graph=TaskGraph(mission_id="M-1", nodes=(TaskNode("n1", "t"),)),
    )
    payload = status_snapshot_payload(snapshot)
    assert payload["external_requests"] == []
    assert payload["model_assignments"] == []


# -- 7. 판정 근거 (§4.7) -----------------------------------------------

def test_conditions_arrive_as_individual_items_on_three_axes():
    payload = _payload()
    verdict = next(v for v in payload["verdicts"] if v["task_node_id"] == "T-A3")
    assert [i["condition_item_id"] for i in verdict["completion"]] == [
        "all_eight_angles_observed", "target_found_in_any_angle"]
    assert verdict["failure"] and verdict["resource"]


def test_an_unjudged_condition_has_no_satisfied_key():
    """판정할 근거가 없는 조건을 거짓으로 적지 않는다 — 미확인과 불충족은 다르다."""
    payload = _payload()
    verdict = next(v for v in payload["verdicts"] if v["task_node_id"] == "T-A3")
    unknown = next(i for i in verdict["resource"] if i["condition_item_id"] == "board_power_headroom")
    assert "condition_satisfied" not in unknown
    assert unknown["condition_reason"] == "not_measured"


# -- 8. 소스 결손 격리 (§3 요구사항 5 · §5) -----------------------------

def test_a_source_never_received_has_no_timestamp_and_is_not_stale():
    payload = _payload()
    source = next(s for s in payload["sources"] if s["source_id"] == "knowledge_memory")
    assert "last_received_at" not in source
    assert source["source_stale"] is False


def test_one_silent_source_blanks_only_its_own_region():
    """나머지 구역은 정상 표시되어야 한다 — 결손은 축소이지 전체 실패가 아니다."""
    snapshot = DashboardSnapshot(
        mission=MissionSummary(mission_id="M-1"),
        graph=TaskGraph(mission_id="M-1", nodes=(TaskNode("n1", "t"),)),
        sources=(
            SourceState("knowledge_memory", "L3", None, (Region.VERDICT,)),
            SourceState("orchestrator", "L3", T0, (Region.TASK_GRAPH, Region.EVENTS)),
        ),
    )
    payload = status_snapshot_payload(snapshot, now=T0 + 1.0)
    by_region = {r["region_id"]: r for r in payload["regions"]}
    assert by_region["G"]["region_available"] is False
    assert by_region["G"]["region_reason"] == "source_not_received"
    assert by_region["G"]["missing_sources"] == ["knowledge_memory"]
    assert by_region["C"]["region_available"] is True


# -- 9. 모델 배정 (AI-L-10) --------------------------------------------

def test_an_assignment_carries_the_reason_not_only_the_model_name():
    message = example_message()
    assigned = next(a for a in message["model_assignments"] if "model" in a)
    assert assigned["model"] == "clip-gate"
    assert assigned["model_version"] == "2026.10.3"
    assert assigned["assignment_reason"] == "assigned"
    assert assigned["rejected"][0]["assignment_reason"] == "outside_verified_hardware_scope"


def test_no_candidate_is_a_normal_state_not_an_empty_model_name():
    message = example_message()
    none = next(a for a in message["model_assignments"] if a["capability_kind"] == "weight_estimation")
    assert "model" not in none
    assert none["assignment_reason"] == "no_candidate_for_conditions"


def test_the_running_model_version_is_visible_per_service():
    """교체가 일어났는지 화면이 알 수 있어야 한다(§4.4 "모델명·버전")."""
    message = example_message()
    vlm = next(s for s in message["services"] if s["service_id"] == "vlm")
    assert (vlm["model"], vlm["model_version"]) == ("clip-gate", "2026.10.3")


# -- 10. 봉투와 조회 전용 ----------------------------------------------

def test_the_envelope_is_the_same_flat_header_as_other_channels():
    message = example_message()
    assert message["schema_version"] == "2.0"
    assert message["channel"] == STATUS_SNAPSHOT_CHANNEL
    assert message["timestamp"].endswith("+09:00")
    assert "payload" not in message


def test_every_instant_is_the_agreed_format():
    offenders = [
        path for path, value in _walk(example_message())
        if isinstance(value, str) and path.rsplit("/", 1)[-1].endswith("_at")
        and not value.endswith("+09:00")
    ]
    assert offenders == []


def test_this_module_offers_no_way_to_change_state():
    """§1.1 조회 전용 · AI-C-19 — 상태 뷰 경로로 실행을 바꿀 수단을 주지 않는다."""
    from mission_runtime.integration import status_wire

    # 모듈이 다시 내보내는 타입 이름(Mapping 등)이 아니라 **함수**만 본다.
    functions = [
        name for name in dir(status_wire)
        if not name.startswith("_") and name.islower() and callable(getattr(status_wire, name))
    ]
    assert not [
        name for name in functions
        if any(verb in name for verb in ("start", "stop", "cancel", "deploy", "apply",
                                         "set_", "update", "pin", "transition"))
    ]
    # 사상 함수만 있어야 한다는 것을 양성으로도 고정한다.
    assert "status_snapshot_payload" in functions


# -- 11. 예제가 생산 코드에서 멀어지지 않게 ----------------------------

def test_the_committed_example_is_what_the_producer_builds_today():
    """손으로 고친 예제는 계약을 거짓으로 증명한다.

    다시 쓰려면: ./.venv/bin/python tests/dashboard_example.py --write
    """
    committed = json.loads(Path(EXAMPLE_PATH).read_text(encoding="utf-8"))
    assert committed == example_message()


# -- 12. 이름은 공통 사전에 등재한 것만 (AI-C-01) ----------------------

def test_every_name_on_the_wire_is_in_the_shared_dictionary():
    """AI-C-01 — 편의상 새 이름을 와이어에 올리지 않는다.

    중첩 구조는 스키마가 소유하므로 **파트 경계를 넘는 의미 단위**를 본다.
    등재하지 않은 이름이 나오면 사전에 뜻·생산자·소비자·데이터 평면을 먼저 적는다.
    """
    from mission_runtime.contracts import data_dictionary as dd

    message = example_message()
    # 제외하는 이름 = **구조**이지 의미 단위가 아닌 것들. `measurement` 안의
    # value/unit/direction 처럼 바깥 이름이 뜻을 이미 정한 자리, 그리고 3축·목록의
    # 묶음 이름이다. 이 구조는 status-snapshot.schema.json 이 소유한다.
    STRUCTURAL = {
        "value", "unit", "direction", "target", "trend", "indicators", "feeds",
        "completion", "failure", "resource", "rejected", "stage_times",
        "missing_sources", "order_after", "depends_on", "re_executed_task_node_ids",
        "re_request_of", "from_task_node_id", "to_task_node_id",
        "external_request_reason_detail",
    }
    message = example_message()
    undocumented = sorted({
        path.rsplit("/", 1)[-1]
        for path, value in _walk(message)
        if path and "[" not in path.rsplit("/", 1)[-1]
        and path.rsplit("/", 1)[-1] not in dd.DATA_DICTIONARY
    } - STRUCTURAL)
    assert undocumented == []
