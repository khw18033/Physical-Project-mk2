"""Execution compatibility, resource budget and deployment profile.

implements: AI-B-01, AI-B-04, AI-B-06, AI-B-10, AI-C-13, AI-C-15, AI-C-16, AI-N-03

These types stay vendor-neutral on purpose: hardware/runtime conditions
are free-form string tags supplied by whoever registers a provider, not
enum members tied to a specific GPU/NPU/runtime vendor. New hardware or
execution modes are added by registering a new tag + profile, never by
editing this module (절대 준수 원칙 #1, #7).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from mission_runtime.contracts.capability import CapabilityRequirement


@dataclass(frozen=True)
class ResourceCost:
    """Estimated resource footprint of running one provider/config.

    Units are intentionally abstract (`compute_units`) rather than tied
    to a specific accelerator's benchmark, since the same capability can
    be satisfied by a CPU model, a GPU model or a remote call.
    """

    compute_units: float = 0.0
    memory_mb: float = 0.0
    max_latency_ms: float | None = None


@dataclass(frozen=True)
class ResourceBudget:
    """A node's remaining resource budget at selection time (AI-B-06, AI-C-13)."""

    compute_units: float
    memory_mb: float
    max_latency_ms: float | None = None

    def can_afford(self, cost: ResourceCost) -> bool:
        if cost.compute_units > self.compute_units:
            return False
        if cost.memory_mb > self.memory_mb:
            return False
        if (
            cost.max_latency_ms is not None
            and self.max_latency_ms is not None
            and cost.max_latency_ms > self.max_latency_ms
        ):
            return False
        return True


@dataclass(frozen=True)
class CompatibilityProfile:
    """Declares where/how a provider is allowed to run (AI-B-01).

    `required_hw_tags` / `required_runtime_tags` must all be present on
    the executing node for the provider to be eligible at all.
    `preferred_hw_tags` are informative only: their absence must not
    exclude the provider, only lower its effective attractiveness to a
    selector that chooses to weigh preference (AI-B-04: "선호 자원이 없으면
    호환 가능한 일반 자원으로 대체").
    """

    required_hw_tags: tuple[str, ...] = ()
    preferred_hw_tags: tuple[str, ...] = ()
    required_runtime_tags: tuple[str, ...] = ()
    cost: ResourceCost = field(default_factory=ResourceCost)
    priority: int = 100  # lower = tried first / kept longest when degrading (AI-C-13, AI-B-06)

    # --- outbound reach declaration (AI-C-16) ---------------------------
    # Free-form "external reach targets" this provider needs in order to
    # work: a URL, a host:port, a bare hostname, a service name — whatever
    # the deployment uses to name a destination. Deliberately NOT an enum
    # of protocols/vendors (절대 준수 원칙 #1); the closed-network check is
    # performed by a policy that knows which locations this deployment
    # considers internal, not by this dataclass.
    #
    # Default is the empty tuple, i.e. "needs no external connection",
    # so every existing registration keeps its meaning unchanged.
    external_endpoints: tuple[str, ...] = ()
    # AI-C-16: "외부 AI 서비스나 외부 API를 사용하는 기능은 항상 선택 기능으로
    # 선언하고, 사용할 수 없으면 해당 기능만 비활성화". A provider that keeps
    # this True is simply dropped from the candidate set when its reach is
    # unavailable; one that sets it False is declaring that it cannot
    # degrade, which a closed-network profile must reject *before* placement
    # rather than discover as a runtime failure.
    external_optional: bool = True

    def is_compatible(self, node_tags: set[str], budget: ResourceBudget) -> bool:
        if not set(self.required_hw_tags).issubset(node_tags):
            return False
        if not set(self.required_runtime_tags).issubset(node_tags):
            return False
        return budget.can_afford(self.cost)

    def unmet_preferences(self, node_tags: set[str]) -> tuple[str, ...]:
        """Preferred-but-absent tags. Never affects eligibility — only
        ranking among already-compatible candidates (AI-B-04).
        """
        return tuple(tag for tag in self.preferred_hw_tags if tag not in node_tags)

    def preference_penalty(self, node_tags: set[str]) -> int:
        """How many preferred resources this node cannot offer.

        Used as a ranking term so that, given two compatible providers of
        equal priority, the one whose preferred resources are actually
        present wins — and so that a provider that prefers an accelerator
        still runs on a plain CPU node instead of being excluded
        (AI-B-04: "선호 자원이 없으면 호환 가능한 일반 자원으로 대체").
        """
        return len(self.unmet_preferences(node_tags))

    def requires_external_connection(self) -> bool:
        """Whether this provider declared any outbound reach at all.

        Registration information alone must reveal this, so a closed-network
        deployment can detect it before placement (AI-C-16).
        """
        return bool(self.external_endpoints)


