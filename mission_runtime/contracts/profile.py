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
from typing import Mapping, Sequence

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
    `runtime/residency.py::thresholds_from_transition_policy`와
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


# ============================================================================
# 실행 구성의 **신원**과 그 구성에서 잰 측정값 — AI-B-01 의 "검증" 쪽
#
# implements: AI-B-01
# 관련: AI-B-09 (새 조합은 프로파일을 새로 만든다), AI-C-18 (선언 규약),
#       AI-L-05/06 (검증·미검증 범위), AI-L-10 (검증 범위를 벗어난 배정 금지),
#       AI-O-05 (미측정은 0 도 미달도 아니다)
#
# 왜 이 층이 따로 필요한가
# ------------------------
# `CompatibilityProfile` 은 "어디서 돌 수 있는가" 를 말한다(선언). AI-B-01 은 그
# 위에 두 가지를 더 요구한다 — **무엇을 실제로 쟀는가**(측정)와 **그 측정이 어느
# 구성의 것인가**(신원). 셋을 한 칸에 담으면 세 번째가 조용히 사라진다: 모델을
# 바꾼 뒤에도 숫자는 그 자리에 남아 있고, 그것이 다른 구성에서 잰 값이라는 사실은
# 아무 자료형도 말하지 않는다.
#
# 그래서 측정값은 홀로 존재하지 않는다. `MeasurementSet` 은 자기가 어느 구성의
# 지문에서 나왔는지를 **필수 칸으로** 들고 다니고, `VerifiedExecutionProfile` 은
# 생성 시점에 그 지문이 자기 구성의 지문과 같은지 확인한다. 구성 축 하나만 바뀌면
# 지문이 바뀌고, 그 순간 옛 측정 묶음은 새 구성의 프로파일로 **만들어질 수 없다** —
# 검토자가 숫자를 지우는 것을 기억해서가 아니라, 옮겨 담을 길이 자료형에 없어서다.
# 다시 재는 것 = 새 `MeasurementSet` 을 그 구성에서 만드는 것이고, 둘은 같은 일이다.
#
# 이미 있는 `contracts/capability_contract.py::ExecutionProfile` 과의 관계
# -----------------------------------------------------------------------
# 그쪽은 **선택 시점의 검사**다 — `matches_conditions(runtime, hardware_tags,
# input_profile)` 로 "지금 조건이 그때 조건과 같은가" 를 묻고, 다르면 그 후보를
# 건너뛴다(`selection/selector.py::REASON_PROFILE_CONDITIONS_MISMATCH`). 그 검사는
# 그대로 두고 여기서 다시 하지 않는다.
#
# 여기 더하는 것은 **신원**이다. 선택 시점 검사만으로는 두 가지가 남는다. 첫째,
# 조건이 세 축뿐이어서 전처리·후처리·보정이 바뀐 것은 같은 구성으로 읽힌다. 둘째,
# 측정값과 조건이 같은 객체의 **독립된 칸**이라 조건만 고쳐 쓰는 것이 가능하고
# `unmeasured_fields` 가 손으로 적는 목록이라 측정값 dict 와 어긋날 수 있다 — 어긋나면
# 통과로 읽히는 쪽이 더 위험하다. 이 절의 자료형은 미측정을 **키의 부재**로만 말하고
# (여집합을 따로 적지 않는다) 측정 묶음이 자기 구성의 지문을 들어 옮겨 담기를
# 막는다. 두 계약의 통합은 `docs/technology-boundaries.md` §10-2 에 남은 합의 사항이다.
#
# 반대쪽도 요구사항이다(AI-B-01 마지막 문장). 사람이 확인한 의미 정보·검증
# 데이터·업무 요구는 구성이 바뀌어도 그대로 쓴다 — 모델을 바꾼 것이 "저 물체는
# 소화기다" 를 다시 묻게 만들어서는 안 된다. 그 차이를 `KnowledgeRecord.binding`
# 한 칸이 선언하고, 구성 결속 지식만 지문을 들고 다닌다.
# ============================================================================

