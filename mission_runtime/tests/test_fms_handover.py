"""implements: AI-N-03, AI-N-02, AI-C-05
tests: RSSI recomputed from the profile agrees with the profile's own radii
       (anti-drift), momentary vs sustained neighbour, requested-but-unconfirmed
       switch, unmeasured counted as unknown, same-AP boundary is no radio
       handover, cache stays usable while out of contact
"""

from pathlib import Path

import pytest

from mission_runtime.execution.mission import MissionItemOutcome
from mission_runtime.ondevice.link_handover import LinkPosture, LinkTransitionPolicy
from mission_runtime.ondevice.mission_cache import (
    CachedMissionItem,
    MissionAutonomy,
    MissionCache,
    MissionDelivery,
)
from mission_runtime.ondevice.zone_handover import (
    ZONE_CANDIDATE_BELOW_MARGIN,
    ZONE_HOLDING_SAMPLES,
    ZoneHandoverPolicy,
)
from mission_runtime.providers.rssi_link_quality import DEFAULT_MAPPING
from mission_runtime.tools.fms_console.fleet import FleetModel, load_domain_profile
from mission_runtime.tools.fms_console.handover import (
    REQUESTED_BY_LINK,
    REQUESTED_BY_POSITION,
    TRANSIT_NOT_REQUESTED,
    TRANSIT_REJECTED,
    TRANSIT_SAME_AP_BOUNDARY,
    Position,
    RadioProfileError,
    RfModel,
    ZoneRadioMap,
    ZoneTransitRuntime,
    recomputed_radii,
)

PROFILE = Path(__file__).resolve().parents[1] / "profiles" / "domains.example.json"

#: 두 AP 가 160m 떨어진 옥외 한 층. 품질 차이를 자리로 제어할 수 있어야
#: 히스테리시스를 시험할 수 있다.
OUTDOOR_RF = {
    "model": "log_distance",
    "tx_eirp_dbm": 23.0,
    "reference_loss_db_at_1m": 46.0,
    "path_loss_exponent": 2.2,
    "thresholds_dbm": {"excellent": -45.0, "handover": -75.0, "floor": -85.0},
    "radius_m": {"excellent": 10.0, "handover": 231.0, "floor": 657.9},
}


def two_zone_profile() -> dict:
    return {
        "map": {"width": 200, "height": 60, "unit": "index"},
        "domains": [{
            "domain_id": "pair",
            "label": {"en": "pair"},
            "rect": {"x": 0, "y": 0, "w": 200, "h": 60},
            "space": {"width": 200, "height": 60, "unit": "meter"},
            "rf": {"outdoor": OUTDOOR_RF},
            "zones": [
                {"zone_id": "zone-a", "label": {"en": "a"},
                 "rect": {"x": 0, "y": 0, "w": 100, "h": 60},
                 "wifi": {"ap_id": "ap-a", "at": {"x": 20, "y": 30}, "rf": "outdoor"}},
                {"zone_id": "zone-b", "label": {"en": "b"},
                 "rect": {"x": 100, "y": 0, "w": 100, "h": 60},
                 "wifi": {"ap_id": "ap-b", "at": {"x": 180, "y": 30}, "rf": "outdoor"}},
            ],
        }],
    }


def radio_of(profile: dict, domain_id: str = "pair") -> ZoneRadioMap:
    return ZoneRadioMap(FleetModel(domain_profile=profile, facts={}), domain_id)


def settled_runtime(**policy_kwargs) -> ZoneTransitRuntime:
    """zone-a 에 확인된 상태로 앉혀 둔 런타임. 전환 시험의 출발점."""
    radio = radio_of(two_zone_profile())
    runtime = ZoneTransitRuntime(radio=radio, policy=ZoneHandoverPolicy(**policy_kwargs))
    attempt = runtime.cross_to("zone-a", at=0.0, position=Position(20.0, 30.0))
    assert attempt.confirmed
    assert runtime.zone_id == "zone-a"
    return runtime


# --- 드리프트 금지: 모델에서 다시 계산한 반경이 프로파일의 반경이다 ----------------


