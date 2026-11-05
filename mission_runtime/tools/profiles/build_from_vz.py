#!/usr/bin/env python3
"""VZ 의 장소 계약에서 **실제 배치 프로파일**을 짓는다.

예시를 지우고 실제만 남기려면, 그 "실제" 가 어디서 왔는지가 파일에 적혀 있어야
한다. 이 도구는 두 곳에서만 읽는다.

* 가시화 파트(`upstream/khw_VZ`)의 `places/places.json` · `places.geometry.json` —
  N4동 5층의 장소 위상과 Unity 월드 좌표. **그쪽이 정본이고 우리는 소비자다**
  (CLAUDE.md: 생성 주체의 계약을 소비하고 중복 구현하지 않는다).
* 하드웨어 파트(`upstream/HW`)의 조인 선언 — `go1-001`(go1) · `ep-001`
  (robomaster_ep). 로봇 신원은 `(node_id, robot_type, robot_id)` 이고 좌표는
  Unity 월드 X·Z 다(`HW-interface/coordinate-contract.md`).

좌표계: VZ 의 `site-global` 은 음수 구간에 있다. 우리 구역 좌표는 0 부터 시작하는
미터라서 **평행이동 한 번**으로 옮기고 그 오프셋을 프로파일에 적는다 — 적어 두지
않으면 두 좌표가 서로 다른 말을 하기 시작한다(AI-C-02: 모든 공간 값은 끝까지 자기
기준 좌표계를 들고 다닌다).

기하가 **없는** 장소는 자리를 지어내지 않고 빼놓는다. 방 20곳이 그렇다 — 문은
좌표가 있고 방 자체는 없다. 없는 좌표를 만들어 넣으면 그 방이 실제로 측량된 것처럼
보인다(AI-S-08).

implements: AI-C-02, AI-C-15, AI-S-08, AI-C-18
"""
from __future__ import annotations

import json
from pathlib import Path

# `local/` 은 `mission_runtime/` 과 **나란히** 있다(저장소 루트 아래). 한 칸 안쪽을
# 보면 영원히 못 찾는다 — `tools/fms_console/fleet.py::_asset_root()` 가 같은 실수를 하고 있었다.
VZ = Path(__file__).resolve().parents[3] / "local" / "vz"
OUT = Path(__file__).resolve().parents[2] / "profiles" / "domains.json"

#: 하드웨어 파트가 선언한 로봇. 어휘와 기종은 그쪽 조인 선언이 정본이다.
HW_ROBOTS = [
    {"node_id": "go1-001", "robot_type": "go1", "relay": "pi7"},
    {"node_id": "ep-001", "robot_type": "robomaster_ep", "relay": "pi1"},
]

#: 실내 RF 모델. `author_zones.py --check` 가 반경을 이 모델에서 되계산해 본다.
INDOOR_RF = {
    "model": "log_distance", "band": "5GHz", "tx_eirp_dbm": 20.0,
    "reference_loss_db_at_1m": 46.0, "path_loss_exponent": 3.5,
    "radius_m": {"excellent": 3.5, "handover": 25.1, "floor": 48.5},
    "thresholds_dbm": {"excellent": -45.0, "handover": -75.0, "floor": -85.0},
}

LANDMARK_KINDS = {"door": "door", "elevator": "elevator", "stair": "stair"}

