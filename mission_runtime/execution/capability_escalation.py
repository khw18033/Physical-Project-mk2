"""Stages 1-2 of the external capability request: judge that the work cannot be
done here, and turn that judgement into a request — including sim/real mismatch.

implements: AI-B-13 (수행 불가 기능의 외부 개발 요청)
관련: AI-C-05 (필수 조건 미충족 시 그 기능만 비활성), AI-S-05 (부족 근거를 남긴다),
      AI-C-10 (등록된 기능으로 탐색), AI-C-19 (발급·제어 경계), AI-B-01 (검증 범위)

`external_request.py` 가 3~6단계(외부 처리·배포·재실행·판정)를 들고 있고, 여기는
그 앞의 두 단계다 — **왜 못 하는가**와 **무엇을 요청하는가**.

두 가지 판정을 한 모듈에 둔 이유
--------------------------------
요구사항이 요청 발생 조건을 둘로 정했다(기능 미탑재 / 시뮬–실물 불일치). 둘은 발생
시점이 다르지만(도출·실행 시도 시 vs 실행 후 판정 시) 산출물이 같다 — "이 작업은
여기서 안 된다"는 근거가 붙은 요청 1건. 산출물이 같으니 조립도 한 곳에서 한다.

판정은 등록된 기능으로만 한다
-----------------------------
1단계는 `CapabilityRegistry` 에 **지금 등록된 것**으로 판정한다. 모델 이름이나 장치
이름으로 분기하지 않으므로 새 provider 를 등록하면 같은 작업이 판정만으로 수행 가능
상태가 된다(AI-C-10). 선택 기능이 없어 축소된 것과 필수 기능이 없어 못 하는 것을
구분한다 — 전자는 요청 사유가 아니다(AI-C-05).

없는 것을 지어내지 않는다
-------------------------
시뮬–실물 비교는 **같은 기준으로 비교할 수 있을 때만** 판정한다. 한쪽이 없거나 단위가
다르면 `NOT_COMPARABLE` 이고 이것은 불일치가 아니다. 비교 가능하지 않은 것을 불일치로
세면 요청이 쌓이고, 일치로 세면 실물 실패가 묻힌다.

발급 경계
---------
요청 식별자는 백엔드가 발급한다(AI-C-19). 그래서 발급을 `RequestIdIssuer` 포트로
두고 백엔드 구현을 주입받는다. `LocalSequentialIssuer` 는 백엔드가 아직 없을 때를
위한 **대역**이며 그 사실을 이름과 docstring 에 남긴다 — `simulation/backend.py` 가
가용성 판정 대역을 두는 것과 같은 방식이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState
from mission_runtime.contracts.profile import ResourceBudget
from mission_runtime.execution.external_request import (
    ExternalRequest,
    RequestReason,
    RequestStage,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry
from mission_runtime.selection.selector import CapabilitySelector

#: 판정 사유 토큰. 표시 문구는 화면이 만든다(언어 중립).
REASON_REQUIRED_KIND_UNREGISTERED = "required_capability_kind_unregistered"
REASON_REQUIRED_KIND_NO_CANDIDATE = "required_capability_no_candidate_within_budget"
REASON_SIM_REAL_DIVERGED = "sim_real_outcome_diverged"

ESCALATION_REASONS: tuple[str, ...] = (
    REASON_REQUIRED_KIND_UNREGISTERED,
    REASON_REQUIRED_KIND_NO_CANDIDATE,
    REASON_SIM_REAL_DIVERGED,
)


class Comparability(str, Enum):
    """시뮬·실물 비교 결과. 세 값이며 둘로 줄이지 않는다."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_COMPARABLE = "NOT_COMPARABLE"


@dataclass(frozen=True)
class CapabilityNeed:
    """한 작업이 요구하는 기능. 필수와 선택을 구분해 선언한다."""

    task_node_id: str
    required_kinds: tuple[str, ...]
    optional_kinds: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnsupportedFinding:
    """1단계 판정 결과 — 왜 여기서 못 하는가.

    `missing_required` 가 비어 있으면 수행 가능하다(선택 기능 결손은 축소이지
    요청 사유가 아니다, AI-C-05). `degraded_optional` 은 그 축소 사실의 기록이다.
    """

    task_node_id: str
    missing_required: tuple[str, ...] = ()
    degraded_optional: tuple[str, ...] = ()
    reason_token: str | None = None
    judged_at: float | None = None

    @property
    def unsupported(self) -> bool:
        return bool(self.missing_required)


