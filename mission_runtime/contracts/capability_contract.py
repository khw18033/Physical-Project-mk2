"""General-component Capability declaration contract.

implements: AI-C-18

AI-C-18: "로봇, 센서, 카메라, 연산 노드, AI 기능과 외부 서비스는 자신이 제공할 수
있는 capability를 공통 의미 규약으로 선언할 수 있어야 한다 ... 모든 항목이 항상
존재한다고 가정해서는 안 된다."

Status: 단계적 구현. `docs/technology-boundaries.md` §4가 정의한
5계층 목표 계약(`Capability → Implementation → ExecutionProfile → RuntimeInstance`,
그리고 이를 요구하는 `TaskIntent`)의 dataclass와 §4.3 selector 불변조건 중 순수하게
데이터로만 판정 가능한 부분(3/4)을 구현한다. `contracts/physical_command.py::Capability`
(물리 명령 action 전용 선언)와 `selection/selector.py::CapabilitySelector`(실제 provider
선택 알고리즘)는 아직 이 계약으로 이관되지 않았다 — §4 "호환 schema와 migration이
끝나기 전에는 구현 완료로 간주하지 않는다"에 따라 기존 코드는 그대로 두고 이 모듈을
나란히 추가한다. 전체 selector 통합은 `docs/technology-boundaries.md`
§10-2에 남은 합의 사항으로 기록되어 있다.

설계 근거(D. Semantic Reference만 — 런타임 의존성 없음): IDTA Capability Description,
IDTA AI Model Nameplate/AI Deployment, ISO 22166-201/-202, Capability/Skill reference
model, TOSCA 2.0, KServe Open Inference Protocol V2, MLModelScope/MLPerf Inference —
전부 기존에 `docs/technology-boundaries.md` §4.2가 검토·채택한 것과
동일하며 이 모듈에서 새로 조사하지 않았다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState


# -- AI-C-18 선언 항목표 ------------------------------------------------------
# 요구사항이 열거한 항목을 **토큰으로 고정**한다. 이 표가 있는 이유는 하나다 —
# "항목마다 담길 칸이 있는가" 를 사람의 기억이 아니라 시험으로 물을 수 있어야
# 한다(`tests/test_capability_contract.py`). 토큰은 `undeclared_items()` 가
# 돌려주는 값 어휘이기도 하므로 닫힌 어휘다.

#: 기능의 의미. 구현이 아니라 목적 수준의 식별자다.
ITEM_MEANING = "meaning"
#: 입력 정보와 schema 참조.
ITEM_INPUT_SCHEMA = "input_schema"
#: 출력 정보와 schema 참조.
ITEM_OUTPUT_SCHEMA = "output_schema"
#: 단위·좌표·시간 기준. 숫자만 오고 기준이 없으면 그 숫자는 해석되지 않는다(AI-C-02/03).
ITEM_BASIS = "basis"
#: 필수·선택 실행 조건.
ITEM_EXECUTION_CONDITIONS = "execution_conditions"
#: 취소 가능 여부.
ITEM_CANCELLABLE = "cancellable"
#: 동일 입력 반복 호출 특성(멱등성).
ITEM_IDEMPOTENT = "idempotent"
#: 동기·비동기 특성.
ITEM_INVOCATION = "invocation"
#: 수행·관측 범위.
ITEM_SCOPE = "scope"
#: 현재 상태. 선언이 아니라 **지금** 의 사실이라 다른 계층(RuntimeInstance)에 산다.
ITEM_STATE = "state"
#: 버전.
ITEM_VERSION = "version"
#: 확인 가능한 품질·지연·자원 특성. 실측 근거는 ExecutionProfile 이 소유한다(AI-B-01).
ITEM_PERFORMANCE = "performance"

#: AI-C-18 이 열거한 선언 항목 전부. **닫힌 어휘다** — 요구사항 본문이 바뀌지
#: 않는 한 늘지 않는다.
CAPABILITY_DECLARATION_ITEMS: tuple[str, ...] = (
    ITEM_MEANING, ITEM_INPUT_SCHEMA, ITEM_OUTPUT_SCHEMA, ITEM_BASIS,
    ITEM_EXECUTION_CONDITIONS, ITEM_CANCELLABLE, ITEM_IDEMPOTENT,
    ITEM_INVOCATION, ITEM_SCOPE, ITEM_STATE, ITEM_VERSION, ITEM_PERFORMANCE,
)

#: 어느 계층이 어느 항목을 담는가. 한 항목을 두 계층이 담으면 같은 사실에 주인이
#: 둘이 되므로(원칙 #19 와 같은 이유) **겹치지 않게** 나눈다.
DECLARATION_ITEM_OWNERS: dict[str, tuple[str, ...]] = {
    "Capability": (
        ITEM_MEANING, ITEM_INPUT_SCHEMA, ITEM_OUTPUT_SCHEMA, ITEM_BASIS,
        ITEM_EXECUTION_CONDITIONS, ITEM_CANCELLABLE, ITEM_IDEMPOTENT,
        ITEM_INVOCATION, ITEM_SCOPE,
    ),
    "Implementation": (ITEM_VERSION,),
    "ExecutionProfile": (ITEM_PERFORMANCE,),
    "RuntimeInstance": (ITEM_STATE,),
}

#: `invocation` 의 값 어휘. 닫힌 어휘다 — 셋째 모드는 계약 변경이다.
INVOCATION_MODES: tuple[str, ...] = ("synchronous", "asynchronous")


@dataclass(frozen=True)
class DeclarationBasis:
    """선언된 수가 **무엇을 기준으로 한 수인가** (AI-C-18 "단위·좌표·시간 기준").

    세 칸 모두 None/빈 값이 가능하다. 여기서 중요한 것은 **객체의 유무가 선언의
    유무**라는 점이다 — 기준을 적지 않은 선언은 이 객체를 들지 않고, 그 상태는
    "기준이 없다" 가 아니라 "기준을 모른다" 다. 기본 단위를 가정해 채우면
    0.5 가 m 인지 m/s 인지 모르는 채로 물리 동작이 나간다.

    `reference_frame` 은 AI-C-02 의 프레임 태깅과 **같은 이름공간**이다. 로컬
    기준과 전역 기준을 같은 칸에 담지 않는다는 규칙도 그대로 적용된다.
    """

    #: 매개변수·결과 이름 -> 단위 기호("m", "m/s", "deg", ...). 적지 않은 이름은
    #: 단위를 모르는 것이고 무단위가 아니다.
    units: dict[str, str] = field(default_factory=dict)
    #: 공간 값의 기준 좌표계 이름. None 은 선언하지 않은 것이다(AI-C-02).
    reference_frame: str | None = None
    #: 시각 값의 기준(예: 백엔드 공통 시간 / 장치 단조시계). None 은 모른다는 뜻이고,
    #: 그때 이 값으로 노드 간 정합을 하면 정확도가 저하된 상태다(AI-C-03).
    time_basis: str | None = None


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
    # --- 2026-11-04: 나머지 AI-C-18 항목에 칸을 준다 ----------------------
    # 그 전까지 이 계약에는 단위·좌표·시간 기준 / 취소 가능 여부 / 멱등성 /
    # 동기·비동기 / 수행·관측 범위 / 선택 실행 조건을 담을 칸이 **없었다.**
    # 칸이 없으면 장치가 보내 와도 받을 자리가 없고, 그러면 "와이어가 못 싣는
    # 것"과 "우리가 못 받는 것"이 구분되지 않는다.
    #: 선택 실행 조건. `preconditions` 가 없으면 DISABLED 지만 이쪽 결손은
    #: DEGRADED 까지만이다(AI-C-05 와 같은 규칙).
    optional_preconditions: tuple[str, ...] = ()
    #: 취소 가능 여부. **세 값이다** — True/False/None(모름). None 을 False 로
    #: 접으면 상위 기능이 "이 장치는 취소를 거부한다" 로 읽고, 실제로는 아무도
    #: 선언하지 않은 것이다. AI-C-20 의 취소 수락/CANCELED 도달 구분이 이 위에
    #: 서 있으므로 접는 순간 그 구분의 전제가 사라진다.
    cancellable: bool | None = None
    #: 같은 입력으로 다시 불렀을 때 물리 효과가 한 번과 같은가(멱등). 여기도
    #: 세 값이다 — None 은 "멱등하지 않다" 가 아니라 모른다는 뜻이다. 같은
    #: command_id 재전달은 프레임워크가 막지만(AI-C-20), **다른 command_id 로
    #: 같은 입력을 다시 보내도 되는가**는 이 선언만이 답할 수 있다.
    idempotent: bool | None = None
    #: 동기·비동기 특성. 값 어휘는 `INVOCATION_MODES`. None 은 선언하지 않은 것이다.
    invocation: str | None = None
    #: 단위·좌표·시간 기준. 객체가 없으면 기준을 모르는 것이다.
    basis: DeclarationBasis | None = None
    #: 수행·관측 범위(구역·반경·대상 등 자유 문자열 태그). **None 과 빈 묶음이
    #: 다르다** — None 은 선언하지 않은 것이고 `()` 는 "범위 제약 없음"을 선언한
    #: 것이다. 벤더 enum 이 아니라 태그인 이유는 AI-B-04 와 같다.
    scope_tags: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.invocation is not None and self.invocation not in INVOCATION_MODES:
            raise ValueError(
                f"invocation='{self.invocation}' 은 어휘 밖이다(허용: {INVOCATION_MODES}). "
                "모르는 값은 None 으로 둔다 — 어휘 밖 문자열을 넣으면 소비자가 "
                "그것을 세 번째 모드로 읽는다."
            )

    def undeclared_items(self) -> tuple[str, ...]:
        """이 선언이 **적지 않은** AI-C-18 항목들(`CAPABILITY_DECLARATION_ITEMS`
        토큰). 빈 묶음이면 이 계층이 담는 항목을 다 적었다는 뜻이다.

        규칙: 기본값은 **절대 선언으로 읽지 않는다.** 묶음 칸이 비어 있으면
        "조건이 없다" 가 아니라 "적지 않았다" 로 센다 — 보수적으로 틀리는 쪽은
        없는 선언을 지어내지 않는 쪽이다(AI-C-18 "모든 항목이 항상 존재한다고
        가정해서는 안 된다").
        """
        missing: list[str] = []
        if not self.kind:
            missing.append(ITEM_MEANING)
        if self.input_schema is None:
            missing.append(ITEM_INPUT_SCHEMA)
        if self.output_schema is None:
            missing.append(ITEM_OUTPUT_SCHEMA)
        if self.basis is None:
            missing.append(ITEM_BASIS)
        if not self.preconditions and not self.optional_preconditions:
            missing.append(ITEM_EXECUTION_CONDITIONS)
        if self.cancellable is None:
            missing.append(ITEM_CANCELLABLE)
        if self.idempotent is None:
            missing.append(ITEM_IDEMPOTENT)
        if self.invocation is None:
            missing.append(ITEM_INVOCATION)
        if self.scope_tags is None:
            missing.append(ITEM_SCOPE)
        return tuple(missing)

    def is_fully_declared(self) -> bool:
        """이 계층이 담는 AI-C-18 항목을 하나도 빼지 않고 적었는가."""
        return not self.undeclared_items()

    def requirement(self) -> CapabilityRequirement:
        """선언한 필수·선택 실행 조건을 기존 AI-C-05 판정으로 넘긴다.

        새 판정 로직을 만들지 않는 것이 요점이다 — 선택 조건의 결손이
        DEGRADED 까지만이고 DISABLED 가 되지 않는다는 규칙은
        `CapabilityRequirement.evaluate` 가 이미 소유한다. 여기서 한 번 더
        판정하면 같은 사실에 주인이 둘이 된다.
        """
        return CapabilityRequirement(
            required=self.preconditions, optional=self.optional_preconditions
        )


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