#: 현장 로컬↔전역 기준점. 공개 지도 조회 결과이고 **검증되지 않았다** —
#: 정확도가 미측정이므로 0 오차가 아니고, 이 datum 으로 유도한 전역 값은
#: 그 재료인 로컬 실측보다 정확한 척할 수 없다(AI-C-02).
DATUM = {'datum_id': 'hanbat-n4-site-2026-11-03',
 'version': '2026-11-03.1',
 'created_at': '2026-11-03T10:00:00+09:00',
 'verified': False,
 'reference_point': {'lat': 36.3503355,
                     'lon': 127.3003088,
                     'crs': 'EPSG:4326',
                     'elevation_m': None},
 'accuracy_m': None,
 'accuracy_basis': 'unmeasured',
 'source': {'kind': 'public_map',
            'name': 'OpenStreetMap — 국립한밭대학교(way 74273291, amenity=university)를 '
                    "Nominatim 으로 조회한 결과. 선언된 주소 '대전 유성구 동서대로 125' 와 같은 대상이다.",
            'url': 'https://www.openstreetmap.org/way/74273291',
            'query_url': 'https://nominatim.openstreetmap.org/search?q=Hanbat+National+University&format=json',
            'retrieved_at': '2026-11-03',
            'license': 'ODbL 1.0 (© OpenStreetMap contributors)'},
 'local_frame': {'anchor': 'space_origin',
                 'anchor_basis': 'assumed',
                 'x_bearing_deg': 90.0,
                 'y_bearing_deg': 180.0,
                 'bearing_basis': 'assumed',
                 'level_stacked': True,
                 'level_axis': 'y'},
 '$note': '기준점은 **캠퍼스 중심**이고 N4동 산업정보관의 모서리가 아니다. 두 점의 어긋남을 재지 않았으므로 accuracy_m 은 '
          'null 이며 이것은 0 이 아니다(AI-C-02: "미측정 정확도는 0 오차가 아니다"). 로컬 (0,0) 이 이 기준점이라는 '
          '것과 방위 둘도 실측이 아니라 가정이다(anchor_basis·bearing_basis = assumed). 또 이 도메인의 로컬 '
          "평면은 층을 +y 로 쌓아 놓은 것이어서(levels[].y_offset) 평면 y 는 'y - 그 층의 y_offset' 이다 — "
          '그 보정 없이 전역으로 올리면 4층이 1층보다 72 m 남쪽에 놓인다. verified 가 false 인 동안 전역 계층은 '
          '비활성이고 로컬 좌표만 쓴다(사유 datum_unverified).'}


def load():
    places = {p["place_id"]: p
              for p in json.loads((VZ / "places.json").read_text())["places"]}
    geo = json.loads((VZ / "places.geometry.json").read_text())["geometry"]
    return places, {g["place_id"]: g for g in geo}


def extent(geo):
    xs, zs = [], []
    for g in geo.values():
        if "position" in g:
            xs.append(g["position"]["x"]); zs.append(g["position"]["z"])
        elif "span" in g:
            a, b = g["span"]["from"], g["span"]["to"]
            (zs if g["axis"] == "z" else xs).extend([a, b])
            (xs if g["axis"] == "z" else zs).append(g["at"])
        elif "bounds" in g:
            xs += [g["bounds"]["x"]["from"], g["bounds"]["x"]["to"]]
            zs += [g["bounds"]["z"]["from"], g["bounds"]["z"]["to"]]
    return min(xs), max(xs), min(zs), max(zs)


