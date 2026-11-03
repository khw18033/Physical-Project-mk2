"""implements: AI-S-06, AI-C-08, AI-C-15, AI-C-02

여기서 검증하는 것은 "그럴듯한 모양이 떴는가" 가 아니라 **모양이 거짓말하지 않는가**
다. 가상환경이 관측된 객체를 저장 자산으로 대신 그릴 때 조용히 거짓말하는 길이 네 개
있고, 네 경우 모두 예외도 추측도 아니어야 한다.

1. 대역을 개체 주장으로 바꾸는 길 — 외형은 종류만 말한다(perception/device_identity.py).
2. 대역이 없을 때 객체를 화면에서 지우는 길 — 모양이 없어도 자리는 나가야 한다.
3. 선언 크기와 실측이 어긋날 때 조용히 늘리는 길 — 미측정은 0 도 불일치도 아니다.
4. 근거가 바뀌었을 때 이전 선택을 덮는 길 — 덮으면 "왜 모양이 바뀌었나" 를 못 되짚는다.

카탈로그 시험은 **공개 트리의 실제 선언**(config/object_models.example.json)으로 돌린다
— 지어낸 카탈로그로만 재면 그 파일이 실제로 읽히는지는 영영 알 수 없다.
"""

import json
from dataclasses import replace

import pytest

from conftest import PACKAGE_DIR
from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.perception.object_appearance import (
    ASSET_KIND_IMAGE,
    ASSET_KIND_MODEL,
    ASSET_ROOT_ENV,
    DEFAULT_PRIORITY,
    GROUP_KEYS,
    IDENTITY_FIELD_NAMES,
    LICENSE_UNKNOWN,
    NO_CATALOG_FILE,
    REASON_EVERY_STAND_IN_UNFIT,
    REASON_KIND_NOT_ESTABLISHED,
    REASON_NO_CATALOG,
    REASON_NO_STAND_IN_FOR_KIND,
    REASON_STANDS_IN_FOR_KIND,
    REFUSE_GLOBAL_FRAME,
    REFUSE_POSITION_UNKNOWN,
    REFUSE_UNKNOWN_FRAME,
    REJECT_ASSET_REF_ESCAPES_ROOT,
    REJECT_DUPLICATE_PROXY_ID,
    REJECT_EXTENT_NOT_POSITIVE,
    REJECT_IDENTITY_FIELD,
    REJECT_MISSING_FIELD,
    REJECT_NO_PROXIES_KEY,
    REJECT_NO_STANDS_IN_FOR,
    REJECT_UNDECLARED_ASSET_KIND,
    REJECT_UNKNOWN_LICENSE_REDISTRIBUTED,
    SIDE_BOTH,
    SIDE_DECLARED,
    SIDE_MEASURED,
    SIZE_MATCH,
    SIZE_MISMATCH,
    SIZE_UNMEASURED,
    SUPERSEDE_KIND_CHANGED,
    SUPERSEDE_OTHER_STAND_IN,
    SUPERSEDE_STAND_IN_FOUND,
    SUPERSEDE_STAND_IN_LOST,
    TIER_DECLARED,
    TIER_ESTIMATED,
    TIER_MEASURED,
    UNFIT_ASSET_FILE_MISSING,
    KindClaim,
    ProxyAsset,
    ProxyCatalog,
    ProxyCatalogError,
    ProxyPlacement,
    ProxyResolver,
    ProxyState,
    catalog_licenses,
    compare_extent,
    confirmed_kind_claim,
    declared_kind_claim,
    default_asset_root,
    identity_fields,
    kind_claim_from_estimate,
    local_placement,
    proxy_kinds_without_stand_in,
    resolver_from_catalog,
    unknown_placement,
    unlicensed_proxies,
)

CATALOG_PATH = PACKAGE_DIR / "config" / "object_models.example.json"


@pytest.fixture(scope="module")
def catalog() -> ProxyCatalog:
    return ProxyCatalog.load(CATALOG_PATH)


@pytest.fixture
def raw_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _write(tmp_path, raw: dict):
    path = tmp_path / "object_models.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def _entry(**overrides) -> dict:
    entry = {
        "proxy_id": "test-proxy",
        "stands_in_for": ["test.kind"],
        "asset_kind": ASSET_KIND_MODEL,
        "asset_ref": "object_proxies/test/thing.glb",
        "origin": "시험용 선언",
        "license": "CC0-1.0",
    }
    entry.update(overrides)
    return entry


def _resolver(catalog: ProxyCatalog, **kwargs) -> ProxyResolver:
    """자산 뿌리를 주지 않는다 — 존재 확인은 전용 시험에서만 켠다."""
    return ProxyResolver(catalog, **kwargs)


