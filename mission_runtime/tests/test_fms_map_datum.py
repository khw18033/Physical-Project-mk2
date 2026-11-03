"""implements: AI-C-02 (좌표계 경계), AI-C-16 (폐쇄망 배포 경계)
관련: AI-C-19 (AI 판단·권한·책임 경계), AI-O-06 (통합 운영 상태 뷰), AI-C-15
tests: (a) datum 이 없는 현장은 정상 배치다 — 전역 계층만 비활성이고 로컬 판단은
그대로 돈다, (b) 미검증 datum 은 전역 값을 **거절**하고 사유를 낸다, (c) 운영자가
명시적으로 물어 유도한 값도 "검증됨" 으로 보이지 않는다, (d) 미측정 정확도가 0 으로
새지 않고 0 선언 자체가 거절된다, (e) 유도한 값의 정확도가 재료보다 좋아지지 않는다,
(f) 로컬 값과 전역 값이 같은 칸에 들어가지 않는다, (g) 층을 쌓은 평면은 층 보정 없이
올라가지 않는다, (h) 배경 타일 기본값이 외부 연결을 요구하지 않고 폐쇄망 선언에서
켜진 외부 레이어가 거절된다, (i) 배포된 선언 파일에서 실제 현장 둘에는 datum 이 있고
예시 둘에는 없다, (j) 전역 좌표 **숫자**가 뷰 계약으로 나가는 조건이 코드 상수가
아니라 현장 선언이고 네 조건 중 하나만 빠져도 사유와 함께 막힌다, (k) 없는 합의를
"있다"고 적을 수 없다 — 누가·언제·어느 문서로·무엇을 대체했는지가 빠진 선언과 예시를
실제로 위장한 선언은 거절된다.

AI-C-02 는 2026-11-03 개정으로 전역 좌표 변환을 AI 소유로 옮겼다. 소유권만 옮기면
옛 경계가 막고 있던 실패("같은 사실에 authoritative 주인이 둘")가 없어지지 않고
자리만 바뀌므로, 같은 요구사항이 세 조건을 함께 건다 — 프레임 보존, 출처와 **선언된
정확도**를 가진 datum, 그리고 datum 없는 현장의 정상 동작. 이 파일이 고정하는 것은
그 셋이다. 특히 (d) 는 한 줄로 썩는 자리다: 미측정 정확도를 0 으로 적으면 공개 지도
에서 받아 적은 기준점으로 만든 전역 값이 사람이 줄자로 잰 로컬 값을 이긴다.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from mission_runtime.tools.fms_console.fleet import (
    ACCURACY_DECLARED,
    ACCURACY_UNMEASURED,
    AGREEMENT_PARTY_AI,
    AGREEMENT_PARTY_BACKEND,
    AGREEMENT_SUBJECT_GLOBAL_COORDINATES,
    GEO_ACCURACY_UNMEASURED,
    GEO_BOUNDARY_NOT_REAGREED,
    GEO_DATUM_UNVERIFIED,
    GEO_LAYER_ACTIVE,
    GEO_LAYER_DISABLED,
    GEO_NO_DATUM,
    GEO_NO_LOCAL_VALUE,
    GEO_UNKNOWN_LEVEL,
    TILE_EXTERNAL_CONNECTION_REQUIRED,
    TILE_KIND_NONE,
    BoundaryAgreementError,
    FleetModel,
    MapTileError,
    SiteDatumError,
    load_domain_profile,
    read_boundary_agreement,
    TILE_KIND_STATIC_IMAGE,
    load_map_tiles,
    map_tiles_block,
    read_site_datum,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_PROFILE = PROJECT_ROOT / "profiles" / "domains.example.json"
WALKTHROUGH_PROFILE = PROJECT_ROOT / "profiles" / "domains.walkthrough.example.json"
SHIPPED_TILES = PROJECT_ROOT / "config" / "map_tiles.example.json"

#: 실제 현장과 예시 현장. 예시에 datum 이 **없어야** 한다는 것이 요구사항이다
#: (AI-C-02: "datum 이 없는 현장은 정상 상태다").
REAL_DOMAINS = ("college", "river")
EXAMPLE_DOMAINS = ("facility", "defense")

#: 경계 재합의가 **예시로** 선언된 현장. 전역 계층이 켜진 경로를 배포 데이터가 한
#: 번은 지나가야 하므로 예시 현장 하나에만 그 기록을 둔다 — 실제 현장 둘에는 없다
#: (AI-C-19 의 재합의가 아직 없으므로 적을 수 없다).
AGREED_EXAMPLE_DOMAIN = "logistics"

#: 전역 좌표를 가리키는 낱말. `tests/test_view_contract.py` 가 쓰는 것과 같은 목록이고,
#: 여기서는 **전역 계층 블록 자체**가 이 칸을 흘리지 않는지 본다.
GLOBAL_COORDINATE_WORDS = frozenset({
    "lat", "latitude", "lon", "lng", "longitude", "utm", "epsg", "wgs84",
    "easting", "northing", "mgrs", "geohash", "altitude_msl",
})


def _keys(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(str(key))
            found |= _keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keys(item)
    return found


def _words(key: str) -> set[str]:
    return {part for part in re.split(r"[^A-Za-z0-9]+", key.lower()) if part}


@pytest.fixture(scope="module")
def shipped() -> dict:
    return load_domain_profile(SHIPPED_PROFILE)


@pytest.fixture(scope="module")
def model(shipped) -> FleetModel:
    # 로봇 사실은 비워 둔다 — 이 파일이 보는 것은 좌표 계층이고, 선언만으로 돌아야
    # 한다. 선언 파일 하나로 재현되지 않는 시험은 현장에서도 재현되지 않는다.
    return FleetModel(domain_profile=copy.deepcopy(shipped), facts={})


def verified_model(shipped, domain_id: str = "college", **datum_changes) -> FleetModel:
    """그 도메인의 datum 을 **검증된 것으로 바꿔** 세운 모델.

    "검증되면 전역 계층이 실제로 켜진다"를 보이려면 검증된 datum 이 하나는 있어야
    한다. 배포 선언을 거짓으로 고치는 대신 사본에서만 올린다 — 배포 파일의
    `verified` 는 현장 실측이 끝났을 때 사람이 올리는 값이다.
    """
    profile = copy.deepcopy(shipped)
    for domain in profile["domains"]:
        if domain["domain_id"] == domain_id:
            datum = domain["site"]["datum"]
            datum["verified"] = True
            datum.update(datum_changes)
    return FleetModel(domain_profile=profile, facts={})


# ---------------------------------------------------------------------------
# (i) 배포된 선언 — 실제 현장 둘에만 datum 이 있다
# ---------------------------------------------------------------------------


def test_the_shipped_profile_declares_a_datum_for_the_two_real_sites(shipped):
    """선언 파일이 정본이다. 좌표를 코드에 적으면 새 현장마다 코드를 고친다(AI-C-15)."""
    datums = {d["domain_id"]: read_site_datum(d) for d in shipped["domains"]}

    for domain_id in REAL_DOMAINS:
        datum = datums[domain_id]
        assert datum is not None, f"{domain_id} 에 datum 선언이 없다"
        # AI-C-02 가 요구하는 칸이 전부 있는가 — 기준점·출처·시점·버전·정확도.
        assert -90.0 <= datum.lat <= 90.0 and -180.0 <= datum.lon <= 180.0
        assert datum.crs
        assert datum.source.get("url"), "출처 URL 이 없는 datum 은 공리다"
        assert datum.created_at and datum.version
        # 공개 지도에서 받아 적은 값이므로 아직 검증된 것이 아니다.
        assert datum.verified is False
        assert datum.accuracy_m is None
        assert datum.accuracy_state == ACCURACY_UNMEASURED


def test_the_example_sites_declare_no_datum_and_that_is_normal(shipped):
    """datum 없는 현장이 정상 배치임을 **배포된 데이터가** 보여야 한다.

    예시 도메인에 그럴듯한 좌표를 넣으면 "전역 계층은 어차피 늘 있다"는 가정이
    코드와 화면에 스며든다. 그 가정이 생기는 순간 datum 없는 현장이 고장처럼 읽힌다.
    """
    for domain in shipped["domains"]:
        if domain["domain_id"] not in EXAMPLE_DOMAINS:
            continue
        assert "datum" not in (domain.get("site") or {})
        assert read_site_datum(domain) is None
        assert domain["site"].get("example") is True


def test_an_unverified_datum_is_listed_as_unverified_on_the_site(shipped):
    """상태 어휘를 새로 만들지 않는다 — 기존 `site.unverified_fields` 에 적는다."""
    for domain in shipped["domains"]:
        if domain["domain_id"] not in REAL_DOMAINS:
            continue
        site = domain["site"]
        assert "datum" in site["unverified_fields"]
        assert "datum" not in site.get("verified_fields", ())


def test_the_walkthrough_profile_keeps_the_same_declaration_shape():
    """사본 프로파일도 같은 모양이어야 한다 — 두 파일이 갈라지면 걸어 보기 문서가
    배포와 다른 것을 가르친다."""
    walkthrough = load_domain_profile(WALKTHROUGH_PROFILE)
    datums = {d["domain_id"]: read_site_datum(d) for d in walkthrough["domains"]}
    for domain_id in REAL_DOMAINS:
        assert datums[domain_id] is not None
    for domain_id in EXAMPLE_DOMAINS:
        assert datums[domain_id] is None
    # 걸어 보기로 더한 다섯째 도메인도 datum 없이 정상이다.
    assert datums["transit"] is None


# ---------------------------------------------------------------------------
# (a) datum 이 없는 현장 — 전역 계층만 비활성이다
# ---------------------------------------------------------------------------


def test_a_site_without_a_datum_disables_only_the_global_layer(model):
    geo = model.domain_geo("facility")

    assert geo["layer"] == GEO_LAYER_DISABLED
    assert geo["reason"] == GEO_NO_DATUM
    # 빈 좌표를 내지 않는다. 사유만 있는 블록이 "없는 것"의 정상적인 표현이다.
    assert "datum" not in geo


def test_the_local_picture_of_a_datum_less_site_is_untouched(model):
    """전역 계층이 꺼진 도메인에서도 지도·구역·로봇은 그대로 나와야 한다."""
    scene = model.domain_scene("facility")

    assert scene["space"]["unit"] == "meter"
    assert [zone["zone_id"] for zone in scene["zones"]], "구역이 사라졌다"
    for zone in scene["zones"]:
        assert set(zone["rect"]) >= {"x", "y", "w", "h"}
    # 구역 상세도 같은 선언으로 그대로 조립된다.
    detail = model.zone_detail(scene["zones"][0]["zone_id"])
    assert detail["space"]["unit"] == "meter"


def test_a_datum_less_site_refuses_a_global_value_with_a_reason(model):
    result = model.global_position("facility", {"x": 10.0, "y": 20.0})

    assert result == {"layer": GEO_LAYER_DISABLED, "reason": GEO_NO_DATUM}


# ---------------------------------------------------------------------------
# (b)(c) 미검증 datum — 거절이 기본이고, 유도해도 검증됨이 아니다
# ---------------------------------------------------------------------------


def test_an_unverified_datum_refuses_the_derivation_by_default(model):
    """§3 금지: "datum 이 없거나 검증되지 않았으면 사유와 함께 거절하고 로컬 값을
    유지한다." 거절이 기본값이어야 한다 — 기본이 유도이면 검증은 아무도 하지 않는다."""
    result = model.global_position("college", {"x": 14.0, "y": 9.0}, level_id="N4-1F")

    assert result["layer"] == GEO_LAYER_DISABLED
    assert result["reason"] == GEO_DATUM_UNVERIFIED
    assert "lat" not in result and "lon" not in result
    # 왜 못 쓰는지 설명할 수 있어야 하므로 datum 에 **대한** 사실은 함께 낸다.
    assert result["datum"]["verified"] is False


