"""implements: AI-S-06, AI-C-08, AI-C-02, AI-C-15
관련: AI-S-04, AI-S-08, AI-C-05, AI-B-12, AI-C-01
covers: (a) 클래스가 저장 자산에 **단계와 함께** 묶인다(정확 → 그룹 → 없음+사유),
        (b) 객체가 움직이는 동안 묶음이 유지되고 맵이 **같은 자산 하나를 옮긴다**,
        (c) 다시 묶기는 덮어쓰기가 아니라 회차와 자취로 남는다,
        (d) 열린 어휘의 모르는 라벨이 틀린 클래스로 밀려 들어가지 않는다,
        (e) 픽셀이 아니라 **참조**만 나간다, 좌표는 프레임을 들고 다닌다,
        (f) 선언 크기가 실측으로 위장하지 않는다,
        (g) 카탈로그는 데이터이고, 없는 것이 정상이다,
        (h) 묶음 산출의 모든 이름이 공통 데이터 사전에 있다,
        (i) 콘솔의 구역 응답이 실제 탐지에서 그 묶음을 낸다

카탈로그 시험은 **공개 트리의 실제 선언**(config/object_assets.example.json)으로 돌린다
— 예시 파일과 코드가 갈라지면 둘 중 하나가 거짓인데, 시험이 임시 파일만 보면 그 거짓이
배치에서 드러난다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
CONSOLE_DIR = PACKAGE_DIR / "tools" / "fms_console"
if str(PACKAGE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR.parent))

from mission_runtime.contracts import data_dictionary as dd  # noqa: E402
from mission_runtime.perception.object_appearance import (  # noqa: E402
    ASSET_KIND_MODEL,
    ProxyCatalog,
    ProxyCatalogError,
    ProxyResolver,
    ProxyState,
    local_placement,
    unknown_placement,
)
from mission_runtime.perception import object_asset_binding as oab  # noqa: E402
from mission_runtime.perception.object_asset_binding import (  # noqa: E402
    GROUP_KEYS,
    GROUP_VOCABULARY,
    MATCH_EXACT_CLASS,
    MATCH_GROUP_FALLBACK,
    REASON_CLASS_NOT_ESTABLISHED,
    REASON_EVERY_ASSET_UNFIT,
    REASON_EXACT_CLASS_ASSET,
    REASON_GROUP_FALLBACK_ASSET,
)
from mission_runtime.perception.object_record import (  # noqa: E402
    UNKNOWN_CLASS,
    Evidence,
    ObjectRecord,
    ProgressiveRecordBuilder,
)

ASSET_CATALOG = PACKAGE_DIR / "config" / "object_assets.example.json"
MODEL_CATALOG = PACKAGE_DIR / "config" / "object_models.example.json"

FRAME = "zone:N4-1F-W"


# ---------------------------------------------------------------------------
# 재료
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def catalog() -> ProxyCatalog:
    """실제 선언 둘을 겹친 카탈로그. 고르는 규칙은 하나여야 한다."""
    return oab.load_catalogs(MODEL_CATALOG, ASSET_CATALOG)


def _binder(catalog: ProxyCatalog, **kwargs) -> oab.AssetBinder:
    """자산 뿌리를 주지 않는다 — 파일 존재 확인은 전용 시험에서만 켠다."""
    return oab.AssetBinder(resolver=ProxyResolver(catalog, **kwargs))


def _claim(label, *, at=0.0, confidence=0.8):
    return oab.claim_for_class(label, source="test_detector", observed_at=at,
                               confidence=confidence)


def _at(x, y):
    return local_placement((x, y), frame_id=FRAME)


# ---------------------------------------------------------------------------
# (g) 카탈로그는 데이터다
# ---------------------------------------------------------------------------


def test_the_example_catalog_declares_an_asset_for_every_group(catalog):
    """그룹 대역이 하나라도 비면 그 그룹의 객체는 화면에서 모양을 못 얻는다. 어느
    그룹이 비었는지는 **파일을 보고** 알 수 있어야 한다."""
    missing = [group for group in GROUP_VOCABULARY if not catalog.for_kind(group)]

    assert not missing, f"그룹 대역이 없는 그룹: {missing}"


def test_every_declared_asset_names_its_origin_and_license(catalog):
    """모르는 라이선스는 **적어야** 한다 — 빈 칸은 "확인했고 제약이 없다" 와 구분되지
    않는다(config/label_sources.example.json 과 같은 규약)."""
    for asset in catalog.proxies:
        assert asset.origin, asset.proxy_id
        assert asset.license, asset.proxy_id
        if not asset.license_known:
            assert not asset.redistributable, asset.proxy_id


def test_group_assets_do_not_claim_a_real_world_size(catalog):
    """그룹은 같은 토큰 안에서 실물 크기가 전혀 다르다. 크기를 적으면 실측과의 비교가
    거짓으로 '맞다' 고 나온다 — 미측정은 0 도 불일치도 아니다(AI-B-01)."""
    for group in GROUP_VOCABULARY:
        for asset in catalog.for_kind(group):
            assert asset.extent_m is None, asset.proxy_id


def test_a_missing_catalog_file_is_a_normal_deployment(tmp_path):
    """카탈로그를 배포하지 않은 노드가 기동조차 못 하면 선택 기능 하나의 결손이
    프로세스 생사가 된다 — AI-C-05 가 금지한 모양이다."""
    binder = oab.binder_from_catalogs(tmp_path / "nope.json", asset_root=None)
    binding = binder.bind("obj-1", _claim("chair"), placement=_at(1.0, 2.0),
                          group="HARD_OBSTACLE")

    assert binding.state is ProxyState.ABSENT
    assert binding.reason == oab.REASON_NO_ASSET_CATALOG
    # 자리는 그대로 나간다. 모양이 없다고 객체를 지우지 않는다.
    assert binding.placement.value == (1.0, 2.0)


def test_two_catalogs_declaring_the_same_asset_id_are_refused(tmp_path):
    """같은 id 가 두 파일에 있으면 어느 선언이 이겼는지 파일만 보고 알 수 없다 —
    조용히 덮지 않고 사유와 함께 거절한다(AI-C-18)."""
    entry = {
        "proxy_id": "dup", "stands_in_for": ["thing"], "asset_kind": ASSET_KIND_MODEL,
        "asset_ref": "object_proxies/t/a.glb", "origin": "시험", "license": "CC0-1.0",
    }
    raw = {"$asset_kinds": {ASSET_KIND_MODEL: "3D"}, "proxies": [entry]}
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    for path in (first, second):
        path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ProxyCatalogError) as error:
        oab.load_catalogs(first, second)

    assert "duplicate_proxy_id:dup" in str(error.value)


# ---------------------------------------------------------------------------
# (a) 단계가 있는 매칭 — 정확 → 그룹 → 없음(사유)
# ---------------------------------------------------------------------------


def test_a_catalogued_class_binds_to_its_own_asset(catalog):
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("chair"), placement=_at(3.0, 4.0),
                          group="HARD_OBSTACLE")

    assert binding.bound
    assert binding.match_tier == MATCH_EXACT_CLASS
    assert binding.match_key == "chair"
    assert binding.reason == REASON_EXACT_CLASS_ASSET
    assert binding.proxy_id == "class-chair"


def test_a_class_outside_the_catalogue_falls_back_to_its_group(catalog):
    """탐지기 어휘는 열려 있다. 카탈로그에 없는 이름이 들어오는 것은 **정상**이고,
    그때 객체를 지우지 않고 그룹 대역으로 세운다."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("fire extinguisher cabinet"),
                          placement=_at(3.0, 4.0), group="HARD_OBSTACLE")

    assert binding.bound
    assert binding.match_tier == MATCH_GROUP_FALLBACK
    assert binding.match_key == "HARD_OBSTACLE"
    assert binding.reason == REASON_GROUP_FALLBACK_ASSET
    assert binding.proxy_id == "group-hard-obstacle"
    # 클래스 이름은 **그대로** 남는다. 그룹으로 그렸다고 클래스를 그룹 이름으로
    # 바꿔 적으면 탐지기가 실제로 무엇이라고 했는지가 사라진다.
    assert binding.semantic_class == "fire extinguisher cabinet"