# ---------------------------------------------------------------------------
# 카탈로그는 데이터다
# ---------------------------------------------------------------------------


def test_the_example_catalog_loads_and_every_proxy_declares_its_provenance(catalog):
    assert catalog.available
    assert len(catalog.proxies) >= 5
    for asset in catalog.proxies:
        assert asset.origin, asset.proxy_id
        assert asset.license, asset.proxy_id
        assert asset.stands_in_for, asset.proxy_id
        # 자산 파일은 공개 트리 밖에 산다 — 선언은 **참조만** 적는다.
        assert not asset.asset_ref.startswith("/")
        assert ".." not in asset.asset_ref
        assert asset.asset_kind in catalog.asset_kinds


def test_an_unknown_license_is_written_down_not_left_blank(catalog):
    """모르는 것을 '공개' 로 적지 않는다(config/label_sources.example.json 과 같은 규약).

    공개 트리의 선언 중 **적어도 하나**는 라이선스 미확인이다. 그 경우가 예시에
    없으면 미확인 경로는 코드에만 있고 아무도 돌려 보지 않은 길이 된다.
    """
    unlicensed = unlicensed_proxies(catalog)
    declared = catalog_licenses(catalog)

    assert set(declared) == {a.proxy_id for a in catalog.proxies}
    assert all(declared.values()), "빈 라이선스 칸은 없다 — 모름도 적는다"
    assert unlicensed, "라이선스 미확인 항목이 예시에 하나는 있어야 한다"
    for proxy_id in unlicensed:
        asset = catalog.get(proxy_id)
        assert asset.license == LICENSE_UNKNOWN
        assert asset.license_known is False
        # 모르는 라이선스를 재배포 가능으로 적는 선언은 애초에 거절된다.
        assert asset.redistributable is False
        assert asset.origin, "출처를 모른다는 사실도 적혀 있어야 한다"


def test_the_catalog_covers_this_project_domains(catalog):
    """하천 부유물 · UGV · UAV · 사람 · 점검 대상이 전부 데이터로 서 있다(AI-C-15).

    도메인 차이가 코드 분기가 아니라 선언으로 표현된다는 것이 이 줄의 뜻이다.
    """
    kinds = set(catalog.kinds)

    assert {"waste.bottle", "floater"} <= kinds          # 하천 부유물
    assert {"locomotion.legged", "locomotion.wheeled"} <= kinds  # UGV 두 종류
    assert "platform.uav" in kinds                        # UAV
    assert "person" in kinds                              # 사람
    assert "inspection.target" in kinds                   # 점검 대상
    # 표현 종류는 둘 다 실제로 쓰인다 — 3D 모델이 없는 종류는 저장 이미지로 선다.
    assert {a.asset_kind for a in catalog.proxies} == {ASSET_KIND_MODEL, ASSET_KIND_IMAGE}


def test_adding_a_proxy_is_a_line_of_data_not_a_code_change(tmp_path, raw_catalog):
    """모듈이 **이름을 모르는** 종류·표현 방식이 선언만으로 들어온다(원칙 #1, #7)."""
    raw_catalog["$asset_kinds"]["point_cloud_scan"] = "현장 스캔 점군"
    raw_catalog["proxies"].append(_entry(
        proxy_id="scanned-mooring-post",
        stands_in_for=["mooring_post", "inspection.target"],
        asset_kind="point_cloud_scan",
        asset_ref="object_proxies/inspection/mooring_post.laz",
        extent_m=1.2,
        priority=5,
    ))

    catalog = ProxyCatalog.load(_write(tmp_path, raw_catalog))
    resolution = _resolver(catalog).resolve(
        "obj-1", KindClaim("mooring_post", source="t", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))

    assert resolution.proxy_id == "scanned-mooring-post"
    assert resolution.proxy.asset_kind == "point_cloud_scan"
    # 우선순위가 더 낮은(= 먼저인) 새 선언이 기존 점검 대역을 앞질렀다. 순서는
    # 선언 데이터이고 코드가 아니다.
    assert [a.proxy_id for a in catalog.for_kind("inspection.target")] == [
        "scanned-mooring-post", "inspection-revetment-block"]


def test_a_missing_catalog_is_a_normal_empty_catalog_not_an_exception(tmp_path):
    """카탈로그를 배포하지 않은 노드가 기동조차 못 하면 AI-C-05 위반이다."""
    catalog = ProxyCatalog.load(tmp_path / "nope.json")

    assert catalog.available is False
    assert catalog.missing_reason == NO_CATALOG_FILE
    assert catalog.for_kind("anything") == ()

    resolution = resolver_from_catalog(tmp_path / "nope.json").resolve(
        "obj-1", KindClaim("waste.bottle", source="t", observed_at=1.0),
        placement=local_placement((3.0, 4.0), frame_id="ZONE-A"))

    assert resolution.state is ProxyState.ABSENT
    assert resolution.reason == REASON_NO_CATALOG
    # 모양이 없어도 자리는 나간다.
    assert resolution.placement.value == (3.0, 4.0)