def test_every_rf_model_in_the_profile_recomputes_its_own_radii():
    """반경을 상수로 베껴 두면 모델을 고치는 날 둘이 갈라진다 — 그 날 깨져야 한다."""
    profile = load_domain_profile(PROFILE)
    checked = 0
    for domain in profile["domains"]:
        radio = radio_of(profile, domain["domain_id"])
        for kind in radio.rf_kinds():
            model = radio.rf_model(kind)
            assert recomputed_radii(model) == dict(model.radius_m), (
                f"{domain['domain_id']}/{kind} radii drifted from its own model")
            checked += 1
    assert checked >= 4  # 네 도메인 모두 실제로 검사됐다


def test_the_handover_radius_is_exactly_where_quality_reaches_the_policy_floor():
    """세 숫자가 한 곳에서 오지 않으면 "표본은 괜찮은데 판정은 바닥"이 된다."""
    profile = load_domain_profile(PROFILE)
    floor = LinkTransitionPolicy().floor
    for domain in profile["domains"]:
        radio = radio_of(profile, domain["domain_id"])
        for kind in radio.rf_kinds():
            model = radio.rf_model(kind)
            assert model.thresholds_dbm["handover"] == -75.0
            level = model.level_dbm(model.radius_m["handover"])
            assert DEFAULT_MAPPING.quality_of_dbm(level) == pytest.approx(floor, abs=0.005)
            # floor 반경에서는 정규화 품질이 0 이다 — 거기부터는 쓸 수 없다.
            bottom = model.level_dbm(model.radius_m["floor"])
            assert DEFAULT_MAPPING.quality_of_dbm(bottom) == pytest.approx(0.0, abs=0.005)


def test_the_inverse_of_the_path_loss_model_is_the_model_itself():
    model = RfModel.from_profile("outdoor", OUTDOOR_RF)
    for distance in (1.0, 12.5, 100.0, 231.0):
        assert model.distance_m_for(model.level_dbm(distance)) == pytest.approx(distance)


def test_an_unsupported_rf_model_is_refused_rather_than_guessed():
    with pytest.raises(RadioProfileError):
        RfModel.from_profile("outdoor", {**OUTDOOR_RF, "model": "ray_tracing"})
    with pytest.raises(RadioProfileError):
        RfModel.from_profile("outdoor", {k: v for k, v in OUTDOOR_RF.items()
                                         if k != "tx_eirp_dbm"})


def test_coordinates_that_are_not_metres_are_refused():
    """반경은 m 인데 좌표가 다른 단위면 거리가 조용히 틀린다."""
    profile = two_zone_profile()
    profile["domains"][0]["space"]["unit"] = "index"
    with pytest.raises(RadioProfileError):
        radio_of(profile)


# --- 자리 → 신호 ---------------------------------------------------------------


def test_the_derived_strength_and_quality_are_exposed_per_zone_for_display():
    radio = radio_of(two_zone_profile())
    rows = {row.zone_id: row for row in radio.readings_at(Position(20.0, 30.0))}
    assert rows["zone-a"].distance_m == pytest.approx(0.0)
    assert rows["zone-a"].quality == pytest.approx(1.0)
    assert rows["zone-b"].distance_m == pytest.approx(160.0)
    # 160m 옥외는 handover 반경(231m) 안쪽이므로 아직 바닥이 아니다.
    assert rows["zone-b"].level_dbm == pytest.approx(-71.49, abs=0.01)
    assert 0.25 < rows["zone-b"].quality < 0.5
    assert set(rows["zone-a"].as_dict()) >= {"ap_id", "level_dbm", "quality", "distance_m"}


def test_a_zone_without_an_access_point_declaration_is_not_a_candidate():
    """모르는 선언을 추측해 채우면 "모르는 구역으로 넘어가지 않는다"는 보호가 사라진다."""
    profile = two_zone_profile()
    del profile["domains"][0]["zones"][1]["wifi"]
    radio = radio_of(profile)
    assert radio.ap_of("zone-b") is None
    assert [p.zone_id for p in radio.peer_observations(Position(20.0, 30.0))] == ["zone-a"]
    runtime = ZoneTransitRuntime(radio=radio)
    attempt = runtime.cross_to("zone-b", at=0.0)
    assert not attempt.confirmed and "no_access_point" in attempt.reason


