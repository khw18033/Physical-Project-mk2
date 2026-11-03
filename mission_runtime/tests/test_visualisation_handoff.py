"""＋ 로 들인 장치가 **가시화 계약으로도** 나간다.

그쪽 계약이 직접 적는다 — "여기 없는 것은 assigned_targets 에 쓸 수 없다."
우리 화면에만 서는 장치는 임무를 받을 수 없으므로, 들이는 일이 거기서 끝나면
확장이 아니다.

implements: AI-C-01, AI-C-04, AI-C-15, AI-B-09
tests: the emitted entry validates against the visualisation's own schema
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "fms_console"))

from visualisation import ROLE_TO_KIND, equipment_entry  # noqa: E402

#: 가시화 브랜치에서 그대로 받아 온 계약. 우리가 베껴 쓴 것이 아니라 **그쪽 파일**이다.
SCHEMA = ROOT.parent / "local" / "vz" / "equipment.schema.json"


@pytest.fixture
def validator():
    jsonschema = pytest.importorskip("jsonschema")
    if not SCHEMA.is_file():
        pytest.skip(f"가시화 계약 사본이 없다: {SCHEMA}")
    return jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))


def test_a_joined_device_validates_against_the_visualisation_contract(validator):
    """그쪽 스키마가 받아들이지 않으면 연동이 아니다."""
    entry = equipment_entry(
        {"device_id": "go1-002", "role": "ugv"}, zone_id="zone-503")

    validator.validate(entry)
    assert entry["equipment_id"] == "go1-002"
    assert entry["kind"] == "robot"
    assert entry["zone_id"] == "zone-503"


def test_an_unknown_name_stays_null_rather_than_becoming_the_id(validator):
    """`label` 주석이 적은 규칙 그대로 — 모르면 null 이고 지어내지 않는다.

    장치 id 를 이름 자리에 복사하면 그쪽 화면이 그것을 사람이 지은 이름으로 읽고,
    나중에 진짜 이름이 생겨도 이미 이름이 있는 줄 알고 덮지 않는다.
    """
    entry = equipment_entry({"device_id": "go1-002", "role": "ugv"})

    validator.validate(entry)
    assert entry["label"] is None


def test_a_role_the_table_does_not_know_still_goes_out(validator):
    """표에 없다고 빠뜨리면 새 역할의 로봇은 그쪽 목록에 영영 못 들어간다.

    들어가지 못하면 임무를 걸 수 없다 — 표가 곧 확장의 문턱이 되는 모양이고,
    그것이 절대 준수 #3·#7 이 금지하는 것이다.
    """
    assert "rail_crawler" not in ROLE_TO_KIND
    entry = equipment_entry({"device_id": "rc-001", "role": "rail_crawler"})

    validator.validate(entry)
    assert entry["kind"] == "rail_crawler"


def test_nothing_we_know_is_smuggled_into_their_contract(validator):
    """`additionalProperties: false` 다 — 우리가 아는 것을 더 실어 보낼 수 없다.

    예산도 공지 어휘도 그쪽 칸에 자리가 없다. 두 계약을 섞지 않는 것이 요점이다.
    """
    entry = equipment_entry({
        "device_id": "go1-002", "role": "ugv",
        "budget": {"compute_units": 6.0},
        "declared_actions": ["move_forward"],
        "node_tags": ["tier.ugv"]})

    validator.validate(entry)
    assert "budget" not in entry and "declared_actions" not in entry


def test_a_device_without_an_id_is_refused():
    """식별자 없는 장비는 그쪽 이름 공간에 들어갈 수 없다."""
    with pytest.raises(ValueError):
        equipment_entry({"role": "ugv"})