def test_a_declaration_that_names_an_individual_is_rejected(tmp_path, raw_catalog):
    """대역은 **종류**의 대역이다. 개체를 적은 선언은 결속 주장이고, 그 주장은 식별력
    있는 단서로만 선다(perception/device_identity.py)."""
    raw_catalog["proxies"].append(_entry(device_id="go1-a"))

    with pytest.raises(ProxyCatalogError) as excinfo:
        ProxyCatalog.load(_write(tmp_path, raw_catalog))

    assert REJECT_IDENTITY_FIELD in str(excinfo.value)
    assert dd.DEVICE_ID in str(excinfo.value)
    assert dd.DEVICE_ID in IDENTITY_FIELD_NAMES
    assert identity_fields({dd.ENTITY_ID: "e-1", dd.PROXY_ID: "p"}) == (dd.ENTITY_ID,)


@pytest.mark.parametrize("overrides, token", [
    ({"license": None}, REJECT_MISSING_FIELD),                       # 모름도 적어야 한다
    ({"origin": None}, REJECT_MISSING_FIELD),
    ({"proxy_id": "floater-generic"}, REJECT_DUPLICATE_PROXY_ID),
    ({"asset_kind": "hologram"}, REJECT_UNDECLARED_ASSET_KIND),      # 파일이 어휘를 정한다
    ({"stands_in_for": []}, REJECT_NO_STANDS_IN_FOR),                # 영원히 안 뽑힌다
    ({"asset_ref": "/srv/models/thing.glb"}, REJECT_ASSET_REF_ESCAPES_ROOT),
    ({"asset_ref": "../../etc/passwd"}, REJECT_ASSET_REF_ESCAPES_ROOT),
    ({"license": LICENSE_UNKNOWN, "redistributable": True},
     REJECT_UNKNOWN_LICENSE_REDISTRIBUTED),
    ({"extent_m": 0}, REJECT_EXTENT_NOT_POSITIVE),                   # 0 은 모름이 아니다
])
def test_a_misdeclared_proxy_is_rejected_with_its_reason(tmp_path, raw_catalog,
                                                         overrides, token):
    """배치 전에 파일만 보고 알 수 있는 잘못을 현장에서 발견할 이유가 없다(AI-B-09)."""
    entry = _entry()
    for key, value in overrides.items():
        if value is None:
            entry.pop(key)
        else:
            entry[key] = value
    raw_catalog["proxies"].append(entry)

    with pytest.raises(ProxyCatalogError) as excinfo:
        ProxyCatalog.load(_write(tmp_path, raw_catalog))

    assert token in str(excinfo.value)


def test_a_catalog_without_the_proxies_key_is_rejected(tmp_path):
    with pytest.raises(ProxyCatalogError) as excinfo:
        ProxyCatalog.load(_write(tmp_path, {"$asset_kinds": {}}))

    assert REJECT_NO_PROXIES_KEY in str(excinfo.value)


def test_the_asset_root_convention_is_the_shared_one(tmp_path, monkeypatch):
    """`tests/conftest.py::asset_root()` · `tools/fms_console` 와 같은 환경변수다."""
    monkeypatch.setenv(ASSET_ROOT_ENV, str(tmp_path / "elsewhere"))

    # 환경변수가 가리키는 자리가 없어도 그대로 쓴다 — 조용히 다른 곳을 집으면 "왜 못
    # 찾느냐" 를 추적할 수 없다.
    assert default_asset_root() == tmp_path / "elsewhere"


# ---------------------------------------------------------------------------
# 종류로 고른다 — 그리고 그 근거를 말한다
# ---------------------------------------------------------------------------


def test_a_proxy_is_chosen_for_the_kind_and_states_the_grounds(catalog):
    claim = KindClaim("waste.bottle", tier=TIER_ESTIMATED, confidence=0.81,
                      source="device_class_estimator", observed_at=10.0,
                      frame_ref="cam-1/0007")

    resolution = _resolver(catalog).resolve(
        "obj-1", claim, placement=local_placement((2.0, 3.0), frame_id="ZONE-A"))

    assert resolution.state is ProxyState.RESOLVED
    assert resolution.reason == REASON_STANDS_IN_FOR_KIND
    assert resolution.proxy_id == "floater-pet-bottle"
    # 근거의 격과 확신이 **따로** 실린다(AI-S-03) — 격은 출처의 성질이고 확신은 모델
    # 이 말한 수치다.
    assert resolution.grounds.tier == TIER_ESTIMATED
    assert resolution.grounds.confidence == 0.81
    assert resolution.grounds.frame_ref == "cam-1/0007"
    payload = resolution.as_dict()
    assert payload["grounds"][dd.EVIDENCE_TIER] == TIER_ESTIMATED
    assert payload[dd.STANDS_IN_FOR] == sorted(resolution.proxy.stands_in_for)


