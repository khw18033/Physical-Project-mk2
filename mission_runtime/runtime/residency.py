"""목적과 링크 안정성으로 "이 장치 안에 무엇을 둘 것인가"를 정한다.

implements: AI-C-15, AI-C-05, AI-B-04, AI-B-06, AI-B-10, AI-C-13, AI-N-03

이 모듈이 답하는 질문은 `ZoneApplication.resolve()`가 답하는 질문과 다르다.

* `resolve()` — "지금 이 노드에서 이 기능이 **돌 수 있는가**" (ACTIVE/DEGRADED/DISABLED)
* 여기 — "등록된 이 장치가 이 기능을 **자기 안에 가지고 있어야 하는가**" (ONDEVICE/EDGE)

둘은 순서대로 이어진다. 먼저 배치를 정하고(`decide_residency`), 그 결과로 만든
온디바이스용 `DeploymentProfile`을 기존 `ZoneApplication`에 그대로 넘긴다. 예산
초과·태그 결손·선택 기능 축소는 전부 기존 경로가 처리하므로 여기서 두 번째 축소
기구를 만들지 않는다(AI-C-05는 하나뿐이어야 한다).

설계 근거 세 가지:

1. **링크 자세는 하나의 어휘여야 한다.** 배치 시점 판정은 운행 중 전환
   (`ondevice/link_handover.py`, AI-N-03)의 배치 시점 짝이다. 두 판정이 서로
   다른 어휘·기준을 쓰면 "배치는 엣지에 맡겼는데 뜨자마자 런타임이 로컬로
   내리는" 상태가 정상처럼 보인다. 그래서 `LinkPosture`를 그대로 import하고
   기준값도 `LinkTransitionPolicy`에서 끌어올 수 있게 했다.
2. **링크 저하의 비용은 페이로드에 대해 선형이 아니다.** 측정: 메타데이터
   543B는 100ms 링크에서 편도 1회분만 늘었지만 21KB JPEG은 초기 혼잡 윈도를
   넘겨 깨끗한 링크 대비 1.1배 → 3.0배가 됐다. 그래서 "링크가 나쁘다"는
   신호는 픽셀을 오가게 하는 기능을 훨씬 일찍 온디바이스로 끌어와야 하고,
   그 차이는 코드 분기가 아니라 kind별 `min_link_quality` 숫자로 표현된다.
3. **모르는 링크는 나쁜 링크로 다룬다.** AI-N-03이 "특정 측정값이 항상
   존재한다고 가정하지 말라"고 요구하므로 값이 없는 경우가 정상 경로이고,
   그때 원격에 기대는 쪽으로 기울면 단절 시 안전 기능이 함께 사라진다.
   보수적으로 LOCAL_ONLY로 두되 **사유 토큰으로 "측정이 아니라 기본값"임을
   드러낸다** — 조용한 가정은 금지 사항이다.

이 모듈에는 도메인 이름이 없다. 드론과 로봇의 차이는 전부
`DevicePurposeProfile` 데이터 차이다(절대 준수 원칙 #3, AI-C-15).
"""

from __future__ import annotations

from dataclasses import dataclass

from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.contracts.profile import (
    CapabilityResidencySpec,
    DeploymentProfile,
    DevicePurposeProfile,
    LinkProfile,
    LinkPostureThresholds,
    OUTAGE_BEHAVIORS,
    OUTAGE_LOCAL_FALLBACK,
    OUTAGE_QUEUED_FOR_EDGE,
    Residency,
    ResidencyPolicy,
)
from mission_runtime.ondevice.link_handover import LinkPosture, LinkTransitionPolicy
from mission_runtime.runtime.application import CapabilitySpec

# --- 사유 통제 어휘 ----------------------------------------------------------
# `SelectionResult.reason`과 같은 규약: ':' 앞이 토큰, 뒤가 데이터. 등록처는
# `contracts/data_dictionary.py::RESIDENCY_DECISION_REASONS`이며
# `tests/test_data_dictionary.py`가 이 상수들이 사전 밖으로 새지 않는지 본다.

# 링크 자세 판정 사유
LINK_REASON_DECLARED = "link_posture_declared"                    # + ":<posture>"
LINK_REASON_QUALITY_UNKNOWN = "link_quality_unknown"
LINK_REASON_SAMPLES_INSUFFICIENT = "link_samples_insufficient"    # + ":<n>/<min>"
LINK_REASON_AT_OR_BELOW_FLOOR = "link_quality_at_or_below_floor"  # + ":<q>"
LINK_REASON_BELOW_RESTORE_MARGIN = "link_quality_below_restore_margin"  # + ":<q>"
LINK_REASON_UNSTABLE = "link_stability_below_threshold"           # + ":<s>"
LINK_REASON_STABLE = "link_quality_stable"                        # + ":<q>"

