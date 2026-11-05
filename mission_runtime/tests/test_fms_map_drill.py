"""implements: AI-C-02 (좌표계 경계), AI-C-05 (선택 기능 부재는 장애가 아니다)
AI-O-06 (통합 운영 상태 뷰 제공)
관련: AI-S-08 (환경·사전정보 관리 — 선언은 관측이 아니다), AI-S-06 (지속 객체
레코드), AI-C-08 (픽셀은 상태 계약으로 나가지 않는다), AI-C-15 (뷰어 교체 가능성)
tests: (a) 층이 여럿인 도메인에서 층마다 제 구역·장치 수를 들고 나온다, (b) 층을
고르면 그 층의 구역만 남고 고르지 않으면 전부 남는다, (c) 도면이 선언되지 않은 층과
선언된 층이 **구분된다**, (d) 미측정 고도는 0 이 아니라 칸이 없다 — 선언하면 생긴다,
(e) 구역 요약이 방·들어갈 수 있는 방·지물·고정 장치·공지 없는 장치를 **따로** 센다,
(f) 바닥 평면이 `rect` 와 같은 숫자이고 자기 프레임과 위쪽 축 이름을 들고 간다,
(g) 선언된 설치 높이만 숫자가 되고 나머지는 상태만 남는다, (h) 융합된 객체 자리는
평면 두 값이고 그 사실이 계약에 적힌다, (i) 새로 더한 칸에 색·픽셀·글꼴이 없다.

이 파일이 지키는 것은 **순차 드릴이 자료로 성립한다**는 성질이다. 화면(한밭대 캠퍼스
지도 → 핀 → 층 선택 → 층 도면 → 구역 호버 → 구역 결합 뷰)은 그리는 쪽의 몫이지만,
각 단계가 물어볼 수 있는 값이 서버에 없으면 그 화면은 숫자를 지어내거나 빈칸을
0 으로 채운다. 그 둘이 여기서 막힌다.

특히 (d)(g)(h) 는 한 줄로 썩는 자리다. 세로 값을 모를 때 0 을 적으면 3D 소비자가
천장 카메라를 바닥에 놓고 모든 층을 지면에 겹쳐 쌓으며, 그렇게 만들어진 그림은
**측정된 것처럼** 보인다(AI-C-02: 미측정은 0 이 아니다).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

#: 자산 뿌리가 이 노드에 있는가. 자리를 시험마다 따로 적으면 재분류가 또 있을 때
#: 어떤 시험은 skip 되고 어떤 시험은 실패한다 — conftest 한 곳이 정한다.
from conftest import asset_root_present
from mission_runtime.tools.fms_console.fleet import (
    ELEVATION_DECLARED,
    ELEVATION_NOT_SURVEYED,
    ELEVATION_UNMEASURED,
    FLOOR_PLANE_AXES,
    FLOOR_UP_AXIS,
    HEIGHT_DECLARED,
    HEIGHT_UNMEASURED,
    OBJECT_POSITION_DIMENSIONS,
    Discovery,
    FleetModel,
    load_domain_profile,
    load_map_tiles,
    static_image_for,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
#: 층이 **여럿인** 도메인은 예시 선언에만 있다(`college` 4개 층). 실제 현장
#: 선언(`domains.json`)은 지금 5층 하나뿐이라 "여러 층" 경로를 지나지 않는다 —
#: 그 경로가 돌지 않는 채로 남지 않게 하는 것이 이 파일의 첫 목적이다.
EXAMPLE_PROFILE = PROJECT_ROOT / "profiles" / "domains.example.json"
#: 실제 현장. 층 도면이 **걸려 있는** 유일한 자리라 (c) 의 반대쪽 예가 된다.
LIVE_PROFILE = PROJECT_ROOT / "profiles" / "domains.json"
SHIPPED_TILES = PROJECT_ROOT / "config" / "map_tiles.example.json"

MULTI_LEVEL_DOMAIN = "college"


@pytest.fixture(scope="module")
def example() -> dict:
    return load_domain_profile(EXAMPLE_PROFILE)


@pytest.fixture(scope="module")
def live() -> dict:
    return load_domain_profile(LIVE_PROFILE)


@pytest.fixture(scope="module")
def tiles() -> dict:
    return load_map_tiles(SHIPPED_TILES)


def model(profile: dict, **kw) -> FleetModel:
    return FleetModel(domain_profile=copy.deepcopy(profile), facts={}, **kw)


# ---------------------------------------------------------------------------
# (a)(b) 층 — 여럿일 때도 같은 길을 지난다
# ---------------------------------------------------------------------------


def test_a_domain_with_several_levels_counts_each_level_on_its_own(example):
    """층 버튼이 "이 층에 구역 몇, 장치 몇" 을 물을 수 있어야 한다.

    세는 일을 뷰어에 맡기면 같은 층을 옆 목록과 지도 팝업이 다르게 센다
    (AI-O-06: 같은 사실은 한 출처에서 파생시킨다).
    """
    fleet = model(example)
    scene = fleet.domain_scene(MULTI_LEVEL_DOMAIN)
    levels = scene["levels"]

    assert len(levels) > 1, "층이 하나뿐이면 이 시험은 아무것도 지키지 않는다"
    # 차례는 **선언된 순서** 그대로다. 고도가 미측정인 현장에서 3D 소비자가 층을
    # 쌓을 수 있는 유일한 근거이므로 뒤섞이면 건물이 거꾸로 선다.
    assert [l["ordinal"] for l in levels] == list(range(len(levels)))

    zones_by_level: dict[str, list[str]] = {}
    for zone in scene["zones"]:
        zones_by_level.setdefault(zone["level_id"], []).append(zone["zone_id"])

    for level in levels:
        mine = sorted(zones_by_level.get(level["level_id"], ()))
        assert sorted(level["zone_ids"]) == mine
        assert level["zone_count"] == len(mine)
        assert level["declared_count"] == sum(
            len(fleet.zone(z).get("declared_nodes", ())) for z in mine)
        # 아무것도 공지하지 않은 모델이므로 탐지 수는 0 이어야 한다. 0 이 아니면
        # "선언" 을 "공지" 로 세고 있다는 뜻이다.
        assert level["discovered_count"] == 0


def test_the_levels_partition_the_domain_so_picking_one_hides_the_others(example):
    """층을 고르면 그 층만 남고, 고르지 않으면 전부 남는다.

    층을 한 평면에 쌓아 그리는 배치에서 층 필터가 없으면 같은 자리의 다른 층이
    서로를 가린다 — 그래서 `level_id` 가 구역을 **나눈다**는 성질이 필요하다.
    """
    fleet = model(example)
    scene = fleet.domain_scene(MULTI_LEVEL_DOMAIN)
    all_zones = {z["zone_id"] for z in scene["zones"]}
    per_level = [set(l["zone_ids"]) for l in scene["levels"]]

    union: set[str] = set()
    for group in per_level:
        assert not (union & group), "한 구역이 두 층에 걸쳐 있다"
        union |= group
    assert union == all_zones, "어느 층에도 속하지 않는 구역이 있다"


def test_a_single_level_site_takes_the_same_path(live):
    """층이 하나인 현장도 **같은 모양**으로 나온다.

    층이 하나라고 칸을 비우면 뷰어가 "층 하나" 와 "층 모름" 을 구분하는 코드를
    따로 들고 있어야 하고, 그 코드는 층이 둘이 되는 날 조용히 어긋난다.
    """
    fleet = model(live)
    domain_id = fleet.domain_ids()[0]
    levels = fleet.domain_scene(domain_id)["levels"]

    assert len(levels) == 1
    assert levels[0]["ordinal"] == 0
    assert levels[0]["zone_count"] == len(fleet.zone_ids(domain_id))


# ---------------------------------------------------------------------------
# (c) 도면이 없는 층은 **없다고** 말한다
# ---------------------------------------------------------------------------


def test_a_level_without_a_drawing_is_told_apart_from_one_with_it(example, live, tiles):
    """도면이 없는 층을 눌러 빈 화면을 만난 뒤에 알게 되는 것이 가장 나쁘다.

    선언은 상태 계약이 아니라 `/api/background` 로만 나간다(AI-C-08: 픽셀은
    상태 계약으로 나가지 않는다). 그래서 "이 층에 도면이 있는가" 도 그 경로로
    묻고, 없으면 `None` 이 답이며 그것은 장애가 아니다(AI-C-05).
    """
    live_fleet = model(live, map_tiles=tiles)
    live_domain = live_fleet.domain_ids()[0]
    live_level = live_fleet.domain_scene(live_domain)["levels"][0]["level_id"]
    drawn = static_image_for(tiles, domain_id=live_domain, level_id=live_level)
    assert drawn is not None, "실제 현장 5층 도면 **선언**이 사라졌다"
    # 선언이 있는 것과 그림 **파일**이 이 노드에 있는 것은 다른 사실이다. 공개
    # 트리만 받은 노드에는 자산 뿌리가 없고 그것이 정상 배치다 — 그 노드에서는
    # 선언이 그대로 남고 `available` 만 거짓이 된다(AI-C-05 · AI-C-08). 두 사실을
    # 한 칸에 담으면 "도면을 선언하지 않은 층" 과 "선언은 했는데 파일이 없는 층"
    # 이 화면에서 같아지고, 그것이 바로 (c) 가 막는 자리다.
    if asset_root_present():
        assert drawn["available"], "선언된 5층 도면 파일이 자산 뿌리에 없다"
    else:
        assert drawn["available"] is False

    example_fleet = model(example, map_tiles=tiles)
    missing = [
        l["level_id"]
        for l in example_fleet.domain_scene(MULTI_LEVEL_DOMAIN)["levels"]
        if static_image_for(tiles, domain_id=MULTI_LEVEL_DOMAIN,
                            level_id=l["level_id"]) is None
    ]
    assert missing, "도면 없는 층이 하나도 없으면 이 시험은 반대쪽을 보지 못한다"


# ---------------------------------------------------------------------------
# (d) 미측정 고도는 0 이 아니라 **칸이 없다**
# ---------------------------------------------------------------------------


def test_an_unmeasured_floor_elevation_leaves_no_number_behind(example):
    """0 을 적으면 모든 층이 지면에 겹쳐 쌓이고, 그 그림은 측정된 것처럼 보인다."""
    fleet = model(example)
    for level in fleet.domain_scene(MULTI_LEVEL_DOMAIN)["levels"]:
        assert level["elevation_state"] == ELEVATION_UNMEASURED
        assert level["elevation_reason"] == ELEVATION_NOT_SURVEYED
        assert "elevation_m" not in level, "미측정인데 숫자 칸이 생겼다"
        # 평면 오프셋은 **고도가 아니다.** 층 도면을 한 평면에 쌓아 그릴 때의
        # y 이동이고, 그 둘을 같은 칸으로 읽으면 위층이 남쪽으로 밀린다.
        assert "plan_stacking_offset_m" in level


def test_a_declared_floor_elevation_shows_up_as_a_number(example):
    """선언하면 숫자가 생긴다 — 길이 두 벌이 아니라 **같은 길**이다."""
    profile = copy.deepcopy(example)
    for domain in profile["domains"]:
        if domain["domain_id"] != MULTI_LEVEL_DOMAIN:
            continue
        domain["levels"][1]["elevation_m"] = 4.2

    fleet = FleetModel(domain_profile=profile, facts={})
    levels = fleet.domain_scene(MULTI_LEVEL_DOMAIN)["levels"]

    assert levels[1]["elevation_state"] == ELEVATION_DECLARED
    assert levels[1]["elevation_m"] == pytest.approx(4.2)
    assert "elevation_reason" not in levels[1]
    assert levels[0]["elevation_state"] == ELEVATION_UNMEASURED

    zone_id = levels[1]["zone_ids"][0]
    floor = fleet.zone_detail(zone_id)["floor"]
    assert floor["elevation_m"] == pytest.approx(4.2)
    assert floor["elevation_state"] == ELEVATION_DECLARED


# ---------------------------------------------------------------------------
# (e) 구역 호버 — 세는 일은 서버가 한다
# ---------------------------------------------------------------------------


def test_the_zone_summary_counts_each_kind_of_thing_on_its_own(live):
    """21개 호실 이름을 늘어놓던 자리다. 팝업이 읽는 것은 **수**다.

    없는 것을 0 으로 적지 않는 것도 여기서 지킨다 — 고정 장치가 하나도 없는
    구역과 장치 목록을 못 읽은 구역은 다른 사실이고, 앞쪽은 정상이다(AI-C-05).
    """
    fleet = model(live)
    zone_id = fleet.zone_ids()[0]
    zone = fleet.zone(zone_id)
    summary = fleet.zone_summary(zone_id)

    assert summary["room_count"] == len(zone["rooms"])
    assert summary["interior_count"] == len(zone.get("interiors", ()))
    assert summary["infrastructure_count"] == len(zone.get("infrastructure", ()))
    assert summary["landmark_count"] == len(zone.get("landmarks", ()))

    # 지물은 **종류별로** 센다. 한 수로 합치면 계단이 몇 개인지 물을 자리가 없다.
    counts = summary["landmark_counts"]
    assert sum(counts.values()) == summary["landmark_count"]
    for kind, number in counts.items():
        assert number == sum(1 for l in zone["landmarks"] if l["kind"] == kind)
    assert set(counts) == {l["kind"] for l in zone.get("landmarks", ())}

    # 이름만 있는 방과 들어갈 수 있는 방은 다른 목록이다. 한 칸에 담으면 21개
    # 방이 전부 열리는 것처럼 보인다.
    assert summary["interior_count"] < summary["room_count"]


def test_a_device_that_never_announced_is_counted_as_such(live):
    """선언만 되고 공지가 오지 않은 장치는 **그 사실**로 센다.

    뷰어가 선언 수에서 탐지 수를 빼게 하면, 선언에 없는 장치가 나타난 구역에서
    음수가 나온다 — 두 수는 같은 집합을 세지 않는다.
    """
    fleet = model(live)
    zone_id = fleet.zone_ids()[0]
    declared = [d["node_id"] for d in fleet.zone(zone_id).get("declared_nodes", ())]
    assert declared, "선언된 장치가 없으면 이 시험은 아무것도 지키지 않는다"

    silent = model(live)
    assert silent.zone_summary(zone_id)["declared_only_count"] == len(declared)

    heard = model(live, discovery=Discovery())
    heard.discovery.note(declared[0], ("perception.detect",))
    assert heard.zone_summary(zone_id)["declared_only_count"] == len(declared) - 1


# ---------------------------------------------------------------------------
# (f)(g)(h) 3D 소비자가 읽는 자리 — 바닥 평면과 세로 축
# ---------------------------------------------------------------------------


def test_the_floor_plane_repeats_the_zone_rect_and_names_its_own_frame(live):
    """바닥 평면을 따로 계산하면 반올림 한 자리에서 2D 도면과 3D 바닥이 갈린다."""
    fleet = model(live)
    zone_id = fleet.zone_ids()[0]
    detail = fleet.zone_detail(zone_id)
    floor = detail["floor"]

    assert floor["plane"] == detail["rect"]
    frame = floor["frame"]
    assert frame["domain_id"] == fleet.domain_of(zone_id)
    assert frame["level_id"] == fleet.zone(zone_id)["level_id"]
    assert frame["unit"] == detail["space"]["unit"]
    assert tuple(frame["plane_axes"]) == FLOOR_PLANE_AXES
    # 위쪽 축을 "z" 라고 부르지 않는다 — 이 계약의 y 는 바닥 위의 **깊이**이고,
    # 뷰어는 그것을 자기 쪽 Z 로 옮겨 Y 를 위로 쓴다. 서버가 위쪽을 z 라 적으면
    # 그 뷰어에서 깊이와 높이가 같은 이름이 된다.
    assert frame["up_axis"] == FLOOR_UP_AXIS != "z"
    # 자리 값에 위쪽 성분이 없다는 사실을 **적어 둔다.** 적지 않으면 받는 쪽이
    # 없는 축을 0 으로 채운다.
    assert frame["position_has_up_component"] is False
    assert "height_m" in frame["up_axis_cells"]


def test_only_a_declared_mounting_height_becomes_a_number(example):
    """천장 카메라의 2.4 m 는 숫자가 되고, 문의 높이는 상태만 남는다.

    0 으로 채우면 "바닥에 붙어 있다고 쟀다" 가 되고, 그 값을 받은 3D 뷰어는
    천장 카메라를 바닥에 놓는다(AI-C-02 · AI-S-08).
    """
    fleet = model(example)
    with_height, without = [], []
    for zone_id in fleet.zone_ids():
        detail = fleet.zone_detail(zone_id)
        for item in (*detail["infrastructure"], *detail["landmarks"]):
            (with_height if item["height_state"] == HEIGHT_DECLARED
             else without).append(item)

    assert with_height, "높이가 선언된 장치가 하나도 없으면 반대쪽만 보게 된다"
    for item in with_height:
        assert item["height_m"] == pytest.approx(item["pose"]["height_m"])
    for item in without:
        assert item["height_state"] == HEIGHT_UNMEASURED
        assert "height_m" not in item, "미측정인데 숫자 칸이 생겼다"


def test_the_zone_says_how_much_of_its_vertical_it_actually_knows(example):
    """"아무것도 모른다" 와 "절반은 안다" 가 한 수로 합쳐지면 안 된다(AI-S-03)."""
    fleet = model(example)
    for zone_id in fleet.zone_ids():
        zone = fleet.zone(zone_id)
        vertical = fleet.zone_detail(zone_id)["vertical"]
        placed = [*zone.get("infrastructure", ()), *zone.get("landmarks", ())]
        if fleet.access_point(zone_id) is not None:
            placed.append(zone.get("wifi") or {})
        declared = sum(1 for i in placed
                       if (i.get("pose") or {}).get("height_m") is not None)

        assert vertical["declared_height_count"] == declared
        assert vertical["unmeasured_height_count"] == len(placed) - declared
        assert vertical["up_axis"] == FLOOR_UP_AXIS


def test_a_fused_object_position_is_two_numbers_and_the_contract_says_so():
    """융합된 자리에는 z 가 **없다**. 없는 축을 0 으로 채우면 미측정이 측정이 된다.

    계약의 숫자를 융합 쪽 자료형과 묶어 둔다 — 한쪽이 3차원이 되는 날 이 시험이
    먼저 깨져야 하고, 조용히 어긋나서는 안 된다(AI-S-06).
    """
    from mission_runtime.tools.fms_console.twin import FusedRecord

    annotation = FusedRecord.__annotations__["fused_position"]
    dimensions = str(annotation).count("float")
    assert dimensions == OBJECT_POSITION_DIMENSIONS

    fleet = model(load_domain_profile(LIVE_PROFILE))
    vertical = fleet.zone_detail(fleet.zone_ids()[0])["vertical"]
    assert vertical["object_position_dimensions"] == OBJECT_POSITION_DIMENSIONS
    assert vertical["object_height_state"] == HEIGHT_UNMEASURED


# ---------------------------------------------------------------------------
# (i) 새 칸도 뜻만 낸다
# ---------------------------------------------------------------------------


#: 표현 결정을 가리키는 낱말(`tests/test_view_contract.py` 와 같은 뜻, 새 칸만 본다).
PRESENTATION_WORDS = frozenset({
    "color", "colour", "fill", "stroke", "font", "px", "pixel", "pixels",
    "opacity", "css", "style", "theme", "icon", "sprite", "shape", "marker",
    "rgb", "zindex", "margin", "padding", "viewbox", "tooltip", "cursor",
    "mesh", "material", "texture",
})


def _keys(node) -> set[str]:
    if isinstance(node, dict):
        out = set(map(str, node))
        for value in node.values():
            out |= _keys(value)
        return out
    if isinstance(node, list):
        out: set[str] = set()
        for item in node:
            out |= _keys(item)
        return out
    return set()


def test_the_new_cells_carry_no_presentation_decision(example):
    """세로 축이 들어왔다고 색·픽셀이 함께 따라 들어오면 안 된다.

    `floor` 와 `vertical` 은 3D 소비자를 위해 더한 칸이고, 그래서 바로 여기가
    머티리얼·메시·색이 새어 들어오기 쉬운 자리다(AI-C-15: 뷰어는 교체된다).
    """
    fleet = model(example)
    offenders = {}
    for zone_id in fleet.zone_ids():
        detail = fleet.zone_detail(zone_id)
        for block in ("floor", "vertical"):
            for key in _keys(detail[block]):
                bad = {w for w in re.split(r"[^a-z0-9]+", key.lower()) if w
                       } & PRESENTATION_WORDS
                if bad:
                    offenders[f"{zone_id}/{block}/{key}"] = sorted(bad)
    for domain_id in fleet.domain_ids():
        for level in fleet.domain_scene(domain_id)["levels"]:
            for key in _keys(level):
                bad = {w for w in re.split(r"[^a-z0-9]+", key.lower()) if w
                       } & PRESENTATION_WORDS
                if bad:
                    offenders[f"{domain_id}/level/{key}"] = sorted(bad)
    assert not offenders, offenders


def test_the_whole_drill_stays_json(example, live):
    """계약은 전송을 타고 나간다. 직렬화되지 않는 값이 섞이면 그 자리에서 끊긴다."""
    for profile in (example, live):
        fleet = model(profile)
        for domain_id in fleet.domain_ids():
            json.dumps(fleet.domain_scene(domain_id))
        for zone_id in fleet.zone_ids():
            json.dumps(fleet.zone_detail(zone_id))
