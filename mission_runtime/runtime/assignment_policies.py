"""배정 정책 비교군 — **같은 조건에서 견주지 못하면 고른 근거가 없다.**

implements: AI-C-13 (기능 선택·자원 최소화 — 교체 가능한 선택 정책, 동일 조건 비교),
            AI-L-10 (하드웨어·임무 조건 기반 모델 배정), AI-B-06 (자원 상태 기반 재구성)
관련: AI-B-01 (미측정 구분), AI-O-01 (선택 로직 자체의 오버헤드), AI-C-19
tests: tests/test_assignment_policies.py

## 메우는 구멍

`runtime/model_assignment.py` 에 `AssignmentPolicy` 자리는 처음부터 있었지만
**비교군이 없었다.** AI-C-13 은 "후보 방법은 동일 조건에서 판단 품질·자원·지연·
실패 안정성과 **선택 로직 자체의 오버헤드**를 포함해 비교할 수 있어야 한다" 고
적는데, 비교할 상대가 없으면 그 문장은 지킬 수 없다.

여기 넷은 외부 캡스톤 설계서(2026-11-20)가 제안한 비교군을 우리 자료형으로 옮긴
것이다. 이름을 빌린 것이지 그 설계의 구현을 재현했다는 뜻이 아니다.

| 정책 | 뜻 | 쓰임 |
|---|---|---|
| `StaticAssignment` | 미리 지정한 버전만 | **기본 비교군** — 동적 선택이 이것보다 나은지 |
| `FirstFeasible` | 조건을 만족한 첫 후보 | 단순 동적 비교군 |
| `ResourceAware` | 가중 비용으로 비교 | 실제 후보군 |
| `AdaptivePolicy` | 실패·열화를 겪으면 재평가 | 운영 후보군 |

## 두 가지를 섞지 않는다

**필수 제약은 점수가 아니다.** 권한·검증 범위·기한·안전은 점수에 가중치로 넣는
순간 "조금 위험하지만 아주 빠른" 후보가 이긴다. 그래서 적격 판정(`ModelAssigner`)
이 먼저 거르고, 정책은 **이미 적격인 것들 중에서만** 고른다. 이 파일에 적격 판정이
없는 것이 그 경계다.

## 갈리지 않으면 고르지 않는다

점수가 같으면 1 위를 집지 않고 `None` 과 사유를 낸다. 동점을 임의로 깨면 "왜 이걸
골랐나" 에 답할 수 없고, 그 답이 없는 선택은 운영자가 신뢰할 수 없다(AI-S-03 과
같은 규칙).

## 되돌아갈 때 흔들리지 않는다

`AdaptivePolicy` 는 열화를 겪으면 내려가지만, 올라올 때는 **연속으로 좋아야**
올라온다(히스테리시스). 한 번 좋아졌다고 바로 올리면 경계에서 배정이 진동하고,
진동하는 배정은 그 자체로 장애다(AI-B-06: "순간 변동으로 불필요한 실행 전환이
반복되지 않도록").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from mission_runtime.runtime.model_assignment import (
    AssignmentPolicy,
    MissionRequirement,
    ModelVersion,
)

#: 고르지 못한 사유 토큰. 문구가 아니라 토큰이다 — 화면이 이걸로 분기한다.
REASON_NO_ELIGIBLE = "no_eligible_candidate"
REASON_TIE = "tie_not_broken"
REASON_PINNED_ABSENT = "pinned_version_not_eligible"
REASON_ALL_DEGRADED = "every_candidate_degraded"


@dataclass(frozen=True)
class Choice:
    """정책의 답. **고르지 못한 것도 답이다.**"""

    version: ModelVersion | None
    reason: str
    considered: int = 0
    scores: tuple[tuple[str, float], ...] = ()

    @property
    def chose(self) -> bool:
        return self.version is not None


@dataclass
class StaticAssignment:
    """미리 지정한 버전만 쓴다. **기본 비교군이다.**

    동적 선택이 이것보다 나은지를 말하려면 이것이 있어야 한다. 지정한 버전이
    적격 목록에 없으면 다른 것으로 바꾸지 않는다 — 그게 "static" 의 뜻이다.
    """

    pinned: dict[str, str] = field(default_factory=dict)   # capability_kind → reference
    name: str = "static"

    def choose(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> ModelVersion | None:
        return self.decide(eligible, requirement).version

    def decide(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> Choice:
        wanted = self.pinned.get(requirement.capability_kind)
        if wanted is None:
            return Choice(None, REASON_PINNED_ABSENT, len(eligible))
        for version in eligible:
            if version.reference == wanted:
                return Choice(version, "pinned", len(eligible))
        return Choice(None, REASON_PINNED_ABSENT, len(eligible))


@dataclass
class FirstFeasible:
    """조건을 만족한 **첫** 후보. 단순 동적 비교군이다.

    순서에 기대므로 입력 순서가 바뀌면 답이 바뀐다 — 그 성질 자체가 비교 대상이다.
    같은 입력에는 같은 답을 내도록 등록 순서를 그대로 쓴다.
    """

    name: str = "first_feasible"

    def choose(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> ModelVersion | None:
        return self.decide(eligible, requirement).version

    def decide(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> Choice:
        if not eligible:
            return Choice(None, REASON_NO_ELIGIBLE, 0)
        return Choice(eligible[0], "first_feasible", len(eligible))


@dataclass
class ResourceAware:
    """가중 비용으로 견준다. **미측정은 점수를 만들지 않는다.**

    `score = wq*quality − wl*latency_norm − wm*memory_norm` 이고 각 항은 후보군
    안에서 정규화한다. 가중치는 **설정**이고 코드가 아니다(AI-C-13: 고정 가중치를
    요구사항으로 두지 않는다).

    미측정 항목이 있는 후보는 점수를 못 만들므로 **고르지 않는다**. 0 으로 채우면
    "아주 빠른 후보" 가 되어 이기고, 그건 측정하지 않은 것이 이기는 것이다.
    """

    quality_weight: float = 1.0
    latency_weight: float = 0.5
    memory_weight: float = 0.2
    #: 점수 차가 이보다 작으면 **갈리지 않았다**고 본다.
    tie_epsilon: float = 1e-6
    name: str = "resource_aware"

    def choose(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> ModelVersion | None:
        return self.decide(eligible, requirement).version

    def decide(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> Choice:
        scorable = [v for v in eligible if v.fully_measured]
        if not scorable:
            return Choice(None, REASON_NO_ELIGIBLE, len(eligible))

        latencies = [v.latency_ms for v in scorable]
        memories = [v.memory_mb for v in scorable]
        scored: list[tuple[ModelVersion, float]] = []
        for version in scorable:
            score = (self.quality_weight * (version.quality or 0.0)
                     - self.latency_weight * _normalise(version.latency_ms, latencies)
                     - self.memory_weight * _normalise(version.memory_mb, memories))
            scored.append((version, score))

        scored.sort(key=lambda row: (-row[1], row[0].reference))
        table = tuple((v.reference, round(s, 6)) for v, s in scored)
        if len(scored) > 1 and abs(scored[0][1] - scored[1][1]) < self.tie_epsilon:
            # **갈리지 않으면 고르지 않는다** — 임의로 깨면 근거를 못 댄다
            return Choice(None, REASON_TIE, len(eligible), table)
        return Choice(scored[0][0], "best_weighted_score", len(eligible), table)


@dataclass
class AdaptivePolicy:
    """실패·열화를 겪으면 **한 단계 내려가고**, 올라올 때는 연속으로 좋아야 한다.

    내려가는 것은 즉시다 — 안전과 가용이 먼저다. 올라오는 것은 느리다 — 경계에서
    진동하면 배정이 계속 바뀌고 그 자체가 장애다(AI-B-06).

    상태를 들고 있으므로 **정책마다 한 개**를 쓴다. 비교 실험에서는 매번 새로
    만들어 이전 실행의 기억이 다음 실행에 새지 않게 한다.
    """

    base: object = field(default_factory=ResourceAware)
    #: 올라오기까지 필요한 연속 성공 횟수.
    recover_after: int = 3
    name: str = "adaptive"
    _degraded: dict[str, bool] = field(default_factory=dict, repr=False)
    _streak: dict[str, int] = field(default_factory=dict, repr=False)

    def observe(self, capability_kind: str, *, ok: bool) -> None:
        """실행 결과를 알려 준다. **정책은 결과를 스스로 알지 못한다.**"""
        if not ok:
            self._degraded[capability_kind] = True
            self._streak[capability_kind] = 0
            return
        self._streak[capability_kind] = self._streak.get(capability_kind, 0) + 1
        if self._streak[capability_kind] >= self.recover_after:
            self._degraded[capability_kind] = False

    def is_degraded(self, capability_kind: str) -> bool:
        return bool(self._degraded.get(capability_kind))

    def choose(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> ModelVersion | None:
        return self.decide(eligible, requirement).version

    def decide(self, eligible: Sequence[ModelVersion],
               requirement: MissionRequirement) -> Choice:
        if not self.is_degraded(requirement.capability_kind):
            return self.base.decide(eligible, requirement)      # type: ignore[attr-defined]

        # 열화 상태 — **싸고 가벼운 쪽**으로 내려간다. 품질은 그 다음이다.
        measured = [v for v in eligible if v.latency_ms is not None]
        if not measured:
            return Choice(None, REASON_ALL_DEGRADED, len(eligible))
        measured.sort(key=lambda v: (v.latency_ms, v.reference))
        return Choice(measured[0], "degraded_cheapest", len(eligible))


def _normalise(value: float | None, pool: Sequence[float | None]) -> float:
    """후보군 안에서 0~1 로. 모두 같으면 0 이다 — 차이가 없으면 벌점도 없다."""
    numbers = [n for n in pool if n is not None]
    if value is None or not numbers:
        return 0.0
    low, high = min(numbers), max(numbers)
    if high - low < 1e-12:
        return 0.0
    return (value - low) / (high - low)


# ----------------------------------------------------------------- 비교

@dataclass(frozen=True)
class PolicyRun:
    """한 정책이 한 추적(trace)을 돈 결과."""

    policy: str
    decided: int
    chose: int
    refused: int
    refusal_reasons: tuple[str, ...]
    chosen_references: tuple[str, ...]

    @property
    def decisiveness(self) -> float:
        """고른 비율. **높다고 좋은 게 아니다** — 아무거나 고르면 1.0 이다."""
        return self.chose / self.decided if self.decided else 0.0


def compare_policies(policies: Sequence[object],
                     trace: Sequence[tuple[Sequence[ModelVersion], MissionRequirement]],
                     ) -> tuple[PolicyRun, ...]:
    """**같은 추적**을 여러 정책에 그대로 먹인다(AI-C-13 의 "동일 조건").

    입력이 같아야 비교가 성립하므로 후보 목록도 요구조건도 정책이 바꾸지 못한다.
    결과는 순위를 매기지 않는다 — 어느 축이 중요한지는 배치가 정한다.
    """
    runs: list[PolicyRun] = []
    for policy in policies:
        chose: list[str] = []
        reasons: list[str] = []
        for eligible, requirement in trace:
            decision = policy.decide(list(eligible), requirement)   # type: ignore[attr-defined]
            if decision.chose:
                chose.append(decision.version.reference)
            else:
                reasons.append(decision.reason)
        runs.append(PolicyRun(
            policy=getattr(policy, "name", type(policy).__name__),
            decided=len(trace),
            chose=len(chose),
            refused=len(reasons),
            refusal_reasons=tuple(sorted(set(reasons))),
            chosen_references=tuple(chose)))
    return tuple(runs)


__all__ = [
    "AdaptivePolicy", "AssignmentPolicy", "Choice", "FirstFeasible", "PolicyRun",
    "REASON_ALL_DEGRADED", "REASON_NO_ELIGIBLE", "REASON_PINNED_ABSENT", "REASON_TIE",
    "ResourceAware", "StaticAssignment", "compare_policies",
]
