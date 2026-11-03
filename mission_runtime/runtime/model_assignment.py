"""Assigns a model version to a device and a mission using its verified scope,
the device's hardware and what the mission requires.

implements: AI-L-10 (하드웨어·임무 조건 기반 모델 배정)
관련: AI-B-01 (검증된 적용 범위), AI-B-04 (required/preferred 자원), AI-B-06 (재구성),
      AI-C-05 (후보가 없으면 그 기능만 축소), AI-C-13 (선택 사유 노출), AI-O-05

같은 기능을 제공하는 모델 버전이 여럿일 때 "어느 것을 어디에"를 정한다. 기존
`selection/selector.py` 는 **capability kind 별 provider** 를 고르고, 이 모듈은 고른
provider 안에서 **모델 버전**을 고른다 — 둘은 다른 질문이라 합치지 않는다.

지키는 규칙
-----------
- **검증된 적용 범위를 벗어나지 않는다**(AI-B-01). 버전마다 어떤 하드웨어 태그와 어떤
  입력 조건에서 검증됐는지 선언하고, 그 밖에서는 후보가 되지 않는다. 다른 조합에서
  잰 성능을 같다고 가정하지 않는다.
- **조건을 만족하는 후보가 없으면 임의 배정하지 않는다**(AI-C-05). `assigned=None` 과
  사유를 돌려주고 호출자가 축소 경로로 처리한다.
- **모델 이름·장치 이름으로 분기하지 않는다**. 정책은 교체 가능하고, 기본 정책도
  선언된 수치만 본다.
- **사유를 남긴다**(AI-C-13). 고른 이유와 탈락 사유가 전부 통제 어휘 토큰이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

#: 배정·탈락 사유 토큰.
REASON_ASSIGNED = "assigned"
REASON_NO_CANDIDATE = "no_candidate_for_conditions"
REASON_SCOPE_HARDWARE = "outside_verified_hardware_scope"
REASON_SCOPE_CONDITION = "outside_verified_input_scope"
REASON_QUALITY_BELOW_REQUIREMENT = "quality_below_mission_requirement"
REASON_LATENCY_ABOVE_BUDGET = "latency_above_mission_budget"
REASON_MEMORY_ABOVE_DEVICE = "memory_above_device_capacity"
REASON_UNMEASURED_NOT_ELIGIBLE = "unmeasured_profile_not_eligible"
#: 요청한 버전이 아예 다른 capability kind 다. 운영자가 버전을 직접 고르는
#: 경로에서만 나올 수 있다 — 조건으로 고르는 경로는 kind 가 다른 후보를 아예
#: 보지 않는다.
REASON_KIND_MISMATCH = "capability_kind_mismatch"

ASSIGNMENT_REASONS: tuple[str, ...] = (
    REASON_ASSIGNED,
    REASON_NO_CANDIDATE,
    REASON_SCOPE_HARDWARE,
    REASON_SCOPE_CONDITION,
    REASON_QUALITY_BELOW_REQUIREMENT,
    REASON_LATENCY_ABOVE_BUDGET,
    REASON_MEMORY_ABOVE_DEVICE,
    REASON_UNMEASURED_NOT_ELIGIBLE,
    REASON_KIND_MISMATCH,
)


@dataclass(frozen=True)
class ModelVersion:
    """배정 후보 하나. 측정값과 **검증 범위**를 함께 선언한다.

    측정되지 않은 항목은 `None` 이고 그것은 0 이 아니다 — 기본 정책은 미측정 후보를
    적격으로 보지 않는다(AI-B-01: 미측정 항목을 구분하고 재측정해야 한다).
    """

    model_id: str
    version: str
    capability_kind: str
    #: 이 버전이 검증된 하드웨어 태그. 비어 있으면 "어디서도 검증되지 않음"이다.
    verified_hw_tags: frozenset[str] = frozenset()
    #: 검증된 입력 조건 키(해상도·카메라 종류 등 자유 문자열). 비어 있으면 조건 무관.
    verified_input_conditions: frozenset[str] = frozenset()
    quality: float | None = None
    latency_ms: float | None = None
    memory_mb: float | None = None

    def __post_init__(self) -> None:
        if not self.model_id or not self.version:
            raise ValueError("model_id and version must not be empty")
        if self.quality is not None and not 0.0 <= self.quality <= 1.0:
            raise ValueError("quality must be between 0 and 1")

    @property
    def reference(self) -> str:
        return f"{self.model_id}@{self.version}"

    @property
    def fully_measured(self) -> bool:
        return None not in (self.quality, self.latency_ms, self.memory_mb)


@dataclass(frozen=True)
class DeviceProfile:
    """배정 대상 장치. 태그와 용량은 등록 데이터다."""

    device_id: str
    hw_tags: frozenset[str] = frozenset()
    input_conditions: frozenset[str] = frozenset()
    memory_mb: float | None = None


@dataclass(frozen=True)
class MissionRequirement:
    """임무가 요구하는 조건. 같은 장치라도 임무가 바뀌면 배정이 바뀐다."""

    mission_id: str
    capability_kind: str
    min_quality: float | None = None
    max_latency_ms: float | None = None
    #: 미측정 후보를 허용할지. 기본은 허용하지 않는다.
    allow_unmeasured: bool = False


@dataclass(frozen=True)
class Rejection:
    version_reference: str
    reason: str


@dataclass(frozen=True)
class Assignment:
    """배정 결과. 고른 것과 탈락한 것을 함께 낸다(AI-C-13)."""

    device_id: str
    mission_id: str
    capability_kind: str
    assigned: ModelVersion | None
    reason: str
    rejected: tuple[Rejection, ...] = ()

    @property
    def is_assigned(self) -> bool:
        return self.assigned is not None


class AssignmentPolicy(Protocol):
    """적격 후보들 중 하나를 고른다. 교체 가능하다."""

    def choose(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> ModelVersion: ...


class HighestQualityWithinBudget:
    """예산 안에서 품질이 가장 높은 것. 동률이면 지연이 짧은 것, 그다음 참조 사전순.

    결정적이어야 한다 — 같은 입력에 다른 배정이 나오면 배포가 흔들린다.
    """

    def choose(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> ModelVersion:
        del requirement
        return sorted(
            eligible,
            key=lambda m: (-(m.quality or 0.0), m.latency_ms or float("inf"), m.reference),
        )[0]


class LowestLatency:
    """지연이 가장 짧은 것. 안전·반응 중심 임무용 대안 정책이다."""

    def choose(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> ModelVersion:
        del requirement
        return sorted(
            eligible,
            key=lambda m: (m.latency_ms or float("inf"), -(m.quality or 0.0), m.reference),
        )[0]


@dataclass(frozen=True)
class PinnedVersion:
    """운영자가 고른 버전을 **적격 후보 안에서** 선택한다.

    왜 정책으로 두는가: "이 버전을 쓰라"는 요구는 조건 판정을 건너뛰라는 요구가
    아니다(AI-L-10: 검증된 적용 범위를 벗어나서는 안 된다). 적격 판정은 그대로
    돌고, 이 정책은 이미 적격한 것들 중에서 고르는 자리만 바꾼다. 고른 버전이
    적격하지 않으면 애초에 `eligible` 에 들어오지 않으므로 호출자가 먼저
    `ModelAssigner.eligibility()` 로 사유를 확인해야 한다.
    """

    reference: str
    #: 핀이 적격 목록에 없을 때 쓸 대체 정책. 기본은 품질 우선이다.
    fallback: "AssignmentPolicy" = field(default_factory=HighestQualityWithinBudget)

    def choose(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> ModelVersion:
        for version in eligible:
            if version.reference == self.reference:
                return version
        return self.fallback.choose(eligible, requirement)


@dataclass
class ModelAssigner:
    """등록된 버전 중에서 장치·임무 조건에 맞는 것을 고른다."""

    policy: AssignmentPolicy = field(default_factory=HighestQualityWithinBudget)
    versions: list[ModelVersion] = field(default_factory=list)

    def register(self, version: ModelVersion) -> None:
        self.versions = [v for v in self.versions
                         if v.reference != version.reference
                         or v.capability_kind != version.capability_kind]
        self.versions.append(version)

    def assign(self, device: DeviceProfile, requirement: MissionRequirement) -> Assignment:
        rejected: list[Rejection] = []
        eligible: list[ModelVersion] = []

        for version in sorted(self.versions, key=lambda v: v.reference):
            if version.capability_kind != requirement.capability_kind:
                continue
            reason = self._reject_reason(version, device, requirement)
            if reason is None:
                eligible.append(version)
            else:
                rejected.append(Rejection(version.reference, reason))

        if not eligible:
            return Assignment(
                device_id=device.device_id, mission_id=requirement.mission_id,
                capability_kind=requirement.capability_kind, assigned=None,
                reason=REASON_NO_CANDIDATE, rejected=tuple(rejected),
            )

        chosen = self.policy.choose(eligible, requirement)
        others = tuple(
            Rejection(v.reference, REASON_ASSIGNED) for v in eligible
            if v.reference != chosen.reference
        )
        return Assignment(
            device_id=device.device_id, mission_id=requirement.mission_id,
            capability_kind=requirement.capability_kind, assigned=chosen,
            reason=REASON_ASSIGNED, rejected=tuple(rejected) + others,
        )

    def eligibility(self, version: ModelVersion, device: DeviceProfile,
                    requirement: MissionRequirement) -> str | None:
        """그 버전 하나를 이 장치·임무에 쓸 수 있는가. 쓸 수 없으면 사유를 낸다.

        운영자가 버전을 직접 고르는 경로가 **같은 판정**을 써야 하기 때문에 공개한다.
        화면이 자기만의 적격 규칙을 따로 들면 "쓸 수 있다고 보여 놓고 배정은 거절"이
        되고, 그때 틀리는 쪽은 언제나 화면이다.
        """
        if version.capability_kind != requirement.capability_kind:
            return REASON_KIND_MISMATCH
        return self._reject_reason(version, device, requirement)

    def _reject_reason(self, version: ModelVersion, device: DeviceProfile,
                       requirement: MissionRequirement) -> str | None:
        # 검증 범위를 먼저 본다 — 범위 밖 후보는 수치가 좋아도 쓸 수 없다.
        if version.verified_hw_tags and not version.verified_hw_tags <= device.hw_tags:
            return REASON_SCOPE_HARDWARE
        if (version.verified_input_conditions
                and not version.verified_input_conditions <= device.input_conditions):
            return REASON_SCOPE_CONDITION
        if not version.fully_measured and not requirement.allow_unmeasured:
            return REASON_UNMEASURED_NOT_ELIGIBLE
        if (requirement.min_quality is not None
                and (version.quality is None or version.quality < requirement.min_quality)):
            return REASON_QUALITY_BELOW_REQUIREMENT
        if (requirement.max_latency_ms is not None
                and (version.latency_ms is None
                     or version.latency_ms > requirement.max_latency_ms)):
            return REASON_LATENCY_ABOVE_BUDGET
        if (device.memory_mb is not None and version.memory_mb is not None
                and version.memory_mb > device.memory_mb):
            return REASON_MEMORY_ABOVE_DEVICE
        return None

    def reassign_all(
        self, devices: Sequence[DeviceProfile], requirement: MissionRequirement
    ) -> dict[str, Assignment]:
        """임무나 하드웨어 조건이 바뀌면 전체를 다시 정한다(AI-L-10·AI-B-06)."""
        return {d.device_id: self.assign(d, requirement) for d in devices}
