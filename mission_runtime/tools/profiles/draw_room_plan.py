#!/usr/bin/env python3
"""방 하나의 **실내 개략도**를 그려 낸다 — 지도의 맨 아래 단.

층 도면에서 한 칸 더 들어간 자리다. 캠퍼스 그림 → 층 도면 → 이 그림 순으로 좁아
지고, 각 단은 앞 단의 맵 포인트를 눌러 들어간다.

측량 도면이 아니다. 가시화 파트가 선언한 방 경계(`bounds`)와 그 방에 달린 문
하나뿐이고, 책상·설비 같은 것은 **아무도 선언하지 않았으므로 그리지 않는다.**
비어 보이는 것이 맞다 — 채워 넣으면 그 순간 측량된 척하는 그림이 된다(AI-S-08).

좌표는 **방 로컬**이다. 원점이 방의 한 모서리이고, 층 도면의 구역 로컬 좌표와
같은 칸에 담지 않는다(AI-C-02). 앵커 두 점은 이 도구가 출력한 값 그대로
`config/map_tiles.example.json` 에 적는다.

implements: AI-C-02, AI-C-08, AI-S-08
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parents[2]
VZ = ROOT / "local" / "vz"
PROFILE = PACKAGE / "profiles" / "domains.json"

PX_PER_M = 60          # 방은 작으므로 층 도면(20)보다 촘촘하게 본다
MARGIN_PX = 70

INK = (40, 43, 48)
WALL = (90, 96, 104)
FAINT = (205, 210, 218)
GRID = (238, 241, 245)


def main() -> int:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    domain = profile["domains"][0]
    zone = domain["zones"][0]
    interiors = zone.get("interiors") or []
    if not interiors:
        print("들어갈 수 있는 방이 선언되어 있지 않다 — 그릴 것이 없다.")
        return 1

    geo = {g["place_id"]: g
           for g in json.loads((VZ / "places.geometry.json").read_text())["geometry"]}
    places = {p["place_id"]: p
              for p in json.loads((VZ / "places.json").read_text())["places"]}

    for room in interiors:
        rect = room["rect"]
        w_m, h_m = rect["w"], rect["h"]
        width = int(w_m * PX_PER_M) + MARGIN_PX * 2
        height = int(h_m * PX_PER_M) + MARGIN_PX * 2
        img = np.full((height, width, 3), 252, np.uint8)

        def to_px(x_room: float, y_room: float) -> tuple[int, int]:
            """방 로컬 미터 → 그림 픽셀. 원점은 방의 가까운 모서리다."""
            return (int(MARGIN_PX + x_room * PX_PER_M),
                    int(MARGIN_PX + y_room * PX_PER_M))

        # 1 m 눈금. 방에서는 1 m 가 읽을 만한 간격이다.
        for metre in range(0, int(w_m) + 1):
            x = MARGIN_PX + metre * PX_PER_M
            cv2.line(img, (x, MARGIN_PX), (x, height - MARGIN_PX), GRID, 1)
        for metre in range(0, int(h_m) + 1):
            y = MARGIN_PX + metre * PX_PER_M
            cv2.line(img, (MARGIN_PX, y), (width - MARGIN_PX, y), GRID, 1)

        # 벽 — 선언된 경계 그대로. 두께는 아무도 재지 않았으므로 선 하나다.
        cv2.rectangle(img, (MARGIN_PX, MARGIN_PX),
                      (width - MARGIN_PX, height - MARGIN_PX), WALL, 3)

        # 문 — 이 방에 달린 것만. 층 도면이 쓴 site-global 좌표를 방 로컬로
        # 옮긴다. 방 경계에서 먼 문은 이 방의 문이 아니므로 그리지 않는다.
        off = domain["frame_offset_from_site_global"]
        door_count = 0
        for place_id, place in sorted(places.items()):
            if place.get("kind") != "door":
                continue
            position = (geo.get(place_id) or {}).get("position")
            if not position:
                continue
            zone_x = position["x"] + off["x"]
            zone_y = position["z"] + off["z"]
            room_x = zone_x - rect["x"]
            room_y = zone_y - rect["y"]
            #: 벽에서 0.6 m 안쪽까지를 "이 방의 문" 으로 본다. 그보다 멀면 옆방
            #: 문이고, 끌어다 붙이면 없는 출입구가 생긴다.
            near_wall = (min(abs(room_x), abs(room_x - w_m)) <= 0.6
                         or min(abs(room_y), abs(room_y - h_m)) <= 0.6)
            inside = -0.6 <= room_x <= w_m + 0.6 and -0.6 <= room_y <= h_m + 0.6
            if not (inside and near_wall):
                continue
            px = to_px(max(0.0, min(w_m, room_x)), max(0.0, min(h_m, room_y)))
            cv2.circle(img, px, 9, (255, 255, 255), -1)
            cv2.circle(img, px, 9, INK, 2)
            cv2.putText(img, place_id, (px[0] + 13, px[1] + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, INK, 1)
            door_count += 1

        # 치수선 — 도면에서 치수는 장식이 아니라 근거다.
        cv2.putText(img, f"{w_m:.2f} m", (width // 2 - 34, MARGIN_PX - 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, INK, 1)
        cv2.putText(img, f"{h_m:.2f} m", (14, height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, INK, 1)
        cv2.putText(img, f"{room['room_id']}  interior schematic from declared "
                         f"bounds - not a survey drawing",
                    (MARGIN_PX, height - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                    (110, 116, 124), 1)

        out = ROOT / "local" / "maps" / f"{room['room_id']}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), img)
        print(f"wrote {out}  {width}x{height}px · {w_m} × {h_m} m · 문 {door_count}개")
        print(f"  anchor A: room-local (0, 0) -> px ({MARGIN_PX}, {MARGIN_PX})")
        print(f"  anchor B: room-local ({w_m}, {h_m}) -> px "
              f"({MARGIN_PX + w_m * PX_PER_M:.0f}, {MARGIN_PX + h_m * PX_PER_M:.0f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