def test_the_tier_says_which_of_the_two_shapes_an_operator_is_looking_at(catalog):
    """"실제 의자 모델" 과 "그냥 단단한 장애물 상자" 는 화면에서 같은 확답으로 보여서는
    안 된다. 그 구분을 담는 칸은 단계 하나뿐이다."""
    binder = _binder(catalog)

    exact = binder.bind("obj-1", _claim("chair"), placement=_at(1.0, 1.0),
                        group="HARD_OBSTACLE")
    fallback = binder.bind("obj-2", _claim("unlabelled thing"),
                           placement=_at(2.0, 2.0), group="HARD_OBSTACLE")

    assert exact.match_tier != fallback.match_tier
    assert exact.proxy_id != fallback.proxy_id


def test_an_exact_asset_wins_even_when_the_group_asset_has_a_better_priority(tmp_path):
    """단계 판정을 우선순위로 하지 않는다. 그룹 대역에 높은 우선순위를 적은 사람이
    정확 묶음을 조용히 이기면, 카탈로그 한 줄이 "정확한 것이 먼저" 를 무너뜨린다."""
    raw = {
        "$asset_kinds": {ASSET_KIND_MODEL: "3D"},
        "proxies": [
            {"proxy_id": "exact", "stands_in_for": ["chair"],
             "asset_kind": ASSET_KIND_MODEL, "asset_ref": "object_proxies/a.glb",
             "origin": "시험", "license": "CC0-1.0", "priority": 99},
            {"proxy_id": "group", "stands_in_for": ["HARD_OBSTACLE"],
             "asset_kind": ASSET_KIND_MODEL, "asset_ref": "object_proxies/b.glb",
             "origin": "시험", "license": "CC0-1.0", "priority": 1},
        ],
    }
    path = tmp_path / "assets.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    binder = oab.binder_from_catalogs(path, asset_root=None)

    binding = binder.bind("obj-1", _claim("chair"), placement=_at(0.0, 0.0),
                          group="HARD_OBSTACLE")

    assert binding.proxy_id == "exact"
    assert binding.match_tier == MATCH_EXACT_CLASS