def test_a_value_derived_from_an_unverified_datum_never_looks_verified(model):
    """운영자가 "미검증이라도 대략 어디쯤인가" 를 명시적으로 물을 수는 있다. 그때
    나오는 값이 검증된 값과 **구분되지 않으면** 그 값은 곧 실측처럼 쓰인다."""
    result = model.global_position(
        "college", {"x": 14.0, "y": 9.0}, level_id="N4-1F", allow_unverified=True)

    assert result["layer"] == GEO_LAYER_ACTIVE
    assert isinstance(result["lat"], float) and isinstance(result["lon"], float)
    assert result["verified"] is False
    assert result["provisional"] is True
    assert result["datum"]["verified"] is False
    assert result["datum"]["source"]["url"]


def test_the_domain_block_says_the_global_layer_is_off_and_why(model):
    geo = model.domain_geo("college")

    assert geo["layer"] == GEO_LAYER_DISABLED
    assert geo["reason"] == GEO_DATUM_UNVERIFIED
    assert geo["datum"]["accuracy_state"] == ACCURACY_UNMEASURED


def test_a_verified_datum_turns_the_layer_on(shipped):
    """검증되면 켜진다 — 그래야 `verified` 가 실제로 무언가를 바꾸는 값이 된다."""
    model = verified_model(shipped)

    assert model.domain_geo("college")["layer"] == GEO_LAYER_ACTIVE
    assert model.domain_geo("college")["reason"] is None
    result = model.global_position("college", {"x": 0.0, "y": 0.0}, level_id="N4-1F")
    assert result["verified"] is True and result["provisional"] is False


