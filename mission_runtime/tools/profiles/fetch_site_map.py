#!/usr/bin/env python3
"""현장 배경 지도를 **공개 지도에서** 받아 한 장으로 잇는다.

왜 OpenStreetMap 인가: 쓸 수 있는 지도 중에 **약관이 분명한** 것이기 때문이다.
포털 지도 화면을 캡처해 쓰는 쪽이 그림은 예쁘지만, 그 그림에는 이용 약관이
따라붙고 저장소에 들어가는 순간 그 사실이 어디에도 남지 않는다. OSM 은 ODbL 이고
출처를 적으면 쓸 수 있어서, 선언의 `source.license` 가 비어 있지 않게 된다.

**자리는 datum 이 정한다.** 타일 한 장의 네 모서리 위경도는 줌 단계에서 정확히
나오고(Web Mercator), datum 이 위경도↔현장 로컬 (0,0) 을 잇는다. 그래서 픽셀↔미터
변환은 수학적으로 정확하다 — **다만 datum 자체가 미검증이면 그림 전체가 그만큼
통째로 밀려 있다.** 찌그러지지는 않고 평행이동한다. 그 사실을 선언의 `source` 에
적어 두는 것이 이 도구가 하는 마지막 일이다(AI-C-02).

받은 그림은 공개 트리 밖(`local/maps/`)에 둔다.

implements: AI-C-02, AI-C-08, AI-C-16
"""
from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROFILE = Path(__file__).resolve().parents[2] / "profiles" / "domains.json"
OUT = ROOT / "local" / "maps" / "site-osm.png"

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
#: OSM 타일 이용 정책이 요구하는 식별. 익명 대량 요청은 차단 대상이다.
AGENT = "mission-runtime/1.0 (site background, one-off; contact: project internal)"
ZOOM = 18
TILE_PX = 256
#: 받을 타일 격자. datum 은 **캠퍼스 전체**의 대표점이라 N4동은 그 가운데가
#: 아니다 — 3×3(약 350 m)으로는 N4 가 위쪽에서 잘렸다. 5×5 로 넓혀 건물이 통째로
#: 들어오게 한다. 앵커 계산은 격자 크기와 무관하게 datum 픽셀에서 나온다.
GRID = 5


def deg2tile(lat: float, lon: float, z: int) -> tuple[float, float]:
    rad = math.radians(lat)
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * n
    return x, y


def main() -> int:
    profile = json.loads(PROFILE.read_text())
    domain = profile["domains"][0]
    datum = (domain["site"] or {}).get("datum")
    if not datum:
        print("이 현장에는 datum 이 없다 — 배경 지도를 놓을 자리를 알 수 없다.")
        return 1
    lat = datum["reference_point"]["lat"]
    lon = datum["reference_point"]["lon"]

    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    tx, ty = deg2tile(lat, lon, ZOOM)
    x0, y0 = int(tx) - GRID // 2, int(ty) - GRID // 2
    canvas = np.zeros((TILE_PX * GRID, TILE_PX * GRID, 3), np.uint8)
    for row in range(GRID):
        for col in range(GRID):
            url = TILE_URL.format(z=ZOOM, x=x0 + col, y=y0 + row)
            request = urllib.request.Request(url, headers={"User-Agent": AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = np.frombuffer(response.read(), np.uint8)
            tile = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            if tile is None:
                print(f"타일을 읽지 못했다: {url}")
                return 1
            canvas[row * TILE_PX:(row + 1) * TILE_PX,
                   col * TILE_PX:(col + 1) * TILE_PX] = tile

    # 출처를 그림 안에 적는다. ODbL 이 요구하는 것이고, 그림만 떼어 가도 남는다.
    cv2.rectangle(canvas, (0, canvas.shape[0] - 22),
                  (canvas.shape[1], canvas.shape[0]), (255, 255, 255), -1)
    cv2.putText(canvas, "(c) OpenStreetMap contributors - ODbL 1.0",
                (8, canvas.shape[0] - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT), canvas)

    # datum 이 가리키는 점의 그림 안 픽셀.
    px = (tx - x0) * TILE_PX
    py = (ty - y0) * TILE_PX
    # 그 위도에서 1 픽셀이 몇 미터인가. 이것이 축척이고 줌에서 정확히 나온다.
    m_per_px = 156543.03392 * math.cos(math.radians(lat)) / (2 ** ZOOM)
    # 현장 로컬 (0,0) 이 datum 점이므로 그 점이 앵커 A 다. 앵커 B 는 로컬 x·y 로
    # 100 m 떨어진 점이고, 로컬 y 는 **남쪽**(화면 아래)으로 자란다.
    span_m = 100.0
    print(f"wrote {OUT}  {canvas.shape[1]}x{canvas.shape[0]}px")
    print(f"  zoom {ZOOM} · {m_per_px:.4f} m/px · datum {lat}, {lon} (verified={datum['verified']})")
    print(f"  anchor A: local (0, 0)         -> px ({px:.1f}, {py:.1f})")
    print(f"  anchor B: local ({span_m}, {span_m}) -> px "
          f"({px + span_m / m_per_px:.1f}, {py + span_m / m_per_px:.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
