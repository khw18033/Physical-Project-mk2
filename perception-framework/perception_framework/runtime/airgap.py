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
3. `EgressGate` — applies the same rule to a provider's *registration*
   (`CompatibilityProfile.external_endpoints`), so a candidate that needs
   outbound reach is filtered out during selection, before placement.
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


# ---------------------------------------------------------------------------
# Registration-level egress gate (AI-C-16)
#
# `AirgapPolicy` above works on an execution unit's declared dependency list.
# The gate below applies the same rule to what a provider *registered* in its
# `CompatibilityProfile`, so the check happens while candidates are being
# filtered — i.e. before placement — and upper-layer code gets nothing but a
# shorter candidate list (no domain branch, no protocol knowledge).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EgressGate:
    """Decides whether a registered provider's declared reach is allowed here.

    implements: AI-C-16

    `internal_endpoints` is deployment data: host names, host:port pairs or
    domain suffixes this deployment counts as inside the closed network. No
    protocol or vendor is named in code (절대 준수 원칙 #1).
    """

    closed_network: bool = True
    internal_endpoints: frozenset[str] = frozenset()

    @classmethod
    def from_profile(cls, profile) -> "EgressGate":
        """Build the gate straight out of a `DeploymentProfile`.

        Kept duck-typed so `contracts.profile` never has to import runtime
        code (the dependency only ever points this way).
        """
        return cls(
            closed_network=bool(getattr(profile, "closed_network", True)),
            internal_endpoints=frozenset(getattr(profile, "internal_endpoints", ()) or ()),
        )

    def is_internal(self, endpoint: str) -> bool:
        raw = (endpoint or "").strip().lower()
        if not raw:
            return True
        if raw in self.internal_endpoints:
            return True
        parsed = urlparse(raw if "://" in raw else f"//{raw}", scheme="")
        host = (parsed.hostname or "").lower()
        if not host:
            # A bare name with no host component (e.g. a local service name)
            # is only internal if the deployment declared it as such.
            return raw in self.internal_endpoints
        if host in INTERNAL_MARKERS or host in self.internal_endpoints:
            return True
        return any(
            host.endswith(marker) for marker in self.internal_endpoints if marker.startswith(".")
        )

    def external_endpoints_of(self, compatibility) -> tuple[str, ...]:
        declared = tuple(getattr(compatibility, "external_endpoints", ()) or ())
        return tuple(ep for ep in declared if not self.is_internal(ep))

    def evaluate(self, unit_id: str, compatibility) -> PlacementVerdict:
        """Pre-placement verdict for one registration.

        In a closed-network profile a provider that reaches outside is not
        placed. If it declared the reach as optional (the default, and what
        AI-C-16 mandates for external-service capabilities) it is simply
        dropped from the candidate set — an ordinary reduction. If it
        declared it as non-optional, that is a declaration error surfaced
        before placement, not a runtime failure.
        """
        unreachable = self.external_endpoints_of(compatibility)
        if not unreachable or not self.closed_network:
            return PlacementVerdict(unit_id, True)
        optional = bool(getattr(compatibility, "external_optional", True))
        if optional:
            return PlacementVerdict(unit_id, False, disabled_optional=unreachable)
        return PlacementVerdict(unit_id, False, blocking_dependencies=unreachable)

    def rejection_reason(self, registration) -> str | None:
        """`None` if this registration may be placed, else why not.

        Shaped as a placement filter for `CapabilitySelector`, which only
        ever sees an opaque reason string.
        """
        verdict = self.evaluate(getattr(registration, "provider_id", "?"), registration.compatibility)
        if verdict.placeable:
            return None
        if verdict.blocking_dependencies:
            return "external_connection_required_in_closed_network"
        return "external_connection_unavailable_in_closed_network"

    def assert_declarations(self, registrations) -> None:
        """Fail a closed-network deployment that registered a provider whose
        external reach is declared non-optional (AI-C-16: 배치 전에 검출).
        """
        offenders = [
            getattr(r, "provider_id", "?")
            for r in registrations
            if self.evaluate(getattr(r, "provider_id", "?"), r.compatibility).blocking_dependencies
        ]
        if offenders:
            raise AirgapViolation(
                "closed-network profile rejects non-optional external connections: "
                f"{sorted(offenders)}"
            )
