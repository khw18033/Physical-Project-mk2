"""Nothing is reflected until someone asks for it.

implements: AI-O-06 (통합 운영 상태 뷰), AI-C-13 (기능 선택·자원 최소화)
관련: AI-O-01 (관리 기능 자체의 비용도 재야 한다), AI-B-06, AI-C-05
tests: tests/test_refresh.py

## 왜 상시 갱신을 하지 않는가

모든 로봇과 모든 구역을 항상 실시간으로 반영하면, 아무도 보고 있지 않은 구역의
카메라·추론·전송까지 계속 돈다. 그 비용은 관측되지 않은 채 전체 자원을 깎고,
정작 임무가 들어왔을 때 쓸 여유가 없다 — AI-O-01 이 "관리 기능이 절감하는 자원보다
더 큰 비용을 유발하는지 평가할 수 있어야 한다"고 요구하는 것이 정확히 이 문제다.

그래서 반영은 **요청으로만** 일어난다. 요청의 출처는 셋뿐이다.

    operator_view    운영자가 그 구역·로봇을 열었다 — 1회성
    mission_assigned 임무를 부여했다 — 그 임무가 닿는 범위만
    subtask_demand   서브태스크가 그 정보를 요구한다 — 그 단계가 필요한 것만
    onboarding       새 장치가 조인했다 — 그 장치만

## 신선한 것과 **한 번도 받지 않은 것**을 구분한다

`as_of(scope)` 가 None 이면 한 번도 반영하지 않은 것이고, 오래된 것과 다른 상태다.
둘을 같은 칸에 담으면 화면이 "0 분 전"과 "모른다"를 같은 모양으로 그린다(AI-O-06:
한 번도 수신하지 않은 상태와 수신했으나 오래된 상태를 구분해야 한다).

## 같은 요청을 연달아 받으면 억제한다

운영자가 탭을 오가면 같은 구역 요청이 초 단위로 반복된다. 억제하지 않으면 화면
조작이 곧 부하가 된다. 억제는 **거절이 아니라 기록**이다 — 왜 건너뛰었는지와
직전 반영 시각을 함께 돌려주므로, 화면은 "방금 받은 값"이라고 정직하게 적을 수 있다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable


class Trigger(str, Enum):
    """반영을 일으킬 수 있는 것. 이 목록 밖의 이유로는 반영하지 않는다."""

    OPERATOR_VIEW = "operator_view"
    MISSION_ASSIGNED = "mission_assigned"
    SUBTASK_DEMAND = "subtask_demand"
    ONBOARDING = "onboarding"


class Freshness(str, Enum):
    NEVER = "never"      # 한 번도 반영하지 않았다
    FRESH = "fresh"
    STALE = "stale"


#: trigger 별 기본 억제 간격(초). **데이터다** — 현장 부하로 조정한다.
#: 임무 부여와 조인은 억제하지 않는다(0): 사람이 방금 지시한 것을 건너뛰면 지시가
#: 먹지 않은 것처럼 보인다.
DEFAULT_MIN_INTERVAL_S: dict[Trigger, float] = {
    Trigger.OPERATOR_VIEW: 3.0,
    Trigger.SUBTASK_DEMAND: 1.0,
    Trigger.MISSION_ASSIGNED: 0.0,
    Trigger.ONBOARDING: 0.0,
}

#: 이 시간이 지나면 오래된 것으로 본다. 화면이 "언제 기준"인지 적는 근거다.
DEFAULT_STALE_AFTER_S = 30.0


def scope_of(kind: str, identifier: str = "") -> str:
    """반영 범위 이름. `zone:N4-1F-W` 처럼 종류와 대상을 붙여 쓴다."""
    return f"{kind}:{identifier}" if identifier else kind


@dataclass(frozen=True)
class RefreshRecord:
    """실제로 반영이 일어난 1건."""

    scope: str
    trigger: Trigger
    at: float
    requested_by: str = ""
    #: 그 반영이 건드린 것들(장치·구역 id). 비용을 되짚는 근거다.
    items: tuple[str, ...] = ()
    #: 반영에 걸린 시간. 관리 기능 자체의 비용이므로 재서 남긴다(AI-O-01).
    duration_ms: float | None = None

    def as_dict(self) -> dict:
        body = {"scope": self.scope, "trigger": self.trigger.value, "at": self.at,
                "requested_by": self.requested_by, "items": list(self.items)}
        if self.duration_ms is not None:
            body["duration_ms"] = round(self.duration_ms, 3)
        return body


@dataclass(frozen=True)
class RefreshDecision:
    """요청 하나의 결과. 건너뛴 것도 실패가 아니라 결과다."""

    scope: str
    trigger: Trigger
    performed: bool
    reason: str
    as_of: float | None = None
    record: RefreshRecord | None = None

    def as_dict(self) -> dict:
        return {"scope": self.scope, "trigger": self.trigger.value,
                "performed": self.performed, "reason": self.reason,
                "as_of": self.as_of,
                "record": self.record.as_dict() if self.record else None}


#: 결정 사유 어휘.
REASON_PERFORMED = "performed"
REASON_SUPPRESSED = "suppressed_within_min_interval"
REASON_NO_WORK = "nothing_to_refresh"
REASON_FAILED = "refresh_failed"


@dataclass
class RefreshLedger:
    """무엇을 언제 왜 반영했는지. 상시 폴링을 대신하는 장부다."""

    min_interval_s: dict[Trigger, float] = field(
        default_factory=lambda: dict(DEFAULT_MIN_INTERVAL_S))
    stale_after_s: float = DEFAULT_STALE_AFTER_S
    clock: Callable[[], float] = time.time
    _last: dict[tuple[str, Trigger], float] = field(default_factory=dict, init=False)
    _as_of: dict[str, float] = field(default_factory=dict, init=False)
    _history: list[RefreshRecord] = field(default_factory=list, init=False)

    # -- 조회 -------------------------------------------------------------

    def as_of(self, scope: str) -> float | None:
        """그 범위를 마지막으로 반영한 시각. None 은 **한 번도 받지 않았다**."""
        return self._as_of.get(scope)

    def age_s(self, scope: str) -> float | None:
        at = self.as_of(scope)
        return None if at is None else max(0.0, self.clock() - at)

    def freshness(self, scope: str) -> Freshness:
        age = self.age_s(scope)
        if age is None:
            return Freshness.NEVER
        return Freshness.FRESH if age <= self.stale_after_s else Freshness.STALE

    def status(self, scopes: Iterable[str]) -> dict:
        """화면이 구역별로 '언제 기준'을 적는 데 쓰는 묶음."""
        return {
            scope: {"as_of": self.as_of(scope), "age_s": self.age_s(scope),
                    "freshness": self.freshness(scope).value}
            for scope in scopes
        }

    def history(self, *, limit: int = 50) -> tuple[RefreshRecord, ...]:
        return tuple(self._history[-limit:])

    # -- 요청 -------------------------------------------------------------

    def would_perform(self, scope: str, trigger: Trigger) -> bool:
        interval = self.min_interval_s.get(trigger, 0.0)
        if interval <= 0.0:
            return True
        last = self._last.get((scope, trigger))
        return last is None or (self.clock() - last) >= interval

    def request(
        self,
        scope: str,
        trigger: Trigger,
        *,
        requested_by: str = "",
        work: Callable[[], Iterable[str]] | None = None,
    ) -> RefreshDecision:
        """반영을 요청한다. 억제되면 `work` 는 **호출되지 않는다** — 억제의 요점이
        호출을 아끼는 것이므로, 돌려 놓고 버리면 아무것도 아끼지 못한다.
        """
        if not self.would_perform(scope, trigger):
            return RefreshDecision(scope, trigger, False, REASON_SUPPRESSED,
                                   as_of=self.as_of(scope))
        started = self.clock()
        items: tuple[str, ...] = ()
        if work is not None:
            try:
                items = tuple(work())
            except Exception as error:  # 반영 실패가 화면 전체를 멈추지 않는다(AI-C-05)
                return RefreshDecision(scope, trigger, False,
                                       f"{REASON_FAILED}:{type(error).__name__}",
                                       as_of=self.as_of(scope))
        at = self.clock()
        record = RefreshRecord(scope=scope, trigger=trigger, at=at,
                               requested_by=requested_by, items=items,
                               duration_ms=(at - started) * 1000.0)
        self._last[(scope, trigger)] = at
        self._as_of[scope] = at
        self._history.append(record)
        reason = REASON_PERFORMED if (work is None or items) else REASON_NO_WORK
        return RefreshDecision(scope, trigger, True, reason, as_of=at, record=record)

    def request_many(
        self,
        scopes: Iterable[str],
        trigger: Trigger,
        *,
        requested_by: str = "",
        work: Callable[[str], Iterable[str]] | None = None,
    ) -> tuple[RefreshDecision, ...]:
        """임무가 여러 구역에 걸칠 때. 구역마다 따로 판단하고 따로 기록한다."""
        return tuple(
            self.request(scope, trigger, requested_by=requested_by,
                         work=(lambda s=scope: work(s)) if work else None)
            for scope in scopes
        )
