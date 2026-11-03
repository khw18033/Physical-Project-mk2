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