@dataclass(frozen=True)
class DeploymentProfile:
    """Binds one domain deployment to adapters/capabilities/rules — data only.

    implements: AI-C-15

    A new domain (robot autonomy support, facility surveillance, river
    risk management, ...) must be expressible entirely as data here:
    which capability kinds are active, which rule set applies, and what
    node tags describe the target execution environment. Core
    perception/decision/risk code must never branch on `domain_id`
    (절대 준수 원칙 #3) — it only ever asks the registry/selector whether a
    capability kind is currently available.
    """

    domain_id: str
    active_capability_kinds: tuple[str, ...]
    rule_set_id: str | None = None
    node_tags: tuple[str, ...] = ()
    # AI-C-16: is this deployment a closed network (폐쇄망)? Defaults to True
    # because 절대 준수 원칙 #18 makes the closed network the operating
    # premise; a development/connected deployment opts out explicitly. It
    # changes nothing for providers that declare no external endpoints,
    # which is the default.
    closed_network: bool = True
    # Locations this deployment counts as inside the closed network. Free-form
    # host names and/or suffixes supplied as deployment data — never compiled
    # into core code.
    internal_endpoints: tuple[str, ...] = ()


# ============================================================================
# 등록된 말단 장치의 "목적"과 "링크 특성" — 온디바이스/엣지 기능 분리의 입력
#
# implements: AI-C-15, AI-C-05, AI-B-04, AI-B-06, AI-B-10, AI-N-03, AI-C-13
#
# `DeploymentProfile`이 "이 배포가 어떤 기능을 쓰는가"를 데이터로 말한다면,
# 아래 타입들은 "등록된 이 장치가 그중 무엇을 **자기 안에** 두어야 하는가"를
# 데이터로 말한다. 판정 로직은 여기 없다 — `runtime/residency.py`가 이 데이터만
# 읽어서 결정하며, 어느 쪽에도 도메인 이름(하천/로봇/시설) 분기가 없다
# (절대 준수 원칙 #3).
#
# 왜 이 층이 필요한가: 상위 코드는 "기능이 있는가/없는가"(AI-C-05)는 이미
# `CapabilityRequirement.evaluate`로 다루지만, "그 기능이 **어디에** 있어야
# 하는가"는 다루지 않았다. 링크가 끊겼을 때 살아남아야 하는 기능과 엣지에
# 물어봐도 되는 기능의 차이는 배치 시점에 정해지는 성질이고, 그것을 코드
# 분기가 아니라 장치별 데이터로 표현하는 것이 이 절의 목적이다.
# ============================================================================


class Residency(str, Enum):
    """결정 결과 — 이 capability kind가 실제로 어디에 놓였는가."""

    ONDEVICE = "ondevice"
    EDGE = "edge"


class ResidencyPolicy(str, Enum):
    """장치 목적이 선언하는 배치 정책. 결정이 아니라 **선언**이다.

    RESIDENT       - 링크 상태와 무관하게 항상 온디바이스에 상주한다.
                     즉시 대응(안전)·실시간 지연 요구·통신 단절 생존이
                     이유이며, 어느 이유인지는 `survives_outage`와
                     `quality_is_safety_affecting`이 따로 표현한다.
    LINK_DEPENDENT - 링크를 신뢰할 수 있으면 엣지에 맡기고, 신뢰할 수 없으면
                     온디바이스로 끌어온다. "링크가 나쁜 장치일수록 상주
                     기능이 늘어난다"는 성질은 이 값 하나에서 나온다(AI-N-03).
    EDGE_SERVED    - 온디바이스에 두지 않는다. 단절 중에는 이 기능만 쓸 수
                     없게 되고 나머지는 계속 동작한다(AI-C-05, 원칙 #4).
    """

    RESIDENT = "resident"
    LINK_DEPENDENT = "link_dependent"
    EDGE_SERVED = "edge_served"


#: `CapabilityResidencySpec.outage_behavior`의 통제 어휘 — 엣지에 닿지 못하는
#: 동안 이 기능이 어떻게 되는지. 자유 문자열로 두면 "그래서 드론이 통신
#: 끊기면 감시가 멈추나?"에 답할 수 없어 어휘를 닫았다(AI-C-05, AI-O-02).
OUTAGE_UNAFFECTED = "resident_unaffected"          # 온디바이스 상주, 링크 무관
OUTAGE_QUEUED_FOR_EDGE = "queued_for_edge"         # 로컬 동작 계속, 결과는 복구 후 전달
OUTAGE_LOCAL_FALLBACK = "local_fallback"           # `local_fallback_kind`로 축소 운용
OUTAGE_UNAVAILABLE = "unavailable_until_link_returns"  # 이 기능만 중단