def test_an_unresolved_class_does_not_reach_for_the_group_asset(catalog):
    """클래스가 안 가려졌으면 그룹도 모르는 것이다. 그룹이 주어졌다고 모양을 세우면
    근거 없는 확답이 화면에 선다(AI-S-04)."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim(None), placement=_at(3.0, 4.0),
                          group="AGENT")

    assert binding.state is ProxyState.ABSENT
    assert binding.reason == REASON_CLASS_NOT_ESTABLISHED
    assert binding.match_tier is None
    assert binding.proxy_id is None
    assert binding.placement.value == (3.0, 4.0), "자리는 그대로 나간다"


def test_unknown_is_not_a_class(catalog):
    """`unknown` 은 클래스 이름이 아니라 "모른다" 다. 그 글자로 자산을 찾으면 언젠가
    `unknown` 이라는 이름의 자산이 생기고, 그때부터 모름이 모양을 갖는다."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim(UNKNOWN_CLASS), placement=_at(1.0, 1.0),
                          group="UNKNOWN_OBSTACLE")

    assert binding.reason == REASON_CLASS_NOT_ESTABLISHED
    assert binding.semantic_class is None


def test_a_class_with_no_asset_and_no_group_says_which_of_the_two_is_missing(catalog):
    """"분류기를 붙이면 풀린다" 와 "자산을 더해야 풀린다" 는 다른 사실이다. 한 사유로
    합치면 운영자가 엉뚱한 쪽을 고친다."""
    binder = _binder(catalog)

    no_group = binder.bind("obj-1", _claim("zebra"), placement=_at(1.0, 1.0))
    with_group = binder.bind("obj-2", _claim("zebra"), placement=_at(1.0, 1.0),
                             group="NOT_A_CATALOGUED_GROUP")

    assert no_group.reason == oab.REASON_UNMAPPED_CLASS_NO_GROUP
    assert with_group.reason == oab.REASON_NO_ASSET_FOR_CLASS_OR_GROUP
    assert not no_group.bound and not with_group.bound


def test_an_unknown_group_token_is_not_a_crash(catalog):
    """그룹 어휘는 열려 있다(분류는 다른 모듈이 소유한다). 모르는 토큰은 거절이 아니라
    "그 그룹의 대역이 없다" 로 끝난다."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("something"), placement=_at(0.0, 0.0),
                          group="SOMETHING_ELSE")

    assert binding.state is ProxyState.ABSENT
    assert binding.object_group == "SOMETHING_ELSE"


def test_a_catalogued_asset_whose_file_is_missing_is_not_the_same_as_no_asset(tmp_path):
    """"그런 종류가 없다" 와 "자산은 정해졌는데 파일이 없다" 는 다른 사실이다 — 합치면
    자산을 더하라는 지시와 파일을 깔라는 지시가 한 빈칸이 된다."""
    raw = {
        "$asset_kinds": {ASSET_KIND_MODEL: "3D"},
        "proxies": [{"proxy_id": "exact", "stands_in_for": ["chair"],
                     "asset_kind": ASSET_KIND_MODEL,
                     "asset_ref": "object_proxies/missing.glb",
                     "origin": "시험", "license": "CC0-1.0"}],
    }
    path = tmp_path / "assets.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    binder = oab.binder_from_catalogs(path, asset_root=tmp_path,
                                      require_asset_file=True)

    binding = binder.bind("obj-1", _claim("chair"), placement=_at(0.0, 0.0))

    assert binding.state is ProxyState.ABSENT
    assert binding.reason == REASON_EVERY_ASSET_UNFIT
    assert binding.unfit == {"exact": "asset_file_missing"}


def test_an_asset_file_that_cannot_be_checked_is_not_reported_as_missing(catalog):
    """자산 뿌리가 없는 노드에서 "확인하지 못했다" 를 '없다' 로 적으면 공개 트리만 받은
    배치에서 모든 모양이 사라진다. 모름은 None 으로 남는다."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("chair"), placement=_at(0.0, 0.0))

    assert binding.bound
    assert binding.asset_present is None


# ---------------------------------------------------------------------------
# (b) 묶음은 객체가 움직이는 동안 유지된다 — "이동 되도록"
# ---------------------------------------------------------------------------