# 배치 결정 사유
RESIDENCY_REASON_RESIDENT_BY_PURPOSE = "resident_by_purpose"
RESIDENCY_REASON_EDGE_BY_PURPOSE = "edge_served_by_purpose"
RESIDENCY_REASON_LINK_REQUIRES_LOCAL = "link_posture_requires_local"    # + ":<posture>"
RESIDENCY_REASON_LINK_PERMITS_REMOTE = "link_posture_permits_remote"    # + ":<posture>"
RESIDENCY_REASON_BELOW_KIND_MINIMUM = "link_quality_below_kind_minimum"  # + ":<q><min>"
RESIDENCY_REASON_KIND_MINIMUM_UNVERIFIABLE = "link_quality_unverifiable_for_kind"

# 프로파일 데이터 자체의 모순 (결정이 아니라 선언의 문제)
VIOLATION_OUTAGE_CRITICAL_NOT_RESIDENT = "outage_critical_not_resident"        # + ":<kind>"
VIOLATION_SAFETY_AFFECTING_NOT_CORE = "safety_affecting_kind_not_core"          # + ":<kind>"
VIOLATION_UNKNOWN_OUTAGE_BEHAVIOR = "unknown_outage_behavior"                   # + ":<kind>"
VIOLATION_FALLBACK_KIND_MISSING = "local_fallback_kind_missing"                 # + ":<kind>"

#: 이 모듈이 만들어내는 모든 토큰. 사전이 소비한다.
LINK_POSTURE_REASONS: tuple[str, ...] = (
    LINK_REASON_DECLARED,
    LINK_REASON_QUALITY_UNKNOWN,
    LINK_REASON_SAMPLES_INSUFFICIENT,
    LINK_REASON_AT_OR_BELOW_FLOOR,
    LINK_REASON_BELOW_RESTORE_MARGIN,
    LINK_REASON_UNSTABLE,
    LINK_REASON_STABLE,
)

RESIDENCY_REASONS: tuple[str, ...] = (
    RESIDENCY_REASON_RESIDENT_BY_PURPOSE,
    RESIDENCY_REASON_EDGE_BY_PURPOSE,
    RESIDENCY_REASON_LINK_REQUIRES_LOCAL,
    RESIDENCY_REASON_LINK_PERMITS_REMOTE,
    RESIDENCY_REASON_BELOW_KIND_MINIMUM,
    RESIDENCY_REASON_KIND_MINIMUM_UNVERIFIABLE,
)

RESIDENCY_VIOLATIONS: tuple[str, ...] = (
    VIOLATION_OUTAGE_CRITICAL_NOT_RESIDENT,
    VIOLATION_SAFETY_AFFECTING_NOT_CORE,
    VIOLATION_UNKNOWN_OUTAGE_BEHAVIOR,
    VIOLATION_FALLBACK_KIND_MISSING,
)

#: 원격에 기댈 수 있는 유일한 자세. 나머지는 전부 "끌어와라"다.
_REMOTE_OK = LinkPosture.REMOTE_OK


