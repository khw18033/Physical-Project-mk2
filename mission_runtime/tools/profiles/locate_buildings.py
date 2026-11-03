"""현장 건물의 **자리**를 공개 지도에서 받아 현장 로컬 좌표로 옮긴다.

`fetch_site_map.py` 가 캠퍼스 그림을 받아 datum 에 앉혔다. 그림 위의 어느 점이
우리 도메인인지는 그림만으로는 알 수 없다 — 사람이 눈으로 찍으면 그 순간 그 값은
근거 없는 숫자가 된다. 그래서 건물 자리도 그림과 **같은 출처**에서 받아 같은
datum 으로 옮긴다. 그러면 배경과 핀이 한 사실에서 나온다.

로컬 프레임은 `fetch_site_map.py` 가 쓴 것과 같다 — 원점은 datum 이 가리키는
점이고, x 는 동쪽, **y 는 남쪽**(화면 아래)으로 자란다. 축척은 그 위도에서
Web Mercator 로 정확히 나온다.

**이것은 선언이지 관측이 아니다**(AI-S-08). 공개 지도가 적어 둔 건물 윤곽의
중심이고 우리가 잰 값이 아니다 — 그래서 `verified: false` 로 나가고, datum 자체가
미검증이면 그 오차가 여기에도 그대로 실린다. 보정판이 실제로 잰 값이 들어오면
그것이 이 값을 대체한다.

바깥 연결을 요구하므로 폐쇄망 배치에서는 돌지 않는다. 돌려 받은 값은 프로파일에
적히고, 그 뒤로는 저장된 선언만 읽는다(AI-C-16).

    python tools/profiles/locate_buildings.py              # 찾은 것을 보여만 준다
    python tools/profiles/locate_buildings.py --write       # 도메인 선언에 적는다

implements: AI-C-02, AI-S-08, AI-C-16
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2]
PROFILE = PACKAGE / "profiles" / "domains.json"

#: Overpass 는 자주 막히므로 거울을 몇 개 둔다. 하나라도 답하면 된다.
ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
AGENT = "mission-runtime-fms/0.1 (site building anchor lookup)"
ZOOM, TILE_PX = 18, 256
#: datum 둘레로 이만큼만 훑는다. 캠퍼스 하나를 덮으면 충분하다.
BOX_DEG = (0.005, 0.006)


def mercator_px(lat: float, lon: float) -> tuple[float, float]:
    """`fetch_site_map.py::deg2tile` 과 같은 식. 픽셀 단위까지 맞춰 둔다."""
    n = 2.0 ** ZOOM
    x = (lon + 180.0) / 360.0 * n * TILE_PX
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n * TILE_PX
    return x, y


def local_of(lat: float, lon: float, datum_lat: float, datum_lon: float) -> dict:
    """위경도 → 현장 로컬 미터. 원점은 datum, x 동쪽, y 남쪽."""
    m_per_px = 156543.03392 * math.cos(math.radians(datum_lat)) / (2 ** ZOOM)
    bx, by = mercator_px(lat, lon)
    ox, oy = mercator_px(datum_lat, datum_lon)
    return {"x": round((bx - ox) * m_per_px, 2), "y": round((by - oy) * m_per_px, 2)}


def ask_overpass(datum_lat: float, datum_lon: float) -> list[dict]:
    dlat, dlon = BOX_DEG
    box = (f"{datum_lat - dlat},{datum_lon - dlon},"
           f"{datum_lat + dlat},{datum_lon + dlon}")
    query = f'[out:json][timeout:50];way["building"]["name"]({box});out center tags;'
    last = ""
    for url in ENDPOINTS:
        try:
            request = urllib.request.Request(
                url, data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": AGENT})
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response).get("elements", [])
        except Exception as exc:                                  # noqa: BLE001
            last = f"{url} → {exc}"
            print(f"  (건너뜀) {last}", file=sys.stderr)
    raise SystemExit(f"공개 지도에 닿지 못했다. 마지막 사유: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="찾은 자리를 profiles/domains.json 의 도메인 선언에 적는다")
    args = parser.parse_args()

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    domains = profile["domains"]
    datum = (domains[0].get("site") or {}).get("datum")
    if not datum:
        print("이 현장에는 datum 이 없다 — 건물 자리를 옮길 기준이 없다.")
        return 1
    datum_lat = datum["reference_point"]["lat"]
    datum_lon = datum["reference_point"]["lon"]

    found = ask_overpass(datum_lat, datum_lon)
    print(f"공개 지도에서 이름 있는 건물 {len(found)} 개를 받았다 "
          f"(datum {datum_lat}, {datum_lon} · verified={datum['verified']})")

    located: dict[str, dict] = {}
    for element in sorted(found, key=lambda e: e["tags"].get("name", "")):
        centre = element.get("center") or {}
        if centre.get("lat") is None:
            continue
        at = local_of(centre["lat"], centre["lon"], datum_lat, datum_lon)
        name = element["tags"].get("name", "")
        located[name] = {
            "at": at,
            "osm": {"type": element["type"], "id": element["id"]},
            "lat": centre["lat"], "lon": centre["lon"],
        }
        print(f"  {name:<28} 로컬 x={at['x']:+8.2f}  y={at['y']:+8.2f}")

    if not args.write:
        print("\n--write 를 주면 도메인 선언에 적는다.")
        return 0

    #: 도메인이 자기 이름으로 공개 지도의 건물 하나를 가리킨다. 그 이름이 없으면
    #: 자리를 지어내지 않고 **그대로 둔다** — 못 찾은 것과 0 은 다르다.
    changed = 0
    for domain in domains:
        want = (domain.get("site") or {}).get("osm_building_name")
        if not want:
            print(f"  {domain['domain_id']}: site.osm_building_name 이 없어 건너뛴다")
            continue
        hit = located.get(want)
        if not hit:
            print(f"  {domain['domain_id']}: 공개 지도에 「{want}」 가 없다 — 자리를 비워 둔다")
            continue
        domain["site_local"] = {
            "at": hit["at"],
            "verified": False,
            "basis": "public_map_declaration",
            "source": {
                "kind": "public_map",
                "name": f"OpenStreetMap {hit['osm']['type']} {hit['osm']['id']} "
                        f"(「{want}」 건물 윤곽의 중심)",
                "license": "ODbL 1.0",
                "attribution": "© OpenStreetMap contributors",
                "reference_point": {"lat": hit["lat"], "lon": hit["lon"],
                                    "crs": "EPSG:4326"},
                "datum_id": datum["datum_id"],
            },
            "$note": "공개 지도가 적어 둔 자리이지 우리가 잰 값이 아니다. datum 이 "
                     "미검증이면 그 오차가 여기에도 그대로 실린다(AI-S-08).",
        }
        changed += 1
        print(f"  {domain['domain_id']}: 로컬 {hit['at']} 로 적었다")

    if changed:
        PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        print(f"\n{PROFILE} 에 {changed} 개를 적었다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