def test_the_choice_is_deterministic_and_declared_priority_decides(catalog):
    """같은 입력에 같은 순서. 아니면 화면이 틱마다 다른 모양을 세운다."""
    for_floater = catalog.for_kind("floater")
    assert [a.proxy_id for a in for_floater] == sorted(
        (a.proxy_id for a in for_floater),
        key=lambda pid: (catalog.get(pid).priority, pid))

    claim = KindClaim("inspection.target", source="t", observed_at=1.0)
    first = _resolver(catalog).resolve(
        "obj-1", claim, placement=local_placement((0.0, 0.0), frame_id="ZONE-A"))
    again = _resolver(catalog).resolve(
        "obj-1", claim, placement=local_placement((0.0, 0.0), frame_id="ZONE-A"))

    assert first.proxy_id == again.proxy_id
    assert first.alternatives == again.alternatives
    assert first.proxy_id not in first.alternatives


def test_a_proxy_never_carries_an_individual_identity_claim(catalog):
    """같은 기종 두 대는 **같은 대역**으로 선다. 그것이 정확한 표현이다.

    외형은 종류까지만 말한다(perception/device_identity.py) — 그래서 이 산출에는
    개체를 가리키는 칸이 하나도 없고, 그 부재가 설계다(AI-C-19).
    """
    resolver = _resolver(catalog)
    claim = KindClaim("go1", source="estimator", observed_at=1.0, confidence=0.9)

    left = resolver.resolve("obj-a", claim,
                            placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))
    right = resolver.resolve("obj-b", claim,
                             placement=local_placement((4.0, 1.0), frame_id="ZONE-A"))

    assert left.proxy_id == right.proxy_id == "ugv-quadruped"

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in IDENTITY_FIELD_NAMES, key
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(left.as_dict())
    # 주체는 객체 레코드 식별자이고 장치 개체가 아니다.
    assert left.as_dict()[dd.OBJECT_ID] == "obj-a"
    # 종류 자리에 개체 이름을 넣는 것은 종류 주장이 아니다.
    with pytest.raises(ValueError):
        KindClaim(dd.DEVICE_ID, source="t", observed_at=1.0)


def test_every_name_that_leaves_the_module_is_in_the_data_dictionary(catalog):
    """AI-C-01: 경계로 나가는 이름은 쓰기 전에 사전에 등록한다."""
    resolution = _resolver(catalog).resolve(
        "obj-1", KindClaim("person", source="t", observed_at=1.0, confidence=0.5),
        placement=local_placement((1.0, 2.0), frame_id="ZONE-A", heading_deg=90.0),
        measured_extent_m=1.75)
    payload = resolution.as_dict()

    flat = {k: v for k, v in payload.items() if k not in GROUP_KEYS}
    assert dd.unknown_fields(flat) == ()
    for group in GROUP_KEYS:
        if payload[group] is not None:
            assert dd.unknown_fields(payload[group]) == (), group
    assert payload[dd.PROXY_STATE] in dd.PROXY_STATES
    assert payload[dd.PROXY_REASON] in dd.PROXY_REASONS
    assert payload["size_fit"][dd.SIZE_FIT_STATE] in dd.SIZE_FIT_STATES
    assert resolution.grounds.tier in dd.SPATIAL_EVIDENCE_TIERS


def test_the_module_reason_vocabularies_are_the_dictionary_vocabularies():
    """모듈이 문자열을 정하고 사전이 어휘를 소유한다(selector 와 같은 규약)."""
    from mission_runtime.perception import object_appearance as oa

    reasons = {v for k, v in vars(oa).items()
               if k.startswith("REASON_") and isinstance(v, str)}
    supersedes = {v for k, v in vars(oa).items()
                  if k.startswith("SUPERSEDE_") and isinstance(v, str)}
    refusals = {v for k, v in vars(oa).items()
                if k.startswith("REFUSE_") and isinstance(v, str)}

    assert reasons and supersedes and refusals
    assert reasons <= set(dd.PROXY_REASONS)
    assert supersedes <= set(dd.PROXY_SUPERSEDE_REASONS)
    assert refusals <= set(dd.PLACEMENT_REFUSAL_REASONS)
    assert {s.value for s in ProxyState} == set(dd.PROXY_STATES)
    assert {SIZE_MATCH, SIZE_MISMATCH, SIZE_UNMEASURED} == set(dd.SIZE_FIT_STATES)


