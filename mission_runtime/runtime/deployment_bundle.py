"""새 기능·새 모델을 **선언 한 건**으로 배포 후보로 만든다 — 코드 변경이 아니다.

implements: AI-B-02 (실행환경 패키징·재현성), AI-B-11 (복수 실행영역 통합 실행관리),
            AI-C-16 (폐쇄망 배포 경계)
관련: AI-B-04 (required/preferred 자원), AI-B-05, AI-B-09 (어댑터·등록만으로 확장),
      AI-C-04 (provider 경계), AI-C-05, AI-L-10
tests: tests/test_deployment_bundle.py

이 모듈이 메우는 공백
---------------------
`runtime/mlops_pipeline.py` 의 `Deployable` 은 이미 선언만으로 이루어진 자료형이고
실행영역을 태그로 찾는다. 그런데 **그것을 만드는 자리가 코드 안에만 있었다** —
`tools/fms_console/deployment.py::deployable_for()` 가 `required_tags=("zone-edge",)`
와 `control_params={"device_id": ...}` 를 손으로 짜 넣는다. 그 결과 두 가지가
비어 있었다.

1. **이미지 참조가 아무 데도 선언되지 않는다.** `providers/k3s.py::_start` 는
   `params["image"]` 가 없으면 `missing_image` 로 거절한다. 즉 선언 경로로 들어온
   배포는 K3s 실행영역에서 **한 번도 뜰 수 없었다**. 로컬 supervisor 는 params 를
   무시하므로 시험은 통과했고, 그래서 이 구멍이 보이지 않았다.
2. **이미지 저장소가 폐쇄망 판정을 지나지 않는다.** `AirgapPolicy` 는
   `Deployable.external_dependencies` 만 본다. AI-C-16 은 "실행에 필요한
   **이미지**·모델·패키지·규칙을 내부 저장소에서 조달"하라고 **이미지를 먼저**
   적는데, 그 이미지가 `docker.io` 를 가리켜도 배치 전에 걸리는 곳이 없었다.

두 번째 판정 기구를 만들지 않는다
---------------------------------
폐쇄망 판정을 여기서 다시 하지 않는다. 대신 선언에서 이미지 저장소를
**비선택 외부 의존 1건**(`ExternalDependency(optional=False)`)으로 내보내고, 기존
`AirgapPolicy` 가 그것을 보고 배치 전에 `REFUSE_EGRESS_REQUIRED` 로 거절한다.
`optional=False` 인 이유: 이미지를 못 받으면 그 실행 단위는 축소 운용이 아니라
아예 뜨지 못한다. 선택 의존으로 적으면 "꺼진 선택 기능" 으로 조용히 넘어가고,
배치는 성공했는데 아무것도 돌지 않는 상태가 된다.

마찬가지로 배정(`ModelAssigner`)·실행영역 해소(`MultiClusterControlProvider`)·
계보(`LearningLineage`)는 손대지 않는다. 이 모듈은 **선언 → 선언** 변환뿐이고
판정이 없다.

오케스트레이터를 전제하지 않는다
--------------------------------
`control_params` 의 칸 이름(`image` · `node_selector` · `image_pull_secrets` …)은
`Deployable` 이 docstring 에 적어 둔 그대로 "현재 provider 가 해석하는 값이 그대로
지나가는 통로" 다. `LocalControlSupervisor` 는 params 를 아예 읽지 않으므로 같은
선언이 양쪽 실행영역에서 그대로 쓰인다(AI-B-11). 다른 오케스트레이터 provider 가
다른 칸 이름을 원하면 `DeploymentBundle` 의 의미 칸(`image` · `node_labels` …)을
직접 읽어 자기 어휘로 옮기면 되고, 그때 이 파일은 바뀌지 않는다.

자격증명은 선언에 담지 않는다
-----------------------------
AI-B-02: "자격증명·비밀정보를 이미지에 포함해서는 안 된다". `image_pull_secrets` 와
`service_account` 는 **이름만** 이고 값은 실행영역이 들고 있다. 선언 파일에 토큰이
들어오면 `load_bundles` 가 거절한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from mission_runtime.runtime.airgap import AssetRef, AssetResolver, ExternalDependency, ResolvedAsset
from mission_runtime.runtime.clusters import PlacementRequest
from mission_runtime.runtime.mlops_pipeline import Deployable

#: 선언이 거절된 사유 토큰. `':'` 앞이 토큰, 뒤가 자료다(기존 규약).
REASON_MISSING_FIELD = "bundle_missing_required_field"
REASON_IMAGE_NOT_PINNED = "image_not_pinned_to_digest"
REASON_DUPLICATE_BUNDLE = "duplicate_bundle_id"
REASON_SECRET_IN_DECLARATION = "secret_value_in_declaration"
REASON_UNKNOWN_BUNDLE = "unknown_bundle_id"

BUNDLE_REASONS: tuple[str, ...] = (
    REASON_MISSING_FIELD,
    REASON_IMAGE_NOT_PINNED,
    REASON_DUPLICATE_BUNDLE,
    REASON_SECRET_IN_DECLARATION,
    REASON_UNKNOWN_BUNDLE,
)

#: 저장소를 적지 않은 이미지 참조가 실제로 가리키는 곳. 폐쇄망에서 이것이
#: 조용히 통과하면 안 되므로 **명시적인 이름으로 바꿔** 외부 의존으로 내보낸다.
IMPLICIT_REGISTRY = "docker.io"

#: 이미지 저장소 의존의 용도 토큰. 화면·감사가 다른 외부 의존과 구분한다.
PURPOSE_CONTAINER_IMAGE = "container_image"

#: 선언 파일에 있어서는 안 되는 칸 이름의 조각. 값이 아니라 **이름**으로 막는다 —
#: 값으로 추측하면 멀쩡한 설정을 비밀로 오해한다.
_SECRET_NAME_MARKERS = ("password", "passwd", "secret_value", "token", "api_key",
                        "apikey", "private_key", "credential")


class BundleDeclarationError(ValueError):
    """선언 파일이 배포 후보가 될 수 없다. **배치 전에** 터진다(AI-C-16)."""


# -- 이미지 참조 --------------------------------------------------------------


@dataclass(frozen=True)
class ImageRef:
    """컨테이너 이미지 참조 하나. 저장소·고정 여부를 **읽어서** 말한다.

    OCI Image Specification 의 content-addressable descriptor 가 AI-B-02 가 말하는
    "식별 가능한 무결성 정보" 의 선례다. digest 로 고정되지 않은 태그는 같은 이름이
    다른 내용을 가리킬 수 있으므로 재현 가능한 배포의 근거가 되지 못한다.
    """

    reference: str

    def __post_init__(self) -> None:
        if not self.reference or not self.reference.strip():
            raise BundleDeclarationError(f"{REASON_MISSING_FIELD}:image")

    @property
    def registry(self) -> str:
        """이미지를 받아 올 저장소. 적지 않았으면 암시적 공개 저장소다.

        구별 규칙은 OCI/Docker 참조 문법 그대로다 — 첫 조각에 `.` 나 `:` 가 있거나
        `localhost` 면 그것이 저장소이고, 아니면 저장소를 적지 않은 것이다.
        """
        head = self.reference.split("/", 1)
        if len(head) == 1:
            return IMPLICIT_REGISTRY
        first = head[0]
        if "." in first or ":" in first or first == "localhost":
            return first
        return IMPLICIT_REGISTRY

    @property
    def digest(self) -> str | None:
        _, _, tail = self.reference.partition("@")
        return tail or None

    @property
    def tag(self) -> str | None:
        if self.digest:
            return None
        last = self.reference.rsplit("/", 1)[-1]
        _, _, tail = last.partition(":")
        return tail or None

    @property
    def pinned(self) -> bool:
        """내용으로 고정됐는가. 태그만 있으면 아니다."""
        return self.digest is not None


# -- 선언 ---------------------------------------------------------------------


@dataclass(frozen=True)
class DeploymentBundle:
    """실행 단위 하나의 배포 선언. **전부 자료이고 판정이 없다.**

    새 기능·새 모델은 이 자료형 한 건을 선언 파일에 더하는 것이고, 어느 모듈도
    고치지 않는다(AI-B-09 와 같은 확장 방식).
    """

    bundle_id: str
    capability_kind: str
    image: ImageRef
    #: 실행영역을 고르는 **유일한** 입력. 클러스터 이름도 노드 이름도 들어가지 않는다.
    required_tags: frozenset[str] = frozenset()
    preferred_tags: frozenset[str] = frozenset()
    #: 노드 수준 배치 조건. 오케스트레이터가 노드 라벨로 해석한다(AI-B-04).
    node_labels: Mapping[str, str] = field(default_factory=dict)
    #: 실행에 필요한 내부 자산(모델 가중치·규칙·지도). 폐쇄망에서 내부 저장소로
    #: 해소된다(AI-C-16).
    assets: tuple[AssetRef, ...] = ()
    #: 이미지 저장소 **외의** 선언된 외부 연결. 기본은 선택(축소 가능)이다.
    external_dependencies: tuple[ExternalDependency, ...] = ()
    #: digest 고정을 요구하는가. 기본은 요구한다(AI-B-02).
    require_digest: bool = True
    core: bool = False
    command: tuple[str, ...] = ()
    #: 이름만 싣는다. 값은 실행영역이 들고 있다.
    image_pull_secrets: tuple[str, ...] = ()
    service_account: str | None = None
    #: 컨테이너 보안 맥락. 필요한 권한만 요청한다(AI-B-04).
    security_context: Mapping[str, Any] = field(default_factory=dict)
    #: 사람이 읽는 메모. 어느 판정에도 쓰이지 않는다.
    note: str = ""

    def __post_init__(self) -> None:
        if not self.bundle_id or not self.capability_kind:
            raise BundleDeclarationError(
                f"{REASON_MISSING_FIELD}:bundle_id_and_capability_kind"
            )
        if self.require_digest and not self.image.pinned:
            raise BundleDeclarationError(
                f"{REASON_IMAGE_NOT_PINNED}:{self.image.reference}"
            )

    # -- 선언 → 선언 ------------------------------------------------------

    @property
    def placement(self) -> PlacementRequest:
        return PlacementRequest(
            required_tags=frozenset(self.required_tags),
            preferred_tags=frozenset(self.preferred_tags),
        )

    @property
    def image_dependency(self) -> ExternalDependency:
        """이미지 저장소를 외부 의존 1건으로. **비선택**이다.

        이미지를 못 받으면 축소 운용이 아니라 뜨지 못한다. 그래서 선택으로 적지
        않고, 폐쇄망 프로파일에서 내부 저장소가 아니면 `AirgapPolicy` 가 배치를
        막는다(AI-C-16). 저장소가 내부면 그 정책이 그냥 지나친다 — 이 모듈이
        "내부인가"를 판정하지 않는 것이 요점이다.
        """
        return ExternalDependency(
            endpoint=self.image.registry,
            purpose=PURPOSE_CONTAINER_IMAGE,
            optional=False,
        )

    def control_params(self, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """provider 로 그대로 지나가는 값. 칸 이름은 현재 provider 의 어휘다.

        `extra` 는 배포마다 다른 값(예: `device_id`)의 자리다 — 선언 파일에 기기
        이름을 적으면 같은 기능을 다른 기기에 올릴 때마다 선언이 하나씩 늘어난다.
        """
        params: dict[str, Any] = {
            "image": self.image.reference,
            "require_image_digest": bool(self.require_digest),
        }
        if self.node_labels:
            params["node_selector"] = dict(self.node_labels)
        if self.command:
            params["command"] = list(self.command)
        if self.image_pull_secrets:
            params["image_pull_secrets"] = list(self.image_pull_secrets)
        if self.service_account:
            params["service_account"] = self.service_account
        if self.security_context:
            params["security_context"] = dict(self.security_context)
        if extra:
            params.update(extra)
        return params

    def to_deployable(
        self,
        *,
        deployable_id: str | None = None,
        control_params: Mapping[str, Any] | None = None,
    ) -> Deployable:
        """선언을 기존 배포 경로의 자료형으로 올린다.

        여기서 새 상태도 새 식별자 규칙도 만들지 않는다 — `MlopsPipeline` 이
        `unit_id_for()` 로 버전까지 포함한 단위 이름을 만들고, 이 자료형은 그 앞
        단계의 선언일 뿐이다.
        """
        return Deployable(
            deployable_id=deployable_id or self.bundle_id,
            capability_kind=self.capability_kind,
            placement=self.placement,
            external_dependencies=(self.image_dependency, *self.external_dependencies),
            control_params=self.control_params(control_params),
            core=self.core,
        )

    def resolve_assets(self, resolver: AssetResolver) -> tuple[ResolvedAsset, ...]:
        """선언된 자산을 내부 저장소 위치로 해소한다(AI-C-16).

        공개 위치로 풀리는 자산은 `AirgapViolation` 으로 터진다 — 그 판정도
        `AssetResolver` 의 것이고 여기서 다시 하지 않는다.
        """
        return tuple(resolver.resolve(asset) for asset in self.assets)


# -- 선언 파일 ----------------------------------------------------------------

#: 선언 파일의 기본 자리. **자료다** — 새 기능은 이 파일에 한 건 더하는 것이다.
BUNDLES_FILE = "bundles.example.json"


def bundle_from_dict(raw: Mapping[str, Any]) -> DeploymentBundle:
    """선언 한 건을 자료형으로. 모르는 칸은 무시하고 비밀은 거절한다."""
    _reject_secrets(raw)
    missing = [key for key in ("bundle_id", "capability_kind", "image") if not raw.get(key)]
    if missing:
        raise BundleDeclarationError(f"{REASON_MISSING_FIELD}:{','.join(missing)}")

    assets = tuple(
        AssetRef(
            asset_id=str(row["asset_id"]),
            kind=str(row.get("kind") or "generic"),
            version=None if row.get("version") is None else str(row["version"]),
        )
        for row in raw.get("assets") or ()
        if isinstance(row, Mapping) and row.get("asset_id")
    )
    dependencies = tuple(
        ExternalDependency(
            endpoint=str(row["endpoint"]),
            purpose=str(row.get("purpose") or ""),
            # 선언하지 않으면 선택이다 — AI-C-16 이 외부 서비스에 요구하는 기본값.
            optional=bool(row.get("optional", True)),
        )
        for row in raw.get("external_dependencies") or ()
        if isinstance(row, Mapping) and row.get("endpoint")
    )
    labels = raw.get("node_labels")
    security = raw.get("security_context")

    return DeploymentBundle(
        bundle_id=str(raw["bundle_id"]),
        capability_kind=str(raw["capability_kind"]),
        image=ImageRef(str(raw["image"])),
        required_tags=frozenset(str(t) for t in raw.get("required_tags") or ()),
        preferred_tags=frozenset(str(t) for t in raw.get("preferred_tags") or ()),
        node_labels={str(k): str(v) for k, v in (labels or {}).items()}
        if isinstance(labels, Mapping) else {},
        assets=assets,
        external_dependencies=dependencies,
        require_digest=bool(raw.get("require_digest", True)),
        core=bool(raw.get("core", False)),
        command=tuple(str(c) for c in raw.get("command") or ()),
        image_pull_secrets=tuple(str(s) for s in raw.get("image_pull_secrets") or ()),
        service_account=(None if raw.get("service_account") is None
                         else str(raw["service_account"])),
        security_context=dict(security) if isinstance(security, Mapping) else {},
        note=str(raw.get("note") or raw.get("$comment") or ""),
    )


def bundles_from_dict(raw: Mapping[str, Any]) -> tuple[DeploymentBundle, ...]:
    """선언 파일 전체를 자료형으로. 같은 `bundle_id` 가 두 번 나오면 거절한다.

    중복을 조용히 덮어쓰면 "무엇이 올라가는가" 가 파일 순서에 달리게 된다.
    """
    bundles: list[DeploymentBundle] = []
    seen: set[str] = set()
    for entry in raw.get("bundles") or ():
        if not isinstance(entry, Mapping):
            raise BundleDeclarationError(f"{REASON_MISSING_FIELD}:bundle_entry")
        bundle = bundle_from_dict(entry)
        if bundle.bundle_id in seen:
            raise BundleDeclarationError(f"{REASON_DUPLICATE_BUNDLE}:{bundle.bundle_id}")
        seen.add(bundle.bundle_id)
        bundles.append(bundle)
    return tuple(bundles)


def load_bundles(path: Path) -> tuple[DeploymentBundle, ...]:
    """선언 파일을 읽는다. 파일이 없으면 **빈 묶음**이고 예외가 아니다.

    선언이 없는 배치는 정상이다 — 배포 관리 기능이 없는 실행영역이 있고, 그곳에서
    이 경로는 그냥 비어 있어야 한다(AI-C-05).
    """
    path = Path(path)
    if not path.is_file():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise BundleDeclarationError(f"{REASON_MISSING_FIELD}:{path.name}") from error
    if not isinstance(raw, Mapping):
        raise BundleDeclarationError(f"{REASON_MISSING_FIELD}:{path.name}")
    return bundles_from_dict(raw)


@dataclass(frozen=True)
class BundleRegistry:
    """선언된 묶음들. 기능(capability kind)으로 찾는다 — 이름으로 찾지 않는다."""

    bundles: tuple[DeploymentBundle, ...] = ()

    @classmethod
    def from_file(cls, path: Path) -> "BundleRegistry":
        return cls(load_bundles(path))

    def ids(self) -> tuple[str, ...]:
        return tuple(b.bundle_id for b in self.bundles)

    def get(self, bundle_id: str) -> DeploymentBundle:
        for bundle in self.bundles:
            if bundle.bundle_id == bundle_id:
                return bundle
        raise KeyError(f"{REASON_UNKNOWN_BUNDLE}:{bundle_id}")

    def for_kind(self, capability_kind: str) -> tuple[DeploymentBundle, ...]:
        """그 기능을 제공하는 묶음들. **없으면 빈 묶음**이고 그것이 사유가 된다."""
        return tuple(b for b in self.bundles if b.capability_kind == capability_kind)

    def external_registries(self, resolver: AssetResolver) -> tuple[str, ...]:
        """내부 저장소가 아닌 이미지 저장소들. 폐쇄망 배치 **전** 점검용이다.

        판정은 `AssetResolver.is_internal` 이 하고 이 함수는 모으기만 한다.
        """
        found = {
            bundle.image.registry
            for bundle in self.bundles
            if not resolver.is_internal(bundle.image.registry)
        }
        return tuple(sorted(found))

    def unpinned(self) -> tuple[str, ...]:
        """digest 로 고정되지 않은 이미지를 선언한 묶음들.

        `require_digest=False` 로 **일부러** 고정을 면제한 선언만 여기 나온다 —
        면제가 조용히 넘어가지 않아야 재현성 이탈을 배치 전에 볼 수 있다(AI-B-02).
        """
        return tuple(sorted(b.bundle_id for b in self.bundles if not b.image.pinned))


def _reject_secrets(raw: Mapping[str, Any]) -> None:
    """선언 안에 비밀 값이 들어온 것을 칸 이름으로 잡는다(AI-B-02)."""
    for key, value in raw.items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in _SECRET_NAME_MARKERS):
            raise BundleDeclarationError(f"{REASON_SECRET_IN_DECLARATION}:{key}")
        if isinstance(value, Mapping):
            _reject_secrets(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Mapping):
                    _reject_secrets(item)


def declared_assets(bundles: Iterable[DeploymentBundle]) -> tuple[AssetRef, ...]:
    """선언된 자산 전부. 폐쇄망 조달 점검의 입력이다(AI-C-16)."""
    seen: dict[tuple[str, str, str | None], AssetRef] = {}
    for bundle in bundles:
        for asset in bundle.assets:
            seen[(asset.asset_id, asset.kind, asset.version)] = asset
    return tuple(seen[key] for key in sorted(seen, key=lambda k: (k[0], k[1], k[2] or "")))


def deployables_for(
    bundles: Sequence[DeploymentBundle],
    *,
    device_id: str | None = None,
) -> tuple[Deployable, ...]:
    """묶음들을 배포 후보로. `device_id` 는 선언이 아니라 배포마다의 값이다."""
    extra = {"device_id": device_id} if device_id else None
    suffix = f"@{device_id}" if device_id else ""
    return tuple(
        bundle.to_deployable(
            deployable_id=f"{bundle.bundle_id}{suffix}", control_params=extra
        )
        for bundle in bundles
    )