def test_a_position_with_no_access_point_in_range_is_unknown_not_zero():
    # 다른 층의 AP 만 보이는 자리는 후보가 없는 것이고, 품질 0 이 아니다.
    profile = two_zone_profile()
    profile["domains"][0]["zones"][0]["level_id"] = "L1"
    profile["domains"][0]["zones"][1]["level_id"] = "L1"
    radio = radio_of(profile)
    assert radio.sample_at(Position(20.0, 30.0, "L2"), at=0.0) is None


# --- 히스테리시스: 요청은 사실이 아니다 -----------------------------------------


def test_a_momentary_better_neighbour_does_not_move_the_zone():
    """한 번 튄 값으로 구역을 바꾸면 경계마다 구성 재적용이 따라붙는다."""
    runtime = settled_runtime()
    near_b = runtime.observe_at(Position(150.0, 30.0), at=1.0)
    assert near_b.switch_to_zone is None
    assert near_b.reason.startswith(ZONE_HOLDING_SAMPLES)
    back = runtime.observe_at(Position(20.0, 30.0), at=2.0)
    assert back.reason.startswith(ZONE_CANDIDATE_BELOW_MARGIN)
    assert runtime.zone_id == "zone-a"
    assert runtime.crossings[-1].zone_id == "zone-a"
    assert runtime.policy.zone_changes == 1


def test_a_sustained_better_neighbour_does_move_the_zone():
    runtime = settled_runtime()
    attempt = runtime.cross_to("zone-b", at=1.0)
    assert attempt.requested and attempt.confirmed
    assert attempt.requested_by == REQUESTED_BY_LINK
    assert runtime.zone_id == "zone-b"
    assert runtime.attached_ap == "ap-b"
    crossing = attempt.crossing
    assert crossing is not None and crossing.previous_zone == "zone-a"
    assert crossing.radio_handover_required and crossing.config_refresh_required


def test_one_sample_is_never_enough_even_when_the_neighbour_is_much_better():
    runtime = settled_runtime()
    attempt = runtime.cross_to("zone-b", at=1.0, ticks=1)
    assert not attempt.confirmed
    assert attempt.reason.startswith(TRANSIT_NOT_REQUESTED)
    assert runtime.zone_id == "zone-a"


def test_a_requested_switch_that_is_never_confirmed_leaves_the_zone_unchanged():
    """요청과 사실을 같은 칸에 담으면 실패한 전환이 성공한 것처럼 보인다."""
    runtime = settled_runtime()
    runtime.confirm_zone_fn = lambda zone_id, at: False
    attempt = runtime.cross_to("zone-b", at=1.0)
    assert attempt.requested is True
    assert attempt.confirmed is False
    assert attempt.failed is True
    assert attempt.reason.startswith(TRANSIT_REJECTED)
    assert attempt.crossing is None
    assert runtime.zone_id == "zone-a"
    assert runtime.attached_ap == "ap-a"
    assert runtime.policy.zone_changes == 1       # 최초 진입분뿐
    assert len(runtime.failed_attempts) == 1
    assert runtime.status()["zone_id"] == "zone-a"


def test_a_rejected_switch_stays_in_the_attempt_history_next_to_the_retry():
    runtime = settled_runtime()
    runtime.confirm_zone_fn = lambda zone_id, at: False
    runtime.cross_to("zone-b", at=1.0)
    runtime.confirm_zone_fn = lambda zone_id, at: True
    second = runtime.cross_to("zone-b", at=20.0)
    history = runtime.attempts_for("zone-b")
    assert [a.attempt for a in history] == [1, 2]
    assert [a.confirmed for a in history] == [False, True]
    assert second.confirmed and runtime.zone_id == "zone-b"


# --- 측정 실패는 정상 경로다 ----------------------------------------------------