def test_a_declared_kind_is_prior_information_and_a_confirmed_one_needs_a_signature():
    """선언은 사전정보이고 관측이 아니다(AI-S-08). 사람 확인은 서명 없이 받지 않는다."""
    declared = declared_kind_claim("go1", source="join_declaration", observed_at=1.0)
    confirmed = confirmed_kind_claim("go1", confirmed_by="operator-kim", observed_at=2.0)

    assert declared.tier == TIER_DECLARED
    assert declared.confidence is None, "선언은 확신을 측정한 것이 아니다"
    assert confirmed.tier == TIER_MEASURED
    with pytest.raises(ValueError):
        confirmed_kind_claim("go1", confirmed_by="", observed_at=2.0)
    with pytest.raises(ValueError):
        KindClaim("go1", tier="vibes", source="t", observed_at=1.0)
    with pytest.raises(ValueError):
        KindClaim("go1", confidence=1.4, source="t", observed_at=1.0)


def test_an_unconfirmed_class_estimate_does_not_become_a_kind(catalog):
    """모호·모순 추정에서 1 위를 집어 오면 화면에서 확답처럼 보인다(AI-S-04)."""
    from mission_runtime.perception.device_class_estimator import (
        ClassEstimate,
        ClassState,
        ClassSupport,
    )

    ranked = (ClassSupport("go1", "지상 로봇", decisive_score=0.7, supporting_score=0.2),)
    confident = ClassEstimate(ClassState.ESTIMATED, "go1", "x", ranked=ranked)
    ambiguous = ClassEstimate(ClassState.AMBIGUOUS, None, "nobody_separated", ranked=ranked)
    conflicted = ClassEstimate(ClassState.CONFLICTED, "go1", "decisive_disagree",
                               ranked=ranked)

    good = kind_claim_from_estimate(confident, source="est", observed_at=1.0)
    assert good.kind == "go1"
    assert good.tier == TIER_ESTIMATED
    assert good.confidence == pytest.approx(0.7 + 0.3 * 0.2)

    for estimate in (ambiguous, conflicted):
        claim = kind_claim_from_estimate(estimate, source="est", observed_at=1.0)
        assert claim.kind is None
        assert claim.established is False
        assert claim.reason == estimate.reason
        resolution = _resolver(catalog).resolve(
            "obj-1", claim, placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))
        assert resolution.state is ProxyState.ABSENT
        assert resolution.reason == REASON_KIND_NOT_ESTABLISHED


# ---------------------------------------------------------------------------
# "대역 없음" 은 정상 상태다
# ---------------------------------------------------------------------------


def test_an_unknown_kind_is_absent_but_the_twin_still_gets_the_position(catalog):
    resolution = _resolver(catalog).resolve(
        "obj-1", KindClaim(None, source="est", observed_at=1.0, reason="no_cue"),
        placement=local_placement((7.5, 1.25), frame_id="ZONE-A", accuracy_m=0.4))

    assert resolution.state is ProxyState.ABSENT
    assert resolution.reason == REASON_KIND_NOT_ESTABLISHED
    assert resolution.proxy is None
    assert resolution.as_dict()[dd.PROXY_ID] is None
    # 자리는 그대로다 — 객체를 목록에서 빼는 것이 거짓말이다.
    assert resolution.placement.value == (7.5, 1.25)
    assert resolution.placement.accuracy_m == 0.4
    # 근거는 ABSENT 일 때도 남는다. 왜 못 골랐는지가 화면에 서야 한다.
    assert resolution.grounds.reason == "no_cue"


def test_a_known_kind_without_a_stand_in_has_its_own_reason(catalog):
    """"종류를 모른다" 와 "그 종류의 대역이 없다" 는 다른 사실이다."""
    resolution = _resolver(catalog).resolve(
        "obj-1", KindClaim("fallen_tree", source="est", observed_at=1.0, confidence=0.9),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))

    assert resolution.state is ProxyState.ABSENT
    assert resolution.reason == REASON_NO_STAND_IN_FOR_KIND
    assert resolution.grounds.kind == "fallen_tree"
    # 카탈로그에 무엇을 더해야 하는지의 목록이 나온다.
    assert proxy_kinds_without_stand_in(catalog, ["fallen_tree", "person"]) == ("fallen_tree",)


