"""구역의 공간 상태를 **출처가 남은 채로** 합친다.

implements: AI-S-06 (이종 근거의 점진적 통합), AI-S-08 (사전정보와 관측의 분리),
            AI-C-02 (좌표계 경계), AI-C-15 (도메인은 데이터)
관련: AI-E-04 (선택형 보조 기능), AI-L-03 (사람 확인 정보), AI-C-19 (권한 경계)
tests: tests/test_spatial_evidence.py

## 문제

"이 구역에서 그 카메라는 어디 있나" 를 말해 주는 출처가 한둘이 아니다 — 선언 프로파일,
GPS 수신, 여러 대가 동시에 본 탐지, 깊이맵, 점군, 열린 어휘 탐지, 그리고 **관제 웹에서
사람이 줄자로 재어 입력한 값**. 이들의 정확도와 믿을 만함이 전부 다르다.

평균 한 번으로 끝내면 숫자 하나는 나오지만 *그 숫자가 어디서 왔는지* 가 사라진다.
사람이 5cm 로 실측한 값과 깊이맵이 먼 거리에서 추측한 값이 융합 뒤에 구분되지 않으면,
지도가 틀렸을 때 **무엇을 고쳐야 하는지** 알 수 없다. 그래서 이 모듈은 값을 합치되
근거를 남긴다.

## 지키는 규칙 (전부 시험으로 고정돼 있다)

1. **로컬 좌표만 낸다.** 여기서 나오는 값은 전부 현장 로컬 미터 좌표다. 전역 좌표
   변환과 최종 디지털 트윈 상태는 백엔드 소유이고(AI-C-02, AI-C-19), GPS 는 로컬
   프레임을 접지·교차검증하는 **입력**일 뿐이다. 그래서 GPS 종류는 로컬 환산 기준
   (`local_reduction_ref`) 없이는 융합에 들어가지 못한다 — 환산 기준 없는 절대 좌표를
   로컬 값에 섞는 순간 그 자리는 전역 좌표가 된다.
2. **정확도는 선언값이고 추정하지 않는다.** `accuracy_m` 이 None 이면 모름으로 남는다.
   선언한 근거가 하나라도 있으면 모름은 가중에서 **보류**된다(역할 `accuracy_unknown`) —
   기본값을 꽂으면 모르는 값이 아는 값을 이길 수 있다.
3. **사람 실측은 다른 격의 근거다.** 사람 입력은 센서 융합에 섞지 않고 현재 상태를
   **덮는다**. 대신 덮기 전 값(`without_human_value`)을 함께 들고 있어서, 덮었다고
   센서가 말한 것이 소급해 바뀌지는 않는다. 서명(`entered_by`)이 없는 사람 입력은
   받지 않는다(AI-L-03: 사용자 확인 정보와 AI 후보를 구분해 보존해야 한다).
4. **없음은 반대 근거가 아니다.** 점군이 없고 깊이가 없고 GPS 가 없는 것은 어떤 값도
   주장하지 않는다. 등록만 돼 있고 관측이 없는 종류는 `unobserved_kinds` 로 드러나며
   값에 아무 영향도 주지 않는다(AI-C-05 의 축소 운용이 정상 구성이라는 것과 같은 축).
5. **한 출처를 빼면 값이 무엇이 되는지 답할 수 있다.** `leave_one_out()` 이 그 답이다.
   이것이 없으면 틀린 지도를 디버깅할 방법이 없다.
6. **같은 원본 관측에서 나온 둘은 하나로 센다.** 독립성의 단위는 생산자가 아니라
   `frame_ref` — 같은 프레임·같은 점군을 읽은 두 provider 는 서로를 확증하지 못한다
   (AI-S-06: 중복·의존 근거를 구분할 여지를 유지해야 한다).
7. **선언만으로는 확정하지 않는다.** 값을 움직인 근거가 전부 `declared` 격이면 값은
   그대로 내지만 `confirmed` 는 False 이고 사유(`declared_prior_only`)가 남는다
   (AI-S-08: "실제 관측과 충돌하는 사전정보만으로 객체·위험 상태를 확정해서는 안
   된다"). 확정에는 측정 또는 추정 격의 근거가 최소 하나 필요하고, 못 갖춘 것은
   오류가 아니라 **상태**다 — 선언만 있는 현장은 정상 배치다(규칙 4).
8. **종류가 늘어나도 `if` 가 늘지 않는다.** 근거 종류는 레지스트리에 등록되는 데이터이고
   (AI-C-18 의 선언 규약과 같은 축), 도메인 이름·센서 제품 이름으로 갈라지는 분기가
   이 모듈에 없다(절대 준수 원칙 #1, #3).

## 소유하지 않는 것

영상 좌표 박스를 미터 평면 자리로 바꾸는 일(보정)은 AI-E-02 의 몫이고, 그 보정이 없는
배치에서는 열린 어휘 탐지가 이 계약에 **관측을 하나도 내지 않는다** — 규칙 4 가 그 경우를
이미 정상으로 다룬다. 어느 값이 권위 있는 최종 지도인지도 백엔드가 정한다(AI-C-19).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability import CapabilityRequirement

#: 공간 융합의 필수·선택 의존. 선언 프로파일만 있으면 구역 공간 상태는 성립하고
#: 나머지는 전부 선택이다 — 선택 결손은 DEGRADED 까지만 내려간다(AI-C-05).
REQUIREMENT = CapabilityRequirement(
    required=("reference.zone_profile",),
    optional=("positioning.absolute", "perception.detect", "perception.depth",
              "perception.point_cloud", "perception.open_vocabulary",
              "reference.human_survey"),
)

# --- 근거의 격 --------------------------------------------------------------
#: 사람이 재어 입력한 값. 현재 상태를 덮을 수 있는 유일한 격이다.
TIER_MEASURED = "measured"
#: 프로파일·인프라 선언. "있을 것" 이라고 적힌 값이다.
TIER_DECLARED = "declared"
#: 센서·모델 추정.
TIER_ESTIMATED = "estimated"

#: 격의 서열. 값이 아니라 **출처의 성질**로 서는 서열이다 — 정확도가 좋은 추정이
#: 사람 실측과 같은 격이 되지는 않는다.
_TIER_RANK = {TIER_MEASURED: 0, TIER_DECLARED: 1, TIER_ESTIMATED: 2}

# --- 등록된 근거 종류 -------------------------------------------------------
KIND_GPS = "gps"
KIND_MULTI_DEVICE_DETECTION = "multi_device_detection"
KIND_DEPTH = "depth"
KIND_POINT_CLOUD = "point_cloud"
KIND_ZERO_SHOT_DETECTION = "zero_shot_detection"
KIND_INFRASTRUCTURE_DECLARATION = "infrastructure_declaration"
KIND_HUMAN_SURVEY = "human_survey"

# --- 거절 사유 (dd.SPATIAL_REJECTION_REASONS) --------------------------------
REJECT_UNREGISTERED_KIND = "unregistered_kind"
REJECT_SOURCE_UNAVAILABLE = "source_unavailable"
REJECT_NOT_LOCAL = "not_reduced_to_local_frame"
REJECT_MISSING_AUTHOR = "missing_author"
REJECT_FRAME_MISMATCH = "frame_mismatch"
REJECT_ARITY_MISMATCH = "arity_mismatch"
REJECT_DUPLICATE = "duplicate_evidence_id"

# --- 역할 (dd.CONTRIBUTION_ROLES) -------------------------------------------
ROLE_INDEPENDENT = "independent"
ROLE_DEPENDENT = "dependent"
ROLE_ACCURACY_UNKNOWN = "accuracy_unknown"
ROLE_UNWEIGHTED_MEAN = "unweighted_mean"
ROLE_OVERRIDE = "override"
ROLE_SUPERSEDED = "superseded"

# --- 결정 규칙 (dd.SPATIAL_DECISION_RULES) -----------------------------------
DECIDED_HUMAN_OVERRIDE = "human_survey_override"
DECIDED_INVERSE_VARIANCE = "inverse_variance_fusion"
DECIDED_UNWEIGHTED_MEAN = "unweighted_mean"
DECIDED_NO_EVIDENCE = "no_evidence"

# --- 확정이 안 된 사유 (dd.UNCONFIRMED_REASONS) ------------------------------
#: 움직일 근거가 아예 없다.
UNCONFIRMED_NO_EVIDENCE = "no_evidence"
#: 값을 움직인 것이 **선언뿐**이다. AI-S-08: "실제 관측과 충돌하는 사전정보만으로
#: 객체·위험 상태를 확정해서는 안 된다." 선언은 "있을 것"이라고 적힌 값이므로 그것만
#: 으로는 확정이 되지 못한다 — 값은 그대로 내고 확정만 보류한다(규칙 4 와 같은 축:
#: 없음은 오류가 아니라 상태다).
UNCONFIRMED_DECLARED_ONLY = "declared_prior_only"

#: 전역 좌표 프레임으로 알려진 이름. 이 이름으로 들어온 관측은 융합 대상이 아니다 —
#: 프레임 **어휘** 검사이고 센서 제품 분기가 아니다(원칙 #1).
GLOBAL_FRAME_TOKENS: frozenset[str] = frozenset({
    "wgs84", "epsg:4326", "epsg:3857", "global", "geodetic", "lla", "ecef", "utm",
})


def is_local_frame(frame_id: str) -> bool:
    """현장 로컬 프레임 이름인가. 전역 프레임 이름은 여기서 막는다(AI-C-02)."""
    return bool(frame_id) and frame_id.strip().lower() not in GLOBAL_FRAME_TOKENS


@dataclass(frozen=True)
class EvidenceKindSpec:
    """한 공간 근거 종류의 선언. **데이터이고 코드 분기가 아니다**(AI-C-18).

    새 센서가 들어오면 이 선언 하나를 등록하면 되고 융합 코드는 그대로다. 종류가
    주장할 수 있는 성질은 두 가지뿐이다 — 어떤 격의 근거인가, 그리고 쓰기 전에
    무엇이 더 필요한가.
    """

    kind: str
    tier: str
    #: 절대 측위처럼 로컬 환산 기준이 있어야 쓸 수 있는가(AI-C-02).
    needs_local_reduction: bool = False
    #: 사람 입력처럼 서명(누가·언제)이 있어야 받는가(AI-L-03).
    requires_author: bool = False
    #: 사람 실측만 현재 상태를 덮는다. 센서 정확도가 아무리 좋아도 격은 못 올린다.
    overrides: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("kind must not be empty")
        if self.tier not in _TIER_RANK:
            raise ValueError(f"unknown evidence tier {self.tier!r}; "
                             f"expected one of {tuple(_TIER_RANK)}")


@dataclass
class SpatialEvidenceKindRegistry:
    """등록된 근거 종류. 등록되지 않은 종류의 관측은 조용히 쓰이지 않고 **거절 사유로**
    남는다 — 종류 이름 오타가 값을 바꾸지 않은 채 사라지는 것이 가장 찾기 어려운 버그다.
    """

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

    def copy(self) -> "SpatialEvidenceKindRegistry":
        return SpatialEvidenceKindRegistry(dict(self._specs))


def default_kind_registry() -> SpatialEvidenceKindRegistry:
    """현재 배포가 아는 일곱 종류. 새 종류는 `register()` 로 늘린다."""
    registry = SpatialEvidenceKindRegistry()
    for spec in (
        EvidenceKindSpec(
            KIND_GPS, TIER_ESTIMATED, needs_local_reduction=True,
            note="거칠고 실내에서는 아예 없다. 로컬 프레임의 접지·교차검증 입력이다."),
        EvidenceKindSpec(
            KIND_MULTI_DEVICE_DETECTION, TIER_ESTIMATED,
            note="여러 대가 동시에 본 결과. 서로 다른 frame_ref 일 때만 독립이다."),
        EvidenceKindSpec(
            KIND_DEPTH, TIER_ESTIMATED,
            note="촘촘하지만 먼 거리에서 급격히 나빠진다 — 그래서 정확도를 거리별로 선언한다."),
        EvidenceKindSpec(
            KIND_POINT_CLOUD, TIER_ESTIMATED,
            note="기하만 있고 의미가 없다. 같은 점군에서 뽑은 두 값은 하나의 지지다."),
        EvidenceKindSpec(
            KIND_ZERO_SHOT_DETECTION, TIER_ESTIMATED,
            note="고정 클래스 없는 의미. 미터 자리로 오려면 보정이 필요하고 보정이 없으면 "
                 "관측을 내지 않는다(규칙 4)."),
        EvidenceKindSpec(
            KIND_INFRASTRUCTURE_DECLARATION, TIER_DECLARED,
            note="프로파일에 적힌 고정 설치물. 실측이 아니라 선언이고, 프로파일은 정확도를 "
                 "적지 않으므로 보통 accuracy_m 가 None 이다."),
        EvidenceKindSpec(
            KIND_HUMAN_SURVEY, TIER_MEASURED, requires_author=True, overrides=True,
            note="관제 웹에서 사람이 재어 넣거나 고친 값. 현재 상태를 덮지만 센서 기록은 "
                 "그대로 남는다."),
    ):
        registry.register(spec)
    return registry


#: 모듈 기본 레지스트리. 배치별로 바꿔야 하면 `copy()` 해서 쓴다.
DEFAULT_KIND_REGISTRY = default_kind_registry()


@dataclass(frozen=True)
class SpatialObservation:
    """공간에 대한 근거 1건.

    provenance 모양은 `perception/object_record.py` 의 `Evidence` 를 그대로 쓴다
    (`evidence_id` · `source_group` · `frame_ref` · `observed_at` · `frame_id`) —
    같은 뜻의 출처 정보를 두 모양으로 들고 다니면 근거를 서로 되짚을 수 없다.
    """

    evidence_id: str
    source_group: str          # provenance: 어느 출처 묶음이 냈는가
    frame_ref: str             # 원본 관측(프레임·점군·실측 회차) — 독립성의 단위
    observed_at: float
    evidence_kind: str         # 등록된 공간 근거 종류
    quantity_id: str           # 구역의 어느 값에 대한 말인가
    value: tuple[float, ...]   # 현장 로컬 미터 값 (길이는 1성분, 평면 자리는 2성분)
    frame_id: str              # 현장 로컬 프레임 (AI-C-02)
    #: 그 관측이 **스스로 선언한** 1σ 정확도(m). None 은 모름이고 모름으로 남는다.
    accuracy_m: float | None = None
    entered_by: str | None = None
    entered_at: float | None = None
    #: 절대 측위를 로컬로 환산한 기준(앵커·측량점 id).
    local_reduction_ref: str | None = None
    detail: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence_id must not be empty")
        if not self.quantity_id:
            raise ValueError("quantity_id must not be empty")
        if not self.value:
            raise ValueError(f"{self.evidence_id}: value must have at least one component")
        if self.accuracy_m is not None and not self.accuracy_m > 0.0:
            # 0 은 "완벽" 이 아니라 무한 가중이다. 모르면 None 으로 적는다.
            raise ValueError(f"{self.evidence_id}: accuracy_m must be > 0 or None, "
                             f"got {self.accuracy_m}")

    @property
    def accuracy_declared(self) -> bool:
        return self.accuracy_m is not None


@dataclass(frozen=True)
class RejectedObservation:
    """쓰지 못한 관측과 그 사유. 조용히 버리지 않는 이유는 규칙 4·5 와 같다."""

    evidence_id: str
    evidence_kind: str
    quantity_id: str
    reason: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {dd.EVIDENCE_ID: self.evidence_id,
                dd.SPATIAL_EVIDENCE_KIND: self.evidence_kind,
                dd.QUANTITY_ID: self.quantity_id,
                dd.REJECTION_REASON: self.reason,
                "detail": self.detail}


@dataclass(frozen=True)
class Contribution:
    """한 근거가 값에 어떻게 들어갔는가. 융합 뒤에도 이 줄이 남는다."""

    evidence_id: str
    evidence_kind: str
    tier: str
    source_group: str
    frame_ref: str
    value: tuple[float, ...]
    accuracy_m: float | None
    weight: float
    role: str
    observed_at: float
    entered_by: str | None = None
    entered_at: float | None = None

    @property
    def weighted(self) -> bool:
        return self.weight > 0.0

    def as_dict(self) -> dict:
        return {
            dd.EVIDENCE_ID: self.evidence_id,
            dd.SPATIAL_EVIDENCE_KIND: self.evidence_kind,
            dd.EVIDENCE_TIER: self.tier,
            dd.SOURCE_GROUP: self.source_group,
            dd.FRAME_REF: self.frame_ref,
            dd.FUSED_VALUE: list(self.value),
            dd.ACCURACY_M: self.accuracy_m,
            dd.CONTRIBUTION_WEIGHT: round(self.weight, 6),
            dd.CONTRIBUTION_ROLE: self.role,
            dd.OBSERVED_AT: self.observed_at,
            dd.ENTERED_BY: self.entered_by,
            dd.ENTERED_AT: self.entered_at,
        }


@dataclass(frozen=True)
class LeaveOneOut:
    """그 출처를 빼면 값이 무엇이 되는가.

    `influence_m` 가 0 이면 그 출처는 값을 정하지 않았다는 뜻이다 — 정확도를 선언하지
    않아 보류된 근거와 같은 원본 관측에 종속된 근거가 그렇다. 틀린 지도를 들고 왔을 때
    먼저 보는 줄이 이것이다.
    """

    removed: str
    unit: str
    value: tuple[float, ...] | None
    accuracy_m: float | None
    decided_by: str
    influence_m: float | None

    @property
    def vanished(self) -> bool:
        """그 출처를 빼면 값 자체가 사라지는가 — 혼자 받치고 있었다는 뜻이다."""
        return self.value is None

    def as_dict(self) -> dict:
        return {"removed": self.removed, "unit": self.unit,
                dd.FUSED_VALUE: None if self.value is None else list(self.value),
                dd.ACCURACY_M: self.accuracy_m,
                dd.DECIDED_BY: self.decided_by,
                dd.INFLUENCE_M: self.influence_m}


@dataclass(frozen=True)
class SpatialQuantityState:
    """구역의 값 하나에 대한 현재 상태와 **그렇게 된 이유** 전부."""

    quantity_id: str
    zone_id: str
    frame_id: str
    value: tuple[float, ...] | None
    accuracy_m: float | None
    decided_by: str
    tier: str | None
    contributing_kinds: tuple[str, ...]
    independent_support: int
    contributions: tuple[Contribution, ...]
    rejected: tuple[RejectedObservation, ...] = ()
    #: 사람 입력을 빼면 센서·선언만으로 무엇이었는가. 사람 입력이 없으면 None 이 아니라
    #: 현재 값과 같다 — 덮은 적이 없다는 것을 값으로 보여 준다.
    without_human_value: tuple[float, ...] | None = None
    without_human_accuracy_m: float | None = None
    entered_by: str | None = None
    entered_at: float | None = None
    #: 융합을 다시 돌릴 수 있도록 받아들인 관측을 들고 있다. leave-one-out 이 이걸 쓴다.
    accepted: tuple[SpatialObservation, ...] = ()
    #: 이 상태를 만든 종류 레지스트리. 다시 계산할 때 같은 선언으로 돌아야 한다.
    kinds: "SpatialEvidenceKindRegistry" = field(default_factory=lambda: DEFAULT_KIND_REGISTRY)
    #: 이 값을 확정으로 써도 되는가. **값이 있다는 것과 다른 축이다** — 선언만으로
    #: 나온 값은 자리를 말해 주지만 확정이 아니다(AI-S-08).
    confirmed: bool = False
    #: 확정이 아니면 그 사유. 확정이면 None 이다. 사유 없이 보류하면 화면은 빈칸만
    #: 보게 되고 운영자는 무엇을 더 재야 하는지 알 수 없다.
    unconfirmed_reason: str | None = UNCONFIRMED_NO_EVIDENCE

    @property
    def human_override(self) -> bool:
        return self.decided_by == DECIDED_HUMAN_OVERRIDE

    @property
    def accuracy_known(self) -> bool:
        return self.accuracy_m is not None

    def contribution(self, evidence_id: str) -> Contribution | None:
        for row in self.contributions:
            if row.evidence_id == evidence_id:
                return row
        return None

    # -- 한 출처를 빼면 ---------------------------------------------------

    def without(self, name: str, *, unit: str = "source_group") -> "SpatialQuantityState":
        """그 출처를 뺀 융합을 **다시 계산해서** 낸다.

        지우고 되돌리는 것이 아니라 받아들인 관측에서 다시 계산한다 — 원래 무엇이
        들어왔는지가 그대로 남아야 같은 질문을 여러 출처에 반복할 수 있다.
        """
        keep = tuple(obs for obs in self.accepted
                     if _unit_key(obs, unit) != name)
        return _fuse_quantity(self.quantity_id, keep, zone_id=self.zone_id,
                              frame_id=self.frame_id, rejected=self.rejected,
                              kinds=self.kinds)

    def leave_one_out(self, *, unit: str = "source_group") -> tuple[LeaveOneOut, ...]:
        """출처별로 "빼면 얼마가 되는가" 를 전부 낸다.

        `unit` 으로 빼는 단위를 고른다 — 출처 묶음(기본), 근거 종류, 원본 관측.
        """
        names = []
        for obs in self.accepted:
            key = _unit_key(obs, unit)
            if key not in names:
                names.append(key)
        out = []
        for name in sorted(names):
            reduced = self.without(name, unit=unit)
            out.append(LeaveOneOut(
                removed=name, unit=unit, value=reduced.value,
                accuracy_m=reduced.accuracy_m, decided_by=reduced.decided_by,
                influence_m=_distance(self.value, reduced.value),
            ))
        return tuple(out)

    def as_dict(self) -> dict:
        """최상위 이름은 전부 공통 데이터 사전에 등재돼 있다(AI-C-01)."""
        return {
            dd.QUANTITY_ID: self.quantity_id,
            dd.ZONE_ID: self.zone_id,
            dd.COORDINATE_FRAME: self.frame_id,
            dd.FUSED_VALUE: None if self.value is None else list(self.value),
            dd.ACCURACY_M: self.accuracy_m,
            dd.DECIDED_BY: self.decided_by,
            dd.EVIDENCE_TIER: self.tier,
            dd.CONTRIBUTING_EVIDENCE_KINDS: list(self.contributing_kinds),
            dd.VALUE_CONFIRMED: self.confirmed,
            dd.UNCONFIRMED_REASON: self.unconfirmed_reason,
            dd.INDEPENDENT_SUPPORT_COUNT: self.independent_support,
            dd.CONTRIBUTIONS: [row.as_dict() for row in self.contributions],
            dd.REJECTED_OBSERVATIONS: [row.as_dict() for row in self.rejected],
            dd.WITHOUT_HUMAN_VALUE: (None if self.without_human_value is None
                                     else list(self.without_human_value)),
            dd.ENTERED_BY: self.entered_by,
            dd.ENTERED_AT: self.entered_at,
            dd.LEAVE_ONE_OUT: [row.as_dict() for row in self.leave_one_out()],
        }


@dataclass(frozen=True)
class ZoneSpatialState:
    """한 구역의 공간 상태 전체. 값마다 출처 내역이 붙어 있다."""

    zone_id: str
    frame_id: str
    quantities: Mapping[str, SpatialQuantityState]
    observed_kinds: tuple[str, ...]
    #: 등록돼 있으나 이번에 관측이 없는 종류. **없음은 반대 근거가 아니다**(규칙 4).
    unobserved_kinds: tuple[str, ...]
    rejected: tuple[RejectedObservation, ...] = ()
    #: 호출 시점에 쓸 수 없었던 출처. 비어 있지 않아도 상태는 성립한다(AI-C-05).
    unavailable_sources: tuple[str, ...] = ()

    def quantity(self, quantity_id: str) -> SpatialQuantityState | None:
        return self.quantities.get(quantity_id)

    def as_dict(self) -> dict:
        return {
            dd.ZONE_ID: self.zone_id,
            dd.COORDINATE_FRAME: self.frame_id,
            "quantities": {qid: state.as_dict()
                           for qid, state in sorted(self.quantities.items())},
            dd.UNOBSERVED_EVIDENCE_KINDS: list(self.unobserved_kinds),
            dd.REJECTED_OBSERVATIONS: [row.as_dict() for row in self.rejected],
        }


# --- 융합 -------------------------------------------------------------------

def _unit_key(obs: SpatialObservation, unit: str) -> str:
    if unit == "source_group":
        return obs.source_group
    if unit == "kind":
        return obs.evidence_kind
    if unit == "frame_ref":
        return obs.frame_ref
    raise ValueError(f"unknown leave-one-out unit {unit!r}; "
                     "expected 'source_group', 'kind' or 'frame_ref'")


def _distance(a: tuple[float, ...] | None, b: tuple[float, ...] | None) -> float | None:
    """두 값이 얼마나 떨어졌는가. 한쪽이 없으면 거리는 **모름**이고 0 이 아니다."""
    if a is None or b is None:
        return None
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _weighted_mean(rows: Sequence[tuple[tuple[float, ...], float]]) -> tuple[tuple[float, ...], float]:
    total = sum(weight for _, weight in rows)
    arity = len(rows[0][0])
    value = tuple(sum(v[i] * w for v, w in rows) / total for i in range(arity))
    return value, total


def _plain_mean(values: Sequence[tuple[float, ...]]) -> tuple[float, ...]:
    arity = len(values[0])
    return tuple(sum(v[i] for v in values) / len(values) for i in range(arity))


def _representatives(
    observations: Sequence[SpatialObservation],
) -> tuple[list[SpatialObservation], list[tuple[SpatialObservation, str]]]:
    """원본 관측별로 대표 하나를 고른다.

    같은 `frame_ref` 에서 나온 값들은 서로를 확증하지 못하므로(규칙 6) 그 안에서
    가장 좋은 정확도 하나만 가중에 들어가고 나머지는 `dependent` 로 남는다. 한
    프레임을 두 번 읽어 지지를 두 배로 만드는 길을 구조적으로 막는 자리다.
    """
    groups: dict[str, list[SpatialObservation]] = {}
    for obs in observations:
        groups.setdefault(obs.frame_ref, []).append(obs)

    chosen: list[SpatialObservation] = []
    dependent: list[tuple[SpatialObservation, str]] = []
    for _, members in sorted(groups.items()):
        # 정확도를 선언한 것이 먼저, 그중 가장 좋은 것. 동점은 id 로 가른다 —
        # 같은 입력에 같은 답을 내야 leave-one-out 이 비교 가능하다.
        ranked = sorted(members, key=lambda o: (o.accuracy_m is None,
                                                o.accuracy_m if o.accuracy_m is not None else 0.0,
                                                o.evidence_id))
        chosen.append(ranked[0])
        dependent.extend((obs, ROLE_DEPENDENT) for obs in ranked[1:])
    return chosen, dependent


def _fuse_quantity(
    quantity_id: str,
    observations: Sequence[SpatialObservation],
    *,
    zone_id: str,
    frame_id: str,
    rejected: Sequence[RejectedObservation] = (),
    kinds: SpatialEvidenceKindRegistry = DEFAULT_KIND_REGISTRY,
) -> SpatialQuantityState:
    """받아들인 관측만으로 값 하나를 정한다. 여기서 더 거절하지 않는다."""
    human = [obs for obs in observations
             if (kinds.spec(obs.evidence_kind) or _FALLBACK_SPEC).overrides]
    overriding = {obs.evidence_id for obs in human}
    sensed = [obs for obs in observations if obs.evidence_id not in overriding]

    rows: list[Contribution] = []

    def tier_of(obs: SpatialObservation) -> str:
        return kinds.tier_of(obs.evidence_kind) or TIER_ESTIMATED

    def row(obs: SpatialObservation, weight: float, role: str) -> Contribution:
        return Contribution(
            evidence_id=obs.evidence_id, evidence_kind=obs.evidence_kind,
            tier=tier_of(obs), source_group=obs.source_group, frame_ref=obs.frame_ref,
            value=obs.value, accuracy_m=obs.accuracy_m, weight=weight, role=role,
            observed_at=obs.observed_at, entered_by=obs.entered_by,
            entered_at=obs.entered_at)

    # -- 센서·선언 쪽 융합 (사람 입력을 섞지 않는다) -----------------------
    sensor_value: tuple[float, ...] | None = None
    sensor_accuracy: float | None = None
    sensor_rule = DECIDED_NO_EVIDENCE
    independent = 0

    if sensed:
        chosen, dependent = _representatives(sensed)
        declared = [obs for obs in chosen if obs.accuracy_declared]
        undeclared = [obs for obs in chosen if not obs.accuracy_declared]
        if declared:
            # 역분산 가중. 정확도를 선언하지 않은 대표는 **보류**된다 — 기본 σ 를
            # 꽂으면 모르는 값이 아는 값을 이길 수 있다(규칙 2).
            weighted = [(obs.value, 1.0 / (obs.accuracy_m ** 2)) for obs in declared]
            sensor_value, total_weight = _weighted_mean(weighted)
            sensor_accuracy = math.sqrt(1.0 / total_weight)
            sensor_rule = DECIDED_INVERSE_VARIANCE
            independent = len(declared)
            for obs in declared:
                rows.append(row(obs, 1.0 / (obs.accuracy_m ** 2), ROLE_INDEPENDENT))
            for obs in undeclared:
                rows.append(row(obs, 0.0, ROLE_ACCURACY_UNKNOWN))
        else:
            # 아무도 정확도를 선언하지 않았다. 평균은 내지만 정확도는 **모름으로 남긴다** —
            # 여기서 숫자를 지어내면 그 숫자가 다음 융합을 지배한다.
            sensor_value = _plain_mean([obs.value for obs in undeclared])
            sensor_accuracy = None
            sensor_rule = DECIDED_UNWEIGHTED_MEAN
            independent = len(undeclared)
            for obs in undeclared:
                rows.append(row(obs, 0.0, ROLE_UNWEIGHTED_MEAN))
        rows.extend(row(obs, 0.0, role) for obs, role in dependent)

    # -- 사람 실측이 있으면 덮는다 (센서 기록은 위에 그대로 남아 있다) -------
    value, accuracy, rule = sensor_value, sensor_accuracy, sensor_rule
    entered_by = entered_at = None
    if human:
        # 가장 나중에 입력된 실측이 현재 값이다. 더 이른 것은 지우지 않고
        # `superseded` 로 남긴다 — 고친 이력이 설명돼야 한다.
        ranked = sorted(human, key=lambda o: (o.entered_at if o.entered_at is not None
                                              else o.observed_at, o.evidence_id))
        current = ranked[-1]
        for obs in ranked[:-1]:
            rows.append(row(obs, 0.0, ROLE_SUPERSEDED))
        rows.append(row(current, 0.0, ROLE_OVERRIDE))
        value, accuracy, rule = current.value, current.accuracy_m, DECIDED_HUMAN_OVERRIDE
        entered_by, entered_at = current.entered_by, current.entered_at
        independent = max(independent, 0) + 1

    moving = [r for r in rows if r.role in (ROLE_INDEPENDENT, ROLE_UNWEIGHTED_MEAN,
                                            ROLE_OVERRIDE)]
    tier = None
    if moving:
        tier = min((r.tier for r in moving), key=lambda t: _TIER_RANK.get(t, 9))

    # -- 확정은 실제 관측을 요구한다 (AI-S-08) -----------------------------
    # 값을 움직인 것이 선언뿐이면 확정하지 않는다. 선언은 "있을 것"이라고 적힌
    # 사전정보이고, 그것만으로 상태를 확정하면 프로파일의 오타가 지도의 사실이 된다.
    # 예외가 아니라 **상태로** 돌려준다 — 선언만 있는 현장은 정상 배치이고(규칙 4),
    # 값은 그대로 쓰되 확정 여부가 따로 적힌다.
    observed = [r for r in moving if r.tier != TIER_DECLARED]
    if not moving:
        confirmed, unconfirmed_reason = False, UNCONFIRMED_NO_EVIDENCE
    elif not observed:
        confirmed, unconfirmed_reason = False, UNCONFIRMED_DECLARED_ONLY
    else:
        confirmed, unconfirmed_reason = True, None

    return SpatialQuantityState(
        quantity_id=quantity_id, zone_id=zone_id, frame_id=frame_id,
        value=value, accuracy_m=accuracy, decided_by=rule, tier=tier,
        contributing_kinds=tuple(sorted({r.evidence_kind for r in moving})),
        independent_support=independent,
        contributions=tuple(sorted(rows, key=lambda r: r.evidence_id)),
        rejected=tuple(rejected),
        without_human_value=sensor_value, without_human_accuracy_m=sensor_accuracy,
        entered_by=entered_by, entered_at=entered_at,
        accepted=tuple(observations), kinds=kinds,
        confirmed=confirmed, unconfirmed_reason=unconfirmed_reason,
    )


#: 등록되지 않은 종류가 `_fuse_quantity` 까지 흘러들어왔을 때의 안전한 기본.
#: 정상 경로에서는 `fuse_zone` 이 이미 거절하므로 여기에 닿지 않는다.
_FALLBACK_SPEC = EvidenceKindSpec("__unregistered__", TIER_ESTIMATED)


def fuse_zone(
    observations: Iterable[SpatialObservation],
    *,
    zone_id: str,
    frame_id: str | None = None,
    kinds: SpatialEvidenceKindRegistry = DEFAULT_KIND_REGISTRY,
    available_sources: set[str] | None = None,
    unavailable_sources: Sequence[str] = (),
) -> ZoneSpatialState:
    """구역 하나의 공간 상태를 만든다.

    `available_sources` 는 capability registry 에서 온다. 지금 쓸 수 없는 출처의
    관측은 **반대 근거가 아니라 없는 것**으로 다룬다(규칙 4, AI-C-05).
    `frame_id` 를 주지 않으면 받아들인 첫 관측의 프레임을 구역 프레임으로 삼고 다른
    프레임의 관측은 거절한다 — 변환 없이 섞으면 그 값은 아무 프레임의 값도 아니다.
    """
    accepted: dict[str, list[SpatialObservation]] = {}
    rejected: list[RejectedObservation] = []
    observed_kinds: set[str] = set()
    seen: set[str] = set()
    zone_frame = frame_id

    def reject(obs: SpatialObservation, reason: str, detail: str = "") -> None:
        rejected.append(RejectedObservation(obs.evidence_id, obs.evidence_kind,
                                            obs.quantity_id, reason, detail))

    # 결정적 순서로 본다 — 같은 입력에 같은 상태를 내야 leave-one-out 이 비교 가능하다.
    for obs in sorted(observations, key=lambda o: (o.observed_at, o.evidence_id)):
        if obs.evidence_id in seen:
            reject(obs, REJECT_DUPLICATE)
            continue
        seen.add(obs.evidence_id)

        spec = kinds.spec(obs.evidence_kind)
        if spec is None:
            reject(obs, REJECT_UNREGISTERED_KIND,
                   f"register an EvidenceKindSpec for {obs.evidence_kind!r} first")
            continue
        if available_sources is not None and obs.source_group not in available_sources:
            reject(obs, REJECT_SOURCE_UNAVAILABLE, obs.source_group)
            continue
        if not is_local_frame(obs.frame_id):
            reject(obs, REJECT_FRAME_MISMATCH,
                   f"{obs.frame_id!r} is a global frame; local frames only (AI-C-02)")
            continue
        if spec.needs_local_reduction and not obs.local_reduction_ref:
            reject(obs, REJECT_NOT_LOCAL,
                   f"{obs.evidence_kind!r} needs local_reduction_ref before it can "
                   "be fused into a site-local value")
            continue
        if spec.requires_author and not obs.entered_by:
            reject(obs, REJECT_MISSING_AUTHOR,
                   f"{obs.evidence_kind!r} needs entered_by")
            continue
        if zone_frame is None:
            zone_frame = obs.frame_id
        if obs.frame_id != zone_frame:
            reject(obs, REJECT_FRAME_MISMATCH,
                   f"{obs.frame_id!r} != zone frame {zone_frame!r}")
            continue
        bucket = accepted.setdefault(obs.quantity_id, [])
        if bucket and len(obs.value) != len(bucket[0].value):
            reject(obs, REJECT_ARITY_MISMATCH,
                   f"{len(obs.value)} components != {len(bucket[0].value)}")
            continue
        bucket.append(obs)
        observed_kinds.add(obs.evidence_kind)

    by_quantity = {qid: rows for qid, rows in sorted(accepted.items())}
    quantities = {
        qid: _fuse_quantity(
            qid, rows, zone_id=zone_id, frame_id=zone_frame or "",
            rejected=[r for r in rejected if r.quantity_id == qid], kinds=kinds)
        for qid, rows in by_quantity.items()
    }
    return ZoneSpatialState(
        zone_id=zone_id, frame_id=zone_frame or "",
        quantities=quantities,
        observed_kinds=tuple(sorted(observed_kinds)),
        unobserved_kinds=tuple(k for k in kinds.kinds() if k not in observed_kinds),
        rejected=tuple(rejected),
        unavailable_sources=tuple(sorted(set(unavailable_sources))),
    )


# --- 출처 수집 (없는 provider 는 아무것도 내지 않는다) -----------------------

ObservationSource = Callable[[], Iterable[SpatialObservation]]


def gather_observations(
    sources: Mapping[str, ObservationSource | None],
) -> tuple[tuple[SpatialObservation, ...], tuple[str, ...]]:
    """등록된 출처들을 돌며 관측을 모으고, 못 쓴 출처의 이름을 따로 낸다.

    provider 가 없으면(None) 또는 호출이 실패하면 **아무 값도 내지 않고** 그 이름만
    남는다 — 선택 기능 하나의 장애가 구역 공간 상태 전체를 멈추게 하지 않는다
    (AI-C-05). 실패를 예외로 올리지 않는 자리가 여기다.
    """
    collected: list[SpatialObservation] = []
    unavailable: list[str] = []
    for name, source in sorted(sources.items()):
        if source is None:
            unavailable.append(name)
            continue
        try:
            rows = list(source() or ())
        except Exception:                       # noqa: BLE001 - provider 장애 격리
            unavailable.append(name)
            continue
        if not rows:
            # 호출은 됐지만 낼 것이 없었다. 이것도 반대 근거가 아니다.
            continue
        collected.extend(rows)
    return tuple(collected), tuple(unavailable)


# --- 선언 프로파일·사람 실측 읽기 -------------------------------------------

def _epoch(value: object) -> float | None:
    """ISO8601 문자열이나 숫자를 epoch 초로. 읽을 수 없으면 None 으로 남긴다."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