#: 측정 항목의 통제 어휘. AI-B-01 이 열거한 항목을 그대로 옮긴 것이다 —
#: "처리지연, 처리량, 메모리·연산 자원, 품질, 실패 특성, 네트워크·외부 호출 비용".
#: 새 항목은 이 목록에 상수를 더하는 일이고, 목록 밖 이름도 측정값으로 담을 수
#: 있다(배치가 자기 지표를 더하는 자리) — 닫는 것은 어휘가 아니라 **미측정과 0 의
#: 구분**이다.
MEASURE_LATENCY_MS = "latency_ms"
MEASURE_THROUGHPUT_HZ = "throughput_hz"
MEASURE_MEMORY_MB = "memory_mb"
MEASURE_COMPUTE_UNITS = "compute_units"
MEASURE_QUALITY = "quality"
MEASURE_FAILURE_RATE = "failure_rate"
MEASURE_NETWORK_BYTES = "network_bytes_per_call"
MEASURE_EXTERNAL_CALL_COST = "external_call_cost"

MEASUREMENT_KINDS: tuple[str, ...] = (
    MEASURE_LATENCY_MS,
    MEASURE_THROUGHPUT_HZ,
    MEASURE_MEMORY_MB,
    MEASURE_COMPUTE_UNITS,
    MEASURE_QUALITY,
    MEASURE_FAILURE_RATE,
    MEASURE_NETWORK_BYTES,
    MEASURE_EXTERNAL_CALL_COST,
)

#: 실행 구성을 가르는 축의 이름. 지문에 들어가는 순서까지 이 순서다 — 같은 구성이
#: 다른 지문을 갖지 않으려면 정규형이 하나여야 한다.
AXIS_CAPABILITY_KIND = "capability_kind"
AXIS_IMPLEMENTATION = "implementation_ref"
AXIS_RUNTIME = "runtime_ref"
AXIS_HARDWARE = "hardware_tags"
AXIS_INPUT_PROFILE = "input_profile"
AXIS_PREPROCESS = "preprocess_ref"
AXIS_POSTPROCESS = "postprocess_ref"
AXIS_CALIBRATION = "calibration_ref"
#: 개방어휘(제로샷) 모델에 **무엇을 찾으라고 말했는가**. 가중치를 그대로 두고 클래스
#: 프롬프트만 바꿔도 그 모델은 다른 것을 찾는다 — 즉 품질도 지연도 다시 재야 한다.
#: 이 축이 없던 동안은 프롬프트를 바꿔도 지문이 같아서 **옛 측정값이 그대로 유효한
#: 척했다.** 프롬프트를 쓰지 않는 구성에서는 빈 문자열이고, 빈 값도 지문에 들어가므로
#: "프롬프트 없음" 과 "프롬프트 있음" 이 같은 구성이 되지 않는다.
AXIS_PROMPT = "prompt_ref"

CONFIGURATION_AXES: tuple[str, ...] = (
    AXIS_CAPABILITY_KIND,
    AXIS_IMPLEMENTATION,
    AXIS_RUNTIME,
    AXIS_HARDWARE,
    AXIS_INPUT_PROFILE,
    AXIS_PREPROCESS,
    AXIS_POSTPROCESS,
    AXIS_CALIBRATION,
    AXIS_PROMPT,
)

#: 지식이 실행 구성에 묶이는가. AI-B-01 의 마지막 두 문장이 이 두 값이다.
BINDING_CONFIGURATION = "configuration_bound"
BINDING_INDEPENDENT = "configuration_independent"
KNOWLEDGE_BINDINGS: tuple[str, ...] = (BINDING_CONFIGURATION, BINDING_INDEPENDENT)

#: 구성과 독립인 지식의 종류 — AI-B-01: "사람에게 확인된 의미 정보, 검증 데이터와
#: 업무 요구처럼 구성과 독립적인 지식". 자유 문자열이 아니라 어휘로 둔 이유는
#: 재사용 여부가 이 값에 달려 있기 때문이다. 벤더·모델 이름은 여기 들어오지 않는다.
KNOWLEDGE_HUMAN_CONFIRMED = "human_confirmed_semantics"
KNOWLEDGE_VALIDATION_DATASET = "validation_dataset"
KNOWLEDGE_BUSINESS_REQUIREMENT = "business_requirement"
KNOWLEDGE_MEASUREMENT = "execution_measurement"

