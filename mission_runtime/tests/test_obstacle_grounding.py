"""장애물 분류 · 근거 · 위험장 — 제로샷 어휘를 들고 들어온다.

이 묶음이 지키는 것 다섯.

1. **모르는 이름을 비슷한 것으로 끌어오지 않는다**(AI-S-04). 제로샷 탐지기는
   아무 문자열이나 내므로 이것이 상시 경로다.
2. 제로샷 라벨은 끝까지 **가설**이다(AI-L-02). 점수가 높아도 확정이 아니다.
3. 배경(벽·기둥)과 객체(의자·상자)는 **같은 group 안에서 갈린다**. 트윈이
   "지도의 몸체인가 움직일 것인가"를 이것으로 정한다.
4. 거리를 못 내면 `None` 이고 **0 이 아니다**(AI-R-02). 0 은 "로봇 바로 앞"으로
   읽혀 없는 위험을 만든다.
5. **"근처에 없다"와 "안 봤다"는 다르다.** 둘을 합치면 안전한 경로가 미관측으로
   걸러지고 장애물 쪽 경로가 선택된다 — 실제로 그렇게 골랐던 결함이다.

implements: AI-S-04, AI-S-03, AI-S-06, AI-R-02, AI-E-01, AI-C-02, AI-L-02
tests: unmapped zero-shot label, label status, role split, missing distance,
       observed-clear vs unobserved, coverage refusal, loop symmetry
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edge.depth_contract import (  # noqa: E402
    DEPTH_SPACE_AFFINE_INVERSE,
    DEPTH_SPACE_METRIC,
    STATUS_UNMEASURED_NO_FORMULA,
    STATUS_UNMEASURED_NO_PROFILE,
    STATUS_UNMEASURED_OUT_OF_RANGE,
    CalibrationMismatch,
    DepthCalibrationProfile,
    DepthField,
    measure_distance,
)
from perception.obstacle_evidence import (  # noqa: E402
    BEARING_FROM_DECLARATION,
    REASON_NO_DEPTH,
    Detection,
    ObstacleEvidence,
    ObstacleEvidenceBuilder,
    fuse_detections,
    load_calibration_profiles,
)
from perception.obstacle_taxonomy import (  # noqa: E402
    REASON_UNMAPPED,
    STATUS_CLASSIFIED,
    STATUS_HYPOTHESIS,
    UNKNOWN_GROUP,
    UNKNOWN_ROLE,
    ObstacleTaxonomy,
)
from planning.path_candidates import choose, generate, path_lengths  # noqa: E402
from risk.hazard_field import (  # noqa: E402
    HAZARD_WEIGHTS,
    REASON_COVERAGE_UNKNOWN,
    HazardField,
    ScanCoverage,
    scored_candidates,
)
from risk.scoring import RuleBasedRiskScorer  # noqa: E402


@pytest.fixture(scope="module")
def tax() -> ObstacleTaxonomy:
    return ObstacleTaxonomy.from_file()


def evidence(**over) -> ObstacleEvidence:
    base = dict(
        evidence_id="e0", frame_ref="f1", rotation_deg=0.0, class_name="person",
        group="AGENT", group_priority=10, role="agent",
        label_status=STATUS_CLASSIFIED, vocabulary="finetune", detector_score=0.9,
        detector_source="yolo", depth_source="unidepth-v2-vitb14.cuda",
        depth_space=DEPTH_SPACE_METRIC, box_xyxy=(0, 0, 10, 10),
        raw_depth=1.0, distance_m=1.2, distance_reason="",
        calibration_profile_id="p1", bearing_deg=0.0,
        bearing_basis=BEARING_FROM_DECLARATION,
        local_bearing_deg=0.0, local_xy_m=(1.0, 2.0), ttc_s=None,
        near_threshold_m=2.0, near_threshold_basis="static_declared(dynamic_disabled)",
        risk_band="near")
    base.update(over)
    return ObstacleEvidence(**base)


# ── 분류: 제로샷을 고려한다 ──────────────────────────────────────────────────

def test_an_unmapped_zeroshot_label_is_not_dragged_onto_a_known_class(tax):
    """**이 시험이 AI-S-04 의 전부다.** 모르는 물체가 조용히 의자가 되면,
    미확인 객체 경로도 학습 후보 경로도 영원히 열리지 않는다."""
    verdict = tax.classify("고양이 인형", vocabulary="zeroshot")

    assert verdict.group == UNKNOWN_GROUP
    assert verdict.role == UNKNOWN_ROLE
    assert verdict.reason == REASON_UNMAPPED
    assert not verdict.is_known


def test_a_zeroshot_label_stays_a_hypothesis_even_when_it_is_known(tax):
    """어휘에 있어도 제로샷은 확정이 아니다(AI-L-02)."""
    zero = tax.classify("chair", vocabulary="zeroshot")
    fine = tax.classify("chair", vocabulary="finetune")

    assert zero.group == fine.group == "HARD_OBSTACLE"
    assert zero.label_status == STATUS_HYPOTHESIS and not zero.can_be_confirmed
    assert fine.label_status == STATUS_CLASSIFIED and fine.can_be_confirmed


def test_the_two_vocabularies_do_not_share_one_confidence_floor(tax):
    """하한을 하나로 쓰면 한쪽은 전부 버리고 다른 쪽은 전부 통과한다."""
    assert tax.confidence_floor("box", vocabulary="zeroshot") < \
        tax.confidence_floor("box", vocabulary="finetune")

    assert tax.passes_floor("box", 0.15, vocabulary="zeroshot")
    assert not tax.passes_floor("box", 0.15, vocabulary="finetune")


def test_an_unknown_vocabulary_declares_no_floor_rather_than_zero(tax):
    """어휘를 모르는데 임계값을 아는 척하지 않는다 — NaN 은 통과하지 않는다."""
    verdict = tax.classify("chair", vocabulary="어디서온어휘")

    assert math.isnan(verdict.confidence_floor)
    assert not tax.passes_floor("chair", 0.99, vocabulary="어디서온어휘")


def test_background_and_object_split_inside_one_group(tax):
    """벽과 의자는 둘 다 HARD_OBSTACLE 이지만 트윈에서 다루는 방식이 다르다.

    그래서 role 은 group 에서 유도할 수 없고 따로 선언된다.
    """
    wall = tax.classify("wall", vocabulary="zeroshot")
    chair = tax.classify("chair", vocabulary="zeroshot")
    stairs = tax.classify("stairs", vocabulary="zeroshot")
    person = tax.classify("person", vocabulary="finetune")

    assert wall.group == chair.group == "HARD_OBSTACLE"
    assert wall.role == "background", "벽은 지도의 몸체다"
    assert chair.role == "object", "의자는 자리가 바뀌면 따라 움직인다"
    assert stairs.role == "ground", "계단은 객체가 아니라 바닥의 성질이다"
    assert person.role == "agent"


def test_a_missing_speed_stream_is_more_conservative_than_assuming_zero(tax):
    """속도를 모를 때 0 m/s 로 가정하면 임계값이 최소로 내려가 "가까운 것이
    없다"가 된다. 선언된 고정값이 더 보수적이어야 한다."""
    unknown = tax.near_threshold_for_speed(None)
    known = tax.near_threshold_for_speed(0.8)

    assert "no_velocity_stream" in unknown.basis or "disabled" in unknown.basis
    assert unknown.value_m >= known.value_m
    assert known.basis.startswith("dynamic(")