def test_a_moving_object_keeps_one_asset_instead_of_being_rebuilt(catalog):
    """맵은 **같은 자산 하나를 옮긴다.** 틱마다 다시 고르면 같은 우선순위의 두 자산
    사이에서 모양이 깜빡이고, 받는 쪽은 "새 객체가 생겼다" 와 구별할 수 없다."""
    binder = _binder(catalog)

    first = binder.bind("obj-1", _claim("chair", at=1.0), placement=_at(1.0, 1.0),
                        group="HARD_OBSTACLE", at=1.0)
    for step, (x, y) in enumerate(((2.0, 1.0), (3.0, 1.5), (4.0, 2.0)), start=2):
        moved = binder.bind("obj-1", _claim("chair", at=float(step)),
                            placement=_at(x, y), group="HARD_OBSTACLE",
                            at=float(step))

    assert moved.proxy_id == first.proxy_id
    assert moved.binding_index == 1, "자리가 바뀌는 것은 새 회차가 아니다"
    assert moved.bound_at == first.bound_at, "묶음이 선 시각은 움직여도 그대로다"
    assert moved.trail == ()
    assert moved.placement.value == (4.0, 2.0), "자리는 따라간다"


def test_the_binding_is_keyed_on_the_persistent_object_not_the_frame(catalog):
    """두 객체가 같은 클래스여도 묶음은 각자의 것이다. 클래스에 걸면 한 객체의 가설
    변화가 다른 객체의 모양을 바꾼다."""
    binder = _binder(catalog)

    binder.bind("obj-1", _claim("chair"), placement=_at(1.0, 1.0))
    binder.bind("obj-2", _claim("chair"), placement=_at(9.0, 9.0))

    assert binder.binding("obj-1").placement.value == (1.0, 1.0)
    assert binder.binding("obj-2").placement.value == (9.0, 9.0)
    assert len(binder.placements()) == 2


def test_an_object_record_can_be_bound_without_restating_its_fields(catalog):
    """지속 객체 모델을 다시 만들지 않는다 — `ObjectRecord` 가 이미 그것이다."""
    builder = ProgressiveRecordBuilder()
    builder.ingest("obj-1", Evidence(
        evidence_id="e1", frame_ref="cam/1", source_group="cam-a",
        observed_at=1.0, available_at=1.0, kind="region", confidence=0.9,
        region=(0.2, 0.2, 0.4, 0.4), label="chair", frame_id=FRAME))
    record = builder.records["obj-1"]
    binder = _binder(catalog)

    binding = binder.bind_record(record, group="HARD_OBSTACLE")

    assert binding.object_id == "obj-1"
    assert binding.semantic_class == "chair"
    assert binding.match_tier == MATCH_EXACT_CLASS
    # 자리는 레코드 기하의 중심이고 **레코드의 프레임**을 그대로 들고 간다(AI-C-02).
    assert binding.placement.value == pytest.approx((0.3, 0.3))
    assert binding.placement.coordinate_frame == FRAME


def test_a_record_without_geometry_does_not_get_an_invented_position(catalog):
    """0 좌표는 원점에 물건을 세운다. 모르는 자리는 모른다고 적는다."""
    binder = _binder(catalog)
    record = ObjectRecord(object_id="obj-1", semantic_class="chair", frame_id=FRAME)

    binding = binder.bind_record(record)

    assert binding.placement.value is None
    assert binding.placement.refused_because == "position_not_observed"
    assert binding.bound, "자리를 몰라도 무엇으로 그릴지는 정해진다"


# ---------------------------------------------------------------------------
# (c) 다시 묶기는 사건이다 — 덮어쓰기가 아니다
# ---------------------------------------------------------------------------


def test_a_changed_class_retires_the_previous_binding_into_a_trail(catalog):
    """"40 프레임 동안 가방이었다가 배낭이 됐다" 를 운영자가 읽을 수 있어야 한다.
    덮어쓰면 화면이 아까와 다른 모양을 그리는 이유를 되짚을 수 없다(AI-S-06)."""
    binder = _binder(catalog)

    binder.bind("obj-1", _claim("chair", at=1.0), placement=_at(1.0, 1.0),
                group="HARD_OBSTACLE", at=1.0)
    rebound = binder.bind("obj-1", _claim("traffic_cone", at=5.0),
                          placement=_at(1.0, 1.0), group="THIN_OBSTACLE", at=5.0)

    assert rebound.proxy_id == "class-traffic-cone"
    assert rebound.binding_index == 2
    assert rebound.bound_at == 5.0
    assert len(rebound.trail) == 1
    retired = rebound.trail[0]
    assert retired.binding_index == 1
    assert retired.proxy_id == "class-chair"
    assert retired.semantic_class == "chair"
    assert retired.bound_at == 1.0 and retired.retired_at == 5.0
    assert retired.supersede_reason == "estimated_kind_changed"


