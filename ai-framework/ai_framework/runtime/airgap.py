"""Air-gapped (폐쇄망) operating boundary: no public-internet egress is a
precondition for anything the system must be able to do.

implements: AI-C-16, AI-B-09, AI-C-09

원칙 #18: 실행에 필요한 이미지·모델·패키지·규칙은 내부 저장소에서 조달하고,
공개 인터넷에 대한 나가는 연결을 기능 동작의 전제로 두지 않는다.

Two mechanisms, both checked *before* placement so a security boundary is
never discovered at runtime (AI-C-16):

1. `AssetResolver` — turns a logical asset id into an internal-repository
   reference and refuses public locations outright.
2. `AirgapPolicy` — inspects declared external endpoints of execution
   units and reports which ones cannot be placed in this profile, while
   allowing units that declare the dependency as *optional*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

# Hosts/schemes that mean "this leaves the closed network". Kept as data so
# a deployment can extend it without touching logic.
PUBLIC_SCHEMES = frozenset({"http", "https", "ftp", "git"})
INTERNAL_MARKERS = frozenset({"localhost", "127.0.0.1", "::1"})


class AirgapViolation(RuntimeError):
    """Raised when a closed-network deployment is asked for public egress."""


@dataclass(frozen=True)
class AssetRef:
    """One externally-sourced artifact an execution unit needs.

    `asset_id` is logical (e.g. "model:detector@3"); the location is
    resolved per deployment, so the same unit runs on an internet-connected
    development box and in a closed network without code changes.
    """

    asset_id: str
    kind: str = "generic"  # image / model / rules / map / package ...
    version: str | None = None


@dataclass(frozen=True)
class ResolvedAsset:
    asset_id: str
    location: str
    internal: bool


@dataclass
class AssetResolver:
    """Resolves logical asset ids against an internal repository only.

    `internal_hosts` names the repositories this deployment trusts. A
    location outside that set is refused rather than fetched, so an
    accidental public dependency fails closed (AI-C-16).
    """

    base_locations: dict[str, str] = field(default_factory=dict)  # kind -> internal base
    internal_hosts: frozenset[str] = field(default_factory=frozenset)
    # Closed networks usually own a whole domain suffix rather than a fixed
    # host list, so both forms are accepted as deployment data.
    internal_suffixes: frozenset[str] = field(default_factory=frozenset)
    allow_public: bool = False

    def resolve(self, asset: AssetRef) -> ResolvedAsset:
        base = self.base_locations.get(asset.kind) or self.base_locations.get("generic")
        if base is None:
            raise AirgapViolation(f"no internal source configured for asset kind {asset.kind!r}")

        suffix = f"{asset.asset_id}" + (f":{asset.version}" if asset.version else "")
        location = f"{base.rstrip('/')}/{suffix}"
        internal = self.is_internal(location)
        if not internal and not self.allow_public:
            raise AirgapViolation(f"asset {asset.asset_id!r} resolves outside the closed network: {location}")
        return ResolvedAsset(asset.asset_id, location, internal)

    def is_internal(self, location: str) -> bool:
        parsed = urlparse(location if "://" in location else f"//{location}", scheme="")
        host = (parsed.hostname or "").lower()
        if not host:
            return True  # a bare path is local by construction
        if host in INTERNAL_MARKERS or host in self.internal_hosts:
            return True
        return any(host.endswith(suffix) for suffix in self.internal_suffixes)


@dataclass(frozen=True)
class ExternalDependency:
    """A declared outbound connection an execution unit wants.

    `optional=True` means the unit runs without it in reduced form — which
    is what AI-C-16 requires of every external-service capability.
    """

    endpoint: str
    purpose: str = ""
    optional: bool = True


@dataclass(frozen=True)
class PlacementVerdict:
    unit_id: str
    placeable: bool
    blocking_dependencies: tuple[str, ...] = ()
    disabled_optional: tuple[str, ...] = ()


class AirgapPolicy:
    """Validates declared egress before an execution unit is placed."""

    def __init__(self, resolver: AssetResolver, *, closed_network: bool = True) -> None:
        self._resolver = resolver
        self._closed = closed_network

    def evaluate(self, unit_id: str, dependencies: list[ExternalDependency]) -> PlacementVerdict:
        if not self._closed:
            return PlacementVerdict(unit_id, True)

        blocking, disabled = [], []
        for dependency in dependencies:
            if self._resolver.is_internal(dependency.endpoint):
                continue
            if dependency.optional:
                # 외부 서비스 provider는 항상 선택 기능이며 사용할 수 없으면
                # 해당 기능만 비활성화한다 (원칙 #18).
                disabled.append(dependency.endpoint)
            else:
                blocking.append(dependency.endpoint)

        return PlacementVerdict(
            unit_id,
            placeable=not blocking,
            blocking_dependencies=tuple(blocking),
            disabled_optional=tuple(disabled),
        )

    def assert_placeable(self, unit_id: str, dependencies: list[ExternalDependency]) -> PlacementVerdict:
        verdict = self.evaluate(unit_id, dependencies)
        if not verdict.placeable:
            raise AirgapViolation(
                f"{unit_id} requires public egress to {list(verdict.blocking_dependencies)}"
            )
        return verdict