KNOWLEDGE_KINDS: tuple[str, ...] = (
    KNOWLEDGE_HUMAN_CONFIRMED,
    KNOWLEDGE_VALIDATION_DATASET,
    KNOWLEDGE_BUSINESS_REQUIREMENT,
    KNOWLEDGE_MEASUREMENT,
)


def prompt_ref_for(class_names, *, prompt_free: bool = False) -> str:
    """클래스 프롬프트 → 구성 축에 쓸 **신원**.

    어휘 전문을 축 값으로 쓰지 않는 이유 둘.

    1. 어휘가 수십 개면 지문의 재료가 그만큼 길어지고, 사람이 두 구성을 눈으로
       견주지 못한다.
    2. **같은 어휘를 다른 순서로 적은 것은 같은 구성이다.** 순서를 그대로 쓰면
       `["person","box"]` 와 `["box","person"]` 이 다른 구성이 되어, 아무것도 바뀌지
       않았는데 재측정 의무가 생긴다. 그래서 정렬·소문자·중복 제거를 거친다.

    `prompt_free=True` 는 **프롬프트를 주지 않는 모델**이다(어휘가 비어 있는 것과
    다르다 — 그쪽은 "찾을 것을 아직 안 정했다" 이고, 이쪽은 "이 모델은 어휘를 받지
    않는다" 다). 두 상태가 같은 축 값을 가지면 둘의 측정값이 섞인다.
    """
    import hashlib

    if prompt_free:
        return "prompt_free"
    normalised = sorted({str(name).strip().lower() for name in class_names or () if str(name).strip()})
    if not normalised:
        return ""
    digest = hashlib.sha256("\n".join(normalised).encode("utf-8")).hexdigest()[:16]
    # 개수를 함께 적는다 — 사람이 두 참조를 볼 때 "몇 개짜리 어휘였나" 가 바로 보이고,
    # 해시만 적힌 축은 운영 화면에서 읽을 수 없는 값이 된다.
    return f"vocab{len(normalised)}:{digest}"


