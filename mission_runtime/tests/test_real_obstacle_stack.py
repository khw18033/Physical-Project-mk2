"""실제 모델·실제 스캔으로 장애물 접지 체인을 끝까지 돌린다.

합성 데이터로는 드러나지 않는 것을 잡으려고 둔 묶음이다. 실제로 셋을 잡았다.

1. 보정식이 provider·깊이 공간에 묶여 있지 않으면, UniDepth 식이 ZipDepth 역깊이
   출력에 **조용히 적용돼** 1110 개 박스 전부가 12.7~15.0cm 로 뭉개진다
   (2026-09-20 데모 실측, MAE 42.7cm). "바로 앞에 장애물" 이 화면 어디에나 생긴다.
2. crop 오프셋을 빼지 않고 배율만 곱하면 박스가 옮겨져 **다른 물체의 깊이**를 읽는다.
3. 박스 대표 퍼센타일이 고정이면, 근거리가 큰 값인 역깊이에서 p40 은 반대쪽을 고른다.

자산·가중치가 없는 기계에서는 그 묶음만 skip 한다 — 선택 구성요소 결손은 축소다.

implements: AI-E-01, AI-E-02, AI-B-08, AI-S-04, AI-R-02, AI-C-02, AI-C-05
tests: real zero-shot detector on a real scan, real monocular depth, calibration
       binding refusal, declared-vs-measured bearing basis, coverage from the real
       scan, refusal to compare paths without distance
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.conftest import asset_path, demo_asset_path  # noqa: E402

from edge.depth_contract import (  # noqa: E402
    DEPTH_SPACE_AFFINE_INVERSE,
    STATUS_UNMEASURED_NO_FORMULA,
    CalibrationMismatch,
    box_to_depth_pixels,
    measure_distance,
    roi_representative,
)
from edge.zipdepth_provider import ZipDepthProvider  # noqa: E402
from perception.obstacle_evidence import (  # noqa: E402
    BEARING_FROM_DECLARATION,
    Detection,
    ObstacleEvidenceBuilder,
    load_calibration_profiles,
)
from perception.obstacle_taxonomy import STATUS_HYPOTHESIS, ObstacleTaxonomy  # noqa: E402
from planning.path_candidates import (  # noqa: E402
    REASON_TIE_BROKEN_BY_COST,
    choose,
    generate,
    path_lengths,
)
from risk.hazard_field import (  # noqa: E402
    HAZARD_WEIGHTS,
    REASON_COVERAGE_UNKNOWN,
    HazardField,
    ScanCoverage,
    scored_candidates,
)
from risk.scoring import RuleBasedRiskScorer  # noqa: E402

#: 실제 로봇 스캔. 8 방향 · 45도 간격 · 464x400(로봇 카메라 실제 해상도).
SCAN_DIR = demo_asset_path("20260910-134818_rot8")
SCAN_ROTATION_STEP_DEG = 45.0
#: 선언된 센서 화각(`edge/auto_calibration.DEFAULT_SENSOR_FOV_PRIORS` 의 imx708).
#: **벤더 제원표이고 실측이 아니다** — 그래서 아래 방위각 근거가 `declared` 다.
DECLARED_HFOV_DEG = 66.0

DEPTH_WEIGHTS = asset_path("models", "zipdepth", "zipdepth_base_384x384.onnx")
DETECTOR_WEIGHTS = asset_path("weights", "yolo", "yolov8s-worldv2.pt")


def _scan_frames() -> list[Path]:
    return sorted(SCAN_DIR.glob("frame_*.jpg")) if SCAN_DIR.is_dir() else []


needs_scan = pytest.mark.skipif(not _scan_frames(), reason=f"실제 스캔 자산이 없다: {SCAN_DIR}")
needs_depth = pytest.mark.skipif(not DEPTH_WEIGHTS.exists(),
                                 reason=f"실제 깊이 가중치가 없다: {DEPTH_WEIGHTS}")
needs_detector = pytest.mark.skipif(not DETECTOR_WEIGHTS.exists(),
                                    reason=f"실제 탐지 가중치가 없다: {DETECTOR_WEIGHTS}")


def _cv2():
    return pytest.importorskip("cv2")


@pytest.fixture(scope="module")
def taxonomy() -> ObstacleTaxonomy:
    return ObstacleTaxonomy.from_file()


@pytest.fixture(scope="module")
def profiles():
    return load_calibration_profiles()


@pytest.fixture(scope="module")
def depth_field():
    """실제 모델을 실제 프레임 한 장에 돌린 결과. 묶음 전체가 이것을 공유한다."""
    cv2 = _cv2()
    provider = ZipDepthProvider(DEPTH_WEIGHTS)
    frame = cv2.imread(str(_scan_frames()[0]))
    return provider.estimate(frame)


@pytest.fixture(scope="module")
def real_evidence(taxonomy, profiles):
    """실제 탐지기 + 실제 깊이로 8 방향 스캔 전체를 돌린 근거."""
    cv2 = _cv2()
    detector_vocabulary = list(
        taxonomy.vocabulary_classes("zeroshot"))
    detector = _detector(detector_vocabulary)
    depth_provider = ZipDepthProvider(DEPTH_WEIGHTS)
    # 선언된 화각에서 fx 를 뽑는다. **측정이 아니라 선언**이고, 그 사실이 근거에 남는다.
    width = 464
    fx = (width / 2.0) / math.tan(math.radians(DECLARED_HFOV_DEG / 2.0))
    builder = ObstacleEvidenceBuilder(taxonomy, profiles=profiles,
                                      declared_intrinsics=(fx, width / 2.0))

    out = []
    for index, path in enumerate(_scan_frames()):
        frame = cv2.imread(str(path))
        detections = [Detection(r.label, r.confidence, r.box, "yolov8s-worldv2", "zeroshot")
                      for r in detector.detect(frame)]
        out.extend(builder.build(
            frame_ref=f"rot8/{index:02d}",
            rotation_deg=index * SCAN_ROTATION_STEP_DEG,
            detections=detections,
            depth=depth_provider.estimate(frame)))
    return out


def _detector(vocabulary):
    from edge.yolo_world_provider import YoloWorldPerceptionProvider

    return YoloWorldPerceptionProvider(vocabulary, DETECTOR_WEIGHTS, conf=0.10)


# ── 실제 깊이 provider ──────────────────────────────────────────────────────

@needs_depth
def test_the_real_depth_model_declares_its_space_and_what_it_cannot_give(depth_field):
    """역깊이 모델은 미터도 내부 파라미터도 내주지 않는다. **0 으로 채우지 않는다.**"""
    assert depth_field is not None
    assert depth_field.depth_space == DEPTH_SPACE_AFFINE_INVERSE
    assert depth_field.nearer_is_larger, "역깊이는 값이 클수록 가깝다"
    assert depth_field.intrinsics is None, "없는 fx·cx 를 지어내지 않는다"
    assert depth_field.provider_key.startswith("zipdepth_base_384x384.onnx")


@needs_depth
def test_the_input_side_comes_from_the_graph_not_from_the_file_name(depth_field):
    """이름과 내용이 어긋난 가중치가 하나 섞이면 그때부터 전부 조용히 틀린다."""
    assert depth_field.infer_wh == (384, 384)
    assert depth_field.frame_wh == (464, 400), "실제 로봇 카메라 해상도"


# ── 보정이 묶여 있다 (이것이 이 파일의 핵심) ─────────────────────────────────

@needs_depth
def test_a_profile_for_another_model_refuses_rather_than_returning_a_number(
        depth_field, profiles):
    """**이 시험이 1110 박스 사고를 막는 유일한 코드 지점이다.**

    UniDepth 용 3차식은 미터 공간 전용이다. 역깊이 출력에 대면 값이 나오는데
    전부 틀리다 — 조용히 틀린 cm 보다 멈추는 쪽이 낫다.
    """
    metric_profile = next(p for p in profiles.values()
                          if p.applies_to_depth_space == "metric_m")

    with pytest.raises(CalibrationMismatch) as caught:
        measure_distance(metric_profile, depth_field, (200.0, 100.0, 300.0, 300.0))

    assert metric_profile.applies_to_provider_key in str(caught.value)
    assert depth_field.provider_key in str(caught.value)


@needs_depth
def test_an_unfitted_profile_says_so_rather_than_blaming_the_range(depth_field, profiles):
    """계수가 없는 것과 범위 밖인 것은 **다음에 할 일이 다르다.**

    전자는 같은 조건에서 재측정해 계수를 채우는 일이고, 후자는 그 구간을 믿지
    않기로 한 결정이다. 한 토큰으로 묶으면 그 차이가 사라진다.
    """
    measured = measure_distance(profiles[depth_field.provider_key], depth_field,
                                (200.0, 100.0, 300.0, 300.0))

    assert measured.distance_cm is None
    assert measured.status == STATUS_UNMEASURED_NO_FORMULA
    assert measured.rel_depth is not None, "상대값은 쟀다 — 환산만 못 했다"


@needs_depth
def test_the_crop_offset_is_removed_before_the_scale_is_applied():
    """crop 을 무시하고 배율만 곱하면 박스가 옮겨져 **다른 물체**의 깊이를 읽는다."""
    cv2 = _cv2()
    frame = cv2.imread(str(_scan_frames()[0]))
    cropped = ZipDepthProvider(DEPTH_WEIGHTS, crop_box=(114, 80, 351, 321))
    field_ = cropped.estimate(frame)

    assert field_.crop_box == (114, 80, 351, 321)
    assert field_.source_wh == (237, 241), "crop 이후 크기"
    assert field_.frame_wh == (464, 400), "crop 이전 원본"

    # 원본 좌표에서 crop 왼쪽-위에 바로 붙은 박스는 깊이 좌표의 원점 근처로 간다.
    x1, y1, _, _ = box_to_depth_pixels(field_, (114.0, 80.0, 164.0, 130.0))
    assert abs(x1) < 1e-6 and abs(y1) < 1e-6


@needs_depth
def test_the_representative_percentile_changes_which_side_of_the_box_is_taken(depth_field):
    """역깊이에서 p60 과 p40 은 **반대쪽**을 고른다 — 가까운 쪽과 먼 쪽이다."""
    box = box_to_depth_pixels(depth_field, (150.0, 100.0, 350.0, 300.0))
    near_side = roi_representative(depth_field.values, box, 60.0)
    far_side = roi_representative(depth_field.values, box, 40.0)

    assert near_side is not None and far_side is not None
    assert near_side > far_side, "역깊이는 값이 클수록 가깝다"


# ── 실제 탐지기 + 실제 스캔 ──────────────────────────────────────────────────

@needs_scan
@needs_detector
@needs_depth
def test_the_real_scan_produces_grounded_evidence(real_evidence):
    """실제 제로샷 탐지기가 실제 스캔에서 낸 것이 우리 어휘로 접지된다."""
    assert real_evidence, "실제 스캔에서 아무 근거도 안 나오면 접지를 볼 수 없다"
    assert all(e.frame == "robot-local" for e in real_evidence)
    assert {e.group for e in real_evidence} <= set(ObstacleTaxonomy.from_file().groups)


@needs_scan
@needs_detector
@needs_depth
def test_nothing_from_a_zero_shot_detector_is_promoted_to_a_confirmed_class(real_evidence):
    """**실제 모델 출력에서 이것이 깨지면 미검증 추론이 학습에 들어간다**(AI-L-02)."""
    assert all(e.label_status == STATUS_HYPOTHESIS for e in real_evidence)
    assert all(e.vocabulary == "zeroshot" for e in real_evidence)


@needs_scan
@needs_detector
@needs_depth
def test_the_real_scan_separates_structure_from_movable_objects(real_evidence):
    """요청의 끝 — 벽·기둥은 지도의 몸체이고 의자·상자는 따라 움직일 것이다.

    실제 스캔에 벽이 찍혀 있어 이 구분이 합성이 아니라 **실측에서** 선다.
    """
    roles = {e.role for e in real_evidence}

    assert "background" in roles, "실제 스캔의 wall 이 배경으로 갈려야 한다"
    assert "object" in roles
    background = [e for e in real_evidence if e.role == "background"]
    assert {e.group for e in background} == {"HARD_OBSTACLE"}, (
        "배경은 group 에서 유도되지 않는다 — 같은 그룹 안에서 갈린다")


@needs_scan
@needs_detector
@needs_depth
def test_no_distance_is_claimed_without_a_fitted_profile(real_evidence):
    """이 기계에는 미터 모델도 기준 거리도 없다. **그러면 거리가 없는 것이 맞다.**

    여기서 숫자가 나오면 그 숫자는 어디서도 재지 않은 값이다.
    """
    assert all(e.distance_m is None for e in real_evidence)
    assert {e.distance_reason for e in real_evidence} == {STATUS_UNMEASURED_NO_FORMULA}
    assert all(e.risk_band == "unknown" for e in real_evidence), (
        "거리를 모르면 far 가 아니라 unknown 이다")


@needs_scan
@needs_detector
@needs_depth
def test_the_bearing_says_it_came_from_a_declaration_not_a_measurement(real_evidence):
    """선언된 화각으로 뽑은 fx 는 **벤더 제원표**이고 이 렌즈를 잰 값이 아니다.

    각도는 쓸 수 있지만 그 사실이 값에 붙어야 한다(AI-S-08).
    """
    assert {e.bearing_basis for e in real_evidence} == {BEARING_FROM_DECLARATION}
    assert all(e.bearing_deg is not None for e in real_evidence)
    # 선언 화각 ±33도 안에 들어야 한다 — 밖으로 나가면 fx 계산이 틀린 것이다.
    assert all(abs(e.bearing_deg) <= DECLARED_HFOV_DEG / 2.0 + 1.0 for e in real_evidence)


@needs_scan
@needs_detector
@needs_depth
def test_each_frames_evidence_keeps_its_own_scan_direction(real_evidence):
    """8 장을 한 기준에 모을 때 회전각을 잃으면 전부 정면에서 본 것이 된다."""
    rotations = sorted({e.rotation_deg for e in real_evidence})

    assert len(rotations) >= 6, f"방향이 너무 적다: {rotations}"
    assert all(r % SCAN_ROTATION_STEP_DEG == 0 for r in rotations)
    for e in real_evidence:
        expected = (e.rotation_deg + e.bearing_deg) % 360.0
        assert abs(e.local_bearing_deg - expected) < 0.02


# ── 거리가 없으면 경로를 고르지 않는다 ───────────────────────────────────────

@needs_scan
@needs_detector
@needs_depth
def test_without_distance_the_obstacles_cannot_be_placed_and_that_is_counted(
        real_evidence, taxonomy):
    """자리를 못 찾은 장애물을 **위험으로 만들지도, 없던 일로 하지도 않는다.**"""
    coverage = ScanCoverage.from_frames(
        sorted({e.rotation_deg for e in real_evidence}),
        fov_deg=DECLARED_HFOV_DEG, max_range_m=6.0)
    field_ = HazardField(list(real_evidence), taxonomy, coverage=coverage)

    assert field_.located == []
    assert field_.unlocatable_count == len(real_evidence)
    assert field_.unlocatable_reasons == {STATUS_UNMEASURED_NO_FORMULA: len(real_evidence)}


@needs_scan
@needs_detector
@needs_depth
def test_the_real_scan_declares_its_coverage_so_clear_ground_counts(real_evidence, taxonomy):
    """실제 스캔의 회전각이 커버리지의 출처다 — 그 값을 다른 곳에 다시 적지 않는다."""
    coverage = ScanCoverage.from_frames(
        sorted({e.rotation_deg for e in real_evidence}),
        fov_deg=DECLARED_HFOV_DEG, max_range_m=6.0)

    assert coverage.is_declared
    assert coverage.covers((0.0, 3.0)), "정면 3m 는 봤다"
    assert not coverage.covers((0.0, 30.0)), "유효 거리 밖은 보지 않은 것이다"

    field_ = HazardField(list(real_evidence), taxonomy, coverage=coverage)
    evaluations, refusal = scored_candidates(
        generate((0.0, 4.0)), field_, RuleBasedRiskScorer(HAZARD_WEIGHTS).score)

    assert refusal is None, "커버리지를 선언했으므로 비교는 성립한다"
    # 장애물 자리를 하나도 못 찾았으니 전 구간이 "봤고 비어 있었다" 로 채점된다.
    assert all(e.max_risk == 0.0 for e in evaluations)
    assert not choose(evaluations).decided, (
        "전부 동률이면 위험으로는 갈리지 않는다 — 차선 기준 없이 1 위를 고르지 않는다")

    # **관측 비율 관문이 실제 데이터에서 길을 막지 않는지**가 이 줄의 질문이다
    # (2026-11-04). 관문을 더한 날 "스캔 밖으로 나가는 경로가 가장 안전해 보이는"
    # 결함은 사라졌지만, 같은 관문이 멀쩡한 길까지 막으면 로봇이 깨끗한 바닥에서
    # 멈춘다 — 한 번 그렇게 멈춘 적이 있어서 실제 스캔으로 확인한다.
    assert all(e.observed_fraction is not None for e in evaluations), (
        "탐침점이 있는 후보의 관측 비율은 미측정이 아니다")
    chosen = choose(evaluations, tie_break=path_lengths(generate((0.0, 4.0))))
    assert chosen.decided, (
        f"실제 스캔 안의 경로는 차선 기준이 있으면 골라져야 한다: {chosen.as_payload()}")
    assert chosen.tie_break_by == REASON_TIE_BROKEN_BY_COST, (
        "위험으로 고른 것과 길이로 고른 것은 구분되어야 한다")


@needs_scan
@needs_detector
@needs_depth
def test_the_same_scan_without_a_coverage_declaration_is_refused(real_evidence, taxonomy):
    """모르는 채로 1 위를 고르면 장애물 쪽 경로가 선택된다 — 실제로 그랬다."""
    field_ = HazardField(list(real_evidence), taxonomy)
    evaluations, refusal = scored_candidates(
        generate((0.0, 4.0)), field_, RuleBasedRiskScorer(HAZARD_WEIGHTS).score)

    assert evaluations == [] and refusal == REASON_COVERAGE_UNKNOWN
