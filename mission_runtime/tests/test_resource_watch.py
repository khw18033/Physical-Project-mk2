"""implements: AI-O-05, AI-O-02, AI-B-12
covers: [E] 의 경고와 [G] 의 자원 조건이 **같은 계측값에서** 나오는가. 기능정의서
        §4.7 은 "자원 조건은 리소스 현황(E)의 Layer 1 계측값과 일관되어야 한다"고
        요구하는데, 두 곳에서 따로 판정하면 0.88 을 한쪽은 경고로 다른 쪽은 정상으로
        적는 날이 온다.
"""

from __future__ import annotations

import pytest

from mission_runtime.observability.dashboard_view import EventKind, Severity
from mission_runtime.observability.layered_metrics import (
    AcceleratorInstance,
    BoardResources,
    Direction,
    LayeredResourceView,
    Measurement,
    MeetState,
    TargetBaseline,
    UnitMismatch,
)
from mission_runtime.observability.resource_watch import (
    REASON_NOT_MEASURED,
    REASON_OVER_THRESHOLD,
    REASON_TARGET_ABSENT,
    REASON_WITHIN_THRESHOLD,
    ResourceWatch,
    WatchTarget,
    WatchTargetInvalid,
    threshold_events,
    with_measured_resource_conditions,
)

AT = 1000.0


def _view() -> LayeredResourceView:
    return LayeredResourceView(
        accelerators=(
            AcceleratorInstance("hot", kind="npu",
                                utilization=Measurement(0.88, "ratio", AT),
                                temperature=Measurement(71.0, "celsius", AT)),
            AcceleratorInstance("calm", kind="cpu",
                                utilization=Measurement(0.41, "ratio", AT),
                                temperature=Measurement(58.0, "celsius", AT)),
            # 아직 아무 값도 못 받은 가속기. 목록에는 있다.
            AcceleratorInstance("quiet", kind="npu"),
        ),
        board=BoardResources(
            memory_utilization=Measurement(0.62, "ratio", AT),
            power=Measurement(38.4, "watt", AT),
        ),
    )


def _util(item_id: str, accelerator_id: str, limit: float = 0.85) -> WatchTarget:
    return WatchTarget(item_id, "utilization",
                       TargetBaseline(limit, Direction.AT_MOST, "ratio"), accelerator_id)


# -- 선언 오류는 만들 때 막는다 ----------------------------------------

def test_a_per_accelerator_field_needs_an_accelerator():
    """나중에 조용히 빈 결과로 나타나면 감시가 걸려 있다고 착각한다."""
    with pytest.raises(WatchTargetInvalid):
        WatchTarget("x", "utilization", TargetBaseline(0.9, Direction.AT_MOST, "ratio"))


def test_a_board_field_has_no_accelerator():
    with pytest.raises(WatchTargetInvalid):
        WatchTarget("x", "power", TargetBaseline(45.0, Direction.AT_MOST, "watt"), "cpu")


def test_an_unknown_field_is_refused_with_the_known_list():
    with pytest.raises(WatchTargetInvalid) as error:
        WatchTarget("x", "fan_rpm", TargetBaseline(1.0, Direction.AT_MOST, "rpm"))
    assert "utilization" in str(error.value)


def test_a_unit_mismatch_is_not_silently_compared():
    """단위가 다른 기준으로 판정하면 숫자만 맞고 뜻이 틀린다."""
    watch = ResourceWatch.of([
        WatchTarget("wrong_unit", "utilization",
                    TargetBaseline(85.0, Direction.AT_MOST, "percent"), "hot"),
    ])
    with pytest.raises(UnitMismatch):
        watch.evaluate(_view())


# -- 같은 판정, 두 출력 ------------------------------------------------

def test_the_warning_and_the_condition_come_from_the_same_judgement():
    watch = ResourceWatch.of([_util("hot_util", "hot"), _util("calm_util", "calm")])
    view = _view()

    over = {r.target.item_id for r in watch.evaluate(view) if r.over_threshold}
    unsatisfied = {c.item_id for c in watch.conditions(view) if c.satisfied is False}
    assert over == unsatisfied == {"hot_util"}