@dataclass(frozen=True)
class ExecutionConfiguration:
    """하나의 **독립적인 실행 구성**. AI-B-01 의 "실행 구성 식별" 이 이것이다.

    AI-B-01: "동일 capability를 제공하는 서로 다른 모델·알고리즘, 런타임, 하드웨어,
    실행 위치, 입력 조건, 전처리·후처리와 필요한 보정의 조합을 독립적인 실행 구성으로
    식별하고".

    모든 축은 **자유 문자열**이다. 벤더 열거형을 두면 새 하드웨어가 이 모듈의 수정이
    되고, 그것이 절대 준수 원칙 #1·#7 이 금지하는 바로 그 결합이다. `hardware_tags`
    는 생성 시 정렬된다 — 태그를 적은 순서가 다른 구성이 되어서는 안 된다
    (`contracts/capability_contract.py::ExecutionProfile.matches_conditions` 의 집합
    비교와 같은 판단이다).

    `extra_axes` 는 배치가 자기만의 축을 더하는 자리다. 더한 축도 지문에 들어가므로
    **새 축을 더하는 것 자체가 재측정 의무를 만든다** — 모르는 축이 생겼는데 옛
    숫자가 그대로 쓰이는 일이 없다.
    """

    capability_kind: str
    implementation_ref: str
    runtime_ref: str
    input_profile: str
    hardware_tags: tuple[str, ...] = ()
    preprocess_ref: str = ""
    postprocess_ref: str = ""
    calibration_ref: str = ""
    #: 개방어휘 모델에 준 클래스 프롬프트의 **신원**. 어휘 목록 자체가 아니라 그것을
    #: 가리키는 참조다 — 어휘가 길면 지문이 어휘 전문을 담게 되고, 같은 어휘를 다른
    #: 순서로 적은 것이 다른 구성이 된다. 참조를 만드는 쪽이 정규화를 책임진다
    #: (`prompt_ref_for()` 참조).
    prompt_ref: str = ""
    #: ((축 이름, 값), ...). 생성 시 축 이름으로 정렬된다.
    extra_axes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.capability_kind:
            raise ValueError("capability_kind must not be empty")
        if not self.implementation_ref:
            raise ValueError("implementation_ref must not be empty")
        object.__setattr__(self, "hardware_tags", tuple(sorted(self.hardware_tags)))
        object.__setattr__(
            self, "extra_axes", tuple(sorted((str(k), str(v)) for k, v in self.extra_axes))
        )

    def axes(self) -> tuple[tuple[str, str], ...]:
        """이 구성을 가르는 축 전부. 지문의 재료이고 어긋난 축을 세는 재료다."""
        core = (
            (AXIS_CAPABILITY_KIND, self.capability_kind),
            (AXIS_IMPLEMENTATION, self.implementation_ref),
            (AXIS_RUNTIME, self.runtime_ref),
            (AXIS_HARDWARE, ",".join(self.hardware_tags)),
            (AXIS_INPUT_PROFILE, self.input_profile),
            (AXIS_PREPROCESS, self.preprocess_ref),
            (AXIS_POSTPROCESS, self.postprocess_ref),
            (AXIS_CALIBRATION, self.calibration_ref),
            (AXIS_PROMPT, self.prompt_ref),
        )
        return core + self.extra_axes

    @property
    def fingerprint(self) -> str:
        """구성 내용에서 파생된 신원. 축 하나가 달라지면 다른 값이 된다.

        내용에서 파생시키는 이유는 `continual/stream_learning.py::ParameterSet.version`
        과 같다 — 같은 내용에 두 개의 신원이 생기면 "같은 구성인가" 를 누군가 손으로
        판정해야 하고, 그 판정이 틀리는 날 옛 숫자가 새 구성에 붙는다.
        """
        import hashlib

        canonical = "\n".join(f"{name}={value}" for name, value in self.axes())
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def differing_axes(self, other: "ExecutionConfiguration") -> tuple[str, ...]:
        """두 구성이 **어느 축에서** 다른가. 재측정 사유를 사람이 읽을 수 있게 한다."""
        mine = dict(self.axes())
        theirs = dict(other.axes())
        names = sorted(set(mine) | set(theirs), key=lambda n: (n not in CONFIGURATION_AXES, n))
        return tuple(n for n in names if mine.get(n, "") != theirs.get(n, ""))

    def measure(
        self,
        values: Mapping[str, float],
        *,
        measured_at: float | None = None,
        evidence_refs: Sequence[str] = (),
        sample_count: int = 0,
    ) -> "MeasurementSet":
        """이 구성에서 잰 값 묶음을 만든다. 측정 묶음을 만드는 **유일한** 경로다.

        구성 객체에서만 만들 수 있게 한 것이 핵심이다 — 측정값이 구성과 떨어져
        떠다니면 어느 구성의 것인지 묻는 자리가 사라진다.
        """
        return MeasurementSet(
            configuration_fingerprint=self.fingerprint,
            values=dict(values),
            measured_at=measured_at,
            evidence_refs=tuple(evidence_refs),
            sample_count=sample_count,
        )