def test_an_unmeasured_sample_is_counted_as_unknown_not_as_bad_quality():
    runtime = settled_runtime()
    runtime.observe_at(Position(20.0, 30.0), at=1.0)
    for tick in range(2, 5):
        decision = runtime.observe_unmeasured(at=float(tick))
        assert decision.quality is None
    assert runtime.posture is LinkPosture.LOCAL_ONLY
    assert runtime.out_of_contact is True
    # 가짜 0.0 표본을 만들지 않았으므로 추세·마지막 품질이 오염되지 않았다.
    link = runtime.policy.transition.status()
    assert link["quality"] == pytest.approx(1.0)
    assert runtime.policy.status()["unmeasured_run"] == 3
    assert runtime.zone_id == "zone-a"


def test_an_access_point_that_vanishes_does_not_borrow_another_ones_reading():
    profile = two_zone_profile()
    radio = radio_of(profile)
    # ap-a 에 붙어 있다고 아는 상태에서 ap-a 를 선언에서 지우면 "못 쟀다"여야 한다.
    assert radio.sample_at(Position(20.0, 30.0), at=0.0, attached_ap="ap-ghost") is None


# --- 같은 AP 경계는 무선 전환이 아니다 -------------------------------------------


def test_crossing_a_same_access_point_boundary_reports_no_radio_handover():
    """옥외에서는 한 AP 가 여러 구역을 덮는다. 구역을 넘었다고 재접속한 것이 아니다."""
    radio = ZoneRadioMap.from_profile(PROFILE, "river")
    assert radio.ap_of("rec-straight").ap_id == radio.ap_of("rec-steep").ap_id
    assert radio.radio_handover_required("rec-straight", "rec-steep") is False

    runtime = ZoneTransitRuntime(radio=radio)
    assert runtime.cross_to("rec-straight", at=0.0).confirmed
    before = runtime.attached_ap
    attempt = runtime.cross_to("rec-steep", at=10.0)

    assert attempt.confirmed
    assert attempt.requested_by == REQUESTED_BY_POSITION
    assert attempt.reason.startswith(TRANSIT_SAME_AP_BOUNDARY)
    assert attempt.radio_handover_required is False
    crossing = attempt.crossing
    assert crossing.radio_handover_required is False
    assert crossing.as_dict()["reconnect_required"] is False
    # 선언된 외부 구성(AP·RF·엣지·층)이 그대로라 다시 받을 것이 없다(AI-N-02).
    assert crossing.config_refresh_required is False
    # 정책이 내놓은 원래 신호는 숨기지 않는다.
    assert crossing.entry.requires_config_refresh is True
    assert runtime.attached_ap == before
    assert runtime.zone_id == "rec-steep"


def test_crossing_to_a_different_access_point_does_require_one():
    radio = ZoneRadioMap.from_profile(PROFILE, "river")
    assert radio.radio_handover_required("rec-steep", "rec-meander") is True
    runtime = ZoneTransitRuntime(radio=radio)
    runtime.cross_to("rec-straight", at=0.0)
    runtime.cross_to("rec-steep", at=10.0)
    attempt = runtime.cross_to("rec-meander", at=20.0)
    assert attempt.confirmed and attempt.radio_handover_required is True
    assert attempt.crossing.config_refresh_required is True
    assert runtime.attached_ap == "ap-rec-east"


def test_a_same_access_point_boundary_is_still_refusable_by_the_provider():
    """지름길이 provider 경계를 우회해서는 안 된다 — 사실은 여전히 provider 가 낸다."""
    radio = ZoneRadioMap.from_profile(PROFILE, "river")
    runtime = ZoneTransitRuntime(radio=radio)
    runtime.cross_to("rec-straight", at=0.0)
    runtime.confirm_zone_fn = lambda zone_id, at: False
    attempt = runtime.cross_to("rec-steep", at=10.0)
    assert attempt.requested and not attempt.confirmed and attempt.failed
    assert runtime.zone_id == "rec-straight"