def test_a_stand_in_whose_asset_file_is_missing_is_unfit_not_silently_dropped(
        tmp_path, catalog):
    """없는 묶음을 '있다' 로 적으면 빈 화면이 뜨고 그 이유를 아무도 모른다."""
    resolver = ProxyResolver(catalog, asset_root=tmp_path)

    resolution = resolver.resolve(
        "obj-1", KindClaim("go1", source="est", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))

    assert resolution.state is ProxyState.ABSENT
    assert resolution.reason == REASON_EVERY_STAND_IN_UNFIT
    assert resolution.unfit == {"ugv-quadruped": UNFIT_ASSET_FILE_MISSING}

    # 파일을 놓아 주면 같은 선언이 그대로 선다 — 선택은 다시 계산되는 값이다.
    asset = catalog.get("ugv-quadruped")
    target = tmp_path / asset.asset_ref
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"glTF")
    after = resolver.resolve(
        "obj-1", KindClaim("go1", source="est", observed_at=2.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))

    assert after.state is ProxyState.RESOLVED
    assert after.asset_present is True
    assert after.unfit == {}

    # 파일 없이도 세우기로 **선언한** 배치에서는 고르되 결손을 함께 낸다 — 렌더러가
    # 자기 기본 모양으로 받을 수 있게 하는 길이고, 그 사실이 숨지 않는다.
    lenient = ProxyResolver(catalog, asset_root=tmp_path, require_asset_file=False)
    tolerated = lenient.resolve(
        "obj-2", KindClaim("person", source="est", observed_at=3.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))

    assert tolerated.state is ProxyState.RESOLVED
    assert tolerated.proxy_id == "person-standing"
    assert tolerated.asset_present is False


def test_without_an_asset_root_presence_is_unknown_not_missing(catalog):
    """미측정은 0 도 아니고 결손도 아니다 — 공개 트리만 받은 노드가 정상이다."""
    resolution = _resolver(catalog).resolve(
        "obj-1", KindClaim("go1", source="est", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))

    assert resolution.state is ProxyState.RESOLVED
    assert resolution.asset_present is None
    assert resolution.as_dict()[dd.ASSET_PRESENT] is None
    assert catalog.get("ugv-quadruped").asset_present(None) is None
    assert catalog.get("ugv-quadruped").asset_path(None) is None


# ---------------------------------------------------------------------------
# 크기 — 늘리지 않고 어긋남을 보고한다
# ---------------------------------------------------------------------------


def test_a_size_mismatch_is_reported_instead_of_stretching_the_asset(catalog):
    """사람 대역(1.7m)인데 실측이 0.4m 면 그것은 사람이 아니거나 대역이 틀린 것이다."""
    resolution = _resolver(catalog).resolve(
        "obj-1", KindClaim("person", source="est", observed_at=1.0, confidence=0.6),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"),
        measured_extent_m=0.4)

    assert resolution.state is ProxyState.RESOLVED, "어긋남이 대역을 지우지는 않는다"
    assert resolution.fit.state == SIZE_MISMATCH
    assert resolution.fit.mismatched is True
    assert resolution.fit.declared_extent_m == 1.7
    assert resolution.fit.measured_extent_m == 0.4
    assert resolution.fit.ratio == pytest.approx(0.4 / 1.7)
    payload = resolution.as_dict()["size_fit"]
    # 배율은 설명용 수치다. 적용 지시로 읽힐 이름이 산출에 없다.
    assert payload[dd.SIZE_RATIO] == pytest.approx(0.4 / 1.7, abs=1e-4)
    assert "scale" not in json.dumps(payload)