def observations_from_domain_profile(
    profile: Mapping, zone_id: str, *, frame_id: str | None = None,
    source_group: str = "zone_profile",
) -> tuple[SpatialObservation, ...]:
    """프로파일에 **선언된** 고정 설치물·노드 자리를 근거로 옮긴다.

    프로파일은 정확도를 적지 않으므로 `accuracy_m` 는 보통 None 이다 — 그래서 선언은
    정확도를 선언한 근거가 하나라도 있으면 가중에서 보류된다. 선언을 실측처럼 쓰지
    않는 것이 AI-S-08 이 요구한 "사전정보와 실제 관측의 분리" 다.
    """
    for domain in profile.get("domains", ()):
        for zone in domain.get("zones", ()):
            if zone.get("zone_id") != zone_id:
                continue
            frame = frame_id or f"site:{domain['domain_id']}"
            rows: list[SpatialObservation] = []
            declared: Iterable[tuple[str, Mapping]] = (
                [(f"infrastructure.{item['id']}.at", item)
                 for item in zone.get("infrastructure", ()) if item.get("at")]
                + [(f"declared_node.{item['node_id']}.at", item)
                   for item in zone.get("declared_nodes", ()) if item.get("at")]
            )
            for quantity_id, item in declared:
                at = item["at"]
                rows.append(SpatialObservation(
                    evidence_id=f"declared:{zone_id}:{quantity_id}",
                    source_group=source_group,
                    # 프로파일 한 판이 하나의 원본이다 — 같은 선언 파일에서 뽑은 두
                    # 값은 서로 독립인 지지가 아니다.
                    frame_ref=f"zone_profile:{domain['domain_id']}",
                    observed_at=0.0,
                    evidence_kind=KIND_INFRASTRUCTURE_DECLARATION,
                    quantity_id=quantity_id,
                    value=(float(at["x"]), float(at["y"])),
                    frame_id=frame,
                    accuracy_m=None,
                    detail={"kind": item.get("kind", "declared_node"),
                            "verified": bool(zone.get("verified", False))},
                ))
            return tuple(rows)
    return ()