# ── 근거: 없는 거리를 0 으로 채우지 않는다 ───────────────────────────────────

def builder(tax, **kw) -> ObstacleEvidenceBuilder:
    return ObstacleEvidenceBuilder(tax, declared_intrinsics=(320.0, 232.0), **kw)


def _field(values, *, space=DEPTH_SPACE_METRIC, key="unidepth-v2-vitb14.cuda") -> DepthField:
    return DepthField(values=values, depth_space=space, provider_key=key,
                      source_wh=(464, 400), infer_wh=(values.shape[1], values.shape[0]),
                      frame_wh=(464, 400))


def test_without_a_depth_field_the_distance_is_absent_with_a_reason(tax):
    [ev] = builder(tax).build(frame_ref="f1", rotation_deg=0.0, detections=[
        Detection("person", 0.9, (200, 100, 260, 300), "yolo", "finetune")])

    assert ev.distance_m is None, "0.0 이면 로봇 바로 앞으로 읽힌다"
    assert ev.distance_reason == REASON_NO_DEPTH
    assert ev.local_xy_m is None
    assert ev.risk_band == "unknown", "far 가 아니다 — 모르는 것을 안전으로 읽지 않는다"


def test_a_depth_field_with_no_bound_profile_gives_no_distance(tax):
    """프로파일이 **그 출력에 묶여 있지 않으면** 거리를 내지 않는다."""
    np = pytest.importorskip("numpy")
    field_ = _field(np.full((40, 46), 1.0), key="어디서온provider")

    [ev] = builder(tax, profiles=load_calibration_profiles()).build(
        frame_ref="f1", rotation_deg=0.0, depth=field_,
        detections=[Detection("person", 0.9, (200, 100, 260, 300), "y")])

    assert ev.distance_m is None
    assert ev.distance_reason == STATUS_UNMEASURED_NO_PROFILE