def test_a_size_within_tolerance_matches_and_the_tolerance_is_data(catalog):
    resolver = _resolver(catalog)
    close = resolver.resolve(
        "obj-1", KindClaim("waste.bottle", source="est", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"),
        measured_extent_m=0.3)

    assert close.fit.state == SIZE_MATCH

    strict = replace(resolver, size_tolerance=1.05).resolve(
        "obj-1", KindClaim("waste.bottle", source="est", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"),
        measured_extent_m=0.3)

    assert strict.fit.state == SIZE_MISMATCH
    assert strict.fit.tolerance == 1.05


def test_an_unmeasured_size_is_neither_zero_nor_a_mismatch(catalog):
    """어느 쪽이 미측정인지 적는다 — 합치면 두 사실이 같은 빈칸이 된다."""
    resolver = _resolver(catalog)

    # 카탈로그가 크기를 적지 않은 대역(미분류 부유물).
    no_declared = resolver.resolve(
        "obj-1", KindClaim("waste.unidentified", source="est", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"),
        measured_extent_m=0.5)
    # 관측이 크기를 재지 못한 경우.
    no_measured = resolver.resolve(
        "obj-2", KindClaim("waste.bottle", source="est", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))

    assert no_declared.proxy_id == "floater-generic"
    assert no_declared.proxy.extent_m is None
    assert no_declared.fit.state == SIZE_UNMEASURED
    assert no_declared.fit.unmeasured_side == SIDE_DECLARED
    assert no_declared.fit.ratio is None
    assert no_measured.fit.state == SIZE_UNMEASURED
    assert no_measured.fit.unmeasured_side == SIDE_MEASURED
    assert compare_extent(None, None).unmeasured_side == SIDE_BOTH
    # 0 을 "크기 없음" 으로 받아 주면 모르는 값이 아는 값처럼 비교된다.
    assert compare_extent(0.0, 0.5).state == SIZE_UNMEASURED


def test_a_proxy_may_leave_its_extent_unmeasured():
    """미측정은 칸을 비우는 것이고 0 을 적는 것이 아니다(AI-B-01)."""
    asset = ProxyAsset(proxy_id="p", stands_in_for=frozenset({"k"}))

    assert asset.extent_m is None
    assert asset.priority == DEFAULT_PRIORITY
    assert compare_extent(asset.extent_m, 1.0).state == SIZE_UNMEASURED


# ---------------------------------------------------------------------------
# 다시 계산되는 값 — 이전 선택을 덮지 않는다
# ---------------------------------------------------------------------------


def test_a_later_observation_supersedes_the_proxy_without_mutating_history(catalog):
    """처음에는 '부유물' 이던 것이 다음 관측에서 'PET 병' 이 된다."""
    resolver = _resolver(catalog)
    first = resolver.resolve(
        "obj-1", KindClaim("floater", source="est", observed_at=1.0, confidence=0.4),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"), resolved_at=1.0)
    second = resolver.resolve(
        "obj-1", KindClaim("waste.bottle", source="est", observed_at=5.0, confidence=0.8),
        placement=local_placement((1.2, 1.0), frame_id="ZONE-A"),
        previous=first, resolved_at=5.0)

    assert first.proxy_id == "floater-generic"
    assert second.proxy_id == "floater-pet-bottle"
    assert second.changed is True
    assert second.revision == 2
    assert second.superseded.previous_proxy_id == "floater-generic"
    assert second.superseded.previous_kind == "floater"
    assert second.superseded.reason == SUPERSEDE_KIND_CHANGED
    assert second.superseded.at == 5.0
    assert second.as_dict()["superseded"][dd.SUPERSEDED_PROXY_ID] == "floater-generic"

    # 이전 결과는 당시 그대로다 — 제자리에서 바뀌지 않는다.
    assert first.proxy_id == "floater-generic"
    assert first.revision == 1
    assert first.superseded is None
    assert first.changed is False
    assert second.history() == (second, first)
    assert [r.proxy_id for r in second.history()] == ["floater-pet-bottle",
                                                      "floater-generic"]


def test_re_resolving_the_same_kind_does_not_claim_a_change(catalog):
    """바뀐 것이 없는데 회차를 올리면 화면은 쉬지 않고 모양을 다시 세운다."""
    resolver = _resolver(catalog)
    claim = KindClaim("go1", source="est", observed_at=1.0, confidence=0.9)
    first = resolver.resolve("obj-1", claim,
                             placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))
    again = resolver.resolve(
        "obj-1", replace(claim, observed_at=2.0, confidence=0.95),
        placement=local_placement((1.4, 1.0), frame_id="ZONE-A"), previous=first)

    assert again.proxy_id == first.proxy_id
    assert again.revision == first.revision
    assert again.superseded is None
    assert again.changed is False
    # 자리와 확신은 갱신됐다 — 바뀌지 않은 것은 **대역 선택**이다.
    assert again.placement.value == (1.4, 1.0)
    assert again.grounds.confidence == 0.95


def test_a_kind_change_that_lands_on_the_same_proxy_is_not_a_supersession(catalog):
    """`go1` 과 `locomotion.legged` 는 같은 대역이다. 모양이 그대로면 대체가 아니다."""
    resolver = _resolver(catalog)
    first = resolver.resolve(
        "obj-1", KindClaim("locomotion.legged", source="est", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))
    second = resolver.resolve(
        "obj-1", KindClaim("go1", source="est", observed_at=2.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"), previous=first)

    assert first.proxy_id == second.proxy_id == "ugv-quadruped"
    assert second.superseded is None
    assert second.grounds.kind == "go1"


def test_losing_and_gaining_a_stand_in_are_different_supersede_reasons(catalog):
    resolver = _resolver(catalog)
    resolved = resolver.resolve(
        "obj-1", KindClaim("person", source="est", observed_at=1.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))
    lost = resolver.resolve(
        "obj-1", KindClaim("fallen_tree", source="est", observed_at=2.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"), previous=resolved)
    found = resolver.resolve(
        "obj-1", KindClaim("person", source="est", observed_at=3.0),
        placement=local_placement((1.0, 1.0), frame_id="ZONE-A"), previous=lost)

    assert lost.state is ProxyState.ABSENT
    assert lost.superseded.reason == SUPERSEDE_STAND_IN_LOST
    assert lost.superseded.previous_proxy_id == "person-standing"
    assert found.state is ProxyState.RESOLVED
    assert found.superseded.reason == SUPERSEDE_STAND_IN_FOUND
    assert found.superseded.previous_proxy_id is None
    assert found.revision == 3
    assert len(found.history()) == 3


def test_the_same_kind_choosing_another_catalogued_asset_says_so(tmp_path, raw_catalog):
    """카탈로그가 바뀌어 같은 종류의 다른 자산이 선택된 경우도 사유가 다르다."""
    before = ProxyCatalog.load(_write(tmp_path, raw_catalog))
    claim = KindClaim("person", source="est", observed_at=1.0)
    first = _resolver(before).resolve(
        "obj-1", claim, placement=local_placement((1.0, 1.0), frame_id="ZONE-A"))

    raw_catalog["proxies"].append(_entry(
        proxy_id="person-mesh", stands_in_for=["person"], priority=1,
        asset_ref="object_proxies/people/person.glb", extent_m=1.7))
    after = ProxyCatalog.load(_write(tmp_path, raw_catalog))
    second = _resolver(after).resolve(
        "obj-1", claim, placement=local_placement((1.0, 1.0), frame_id="ZONE-A"),
        previous=first)

    assert first.proxy_id == "person-standing"
    assert second.proxy_id == "person-mesh"
    assert second.superseded.reason == SUPERSEDE_OTHER_STAND_IN
    assert second.alternatives == ("person-standing",)


# ---------------------------------------------------------------------------
# 자리는 자기 프레임을 들고 다닌다 (AI-C-02)
# ---------------------------------------------------------------------------


def test_a_placement_keeps_the_frame_the_observation_came_in(catalog):
    resolution = _resolver(catalog).resolve(
        "obj-1", KindClaim("go1", source="est", observed_at=1.0),
        placement=local_placement((3.0, 4.0), frame_id="ZONE-B", heading_deg=45.0))
    payload = resolution.as_dict()["placement"]

    assert payload[dd.COORDINATE_FRAME] == "ZONE-B"
    assert payload[dd.PROXY_POSITION] == [3.0, 4.0]
    assert payload[dd.HEADING_DEG] == 45.0
    assert payload[dd.PLACEMENT_REFUSAL_REASON] is None


def test_a_global_frame_value_is_refused_and_never_shares_a_cell_with_a_local_one():
    """전역 변환은 검증된 datum 을 가진 계층의 일이다(AI-C-02). 여기서는 변환하지 않는다."""
    refused = local_placement((37.4563, 126.7052), frame_id="WGS84")

    assert refused.available is False
    assert refused.value is None, "전역 좌표가 로컬 자리 칸에 담기지 않는다"
    assert refused.refused_because == REFUSE_GLOBAL_FRAME
    payload = refused.as_dict()
    assert payload[dd.PROXY_POSITION] is None
    assert payload[dd.COORDINATE_FRAME] == "WGS84"
    assert "37.4563" not in json.dumps(payload)

    nameless = ProxyPlacement(value=(1.0, 1.0), coordinate_frame="")
    assert nameless.refused_because == REFUSE_UNKNOWN_FRAME
    unknown = unknown_placement(frame_id="ZONE-A")
    assert unknown.refused_because == REFUSE_POSITION_UNKNOWN
    assert unknown.heading_deg is None, "자세 미측정은 0 도가 아니다"


def test_a_refused_placement_does_not_take_the_proxy_down_with_it(catalog):
    """자리와 모양은 **다른 축**이다. 한쪽의 결손이 다른 쪽을 지우지 않는다(AI-C-05)."""
    resolution = _resolver(catalog).resolve(
        "obj-1", KindClaim("platform.uav", source="est", observed_at=1.0, confidence=0.7),
        placement=unknown_placement(frame_id="ZONE-A", reason=REFUSE_POSITION_UNKNOWN))

    assert resolution.state is ProxyState.RESOLVED
    assert resolution.proxy_id == "uav-quadrotor"
    assert resolution.placement.available is False
    assert resolution.placement.refused_because == REFUSE_POSITION_UNKNOWN
