"""레코드가 **확정으로 승격되는 한 자리**, 그리고 모자랄 때 무엇을 더 **요청**하는가.

implements: AI-S-03, AI-S-05, AI-E-04, AI-C-05, AI-C-19
관련: AI-S-06 (레코드 구성은 **상류**가 한다), AI-S-07 (무엇이 필요한가는 계약이 소유),
      AI-R-02 (관측·분석 수준), AI-C-02 (로컬·전역을 같은 칸에 담지 않는다),
      AI-C-03 (파생 결과는 원본 관측 참조를 들고 있다), AI-O-06 (조회와 제어는 다른 계약)
tests: tests/test_perception_loop.py, tests/test_fms_promotion.py

## 이 모듈이 **판정하지 않는** 것 — 먼저 적는다

`tools/fms_console/` 가 "판정을 하지 않는다 — 다른 모듈이 이미 내는 값을 모아 한
스냅샷으로 낸다" 인 것과 같은 규약이다. 같은 사실에 주인이 둘이면 두 화면이 서로 다른
답을 말한다(`tools/status_ui/serve.py::StatusService.fleet()` 의 주석이 그 이유를 적는다).
그래서 이 루프는 **순서만 잡고**, 아래 각 줄의 판정은 전부 남의 것이다.

```
무엇을 묻는가                                   주인
-------------------------------------------- -----------------------------------------
이 근거들이 같은 물리 객체의 것인가             상류 레코드 구성
                                             (tools/fms_console/twin.py ·
                                              edge/object_evidence_fusion.py)
레코드의 기하·클래스·lifecycle 은 무엇인가       perception/object_record.py
원본 관측을 **몇 번** 본 것인가                 perception/uncertainty.py
                                             (`(source_group, frame_ref)` 가 단위다)
이 목적에 **무엇이 필요한가**                   perception/purpose_requirements.py
                                             (+ contracts/evidence_contract.py 가 품질·
                                              해상도·개정을 얹는다)
계약 대비 지금 **무엇이 모자란가**              decision/evidence_gap.py
**멈춰도 되는가**(승격)                         decision/sufficiency.py 의 StopRule
더 **요청할 것인가**, 어느 순서로               perception/info_selection.py
그 요청에 **누가 답할 수 있는가**               decision/info_request.py
보조 기능을 **실제로 돌리는** 일                perception/auxiliary.py
요청할 관측·분석 **수준**                       risk/adjustment.py
provider 가 쓸 만한가·고를 수 있는가            selection/selector.py
장치의 최종 가용성                              백엔드 (원칙 #15 — 여기서 묻지 않는다)
물리 명령 발급·액추에이터 제어                  백엔드·하드웨어 (AI-C-19)
```

루프가 더하는 것은 하나다 — **순서와 축소 사유**. 어느 단계가 없으면 거기서 멈추지
않고 사유를 적고 지나간다(AI-C-05).

## 왜 `runtime/` 인가

조립 지점이기 때문이다. `runtime/application.py`(capability 해소) ·
`runtime/refresh.py`(언제 반영하는가) · `runtime/reconfiguration.py` 가 같은 성격으로
여기 있다. `perception/` 에 두면 인지 계층이 `decision/` · `risk/` · `selection/` 를
import 하게 되어 층이 거꾸로 선다 — 그 셋이 인지를 소비하는 쪽이다.

## 반영은 **요청으로만** 일어난다

이 모듈에는 타이머도 루프문도 없다. `run()` 은 호출될 때 한 번 돈다. 주기의 주인은
`runtime/refresh.py` 이고(요청의 출처는 운영자 조회·임무 부여·서브태스크 요구·조인
넷뿐이다), `as_refresh_work()` 가 그 `RefreshLedger.request(work=...)` 자리에 그대로
들어가는 모양을 낸다. 상시 갱신하면 아무도 보지 않는 구역의 추론·전송까지 계속
돈다(AI-C-13, AI-O-01).

## 선택 단계가 없는 것은 **정상 구성**이다

`REQUIREMENT.required` 가 비어 있는 것은 실수가 아니다. 이 루프는 어느 단계가 없어도
DISABLED 가 되지 않는다 — 평가자가 없으면 레코드 자신의 lifecycle 만 남고, 계약이
선언되지 않았으면 승격 질문 자체가 성립하지 않으며, 보조 실행기가 없으면 보조를 돌리지
않는다. 그 전부가 사유와 함께 `degraded_stage_reasons` 에 남는다. 추적기가 없으면
프레임별 결과만 남는다는 AI-S-01 의 축소 경로도 같은 칸에 적는다 — 추적 자체는 상류가
하므로 여기서는 받은 값을 들고 다닐 뿐이다.

## 두 "충분도" 는 다른 질문이다 — 섞지 않는다

* **보조를 그만 돌려도 되는가**(AI-E-04) — 모인 원본 관측 단위가 요구 수를 채웠는가.
  단위를 세는 것도 요구 수를 드는 것도 `perception/uncertainty.py` 하나이고, 루프는
  방금 돌린 보조의 결과를 `(capability_kind, frame_ref)` origin 으로 더해 다시 묻는다.
* **확정으로 승격해도 되는가**(AI-S-03/S-07) — 이 목적이 요구한 **종류별** 근거가
  모였는가. `decision/evidence_gap.py` 가 대조하고 `decision/sufficiency.py` 의
  StopRule 이 멈출지를 정한다. `UncertaintyAssessment.confirmed` 는 승격에 쓰지
  않는다 — 같은 질문에 주인이 둘이 되지 않게 하는 선이고, 그 칸이 아직 남아 있는
  것은 `internal/docs-dev/ai/requirement-traceability.md` 가 적는 미해소 결함이다.
* **무엇을 먼저 요청하는가**(AI-S-05) — `perception/info_selection.py` 가 기대 이득
  순으로 세우고 요구 수준을 넘으면 비운다. 그 눈금에는 **계약 축**(필수 중 몇이
  met 인가)을 넣는다. 원본 관측 단위 수를 넣으면 "두 번 봤다" 가 "거리 측정이 아직
  없다" 를 덮는다.

둘을 한 칸에 담으면 "많이 봤다" 가 "맞다" 로 읽힌다. 실측으로 그 구분이 필요했던
사례가 `decision/sufficiency.py` 의 docstring 에 있다(한 모델이 0.94 로 틀렸고 임계를
올려도 못 고쳤다).

## 요청은 명령이 아니다 (AI-C-19)

물리 행동이 필요한 결손은 **요청으로만** 나간다 — 대상 객체 · 필요한 정보 · 관측 조건 ·
사유 넷을 싣고, `command_id` 를 싣지 않는다. 명령 발급은 백엔드이고 그 의미 계약은
AI-C-20 이다. 이 모듈은 `execution/` 의 어떤 것도 import 하지 않는다.

## 좌표와 프레임 (AI-C-02, AI-C-03)

공간 값은 상류가 준 기준 좌표계를 그대로 들고 다니고, 이 모듈은 전역 값을 만들지
않는다 — datum 이 없는 현장은 정상 배치다. 모든 산출은 `frame_ref` 를 들고 있어 원본
관측으로 되짚을 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Mapping, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.contracts.evidence_contract import MissionContract
from mission_runtime.contracts.profile import ResourceBudget
from mission_runtime.decision.evidence_gap import (
    DEFAULT_KIND_PROVIDERS,
    evaluate as evaluate_gap,
    gap as evidence_gap,
)
from mission_runtime.decision.info_request import DecisionSupportRequester, EvidenceNeed
from mission_runtime.decision.sufficiency import StopDecision, StopRule, SufficiencyRule
from mission_runtime.perception.auxiliary import (
    AuxiliaryExecutionOrchestrator,
    AuxiliaryRunRecord,
)
from mission_runtime.perception.info_selection import AdditionalInfoSelector
from mission_runtime.perception.object_record import Lifecycle, ObjectRecord
from mission_runtime.perception.uncertainty import (
    EvidenceLevel,
    EvidenceOrigin,
    UncertaintyAssessment,
    UncertaintyEvaluator,
)
from mission_runtime.risk.adjustment import ObservationLevelAdjuster

# --- 단계 이름 --------------------------------------------------------------
#: 원본 관측 단위를 세는 단계(`perception/uncertainty.py`).
STAGE_ORIGIN_AUDIT = "origin_unit_audit"
#: 목적 계약 대비 종류별 충족을 묻고 승격을 정하는 단계(`decision/`).
STAGE_PURPOSE_SUFFICIENCY = "purpose_sufficiency"
#: 부족분을 어느 순서로 요청할지 정하는 단계(`perception/info_selection.py`).
STAGE_SHORTFALL_ORDERING = "shortfall_ordering"
#: 그 요청에 누가 답할 수 있는지 고르는 단계(`decision/info_request.py`).
STAGE_REQUEST_PLANNING = "request_planning"
#: 보조 기능을 실제로 돌리는 단계(`perception/auxiliary.py`).
STAGE_AUXILIARY_EXECUTION = "auxiliary_execution"
#: 요청할 관측·분석 수준을 올리고 내리는 단계(`risk/adjustment.py`).
STAGE_OBSERVATION_LEVEL = "observation_level"
#: 프레임 간 정체성을 상류에서 받아 레코드에 싣는 단계(`perception/tracking.py` 계열).
STAGE_TRACK_IDENTITY = "track_identity"

#: **required 가 비어 있다**. 위 docstring 의 이유로 이 루프는 DISABLED 가 되지 않는다.
REQUIREMENT = CapabilityRequirement(
    required=(),
    optional=(
        STAGE_ORIGIN_AUDIT, STAGE_PURPOSE_SUFFICIENCY, STAGE_SHORTFALL_ORDERING,
        STAGE_REQUEST_PLANNING, STAGE_AUXILIARY_EXECUTION, STAGE_OBSERVATION_LEVEL,
        STAGE_TRACK_IDENTITY,
    ),
)

# --- 축소 사유 (어휘는 데이터 사전이 소유한다) -------------------------------
DEGRADE_NO_EVALUATOR = "evaluator_absent_record_lifecycle_only"
DEGRADE_NO_CONTRACT = "contract_not_declared_record_lifecycle_only"
DEGRADE_NO_SELECTOR = "info_selector_absent_shortfall_not_routed"
DEGRADE_NO_PLANNER = "request_planner_absent_no_capability_named"
DEGRADE_NO_AUXILIARY = "auxiliary_absent_no_optional_run"
DEGRADE_NO_LEVELS = "observation_levels_not_declared"
DEGRADE_NO_TRACKER = "tracker_absent_frame_results_only"

# --- 요청 사유 --------------------------------------------------------------
REQUEST_NO_PROVIDER_HERE = "needed_information_has_no_usable_provider_here"
REQUEST_PHYSICAL_ACTION = "needed_information_requires_a_physical_action"
REQUEST_AWAITS_EXECUTION = "needed_information_awaits_execution_elsewhere"

PROMOTION_CONFIRMED = "confirmed"
PROMOTION_UNCONFIRMED = "unconfirmed"


def _check_vocabulary() -> None:
    """어휘가 사전과 어긋나면 **import 시점에** 깨뜨린다.

    사유 토큰을 모듈과 사전 두 곳에 적는 순간 한쪽만 고쳐질 수 있고, 그러면 화면이
    모르는 토큰을 받아 조용히 빈칸으로 그린다(AI-C-01).
    """
    for token in (DEGRADE_NO_EVALUATOR, DEGRADE_NO_CONTRACT, DEGRADE_NO_SELECTOR,
                  DEGRADE_NO_PLANNER, DEGRADE_NO_AUXILIARY, DEGRADE_NO_LEVELS,
                  DEGRADE_NO_TRACKER):
        if token not in dd.PERCEPTION_LOOP_DEGRADATIONS:
            raise ValueError(f"축소 사유 {token!r} 가 데이터 사전 어휘에 없다")
    for token in (REQUEST_NO_PROVIDER_HERE, REQUEST_PHYSICAL_ACTION,
                  REQUEST_AWAITS_EXECUTION):
        if token not in dd.INFORMATION_REQUEST_REASONS:
            raise ValueError(f"요청 사유 {token!r} 가 데이터 사전 어휘에 없다")
    for token in (PROMOTION_CONFIRMED, PROMOTION_UNCONFIRMED):
        if token not in dd.PROMOTION_STATES:
            raise ValueError(f"승격 상태 {token!r} 가 데이터 사전 어휘에 없다")


_check_vocabulary()


@dataclass(frozen=True)
class RecordInput:
    """상류 레코드 구성이 낸 것 하나. **픽셀은 없다**(AI-C-08).

    `origins` 는 **접히지 않은 채** 들어온다 — 같은 `(source_group, frame_ref)` 가 두
    번 들어 있어도 그것을 하나로 접는 규칙은 `perception/uncertainty.py` 가 소유하고,
    여기서 미리 접으면 접었다는 사실(`duplicate_count`)이 사라져 소비자가 중복을
    지지로 센다.

    `coordinate_frame` 은 상류가 준 기준 좌표계를 그대로 들고 다닌다. 전역 값은 이
    칸에도 다른 칸에도 만들어 넣지 않는다(AI-C-02).
    """

    record: ObjectRecord
    origins: tuple[tuple[str, str], ...]
    frame_ref: str
    coordinate_frame: str
    #: 프레임 간 추적기가 부여한 식별자. `None` 은 추적기가 없거나 이 레코드를 집지
    #: 않은 것이고, 둘 다 오류가 아니다(AI-S-01).
    track_identity: int | None = None
    #: 위험 분석이 이미 낸 값. 루프가 위험도를 계산하지 않는다(AI-R-02 가 주인).
    risk_level: float = 0.0


@dataclass(frozen=True)
class InformationRequest:
    """물리 행동이나 다른 실행 위치가 필요해 **요청으로만** 남긴 것 하나.

    넷을 싣는다 — 대상 객체 · 필요한 정보 · 관측 조건 · 사유. 그리고 `frame_ref` 로
    원본 관측을 되짚을 수 있다(AI-C-03). `command_id` 는 **없다**: 명령 발급은
    백엔드이고 전달 성공이 수락도 완료도 아니다(AI-C-19, AI-C-20).
    """

    object_id: str
    needed_information: tuple[str, ...]
    observation_conditions: Mapping[str, str]
    information_request_reason: str
    frame_ref: str

    def as_dict(self) -> dict:
        return {
            dd.OBJECT_ID: self.object_id,
            dd.NEEDED_INFORMATION: list(self.needed_information),
            dd.OBSERVATION_CONDITIONS: dict(self.observation_conditions),
            dd.INFORMATION_REQUEST_REASON: self.information_request_reason,
            dd.FRAME_REF: self.frame_ref,
        }


@dataclass(frozen=True)
class RecordOutcome:
    """레코드 하나에 대한 이번 회차의 결과.

    `lifecycle_state` 는 레코드 자신의 것이고 `promotion_state` 는 이 목적에 대해
    승격했는가다. 두 칸을 합치면 "객체로 지속한다" 와 "이 임무가 요구한 근거가
    모였다" 가 구분되지 않는다.
    """

    zone_local_track_id: str
    lifecycle_state: str
    promotion_state: str
    coordinate_frame: str
    confidence: float
    frame_ref: str
    track_identity: int | None = None
    evidence_assessment: UncertaintyAssessment | None = None
    #: 승격 판정을 낸 StopRule 의 기록. `None` 은 계약이 없어 묻지 못한 것이다.
    stop_decision: StopDecision | None = None
    #: 계약 대비 아직 모자란 근거 종류(필수가 앞). 비어 있으면 모자란 것이 없다.
    unmet_evidence_kinds: tuple[str, ...] = ()
    #: 이번에 실제로 돌린 보조 기능의 capability kind.
    auxiliary_kinds_run: tuple[str, ...] = ()
    requested_observation_level: str | None = None
    information_requests: tuple[InformationRequest, ...] = ()

    @property
    def promoted(self) -> bool:
        return self.promotion_state == PROMOTION_CONFIRMED

    def as_dict(self) -> dict:
        return {
            dd.ZONE_LOCAL_TRACK_ID: self.zone_local_track_id,
            dd.LIFECYCLE_STATE: self.lifecycle_state,
            dd.PROMOTION_STATE: self.promotion_state,
            dd.COORDINATE_FRAME: self.coordinate_frame,
            dd.CONFIDENCE: self.confidence,
            dd.FRAME_REF: self.frame_ref,
            dd.TRACK_IDENTITY: self.track_identity,
            dd.EVIDENCE_ASSESSMENT: (None if self.evidence_assessment is None
                                     else self.evidence_assessment.as_dict()),
            dd.UNMET_EVIDENCE_KINDS: list(self.unmet_evidence_kinds),
            dd.REQUESTED_OBSERVATION_LEVEL: self.requested_observation_level,
            dd.INFORMATION_REQUESTS: [r.as_dict() for r in self.information_requests],
        }


@dataclass(frozen=True)
class LoopResult:
    """한 번의 반영 결과. **조회 전용이다** — 이 경로로 실행 상태를 바꾸지 않는다(AI-O-06)."""

    frame_ref: str
    capability_state: CapabilityState
    degraded_stage_reasons: Mapping[str, str]
    object_records: tuple[RecordOutcome, ...] = ()

    @property
    def information_requests(self) -> tuple[InformationRequest, ...]:
        return tuple(req for outcome in self.object_records
                     for req in outcome.information_requests)

    @property
    def promoted_ids(self) -> tuple[str, ...]:
        return tuple(o.zone_local_track_id for o in self.object_records if o.promoted)

    def as_dict(self) -> dict:
        return {
            dd.FRAME_REF: self.frame_ref,
            dd.CAPABILITY_STATE: self.capability_state.value,
            dd.DEGRADED_STAGE_REASONS: dict(self.degraded_stage_reasons),
            dd.OBJECT_RECORDS: [o.as_dict() for o in self.object_records],
            dd.INFORMATION_REQUESTS: [r.as_dict() for r in self.information_requests],
        }


@dataclass
class PerceptionLoop:
    """순서를 잡는 쪽. 어느 칸도 스스로 판정하지 않는다.

    생성자 인자가 전부 선택인 이유: 배치마다 있는 단계가 다르고, 없는 단계는 사유와
    함께 축소된다(AI-C-05). 어느 인자도 모델·런타임·프로토콜을 가리키지 않는다 —
    provider 는 레지스트리 뒤에 있고 이 모듈은 그 이름을 모른다(AI-C-04).
    """

    #: 원본 관측 단위를 세고 요구 수의 주인인 쪽. `None` 이면 세지 않는다.
    evaluator: UncertaintyEvaluator | None = None
    #: 이 목적이 요구하는 근거. `None` 이면 승격 질문이 성립하지 않는다(AI-S-07).
    contract: MissionContract | None = None
    #: 멈출지(=승격할지)를 정하는 규칙. 교체 가능해야 비교가 성립한다(AI-C-13).
    stop_rule: StopRule | None = None
    #: 부족분을 어느 순서로 요청할지 정하는 쪽. 레지스트리가 필요하다.
    info_selector: AdditionalInfoSelector | None = None
    #: 그 요청에 누가 답할 수 있는지 고르는 쪽. 레지스트리가 필요하다.
    request_planner: DecisionSupportRequester | None = None
    #: 보조 기능을 실제로 돌리는 쪽.
    auxiliary: AuxiliaryExecutionOrchestrator | None = None
    #: 요청할 관측·분석 수준을 올리고 내리는 쪽.
    level_adjuster: ObservationLevelAdjuster | None = None
    node_tags: set[str] = field(default_factory=set)
    budget: ResourceBudget | None = None
    #: 근거 종류 → 그것을 만들 수 있는 capability kind. **데이터다** — 배치가 덮어쓴다.
    kind_providers: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_KIND_PROVIDERS))
    #: capability kind → 기대 이득. 선언되지 않은 kind 는 0.0 이고, 그때 순서는
    #: `decision/evidence_gap.gap()` 이 낸 순서(필수가 앞)를 그대로 따른다.
    expected_gain_by_kind: Mapping[str, float] = field(default_factory=dict)
    #: **물리 행동이 필요한** capability kind 들. 선언이고 분기문이 아니다 — 카메라를
    #: 돌리거나 이동형 센서를 투입해야 얻는 것들이 여기 적힌다(AI-S-05). 이 집합의
    #: kind 는 루프가 돌리지 않고 요청으로만 낸다(AI-C-19).
    physical_action_kinds: frozenset[str] = frozenset()
    #: 수준을 올릴 기준. 데이터이고 이 값으로 위험도를 만들지 않는다.
    risk_threshold: float = 0.7

    def __post_init__(self) -> None:
        if self.budget is None:
            # 예산을 선언하지 않은 배치도 정상이다. "모른다" 를 0 으로 적으면 모든
            # provider 가 자원 때문에 탈락해 축소가 아니라 **전면 불가**가 되므로,
            # 선언이 없을 때는 자원으로 거르지 않는 값을 쓴다 — 자원 판정의 주인은
            # `selection/selector.py` 이고 이 값은 그 쪽에 넘기는 입력일 뿐이다.
            self.budget = ResourceBudget(compute_units=float("inf"),
                                         memory_mb=float("inf"))

    # -- 축소 상태 --------------------------------------------------------

    def _present_stages(self, *, track_identity_seen: bool) -> set[str]:
        present: set[str] = set()
        if self.evaluator is not None:
            present.add(STAGE_ORIGIN_AUDIT)
        if self.contract is not None:
            present.add(STAGE_PURPOSE_SUFFICIENCY)
        if self.info_selector is not None:
            present.add(STAGE_SHORTFALL_ORDERING)
        if self.request_planner is not None:
            present.add(STAGE_REQUEST_PLANNING)
        if self.auxiliary is not None:
            present.add(STAGE_AUXILIARY_EXECUTION)
        if self.level_adjuster is not None:
            present.add(STAGE_OBSERVATION_LEVEL)
        if track_identity_seen:
            present.add(STAGE_TRACK_IDENTITY)
        return present

    def degradation(self, *, track_identity_seen: bool = False
                    ) -> tuple[CapabilityState, dict[str, str]]:
        """지금 이 조립이 어느 상태이고 **무엇이 없어서** 그런가.

        레코드가 하나도 없는 회차에도 물을 수 있어야 한다 — 축소는 레코드의 성질이
        아니라 조립의 성질이고, "볼 것이 없었다" 를 ACTIVE 로 적으면 없는 단계가
        숨는다. 판정 자체는 `contracts/capability.py` 가 소유한다.
        """
        present = self._present_stages(track_identity_seen=track_identity_seen)
        return REQUIREMENT.evaluate(present), self._reasons(present)

    @staticmethod
    def _reasons(present: set[str]) -> dict[str, str]:
        absent = {
            STAGE_ORIGIN_AUDIT: DEGRADE_NO_EVALUATOR,
            STAGE_PURPOSE_SUFFICIENCY: DEGRADE_NO_CONTRACT,
            STAGE_SHORTFALL_ORDERING: DEGRADE_NO_SELECTOR,
            STAGE_REQUEST_PLANNING: DEGRADE_NO_PLANNER,
            STAGE_AUXILIARY_EXECUTION: DEGRADE_NO_AUXILIARY,
            STAGE_OBSERVATION_LEVEL: DEGRADE_NO_LEVELS,
            STAGE_TRACK_IDENTITY: DEGRADE_NO_TRACKER,
        }
        return {stage: reason for stage, reason in absent.items() if stage not in present}

    # -- 한 레코드 --------------------------------------------------------

    def assess(self, item: RecordInput, *,
               available_kinds: frozenset[str] | None = None) -> RecordOutcome:
        """레코드 하나를 사슬에 통과시킨다. **예외를 내지 않는 것이 규약이다** —
        없는 단계는 축소이고, 축소는 결과이지 실패가 아니다(AI-C-05).

        `available_kinds` 는 지금 provider 가 있는 capability kind 집합이고, `None` 은
        "무엇이 가능한지 모른다" 로 `decision/evidence_gap` 이 읽는다(모른다는 이유로
        미리 포기하지 않는다, AI-S-05).
        """
        record = item.record

        # 1) 원본 관측 단위 — 세는 쪽은 하나다(AI-S-03).
        assessment: UncertaintyAssessment | None = None
        if self.evaluator is not None:
            assessment = self.evaluator.evaluate(
                record.confidence,
                evidence_origins=[EvidenceOrigin.of(o) for o in item.origins])

        # 2) 승격 — 계약이 있으면 StopRule 이, 없으면 레코드 자신의 lifecycle 이 정한다.
        #    루프가 두 답을 섞어 새 판정을 만들지 않는다.
        decision: StopDecision | None = None
        unmet: tuple[str, ...] = ()
        needs: tuple[EvidenceNeed, ...] = ()
        met_required = 0
        total_required = 0
        if self.contract is not None:
            verdict = evaluate_gap(self.contract, record, available_kinds,
                                   dict(self.kind_providers))
            rule = self.stop_rule or SufficiencyRule()
            decision = rule.decide(self.contract, record, verdict, 0.0)
            unmet = verdict.unmet_kinds
            needs = evidence_gap(self.contract, record, available_kinds,
                                 dict(self.kind_providers))
            # 요청 순서를 정하는 쪽(`info_selection`)이 쓰는 눈금은 **계약 축**이다 —
            # 그 모듈의 정지 조건이 "요구 수준을 넘으면 그만" 이므로, 거기에 원본
            # 관측 단위 수를 넣으면 "두 번 봤다" 가 "거리 측정이 아직 없다" 를 덮는다.
            # 둘은 다른 질문이고(위 docstring), 여기서 세는 것은 판정이 아니라 주인이
            # 이미 낸 판정 항목을 읽는 것이다.
            required_items = tuple(i for i in verdict.items if i.necessity == "required")
            total_required = len(required_items)
            met_required = sum(1 for i in required_items if i.state == "met")
            promoted = decision is not None and decision.confirmed
        else:
            promoted = record.lifecycle is Lifecycle.CONFIRMED

        promotion = PROMOTION_CONFIRMED if promoted else PROMOTION_UNCONFIRMED

        outcome = RecordOutcome(
            zone_local_track_id=record.object_id,
            lifecycle_state=record.lifecycle.value,
            promotion_state=promotion,
            coordinate_frame=item.coordinate_frame,
            confidence=record.confidence,
            frame_ref=item.frame_ref,
            track_identity=item.track_identity,
            evidence_assessment=assessment,
            stop_decision=decision,
            unmet_evidence_kinds=unmet,
        )
        if promoted:
            # 근거가 모였으면 **더 요청하지 않는다**(AI-E-04, AI-S-05).
            return outcome

        return self._close_shortfall(item, outcome, needs, assessment,
                                     met_required, total_required)

    # -- 부족분 처리 ------------------------------------------------------

    def _close_shortfall(self, item: RecordInput, outcome: RecordOutcome,
                         needs: tuple[EvidenceNeed, ...],
                         assessment: UncertaintyAssessment | None,
                         met_required: int, total_required: int) -> RecordOutcome:
        """승격하지 못한 레코드의 부족분을 요청·실행·요청기록으로 나눈다."""
        level = self._requested_level(item, assessment)
        conditions = {
            dd.FRAME_REF: item.frame_ref,
            dd.COORDINATE_FRAME: item.coordinate_frame,
            dd.REQUESTED_OBSERVATION_LEVEL: level or "",
        }

        if self.info_selector is None or self.request_planner is None:
            # 부족분을 어디로도 보낼 수 없다. 그 사실을 사유로 남긴다 — 조용히
            # 지나가면 "모자란데 아무 일도 일어나지 않았다" 가 설명되지 않는다.
            requests = ()
            if outcome.unmet_evidence_kinds:
                requests = (InformationRequest(
                    object_id=outcome.zone_local_track_id,
                    needed_information=outcome.unmet_evidence_kinds,
                    observation_conditions=conditions,
                    information_request_reason=REQUEST_NO_PROVIDER_HERE,
                    frame_ref=item.frame_ref),)
            return _with(outcome, requested_observation_level=level,
                         information_requests=requests)

        plan = self.request_planner.plan(list(needs), self.node_tags, self.budget)
        # 답할 수 있는 kind 만 순서 판단으로 보낸다. 없는 기능을 요청하지 않는다.
        gains = {req.capability_kind: float(self.expected_gain_by_kind.get(
            req.capability_kind, 0.0)) for req in plan.requests}
        ordered = self.info_selector.select_requests(
            gains, self.node_tags, self.budget,
            required_evidence_level=float(total_required),
            current_evidence_level=float(met_required),
        )
        ordered_kinds = tuple(req.capability_kind for req in ordered)

        runnable = tuple(k for k in ordered_kinds if k not in self.physical_action_kinds)
        physical = tuple(k for k in ordered_kinds if k in self.physical_action_kinds)

        ran = self._run_auxiliary(item, runnable)
        # 고른 것 중 **돌리지 못한** 것은 조용히 버리지 않는다. 답할 provider 가 있는데
        # 이 조립이 돌릴 수단을 갖지 않은 상태를 침묵으로 두면, 모자란 레코드에 대해
        # 아무 일도 일어나지 않은 이유가 어디에도 남지 않는다(AI-S-05, AI-C-19:
        # 실행이 남의 몫이면 **요청**이 우리 산출이다).
        # **조기 정지는 요청이 아니다.** 보조가 돌다가 "근거가 모였다" 로 멈춘 뒤
        # 남은 후보는 일부러 돌리지 않은 것이므로(AI-E-04) 요청으로 내지 않는다.
        # 요청이 되는 것은 **돌릴 수단이 애초에 없었을 때**의 후보뿐이다.
        pending = () if self._can_run_auxiliary() else runnable

        requests: list[InformationRequest] = []
        if plan.unresolved:
            requests.append(InformationRequest(
                object_id=outcome.zone_local_track_id,
                needed_information=tuple(plan.unresolved),
                observation_conditions=conditions,
                information_request_reason=REQUEST_NO_PROVIDER_HERE,
                frame_ref=item.frame_ref))
        if physical:
            requests.append(InformationRequest(
                object_id=outcome.zone_local_track_id,
                needed_information=physical,
                observation_conditions=conditions,
                information_request_reason=REQUEST_PHYSICAL_ACTION,
                frame_ref=item.frame_ref))
        if pending:
            requests.append(InformationRequest(
                object_id=outcome.zone_local_track_id,
                needed_information=pending,
                observation_conditions=conditions,
                information_request_reason=REQUEST_AWAITS_EXECUTION,
                frame_ref=item.frame_ref))

        return _with(outcome, requested_observation_level=level,
                     auxiliary_kinds_run=ran,
                     information_requests=tuple(requests))

    def _can_run_auxiliary(self) -> bool:
        """보조를 돌릴 수단이 있는가.

        평가자도 조건이다 — 멈출 조건을 말해 줄 쪽이 없으면 후보를 전부 돌리게 되고,
        그 비용이 바로 AI-E-04 가 막으려는 것이다.
        """
        return self.auxiliary is not None and self.evaluator is not None

    def _run_auxiliary(self, item: RecordInput,
                       kinds: tuple[str, ...]) -> tuple[str, ...]:
        """보조 기능을 **멈출 조건과 함께** 돌린다.

        멈출 조건의 주인은 `perception/uncertainty.py` 하나다 — 돌린 결과도 이 프레임의
        한 출처이므로 origin 쌍을 더해 다시 묻고, 그 쪽이 SUFFICIENT 라고 하면 남은
        후보를 돌리지 않는다(AI-E-04: "필요한 근거가 확보되면 추가 실행을 중단").
        평가자가 없으면 멈출 조건을 말해 줄 쪽이 없으므로 **돌리지 않는다**: 그때
        전부 돌리는 것은 AI-E-04 가 막으려는 바로 그 비용이다.
        """
        if not kinds or not self._can_run_auxiliary():
            return ()

        def enough(records: Sequence[AuxiliaryRunRecord]) -> bool:
            # 방금 돌린 보조 기능의 결과도 **이 프레임의 한 출처**다. 같은 kind 를 두
            # 번 돌린 것은 한 번 본 것이고, 접는 것도 충분한지 답하는 것도 평가자가
            # 한다 — 루프는 origin 쌍을 만들어 넘길 뿐이다(AI-E-04, AI-S-03).
            origins = [EvidenceOrigin.of(o) for o in item.origins]
            origins += [EvidenceOrigin(rec.capability_kind, item.frame_ref)
                        for rec in records]
            refreshed = self.evaluator.evaluate(
                item.record.confidence, evidence_origins=origins)
            return refreshed.evidence_level is EvidenceLevel.SUFFICIENT

        ran = self.auxiliary.run_until_sufficient(
            list(kinds),
            {dd.FRAME_REF: item.frame_ref,
             dd.ZONE_LOCAL_TRACK_ID: item.record.object_id,
             dd.OBSERVED_AT: item.record.observed_at},
            self.node_tags, self.budget, evidence_check=enough)
        return tuple(rec.capability_kind for rec in ran)

    def _requested_level(self, item: RecordInput,
                         assessment: UncertaintyAssessment | None) -> str | None:
        """요청할 관측·분석 수준. 수준 목록이 선언되지 않으면 `None` 이다."""
        if self.level_adjuster is None:
            return None
        result = self.level_adjuster.request_level(
            risk_level=item.risk_level,
            evidence_sufficiency=self._current_level(assessment),
            risk_threshold=self.risk_threshold,
            evidence_threshold=self._required_level(),
            node_tags=self.node_tags,
            budget=self.budget,
        )
        return None if result.provider is None else result.provider.capability_kind

    def _required_level(self) -> float:
        """요구되는 원본 관측 단위 수. 경계의 주인은 평가자 하나다."""
        return float(self.evaluator.min_evidence_count) if self.evaluator else 0.0

    @staticmethod
    def _current_level(assessment: UncertaintyAssessment | None) -> float:
        return 0.0 if assessment is None else float(assessment.evidence_count)

    # -- 한 회차 ----------------------------------------------------------

    def run(self, items: Iterable[RecordInput], *,
            frame_ref: str = "",
            available_kinds: frozenset[str] | None = None) -> LoopResult:
        """받은 레코드들을 한 번 통과시킨다. **타이머는 없다** — 주기의 주인은
        `runtime/refresh.py` 이고 이 함수는 요청이 올 때 한 번 돈다.
        """
        items = tuple(items)
        outcomes = tuple(self.assess(item, available_kinds=available_kinds)
                         for item in items)
        state, reasons = self.degradation(
            track_identity_seen=any(i.track_identity is not None for i in items))
        return LoopResult(
            frame_ref=frame_ref or (items[0].frame_ref if items else ""),
            capability_state=state,
            degraded_stage_reasons=reasons,
            object_records=outcomes,
        )

    def as_refresh_work(self, items: Iterable[RecordInput], *,
                        frame_ref: str = "",
                        available_kinds: frozenset[str] | None = None,
                        sink: Callable[[LoopResult], None] | None = None,
                        ) -> Callable[[], tuple[str, ...]]:
        """`RefreshLedger.request(scope, trigger, work=...)` 자리에 그대로 들어가는 모양.

        억제되면 이 콜러블은 **호출되지 않는다** — 억제의 요점이 호출을 아끼는 것이고,
        돌려 놓고 버리면 아무것도 아끼지 못한다(`runtime/refresh.py`). 반환은 이번에
        건드린 레코드 식별자들이고, 장부가 비용을 되짚는 근거로 쓴다(AI-O-01).
        """
        def work() -> tuple[str, ...]:
            result = self.run(items, frame_ref=frame_ref,
                              available_kinds=available_kinds)
            if sink is not None:
                sink(result)
            return tuple(o.zone_local_track_id for o in result.object_records)

        return work


def _with(outcome: RecordOutcome, **changes) -> RecordOutcome:
    return replace(outcome, **changes)