def test_a_missing_local_value_is_its_own_reason(shipped):
    """자리를 모르는 장치(`at: null`)를 원점으로 올리지 않는다 — (0,0) 에 그리는 것은
    없는 위치를 있다고 말하는 것이다."""
    model = verified_model(shipped)

    assert model.global_position("college", None, level_id="N4-1F")["reason"] == \
        GEO_NO_LOCAL_VALUE


# ---------------------------------------------------------------------------
# (d)(e) 정확도 — 미측정은 0 이 아니고, 유도가 재료를 이기지 않는다
# ---------------------------------------------------------------------------


def test_an_unmeasured_accuracy_never_leaks_out_as_zero(shipped):
    """`null` 과 `0` 은 다른 뜻이다. 0 은 "오차가 없다" 는 주장이다."""
    model = verified_model(shipped)
    result = model.global_position("college", {"x": 30.0, "y": 9.0}, level_id="N4-1F")

    assert result["accuracy_m"] is None
    assert result["accuracy_m"] != 0
    assert result["accuracy_state"] == ACCURACY_UNMEASURED
    assert model.domain_geo("college")["datum"]["accuracy_m"] is None


def test_declaring_a_zero_accuracy_is_refused_with_a_reason(shipped):
    """선언 단계에서 막는다. 0 을 통과시키면 그 datum 으로 유도한 전역 값이 사람이
    줄자로 잰 로컬 값보다 정확한 척하게 된다(AI-C-02)."""
    broken = copy.deepcopy(shipped["domains"][0])
    broken["site"]["datum"]["accuracy_m"] = 0

    with pytest.raises(SiteDatumError) as error:
        read_site_datum(broken)
    assert "accuracy_m" in str(error.value)


def test_a_derived_value_is_no_more_accurate_than_the_datum_it_came_from(shipped):
    """선언된 정확도가 있으면 그 값이 따라붙는다. 유도 과정이 정확도를 **좋게** 만드는
    일은 없다 — 접평면 근사 오차가 cm 라는 사실은 datum 오차를 지우지 않는다."""
    model = verified_model(shipped, accuracy_m=2.5, accuracy_basis="rtk_gnss_single_point")
    result = model.global_position("college", {"x": 10.0, "y": 5.0}, level_id="N4-1F")

    assert result["accuracy_m"] == 2.5
    assert result["accuracy_state"] == ACCURACY_DECLARED
    assert result["datum"]["accuracy_basis"] == "rtk_gnss_single_point"