def test_only_the_breach_becomes_an_event():
    """정상 보고로 스트림을 채우면 경고가 묻힌다."""
    watch = ResourceWatch.of([_util("hot_util", "hot"), _util("calm_util", "calm")])
    events = watch.events(_view())
    assert len(events) == 1
    assert events[0].severity is Severity.WARN
    assert events[0].kind is EventKind.RESOURCE
    assert "hot" in events[0].message and "0.88" in events[0].message


def test_the_event_message_carries_the_threshold_it_breached():
    """운영자가 "무엇을 얼마나 넘었나"를 사건 한 줄에서 읽어야 한다."""
    watch = ResourceWatch.of([_util("hot_util", "hot")])
    assert "0.85" in watch.events(_view())[0].message


def test_the_event_time_is_the_measurement_time_not_now():
    """계측 시각이 있으면 그것을 쓴다 — 사건 시각이 수집 시각으로 밀리면 지연 분석이 틀린다."""
    watch = ResourceWatch.of([_util("hot_util", "hot")])
    assert watch.events(_view(), at=9999.0)[0].at == AT


# -- 미측정은 경고가 아니다 --------------------------------------------

def test_an_unmeasured_value_makes_no_event():
    """임계를 넘었다고 말할 근거가 없다."""
    watch = ResourceWatch.of([_util("quiet_util", "quiet")])
    assert watch.events(_view()) == ()


def test_an_unmeasured_value_is_an_unknown_condition_not_a_normal_one():
    """못 쟀다는 사실이 "정상"으로 접히면 자원 이상이 화면에서 사라진다."""
    watch = ResourceWatch.of([_util("quiet_util", "quiet")])
    condition = watch.conditions(_view())[0]
    assert condition.satisfied is None
    assert condition.reason_token == REASON_NOT_MEASURED


def test_a_target_that_is_not_in_the_list_is_told_apart_from_a_healthy_one():
    """장치가 빠진 것과 값이 정상인 것은 다른 사실이다(AI-C-05)."""
    watch = ResourceWatch.of([_util("gone_util", "pulled-out")])
    result = watch.evaluate(_view())[0]
    assert result.meet_state is MeetState.NOT_MEASURED
    assert result.reason_token == REASON_TARGET_ABSENT
    assert watch.conditions(_view())[0].satisfied is None


# -- 구성 가변성 (§5) --------------------------------------------------

def test_a_new_accelerator_needs_no_code_change():
    """감시 대상은 등록 데이터다. 가속기가 늘어도 이 모듈을 고치지 않는다."""
    view = LayeredResourceView(
        accelerators=_view().accelerators + (
            AcceleratorInstance("brand-new", kind="npu",
                                utilization=Measurement(0.95, "ratio", AT)),
        ),
        board=_view().board,
    )
    watch = ResourceWatch.of([_util("new_util", "brand-new")])
    assert watch.conditions(view)[0].satisfied is False


def test_board_wide_values_are_watched_too():
    watch = ResourceWatch.of([
        WatchTarget("power_budget", "power",
                    TargetBaseline(35.0, Direction.AT_MOST, "watt")),
        WatchTarget("memory_budget", "memory_utilization",
                    TargetBaseline(0.9, Direction.AT_MOST, "ratio")),
    ])
    by_id = {c.item_id: c for c in watch.conditions(_view())}
    assert by_id["power_budget"].satisfied is False
    assert by_id["memory_budget"].satisfied is True
    assert by_id["memory_budget"].reason_token == REASON_WITHIN_THRESHOLD


def test_an_at_least_target_also_works():
    """기준이 하한인 자원도 있다 — 방향을 고정하지 않는다."""
    watch = ResourceWatch.of([
        WatchTarget("min_util", "utilization",
                    TargetBaseline(0.5, Direction.AT_LEAST, "ratio"), "calm"),
    ])
    result = watch.evaluate(_view())[0]
    assert result.over_threshold is True
    assert result.reason_token == REASON_OVER_THRESHOLD