def thresholds_from_transition_policy(policy: LinkTransitionPolicy) -> LinkPostureThresholds:
    """운행 중 전환 정책에서 배치 시점 기준값을 끌어온다.

    두 판정이 같은 숫자를 쓰게 하는 유일한 연결점이다(AI-N-03). 운행 중
    정책이 오탐으로 여유를 좁히면(`false_reductions`) 그 결과가 다음 배치
    판정에도 그대로 반영된다.
    """
    return LinkPostureThresholds(
        floor=policy.floor,
        restore_margin=policy.restore_margin,
        min_samples=max(1, policy.restore_hold_samples // 2),
    )


@dataclass(frozen=True)
class LinkPostureAssessment:
    """배치 시점에 본 링크의 자세와 그 근거."""

    posture: LinkPosture
    reason: str
    quality: float | None
    stability: float | None
    source: str

    @property
    def permits_remote(self) -> bool:
        return self.posture is _REMOTE_OK


def assess_link(
    link: LinkProfile | None,
    thresholds: LinkPostureThresholds | None = None,
) -> LinkPostureAssessment:
    """링크 특성 → `LinkPosture`. 측정값이 없어도 반드시 답을 낸다.

    판정 순서가 곧 우선순위다. 선언이 측정을 덮고, 표본 부족은 모름과 같고,
    바닥 아래는 즉시 LOCAL_ONLY, 평균이 좋아도 불안정하면 REDUCING이다.
    마지막 항목이 핵심이다 — 평균 품질만 보면 "어떤 날은 0% 손실, 어떤 날은
    33% 손실"인 장치가 좋은 링크로 보인다.
    """
    thresholds = thresholds or LinkPostureThresholds()
    link = link or LinkProfile()

    if link.declared_posture is not None:
        try:
            posture = LinkPosture(link.declared_posture)
        except ValueError:
            # 잘못된 선언을 조용히 좋은 쪽으로 해석하지 않는다.
            return LinkPostureAssessment(
                LinkPosture.LOCAL_ONLY, LINK_REASON_QUALITY_UNKNOWN,
                link.quality, link.stability, link.source,
            )
        return LinkPostureAssessment(
            posture, f"{LINK_REASON_DECLARED}:{posture.value}",
            link.quality, link.stability, link.source,
        )

    if link.quality is None:
        return LinkPostureAssessment(
            LinkPosture.LOCAL_ONLY, LINK_REASON_QUALITY_UNKNOWN, None, link.stability, link.source
        )

    if link.samples < thresholds.min_samples:
        # 순간값 한 번으로 배치를 흔들지 않는다(AI-N-03: 이력과 상태 변화를
        # 구분하라). 실제로 같은 장치를 다른 시각에 재면 0% 손실과 33% 손실이
        # 둘 다 나온다 — 한 번의 관측은 배치 근거가 되기에 모자란다.
        return LinkPostureAssessment(
            LinkPosture.LOCAL_ONLY,
            f"{LINK_REASON_SAMPLES_INSUFFICIENT}:{link.samples}/{thresholds.min_samples}",
            link.quality, link.stability, link.source,
        )

    if link.quality <= thresholds.floor:
        return LinkPostureAssessment(
            LinkPosture.LOCAL_ONLY, f"{LINK_REASON_AT_OR_BELOW_FLOOR}:{link.quality:g}",
            link.quality, link.stability, link.source,
        )

    if link.quality < thresholds.floor + thresholds.restore_margin:
        return LinkPostureAssessment(
            LinkPosture.REDUCING, f"{LINK_REASON_BELOW_RESTORE_MARGIN}:{link.quality:g}",
            link.quality, link.stability, link.source,
        )

    if link.stability is not None and link.stability < thresholds.min_stability:
        return LinkPostureAssessment(
            LinkPosture.REDUCING, f"{LINK_REASON_UNSTABLE}:{link.stability:g}",
            link.quality, link.stability, link.source,
        )

    return LinkPostureAssessment(
        _REMOTE_OK, f"{LINK_REASON_STABLE}:{link.quality:g}",
        link.quality, link.stability, link.source,
    )


@dataclass(frozen=True)
class ResidencyDecision:
    """한 capability kind에 대한 배치 결정 1건 — 기계가 읽을 수 있는 사유 포함."""

    kind: str
    placement: Residency
    reason: str
    policy: ResidencyPolicy
    survives_outage: bool
    quality_is_safety_affecting: bool
    #: 온디바이스에 두지 않았을 때 엣지에서 이 kind를 담당하는 것
    edge_service: str | None
    #: 엣지에 닿지 못하는 동안의 동작
    outage_behavior: str
    local_fallback_kind: str | None

    @property
    def is_ondevice(self) -> bool:
        return self.placement is Residency.ONDEVICE


@dataclass(frozen=True)
class ResidencyPlan:
    """한 장치·한 링크 상태에 대한 배치 결정 전체.

    `violations`는 결정 실패가 아니라 **선언 데이터의 모순**이다. 예: 통신
    단절 중에도 살아야 한다고 선언한 기능이 엣지로 결정됐다면, 그건 판정
    버그가 아니라 목적 프로파일이 서로 모순되는 말을 하고 있다는 뜻이고
    배치 전에 사람이 봐야 한다(AI-B-09: 운영 후보가 되기 전에 검증).
    """

    purpose_id: str
    link: LinkPostureAssessment
    decisions: tuple[ResidencyDecision, ...]
    violations: tuple[str, ...] = ()

    # --- 조회 ---------------------------------------------------------------
    @property
    def ondevice_kinds(self) -> tuple[str, ...]:
        return tuple(d.kind for d in self.decisions if d.is_ondevice)

    @property
    def edge_kinds(self) -> tuple[str, ...]:
        return tuple(d.kind for d in self.decisions if not d.is_ondevice)

    def decision_for(self, kind: str) -> ResidencyDecision | None:
        for decision in self.decisions:
            if decision.kind == kind:
                return decision
        return None

    def survives_outage_kinds(self) -> tuple[str, ...]:
        """통신이 끊긴 동안에도 장치 안에서 계속 도는 기능들."""
        return tuple(d.kind for d in self.decisions if d.is_ondevice and d.survives_outage)

    # --- 기존 경로로 넘기기 --------------------------------------------------
    def ondevice_profile(self, base: DeploymentProfile) -> DeploymentProfile:
        """온디바이스 결정분만 활성화한 `DeploymentProfile`.

        도메인·폐쇄망·내부 엔드포인트 등 나머지 배포 성질은 `base`를 그대로
        따른다 — 이 계획이 바꾸는 것은 "이 장치가 무엇을 켜는가" 하나뿐이다.
        결과는 기존 `ZoneApplication`에 그대로 들어가며, 예산·태그·축소는
        전부 거기서 처리된다(AI-C-05, AI-B-04, AI-C-13).
        """
        from dataclasses import replace as _replace

        return _replace(base, active_capability_kinds=self.ondevice_kinds)

    def capability_specs(self, purpose: DevicePurposeProfile) -> list[CapabilitySpec]:
        """온디바이스 결정분을 기존 `CapabilitySpec`으로 환산한다."""
        specs: list[CapabilitySpec] = []
        for kind in self.ondevice_kinds:
            declared = purpose.spec(kind)
            if declared is None:  # pragma: no cover - 계획은 목적에서만 나온다
                continue
            specs.append(
                CapabilitySpec(
                    kind=declared.kind,
                    is_core=declared.is_core,
                    requirement=declared.requirement or CapabilityRequirement(),
                    degrade_rank=declared.degrade_rank,
                )
            )
        return specs

    # --- 엣지 쪽 짝 ----------------------------------------------------------
    def edge_complement(self) -> tuple["EdgeComplement", ...]:
        """온디바이스에 두지 않은 kind마다 "누가 대신 하고, 끊기면 어떻게 되는가".

        AI-C-05의 격리 규칙을 배치 축으로 옮긴 것이다. 엣지 서비스에 닿지
        못하는 것은 그 기능 하나의 문제여야 하고 장치 전체의 문제가 되어서는
        안 되므로, 각 항목이 자기 단절 동작을 따로 들고 있다.
        """
        return tuple(
            EdgeComplement(
                kind=d.kind,
                edge_service=d.edge_service,
                outage_behavior=d.outage_behavior,
                local_fallback_kind=d.local_fallback_kind,
            )
            for d in self.decisions
            if not d.is_ondevice
        )

    def outage_survival_report(self) -> dict:
        """통신 단절 시뮬레이션 요약 — 무엇이 살아남고 무엇이 멈추는가."""
        keeps, queued, degrades, stops = [], [], [], []
        for decision in self.decisions:
            if decision.is_ondevice:
                if decision.outage_behavior == OUTAGE_QUEUED_FOR_EDGE:
                    queued.append(decision.kind)
                else:
                    keeps.append(decision.kind)
            elif decision.outage_behavior == OUTAGE_LOCAL_FALLBACK:
                degrades.append(decision.kind)
            else:
                stops.append(decision.kind)
        return {
            "keeps_running": tuple(keeps),
            "keeps_running_results_queued": tuple(queued),
            "degrades_to_local_fallback": tuple(degrades),
            "stops_until_link_returns": tuple(stops),
        }


@dataclass(frozen=True)
class EdgeComplement:
    """온디바이스에 없는 kind 하나의 엣지 쪽 짝."""

    kind: str
    edge_service: str | None
    outage_behavior: str
    local_fallback_kind: str | None


def decide_residency(
    purpose: DevicePurposeProfile,
    link: LinkProfile | None = None,
    thresholds: LinkPostureThresholds | None = None,
) -> ResidencyPlan:
    """목적 선언 + 링크 특성 → 장치별 배치 계획.

    `link`를 주면 목적 프로파일에 적힌 링크 대신 그것으로 판정한다 —
    "링크가 나빠지면?" what-if의 진입점이며, 목적 데이터는 손대지 않는다.

    판정 규칙은 세 줄이 전부이고 어디에도 도메인·장치 이름이 없다:

    * RESIDENT → 항상 온디바이스
    * EDGE_SERVED → 항상 엣지
    * LINK_DEPENDENT → 링크를 신뢰할 수 있을 때만 엣지

    "신뢰할 수 있다"는 자세(REMOTE_OK)와 kind별 `min_link_quality`를 **둘 다**
    만족하는 것이다. 후자가 필요한 이유는 모듈 docstring 2번 — 픽셀을
    오가게 하는 kind는 메타데이터만 오가는 kind와 같은 링크에서도 비용이
    전혀 다르다.
    """
    assessment = assess_link(link if link is not None else purpose.link, thresholds or purpose.link_thresholds)
    decisions = tuple(_decide_one(spec, assessment) for spec in purpose.capabilities)
    return ResidencyPlan(
        purpose_id=purpose.purpose_id,
        link=assessment,
        decisions=decisions,
        violations=_violations(purpose, decisions),
    )


def _decide_one(spec: CapabilityResidencySpec, link: LinkPostureAssessment) -> ResidencyDecision:
    placement, reason = _placement_of(spec, link)
    return ResidencyDecision(
        kind=spec.kind,
        placement=placement,
        reason=reason,
        policy=spec.policy,
        survives_outage=spec.survives_outage,
        quality_is_safety_affecting=spec.quality_is_safety_affecting,
        edge_service=None if placement is Residency.ONDEVICE else spec.edge_service,
        outage_behavior=spec.outage_behavior,
        local_fallback_kind=spec.local_fallback_kind,
    )


def _placement_of(spec: CapabilityResidencySpec, link: LinkPostureAssessment) -> tuple[Residency, str]:
    if spec.policy is ResidencyPolicy.RESIDENT:
        return Residency.ONDEVICE, RESIDENCY_REASON_RESIDENT_BY_PURPOSE
    if spec.policy is ResidencyPolicy.EDGE_SERVED:
        return Residency.EDGE, RESIDENCY_REASON_EDGE_BY_PURPOSE

    # --- LINK_DEPENDENT -----------------------------------------------------
    if not link.permits_remote:
        return Residency.ONDEVICE, f"{RESIDENCY_REASON_LINK_REQUIRES_LOCAL}:{link.posture.value}"

    if spec.min_link_quality is not None:
        if link.quality is None:
            # 자세는 원격을 허용했지만(선언 등) 이 kind가 요구하는 수치를
            # 확인할 수단이 없다. 확인 못 한 것을 충족으로 읽지 않는다.
            return Residency.ONDEVICE, RESIDENCY_REASON_KIND_MINIMUM_UNVERIFIABLE
        if link.quality < spec.min_link_quality:
            return (
                Residency.ONDEVICE,
                f"{RESIDENCY_REASON_BELOW_KIND_MINIMUM}:{link.quality:g}<{spec.min_link_quality:g}",
            )

    return Residency.EDGE, f"{RESIDENCY_REASON_LINK_PERMITS_REMOTE}:{link.posture.value}"


def _violations(purpose: DevicePurposeProfile, decisions: tuple[ResidencyDecision, ...]) -> tuple[str, ...]:
    """선언 데이터의 모순만 모은다. 자원 부족·provider 부재는 여기 오지 않는다."""
    found: list[str] = []
    for decision in decisions:
        spec = purpose.spec(decision.kind)
        if decision.survives_outage and not decision.is_ondevice:
            found.append(f"{VIOLATION_OUTAGE_CRITICAL_NOT_RESIDENT}:{decision.kind}")
        if decision.quality_is_safety_affecting and spec is not None and not spec.is_core:
            # 안전 판정을 바꾸는 품질은 여유를 만들기 위한 축소 손잡이가 될 수
            # 없다. 축소 대상이 아니라는 뜻이므로 core로 선언돼 있어야 한다.
            found.append(f"{VIOLATION_SAFETY_AFFECTING_NOT_CORE}:{decision.kind}")
        if decision.outage_behavior not in OUTAGE_BEHAVIORS:
            found.append(f"{VIOLATION_UNKNOWN_OUTAGE_BEHAVIOR}:{decision.kind}")
        if decision.outage_behavior == OUTAGE_LOCAL_FALLBACK and not decision.local_fallback_kind:
            found.append(f"{VIOLATION_FALLBACK_KIND_MISSING}:{decision.kind}")
    return tuple(found)
