"""implements: AI-C-15, AI-S-08, AI-C-02
tests: 배포된 프로파일이 검사를 통과한다 · RF 반경이 모델에서 다시 계산한 값과 같다
       (손으로 적은 숫자의 드리프트 차단) · 구역 id 중복·도메인 공간 이탈·없는 층을
       각각 **그 사유로** 거절한다 · 통과한 조각이 기존 프로파일 로더로도 읽힌다

새 현장을 올리는 잘못은 대부분 파일만 봐도 알 수 있는 것들이다. 그걸 현장에서
발견하지 않도록 여기서 고정한다.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = PROJECT_ROOT / "tools" / "profiles"
CONSOLE_DIR = PROJECT_ROOT / "tools" / "fms_console"
for _dir in (TOOL_DIR, CONSOLE_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import author_zones as az  # noqa: E402

SHIPPED = PROJECT_ROOT / "profiles" / "domains.example.json"


@pytest.fixture(scope="module")
def shipped() -> dict:
    return json.loads(SHIPPED.read_text(encoding="utf-8"))


def codes(findings, severity=None) -> list[str]:
    return [f.code for f in findings if severity is None or f.severity == severity]


def find(findings, code: str):
    rows = [f for f in findings if f.code == code]
    assert rows, f"expected a {code!r} finding, got {codes(findings)}"
    return rows[0]


def declaration() -> dict:
    """새 현장 하나의 작은 선언. **반경은 적지 않는다** — 모델이 낸다."""
    return {
        "domain": {
            "domain_id": "harbor",
            "label": {"ko": "항만 — 예시", "en": "Harbor - example"},
            "domain_profile": "facility_surveillance",
            "site": {
                "name": {"ko": "항만 예시", "en": "Harbor example"},
                "address": None,
                "source": "예시 선언",
                "verified_fields": ["address"],
                "unverified_fields": ["quay_length_m", "ap_placement"],
            },
            "rect": {"x": 4, "y": 6, "w": 40, "h": 24},
            "space": {"width": 300, "height": 200, "unit": "meter"},
            "levels": [{"level_id": "harbor-ground",
                        "label": {"ko": "지상", "en": "Ground"},
                        "verified": False, "y_offset": 0}],
            "rf": {"outdoor": {"model": "log_distance", "band": "5GHz",
                               "tx_eirp_dbm": 23.0, "reference_loss_db_at_1m": 46.0,
                               "path_loss_exponent": 2.2,
                               "thresholds_dbm": {"excellent": -45.0, "handover": -75.0,
                                                  "floor": -85.0}}},
        },
        "zones": [{
            "zone_id": "harbor-quay",
            "label": {"ko": "안벽", "en": "Quay"},
            "level_id": "harbor-ground",
            "verified": False,
            "rect": {"x": 10, "y": 20, "w": 180, "h": 90},
            "rooms": [],
            "wifi": {"ap_id": "ap-harbor", "at": {"x": 100, "y": 65}, "rf": "outdoor"},
            "edge_node": "edge-harbor",
            "infrastructure": [{"id": "edge-harbor", "kind": "edge_node",
                                "at": {"x": 150, "y": 30}}],
            "declared_nodes": [],
        }],
    }


# --- RF 모델이 반경의 유일한 출처다 -----------------------------------------

def test_the_recomputed_radii_equal_the_ones_in_the_shipped_profile(shipped):
    # 반경을 손으로 적으면 모델 파라미터와 조용히 어긋난다. 배포된 값이 모델에서
    # 그대로 나오는지가 "왜 구역을 이 크기로 잡았나" 의 근거를 지킨다.
    checked = 0
    for domain in shipped["domains"]:
        for band_name, band in (domain.get("rf") or {}).items():
            derived = az.derive_radii(band)
            assert derived == {k: pytest.approx(v) for k, v in band["radius_m"].items()}, \
                f"{domain['domain_id']}/{band_name} radii drifted from the model"
            checked += 1
    assert checked >= 2          # 실내·옥외 모델 둘 다 확인했다


def test_the_log_distance_inversion_is_the_documented_one():
    # 실내 n=3.5, EIRP 20dBm, 1m 기준손실 46dB 에서 -75dBm 까지는 25.1 m.
    assert az.radius_for_threshold(
        tx_eirp_dbm=20.0, reference_loss_db_at_1m=46.0,
        path_loss_exponent=3.5, threshold_dbm=-75.0) == pytest.approx(25.1)
    # 같은 임계가 옥외 n=2.2, 23dBm 에서는 231.0 m — 한 AP 가 수백 m 를 덮는다.
    assert az.radius_for_threshold(
        tx_eirp_dbm=23.0, reference_loss_db_at_1m=46.0,
        path_loss_exponent=2.2, threshold_dbm=-75.0) == pytest.approx(231.0)


def test_authoring_fills_the_radii_so_nobody_hand_writes_them():
    domain = az.build_domain(declaration())

    assert domain["rf"]["outdoor"]["radius_m"] == {
        "excellent": pytest.approx(10.0), "handover": pytest.approx(231.0),
        "floor": pytest.approx(657.9)}
    assert domain["zones"][0]["zone_id"] == "harbor-quay"


def test_a_hand_written_radius_that_disagrees_with_the_model_is_refused():
    body = declaration()
    body["domain"]["rf"]["outdoor"]["radius_m"] = {"excellent": 10.0, "handover": 400.0,
                                                   "floor": 657.9}

    with pytest.raises(az.DeclarationError, match="radius_m"):
        az.build_domain(body)

    _, findings = az.validate_declaration(body)
    assert codes(findings) == ["declaration_unreadable"]


def test_the_shipped_profile_records_no_drifting_radius(shipped):
    assert "rf_radius_drift" not in codes(az.validate_profile(shipped))


# --- 선언 검증 --------------------------------------------------------------

def test_a_clean_declaration_passes_and_yields_a_pasteable_fragment(shipped, tmp_path):
    domain, findings = az.validate_declaration(declaration(), against=shipped)

    assert codes(findings, az.ERROR) == []
    assert domain is not None
    # 기존 로더가 읽을 수 있어야 한다 — 두 검사가 다른 답을 내면 배포에서 드러난다.
    from fleet import load_domain_profile

    spliced = dict(shipped)
    spliced["domains"] = list(shipped["domains"]) + [domain]
    target = tmp_path / "spliced.json"
    target.write_text(json.dumps(spliced), encoding="utf-8")
    loaded = load_domain_profile(target)
    assert [d["domain_id"] for d in loaded["domains"]][-1] == "harbor"


def test_a_duplicate_zone_id_is_refused_and_names_the_domain_that_has_it(shipped):
    body = declaration()
    body["zones"][0]["zone_id"] = "rec-meander"          # 하천 도메인이 이미 쓰는 id

    domain, findings = az.validate_declaration(body, against=shipped)

    assert domain is None
    finding = find(findings, "duplicate_zone_id")
    assert "'river'" in finding.message and "unique across domains" in finding.message
    assert "rec-meander" in finding.where


def test_a_zone_outside_its_domain_space_is_refused_with_the_offending_edge():
    body = declaration()
    body["zones"][0]["rect"] = {"x": 10, "y": 20, "w": 400, "h": 90}   # 공간 폭 300

    domain, findings = az.validate_declaration(body)

    assert domain is None
    finding = find(findings, "zone_outside_domain_space")
    assert "300x200 m" in finding.message and "right edge 410" in finding.message


def test_a_zone_on_an_undeclared_level_is_refused_and_lists_what_is_declared():
    body = declaration()
    body["zones"][0]["level_id"] = "harbor-2F"

    domain, findings = az.validate_declaration(body)

    assert domain is None
    finding = find(findings, "undeclared_level")
    assert "'harbor-2F'" in finding.message
    assert "['harbor-ground']" in finding.message


def test_a_zone_corner_with_no_link_at_all_is_refused():
    body = declaration()
    # 실내 모델로 바꾸면 한 AP 의 바닥 반경이 48.5 m 이고, 180x90 구역의 먼 구석은 그 밖이다.
    body["domain"]["rf"] = {"indoor": {
        "model": "log_distance", "band": "5GHz", "tx_eirp_dbm": 20.0,
        "reference_loss_db_at_1m": 46.0, "path_loss_exponent": 3.5,
        "thresholds_dbm": {"excellent": -45.0, "handover": -75.0, "floor": -85.0}}}
    body["zones"][0]["wifi"]["rf"] = "indoor"

    domain, findings = az.validate_declaration(body)

    assert domain is None
    finding = find(findings, "zone_beyond_rf_floor")
    assert "48.5 m" in finding.message and "no link at all" in finding.message


def test_an_ap_placed_outside_the_site_is_refused():
    body = declaration()
    body["zones"][0]["wifi"]["at"] = {"x": 900, "y": 65}

    domain, findings = az.validate_declaration(body)

    assert domain is None
    assert "ap_outside_domain_space" in codes(findings)


def test_an_edge_node_that_is_declared_nowhere_is_refused():
    body = declaration()
    body["zones"][0]["edge_node"] = "edge-that-does-not-exist"

    domain, findings = az.validate_declaration(body)

    assert domain is None
    assert "edge_node" in find(findings, "unknown_edge_node").message


def test_a_declared_node_outside_its_own_zone_is_refused():
    body = declaration()
    body["zones"][0]["declared_nodes"] = [{"node_id": "quay-crawler",
                                           "at": {"x": 250, "y": 150}}]

    domain, findings = az.validate_declaration(body)

    assert domain is None
    assert "outside its own zone rect" in find(findings, "declared_node_outside_zone").message


def test_a_second_domain_with_the_same_id_is_refused(shipped):
    body = declaration()
    body["domain"]["domain_id"] = "river"
    body["zones"][0]["zone_id"] = "harbor-quay"

    domain, findings = az.validate_declaration(body, against=shipped)

    assert domain is None
    assert "duplicate_domain_id" in codes(findings)


# --- 실측 여부 표시의 정직성 (새 상태 어휘를 만들지 않는다) -------------------

def test_claiming_verified_on_an_unverified_level_is_refused():
    body = declaration()
    body["zones"][0]["verified"] = True            # 층은 verified: false 로 남아 있다

    domain, findings = az.validate_declaration(body)

    assert domain is None
    assert "does not" in find(findings, "verified_zone_on_unverified_level").message


def test_a_site_field_cannot_be_both_verified_and_unverified():
    body = declaration()
    body["domain"]["site"]["verified_fields"] = ["ap_placement"]

    domain, findings = az.validate_declaration(body)

    assert domain is None
    assert "ap_placement" in find(findings, "verified_fields_overlap").message


def test_an_example_site_cannot_claim_verified_zones():
    body = declaration()
    body["domain"]["site"]["example"] = True
    body["domain"]["levels"][0]["verified"] = True
    body["zones"][0]["verified"] = True

    domain, findings = az.validate_declaration(body)

    assert domain is None
    assert "verified_zone_in_example_domain" in codes(findings)


# --- CLI --------------------------------------------------------------------

def test_check_passes_on_the_shipped_profile():
    out = io.StringIO()

    assert az.main(["--check"], stream=out) == 0
    report = out.getvalue()
    assert "0 error(s)" in report
    assert "ERROR" not in report


def test_check_still_lists_what_is_not_verified_on_the_shipped_profile():
    # 통과는 "전부 확인됐다" 가 아니다. 무엇이 미확인인지가 같은 목록에 남아야 한다.
    out = io.StringIO()
    az.main(["--check"], stream=out)
    report = out.getvalue()

    assert "undeclared_rf_band" in report              # facility 의 indoor 밴드 미선언
    assert "zone_beyond_handover_radius" in report     # 한 AP 보다 넓은 옥외 구역
    assert "verified_zone_camera_uncalibrated" in report


def test_strict_mode_turns_the_unverified_list_into_a_failure():
    out = io.StringIO()
    assert az.main(["--check", "--strict"], stream=out) == 1


def test_declare_writes_the_fragment_only_when_it_passes(tmp_path):
    good = tmp_path / "harbor.json"
    good.write_text(json.dumps(declaration()), encoding="utf-8")
    fragment = tmp_path / "fragment.json"
    out = io.StringIO()

    assert az.main(["--declare", str(good), "--out", str(fragment)], stream=out) == 0
    written = json.loads(fragment.read_text(encoding="utf-8"))
    assert written["rf"]["outdoor"]["radius_m"]["handover"] == pytest.approx(231.0)

    bad = tmp_path / "broken.json"
    body = declaration()
    body["zones"][0]["zone_id"] = "rec-meander"
    bad.write_text(json.dumps(body), encoding="utf-8")
    missing = tmp_path / "never.json"
    out = io.StringIO()

    assert az.main(["--declare", str(bad), "--out", str(missing)], stream=out) == 1
    assert not missing.exists()
    assert "duplicate_zone_id" in out.getvalue()


def test_findings_print_severity_code_and_place():
    finding = az.Finding(az.ERROR, "undeclared_level", "zone 'x'", "no such level")

    rendered = str(finding)
    assert rendered.startswith("ERROR")
    assert "undeclared_level" in rendered and "zone 'x'" in rendered
