"""방문 순서를 **자리에 앉히고** 그 위에서 진행을 추적한다.

`replanning.py` 의 `visit_order()` 는 들를 자리를 **이름으로만** 낸다 — 그 모듈의
주석이 "자리의 좌표도 거리도 여기서 내지 않는다" 고 적어 두었고 그 결정을 바꾸지
않는다. 이 모듈은 그 순서를 **소비해서** 선언된 자리에 앉히고, 관측된 위치로 어디까지
왔는지를 해석한다.

## 주행 경로를 만들지 않는다

이 저장소는 이미 정해 두었다 — **경로 계획은 우리 것이 아니다**(FMS 콘솔의 경로 선이
점선이고 범례가 "계획된 순서" 라고 적는 이유다). 실증 배치에서도 유니티가 경로를
내고 `go1_sdk_pc.cpp` 가 그것을 받아 달린다. 그래서 여기서 내는 것은 셋뿐이다.

1. **들를 자리의 좌표** — 선언된 랜드마크를 찾아본 결과이지 우리가 그린 길이 아니다
2. **직선 거리** — `straight_line_m` 이라고 이름을 박는다. 주행 거리가 **아니다**
3. **어디까지 왔는가** — 관측된 위치를 순서에 비추어 해석한 것(이것이 우리 몫이다)

벽을 돌아가는 실제 거리는 직선보다 길다. 이름을 `distance_m` 으로 두면 받는 쪽이
그것을 주행 거리로 읽고 도착 시각을 계산한다 — 그래서 이름에 `straight_line` 을
남긴다.

## 자리를 모르면 비운다

선언에 없는 이름은 **좌표를 지어내지 않는다.** `at=None` 과 사유가 함께 나가고,
그 자리는 진행률 계산에서 빠진다. 0 이나 구역 중심으로 채우면 화면이 그것을 아는
자리로 읽는다(AI-S-08).

## 좌표계

전부 **구역 로컬 미터**다. 전역이라고 주장하지 않는다 — 이 현장 datum 은 미검증이고
경계 재합의도 끝나지 않았다(AI-C-02). 모든 값이 `frame` 을 들고 다닌다.

implements: AI-B-12, AI-C-02, AI-C-19, AI-S-08
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

#: 자리를 못 찾은 사유. 셋을 구분한다 — 이름이 선언에 없는 것과, 선언은 있는데
#: 좌표가 없는 것과, 아예 묻지 않은 것은 다른 상태다.
REASON_UNDECLARED = "place_not_declared"
REASON_NO_COORDINATE = "place_has_no_coordinate"

#: 이 거리 안이면 "그 자리에 있다" 로 본다. 선언된 랜드마크의 좌표 정밀도와 로봇
#: 자기보고 오차를 합친 어림이고, **측정으로 정한 값이 아니다** — 현장에서 재면
#: 그 값으로 바꾼다. 그래서 인자로 바꿀 수 있다.
DEFAULT_ARRIVAL_M = 1.5


@dataclass(frozen=True)
class Place:
    """선언된 자리 하나. 좌표가 없을 수 있고, 없는 것이 정상이다."""

    place_id: str
    kind: str
    at: Mapping[str, float] | None
    frame: str = "zone-local"
    verified: bool = False

    @property
    def located(self) -> bool:
        return self.at is not None


def places_from_zone(zone: Mapping) -> dict[str, Place]:
    """구역 선언에서 자리를 모은다 — 랜드마크 · 방 · AP.

    **선언을 읽을 뿐 아무것도 계산하지 않는다.** 방은 경계의 가운데를 자리로 쓰되
    그 사실이 `kind="room"` 으로 남는다(점이 아니라 영역이었다는 뜻이다).
    """
    out: dict[str, Place] = {}
    for mark in zone.get("landmarks", ()) or ():
        at = mark.get("at")
        out[mark["id"]] = Place(place_id=mark["id"], kind=mark.get("kind", "landmark"),
                                at=dict(at) if at else None,
                                verified=bool(mark.get("verified", False)))
    for room in zone.get("interiors", ()) or ():
        rect = room.get("rect") or {}
        at = ({"x": rect["x"] + rect["w"] / 2, "y": rect["y"] + rect["h"] / 2}
              if {"x", "y", "w", "h"} <= set(rect) else None)
        out[room["room_id"]] = Place(place_id=room["room_id"], kind="room", at=at,
                                     verified=bool(room.get("verified", False)))
    wifi = zone.get("wifi") or {}
    if wifi.get("ap_id"):
        at = wifi.get("at")
        out[wifi["ap_id"]] = Place(place_id=wifi["ap_id"], kind="access_point",
                                   at=dict(at) if at else None,
                                   verified=bool(wifi.get("placement_verified", False)))
    return out


@dataclass(frozen=True)
class Stop:
    """순서 위의 한 자리."""

    index: int
    place_id: str
    subtask_id: str | None
    place: Place | None
    reason: str | None = None

    def as_payload(self) -> dict:
        body: dict = {"index": self.index, "place_id": self.place_id,
                      "subtask_id": self.subtask_id}
        if self.place is not None and self.place.located:
            body["at"] = dict(self.place.at or {})
            body["frame"] = self.place.frame
            body["kind"] = self.place.kind
            # 선언된 자리이지 측량된 자리가 아니다. 받는 쪽이 이 칸을 보고
            # 측량값처럼 그리지 않게 한다(AI-S-08).
            body["verified"] = self.place.verified
        else:
            body["reason"] = self.reason or REASON_UNDECLARED
        return body


def resolve(visit_order: Iterable[tuple[str, str, int]],
            places: Mapping[str, Place]) -> list[Stop]:
    """이름 순서 → 자리 순서. 못 찾은 것은 **빼지 않고 사유와 함께 남긴다**.

    빼 버리면 화면의 순서가 조용히 짧아지고, 왜 짧은지 아무도 모른다.
    """
    stops: list[Stop] = []
    for index, row in enumerate(visit_order):
        place_id, subtask_id = row[0], (row[1] if len(row) > 1 else None)
        place = places.get(place_id)
        if place is None:
            stops.append(Stop(index, place_id, subtask_id, None, REASON_UNDECLARED))
        elif not place.located:
            stops.append(Stop(index, place_id, subtask_id, place, REASON_NO_COORDINATE))
        else:
            stops.append(Stop(index, place_id, subtask_id, place))
    return stops


def _straight_line_m(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    return math.hypot(float(b["x"]) - float(a["x"]), float(b["y"]) - float(a["y"]))


@dataclass
class Progress:
    """관측된 위치를 순서에 비추어 읽은 결과. **해석이지 명령이 아니다.**"""

    at_index: int | None
    next_index: int | None
    arrived: bool
    straight_line_to_next_m: float | None
    located_stops: int
    total_stops: int
    reason: str | None = None

    def as_payload(self) -> dict:
        body = {
            "at_index": self.at_index,
            "next_index": self.next_index,
            "arrived": self.arrived,
            # **직선이다.** 주행 거리가 아니다 — 벽을 돌아가면 이보다 길다.
            "straight_line_to_next_m": (None if self.straight_line_to_next_m is None
                                        else round(self.straight_line_to_next_m, 2)),
            "located_stops": self.located_stops,
            "total_stops": self.total_stops,
        }
        if self.reason is not None:
            body["reason"] = self.reason
        return body


def track(stops: list[Stop], observed_at: Mapping[str, float] | None, *,
          arrival_m: float = DEFAULT_ARRIVAL_M) -> Progress:
    """지금 어디까지 왔는가.

    위치 관측이 없으면 **진행을 추측하지 않는다** — `reason="no_observed_position"`
    이고 다음 자리는 아직 안 지난 첫 자리다. 추측해서 채우면 화면이 "가고 있다" 로
    읽는데 사실은 아무도 안 보고 있는 것이다(AI-O-04).
    """
    located = [s for s in stops if s.place is not None and s.place.located]
    if observed_at is None:
        nxt = located[0].index if located else None
        return Progress(at_index=None, next_index=nxt, arrived=False,
                        straight_line_to_next_m=None, located_stops=len(located),
                        total_stops=len(stops), reason="no_observed_position")
    if not located:
        return Progress(at_index=None, next_index=None, arrived=False,
                        straight_line_to_next_m=None, located_stops=0,
                        total_stops=len(stops), reason="no_located_stop")

    distances = [(s, _straight_line_m(observed_at, s.place.at)) for s in located]  # type: ignore[arg-type]
    nearest, nearest_m = min(distances, key=lambda row: row[1])
    arrived = nearest_m <= arrival_m

    after = [s for s in located if s.index > nearest.index]
    if arrived:
        nxt = after[0] if after else None
    else:
        # 아직 도착하지 않았으면 **가장 가까운 자리가 다음 자리**다. 이미 지난
        # 자리로 보이더라도 그렇게 단정하지 않는다 — 되돌아가는 임무가 있다.
        nxt = nearest
    to_next = (_straight_line_m(observed_at, nxt.place.at)      # type: ignore[arg-type]
               if nxt is not None else None)
    return Progress(at_index=nearest.index if arrived else None,
                    next_index=nxt.index if nxt is not None else None,
                    arrived=arrived, straight_line_to_next_m=to_next,
                    located_stops=len(located), total_stops=len(stops))


def route_payload(visit_order: Iterable[tuple[str, str, int]],
                  zone: Mapping,
                  observed_at: Mapping[str, float] | None = None,
                  *, arrival_m: float = DEFAULT_ARRIVAL_M) -> dict:
    """화면이 그대로 읽는 한 덩어리.

    **색·픽셀·폰트가 없다**(AI-C-08 · 뷰 계약). 좌표는 전부 구역 로컬이다.
    """
    places = places_from_zone(zone)
    stops = resolve(visit_order, places)
    progress = track(stops, observed_at, arrival_m=arrival_m)
    return {
        "frame": "zone-local",
        "unit": "meter",
        # 길을 그리지 않았다는 사실을 **데이터가 말한다**. 받는 쪽이 이것을 주행
        # 경로로 읽지 않게 한다 — 경로 계획은 우리 것이 아니다(AI-C-19).
        "kind": "visit_order",
        "is_driving_path": False,
        "arrival_m": arrival_m,
        "stops": [s.as_payload() for s in stops],
        "progress": progress.as_payload(),
    }