# ---------------------------------------------------------------------------
# (f) 로컬 값과 전역 값은 같은 칸에 들어가지 않는다
# ---------------------------------------------------------------------------


def test_the_global_value_and_the_local_value_live_in_different_cells(shipped):
    """AI-C-02 의 마지막 문장이다. 한 칸에 담으면 받는 쪽이 단위와 기준을 추측하고,
    추측은 반드시 틀린다."""
    model = verified_model(shipped)
    at = {"x": 14.0, "y": 33.0}
    result = model.global_position("college", at, level_id="N4-2F")

    # 전역 값 칸에 로컬 좌표가 섞여 있지 않다.
    assert "x" not in result and "y" not in result and "at" not in result
    # 재료인 로컬 값은 자기 프레임과 함께 **따로** 남는다(AI-C-19 역추적).
    assert result["source_local"]["x"] == at["x"]
    assert result["source_local"]["y"] == at["y"]
    assert result["source_local"]["frame"]["kind"] == "site_local"
    assert result["source_local"]["frame"]["domain_id"] == "college"
    assert result["source_local"]["frame"]["level_id"] == "N4-2F"
    assert result["source_local"]["frame"]["unit"] == "meter"
    # 전역 값도 자기 좌표계를 말한다 — 숫자만 주고 평면을 말하지 않는 칸은 없다.
    assert result["crs"]
    # 넘겨 준 로컬 좌표를 건드리지 않는다.
    assert at == {"x": 14.0, "y": 33.0}


def test_the_view_payload_keeps_the_global_layer_out_of_the_local_cells(model):
    """뷰 응답의 `geo` 는 상태만 말하고, 로컬 좌표 칸은 그대로다.

    전역 좌표 **숫자**는 아직 이 계약으로 나가지 않는다 — AI-C-02 개정은 소유를 AI 로
    옮겼지만 같은 사실을 백엔드(BE-C-04)·디지털 트윈(DT-03)이 아직 authoritative 로
    적고 있어 요구사항 자체가 경계 재합의를 선행 조건으로 둔다(AI-C-19). 그 재합의가
    끝나기 전에 숫자를 내보내면 "같은 사실에 주인이 둘" 이 그대로 재현된다.
    """
    scene = model.domain_scene("college")

    offenders = {key: sorted(_words(key) & GLOBAL_COORDINATE_WORDS)
                 for key in _keys(scene) if _words(key) & GLOBAL_COORDINATE_WORDS}
    assert not offenders, offenders
    assert scene["geo"]["coordinates_in_view_contract"] is False
    # 현장 블록은 datum 선언을 그대로 싣지 않는다 — 같은 사실의 출처는 한 곳이다.
    assert "datum" not in scene["site"]
    assert "datum" in scene["site"]["unverified_fields"]
    for zone in scene["zones"]:
        for robot in zone["robots"]:
            if robot["at"] is not None:
                assert set(robot["at"]) == {"x", "y"}


def test_the_main_map_carries_the_same_global_layer_state(model):
    """메인 맵과 도메인 장면이 같은 사실을 말해야 한다(AI-O-06: 같은 사실은 한
    출처에서 파생된다)."""
    scene = model.scene()
    summaries = {domain["domain_id"]: domain for domain in scene["domains"]}

    assert summaries["college"]["geo"] == model.domain_scene("college")["geo"]
    assert summaries["facility"]["geo"]["reason"] == GEO_NO_DATUM


# ---------------------------------------------------------------------------
# (g) 층을 쌓은 평면은 층 보정 없이 올라가지 않는다
# ---------------------------------------------------------------------------


def test_a_level_stacked_plane_refuses_to_lift_without_the_level(shipped):
    """`levels[].y_offset` 으로 층을 +y 로 쌓은 장면에서 층을 모르면 올릴 수 없다.

    모르는 채로 올리면 4층 로봇이 1층보다 72 m 남쪽, 즉 **건물 밖**에 놓인다. 그런
    값은 틀렸다고 말해 주는 사람이 없어서 오래 살아남는다.
    """
    model = verified_model(shipped)

    assert model.global_position("college", {"x": 14.0, "y": 81.0})["reason"] == \
        GEO_UNKNOWN_LEVEL
    assert model.global_position(
        "college", {"x": 14.0, "y": 81.0}, level_id="N4-9F")["reason"] == GEO_UNKNOWN_LEVEL


def test_the_same_plan_position_on_two_floors_lifts_to_the_same_point(shipped):
    """같은 평면 위치라면 층이 달라도 같은 전역 점이다 — 층 보정이 실제로 걸렸다는
    뜻이고, 높이는 평면 좌표가 말할 것이 아니다."""
    model = verified_model(shipped)
    first = model.global_position("college", {"x": 14.0, "y": 9.0}, level_id="N4-1F")
    fourth = model.global_position("college", {"x": 14.0, "y": 81.0}, level_id="N4-4F")

    assert (first["lat"], first["lon"]) == (fourth["lat"], fourth["lon"])
    # 그래도 둘은 서로 다른 로컬 값에서 나왔고 그 사실이 남아 있다.
    assert first["source_local"]["y"] != fourth["source_local"]["y"]


