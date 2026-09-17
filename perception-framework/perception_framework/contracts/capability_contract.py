"""General-component Capability declaration contract.

implements: AI-C-18

AI-C-18: "로봇, 센서, 카메라, 연산 노드, AI 기능과 외부 서비스는 자신이 제공할 수
있는 capability를 공통 의미 규약으로 선언할 수 있어야 한다 ... 모든 항목이 항상
존재한다고 가정해서는 안 된다."

Status: 단계적 구현. `docs/ai/design/external-technology-decisions.md` §4가 정의한
5계층 목표 계약(`Capability → Implementation → ExecutionProfile → RuntimeInstance`,
그리고 이를 요구하는 `TaskIntent`)의 dataclass와 §4.3 selector 불변조건 중 순수하게
데이터로만 판정 가능한 부분(3/4)을 구현한다. `contracts/physical_command.py::Capability`
(물리 명령 action 전용 선언)와 `selection/selector.py::CapabilitySelector`(실제 provider
선택 알고리즘)는 아직 이 계약으로 이관되지 않았다 — §4 "호환 schema와 migration이
끝나기 전에는 구현 완료로 간주하지 않는다"에 따라 기존 코드는 그대로 두고 이 모듈을
나란히 추가한다. 전체 selector 통합은 `docs/ai/design/external-technology-decisions.md`
§10-2에 남은 합의 사항으로 기록되어 있다.

설계 근거(D. Semantic Reference만 — 런타임 의존성 없음): IDTA Capability Description,
IDTA AI Model Nameplate/AI Deployment, ISO 22166-201/-202, Capability/Skill reference
model, TOSCA 2.0, KServe Open Inference Protocol V2, MLModelScope/MLPerf Inference —
전부 기존에 `docs/ai/design/external-technology-decisions.md` §4.2가 검토·채택한 것과
동일하며 이 모듈에서 새로 조사하지 않았다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState


@dataclass(frozen=True)
class Capability:
    """구현 독립적인 의미와 제약 (IDTA Capability Description, ISO 22166 설계 근거).

    `kind`는 `CapabilityRegistry`가 쓰는 capability-kind 식별자와 같은 이름공간이다
    (`contracts/capability.py::CapabilityRequirement.required/optional`). 모든 선택
    필드는 "항상 존재한다고 가정하지 않는다"는 AI-C-18 원칙에 따라 기본값을 가진다.
    """

    kind: str
    input_schema: str | None = None
    output_schema: str | None = None
    properties: dict[str, str] = field(default_factory=dict)
    preconditions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Implementation:
    """Capability를 실제로 실현하는 provider/model artifact.

    설계 근거: Capability/Skill reference model, IDTA AI Model Nameplate — capability의
    "무엇을 하는가"와 "무엇으로 하는가"를 분리한다.
    """

    capability_kind: str
    provider_id: str
    implementation_version: str
    model_ref: str | None = None
    artifact_digest: str | None = None


@dataclass(frozen=True)
class ExecutionProfile:
    """고정 조건(model/artifact × runtime × hardware × input profile)에서 실측한
    실행 특성.

    AI-B-01: "다른 구성에서 측정한 성능·비용을 자동으로 동일하다고 가정해서는 안
    되며 새 구성은 재측정·재검증해야 한다." `matches_conditions()`가 §4.3 불변조건
    3(조건이 하나라도 다르면 이 evidence를 재사용하지 않음)을 구현한다.

    설계 근거: IDTA AI Deployment, MLModelScope, MLPerf Inference(조건 고정·재현
    가능한 execution evidence 방법론만 참고 — MLPerf 자체를 core dependency로 쓰지
    않음).
    """

    implementation_ref: str
    runtime: str
    hardware_tags: tuple[str, ...]
    input_profile: str
    latency_ms: float | None = None
    quality: dict[str, float] = field(default_factory=dict)
    resources: dict[str, float] = field(default_factory=dict)
    evidence_ref: str | None = None
    measured_at: float | None = None
    unmeasured_fields: tuple[str, ...] = ()

    def matches_conditions(
        self, *, runtime: str, hardware_tags: tuple[str, ...], input_profile: str
    ) -> bool:
        """이 프로파일의 측정값을 지금 조건에서 그대로 써도 되는지 판정한다.

        하드웨어 태그는 순서 없는 집합으로 비교한다 — 태그 나열 순서가 다르다고
        다른 실행 구성으로 취급하지 않는다.
        """
        return (
            self.runtime == runtime
            and set(self.hardware_tags) == set(hardware_tags)
            and self.input_profile == input_profile
        )


@dataclass(frozen=True)
class RuntimeInstance:
    """현재 배치와 가용성.

    설계 근거: KServe Open Inference Protocol V2의 live/ready/model-ready 패턴 —
    "과거에 검증됐다"와 "지금 응답 가능하다"를 분리한다.
    """

    instance_id: str
    deployment_ref: str
    healthy: bool
    health_ttl: float
    health_checked_at: float
    current_load: float | None = None

    def is_selectable(self, *, now: float) -> bool:
        """§4.3 불변조건 4: health가 없거나 TTL이 만료된 runtime instance는 과거
        benchmark가 있어도 선택하지 않는다.
        """
        if not self.healthy:
            return False
        return (now - self.health_checked_at) <= self.health_ttl


@dataclass(frozen=True)
class TaskIntent:
    """작업이 요구하는 capability와 hard constraint.

    설계 근거: IDTA required/provided matching, TOSCA requirement/capability
    allocation — capability 매칭과 배치 제약을 같은 대상(TaskIntent)에서 표현한다.
    """

    required_capabilities: tuple[str, ...] = ()
    optional_capabilities: tuple[str, ...] = ()
    deadline: float | None = None
    max_input_age: float | None = None
    minimum_evidence: str | None = None
    safety_invariants: tuple[str, ...] = ()

    def evaluate_availability(self, available: set[str]) -> CapabilityState:
        """required/optional 평가는 새 판정 로직을 만들지 않고 기존 AI-C-05 계약에
        위임한다 — §4.3 불변조건 5(required 부족을 optional로 메워 성공 처리하지
        않음)는 `CapabilityRequirement.evaluate`가 이미 보장한다(optional 결손은
        DEGRADED까지만, required 결손만 DISABLED).
        """
        return CapabilityRequirement(
            required=self.required_capabilities, optional=self.optional_capabilities
        ).evaluate(available)

    def is_within_deadline(self, *, now: float) -> bool:
        """§4.3 불변조건 2: deadline은 hard filter다."""
        return self.deadline is None or now <= self.deadline

    def is_input_fresh_enough(self, *, frame_age: float | None) -> bool:
        """§4.3 불변조건 2: input age는 hard filter다. `frame_age`를 알 수 없으면
        (None) 판정을 보류하고 통과시킨다 — 미측정 항목이 배치를 막지 않는다."""
        if self.max_input_age is None or frame_age is None:
            return True
        return frame_age <= self.max_input_age
