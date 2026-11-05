"""Turns Layer 1 measurements into warnings and into the resource-condition axis.

implements: AI-O-05 (계층별 자원·서비스 지표 관측), AI-O-02 (오류·이상 사건 기록)
관련: AI-B-12 (판정), AI-O-06 (통합 상태 뷰), AI-C-05 (결손은 축소)

기능정의서가 두 곳에서 같은 수치를 요구한다.

    §4.4 [E]  "임계값 초과 시 해당 항목이 경고 상태로 전환되며, 이벤트/알람(D)에
              기록된다" · "감시 대상은 구성 가능해야 한다"
    §4.7 [G]  "자원 조건은 리소스 현황(E)의 Layer 1 계측값과 **일관되어야** 한다"

두 요구를 따로 구현하면 반드시 어긋난다 — [E] 는 0.88 을 경고로 칠하는데 [G] 의 자원
조건은 정상이라고 적는 날이 온다. 그래서 **한 곳에서** 계측값을 읽어 경고 사건과 자원
조건을 같이 만든다. 같은 입력, 같은 판정, 두 출력이다.

## 임계는 코드가 아니라 등록 데이터다

감시 대상(어느 가속기의 어느 값을 어떤 기준으로 볼지)은 `WatchTarget` 목록으로 받는다.
가속기가 추가·교체되어도 이 모듈을 고치지 않는다(§5 구성 가변성). 기준은 이미 있는
`TargetBaseline` 을 그대로 쓴다 — 지표(E′)와 자원(E)이 서로 다른 기준 표현을 쓰면
화면이 두 어휘를 배워야 한다.

## 미측정은 경고가 아니다

값을 못 쟀으면 **사건을 만들지 않는다.** 임계를 넘었다고 말할 근거가 없기 때문이다.
대신 자원 조건은 `satisfied=None`(미확인)으로 남는다 — 못 쟀다는 사실이 "정상"으로
접히지 않는 자리가 여기다. 이것이 측정 없음을 미달과 섞지 않는 §4.5 규칙의 자원 쪽
대응이다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from mission_runtime.observability.dashboard_view import (
    ConditionItem,
    EventKind,
    EventRecord,
    NodeVerdict,
    Severity,
)
from mission_runtime.observability.layered_metrics import (
    LayeredResourceView,
    Measurement,
    MeetState,
    TargetBaseline,
)

#: 감시할 수 있는 계측 이름. 가속기 개체의 것과 보드 전체의 것을 가른다 —
#: 보드 값에 가속기 id 를 붙이면 "어느 가속기의 보드 메모리"라는 말이 된다.
ACCELERATOR_FIELDS: tuple[str, ...] = ("utilization", "temperature")
BOARD_FIELDS: tuple[str, ...] = ("memory_utilization", "power")

#: 사건 메시지에 쓰는 사유 토큰. 문구는 화면이 만든다.
REASON_OVER_THRESHOLD = "over_threshold"
REASON_WITHIN_THRESHOLD = "within_threshold"
REASON_NOT_MEASURED = "not_measured"
#: 감시 대상으로 등록했는데 그 가속기가 지금 목록에 없다. 정상으로 접지 않는다 —
#: 장치가 빠진 것과 값이 정상인 것은 다른 사실이다(AI-C-05).
REASON_TARGET_ABSENT = "watch_target_absent"


class WatchTargetInvalid(Exception):
    """감시 대상 선언이 읽을 수 없다."""


@dataclass(frozen=True)
class WatchTarget:
    """감시 대상 하나. 등록 데이터이고 코드가 아니다.

    `accelerator_id` 가 None 이면 보드 전체 값이다. 가속기 값에 None 을 주거나 보드
    값에 가속기 id 를 주는 것은 선언 오류이므로 만들 때 막는다 — 나중에 조용히 빈
    결과로 나타나면 감시가 걸려 있다고 착각한다.
    """

    item_id: str
    field: str
    target: TargetBaseline
    accelerator_id: str | None = None

    def __post_init__(self) -> None:
        if not self.item_id:
            raise WatchTargetInvalid("item_id must not be empty")
        if self.field in ACCELERATOR_FIELDS:
            if self.accelerator_id is None:
                raise WatchTargetInvalid(
                    f"{self.field!r} is measured per accelerator; accelerator_id is required"
                )
        elif self.field in BOARD_FIELDS:
            if self.accelerator_id is not None:
                raise WatchTargetInvalid(
                    f"{self.field!r} is a board-wide value; it has no accelerator_id"
                )
        else:
            raise WatchTargetInvalid(
                f"unknown watch field {self.field!r}: "
                f"{ACCELERATOR_FIELDS + BOARD_FIELDS}"
            )


@dataclass(frozen=True)
class WatchResult:
    """판정 1건. [E] 의 경고 상태와 [G] 의 자원 조건이 **이 하나**에서 나온다."""

    target: WatchTarget
    measurement: Measurement
    meet_state: MeetState
    reason_token: str

    @property
    def over_threshold(self) -> bool:
        """경고 상태로 칠할지. 미측정은 경고가 아니다."""
        return self.meet_state is MeetState.UNMET

    def as_condition(self) -> ConditionItem:
        """[G] 자원 조건 1개. 미확인을 정상으로 접지 않는다."""
        satisfied = {
            MeetState.MET: True,
            MeetState.UNMET: False,
            MeetState.NOT_MEASURED: None,
        }[self.meet_state]
        return ConditionItem(self.target.item_id, satisfied, self.reason_token)


@dataclass(frozen=True)
class ResourceWatch:
    """등록된 감시 대상으로 계측값을 읽는다. 상태를 바꾸지 않는다."""

    targets: tuple[WatchTarget, ...] = ()

    @staticmethod
    def of(targets: Iterable[WatchTarget]) -> ResourceWatch:
        return ResourceWatch(tuple(targets))

    def evaluate(self, view: LayeredResourceView) -> tuple[WatchResult, ...]:
        return tuple(self._evaluate_one(target, view) for target in self.targets)

    def _evaluate_one(self, target: WatchTarget, view: LayeredResourceView) -> WatchResult:
        measurement = self._measurement(target, view)
        if measurement is None:
            # 대상 자체가 없다. 값이 정상인 것과 다르므로 사유를 따로 둔다.
            return WatchResult(
                target, Measurement(None, target.target.unit),
                MeetState.NOT_MEASURED, REASON_TARGET_ABSENT,
            )
        meet_state = target.target.evaluate(measurement)
        reason = {
            MeetState.MET: REASON_WITHIN_THRESHOLD,
            MeetState.UNMET: REASON_OVER_THRESHOLD,
            MeetState.NOT_MEASURED: REASON_NOT_MEASURED,
        }[meet_state]
        return WatchResult(target, measurement, meet_state, reason)

    @staticmethod
    def _measurement(target: WatchTarget, view: LayeredResourceView) -> Measurement | None:
        if target.accelerator_id is None:
            return getattr(view.board, target.field)
        for accelerator in view.accelerators:
            if accelerator.instance_id == target.accelerator_id:
                return getattr(accelerator, target.field)
        return None

    def conditions(self, view: LayeredResourceView) -> tuple[ConditionItem, ...]:
        """[G] 자원 조건 축. [E] 의 경고와 같은 판정에서 나오므로 어긋날 수 없다."""
        return tuple(result.as_condition() for result in self.evaluate(view))

    def events(
        self, view: LayeredResourceView, *, at: float | None = None
    ) -> tuple[EventRecord, ...]:
        """[D] 경고 사건. **임계를 넘은 것만** 사건이 된다.

        정상은 사건이 아니고(스트림이 정상 보고로 가득 차면 경고가 묻힌다), 미측정도
        사건이 아니다(넘었다고 말할 근거가 없다). 못 쟀다는 사실은 자원 조건의
        미확인으로 남는다.
        """
        return threshold_events(self.evaluate(view), at=at)


def threshold_events(
    results: Iterable[WatchResult], *, at: float | None = None
) -> tuple[EventRecord, ...]:
    """판정 묶음 → [D] 경고 사건. 판정을 **다시 하지 않는다**.

    같은 입력을 두 번 평가하면 두 출력이 어긋날 자리가 생긴다(AI-O-06 상태 일관성).
    그래서 한 번 평가한 결과를 받아 사건으로만 옮긴다.
    """
    records = []
    for result in results:
        if not result.over_threshold:
            continue
        where = result.target.accelerator_id or "board"
        records.append(EventRecord(
            at=result.measurement.at if result.measurement.at is not None else at,
            severity=Severity.WARN,
            kind=EventKind.RESOURCE,
            message=(
                f"{where} {result.target.field} {result.measurement.value} "
                f"{result.measurement.unit} — "
                f"임계 {result.target.target.value} "
                f"{result.target.target.unit} ({result.target.target.direction.value})"
            ),
        ))
    return tuple(records)


def with_measured_resource_conditions(
    verdict: NodeVerdict, conditions: Iterable[ConditionItem]
) -> NodeVerdict:
    """[G] 자원 축의 **같은 item_id 를 계측 판정으로 바꾼** 새 판정.

    implements: AI-O-05, AI-B-12 (노드 판정), AI-O-06 (상태 일관성)

    기능정의서 §4.7: "자원 조건은 리소스 현황(E)의 Layer 1 계측값과 **일관되어야**
    한다." 선언이 자원 조건의 충족 여부까지 적으면 그 칸은 **선언값이 측정값 자리에
    앉은 것**이고, [E] 가 0.93 을 임계 초과로 칠하는 동안 [G] 는 정상이라고 적는
    날이 온다. 그래서 역할을 가른다 — **어떤 조건이 이 노드에 걸리는지는 선언이,
    그 조건이 지금 성립하는지는 계측이** 소유한다.

    감시 대상에 없는 조건은 그대로 둔다. 노드가 선언하지 않은 조건을 여기서 더하지도
    않는다 — 감시는 [E]/[D] 축이고 어느 노드의 성공 조건인지는 선언이 정한다.
    """
    by_id = {item.item_id: item for item in conditions}
    if not by_id or not verdict.resource:
        return verdict
    merged = tuple(by_id.get(item.item_id, item) for item in verdict.resource)
    if merged == verdict.resource:
        return verdict
    return replace(verdict, resource=merged)
