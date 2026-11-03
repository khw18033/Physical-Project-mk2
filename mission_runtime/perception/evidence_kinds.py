"""추론 근거는 사진 유사도 하나가 아니다 — 흩어진 근거를 한 계약으로 모은다.

implements: AI-S-03 (불확실성·근거 충분도), AI-S-05 (부족한 근거의 추가 요청),
            AI-S-06 (이종 모델 결과의 점진적 객체 레코드)
관련: AI-E-04 (선택형 보조 기능), AI-S-04, AI-S-08, AI-C-01, AI-C-05, AI-C-19
tests: tests/test_evidence_kinds.py

## 문제

관제 콘솔의 "추론 근거" 화면은 CLIP 외형 임베딩의 사진 유사도 하나만 보여 준다. 그런데
이 저장소는 이미 여러 격의 근거를 내고 있다 — 무선 거리와 운동 상관과 마커
(`device_identity.py`), 장치가 스스로 공지한 action 어휘와 자원 태그
(`device_class_estimator.py`), GPS·깊이·점군·열린 어휘·선언 인프라·사람이 잰 실측값
(`spatial_evidence.py`), 여러 장치가 같은 객체에 올린 투영과 클래스 표
(`tools/fms_console/twin.py`), 환경 사전정보(`environment_prior.py`).

모듈마다 자기 모양으로 근거를 들고 있어서, 화면은 그중 **하나**만 그릴 수 있었다. 이
모듈은 그 모양들을 한 계약으로 옮기고, 그 위에서 "지금 결론을 낼 만큼 근거가 있는가"를
답한다. 각 모듈을 고치지 않는다 — 어댑터가 읽어서 옮긴다. 그 모듈들에는 각자 주인이
있고, 근거를 내는 규칙은 그 주인이 소유한다.

## 이 모듈이 지키는 규칙 (전부 시험으로 고정돼 있다)

1. **근거 1건은 출처를 끝까지 들고 다닌다.** 무엇이 냈는가(`producer`·`source_group`),
   무엇을 보고 냈는가(`frame_ref`), 얼마나 센가(`strength`), 언제 것인가(`observed_at`).
   그리고 근거 1건이 스스로 주장하지 못하는 두 가지 — **식별력**과 **격**(측정/선언/추정)
   — 은 종류 선언(`EvidenceKindSpec`)에서만 나온다. 근거가 자기 격을 주장할 수 있으면
   아무 근거나 사람 실측을 자칭할 수 있다.
2. **비식별 근거가 아무리 쌓여도 식별 근거 하나를 뒤집지 못한다.**
   `device_identity.py` 가 개체 식별에서 세운 규칙이고 여기서 그대로 보존한다. 점수를
   합치는 자리가 아니라 **경로**가 갈린다 — 식별 근거가 있으면 식별 경로로 정하고,
   없으면 식별 경로는 아예 열리지 않는다.
3. **독립성의 단위는 생산자가 아니라 원본 관측이다.** `(source_group, frame_ref)` 당
   대표 1건만 세고 나머지는 `dependent` 로 남는다. `twin.py` 가 `(장치, 프레임)` 으로
   쓰는 규칙과 같은 뜻이고, `spatial_evidence.py` 가 `frame_ref` 로 쓰는 규칙과 같은
   뜻이다. 같은 프레임을 탐지기와 분류기가 각각 읽은 것은 **한 번 본 것**이다(AI-S-06).
4. **고르지 못하면 1 위를 고르지 않고 무엇이 없는지 낸다.** `resolution_requests` 가
   AI-S-05 의 입구이며, 실제 실행(명령 발급·마커 부착)은 다른 파트의 몫이다(AI-C-19).
   요청과 결손은 **그 질문의 범위 안에서만** 낸다(`DEFAULT_SUBJECT_SCOPES`) — 개체
   식별을 묻는 화면에 "구역을 실측해 달라" 가 뜨면 운영자는 엉뚱한 일을 하게 된다.
5. **제공자가 없는 종류는 비활성이고 오류가 아니다.** 사전·모델이 없는 설치에서도 이
   모듈은 돌고, 그 사실은 "정상"이 아니라 `unavailable_kinds`(미측정)로 나온다. 등록은
   됐는데 이번에 아무 말도 하지 않은 종류는 `unobserved_kinds` 로 따로 나온다 — 둘을
   한 칸에 넣으면 "볼 능력이 없다" 와 "보이지 않았다" 가 같은 모양이 된다(AI-C-05).
6. **선언만으로는 확정되지 않는다.** 환경 사전정보·프로파일 선언 같은 비식별 선언
   근거만 모여도 `met` 이 되지 않는다(AI-S-08: 실제 관측과 분리해 관리하고 사전정보만으로
   확정하지 않는다). 장치가 스스로 공지한 action 어휘는 선언이지만 **식별력이 있어서**
   식별 경로로 통과한다 — 이 둘을 구분하지 않으면 공지 한 줄이 환경 사전정보와 같은
   격으로 떨어진다.
7. **왜 그렇게 판단했는지가 산출물이다.** `explanation()` 은 어느 근거가 결론을 끌었고,
   무엇이 배제됐고, 그 근거 하나를 빼면 결론이 바뀌는지(`leave_one_out()`)를 한 묶음으로
   낸다. 기여 점수만 보여 주면 식별 근거 하나가 전부를 정한 경우와 여럿이 합쳐 정한
   경우가 같아 보인다.

## 질문이 다르면 충분도 기준도 다르다

개체 식별(`device_identity.py`)은 **식별 근거**를 요구한다 — 사진이 열 장 모여도 같은
기종 두 대를 가리지 못한다. 객체 클래스(`object_record.py`)는 **독립 출처 두 개**를
요구한다(`CONFIRMING_GROUPS`). 두 기준을 한 축에 억지로 합치면 둘 중 하나가 거짓말을
하므로, 평가자 설정(`require_discriminating`)으로 갈라 둔다. 임계값은 각 주인 모듈에서
**읽어 온다** — 같은 규칙을 두 값으로 재면 두 화면이 서로 다른 답을 말한다.

## 이 모듈이 소유하지 않는 것

근거를 만드는 규칙(무엇이 식별력 있는 단서인가, 유사도를 어떻게 재는가)은 전부 각 주인
모듈의 것이다. 최종 "이 track 은 이 장치다" 라는 권위 있는 결속과 장치의 최종 가용성,
물리 명령 발급은 백엔드·하드웨어의 몫이고(AI-C-19), 좌표는 로컬에 머문다(AI-C-02).
`tools/fms_console/twin.py` 는 패키지 밖이므로 import 하지 않고 **덕 타이핑**으로 읽는다 —
공개 패키지가 도구 디렉터리를 의존하면 그 도구 없이는 패키지가 import 되지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.perception.device_identity import (
    DISCRIMINATING_CUES,
    CueKind,
    DeviceIdentityResolver,
    IdentityCue,
)
from mission_runtime.perception.object_record import CONFIRMING_GROUPS
from mission_runtime.perception.spatial_evidence import (
    REJECT_SOURCE_UNAVAILABLE,
    REJECT_UNREGISTERED_KIND,
    ROLE_DEPENDENT as SPATIAL_ROLE_DEPENDENT,
    ROLE_INDEPENDENT as SPATIAL_ROLE_INDEPENDENT,
    ROLE_OVERRIDE,
    ROLE_UNWEIGHTED_MEAN,
    TIER_DECLARED,
    TIER_ESTIMATED,
    TIER_MEASURED,
)

#: 이 계약 자체의 필수·선택 의존. **아무 근거 종류도 없어도 모듈은 성립한다** — 그래서
#: required 가 비어 있다. 근거를 하나도 못 받는 노드에서 `NO_EVIDENCE` 를 내는 것이
#: 이 모듈이 할 일이고, import 를 막는 것은 아니다(AI-C-05).
REQUIREMENT = CapabilityRequirement(
    required=(),
    optional=("perception.classify", "perception.detect", "perception.depth",
              "perception.point_cloud", "perception.open_vocabulary",
              "positioning.absolute", "reference.zone_profile",
              "reference.human_survey", "radio.ranging", "control.motion_probe",
              "perception.fiducial", "registry.device_declaration"),
)

# --- 식별 경로의 임계값은 주인 모듈에서 읽어 온다 -----------------------------
#: `device_identity.DeviceIdentityResolver` 의 선언값을 그대로 쓴다. 숫자를 베껴 적으면
#: 그쪽이 바뀐 날 두 모듈이 다른 답을 내고, 그 어긋남은 시험이 아니라 화면에서 발견된다.
_IDENTITY_RULE = DeviceIdentityResolver()
DISCRIMINATING_MIN_STRENGTH: float = _IDENTITY_RULE.discriminating_min_strength
DISCRIMINATING_MARGIN: float = _IDENTITY_RULE.discriminating_margin
#: 비식별 경로에서 요구하는 독립 지지 수. `object_record.CONFIRMING_GROUPS` 와 같은 값이다.
MIN_INDEPENDENT_SUPPORT: int = CONFIRMING_GROUPS

# --- 등록된 근거 종류 -------------------------------------------------------
# 이름은 **주인 모듈이 쓰는 이름 그대로**다. 여기서 다시 지으면 같은 근거가 두 어휘로
# 불리고, 그러면 화면이 둘을 서로 다른 근거로 그린다.

#: 출처 모듈 표시. 어댑터가 어디서 옮겨 왔는지를 선언에 남긴다.
ORIGIN_APPEARANCE_CLASSIFIER = "perception.appearance_classifier"
ORIGIN_DEVICE_IDENTITY = "perception.device_identity"
ORIGIN_DEVICE_CLASS_ESTIMATOR = "perception.device_class_estimator"
ORIGIN_SPATIAL_EVIDENCE = "perception.spatial_evidence"
ORIGIN_OBJECT_RECORD = "perception.object_record"
ORIGIN_ENVIRONMENT_PRIOR = "perception.environment_prior"
ORIGIN_TWIN_LEDGER = "tools.fms_console.twin"

# appearance_classifier.py — 참조영상별 유사도
KIND_APPEARANCE_REFERENCE_SIMILARITY = "appearance_reference_similarity"

# device_identity.py — 개체를 가리는 단서와 가리지 못하는 단서
KIND_APPEARANCE_CLASS = CueKind.APPEARANCE_CLASS.value
KIND_DECLARED_PLACEMENT = CueKind.DECLARED_PLACEMENT.value
KIND_RADIO_RANGE = CueKind.RADIO_RANGE.value
KIND_MOTION_CORRELATION = CueKind.MOTION_CORRELATION.value
KIND_FIDUCIAL_MARKER = CueKind.FIDUCIAL_MARKER.value

# device_class_estimator.py — 기종을 배제할 수 있는 단서와 지지만 하는 단서
KIND_APPEARANCE_EMBEDDING = "appearance_embedding"
KIND_ANNOUNCED_ACTIONS = "announced_action_vocabulary"
KIND_RESOURCE_TAGS = "resource_tags"
KIND_APPARENT_SIZE = "apparent_size"
KIND_MOTION = "motion"
KIND_DECLARED_ZONE = "declared_zone"

# spatial_evidence.py — 구역 공간 값의 일곱 출처
KIND_GPS = "gps"
KIND_MULTI_DEVICE_DETECTION = "multi_device_detection"
KIND_DEPTH = "depth"
KIND_POINT_CLOUD = "point_cloud"
KIND_ZERO_SHOT_DETECTION = "zero_shot_detection"
KIND_INFRASTRUCTURE_DECLARATION = "infrastructure_declaration"
KIND_HUMAN_SURVEY = "human_survey"

# object_record.py — 비동기 provider 결과의 세 모양
KIND_RECORD_REGION = "record_region"
KIND_RECORD_MASK = "record_mask"
KIND_RECORD_SEMANTIC = "record_semantic"

# environment_prior.py — 관측이 아닌 사전정보
KIND_ENVIRONMENT_PRIOR = "environment_prior"

# twin.py — 여러 장치가 한 객체에 올린 투영과 클래스 표
KIND_ZONE_REGION_PROJECTION = "zone_region_projection"
KIND_ZONE_CLASS_VOTE = "zone_class_vote"

# --- 해법 요청 어휘 (AI-S-05 의 입구; 실행은 다른 파트다) ----------------------
REQUEST_MOTION_PROBE = "run_motion_probe"
REQUEST_ATTACH_FIDUCIAL = "attach_fiducial_marker"
REQUEST_ENABLE_RADIO_RANGING = "enable_radio_ranging"
REQUEST_ANNOUNCE_ACTIONS = "request_action_announcement"
REQUEST_REGISTER_TAGS = "request_resource_tag_registration"
REQUEST_RANGE = "request_range_measurement"
REQUEST_HUMAN_SURVEY = "request_human_survey"
REQUEST_BETTER_VIEW = "request_closer_or_unoccluded_view"

# --- 판정 사유 어휘 (dd.EVIDENCE_SUFFICIENCY_REASONS) --------------------------
REASON_NO_EVIDENCE = "no_evidence_arrived"
REASON_NO_DISCRIMINATING_PROVIDER = "no_discriminating_kind_is_available"
REASON_DISCRIMINATING_SUPPORTS = "discriminating_evidence_supports"
REASON_DISCRIMINATING_TOO_CLOSE = "discriminating_evidence_too_close"
REASON_ONLY_NON_DISCRIMINATING = "only_non_discriminating_evidence"
REASON_SOLE_CANDIDATE = "sole_candidate_without_discriminating_evidence"
REASON_ONLY_DECLARED_PRIORS = "only_declared_prior_information"
REASON_INDEPENDENT_SUPPORT_SHORT = "independent_support_below_minimum"
REASON_INDEPENDENT_SUPPORT_MET = "independent_support_met"
REASON_EVERY_CLAIM_REFUTED = "every_claim_refuted_by_discriminating_evidence"
REASON_CLAIMS_TIED = "claims_tied_without_discriminating_evidence"

# --- 역할 어휘 (dd.CONTRIBUTION_ROLES 의 부분집합) ----------------------------
# 공간 융합과 **같은 상수**를 쓴다. 토큰 두 개를 베껴 적는 것이 더 짧아 보이지만, 그러면
# 그쪽이 어휘를 고친 날 두 모듈이 서로 다른 역할 이름을 내보낸다.
ROLE_INDEPENDENT = SPATIAL_ROLE_INDEPENDENT
ROLE_DEPENDENT = SPATIAL_ROLE_DEPENDENT

#: 거절 사유. 공간 융합과 **같은 토큰**을 쓴다 — 같은 뜻을 두 이름으로 적으면 사유별로
#: 화면을 가를 수 없다.
REJECT_UNREGISTERED = REJECT_UNREGISTERED_KIND
REJECT_UNAVAILABLE = REJECT_SOURCE_UNAVAILABLE
#: 등록된 종류지만 **이 질문의 것이 아니다**. 공간 값의 근거가 개체 식별 판정에 섞이면
#: 그 순위표는 어느 질문의 답도 아니다.
REJECT_OUT_OF_SCOPE = "kind_out_of_question_scope"

# --- 질문별 종류 범위 (데이터다) ----------------------------------------------
# 레지스트리는 이 저장소가 내는 근거 **전부**를 들고 있다. 그런데 한 질문이 그 전부를
# 자기 범위로 보면 "무엇이 없어서 못 고르는가" 가 엉뚱해진다 — 개체 식별을 묻는데
# "사람이 구역을 실측해 달라" 를 요청하게 된다. 그래서 질문 이름마다 자기 범위를
# 선언해 두고, 범위 밖의 근거는 조용히 쓰이지 않고 **사유로** 남는다.
SUBJECT_DEVICE_IDENTITY = "device_identity"
SUBJECT_DEVICE_CLASS = "device_class"
SUBJECT_ZONE_QUANTITY = "zone_quantity"
SUBJECT_OBJECT_CLASS = "object_class"
SUBJECT_ENVIRONMENT_STATE = "environment_state"

#: 질문 → 그 질문이 보는 종류. 한 종류가 여러 질문에 속할 수 있다(외형은 개체 식별에도
#: 기종 추정에도 쓰이고, 어느 쪽에서도 가리지 못한다).
DEFAULT_SUBJECT_SCOPES: Mapping[str, tuple[str, ...]] = {
    SUBJECT_DEVICE_IDENTITY: (
        KIND_APPEARANCE_REFERENCE_SIMILARITY, KIND_APPEARANCE_CLASS,
        KIND_DECLARED_PLACEMENT, KIND_RADIO_RANGE, KIND_MOTION_CORRELATION,
        KIND_FIDUCIAL_MARKER),
    SUBJECT_DEVICE_CLASS: (
        KIND_APPEARANCE_REFERENCE_SIMILARITY, KIND_APPEARANCE_CLASS,
        KIND_APPEARANCE_EMBEDDING, KIND_ANNOUNCED_ACTIONS, KIND_RESOURCE_TAGS,
        KIND_APPARENT_SIZE, KIND_MOTION, KIND_DECLARED_ZONE),
    SUBJECT_ZONE_QUANTITY: (
        KIND_GPS, KIND_MULTI_DEVICE_DETECTION, KIND_DEPTH, KIND_POINT_CLOUD,
        KIND_ZERO_SHOT_DETECTION, KIND_INFRASTRUCTURE_DECLARATION,
        KIND_HUMAN_SURVEY),
    SUBJECT_OBJECT_CLASS: (
        KIND_RECORD_REGION, KIND_RECORD_MASK, KIND_RECORD_SEMANTIC,
        KIND_ZONE_REGION_PROJECTION, KIND_ZONE_CLASS_VOTE,
        KIND_ZERO_SHOT_DETECTION),
    SUBJECT_ENVIRONMENT_STATE: (
        KIND_ENVIRONMENT_PRIOR, KIND_INFRASTRUCTURE_DECLARATION,
        KIND_HUMAN_SURVEY, KIND_ZERO_SHOT_DETECTION),
}


@dataclass(frozen=True)
class EvidenceKindSpec:
    """한 근거 종류의 선언. **데이터이고 코드 분기가 아니다**(AI-C-18).

    근거 1건이 주장할 수 없는 두 가지가 여기 있다.

    * `discriminating` — 이 종류가 결론을 **가릴** 수 있는가. 참이라는 것은 "항상
      맞다" 가 아니라 "이것 하나로 후보를 좁힐 수 있다" 는 뜻이다. 외형은 아무리
      점수가 높아도 거짓이고(`device_identity.DISCRIMINATING_CUES` 에 없다), 그래서
      식별 근거를 뒤집지도 못한다.
    * `tier` — 사람 실측 / 선언 / 센서 추정(`spatial_evidence` 와 같은 어휘). 정확도와
      **다른 축**이다. 정확도가 좋은 추정이 사람 실측과 같은 격이 되지는 않는다.

    `capability_kind` 는 이 종류를 실제로 만들어 주는 capability 다. 그것이 지금
    가용 집합에 없으면 이 종류는 **미측정**이 되고 비활성은 오류가 아니다(AI-C-05).
    """

    kind: str
    tier: str
    discriminating: bool
    origin: str
    capability_kind: str = ""
    #: 이 종류가 없을 때 낼 해법 요청. 비어 있으면 요청하지 않는다.
    request: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("kind must not be empty")
        if self.tier not in dd.SPATIAL_EVIDENCE_TIERS:
            raise ValueError(f"unknown evidence tier {self.tier!r}; "
                             f"expected one of {dd.SPATIAL_EVIDENCE_TIERS}")
        if not self.origin:
            raise ValueError(f"{self.kind}: origin must name the module that produces it")


@dataclass
class EvidenceKindRegistry:
    """등록된 근거 종류. 등록되지 않은 종류의 근거는 조용히 쓰이지 않고 **사유로**
    남는다 — 종류 이름 오타가 판정을 바꾸지 않은 채 사라지는 것이 가장 찾기 어렵다."""

    _specs: dict[str, EvidenceKindSpec] = field(default_factory=dict)

    def register(self, spec: EvidenceKindSpec) -> EvidenceKindSpec:
        self._specs[spec.kind] = spec
        return spec

    def spec(self, kind: str) -> EvidenceKindSpec | None:
        return self._specs.get(kind)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def tier_of(self, kind: str) -> str | None:
        spec = self._specs.get(kind)
        return spec.tier if spec else None

    def is_discriminating(self, kind: str) -> bool:
        spec = self._specs.get(kind)
        return bool(spec and spec.discriminating)

    def discriminating_kinds(self) -> tuple[str, ...]:
        return tuple(k for k in self.kinds() if self._specs[k].discriminating)

    def of_origin(self, origin: str) -> tuple[str, ...]:
        """어느 모듈에서 온 종류들인가. 화면이 근거를 출처별로 묶을 때 쓴다."""
        return tuple(k for k in self.kinds() if self._specs[k].origin == origin)

    def capability_kinds(self) -> tuple[str, ...]:
        return tuple(sorted({s.capability_kind for s in self._specs.values()
                             if s.capability_kind}))

    def subset(self, kinds: Iterable[str]) -> "EvidenceKindRegistry":
        """그 종류들만 담은 레지스트리. 등록되지 않은 이름은 조용히 빠진다."""
        wanted = set(kinds)
        return EvidenceKindRegistry(
            {k: v for k, v in self._specs.items() if k in wanted})

    def copy(self) -> "EvidenceKindRegistry":
        return EvidenceKindRegistry(dict(self._specs))


def default_kind_registry() -> EvidenceKindRegistry:
    """지금 이 저장소가 실제로 내는 근거 종류 전부.

    새 종류는 `register()` 로 늘린다 — 이 함수를 고치지 않고도 늘어나야 새 하드웨어·새
    모델이 핵심 코드를 건드리지 않는다(절대 준수 원칙 #7).
    """
    registry = EvidenceKindRegistry()
    for spec in (
        # -- perception/appearance_classifier.py --------------------------
        EvidenceKindSpec(
            KIND_APPEARANCE_REFERENCE_SIMILARITY, TIER_ESTIMATED, False,
            ORIGIN_APPEARANCE_CLASSIFIER, capability_kind="perception.classify",
            request=REQUEST_BETTER_VIEW,
            note="참조영상 한 장과의 유사도. 사전의 자체 실측(42 회 leave-one-out)에서 "
                 "절대점수 구간이 기종 간에 겹치므로 점수 하나로는 아무것도 가르지 못한다."),
        # -- perception/device_identity.py --------------------------------
        EvidenceKindSpec(
            KIND_APPEARANCE_CLASS, TIER_ESTIMATED, False, ORIGIN_DEVICE_IDENTITY,
            capability_kind="perception.classify", request=REQUEST_BETTER_VIEW,
            note="외형은 **종류**만 말한다. 같은 기종 두 대에 같은 단서가 가므로 개체를 "
                 "가리지 못하고, 그것이 고장이 아니라 설계다."),
        EvidenceKindSpec(
            KIND_DECLARED_PLACEMENT, TIER_DECLARED, False, ORIGIN_DEVICE_IDENTITY,
            capability_kind="reference.zone_profile",
            note="프로파일에 '있을 것' 이라고 적힌 자리. 가장 약하고 단독으로는 아무것도 "
                 "확정하지 못한다."),
        EvidenceKindSpec(
            KIND_RADIO_RANGE, TIER_ESTIMATED, True, ORIGIN_DEVICE_IDENTITY,
            capability_kind="radio.ranging", request=REQUEST_ENABLE_RADIO_RANGING,
            note="개체 id 와 거친 거리. 두 대가 가까이 있으면 못 가리므로 세기가 낮게 나온다."),
        EvidenceKindSpec(
            KIND_MOTION_CORRELATION, TIER_ESTIMATED, True, ORIGIN_DEVICE_IDENTITY,
            capability_kind="control.motion_probe", request=REQUEST_MOTION_PROBE,
            note="명령과 움직임의 상관. 하드웨어 변경이 없어 1 순위 해법이다."),
        EvidenceKindSpec(
            KIND_FIDUCIAL_MARKER, TIER_ESTIMATED, True, ORIGIN_DEVICE_IDENTITY,
            capability_kind="perception.fiducial", request=REQUEST_ATTACH_FIDUCIAL,
            note="마커는 개체를 직접 말하지만 부착이 필요하고 가려지면 사라진다."),
        # -- perception/device_class_estimator.py -------------------------
        EvidenceKindSpec(
            KIND_APPEARANCE_EMBEDDING, TIER_ESTIMATED, False,
            ORIGIN_DEVICE_CLASS_ESTIMATOR, capability_kind="perception.classify",
            request=REQUEST_BETTER_VIEW,
            note="사진 한 장. 배경·조명이 닮으면 뒤집히므로 어떤 기종도 배제하지 못한다."),
        EvidenceKindSpec(
            KIND_ANNOUNCED_ACTIONS, TIER_DECLARED, True,
            ORIGIN_DEVICE_CLASS_ESTIMATOR, capability_kind="registry.device_declaration",
            request=REQUEST_ANNOUNCE_ACTIONS,
            note="장치가 조인에서 스스로 공지한 action 어휘. 선언이지만 **식별력이 있다** — "
                 "takeoff 를 공지한 것은 책상에 고정된 매니퓰레이터가 아니다. 환경 사전정보와 "
                 "같은 격으로 떨어뜨리면 그 한 줄이 사진 86 장보다 확실하다는 사실이 사라진다."),
        EvidenceKindSpec(
            KIND_RESOURCE_TAGS, TIER_DECLARED, True, ORIGIN_DEVICE_CLASS_ESTIMATOR,
            capability_kind="registry.device_declaration", request=REQUEST_REGISTER_TAGS,
            note="조인에 실린 자원 태그. 같은 역할이어도 다리와 바퀴는 여기서 갈린다."),
        EvidenceKindSpec(
            KIND_APPARENT_SIZE, TIER_ESTIMATED, True, ORIGIN_DEVICE_CLASS_ESTIMATOR,
            capability_kind="perception.depth", request=REQUEST_RANGE,
            note="거리를 알 때만 나온다. 보통 가르지는 못하고 **배제**한다."),
        EvidenceKindSpec(
            KIND_MOTION, TIER_ESTIMATED, True, ORIGIN_DEVICE_CLASS_ESTIMATOR,
            capability_kind="perception.detect", request=REQUEST_MOTION_PROBE,
            note="움직였다는 것만 말한다. 안 움직인 것은 고정됐다는 뜻이 아니다."),
        EvidenceKindSpec(
            KIND_DECLARED_ZONE, TIER_DECLARED, False, ORIGIN_DEVICE_CLASS_ESTIMATOR,
            capability_kind="reference.zone_profile",
            note="프로파일에 적힌 배치. 가장 약한 근거이고 단독으로는 아무것도 못 한다."),
        # -- perception/spatial_evidence.py -------------------------------
        EvidenceKindSpec(
            KIND_GPS, TIER_ESTIMATED, False, ORIGIN_SPATIAL_EVIDENCE,
            capability_kind="positioning.absolute",
            note="거칠고 실내에서는 아예 없다. 로컬 환산 기준 없이는 융합에 들어가지 못한다."),
        EvidenceKindSpec(
            KIND_MULTI_DEVICE_DETECTION, TIER_ESTIMATED, False, ORIGIN_SPATIAL_EVIDENCE,
            capability_kind="perception.detect",
            note="여러 대가 동시에 본 결과. 서로 다른 frame_ref 일 때만 독립이다."),
        EvidenceKindSpec(
            KIND_DEPTH, TIER_ESTIMATED, False, ORIGIN_SPATIAL_EVIDENCE,
            capability_kind="perception.depth", request=REQUEST_RANGE,
            note="촘촘하지만 먼 거리에서 급격히 나빠진다."),
        EvidenceKindSpec(
            KIND_POINT_CLOUD, TIER_ESTIMATED, False, ORIGIN_SPATIAL_EVIDENCE,
            capability_kind="perception.point_cloud",
            note="기하만 있고 의미가 없다. 같은 점군에서 뽑은 두 값은 하나의 지지다."),
        EvidenceKindSpec(
            KIND_ZERO_SHOT_DETECTION, TIER_ESTIMATED, False, ORIGIN_SPATIAL_EVIDENCE,
            capability_kind="perception.open_vocabulary",
            note="고정 클래스 없는 의미. 미터 자리로 오려면 보정이 필요하다(AI-E-02)."),
        EvidenceKindSpec(
            KIND_INFRASTRUCTURE_DECLARATION, TIER_DECLARED, False, ORIGIN_SPATIAL_EVIDENCE,
            capability_kind="reference.zone_profile",
            note="프로파일에 적힌 고정 설치물. 실측이 아니라 선언이다."),
        EvidenceKindSpec(
            KIND_HUMAN_SURVEY, TIER_MEASURED, True, ORIGIN_SPATIAL_EVIDENCE,
            capability_kind="reference.human_survey", request=REQUEST_HUMAN_SURVEY,
            note="사람이 재어 넣은 값. 센서가 아무리 쌓여도 이것을 뒤집지 못한다 — "
                 "`spatial_evidence` 의 overrides 와 같은 뜻이고, 그래서 식별력으로 옮겼다."),
        # -- perception/object_record.py ----------------------------------
        EvidenceKindSpec(
            KIND_RECORD_REGION, TIER_ESTIMATED, False, ORIGIN_OBJECT_RECORD,
            capability_kind="perception.detect",
            note="한 provider 가 낸 영상 좌표 박스. 지속 객체의 기하를 받친다."),
        EvidenceKindSpec(
            KIND_RECORD_MASK, TIER_ESTIMATED, False, ORIGIN_OBJECT_RECORD,
            capability_kind="perception.segment",
            note="분할 결과. 박스와 공간적으로 맞을 때만 기하로 승격된다."),
        EvidenceKindSpec(
            KIND_RECORD_SEMANTIC, TIER_ESTIMATED, False, ORIGIN_OBJECT_RECORD,
            capability_kind="perception.classify",
            note="의미 근거. 출처 묶음별 '현재 입장' 으로 누적되고 사라짐은 표가 아니다."),
        # -- perception/environment_prior.py ------------------------------
        EvidenceKindSpec(
            KIND_ENVIRONMENT_PRIOR, TIER_DECLARED, False, ORIGIN_ENVIRONMENT_PRIOR,
            capability_kind="reference.zone_profile",
            note="관측이 아닌 사전정보. 실제 관측과 충돌하는 사전정보만으로 확정해서는 "
                 "안 된다(AI-S-08) — 비식별 선언이라는 두 칸이 그 금지의 코드상 표현이다."),
        # -- tools/fms_console/twin.py ------------------------------------
        EvidenceKindSpec(
            KIND_ZONE_REGION_PROJECTION, TIER_ESTIMATED, False, ORIGIN_TWIN_LEDGER,
            capability_kind="perception.detect",
            note="한 장치의 영상 좌표를 구역 로컬 평면으로 옮긴 값. 거리가 없으면 "
                 "위치를 혼자 정하지 못하므로 이 근거가 되지 않는다."),
        EvidenceKindSpec(
            KIND_ZONE_CLASS_VOTE, TIER_ESTIMATED, False, ORIGIN_TWIN_LEDGER,
            capability_kind="perception.classify",
            note="한 장치가 그 객체에 대해 말한 클래스. 확정 label 이 아니라 가설이다."),
    ):
        registry.register(spec)
    return registry


#: 모듈 기본 레지스트리. 배치별로 바꿔야 하면 `copy()` 해서 쓴다.
DEFAULT_KIND_REGISTRY = default_kind_registry()


# ---------------------------------------------------------------------------
# 근거 1건
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroundedEvidence:
    """어떤 결론을 받치는(또는 반박하는) 근거 1 건.

    provenance 모양은 `perception/object_record.py` 의 `Evidence` 와
    `perception/spatial_evidence.py` 의 `SpatialObservation` 을 그대로 따른다
    (`evidence_id` · `source_group` · `frame_ref` · `observed_at`) — 같은 뜻의 출처
    정보를 세 모양으로 들고 다니면 근거를 서로 되짚을 수 없다.

    `strength` 는 그 근거를 낸 쪽이 말한 세기(0..1)다. **격과 식별력은 여기 없다** —
    종류 선언에서만 나온다(규칙 1).
    """

    evidence_id: str
    evidence_kind: str
    #: 이 근거가 가리키는 결론. 개체 id·기종 이름·구역 값 이름 등 질문에 따라 다르다.
    claim: str
    source_group: str
    #: 원본 관측(프레임·점군·실측 회차). **독립성의 단위**다(규칙 3).
    frame_ref: str
    observed_at: float
    strength: float
    #: 이 근거를 실제로 만든 모듈·provider. 출처 추적의 네 번째 축이다.
    producer: str = ""
    #: 지지가 아니라 **반박**인가. 식별력 있는 반박만 후보를 배제할 수 있다.
    refutes: bool = False
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence_id must not be empty")
        if not self.claim:
            raise ValueError(f"{self.evidence_id}: claim must not be empty")
        if not self.frame_ref:
            # frame_ref 가 없으면 독립성을 셀 수 없고, 못 세면 중복이 지지가 된다.
            raise ValueError(f"{self.evidence_id}: frame_ref must not be empty "
                             "(독립성의 단위다)")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"{self.evidence_id}: strength must be within 0..1, "
                             f"got {self.strength}")

    @property
    def observation_unit(self) -> tuple[str, str]:
        """같은 것을 한 번 본 단위. `twin.py` 의 `(장치, 프레임)` 과 같은 뜻이다."""
        return (self.source_group, self.frame_ref)

    def as_dict(self) -> dict:
        return {
            dd.EVIDENCE_ID: self.evidence_id,
            dd.EVIDENCE_KIND: self.evidence_kind,
            dd.CLAIM: self.claim,
            dd.SOURCE_GROUP: self.source_group,
            dd.FRAME_REF: self.frame_ref,
            dd.OBSERVED_AT: self.observed_at,
            dd.EVIDENCE_STRENGTH: round(self.strength, 4),
            dd.PRODUCER: self.producer,
            dd.REFUTES: self.refutes,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class EvidenceBatch:
    """한 어댑터가 옮겨 온 결과.

    `inactive` 가 이 자료형의 존재 이유다 — 사전이 없거나 모델이 없거나 사전정보의
    유효기간이 지난 것은 **오류가 아니라 미측정**이고(AI-C-05), 그 사실이 빈 목록과
    같은 모양으로 사라지면 "볼 능력이 없다" 와 "보이지 않았다" 를 화면이 구분하지
    못한다. 종류 → 사유로 남긴다.
    """

    evidence: tuple[GroundedEvidence, ...] = ()
    inactive: Mapping[str, str] = field(default_factory=dict)

    def __add__(self, other: "EvidenceBatch") -> "EvidenceBatch":
        merged = dict(self.inactive)
        # 근거가 실제로 온 종류는 비활성이 아니다 — 나중 어댑터가 같은 종류를 냈으면
        # 앞선 '없음' 선언을 지운다.
        merged.update(other.inactive)
        for row in self.evidence + other.evidence:
            merged.pop(row.evidence_kind, None)
        return EvidenceBatch(self.evidence + other.evidence, merged)

    def as_dict(self) -> dict:
        return {dd.CONTRIBUTIONS: [row.as_dict() for row in self.evidence],
                dd.UNAVAILABLE_EVIDENCE_KINDS: dict(sorted(self.inactive.items()))}


def collect(*batches: EvidenceBatch) -> EvidenceBatch:
    """여러 어댑터의 결과를 하나로 모은다. 비어 있어도 정상이다."""
    out = EvidenceBatch()
    for batch in batches:
        out = out + batch
    return out


# ---------------------------------------------------------------------------
# 어댑터 — 기존 모듈을 **읽어서** 옮긴다. 그 모듈들에는 각자 주인이 있다.
# ---------------------------------------------------------------------------


def from_appearance_verdict(
    verdict: Any,
    *,
    frame_ref: str,
    source_group: str,
    observed_at: float,
    producer: str = ORIGIN_APPEARANCE_CLASSIFIER,
) -> EvidenceBatch:
    """`appearance_classifier.AppearanceVerdict` 를 근거로 옮긴다.

    세 가지를 구분한다.

    * `CLASSIFIED` · `AMBIGUOUS` — 순위에 오른 기종 전부가 근거가 된다. 모호해도
      근거는 남는다(판정만 안 한다) — 지우면 화면이 "왜 못 골랐는지" 를 못 그린다.
    * `UNRECOGNISED` — 어느 참조영상과도 닮지 않았다. **아무 주장도 하지 않는다**.
      근거 0 건이고, 종류는 `unobserved`(말은 할 수 있었는데 안 했다)로 남는다.
    * `NO_REFERENCE` — 사전·모델·참조영상이 없다. 그 사유가 `inactive` 에 들어가
      미측정으로 나온다(AI-C-05).

    `frame_ref` 를 호출자가 주는 이유: 분류기는 crop 하나를 받고 그 crop 이 어느
    프레임에서 왔는지 모른다. 독립성을 세는 단위가 프레임이므로(규칙 3) 그 사실을
    여기서 지어내지 않고 받는다.
    """
    state = getattr(verdict, "state", None)
    state_value = getattr(state, "value", state)
    if state_value == "NO_REFERENCE":
        return EvidenceBatch(
            inactive={KIND_APPEARANCE_REFERENCE_SIMILARITY:
                      getattr(verdict, "reason", "") or "no_reference"})
    rows: list[GroundedEvidence] = []
    for index, score in enumerate(getattr(verdict, "ranked", ()) or ()):
        if state_value == "UNRECOGNISED":
            break
        rows.append(GroundedEvidence(
            evidence_id=f"appearance:{frame_ref}:{score.class_name}",
            evidence_kind=KIND_APPEARANCE_REFERENCE_SIMILARITY,
            claim=score.class_name,
            source_group=source_group,
            frame_ref=frame_ref,
            observed_at=observed_at,
            strength=max(0.0, min(1.0, float(score.score))),
            producer=producer,
            detail={
                "label": score.label,
                "rank": index,
                dd.MODEL_VERSION: getattr(verdict, "model_version", ""),
                # 어느 사진이 점수를 만들었는지. 화면에 그대로 띄울 단위다.
                dd.FEATURE_SIMILARITIES: {m.file: round(m.similarity, 4)
                                          for m in score.driving_references},
            },
        ))
    return EvidenceBatch(tuple(rows))


def from_identity_cues(
    cues: Iterable[IdentityCue],
    *,
    frame_ref: str | None = None,
    producer: str = ORIGIN_DEVICE_IDENTITY,
) -> EvidenceBatch:
    """`device_identity.IdentityCue` 들을 근거로 옮긴다.

    원본 관측 참조는 세 자리에서 찾는다. 단서가 자기 `frame_ref` 를 들고 왔으면
    **그것이 정본**이다 — 단서를 낸 쪽만 자기가 무엇을 보고 냈는지 안다. 없으면
    호출자가 준 `frame_ref` 를 쓰고, 그것도 없으면 `(source, observed_at)` 을 하나의
    원본 관측으로 본다. 마지막 환산은 보수적이다: 같은 관측자가 같은 순간에 낸 두
    단서를 **하나로** 세므로 중복이 지지가 되지 않는다(규칙 3).
    """
    rows = []
    for cue in cues:
        ref = (getattr(cue, "frame_ref", "") or frame_ref
               or f"{cue.source or 'unknown'}@{cue.observed_at}")
        rows.append(GroundedEvidence(
            evidence_id=f"identity:{cue.kind.value}:{cue.device_id}:{ref}",
            evidence_kind=cue.kind.value,
            claim=cue.device_id,
            source_group=cue.source or cue.kind.value,
            frame_ref=ref,
            observed_at=cue.observed_at,
            strength=cue.strength,
            producer=producer,
            detail=dict(cue.detail),
        ))
    return EvidenceBatch(tuple(rows))


def from_class_cues(
    cues: Iterable[Any],
    *,
    frame_ref: str | None = None,
    producer: str = ORIGIN_DEVICE_CLASS_ESTIMATOR,
) -> EvidenceBatch:
    """`device_class_estimator.ClassCue` 들을 근거로 옮긴다.

    그 모듈의 두 칸이 여기서 두 가지로 갈린다.

    * `support` — 기종별 지지. 지지 근거 1 건씩이 된다.
    * `excludes` — 그 단서가 **배제한** 기종과 사유. `refutes=True` 인 근거가 되고,
      식별력 있는 종류의 배제만 후보를 떨어뜨린다. 지지 단서의 배제는 기록만 남는다 —
      그것이 `ClassCueSpec.decisive` 가 뜻하는 바다.

    침묵한 단서(`cue.silent`)는 아무것도 내지 않는다. 없음은 반대 근거가 아니다.
    """
    rows: list[GroundedEvidence] = []
    for cue in cues:
        if getattr(cue, "silent", False):
            continue
        ref = frame_ref or f"{cue.source or 'unknown'}@{cue.observed_at}"
        group = cue.source or cue.kind
        for class_name, support in sorted(dict(cue.support or {}).items()):
            rows.append(GroundedEvidence(
                evidence_id=f"class:{cue.kind}:{class_name}:{ref}",
                evidence_kind=cue.kind,
                claim=class_name,
                source_group=group,
                frame_ref=ref,
                observed_at=cue.observed_at,
                strength=max(0.0, min(1.0, float(support))),
                producer=producer,
                detail={"separated": getattr(cue, "separated", None),
                        "tied": list(getattr(cue, "tied", ()) or ()),
                        **dict(getattr(cue, "detail", {}) or {})},
            ))
        for class_name, why in sorted(dict(getattr(cue, "excludes", {}) or {}).items()):
            rows.append(GroundedEvidence(
                evidence_id=f"class:{cue.kind}:not:{class_name}:{ref}",
                evidence_kind=cue.kind,
                claim=class_name,
                source_group=group,
                frame_ref=ref,
                observed_at=cue.observed_at,
                strength=1.0,
                producer=producer,
                refutes=True,
                detail={dd.REJECTION_REASON: why},
            ))
    return EvidenceBatch(tuple(rows))


def from_spatial_quantity(
    state: Any,
    *,
    producer: str = ORIGIN_SPATIAL_EVIDENCE,
) -> EvidenceBatch:
    """`spatial_evidence.SpatialQuantityState` 의 기여 내역을 근거로 옮긴다.

    공간 값의 결론은 label 이 아니라 수치다. 그래서 `claim` 은 그 값의 이름
    (`quantity_id`)이고, "어느 수치인가" 는 `spatial_evidence` 의 leave-one-out 이 이미
    답한다 — 여기서 다시 답하면 두 답이 어긋난다. 이 어댑터가 답하는 것은 하나다:
    **그 값이 받쳐지고 있는가**(AI-S-03).

    `accuracy_unknown` · `dependent` · `superseded` 역할의 기여는 공간 융합에서 가중
    0 이었다. 그 사실을 세기 0 으로 옮기므로 독립 지지로 세어지지 않는다 — 그쪽이
    보류한 것을 여기서 되살리면 모르는 값이 아는 값을 이긴다(그 모듈 규칙 2).
    """
    rows: list[GroundedEvidence] = []
    for row in getattr(state, "contributions", ()) or ():
        # 공간 융합이 가중한 역할만 세기 1 로 옮긴다. 역할 이름을 여기서 다시 적지 않고
        # 그 모듈의 상수를 쓴다 — 어휘가 갈리면 보류된 근거가 되살아난다.
        counted = row.role in (ROLE_INDEPENDENT, ROLE_OVERRIDE, ROLE_UNWEIGHTED_MEAN)
        rows.append(GroundedEvidence(
            evidence_id=row.evidence_id,
            evidence_kind=row.evidence_kind,
            claim=state.quantity_id,
            source_group=row.source_group,
            frame_ref=row.frame_ref,
            observed_at=row.observed_at,
            strength=1.0 if counted else 0.0,
            producer=producer,
            detail={dd.CONTRIBUTION_ROLE: row.role,
                    dd.ACCURACY_M: row.accuracy_m,
                    dd.EVIDENCE_TIER: row.tier,
                    dd.ENTERED_BY: row.entered_by,
                    dd.ZONE_ID: getattr(state, "zone_id", ""),
                    dd.COORDINATE_FRAME: getattr(state, "frame_id", "")},
        ))
    # 관측이 없는 종류를 여기서 `inactive` 로 적지 않는다 — 그것은 "제공자가 없다" 가
    # 아니라 "이번에 말하지 않았다" 이고, 평가자가 `unobserved_kinds` 로 이미 낸다.
    # 둘을 합치면 "볼 능력이 없다" 와 "보이지 않았다" 가 같은 모양이 된다.
    return EvidenceBatch(tuple(rows))


def from_object_record_evidence(
    evidence: Iterable[Any],
    *,
    object_id: str,
    producer: str = ORIGIN_OBJECT_RECORD,
) -> EvidenceBatch:
    """`object_record.Evidence` 들을 근거로 옮긴다.

    `kind` 세 값(region/mask/semantic)을 등록된 종류 세 개로 옮기고, label 이 있으면
    그 label 이 결론이고 없으면 객체 자체의 존재(`object_id`)가 결론이다 — 박스는
    "무엇인가" 를 말하지 않고 "거기 있다" 만 말한다.
    """
    mapping = {"region": KIND_RECORD_REGION, "mask": KIND_RECORD_MASK,
               "semantic": KIND_RECORD_SEMANTIC}
    rows = []
    for row in evidence:
        kind = mapping.get(row.kind)
        if kind is None:
            continue
        rows.append(GroundedEvidence(
            evidence_id=row.evidence_id,
            evidence_kind=kind,
            claim=row.label or object_id,
            source_group=row.source_group,
            frame_ref=row.frame_ref,
            observed_at=row.observed_at,
            strength=max(0.0, min(1.0, float(row.confidence))),
            producer=producer,
            detail={dd.OBJECT_ID: object_id, dd.AVAILABLE_AT: row.available_at,
                    dd.COORDINATE_FRAME: row.frame_id},
        ))
    return EvidenceBatch(tuple(rows))


def from_prior_records(
    records: Iterable[Any],
    *,
    now: float,
    claim_of: Any = None,
    producer: str = ORIGIN_ENVIRONMENT_PRIOR,
) -> EvidenceBatch:
    """`environment_prior.PriorInfoRecord` 들을 근거로 옮긴다.

    유효기간이 지났거나 사용 불가로 표시된 사전정보는 근거가 되지 않고 `inactive` 로
    남는다 — 조용히 쓰면 오래된 정보가 판단을 오염시키고, 조용히 버리면 왜 안 쓰였는지
    알 수 없다(AI-S-08).

    `claim_of` 는 레코드 → 결론 이름 콜러블이다. 주지 않으면 `record_id` 를 결론으로
    쓴다 — 어떤 사전정보가 무엇을 주장하는지는 그 레코드의 payload 가 아는 일이고 이
    어댑터가 추측할 일이 아니다.
    """
    rows: list[GroundedEvidence] = []
    inactive: dict[str, str] = {}
    for record in records:
        if not record.is_valid_at(now):
            inactive[KIND_ENVIRONMENT_PRIOR] = (
                "prior_not_available" if not record.available else "prior_outside_validity")
            continue
        claim = claim_of(record) if claim_of is not None else record.record_id
        rows.append(GroundedEvidence(
            evidence_id=f"prior:{record.record_id}:{record.version}",
            evidence_kind=KIND_ENVIRONMENT_PRIOR,
            claim=str(claim),
            source_group=record.source,
            # 한 사전정보 레코드 판이 하나의 원본이다 — 같은 레코드에서 뽑은 두 값은
            # 서로 독립인 지지가 아니다.
            frame_ref=f"prior:{record.record_id}:{record.version}",
            observed_at=record.updated_at,
            strength=1.0,
            producer=producer,
            detail={"kind": record.kind, dd.SCHEMA_VERSION: record.version,
                    "scope": list(record.scope),
                    "conflict_count": record.conflict_count,
                    "needs_reevaluation": record.needs_reevaluation(now=now)},
        ))
    if rows:
        inactive.pop(KIND_ENVIRONMENT_PRIOR, None)
    return EvidenceBatch(tuple(rows), inactive)


def from_twin_evidence_rows(
    rows: Iterable[Any],
    *,
    producer: str = ORIGIN_TWIN_LEDGER,
) -> EvidenceBatch:
    """`tools/fms_console/twin.py` 의 `ContributedEvidence` 원장을 근거로 옮긴다.

    **덕 타이핑으로 읽는다** — 공개 패키지가 도구 디렉터리를 import 하면 그 도구가 없는
    배포에서 패키지가 import 되지 않는다.

    `source_group` 에 twin 의 `device_id` 를, `frame_ref` 에 그 장치의 프레임 참조를
    그대로 넣는다. 그러면 이 모듈의 독립성 규칙 `(source_group, frame_ref)` 가 twin 의
    `(장치, 프레임)` 규칙과 **같은 답**을 낸다 — 규칙을 복제하지 않고 같은 뜻으로
    맞춘다는 것이 이 자리의 뜻이다. 위치를 들고 있으면 투영 근거, 아니면 클래스 표다.
    """
    out = []
    for row in rows:
        position = getattr(row, "position", None)
        kind = (KIND_ZONE_REGION_PROJECTION if position is not None
                else KIND_ZONE_CLASS_VOTE)
        claim = row.label or getattr(row, "object_id", "") or row.device_id
        out.append(GroundedEvidence(
            evidence_id=row.evidence_id,
            evidence_kind=kind,
            claim=claim,
            source_group=row.device_id,
            frame_ref=row.frame_ref,
            observed_at=row.observed_at,
            strength=max(0.0, min(1.0, float(row.confidence))),
            producer=getattr(row, "provider_id", "") or producer,
            detail={dd.OBJECT_ID: getattr(row, "object_id", ""),
                    dd.CONTRIBUTION_ROLE: (ROLE_INDEPENDENT if row.independent
                                           else ROLE_DEPENDENT),
                    dd.DEPENDS_ON: getattr(row, "depends_on", None),
                    dd.COORDINATE_FRAME: getattr(row, "frame_id", "")},
        ))
    return EvidenceBatch(tuple(out))


# ---------------------------------------------------------------------------
# 근거 충분도 평가 (AI-S-03)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RejectedEvidence:
    """쓰지 못한 근거와 그 사유. 조용히 버리지 않는 이유는 규칙 5 와 같다."""

    evidence_id: str
    evidence_kind: str
    reason: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {dd.EVIDENCE_ID: self.evidence_id, dd.EVIDENCE_KIND: self.evidence_kind,
                dd.REJECTION_REASON: self.reason, "detail": self.detail}


@dataclass(frozen=True)
class EvidenceRow:
    """한 근거가 결론에 어떻게 들어갔는가. 평가 뒤에도 이 줄이 남는다."""

    evidence: GroundedEvidence
    tier: str
    discriminating: bool
    role: str
    depends_on: str | None = None

    @property
    def counted(self) -> bool:
        """독립 지지로 세어졌는가. 종속 근거와 세기 0 은 세어지지 않는다."""
        return self.role == ROLE_INDEPENDENT and self.evidence.strength > 0.0

    def as_dict(self) -> dict:
        payload = self.evidence.as_dict()
        payload.update({dd.EVIDENCE_TIER: self.tier,
                        dd.DISCRIMINATING: self.discriminating,
                        dd.CONTRIBUTION_ROLE: self.role,
                        dd.DEPENDS_ON: self.depends_on})
        return payload


@dataclass(frozen=True)
class ClaimSupport:
    """한 결론에 모인 근거의 집계. 식별 지지와 비식별 지지를 **끝까지 따로** 든다."""

    claim: str
    rows: tuple[EvidenceRow, ...]
    independent_support: int
    discriminating_support: int
    best_discriminating_strength: float
    strength: float
    #: 식별력 있는 반박이 이 결론을 떨어뜨렸으면 (종류, 사유).
    excluded_by: tuple[str, str] | None = None

    @property
    def excluded(self) -> bool:
        return self.excluded_by is not None

    @property
    def tiers(self) -> tuple[str, ...]:
        return tuple(sorted({row.tier for row in self.rows if row.counted}))

    @property
    def driving_evidence(self) -> tuple[EvidenceRow, ...]:
        """결론을 실제로 끌어온 근거. 식별 근거가 있으면 그것만이다.

        비식별 근거를 함께 '끌었다' 고 적으면 사진 열 장이 마커 하나와 같은 자리에
        나타나고, 화면을 보는 사람은 그 둘이 같은 격이라고 읽는다.
        """
        strong = tuple(row for row in self.rows
                       if row.counted and row.discriminating
                       and row.evidence.strength >= DISCRIMINATING_MIN_STRENGTH)
        if strong:
            return tuple(sorted(strong, key=lambda r: (-r.evidence.strength,
                                                       r.evidence.evidence_id)))
        return tuple(sorted((row for row in self.rows if row.counted),
                            key=lambda r: (-r.evidence.strength, r.evidence.evidence_id)))

    def as_dict(self) -> dict:
        return {
            dd.CLAIM: self.claim,
            dd.EVIDENCE_STRENGTH: round(self.strength, 4),
            dd.INDEPENDENT_SUPPORT_COUNT: self.independent_support,
            "discriminating_support_count": self.discriminating_support,
            dd.EVIDENCE_TIER: list(self.tiers),
            "excluded": self.excluded,
            "excluded_by": (None if self.excluded_by is None
                            else {dd.EVIDENCE_KIND: self.excluded_by[0],
                                  dd.REJECTION_REASON: self.excluded_by[1]}),
            "driving_evidence": [row.evidence.evidence_id
                                 for row in self.driving_evidence],
            dd.CONTRIBUTIONS: [row.as_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class LeaveOneOutRow:
    """그 단위를 빼면 판정이 무엇이 되는가.

    "이 판정은 무엇 때문인가" 에 답할 수 있는 유일한 방법이다. 기여 점수만 보여 주면
    식별 근거 하나가 전부를 정한 경우와 여럿이 합쳐 정한 경우가 같아 보인다.
    """

    removed: str
    unit: str
    sufficiency_state: str
    claim: str | None
    reason: str
    changed: bool

    def as_dict(self) -> dict:
        return {"removed": self.removed, "unit": self.unit,
                dd.SUFFICIENCY_STATE: self.sufficiency_state, dd.CLAIM: self.claim,
                dd.SUFFICIENCY_REASON: self.reason, "changed": self.changed}


def _unit_key(row: GroundedEvidence, unit: str) -> str:
    if unit == "source_group":
        return row.source_group
    if unit == "evidence_kind":
        return row.evidence_kind
    if unit == "frame_ref":
        return row.frame_ref
    raise ValueError(f"unknown leave-one-out unit {unit!r}; expected "
                     "'source_group', 'evidence_kind' or 'frame_ref'")


@dataclass(frozen=True)
class SufficiencyAssessment:
    """한 질문에 대한 근거 충분도 판정과 **그렇게 된 이유** 전부.

    `sufficiency_state` 의 값 어휘는 데이터 사전의 `SUFFICIENCY_STATES` 를 그대로
    쓴다 — `met` 은 신뢰도가 높다는 뜻이 아니라 **요구한 근거가 확보됐다**는 뜻이다
    (AI-S-03: 신뢰도와 근거 충분도는 다른 축).
    """

    claim_subject: str
    sufficiency_state: str
    claim: str | None
    reason: str
    ranked: tuple[ClaimSupport, ...] = ()
    #: 식별력 있는 근거가 다른 결론을 가리켜 떨어진 결론들.
    contradicted_claims: tuple[str, ...] = ()
    observed_kinds: tuple[str, ...] = ()
    #: 등록됐고 제공자도 있는데 이번에 아무 말도 하지 않은 종류.
    unobserved_kinds: tuple[str, ...] = ()
    #: 제공자가 없어 **미측정**인 종류 → 사유. 오류가 아니다(AI-C-05).
    unavailable_kinds: Mapping[str, str] = field(default_factory=dict)
    rejected: tuple[RejectedEvidence, ...] = ()
    #: 무엇을 더 하면 풀리는지. 실행은 다른 파트다(AI-S-05, AI-C-19).
    resolution_requests: tuple[str, ...] = ()
    #: 판정에 들어간 근거. leave-one-out 이 이걸 다시 돌린다.
    accepted: tuple[GroundedEvidence, ...] = ()
    #: 이 판정이 본 가용 capability 집합. leave-one-out 이 **같은 조건으로** 다시 돌려야
    #: 비교가 된다 — 조건이 달라지면 "빼서 바뀐 것"과 "조건이 바뀌어 바뀐 것"이 섞인다.
    available_capability_kinds: frozenset[str] | None = None
    assessor: "EvidenceAssessor | None" = field(default=None, repr=False, compare=False)

    @property
    def sufficient(self) -> bool:
        """이 결론을 그대로 써도 되는가. `met` 만 참이다 — 약한 상태를 통과시키지 않는다."""
        return self.sufficiency_state == "met"

    @property
    def missing_kinds(self) -> tuple[str, ...]:
        """없어서 못 고르고 있는 종류 전부(미관측 + 미측정)."""
        return tuple(sorted(set(self.unobserved_kinds) | set(self.unavailable_kinds)))

    def without(self, name: str, *, unit: str = "source_group") -> "SufficiencyAssessment":
        """그 단위를 뺀 판정을 **다시 계산해서** 낸다.

        지우고 되돌리는 것이 아니라 받아들인 근거에서 다시 계산한다 — 원래 무엇이
        들어왔는지가 그대로 남아야 같은 질문을 여러 단위에 반복할 수 있다.
        """
        if self.assessor is None:
            return self
        keep = tuple(row for row in self.accepted if _unit_key(row, unit) != name)
        return self.assessor.assess(
            keep, claim_subject=self.claim_subject,
            inactive=self.unavailable_kinds,
            available_capability_kinds=self.available_capability_kinds)

    def leave_one_out(self, *, unit: str = "source_group") -> tuple[LeaveOneOutRow, ...]:
        """단위별로 "빼면 판정이 무엇이 되는가" 를 전부 낸다."""
        if self.assessor is None:
            return ()
        names: list[str] = []
        for row in self.accepted:
            key = _unit_key(row, unit)
            if key not in names:
                names.append(key)
        out = []
        for name in sorted(names):
            reduced = self.without(name, unit=unit)
            out.append(LeaveOneOutRow(
                removed=name, unit=unit,
                sufficiency_state=reduced.sufficiency_state, claim=reduced.claim,
                reason=reduced.reason,
                changed=(reduced.sufficiency_state != self.sufficiency_state
                         or reduced.claim != self.claim)))
        return tuple(out)

    def explanation(self, *, unit: str = "source_group") -> dict:
        """화면이 "왜 이 판정인가" 를 그리는 데 필요한 것 전부.

        고른 이유(어느 근거가 끌었는가)와 **고르지 못한 이유**(무엇이 없는가, 무엇이
        배제됐는가, 무엇이 미측정인가)를 같은 묶음에 넣는다 — 둘을 나누면 화면은
        확정만 그리게 되고 모호는 빈칸으로 보인다.
        """
        return {
            dd.CLAIM_SUBJECT: self.claim_subject,
            dd.SUFFICIENCY_STATE: self.sufficiency_state,
            dd.CLAIM: self.claim,
            dd.SUFFICIENCY_REASON: self.reason,
            "sufficient": self.sufficient,
            "ranked": [row.as_dict() for row in self.ranked],
            "contradicted_claims": list(self.contradicted_claims),
            dd.OBSERVED_EVIDENCE_KINDS: list(self.observed_kinds),
            dd.UNOBSERVED_EVIDENCE_KINDS: list(self.unobserved_kinds),
            dd.UNAVAILABLE_EVIDENCE_KINDS: dict(sorted(self.unavailable_kinds.items())),
            dd.REJECTED_OBSERVATIONS: [row.as_dict() for row in self.rejected],
            dd.RESOLUTION_REQUESTS: list(self.resolution_requests),
            dd.LEAVE_ONE_OUT: [row.as_dict() for row in self.leave_one_out(unit=unit)],
        }

    def as_dict(self) -> dict:
        return self.explanation()


def _saturating(values: Iterable[float]) -> float:
    """독립 지지를 더하되 1.0 에서 포화시킨다.

    `device_identity._score` 와 같은 모양이다 — 같은 종류의 근거가 여러 번 와도 두
    배의 근거가 되지 않고, 서로 다른 종류는 더해지되 1 을 넘지 않는다.
    """
    total = 0.0
    for value in values:
        total += value * (1.0 - total)
    return total


@dataclass
class EvidenceAssessor:
    """근거 묶음을 받아 "결론을 낼 만큼 받쳐지는가" 를 낸다. 상태를 바꾸지 않는다.

    판정 규칙은 네 줄로 끝난다.

    1. 식별력 있는 **반박**이 가리킨 결론은 후보에서 빠진다. 비식별 지지가 아무리
       많아도 돌아오지 않는다.
    2. 남은 후보 중 식별 근거가 받치는 것이 답이다. 둘 이상이 식별 근거로 받쳐지고
       그 세기 차이가 마진 이하면 고르지 않는다(`contested`) — 거기서 1 위를 고르면
       그것은 판단이 아니라 추측이고, 그 추측이 명령 대상이 된다.
    3. 식별 근거가 하나도 없으면 식별 경로는 **열리지 않는다**. `require_discriminating`
       이 참이면 후보가 하나뿐이어도 `unmet` 이다(`device_identity` 의 `SOLE_CANDIDATE`
       와 같은 뜻 — 이름은 적지만 결속으로 쓰지 않는다).
    4. `require_discriminating` 이 거짓인 질문(객체 클래스 등)은 **독립 출처 수**로
       정한다. 그래도 비식별 선언 근거만으로는 `met` 이 되지 않는다(AI-S-08).

    세기 합은 순위와 동점 처리에만 쓴다. 판정을 만드는 것은 식별력과 독립성의 구조이고,
    그래서 비식별 근거 셋이 식별 근거 하나를 이기는 일이 **구조적으로** 일어나지 않는다.
    """

    kinds: EvidenceKindRegistry = field(default_factory=lambda: DEFAULT_KIND_REGISTRY)
    discriminating_min_strength: float = DISCRIMINATING_MIN_STRENGTH
    discriminating_margin: float = DISCRIMINATING_MARGIN
    min_independent_support: int = MIN_INDEPENDENT_SUPPORT
    #: 이 질문이 식별력 있는 근거를 요구하는가. 개체 식별은 참, 객체 클래스는 거짓이다.
    require_discriminating: bool = True
    #: 질문 이름 → 그 질문이 보는 종류. 데이터이고 코드 분기가 아니다.
    subject_scopes: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_SUBJECT_SCOPES))
    #: 범위를 직접 못박을 때. 주면 `subject_scopes` 보다 앞선다.
    scope: tuple[str, ...] | None = None

    # -- 평가 ------------------------------------------------------------

    def assess(
        self,
        evidence: Iterable[GroundedEvidence],
        *,
        claim_subject: str,
        available_capability_kinds: Iterable[str] | None = None,
        inactive: Mapping[str, str] | None = None,
    ) -> SufficiencyAssessment:
        """근거 묶음 하나를 판정한다.

        한 번의 호출은 **한 질문**을 묻는다. `claim_subject` 가 그 질문의 이름이고,
        선언된 범위(`DEFAULT_SUBJECT_SCOPES`) 밖의 근거는 `kind_out_of_question_scope`
        사유로 거절된다. 섞어 넣으면 개체 id 와 기종 이름이 같은 순위표에 올라 서로
        경쟁하는 것처럼 보이고, 그 순위표는 어느 질문의 답도 아니다. 범위는
        "무엇이 없어서 못 고르는가" 에도 쓰인다 — 개체 식별을 묻는데 "구역을 실측해
        달라" 를 요청하면 운영자는 엉뚱한 일을 하게 된다.

        `available_capability_kinds` 를 주면 그 집합에 없는 capability 가 만드는 종류는
        **미측정**이 된다. 주지 않으면 가용성을 모르는 상태이고, 그때는 등록된 종류
        전부를 말할 수 있었던 것으로 본다 — 모름을 '없음' 으로 바꾸지 않는다.
        """
        rows = tuple(evidence)
        # 가용 집합은 평가자에 저장하지 않고 **판정 결과에 실어** 보낸다 — 평가자를
        # 여러 질문에 재사용할 때 직전 호출의 조건이 다음 판정에 새지 않아야 한다.
        available = (None if available_capability_kinds is None
                     else frozenset(available_capability_kinds))
        inactive_kinds: dict[str, str] = dict(inactive or {})

        in_scope = self.scope_for(claim_subject)
        rejected: list[RejectedEvidence] = []
        usable: list[GroundedEvidence] = []
        for row in sorted(rows, key=lambda r: (r.observed_at, r.evidence_id)):
            spec = self.kinds.spec(row.evidence_kind)
            if spec is None:
                rejected.append(RejectedEvidence(
                    row.evidence_id, row.evidence_kind, REJECT_UNREGISTERED,
                    f"register an EvidenceKindSpec for {row.evidence_kind!r} first"))
                continue
            if row.evidence_kind not in in_scope:
                rejected.append(RejectedEvidence(
                    row.evidence_id, row.evidence_kind, REJECT_OUT_OF_SCOPE,
                    claim_subject))
                continue
            if (available is not None and spec.capability_kind
                    and spec.capability_kind not in available):
                # 장치·제공자가 사라진 근거는 **반대 근거가 아니라 없는 것**이다.
                rejected.append(RejectedEvidence(
                    row.evidence_id, row.evidence_kind, REJECT_UNAVAILABLE,
                    spec.capability_kind))
                continue
            usable.append(row)

        observed = tuple(sorted({row.evidence_kind for row in usable}))
        # 범위 밖 종류의 '없음' 선언은 이 질문의 답에 싣지 않는다 — 공간 실측이 없다는
        # 사실이 개체 식별 화면에 뜨면 운영자는 엉뚱한 일을 하게 된다.
        inactive_kinds = {k: v for k, v in inactive_kinds.items() if k in in_scope}
        for kind in in_scope:
            spec = self.kinds.spec(kind)
            if kind in observed:
                inactive_kinds.pop(kind, None)
                continue
            if (available is not None and spec.capability_kind
                    and spec.capability_kind not in available):
                inactive_kinds.setdefault(kind, f"no_provider:{spec.capability_kind}")
        unobserved = tuple(k for k in in_scope
                           if k not in observed and k not in inactive_kinds)

        ranked = self._rank(usable)
        state, claim, reason, contradicted = self._decide(ranked, usable, in_scope, available)
        return SufficiencyAssessment(
            claim_subject=claim_subject,
            sufficiency_state=state, claim=claim, reason=reason,
            ranked=ranked, contradicted_claims=contradicted,
            observed_kinds=observed, unobserved_kinds=unobserved,
            unavailable_kinds=dict(sorted(inactive_kinds.items())),
            rejected=tuple(rejected),
            resolution_requests=self._requests(observed, in_scope),
            accepted=tuple(usable), available_capability_kinds=available, assessor=self)

    def scope_for(self, claim_subject: str) -> tuple[str, ...]:
        """이 질문이 보는 종류. 못박은 범위 → 선언된 범위 → 등록된 전부 순이다.

        모르는 질문 이름에 전부를 주는 이유: 새 질문이 들어왔을 때 근거가 조용히
        빠지는 것보다 범위가 넓은 편이 낫다. 좁히는 것은 선언 한 줄이다.
        """
        if self.scope is not None:
            return tuple(k for k in self.kinds.kinds() if k in set(self.scope))
        declared = self.subject_scopes.get(claim_subject)
        if declared is None:
            return self.kinds.kinds()
        return tuple(k for k in self.kinds.kinds() if k in set(declared))

    # -- 내부 ------------------------------------------------------------

    def _row(self, evidence: GroundedEvidence, role: str,
             depends_on: str | None) -> EvidenceRow:
        return EvidenceRow(
            evidence=evidence,
            tier=self.kinds.tier_of(evidence.evidence_kind) or TIER_ESTIMATED,
            discriminating=self.kinds.is_discriminating(evidence.evidence_kind),
            role=role, depends_on=depends_on)

    def _rank(self, usable: Sequence[GroundedEvidence]) -> tuple[ClaimSupport, ...]:
        """결론별로 근거를 모으고 독립성을 센다."""
        by_claim: dict[str, list[GroundedEvidence]] = {}
        for row in usable:
            by_claim.setdefault(row.claim, []).append(row)

        supports: list[ClaimSupport] = []
        for claim, items in by_claim.items():
            supporting = [row for row in items if not row.refutes]
            refuting = [row for row in items if row.refutes]

            # 같은 원본 관측에서 나온 것들 중 대표 하나만 센다(규칙 3). 같은 프레임을
            # 두 번 읽어 지지를 두 배로 만드는 길을 구조적으로 막는 자리다.
            groups: dict[tuple[str, str], list[GroundedEvidence]] = {}
            for row in supporting:
                groups.setdefault(row.observation_unit, []).append(row)

            rows: list[EvidenceRow] = []
            representatives: list[GroundedEvidence] = []
            for _, members in sorted(groups.items()):
                ordered = sorted(members, key=lambda r: (-r.strength, r.evidence_id))
                representatives.append(ordered[0])
                rows.append(self._row(ordered[0], ROLE_INDEPENDENT, None))
                rows.extend(self._row(other, ROLE_DEPENDENT, ordered[0].evidence_id)
                            for other in ordered[1:])
            rows.extend(self._row(row, ROLE_DEPENDENT, None) for row in refuting)

            counted = [row for row in representatives if row.strength > 0.0]
            discriminating = [
                row for row in counted
                if self.kinds.is_discriminating(row.evidence_kind)
                and row.strength >= self.discriminating_min_strength]

            # 종류별 최고만 더한다 — 같은 종류가 여러 번 온 것은 한 종류의 지지다.
            best_per_kind: dict[str, float] = {}
            for row in counted:
                best_per_kind[row.evidence_kind] = max(
                    best_per_kind.get(row.evidence_kind, 0.0), row.strength)

            excluded_by = None
            for row in sorted(refuting, key=lambda r: (-r.strength, r.evidence_id)):
                if (self.kinds.is_discriminating(row.evidence_kind)
                        and row.strength >= self.discriminating_min_strength):
                    excluded_by = (row.evidence_kind,
                                   str(row.detail.get(dd.REJECTION_REASON, "refuted")))
                    break

            supports.append(ClaimSupport(
                claim=claim,
                rows=tuple(sorted(rows, key=lambda r: r.evidence.evidence_id)),
                independent_support=len(counted),
                discriminating_support=len(discriminating),
                best_discriminating_strength=max((r.strength for r in discriminating),
                                                 default=0.0),
                strength=_saturating(sorted(best_per_kind.values(), reverse=True)),
                excluded_by=excluded_by))

        # 동점은 결론 이름 순으로 깬다 — 같은 입력이 실행마다 다른 순위를 내면 그
        # 순위를 근거로 한 어떤 설명도 재현되지 않는다.
        return tuple(sorted(supports, key=lambda s: (s.excluded, -s.strength, s.claim)))

    def _decide(
        self, ranked: Sequence[ClaimSupport], usable: Sequence[GroundedEvidence],
        in_scope: Sequence[str], available: frozenset[str] | None,
    ) -> tuple[str, str | None, str, tuple[str, ...]]:
        if not usable:
            if (self.require_discriminating
                    and not self._any_discriminating_kind_available(in_scope, available)):
                return "unobtainable", None, REASON_NO_DISCRIMINATING_PROVIDER, ()
            return "unmet", None, REASON_NO_EVIDENCE, ()

        candidates = [row for row in ranked if not row.excluded]
        if not candidates:
            return ("contested", None, REASON_EVERY_CLAIM_REFUTED,
                    tuple(row.claim for row in ranked if row.excluded))

        supported = sorted(
            (row for row in candidates if row.discriminating_support > 0),
            key=lambda s: (-s.best_discriminating_strength, s.claim))

        if len(supported) > 1:
            best, second = supported[0], supported[1]
            gap = best.best_discriminating_strength - second.best_discriminating_strength
            if gap <= self.discriminating_margin:
                # 식별 근거가 둘을 거의 같게 가리켰다 — 가린 것이 아니다.
                return ("contested", None,
                        f"{REASON_DISCRIMINATING_TOO_CLOSE}:"
                        f"{best.best_discriminating_strength:.2f}/"
                        f"{second.best_discriminating_strength:.2f}",
                        tuple(row.claim for row in supported))
            # 뚜렷한 차이가 있으면 약한 쪽은 **밀린 것**이지 무시된 것이 아니다.
            return ("met", best.claim,
                    f"{REASON_DISCRIMINATING_SUPPORTS}:{best.claim}",
                    tuple(row.claim for row in supported[1:]))

        if len(supported) == 1:
            best = supported[0]
            return ("met", best.claim,
                    f"{REASON_DISCRIMINATING_SUPPORTS}:{best.claim}", ())

        # 여기부터는 식별 근거가 하나도 없다.
        if self.require_discriminating:
            if not self._any_discriminating_kind_available(in_scope, available):
                # 더 기다려서 될 일이 아니다 — 이 배치에는 가릴 수 있는 종류가 없다.
                # `unmet`("아직 모자라다")과 섞으면 운영자가 기다려야 하는지 장비를
                # 들여야 하는지 알 수 없다.
                return ("unobtainable", None, REASON_NO_DISCRIMINATING_PROVIDER, ())
            if len(candidates) == 1:
                # 이름은 적지만 결속으로 쓰지 않는다 — device_identity 의 SOLE_CANDIDATE.
                return "unmet", candidates[0].claim, REASON_SOLE_CANDIDATE, ()
            return "unmet", None, REASON_ONLY_NON_DISCRIMINATING, ()

        # 동점은 결론 이름 순으로 깬다 — 같은 입력에 같은 답을 내야 설명이 재현된다.
        ordered = sorted(candidates,
                         key=lambda s: (-s.independent_support, -s.strength, s.claim))
        best = ordered[0]
        rivals = ordered[1:]
        if rivals:
            top_rival = rivals[0]
            if (top_rival.independent_support == best.independent_support
                    and abs(top_rival.strength - best.strength)
                    <= self.discriminating_margin):
                return ("contested", None, REASON_CLAIMS_TIED,
                        tuple(sorted({best.claim, top_rival.claim})))
        if set(best.tiers) == {TIER_DECLARED}:
            # 선언만 모였다. 사전정보만으로 확정하지 않는다(AI-S-08).
            return "unmet", best.claim, REASON_ONLY_DECLARED_PRIORS, ()
        if best.independent_support < self.min_independent_support:
            return ("unmet", best.claim,
                    f"{REASON_INDEPENDENT_SUPPORT_SHORT}:"
                    f"{best.independent_support}/{self.min_independent_support}", ())
        return ("met", best.claim,
                f"{REASON_INDEPENDENT_SUPPORT_MET}:{best.independent_support}", ())

    def _any_discriminating_kind_available(
        self, in_scope: Sequence[str], available: frozenset[str] | None,
    ) -> bool:
        """이 질문에 가릴 수 있는 종류가 지금 하나라도 있는가.

        가용성을 모르는 호출(`available is None`)에서는 **있다고 본다** — 모름을
        '없음' 으로 바꾸면 가용 집합을 넘기지 않는 호출자가 전부 `unobtainable` 을
        받게 되고, 그것은 사실이 아니다.
        """
        discriminating = [k for k in in_scope if self.kinds.is_discriminating(k)]
        if available is None:
            return bool(discriminating)
        for kind in discriminating:
            spec = self.kinds.spec(kind)
            if not spec.capability_kind or spec.capability_kind in available:
                return True
        return False

    def _requests(self, observed: Sequence[str],
                  in_scope: Sequence[str]) -> tuple[str, ...]:
        """무엇을 더 하면 풀리는지. 이미 말한 종류는 다시 요청하지 않는다.

        `device_identity._requests` 와 같은 모양이다 — 요청은 "이것을 가능하게 해
        달라" 는 말이고, 지금 제공자가 없다는 사실이 요청을 막지는 않는다(마커 부착은
        capability 등록이 아니라 물리 행동이다). 실제 실행은 다른 파트다(AI-C-19).
        """
        wanted = ([k for k in in_scope if self.kinds.is_discriminating(k)]
                  if self.require_discriminating else list(in_scope))
        requests: list[str] = []
        for kind in wanted:
            if kind in observed:
                continue
            request = self.kinds.spec(kind).request
            if request and request not in requests:
                requests.append(request)
        return tuple(sorted(requests))


#: 개체 식별을 묻는 평가자. 식별력 있는 근거를 요구한다(`device_identity` 와 같은 규칙).
def identity_assessor(kinds: EvidenceKindRegistry | None = None) -> EvidenceAssessor:
    return EvidenceAssessor(kinds=kinds or DEFAULT_KIND_REGISTRY,
                            require_discriminating=True)


#: 객체 클래스·공간 값을 묻는 평가자. 독립 출처 수로 정한다(`object_record` 와 같은 규칙).
def support_count_assessor(kinds: EvidenceKindRegistry | None = None) -> EvidenceAssessor:
    return EvidenceAssessor(kinds=kinds or DEFAULT_KIND_REGISTRY,
                            require_discriminating=False)


__all__ = [
    "DEFAULT_KIND_REGISTRY", "DEFAULT_SUBJECT_SCOPES", "REJECT_OUT_OF_SCOPE",
    "REJECT_UNAVAILABLE", "REJECT_UNREGISTERED",
    "SUBJECT_DEVICE_CLASS", "SUBJECT_DEVICE_IDENTITY", "SUBJECT_ENVIRONMENT_STATE",
    "SUBJECT_OBJECT_CLASS", "SUBJECT_ZONE_QUANTITY",
    "DISCRIMINATING_CUES", "DISCRIMINATING_MARGIN",
    "DISCRIMINATING_MIN_STRENGTH", "MIN_INDEPENDENT_SUPPORT", "REQUIREMENT",
    "ROLE_DEPENDENT", "ROLE_INDEPENDENT",
    "TIER_DECLARED", "TIER_ESTIMATED", "TIER_MEASURED",
    "ClaimSupport", "EvidenceAssessor", "EvidenceBatch", "EvidenceKindRegistry",
    "EvidenceKindSpec", "EvidenceRow", "GroundedEvidence", "LeaveOneOutRow",
    "RejectedEvidence", "SufficiencyAssessment",
    "collect", "default_kind_registry", "from_appearance_verdict", "from_class_cues",
    "from_identity_cues", "from_object_record_evidence", "from_prior_records",
    "from_spatial_quantity", "from_twin_evidence_rows", "identity_assessor",
    "support_count_assessor",
]