def test_an_indoor_floor_boundary_is_a_radio_handover_and_a_config_refresh():
    radio = ZoneRadioMap.from_profile(PROFILE, "college")
    assert radio.radio_handover_required("N4-1F-W", "N4-1F-E") is True
    assert radio.config_refresh_required("N4-1F-W", "N4-1F-E") is True


# --- 링크가 없는 동안에도 로컬은 돈다 (AI-N-01, AI-N-03) --------------------------


def cached_runtime() -> tuple[ZoneTransitRuntime, MissionCache]:
    cache = MissionCache()
    result = cache.apply(MissionDelivery(
        mission_id="m-1", version=1, full=True, origin_command_id="cmd-1",
        approved_by="operator-1",
        items=(
            CachedMissionItem(item_id="keep-going", required=True, order_index=0,
                              action="observe_close",
                              autonomy=MissionAutonomy.AUTONOMOUS_WHEN_CACHED),
            CachedMissionItem(item_id="needs-order", required=False, order_index=1,
                              action="grasp_object",
                              autonomy=MissionAutonomy.REQUIRES_FRESH_COMMAND),
        ),
    ))
    assert result.accepted
    runtime = settled_runtime()
    runtime.cache = cache
    return runtime, cache


def test_the_cache_still_answers_while_out_of_contact():
    runtime, cache = cached_runtime()
    for tick in range(1, 5):
        runtime.observe_unmeasured(at=float(tick))
    assert runtime.out_of_contact is True

    state = runtime.cache_state()
    assert state["out_of_contact"] is True
    assert state["mission_id"] == "m-1"
    assert state["origin_command_id"] == "cmd-1"
    # 발급자가 허가해 둔 항목은 링크가 없어도 그대로 남는다 — 링크 상태가 허가를
    # 좁히면 연결이 없는 동안 로컬이 멈춘다(AI-N-01, AI-N-03).
    assert state["resumable_without_link"] == ["keep-going"]
    assert state["blocked_pending_command"] == ["needs-order"]
    assert state["autonomy_block_reason"] is None
    assert state["safety_suspended"] is False


def test_the_runtime_never_suspends_the_cache_on_its_own():
    """링크 단절은 안전 정지가 아니다. 정지는 안전 경로만 선언한다(AI-C-20)."""
    runtime, cache = cached_runtime()
    for tick in range(1, 10):
        runtime.observe_unmeasured(at=float(tick))
    assert cache.safety_suspended is False
    cache.begin("keep-going")
    cache.complete("keep-going", MissionItemOutcome.SUCCEEDED)
    assert runtime.cache_state()["completed"] == ["keep-going"]


def test_a_local_safety_suspension_is_visible_but_not_caused_here():
    runtime, cache = cached_runtime()
    cache.suspend_for_safety("obstacle_within_stopping_distance")
    state = runtime.cache_state()
    assert state["safety_suspended"] is True
    assert state["resumable_without_link"] == []
    assert state["autonomy_block_reason"] is not None


def test_no_cache_is_a_normal_configuration():
    runtime = settled_runtime()
    assert runtime.cache_state() is None
    assert runtime.status()["cache"] is None


# --- 상태 ---------------------------------------------------------------------


def test_zone_transit_is_reported_as_its_own_signal():
    runtime = settled_runtime()
    runtime.observe_at(Position(150.0, 30.0), at=1.0)
    status = runtime.status()
    assert status["signal"] == "zone_transit"
    # 구역 전환·링크 품질·임무 캐시는 서로 다른 신호다. 한 칸에 합치지 않는다.
    assert status["zone_handover"]["signal"] == "zone_handover"
    assert status["link_quality"]["signal"] == "link_quality"
    assert status["zone_id"] == "zone-a"
    assert status["containing_zone"] == "zone-b"
    assert status["in_transit"] is True
    assert status["decision"]["readings"]
    assert status["attached_ap"] == "ap-a"


def test_the_same_observations_produce_the_same_status():
    def drive():
        runtime = settled_runtime()
        runtime.cross_to("zone-b", at=1.0)
        return runtime.status()["crossings"]

    assert drive() == drive()
