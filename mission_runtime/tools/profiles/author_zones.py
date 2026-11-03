"""새 도메인·구역을 **선언으로** 추가한다. 손으로 고치지 않는다.

implements: AI-C-15 (도메인·배포 프로파일 분리), AI-S-08 (사전정보의 출처·유효범위),
            AI-C-02 (좌표계 경계)
관련: AI-C-10, AI-C-18, AI-B-04
tests: tests/test_zone_authoring.py

## 왜 도구가 필요한가

지금 새 현장을 올리는 길은 `profiles/domains.example.json` 을 손으로 고치는 것이다.
그 파일에는 **모델에서 역산한 숫자**(RF 반경)와 **손으로 적은 숫자**(구역 사각형,
AP 자리)가 섞여 있다. 손으로 고치면 두 가지가 조용히 어긋난다.

* `rf.radius_m` 를 손으로 적으면 log-distance 모델 파라미터와 **따로 움직인다**.
  그러면 "구역 크기를 왜 이렇게 잡았나" 의 근거가 사라진다. 그래서 이 도구는 반경을
  항상 모델에서 다시 계산하고, 손으로 적힌 값이 모델과 다르면 **거절한다**.
* 구역이 도메인 공간 밖으로 나가거나, 없는 층을 가리키거나, 구역 id 가 다른 도메인과
  겹치는 것은 전부 현장에 가서야 드러난다. 그 세 가지는 파일만 읽어도 알 수 있다.

그래서 이 도구가 하는 일은 두 개다 — **모델에서 파생되는 값을 계산**하고, **파일만
보고 알 수 있는 잘못을 지금 말한다**. 무엇이 아직 실측되지 않았는지도 같은 목록에
낸다. 상태 어휘를 새로 만들지 않고 기존 `verified` · `site.unverified_fields` 를
그대로 읽는다.

## 쓰는 법

    # 배포된 프로파일 자체를 검사한다
    python tools/profiles/author_zones.py --check

    # 새 현장 선언을 검증하고 붙여 넣을 조각을 낸다
    python tools/profiles/author_zones.py --declare new_site.json --out fragment.json

`--strict` 는 경고도 실패로 센다. 경고는 "틀렸다" 가 아니라 "확인되지 않았다" 이고,
배포된 프로파일에도 그런 자리가 남아 있다(옥외 구역이 한 AP 의 핸드오버 반경보다 넓은
것 등) — 그래서 기본 검사에서 경고는 통과시키고 목록에만 남긴다.

## 도메인 이름으로 갈라지지 않는다

여기에는 `college` · `river` 같은 이름 분기가 없다(절대 준수 원칙 #3). 검사는 전부
선언된 데이터(공간 크기, 층 목록, RF 밴드, `verified` 표시)만 읽는다. 새 도메인이
늘어나면 이 파일은 그대로다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = PROJECT_ROOT / "profiles" / "domains.example.json"

ERROR = "error"
WARNING = "warning"

#: RF 반경을 반올림하는 자리. 배포된 프로파일이 소수 1자리로 적혀 있고, 그 값과
#: 그대로 맞아야 "손으로 적은 값이 모델과 어긋나지 않았다" 를 시험으로 고정할 수 있다.
RADIUS_DECIMALS = 1

#: log-distance 모델이 반드시 들고 있어야 하는 파라미터.
_RF_PARAMS = ("tx_eirp_dbm", "reference_loss_db_at_1m", "path_loss_exponent")

#: 구역을 지금 쓸 수 있다고 보기 위한 최소 수신 임계의 이름. `floor` 아래는 링크가
#: 아예 없는 자리이고 `handover` 아래는 전환 띠다 — 그래서 둘의 심각도가 다르다.
THRESHOLD_FLOOR = "floor"
THRESHOLD_HANDOVER = "handover"


@dataclass(frozen=True)
class Finding:
    """무엇이 잘못됐거나 확인되지 않았는지 한 줄.

    `where` 는 사람이 파일에서 찾아갈 수 있는 자리(도메인/구역 id)이고 `code` 는
    시험이 붙잡는 이름이다 — 메시지 문장만으로 시험을 쓰면 문장을 다듬을 때마다
    시험이 깨진다.
    """

    severity: str
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper():7s} {self.code:36s} {self.where}: {self.message}"


class DeclarationError(ValueError):
    """선언 자체를 읽을 수 없다 — 검증 이전의 문제다."""


# --- RF 모델 ----------------------------------------------------------------

def radius_for_threshold(
    *, tx_eirp_dbm: float, reference_loss_db_at_1m: float,
    path_loss_exponent: float, threshold_dbm: float,
) -> float:
    """log-distance 경로손실을 거리로 역산한다.

        RSSI(d) = tx_eirp - (L1 + 10·n·log10 d)

    를 `RSSI(d) = threshold` 에서 d 에 대해 푼 것이다. 이 한 식이 구역 한 칸의 크기를
    정하는 근거이고, 그래서 반경을 손으로 적지 않는다.
    """
    if path_loss_exponent <= 0:
        raise DeclarationError(f"path_loss_exponent must be > 0, got {path_loss_exponent}")
    budget_db = tx_eirp_dbm - reference_loss_db_at_1m - threshold_dbm
    return round(10.0 ** (budget_db / (10.0 * path_loss_exponent)), RADIUS_DECIMALS)


def derive_radii(band: Mapping[str, Any]) -> dict[str, float]:
    """한 RF 밴드 선언의 임계값들을 전부 반경으로 환산한다."""
    for key in _RF_PARAMS:
        if key not in band:
            raise DeclarationError(f"rf band missing {key!r}")
    thresholds = band.get("thresholds_dbm") or {}
    if not thresholds:
        raise DeclarationError("rf band missing 'thresholds_dbm'")
    return {
        name: radius_for_threshold(
            tx_eirp_dbm=float(band["tx_eirp_dbm"]),
            reference_loss_db_at_1m=float(band["reference_loss_db_at_1m"]),
            path_loss_exponent=float(band["path_loss_exponent"]),
            threshold_dbm=float(value),
        )
        for name, value in thresholds.items()
    }


# --- 작은 기하 -------------------------------------------------------------

def _rect(raw: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return (float(raw["x"]), float(raw["y"]), float(raw["w"]), float(raw["h"]))


def _inside(point: tuple[float, float], rect: tuple[float, float, float, float]) -> bool:
    x, y, w, h = rect
    # 경계는 포함으로 본다 — 인접한 두 구역이 변을 공유하는 것이 정상 배치다.
    return x <= point[0] <= x + w and y <= point[1] <= y + h


def _corners(rect: tuple[float, float, float, float]) -> tuple[tuple[float, float], ...]:
    x, y, w, h = rect
    return ((x, y), (x + w, y), (x, y + h), (x + w, y + h))


def _overlap_area(a: tuple[float, float, float, float],
                  b: tuple[float, float, float, float]) -> float:
    ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0.0, ox) * max(0.0, oy)


def _farthest_corner(point: tuple[float, float],
                     rect: tuple[float, float, float, float]) -> tuple[tuple[float, float], float]:
    best, far = None, -1.0
    for corner in _corners(rect):
        d = math.dist(point, corner)
        if d > far:
            best, far = corner, d
    return best, far            # type: ignore[return-value]


# --- 검증 -------------------------------------------------------------------

def _require(body: Mapping[str, Any], keys: Sequence[str], where: str,
             out: list[Finding]) -> bool:
    missing = [k for k in keys if k not in body]
    for key in missing:
        out.append(Finding(ERROR, "missing_field", where, f"missing required field {key!r}"))
    return not missing


def validate_rf(domain: Mapping[str, Any], out: list[Finding]) -> None:
    """선언된 RF 밴드가 모델과 맞는지 본다.

    반경이 적혀 있으면 모델에서 다시 계산한 값과 비교한다. 다르면 **거절한다** —
    손으로 적은 반경이 모델보다 넓으면 구역이 덮인다고 착각하고 배치한다.
    """
    domain_id = domain.get("domain_id", "?")
    for band_name, band in (domain.get("rf") or {}).items():
        where = f"domain {domain_id!r} rf.{band_name}"
        try:
            derived = derive_radii(band)
        except DeclarationError as exc:
            out.append(Finding(ERROR, "rf_model_incomplete", where, str(exc)))
            continue
        stated = band.get("radius_m")
        if stated is None:
            out.append(Finding(WARNING, "rf_radius_not_recorded", where,
                               "no radius_m recorded; authoring fills it from the model"))
            continue
        for name, value in sorted(derived.items()):
            if name not in stated:
                out.append(Finding(ERROR, "rf_radius_missing", where,
                                   f"radius_m has no {name!r} although thresholds_dbm does"))
            elif abs(float(stated[name]) - value) > 10 ** -RADIUS_DECIMALS / 2:
                out.append(Finding(
                    ERROR, "rf_radius_drift", where,
                    f"radius_m.{name} is {stated[name]} but the declared log-distance "
                    f"model gives {value} — a hand-edited radius has drifted"))
        for name in sorted(set(stated) - set(derived)):
            out.append(Finding(ERROR, "rf_radius_unbacked", where,
                               f"radius_m.{name} has no matching threshold in thresholds_dbm"))


def validate_site_honesty(domain: Mapping[str, Any], out: list[Finding]) -> None:
    """실측 여부 표시가 서로 모순되지 않는지 본다(새 상태 어휘를 만들지 않는다)."""
    domain_id = domain.get("domain_id", "?")
    site = domain.get("site") or {}
    verified = set(site.get("verified_fields") or ())
    unverified = set(site.get("unverified_fields") or ())
    for name in sorted(verified & unverified):
        out.append(Finding(ERROR, "verified_fields_overlap", f"domain {domain_id!r}",
                           f"site field {name!r} is listed as both verified and unverified"))
    example = bool(site.get("example"))
    levels = {level.get("level_id"): level for level in domain.get("levels") or ()}
    for zone in domain.get("zones") or ():
        zone_id = zone.get("zone_id", "?")
        if not zone.get("verified", False):
            continue
        if example:
            out.append(Finding(ERROR, "verified_zone_in_example_domain", f"zone {zone_id!r}",
                               "zone claims verified while its site is marked example: true"))
        level = levels.get(zone.get("level_id"))
        if level is not None and not level.get("verified", False):
            out.append(Finding(
                ERROR, "verified_zone_on_unverified_level", f"zone {zone_id!r}",
                f"zone claims verified while level {zone.get('level_id')!r} does not"))
        for item in zone.get("infrastructure") or ():
            if item.get("kind") == "fixed_camera" and not item.get("calibration"):
                out.append(Finding(
                    WARNING, "verified_zone_camera_uncalibrated", f"zone {zone_id!r}",
                    f"fixed_camera {item.get('id')!r} has no calibration profile in a "
                    "zone marked verified — its pose is declared, not surveyed"))


def validate_domain(domain: Mapping[str, Any], *, map_size: Mapping[str, Any] | None,
                    known_zone_ids: Mapping[str, str], out: list[Finding]) -> None:
    """한 도메인과 그 구역들을 본다. `known_zone_ids` 는 이미 쓰인 구역 id → 도메인."""
    domain_id = domain.get("domain_id", "?")
    where_domain = f"domain {domain_id!r}"
    if not _require(domain, ("domain_id", "label", "rect", "space", "levels", "zones"),
                    where_domain, out):
        return

    space = domain["space"]
    space_w, space_h = float(space["width"]), float(space["height"])
    if space.get("unit") != "meter":
        out.append(Finding(ERROR, "space_unit_not_meter", where_domain,
                           f"space.unit is {space.get('unit')!r}; zone geometry is metric "
                           "site-local (AI-C-02)"))
    if map_size is not None:
        rect = _rect(domain["rect"])
        if rect[0] < 0 or rect[1] < 0 or \
                rect[0] + rect[2] > float(map_size["width"]) or \
                rect[1] + rect[3] > float(map_size["height"]):
            out.append(Finding(ERROR, "domain_rect_outside_map", where_domain,
                               f"rect {domain['rect']} leaves the main map "
                               f"{map_size['width']}x{map_size['height']} index space"))

    validate_rf(domain, out)
    validate_site_honesty(domain, out)

    level_ids = [level.get("level_id") for level in domain["levels"]]
    bands = set((domain.get("rf") or {}).keys())
    edge_nodes = {item.get("id") for zone in domain["zones"]
                  for item in zone.get("infrastructure") or ()
                  if item.get("kind") == "edge_node"}

    seen_here: dict[str, tuple[float, float, float, float]] = {}
    for zone in domain["zones"]:
        zone_id = zone.get("zone_id", "?")
        where = f"zone {zone_id!r}"
        if not _require(zone, ("zone_id", "label", "rect"), where, out):
            continue

        # 구역 id 는 도메인을 가로질러 유일해야 한다 — 화면과 API 가 구역을 id 하나로
        # 가리키므로 겹치면 다른 도메인의 구역이 열린다(fleet.load_domain_profile 과 같은 규칙).
        if zone_id in known_zone_ids:
            out.append(Finding(
                ERROR, "duplicate_zone_id", where,
                f"zone_id already declared in domain "
                f"{known_zone_ids[zone_id]!r}; zone ids must be unique across domains"))
        else:
            known_zone_ids[zone_id] = domain_id

        rect = _rect(zone["rect"])
        if rect[2] <= 0 or rect[3] <= 0:
            out.append(Finding(ERROR, "zone_rect_empty", where,
                               f"rect {zone['rect']} has no area"))
        if rect[0] < 0 or rect[1] < 0 or rect[0] + rect[2] > space_w or rect[1] + rect[3] > space_h:
            out.append(Finding(
                ERROR, "zone_outside_domain_space", where,
                f"rect {zone['rect']} leaves the domain space {space_w:g}x{space_h:g} m "
                f"(right edge {rect[0] + rect[2]:g}, bottom edge {rect[1] + rect[3]:g})"))

        level_id = zone.get("level_id")
        if level_id not in level_ids:
            out.append(Finding(
                ERROR, "undeclared_level", where,
                f"references level {level_id!r} which domain {domain_id!r} does not "
                f"declare; declared levels are {level_ids}"))

        for other_id, other in seen_here.items():
            if _overlap_area(rect, other) > 0:
                out.append(Finding(WARNING, "zone_overlap", where,
                                   f"rect overlaps zone {other_id!r} on the same domain"))
        seen_here[zone_id] = rect

        _validate_wifi(zone, domain, rect, bands, out)

        for item in zone.get("infrastructure") or ():
            at = item.get("at")
            if at and not _inside((float(at["x"]), float(at["y"])), rect):
                out.append(Finding(
                    ERROR, "infrastructure_outside_zone", where,
                    f"{item.get('kind', 'infrastructure')} {item.get('id')!r} sits at "
                    f"({at['x']}, {at['y']}), outside its own zone rect {zone['rect']}"))
        for node in zone.get("declared_nodes") or ():
            at = node.get("at")
            if at and not _inside((float(at["x"]), float(at["y"])), rect):
                out.append(Finding(
                    ERROR, "declared_node_outside_zone", where,
                    f"declared node {node.get('node_id')!r} sits at ({at['x']}, {at['y']}), "
                    f"outside its own zone rect {zone['rect']}"))
        edge = zone.get("edge_node")
        if edge and edge not in edge_nodes:
            out.append(Finding(
                ERROR, "unknown_edge_node", where,
                f"edge_node {edge!r} is not declared as infrastructure of kind "
                f"'edge_node' anywhere in domain {domain_id!r}"))


def _validate_wifi(zone: Mapping[str, Any], domain: Mapping[str, Any],
                   rect: tuple[float, float, float, float],
                   bands: set[str], out: list[Finding]) -> None:
    """AP 자리가 말이 되는가.

    AP 가 자기 구역 **안**에 있어야 한다고 보지 않는다 — 옥외에서는 한 AP 가 여러
    구역을 덮고, 배포된 프로파일이 실제로 그렇게 선언돼 있다. 대신 두 가지를 본다:
    AP 가 현장 공간 안에 있는가, 그리고 구역의 가장 먼 구석이 그 AP 의 반경 안인가.
    """
    zone_id = zone.get("zone_id", "?")
    where = f"zone {zone_id!r}"
    wifi = zone.get("wifi")
    if not wifi:
        out.append(Finding(WARNING, "zone_without_ap", where,
                           "no wifi declaration; remote capability in this zone is unverified"))
        return
    at = wifi.get("at")
    if not at:
        out.append(Finding(ERROR, "ap_without_position", where,
                           f"wifi.ap_id {wifi.get('ap_id')!r} has no 'at'"))
        return
    ap = (float(at["x"]), float(at["y"]))
    space = domain["space"]
    if not _inside(ap, (0.0, 0.0, float(space["width"]), float(space["height"]))):
        out.append(Finding(ERROR, "ap_outside_domain_space", where,
                           f"ap {wifi.get('ap_id')!r} sits at {ap}, outside the domain "
                           f"space {space['width']}x{space['height']} m"))

    band_name = wifi.get("rf")
    band = (domain.get("rf") or {}).get(band_name)
    if band is None:
        # 밴드가 없으면 덮이는지 **계산할 수 없다**. 모르는 것을 통과도 실패도 아닌
        # 미확인으로 남긴다 — 여기서 임의의 모델을 가정하면 그 가정이 배치 근거가 된다.
        out.append(Finding(
            WARNING, "undeclared_rf_band", where,
            f"wifi.rf is {band_name!r} but domain {domain.get('domain_id')!r} declares "
            f"only {sorted(bands)} — ap coverage cannot be verified"))
        return
    try:
        radii = derive_radii(band)
    except DeclarationError:
        return                                  # validate_rf 가 이미 사유를 남겼다
    corner, distance = _farthest_corner(ap, rect)
    floor = radii.get(THRESHOLD_FLOOR)
    handover = radii.get(THRESHOLD_HANDOVER)
    if floor is not None and distance > floor:
        out.append(Finding(
            ERROR, "zone_beyond_rf_floor", where,
            f"corner {corner} is {distance:.1f} m from ap {wifi.get('ap_id')!r}, past the "
            f"{band_name} floor radius {floor} m — that corner has no link at all"))
    elif handover is not None and distance > handover:
        out.append(Finding(
            WARNING, "zone_beyond_handover_radius", where,
            f"corner {corner} is {distance:.1f} m from ap {wifi.get('ap_id')!r}, past the "
            f"{band_name} handover radius {handover} m — that part of the zone runs below "
            "the handover floor"))


def validate_profile(profile: Mapping[str, Any]) -> tuple[Finding, ...]:
    """프로파일 한 장 전체를 검사한다. 아무것도 고치지 않는다."""
    out: list[Finding] = []
    for key in ("map", "domains"):
        if key not in profile:
            out.append(Finding(ERROR, "missing_field", "profile",
                               f"domain profile needs {key!r}"))
    if out:
        return tuple(out)
    known: dict[str, str] = {}
    for domain in profile["domains"]:
        validate_domain(domain, map_size=profile["map"], known_zone_ids=known, out=out)
    return tuple(out)


# --- 선언 → 조각 ------------------------------------------------------------

def build_domain(declaration: Mapping[str, Any]) -> dict:
    """작은 선언 하나를 프로파일에 붙여 넣을 도메인 조각으로 만든다.

    하는 일은 거의 전사(轉寫)이고, 계산하는 것은 **RF 반경 하나뿐**이다 — 그 값만
    모델에서 파생되고 나머지는 사람이 선언한 사실이기 때문이다.
    """
    if "domain" not in declaration:
        raise DeclarationError("declaration needs a 'domain' object")
    domain: dict[str, Any] = json.loads(json.dumps(declaration["domain"]))
    zones = declaration.get("zones", domain.pop("zones", []))
    for band_name, band in (domain.get("rf") or {}).items():
        derived = derive_radii(band)
        stated = band.get("radius_m")
        if stated is not None:
            drift = {k: (stated.get(k), v) for k, v in derived.items()
                     if k not in stated or
                     abs(float(stated[k]) - v) > 10 ** -RADIUS_DECIMALS / 2}
            if drift:
                raise DeclarationError(
                    f"rf.{band_name}.radius_m disagrees with the declared log-distance "
                    f"model at {sorted(drift)}; drop radius_m and let it be derived")
        band["radius_m"] = derived
    domain["zones"] = list(zones)
    return domain


def _load_domain_profile_checker():
    """`tools/fms_console/fleet.load_domain_profile` 를 쓸 수 있으면 가져온다.

    못 가져와도 검증은 계속한다 — 콘솔 도구 하나가 없다고 현장 선언을 검사하지 못하면
    선택 구성요소의 결손이 핵심 작업을 막는 것이다(AI-C-05).
    """
    console = PROJECT_ROOT / "tools" / "fms_console"
    if str(console) not in sys.path:
        sys.path.insert(0, str(console))
    try:
        from fleet import load_domain_profile      # type: ignore[import-not-found]
    except Exception:                              # noqa: BLE001
        return None
    return load_domain_profile


def validate_declaration(
    declaration: Mapping[str, Any], *, against: Mapping[str, Any] | None = None,
) -> tuple[dict | None, tuple[Finding, ...]]:
    """선언을 검증하고, 통과하면 붙여 넣을 조각을 함께 낸다.

    `against` 는 이미 배포된 프로파일이다 — 구역 id 유일성은 그 파일까지 봐야 알 수
    있고, 메인 맵 index 공간도 거기서 온다.
    """
    out: list[Finding] = []
    try:
        domain = build_domain(declaration)
    except (DeclarationError, KeyError) as exc:
        return None, (Finding(ERROR, "declaration_unreadable", "declaration", str(exc)),)

    known: dict[str, str] = {}
    map_size = None
    if against is not None:
        map_size = against.get("map")
        for other in against.get("domains", ()):
            if other.get("domain_id") == domain.get("domain_id"):
                out.append(Finding(
                    ERROR, "duplicate_domain_id", f"domain {domain.get('domain_id')!r}",
                    "a domain with this id is already declared in the target profile"))
            for zone in other.get("zones", ()):
                known[zone["zone_id"]] = other.get("domain_id", "?")

    validate_domain(domain, map_size=map_size, known_zone_ids=known, out=out)

    checker = _load_domain_profile_checker()
    if checker is not None and against is not None and not any(
            f.severity == ERROR for f in out):
        # 우리 검사를 통과한 조각이 **기존 로더로도** 읽히는지 확인한다. 두 검사가
        # 다른 답을 내면 배포 시점에 드러난다.
        spliced = {**json.loads(json.dumps(against))}
        spliced["domains"] = list(spliced.get("domains", ())) + [domain]
        try:
            _check_with_loader(checker, spliced)
        except Exception as exc:                   # noqa: BLE001
            out.append(Finding(ERROR, "rejected_by_profile_loader", "declaration", str(exc)))

    if any(f.severity == ERROR for f in out):
        return None, tuple(out)
    return domain, tuple(out)


def _check_with_loader(checker, profile: Mapping[str, Any]) -> None:
    """로더는 경로를 받으므로 임시 파일 한 장을 거친다."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8",
                                     delete=False) as handle:
        json.dump(profile, handle)
        name = handle.name
    try:
        checker(name)
    finally:
        Path(name).unlink(missing_ok=True)