def load_survey_observations(
    path: str | Path, *, zone_id: str | None = None,
) -> tuple[SpatialObservation, ...]:
    """관제 웹에서 사람이 입력한 실측값 파일을 근거로 읽는다.

    파일이 없으면 빈 묶음이다 — 실측이 아직 없는 현장도 정상 배치다(규칙 4). 서명이
    없는 줄은 여기서 만들지 않고 `fuse_zone` 이 사유와 함께 거절하도록 그대로 넘긴다.
    """
    file = Path(path)
    if not file.exists():
        return ()
    body = json.loads(file.read_text(encoding="utf-8"))
    file_zone = body.get("zone_id", "")
    if zone_id is not None and file_zone != zone_id:
        return ()
    frame = body.get("coordinate_frame") or body.get("frame_id", "")
    rows: list[SpatialObservation] = []
    for entry in body.get("survey", ()):
        observed = _epoch(entry.get("observed_at")) or 0.0
        rows.append(SpatialObservation(
            evidence_id=entry["evidence_id"],
            source_group=entry.get("source_group", "ops_web.survey"),
            frame_ref=entry["frame_ref"],
            observed_at=observed,
            evidence_kind=entry.get("spatial_evidence_kind", KIND_HUMAN_SURVEY),
            quantity_id=entry["quantity_id"],
            value=tuple(float(v) for v in entry["value"]),
            frame_id=entry.get("coordinate_frame", frame),
            accuracy_m=entry.get("accuracy_m"),
            entered_by=entry.get("entered_by"),
            entered_at=_epoch(entry.get("entered_at")),
            detail={"note": entry.get("note", ""), "unit": entry.get("unit", "meter")},
        ))
    return tuple(rows)
