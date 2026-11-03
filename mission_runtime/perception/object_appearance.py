"""관측된 객체를 가상환경에서 **무엇으로 대신 그릴까**.

implements: AI-S-06 (이종 근거의 점진적 객체 레코드), AI-C-15 (도메인은 데이터),
            AI-C-08 (픽셀은 상태 계약으로 나가지 않는다), AI-C-02 (좌표계 경계)
관련: AI-S-03 (신뢰도와 근거 충분도는 다른 축), AI-S-04 (확정 label 강제 금지),
      AI-C-05 (선택 결손은 축소), AI-C-18 (선언 규약), AI-C-19 (판단·권한 경계)
tests: tests/test_object_appearance.py

## 문제

디지털 트윈 화면은 "저기에 무언가 있다" 만으로는 그릴 것이 없다. 로봇이든 하천
부유물이든 화면에 **모양**이 서야 하고, 우리에게 그 개체의 실제 스캔은 없다. 있는
것은 저장해 둔 비슷한 물체 — 3D 모델 몇 개와 사진 몇 장 — 이고, 관측이 말해 주는
것은 **종류**다. 그래서 이 모듈은 종류를 대역 자산(proxy)으로 환산한다.

여기서 조용히 거짓말하는 길이 세 개 있고, 셋 다 막는다.

1. **대역을 개체 주장으로 바꾸는 길.** 화면에 `go1` 모양이 섰다는 것은 "저것이
   go1-a 다" 가 아니다. 외형은 종류까지만 말한다(`perception/device_identity.py`).
   그래서 카탈로그는 개체를 가리키는 이름(`device_id`·`entity_id`)을 **선언에 담을
   수 없고**(`ProxyCatalogError`), 이 모듈의 산출에도 그 칸이 없다. 같은 기종 두
   대는 같은 대역으로 선다 — 그것이 정확한 표현이다.
2. **대역이 없을 때 객체를 지우는 길.** 종류가 안 가려졌거나 그 종류의 대역이
   카탈로그에 없는 것은 오류가 아니라 정상이다(AI-C-05). 그때 `ABSENT` 를 사유와
   함께 내고 **자리는 그대로 낸다** — 모양 없이 자리만 그리는 것은 화면이 할 수
   있는 일이고, 객체를 목록에서 빼는 것은 "없다" 는 거짓말이다.
3. **크기를 맞춰 늘리는 길.** 카탈로그가 적은 실물 크기와 관측이 **실측한** 크기가
   어긋나면 자산을 조용히 늘리지 않고 어긋남을 보고한다. 늘리면 화면은 그럴듯해
   지고 그 그럴듯함이 다음 판단의 전제가 된다. 둘 중 하나가 미측정이면 '어긋남'
   이 아니라 '모름' 이다 — 미측정은 0 도 아니고 불일치도 아니다(AI-B-01).

## 선택은 다시 계산되는 값이다

근거는 뒤에 더 온다. 처음에는 "부유물" 이던 것이 다음 관측에서 "PET 병" 이 되고,
그러면 대역도 바뀌어야 한다. 바뀐 결과는 **이전 선택을 덮지 않는다** — 새
`ProxyResolution` 이 이전 것을 `previous` 로 들고 `superseded` 에 무엇이 왜
대체됐는지 적는다. 덮어쓰면 "화면이 아까와 다른 모양을 그리는 이유" 를 되짚을 수
없고, 그 되짚기가 AI-S-06 이 요구한 근거 추적이다.

## 카탈로그는 데이터다

`config/object_models.example.json` 에 한 줄 더하면 새 대역이 생기고 이 파일은
고치지 않는다(원칙 #1, #7). 종류 태그·자산 종류는 벤더 열거형이 아니라 자유
문자열이고, 자산 종류의 어휘조차 **파일 자신이** `$asset_kinds` 로 선언한다 —
어휘를 코드에 적으면 새 표현 방식을 더하는 일이 코드 변경이 된다.

자산 파일은 공개 트리 밖(`$MISSION_RUNTIME_ASSETS`, 기본 `../local`)에 살고
카탈로그는 **참조만** 적는다. 자산이 실제로 그 자리에 있는지는 선언이 말하지 않고
이 모듈이 확인해 `asset_present` 로 낸다 — 뿌리가 없는 배치에서는 확인하지 못한
것이므로 `None` 이고, 그 `None` 은 '없다' 가 아니다.

## 이 모듈이 소유하지 않는 것

**그리는 일은 여기 없다.** 색·픽셀·폰트·카메라 각도는 서버 응답에 나가지 않고
(`docs/view-contract.md`), 이 모듈은 "어느 자산을, 어떤 근거로" 까지만 말한다.
자산의 픽셀도 상태 계약으로 나가지 않는다 — 뷰어는 `asset_ref` 로 미디어 경로에서
받는다(AI-C-08). 종류를 정하는 일은 `perception/device_class_estimator.py`,
개체 결속은 `perception/device_identity.py`, 자리의 전역 변환은 `perception/twin_map.py`
의 datum 계층이고, 이 모듈은 자리를 **들어온 프레임 그대로 통과시킨다**(AI-C-02).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.perception.spatial_evidence import (
    TIER_DECLARED,
    TIER_ESTIMATED,
    TIER_MEASURED,
    is_local_frame,
)

#: 대역 선택은 **선택 계층**이다. 종류 추정이 하나라도 있으면 성립하고, 카탈로그·
#: 자산·실측 크기는 전부 선택이다 — 결손은 DEGRADED 까지만 내려간다(AI-C-05).
REQUIREMENT = CapabilityRequirement(
    required=("perception.classify",),
    optional=("reference.object_proxy_catalog", "media.asset_store",
              "perception.depth", "reference.site_datum"),
)

#: 자산 뿌리의 환경변수. `tests/conftest.py::asset_root()` · `tools/fms_console` 와
#: **같은 규약**이다 — 자리를 모듈마다 따로 적으면 재분류가 또 있을 때 어떤 쪽은
#: 조용히 '자산 없음' 이 된다.
ASSET_ROOT_ENV = "MISSION_RUNTIME_ASSETS"

#: 카탈로그 선언에 들어올 수 없는 이름. **개체를 가리키는 칸**이고, 대역은 종류의
#: 대역이므로 이 칸이 선언에 있으면 그 선언은 대역이 아니라 결속 주장이다.
IDENTITY_FIELD_NAMES: frozenset[str] = frozenset({dd.DEVICE_ID, dd.ENTITY_ID})

#: 예시 카탈로그가 선언하는 자산 종류. **코드가 아는 값이 아니라 그 파일이 적은
#: 값**이고, 여기 둔 상수는 시험과 호출부가 문자열을 직접 쓰지 않게 하기 위한
#: 편의다. 새 종류는 카탈로그의 `$asset_kinds` 에 한 줄 더하면 된다.
ASSET_KIND_IMAGE = "stored_image"
ASSET_KIND_MODEL = "model_3d"

#: 선언 크기와 실측 크기의 허용 배율. `device_class_estimator` 의 크기 단서와 같은
#: 값에서 출발한다 — 데이터이고 현장 비교로 바꾼다(AI-C-13).
DEFAULT_SIZE_TOLERANCE = 1.6

#: 카탈로그가 우선순위를 적지 않았을 때의 값. `CompatibilityProfile.priority` 와
#: 같은 규약(작은 값이 먼저)이다.
DEFAULT_PRIORITY = 50

# --- 카탈로그가 없을 때의 사유 ------------------------------------------------
NO_CATALOG_FILE = "no_object_model_catalog_file"

# --- 선언 거절 사유 (ProxyCatalogError 메시지 토큰) ----------------------------
REJECT_NO_PROXIES_KEY = "catalog_has_no_proxies_key"
REJECT_MISSING_FIELD = "missing_field"
REJECT_DUPLICATE_PROXY_ID = "duplicate_proxy_id"
REJECT_UNDECLARED_ASSET_KIND = "asset_kind_not_declared_by_catalog"
REJECT_NO_STANDS_IN_FOR = "stands_in_for_is_empty"
REJECT_ASSET_REF_ESCAPES_ROOT = "asset_ref_escapes_asset_root"
REJECT_UNKNOWN_LICENSE_REDISTRIBUTED = "unknown_license_declared_redistributable"
REJECT_EXTENT_NOT_POSITIVE = "extent_m_must_be_positive_or_absent"
REJECT_IDENTITY_FIELD = "proxy_declaration_names_an_individual"

#: 라이선스를 모를 때 **적어야 하는** 값. 비워 두는 것과 다르다 — 비우면 "확인했고
#: 제약이 없다" 와 구분되지 않는다.
LICENSE_UNKNOWN = "unknown"

# --- 대역을 쓸 수 없는 사유 (proxy_id → 사유) ---------------------------------
UNFIT_ASSET_FILE_MISSING = "asset_file_missing"


class ProxyState(str, Enum):
    """대역 선택 상태. `RESOLVED` 만 모양을 말한다."""

    RESOLVED = "RESOLVED"
    #: 그릴 대역이 없다. **오류가 아니라 정상 상태**이고 자리는 그대로 나간다.
    ABSENT = "ABSENT"


#: `ProxyState` 의 사유 어휘. 문자열을 호출부에 흩뿌리면 화면이 사유별로 분기할 수
#: 없고 "모양이 없다" 의 네 가지 이유가 한 빈칸이 된다.
REASON_STANDS_IN_FOR_KIND = "catalogued_stand_in_for_kind"
REASON_KIND_NOT_ESTABLISHED = "kind_not_established"
REASON_NO_STAND_IN_FOR_KIND = "no_catalogued_stand_in_for_kind"
REASON_NO_CATALOG = "no_proxy_catalog"
REASON_EVERY_STAND_IN_UNFIT = "every_stand_in_unfit"

# --- 크기 비교 상태 -----------------------------------------------------------
SIZE_MATCH = "match"
SIZE_MISMATCH = "mismatch"
#: 선언·실측 중 하나라도 없다. **불일치가 아니고 0 도 아니다.**
SIZE_UNMEASURED = "unmeasured"

SIDE_DECLARED = "declared_extent"
SIDE_MEASURED = "measured_extent"
SIDE_BOTH = "both"

#: `ProxyResolution.as_dict()` 가 **묶음**으로 쓰는 키. 값의 이름이 아니라 자리의
#: 이름이라 사전 항목이 아니고, 그 안의 잎 이름은 전부 사전에 있다(AI-C-01).
GROUP_KEYS: tuple[str, ...] = ("grounds", "placement", "size_fit", "superseded")

# --- 자리를 내지 못하는 사유 --------------------------------------------------
#: 프레임 이름이 없다. 어느 기준의 값인지 모르는 좌표는 좌표가 아니다(AI-C-02).
REFUSE_UNKNOWN_FRAME = "unregistered_frame"
#: 전역 프레임 값이 들어왔다. 전역 변환은 검증된 site datum 을 가진 계층의 일이고
#: (`perception/twin_map.py`) 이 모듈은 변환을 하지 않는다 — 공개 상태 계약은 아직
#: 전역 좌표 칸을 내지 않는다(`tools/fms_console/fleet.py::global_release()` 가 그 게이트다).
REFUSE_GLOBAL_FRAME = "global_value_not_owned_here"
#: 자리를 아직 관측하지 못했다. 모름이고 0 좌표가 아니다.
REFUSE_POSITION_UNKNOWN = "position_not_observed"

# --- 대체 사유 ---------------------------------------------------------------
SUPERSEDE_KIND_CHANGED = "estimated_kind_changed"
SUPERSEDE_OTHER_STAND_IN = "same_kind_different_stand_in"
SUPERSEDE_STAND_IN_LOST = "stand_in_no_longer_available"
SUPERSEDE_STAND_IN_FOUND = "stand_in_became_available"


class ProxyCatalogError(ValueError):
    """대역 카탈로그 선언을 읽을 수 없다. 거절은 사유와 함께 낸다(AI-C-18)."""


def identity_fields(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """`payload` 안의 **개체를 가리키는** 이름들. 대역 선언에는 있을 수 없다."""
    return tuple(sorted(name for name in payload if name in IDENTITY_FIELD_NAMES))


def default_asset_root() -> Path | None:
    """자산이 사는 자리. `tests/conftest.py` · `tools/fms_console` 와 같은 규약.

    환경변수가 있으면 없는 자리라도 그대로 쓴다(조용히 다른 곳을 집으면 "왜 못
    찾느냐" 를 추적할 수 없다). 없으면 개발 배치의 `../local` 이고, 그것도 없으면
    뿌리가 없다 — 없는 뿌리는 오류가 아니라 **확인할 수 없는 상태**다.
    """
    override = os.environ.get(ASSET_ROOT_ENV)
    if override:
        return Path(override)
    sibling = Path(__file__).resolve().parents[2] / "local"
    return sibling if sibling.is_dir() else None


# ---------------------------------------------------------------------------
# 카탈로그 — 데이터이고, 없는 것이 정상인 자료
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProxyAsset:
    """저장해 둔 대역 자산 1건의 선언.

    `stands_in_for` 는 이 자산이 대신하는 **종류** 태그다. 개체 id 가 아니고, 될 수도
    없다 — 그 구분이 이 모듈의 핵심 주장이다(모듈 docstring 1번).

    `extent_m` 은 이 자산이 묘사하는 실물의 가장 긴 변(m)이다. None 은 **미측정**
    이고 0 이 아니다 — 적지 않은 크기는 실측과 비교되지 않는다.
    """

    proxy_id: str
    #: 이 자산이 무엇을 묘사하는가(표시용 다국어 라벨). 표현 결정이 아니라 자료다.
    depicts: Mapping[str, str] = field(default_factory=dict)
    stands_in_for: frozenset[str] = frozenset()
    asset_kind: str = ""
    #: 자산 뿌리 기준 **상대** 참조. 픽셀은 이 경로로 미디어 경로가 낸다(AI-C-08).
    asset_ref: str = ""
    extent_m: float | None = None
    priority: int = DEFAULT_PRIORITY
    origin: str = ""
    license: str = LICENSE_UNKNOWN
    redistributable: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if not self.proxy_id:
            raise ProxyCatalogError(f"{REJECT_MISSING_FIELD}:proxy_id")

    @property
    def license_known(self) -> bool:
        """라이선스를 확인했는가. 거짓이어도 선언은 유효하다 — 모름을 적은 것이다."""
        return bool(self.license) and self.license != LICENSE_UNKNOWN

    def stands_in(self, kind: str) -> bool:
        return bool(kind) and kind in self.stands_in_for

    def asset_path(self, root: Path | None) -> Path | None:
        """자산 파일의 자리. 뿌리가 없으면 **자리를 지어내지 않는다**."""
        if root is None or not self.asset_ref:
            return None
        return Path(root) / self.asset_ref

    def asset_present(self, root: Path | None) -> bool | None:
        """자산이 실제로 있는가. `None` 은 뿌리가 없어 **확인하지 못한 것**이다."""
        path = self.asset_path(root)
        if path is None:
            return None
        return path.is_file()

    def as_dict(self) -> dict:
        return {
            dd.PROXY_ID: self.proxy_id,
            dd.DEPICTS: dict(self.depicts),
            dd.STANDS_IN_FOR: sorted(self.stands_in_for),
            dd.ASSET_KIND: self.asset_kind,
            dd.ASSET_REF: self.asset_ref,
            dd.PROXY_EXTENT_M: self.extent_m,
            dd.ASSET_ORIGIN: self.origin,
            dd.ASSET_LICENSE: self.license,
        }


@dataclass(frozen=True)
class ProxyCatalog:
    """이 배치가 가진 대역 자산들. **비어 있을 수 있고 비어 있는 것은 오류가 아니다.**"""

    proxies: tuple[ProxyAsset, ...] = ()
    #: 이 카탈로그가 스스로 선언한 자산 종류 어휘 → 설명. 코드의 enum 이 아니다.
    asset_kinds: Mapping[str, str] = field(default_factory=dict)
    missing_reason: str = ""

    @property
    def available(self) -> bool:
        return bool(self.proxies)

    @property
    def kinds(self) -> tuple[str, ...]:
        """이 카탈로그가 대역을 가진 종류 태그 전부."""
        return tuple(sorted({kind for p in self.proxies for kind in p.stands_in_for}))

    def get(self, proxy_id: str) -> ProxyAsset | None:
        return next((p for p in self.proxies if p.proxy_id == proxy_id), None)

    def for_kind(self, kind: str) -> tuple[ProxyAsset, ...]:
        """그 종류를 대신할 수 있는 자산들. **결정적 순서**로 돌려준다.

        우선순위는 선언 데이터이고 동점은 id 순이다 — 같은 입력에 같은 순서가 나와야
        화면이 틱마다 다른 모양을 그리지 않는다.
        """
        return tuple(sorted((p for p in self.proxies if p.stands_in(kind)),
                            key=lambda p: (p.priority, p.proxy_id)))

    @classmethod
    def missing(cls, reason: str) -> "ProxyCatalog":
        return cls(missing_reason=reason)

    @classmethod
    def load(cls, path: str | Path) -> "ProxyCatalog":
        """카탈로그를 읽는다. **파일이 없으면 예외가 아니라 빈 카탈로그다.**

        여기서 raise 하면 카탈로그를 배포하지 않은 노드는 기동조차 못 한다 — 선택
        기능 하나의 결손이 프로세스 생사가 되는 것이 AI-C-05 가 금지한 모양이다.

        반대로 **적혀 있는데 잘못 적힌** 선언은 거절한다. 배치 전에 파일만 보고 알
        수 있는 잘못을 현장에서 발견할 이유가 없다(AI-C-18, AI-B-09).
        """
        path = Path(path)
        if not path.exists():
            return cls.missing(NO_CATALOG_FILE)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "proxies" not in raw:
            raise ProxyCatalogError(f"{REJECT_NO_PROXIES_KEY}:{path.name}")
        asset_kinds = dict(raw.get("$asset_kinds") or {})

        proxies: list[ProxyAsset] = []
        seen: set[str] = set()
        for entry in raw["proxies"]:
            proxies.append(_parse_proxy(entry, asset_kinds=asset_kinds, seen=seen))
        return cls(proxies=tuple(proxies), asset_kinds=asset_kinds)


#: 선언이 반드시 적어야 하는 칸. `license` 가 여기 있는 이유는 모름을 **적게**
#: 하려는 것이다 — 빈 칸과 "unknown" 은 다른 사실이다.
REQUIRED_PROXY_FIELDS: tuple[str, ...] = (
    "proxy_id", "stands_in_for", "asset_kind", "asset_ref", "origin", "license",
)


def _parse_proxy(entry: Mapping[str, Any], *, asset_kinds: Mapping[str, str],
                 seen: set[str]) -> ProxyAsset:
    """선언 1건을 읽고, 잘못 적힌 것은 사유와 함께 거절한다."""
    named = identity_fields(entry)
    if named:
        # 대역은 종류의 대역이다. 개체를 적은 선언은 결속 주장이고, 그 주장은
        # 식별력 있는 단서로만 선다(`perception/device_identity.py`).
        raise ProxyCatalogError(f"{REJECT_IDENTITY_FIELD}:{list(named)}")
    for key in REQUIRED_PROXY_FIELDS:
        if key not in entry:
            raise ProxyCatalogError(f"{REJECT_MISSING_FIELD}:{key}")
    proxy_id = str(entry["proxy_id"])
    if proxy_id in seen:
        raise ProxyCatalogError(f"{REJECT_DUPLICATE_PROXY_ID}:{proxy_id}")
    seen.add(proxy_id)

    stands_in_for = frozenset(str(tag) for tag in (entry["stands_in_for"] or ()))
    if not stands_in_for:
        # 아무 종류도 대신하지 않는 자산은 영원히 선택되지 않는다. 조용히 죽은
        # 선언을 남기면 "왜 저 모양이 안 뜨지" 가 파일에서 보이지 않는다.
        raise ProxyCatalogError(f"{REJECT_NO_STANDS_IN_FOR}:{proxy_id}")

    asset_kind = str(entry["asset_kind"])
    if asset_kinds and asset_kind not in asset_kinds:
        # 어휘는 코드가 아니라 **이 파일**이 정한다. 새 종류는 `$asset_kinds` 에
        # 한 줄이고, 적지 않은 종류를 쓰는 것은 오타다.
        raise ProxyCatalogError(f"{REJECT_UNDECLARED_ASSET_KIND}:{proxy_id}:{asset_kind}")

    asset_ref = str(entry["asset_ref"])
    if _escapes_root(asset_ref):
        raise ProxyCatalogError(f"{REJECT_ASSET_REF_ESCAPES_ROOT}:{proxy_id}:{asset_ref}")

    license_text = str(entry["license"])
    redistributable = bool(entry.get("redistributable", False))
    if redistributable and license_text == LICENSE_UNKNOWN:
        # 모르는 것을 '공개' 로 적지 않는다(config/label_sources.example.json 과
        # 같은 규약).
        raise ProxyCatalogError(f"{REJECT_UNKNOWN_LICENSE_REDISTRIBUTED}:{proxy_id}")

    extent = entry.get("extent_m")
    if extent is not None and not float(extent) > 0.0:
        # 0 은 "크기가 없다" 가 아니다. 모르면 칸을 비운다.
        raise ProxyCatalogError(f"{REJECT_EXTENT_NOT_POSITIVE}:{proxy_id}")

    return ProxyAsset(
        proxy_id=proxy_id,
        depicts=dict(entry.get("depicts") or {}),
        stands_in_for=stands_in_for,
        asset_kind=asset_kind,
        asset_ref=asset_ref,
        extent_m=None if extent is None else float(extent),
        priority=int(entry.get("priority", DEFAULT_PRIORITY)),
        origin=str(entry["origin"]),
        license=license_text,
        redistributable=redistributable,
        note=str(entry.get("note") or ""),
    )


def _escapes_root(asset_ref: str) -> bool:
    """자산 뿌리를 벗어나는 참조인가. 절대경로는 기계마다 다른 자리를 못 박는다."""
    if not asset_ref:
        return True
    candidate = Path(asset_ref)
    return candidate.is_absolute() or ".." in candidate.parts


# ---------------------------------------------------------------------------
# 근거 — 어떤 종류라고 누가 말했는가
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KindClaim:
    """"이 객체는 이 **종류**다" 라는 근거 1건.

    `kind` 가 None 이면 종류가 아직 가려지지 않은 것이고, 그것도 정상 상태다 —
    `reason` 이 왜 못 가렸는지를 든다(AI-S-04: 확정하기 어려운 것을 기존 클래스에
    강제 매핑하지 않는다).

    `tier` 는 그 근거의 **격**이다(`spatial_evidence` 와 같은 어휘): 사람이 확인한
    종류 > 조인에서 선언된 종류 > 모델이 추정한 종류. `confidence` 는 모델이 말한
    확신이고 None 은 **미측정**이다 — 격과 확신은 다른 축이라 한 칸에 담지 않는다
    (AI-S-03).
    """

    kind: str | None
    tier: str = TIER_ESTIMATED
    confidence: float | None = None
    #: 이 주장을 낸 쪽(추정기·운영자·조인 선언). 자유 문자열이다.
    source: str = ""
    observed_at: float = 0.0
    #: 원본 관측 참조. 근거를 되짚는 칸이고 독립성의 단위다(AI-S-06).
    frame_ref: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.tier not in dd.SPATIAL_EVIDENCE_TIERS:
            raise ValueError(f"unknown kind claim tier {self.tier!r}")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be within 0..1, got {self.confidence}")
        if self.kind in IDENTITY_FIELD_NAMES:
            # 종류 자리에 개체를 가리키는 이름을 넣는 것은 종류 주장이 아니다.
            raise ValueError(f"a kind claim must not be an identity: {self.kind!r}")

    @property
    def established(self) -> bool:
        """종류를 말했는가. 거짓이면 대역을 고르지 않는다 — 고르면 추측이다."""
        return bool(self.kind)

    def as_dict(self) -> dict:
        return {
            dd.SEMANTIC_CLASS: self.kind,
            dd.EVIDENCE_TIER: self.tier,
            dd.CONFIDENCE: self.confidence,
            dd.SOURCE_GROUP: self.source,
            dd.OBSERVED_AT: self.observed_at,
            dd.FRAME_REF: self.frame_ref,
            dd.KIND_CLAIM_REASON: self.reason,
        }


def kind_claim_from_estimate(estimate: Any, *, source: str, observed_at: float,
                             frame_ref: str = "") -> KindClaim:
    """`device_class_estimator.ClassEstimate` 를 근거 1건으로 바꾼다.

    타입을 수입하지 않고 **모양만 읽는다**(`appearance_cue(verdict: Any, ...)` 와 같은
    규약) — 추정기가 없는 배치에서도 이 모듈은 import 되어야 한다(AI-C-05).

    확정되지 않은 추정은 종류를 말하지 않는다. 1 위를 그냥 집어 오면 모호·모순이
    화면에서 확답처럼 보이고, 그 확답이 다음 판단의 전제가 된다(AI-S-04).
    """
    classified = bool(getattr(estimate, "classified", False))
    ranked = tuple(getattr(estimate, "ranked", ()) or ())
    confidence: float | None = None
    if classified and ranked:
        top = ranked[0]
        decisive = float(getattr(top, "decisive_score", 0.0))
        supporting = float(getattr(top, "supporting_score", 0.0))
        confidence = decisive + (1.0 - decisive) * supporting
    return KindClaim(
        kind=getattr(estimate, "device_class", None) if classified else None,
        tier=TIER_ESTIMATED,
        confidence=confidence,
        source=source,
        observed_at=observed_at,
        frame_ref=frame_ref,
        reason=str(getattr(estimate, "reason", "") or ""),
    )


def declared_kind_claim(kind: str, *, source: str, observed_at: float) -> KindClaim:
    """조인 선언·프로파일이 적은 종류. **사전정보이고 관측이 아니다**(AI-S-08).

    그래서 격이 `declared` 이고 확신은 미측정이다 — 선언만으로 "확인됐다" 가 되면
    보정판이 실제로 측정한 값과 비교할 기준이 사라진다.
    """
    return KindClaim(kind=kind, tier=TIER_DECLARED, confidence=None,
                     source=source, observed_at=observed_at)


def confirmed_kind_claim(kind: str, *, confirmed_by: str, observed_at: float) -> KindClaim:
    """사람이 확인한 종류(AI-L-03). 가장 높은 격이고 **서명 없이는 받지 않는다**."""
    if not confirmed_by:
        raise ValueError("a confirmed kind claim needs confirmed_by (AI-L-03)")
    return KindClaim(kind=kind, tier=TIER_MEASURED, confidence=None,
                     source=confirmed_by, observed_at=observed_at)


# ---------------------------------------------------------------------------
# 크기 — 맞춰 늘리지 않고 어긋남을 보고한다
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SizeFit:
    """선언 크기와 실측 크기의 비교. **배율을 적용 지시로 내지 않는다.**

    `ratio` 는 실측/선언이고 설명용 수치다. 자산을 늘릴지 그대로 둘지는 렌더러의
    결정이며, 어긋남은 화면에서 보여야 한다 — 조용히 맞추면 "대역이 실물과 다르다"
    는 사실이 사라진다.
    """

    state: str
    declared_extent_m: float | None = None
    measured_extent_m: float | None = None
    ratio: float | None = None
    tolerance: float = DEFAULT_SIZE_TOLERANCE
    #: 어느 쪽이 미측정인가. `state` 가 `unmeasured` 일 때만 값이 있다.
    unmeasured_side: str | None = None

    @property
    def mismatched(self) -> bool:
        return self.state == SIZE_MISMATCH

    def as_dict(self) -> dict:
        return {
            dd.SIZE_FIT_STATE: self.state,
            dd.PROXY_EXTENT_M: self.declared_extent_m,
            dd.MEASURED_EXTENT_M: self.measured_extent_m,
            dd.SIZE_RATIO: None if self.ratio is None else round(self.ratio, 4),
            dd.SIZE_TOLERANCE: self.tolerance,
            dd.UNMEASURED_SIDE: self.unmeasured_side,
        }


def compare_extent(declared_m: float | None, measured_m: float | None, *,
                   tolerance: float = DEFAULT_SIZE_TOLERANCE) -> SizeFit:
    """두 크기를 비교한다. **하나라도 모르면 '모름' 이고 불일치가 아니다.**"""
    missing_declared = declared_m is None or declared_m <= 0.0
    missing_measured = measured_m is None or measured_m <= 0.0
    if missing_declared or missing_measured:
        side = (SIDE_BOTH if missing_declared and missing_measured
                else SIDE_DECLARED if missing_declared else SIDE_MEASURED)
        return SizeFit(SIZE_UNMEASURED, declared_extent_m=declared_m,
                       measured_extent_m=measured_m, tolerance=tolerance,
                       unmeasured_side=side)
    ratio = float(measured_m) / float(declared_m)
    inside = (1.0 / tolerance) <= ratio <= tolerance if tolerance > 0 else ratio == 1.0
    return SizeFit(SIZE_MATCH if inside else SIZE_MISMATCH,
                   declared_extent_m=float(declared_m),
                   measured_extent_m=float(measured_m),
                   ratio=ratio, tolerance=tolerance)


# ---------------------------------------------------------------------------
# 자리 — 들어온 프레임 그대로 통과시킨다 (AI-C-02)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProxyPlacement:
    """대역을 세울 자리. **어느 프레임의 값인지 잃지 않는다**(AI-C-02).

    칸 이름은 `twin_map.FramedPosition` 과 같다(`value`·`coordinate_frame`·
    `accuracy_m`·`refused_because`) — 같은 뜻의 자리를 다른 이름으로 들고 다니면 둘을
    합칠 수 없다. 여기서 그 타입을 그대로 쓰지 않는 이유는 그쪽 `as_dict()` 가 아직
    사전에 없는 이름들을 쓰고 있어서다(그 이름들이 등록되면 이 자리는 그 타입으로
    합쳐도 된다).

    **전역 값은 이 자리에 담기지 않는다.** 전역 변환은 검증된 site datum 을 가진
    계층의 일이고(AI-C-02) 공개 상태 계약은 아직 전역 좌표 칸을 내지 않는다. 전역
    프레임으로 들어온 자리는 좌표를 **버리고** 프레임 이름과 사유만 남긴다 — 로컬
    값과 전역 값이 같은 칸에 섞이는 것보다 비는 편이 낫다.

    `heading_deg` 가 None 이면 자세는 미측정이고 0 도가 아니다 — 저장 이미지 대역은
    애초에 자세를 말하지 못한다.
    """

    value: tuple[float, float] | None
    coordinate_frame: str
    accuracy_m: float | None = None
    heading_deg: float | None = None
    refused_because: str | None = None

    def __post_init__(self) -> None:
        if self.value is None:
            if self.refused_because is None:
                object.__setattr__(self, "refused_because", REFUSE_POSITION_UNKNOWN)
            return
        refusal = ""
        if not self.coordinate_frame:
            refusal = REFUSE_UNKNOWN_FRAME
        elif not is_local_frame(self.coordinate_frame):
            refusal = REFUSE_GLOBAL_FRAME
        if refusal:
            object.__setattr__(self, "value", None)
            object.__setattr__(self, "accuracy_m", None)
            object.__setattr__(self, "refused_because", refusal)

    @property
    def available(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict:
        return {
            dd.PROXY_POSITION: None if self.value is None else list(self.value),
            dd.COORDINATE_FRAME: self.coordinate_frame,
            dd.ACCURACY_M: self.accuracy_m,
            dd.HEADING_DEG: self.heading_deg,
            dd.PLACEMENT_REFUSAL_REASON: self.refused_because,
        }


def local_placement(value: tuple[float, float], *, frame_id: str,
                    accuracy_m: float | None = None,
                    heading_deg: float | None = None) -> ProxyPlacement:
    """현장 로컬 자리 하나를 자리 계약으로 감싼다."""
    return ProxyPlacement(value=value, coordinate_frame=frame_id,
                          accuracy_m=accuracy_m, heading_deg=heading_deg)


def unknown_placement(*, frame_id: str = "",
                      reason: str = REFUSE_POSITION_UNKNOWN) -> ProxyPlacement:
    """자리를 모르는 객체의 빈 자리. 모르는 것도 상태이고 0 좌표가 아니다."""
    return ProxyPlacement(value=None, coordinate_frame=frame_id,
                          refused_because=reason)


# ---------------------------------------------------------------------------
# 선택 결과 — 이전 선택을 덮지 않는다
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Supersession:
    """무엇이 무엇으로 왜 바뀌었는가. 이전 선택은 지워지지 않는다(AI-S-06)."""

    previous_proxy_id: str | None
    previous_kind: str | None
    reason: str
    at: float = 0.0

    def as_dict(self) -> dict:
        return {
            dd.SUPERSEDED_PROXY_ID: self.previous_proxy_id,
            dd.SEMANTIC_CLASS: self.previous_kind,
            dd.SUPERSEDE_REASON: self.reason,
            dd.OBSERVED_AT: self.at,
        }


@dataclass(frozen=True)
class ProxyResolution:
    """한 객체를 **무엇으로 그릴지**의 선언. 개체 주장이 아니다(AI-C-19).

    `subject_id` 는 객체 레코드 식별자다(`dd.OBJECT_ID`) — 장치 개체가 아니다. 이
    결과에는 `device_id` 칸이 없고, 없는 것이 설계다.
    """

    subject_id: str
    state: ProxyState
    proxy: ProxyAsset | None
    reason: str
    #: 이 선택이 **무엇을 근거로** 섰는가. 상태가 ABSENT 일 때도 남는다.
    grounds: KindClaim | None
    placement: ProxyPlacement
    fit: SizeFit
    #: 같은 종류를 대신할 수 있었던 다른 자산들(결정적 순서).
    alternatives: tuple[str, ...] = ()
    #: 그 종류의 대역이지만 지금 쓸 수 없었던 자산 → 사유.
    unfit: Mapping[str, str] = field(default_factory=dict)
    #: 선택한 자산의 파일이 자산 뿌리에 있는가. **None 은 확인하지 못한 것**이다.
    asset_present: bool | None = None
    revision: int = 1
    #: 이 선택이 대체한 것. None 이면 바뀐 것이 없다.
    superseded: Supersession | None = None
    #: 이전 선택 그대로. 체인이고 **덮어쓰기가 아니다**.
    previous: "ProxyResolution | None" = field(default=None, repr=False, compare=False)
    resolved_at: float = 0.0

    @property
    def resolved(self) -> bool:
        return self.state is ProxyState.RESOLVED

    @property
    def proxy_id(self) -> str | None:
        return None if self.proxy is None else self.proxy.proxy_id

    @property
    def changed(self) -> bool:
        """이전 선택과 다른가. 화면이 모양을 다시 세워야 하는지의 유일한 근거다."""
        return self.superseded is not None

    def history(self) -> tuple["ProxyResolution", ...]:
        """최신부터 거슬러 올라간 선택 이력. 각 항목은 당시 그대로다."""
        chain: list[ProxyResolution] = []
        node: ProxyResolution | None = self
        while node is not None:
            chain.append(node)
            node = node.previous
        return tuple(chain)

    def as_dict(self) -> dict:
        """화면이 "무엇을, 어떤 근거로 그리는가" 를 세우는 데 필요한 것 전부.

        고른 이유와 **고르지 못한 이유**(종류 미확정, 대역 없음, 자산 결손)를 같은
        묶음에 넣는다 — 나누면 화면은 확정만 그리게 되고 나머지는 빈칸이 된다.
        """
        payload = {
            dd.OBJECT_ID: self.subject_id,
            dd.PROXY_STATE: self.state.value,
            dd.PROXY_REASON: self.reason,
            dd.PROXY_REVISION: self.revision,
            dd.PROXY_ALTERNATIVES: list(self.alternatives),
            dd.UNFIT_PROXIES: dict(self.unfit),
            dd.ASSET_PRESENT: self.asset_present,
            "grounds": None if self.grounds is None else self.grounds.as_dict(),
            "placement": self.placement.as_dict(),
            "size_fit": self.fit.as_dict(),
            "superseded": None if self.superseded is None else self.superseded.as_dict(),
        }
        payload.update(self.proxy.as_dict() if self.proxy is not None
                       else {dd.PROXY_ID: None})
        return payload


# ---------------------------------------------------------------------------
# 선택기
# ---------------------------------------------------------------------------


@dataclass
class ProxyResolver:
    """종류 근거 하나를 대역 선언으로 환산한다. 상태를 바꾸지 않는다.

    `asset_root` 가 None 이면 자산 존재를 **확인하지 않는다** — 확인하지 못한 것을
    '없다' 로 적으면 공개 트리만 받은 노드에서 모든 대역이 사라진다. 배포 기본값
    (`$MISSION_RUNTIME_ASSETS`, 기본 `../local`)을 쓰려면 `resolver_from_catalog()`
    를 쓰거나 `default_asset_root()` 를 직접 넘긴다.
    """

    catalog: ProxyCatalog
    #: None 은 **뿌리 없음**이고, 그때 자산 존재는 모름으로 남는다.
    asset_root: Path | None = None
    size_tolerance: float = DEFAULT_SIZE_TOLERANCE
    #: 자산 파일이 없는 대역을 후보에서 빼는가. 뿌리가 없으면 이 값과 무관하게
    #: 확인하지 않는다(모름은 결손이 아니다).
    require_asset_file: bool = True

    def resolve(
        self,
        subject_id: str,
        claim: KindClaim,
        *,
        placement: ProxyPlacement,
        measured_extent_m: float | None = None,
        previous: ProxyResolution | None = None,
        resolved_at: float = 0.0,
    ) -> ProxyResolution:
        """지금 아는 것으로 대역을 고른다. 근거가 바뀌면 다시 불러도 된다.

        이전 결과를 넘기면 그것을 **덮지 않고** 체인으로 잇고, 선택이 바뀐 경우에만
        `superseded` 에 사유를 적는다.
        """
        candidates = () if claim.kind is None else self.catalog.for_kind(claim.kind)
        unfit = {}
        fit_candidates: list[ProxyAsset] = []
        for asset in candidates:
            present = asset.asset_present(self.asset_root)
            if present is False and self.require_asset_file:
                unfit[asset.proxy_id] = UNFIT_ASSET_FILE_MISSING
                continue
            fit_candidates.append(asset)

        chosen = fit_candidates[0] if fit_candidates else None
        state = ProxyState.RESOLVED if chosen is not None else ProxyState.ABSENT
        reason = self._reason(claim, chosen, candidates, unfit)
        fit = compare_extent(None if chosen is None else chosen.extent_m,
                             measured_extent_m, tolerance=self.size_tolerance)

        result = ProxyResolution(
            subject_id=subject_id,
            state=state,
            proxy=chosen,
            reason=reason,
            grounds=claim,
            placement=placement,
            fit=fit,
            alternatives=tuple(a.proxy_id for a in fit_candidates[1:]),
            unfit=unfit,
            asset_present=(None if chosen is None
                           else chosen.asset_present(self.asset_root)),
            revision=1 if previous is None else previous.revision,
            previous=previous,
            resolved_at=resolved_at,
        )
        if previous is None:
            return result
        return self._link(previous, result, resolved_at=resolved_at)

    # -- 내부 ------------------------------------------------------------

    def _reason(self, claim: KindClaim, chosen: ProxyAsset | None,
                candidates: Sequence[ProxyAsset], unfit: Mapping[str, str]) -> str:
        if chosen is not None:
            return REASON_STANDS_IN_FOR_KIND
        if not claim.established:
            # 종류가 안 가려진 것은 대역의 실패가 아니다. 사유를 종류 쪽에 둔다.
            return REASON_KIND_NOT_ESTABLISHED
        if not self.catalog.available:
            return REASON_NO_CATALOG
        if candidates and unfit:
            # 대역은 **있는데** 자산 파일이 없다. "없는 종류" 와 다른 사실이다.
            return REASON_EVERY_STAND_IN_UNFIT
        return REASON_NO_STAND_IN_FOR_KIND

    @staticmethod
    def _link(previous: ProxyResolution, current: ProxyResolution, *,
              resolved_at: float) -> ProxyResolution:
        """이전 선택과 이번 선택을 잇는다. **이전 객체는 손대지 않는다.**"""
        previous_kind = None if previous.grounds is None else previous.grounds.kind
        current_kind = None if current.grounds is None else current.grounds.kind
        if previous.proxy_id == current.proxy_id and previous.state is current.state:
            # 바뀐 것이 없으면 회차를 올리지 않는다 — 올리면 "모양이 바뀌었다" 가
            # 매 관측마다 참이 되고 화면은 쉬지 않고 다시 세운다.
            return current
        if previous.resolved and current.resolved:
            reason = (SUPERSEDE_KIND_CHANGED if previous_kind != current_kind
                      else SUPERSEDE_OTHER_STAND_IN)
        elif previous.resolved:
            reason = SUPERSEDE_STAND_IN_LOST
        else:
            reason = SUPERSEDE_STAND_IN_FOUND
        return replace(
            current,
            revision=previous.revision + 1,
            superseded=Supersession(previous_proxy_id=previous.proxy_id,
                                    previous_kind=previous_kind,
                                    reason=reason, at=resolved_at),
        )


def resolver_from_catalog(path: str | Path, **kwargs: Any) -> ProxyResolver:
    """카탈로그 파일과 배포 기본 자산 뿌리로 선택기를 만든다.

    파일이 없어도 선택기는 만들어진다 — 그때는 모든 객체가
    `ABSENT`(`no_proxy_catalog`)이고 **자리는 그대로 나간다**(AI-C-05).
    """
    kwargs.setdefault("asset_root", default_asset_root())
    return ProxyResolver(ProxyCatalog.load(path), **kwargs)


def catalog_licenses(catalog: ProxyCatalog) -> dict[str, str]:
    """자산별 라이선스 선언. 운영자가 "이 화면의 모양들은 어디서 왔나" 를 묻는 자리.

    확인되지 않은 것은 `unknown` 으로 **그대로** 남는다 — 모르는 것을 공개로 적지
    않는다(config/label_sources.example.json 과 같은 규약).
    """
    return {asset.proxy_id: asset.license for asset in catalog.proxies}


def unlicensed_proxies(catalog: ProxyCatalog) -> tuple[str, ...]:
    """라이선스가 확인되지 않은 자산들. 거절 사유가 아니라 **드러내는 사실**이다."""
    return tuple(sorted(a.proxy_id for a in catalog.proxies if not a.license_known))


def proxy_kinds_without_stand_in(catalog: ProxyCatalog,
                                 kinds: Iterable[str]) -> tuple[str, ...]:
    """그 종류들 중 대역이 없는 것. 카탈로그에 무엇을 더해야 하는지의 목록이다."""
    return tuple(sorted(k for k in kinds if not catalog.for_kind(k)))
