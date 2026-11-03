"""implements: AI-O-06, AI-L-03, AI-C-13
covers: the one loop the operations screen exists for — several devices report,
        the picture fuses, a developer traces it, an operator corrects it, and
        the correction becomes a human-confirmed learning candidate on disk
"""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONSOLE_DIR = PROJECT_DIR / "tools" / "fms_console"
for candidate in (CONSOLE_DIR, PROJECT_DIR / "tools" / "status_ui"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from accounts import Caller  # noqa: E402


def _console():
    """`tools/fms_console/serve.py` 를 경로로 싣는다.

    `tools/status_ui/serve.py` 와 모듈 이름이 겹쳐서 `import serve` 는 먼저 올라온
    쪽을 집는다 — 이름이 아니라 경로로 실어 그 모호함을 없앤다.
    """
    spec = importlib.util.spec_from_file_location(
        "fms_console_serve_under_test", CONSOLE_DIR / "serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


console = _console()


@pytest.fixture()
def service(tmp_path):
    """실제 설정·실제 프로파일로 조립한다. 가짜 데이터를 넣지 않는다."""
    return console.build_service(
        ui_config=PROJECT_DIR / "config" / "status_ui.fms.example.json",
        zone_profile=PROJECT_DIR / "profiles" / "domains.example.json",
        goal_kinds=PROJECT_DIR / "profiles" / "goal_kinds.example.json",
        with_fleet=True,
        overlay_path=tmp_path / "edits.json",
    )


#: 고정 카메라 한 대(pi6)와 이동형 로봇 한 대(go1-onboard)가 있는 구역.
#: 이 배치에 보유한 고정 카메라는 3대뿐이고 둘은 하천 현장에 있으므로, 한 구역의
#: 두 번째 관측자는 **로봇의 카메라**다 — 그래서 아래 시험은 로봇이 자기 방향을
#: 보고한 뒤에 비로소 두 관측이 한 객체로 합쳐지는 것을 확인한다.
ZONE = "N4-1F-W"

#: 두 관측이 가리키는 지점(구역 로컬 미터). pi6(6,4,yaw 90)의 정면 6 m 다.
TARGET = (6.0, 10.0)

#: go1 의 선언 자리와, 거기서 TARGET 을 보기 위한 방향·거리. 숫자를 손으로 적지 않고
#: 기하에서 계산한다 — 손으로 적으면 좌표를 바꿀 때 조용히 틀린다.
GO1_AT = (14.0, 9.0)
GO1_YAW_DEG = math.degrees(math.atan2(TARGET[1] - GO1_AT[1], TARGET[0] - GO1_AT[0]))
GO1_RANGE_M = math.hypot(TARGET[0] - GO1_AT[0], TARGET[1] - GO1_AT[1])


def _robot_faces_target(service):
    """로봇이 자기 자세를 알린다. 선언 프로파일에는 방향이 없다 — 방향은 관측값이다."""
    return service.report_pose(caller=Caller.for_role("admin"), body={
        "device_id": "go1-onboard", "zone_id": ZONE,
        "pose": {"x": GO1_AT[0], "y": GO1_AT[1], "yaw_deg": GO1_YAW_DEG},
        "pose_source": "reported",
    })


def _see(service, *, detection_id, device_id, range_m, label="person", track=1):
    return service.ingest_detection(caller=Caller.for_role("admin"), body={
        "detection_id": detection_id, "device_id": device_id, "track_local_id": track,
        "frame_ref": f"{device_id}/f1", "bbox": [0.48, 0.4, 0.52, 0.6],
        "label": label, "confidence": 0.8, "range_m": range_m,
    })


# --- 탐지가 없으면 그림도 없다 ----------------------------------------------


def test_the_fused_picture_is_empty_until_a_device_reports(service):
    """콘솔이 지어낸 값은 관측이 아니다. 비어 있는 것이 정상 상태다(AI-C-05)."""
    view = service.twin_view(ZONE, caller=Caller.for_role("admin"))

    assert view["records"] == []
    assert view["devices"], "장치는 선언되어 있다 — 기여가 0 인 것과 장치가 없는 것은 다르다"


def test_a_zone_view_reports_when_it_was_last_refreshed(service):
    view = service.twin_view(ZONE, caller=Caller.for_role("admin"))

    assert view["freshness"] in ("never", "fresh", "stale")
    assert view["as_of"] is not None, "열었으면 그 시각이 있어야 한다"


def test_a_repeated_view_is_suppressed_rather_than_recomputed(service):
    service.twin_view(ZONE, caller=Caller.for_role("admin"))

    second = service.twin_view(ZONE, caller=Caller.for_role("admin"))

    assert second["refresh"]["performed"] is False
    assert second["refresh"]["reason"] == "suppressed_within_min_interval"


# --- 두 장치가 본 것이 하나로 합쳐진다 --------------------------------------


def test_a_fixed_camera_and_a_robot_seeing_one_object_produce_one_record(service):
    _robot_faces_target(service)
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    _see(service, detection_id="d2", device_id="go1-onboard", range_m=GO1_RANGE_M, track=4)

    records = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"]

    assert len(records) == 1, "같은 자리를 본 두 관측이 두 객체가 되면 지도가 중복된다"
    assert set(records[0]["contributor_device_ids"]) == {"go1-onboard", "pi6"}


def test_without_the_reported_heading_the_two_observations_stay_separate(service):
    """로봇의 방향을 선언값(0도)으로 두면 같은 물체를 봐도 다른 자리에 투영된다.

    이것이 융합이 틀리는 가장 흔한 이유이고, 그래서 자세는 관측으로 들어와야 한다.
    연계를 억지로 붙이지 않고 **두 객체로 남기는 것**이 올바른 거절이다.
    """
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    _see(service, detection_id="d2", device_id="go1-onboard", range_m=GO1_RANGE_M, track=4)

    assert len(service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"]) == 2


def test_an_object_only_one_device_can_see_stays_a_single_contributor_record(service):
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)

    records = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"]

    assert len(records) == 1
    assert records[0]["contributor_device_ids"] == ["pi6"]


def test_the_same_detection_twice_does_not_become_two_observations(service):
    first = _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    again = _see(service, detection_id="d1", device_id="pi6", range_m=6.0)

    assert first["object_id"] == again["object_id"]
    devices = {d["device_id"]: d for d in service.twin_view(ZONE, caller=Caller.for_role("admin"))["devices"]}
    assert devices["pi6"]["observation_count"] == 1


# --- 개발자만 내부를 본다 ---------------------------------------------------


def test_tracing_a_value_needs_the_internals_capability(service):
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    object_id = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"][0]["object_id"]

    # 운영자는 명령은 내지만 계약 원문·provider 내부는 보지 않는다. 역할 이름으로
    # 가르지 않고 능력(`may_see_internals`)으로 가르는 것이 요점이다.
    with pytest.raises(console.ApiError) as caught:
        service.object_trace(object_id, about="position",
                             caller=Caller.for_role("operator"))

    assert caught.value.status == 403
    # 같은 호출이 개발자에게는 통한다.
    assert service.object_trace(object_id, about="position",
                                caller=Caller.for_role("developer"))["ranking_rule"]


def test_the_trace_names_the_device_whose_evidence_moved_the_value(service):
    _robot_faces_target(service)
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    _see(service, detection_id="d2", device_id="go1-onboard", range_m=GO1_RANGE_M, track=4)
    object_id = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"][0]["object_id"]

    trace = service.object_trace(object_id, about="position", caller=Caller.for_role("developer"))

    assert trace["ranking_rule"]
    assert {c["device_id"] for c in trace["contributors"]} == {"go1-onboard", "pi6"}
    assert len(trace["evidence_rows"]) == 2


def test_a_reported_pose_is_marked_as_reported_not_declared(service):
    outcome = _robot_faces_target(service)

    assert outcome["pose_source"] == "reported"
    devices = {d["device_id"]: d
               for d in service.twin_view(ZONE, caller=Caller.for_role("admin"))["devices"]}
    assert devices["go1-onboard"]["pose_source"] == "reported"


# --- 사람이 고치면 객체는 바뀌고 모델은 바뀌지 않는다 ------------------------


def test_a_position_correction_keeps_the_sensor_answer_beside_it(service):
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    object_id = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"][0]["object_id"]

    outcome = service.correction(caller=Caller.for_role("admin"), body={
        "object_id": object_id, "at": {"x": 7.5, "y": 11.2},
        "reason": "operator_drag", "zone_id": ZONE})

    record = outcome["record"]
    assert record["fused_position"] == [7.5, 11.2]
    assert record["sensor_fused_position"] != [7.5, 11.2], "센서가 말한 값이 지워지면 안 된다"
    assert record["position_disagreement_m"] > 0


def test_a_correction_files_a_human_confirmed_candidate_at_candidate_state(service):
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    object_id = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"][0]["object_id"]

    outcome = service.correction(caller=Caller.for_role("admin"), body={
        "object_id": object_id, "at": {"x": 7.5, "y": 11.2}, "reason": "drag"})

    assert outcome["learning_candidate_id"]
    assert outcome["learning_state"] == "candidate", "승인 없이 모델에 반영되면 AI-L-07 위반"
    ledger = service.learning_candidates(caller=Caller.for_role("admin"))
    assert len(ledger["human_confirmed"]) == 1
    assert ledger["auto_inference"] == []


def test_a_cue_correction_makes_the_operator_label_win_without_losing_the_sensor_label(service):
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0, label="person")
    object_id = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"][0]["object_id"]

    outcome = service.correction(caller=Caller.for_role("admin"), body={
        "object_id": object_id, "device_id": "pi6", "cue_name": "semantic_class",
        "value": "maintenance_cart", "reason": "wrong_label"})

    record = outcome["record"]
    assert record["semantic_class"] == "maintenance_cart"
    assert record["sensor_semantic_class"] == "person"


def test_correcting_is_refused_without_the_correction_capability(service):
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    object_id = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"][0]["object_id"]

    # 개발자는 정정 권한이 있으므로 여기서는 운영자를 쓴다 — 명령은 내지만 근거를
    # 고치지는 않는 역할이다.
    with pytest.raises(console.ApiError) as caught:
        service.correction(caller=Caller.for_role("operator"), body={
            "object_id": object_id, "at": {"x": 1.0, "y": 1.0}})

    assert caught.value.status == 403


# --- 고친 값은 디스크에 남는다 ----------------------------------------------


def test_every_correction_lands_in_the_operator_edit_log(service):
    _see(service, detection_id="d1", device_id="pi6", range_m=6.0)
    object_id = service.twin_view(ZONE, caller=Caller.for_role("admin"))["records"][0]["object_id"]
    service.correction(caller=Caller.for_role("admin"), body={
        "object_id": object_id, "at": {"x": 7.5, "y": 11.2}, "reason": "drag"})

    log = service.overlay_log(kind=None, target_id=None)

    assert log["available"] is True
    assert [e["kind"] for e in log["entries"]] == ["object_position"]
    # 예시 자세의 작성자는 `demo:<role>` 이다 — 나중에 장부를 읽을 때 실제 사람이
    # 한 것과 구분되어야 한다(AI-L-03).
    assert log["entries"][0]["actor"] == "demo:admin"


def test_a_placement_edit_is_persisted_and_reloaded_by_a_fresh_service(service, tmp_path):
    service.placement(caller=Caller.for_role("admin"), body={
        "device_id": "mt4", "zone_id": "N4-2F-W",
        "at": {"x": 20.0, "y": 30.0}, "reason": "surveyed"})

    restarted = console.build_service(
        ui_config=PROJECT_DIR / "config" / "status_ui.fms.example.json",
        zone_profile=PROJECT_DIR / "profiles" / "domains.example.json",
        goal_kinds=PROJECT_DIR / "profiles" / "goal_kinds.example.json",
        with_fleet=False, overlay_path=tmp_path / "edits.json")
    zone = restarted.zone("N4-2F-W")

    moved = [i for i in zone["infrastructure"] if i["id"] == "mt4"][0]
    assert moved["at"] == {"x": 20.0, "y": 30.0}
    assert moved["at_origin"] == "operator_edit"
    assert moved["declared_at"] != moved["at"], "선언된 자리가 지워지면 어긋남을 말할 수 없다"


def test_a_mobile_robot_is_not_a_placement_a_human_may_drag(service):
    """이동형 로봇의 자리는 관측이 정한다 — 사람이 넣은 값이 관측을 덮으면 갈린다."""
    with pytest.raises(console.ApiError) as caught:
        service.placement(caller=Caller.for_role("admin"), body={
            "device_id": "go1-onboard", "zone_id": ZONE, "at": {"x": 1.0, "y": 1.0}})

    assert caught.value.reason == "device_not_movable"


def test_a_survey_value_records_who_measured_it(service):
    service.survey(caller=Caller.for_role("admin"), body={
        "zone_id": ZONE, "quantity_id": "wall_length", "value": 29.4,
        "unit": "m", "reason": "줄자 실측"})

    rows = service.overlay_log(kind="survey", target_id=None)["entries"]

    assert rows[0]["target_id"] == f"{ZONE}/wall_length"
    assert rows[0]["actor"] == "demo:admin"
    assert rows[0]["payload"]["value"] == 29.4


# --- 임무는 구역 순서를 보존한다 --------------------------------------------


def test_a_multi_zone_plan_keeps_the_derived_order(service):
    plan = service.mission_plan(
        node_id="go1-onboard", goal_kind="m10_dt_map_update", zones=(), caller=Caller.for_role("admin"))

    assert plan["zone_order"]
    assert [leg["zone_id"] for leg in plan["legs"]] == list(plan["zone_order"])
    assert [leg["order_index"] for leg in plan["legs"]] == list(range(len(plan["legs"])))


def test_assigning_a_mission_refreshes_exactly_the_zones_it_touches(service):
    plan = service.mission_plan(
        node_id="go1-onboard", goal_kind="m10_dt_map_update", zones=(), caller=Caller.for_role("admin"))

    refreshed = {d["scope"] for d in plan["refresh"]}

    assert refreshed == {f"zone:{z}" for z in plan["zone_order"]}
    assert all(d["performed"] for d in plan["refresh"]), "임무 부여는 억제하지 않는다"


# --- 사람이 만든 정답은 후보 원장과 계보에 함께 선다 ------------------------
#
# 정답을 후보 보관소에 직접 넣으면 표본은 생기지만 원장(AI-L-02)에도 계보(AI-L-08)에도
# 나타나지 않는다. 그러면 운영자가 손으로 만든 정답이 후보 화면에서 보이지 않고,
# 나중에 그 가중치가 어느 검수에서 왔는지 되짚을 입구가 사라진다. 아래 시험들이
# 그 문이 열려 있는지 고정한다. 추론기가 없는 기계에서도 돌도록 상자는 직접 만든다.

@pytest.fixture()
def labeled(service):
    """상자 하나를 고친 정답을 만든다. 실제 프레임·실제 모델이 없어도 선다."""
    from labeling import BoxVerdict, GroundTruthRecord, LabeledBox, PredictedBox

    predicted = PredictedBox(box_id="p0", box=(0.5, 0.2, 0.6, 0.6),
                             semantic_class="person", confidence=0.88, range_m=6.0)
    corrected = LabeledBox(box_id="p0", verdict=BoxVerdict.RELABELED, predicted=predicted,
                           corrected_box=(0.53, 0.2, 0.67, 0.66),
                           corrected_class="maintenance_worker", corrected_range_m=5.4,
                           labeled_by="demo:labeler", labeled_at=100.0)
    missed = LabeledBox(box_id="hand-1", verdict=BoxVerdict.ADDED,
                        corrected_box=(0.8, 0.3, 0.92, 0.72),
                        corrected_class="trash bag", labeled_by="demo:labeler",
                        labeled_at=100.0)
    record = GroundTruthRecord(
        task_id="pi4:frame_000020.jpg", frame_ref="pi4/frame_000020.jpg",
        device_id="pi4", boxes=(corrected, missed), submitted_by="demo:labeler",
        submitted_at=100.0, model_version="YoloWorldPerceptionProvider",
        zone_id=ZONE, reason="작업자 오분류와 쓰레기 봉투 누락")
    filed = service._file_label_candidates(
        record, caller=Caller.for_role("labeler"), reason=record.reason)
    return record, filed


def test_ground_truth_stands_on_the_human_confirmed_side_of_the_ledger(service, labeled):
    _record, filed = labeled

    ledger = service.learning_candidates(caller=Caller.for_role("admin"))

    assert len(ledger["human_confirmed"]) == len(filed) == 2
    assert ledger["auto_inference"] == []
    assert {c["learning_candidate_id"] for c in ledger["human_confirmed"]} == \
           {c["learning_candidate_id"] for c in filed}


def test_a_filed_candidate_names_the_box_it_came_from(service, labeled):
    """`object_id` 가 비는 것이 요점이다 — 저장된 프레임의 상자는 지속 객체에
    묶이지 않았고, 묶이지 않았다고 적는 편이 없는 식별자를 지어내는 것보다 낫다."""
    _record, _filed = labeled

    rows = {c["box_ref"]: c
            for c in service.learning_candidates(caller=Caller.for_role("admin"))["human_confirmed"]}

    assert set(rows) == {"pi4:frame_000020.jpg:p0", "pi4:frame_000020.jpg:hand-1"}
    assert rows["pi4:frame_000020.jpg:p0"]["label"] == "maintenance_worker"
    assert rows["pi4:frame_000020.jpg:p0"]["reason"] == "ground_truth:relabeled"
    assert rows["pi4:frame_000020.jpg:hand-1"]["reason"] == "ground_truth:added"
    assert all(c["object_id"] == "" for c in rows.values())
    assert all(c["frame_ref"] == "pi4/frame_000020.jpg" for c in rows.values())


def test_the_developer_can_walk_back_from_a_candidate_to_the_review(service, labeled):
    _record, filed = labeled

    answer = service.lineage(filed[0]["learning_lineage_id"],
                             caller=Caller.for_role("developer"))

    assert answer["lineage"]["state"] == "candidate"
    first = answer["lineage"]["events"][0]
    assert first["requirement_id"] == "AI-L-01"
    assert first["actor"] == "demo:labeler"
    assert first["reason"] == "작업자 오분류와 쓰레기 봉투 누락"
    assert first["evidence_ref"] == "pi4/frame_000020.jpg"
    assert answer["candidate"]["box_ref"] == "pi4:frame_000020.jpg:p0"


def test_tracing_a_lineage_needs_the_internals_capability(service, labeled):
    _record, filed = labeled
    lineage_id = filed[0]["learning_lineage_id"]

    with pytest.raises(console.ApiError) as refused:
        service.lineage(lineage_id, caller=Caller.for_role("operator"))

    assert refused.value.status == 403
    assert service.lineage(lineage_id, caller=Caller.for_role("admin"))["lineage"]


def test_an_unknown_lineage_is_a_miss_not_a_crash(service):
    with pytest.raises(console.ApiError) as missing:
        service.lineage("lin-does-not-exist", caller=Caller.for_role("developer"))

    assert missing.value.status == 404


def test_a_candidate_cannot_be_filed_without_saying_why(service, labeled):
    """사유 없는 정답은 계보를 열 수 없다. 그래서 여기서 거절한다 — 통과시키면
    나중에 그 가중치를 보고도 어떤 판단이었는지 말할 수 없다."""
    record, _filed = labeled

    with pytest.raises(ValueError):
        service._file_label_candidates(record, caller=Caller.for_role("labeler"), reason="")


# --- 라우터는 따로 선다 ------------------------------------------------------
#
# 와이파이 송출기를 엣지 노드에 랜선으로 붙이지 않고 따로 두기로 했다. 그러면 그
# 자리는 실측값이고 가상 환경에 보여야 하는 물건이며, 처음 적는 값은 거의 틀린다 —
# 실내에서는 AP 를 천장 어디에 달았는지가 반경보다 구역 모양을 더 바꾼다. 아래
# 시험들이 그 세 가지를 고정한다: 장치로 보인다, 사람이 옮긴다, 선언값임을 말한다.

def test_the_router_shows_up_as_a_device_of_its_own(service):
    view = service.zone(ZONE)
    access_point = view["access_point"]

    assert access_point["id"] == (view["wifi"] or {})["ap_id"]
    assert access_point["kind"] == "access_point"
    assert access_point["at"] == access_point["declared_at"]
    # 노드로 조인하지 않는다 — 자원도 capability 도 없고, 그 사실을 적는다.
    assert access_point["joins_as_node"] is False


def test_the_router_position_is_declared_until_somebody_surveys_it(service):
    """`site.verified_fields` 가 `ap_placement` 를 적지 않았으면 실측이 아니다.
    아무 말도 없는 것을 확인으로 읽으면 선언값이 실측값처럼 보인다."""
    view = service.zone(ZONE)

    assert view["access_point"]["placement_verified"] is False


def test_an_operator_can_move_the_router_like_any_other_fixed_device(service):
    """라우터도 스스로 움직이지 않으므로 같은 규칙에 든다. 노드로 조인하지 않아
    `facts` 에 없을 뿐이고, 없다는 것이 "옮기면 안 된다" 는 뜻은 아니다."""
    before = service.zone(ZONE)["access_point"]
    assert before["id"] in service.fleet.movable_devices(ZONE)

    moved = service.placement(caller=Caller.for_role("operator"), body={
        "device_id": before["id"], "zone_id": ZONE,
        "at": {"x": 22.5, "y": 3.0}, "reason": "천장 AP 실측 — 복도 쪽 끝"})

    after = service.zone(ZONE)["access_point"]
    assert moved["at_origin"] == "operator_edit"
    assert after["at"] == {"x": 22.5, "y": 3.0}
    # 선언을 지우지 않는다 — 선언과 실측이 얼마나 어긋났는지가 다음 조사의 근거다.
    assert after["declared_at"] == before["declared_at"]
    assert after["at_origin"] == "operator_edit"


def test_moving_the_router_is_refused_without_the_placement_capability(service):
    ap_id = service.zone(ZONE)["access_point"]["id"]

    with pytest.raises(console.ApiError) as refused:
        service.placement(caller=Caller.for_role("labeler"), body={
            "device_id": ap_id, "zone_id": ZONE, "at": {"x": 1.0, "y": 1.0},
            "reason": "해보기"})

    assert refused.value.status == 403


def test_resetting_the_router_position_returns_to_the_declaration(service):
    ap_id = service.zone(ZONE)["access_point"]["id"]
    declared = service.zone(ZONE)["access_point"]["declared_at"]
    service.placement(caller=Caller.for_role("operator"), body={
        "device_id": ap_id, "zone_id": ZONE, "at": {"x": 2.0, "y": 2.0}, "reason": "오타"})

    service.placement(caller=Caller.for_role("operator"), body={
        "device_id": ap_id, "zone_id": ZONE, "reset": True, "reason": "오타였다"})

    after = service.zone(ZONE)["access_point"]
    assert after["at"] == declared
    assert after["at_origin"] == "declared"
    # 되돌림도 삭제가 아니라 기록이다.
    kinds = [row["kind"] for row in service.overlay_log(kind="placement",
                                                        target_id=ap_id)["entries"]]
    assert kinds.count("placement") >= 2


# --- 화면의 능력 이름과 서버의 능력 이름은 같아야 한다 ----------------------


FMS_PAGE = (CONSOLE_DIR / "index.html").read_text(encoding="utf-8")


def test_the_page_gates_moving_devices_on_the_placement_capability():
    """자리를 고치는 손잡이를 **근거 정정** 능력에 걸면 두 가지가 동시에 틀린다:
    서버가 허용하는 운용자에게 손잡이가 없고, 서버가 거절할 검수자에게 손잡이가
    생긴다. 화면이 묻는 능력 이름을 여기서 고정한다."""
    from accounts import PERM_CORRECT, PERM_EDIT_PLACEMENT

    assert f'may_edit_placement: may("{PERM_EDIT_PLACEMENT}")' in FMS_PAGE
    assert "const mayMove = !!S.caps.may_edit_placement;" in FMS_PAGE
    # 근거 정정 능력은 남아 있되 자리와 섞이지 않는다.
    assert PERM_CORRECT in FMS_PAGE
    assert "mayEdit" not in FMS_PAGE, "한 칸으로 묶은 옛 이름이 남아 있다"


def test_only_hit_areas_on_the_map_receive_the_pointer():
    """맵 위의 글자·격자·방향선은 장식이다. 포인터를 받게 두면 장치 위에 겹쳐
    그 장치를 집을 수 없게 된다 — 실제로 장치 이름(text)과 카메라 방향선(line)이
    마커를 덮어 끌기가 되지 않았다. 그 한 줄이 지워지면 다시 그렇게 된다."""
    assert "svg.stage *{pointer-events:none}" in FMS_PAGE
    assert "svg.stage .zonehit,svg.stage .zonehit *{pointer-events:all}" in FMS_PAGE


def test_the_router_is_listed_where_the_undo_button_lives():
    """맵에서는 끌 수 있는데 목록에 없으면 되돌릴 길이 없다 — 되돌리기 버튼이
    그 목록에만 있다."""
    assert "...(zone.access_point ? [zone.access_point] : [])].map(i =>" in FMS_PAGE
