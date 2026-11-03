"""사람이 만든 정답이 모델 출력과 섞이지 않는지.

implements: AI-L-02, AI-L-03
관련: AI-L-01, AI-C-08
tests: 미검수 상자는 정답이 아니다 / 고친 것만 후보가 된다 / 픽셀은 오지 않는다

여기서 고정하려는 것은 좌표 산수가 아니라 **경계**다. 검수하지 않은 모델 출력이
정답으로 승격되면 AI-L-02 가 금지한 일이 그대로 일어나므로, 그 문이 닫혀 있는지를
판정·GT 집계·학습 후보 선별 세 층에서 각각 확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "fms_console"))

from labeling import (  # noqa: E402
    CORRECTING_VERDICTS,
    GROUND_TRUTH_VERDICTS,
    BoxVerdict,
    FrameLabelSource,
    GroundTruthRecord,
    LabelingError,
    LabeledBox,
    PredictedBox,
    centre_shift,
    iou,
    labeled_box_from_dict,
)

AUTHOR = "demo:labeler"


def _predicted(box=(0.5, 0.2, 0.6, 0.6), semantic_class="person", range_m=6.0):
    return PredictedBox(box_id="p0", box=box, semantic_class=semantic_class,
                        confidence=0.88, range_m=range_m)


def _from(raw, predicted=None):
    source = {"p0": predicted or _predicted()}
    return labeled_box_from_dict(raw, predicted=source, author=AUTHOR, clock=lambda: 100.0)


# -- 좌표는 정규화된 영상 좌표다 ------------------------------------------


@pytest.mark.parametrize("box", [
    (0.1, 0.1, 1.4, 0.5),      # 1 을 넘는다
    (-0.1, 0.1, 0.5, 0.5),     # 음수
    (0.6, 0.1, 0.5, 0.5),      # x2 <= x1
    (0.1, 0.5, 0.5, 0.5),      # y2 <= y1
])
def test_a_box_outside_normalised_coordinates_is_refused(box):
    """픽셀 좌표를 그대로 보내면 여기서 막힌다 — 해상도가 바뀌면 전부 틀리므로."""
    with pytest.raises(LabelingError):
        _from({"box_id": "p0", "box": list(box)})


def test_the_task_carries_a_frame_reference_and_never_pixels(tmp_path):
    """AI-C-08: 상태 계약에 픽셀을 싣지 않는다. 프레임은 참조로만 간다."""
    (tmp_path / "frame_000001.jpg").write_bytes(b"\xff\xd8\xff")
    source = FrameLabelSource(frame_root=tmp_path, device_id="pi4", zone_id="z1")
    task = source.task("frame_000001.jpg", media_ref={"path": "/api/media"})
    payload = task.as_dict()
    blob = repr(payload)
    assert payload["frame_ref"] == "pi4/frame_000001.jpg"
    assert "data:image" not in blob and "base64" not in blob


# -- 판정: 서버가 정하고 클라이언트가 정하지 않는다 ------------------------


def test_the_client_cannot_declare_its_own_verdict():
    """"confirmed" 라고 적어 보내면서 좌표를 바꿔 놓으면 고친 사실이 사라진다."""
    box = _from({"box_id": "p0", "verdict": "confirmed", "box": [0.1, 0.1, 0.2, 0.3]})
    assert box.verdict is BoxVerdict.ADJUSTED


def test_an_untouched_box_is_confirmed_not_unreviewed():
    box = _from({"box_id": "p0"})
    assert box.verdict is BoxVerdict.CONFIRMED


def test_changing_the_class_outranks_moving_the_box():
    """둘 다 바뀌면 class 변경으로 적되 **고친 좌표는 버리지 않는다**."""
    box = _from({"box_id": "p0", "box": [0.52, 0.21, 0.63, 0.62],
                 "semantic_class": "maintenance_worker"})
    assert box.verdict is BoxVerdict.RELABELED
    assert box.final_box == (0.52, 0.21, 0.63, 0.62)
    assert box.final_class == "maintenance_worker"


def test_correcting_only_the_distance_still_counts_as_a_correction():
    """거리만 고친 것을 `confirmed` 로 적으면 그 수정이 학습 후보에서 사라진다."""
    box = _from({"box_id": "p0", "range_m": 9.5})
    assert box.verdict is BoxVerdict.ADJUSTED
    assert box.verdict in CORRECTING_VERDICTS
    assert box.disagreement()["range_error_m"] == 3.5


def test_resubmitting_the_same_distance_is_not_a_correction():
    box = _from({"box_id": "p0", "range_m": 6.0})
    assert box.verdict is BoxVerdict.CONFIRMED


def test_a_rejected_box_has_no_final_box_and_that_is_the_answer():
    box = _from({"box_id": "p0", "rejected": True, "note": "벽 무늬"})
    assert box.verdict is BoxVerdict.REJECTED
    assert box.final_box is None and box.final_class is None
    assert box.disagreement() == {"kind": "model_saw_nothing_there"}


def test_rejecting_a_box_the_model_never_produced_is_refused():
    with pytest.raises(LabelingError):
        _from({"box_id": "ghost", "rejected": True})


def test_a_box_the_model_missed_is_added_and_needs_coordinates():
    added = labeled_box_from_dict(
        {"box_id": "new1", "box": [0.8, 0.3, 0.92, 0.72], "semantic_class": "trash bag"},
        predicted={}, author=AUTHOR, clock=lambda: 100.0)
    assert added.verdict is BoxVerdict.ADDED
    assert added.disagreement() == {"kind": "model_missed_it"}
    with pytest.raises(LabelingError):
        labeled_box_from_dict({"box_id": "new2", "semantic_class": "box"},
                              predicted={}, author=AUTHOR, clock=lambda: 100.0)


def test_ground_truth_without_an_author_is_refused():
    """누가 정답이라 했는지 없으면 되짚을 수 없다(AI-L-03)."""
    with pytest.raises(LabelingError):
        LabeledBox(box_id="p0", verdict=BoxVerdict.CONFIRMED, predicted=_predicted())


# -- 미검수는 정답이 아니다 -------------------------------------------------


def test_unreviewed_is_the_only_verdict_outside_ground_truth():
    assert BoxVerdict.UNREVIEWED not in GROUND_TRUTH_VERDICTS
    assert GROUND_TRUTH_VERDICTS == frozenset(set(BoxVerdict) - {BoxVerdict.UNREVIEWED})


def test_confirmed_is_ground_truth_but_not_a_correction():
    """모델이 맞힌 것은 정답이되 학습 후보가 아니다 — 넣으면 후보가 스트림이 된다."""
    assert BoxVerdict.CONFIRMED in GROUND_TRUTH_VERDICTS
    assert BoxVerdict.CONFIRMED not in CORRECTING_VERDICTS


def test_a_half_reviewed_frame_does_not_look_finished():
    reviewed = _from({"box_id": "p0", "semantic_class": "robot"})
    untouched = LabeledBox(box_id="p1", verdict=BoxVerdict.UNREVIEWED,
                           predicted=PredictedBox(box_id="p1", box=(0.1, 0.1, 0.2, 0.2),
                                                  semantic_class="box", confidence=0.2))
    record = GroundTruthRecord(task_id="t", frame_ref="pi4/f.jpg", device_id="pi4",
                               boxes=(reviewed, untouched), submitted_by=AUTHOR,
                               submitted_at=100.0)
    summary = record.summary()
    assert summary["box_count"] == 2
    assert summary["reviewed_count"] == 1
    assert summary["unreviewed_count"] == 1
    assert record.corrections == (reviewed,)


# -- 불일치의 크기 ---------------------------------------------------------


def test_iou_and_centre_shift_are_zero_and_identity_at_the_edges():
    box = (0.2, 0.2, 0.4, 0.4)
    assert iou(box, box) == pytest.approx(1.0)
    assert centre_shift(box, box) == pytest.approx(0.0)
    assert iou(box, (0.6, 0.6, 0.8, 0.8)) == pytest.approx(0.0)


def test_disagreement_reports_how_far_the_model_was():
    box = _from({"box_id": "p0", "box": [0.53, 0.20, 0.67, 0.66],
                 "semantic_class": "maintenance_worker", "range_m": 5.4})
    body = box.disagreement()
    assert body["kind"] == "compared"
    assert 0.0 < body["iou"] < 1.0
    assert body["class_changed"] is True
    assert body["range_error_m"] == pytest.approx(-0.6)


# -- 추론 제공자가 없는 배치 -----------------------------------------------


def test_a_missing_detector_is_an_empty_task_not_a_failure(tmp_path):
    """추론 provider 가 없으면 사람이 처음부터 그린다 — 선택 기능 결손이다(AI-C-05)."""
    (tmp_path / "frame_000001.jpg").write_bytes(b"\xff\xd8\xff")
    source = FrameLabelSource(frame_root=tmp_path, device_id="pi4", zone_id="z1")
    task = source.task("frame_000001.jpg", media_ref={})
    assert task.predicted == ()
    assert source.detector_reason == "no_detector_available"


def test_an_install_without_frames_offers_no_work_instead_of_crashing():
    """자산 없이 설치한 배치에서도 콘솔은 돈다 — 라벨 기능만 빈다(AI-C-05)."""
    source = FrameLabelSource(frame_root=None, device_id="pi4", zone_id="z1")
    assert source.frames() == ()
    with pytest.raises(LabelingError):
        source.task("frame_000001.jpg", media_ref={})


# ---------------------------------------------------------------------------
# 출처 — 프레임이 아니라 **어디서 온 데이터인가**가 작업 단위다
# ---------------------------------------------------------------------------

from labeling import (  # noqa: E402
    DATASET_SUBJECT_PREFIX,
    MAX_LISTED_FRAMES,
    SOURCE_DEVICE_CAPTURE,
    SOURCE_EXTERNAL_DATASET,
    SOURCE_MISSION_CAPTURE,
    LabelSource,
    label_sources_from_dict,
    resolve_frame,
)

PROJECT_DIR = Path(__file__).resolve().parents[1]
DECLARED_SOURCES = PROJECT_DIR / "config" / "label_sources.example.json"


def _png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 1x1 PNG. 내용은 중요하지 않고 **확장자와 자리**가 중요하다.
    path.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"))


def test_an_external_dataset_must_not_claim_one_of_our_devices():
    """공개 데이터셋에 기기를 달면 그 사진이 우리 기기가 본 것이 된다 — 그 거짓이
    학습 후보의 조건에 그대로 실린다(AI-L-09 는 기기별 구분을 요구한다)."""
    with pytest.raises(LabelingError, match="must not claim a device_id"):
        LabelSource(source_id="public", kind=SOURCE_EXTERNAL_DATASET,
                    path="datasets/public", device_id="pi4")


def test_a_capture_without_a_device_is_refused():
    """우리가 찍었다고 적어 놓고 어느 기기인지 비우면 되짚을 입구가 없다."""
    with pytest.raises(LabelingError, match="needs a device_id"):
        LabelSource(source_id="ours", kind=SOURCE_DEVICE_CAPTURE, path="datasets/ours")


def test_the_subject_of_a_dataset_is_the_dataset_itself():
    source = LabelSource(source_id="uavvaste", kind=SOURCE_EXTERNAL_DATASET,
                         path="datasets/uavvaste/images")

    assert source.subject_id == f"{DATASET_SUBJECT_PREFIX}uavvaste"
    assert source.from_our_device is False


def test_an_unknown_source_kind_is_refused_by_name():
    with pytest.raises(LabelingError, match="unknown label source kind"):
        LabelSource(source_id="x", kind="그냥사진", path="datasets/x")


def test_two_sources_may_not_share_an_id():
    with pytest.raises(LabelingError, match="duplicate label source id"):
        label_sources_from_dict({"sources": [
            {"source_id": "a", "kind": SOURCE_EXTERNAL_DATASET, "path": "p"},
            {"source_id": "a", "kind": SOURCE_EXTERNAL_DATASET, "path": "q"},
        ]})


def test_the_shipped_source_declaration_is_readable_and_consistent():
    """새 출처가 코드 변경이 아니라는 것은 선언 파일이 읽히는지로 고정한다."""
    import json

    sources = label_sources_from_dict(
        json.loads(DECLARED_SOURCES.read_text(encoding="utf-8")))

    assert len(sources) >= 5
    by_kind = {}
    for source in sources:
        by_kind.setdefault(source.kind, []).append(source)
    assert set(by_kind) == {SOURCE_DEVICE_CAPTURE, SOURCE_MISSION_CAPTURE,
                            SOURCE_EXTERNAL_DATASET}
    # 공개 데이터셋은 출처와 라이선스를 적어야 한다 — 모르면 모른다고 적는다.
    for source in by_kind[SOURCE_EXTERNAL_DATASET]:
        assert source.origin, source.source_id
        assert source.license, source.source_id
        if source.license == "unknown":
            assert source.redistributable is not True


def test_frames_from_different_sources_do_not_collide(tmp_path):
    """같은 파일 이름이 두 출처에 있어도 작업 id 가 겹치지 않는다."""
    one = tmp_path / "a"
    two = tmp_path / "b"
    _png(one / "frame_000001.jpg")
    _png(two / "frame_000001.jpg")

    first = FrameLabelSource(frame_root=one, source=LabelSource(
        source_id="ours", kind=SOURCE_DEVICE_CAPTURE, path="a", device_id="pi4"))
    second = FrameLabelSource(frame_root=two, source=LabelSource(
        source_id="theirs", kind=SOURCE_EXTERNAL_DATASET, path="b"))

    a = first.task("frame_000001.jpg", media_ref={})
    b = second.task("frame_000001.jpg", media_ref={})

    assert a.task_id != b.task_id
    assert a.device_id == "pi4"
    assert b.device_id == f"{DATASET_SUBJECT_PREFIX}theirs"
    assert b.source_kind == SOURCE_EXTERNAL_DATASET


def test_a_mission_capture_lists_frames_by_their_path_under_the_source(tmp_path):
    """임무 폴더마다 같은 이름이 있으므로 이름만 내면 한 칸으로 겹친다."""
    root = tmp_path / "missions"
    _png(root / "143715_MSN-01" / "images" / "detect" / "0.jpg")
    _png(root / "143835_MSN-01" / "images" / "detect" / "0.jpg")

    bundle = FrameLabelSource(frame_root=root, source=LabelSource(
        source_id="mission-260915", kind=SOURCE_MISSION_CAPTURE, path="missions",
        device_id="pi7", recursive=True))

    assert bundle.frames() == ("143715_MSN-01/images/detect/0.jpg",
                               "143835_MSN-01/images/detect/0.jpg")
    assert bundle.frame_count() == 2


def test_a_source_that_is_not_recursive_does_not_descend(tmp_path):
    root = tmp_path / "flat"
    _png(root / "a.jpg")
    _png(root / "deeper" / "b.jpg")

    bundle = FrameLabelSource(frame_root=root, source=LabelSource(
        source_id="flat", kind=SOURCE_EXTERNAL_DATASET, path="flat"))

    assert bundle.frames() == ("a.jpg",)


def test_a_long_listing_is_cut_but_the_real_count_is_not(tmp_path):
    """3,000 장을 한 번에 내려보내면 화면이 그것을 그리다 멈춘다. 자르되 **전체 수를
    함께 적어** 자른 사실을 숨기지 않는다."""
    root = tmp_path / "big"
    for index in range(MAX_LISTED_FRAMES + 7):
        _png(root / f"{index:05d}.jpg")

    bundle = FrameLabelSource(frame_root=root, source=LabelSource(
        source_id="big", kind=SOURCE_EXTERNAL_DATASET, path="big"))

    assert len(bundle.frames()) == MAX_LISTED_FRAMES
    assert bundle.frame_count() == MAX_LISTED_FRAMES + 7


@pytest.mark.parametrize("name", [
    "../secret.jpg", "a/../../secret.jpg", "/etc/passwd", "", "./a.jpg",
])
def test_a_frame_name_cannot_leave_its_source(tmp_path, name):
    """하위 디렉터리를 허용하는 순간 `../` 한 번이면 자산 뿌리 밖이 읽힌다."""
    root = tmp_path / "src"
    _png(root / "a.jpg")

    with pytest.raises(LabelingError):
        resolve_frame(root, name)


def test_a_symlink_that_points_outside_its_source_is_refused(tmp_path):
    """이름 규약만으로는 부족하다 — 푼 경로가 실제로 뿌리 아래인지 본다."""
    outside = tmp_path / "outside.jpg"
    _png(outside)
    root = tmp_path / "src"
    root.mkdir(parents=True, exist_ok=True)
    try:
        (root / "link.jpg").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("이 기계에서는 심볼릭 링크를 만들 수 없다")

    with pytest.raises(LabelingError, match="outside its source"):
        resolve_frame(root, "link.jpg")


def test_a_frame_inside_the_source_resolves(tmp_path):
    root = tmp_path / "src"
    _png(root / "deeper" / "a.jpg")

    assert resolve_frame(root, "deeper/a.jpg").is_file()