@dataclass(frozen=True)
class MeasurementSet:
    """한 구성에서 **실제로 잰** 값들. 재지 않은 항목은 **키가 없다**.

    implements: AI-B-01

    `edge/calibration_profile.py::CalibrationProfile.quality` 와 같은 모양이다 —
    미측정 항목은 0 이 아니라 **부재**다. 0 을 넣으면 지연은 빠른 것으로, 메모리는
    싼 것으로, 실패율은 완벽한 것으로 읽힌다(AI-O-05: 미측정 ≠ 0 ≠ 미달).

    `None` 을 값으로 받지 않는다. `{"quality": None}` 을 허용하면 "키는 있는데 값이
    없다" 는 세 번째 상태가 생기고, 그것을 읽는 쪽마다 다르게 해석한다.
    """

    #: 어느 구성에서 쟀는가. 기본값이 없다 — 이 칸이 없는 측정값은 만들 수 없다.
    configuration_fingerprint: str
    values: Mapping[str, float] = field(default_factory=dict)
    measured_at: float | None = None
    #: 측정 근거 참조(보고서·실험 기록). 픽셀·원본은 들어오지 않는다(AI-C-08).
    evidence_refs: tuple[str, ...] = ()
    #: 표본 수. 한 번 잰 값과 25회 잰 값은 같은 근거가 아니다.
    sample_count: int = 0

    def __post_init__(self) -> None:
        if not self.configuration_fingerprint:
            raise ValueError("measurements must name the configuration they were taken on")
        cleaned: dict[str, float] = {}
        for name, value in dict(self.values).items():
            if not name:
                raise ValueError("measurement name must not be empty")
            if value is None:
                raise ValueError(
                    f"measurement {name!r} is None — 재지 않은 항목은 키를 넣지 않는다 (AI-B-01)"
                )
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                raise ValueError(f"measurement {name!r} must be a finite number")
            cleaned[name] = number
        object.__setattr__(self, "values", cleaned)
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    def has(self, name: str) -> bool:
        return name in self.values

    def value(self, name: str) -> float | None:
        """잰 값, 또는 재지 않았으면 `None`. 기본값 인자를 두지 않는다 —
        `value("latency_ms", 0.0)` 같은 호출 하나가 이 모듈의 목적을 무효로 만든다.
        """
        return self.values.get(name)

    def measured(self) -> tuple[str, ...]:
        return tuple(sorted(self.values))

    def unmeasured(self, among: Sequence[str] = MEASUREMENT_KINDS) -> tuple[str, ...]:
        """`among` 중 **재지 않은** 항목. AI-B-01 "미측정 항목은 구분해야 한다"."""
        return tuple(name for name in among if name not in self.values)


@dataclass(frozen=True)
class VerifiedExecutionProfile:
    """한 실행 구성의 프로파일 — 측정값과 **실제로 돌린 검증 항목**을 함께 든다.

    implements: AI-B-01
    관련: AI-B-09, AI-L-05, AI-L-06, AI-L-10

    생성 시 `measurements.configuration_fingerprint` 가 `configuration.fingerprint`
    와 같은지 확인하고, 다르면 거절한다. `dataclasses.replace(profile,
    configuration=other)` 도 이 확인을 다시 거치므로 **옛 측정값을 새 구성에 붙여
    넣는 경로가 없다**. 그것이 "재측정 의무를 구조로 만든다" 의 실제 내용이다.

    `validated_by` 는 `CalibrationProfile.validated_by` 와 같은 뜻이다 — 돌린 검증
    항목의 목록이고, **돌리지 않은 것은 그 여집합**으로 드러난다. 여집합을 직접
    적지 않는 이유: 두 목록을 따로 적으면 둘이 어긋날 수 있고, 어긋났을 때 통과로
    읽히는 쪽이 더 위험하다.
    """

    configuration: ExecutionConfiguration
    measurements: MeasurementSet
    validated_by: tuple[str, ...] = ()
    #: 이 프로파일을 만든 주체(사람·도구 id). 자유 문자열.
    measured_by: str = ""
    #: 알려진 실패 조건. AI-B-01 "실패 특성" 중 수치가 아닌 쪽이다.
    known_failure_conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        expected = self.configuration.fingerprint
        if self.measurements.configuration_fingerprint != expected:
            raise ValueError(
                "measurements were taken on another execution configuration "
                f"({self.measurements.configuration_fingerprint[:12]} != {expected[:12]}); "
                "다른 구성의 측정값을 옮겨 적지 않는다 — 새 구성은 재측정한다 (AI-B-01)"
            )
        object.__setattr__(self, "validated_by", tuple(self.validated_by))
        object.__setattr__(
            self, "known_failure_conditions", tuple(self.known_failure_conditions)
        )

    @property
    def fingerprint(self) -> str:
        return self.configuration.fingerprint

    def value(self, name: str) -> float | None:
        return self.measurements.value(name)

    def unmeasured(self, among: Sequence[str] = MEASUREMENT_KINDS) -> tuple[str, ...]:
        return self.measurements.unmeasured(among)

    def not_validated(self, required_checks: Sequence[str]) -> tuple[str, ...]:
        """요구된 검증 항목 중 **돌리지 않은** 것. 돌리지 않은 것은 통과가 아니다."""
        done = set(self.validated_by)
        return tuple(check for check in required_checks if check not in done)

    def covers(self, configuration: ExecutionConfiguration) -> bool:
        """이 프로파일의 측정값을 그 구성에 써도 되는가 — **지문이 같을 때만**.

        '비슷한 구성' 이라는 상태를 두지 않는다. 비슷함의 판정은 사람의 암묵지이고,
        AI-B-01 이 금지하는 "자동으로 동일하다고 가정" 은 정확히 그 암묵지가 코드로
        들어온 모양이다.
        """
        return self.fingerprint == configuration.fingerprint

    def to_resource_cost(self) -> ResourceCost | None:
        """선택기가 쓰는 `ResourceCost` 로. **재지 않았으면 만들지 않는다.**

        연산·메모리 중 하나라도 미측정이면 `None` 이다. 0 으로 채운 `ResourceCost`
        는 예산 심사에서 언제나 통과하므로, 재지 않은 구성이 가장 싼 후보가 된다 —
        없는 이득을 보고 고르는 그 경로를 자료형에서 막는다.
        """
        compute = self.value(MEASURE_COMPUTE_UNITS)
        memory = self.value(MEASURE_MEMORY_MB)
        if compute is None or memory is None:
            return None
        return ResourceCost(
            compute_units=compute,
            memory_mb=memory,
            max_latency_ms=self.value(MEASURE_LATENCY_MS),
        )