def test_a_metric_profile_refuses_an_inverse_depth_field(tax):
    """**이것이 1110 박스 사고를 막는 자리다.**

    미터 공간 전용 3차식을 역깊이 출력에 대면 값은 나오고 전부 틀린다
    (2026-09-20 실측: 전부 12.7~15.0cm, MAE 42.7cm). 조용히 틀린 cm 보다 멈추는
    쪽이 낫다 — 이 예외는 잡아서 축소할 것이 아니라 고칠 것이다.
    """
    np = pytest.importorskip("numpy")
    profiles = load_calibration_profiles()
    metric = next(p for p in profiles.values()
                  if p.applies_to_depth_space == DEPTH_SPACE_METRIC)
    inverse = _field(np.full((40, 46), 0.05), space=DEPTH_SPACE_AFFINE_INVERSE,
                     key=metric.applies_to_provider_key)

    with pytest.raises(CalibrationMismatch):
        measure_distance(metric, inverse, (200, 100, 260, 300))


def test_outside_the_calibrated_range_the_distance_is_none_not_clamped_to_zero(tax):
    """**옛 구현이 여기서 0cm 를 돌려줬고 소비자는 그것을 충돌 임박으로 읽었다.**"""
    np = pytest.importorskip("numpy")
    profiles = load_calibration_profiles()
    metric = next(p for p in profiles.values()
                  if p.applies_to_depth_space == DEPTH_SPACE_METRIC)
    # 선언된 유효 범위를 한참 벗어난 상대값.
    far_out = _field(np.full((40, 46), 99.0), key=metric.applies_to_provider_key)

    measured = measure_distance(metric, far_out, (200, 100, 260, 300))

    assert measured.distance_cm is None
    assert measured.status == STATUS_UNMEASURED_OUT_OF_RANGE


def test_an_unfitted_profile_is_a_different_reason_from_out_of_range():
    """계수를 채우는 일과 그 구간을 믿지 않는 일은 다르다."""
    np = pytest.importorskip("numpy")
    profiles = load_calibration_profiles()
    unfitted = next(p for p in profiles.values() if p.fn is None)
    field_ = _field(np.full((40, 46), 0.05), space=unfitted.applies_to_depth_space,
                    key=unfitted.applies_to_provider_key)

    measured = measure_distance(unfitted, field_, (200, 100, 260, 300))

    assert measured.status == STATUS_UNMEASURED_NO_FORMULA
    assert measured.rel_depth is not None, "상대값은 쟀다 — 환산만 못 했다"