def test_a_class_change_that_does_not_change_the_asset_is_not_a_rebinding(catalog):
    """회차를 올리면 "모양이 바뀌었다" 가 참이 된다. 두 가설이 같은 그룹 대역으로
    선다면 **맵이 세운 모양은 바뀌지 않았다** — 클래스 가설의 이력은 객체 레코드의
    것이고 묶음의 자취가 아니다."""
    binder = _binder(catalog)

    binder.bind("obj-1", _claim("bag", at=1.0), placement=_at(1.0, 1.0),
                group="SOFT_PUSHABLE", at=1.0)
    later = binder.bind("obj-1", _claim("backpack", at=2.0), placement=_at(1.0, 1.0),
                        group="SOFT_PUSHABLE", at=2.0)

    assert later.proxy_id == "group-soft-pushable"
    assert later.binding_index == 1
    assert later.trail == ()
    assert later.semantic_class == "backpack", "클래스는 그대로 갱신된다"


def test_a_group_fallback_replaced_by_the_exact_asset_says_so(catalog):
    """그룹 대역이 정확 모델로 올라간 것은 "같은 종류의 다른 자산" 과 다른 사건이다 —
    카탈로그가 자란 것이고, 운영자에게는 "드디어 제대로 그린다" 는 소식이다."""
    binder = _binder(catalog)

    binder.bind("obj-1", _claim("wooden stool", at=1.0), placement=_at(1.0, 1.0),
                group="HARD_OBSTACLE", at=1.0)
    promoted = binder.bind("obj-1", _claim("chair", at=2.0), placement=_at(1.0, 1.0),
                           group="HARD_OBSTACLE", at=2.0)

    assert promoted.match_tier == MATCH_EXACT_CLASS
    assert promoted.binding_index == 2
    assert promoted.trail[0].supersede_reason == oab.REBIND_EXACT_REPLACED_GROUP
    assert promoted.trail[0].match_tier == MATCH_GROUP_FALLBACK


def test_losing_the_exact_asset_falls_back_and_records_the_descent(catalog):
    binder = _binder(catalog)

    binder.bind("obj-1", _claim("chair", at=1.0), placement=_at(1.0, 1.0),
                group="HARD_OBSTACLE", at=1.0)
    down = binder.bind("obj-1", _claim("some cabinet", at=2.0),
                       placement=_at(1.0, 1.0), group="HARD_OBSTACLE", at=2.0)

    assert down.match_tier == MATCH_GROUP_FALLBACK
    assert down.trail[0].supersede_reason == oab.REBIND_GROUP_REPLACED_EXACT


def test_a_binding_lost_entirely_is_recorded_as_a_loss_not_as_nothing(catalog):
    binder = _binder(catalog)

    binder.bind("obj-1", _claim("chair", at=1.0), placement=_at(1.0, 1.0), at=1.0)
    lost = binder.bind("obj-1", _claim("zebra", at=2.0), placement=_at(1.0, 1.0),
                       at=2.0)

    assert not lost.bound
    assert lost.binding_index == 2
    assert lost.trail[0].supersede_reason == "stand_in_no_longer_available"
    assert lost.rebound


def test_the_trail_keeps_every_round_in_order(catalog):
    binder = _binder(catalog)

    binder.bind("obj-1", _claim("chair", at=1.0), placement=_at(0.0, 0.0), at=1.0)
    binder.bind("obj-1", _claim("traffic_cone", at=2.0), placement=_at(0.0, 0.0),
                at=2.0)
    third = binder.bind("obj-1", _claim("wet_floor", at=3.0), placement=_at(0.0, 0.0),
                        at=3.0)

    assert [entry.binding_index for entry in third.trail] == [1, 2]
    assert [entry.proxy_id for entry in third.trail] == ["class-chair",
                                                         "class-traffic-cone"]
    assert third.binding_index == 3


# ---------------------------------------------------------------------------
# (e) 참조만 나간다 · 좌표는 프레임을 들고 다닌다
# ---------------------------------------------------------------------------


def test_the_binding_carries_an_asset_reference_and_never_the_bytes(catalog):
    """AI-C-08: 영상·메시 픽셀은 상태 계약으로 나가지 않는다. 나가는 것은 참조 하나고
    뷰어가 그것으로 미디어 경로에서 받는다."""
    binder = _binder(catalog)

    payload = binder.bind("obj-1", _claim("chair"), placement=_at(1.0, 2.0)).as_dict()

    assert payload[dd.ASSET_REF] == "object_proxies/indoor/chair_office.glb"
    assert payload[dd.ASSET_KIND] == ASSET_KIND_MODEL
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("base64", "data:image", "vertices", "pixels"):
        assert forbidden not in serialized


def test_no_binding_field_name_carries_a_presentation_decision(catalog):
    """계약이 색·픽셀·폰트를 말하지 않는다는 성질은 이 산출에도 걸린다
    (`tests/test_view_contract.py` 와 같은 낱말 검사)."""
    binder = _binder(catalog)
    payload = binder.bind("obj-1", _claim("chair"), placement=_at(1.0, 2.0)).as_dict()

    forbidden = {"color", "colour", "fill", "font", "icon", "shape", "mesh",
                 "material", "texture", "opacity", "style", "marker"}

    def names(node):
        out = set()
        if isinstance(node, dict):
            for key, value in node.items():
                out.add(str(key))
                out |= names(value)
        elif isinstance(node, list):
            for item in node:
                out |= names(item)
        return out

    offenders = {name for name in names(payload)
                 for word in name.lower().split("_") if word in forbidden}
    assert not offenders, offenders


