"""RSSI 로 본 자리 — 점이 아니라 영역이고, 모르면 모른다고 한다.

implements: AI-N-03, AI-S-02, AI-S-03, AI-C-02, AI-E-04
tests: 모델 계수가 데이터에서 온다 · AP 한 대는 방향을 못 낸다 · 미측정 ≠ 0 ≠ 범위 밖 ·
       덮임 판정이 데이터에서 계산된다 · radio_range 단서가 실제로 채워진다 ·
       흔들림이 크면 1 위를 고르지 않는다

이 시험들이 지키는 것은 성능이 아니라 **거짓말을 하지 않는 것**이다. RSSI 추정은
어차피 거칠다 — 거친 것을 거칠다고 말하는지가 시험 대상이고, 숫자가 작아지는지가
아니다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from mission_runtime.perception.device_identity import (
    CueKind,
    DeviceIdentityResolver,
    REQUEST_ENABLE_RADIO_RANGING as IDENTITY_REQUEST_RANGING,
    Verdict,
    appearance_cue,
)
from mission_runtime.perception.rssi_localization import (
    AP_PLACEMENT_FIELD,
    CUE_BEYOND_FLOOR,
    CUE_FRAME_MISMATCH,
    CUE_OK,
    CUE_UNMEASURED,
    COORDINATE_FRAME,
    FLOOR_THRESHOLD,
    Anchor,
    BeliefState,
    Geometry,
    RadioMap,
    RangeState,
    REASON_OUT_OF_MAP,
    REQUEST_ADD_ANCHOR,
    REQUEST_ENABLE_RADIO_RANGING,
    REQUEST_SURVEY_AP_PLACEMENT,
    RssiLocalizer,
    ZoneExtent,
    radio_range_cue_for_track,
    radio_range_cues,
)
from mission_runtime.providers.rssi_link_quality import (
    DEFAULT_SHADOWING_SIGMA_DB,
    LogDistancePathLoss,
    RadioModelError,
    REASON_SOURCE_UNAVAILABLE,
    RssiReading,
    SIGMA_BASIS_DECLARED,
    SIGMA_BASIS_UNMEASURED,
    SHADOWING_SIGMA_KEY,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_PROFILE = PROJECT_ROOT / "profiles" / "domains.json"
AP_ID = "ap-n4-5f"
ZONE_ID = "zone-503"


@pytest.fixture(scope="module")
def shipped() -> dict:
    return json.loads(SHIPPED_PROFILE.read_text(encoding="utf-8"))


@pytest.fixture
def shipped_map(shipped) -> RadioMap:
    return RadioMap.from_domain_profile(shipped)


def _rf(shipped) -> dict:
    return shipped["domains"][0]["rf"]["indoor"]


def _reading(level_dbm: float | None = None, *, peer_id: str = AP_ID,
             at: float = 1000.0, reason: str | None = None) -> RssiReading:
    return RssiReading(peer_id=peer_id, source="test", at=at,
                       level_dbm=level_dbm, reason=reason)


# ---------------------------------------------------------------------------
# 1. 모델 계수는 데이터에서 온다
# ---------------------------------------------------------------------------


def test_the_inversion_reproduces_the_radius_the_profile_declared(shipped):
    """역산한 반경 == 프로파일이 적어 둔 `radius_m`.

    프로파일의 반경은 같은 파일의 계수에서 **유도된 값**이다. 코드가 반경을 베껴
    두면 계수를 고치는 날 둘이 갈라지고 화면은 어느 쪽이 참인지 말할 수 없다.
    """
    raw = _rf(shipped)
    model = LogDistancePathLoss.from_profile("indoor", raw)
    for name, declared in raw["radius_m"].items():
        assert model.radius_for_threshold(name) == pytest.approx(declared, abs=0.05), name


def test_the_same_inversion_as_the_zone_handover_tool(shipped):
    """같은 식의 복사본이 두 곳에 있다 — 숫자가 갈라지면 여기서 잡힌다.

    `tools/fms_console/handover.py::RfModel` 은 구역 핸드오버 입력을 만들면서 같은
    log-distance 식을 쓴다. 공개 패키지가 도구 디렉터리를 import 하지 않기 위해
    구현이 둘인데, 둘이 조용히 갈라지면 콘솔과 추정기가 서로 다른 거리를 말한다.
    """
    from mission_runtime.tools.fms_console.handover import RfModel

    raw = _rf(shipped)
    mine = LogDistancePathLoss.from_profile("indoor", raw)
    theirs = RfModel.from_profile("indoor", raw)
    for level in (-30.0, -45.0, -60.0, -75.0, -85.0):
        assert mine.distance_m_for(level) == pytest.approx(theirs.distance_m_for(level))
    for distance in (1.0, 5.0, 25.1, 48.5):
        assert mine.level_dbm(distance) == pytest.approx(theirs.level_dbm(distance))


@pytest.mark.parametrize("key,bumped", [
    ("path_loss_exponent", 4.5),
    ("tx_eirp_dbm", 26.0),
    ("reference_loss_db_at_1m", 40.0),
])
def test_changing_a_coefficient_changes_the_answer(shipped, key, bumped):
    """계수가 바뀌면 결과가 **따라 바뀐다**(하드코딩이 아니다).

    닫힌 형태로 다시 계산한 값과 맞는지까지 본다 — "바뀌었다" 만 보면 아무 숫자나
    바뀌어도 통과한다.
    """
    raw = dict(_rf(shipped))
    base = LogDistancePathLoss.from_profile("indoor", raw)
    raw[key] = bumped
    changed = LogDistancePathLoss.from_profile("indoor", raw)

    level = -70.0
    assert changed.distance_m_for(level) != pytest.approx(base.distance_m_for(level))
    budget = (changed.tx_eirp_dbm - changed.reference_loss_db_at_1m - level)
    expected = 10.0 ** (budget / (10.0 * changed.path_loss_exponent))
    assert changed.distance_m_for(level) == pytest.approx(expected)


def test_a_bigger_exponent_shrinks_every_radius(shipped):
    """n 이 커지면(차폐가 심하면) 같은 세기가 **더 가까운** 거리를 뜻한다."""
    raw = dict(_rf(shipped))
    soft = LogDistancePathLoss.from_profile("indoor", {**raw, "path_loss_exponent": 2.0})
    hard = LogDistancePathLoss.from_profile("indoor", {**raw, "path_loss_exponent": 4.5})
    assert hard.radius_for_threshold(FLOOR_THRESHOLD) < soft.radius_for_threshold(FLOOR_THRESHOLD)


def test_an_unknown_rf_model_is_refused(shipped):
    """모르는 모델 이름은 조용히 log-distance 로 떨어지지 않는다."""
    raw = {**_rf(shipped), "model": "free_space"}
    with pytest.raises(RadioModelError):
        LogDistancePathLoss.from_profile("indoor", raw)


def test_a_nonpositive_exponent_is_refused(shipped):
    with pytest.raises(RadioModelError):
        LogDistancePathLoss.from_profile("indoor", {**_rf(shipped),
                                                    "path_loss_exponent": 0.0})


# ---------------------------------------------------------------------------
# 2. 흔들림은 계수가 아니라 분산이고, 미실측임을 들고 다닌다
# ---------------------------------------------------------------------------


def test_the_shipped_profile_does_not_declare_a_shadowing_sigma(shipped):
    """지금 프로파일에 σ 가 **없다** — 그래서 모든 추정이 미실측 기본값을 쓴다.

    이 시험은 실패하면 고쳐야 할 시험이 아니라 **좋은 소식**이다: 현장에서 σ 를
    재어 프로파일에 적는 날 여기가 깨지고, 그때 basis 가 declared 로 바뀐다.
    """
    assert SHADOWING_SIGMA_KEY not in _rf(shipped)
    model = LogDistancePathLoss.from_profile("indoor", _rf(shipped))
    assert model.shadowing_basis == SIGMA_BASIS_UNMEASURED
    assert model.shadowing_sigma_db == DEFAULT_SHADOWING_SIGMA_DB


def test_a_declared_sigma_is_marked_as_declared(shipped):
    model = LogDistancePathLoss.from_profile(
        "indoor", {**_rf(shipped), SHADOWING_SIGMA_KEY: 3.0})
    assert model.shadowing_basis == SIGMA_BASIS_DECLARED
    assert model.shadowing_sigma_db == 3.0


def test_the_distance_interval_is_multiplicative_not_symmetric(shipped):
    """dB 의 덧셈 오차는 거리의 **곱셈 오차**다 — 구간이 대칭이 아니다."""
    model = LogDistancePathLoss.from_profile("indoor", _rf(shipped))
    centre = model.distance_m_for(-75.0)
    lower, upper = model.distance_bounds_for(-75.0, k_sigma=1.0)
    assert lower < centre < upper
    # 비율이 양쪽에서 같다. 즉 centre - lower != upper - centre.
    assert centre / lower == pytest.approx(upper / centre)
    assert (centre - lower) != pytest.approx(upper - centre)


def test_a_bigger_sigma_widens_the_interval_and_the_region(shipped, shipped_map):
    """σ 가 크면 구간도 영역도 넓어진다. 좁은 영역은 σ 가 작을 때만 나온다."""
    tight_raw = {**_rf(shipped), SHADOWING_SIGMA_KEY: 2.0}
    loose_raw = {**_rf(shipped), SHADOWING_SIGMA_KEY: 9.0}
    tight = LogDistancePathLoss.from_profile("indoor", tight_raw)
    loose = LogDistancePathLoss.from_profile("indoor", loose_raw)
    tl, tu = tight.distance_bounds_for(-70.0)
    ll, lu = loose.distance_bounds_for(-70.0)
    assert (lu - ll) > (tu - tl)

    anchor = shipped_map.anchors[0]
    reading = _reading(-70.0)
    areas = []
    for model in (tight, loose):
        narrow_map = RadioMap(
            domain_id=shipped_map.domain_id, frame_id=shipped_map.frame_id,
            anchors=(Anchor(anchor.ap_id, anchor.at, anchor.frame_id, model,
                            anchor.zone_ids, anchor.placement_verified,
                            anchor.placement_basis),),
            zones=shipped_map.zones)
        belief = RssiLocalizer(narrow_map).locate([reading])
        areas.append(belief.region.area_m2)
    assert areas[1] > areas[0]


# ---------------------------------------------------------------------------
# 3. AP 가 한 대라는 사실이 결과에 적혀 나간다
# ---------------------------------------------------------------------------


def test_the_shipped_site_declares_exactly_one_access_point(shipped_map):
    """이 현장은 한 대짜리다. 아래 시험들이 다루는 제약의 전제다."""
    assert [a.ap_id for a in shipped_map.anchors] == [AP_ID]


def test_a_single_access_point_never_resolves_a_bearing(shipped_map):
    """한 대로는 **거리만** 나온다. 점을 지어내지 않는다."""
    belief = RssiLocalizer(shipped_map).locate([_reading(-70.0)])
    assert belief.state is BeliefState.LOCATED
    assert belief.geometry is Geometry.RANGE_ONLY
    assert belief.anchor_count == 1
    assert belief.bearing_resolved is False
    # 영역은 고리다 — 질량 가중 중심이 영역 안에 **없다**. 그 중심을 "위치" 로 쓰면
    # 로봇은 AP 바로 위에 있는 것으로 그려진다.
    assert belief.region.centroid_inside is False
    assert belief.region.centroid_at[0] == pytest.approx(shipped_map.anchors[0].at[0], abs=2.0)
    # 그리고 AP 양쪽에 모두 질량이 있다 — 방향이 가려지지 않았다는 기하적 표현.
    xs = [c[0] for c in belief.region.cells]
    ap_x = shipped_map.anchors[0].at[0]
    assert min(xs) < ap_x < max(xs)


def test_a_single_access_point_always_asks_for_another(shipped_map):
    """막힌 사유를 감추지 않는다 — 한 대짜리 현장에서 이 요청은 늘 서 있다."""
    belief = RssiLocalizer(shipped_map).locate([_reading(-70.0)])
    assert REQUEST_ADD_ANCHOR in belief.resolution_requests
    # AP 자리가 실측이 아니므로 실측 요청도 함께 선다.
    assert REQUEST_SURVEY_AP_PLACEMENT in belief.resolution_requests


def test_one_access_point_covering_one_zone_discriminates_no_zone(shipped_map):
    """한 대가 구역 하나를 통째로 덮으면 구역 확률은 **아무 것도 가르지 못한다**.

    질량이 그 구역에 1.0 으로 몰리는 것은 추정이 좋아서가 아니라 고를 것이 없어서다.
    그 사실이 산출물에 그대로 보이는 쪽이 "확률 1.0" 을 자신감으로 읽히는 쪽보다 낫다.
    """
    belief = RssiLocalizer(shipped_map).locate([_reading(-70.0)])
    assert belief.zone_posterior == {ZONE_ID: pytest.approx(1.0)}
    assert belief.most_likely_zone == ZONE_ID
    assert belief.geometry is Geometry.RANGE_ONLY  # 1.0 이어도 방향은 없다


# --- 여러 대가 있을 때는 달라진다 (같은 코드, 데이터만 다름) ------------------


def _multi_anchor_map(shipped, *, count: int) -> RadioMap:
    """같은 RF 모델을 쓰는 AP 를 여러 대 선언한 지도. **코드 분기가 아니라 데이터다**."""
    model = LogDistancePathLoss.from_profile("indoor", _rf(shipped))
    frame = "site:test-multi"
    places = {
        "ap-a": (5.0, 5.0),
        "ap-b": (45.0, 5.0),
        "ap-c": (25.0, 40.0),
    }
    anchors = tuple(
        Anchor(ap_id=ap_id, at=at, frame_id=frame, model=model,
               zone_ids=("zone-test",), placement_verified=True,
               placement_basis="surveyed")
        for ap_id, at in list(places.items())[:count])
    return RadioMap(domain_id="test-multi", frame_id=frame, anchors=anchors,
                    zones=(ZoneExtent("zone-test", frame, (0.0, 0.0, 50.0, 45.0),
                                      level_id="L1", verified=True),))


def _noiseless_readings(radio_map: RadioMap, truth: tuple[float, float], at: float = 7.0):
    return [
        RssiReading(peer_id=a.ap_id, source="synthetic", at=at,
                    level_dbm=a.model.level_dbm(a.distance_to(truth)))
        for a in radio_map.anchors
    ]


def test_two_access_points_leave_a_mirror_ambiguity(shipped):
    """두 대는 두 고리가 두 점에서 만난다 — 거울상이 남고 그 사실을 이름으로 낸다."""
    radio_map = _multi_anchor_map(shipped, count=2)
    truth = (20.0, 30.0)
    belief = RssiLocalizer(radio_map, grid_step_m=0.5).locate(
        _noiseless_readings(radio_map, truth))
    assert belief.geometry is Geometry.TWO_LOBED
    assert belief.bearing_resolved is False
    # 두 lobe 가 y 축 양쪽으로 갈린다 — 영역이 거울상을 모두 품는다.
    ys = [c[1] for c in belief.region.cells]
    assert max(ys) - min(ys) > 20.0


def test_three_access_points_bound_the_region(shipped):
    """세 대면 영역이 닫히고 진짜 자리를 품는다. 같은 코드, 데이터만 늘었다."""
    radio_map = _multi_anchor_map(shipped, count=3)
    truth = (20.0, 30.0)
    belief = RssiLocalizer(radio_map, grid_step_m=0.5).locate(
        _noiseless_readings(radio_map, truth))
    assert belief.geometry is Geometry.BOUNDED
    assert belief.bearing_resolved is True
    assert belief.region.centroid_inside is True
    assert math.dist(belief.region.peak_at, truth) <= 1.0
    # 그래도 점이 아니다 — 영역은 여전히 넓다(σ=6dB 가 하는 일).
    assert belief.region.area_m2 > 1.0


def test_more_anchors_shrink_the_region(shipped):
    """한 대 → 두 대 → 세 대로 갈수록 영역이 작아진다(값이 데이터를 따른다)."""
    truth = (20.0, 30.0)
    areas = []
    for count in (1, 2, 3):
        radio_map = _multi_anchor_map(shipped, count=count)
        belief = RssiLocalizer(radio_map, grid_step_m=0.5).locate(
            _noiseless_readings(radio_map, truth))
        areas.append(belief.region.area_m2)
    assert areas[0] > areas[1] > areas[2]


# ---------------------------------------------------------------------------
# 4. 미측정 ≠ 0 ≠ 범위 밖
# ---------------------------------------------------------------------------


def test_the_three_states_are_three_different_states(shipped_map):
    localizer = RssiLocalizer(shipped_map)
    unmeasured = localizer.range_for(_reading(reason=REASON_SOURCE_UNAVAILABLE))
    in_range = localizer.range_for(_reading(-70.0))
    beyond = localizer.range_for(_reading(-90.0))
    assert len({unmeasured.state, in_range.state, beyond.state}) == 3
    assert unmeasured.state is RangeState.UNMEASURED
    assert in_range.state is RangeState.IN_RANGE
    assert beyond.state is RangeState.BEYOND_FLOOR


def test_no_measurement_is_none_and_never_zero(shipped_map):
    """재지 못한 것을 0 으로 채우면 "아주 가깝다" 가 된다 — 최악의 거짓말이다."""
    estimate = RssiLocalizer(shipped_map).range_for(
        _reading(reason=REASON_SOURCE_UNAVAILABLE))
    assert estimate.measured is False
    assert estimate.range_m is None
    assert estimate.lower_m is None and estimate.upper_m is None
    assert estimate.lower_bound_m is None
    assert estimate.half_width_m is None
    assert estimate.reason == REASON_SOURCE_UNAVAILABLE


def test_no_measurement_yields_no_region_and_no_zero_mass(shipped_map):
    """구역 확률이 **빈 사전**이다. {구역: 0.0} 이면 "그 구역에 없다" 로 읽힌다."""
    belief = RssiLocalizer(shipped_map).locate(
        [_reading(reason=REASON_SOURCE_UNAVAILABLE)])
    assert belief.state is BeliefState.UNMEASURED
    assert belief.geometry is Geometry.NONE
    assert belief.region is None
    assert belief.zone_posterior == {}
    assert belief.most_likely_zone is None
    assert belief.anchor_count == 0
    assert belief.fit_residual_sigma is None
    assert REQUEST_ENABLE_RADIO_RANGING in belief.resolution_requests


def test_no_reading_at_all_is_also_unmeasured(shipped_map):
    belief = RssiLocalizer(shipped_map).locate([])
    assert belief.state is BeliefState.UNMEASURED
    assert belief.region is None
    assert belief.zone_posterior == {}


def test_below_the_receive_floor_is_a_lower_bound_not_a_distance(shipped_map):
    """바닥 아래 dBm 은 수신기 한계에 눌린 값이다 — 환산하면 거짓말이 된다."""
    estimate = RssiLocalizer(shipped_map).range_for(_reading(-95.0))
    assert estimate.state is RangeState.BEYOND_FLOOR
    assert estimate.measured is True          # 쟀다. 못 쓴 것이 아니다.
    assert estimate.range_m is None           # 그래도 점 추정은 내지 않는다
    assert estimate.lower_bound_m == pytest.approx(
        shipped_map.anchors[0].floor_radius_m)
    assert estimate.level_dbm == -95.0        # 원본 측정은 버리지 않는다


def test_below_the_floor_does_not_ask_to_turn_ranging_on(shipped_map):
    """이미 재고 있는 무선 측정을 다시 켜라고 요청하지 않는다."""
    belief = RssiLocalizer(shipped_map).locate([_reading(-95.0)])
    assert REQUEST_ENABLE_RADIO_RANGING not in belief.resolution_requests
    assert belief.geometry is Geometry.NONE   # 거리가 없으므로 기하도 없다


def test_an_unknown_access_point_is_not_a_distance_of_zero(shipped_map):
    """AP 자리를 모르면 거리를 지어내지 않는다."""
    estimate = RssiLocalizer(shipped_map).range_for(
        _reading(-60.0, peer_id="ap-not-declared"))
    assert estimate.state is RangeState.UNMEASURED
    assert estimate.range_m is None
    assert "ap-not-declared" in estimate.reason


def test_a_driver_percentage_alone_cannot_become_a_distance(shipped_map):
    """`nmcli` 백분율만 있는 장비에서는 거리를 내지 않는다.

    대상 하드웨어(pi6·pi2)에는 `/proc/net/wireless` 가 없는 경로가 있고 그때 읽히는
    것은 드라이버가 이미 환산한 0~100 백분율뿐이다. 그 역함수는 드라이버마다 다르다 —
    되돌려 dBm 으로 가정하면 거리는 **드라이버 구현을 믿은 숫자**가 된다. 링크 품질로는
    충분하지만(그쪽은 순서 관계만 필요하다) 거리로는 쓸 수 없고, 그 차이가 여기서
    `UNMEASURED` 로 갈린다.
    """
    percent_only = RssiReading(peer_id=AP_ID, source="rssi_network_manager_scan",
                               at=1000.0, signal_percent=72.0)
    assert percent_only.measured is True        # 링크 품질로는 쓸 수 있다
    estimate = RssiLocalizer(shipped_map).range_for(percent_only)
    assert estimate.state is RangeState.UNMEASURED   # 거리로는 쓸 수 없다
    assert estimate.range_m is None


def test_a_measurement_no_cell_can_explain_is_refused(shipped_map):
    """지도의 어느 칸과도 맞지 않으면 억지로 맞춘 영역을 내지 않는다."""
    belief = RssiLocalizer(shipped_map).locate([_reading(0.0)])
    assert belief.state is BeliefState.OUT_OF_MAP
    assert belief.region is None
    assert belief.zone_posterior == {}
    assert belief.reason.startswith(REASON_OUT_OF_MAP)
    assert belief.fit_residual_sigma > 3.0


# ---------------------------------------------------------------------------
# 5. 덮임 판정은 데이터에서 계산된다 (상수 55.7 도 48.5 도 코드에 없다)
# ---------------------------------------------------------------------------


def test_coverage_numbers_come_from_the_model_not_from_constants(shipped, shipped_map):
    """바닥 반경은 선언된 반경을 읽은 것이 아니라 계수에서 다시 계산한 값이다."""
    assessment, = shipped_map.coverage()
    model = LogDistancePathLoss.from_profile("indoor", _rf(shipped))
    assert assessment.floor_radius_m == pytest.approx(
        model.radius_for_threshold(FLOOR_THRESHOLD))
    anchor = shipped_map.anchors[0]
    zone = shipped_map.zone(ZONE_ID)
    assert assessment.max_corner_distance_m == pytest.approx(
        max(anchor.distance_to(c) for c in zone.corners()))


def test_the_declared_placement_covers_the_floor_but_was_never_surveyed(shipped_map):
    """지금 덮인다는 결론은 **편의로 고른 자리** 덕분이다. 그 사실을 함께 낸다.

    프로파일 선언문이 적는 대로다 — "복도 교차점에 두면 먼 모서리가 바닥 반경 밖이라
    지금은 덮이는 자리에 선언해 두었다". 그래서 `covered` 와 `placement_verified` 는
    한 칸에 합치지 않는다.
    """
    assessment, = shipped_map.coverage()
    assert assessment.covered is True
    assert assessment.uncovered_corners == ()
    assert assessment.placement_verified is False
    assert AP_PLACEMENT_FIELD in assessment.placement_basis


def test_the_profile_still_lists_the_access_point_placement_as_unverified(shipped):
    assert AP_PLACEMENT_FIELD in shipped["domains"][0]["site"]["unverified_fields"]


def test_moving_the_access_point_to_a_corridor_corner_leaves_corners_uncovered(
        shipped, shipped_map):
    """그 자리를 복도 쪽으로 옮기면 먼 모서리가 바닥 반경 밖으로 나간다.

    숫자를 코드에 적지 않고 계산해서 확인한다 — 그래야 계수나 구역 크기가 바뀌어도
    이 시험이 같은 사실을 계속 본다.
    """
    anchor = shipped_map.anchors[0]
    corridor_at = (44.85, 13.74)   # 520호 앞문 — 동편 복도. 프로파일의 랜드마크다.
    moved = RadioMap(
        domain_id=shipped_map.domain_id, frame_id=shipped_map.frame_id,
        anchors=(Anchor(anchor.ap_id, corridor_at, anchor.frame_id, anchor.model,
                        anchor.zone_ids, anchor.placement_verified,
                        anchor.placement_basis),),
        zones=shipped_map.zones)
    assessment, = moved.coverage()
    assert assessment.uncovered_corners != ()
    assert assessment.covered is False
    assert assessment.max_corner_distance_m > assessment.floor_radius_m


def test_coverage_does_not_claim_cover_without_a_declared_floor(shipped, shipped_map):
    """바닥 문턱을 선언하지 않았으면 덮인다고 **주장하지 않는다**(미측정 ≠ 덮임)."""
    raw = {k: v for k, v in _rf(shipped).items() if k != "thresholds_dbm"}
    model = LogDistancePathLoss.from_profile("indoor", raw)
    anchor = shipped_map.anchors[0]
    silent = RadioMap(
        domain_id=shipped_map.domain_id, frame_id=shipped_map.frame_id,
        anchors=(Anchor(anchor.ap_id, anchor.at, anchor.frame_id, model,
                        anchor.zone_ids, True, "surveyed"),),
        zones=shipped_map.zones)
    assessment, = silent.coverage()
    assert assessment.floor_radius_m is None
    assert assessment.covered is False


# ---------------------------------------------------------------------------
# 6. 좌표계는 끝까지 붙어 다니고 전역을 주장하지 않는다 (AI-C-02)
# ---------------------------------------------------------------------------


def test_every_value_carries_its_local_frame(shipped_map):
    belief = RssiLocalizer(shipped_map).locate([_reading(-70.0)])
    assert belief.frame_id == f"site:{shipped_map.domain_id}"
    body = belief.as_dict()
    assert body["coordinate_frame"] == COORDINATE_FRAME == "ZONE"
    assert body["frame_id"] == belief.frame_id
    assert all(r["frame_id"] == belief.frame_id for r in body["ranges"])


def test_the_belief_never_emits_a_global_position(shipped_map):
    """이 현장 datum 은 `verified: false` 다 — 전역 값을 만들지 않는다."""
    body = RssiLocalizer(shipped_map).locate([_reading(-70.0)]).as_dict()
    assert "global_position" not in body
    assert body["coordinate_frame"] != "GLOBAL"


def test_a_global_frame_name_is_refused(shipped):
    with pytest.raises(RadioModelError):
        RadioMap.from_domain_profile(shipped, frame_id="wgs84")


def test_the_site_datum_is_still_unverified(shipped):
    """전역 계층이 비활성인 전제. 검증되는 날 이 시험이 깨지고 그때 다시 생각한다."""
    assert shipped["domains"][0]["site"]["datum"]["verified"] is False


# ---------------------------------------------------------------------------
# 7. device_identity 의 `radio_range` 단서를 실제로 채운다 (AI-S-02)
# ---------------------------------------------------------------------------


def _belief_for(shipped_map, level_dbm: float, *, sigma_db: float | None = None,
                at: float = 1000.0):
    radio_map = shipped_map
    if sigma_db is not None:
        anchor = shipped_map.anchors[0]
        model = LogDistancePathLoss(
            kind=anchor.model.kind, tx_eirp_dbm=anchor.model.tx_eirp_dbm,
            reference_loss_db_at_1m=anchor.model.reference_loss_db_at_1m,
            path_loss_exponent=anchor.model.path_loss_exponent,
            shadowing_sigma_db=sigma_db, shadowing_basis=SIGMA_BASIS_DECLARED,
            thresholds_dbm=anchor.model.thresholds_dbm,
            declared_radius_m=anchor.model.declared_radius_m)
        radio_map = RadioMap(
            domain_id=shipped_map.domain_id, frame_id=shipped_map.frame_id,
            anchors=(Anchor(anchor.ap_id, anchor.at, anchor.frame_id, model,
                            anchor.zone_ids, anchor.placement_verified,
                            anchor.placement_basis),),
            zones=shipped_map.zones)
    return RssiLocalizer(radio_map).locate([_reading(level_dbm, at=at)]), radio_map


def test_the_radio_range_cue_is_actually_filled(shipped_map):
    """`radio_range` 는 더 이상 빈 자리가 아니다 — 측정이 그 칸을 채운다."""
    anchor = shipped_map.anchors[0]
    track_at = (anchor.at[0] + 10.0, anchor.at[1])
    level = anchor.model.level_dbm(10.0)
    belief, _ = _belief_for(shipped_map, level, sigma_db=2.0)
    outcome = radio_range_cue_for_track(
        belief, device_id="go1-001", track_id="track-7", track_at=track_at,
        track_frame_id=shipped_map.frame_id, anchor=anchor)
    assert outcome.reason == CUE_OK
    assert outcome.cue is not None
    assert outcome.cue.kind is CueKind.RADIO_RANGE
    assert outcome.cue.discriminating is True
    assert outcome.cue.strength > 0.9
    assert outcome.expected_m == pytest.approx(10.0)
    # 허용 오차는 이 모듈이 정한 상수가 아니라 **그 측정의 kσ 반폭**이다.
    estimate = belief.ranges[0]
    assert outcome.tolerance_m == pytest.approx(estimate.half_width_m)
    # 원본 측정 참조가 단서까지 따라간다(AI-S-06).
    assert outcome.cue.frame_ref == estimate.frame_ref


def test_a_sharp_measurement_discriminates_between_two_lookalike_tracks(shipped_map):
    """같은 기종 두 대 — 외형은 못 가리고 무선 거리가 가린다."""
    anchor = shipped_map.anchors[0]
    near_at = (anchor.at[0] + 6.0, anchor.at[1])
    resolver = DeviceIdentityResolver()

    beliefs = {}
    for device_id, true_range in (("go1-001", 6.0), ("go1-002", 30.0)):
        belief, _ = _belief_for(shipped_map, anchor.model.level_dbm(true_range),
                                sigma_db=1.0)
        beliefs[device_id] = belief

    outcomes = radio_range_cues(
        beliefs, track_id="track-7", track_at=near_at,
        track_frame_id=shipped_map.frame_id, anchor=anchor)
    cues = [o.cue for o in outcomes if o.cue is not None]
    cues += list(appearance_cue(["go1-001", "go1-002"], observed_at=1000.0,
                                source="cam-1", confidence=0.9,
                                robot_class="quadruped", frame_ref="frame-1"))
    verdict = resolver.resolve("track-7", cues)
    assert verdict.verdict is Verdict.CONFIRMED
    assert verdict.device_id == "go1-001"


def _verdict_for_separation(shipped_map, *, sigma_db: float, separation_m: float):
    """두 후보가 `separation_m` 만큼 떨어져 있을 때의 판정. 측정은 각자의 참값이다."""
    anchor = shipped_map.anchors[0]
    near_range = 12.0
    track_at = (anchor.at[0] + near_range, anchor.at[1])
    beliefs = {}
    for device_id, true_range in (("go1-001", near_range),
                                  ("go1-002", near_range + separation_m)):
        belief, _ = _belief_for(shipped_map, anchor.model.level_dbm(true_range),
                                sigma_db=sigma_db)
        beliefs[device_id] = belief
    outcomes = radio_range_cues(
        beliefs, track_id="track-7", track_at=track_at,
        track_frame_id=shipped_map.frame_id, anchor=anchor)
    cues = [o.cue for o in outcomes if o.cue is not None]
    assert len(cues) == 2
    return DeviceIdentityResolver().resolve("track-7", cues)


def test_two_candidates_too_close_to_separate_refuse_the_top_pick(shipped_map):
    """두 후보가 흔들림에 비해 가까우면 1 위를 고르지 않는다.

    이 모듈이 허용 오차를 임의로 적지 않는 이유가 여기 있다. 오차가 σ 에서 나오므로
    두 단서의 세기가 가까워지고, `device_identity` 의 `discriminating_margin` 규칙이
    그대로 `AMBIGUOUS` 를 낸다. 숫자를 베껴 적었다면 이 보호가 끊긴다.
    """
    verdict = _verdict_for_separation(shipped_map, sigma_db=9.0, separation_m=0.5)
    assert verdict.verdict is Verdict.AMBIGUOUS
    assert verdict.device_id is None
    assert set(verdict.conflicting_device_ids) == {"go1-001", "go1-002"}
    # 그리고 무엇을 더 하면 풀리는지 함께 낸다(AI-S-05).
    assert verdict.resolution_requests


def test_how_far_apart_two_candidates_must_be_follows_sigma(shipped_map):
    """가릴 수 있는 최소 간격이 **σ 를 따라 움직인다**(상수가 아니다).

    σ 를 올리면 같은 간격으로는 못 가리게 되고, 최소 간격은 커진다. 이 값이 코드에
    적힌 상수라면 σ 를 고쳐도 움직이지 않을 것이다.

    여기서 드러나는 한계도 함께 적어 둔다: `radio_range_cue` 의 세기는 오차에 **선형**
    이고 `discriminating_margin` 은 세기 차이라서, 가릴 수 있는 간격이 허용 오차보다
    훨씬 작게 나온다(대략 margin × tolerance). RSSI 가 실제로 그만큼 가를 수 있다는
    주장은 아니다 — 그 임계값은 `device_identity.py` 의 소유이고, 실측 σ 가 들어오면
    그쪽에서 다시 보정할 몫이다.
    """
    def min_separation(sigma_db: float) -> float:
        separation = 0.1
        while separation < 30.0:
            verdict = _verdict_for_separation(
                shipped_map, sigma_db=sigma_db, separation_m=separation)
            if verdict.verdict is Verdict.CONFIRMED:
                return separation
            separation += 0.1
        raise AssertionError(f"never separated at sigma={sigma_db}")

    tight = min_separation(2.0)
    loose = min_separation(9.0)
    assert loose > tight


def test_an_unmeasured_belief_emits_no_cue_so_the_request_survives(shipped_map):
    """세기 0 의 단서를 만들지 않는다 — 만들면 해법 요청이 사라진다(AI-S-05)."""
    anchor = shipped_map.anchors[0]
    belief = RssiLocalizer(shipped_map).locate(
        [_reading(reason=REASON_SOURCE_UNAVAILABLE)])
    outcome = radio_range_cue_for_track(
        belief, device_id="go1-001", track_id="track-7",
        track_at=(30.0, 23.0), track_frame_id=shipped_map.frame_id, anchor=anchor)
    assert outcome.cue is None
    assert outcome.reason == CUE_UNMEASURED

    # 외형 단서만으로 판정하면 모호하고, 무선 측정을 켜라는 요청이 남아 있다.
    cues = list(appearance_cue(["go1-001", "go1-002"], observed_at=1000.0,
                               source="cam-1", confidence=0.9,
                               robot_class="quadruped", frame_ref="frame-1"))
    verdict = DeviceIdentityResolver().resolve("track-7", cues)
    assert verdict.verdict is Verdict.AMBIGUOUS
    assert IDENTITY_REQUEST_RANGING in verdict.resolution_requests


def test_a_below_floor_belief_gives_a_lower_bound_instead_of_a_cue(shipped_map):
    """"멀다" 는 사실은 남기고 단서로는 쓰지 않는다."""
    anchor = shipped_map.anchors[0]
    belief = RssiLocalizer(shipped_map).locate([_reading(-95.0)])
    outcome = radio_range_cue_for_track(
        belief, device_id="go1-001", track_id="track-7",
        track_at=(30.0, 23.0), track_frame_id=shipped_map.frame_id, anchor=anchor)
    assert outcome.cue is None
    assert outcome.reason == CUE_BEYOND_FLOOR
    assert outcome.lower_bound_m == pytest.approx(anchor.floor_radius_m)


def test_a_track_from_another_frame_is_refused(shipped_map):
    """로컬과 전역은 교환 가능하지 않다 — 섞으면 그 거리는 아무 프레임의 값도 아니다."""
    anchor = shipped_map.anchors[0]
    belief = RssiLocalizer(shipped_map).locate([_reading(-70.0)])
    outcome = radio_range_cue_for_track(
        belief, device_id="go1-001", track_id="track-7", track_at=(30.0, 23.0),
        track_frame_id="wgs84", anchor=anchor)
    assert outcome.cue is None
    assert outcome.reason == CUE_FRAME_MISMATCH


def test_candidates_without_a_cue_stay_in_the_outcome_list(shipped_map):
    """단서가 못 나온 후보는 빠지지 않고 **사유를 달고 남는다**."""
    anchor = shipped_map.anchors[0]
    beliefs = {
        "go1-001": RssiLocalizer(shipped_map).locate([_reading(-70.0)]),
        "go1-002": RssiLocalizer(shipped_map).locate(
            [_reading(reason=REASON_SOURCE_UNAVAILABLE)]),
    }
    outcomes = radio_range_cues(
        beliefs, track_id="track-7", track_at=(36.0, 23.22),
        track_frame_id=shipped_map.frame_id, anchor=anchor)
    assert [o.device_id for o in outcomes] == ["go1-001", "go1-002"]
    assert [o.reason for o in outcomes] == [CUE_OK, CUE_UNMEASURED]
    assert outcomes[1].as_dict()["has_cue"] is False
    assert outcomes[1].as_dict()["strength"] is None


# ---------------------------------------------------------------------------
# 8. 재현 가능성 — 같은 입력에 같은 답
# ---------------------------------------------------------------------------


def test_the_same_input_gives_the_same_answer(shipped_map):
    localizer = RssiLocalizer(shipped_map)
    first = localizer.locate([_reading(-70.0)]).as_dict()
    second = localizer.locate([_reading(-70.0)]).as_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_belief_serialises(shipped_map):
    """화면·전송으로 나갈 수 있는 모양인가. 직렬화되지 않으면 계약이 아니다."""
    body = RssiLocalizer(shipped_map).locate([_reading(-70.0)]).as_dict()
    json.dumps(body)
    assert body["pose_source"] == "radio_range_likelihood"
    assert body["bearing_resolved"] is False
    assert body["coverage"][0]["placement_verified"] is False


def test_the_module_needs_no_required_capability():
    """측정도 AP 도 없는 배치에서 이 모듈은 돌고, import 를 막지 않는다(AI-C-05)."""
    from mission_runtime.perception.rssi_localization import REQUIREMENT

    assert REQUIREMENT.required == ()
    assert "radio.ranging" in REQUIREMENT.optional