def test_a_flat_site_lifts_without_a_level_and_lands_near_its_datum(shipped):
    """단층 현장(하천실험센터)은 층을 묻지 않는다. 그리고 유도한 점은 기준점에서
    선언된 로컬 거리만큼 떨어진 자리여야 한다 — 변환이 실제로 거리를 보존하는지
    여기서 본다(동 100 m · 남 200 m)."""
    model = verified_model(shipped, domain_id="river")
    datum = model.site_datum("river")
    result = model.global_position("river", {"x": 100.0, "y": 200.0})

    assert result["layer"] == GEO_LAYER_ACTIVE
    # 남쪽으로 200 m 내려갔으니 위도는 줄고, 동쪽으로 100 m 갔으니 경도는 늘어난다.
    assert result["lat"] < datum.lat and result["lon"] > datum.lon
    # 1 도 ≈ 111 km 를 쓰면 200 m 는 약 0.0018 도다. 자릿수가 어긋나면 축을 잘못 걸었다.
    assert abs((datum.lat - result["lat"]) - 200.0 / 111_132.0) < 1e-4


# ---------------------------------------------------------------------------
# (h) 배경 타일 — 기본값은 외부 연결을 요구하지 않는다 (AI-C-16)
# ---------------------------------------------------------------------------


def test_the_built_in_default_asks_for_no_tiles_and_no_outbound_connection():
    """선언 파일이 없는 배치에서도 블록은 나가고, 그 값은 폐쇄망에서 전제 없이 돈다."""
    block = map_tiles_block(None)

    assert block["declared"] is False
    assert block["default_layer_id"] == TILE_KIND_NONE
    assert block["requires_external_connection"] is False
    assert block["external_hosts"] == []
    assert [layer["kind"] for layer in block["layers"]] == [TILE_KIND_NONE]


def test_the_shipped_tile_declaration_is_closed_network_safe():
    """AI-C-16: "어떤 실행 단위가 외부 연결을 요구하는지는 등록 정보로 드러나야 한다."
    드러나되 **켜져 있지 않아야** 메인 화면이 폐쇄망에서 깨지지 않는다."""
    block = map_tiles_block(load_map_tiles(SHIPPED_TILES))

    assert block["default_layer_id"] == TILE_KIND_NONE
    assert block["requires_external_connection"] is False
    assert block["external_hosts"] == []
    external = [layer for layer in block["layers"]
                if layer["requires_external_connection"]]
    assert external, "외부 연결을 요구하는 레이어가 **선언에는** 있어야 한다(선택 기능)"
    for layer in external:
        assert layer["enabled"] is False
        assert layer["available"] is False
        assert layer["unavailable_reason"] == TILE_EXTERNAL_CONNECTION_REQUIRED
        assert layer["external_hosts"], "어느 호스트로 나가는지 적혀 있어야 한다"


def test_a_tile_pack_that_is_not_there_says_so_instead_of_pretending(model):
    """묶음 없음은 고장이 아니라 선언된 선택 조건이다(AI-C-05). 빈 배경이 뜨고 사유가
    없는 것이 고장이다."""
    block = map_tiles_block(load_map_tiles(SHIPPED_TILES))
    packs = [layer for layer in block["layers"] if layer["kind"] == "offline_pack"]

    assert packs
    for layer in packs:
        assert layer["requires_external_connection"] is False
        if not layer["available"]:
            assert layer["unavailable_reason"] == "pack_missing"