@dataclass(frozen=True)
class KnowledgeRecord:
    """기록된 지식 1건과 그것이 **구성에 묶이는지**의 선언.

    implements: AI-B-01

    AI-B-01 의 마지막 두 문장이 짝이다. "새 구성은 재측정·재검증해야 한다" 와
    "사람에게 확인된 의미 정보, 검증 데이터와 업무 요구처럼 구성과 독립적인 지식은
    재사용할 수 있어야 한다." 모델을 바꾸면 지연은 다시 재야 하지만 "저것은
    소화기다" 를 사람에게 다시 묻지는 않는다 — 그 차이가 `binding` 한 칸이다.

    구성 결속 기록은 지문을 **반드시** 들고, 구성 독립 기록은 지문을 **들 수 없다**.
    후자를 막는 이유: 구성에 묶이지 않는다고 선언하면서 구성을 들고 있으면 어느
    쪽이 참인지 읽는 쪽이 고르게 되고, 그때 고르는 기준은 코드가 아니라 습관이다.
    """

    knowledge_id: str
    kind: str
    binding: str
    #: 무엇에 대한 지식인가 — 객체·데이터셋·업무 식별자. 자유 문자열.
    subject: str = ""
    #: 내용 자체는 여기 담지 않고 참조만 둔다.
    content_ref: str = ""
    #: 사람이 확인한 것이면 그 주체. 비어 있으면 사람 확인이 아니다(AI-L-02).
    confirmed_by: str = ""
    recorded_at: float | None = None
    #: 구성 결속 기록만 값을 갖는다.
    configuration_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.knowledge_id:
            raise ValueError("knowledge_id must not be empty")
        if self.binding not in KNOWLEDGE_BINDINGS:
            raise ValueError(f"unknown binding {self.binding!r}; expected one of {KNOWLEDGE_BINDINGS}")
        if self.binding == BINDING_CONFIGURATION and not self.configuration_fingerprint:
            raise ValueError(
                "configuration-bound knowledge must name its execution configuration (AI-B-01)"
            )
        if self.binding == BINDING_INDEPENDENT and self.configuration_fingerprint:
            raise ValueError(
                "configuration-independent knowledge must not carry a configuration fingerprint"
            )

    @property
    def reusable_across_configurations(self) -> bool:
        return self.binding == BINDING_INDEPENDENT