# --- CLI --------------------------------------------------------------------

def _report(findings: Iterable[Finding], stream) -> tuple[int, int]:
    errors = warnings = 0
    for finding in findings:
        print(finding, file=stream)
        if finding.severity == ERROR:
            errors += 1
        else:
            warnings += 1
    return errors, warnings


def main(argv: Sequence[str] | None = None, *, stream=None) -> int:
    stream = stream or sys.stdout
    parser = argparse.ArgumentParser(
        description="새 도메인·구역 선언을 검증하고 프로파일 조각을 낸다")
    parser.add_argument("--check", action="store_true",
                        help="배포된 도메인 프로파일 자체를 검사한다")
    parser.add_argument("--declare", metavar="FILE",
                        help="새 도메인·구역 선언(JSON)")
    parser.add_argument("--profile", metavar="FILE", default=str(DEFAULT_PROFILE),
                        help="검사하거나 비교 대상으로 쓸 도메인 프로파일")
    parser.add_argument("--out", metavar="FILE",
                        help="통과한 도메인 조각을 쓸 자리(없으면 표준출력)")
    parser.add_argument("--strict", action="store_true",
                        help="미확인(경고)도 실패로 센다")
    args = parser.parse_args(argv)

    if not args.check and not args.declare:
        parser.error("--check or --declare is required")

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))

    if args.check:
        findings = validate_profile(profile)
        errors, warnings = _report(findings, stream)
        print(f"-- {args.profile}: {errors} error(s), {warnings} unverified/warning(s)",
              file=stream)
        if errors or (args.strict and warnings):
            return 1
        return 0

    declaration = json.loads(Path(args.declare).read_text(encoding="utf-8"))
    domain, findings = validate_declaration(declaration, against=profile)
    errors, warnings = _report(findings, stream)
    if domain is None or (args.strict and warnings):
        print(f"-- declaration rejected: {errors} error(s), "
              f"{warnings} unverified/warning(s)", file=stream)
        return 1
    fragment = json.dumps(domain, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(fragment + "\n", encoding="utf-8")
        print(f"-- wrote domain fragment to {args.out} "
              f"({warnings} unverified/warning(s))", file=stream)
    else:
        print(fragment, file=stream)
    return 0


if __name__ == "__main__":                        # pragma: no cover
    raise SystemExit(main())
