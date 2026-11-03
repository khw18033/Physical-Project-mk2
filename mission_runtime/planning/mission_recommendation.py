"""Proposes missions that the current situation makes worth doing — and only proposes.

implements: AI-B-15 (상황 기반 임무 추천)
관련: AI-S-04 (미확인 객체), AI-S-05 (추가 정보 요청), AI-B-13 (외부 요청),
      AI-C-05 (후보가 없으면 축소), AI-C-19 (AI 는 임무를 발령하지 않는다), AI-L-06

운영자가 화면을 보며 "그래서 지금 무엇을 하면 되나"를 묻는다. 그 답의 재료는 이미
우리 쪽에 다 있다 — 쓸 수 있는 capability, 유휴 가속기, 풀리지 않은 미확인 객체,
위험 상태, 대기 중인 외부 요청. 흩어져 있어서 답이 되지 않을 뿐이다.

## 추천은 발령이 아니다

이 모듈은 **후보와 사유만** 낸다. 임무를 띄우는 것은 사람의 승인을 거쳐 백엔드가
하는 일이다(AI-C-19). 그래서 여기에는 실행·명령·발행에 해당하는 함수가 하나도 없고,
시험이 그것을 고정한다. 자동 실행을 붙이고 싶다는 요구가 오면 그것은 요구사항 변경이지
이 모듈의 확장이 아니다.

## 못 하는 것도 같이 보여 준다

조건을 만족하는 후보만 보여 주면 "왜 그 임무는 못 하나"에 답할 수 없다. 그래서 막힌
후보도 **무엇이 없어서 막혔는지**와 함께 낸다 — 그 목록이 곧 다음에 붙일 기능의
우선순위이고, 외부 개발 요청(AI-B-13)의 재료다.

## 근거 없는 추천을 하지 않는다

임무 후보는 **촉발 근거가 있을 때만** 올라온다. 미확인 객체가 없으면 "재관측" 임무를
권하지 않는다. 상시 추천은 화면을 채우지만 운영자의 신뢰를 깎는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

#: 촉발 근거 토큰. 왜 이 임무가 지금 올라왔는지를 말한다. 표시 문구는 화면이 만든다.
TRIGGER_UNRESOLVED_UNKNOWN = "unresolved_unknown_objects"
TRIGGER_IDLE_ACCELERATOR = "idle_accelerator_available"
TRIGGER_RISK_ELEVATED = "risk_state_elevated"
TRIGGER_DEPLOYMENT_PENDING = "external_deployment_pending"
TRIGGER_STALE_CALIBRATION = "calibration_stale"
TRIGGER_ALWAYS = "always_applicable"

TRIGGERS: tuple[str, ...] = (
    TRIGGER_UNRESOLVED_UNKNOWN, TRIGGER_IDLE_ACCELERATOR, TRIGGER_RISK_ELEVATED,
    TRIGGER_DEPLOYMENT_PENDING, TRIGGER_STALE_CALIBRATION, TRIGGER_ALWAYS,
)

#: 후보가 막힌 사유.
BLOCKED_MISSING_CAPABILITY = "missing_required_capability"
BLOCKED_NO_TRIGGER = "no_triggering_evidence"
RECOMMENDED = "recommended"


@dataclass(frozen=True)
class SituationSnapshot:
    """지금 상황. 전부 **다른 모듈이 이미 내는 값**이고 여기서 새로 재지 않는다.

    `risk_level` 은 위험 분석이 낸 값을 그대로 받는다 — 우리가 다시 판정하면 같은
    사실에 두 주인이 생긴다.
    """

    available_capabilities: frozenset[str] = frozenset()
    #: 배치된 서비스가 없는 가속기 개체. 유휴가 있으면 추가 분석을 권할 근거가 된다.
    idle_accelerators: tuple[str, ...] = ()
    #: 아직 의미가 확정되지 않은 지속 객체(AI-S-04).
    unresolved_unknown_object_ids: tuple[str, ...] = ()
    #: 위험 분석이 낸 상태 문자열. 없으면 위험 분석이 비활성인 배치다.
    risk_level: str | None = None
    #: 배포를 기다리는 외부 요청 식별자(AI-B-13).
    pending_external_request_ids: tuple[str, ...] = ()
    #: 보정이 오래된 카메라(AI-E-02).
    stale_calibration_camera_ids: tuple[str, ...] = ()

    def triggers(self, *, elevated_risk_levels: frozenset[str] = frozenset({"watch", "alert"})
                 ) -> frozenset[str]:
        """지금 성립하는 촉발 근거. 상시 근거는 항상 들어간다."""
        found = {TRIGGER_ALWAYS}
        if self.unresolved_unknown_object_ids:
            found.add(TRIGGER_UNRESOLVED_UNKNOWN)
        if self.idle_accelerators:
            found.add(TRIGGER_IDLE_ACCELERATOR)
        if self.risk_level in elevated_risk_levels:
            found.add(TRIGGER_RISK_ELEVATED)
        if self.pending_external_request_ids:
            found.add(TRIGGER_DEPLOYMENT_PENDING)
        if self.stale_calibration_camera_ids:
            found.add(TRIGGER_STALE_CALIBRATION)
        return frozenset(found)


@dataclass(frozen=True)
class MissionTemplate:
    """추천할 수 있는 임무 하나. **데이터다** — 새 임무는 코드 변경이 아니다.

    `goal_kind` 는 `planning/decomposition.py` 의 템플릿 키와 같은 어휘다. 추천이
    승인되면 그 키로 분해가 이어진다 — 추천과 실행 계획이 다른 어휘를 쓰면 승인된
    임무를 다시 해석해야 한다.
    """

    mission_kind: str
    title: str
    goal_kind: str
    required_capabilities: frozenset[str] = frozenset()
    #: 이 중 하나라도 성립하면 올라온다. 비어 있으면 상시 후보다.
    triggers: frozenset[str] = frozenset({TRIGGER_ALWAYS})
    #: 낮을수록 먼저. 같은 값이면 mission_kind 사전순으로 결정적이다.
    priority: int = 100

    def __post_init__(self) -> None:
        if not self.mission_kind or not self.goal_kind:
            raise ValueError("mission_kind and goal_kind must not be empty")
        unknown = self.triggers - set(TRIGGERS)
        if unknown:
            raise ValueError(f"unknown trigger tokens: {sorted(unknown)}")


@dataclass(frozen=True)
class MissionCandidate:
    """후보 하나와 그 판단 근거. 실행 수단을 들고 있지 않다."""

    mission_kind: str
    title: str
    goal_kind: str
    recommended: bool
    reason: str
    matched_triggers: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()
    #: 이 후보가 가리키는 대상(미확인 객체 id 등). 운영자가 무엇에 대한 임무인지 안다.
    subjects: tuple[str, ...] = ()
    priority: int = 100


class RecommendationPolicy(Protocol):
    """후보 정렬 정책. 교체 가능하다(AI-C-13)."""

    def order(self, candidates: Sequence[MissionCandidate]) -> list[MissionCandidate]: ...


class PriorityThenKind:
    """우선순위 → 종류 사전순. 같은 입력에 같은 순서가 나와야 화면이 흔들리지 않는다."""

    def order(self, candidates: Sequence[MissionCandidate]) -> list[MissionCandidate]:
        return sorted(candidates, key=lambda c: (not c.recommended, c.priority, c.mission_kind))


@dataclass
class MissionRecommender:
    """선언된 임무 목록을 상황에 비춰 후보로 만든다. 발령하지 않는다."""

    templates: tuple[MissionTemplate, ...] = ()
    policy: RecommendationPolicy = field(default_factory=PriorityThenKind)

    def register(self, template: MissionTemplate) -> None:
        self.templates = tuple(
            t for t in self.templates if t.mission_kind != template.mission_kind
        ) + (template,)

    def recommend(self, situation: SituationSnapshot) -> tuple[MissionCandidate, ...]:
        active = situation.triggers()
        candidates = [self._judge(template, situation, active) for template in self.templates]
        return tuple(self.policy.order(candidates))

    def recommended_only(self, situation: SituationSnapshot) -> tuple[MissionCandidate, ...]:
        return tuple(c for c in self.recommend(situation) if c.recommended)

    def _judge(
        self, template: MissionTemplate, situation: SituationSnapshot, active: frozenset[str]
    ) -> MissionCandidate:
        matched = tuple(sorted(template.triggers & active))
        missing = tuple(sorted(template.required_capabilities - situation.available_capabilities))
        subjects = self._subjects(template, situation)

        if not matched:
            return MissionCandidate(
                template.mission_kind, template.title, template.goal_kind,
                False, BLOCKED_NO_TRIGGER, (), missing, subjects, template.priority,
            )
        if missing:
            # 근거는 있는데 기능이 없다. 이 목록이 다음에 붙일 기능의 우선순위다.
            return MissionCandidate(
                template.mission_kind, template.title, template.goal_kind,
                False, BLOCKED_MISSING_CAPABILITY, matched, missing, subjects,
                template.priority,
            )
        return MissionCandidate(
            template.mission_kind, template.title, template.goal_kind,
            True, RECOMMENDED, matched, (), subjects, template.priority,
        )

    @staticmethod
    def _subjects(template: MissionTemplate, situation: SituationSnapshot) -> tuple[str, ...]:
        """이 임무가 가리키는 대상. 촉발 근거에서 끌어온다 — 지어내지 않는다."""
        if TRIGGER_UNRESOLVED_UNKNOWN in template.triggers:
            return situation.unresolved_unknown_object_ids
        if TRIGGER_STALE_CALIBRATION in template.triggers:
            return situation.stale_calibration_camera_ids
        if TRIGGER_DEPLOYMENT_PENDING in template.triggers:
            return situation.pending_external_request_ids
        return ()