def test_no_targets_means_no_opinion():
    """감시 대상이 없는 배치에서도 정상 동작한다 — 빈 결과가 오류가 아니다."""
    watch = ResourceWatch()
    assert watch.evaluate(_view()) == ()
    assert watch.conditions(_view()) == ()
    assert watch.events(_view()) == ()


# -- [G] 자원 축은 계측이 소유한다 (§4.7 일관성) ------------------------------


def test_a_declared_resource_condition_is_replaced_by_the_measured_verdict():
    """선언이 적어 둔 `satisfied` 가 계측 판정으로 바뀐다.

    기능정의서 §4.7: "자원 조건은 리소스 현황(E)의 Layer 1 계측값과 **일관되어야**
    한다." 선언이 충족 여부까지 적으면 그 칸은 선언값이 측정값 자리에 앉은 것이고,
    [E] 가 임계 초과를 칠하는 동안 [G] 는 정상이라고 적는 날이 온다. 어떤 조건이
    걸리는지는 선언이, 지금 성립하는지는 계측이 소유한다.
    """
    from mission_runtime.observability.dashboard_view import ConditionItem, NodeVerdict

    watch = ResourceWatch.of([
        WatchTarget("thermal_ok", "temperature",
                    TargetBaseline(60.0, Direction.AT_MOST, "celsius"), "hot"),
    ])
    conditions = watch.conditions(_view())
    verdict = NodeVerdict(
        node_id="n1",
        completion=(ConditionItem("arrived", True),),
        resource=(ConditionItem("thermal_ok", True), ConditionItem("disk_ok", True)),
    )

    merged = with_measured_resource_conditions(verdict, conditions)
    by_id = {item.item_id: item for item in merged.resource}
    # 계측이 뒤집는다 — 71.0 celsius 는 기준 60.0 을 넘는다.
    assert by_id["thermal_ok"].satisfied is False
    assert by_id["thermal_ok"].reason_token == REASON_OVER_THRESHOLD
    # 감시 대상이 아닌 조건은 그대로다 — 감시가 노드의 조건 목록을 바꾸지 않는다.
    assert by_id["disk_ok"].satisfied is True
    # 다른 축은 건드리지 않는다.
    assert merged.completion == verdict.completion
    # 감시 대상에만 있고 노드가 선언하지 않은 조건을 더하지도 않는다.
    assert set(by_id) == {"thermal_ok", "disk_ok"}


def test_merging_nothing_returns_the_same_verdict():
    """감시가 없거나 겹치는 조건이 없으면 판정은 그대로다 (AI-C-05)."""
    from mission_runtime.observability.dashboard_view import ConditionItem, NodeVerdict

    verdict = NodeVerdict(node_id="n1", resource=(ConditionItem("disk_ok", True),))
    assert with_measured_resource_conditions(verdict, ()) is verdict
    assert with_measured_resource_conditions(
        verdict, (ConditionItem("other", False),)) is verdict


def test_events_are_built_from_an_already_made_judgement():
    """판정을 두 번 하지 않는다 (AI-O-06 상태 일관성).

    같은 입력을 두 번 평가하면 두 출력이 어긋날 자리가 생긴다. 그래서 사건은 평가
    결과를 받아 옮기기만 하고, `ResourceWatch.events` 도 같은 함수를 쓴다.
    """
    watch = ResourceWatch.of([
        WatchTarget("thermal_ok", "temperature",
                    TargetBaseline(60.0, Direction.AT_MOST, "celsius"), "hot"),
        WatchTarget("calm_ok", "temperature",
                    TargetBaseline(60.0, Direction.AT_MOST, "celsius"), "calm"),
        WatchTarget("quiet_ok", "temperature",
                    TargetBaseline(60.0, Direction.AT_MOST, "celsius"), "quiet"),
    ])
    results = watch.evaluate(_view())
    events = threshold_events(results, at=AT)
    assert [e.kind for e in events] == [EventKind.RESOURCE]
    assert events[0].severity is Severity.WARN
    assert "hot" in events[0].message
    # 같은 결과에서 나오므로 두 길이 같다.
    assert events == watch.events(_view(), at=AT)
