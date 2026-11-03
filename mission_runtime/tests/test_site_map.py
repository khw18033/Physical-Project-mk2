"""현장 지도 — 메인 맵이 캠퍼스 그림 위에 서고 도메인이 제 자리에 선다.

메인 맵은 오래도록 **추상 격자**였다. 배치가 가진 도메인을 네모로 늘어놓았을 뿐
이라 "어디인가" 에 답하지 못했고, 실제 지도는 도메인을 한 번 열어야 나왔다. 현장에
datum 과 배경 그림이 있으면 메인 맵 자체가 현장 지도가 되고 도메인은 그 위의
**맵 포인트**로 선다.

여기서 고정하는 것은 넷이다.

1. 평면의 **프레임과 단위가 선언으로 나간다**. 현장 평면은 미터이고 원점이
   (0,0) 이 아니다 — datum 이 가리키는 점이 (0,0) 이라 평면은 음수 쪽까지
   뻗는다. 원점을 적지 않으면 받는 쪽이 0 에서 그려 지도 한쪽을 잘라 낸다.
2. 평면이 **그림에서 유도된다**. 따로 선언하면 그림을 갈아 끼운 날 핀만
   제자리에 남는다.
3. 현장 그림과 도메인 그림은 **다른 프레임**이다. 현장 그림의 앵커는 현장 로컬
   좌표이고, 도메인 로컬 프레임에 깔면 건물이 제자리에서 벗어난다(AI-C-02).
4. 자리를 모르는 도메인은 **칸 자체가 없다**. 0 으로 채우면 지도 왼쪽 위 구석에
   건물이 하나 생긴다(AI-S-08).

그리고 배경이 없는 현장이 **정상 배치**라는 것 — 그때 메인 맵은 지금까지와 같은
격자이고 아무것도 깨지지 않는다(AI-C-05).

implements: AI-C-02, AI-C-05, AI-C-08, AI-S-08
tests: site scope, derived plane, frame separation, missing position, no-datum site
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "fms_console"))

from fleet import plane_of, static_image_for  # noqa: E402

PROFILE = Path(__file__).resolve().parents[1] / "profiles" / "domains.json"
TILES = Path(__file__).resolve().parents[1] / "config" / "map_tiles.example.json"


def _layer(layer_id: str, scope: dict) -> dict:
    """앵커 두 점이 1 m = 2 px 인 그림 하나."""
    return {
        "layer_id": layer_id,
        "kind": "static_image",
        "label": {"ko": layer_id, "en": layer_id},
        "enabled": True,
        "requires_external_connection": False,
        "external_hosts": [],
        "scope": scope,
        "image": {"ref": "maps/none.png", "width_px": 400, "height_px": 400},
        "anchors": [
            {"local": {"x": 0, "y": 0}, "pixel": {"x": 100, "y": 100}},
            {"local": {"x": 100, "y": 100}, "pixel": {"x": 300, "y": 300}},
        ],
        "source": {"name": "시험용", "license": "none"},
    }


def test_a_layer_with_no_scope_answers_the_site_and_not_a_domain():
    """scope 가 비어 있으면 **현장** 그림이다.

    도메인을 물었을 때 이것이 나오면 현장 좌표의 그림이 도메인 프레임에 깔린다.
    """
    declaration = {"layers": [_layer("site", {})]}

    site = static_image_for(declaration, domain_id=None)
    assert site is not None and site["layer_id"] == "site"

    assert static_image_for(declaration, domain_id="d1") is None


def test_a_domain_layer_does_not_answer_the_site():
    """반대 방향도 같다 — 도메인 그림이 현장 지도로 올라오면 안 된다."""
    declaration = {"layers": [_layer("floor", {"domain_id": "d1"})]}

    assert static_image_for(declaration, domain_id="d1") is not None
    assert static_image_for(declaration, domain_id=None) is None


def test_the_narrower_scope_wins():
    """구역 → 층 → 도메인 순으로 좁은 자리가 이긴다.

    방 하나를 보려던 사람에게 층 도면을 깔면 그 화면은 틀린 것을 보여 준다.
    """
    declaration = {"layers": [
        _layer("domain", {"domain_id": "d1"}),
        _layer("level", {"domain_id": "d1", "level_id": "L1"}),
        _layer("zone", {"domain_id": "d1", "level_id": "L1", "zone_id": "z1"}),
    ]}

    picked = static_image_for(declaration, domain_id="d1", level_id="L1",
                              zone_id="z1")
    assert picked["layer_id"] == "zone"
    assert static_image_for(declaration, domain_id="d1",
                            level_id="L1")["layer_id"] == "level"
    assert static_image_for(declaration, domain_id="d1")["layer_id"] == "domain"


def test_the_plane_is_derived_from_the_image_so_pin_and_picture_cannot_drift():
    """`px = local * scale + offset` 의 역이 평면이다.

    평면을 따로 선언해 두면 그림을 갈아 끼운 날 둘이 어긋나고, 어긋난 줄 아무도
    모른다 — 핀은 여전히 "건물 위" 에 보이기 때문이다.
    """
    image = static_image_for({"layers": [_layer("site", {})]}, domain_id=None)
    plane = plane_of(image)

    # 앵커가 1 m = 2 px 이고 로컬 (0,0) 이 px (100,100) 이므로 그림의 왼쪽 위는
    # 로컬 (-50, -50) 이고 폭은 400 px / 2 = 200 m 다.
    assert plane["origin"] == {"x": -50.0, "y": -50.0}
    assert plane["width"] == 200.0 and plane["height"] == 200.0


def test_the_shipped_campus_layer_is_declared_for_the_site():
    """실제로 싣고 다니는 선언을 고정한다.

    이 그림의 앵커는 datum 을 원점으로 삼는 현장 로컬 좌표다(`fetch_site_map.py`).
    도메인 scope 로 되돌아가면 건물이 제자리에서 벗어난다.
    """
    layers = {row["layer_id"]: row
              for row in json.loads(TILES.read_text(encoding="utf-8"))["layers"]}

    assert layers["site-osm"]["scope"] == {}, "캠퍼스 그림은 현장 그림이다"
    assert layers["n4-5f-plan"]["scope"]["level_id"] == "N4-5F", "층 도면은 층에 건다"


def test_the_declared_building_position_says_it_is_not_a_survey():
    """자리는 공개 지도에서 받아 적은 **선언**이다.

    측량값처럼 보이면 그것으로 거리를 재는 사람이 생긴다. 그래서 `verified` 가
    거짓이고 출처가 값과 함께 다닌다(AI-S-08).
    """
    domain = json.loads(PROFILE.read_text(encoding="utf-8"))["domains"][0]
    declared = domain.get("site_local")
    if declared is None:
        pytest.skip("이 현장은 아직 자리를 받아 오지 않았다 — 정상 상태다")

    assert declared["verified"] is False
    assert declared["basis"] == "public_map_declaration"
    assert declared["source"]["license"] == "ODbL 1.0"
    assert "x" in declared["at"] and "y" in declared["at"]


def test_a_site_without_a_background_keeps_the_plain_grid():
    """배경 없는 현장이 **기본값**이다.

    그림을 못 찾으면 평면은 프로파일의 격자 그대로이고 메인 맵은 지금까지처럼
    그려진다 — 선택 계층의 결손이 화면을 깨지 않는다(AI-C-05).
    """
    assert static_image_for({"layers": []}, domain_id=None) is None
    assert static_image_for(None, domain_id=None) is None