def test_a_profile_knows_whether_it_was_measured_on_the_robot():
    """로봇 실측으로 만든 식과 다른 경로를 기준으로 맞춘 식은 같은 확신이 아니다."""
    profiles = load_calibration_profiles()
    metric = next(p for p in profiles.values()
                  if p.applies_to_depth_space == DEPTH_SPACE_METRIC)

    assert metric.is_robot_measured
    assert "quality" in metric.describe()
    assert metric.quality == {}, "미측정 품질 항목은 키가 없다 — 0 이 아니다"


def test_fusing_two_detectors_keeps_both_sources(tax):
    """근거 둘이 하나로 줄어든 사실이 보이지 않으면 충분도가 실제보다 커 보인다."""
    merged = fuse_detections([
        Detection("box", 0.8, (10, 10, 50, 50), "finetune"),
        Detection("box", 0.6, (12, 12, 52, 52), "zeroshot"),
    ], tax.fusion_iou)

    assert len(merged) == 1
    assert set(merged[0].source.split("+")) == {"finetune", "zeroshot"}


def test_a_bearing_without_any_intrinsics_is_not_invented(tax):
    """없는 기준으로 만든 각도는 좌표가 아니다(AI-C-02)."""
    plain = ObstacleEvidenceBuilder(tax)

    [ev] = plain.build(frame_ref="f1", rotation_deg=45.0, detections=[
        Detection("person", 0.9, (200, 100, 260, 300), "yolo")])

    assert ev.bearing_deg is None
    assert ev.bearing_basis == "unmeasured_no_intrinsics"
    assert ev.local_bearing_deg == 45.0, "각도를 모르면 프레임 방향 그대로다"


def test_local_coordinates_say_they_are_local(tax):
    [ev] = builder(tax).build(frame_ref="f1", rotation_deg=0.0, detections=[
        Detection("person", 0.9, (200, 100, 260, 300), "yolo")])

    assert ev.frame == "robot-local"


# ── 위험장: 본 곳과 안 본 곳 ─────────────────────────────────────────────────

def test_with_no_evidence_the_lookup_is_empty_not_zero(tax):
    """`{"proximity": 0.0}` 을 돌려주면 평가기가 "확인했고 안전했다"로 읽는다."""
    field = HazardField([evidence()], tax)

    assert field.lookup((-3.0, 2.0)) == {}


def test_observed_clear_ground_is_evidence_but_unobserved_ground_is_not(tax):
    """커버리지가 이 둘을 가른다."""
    cov = ScanCoverage.from_frames([0.0], fov_deg=60, max_range_m=6.0)
    field = HazardField([evidence()], tax, coverage=cov)

    assert field.lookup((0.0, 3.0)), "정면 3m 는 봤고 비어 있었다 — 근거다"
    assert field.lookup((0.0, 30.0)) == {}, "유효 거리 밖은 보지 않은 것이다"
    assert field.lookup((-3.0, 0.1)) == {}, "화각 밖은 보지 않은 것이다"


def test_ttc_is_absent_without_a_closing_speed_so_sufficiency_drops(tax):
    """없는 칸을 채우지 않으면 모자란 근거가 수치에 자동으로 드러난다."""
    field = HazardField([evidence(ttc_s=None)], tax)
    inputs = field.lookup((1.0, 2.0))

    assert "ttc" not in inputs
    score = RuleBasedRiskScorer(HAZARD_WEIGHTS).score(inputs)
    assert score.evidence_sufficiency < 1.0


def test_obstacles_that_could_not_be_placed_are_counted_not_invented(tax):
    """자리를 못 찾은 장애물을 위험으로 만들지도, 없던 일로 하지도 않는다."""
    field = HazardField([evidence(local_xy_m=None, distance_m=None,
                                  distance_reason=STATUS_UNMEASURED_OUT_OF_RANGE)], tax)

    assert field.lookup((1.0, 2.0)) == {}
    assert field.unlocatable_count == 1
    assert field.unlocatable_reasons == {STATUS_UNMEASURED_OUT_OF_RANGE: 1}


