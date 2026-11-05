"""implements: AI-B-09, AI-E-02, AI-L-09, AI-L-10
covers: 비개발자가 웹에서 하는 네 가지 — 장치를 들이고, 카메라 정보를 적어 보정하고,
        확인된 후보로 학습하고, 기기별 모델을 바꾼다. 그 네 가지가 **거절해야 할 때
        거절하는가**를 고정한다. 정상 경로보다 먼저 거절을 적는 것이 §6-7 의 순서다.
"""

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
CONSOLE_DIR = PROJECT_DIR / "tools" / "fms_console"
for candidate in (CONSOLE_DIR, PROJECT_DIR / "tools" / "status_ui"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import deployment as D  # noqa: E402
from accounts import (  # noqa: E402
    PERM_CALIBRATE,
    PERM_DEPLOY_MODEL,
    PERM_ONBOARD,
    PERM_TRAIN,
    Caller,
)
from mission_runtime.continual.lineage import LearningLineage, LearningState  # noqa: E402
from mission_runtime.continual.parameter_evaluation import EvaluationGate  # noqa: E402
from mission_runtime.continual.stream_learning import (  # noqa: E402
    CandidateOrigin,
    CandidateStore,
    InputConditions,
    StreamSample,
)
from mission_runtime.runtime.model_assignment import (  # noqa: E402
    DeviceProfile,
    MissionRequirement,
    ModelVersion,
)
from mission_runtime.runtime.mlops_pipeline import PromotionScope, next_scope  # noqa: E402

MODEL_REGISTRY = PROJECT_DIR / "config" / "model_versions.example.json"


def _console():
    spec = importlib.util.spec_from_file_location(
        "fms_console_serve_for_deployment", CONSOLE_DIR / "serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


console = _console()


@pytest.fixture()
def service(tmp_path):
    return console.build_service(
        ui_config=PROJECT_DIR / "config" / "status_ui.fms.example.json",
        zone_profile=PROJECT_DIR / "profiles" / "domains.example.json",
        goal_kinds=PROJECT_DIR / "profiles" / "goal_kinds.example.json",
        with_fleet=True,
        overlay_path=tmp_path / "edits.json",
    )


def _admin():
    return Caller.for_role("admin")


# ---------------------------------------------------------------------------
# 1. 들이기 — 선언을 받되 가용성은 판정하지 않는다
# ---------------------------------------------------------------------------

GOOD_JOIN = {
    "device_id": "go2-01", "role": "ugv",
    "node_tags": ["compute.cpu", "tier.ugv", "sensor.camera.front"],
    "declared_actions": ["move_to", "stop", "look_at"],
    "announced_actions": ["move_to", "stop"],
    "has_camera": True, "reason": "현장에 새로 들어온 로봇",
}


def test_a_declaration_that_fits_the_contract_leaves_the_work_that_is_not_automatic(service):
    """조인은 코드 변경이 아니다 — 선언 1건이 설정 한 줄이 되고, 자동으로 되지
    않는 것만 할 일로 남는다(AI-B-09)."""
    body = service.join_device(caller=_admin(), body=dict(GOOD_JOIN))

    assert body["outcome"]["accepted"] is True
    # 카메라를 달고 왔고 보정 버전이 없으므로 보정이, 외형 이미지가 없으므로 외형
    # 학습이, 예산을 적지 않았으므로 프로파일 측정이 남는다.
    assert set(body["outcome"]["next_steps"]) == {
        "calibrate_camera", "learn_appearance", "confirm_placement",
        "verify_execution_profile"}
    entry = body["config_entry"]
    assert entry["node_id"] == "go2-01"
    assert entry["verified"] is False          # 현장 실측 전이라는 표시
    assert "budget" not in entry               # 미측정 예산을 0 으로 메우지 않는다


def test_an_action_declared_but_never_announced_is_reported_as_an_adapter_gap(service):
    body = service.join_device(caller=_admin(), body=dict(GOOD_JOIN))

    assert body["outcome"]["unannounced_declarations"] == ["look_at"]


def test_a_declaration_that_does_not_fit_is_refused_field_by_field(service):
    body = service.join_device(caller=_admin(), body={
        "device_id": "GO2 01", "role": "", "reason": "일부러 틀리게"})

    codes = {r["code"] for r in body["outcome"]["rejections"]}
    assert codes == {"bad_device_id", "missing_field", "no_action_vocabulary"}
    assert body["config_entry"] is None


def test_a_join_without_a_reason_is_refused_before_anything_is_recorded(service):
    with pytest.raises(console.ApiError) as raised:
        service.join_device(caller=_admin(), body={k: v for k, v in GOOD_JOIN.items()
                                                   if k != "reason"})

    assert raised.value.reason == "reason_required"
    assert service.joins().onboarding.joined() == ()


def test_a_device_the_declaration_file_already_names_is_not_joined_twice(service):
    body = service.join_device(caller=_admin(), body={
        "device_id": "pi6", "role": "fixed_camera", "node_tags": ["compute.cpu"],
        "declared_actions": ["capture"], "reason": "선언 파일에 이미 있다"})

    assert [r["code"] for r in body["outcome"]["rejections"]] == ["duplicate_device_id"]


def test_a_duplicate_declaration_does_not_erase_the_work_left_for_the_device_already_in(service):
    """같은 id 로 실수로 한 번 더 올려도 그 장치의 할 일이 사라지지 않는다.

    이것이 실제로 났던 결함이다 — 거절 결과가 받아들인 결과를 덮어써서
    `accepted` 가 거짓이 되고, 남아 있던 보정·외형학습·자리확인이 대기 목록에서
    조용히 빠졌다. 할 일이 없어진 것처럼 보이지만 아무것도 끝나지 않은 상태다.
    """
    service.join_device(caller=_admin(), body=dict(GOOD_JOIN))
    before = service.deployment_view(caller=_admin())["join"]["pending"]

    again = service.join_device(caller=_admin(), body=dict(GOOD_JOIN))
    after = service.deployment_view(caller=_admin())["join"]

    assert [r["code"] for r in again["outcome"]["rejections"]] == ["duplicate_device_id"]
    assert after["pending"] == before
    assert "go2-01" in after["pending"]["calibrate_camera"]
    # 거절도 사라지지 않는다 — 올렸는데 아무 일도 없었다가 되면 안 된다.
    assert [o["device_id"] for o in after["refused"]] == ["go2-01"]


def test_finishing_one_step_removes_only_that_step(service):
    service.join_device(caller=_admin(), body=dict(GOOD_JOIN))

    body = service.resolve_join_step(caller=_admin(), body={
        "device_id": "go2-01", "step": "confirm_placement", "reason": "현장 확인"})

    assert "confirm_placement" not in body["outcome"]["next_steps"]
    assert "calibrate_camera" in body["outcome"]["next_steps"]


def test_a_step_name_the_contract_does_not_know_is_refused(service):
    service.join_device(caller=_admin(), body=dict(GOOD_JOIN))

    with pytest.raises(console.ApiError) as raised:
        service.resolve_join_step(caller=_admin(), body={
            "device_id": "go2-01", "step": "폴리시", "reason": "r"})

    assert raised.value.reason == "unknown_step:폴리시"


def test_a_joined_camera_shows_up_in_the_calibration_list(service):
    """보정 대상은 고정 카메라만이 아니다 — 카메라를 달고 온 로봇도 들어온다."""
    service.join_device(caller=_admin(), body=dict(GOOD_JOIN))

    cameras = {c["device_id"] for c
               in service.deployment_view(caller=_admin())["calibration"]["cameras"]}

    assert "go2-01" in cameras
    assert "pi6" in cameras


# ---------------------------------------------------------------------------
# 2. 카메라 정보 → 보정 — 선언과 측정을 섞지 않는다
# ---------------------------------------------------------------------------

#: 합성 보정판을 만들 조건. 알려진 fx 로 투영하므로 **되찾은 값을 검사할 수 있다**.
BOARD_COLS, BOARD_ROWS, SQUARE_MM = 9, 6, 25.0
IMAGE_W, IMAGE_H, TRUE_FX = 1280, 720, 900.0
VIEWS = (
    ((0.0, 0.0, 0.0), (0.0, 0.0, 0.62)),
    ((0.30, 0.0, 0.0), (0.02, 0.0, 0.60)),
    ((0.0, 0.32, 0.0), (-0.02, 0.01, 0.58)),
    ((-0.28, 0.18, 0.1), (0.01, -0.02, 0.64)),
    ((0.22, -0.26, -0.08), (0.0, 0.02, 0.59)),
)


def _render_board_captures(out_dir: Path) -> int:
    """알려진 내부 파라미터로 보정판을 투영해 실제 영상을 만든다.

    왜 합성인가: 보정판을 들고 찍은 사진은 공개 트리에 없고 기계마다 다르다. 반면
    여기서 **측정되는 것은 진짜다** — 코너는 검출로 찾고 내부 파라미터는
    `cv2.calibrateCamera` 가 푼다. 투영에 쓴 fx 를 알고 있으므로 되찾은 값이 맞는지
    검사할 수 있다. 캡처를 미리 넣어 두고 수치를 손으로 적는 쪽은 아무것도 재지 않는다.
    """
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    out_dir.mkdir(parents=True, exist_ok=True)

    scale = 80
    pad = scale
    cells_x, cells_y = BOARD_COLS + 1, BOARD_ROWS + 1
    board = np.full((cells_y * scale + 2 * pad, cells_x * scale + 2 * pad), 255, np.uint8)
    for j in range(cells_y):
        for i in range(cells_x):
            if (i + j) % 2 == 0:
                board[pad + j * scale:pad + (j + 1) * scale,
                      pad + i * scale:pad + (i + 1) * scale] = 0
    bh, bw = board.shape
    half_w = cells_x * SQUARE_MM / 2000.0 + pad / scale * SQUARE_MM / 1000.0
    half_h = cells_y * SQUARE_MM / 2000.0 + pad / scale * SQUARE_MM / 1000.0
    plane = np.float32([[-half_w, -half_h, 0], [half_w, -half_h, 0],
                        [half_w, half_h, 0], [-half_w, half_h, 0]])
    src = np.float32([[0, 0], [bw, 0], [bw, bh], [0, bh]])
    matrix_k = np.float32([[TRUE_FX, 0, IMAGE_W / 2], [0, TRUE_FX, IMAGE_H / 2], [0, 0, 1]])

    written = 0
    for index, (rvec, tvec) in enumerate(VIEWS):
        projected, _ = cv2.projectPoints(plane, np.float32(rvec), np.float32(tvec),
                                         matrix_k, np.zeros(5, np.float32))
        warp = cv2.getPerspectiveTransform(
            src, projected.reshape(-1, 2).astype(np.float32))
        canvas = np.full((IMAGE_H, IMAGE_W), 128, np.uint8)
        warped = cv2.warpPerspective(board, warp, (IMAGE_W, IMAGE_H), borderValue=128)
        mask = cv2.warpPerspective(np.full_like(board, 255), warp, (IMAGE_W, IMAGE_H),
                                   borderValue=0)
        canvas[mask > 0] = warped[mask > 0]
        cv2.imwrite(str(out_dir / f"v{index + 1}.png"), canvas)
        written += 1
    return written


DECLARED = {
    "device_id": "pi6", "width_px": IMAGE_W, "height_px": IMAGE_H,
    # 1280 * 3.6 / 5.12 = 900 px — 투영에 쓴 값과 같다.
    "focal_mm": 3.6, "sensor_width_mm": 5.12,
    "zoom_token": "full", "mount_token": "bracket-a",
}
BOARD = {"board_cols": BOARD_COLS, "board_rows": BOARD_ROWS, "square_mm": SQUARE_MM}


@pytest.fixture()
def board_desk(tmp_path):
    """보정판 캡처가 규약 경로에 놓인 책상."""
    count = _render_board_captures(tmp_path / "calibration" / "pi6")
    assert count >= D.MIN_CALIBRATION_VIEWS
    return D.CalibrationDesk(frames_root=tmp_path / "calibration")


def test_a_lens_spec_alone_never_becomes_an_active_profile():
    """제원표의 숫자는 관측이 아니다(AI-S-08) — 그것만으로 승격하지 않는다."""
    desk = D.CalibrationDesk(frames_root=None)
    info = D.camera_info_from_dict(dict(DECLARED))
    desk.declare(info)

    run = desk.calibrate("pi6")

    assert run.verdict == D.CALIB_NOT_MEASURED
    assert run.reasons == (D.NEED_BOARD_DECLARATION,)
    assert desk.store("pi6").active is None
    # 유도값은 남지만 측정값 칸에 들어가지 않는다.
    assert info.derived_fx() == pytest.approx(TRUE_FX, rel=1e-6)
    assert desk.view("pi6")["declared"]["derived_fx_px"] == pytest.approx(TRUE_FX)


def test_a_declaration_without_captures_keeps_the_last_known_good(board_desk, tmp_path):
    """캡처가 없는 카메라는 미측정이고, 활성 프로파일은 손대지 않는다(AI-E-02)."""
    board_desk.declare(D.camera_info_from_dict({**DECLARED, **BOARD, "device_id": "pi4"}))

    run = board_desk.calibrate("pi4")

    assert run.verdict == D.CALIB_NOT_MEASURED
    assert run.reasons == (D.NEED_FRAMES,)


def test_the_board_is_actually_measured_and_the_recovered_focal_length_is_right(board_desk):
    """측정은 흉내가 아니다 — 투영에 쓴 fx 를 되찾는다."""
    board_desk.declare(D.camera_info_from_dict({**DECLARED, **BOARD}))

    run = board_desk.calibrate("pi6")

    assert run.verdict == D.CALIB_PROMOTED, run.reasons
    assert run.measured_fx_px == pytest.approx(TRUE_FX, rel=0.02)
    assert run.reprojection_error_rms < 1.0
    assert run.frames_used == len(VIEWS)


def test_a_promoted_profile_carries_the_condition_it_was_verified_in(board_desk):
    """같은 카메라라도 해상도·장착이 바뀌면 다른 조건의 보정이다(AI-E-02)."""
    from mission_runtime.edge.calibration_profile import ApplicabilityScope

    board_desk.declare(D.camera_info_from_dict({**DECLARED, **BOARD}))
    board_desk.calibrate("pi6")
    profile = board_desk.store("pi6").active

    same = ApplicabilityScope("pi6", (IMAGE_W, IMAGE_H), "full", "bracket-a")
    half = ApplicabilityScope("pi6", (IMAGE_W // 2, IMAGE_H // 2), "full", "bracket-a")
    remounted = ApplicabilityScope("pi6", (IMAGE_W, IMAGE_H), "full", "bracket-b")

    assert profile.applies_to(same)
    assert not profile.applies_to(half)
    assert not profile.applies_to(remounted)


def test_a_measurement_that_disagrees_with_the_declared_lens_is_not_promoted(board_desk):
    """선언과 측정이 어긋나면 어느 쪽이 틀렸는지 이 코드가 알 수 없다 — 사람이 본다."""
    board_desk.declare(D.camera_info_from_dict({**DECLARED, **BOARD}))
    board_desk.calibrate("pi6")
    good_version = board_desk.store("pi6").active.version

    board_desk.declare(D.camera_info_from_dict(
        {**DECLARED, **BOARD, "focal_mm": 8.0}))     # fx 2000 — 측정의 두 배
    run = board_desk.calibrate("pi6")

    assert run.verdict == D.CALIB_REJECTED
    assert D.REJECT_FX_DISAGREES in run.reasons
    assert board_desk.store("pi6").active.version == good_version
    rejection = board_desk.store("pi6").rejections[-1]
    assert rejection.kept_version == good_version


def test_captures_that_are_not_the_declared_resolution_are_not_promoted(board_desk):
    board_desk.declare(D.camera_info_from_dict(
        {**DECLARED, **BOARD, "width_px": 1920, "height_px": 1080}))

    run = board_desk.calibrate("pi6")

    assert run.verdict == D.CALIB_REJECTED
    assert D.REJECT_SIZE_DISAGREES in run.reasons


def test_a_board_declared_with_the_wrong_grid_is_not_found(board_desk):
    board_desk.declare(D.camera_info_from_dict(
        {**DECLARED, "board_cols": 7, "board_rows": 5, "square_mm": SQUARE_MM}))

    run = board_desk.calibrate("pi6")

    assert run.verdict == D.CALIB_NOT_MEASURED
    assert run.reasons[0].startswith(D.NEED_BOARD_IN_FRAMES)


def test_the_screen_is_told_the_directory_that_is_actually_searched(board_desk, tmp_path):
    """화면이 적는 자리와 코드가 뒤지는 자리가 달라지면, 그것을 보고 캡처를 넣은
    사람은 없는 자리에 넣고 "왜 안 찾느냐" 를 묻게 된다."""
    board_desk.declare(D.camera_info_from_dict({**DECLARED, **BOARD}))

    shown = board_desk.view("pi6")["frame_dir"]

    assert shown == f"{tmp_path / 'calibration' / 'pi6'}/"
    assert Path(shown).is_dir()


def test_a_promoted_profile_claims_no_extrinsic(board_desk):
    """자리는 실측·관측이 정한다 — 보정판은 내부 파라미터만 낸다(AI-C-02)."""
    board_desk.declare(D.camera_info_from_dict({**DECLARED, **BOARD}))
    board_desk.calibrate("pi6")

    assert board_desk.store("pi6").active.has_extrinsic is False


def test_the_field_of_view_route_derives_the_same_kind_of_number():
    """제원표에 초점거리가 없고 화각만 있는 카메라도 비교 기준을 가진다."""
    hfov = 2.0 * math.degrees(math.atan((IMAGE_W / 2.0) / TRUE_FX))
    info = D.camera_info_from_dict({
        "device_id": "pi6", "width_px": IMAGE_W, "height_px": IMAGE_H, "hfov_deg": hfov})

    assert info.derived_fx() == pytest.approx(TRUE_FX, rel=1e-6)


def test_camera_info_without_an_image_size_is_refused():
    with pytest.raises(ValueError, match="image_size_required"):
        D.camera_info_from_dict({"device_id": "pi6"})


# ---------------------------------------------------------------------------
# 3. 학습 — 확인된 것만, 관문은 하나씩
# ---------------------------------------------------------------------------

CONDITIONS = InputConditions(device_id="pi4", camera_id="pi4",
                             extra=(("candidate_reason", "ground_truth:added"),))

#: 종류에 따라 상자 모양이 실제로 다르다. 문은 넓고 낮게, 사람은 좁고 높게.
BOXES = {
    "door": [(0.10, 0.30, 0.44, 0.76), (0.12, 0.31, 0.48, 0.75),
             (0.09, 0.29, 0.42, 0.76), (0.11, 0.32, 0.46, 0.77)],
    "person": [(0.52, 0.18, 0.63, 0.80), (0.55, 0.20, 0.65, 0.80),
               (0.50, 0.17, 0.62, 0.80)],
}


def _store(*, confirmed=True, conditions=CONDITIONS):
    store = CandidateStore()
    lineages = {}
    index = 0
    for label, boxes in BOXES.items():
        for box in boxes:
            index += 1
            sample_id = f"cand-{index}"
            store.add(StreamSample(
                sample_id=sample_id, conditions=conditions, label=label,
                feature=tuple(box),
                origin=(CandidateOrigin.HUMAN_CONFIRMED if confirmed
                        else CandidateOrigin.AUTO_INFERENCE)))
            lineages[sample_id] = LearningLineage(
                f"lin-{index}", actor="lab-1", evidence_ref=sample_id, reason="검수")
    return store, lineages


def _desk(**kwargs):
    store, lineages = _store(**kwargs)
    return D.TrainingDesk(store=store, sample_lineages=lineages)


def test_only_confirmed_candidates_are_counted_as_trainable():
    """자동 추론 결과는 몇 건이든 학습에 쓸 수 있는 수가 아니다(AI-L-02)."""
    auto = _desk(confirmed=False)

    group = auto.groups()[0]

    assert group["total"] == 7
    assert group["confirmed"] == 0
    assert group["trainable"] is False
    assert auto.train(group["group_key"], actor="dev-1",
                      reason="r") == {"produced": False, "reason": D.NO_CONFIRMED}


def test_the_hold_out_split_keeps_every_label_learnable():
    """라벨별로 뗀다. 통째로 뒷부분을 떼면 어떤 라벨이 학습에서 통째로 빠지고,
    그 라벨의 보류 표본은 "배우지 않은 것을 맞히라"는 문제가 된다.

    문 4 · 사람 3 · 라벨당 최소 3 이면 문에서만 1 건을 뗄 수 있다 — 사람은 뗄 여유가
    없다. 그래서 **두 라벨 모두 학습되고**, 재지 못한 라벨은 이름으로 드러난다.
    """
    desk = _desk()

    out = desk.train(desk.groups()[0]["group_key"], actor="dev-1", reason="혼동이 반복된다")
    candidate = desk.candidate(out["candidate"]["version"])

    assert set(candidate.parameters.labels()) == {"door", "person"}
    held = {s.label for s in desk._samples(candidate.held_out_sample_ids)}
    assert held == {"door"}
    assert candidate.unmeasured_labels == ("person",)


def test_a_label_with_room_to_spare_gets_its_own_held_out_sample():
    """뗄 여유가 생기면 그 라벨도 검증 집합에 들어간다 — 미측정이 줄어든다."""
    store, lineages = _store()
    store.add(StreamSample(sample_id="cand-extra", conditions=CONDITIONS, label="person",
                           feature=(0.53, 0.19, 0.64, 0.79),
                           origin=CandidateOrigin.HUMAN_CONFIRMED))
    lineages["cand-extra"] = LearningLineage("lin-extra", actor="lab-1",
                                             evidence_ref="cand-extra", reason="검수")
    desk = D.TrainingDesk(store=store, sample_lineages=lineages)

    out = desk.train(desk.groups()[0]["group_key"], actor="dev-1", reason="r")
    candidate = desk.candidate(out["candidate"]["version"])

    held = {s.label for s in desk._samples(candidate.held_out_sample_ids)}
    assert held == {"door", "person"}
    assert candidate.unmeasured_labels == ()


def test_the_lineage_records_only_the_samples_the_provider_actually_used():
    """제공자는 라벨별 최소 표본 수를 못 채운 라벨을 버린다 — 넘긴 수를 적으면
    계보가 거짓을 말한다."""
    desk = _desk()
    out = desk.train(desk.groups()[0]["group_key"], actor="dev-1", reason="r")
    candidate = desk.candidate(out["candidate"]["version"])

    counted = int(candidate.lineage.events[1].reason.split(":")[1])

    assert counted == len(candidate.used_sample_ids)


def test_training_opens_the_three_gates_it_actually_performed_and_stops():
    """학습 요청이 지나는 관문은 셋이고, 검증은 사람이 따로 돌린다."""
    desk = _desk()

    out = desk.train(desk.groups()[0]["group_key"], actor="dev-1", reason="r")
    lineage = desk.candidate(out["candidate"]["version"]).lineage

    assert lineage.state is LearningState.STRATEGY_SELECTED
    assert [e.requirement_id for e in lineage.events] == [
        "AI-L-01", "AI-L-02", "AI-L-03", "AI-L-04"]


def test_a_consumed_candidate_lineage_records_what_consumed_it():
    desk = _desk()
    out = desk.train(desk.groups()[0]["group_key"], actor="dev-1", reason="r")
    candidate = desk.candidate(out["candidate"]["version"])

    used = desk.sample_lineages[candidate.used_sample_ids[0]]

    assert used.state is LearningState.QUARANTINED
    assert used.events[-1].reason == f"consumed_by:{candidate.lineage.lineage_id}"


def test_nothing_held_out_means_not_measured_and_not_measured_is_not_a_pass():
    """라벨당 표본이 최소 수와 같으면 보류를 뗄 수 없다. 그때 통과시키면 게이트가
    아무것도 막지 못한다(AI-L-05)."""
    store = CandidateStore()
    lineages = {}
    index = 0
    for label, boxes in BOXES.items():
        for box in boxes[:3]:               # 라벨당 정확히 최소 수만
            index += 1
            sample_id = f"tight-{index}"
            store.add(StreamSample(sample_id=sample_id, conditions=CONDITIONS,
                                   label=label, feature=tuple(box),
                                   origin=CandidateOrigin.HUMAN_CONFIRMED))
            lineages[sample_id] = LearningLineage(f"lin-{sample_id}", actor="lab-1",
                                                  evidence_ref=sample_id, reason="검수")
    desk = D.TrainingDesk(store=store, sample_lineages=lineages)
    version = desk.train(desk.groups()[0]["group_key"], actor="dev-1",
                         reason="r")["candidate"]["version"]

    out = desk.validate(version, actor="dev-1", reason="쟀다")

    assert out["advanced"] is False
    assert out["result"] == "NOT_MEASURED"
    assert desk.candidate(version).lineage.state is LearningState.STRATEGY_SELECTED


def test_a_candidate_that_misses_the_held_out_sample_does_not_advance():
    """보류 집합에서 틀리면 통과하지 못한다. 마지막 문 상자를 아주 다르게 그려 두면
    그것이 보류로 가고, 프로토타입이 그것을 자기 class 로 보지 못한다."""
    store, lineages = _store()
    store.add(StreamSample(sample_id="cand-outlier", conditions=CONDITIONS, label="door",
                           feature=(0.80, 0.02, 0.99, 0.08),   # 동떨어진 상자
                           origin=CandidateOrigin.HUMAN_CONFIRMED))
    lineages["cand-outlier"] = LearningLineage("lin-outlier", actor="lab-1",
                                               evidence_ref="cand-outlier", reason="검수")
    desk = D.TrainingDesk(store=store, sample_lineages=lineages)
    version = desk.train(desk.groups()[0]["group_key"], actor="dev-1",
                         reason="r")["candidate"]["version"]

    out = desk.validate(version, actor="dev-1", reason="쟀다")

    assert out["advanced"] is False
    assert out["result"] == "FAIL"
    assert out["reason"] == "new_accuracy_below_minimum"
    assert desk.candidate(version).lineage.state is LearningState.STRATEGY_SELECTED


def test_the_criteria_actually_applied_are_written_into_the_lineage():
    """기준은 데이터지만, 기준을 낮춰 통과한 것과 기준을 넘은 것은 구분돼야 한다."""
    desk = _desk()
    version = desk.train(desk.groups()[0]["group_key"], actor="dev-1",
                         reason="r")["candidate"]["version"]

    out = desk.validate(version, actor="dev-1", reason="현장 기준선",
                        gate=EvaluationGate(min_new_accuracy=0.0))

    assert out["advanced"] is True
    note = desk.candidate(version).lineage.events[-1].reason
    assert "min_new=0.0" in note
    assert desk.candidate(version).as_dict()["gate_used"]["min_new_accuracy"] == 0.0


def test_approval_needs_two_separate_states_so_two_people_can_sign_them():
    """검증 통과 → 승인 요청 → 승인. 한 번에 밀면 요청한 사람과 승인한 사람이
    같아도 알 수 없다(AI-L-06)."""
    desk = _desk()
    version = desk.train(desk.groups()[0]["group_key"], actor="dev-1",
                         reason="r")["candidate"]["version"]
    desk.validate(version, actor="dev-1", reason="쟀다",
                  gate=EvaluationGate(min_new_accuracy=0.0))

    # 검증만 통과한 상태에서 바로 승인하면 상태가 맞지 않는다.
    assert desk.approve(version, actor="jny", reason="승인")["advanced"] is False

    assert desk.request_approval(version, actor="dev-1", reason="요청")["advanced"] is True
    assert desk.approve(version, actor="jny", reason="승인")["advanced"] is True
    lineage = desk.candidate(version).lineage
    assert lineage.state is LearningState.APPROVED
    assert lineage.events[-1].actor == "jny"
    assert lineage.events[-2].actor == "dev-1"


def test_the_approval_screen_is_told_what_was_not_measured():
    """AI-L-06 은 "검증된 적용 범위와 미검증 범위" 를 함께 요구한다."""
    desk = _desk()
    version = desk.train(desk.groups()[0]["group_key"], actor="dev-1",
                         reason="r")["candidate"]["version"]
    desk.validate(version, actor="dev-1", reason="쟀다",
                  gate=EvaluationGate(min_new_accuracy=0.0))

    info = desk.approval_info(version)

    assert info["eligible"] is True
    assert "unmeasured_labels" in info and "lost_labels" in info
    assert info["why_trained"] == "r"


def test_a_candidate_that_never_passed_validation_is_not_offered_for_approval():
    desk = _desk()
    version = desk.train(desk.groups()[0]["group_key"], actor="dev-1",
                         reason="r")["candidate"]["version"]

    assert desk.approval_info(version)["eligible"] is False


def test_training_and_validation_require_an_actor_and_a_reason():
    desk = _desk()
    token = desk.groups()[0]["group_key"]

    for call in (lambda: desk.train(token, actor="", reason="r"),
                 lambda: desk.train(token, actor="dev-1", reason="")):
        with pytest.raises(ValueError, match="actor_and_reason_required"):
            call()


# ---------------------------------------------------------------------------
# 4. 모델 교체 — 조건으로 고르고, 범위를 한 칸씩 넓힌다
# ---------------------------------------------------------------------------

PI6 = DeviceProfile("pi6", frozenset({"compute.cpu", "tier.fixed_camera"}),
                    frozenset(), 7900.0)
EDGE = DeviceProfile("edge-dev", frozenset({"compute.cpu", "compute.gpu", "tier.edge"}),
                     frozenset({"resolution.1920x1080"}), 4096.0)
CLASSIFY = MissionRequirement("m-door", "perception.classify",
                              min_quality=0.7, max_latency_ms=500.0)


def _versions():
    return D.model_versions_from_dict(
        json.loads(MODEL_REGISTRY.read_text(encoding="utf-8")))


def _model_desk():
    return D.ModelDesk(pipeline=D.local_pipeline(versions=_versions()),
                       device_profiles={"pi6": PI6, "edge-dev": EDGE})


#: 품질·지연 조건을 걸지 않은 요청. 승격된 학습 버전의 품질은 보류 집합에서 **실제로
#: 잰** 값이고(상자 좌표 특징의 성질상 낮다 — `TrainingDesk` docstring), 그 수치를
#: 넘기려고 요구를 느슨하게 두는 것이 아니라 이 묶음이 보는 것이 신원이기 때문이다.
CLASSIFY_LOOSE = MissionRequirement("m-door", "perception.classify")


def _approved_candidate(device_id="pi6"):
    """학습 → 검증 → 승인까지 끌고 간 후보 하나. 콘솔이 지나는 순서 그대로다."""
    conditions = InputConditions(
        device_id=device_id, camera_id=device_id,
        extra=(("candidate_reason", "ground_truth:added"),))
    store, lineages = _store(conditions=conditions)
    training = D.TrainingDesk(store=store, sample_lineages=lineages)
    version = training.train(training.groups()[0]["group_key"], actor="dev-1",
                             reason="문과 사람이 반복해서 뒤바뀐다")["candidate"]["version"]
    training.validate(version, actor="dev-1", reason="보류 집합에서 쟀다",
                      gate=EvaluationGate(min_new_accuracy=0.0))
    training.request_approval(version, actor="dev-1", reason="승인 요청")
    training.approve(version, actor="jny", reason="현장 반영을 승인한다")
    return training.candidate(version)


def _promoted(desk, *, device_id="pi6", capability_kind="perception.classify",
              model_id="door-detector"):
    """승인된 후보를 배정 목록에 올린다. 지연·메모리는 **쟀다고 치지 않고** 넘긴다."""
    candidate = _approved_candidate(device_id)
    out = desk.register_learned(candidate, model_id=model_id,
                                capability_kind=capability_kind, device_id=device_id,
                                actor="jny", reason="배정 목록에 올린다",
                                measured_latency_ms=120.0, measured_memory_mb=1200.0)
    assert out["registered"] is True, out
    return candidate, out["version_reference"]


def test_a_new_model_version_is_a_line_in_a_declaration_file():
    """새 모델 추가가 코드 변경이 아니라는 것은 선언 파일이 읽히는지로 고정한다."""
    versions = _versions()

    assert len(versions) >= 4
    assert all(isinstance(v, ModelVersion) for v in versions)
    # 미측정 항목은 None 으로 남는다 — 0 으로 메우지 않는다(AI-B-01). 세 칸
    # (quality·latency·memory) 어느 쪽이 비어도 미측정이다: 실측 보고가 지연과
    # 메모리는 남겼지만 품질 지표는 남기지 않은 버전이 실제로 있다
    # (unidepth@v2-vitb14-edge — internal/reports/2026-09-18_1600). 그 줄을
    # "지연이 있으니 측정됐다"로 읽으면 품질 조건이 있는 임무에 배정된다.
    unmeasured = [v for v in versions if not v.fully_measured]
    assert unmeasured and all(None in (v.quality, v.latency_ms, v.memory_mb)
                              for v in unmeasured)


def test_a_version_outside_its_verified_hardware_scope_is_not_a_candidate():
    rows = {r["reference"]: r for r in _model_desk().eligibility("pi6", CLASSIFY)}

    assert rows["clip-dictionary@vit-b32"]["eligible"] is True
    assert rows["clip-dictionary@vit-b32-cuda"]["reason"] == "outside_verified_hardware_scope"


def test_a_version_whose_cost_was_never_measured_is_not_a_candidate():
    rows = {r["reference"]: r for r in _model_desk().eligibility("pi6", CLASSIFY)}

    assert rows["clip-dictionary@vit-b32-site-tuned"]["reason"] == \
        "unmeasured_profile_not_eligible"


def test_the_same_eligibility_rule_answers_the_screen_and_the_assignment():
    """화면이 "쓸 수 있다"고 보여 준 것이 적용에서 거절되면 안 된다 — 같은 판정이다."""
    desk = _model_desk()
    _candidate, reference = _promoted(desk)
    allowed = {r["reference"] for r in desk.eligibility("pi6", CLASSIFY_LOOSE)
               if r["eligible"]}

    chosen = desk.plan("pi6", CLASSIFY_LOOSE,
                       deployable=D.deployable_for("perception.classify", "pi6"),
                       version_reference=reference)["assignment"]["assigned"]["reference"]

    assert chosen == reference
    assert chosen in allowed


def test_a_promoted_version_still_passes_the_same_hardware_check():
    """승인은 "이 기기에서 쓸 수 있다" 가 아니다 — 검증 범위는 따로 본다(AI-L-10)."""
    desk = D.ModelDesk(pipeline=D.local_pipeline(versions=_versions()),
                       device_profiles={"pi6": PI6, "edge-dev": EDGE})
    _candidate, reference = _promoted(desk, device_id="edge-dev")   # GPU 태그로 검증됐다

    out = desk.apply("pi6", CLASSIFY_LOOSE,
                     deployable=D.deployable_for("perception.classify", "pi6"),
                     version_reference=reference, actor="jny",
                     reason="엣지에서 검증한 것을 고정 카메라에 올려 본다")

    assert out["applied"] is False
    assert out["reason"] == "outside_verified_hardware_scope"
    assert desk.deployments() == []          # 거절은 아무것도 올리지 않는다


def test_naming_a_version_that_is_not_declared_is_refused():
    out = _model_desk().apply(
        "pi6", CLASSIFY, deployable=D.deployable_for("perception.classify", "pi6"),
        version_reference="made-up@1", actor="jny", reason="없는 버전")

    assert out["reason"] == D.REFUSE_UNKNOWN_VERSION


def test_a_declared_version_with_no_promotion_record_cannot_be_applied():
    """선언 파일의 버전에는 **그것을 허가한 계보가 없다.** 그런 버전을 올릴 길을
    열어 두면 검증·승인 관문이 선택 사항이 되고, 전에는 바로 그 길이 열려 있었다 —
    다른 후보의 계보를 들고 이 버전을 올릴 수 있었다(AI-L-07, AI-L-08).

    오타("없는 버전")와 **구분되는** 사유로 거절한다. 둘을 한 사유로 합치면 운영자가
    무엇을 해야 하는지 알 수 없다.
    """
    out = _model_desk().apply(
        "edge-dev", MissionRequirement("m-ovd", "perception.detect_ovd"),
        deployable=D.deployable_for("perception.detect_ovd", "edge-dev"),
        version_reference="yolo-world@v2-s", actor="jny", reason="손으로 적은 버전")

    assert out["applied"] is False
    assert out["reason"] == D.REFUSE_NOT_PROMOTED


def test_the_version_that_goes_up_is_the_one_the_lineage_approved():
    """메운 구멍 그 자체. 올라간 버전의 신원에 **그 후보의 버전 문자열**이 있다."""
    desk = _model_desk()
    candidate, reference = _promoted(desk)

    out = desk.apply("pi6", CLASSIFY_LOOSE,
                     deployable=D.deployable_for("perception.classify", "pi6"),
                     version_reference=reference, actor="jny", reason="현장 반영")

    assert out["applied"] is True
    assert out["status"]["version_reference"] == reference
    assert candidate.version in reference
    assert out["candidate_version"] == candidate.version
    # 계보도 그 후보의 것이다 — 적용이 전진시킨 것이 그 계보다.
    assert candidate.lineage.state is LearningState.DEPLOYED
    assert candidate.lineage.cites(candidate.version)


def test_a_lineage_that_never_cited_the_candidate_cannot_approve_it():
    """구멍의 모양: **따로 넘어온 짝**. 승인은 사람의 행위라서, 어긋난 계보를
    붙이면 운영자가 보지도 않은 물건을 그 사람이 승인한 것으로 기록된다(AI-L-06).

    승격이 그 짝을 거절하므로 어긋난 계보는 애초에 등록부에 들어가지 못한다.
    """
    from mission_runtime.runtime.learned_version import REASON_LINEAGE_MISMATCH

    desk = _model_desk()
    mine = _approved_candidate("pi6")
    stranger = _approved_candidate("edge-dev")
    # 같은 재료로 학습하면 버전 문자열도 같다(내용에서 파생한다) — 그때는 계보가
    # 같은 것을 가리키므로 어긋남이 아니다. 어긋남을 보려면 **다른 후보**여야 한다.
    assert stranger.version != mine.version
    # 다른 후보의 계보를 이 후보에 붙인다 — 전에는 이것이 통과했다.
    forged = D.TrainedCandidate(
        parameters=mine.parameters, group_key=mine.group_key,
        conditions=mine.conditions, lineage=stranger.lineage,
        used_sample_ids=mine.used_sample_ids,
        held_out_sample_ids=mine.held_out_sample_ids, report=mine.report)

    out = desk.register_learned(forged, model_id="door-detector",
                                capability_kind="perception.classify",
                                device_id="pi6", actor="jny", reason="어긋난 짝")

    assert out["registered"] is False
    assert out["reason"].startswith(REASON_LINEAGE_MISMATCH)
    assert desk.promotions() == []


def test_the_apply_call_has_no_second_place_to_put_an_identity():
    """구조로 막은 자리를 구조로 고정한다.

    `lineage` 와 `pinned_reference` 를 **따로** 받는 동안은 어떤 검사를 넣어도
    "계보 A, 버전 B" 라는 요청을 *표현할 수 있었다*. 지금은 신원을 넣는 칸이 하나뿐
    이고 계보는 그 버전의 승격 기록에서 유도된다 — 어긋난 짝은 표현되지 않는다.
    """
    import inspect

    names = set(inspect.signature(D.ModelDesk.apply).parameters)

    assert "version_reference" in names
    assert "lineage" not in names and "pinned_reference" not in names
    assert "lineage" not in set(inspect.signature(D.ModelDesk.plan).parameters)


def test_a_candidate_that_was_never_approved_is_not_registered():
    """승인 전 후보는 배정 목록에 올라가지 않는다 — 올라가면 적용할 수 있게 된다."""
    from mission_runtime.runtime.learned_version import REASON_NOT_APPROVED

    desk = _model_desk()
    conditions = InputConditions(device_id="pi6", camera_id="pi6")
    store, lineages = _store(conditions=conditions)
    training = D.TrainingDesk(store=store, sample_lineages=lineages)
    version = training.train(training.groups()[0]["group_key"], actor="dev-1",
                             reason="r")["candidate"]["version"]

    out = desk.register_learned(training.candidate(version), model_id="door-detector",
                                capability_kind="perception.classify", device_id="pi6",
                                actor="jny", reason="승인 전에 올려 본다")

    assert out["registered"] is False
    assert out["reason"].startswith(REASON_NOT_APPROVED)


def test_a_candidate_with_no_report_has_nothing_to_promote():
    """검증을 돌리지 않은 것은 통과가 아니다(AI-L-05) — 성적표 없는 승격은 거절이다."""
    from mission_runtime.runtime.learned_version import REASON_NOT_EVALUATED

    desk = _model_desk()
    candidate = _approved_candidate("pi6")
    stripped = D.TrainedCandidate(
        parameters=candidate.parameters, group_key=candidate.group_key,
        conditions=candidate.conditions, lineage=candidate.lineage,
        used_sample_ids=candidate.used_sample_ids,
        held_out_sample_ids=candidate.held_out_sample_ids, report=None)

    out = desk.register_learned(stripped, model_id="door-detector",
                                capability_kind="perception.classify",
                                device_id="pi6", actor="jny", reason="성적표 없이")

    assert out["registered"] is False
    assert out["reason"] == REASON_NOT_EVALUATED


def test_the_unit_may_not_target_a_device_other_than_the_one_judged():
    """적격은 `device_id` 의 하드웨어로 보고 제어면에는 `deployable` 의 기기가 간다.
    둘을 따로 받으므로 어긋날 수 있고, 어긋나면 A 의 태그로 적격을 받은 버전이
    B 에서 돈다(같은 모양의 또 한 자리)."""
    desk = D.ModelDesk(pipeline=D.local_pipeline(versions=_versions()),
                       device_profiles={"pi6": PI6, "edge-dev": EDGE})
    _candidate, reference = _promoted(desk)

    out = desk.apply("pi6", CLASSIFY_LOOSE,
                     deployable=D.deployable_for("perception.classify", "edge-dev"),
                     version_reference=reference, actor="jny", reason="다른 기기의 단위")

    assert out["applied"] is False
    assert out["reason"] == f"{D.REFUSE_DEPLOYABLE_OTHER_DEVICE}:edge-dev"


def test_the_promotion_list_puts_the_version_and_its_lineage_in_one_row():
    """화면이 여기서 고르면 계보를 따로 들고 올 이유가 없어진다 — 따로 들고 오는
    길이 바로 어긋난 짝의 자리였다(AI-L-08). 미검증 범위도 같은 줄에 있다(AI-L-06)."""
    desk = _model_desk()
    candidate, reference = _promoted(desk)

    (row,) = desk.promotions()

    assert row["version_reference"] == reference
    assert row["candidate_version"] == candidate.version
    assert row["learning_lineage_id"] == candidate.lineage.lineage_id
    assert row["learning_state"] == LearningState.APPROVED.value
    # 해상도를 모르는 후보는 "조건 무관"이 아니라 **모르는 것**이다.
    assert "resolution_unknown" in row["unverified_scope"]
    assert row["sample_ids"] == list(candidate.parameters.sample_ids)


def test_applying_starts_in_verification_and_widens_one_step_at_a_time():
    """AI-L-07: 승인된 것이 곧 전체 운영 적용은 아니다."""
    desk = _model_desk()
    _candidate, reference = _promoted(desk)
    applied = desk.apply("pi6", CLASSIFY_LOOSE,
                         deployable=D.deployable_for("perception.classify", "pi6"),
                         version_reference=reference, actor="jny", reason="현장 반영")
    deployment_id = applied["status"]["deployment_id"]

    assert applied["status"]["scope"] == PromotionScope.VERIFICATION.value
    assert applied["status"]["next_scope"] == PromotionScope.LIMITED.value

    first = desk.widen(deployment_id, actor="jny", reason="검증 통과")
    assert first["status"]["scope"] == PromotionScope.LIMITED.value

    held = desk.widen(deployment_id, actor="jny", reason="아직", verification_met=False)
    assert held["status"]["scope"] == PromotionScope.LIMITED.value
    assert held["status"]["reason"] == "operational_verification_not_met"

    full = desk.widen(deployment_id, actor="jny", reason="회귀 없음")
    assert full["status"]["scope"] == PromotionScope.OPERATIONAL.value
    assert full["status"]["next_scope"] is None


def test_the_widening_order_has_exactly_one_owner():
    """화면이 "다음 범위" 를 적으려면 이 순서를 알아야 한다 — 표를 따로 들면
    건너뛰기 금지가 두 곳에 적히고 한쪽만 바뀐다."""
    assert next_scope(PromotionScope.VERIFICATION) is PromotionScope.LIMITED
    assert next_scope(PromotionScope.LIMITED) is PromotionScope.OPERATIONAL
    assert next_scope(PromotionScope.OPERATIONAL) is None


def test_rolling_back_with_nothing_to_return_to_says_so():
    """"검증된 상태로 복구됐다" 와 "그냥 없어졌다" 는 운영자에게 다른 사실이다."""
    desk = _model_desk()
    _candidate, reference = _promoted(desk)
    applied = desk.apply("pi6", CLASSIFY_LOOSE,
                         deployable=D.deployable_for("perception.classify", "pi6"),
                         version_reference=reference, actor="jny", reason="현장 반영")

    out = desk.rollback(applied["status"]["deployment_id"], actor="jny",
                        reason="지연이 늘었다")

    assert out["status"]["phase"] == "WITHDRAWN"
    assert "no_last_known_good_version" in out["status"]["reason"]


def test_an_already_deployed_lineage_is_not_deployed_again():
    desk = _model_desk()
    _candidate, reference = _promoted(desk)
    deployable = D.deployable_for("perception.classify", "pi6")
    desk.apply("pi6", CLASSIFY_LOOSE, deployable=deployable,
               version_reference=reference, actor="jny", reason="처음")

    again = desk.apply("pi6", CLASSIFY_LOOSE, deployable=deployable,
                       version_reference=reference, actor="jny", reason="또")

    assert again["applied"] is False


def test_a_device_profile_is_carried_from_the_fleet_not_measured_again(service):
    """자원은 이미 해소된 사실이다 — 이 책상이 다시 재지 않는다."""
    rows = {d["device_id"]: d for d in service.models().devices()}

    assert rows["pi6"]["hw_tags"] == sorted(service.fleet.facts["pi6"].tags)
    assert rows["pi6"]["memory_mb"] == service.fleet.facts["pi6"].memory_mb


# ---------------------------------------------------------------------------
# 5. 경로와 권한 — 조회와 제어가 섞이지 않는다
# ---------------------------------------------------------------------------

#: 바꾸는 경로와 그 일에 필요한 능력. 한 묶음으로 두면 라벨 작업자에게 모델 교체
#: 권한이, 운영자에게 학습 실행 권한이 함께 간다.
WRITE_PERMISSIONS = {
    "/api/join": PERM_ONBOARD,
    "/api/join-step": PERM_ONBOARD,
    "/api/camera-info": PERM_CALIBRATE,
    "/api/training": PERM_TRAIN,
    "/api/model": PERM_DEPLOY_MODEL,
}


@pytest.mark.parametrize("path,permission", sorted(WRITE_PERMISSIONS.items()))
def test_each_deployment_write_requires_its_own_capability(path, permission):
    assert console._POST_PERMISSIONS[path] == permission


def test_the_four_deployment_reads_are_not_the_paths_that_change_anything():
    reads = {"/api/deployment", "/api/calibration", "/api/approval"}

    assert reads <= set(console._ROUTES_GET)
    assert not reads & set(console._ROUTES_POST)
    assert set(WRITE_PERMISSIONS) <= set(console._ROUTES_POST)


def test_the_snapshot_names_the_capability_a_locked_section_needs(service):
    """권한 없는 구역은 빈 목록이 아니라 **무엇이 필요한가**를 적는다 — 빈 목록은
    "할 일이 없다" 와 "볼 수 없다" 를 구분하지 못한다(AI-O-06)."""
    body = service.deployment_view(caller=Caller.for_role("viewer"))

    assert body["permissions"] == {
        "join": PERM_ONBOARD, "calibration": PERM_CALIBRATE,
        "training": PERM_TRAIN, "model": PERM_DEPLOY_MODEL}
    assert body["training"]["may_submit"] is False
    assert body["model"]["may_submit"] is False
    assert body["join"]["may_submit"] is False


def test_the_snapshot_is_one_call_covering_all_four_jobs(service):
    body = service.deployment_view(caller=_admin())

    assert set(body) == {"permissions", "join", "calibration", "training", "model"}
    assert body["model"]["versions"], "선언된 모델 버전이 비었다"
    assert body["calibration"]["min_views"] == D.MIN_CALIBRATION_VIEWS


@pytest.mark.parametrize("path,body", [
    ("join_device", dict(GOOD_JOIN)),
    ("submit_camera_info", {**DECLARED}),
    ("run_training", {"step": "train", "group_key": "x"}),
    ("manage_model", {"step": "approve", "version": "x"}),
])
def test_every_deployment_write_refuses_without_a_reason(service, path, body):
    """사유 없는 변경은 되짚을 수 없다 — 다섯 경로 전부 같은 규칙이다(AI-L-03)."""
    without = {k: v for k, v in body.items() if k != "reason"}

    with pytest.raises(console.ApiError) as raised:
        getattr(service, path)(caller=_admin(), body=without)

    assert raised.value.reason == "reason_required"


def test_camera_info_without_an_image_size_is_a_bad_request(service):
    with pytest.raises(console.ApiError) as raised:
        service.submit_camera_info(caller=_admin(),
                                   body={"device_id": "pi6", "reason": "해상도 없음"})

    assert raised.value.reason.startswith("bad_camera_info:")


def test_an_unknown_training_step_is_refused_by_name(service):
    with pytest.raises(console.ApiError) as raised:
        service.run_training(caller=_admin(), body={"step": "학습해줘", "reason": "r"})

    assert raised.value.reason == "unknown_step:학습해줘"


def test_declaring_camera_info_is_recorded_in_the_operator_ledger(service):
    service.submit_camera_info(caller=_admin(),
                               body={**DECLARED, "reason": "제원표 입력"})

    entries = service.overlay.entries("calibration", "pi6")

    assert len(entries) == 1
    assert entries[0].actor == _admin().actor
    assert entries[0].payload["verdict"] == D.CALIB_NOT_MEASURED


# ---------------------------------------------------------------------------
# 6. 라벨 출처 — 외부 데이터셋이 기기 후보를 오염시키지 않는다
# ---------------------------------------------------------------------------


def test_the_console_serves_every_declared_source_with_its_provenance(service):
    body = service.label_tasks(None, caller=_admin())

    declared = {s["source_id"] for s in body["sources"]}
    assert "pi4-20260910-sampled" in declared
    assert body["selected"] in declared
    for row in body["sources"]:
        assert "license" in row and "origin" in row
        # 공개 데이터셋은 우리 기기를 주장하지 않는다.
        if row["kind"] == "external_dataset":
            assert row["device_id"] is None
            assert row["subject_id"].startswith("dataset:")


def test_ground_truth_from_a_dataset_is_not_filed_under_a_device(service, tmp_path):
    """이것이 요점이다 — 공개 데이터셋 사진을 라벨했는데 그 후보가 "pi4 가 본 것"
    으로 적히면, 그 가중치가 어느 기기에서 나빠졌는지 되짚을 수 없다(AI-L-09)."""
    from labeling import LabelSource, SOURCE_EXTERNAL_DATASET, FrameLabelSource

    root = tmp_path / "public"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.png").write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000a49444154789c63000100000500010d0a2db4"
        "0000000049454e44ae426082"))
    # 선언 파일을 건드리지 않고 이 서비스에만 출처를 하나 더 붙인다.
    service._label_sources = tuple(service.label_sources()) + (
        LabelSource(source_id="unit-public", kind=SOURCE_EXTERNAL_DATASET,
                    path="unused"),)
    service._labels["unit-public"] = FrameLabelSource(
        frame_root=root, source=service._label_sources[-1])

    body = service.submit_labels(caller=_admin(), body={
        "source": "unit-public", "frame": "a.png",
        "boxes": [{"box_id": "h1", "box": [0.1, 0.2, 0.4, 0.6],
                   "semantic_class": "door"}],
        "reason": "모델이 문을 놓쳤다"})

    assert body["device_id"] == "dataset:unit-public"
    filed = service.twin().learning_candidates().human_confirmed
    assert [c.device_id for c in filed] == ["dataset:unit-public"]
    groups = {g["device_id"] for g in service.training().groups()}
    assert groups == {"dataset:unit-public"}


def test_media_refuses_a_frame_name_that_leaves_its_source(service):
    for name in ("../../../etc/passwd", "/etc/passwd", "a/../../x.jpg"):
        with pytest.raises(console.ApiError) as raised:
            service.media_bytes(kind="frame", sample_class="pi4-20260910-sampled",
                                sample_file=name)
        if raised.value.reason == "no_frame_assets":
            # 프레임 출처(자산 뿌리)가 없는 노드에서는 경로 이탈 검사에 **닿기
            # 전에** 503 으로 막힌다. 그 거절이 올바른 축소이고(AI-C-05) 라벨
            # 미디어 경로만 비활성이다 — 이탈 거절 자체는 출처가 있어야 볼 수 있다.
            pytest.skip(
                "프레임 출처가 이 노드에 없다(자산 뿌리 미설치) — 라벨 미디어 "
                "경로만 비활성이고 나머지 배포 탭은 그대로 돈다. "
                "MISSION_RUNTIME_ASSETS 로 자산 뿌리를 가리키면 이 시험이 돈다"
            )
        assert raised.value.reason.startswith("bad_frame:"), name


def test_an_unknown_source_is_a_404_not_a_silent_fallback(service):
    """모르는 출처를 조용히 첫 번째로 바꾸면, 화면은 다른 데이터를 보면서 고른
    출처를 보고 있다고 믿는다."""
    with pytest.raises(console.ApiError) as raised:
        service.label_tasks("없는출처", caller=_admin())

    assert raised.value.reason == "unknown_label_source"