def test_a_placement_keeps_the_frame_it_came_from(catalog):
    binder = _binder(catalog)

    payload = binder.bind("obj-1", _claim("chair"), placement=_at(1.0, 2.0)).as_dict()

    assert payload["placement"][dd.COORDINATE_FRAME] == FRAME
    assert payload["placement"][dd.PROXY_POSITION] == [1.0, 2.0]


def test_a_global_position_is_refused_instead_of_being_mixed_in(catalog):
    """전역 변환은 검증된 site datum 을 가진 계층의 일이다(AI-C-02). 로컬 값과 전역
    값을 같은 칸에 담는 것보다 비는 편이 낫다."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("chair"),
                          placement=local_placement((37.5, 127.0), frame_id="GLOBAL"))

    assert binding.placement.value is None
    assert binding.placement.refused_because == "global_value_not_owned_here"


def test_an_unknown_placement_is_not_the_origin(catalog):
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("chair"),
                          placement=unknown_placement(frame_id=FRAME))

    assert binding.placement.value is None
    assert binding.placement.as_dict()[dd.PROXY_POSITION] is None


# ---------------------------------------------------------------------------
# (f) 선언 크기는 실측으로 위장하지 않는다
# ---------------------------------------------------------------------------


def test_a_declared_extent_never_sits_in_the_measured_cell(catalog):
    """카탈로그의 크기는 **사전정보**이고 이 객체를 잰 값이 아니다(AI-S-08). 한 칸에
    담으면 선언이 관측으로 보이고, 그 관측은 아무도 재지 않은 것이다."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("chair"), placement=_at(0.0, 0.0))
    fit = binding.fit.as_dict()

    assert fit[dd.PROXY_EXTENT_M] == 0.9, "선언된 값"
    assert fit[dd.MEASURED_EXTENT_M] is None, "아무도 재지 않았다"
    assert fit[dd.SIZE_FIT_STATE] == "unmeasured"
    assert fit[dd.UNMEASURED_SIDE] == "measured_extent"