@dataclass(frozen=True)
class OutcomeSample:
    """비교할 한쪽의 결과. 지표 이름과 단위를 함께 들고 다닌다."""

    metric: str
    unit: str
    value: float | None

    @property
    def measured(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class MismatchFinding:
    """시뮬–실물 비교 결과."""

    task_node_id: str
    comparability: Comparability
    expected: OutcomeSample | None = None
    actual: OutcomeSample | None = None
    divergence: float | None = None
    reason_token: str | None = None
    judged_at: float | None = None
    #: 비교할 수 없었던 이유. NOT_COMPARABLE 일 때만 채운다.
    not_comparable_because: str | None = None

    @property
    def unsupported(self) -> bool:
        return self.comparability is Comparability.MISMATCH


class RequestIdIssuer(Protocol):
    """요청 식별자 발급 포트. 실제 발급 주체는 백엔드다(AI-C-19)."""

    def issue(self, *, task_node_id: str, reason: RequestReason) -> str: ...


class LocalSequentialIssuer:
    """백엔드가 없을 때의 **대역**. 운영 발급기가 아니다.

    실제 배포에서는 백엔드 발급기를 주입한다. 이 구현을 쓰는 동안 만들어진 식별자는
    다른 노드가 만든 것과 충돌할 수 있으므로 `prefix` 로 출처를 남긴다.
    """

    def __init__(self, *, prefix: str = "local") -> None:
        self._prefix = prefix
        self._next = 1

    def issue(self, *, task_node_id: str, reason: RequestReason) -> str:
        del task_node_id, reason
        value = f"{self._prefix}-req-{self._next:04d}"
        self._next += 1
        return value


class RequestSink(Protocol):
    """요청을 밖으로 내보내는 경계. 어떤 경로인지는 provider 의 몫이다(AI-C-04)."""

    def send(self, request: ExternalRequest) -> None: ...


class CollectingSink:
    """시험·검토용 sink. 보낸 것을 모아 둔다."""

    def __init__(self) -> None:
        self.sent: list[ExternalRequest] = []

    def send(self, request: ExternalRequest) -> None:
        self.sent.append(request)


# -- 1단계: 수행 가능성 판정 -------------------------------------------------


class OnDeviceFeasibilityJudge:
    """지금 등록된 기능으로 그 작업을 할 수 있는지 판정한다.

    판정 결과를 **입력으로 소비**할 뿐 장치의 최종 가용성을 재판정하지 않는다
    (절대 준수 원칙 #15). 여기서 보는 것은 "이 기능 종류를 제공하는 provider 가
    지금 있는가"이고 장치가 살아 있는지는 백엔드가 판정한 결과를 registry 가 이미
    반영했다고 본다.
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry
        self._selector = CapabilitySelector(registry)

    def judge(
        self,
        need: CapabilityNeed,
        *,
        node_tags: set[str] | None = None,
        budget: ResourceBudget | None = None,
        at: float | None = None,
    ) -> UnsupportedFinding:
        tags = node_tags or set()
        missing: list[str] = []
        unregistered: list[str] = []
        for kind in need.required_kinds:
            result = self._selector.select(kind, tags, budget) if budget is not None else None
            if result is not None and result.provider is not None:
                continue
            if not self._registry.available_providers(kind):
                unregistered.append(kind)
                missing.append(kind)
            elif budget is not None:
                missing.append(kind)
            # budget 이 없으면 등록 여부까지만 본다 — 예산 없이 "예산 초과"를
            # 판정할 수는 없다.
        degraded: list[str] = []
        for kind in need.optional_kinds:
            if not self._registry.available_providers(kind):
                degraded.append(kind)

        reason = None
        if missing:
            reason = (REASON_REQUIRED_KIND_UNREGISTERED if unregistered
                      else REASON_REQUIRED_KIND_NO_CANDIDATE)
        return UnsupportedFinding(
            task_node_id=need.task_node_id,
            missing_required=tuple(missing),
            degraded_optional=tuple(degraded),
            reason_token=reason,
            judged_at=at,
        )

    def capability_state(self, need: CapabilityNeed) -> CapabilityState:
        """같은 선언을 기존 축소 규칙으로도 환산해 준다.

        선택 결손이 DEGRADED 까지만 내려가고 DISABLED 가 되지 않는다는 규칙을
        여기서 다시 구현하지 않는다(AI-C-05 는 `CapabilityRequirement` 가 소유).
        """
        available = {
            kind for kind in need.required_kinds + need.optional_kinds
            if self._registry.available_providers(kind)
        }
        return CapabilityRequirement(
            required=need.required_kinds,
            optional=need.optional_kinds,
        ).evaluate(available)


# -- 1단계(실행 후): 시뮬–실물 불일치 판정 -----------------------------------


class OutcomeComparator(Protocol):
    """교체 가능한 비교 정책. 무엇을 불일치로 볼지는 배포가 정한다."""

    def compare(self, expected: OutcomeSample, actual: OutcomeSample) -> tuple[bool, float]:
        """(일치인가, 벌어진 정도)."""
        ...


class RelativeToleranceComparator:
    """상대 오차 기준 비교. 기본 정책이며 유일한 정책은 아니다."""

    def __init__(self, *, tolerance: float = 0.1) -> None:
        if tolerance < 0:
            raise ValueError("tolerance must not be negative")
        self._tolerance = tolerance

    def compare(self, expected: OutcomeSample, actual: OutcomeSample) -> tuple[bool, float]:
        assert expected.value is not None and actual.value is not None
        scale = abs(expected.value) if expected.value else 1.0
        divergence = abs(actual.value - expected.value) / scale
        return (divergence <= self._tolerance, divergence)


class SimRealMismatchJudge:
    """시뮬레이션에서 가능하다고 본 것이 실물에서 어긋났는지 판정한다."""

    def __init__(self, comparator: OutcomeComparator | None = None) -> None:
        self._comparator = comparator or RelativeToleranceComparator()

    def judge(
        self,
        task_node_id: str,
        expected: OutcomeSample | None,
        actual: OutcomeSample | None,
        *,
        at: float | None = None,
    ) -> MismatchFinding:
        def not_comparable(why: str) -> MismatchFinding:
            return MismatchFinding(
                task_node_id=task_node_id,
                comparability=Comparability.NOT_COMPARABLE,
                expected=expected,
                actual=actual,
                judged_at=at,
                not_comparable_because=why,
            )

        if expected is None or actual is None:
            return not_comparable("one side is absent")
        if not expected.measured or not actual.measured:
            return not_comparable("one side was not measured")
        if expected.metric != actual.metric:
            return not_comparable(f"different metrics: {expected.metric} vs {actual.metric}")
        if expected.unit != actual.unit:
            return not_comparable(f"different units: {expected.unit} vs {actual.unit}")

        matched, divergence = self._comparator.compare(expected, actual)
        return MismatchFinding(
            task_node_id=task_node_id,
            comparability=Comparability.MATCH if matched else Comparability.MISMATCH,
            expected=expected,
            actual=actual,
            divergence=divergence,
            reason_token=None if matched else REASON_SIM_REAL_DIVERGED,
            judged_at=at,
        )


# -- 2단계: 요청 조립과 발신 -------------------------------------------------


class EscalationRejected(Exception):
    """수행 가능한 작업이나 비교 불가 판정으로는 요청을 만들지 않는다."""


@dataclass(frozen=True)
class EscalationRequester:
    """판정 → 요청 조립 → 발신. 식별자 발급과 전송은 주입받은 경계로 나간다."""

    issuer: RequestIdIssuer
    sink: RequestSink | None = None

    def from_unsupported(
        self, finding: UnsupportedFinding, *, at: float | None = None
    ) -> ExternalRequest:
        if not finding.unsupported:
            raise EscalationRejected(
                f"{finding.task_node_id}: nothing is missing, there is nothing to request"
            )
        detail = (
            f"{finding.reason_token}: " + ", ".join(finding.missing_required)
        )
        return self._build(
            task_node_id=finding.task_node_id,
            reason=RequestReason.UNSUPPORTED_CAPABILITY,
            detail=detail,
            judged_at=finding.judged_at,
            at=at,
        )

    def from_mismatch(
        self, finding: MismatchFinding, *, at: float | None = None
    ) -> ExternalRequest:
        if finding.comparability is Comparability.NOT_COMPARABLE:
            raise EscalationRejected(
                f"{finding.task_node_id}: not comparable "
                f"({finding.not_comparable_because}) — this is not a mismatch"
            )
        if not finding.unsupported:
            raise EscalationRejected(
                f"{finding.task_node_id}: simulation and reality agree"
            )
        assert finding.expected is not None and finding.actual is not None
        detail = (
            f"{REASON_SIM_REAL_DIVERGED}: {finding.expected.metric} "
            f"expected={finding.expected.value}{finding.expected.unit} "
            f"actual={finding.actual.value}{finding.actual.unit} "
            f"divergence={finding.divergence:.4f}"
        )
        return self._build(
            task_node_id=finding.task_node_id,
            reason=RequestReason.SIM_REAL_MISMATCH,
            detail=detail,
            judged_at=finding.judged_at,
            at=at,
        )

    def _build(
        self,
        *,
        task_node_id: str,
        reason: RequestReason,
        detail: str,
        judged_at: float | None,
        at: float | None,
    ) -> ExternalRequest:
        request_id = self.issuer.issue(task_node_id=task_node_id, reason=reason)
        if not request_id:
            raise EscalationRejected("the issuer returned an empty request id")
        request = ExternalRequest(
            request_id=request_id,
            reason=reason,
            reason_detail=detail,
            origin_node_id=task_node_id,
        )
        # 1단계(판정)와 2단계(전송)를 각각 기록한다 — 둘의 시각이 다르다.
        request = request.advance(RequestStage.JUDGED, at=judged_at)
        request = request.advance(RequestStage.SENT, at=at)
        if self.sink is not None:
            self.sink.send(request)
        return request