OUTAGE_BEHAVIORS: tuple[str, ...] = (
    OUTAGE_UNAFFECTED,
    OUTAGE_QUEUED_FOR_EDGE,
    OUTAGE_LOCAL_FALLBACK,
    OUTAGE_UNAVAILABLE,
)


@dataclass(frozen=True)
class LinkProfile:
    """장치의 링크 특성 — 측정값이거나 선언값이거나, 아예 모를 수도 있다.

    implements: AI-N-03

    무선 규격도 지표 이름도 여기 없다. `quality`는 `ondevice/link_handover.py`의
    `LinkSample.quality`와 **같은 정규화 값**(1.0 최상, 0.0 사용 불가)이고,
    어떤 provider가 RSSI·SNR·손실률·RTT 중 무엇으로 만들었는지는 `source`가
    문자열로만 남긴다. AI-N-03: "특정 무선 규격이나 측정값이 항상 존재한다고
    가정해서는 안 된다" — 그래서 모든 필드가 None일 수 있고, 모르는 링크는
    판정에서 보수적으로 다룬다.

    `stability`는 평균 품질과 **다른 축**이다. 평균은 좋은데 자주 떨어지는
    링크(측정 사례: 같은 장치가 어떤 날은 0% 손실, 어떤 날은 33% 손실)를
    평균만으로는 구분할 수 없어 별도 값으로 둔다. 0.0~1.0, "floor 위에
    머문 시간 비율"의 의미.

    `samples`는 이 값이 몇 번의 관측에서 나왔는지다. 순간값 한 번으로 배치를
    바꾸면 AI-N-03이 경고하는 반복 전환이 배치 시점으로 옮겨올 뿐이므로,
    표본이 모자란 측정값은 '모름'과 같게 취급한다.
    """

    #: "declared" | "measured:<provider_id>" | "unknown" — 자유 문자열.
    source: str = "unknown"
    quality: float | None = None
    stability: float | None = None
    #: 관측 대신 배포자가 직접 못박는 자세. 값은 LinkPosture의 value 문자열
    #: ("remote_ok" | "reducing" | "local_only"). 측정 수단이 아예 없는 현장에서
    #: "이 장치는 원래 링크가 나쁘다"를 데이터로 말하는 경로다.
    declared_posture: str | None = None
    samples: int = 0
    observed_at: float | None = None

    def is_known(self) -> bool:
        return self.declared_posture is not None or self.quality is not None


@dataclass(frozen=True)
class LinkPostureThresholds:
    """정규화 품질 → 배치 시점 자세로 환산하는 기준값.

    implements: AI-N-03, AI-B-06

    기본값은 `ondevice/link_handover.py::LinkTransitionPolicy`의 기본값과
    **같은 숫자**다(floor 0.25 / restore_margin 0.20). 배치 시점 결정과 운행
    중 전환이 서로 다른 기준을 쓰면 "배치는 엣지에 맡겼는데 뜨자마자 런타임이
    로컬로 내린다"가 되므로 한쪽을 바꾸면 다른 쪽도 바꿔야 한다 —
    `runtime/residency.py::LinkPostureThresholds.from_transition_policy`와
    `tests/test_residency.py`가 이 일치를 고정한다.

    `min_samples`는 측정 링크에만 적용된다. 선언 링크는 표본 개념이 없다.

    `min_stability`는 평균 품질이 좋아도 자주 끊기는 링크를 잡는 기준이다.
    """

    floor: float = 0.25
    restore_margin: float = 0.20
    min_stability: float = 0.90
    min_samples: int = 3