def test_a_measured_extent_that_disagrees_is_reported_not_scaled_away(catalog):
    """맞춰 늘리면 화면은 그럴듯해지고 그 그럴듯함이 다음 판단의 전제가 된다."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("chair"), placement=_at(0.0, 0.0),
                          measured_extent_m=4.0)

    assert binding.fit.state == "mismatch"
    assert binding.fit.ratio == pytest.approx(4.0 / 0.9)
    assert binding.bound, "어긋남은 묶음을 취소하지 않는다 — 사실로 보고된다"


def test_a_group_fallback_has_no_declared_size_to_compare(catalog):
    """그룹 대역은 크기를 말하지 않으므로 실측과의 비교는 **모름**이다. 불일치가
    아니고 0 도 아니다."""
    binder = _binder(catalog)

    binding = binder.bind("obj-1", _claim("unlabelled"), placement=_at(0.0, 0.0),
                          group="HARD_OBSTACLE", measured_extent_m=1.2)

    assert binding.fit.state == "unmeasured"
    assert binding.fit.unmeasured_side == "declared_extent"


def test_moving_an_object_recomputes_the_size_comparison_without_rebinding(catalog):
    binder = _binder(catalog)

    binder.bind("obj-1", _claim("chair", at=1.0), placement=_at(0.0, 0.0), at=1.0)
    moved = binder.bind("obj-1", _claim("chair", at=2.0), placement=_at(1.0, 0.0),
                        measured_extent_m=0.95, at=2.0)

    assert moved.binding_index == 1
    assert moved.fit.state == "match"
    assert moved.fit.measured_extent_m == 0.95


# ---------------------------------------------------------------------------
# (h) 이름은 공통 데이터 사전의 것이다 (AI-C-01)
# ---------------------------------------------------------------------------


def test_every_emitted_name_is_registered_in_the_data_dictionary(catalog):
    binder = _binder(catalog)
    binder.bind("obj-1", _claim("chair", at=1.0), placement=_at(1.0, 1.0), at=1.0)
    payload = binder.bind("obj-1", _claim("traffic_cone", at=2.0),
                          placement=_at(1.0, 1.0), measured_extent_m=0.7,
                          at=2.0).as_dict()

    leaves = {key: value for key, value in payload.items() if key not in GROUP_KEYS}
    assert dd.unknown_fields(leaves) == ()
    for group in ("grounds", "placement", "size_fit"):
        assert dd.unknown_fields(payload[group]) == (), group
    assert payload["trail"], "이 묶음은 한 번 다시 묶였다"
    for entry in payload["trail"]:
        assert dd.unknown_fields(entry) == ()


def test_the_reason_and_tier_tokens_are_the_published_vocabulary(catalog):
    """화면이 사유별로 분기하려면 어휘가 한 곳에 있어야 한다."""
    assert set(dd.ASSET_MATCH_TIERS) == {MATCH_EXACT_CLASS, MATCH_GROUP_FALLBACK}
    for token in (REASON_EXACT_CLASS_ASSET, REASON_GROUP_FALLBACK_ASSET,
                  REASON_CLASS_NOT_ESTABLISHED, oab.REASON_NO_ASSET_CATALOG,
                  oab.REASON_UNMAPPED_CLASS_NO_GROUP,
                  oab.REASON_NO_ASSET_FOR_CLASS_OR_GROUP, REASON_EVERY_ASSET_UNFIT):
        assert token in dd.ASSET_BINDING_REASONS, token
    for token in (oab.REBIND_EXACT_REPLACED_GROUP, oab.REBIND_GROUP_REPLACED_EXACT):
        assert token in dd.PROXY_SUPERSEDE_REASONS, token


def test_unbound_objects_stay_in_the_emitted_list(catalog):
    """자리는 아는데 모양이 없는 것은 정상 상태다. 목록에서 빼면 "거기 아무것도 없다"
    는 거짓말이 된다(AI-C-05)."""
    binder = _binder(catalog)
    binder.bind("obj-1", _claim("chair"), placement=_at(1.0, 1.0))
    binder.bind("obj-2", _claim("zebra"), placement=_at(2.0, 2.0))

    rows = binder.placements()

    assert [row[dd.OBJECT_ID] for row in rows] == ["obj-1", "obj-2"]
    assert rows[1][dd.PROXY_STATE] == "ABSENT"
    assert rows[1][dd.PROXY_ID] is None
    assert rows[1]["placement"][dd.PROXY_POSITION] == [2.0, 2.0]


def test_classes_without_an_exact_asset_are_listed_for_the_operator(catalog):
    """"왜 전부 상자로 보이나" 에 답이 되는 자리."""
    missing = oab.classes_without_asset(catalog, ["chair", "zebra", "traffic_cone"])

    assert missing == ("zebra",)


# ---------------------------------------------------------------------------
# (i) 콘솔의 구역 응답이 실제 탐지에서 그 묶음을 낸다
# ---------------------------------------------------------------------------

ZONE = "N4-1F-W"


def _console():
    """`tools/fms_console/serve.py` 를 **경로로** 싣는다(`tools/status_ui/serve.py`
    와 이름이 겹친다)."""
    name = "fms_console_serve_under_asset_binding_test"
    if name in sys.modules:
        return sys.modules[name]
    for candidate in (CONSOLE_DIR, PACKAGE_DIR / "tools" / "status_ui"):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    spec = importlib.util.spec_from_file_location(name, CONSOLE_DIR / "serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def console():
    return _console()


@pytest.fixture()
def service(console, tmp_path):
    return console.build_service(
        ui_config=PACKAGE_DIR / "config" / "status_ui.fms.example.json",
        zone_profile=PACKAGE_DIR / "profiles" / "domains.example.json",
        goal_kinds=PACKAGE_DIR / "profiles" / "goal_kinds.example.json",
        with_fleet=True,
        overlay_path=tmp_path / "edits.json",
    )


def _caller(console):
    from accounts import Caller  # noqa: PLC0415

    return Caller.for_role("admin")


def test_a_zone_with_no_detection_yet_has_an_empty_placement_list(service, console):
    """콘솔이 지어낸 값은 관측이 아니다. 빈 목록이 정상 상태다(AI-C-05)."""
    detail = service.zone(ZONE)

    assert detail["object_placements"] == []


def test_a_reported_detection_becomes_an_asset_placement_on_the_map(service, console):
    """요구의 끝: 인식한 객체가 저장 자산과 묶여 맵이 읽는 자리로 나간다."""
    service.ingest_detection(caller=_caller(console), body={
        "detection_id": "d1", "device_id": "pi6", "track_local_id": 1,
        "frame_ref": "pi6/f1", "bbox": [0.48, 0.4, 0.52, 0.6],
        "label": "person", "confidence": 0.8, "range_m": 6.0,
    })

    rows = service.zone(ZONE)["object_placements"]

    assert len(rows) == 1
    row = rows[0]
    assert row[dd.SEMANTIC_CLASS] == "person"
    assert row[dd.ASSET_MATCH_TIER] == MATCH_EXACT_CLASS
    assert row[dd.PROXY_ID] == "person-standing"
    assert row[dd.ASSET_REF], "자산 참조가 나간다 — 픽셀은 나가지 않는다"
    assert row["placement"][dd.COORDINATE_FRAME] == f"zone:{ZONE}"
    assert row["placement"][dd.PROXY_POSITION] is not None
    # 그룹은 `perception/obstacle_taxonomy.py` 가 정하고 융합 레코드가 들고 온다.
    # 콘솔이 다시 분류하지 않으므로 이 값은 **어휘 선언 그대로**다.
    assert row[dd.OBJECT_GROUP] == "AGENT"


def test_a_class_outside_the_declared_vocabulary_shows_no_group_rather_than_a_guess(
        service, console):
    """**미등록 이름을 비슷한 그룹으로 끌어오지 않는다**(AI-S-04).

    제로샷 탐지기는 아무 문자열이나 내므로 이것이 상시 경로다. 조용히 그룹이
    붙으면 그 객체는 미확인 경로에서 사라지고 엉뚱한 자산으로 그려진다.
    """
    service.ingest_detection(caller=_caller(console), body={
        "detection_id": "d1", "device_id": "pi6", "track_local_id": 1,
        "frame_ref": "pi6/f1", "bbox": [0.48, 0.4, 0.52, 0.6],
        "label": "고양이 인형", "confidence": 0.8, "range_m": 6.0,
    })

    row, = service.zone(ZONE)["object_placements"]

    assert row[dd.SEMANTIC_CLASS] == "고양이 인형"
    assert row[dd.OBJECT_GROUP] == "UNKNOWN_OBSTACLE", (
        "모른다는 것이 값으로 나가야 한다 — 빈 칸이 아니다")
    assert row[dd.ASSET_MATCH_TIER] != MATCH_EXACT_CLASS


def test_the_same_object_moving_keeps_one_asset_in_the_zone_response(service, console):
    """맵이 같은 자산을 **옮긴다.** 매 요청에 묶음기를 새로 만들면 회차가 1 로
    돌아가고 화면은 모양을 다시 세운다."""
    caller = _caller(console)
    for index, range_m in enumerate((6.0, 7.0, 8.0), start=1):
        service.ingest_detection(caller=caller, body={
            "detection_id": f"d{index}", "device_id": "pi6", "track_local_id": 1,
            "frame_ref": f"pi6/f{index}", "bbox": [0.48, 0.4, 0.52, 0.6],
            "label": "person", "confidence": 0.8, "range_m": range_m,
        })

    rows = service.zone(ZONE)["object_placements"]

    assert len(rows) == 1, "한 물리 객체는 한 자리다"
    assert rows[0][dd.BINDING_INDEX] == 1, "움직인 것은 새 묶음이 아니다"
    assert rows[0]["trail"] == []


def test_a_robot_with_only_a_declared_pose_is_not_reported_as_observed(service, console):
    """2026-11-04 수정을 고정한다. 트윈은 **선언된 자리로** 장치를 등록하므로
    `placement_of()` 는 관측이 없어도 자세를 돌려준다. 그것으로 `at_origin` 을
    "장치가 알린 자리" 로 바꾸면 아무도 본 적 없는 자리가 관측이 되고, 그 값은
    공표된 닫힌 어휘(`declared`·`operator_edit`) 밖이어서 바깥 뷰어의 검증을 깬다.

    이 시험이 없어서 그 분기가 **깨어날 때까지** 아무도 보지 못했다: 구역 응답이
    트윈을 만들기 시작한 순간(객체 묶음이 그것을 쓴다) 처음 드러났다.
    """
    # 묶음 산출이 트윈을 만든다 — 그 자체가 이 분기를 깨우는 조건이었다.
    service.object_placements(ZONE)

    detail = service.zone(ZONE)
    robots = detail["robots"]
    assert robots, "이 구역에는 선언된 로봇이 있다"
    for robot in robots:
        assert robot["at_origin"] in ("declared", "operator_edit"), robot["node_id"]
        # 관측이 없으면 그 칸 자체가 없다. null 이나 "declared" 로 채우면 "관측이
        # 있었고 선언이 그것을 만들었다" 로 읽힌다(§3.2).
        assert "position_source" not in robot, robot["node_id"]


def test_a_reported_pose_moves_the_robot_without_touching_its_declaration(service, console):
    """관측이 자리를 정하면 `at` 이 바뀌고 **무엇이 그 값을 만들었는지**가 따로 온다.
    선언의 출처(`at_origin`)는 그대로다 — 그 선언이 사라진 것은 아니다."""
    service.report_pose(caller=_caller(console), body={
        "device_id": "go1-onboard", "zone_id": ZONE,
        "pose": {"x": 12.0, "y": 8.0, "yaw_deg": 90.0},
        "pose_source": "reported",
    })

    robots = {r["node_id"]: r for r in service.zone(ZONE)["robots"]}
    moved = robots["go1-onboard"]

    assert moved["at"] == {"x": 12.0, "y": 8.0}
    assert moved["position_source"] == "reported"
    assert moved["at_origin"] == "declared", "선언은 관측에 덮이지 않는다"
    # 살아 있는가는 또 다른 축이고 같은 칸에 담기지 않는다.
    assert "presence" in moved and "last_seen_age_s" in moved


def test_the_zone_response_stays_read_only(service, console):
    """조회가 묶음기를 만들고 상태를 기억하지만, 그것으로 **실행 상태가 바뀌지는
    않는다**(AI-O-06). 같은 조회를 두 번 해도 같은 답이다."""
    first = service.zone(ZONE)["object_placements"]
    second = service.zone(ZONE)["object_placements"]

    assert first == second
