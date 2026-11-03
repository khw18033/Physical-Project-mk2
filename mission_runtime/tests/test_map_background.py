"""바탕 그림 — 선언 · 앵커 · 없을 때.

implements: AI-C-02, AI-C-08, AI-C-16, AI-C-05
tests: anchor rejection, pixel transform, level beats domain, absent asset,
       state contract stays pixel-free
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "fms_console"))

from fleet import (  # noqa: E402
    TILE_KIND_STATIC_IMAGE,
    MapTileError,
    load_map_tiles,
    static_image_for,
)

SHIPPED = Path(__file__).resolve().parents[1] / "config" / "map_tiles.example.json"


def _image_layer(**over):
    layer = {
        "layer_id": "test-image",
        "kind": TILE_KIND_STATIC_IMAGE,
        "requires_external_connection": False,
        "enabled": True,
        "scope": {"domain_id": "college"},
        "image": {"ref": "maps/x.png", "width_px": 100, "height_px": 50},
        "anchors": [
            {"pixel": {"x": 10, "y": 10}, "local": {"x": 0.0, "y": 0.0}},
            {"pixel": {"x": 90, "y": 40}, "local": {"x": 8.0, "y": 3.0}},
        ],
        "source": {"name": "test", "license": "unknown"},
    }
    layer.update(over)
    return layer


def _declaration(*layers):
    return {"closed_network": True, "layers": list(layers)}


def _write(tmp_path, payload):
    path = tmp_path / "tiles.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_shipped_declaration_loads(tmp_path):
    """출하 선언이 그대로 읽힌다 — 예시 그림 두 장이 거기 있다."""
    loaded = load_map_tiles(SHIPPED)
    images = [row for row in loaded["layers"]
              if row["kind"] == TILE_KIND_STATIC_IMAGE]

    assert images, "출하 선언에 바탕 그림 예시가 있어야 한다"
    for row in images:
        assert row["source"]["license"], "라이선스는 모르면 모른다고 적는다"


@pytest.mark.parametrize("broken, why", [
    ({"image": {"ref": "maps/x.png"}}, "width_px"),
    ({"source": {"name": "test"}}, "license"),
    ({"anchors": [{"pixel": {"x": 1, "y": 1}, "local": {"x": 0, "y": 0}}]}, "two anchors"),
])
def test_a_half_written_image_layer_is_refused(tmp_path, broken, why):
    """배치 전에 파일만 보고 알 수 있는 잘못은 배치 전에 거절한다(AI-C-16)."""
    path = _write(tmp_path, _declaration(_image_layer(**broken)))

    with pytest.raises(MapTileError) as caught:
        load_map_tiles(path)
    assert why.split()[0] in str(caught.value)


def test_two_anchors_on_one_line_have_no_scale(tmp_path):
    """같은 x 를 가진 두 점에서는 그 축의 배율이 0 으로 나누기가 된다.

    현장에서 터질 이유가 없는 잘못이라 선언을 읽을 때 끊는다.
    """
    flat = _image_layer(anchors=[
        {"pixel": {"x": 10, "y": 10}, "local": {"x": 0.0, "y": 0.0}},
        {"pixel": {"x": 10, "y": 40}, "local": {"x": 8.0, "y": 3.0}},
    ])

    with pytest.raises(MapTileError, match="share x in pixels"):
        load_map_tiles(_write(tmp_path, _declaration(flat)))


def test_the_transform_takes_a_local_point_to_its_pixel(tmp_path):
    """앵커 두 점에서 역산한 계수가 그 두 점을 **그대로** 되돌려야 한다.

    뷰어가 앵커에서 같은 계산을 다시 하게 하면 두 화면이 반올림 한 자리에서
    갈린다. 계수는 한 곳에서 내고 뷰어는 곱하기만 한다.
    """
    loaded = load_map_tiles(_write(tmp_path, _declaration(_image_layer())))
    block = static_image_for(loaded, domain_id="college")

    for anchor in ({"local": (0.0, 0.0), "pixel": (10, 10)},
                   {"local": (8.0, 3.0), "pixel": (90, 40)}):
        local_x, local_y = anchor["local"]
        assert local_x * block["scale"]["x"] + block["offset"]["x"] == pytest.approx(
            anchor["pixel"][0])
        assert local_y * block["scale"]["y"] + block["offset"]["y"] == pytest.approx(
            anchor["pixel"][1])


def test_a_level_drawing_wins_over_the_site_photo(tmp_path):
    """층 도면이 있으면 조감도보다 먼저다 — 조감도를 깔면 로봇이 지붕 위에 선다."""
    site = _image_layer(layer_id="site", scope={"domain_id": "college"})
    floor = _image_layer(layer_id="floor",
                         scope={"domain_id": "college", "level_id": "n4-1f"})
    loaded = load_map_tiles(_write(tmp_path, _declaration(site, floor)))

    assert static_image_for(loaded, domain_id="college",
                            level_id="n4-1f")["layer_id"] == "floor"
    # 그 층의 도면이 없으면 조감도로 내려간다 — 빈 화면을 주지 않는다.
    assert static_image_for(loaded, domain_id="college",
                            level_id="n4-9f")["layer_id"] == "site"
    assert static_image_for(loaded, domain_id="river") is None


def test_a_missing_image_file_is_a_reason_not_a_crash(tmp_path):
    """그림이 아직 없는 노드는 정상이다. 그때 지도는 로컬 좌표 도면으로 그려진다."""
    loaded = load_map_tiles(_write(tmp_path, _declaration(_image_layer())))
    block = static_image_for(loaded, domain_id="college")

    assert block["available"] is False
    assert block["unavailable_reason"] == "image_missing"
    # 쓸 수 없어도 **어디를 봐야 하는지**는 말한다 — 어느 파일이 없는지 알아야
    # 가져다 놓을 수 있다.
    assert block["media"]["file"] == "test-image"


def test_an_image_layer_needs_no_outbound_connection(tmp_path):
    """폐쇄망에서도 그대로 돈다 — 파일 하나이고 타일 서버가 아니다(AI-C-16)."""
    loaded = load_map_tiles(_write(tmp_path, _declaration(_image_layer())))
    row = loaded["layers"][0]

    assert row["requires_external_connection"] is False
    assert row.get("external_hosts", []) == []