@dataclass(frozen=True)
class CapabilityResidencySpec:
    """한 capability kind에 대한 배치 선언. 판정이 아니라 입력이다.

    implements: AI-C-15, AI-C-05, AI-B-04, AI-B-10, AI-N-03

    `requirement`/`is_core`/`degrade_rank`는 `runtime/application.py::
    CapabilitySpec`과 같은 의미로, 온디바이스로 결정된 kind에 대해 그대로
    넘겨진다 — 배치 결정이 끝난 뒤의 축소·격리는 기존 AI-C-05 경로가 그대로
    담당하고 여기서 두 번째 축소 기구를 만들지 않는다.
    """

    kind: str
    policy: ResidencyPolicy = ResidencyPolicy.EDGE_SERVED

    #: 통신 단절 동안에도 계속 동작해야 하는가. True인데 결정 결과가 EDGE면
    #: 그 자체가 프로파일 데이터의 모순이고 계획이 위반으로 보고한다.
    survives_outage: bool = False

    #: 이 기능의 **품질·해상도를 낮추는 것이 안전 판정을 바꾸는가**.
    #: 측정 근거: depth 입력 해상도를 절반으로 줄였을 때 detection recall은
    #: 1.000으로 유지됐지만 근접 장애물 안전 판정이 14/20 → 4/20으로 무너졌다.
    #: 실행 위치(CPU/GPU, fp16/fp32)를 바꾸는 것은 결과를 바꾸지 않으므로
    #: 자유롭게 교환할 수 있지만, 온디바이스 속도를 입력 해상도로 사는 것은
    #: 안전을 파는 것이다. True인 kind는 축소 대상이 아니므로 core여야 한다.
    quality_is_safety_affecting: bool = False

    #: 온디바이스에 두지 않았을 때 엣지에서 이 kind를 담당하는 서비스 식별자.
    #: 자유 문자열(배포가 정하는 이름)이며 프레임워크는 의미를 모른다.
    edge_service: str | None = None

    #: 엣지에 닿지 못하는 동안 이 기능이 어떻게 되는가. OUTAGE_BEHAVIORS 중 하나.
    outage_behavior: str = OUTAGE_UNAVAILABLE

    #: `outage_behavior == OUTAGE_LOCAL_FALLBACK`일 때 대신 쓰는 로컬 kind.
    local_fallback_kind: str | None = None

    #: 엣지에 맡기려면 최소한 이만큼의 정규화 품질이 필요하다(선언 없으면 None).
    #: 왜 kind마다 다른가: 링크 저하의 비용이 페이로드 크기에 대해 선형이
    #: 아니다. 측정 근거 — 메타데이터 543B는 100ms 링크에서 정확히 편도
    #: 1회분만 늘었지만, 21KB JPEG은 초기 혼잡 윈도를 넘겨 깨끗한 링크 1.1배
    #: 대비 3.0배가 됐다. 그래서 픽셀을 오가게 하는 kind는 메타데이터만
    #: 오가는 kind보다 훨씬 좋은 링크를 요구해야 하고, 그 차이는 정책 분기가
    #: 아니라 이 숫자로 표현한다.
    min_link_quality: float | None = None

    #: 이 kind를 엣지에 맡길 때 링크에 실리는 것의 성격 — "metadata" | "media".
    #: 표시·설명용 자유 문자열이며 판정에 쓰이지 않는다(판정은 위 숫자가 한다).
    edge_payload: str = "metadata"

    # --- 온디바이스로 결정됐을 때 기존 AI-C-05 경로에 그대로 넘어가는 항목 ---
    is_core: bool = False
    degrade_rank: int = 0
    requirement: CapabilityRequirement = field(default_factory=CapabilityRequirement)


@dataclass(frozen=True)
class DevicePurposeProfile:
    """등록된 장치 하나의 **목적**을 데이터로 표현한 것.

    implements: AI-C-15, AI-B-04, AI-B-10, AI-C-13

    하천 감시 드론과 지상 로봇의 차이는 이 객체의 내용 차이일 뿐이고,
    이것을 읽는 코드에는 두 경우를 가르는 분기가 없다(절대 준수 원칙 #3).

    `node_tags`/`preferred_node_tags`는 AI-B-04의 필수/선호 구분을 그대로
    따른다 — 필수 태그가 없는 장치에서는 그 태그를 요구하는 provider만
    선택되지 않을 뿐 나머지는 계속 배치된다.

    `budget`은 말단 경량 경계(AI-B-10)를 숫자로 못박는 자리다. 상주 집합이
    이 예산을 넘는지는 여기서 재판정하지 않고 기존 `ZoneApplication.resolve`가
    판정한다.
    """

    purpose_id: str
    capabilities: tuple[CapabilityResidencySpec, ...] = ()
    node_tags: tuple[str, ...] = ()
    preferred_node_tags: tuple[str, ...] = ()
    budget: ResourceBudget | None = None
    link: LinkProfile = field(default_factory=LinkProfile)
    link_thresholds: LinkPostureThresholds = field(default_factory=LinkPostureThresholds)
    description: str = ""

    def kinds(self) -> tuple[str, ...]:
        return tuple(spec.kind for spec in self.capabilities)

    def spec(self, kind: str) -> CapabilityResidencySpec | None:
        for spec in self.capabilities:
            if spec.kind == kind:
                return spec
        return None

    def with_link(self, link: LinkProfile) -> "DevicePurposeProfile":
        """같은 목적, 다른 링크 — what-if("링크가 나빠지면")의 유일한 입력.

        목적 데이터를 건드리지 않고 링크만 바꿔 다시 결정할 수 있어야
        "링크 때문에 바뀐 것"과 "목적 때문에 바뀐 것"을 가를 수 있다.
        """
        return replace(self, link=link)
