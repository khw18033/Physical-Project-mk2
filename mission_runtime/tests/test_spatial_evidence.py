"""implements: AI-S-06, AI-S-08, AI-C-02, AI-C-15
tests: 사람 실측이 융합 뒤에도 구분되고 서명이 남는다 · 미선언 정확도가 숫자가 되지
       않고 지배하지도 않는다 · 같은 프레임에서 나온 둘은 하나의 지지다 ·
       leave-one-out 이 값을 실제로 움직인 출처를 가린다 · 없는 provider 는 아무것도
       주장하지 않는다 · 전역 좌표는 어디서도 나오지 않는다

여기 있는 시험은 "값이 맞다" 가 아니라 **"왜 그 값인지가 남아 있다"** 를 고정한다.
평균 하나로 뭉갠 지도는 틀렸을 때 고칠 수가 없고, 그 구분이 이 모듈의 존재 이유다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityState
from mission_runtime.perception.spatial_evidence import (
    DECIDED_HUMAN_OVERRIDE,
    DECIDED_INVERSE_VARIANCE,
    DECIDED_UNWEIGHTED_MEAN,
    DEFAULT_KIND_REGISTRY,
    KIND_DEPTH,
    KIND_GPS,
    KIND_HUMAN_SURVEY,
    KIND_INFRASTRUCTURE_DECLARATION,
    KIND_MULTI_DEVICE_DETECTION,
    KIND_POINT_CLOUD,
    KIND_ZERO_SHOT_DETECTION,
    REJECT_FRAME_MISMATCH,
    REJECT_MISSING_AUTHOR,
    REJECT_NOT_LOCAL,
    REJECT_SOURCE_UNAVAILABLE,
    REJECT_UNREGISTERED_KIND,
    REQUIREMENT,
    ROLE_ACCURACY_UNKNOWN,
    UNCONFIRMED_DECLARED_ONLY,
    UNCONFIRMED_NO_EVIDENCE,
    ROLE_DEPENDENT,
    ROLE_INDEPENDENT,
    ROLE_OVERRIDE,
    ROLE_SUPERSEDED,
    TIER_ESTIMATED,
    TIER_MEASURED,
    EvidenceKindSpec,
    SpatialObservation,
    default_kind_registry,
    fuse_zone,
    gather_observations,
    load_survey_observations,
    observations_from_domain_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZONE = "N4-1F-W"
FRAME = "site:college"
QUANTITY = "infrastructure.pi6.at"


def obs(evidence_id, kind, source_group, frame_ref, value, accuracy=None,
        *, quantity=QUANTITY, at=1.0, frame=FRAME, **kwargs):
    return SpatialObservation(
        evidence_id=evidence_id, source_group=source_group, frame_ref=frame_ref,
        observed_at=at, evidence_kind=kind, quantity_id=quantity, value=value,
        frame_id=frame, accuracy_m=accuracy, **kwargs)


def survey(evidence_id, value, accuracy=0.05, *, who="jinnayoung", when=100.0, **kwargs):
    return obs(evidence_id, KIND_HUMAN_SURVEY, "ops_web.survey",
               f"survey_session:{evidence_id}", value, accuracy,
               entered_by=who, entered_at=when, **kwargs)


# --- 사람 실측 ---------------------------------------------------------------

def test_human_survey_stays_distinguishable_from_a_sensor_estimate():
    # 깊이맵이 20cm 로 말한 자리를 사람이 5cm 로 재어 고쳤다. 융합 뒤에 두 값이
    # 구분되지 않으면 지도가 틀렸을 때 누구를 의심해야 할지 알 수 없다.
    state = fuse_zone([
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.9, 4.4), 0.2),
        survey("survey-1", (6.35, 3.95)),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert state.decided_by == DECIDED_HUMAN_OVERRIDE
    assert state.value == (6.35, 3.95)
    assert state.tier == TIER_MEASURED
    assert state.entered_by == "jinnayoung"
    assert state.entered_at == 100.0

    override = state.contribution("survey-1")
    sensed = state.contribution("depth-1")
    assert (override.role, override.tier) == (ROLE_OVERRIDE, TIER_MEASURED)
    assert (sensed.role, sensed.tier) == (ROLE_INDEPENDENT, TIER_ESTIMATED)
    assert override.entered_by == "jinnayoung" and sensed.entered_by is None


def test_an_override_does_not_retroactively_change_what_the_sensors_reported():
    state = fuse_zone([
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.9, 4.4), 0.2),
        survey("survey-1", (6.35, 3.95)),
    ], zone_id=ZONE).quantity(QUANTITY)

    # 덮은 것은 **현재 상태**일 뿐이고 센서가 말한 값은 그대로 읽을 수 있다.
    assert state.without_human_value == pytest.approx((6.9, 4.4))
    assert state.without_human_accuracy_m == pytest.approx(0.2)
    assert state.contribution("depth-1").value == (6.9, 4.4)
    # 사람 입력을 빼면 센서만의 값으로 되돌아간다 — 같은 질문의 다른 방향이다.
    assert state.without("ops_web.survey").value == pytest.approx((6.9, 4.4))


def test_an_unsigned_human_value_is_refused_with_its_reason():
    zone = fuse_zone([survey("survey-1", (6.35, 3.95), who=None)], zone_id=ZONE)

    assert zone.quantities == {}
    assert [(r.evidence_id, r.reason) for r in zone.rejected] == \
           [("survey-1", REJECT_MISSING_AUTHOR)]


def test_a_later_survey_supersedes_the_earlier_one_without_erasing_it():
    state = fuse_zone([
        survey("survey-1", (6.2, 4.1), 0.1, when=100.0),
        survey("survey-2", (6.35, 3.95), 0.05, when=200.0),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert state.value == (6.35, 3.95)
    assert state.contribution("survey-1").role == ROLE_SUPERSEDED
    assert state.contribution("survey-2").role == ROLE_OVERRIDE


# --- 정확도 ------------------------------------------------------------------

def test_unknown_accuracy_never_becomes_a_number_and_never_dominates():
    # 선언 프로파일은 정확도를 적지 않는다. 기본값을 꽂으면 그 "모르는" 값이 20cm 로
    # 선언한 깊이맵을 이길 수 있고, 그러면 아무도 모르는 사이에 지도가 선언으로 되돌아간다.
    state = fuse_zone([
        obs("declared", KIND_INFRASTRUCTURE_DECLARATION, "zone_profile",
            "zone_profile:college", (6.0, 4.0)),
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert state.decided_by == DECIDED_INVERSE_VARIANCE
    assert state.value == (6.5, 4.2)                     # 선언이 값을 끌어당기지 않았다
    assert state.contribution("declared").role == ROLE_ACCURACY_UNKNOWN
    assert state.contribution("declared").accuracy_m is None
    assert state.contribution("declared").weight == 0.0
    assert state.contributing_kinds == (KIND_DEPTH,)


def test_with_no_declared_accuracy_anywhere_the_result_stays_unknown():
    state = fuse_zone([
        obs("declared", KIND_INFRASTRUCTURE_DECLARATION, "zone_profile",
            "zone_profile:college", (6.0, 4.0)),
        obs("zs-1", KIND_ZERO_SHOT_DETECTION, "edge.openvocab", "frame:pi6:1001", (6.4, 4.4)),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert state.decided_by == DECIDED_UNWEIGHTED_MEAN
    assert state.value == (6.2, 4.2)
    # 평균은 낼 수 있지만 정확도는 지어내지 않는다.
    assert state.accuracy_m is None
    assert state.accuracy_known is False


def test_a_better_declared_accuracy_pulls_the_value_more():
    state = fuse_zone([
        obs("coarse", KIND_GPS, "gnss", "fix:9", (10.0, 0.0), 2.0,
            local_reduction_ref="anchor:n4-door"),
        obs("fine", KIND_MULTI_DEVICE_DETECTION, "edge.multi", "frame:mt4:77", (0.0, 0.0), 0.2),
    ], zone_id=ZONE).quantity(QUANTITY)

    # 역분산 가중: σ=0.2 의 무게가 σ=2.0 의 100배다.
    assert state.value[0] == pytest.approx(10.0 * (1 / 4) / (1 / 4 + 1 / 0.04), abs=1e-9)
    assert state.accuracy_m < 0.2
    assert state.independent_support == 2


def test_zero_accuracy_is_refused_at_construction():
    # 0 은 "완벽" 이 아니라 무한 가중이다. 모르면 None 으로 적는다.
    with pytest.raises(ValueError, match="accuracy_m"):
        obs("bad", KIND_DEPTH, "edge.depth", "frame:1", (1.0, 1.0), 0.0)


# --- 독립성 ------------------------------------------------------------------

def test_two_values_from_one_frame_are_one_independent_support():
    one_frame = fuse_zone([
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
        obs("cloud-1", KIND_POINT_CLOUD, "edge.cloud", "frame:pi6:1001", (6.5, 4.2), 0.2),
    ], zone_id=ZONE).quantity(QUANTITY)

    two_frames = fuse_zone([
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
        obs("cloud-1", KIND_POINT_CLOUD, "edge.cloud", "frame:mt4:77", (6.5, 4.2), 0.2),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert one_frame.independent_support == 1
    assert two_frames.independent_support == 2
    # 같은 프레임을 두 번 읽어 정확도를 좋게 만들 수는 없다.
    assert one_frame.accuracy_m == pytest.approx(0.2)
    assert two_frames.accuracy_m < one_frame.accuracy_m
    dependent = [r for r in one_frame.contributions if r.role == ROLE_DEPENDENT]
    assert len(dependent) == 1


def test_the_dependent_sibling_is_kept_with_its_own_value():
    state = fuse_zone([
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
        obs("cloud-1", KIND_POINT_CLOUD, "edge.cloud", "frame:pi6:1001", (9.9, 9.9), 0.5),
    ], zone_id=ZONE).quantity(QUANTITY)

    # 버리지 않고 역할만 달리 적는다 — 어느 값이 왜 안 쓰였는지가 답할 수 있어야 한다.
    sibling = state.contribution("cloud-1")
    assert (sibling.role, sibling.value) == (ROLE_DEPENDENT, (9.9, 9.9))
    assert state.value == (6.5, 4.2)


# --- 한 출처를 빼면 ----------------------------------------------------------

def test_leave_one_out_names_the_source_that_actually_moved_the_value():
    state = fuse_zone([
        obs("fine", KIND_MULTI_DEVICE_DETECTION, "edge.multi", "frame:mt4:77", (6.0, 4.0), 0.1),
        obs("coarse", KIND_GPS, "gnss", "fix:9", (16.0, 4.0), 3.0,
            local_reduction_ref="anchor:n4-door"),
        obs("declared", KIND_INFRASTRUCTURE_DECLARATION, "zone_profile",
            "zone_profile:college", (0.0, 0.0)),
    ], zone_id=ZONE).quantity(QUANTITY)

    influence = {row.removed: row.influence_m for row in state.leave_one_out()}
    # 정확도를 선언하지 않은 선언값은 값을 정하지 않았으므로 빼도 그대로다.
    assert influence["zone_profile"] == pytest.approx(0.0)
    # GPS 는 거칠지만 값을 움직였다 — 그 사실이 숫자로 답해진다.
    assert influence["gnss"] > 0.0
    assert influence["edge.multi"] > influence["gnss"]
    assert state.without("gnss").value[0] == pytest.approx(6.0)


def test_leave_one_out_says_when_a_source_was_holding_the_value_alone():
    state = fuse_zone([
        obs("only", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
    ], zone_id=ZONE).quantity(QUANTITY)

    [row] = state.leave_one_out()
    assert row.removed == "edge.depth"
    assert row.vanished is True
    # 값이 사라진 것과 값이 0 인 것은 다르다 — 거리는 모름으로 남는다.
    assert row.influence_m is None


def test_leave_one_out_can_be_asked_by_kind_or_by_source_observation():
    state = fuse_zone([
        obs("a", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.0, 4.0), 0.2),
        obs("b", KIND_DEPTH, "edge.depth", "frame:pi6:1002", (8.0, 4.0), 0.2),
    ], zone_id=ZONE).quantity(QUANTITY)

    by_kind = state.leave_one_out(unit="kind")
    by_frame = state.leave_one_out(unit="frame_ref")
    assert [row.removed for row in by_kind] == [KIND_DEPTH]
    assert by_kind[0].vanished is True              # 그 종류가 값을 혼자 받치고 있었다
    assert {row.removed for row in by_frame} == {"frame:pi6:1001", "frame:pi6:1002"}
    assert all(row.influence_m == pytest.approx(1.0) for row in by_frame)


# --- 없음은 반대 근거가 아니다 ----------------------------------------------

def test_a_missing_provider_contributes_nothing():
    present = [obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2)]

    collected, unavailable = gather_observations({
        "edge.depth": lambda: present,
        "edge.cloud": None,                        # 그 노드에 점군 provider 가 없다
        "gnss": lambda: (_ for _ in ()).throw(RuntimeError("no fix")),
    })

    assert [o.evidence_id for o in collected] == ["depth-1"]
    assert unavailable == ("edge.cloud", "gnss")

    with_absence = fuse_zone(collected, zone_id=ZONE, unavailable_sources=unavailable)
    without_absence = fuse_zone(present, zone_id=ZONE)
    # 없는 provider 가 값에 아무 영향도 주지 않는다. 반대 값도, 불확실도 증가도 아니다.
    assert with_absence.quantity(QUANTITY).value == without_absence.quantity(QUANTITY).value
    assert with_absence.quantity(QUANTITY).accuracy_m == \
           without_absence.quantity(QUANTITY).accuracy_m
    assert with_absence.unavailable_sources == ("edge.cloud", "gnss")
    assert KIND_POINT_CLOUD in with_absence.unobserved_kinds


def test_an_unavailable_source_is_skipped_rather_than_treated_as_disagreement():
    zone = fuse_zone([
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
        obs("gone", KIND_MULTI_DEVICE_DETECTION, "edge.multi", "frame:mt4:77", (99.0, 99.0), 0.1),
    ], zone_id=ZONE, available_sources={"edge.depth"})

    assert zone.quantity(QUANTITY).value == (6.5, 4.2)
    assert [(r.evidence_id, r.reason) for r in zone.rejected] == \
           [("gone", REJECT_SOURCE_UNAVAILABLE)]


def test_losing_optional_sources_degrades_rather_than_disables():
    # 선언 프로파일만 있으면 구역 공간 상태는 성립한다(AI-C-05).
    assert REQUIREMENT.evaluate({"reference.zone_profile"}) is CapabilityState.DEGRADED
    assert REQUIREMENT.evaluate(set()) is CapabilityState.DISABLED


# --- 좌표계 경계 -------------------------------------------------------------

def test_a_gps_fix_without_a_local_reduction_is_not_fused():
    zone = fuse_zone([
        obs("fix-1", KIND_GPS, "gnss", "fix:9", (36.3, 127.3), 2.5),
    ], zone_id=ZONE)

    # 환산 기준 없는 절대 측위를 로컬 값에 섞으면 그 자리는 전역 좌표가 된다(AI-C-02).
    assert zone.quantities == {}
    assert [(r.evidence_id, r.reason) for r in zone.rejected] == [("fix-1", REJECT_NOT_LOCAL)]


def test_a_gps_fix_reduced_to_the_local_frame_is_ordinary_evidence():
    state = fuse_zone([
        obs("fix-1", KIND_GPS, "gnss", "fix:9", (6.8, 4.6), 2.5,
            local_reduction_ref="anchor:n4-door"),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert state.value == pytest.approx((6.8, 4.6))
    assert state.frame_id == FRAME


def test_a_global_coordinate_frame_is_refused_and_never_appears_in_the_output():
    zone = fuse_zone([
        obs("bad", KIND_GPS, "gnss", "fix:9", (36.3, 127.3), 2.5,
            frame="wgs84", local_reduction_ref="anchor:n4-door"),
        obs("good", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
    ], zone_id=ZONE)

    assert [(r.evidence_id, r.reason) for r in zone.rejected] == [("bad", REJECT_FRAME_MISMATCH)]
    # 거절 **사유**에는 그 프레임 이름이 남아야 하지만, 값 쪽에는 전역 좌표가 없다.
    assert "wgs84" in zone.rejected[0].detail
    values = {qid: {k: v for k, v in row.items() if k != dd.REJECTED_OBSERVATIONS}
              for qid, row in zone.as_dict()["quantities"].items()}
    body = json.dumps(values)
    assert "wgs84" not in body
    for banned in ("latitude", "longitude", "lat", "lon", "altitude", "easting", "northing"):
        assert f'"{banned}"' not in body
    assert zone.as_dict()[dd.COORDINATE_FRAME] == FRAME


def test_mixing_two_local_frames_in_one_quantity_is_refused():
    zone = fuse_zone([
        obs("a", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
        obs("b", KIND_DEPTH, "robot.depth", "frame:go1:5", (0.4, 1.1), 0.2, frame="body:go1"),
    ], zone_id=ZONE)

    # 변환은 우리 것이 아니다. 섞으면 그 값은 어느 프레임의 값도 아니게 된다.
    assert zone.frame_id == FRAME
    assert [(r.evidence_id, r.reason) for r in zone.rejected] == [("b", REJECT_FRAME_MISMATCH)]


# --- 종류 레지스트리 --------------------------------------------------------

def test_the_seven_deployed_kinds_are_registered_with_their_tiers():
    assert set(DEFAULT_KIND_REGISTRY.kinds()) == {
        KIND_GPS, KIND_MULTI_DEVICE_DETECTION, KIND_DEPTH, KIND_POINT_CLOUD,
        KIND_ZERO_SHOT_DETECTION, KIND_INFRASTRUCTURE_DECLARATION, KIND_HUMAN_SURVEY,
    }
    assert DEFAULT_KIND_REGISTRY.tier_of(KIND_HUMAN_SURVEY) == TIER_MEASURED
    assert DEFAULT_KIND_REGISTRY.tier_of(KIND_DEPTH) == TIER_ESTIMATED
    assert DEFAULT_KIND_REGISTRY.spec(KIND_HUMAN_SURVEY).overrides is True
    assert DEFAULT_KIND_REGISTRY.spec(KIND_DEPTH).overrides is False


def test_a_new_sensor_kind_arrives_as_a_registration_not_as_a_branch():
    kinds = default_kind_registry()
    thermal = [obs("t-1", "thermal_array", "edge.thermal", "frame:ir:1", (6.6, 4.1), 0.3)]

    before = fuse_zone(thermal, zone_id=ZONE, kinds=kinds)
    assert before.quantities == {}
    assert [(r.evidence_id, r.reason) for r in before.rejected] == \
           [("t-1", REJECT_UNREGISTERED_KIND)]

    kinds.register(EvidenceKindSpec("thermal_array", TIER_ESTIMATED))
    after = fuse_zone(thermal, zone_id=ZONE, kinds=kinds)
    assert after.quantity(QUANTITY).value == (6.6, 4.1)
    # 기본 레지스트리는 더럽혀지지 않는다 — 배치별 종류가 전역으로 번지면 안 된다.
    assert "thermal_array" not in DEFAULT_KIND_REGISTRY.kinds()


def test_a_tier_outside_the_declared_vocabulary_is_refused():
    with pytest.raises(ValueError, match="evidence tier"):
        EvidenceKindSpec("made_up", "very_trustworthy")


# --- 선언만으로는 확정하지 않는다 (AI-S-08) ----------------------------------


def test_a_declared_prior_alone_does_not_confirm_the_value():
    """AI-S-08: "실제 관측과 충돌하는 사전정보만으로 객체·위험 상태를 확정해서는 안
    된다." 선언은 "있을 것" 이라고 적힌 값이고, 그것만으로 확정하면 프로파일의 오타가
    지도의 사실이 된다.

    그래도 **값은 그대로 낸다** — 선언만 있는 현장은 정상 배치다(규칙 4). 거절이
    아니라 확정만 보류하고 사유를 남긴다.
    """
    state = fuse_zone([
        obs("declared", KIND_INFRASTRUCTURE_DECLARATION, "zone_profile",
            "zone_profile:college", (6.0, 4.0)),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert state.value == (6.0, 4.0)
    assert state.decided_by == DECIDED_UNWEIGHTED_MEAN
    assert state.confirmed is False
    assert state.unconfirmed_reason == UNCONFIRMED_DECLARED_ONLY
    assert state.as_dict()[dd.UNCONFIRMED_REASON] in dd.UNCONFIRMED_REASONS


def test_many_declarations_still_do_not_add_up_to_a_confirmation():
    """선언을 더 쌓아도 격이 올라가지 않는다 — 센 것은 수가 아니라 출처의 성질이다."""
    state = fuse_zone([
        obs("declared-a", KIND_INFRASTRUCTURE_DECLARATION, "zone_profile",
            "zone_profile:college", (6.0, 4.0)),
        obs("declared-b", KIND_INFRASTRUCTURE_DECLARATION, "ops_web.profile",
            "zone_profile:override", (6.2, 4.1)),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert state.independent_support == 2
    assert state.confirmed is False
    assert state.unconfirmed_reason == UNCONFIRMED_DECLARED_ONLY


def test_one_real_observation_beside_the_declaration_confirms_it():
    """측정·추정 격의 근거가 하나라도 값을 움직이면 확정이 된다."""
    state = fuse_zone([
        obs("declared", KIND_INFRASTRUCTURE_DECLARATION, "zone_profile",
            "zone_profile:college", (6.0, 4.0)),
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert state.confirmed is True
    assert state.unconfirmed_reason is None


def test_a_human_measurement_confirms_on_its_own():
    """사람 실측은 선언이 아니라 **측정**이다 — 혼자서도 확정된다(AI-L-03)."""
    state = fuse_zone([survey("survey-1", (6.35, 3.95))],
                      zone_id=ZONE).quantity(QUANTITY)

    assert (state.confirmed, state.unconfirmed_reason) == (True, None)


def test_removing_the_only_observation_falls_back_to_unconfirmed_with_a_reason():
    """한 출처를 빼면 확정도 사라진다 — 그 사실이 사유와 함께 나와야 운영자가 무엇을
    다시 재야 하는지 안다."""
    state = fuse_zone([
        obs("declared", KIND_INFRASTRUCTURE_DECLARATION, "zone_profile",
            "zone_profile:college", (6.0, 4.0)),
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
    ], zone_id=ZONE).quantity(QUANTITY)

    without_depth = state.without("edge.depth")

    assert without_depth.confirmed is False
    assert without_depth.unconfirmed_reason == UNCONFIRMED_DECLARED_ONLY
    # 값이 아예 사라지는 경우는 또 다른 사유다.
    assert without_depth.without("zone_profile").unconfirmed_reason \
        == UNCONFIRMED_NO_EVIDENCE


# --- 공통 데이터 사전 · 결정성 ----------------------------------------------

def test_every_top_level_name_is_registered_in_the_data_dictionary():
    state = fuse_zone([
        obs("depth-1", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
        survey("survey-1", (6.35, 3.95)),
    ], zone_id=ZONE).quantity(QUANTITY)

    assert dd.unknown_fields(state.as_dict()) == ()
    assert state.as_dict()[dd.DECIDED_BY] in dd.SPATIAL_DECISION_RULES
    assert state.as_dict()[dd.EVIDENCE_TIER] in dd.SPATIAL_EVIDENCE_TIERS
    roles = {row[dd.CONTRIBUTION_ROLE] for row in state.as_dict()[dd.CONTRIBUTIONS]}
    assert roles <= set(dd.CONTRIBUTION_ROLES)


def test_the_same_observations_always_produce_the_same_state():
    rows = [
        obs("b", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (6.5, 4.2), 0.2),
        obs("a", KIND_MULTI_DEVICE_DETECTION, "edge.multi", "frame:mt4:77", (6.1, 4.0), 0.2),
    ]
    first = fuse_zone(rows, zone_id=ZONE).quantity(QUANTITY)
    second = fuse_zone(list(reversed(rows)), zone_id=ZONE).quantity(QUANTITY)

    assert first.value == second.value
    assert [r.evidence_id for r in first.contributions] == \
           [r.evidence_id for r in second.contributions]


def test_quantities_of_different_arity_are_kept_apart():
    zone = fuse_zone([
        obs("len-1", KIND_HUMAN_SURVEY, "ops_web.survey", "survey:1", (8.64,), 0.02,
            quantity="room.N4-102.wall_west_length_m", entered_by="jny", entered_at=1.0),
        obs("len-2", KIND_DEPTH, "edge.depth", "frame:pi6:1001", (8.4, 0.0), 0.3,
            quantity="room.N4-102.wall_west_length_m"),
    ], zone_id=ZONE)

    # 1성분 길이와 2성분 자리를 같은 quantity 에 섞으면 성분이 조용히 밀린다.
    assert zone.quantity("room.N4-102.wall_west_length_m").value == (8.64,)
    assert [r.reason for r in zone.rejected] == ["arity_mismatch"]


# --- 실물 파일과 맞물려 돈다 -------------------------------------------------

def test_the_shipped_survey_example_overrides_the_shipped_declaration():
    profile = json.loads(
        (PROJECT_ROOT / "profiles" / "domains.example.json").read_text(encoding="utf-8"))
    declared = observations_from_domain_profile(profile, ZONE)
    surveyed = load_survey_observations(
        PROJECT_ROOT / "profiles" / "space_survey.example.json", zone_id=ZONE)

    zone = fuse_zone(declared + surveyed, zone_id=ZONE)
    camera = zone.quantity(QUANTITY)

    assert {o.evidence_kind for o in declared} == {KIND_INFRASTRUCTURE_DECLARATION}
    assert camera.decided_by == DECIDED_HUMAN_OVERRIDE
    assert camera.value == (6.35, 3.95)                  # 가장 나중 실측
    assert camera.entered_by == "jinnayoung"
    # 프로파일에 적힌 (6, 4) 는 지워지지 않고 미선언 정확도의 근거로 남는다.
    assert camera.without_human_value == (6.0, 4.0)
    assert camera.without_human_accuracy_m is None
    declaration_row = camera.contribution(f"declared:{ZONE}:{QUANTITY}")
    assert declaration_row.accuracy_m is None and declaration_row.weight == 0.0
    # 기준점은 정확도를 모르는 채 그대로 쓰인다 — 그럴듯한 숫자를 넣지 않는다.
    marker = zone.quantity("reference_point.n4-1f-w-door.at")
    assert marker.value == (0.0, 9.0) and marker.accuracy_m is None


def test_a_zone_with_no_survey_file_still_has_its_declared_state():
    profile = json.loads(
        (PROJECT_ROOT / "profiles" / "domains.example.json").read_text(encoding="utf-8"))
    declared = observations_from_domain_profile(profile, "rec-meander")
    surveyed = load_survey_observations(PROJECT_ROOT / "profiles" / "does_not_exist.json")

    zone = fuse_zone(declared + surveyed, zone_id="rec-meander")

    assert surveyed == ()
    assert zone.frame_id == "site:river"
    assert zone.quantity("infrastructure.pi4.at").value == (430.0, 150.0)
    # 선언만 있는 구역은 정확도를 모르는 상태로 정상 성립한다.
    assert zone.quantity("infrastructure.pi4.at").decided_by == DECIDED_UNWEIGHTED_MEAN
    assert KIND_HUMAN_SURVEY in zone.unobserved_kinds