def test_a_person_outranks_a_box_at_the_same_distance(tax):
    """사람이 먼저다. 그 순서는 선언이 정하고 코드가 분기하지 않는다."""
    field = HazardField([
        evidence(evidence_id="box", group="SOFT_PUSHABLE",
                 group_priority=tax.priority_of("SOFT_PUSHABLE"), local_xy_m=(1.0, 2.0)),
        evidence(evidence_id="person", group="AGENT",
                 group_priority=tax.priority_of("AGENT"), local_xy_m=(1.0, 2.0)),
    ], tax)

    assert field.worst_evidence_near((1.0, 2.0)).evidence_id == "person"


# ── 합성: 안전한 길이 안전하다는 이유로 탈락하지 않는다 ──────────────────────

def _loop(tax, obstacle_xy, *, coverage=True):
    cands = generate((0.0, 4.0))
    cov = (ScanCoverage.from_frames([i * 45 for i in range(8)], fov_deg=60,
                                    max_range_m=6.0) if coverage else None)
    field = HazardField([evidence(local_xy_m=obstacle_xy)], tax, coverage=cov)
    evals, refusal = scored_candidates(cands, field, RuleBasedRiskScorer(HAZARD_WEIGHTS).score)
    return cands, evals, refusal


def test_the_detour_toward_the_obstacle_scores_worse_than_the_one_away(tax):
    """**이 시험이 처음 돌렸을 때 깨졌다** — 장애물 쪽 경로가 선택됐다."""
    _, evals, _ = _loop(tax, (1.0, 2.0))
    risk = {e.candidate_id: e.max_risk for e in evals}

    assert risk["lateral_right_1p2"] > risk["lateral_left_1p2"]
    assert risk["lateral_left_1p2"] == 0.0, "장애물 반대쪽은 비어 있었다"


def test_the_same_holds_mirrored(tax):
    """부호 한 곳이 뒤집히면 이 시험만 깨진다."""
    _, evals, _ = _loop(tax, (-1.0, 2.0))
    risk = {e.candidate_id: e.max_risk for e in evals}

    assert risk["lateral_left_1p2"] > risk["lateral_right_1p2"]


def test_a_safe_candidate_is_not_filtered_out_for_being_safe(tax):
    """빈 곳을 지나는 후보도 **같은 충분도**로 비교돼야 한다."""
    _, evals, _ = _loop(tax, (1.0, 2.0))

    safe = next(e for e in evals if e.candidate_id == "lateral_left_1p2")
    risky = next(e for e in evals if e.candidate_id == "lateral_right_1p2")
    assert safe.evidence_sufficiency == pytest.approx(risky.evidence_sufficiency)
    assert safe.points_missing_evidence == 0


def test_without_declared_coverage_the_candidates_are_refused_not_ranked(tax):
    """모르는 채로 1 위를 고르는 것이 그 결함의 정체였다."""
    _, evals, refusal = _loop(tax, (1.0, 2.0), coverage=False)

    assert evals == [] and refusal == REASON_COVERAGE_UNKNOWN


def test_when_risk_ties_the_choice_says_it_was_not_risk_that_decided(tax):
    """길이 비어 있으면 후보 여럿이 똑같이 위험 0 이다. 거절만 하면 멈춘다."""
    cands, evals, _ = _loop(tax, (1.0, 2.0))

    refused = choose(evals)
    assert not refused.decided, "차선 기준 없이는 옛 동작대로 거절한다"

    picked = choose(evals, tie_break=path_lengths(cands))
    assert picked.candidate_id == "direct", "동률이면 짧은 쪽"
    assert picked.tie_break_by == "tie_broken_by_path_length"
    assert picked.as_payload()["tie_break_by"] == "tie_broken_by_path_length"


def test_the_tie_break_does_not_reach_candidates_that_risk_separated(tax):
    """위험이 갈린 후보까지 길이로 줄 세우면 위험 판정이 길이에 덮인다."""
    cands, evals, _ = _loop(tax, (1.0, 2.0))
    lengths = path_lengths(cands)
    # 위험한 우회를 **가장 짧게** 선언해도 고르지 않아야 한다.
    lengths["lateral_right_1p2"] = 0.001

    picked = choose(evals, tie_break=lengths)
    assert picked.candidate_id != "lateral_right_1p2"