def build():
    places, geo = load()
    x0, x1, z0, z1 = extent(geo)
    pad = 1.0
    # site-global → zone-local 평행이동. 회전도 배율도 없다.
    off_x, off_z = -(x0 - pad), -(z0 - pad)
    width = round((x1 - x0) + pad * 2, 2)
    depth = round((z1 - z0) + pad * 2, 2)

    def local(x, z):
        return {"x": round(x + off_x, 2), "y": round(z + off_z, 2)}

    # 문·계단·엘리베이터는 **장소 지물이지 장치가 아니다.** 인프라 칸에 넣으면
    # 장치 목록에 문 26개가 들어오고, 운영자가 모니터링에서 "문"을 고르게 된다.
    # 고를 수 있는 것과 지도에 그려질 것은 다른 목록이다(AI-C-18: 상위 기능은
    # 필요한 capability 로 구성요소를 찾는다 — 문은 아무 capability 도 내지 않는다).
    landmarks = []
    for pid, place in sorted(places.items()):
        kind = LANDMARK_KINDS.get(place["kind"])
        g = geo.get(pid)
        if kind is None or g is None or "position" not in g:
            continue
        landmarks.append({"id": pid, "kind": kind, "label": place.get("label", pid),
                          "at": local(g["position"]["x"], g["position"]["z"])})

    lab = geo.get("room-503", {})
    anchors = lab.get("anchors", {})
    declared = []
    for robot in HW_ROBOTS:
        anchor = anchors.get(robot["robot_type"]) or anchors.get("go1")
        row = {"node_id": robot["node_id"]}
        # 자리를 아는 로봇만 자리를 적는다. 모르면 선언만 하고 자리는 비운다 —
        # 그 로봇은 "선언됐으나 아직 어디인지 모름" 으로 화면에 남는다.
        if robot["robot_type"] == "go1" and anchor:
            row["at"] = local(anchor["x"], anchor["z"])
        declared.append(row)

    rooms = [p["label"] for pid, p in sorted(places.items())
             if p["kind"] == "room"]

    # 안으로 더 들어갈 수 있는 방 — **기하가 있는 방만**이다. 이름만 있는 방은
    # 여기 들어오지 않는다. 그래야 화면이 "들어갈 수 있다"고 말한 자리가 실제로
    # 열린다(AI-S-08: 선언과 관측을 가르고, 없는 것을 있는 척하지 않는다).
    interiors = []
    for pid, place in sorted(places.items()):
        g = geo.get(pid)
        if place["kind"] != "room" or not g or "bounds" not in g:
            continue
        bounds = g["bounds"]
        near = local(bounds["x"]["from"], bounds["z"]["from"])
        far = local(bounds["x"]["to"], bounds["z"]["to"])
        entry = {
            "room_id": pid,
            "label": place.get("label", pid),
            "rect": {"x": min(near["x"], far["x"]), "y": min(near["y"], far["y"]),
                     "w": round(abs(far["x"] - near["x"]), 2),
                     "h": round(abs(far["y"] - near["y"]), 2)},
            "size_m": g.get("size_m"),
            "verified": False,
        }
        interior = g.get("interior") or {}
        if interior:
            # 실내 장면의 **참조**만 적는다. 그 장면을 여는 일은 가시화 몫이고
            # 여기 적힌 것은 "더 들어갈 자리가 있다"는 사실이다(AI-C-19).
            entry["interior"] = {k: interior[k] for k in ("scene", "anchor")
                                 if k in interior}
        interiors.append(entry)

    zone = {
        "zone_id": "zone-503",
        "label": {"ko": "N4동 5층 — 503호 구역", "en": "N4 5F — zone 503"},
        "level_id": "N4-5F",
        "verified": False,
        "rect": {"x": 0, "y": 0, "w": width, "h": depth},
        "rooms": rooms,
        # 이름만 있는 방(`rooms`)과 **안으로 들어갈 수 있는 방**(`interiors`)은
        # 다른 목록이다. 한 칸에 담으면 21 개 방이 전부 열리는 것처럼 보인다.
        "interiors": interiors,
        # AP 자리는 아무도 재지 않았다. 복도 교차점(-11.37, -44.57)에 두어 보니
        # `author_zones.py --check` 가 거절했다 — 그 자리에서 가장 먼 모서리가
        # 55.7 m 로 실내 바닥 반경 48.5 m 밖이다. **AP 한 대로는 이 층이 덮이지
        # 않는다**는 사실이고, 숨기지 않고 여기 적는다. 실측 전까지는 덮이는
        # 자리(선언된 장소들의 가운데)에 선언해 두고 `unverified_fields` 의
        # `ap_placement` 가 그것이 측량값이 아님을 말한다(AI-S-08).
        "wifi": {"ap_id": "ap-n4-5f", "rf": "indoor",
                 "at": {"x": round(width / 2, 2), "y": round(depth / 2, 2)}},
        # 이 층에 선언된 **장치**는 아직 없다(AP 는 wifi 칸이 따로 든다).
        "infrastructure": [],
        "landmarks": landmarks,
        "declared_nodes": declared,
    }

    domain = {
        "$comment": ("실제 배치. 장소와 좌표는 가시화 파트의 `places/places.json` · "
                     "`places.geometry.json`(Unity `N45F_Map.unity` 월드 좌표, 단위 m, "
                     "줄자 실측이며 측량 등급이 아니다)에서 가져왔고, 로봇은 하드웨어 "
                     "파트의 조인 선언(go1-001 · ep-001)이다. 우리가 한 것은 "
                     "site-global → 구역 로컬 **평행이동 한 번**뿐이고 그 오프셋을 "
                     "`frame_offset_from_site_global` 에 적어 둔다. 기하가 없는 장소 "
                     "20곳(방)은 자리를 지어내지 않고 뺐다 — 문은 좌표가 있고 방 자체는 "
                     "없다. AP 는 한 대만 선언돼 있고 그 한 대로는 이 층이 다 덮이지 "
                     "않는다 — 복도 교차점에 두면 먼 모서리가 바닥 반경 밖이라 지금은 "
                     "덮이는 자리에 선언해 두었고 `ap_placement` 가 미실측임을 적는다. "
                     "이 파일은 `tools/profiles/build_from_vz.py` 가 짓는다."),
        "domain_id": "hanbat-n4",
        "label": {"ko": "한밭대 N4동 산업정보관",
                  "en": "Hanbat N4 Industrial Information Hall"},
        "domain_profile": "robot_autonomy_support",
        "rect": {"x": 4, "y": 6, "w": 108, "h": 60},
        "space": {"width": width, "height": depth, "unit": "meter"},
        "frame_offset_from_site_global": {"x": round(off_x, 2),
                                          "z": round(off_z, 2),
                                          "source_frame": "site-global",
                                          "scene": "N45F_Map.unity"},
        "site": {
            "name": {"ko": "국립한밭대학교 유성 덕명캠퍼스 N4동 산업정보관",
                     "en": "Hanbat National University, N4 Industrial Information Hall"},
            "address": "대전 유성구 동서대로 125 (34158)",
            "source": "장소·좌표 = 가시화 파트 places 계약 / 건물·주소 = hanbat.ac.kr 캠퍼스 맵",
            # 이 도메인이 공개 지도에서 **어느 건물인가**. 이 이름 하나가 배경
            # 그림과 지도 위의 핀을 같은 출처로 묶는다 —
            # `tools/profiles/locate_buildings.py` 가 이것으로 자리를 받아 온다.
            "osm_building_name": "N4 산업정보관",
            "verified_fields": ["building_name", "address", "rooms", "place_topology"],
            "unverified_fields": ["ap_placement", "datum", "room_footprints"],
            # 공개 지도에서 받아 적은 **미검증** 기준점이다. 정확도는 미측정이고
            # 그래서 0 오차가 아니다 — 이 datum 으로 유도한 전역 값은 그 재료인
            # 로컬 실측보다 정확한 척할 수 없다(AI-C-02). 전역 숫자가 뷰 계약으로
            # 나가려면 검증과 경계 재합의가 함께 있어야 한다.
            "datum": DATUM,
        },
        "levels": [{"level_id": "N4-5F",
                    "label": {"ko": "산업정보관 5층", "en": "N4 5F"},
                    "verified": True, "y_offset": 0}],
        "rf": {"indoor": INDOOR_RF},
        "zones": [zone],
    }

    return {
        "$comment": ("배치 프로파일 — **실제만** 들어간다. 예시 현장은 두지 않는다. "
                     "장소는 가시화 파트, 로봇은 하드웨어 파트의 선언이 정본이고 이 "
                     "파일은 그 둘을 우리 좌표로 옮긴 결과다. 새 현장은 선언을 더하는 "
                     "것이지 코드를 고치는 일이 아니다(AI-C-15)."),
        "map": {"width": 116, "height": 72, "unit": "index"},
        "domains": [domain],
    }


