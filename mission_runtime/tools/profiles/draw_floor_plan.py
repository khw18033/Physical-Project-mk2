#!/usr/bin/env python3
"""장소 기하에서 **층 도면을 그려 낸다.**

측량 도면이 아니다. 가시화 파트가 Unity 씬에서 뽑은 장소 좌표(문 · 복도 · 503호
경계)로 그린 **개략도**이고, 그 사실을 그림 안에도 선언에도 적는다 — 측량 도면처럼
보이면 그것으로 거리를 재는 사람이 생긴다.

그릴 수 있는 것만 그린다. 좌표가 있는 장소 31곳만 나오고 좌표가 없는 방 20곳은
빠진다. 빠진 것을 네모로 채워 넣으면 그 방이 측량된 것처럼 보인다(AI-S-08).

나오는 그림의 픽셀↔미터 관계는 `build_from_vz.py` 가 쓴 구역 로컬 좌표와 **같은
축척**이고, 그래서 `config/map_tiles.example.json` 의 앵커 두 점이 계산 없이 맞는다.

implements: AI-C-02, AI-C-08, AI-S-08
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
VZ = ROOT / "local" / "vz"
OUT = ROOT / "local" / "maps" / "n4-5f.png"
PROFILE = Path(__file__).resolve().parents[2] / "profiles" / "domains.json"

PX_PER_M = 20          # 1 m = 20 px → 52.5 m 이면 1050 px
MARGIN_PX = 60

INK = (40, 43, 48)
WALL = (90, 96, 104)
FAINT = (205, 210, 218)
DOOR = (60, 60, 60)


def main() -> None:
    profile = json.loads(PROFILE.read_text())
    domain = profile["domains"][0]
    off = domain["frame_offset_from_site_global"]
    zone = domain["zones"][0]
    w_m, h_m = zone["rect"]["w"], zone["rect"]["h"]

    geo = json.loads((VZ / "places.geometry.json").read_text())["geometry"]
    places = {p["place_id"]: p
              for p in json.loads((VZ / "places.json").read_text())["places"]}

    W = int(w_m * PX_PER_M) + MARGIN_PX * 2
    H = int(h_m * PX_PER_M) + MARGIN_PX * 2
    img = np.full((H, W, 3), 252, np.uint8)

    def to_px(x_site, z_site):
        """site-global → 그림 픽셀. 프로파일이 쓴 것과 **같은** 평행이동이다."""
        return (int(MARGIN_PX + (x_site + off["x"]) * PX_PER_M),
                int(MARGIN_PX + (z_site + off["z"]) * PX_PER_M))

    # 1 m 눈금 — 도면에서 축척을 눈으로 읽을 수 있게.
    for m in range(0, int(w_m) + 1, 5):
        x = MARGIN_PX + m * PX_PER_M
        cv2.line(img, (x, MARGIN_PX), (x, H - MARGIN_PX), (238, 241, 245), 1)
    for m in range(0, int(h_m) + 1, 5):
        y = MARGIN_PX + m * PX_PER_M
        cv2.line(img, (MARGIN_PX, y), (W - MARGIN_PX, y), (238, 241, 245), 1)

    # 층 경계
    cv2.rectangle(img, (MARGIN_PX, MARGIN_PX),
                  (W - MARGIN_PX, H - MARGIN_PX), FAINT, 2)

    # 복도 — 선언된 축과 범위 그대로. 폭은 모르므로 **선 하나**로 그린다.
    for g in geo:
        if "span" not in g:
            continue
        a, b = g["span"]["from"], g["span"]["to"]
        # `axis` 는 **고정된** 축이고 `at` 이 그 축의 값이다. 복도는 나머지 축을
        # 따라 `span` 만큼 뻗는다. 반대로 읽으면 복도가 90도 돌아간다 — 문이 전부
        # z≈-45.97 에 줄지어 있는데 `axis:"z"` 인 복도를 세로로 그리면 그 줄과
        # 만나지 않는다는 데서 드러났다.
        if g["axis"] == "z":
            p0, p1 = to_px(a, g["at"]), to_px(b, g["at"])
        else:
            p0, p1 = to_px(g["at"], a), to_px(g["at"], b)
        cv2.line(img, p0, p1, WALL, 6)
        cv2.line(img, p0, p1, (246, 248, 250), 2)

    # 경계가 선언된 방 — 지금은 503호 하나뿐이다.
    for g in geo:
        if "bounds" not in g:
            continue
        p0 = to_px(g["bounds"]["x"]["from"], g["bounds"]["z"]["from"])
        p1 = to_px(g["bounds"]["x"]["to"], g["bounds"]["z"]["to"])
        cv2.rectangle(img, p0, p1, INK, 3)
        # OpenCV 의 Hershey 글꼴에는 한글이 없다 — `label`(503호)을 그리면 네모가
        # 나온다. 장소 id 는 ASCII 라 그대로 읽힌다.
        label = g["place_id"]
        cv2.putText(img, label, (min(p0[0], p1[0]) + 10, min(p0[1], p1[1]) + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, INK, 2)
        size = g.get("size_m", {})
        if size:
            cv2.putText(img, f"{size['width']} x {size['depth']} m",
                        (min(p0[0], p1[0]) + 10, min(p0[1], p1[1]) + 62),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, WALL, 1)

    # 문 · 계단 · 엘리베이터 — 점과 이름. 방은 좌표가 없어 나오지 않는다.
    for g in geo:
        if "position" not in g:
            continue
        place = places.get(g["place_id"], {})
        kind = place.get("kind")
        px = to_px(g["position"]["x"], g["position"]["z"])
        if kind == "door":
            cv2.line(img, (px[0] - 7, px[1]), (px[0] + 7, px[1]), DOOR, 3)
        elif kind in ("elevator", "stair"):
            cv2.rectangle(img, (px[0] - 9, px[1] - 9), (px[0] + 9, px[1] + 9), INK, 2)
            cv2.putText(img, "E" if kind == "elevator" else "S",
                        (px[0] - 6, px[1] + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, INK, 1)
        else:
            cv2.circle(img, px, 4, WALL, -1)

    # 이 그림이 무엇인지 그림 안에 적는다.
    cv2.putText(img, "N4 5F  schematic from place geometry - not a survey drawing",
                (MARGIN_PX, H - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.52, WALL, 1)
    cv2.putText(img, f"grid 5 m   scale 1 m = {PX_PER_M} px",
                (W - 320, H - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.52, WALL, 1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT), img)
    # 앵커 두 점 — 구역 로컬 (0,0) 과 (w,h) 가 어느 픽셀인가.
    print(f"wrote {OUT}  {W}x{H}px")
    print(f"  anchor A: local (0, 0)        -> px ({MARGIN_PX}, {MARGIN_PX})")
    print(f"  anchor B: local ({w_m}, {h_m}) -> px "
          f"({MARGIN_PX + int(w_m * PX_PER_M)}, {MARGIN_PX + int(h_m * PX_PER_M)})")


if __name__ == "__main__":
    main()
