"""인식한 객체의 **클래스**를 저장해 둔 자산에 묶고, 객체가 움직이는 동안 그 묶음을
유지한다.

implements: AI-S-06 (이종 근거의 점진적 객체 레코드), AI-C-08 (픽셀은 상태 계약으로
            나가지 않는다), AI-C-02 (좌표계 경계), AI-C-15 (도메인은 데이터)
관련: AI-S-04 (확정 label 강제 금지), AI-S-08 (선언은 관측이 아니다), AI-C-05 (선택
      결손은 축소), AI-B-12 (재실행은 덮지 않고 회차를 남긴다), AI-C-19 (판단·권한 경계)
tests: tests/test_object_asset_binding.py

## 문제

"인식한 객체를 저장된 모델 혹은 이미지와 클래스를 매칭해 실시간으로 맵에 반영 및
이동 되도록" — 요구를 쪼개면 세 가지다.

1. **매칭**: 떨어진 클래스 이름으로 어떤 저장 자산이 그 객체를 대신할지 고른다.
2. **반영**: 그 선택을 맵이 읽는 상태 계약으로 낸다(참조만, 픽셀은 아니다).
3. **이동**: 객체가 움직이는 동안 맵이 **같은 자산 하나를 옮긴다** — 매 프레임 다시
   세우지 않는다.

3 번이 이 모듈이 상태를 들고 있는 유일한 이유다. 묶음은 **지속 객체 식별자**
(`perception/object_record.ObjectRecord.object_id`)에 걸리고, 클래스 가설이 그대로인
동안 한 번 고른 자산을 다시 고르지 않는다. 틱마다 고르면 같은 우선순위의 두 자산
사이에서 모양이 깜빡이고, 받는 쪽은 "새 객체가 생겼다" 와 구별할 수 없다.

## 이미 있는 것을 다시 만들지 않는다

자산 카탈로그·자산 참조·자리 계약·크기 비교는 `perception/object_appearance.py` 가
이미 소유한다. 이 모듈은 그것을 **쓴다** — `ProxyCatalog`(선언 로딩과 거절),
`ProxyResolver`(후보 선택·자산 존재 확인), `ProxyPlacement`(프레임 태깅),
`compare_extent`(선언 크기 대 실측 크기). 같은 일을 두 번 구현하면 두 화면이 같은
객체를 다른 모양으로 그린다.

이 모듈이 더하는 것은 셋뿐이다.

* **단계(tier) 가 있는 매칭**: 정확 클래스 → 그룹 대역 → 없음(사유). 어느 단계로
  골랐는지를 산출에 적는다 — 그래야 운영자가 "저것이 실제 의자 모델" 과 "그냥 단단한
  장애물 상자" 를 구분한다. `object_appearance` 는 태그 하나로만 찾으므로 이 구분이
  없었다.
* **묶음의 지속**: 객체 식별자에 걸린 상태. 자리만 바뀌면 자산을 다시 고르지 않는다.
* **다시 묶기는 사건이다**: 바뀐 묶음이 이전 것을 덮지 않고 회차(`binding_index`)와
  함께 자취(`trail`)에 쌓인다. AI-B-12 가 재실행에 요구한 것과 같은 규약이고, 그래서
  "40 프레임 동안 가방이었다가 배낭이 됐다" 를 뒤에서 읽을 수 있다.

## 그룹은 문자열 인자다

어떤 클래스가 어느 그룹인지는 **여기서 정하지 않는다** — 그 분류는
`perception/obstacle_taxonomy.py` 가 소유하고 이 모듈은 그 타입을 import 하지 않는다.
들어오는 것은 그룹 토큰 문자열 하나이고, 비어 있어도 된다(그때는 그룹 단계가 없고
정확 클래스만 본다). 분류기가 없는 배치에서도 이 모듈이 돌아야 하기 때문이다(AI-C-05).

## 조용히 거짓말하는 길을 막는다

* **열린 어휘를 틀린 클래스로 밀어 넣지 않는다.** 탐지기 어휘는 임의 문자열이다.
  카탈로그에 없는 이름은 그룹 대역으로 내려가거나 사유와 함께 **묶이지 않는다** —
  비슷한 이름을 집어 오면 화면이 틀린 물건을 확답처럼 보여 준다(AI-S-04).
* **묶이지 않은 것은 정상 상태다.** 자리는 그대로 나가고 모양만 없다. 목록에서 빼면
  "없다" 는 거짓말이 된다(AI-C-05).
* **선언 크기는 관측이 아니다.** 카탈로그의 `extent_m` 은 사전정보이고(AI-S-08) 실측
  크기와 **다른 칸**에 담긴다. 둘 중 하나가 미측정이면 불일치가 아니라 모름이다.
* **픽셀은 나가지 않는다.** 산출에는 자산 **참조**(id·상대 경로·종류·선언 크기)만
  있고 바이트가 없다. 뷰어가 그 참조로 미디어 경로에서 받는다(AI-C-08).
* **좌표는 프레임을 들고 다닌다.** 자리는 현장 로컬이고 전역 값은 이 칸에 담기지
  않는다(AI-C-02) — 그 거절은 `ProxyPlacement` 가 이미 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.perception.object_appearance import (
    DEFAULT_SIZE_TOLERANCE,
    REASON_EVERY_STAND_IN_UNFIT,
    REASON_KIND_NOT_ESTABLISHED,
    REASON_NO_CATALOG,
    SUPERSEDE_KIND_CHANGED,
    SUPERSEDE_OTHER_STAND_IN,
    SUPERSEDE_STAND_IN_FOUND,
    SUPERSEDE_STAND_IN_LOST,
    KindClaim,
    ProxyAsset,
    ProxyCatalog,
    ProxyCatalogError,
    ProxyPlacement,
    ProxyResolution,
    ProxyResolver,
    ProxyState,
    SizeFit,
    compare_extent,
    default_asset_root,
    local_placement,
    unknown_placement,
)
from mission_runtime.perception.object_record import UNKNOWN_CLASS, ObjectRecord

#: 묶음은 **선택 계층**이다. 클래스 가설이 하나라도 있으면 성립하고 카탈로그·자산
#: 파일·실측 크기는 전부 선택이다 — 결손은 DEGRADED 까지만 내려간다(AI-C-05).
REQUIREMENT = CapabilityRequirement(
    required=("perception.classify",),
    optional=("reference.object_asset_catalog", "media.asset_store",
              "perception.depth"),
)

#: 그룹 대역의 어휘. **값을 강제하지 않는다** — 그룹 문자열은 그대로 태그로 쓰이고,
#: 어떤 클래스가 어느 그룹인지는 `perception/obstacle_taxonomy.py` 가 소유한다. 여기
#: 적어 두는 이유는 카탈로그를 쓰는 사람이 토큰을 짐작하지 않게 하는 것뿐이고, 모르는
#: 그룹이 들어오면 거절이 아니라 "그 그룹의 대역이 없다" 로 끝난다(열린 어휘).
GROUP_VOCABULARY: tuple[str, ...] = (
    "AGENT", "VEHICLE", "THIN_OBSTACLE", "HARD_OBSTACLE",
    "GROUND_HAZARD", "SOFT_PUSHABLE", "LOW_OBSTACLE", "UNKNOWN_OBSTACLE",
)

# --- 매칭 단계 ---------------------------------------------------------------
#: 그 클래스 이름으로 카탈로그에 등록된 자산을 찾았다. "저것이 실제 의자 모델" 이다.
MATCH_EXACT_CLASS = "exact_class"
#: 클래스 이름으로는 못 찾고 **그룹** 대역으로 내려왔다. "그냥 단단한 장애물 상자" 다.
MATCH_GROUP_FALLBACK = "group_fallback"

# --- 묶음 사유 ---------------------------------------------------------------
REASON_EXACT_CLASS_ASSET = "exact_class_asset"
REASON_GROUP_FALLBACK_ASSET = "group_fallback_asset"
#: 클래스가 아직 가려지지 않았다. 묶음의 실패가 아니라 인지의 상태다(AI-S-04).
REASON_CLASS_NOT_ESTABLISHED = "class_not_established"
#: 이 배치에 카탈로그가 없다. 정상 축소다(AI-C-05).
REASON_NO_ASSET_CATALOG = "no_asset_catalog"
#: 클래스는 아는데 카탈로그에 없고 그룹도 주어지지 않았다. "그룹 대역이 없다" 와 다른
#: 사실이다 — 합치면 분류기를 붙이면 풀리는 경우와 자산을 더해야 풀리는 경우가 한
#: 빈칸이 된다.
REASON_UNMAPPED_CLASS_NO_GROUP = "unmapped_class_and_no_group_given"
#: 클래스도 그룹도 카탈로그에 없다. 자산을 한 줄 더하면 풀린다.
REASON_NO_ASSET_FOR_CLASS_OR_GROUP = "no_asset_for_class_or_group"
#: 자산은 등록되어 있는데 파일이 없다. "그런 종류가 없다" 와 다른 사실이다.
REASON_EVERY_ASSET_UNFIT = "every_catalogued_asset_unfit"

#: 묶음이 바뀐 사유 중 이 모듈이 더하는 둘. 나머지 넷은 `object_appearance` 의 것을
#: 그대로 쓴다 — 같은 뜻을 다른 토큰으로 적으면 화면이 두 어휘를 알아야 한다.
REBIND_EXACT_REPLACED_GROUP = "exact_stand_in_replaced_group_fallback"
REBIND_GROUP_REPLACED_EXACT = "group_fallback_replaced_exact_stand_in"

#: `AssetBinding.as_dict()` 가 **묶음**으로 쓰는 키. 값의 이름이 아니라 자리의 이름이라
#: 사전 항목이 아니고, 그 안의 잎 이름은 전부 사전에 있다(AI-C-01). `object_appearance`
#: 의 `GROUP_KEYS` 와 같은 규약이다.
GROUP_KEYS: tuple[str, ...] = ("grounds", "placement", "size_fit", "trail")


# ---------------------------------------------------------------------------
# 카탈로그 — 데이터이고, 여러 장을 겹쳐 쓸 수 있다
# ---------------------------------------------------------------------------


def merge_catalogs(*catalogs: ProxyCatalog) -> ProxyCatalog:
    """여러 선언 파일을 한 카탈로그로 겹친다. **같은 id 두 번은 거절한다.**

    장치 대역(`config/object_models.example.json`)과 클래스·그룹 대역
    (`config/object_assets.example.json`)은 역할이 달라 파일이 둘이지만 고르는
    규칙은 하나여야 한다. 같은 `proxy_id` 가 두 파일에 있으면 어느 선언이 이겼는지
    파일만 보고 알 수 없으므로 조용히 덮지 않고 사유와 함께 거절한다(AI-C-18).
    """
    proxies: list[ProxyAsset] = []
    kinds: dict[str, str] = {}
    seen: set[str] = set()
    missing: list[str] = []
    for catalog in catalogs:
        for asset in catalog.proxies:
            if asset.proxy_id in seen:
                raise ProxyCatalogError(f"duplicate_proxy_id:{asset.proxy_id}")
            seen.add(asset.proxy_id)
            proxies.append(asset)
        kinds.update(catalog.asset_kinds)
        if catalog.missing_reason:
            missing.append(catalog.missing_reason)
    return ProxyCatalog(
        proxies=tuple(proxies), asset_kinds=kinds,
        # 한 장이라도 실렸으면 '없음' 사유는 남기지 않는다. 전부 없을 때만 사유가 있고
        # 그때 묶음은 ABSENT(no_asset_catalog) 다.
        missing_reason="" if proxies else (missing[0] if missing else ""),
    )


def load_catalogs(*paths: str | Path) -> ProxyCatalog:
    """선언 파일들을 읽어 하나로 겹친다. **없는 파일은 오류가 아니다**(AI-C-05)."""
    return merge_catalogs(*(ProxyCatalog.load(path) for path in paths))


# ---------------------------------------------------------------------------
# 묶음 — 이전 묶음을 덮지 않는다
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BindingTrailEntry:
    """물러난 묶음 1건. 회차와 함께 남고 **지워지지 않는다**(AI-B-12 와 같은 규약)."""

    binding_index: int
    proxy_id: str | None
    semantic_class: str | None
    match_tier: str | None
    bound_at: float
    retired_at: float
    supersede_reason: str

    def as_dict(self) -> dict:
        return {
            dd.BINDING_INDEX: self.binding_index,
            dd.PROXY_ID: self.proxy_id,
            dd.SEMANTIC_CLASS: self.semantic_class,
            dd.ASSET_MATCH_TIER: self.match_tier,
            dd.BOUND_AT: self.bound_at,
            dd.RETIRED_AT: self.retired_at,
            dd.SUPERSEDE_REASON: self.supersede_reason,
        }


@dataclass(frozen=True)
class AssetBinding:
    """한 지속 객체를 **무엇으로 그릴지**와 **어디에 세울지**.

    `object_id` 는 객체 레코드 식별자이고 장치 개체가 아니다 — 이 산출에 `device_id`
    칸이 없는 것은 설계다(외형은 종류까지만 말한다: `perception/device_identity.py`).

    `asset` 은 **참조**를 들고 있고 픽셀을 들고 있지 않다(AI-C-08).
    """

    object_id: str
    state: ProxyState
    reason: str
    #: 어느 단계로 골랐는가. `None` 은 고르지 못한 것이다.
    match_tier: str | None
    #: 그 단계에서 **실제로 찾은 키**(클래스 이름 또는 그룹 토큰). 사유만으로는 어느
    #: 이름이 맞았는지 알 수 없다.
    match_key: str | None
    #: 이 묶음이 선 클래스 가설. `None` 은 아직 가려지지 않은 것이다(AI-S-04).
    semantic_class: str | None
    #: 묶음에 쓰인 그룹 토큰. `None` 은 주어지지 않은 것이고 "그룹이 없다" 가 아니다.
    object_group: str | None
    asset: ProxyAsset | None
    placement: ProxyPlacement
    fit: SizeFit
    #: 클래스를 누가 어떤 격으로 말했는가. 상태가 ABSENT 일 때도 남는다(AI-S-03).
    grounds: KindClaim | None = None
    #: 자산 파일이 자산 뿌리에 있는가. **None 은 확인하지 못한 것**이고 '없다' 가 아니다.
    asset_present: bool | None = None
    #: 같은 키를 대신할 수 있었던 다른 자산들(결정적 순서).
    alternatives: tuple[str, ...] = ()
    #: 등록되어 있으나 지금 쓸 수 없었던 자산 → 사유. 정확·그룹 두 단계를 합쳐 적는다.
    unfit: Mapping[str, str] = field(default_factory=dict)
    #: 묶음 회차. 1 에서 시작하고 **묶음이 실제로 바뀔 때만** 올라간다.
    binding_index: int = 1
    #: 이 회차가 선 시각. 객체가 움직여도 바뀌지 않는다 — 바뀌면 "언제부터 이 모양
    #: 이었나" 를 답할 수 없다.
    bound_at: float = 0.0
    #: 물러난 묶음들(오래된 것부터). 덮어쓰기가 아니다.
    trail: tuple[BindingTrailEntry, ...] = ()

    @property
    def bound(self) -> bool:
        return self.state is ProxyState.RESOLVED

    @property
    def proxy_id(self) -> str | None:
        return None if self.asset is None else self.asset.proxy_id

    @property
    def asset_ref(self) -> str | None:
        """자산의 상대 참조. 뷰어가 미디어 경로에서 받을 때 쓰는 그 값이다."""
        return None if self.asset is None else self.asset.asset_ref

    @property
    def rebound(self) -> bool:
        """한 번이라도 다시 묶였는가. 화면이 모양을 다시 세워야 하는지의 근거다."""
        return bool(self.trail)

    def moved(self, placement: ProxyPlacement, *,
              measured_extent_m: float | None = None,
              tolerance: float = DEFAULT_SIZE_TOLERANCE) -> "AssetBinding":
        """자리만 옮긴 같은 묶음. **자산을 다시 고르지 않는다.**

        이것이 "이동 되도록" 의 구현이다 — 회차도 `bound_at` 도 그대로이므로 받는
        쪽은 같은 자산 하나를 옮기면 되고, 새 객체가 생겼다고 읽지 않는다.
        """
        return replace(
            self, placement=placement,
            fit=compare_extent(None if self.asset is None else self.asset.extent_m,
                               measured_extent_m, tolerance=tolerance),
        )

    def as_dict(self) -> dict:
        """맵이 "무엇을, 어디에, 어떤 근거로 세우는가" 를 아는 데 필요한 것 전부.

        고른 이유와 **고르지 못한 이유**를 같은 묶음에 넣는다 — 나누면 화면은 묶인
        것만 그리고 나머지는 빈칸이 된다. 색·크기 배율·카메라 각도 같은 표현 결정은
        여기 없다(docs/view-contract.md §3.1).
        """
        payload = {
            dd.OBJECT_ID: self.object_id,
            dd.SEMANTIC_CLASS: self.semantic_class,
            dd.OBJECT_GROUP: self.object_group,
            dd.PROXY_STATE: self.state.value,
            dd.ASSET_BINDING_REASON: self.reason,
            dd.ASSET_MATCH_TIER: self.match_tier,
            dd.ASSET_MATCH_KEY: self.match_key,
            dd.BINDING_INDEX: self.binding_index,
            dd.BOUND_AT: self.bound_at,
            dd.ASSET_PRESENT: self.asset_present,
            dd.PROXY_ALTERNATIVES: list(self.alternatives),
            dd.UNFIT_PROXIES: dict(self.unfit),
            "grounds": None if self.grounds is None else self.grounds.as_dict(),
            "placement": self.placement.as_dict(),
            "size_fit": self.fit.as_dict(),
            "trail": [entry.as_dict() for entry in self.trail],
        }
        payload.update(self.asset.as_dict() if self.asset is not None
                       else {dd.PROXY_ID: None})
        return payload


# ---------------------------------------------------------------------------
# 묶음기 — 객체 식별자에 걸린 상태를 들고 있다
# ---------------------------------------------------------------------------


#: 레코드가 클래스를 말하지 못한 상태의 사유. 묶음 실패가 아니라 인지의 상태다.
CLAIM_UNRESOLVED_IN_RECORD = "class_unresolved_in_record"


def claim_for_class(semantic_class: str | None, *, source: str,
                    observed_at: float = 0.0, confidence: float | None = None,
                    frame_ref: str = "") -> KindClaim:
    """클래스 가설 문자열 하나를 근거 1건으로 바꾼다.

    `unknown`(`object_record.UNKNOWN_CLASS`)과 빈 문자열은 **종류를 말하지 않은 것**
    이고 그 상태를 그대로 옮긴다 — 자리 채우기로 1 위를 집어 오면 미확정이 화면에서
    확답처럼 보인다(AI-S-04). "unknown 은 클래스가 아니다" 를 아는 자리는 이 함수
    하나이고, 호출부가 각자 판정하면 어느 화면에서는 `unknown` 이라는 이름의 자산을
    찾게 된다.
    """
    established = bool(semantic_class) and semantic_class != UNKNOWN_CLASS
    return KindClaim(
        kind=semantic_class if established else None,
        confidence=confidence if established else None,
        source=source,
        observed_at=observed_at,
        frame_ref=frame_ref,
        reason="" if established else CLAIM_UNRESOLVED_IN_RECORD,
    )


def claim_from_record(record: ObjectRecord, *, source: str = "object_record",
                      frame_ref: str = "") -> KindClaim:
    """지속 객체 레코드의 클래스 가설을 근거 1건으로 바꾼다.

    확신(`confidence`)과 근거 충분도(`supporting_groups`)는 다른 축이므로 한 칸에
    담지 않는다(AI-S-03). 여기서 옮기는 것은 확신뿐이고, 충분도는 레코드 쪽에 남는다.
    """
    return claim_for_class(record.semantic_class, source=source,
                           observed_at=record.observed_at,
                           confidence=record.confidence, frame_ref=frame_ref)


def placement_from_record(record: ObjectRecord, *,
                          heading_deg: float | None = None,
                          accuracy_m: float | None = None) -> ProxyPlacement:
    """레코드의 기하에서 자리 하나를 만든다. **프레임을 잃지 않는다**(AI-C-02).

    레코드의 기하는 영역(bbox)이고 자리는 그 중심이다. 기하가 없으면 자리를 **지어내지
    않고** 모른다고 적는다 — 0 좌표는 원점에 물건을 세운다.
    """
    if record.geometry is None:
        return unknown_placement(frame_id=record.frame_id)
    x1, y1, x2, y2 = record.geometry
    return local_placement(((x1 + x2) / 2.0, (y1 + y2) / 2.0),
                           frame_id=record.frame_id, accuracy_m=accuracy_m,
                           heading_deg=heading_deg)


@dataclass
class AssetBinder:
    """클래스를 자산에 묶고, 객체가 움직이는 동안 그 묶음을 유지한다.

    상태를 들고 있는 이유는 하나다 — **같은 자산 하나를 옮기기 위해서**다. 묶음은
    지속 객체 식별자에 걸리고, 클래스 가설과 그룹이 그대로인 동안 자산을 다시 고르지
    않는다.

    `resolver` 는 `object_appearance.ProxyResolver` 다. 후보 선택·자산 존재 확인·우선
    순위는 그쪽 규칙을 그대로 쓴다 — 여기서 다시 정하면 같은 객체가 두 화면에서 다른
    모양이 된다.
    """

    resolver: ProxyResolver
    size_tolerance: float = DEFAULT_SIZE_TOLERANCE
    #: 객체 식별자 → 지금 묶음. **공개 상태**가 아니라 이 묶음기의 기억이다.
    bindings: dict[str, AssetBinding] = field(default_factory=dict)

    # -- 조회 ------------------------------------------------------------

    def binding(self, object_id: str) -> AssetBinding | None:
        return self.bindings.get(object_id)

    def placements(self) -> list[dict]:
        """지금 묶인 객체 전부의 자리(식별자 순).

        **묶이지 않은 객체도 낸다** — 자리는 아는데 모양이 없는 것은 정상 상태이고,
        목록에서 빼면 "거기 아무것도 없다" 는 거짓말이 된다(AI-C-05).
        """
        return [self.bindings[key].as_dict() for key in sorted(self.bindings)]

    def forget(self, object_id: str) -> AssetBinding | None:
        """그 객체의 묶음을 잊는다(레코드가 만료됐을 때).

        자취도 함께 사라진다 — 계보를 남겨야 하면 지우기 전에 `trail` 을 가져가야
        한다. 이 모듈은 장기 저장소가 아니다(AI-O-03).
        """
        return self.bindings.pop(object_id, None)

    # -- 묶기 ------------------------------------------------------------

    def bind(
        self,
        object_id: str,
        claim: KindClaim,
        *,
        placement: ProxyPlacement,
        group: str = "",
        measured_extent_m: float | None = None,
        at: float = 0.0,
    ) -> AssetBinding:
        """클래스 가설 하나를 자산에 묶는다. 매 관측마다 불러도 된다.

        클래스와 그룹이 지난번과 같으면 **자산을 다시 고르지 않고** 자리만 옮긴다.
        바뀌었으면 다시 고르고, 그 결과가 실제로 다른 자산이면 이전 묶음을 자취로
        물린 뒤 회차를 올린다.

        `group` 은 문자열이다. 비어 있으면 그룹 단계가 없고 정확 클래스만 본다 —
        분류기가 없는 배치에서도 이 묶음기는 돌아야 한다(AI-C-05).
        """
        previous = self.bindings.get(object_id)
        label = claim.kind or None
        group_token = group or None

        if (previous is not None and previous.semantic_class == label
                and previous.object_group == group_token):
            # 바뀐 것이 없다. 같은 자산을 **옮긴다**.
            current = previous.moved(placement, measured_extent_m=measured_extent_m,
                                     tolerance=self.size_tolerance)
            self.bindings[object_id] = current
            return current

        current = self._resolve(object_id, claim, placement=placement,
                                group=group_token,
                                measured_extent_m=measured_extent_m, at=at)
        if previous is not None:
            current = self._link(previous, current, at=at)
        self.bindings[object_id] = current
        return current

    def bind_record(
        self,
        record: ObjectRecord,
        *,
        group: str = "",
        placement: ProxyPlacement | None = None,
        measured_extent_m: float | None = None,
        heading_deg: float | None = None,
        at: float | None = None,
    ) -> AssetBinding:
        """지속 객체 레코드 하나를 묶는다. 레코드가 가진 것만 읽는다.

        자리를 따로 주지 않으면 레코드의 기하에서 만든다. 융합 레코드처럼 자리를 이미
        현장 로컬로 들고 있는 쪽은 그 자리를 넘기면 된다.
        """
        return self.bind(
            record.object_id,
            claim_from_record(record),
            placement=(placement if placement is not None
                       else placement_from_record(record, heading_deg=heading_deg)),
            group=group,
            measured_extent_m=measured_extent_m,
            at=record.observed_at if at is None else at,
        )

    # -- 내부 ------------------------------------------------------------

    def _resolve(self, object_id: str, claim: KindClaim, *,
                 placement: ProxyPlacement, group: str | None,
                 measured_extent_m: float | None, at: float) -> AssetBinding:
        """정확 클래스 → 그룹 대역 → 없음(사유). 단계는 **찾은 키**가 정한다.

        단계 판정을 우선순위로 하지 않는 이유: 그룹 대역의 우선순위를 낮게 적는 것은
        같은 단계 안의 순서를 정하는 일이고, "정확한 것이 먼저" 는 그보다 앞선 규칙
        이다. 두 축을 한 숫자에 담으면 그룹 대역에 높은 우선순위를 적은 사람이 정확
        묶음을 조용히 이긴다.
        """
        if not claim.established:
            # 클래스가 안 가려졌다. 그룹 대역으로 내려가지 **않는다** — 그룹도 분류의
            # 결과이고, 분류가 없는데 그룹이 있다고 가정하면 근거 없는 모양이 선다.
            attempt = self._attempt(object_id, claim, key=None, placement=placement,
                                    measured_extent_m=measured_extent_m)
            return self._absent(object_id, claim, attempt, group=group,
                                reason=REASON_CLASS_NOT_ESTABLISHED,
                                extra_unfit={}, at=at)

        exact = self._attempt(object_id, claim, key=claim.kind, placement=placement,
                              measured_extent_m=measured_extent_m)
        if exact.resolved:
            return self._bound(object_id, claim, exact, group=group,
                               tier=MATCH_EXACT_CLASS, key=claim.kind,
                               reason=REASON_EXACT_CLASS_ASSET, extra_unfit={}, at=at)

        if group:
            fallback = self._attempt(object_id, claim, key=group, placement=placement,
                                     measured_extent_m=measured_extent_m)
            if fallback.resolved:
                return self._bound(object_id, claim, fallback, group=group,
                                   tier=MATCH_GROUP_FALLBACK, key=group,
                                   reason=REASON_GROUP_FALLBACK_ASSET,
                                   extra_unfit=dict(exact.unfit), at=at)
            return self._absent(object_id, claim, fallback, group=group,
                                reason=self._absent_reason(exact, fallback, group=group),
                                extra_unfit=dict(exact.unfit), at=at)

        return self._absent(object_id, claim, exact, group=group,
                            reason=self._absent_reason(exact, None, group=group),
                            extra_unfit={}, at=at)

    def _attempt(self, object_id: str, claim: KindClaim, *, key: str | None,
                 placement: ProxyPlacement,
                 measured_extent_m: float | None) -> ProxyResolution:
        """한 키로 카탈로그를 찾아본다. 후보 규칙은 `ProxyResolver` 의 것이다.

        `previous` 를 넘기지 않는 이유: 회차는 이 모듈이 `binding_index` 로 센다.
        둘을 다 올리면 "몇 번째 묶음인가" 에 답이 두 개가 되고 서로 어긋난다.
        """
        return self.resolver.resolve(
            object_id, replace(claim, kind=key), placement=placement,
            measured_extent_m=measured_extent_m, resolved_at=claim.observed_at)

    def _absent_reason(self, exact: ProxyResolution,
                       fallback: ProxyResolution | None, *, group: str | None) -> str:
        """왜 못 묶였는가. 네 가지 이유를 한 빈칸으로 만들지 않는다."""
        if exact.reason == REASON_NO_CATALOG:
            return REASON_NO_ASSET_CATALOG
        unfit = dict(exact.unfit)
        if fallback is not None:
            unfit.update(fallback.unfit)
        if unfit or exact.reason == REASON_EVERY_STAND_IN_UNFIT or (
                fallback is not None and fallback.reason == REASON_EVERY_STAND_IN_UNFIT):
            return REASON_EVERY_ASSET_UNFIT
        if not group:
            return REASON_UNMAPPED_CLASS_NO_GROUP
        return REASON_NO_ASSET_FOR_CLASS_OR_GROUP

    def _bound(self, object_id: str, claim: KindClaim, resolution: ProxyResolution, *,
               group: str | None, tier: str, key: str | None, reason: str,
               extra_unfit: dict, at: float) -> AssetBinding:
        unfit = {**extra_unfit, **dict(resolution.unfit)}
        return AssetBinding(
            object_id=object_id, state=ProxyState.RESOLVED, reason=reason,
            match_tier=tier, match_key=key, semantic_class=claim.kind,
            object_group=group, asset=resolution.proxy, placement=resolution.placement,
            fit=resolution.fit, grounds=claim,
            asset_present=resolution.asset_present,
            alternatives=resolution.alternatives, unfit=unfit,
            binding_index=1, bound_at=at,
        )

    def _absent(self, object_id: str, claim: KindClaim, resolution: ProxyResolution, *,
                group: str | None, reason: str, extra_unfit: dict,
                at: float) -> AssetBinding:
        """묶이지 않은 상태. **자리는 그대로 낸다**(AI-C-05).

        크기 비교는 선언 쪽이 없으므로 `unmeasured` 이고, 그 '모름' 은 불일치가 아니다.
        """
        unfit = {**extra_unfit, **dict(resolution.unfit)}
        return AssetBinding(
            object_id=object_id, state=ProxyState.ABSENT, reason=reason,
            match_tier=None, match_key=None, semantic_class=claim.kind,
            object_group=group, asset=None, placement=resolution.placement,
            fit=resolution.fit, grounds=claim, asset_present=None,
            alternatives=(), unfit=unfit, binding_index=1, bound_at=at,
        )

    @staticmethod
    def _link(previous: AssetBinding, current: AssetBinding, *,
              at: float) -> AssetBinding:
        """이전 묶음을 자취로 물리고 회차를 올린다. **이전 묶음은 손대지 않는다.**

        자산도 단계도 그대로면 회차를 올리지 않는다 — 올리면 "모양이 바뀌었다" 가 매
        관측마다 참이 되고 화면은 쉬지 않고 다시 세운다
        (`object_appearance.ProxyResolver._link` 와 같은 규약). 클래스 이름만 바뀌고
        같은 자산으로 묶이는 경우가 그렇다: 가방에서 배낭으로 가설이 바뀌었어도 둘 다
        같은 그룹 대역으로 선다면 **맵이 세운 모양은 바뀌지 않았다.** 클래스 가설의
        이력은 객체 레코드의 것이고 묶음의 자취가 아니다.
        """
        if (previous.proxy_id == current.proxy_id
                and previous.match_tier == current.match_tier):
            return replace(current, binding_index=previous.binding_index,
                           bound_at=previous.bound_at, trail=previous.trail)
        entry = BindingTrailEntry(
            binding_index=previous.binding_index, proxy_id=previous.proxy_id,
            semantic_class=previous.semantic_class, match_tier=previous.match_tier,
            bound_at=previous.bound_at, retired_at=at,
            supersede_reason=_rebind_reason(previous, current),
        )
        return replace(current, binding_index=previous.binding_index + 1,
                       bound_at=at, trail=previous.trail + (entry,))


def _rebind_reason(previous: AssetBinding, current: AssetBinding) -> str:
    """왜 다시 묶였는가. 단계가 바뀐 것과 클래스가 바뀐 것을 구분한다.

    단계 변화를 먼저 보는 이유: 같은 클래스에서 그룹 대역이 정확 모델로 올라간 것은
    "같은 종류의 다른 자산" 과 다른 사건이다 — 그쪽은 카탈로그가 자란 것이고, 운영자
    에게는 "드디어 제대로 그린다" 는 소식이다.
    """
    if previous.bound and current.bound:
        if previous.match_tier != current.match_tier:
            return (REBIND_EXACT_REPLACED_GROUP
                    if current.match_tier == MATCH_EXACT_CLASS
                    else REBIND_GROUP_REPLACED_EXACT)
        if previous.semantic_class != current.semantic_class:
            return SUPERSEDE_KIND_CHANGED
        return SUPERSEDE_OTHER_STAND_IN
    if previous.bound:
        return SUPERSEDE_STAND_IN_LOST
    return SUPERSEDE_STAND_IN_FOUND


def binder_from_catalogs(*paths: str | Path, require_asset_file: bool = False,
                         size_tolerance: float = DEFAULT_SIZE_TOLERANCE,
                         **resolver_kwargs: Any) -> AssetBinder:
    """선언 파일들로 묶음기를 만든다. **파일이 없어도 만들어진다**(AI-C-05).

    자산 뿌리는 배포 기본값($MISSION_RUNTIME_ASSETS, 기본 `../local`)이고, `asset_root`
    를 **명시적으로 None 으로** 넘기면 뿌리가 없는 것이다 — 그때 자산 존재는 확인하지
    않고 `asset_present` 가 None 으로 남는다(`object_appearance.resolver_from_catalog`
    와 같은 규약).

    `require_asset_file` 의 기본이 거짓인 이유: 자산 파일은 공개 트리 밖에 있고 대부분
    의 노드에 없다. 파일이 없다고 자산을 후보에서 빼면 화면이 "이 클래스는 그릴 것이
    없다" 로 읽지만 사실은 "그릴 것은 정해졌고 파일만 아직 없다" 다. 둘은 다른 상태
    이므로 묶음은 남기고 `asset_present` 로 사실을 적는다. 자산이 실제로 깔린 노드에서
    결손을 거르려면 참으로 넘긴다.
    """
    resolver_kwargs.setdefault("asset_root", default_asset_root())
    resolver = ProxyResolver(
        catalog=load_catalogs(*paths), require_asset_file=require_asset_file,
        size_tolerance=size_tolerance, **resolver_kwargs,
    )
    return AssetBinder(resolver=resolver, size_tolerance=size_tolerance)


def classes_without_asset(catalog: ProxyCatalog,
                          labels: Iterable[str]) -> tuple[str, ...]:
    """그 클래스들 중 정확 묶음이 없는 것. **카탈로그에 무엇을 더할지의 목록**이다.

    그룹 대역으로 그려지는 것은 오류가 아니지만, 운영자가 "왜 전부 상자로 보이나" 를
    물을 때 답이 되는 자리가 있어야 한다.
    """
    return tuple(sorted({label for label in labels
                         if label and not catalog.for_kind(label)}))