def keep_looked_up(payload: dict) -> dict:
    """다시 지어도 **밖에서 받아 온 값**은 살려 둔다.

    `site_local` 은 공개 지도 조회의 결과라 이 도구가 만들어 낼 수 없다. 덮어
    버리면 프로파일을 다시 지을 때마다 지도 위의 핀이 조용히 사라지고, 그것을
    되살리려면 바깥 연결이 다시 필요해진다 — 폐쇄망에서는 되살릴 길이 없다.
    """
    if not OUT.is_file():
        return payload
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return payload
    before = {d["domain_id"]: d for d in old.get("domains", ())}
    for domain in payload["domains"]:
        kept = (before.get(domain["domain_id"]) or {}).get("site_local")
        if kept:
            domain["site_local"] = kept
    return payload


if __name__ == "__main__":
    payload = keep_looked_up(build())
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    zone = payload["domains"][0]["zones"][0]
    print(f"wrote {OUT}")
    print(f"  구역 {zone['rect']['w']} × {zone['rect']['h']} m")
    print(f"  장소 지물 {len(zone['landmarks'])}건 · 선언 로봇 {len(zone['declared_nodes'])}대")
    print(f"  방 이름 {len(zone['rooms'])}개 (좌표 없는 방은 자리를 두지 않았다)")
    print(f"  들어갈 수 있는 방 {len(zone['interiors'])}개 (기하가 있는 방만)")