def test_enabling_an_external_layer_in_a_closed_network_profile_is_refused(tmp_path):
    declaration = json.loads(SHIPPED_TILES.read_text(encoding="utf-8"))
    for layer in declaration["layers"]:
        if layer["requires_external_connection"]:
            layer["enabled"] = True
    path = tmp_path / "map_tiles.json"
    path.write_text(json.dumps(declaration, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(MapTileError) as error:
        load_map_tiles(path)
    assert "closed_network" in str(error.value)


def test_an_external_layer_without_its_hosts_is_refused(tmp_path):
    """호스트를 적지 않은 외부 레이어는 배치 전 검증을 **할 수 없게** 만든다."""
    declaration = {
        "closed_network": False,
        "default_layer_id": "x",
        "layers": [{"layer_id": "x", "kind": "remote_xyz",
                    "requires_external_connection": True, "enabled": True}],
    }
    path = tmp_path / "map_tiles.json"
    path.write_text(json.dumps(declaration), encoding="utf-8")

    with pytest.raises(MapTileError) as error:
        load_map_tiles(path)
    assert "external_hosts" in str(error.value)


def test_a_tile_block_carries_no_presentation_or_global_coordinate_cell():
    """배경 타일은 그리는 쪽의 일이지만 **어디서 가져오는가**는 데이터다. 그 경계가
    새면 서버가 색과 두께를 말하기 시작한다(docs/view-contract.md §3.1)."""
    block = map_tiles_block(load_map_tiles(SHIPPED_TILES))
    presentation = {"color", "colour", "fill", "stroke", "font", "px", "pixel",
                    "opacity", "style", "theme", "icon", "shape", "marker"}

    for key in _keys(block):
        assert not _words(key) & presentation, key
        assert not _words(key) & GLOBAL_COORDINATE_WORDS, key


def test_the_main_map_carries_the_tile_declaration_it_was_given(shipped):
    """선언을 준 배치에서는 그 선언이 응답으로 그대로 나간다 — 뷰어가 레이어 목록을
    서버에서 받아야 새 타일 추가가 코드 변경이 되지 않는다(AI-C-15)."""
    model = FleetModel(domain_profile=copy.deepcopy(shipped), facts={},
                       map_tiles=load_map_tiles(SHIPPED_TILES))
    block = model.scene()["map_tiles"]

    assert block["declared"] is True
    assert block["closed_network"] is True
    # 한 장짜리 바탕 그림은 이 블록에 **없다**. 픽셀 크기와 그림 참조가 상태 계약에
    # 섞이면 "서버 응답에는 색·픽셀·폰트가 없다" 는 경계가 무너지므로(AI-C-08) 그
    # 종류만 `/api/background` 로 따로 나간다. 나머지 레이어는 그대로 실린다.
    assert {layer["layer_id"] for layer in block["layers"]} == {
        layer["layer_id"] for layer in load_map_tiles(SHIPPED_TILES)["layers"]
        if layer["kind"] != TILE_KIND_STATIC_IMAGE}
    assert all(layer["kind"] != TILE_KIND_STATIC_IMAGE for layer in block["layers"])


# ---------------------------------------------------------------------------
# (j)(k) 숫자가 뷰 계약으로 나가는 조건은 **현장 선언**이다 (AI-C-19)
# ---------------------------------------------------------------------------
#
# 유도할 수 있다는 것과 공개 계약으로 내보내도 된다는 것은 다른 문제다. AI-C-02 는
# 소유를 AI 로 옮겼지만 같은 사실을 백엔드(BE-C-04)·디지털 트윈(DT-03)이 아직
# authoritative 로 적고 있고, AI-C-19 가 그 경계 재합의를 선행 조건으로 둔다. 그래서
# 숫자는 재합의가 **기록된 현장에서만** 나가고, 기록되지 않은 현장은 오류가 아니라
# 기본값이다.


def agreement(**changes) -> dict:
    """온전한 재합의 선언 하나. 시험이 여기서 한 칸씩 빼서 거절을 확인한다."""
    body = {
        "subject": AGREEMENT_SUBJECT_GLOBAL_COORDINATES,
        "agreed_by": [AGREEMENT_PARTY_AI, AGREEMENT_PARTY_BACKEND, "visualisation"],
        "agreed_at": "2026-12-01",
        "document": {"name": "경계 재합의 회의록", "url": "https://example.invalid/minutes"},
        "supersedes": ["BE-C-04", "DT-03"],
    }
    body.update(changes)
    return body


def agreed_model(shipped, domain_id: str = AGREED_EXAMPLE_DOMAIN, **datum_changes) -> FleetModel:
    """선언된 현장을 그대로 세운 모델(필요하면 datum 칸만 바꿔서)."""
    profile = copy.deepcopy(shipped)
    for domain in profile["domains"]:
        if domain["domain_id"] == domain_id:
            domain["site"]["datum"].update(datum_changes)
    return FleetModel(domain_profile=profile, facts={})


def test_the_real_sites_have_not_declared_the_re_agreement(shipped):
    """적을 수 없는 것을 적지 않는다. 실제 현장 둘에는 합의 기록이 **없다**.

    이것이 이 변경의 핵심이다 — 게이트를 데이터로 옮겼다는 것이 "이제 합의가 됐다"는
    뜻이 아니다. 재합의 요청은 `docs/integration-handover.md` 에 있고, 그것이 끝나면
    그 현장 선언에 기록이 생긴다.
    """
    for domain in shipped["domains"]:
        if domain["domain_id"] not in REAL_DOMAINS:
            continue
        assert "boundary_agreement" not in domain["site"]
        assert read_boundary_agreement(domain) is None


def test_the_shipped_profile_exercises_the_declared_path_on_an_example_site(shipped, model):
    """선언된 경로가 **배포 데이터로** 한 번은 지나가야 한다.

    예시 데이터 없이 이 경로를 두면 아무도 지나가지 않는 분기가 되고, 그런 분기는
    처음 쓰는 현장에서 고장난다.
    """
    declared = next(d for d in shipped["domains"]
                    if d["domain_id"] == AGREED_EXAMPLE_DOMAIN)
    record = read_boundary_agreement(declared)

    assert record is not None
    assert record.subject == AGREEMENT_SUBJECT_GLOBAL_COORDINATES
    assert {AGREEMENT_PARTY_AI, AGREEMENT_PARTY_BACKEND} <= set(record.agreed_by)
    assert record.agreed_at and record.supersedes
    assert record.document.get("url") or record.document.get("name")
    # 예시는 예시로 표시된다 — 예시 데이터가 실제 합의 기록처럼 읽히면 이 문이 막으려는
    # 잘못을 그대로 저지른다.
    assert record.example is True
    assert declared["site"]["example"] is True

    geo = model.domain_geo(AGREED_EXAMPLE_DOMAIN)
    assert geo["layer"] == GEO_LAYER_ACTIVE
    assert geo["coordinates_in_view_contract"] is True
    assert "coordinates_withheld_reason" not in geo
    assert geo["boundary_agreement"]["supersedes"] == ["BE-C-04", "DT-03"]


def test_each_of_the_four_conditions_gates_the_numbers_on_its_own(shipped):
    """네 조건의 논리곱이다 — 하나만 빠져도 막히고, **무엇이 빠졌는지**가 사유다."""
    def released(mutate) -> dict:
        profile = copy.deepcopy(shipped)
        site = next(d for d in profile["domains"]
                    if d["domain_id"] == AGREED_EXAMPLE_DOMAIN)["site"]
        mutate(site)
        return FleetModel(domain_profile=profile, facts={}).global_release(
            AGREED_EXAMPLE_DOMAIN)

    def drop_datum(site):
        del site["datum"]

    def unverify(site):
        site["datum"]["verified"] = False

    def unmeasure(site):
        site["datum"]["accuracy_m"] = None

    def drop_agreement(site):
        del site["boundary_agreement"]

    assert released(lambda site: None) == {
        "released": True, "reason": None,
        "agreement": released(lambda site: None)["agreement"]}
    assert released(drop_datum)["reason"] == GEO_NO_DATUM
    assert released(unverify)["reason"] == GEO_DATUM_UNVERIFIED
    # 미측정 정확도로는 나가지 않는다. 확신을 모르는 숫자는 "정확하다" 로 읽힌다.
    assert released(unmeasure)["reason"] == GEO_ACCURACY_UNMEASURED
    assert released(drop_agreement)["reason"] == GEO_BOUNDARY_NOT_REAGREED
    for mutate in (drop_datum, unverify, unmeasure, drop_agreement):
        assert released(mutate)["released"] is False


def test_a_withheld_site_keeps_the_local_picture_and_says_what_is_missing(shipped):
    """막힌 것은 전역 숫자 하나뿐이다 — 지도·구역·장치는 그대로 나온다(AI-C-05)."""
    profile = copy.deepcopy(shipped)
    site = next(d for d in profile["domains"]
                if d["domain_id"] == AGREED_EXAMPLE_DOMAIN)["site"]
    del site["boundary_agreement"]
    withheld = FleetModel(domain_profile=profile, facts={})

    scene = withheld.domain_scene(AGREED_EXAMPLE_DOMAIN)
    assert scene["geo"]["coordinates_in_view_contract"] is False
    assert scene["geo"]["coordinates_withheld_reason"] == GEO_BOUNDARY_NOT_REAGREED
    # 유도 자체는 막히지 않는다 — 막힌 것은 **공개 계약으로 내보내는 것**이다.
    assert withheld.global_position(
        AGREED_EXAMPLE_DOMAIN, {"x": 10.0, "y": 5.0})["layer"] == GEO_LAYER_ACTIVE
    assert withheld.global_cell(AGREED_EXAMPLE_DOMAIN, {"x": 10.0, "y": 5.0}) is None
    for zone in scene["zones"]:
        assert set(zone["rect"]) >= {"x", "y", "w", "h"}
        for item in zone["infrastructure"]:
            assert "at_global" not in item
            if item["at"] is not None:
                assert set(item["at"]) == {"x", "y"}


def test_the_global_block_sits_beside_the_local_cell_not_inside_it(model):
    """AI-C-02: "로컬 값과 전역 값은 같은 칸에 담지 않는다." 선언된 현장에서도 그렇다."""
    scene = model.domain_scene(AGREED_EXAMPLE_DOMAIN)
    rows = [item for zone in scene["zones"] for item in zone["infrastructure"]
            if item["at"] is not None]

    assert rows, "자리가 있는 장치가 하나는 있어야 이 성질을 보일 수 있다"
    for row in rows:
        local, global_cell = row["at"], row["at_global"]
        # 로컬 칸에는 로컬 숫자만, 전역 칸에는 전역 숫자만 있다.
        assert set(local) == {"x", "y"}
        assert "x" not in global_cell and "y" not in global_cell
        # 전역 칸은 자기 좌표계와 **재료의 정확도**를 들고 다닌다.
        assert global_cell["crs"]
        assert global_cell["accuracy_state"] == ACCURACY_DECLARED
        assert global_cell["accuracy_m"] == 0.8
        assert global_cell["verified"] is True
        # 재료가 살던 프레임은 말하되 숫자는 복사하지 않는다(주인이 둘이 되지 않게).
        assert global_cell["derived_from"]["kind"] == "site_local"
        assert global_cell["derived_from"]["domain_id"] == AGREED_EXAMPLE_DOMAIN
        assert "x" not in global_cell["derived_from"]


def test_a_derived_block_is_no_more_accurate_than_the_datum_it_came_from(shipped):
    """datum 의 정확도를 낮춰 적으면 전역 블록의 정확도도 같이 낮아진다."""
    coarse = agreed_model(shipped, accuracy_m=12.0)
    cell = coarse.global_cell(AGREED_EXAMPLE_DOMAIN, {"x": 10.0, "y": 5.0})

    assert cell is not None
    assert cell["accuracy_m"] == 12.0


def test_the_site_block_does_not_carry_the_agreement_twice(model):
    """같은 사실의 출처는 한 곳이다 — `geo` 가 말하고 `site` 는 싣지 않는다(AI-O-06)."""
    scene = model.domain_scene(AGREED_EXAMPLE_DOMAIN)

    assert "boundary_agreement" not in scene["site"]
    assert "datum" not in scene["site"]
    assert scene["geo"]["boundary_agreement"]["agreed_at"]


def test_the_main_map_says_the_same_thing_as_the_domain_scene(model):
    scene = model.scene()
    summaries = {domain["domain_id"]: domain for domain in scene["domains"]}

    assert summaries[AGREED_EXAMPLE_DOMAIN]["geo"] == \
        model.domain_scene(AGREED_EXAMPLE_DOMAIN)["geo"]


# --- 없는 합의를 "있다" 고 적을 수는 없다 ------------------------------------


@pytest.mark.parametrize("missing", ["subject", "agreed_by", "agreed_at", "document",
                                     "supersedes"])
def test_a_half_written_agreement_is_refused_with_the_missing_field(shipped, missing):
    """반쯤 적힌 합의를 통과시키면 "누가 언제 합의했는지 모르는 합의" 가 전역 숫자의
    근거가 된다 — 출처 없는 datum 과 같은 종류의 공리다."""
    domain = copy.deepcopy(next(d for d in shipped["domains"]
                                if d["domain_id"] == AGREED_EXAMPLE_DOMAIN))
    declaration = agreement(example=True)
    del declaration[missing]
    domain["site"]["boundary_agreement"] = declaration

    with pytest.raises(BoundaryAgreementError) as error:
        read_boundary_agreement(domain)
    assert missing in str(error.value)


def test_an_agreement_that_does_not_name_both_parts_is_not_an_agreement(shipped):
    """AI-C-19 가 선행 조건으로 적은 것은 AI↔백엔드 경계다. 한쪽만 적힌 것은 합의가
    아니라 통보다."""
    domain = copy.deepcopy(next(d for d in shipped["domains"]
                                if d["domain_id"] == AGREED_EXAMPLE_DOMAIN))
    domain["site"]["boundary_agreement"] = agreement(
        agreed_by=[AGREEMENT_PARTY_AI, "visualisation"], example=True)

    with pytest.raises(BoundaryAgreementError) as error:
        read_boundary_agreement(domain)
    assert AGREEMENT_PARTY_BACKEND in str(error.value)


def test_an_agreement_about_something_else_does_not_open_this_gate(shipped):
    """다른 subject 를 조용히 통과시키면 현장은 "적었으니 됐다" 고 믿고 우리는 "그
    합의가 아니다" 로 막아, 양쪽이 서로 다른 것을 본다."""
    domain = copy.deepcopy(next(d for d in shipped["domains"]
                                if d["domain_id"] == AGREED_EXAMPLE_DOMAIN))
    domain["site"]["boundary_agreement"] = agreement(subject="availability_ownership",
                                                     example=True)

    with pytest.raises(BoundaryAgreementError) as error:
        read_boundary_agreement(domain)
    assert "availability_ownership" in str(error.value)


def test_an_empty_supersedes_list_is_refused(shipped):
    """무엇을 대체했는지 적지 않으면 소유권이 어디서 왔는지 역추적이 끊긴다(AI-C-19)."""
    domain = copy.deepcopy(next(d for d in shipped["domains"]
                                if d["domain_id"] == AGREED_EXAMPLE_DOMAIN))
    domain["site"]["boundary_agreement"] = agreement(supersedes=[], example=True)

    with pytest.raises(BoundaryAgreementError) as error:
        read_boundary_agreement(domain)
    assert "supersedes" in str(error.value)


def test_an_example_site_may_only_carry_an_example_agreement(shipped):
    """예시 현장의 선언이 실제 합의 기록처럼 읽히면 안 된다 — 두 방향 모두 막는다."""
    example_site = copy.deepcopy(next(d for d in shipped["domains"]
                                      if d["domain_id"] == AGREED_EXAMPLE_DOMAIN))
    example_site["site"]["boundary_agreement"] = agreement()      # example 표시 없음

    with pytest.raises(BoundaryAgreementError) as error:
        read_boundary_agreement(example_site)
    assert "example" in str(error.value)

    # 반대로 실제 현장이 예시 합의를 들고 있을 수도 없다.
    real_site = copy.deepcopy(next(d for d in shipped["domains"]
                                   if d["domain_id"] == REAL_DOMAINS[0]))
    real_site["site"]["boundary_agreement"] = agreement(example=True)

    with pytest.raises(BoundaryAgreementError) as error:
        read_boundary_agreement(real_site)
    assert "example" in str(error.value)


def test_a_broken_agreement_is_refused_when_the_profile_is_loaded(shipped, tmp_path):
    """현장에서 발견할 이유가 없는 잘못은 파일을 읽는 자리에서 막는다."""
    profile = copy.deepcopy(shipped)
    site = next(d for d in profile["domains"]
                if d["domain_id"] == AGREED_EXAMPLE_DOMAIN)["site"]
    del site["boundary_agreement"]["agreed_at"]
    path = tmp_path / "domains.json"
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(BoundaryAgreementError):
        load_domain_profile(path)
