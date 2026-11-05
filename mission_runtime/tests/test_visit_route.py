"""방문 순서를 자리에 앉히고 추적한다 — 경계와 결손을 고정한다.

여기서 지키려는 것은 셋이다.

1. **주행 경로를 만들지 않는다.** 내는 거리는 직선이고 이름이 그렇게 박혀 있다.
   `distance_m` 으로 바뀌는 날 받는 쪽이 도착 시각을 계산하기 시작한다.
2. **모르는 자리를 지어내지 않는다.** 선언에 없으면 좌표를 비우고 사유를 남기되
   순서에서 빼지는 않는다 — 빼면 순서가 조용히 짧아진다.
3. **안 보고 있는 것과 가고 있는 것을 구분한다.** 위치 관측이 없으면 진행을
   추측하지 않는다.

implements: AI-B-12, AI-C-02, AI-C-19, AI-S-08
tests: boundary naming, undeclared place, no observation, arrival, backtracking
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from planning.visit_route import (  # noqa: E402
    REASON_NO_COORDINATE,
    REASON_UNDECLARED,
    places_from_zone,
    resolve,
    route_payload,
    track,
)

ZONE = {
    "landmarks": [
        {"id": "door-a", "kind": "door", "at": {"x": 0.0, "y": 0.0}},
        {"id": "door-b", "kind": "door", "at": {"x": 10.0, "y": 0.0}},
        {"id": "stair-x", "kind": "stair", "at": {"x": 20.0, "y": 0.0}},
        {"id": "door-nowhere", "kind": "door"},          # 선언은 있고 좌표가 없다
    ],
    "interiors": [{"room_id": "room-1", "rect": {"x": 4.0, "y": 4.0, "w": 2.0, "h": 2.0}}],
    "wifi": {"ap_id": "ap-1", "rf": "indoor", "at": {"x": 5.0, "y": 5.0}},
}

ORDER = (("door-a", "t1", 0), ("door-b", "t2", 1), ("stair-x", "t3", 2))


# ── 경계 ────────────────────────────────────────────────────────────────────

def test_the_payload_says_out_loud_that_it_is_not_a_driving_path():
    """경로 계획은 우리 것이 아니다. **데이터가 그렇게 말해야** 받는 쪽이 안 헷갈린다."""
    payload = route_payload(ORDER, ZONE, {"x": 0.0, "y": 0.0})

    assert payload["kind"] == "visit_order"
    assert payload["is_driving_path"] is False


def test_the_distance_is_named_straight_line_not_distance():
    """이름이 곧 계약이다.

    `distance_m` 으로 두면 받는 쪽이 그것을 주행 거리로 읽고 도착 시각을 계산한다.
    벽을 돌아가는 실제 거리는 직선보다 길다.
    """
    payload = route_payload(ORDER, ZONE, {"x": 0.0, "y": 0.0})
    progress = payload["progress"]

    assert "straight_line_to_next_m" in progress
    assert "distance_m" not in progress
    assert not any(k == "distance_m" for stop in payload["stops"] for k in stop)


def test_every_coordinate_carries_its_frame_and_never_claims_global():
    payload = route_payload(ORDER, ZONE, {"x": 0.0, "y": 0.0})

    assert payload["frame"] == "zone-local" and payload["unit"] == "meter"
    for stop in payload["stops"]:
        if "at" in stop:
            assert stop["frame"] == "zone-local"
            assert "global" not in stop["frame"]


# ── 결손 ────────────────────────────────────────────────────────────────────

def test_an_undeclared_place_keeps_its_slot_and_says_why():
    """빼 버리면 순서가 조용히 짧아지고 왜 짧은지 아무도 모른다."""
    stops = resolve((("door-a", "t1", 0), ("ghost", "t2", 1)), places_from_zone(ZONE))

    assert len(stops) == 2, "못 찾은 자리도 순서에 남는다"
    assert stops[1].place is None and stops[1].reason == REASON_UNDECLARED
    assert "at" not in stops[1].as_payload(), "모르는 자리에 좌표를 지어내지 않는다"


def test_a_declared_place_without_a_coordinate_is_a_different_state():
    """선언에 없는 것과 선언은 있는데 좌표가 없는 것은 다르다."""
    stops = resolve((("door-nowhere", "t1", 0),), places_from_zone(ZONE))

    assert stops[0].place is not None
    assert stops[0].reason == REASON_NO_COORDINATE


def test_declared_places_are_not_marked_verified():
    """선언된 자리이지 측량된 자리가 아니다(AI-S-08)."""
    payload = route_payload(ORDER, ZONE, {"x": 0.0, "y": 0.0})

    for stop in payload["stops"]:
        if "at" in stop:
            assert stop["verified"] is False


# ── 추적 ────────────────────────────────────────────────────────────────────

def test_without_an_observed_position_progress_is_not_guessed():
    """추측해 채우면 화면이 "가고 있다" 로 읽는데 사실은 아무도 안 보고 있다."""
    progress = track(resolve(ORDER, places_from_zone(ZONE)), None)

    assert progress.reason == "no_observed_position"
    assert progress.at_index is None and progress.arrived is False
    assert progress.straight_line_to_next_m is None
    assert progress.next_index == 0, "아직 안 지난 첫 자리는 가리킨다"


def test_standing_on_a_stop_counts_as_arrived_and_points_at_the_next():
    stops = resolve(ORDER, places_from_zone(ZONE))
    progress = track(stops, {"x": 0.2, "y": 0.0})

    assert progress.arrived is True and progress.at_index == 0
    assert progress.next_index == 1
    assert progress.straight_line_to_next_m == 9.8


def test_between_stops_the_nearest_is_the_next_not_the_one_behind():
    """되돌아가는 임무가 있다. 지나왔다고 단정하지 않는다.

    x=6 은 door-a(0)에서 6 m · door-b(10)에서 4 m 라 어느 쪽 도착 반경에도 없다.
    """
    stops = resolve(ORDER, places_from_zone(ZONE))
    progress = track(stops, {"x": 6.0, "y": 0.0})

    assert progress.arrived is False and progress.at_index is None
    assert progress.next_index == 1, "가장 가까운 door-b 가 다음 자리다"
    assert progress.straight_line_to_next_m == 4.0


def test_a_zone_with_no_located_stop_says_so():
    stops = resolve((("door-nowhere", "t1", 0),), places_from_zone(ZONE))
    progress = track(stops, {"x": 0.0, "y": 0.0})

    assert progress.reason == "no_located_stop"
    assert progress.located_stops == 0 and progress.total_stops == 1


# ── 선언 읽기 ───────────────────────────────────────────────────────────────

def test_rooms_become_places_but_keep_the_fact_that_they_were_areas():
    places = places_from_zone(ZONE)

    assert places["room-1"].kind == "room", "점이 아니라 영역이었다는 사실이 남는다"
    assert places["room-1"].at == {"x": 5.0, "y": 5.0}


def test_the_access_point_is_a_place_too():
    """AP 는 장치가 아니지만 **자리**이고, 임무가 그리로 갈 수 있다."""
    assert places_from_zone(ZONE)["ap-1"].kind == "access_point"


def test_the_real_site_declaration_resolves():
    """출하되는 선언으로 실제로 돈다 — 시험용 자료만으로 통과하지 않게."""
    import json  # noqa: PLC0415

    profile = json.loads((Path(__file__).resolve().parents[1]
                          / "profiles" / "domains.json").read_text(encoding="utf-8"))
    zone = profile["domains"][0]["zones"][0]
    places = places_from_zone(zone)

    assert len(places) >= 30, "문 26 · 계단 3 · 승강기 1 · 방 1 · AP 1"
    assert places["door-503"].located
    assert places["room-503"].kind == "room"
