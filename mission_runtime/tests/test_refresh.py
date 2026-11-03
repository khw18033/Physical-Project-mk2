"""implements: AI-O-06, AI-C-13
covers: nothing is reflected without a request, suppression actually skips the
        work, never-received differs from stale, failure does not propagate
"""

import pytest

from mission_runtime.runtime.refresh import (
    REASON_FAILED,
    REASON_NO_WORK,
    REASON_PERFORMED,
    REASON_SUPPRESSED,
    Freshness,
    RefreshLedger,
    Trigger,
    scope_of,
)


def ledger(start: float = 1000.0):
    clock = [start]
    return RefreshLedger(clock=lambda: clock[0]), clock


# --- 요청이 없으면 아무것도 반영되지 않는다 ----------------------------------


def test_a_scope_nobody_asked_for_has_never_been_reflected():
    led, _ = ledger()

    assert led.as_of(scope_of("zone", "z1")) is None
    assert led.freshness(scope_of("zone", "z1")) is Freshness.NEVER
    assert led.age_s(scope_of("zone", "z1")) is None


def test_never_received_is_not_the_same_as_old():
    """AI-O-06: 한 번도 수신하지 않은 상태와 오래된 상태를 구분해야 한다."""
    led, clock = ledger()
    led.request(scope_of("zone", "seen"), Trigger.OPERATOR_VIEW)
    clock[0] += 10_000

    assert led.freshness(scope_of("zone", "seen")) is Freshness.STALE
    assert led.freshness(scope_of("zone", "unseen")) is Freshness.NEVER


# --- 억제는 실제로 일을 아낀다 ----------------------------------------------


def test_a_repeated_operator_view_skips_the_work_entirely():
    led, _ = ledger()
    calls = []

    first = led.request(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW,
                        work=lambda: (calls.append(1), ["a"])[1])
    second = led.request(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW,
                         work=lambda: (calls.append(1), ["a"])[1])

    assert first.performed is True
    assert (second.performed, second.reason) == (False, REASON_SUPPRESSED)
    assert len(calls) == 1, "억제했는데 일을 했다면 아무것도 아끼지 못한 것이다"


def test_suppression_still_reports_when_the_value_is_from():
    led, _ = ledger()
    led.request(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW)

    second = led.request(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW)

    assert second.as_of is not None


def test_after_the_interval_passes_the_same_view_refreshes_again():
    led, clock = ledger()
    led.request(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW)
    clock[0] += 5.0

    assert led.request(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW).performed is True


def test_a_mission_assignment_is_never_suppressed():
    """사람이 방금 지시한 것을 건너뛰면 지시가 먹지 않은 것처럼 보인다."""
    led, _ = ledger()
    led.request(scope_of("zone", "z1"), Trigger.MISSION_ASSIGNED)

    assert led.request(scope_of("zone", "z1"), Trigger.MISSION_ASSIGNED).performed is True


def test_onboarding_is_never_suppressed_either():
    led, _ = ledger()
    led.request(scope_of("robot", "new-1"), Trigger.ONBOARDING)

    assert led.request(scope_of("robot", "new-1"), Trigger.ONBOARDING).performed is True


def test_suppression_is_per_scope_and_per_trigger():
    led, _ = ledger()
    led.request(scope_of("zone", "a"), Trigger.OPERATOR_VIEW)

    assert led.request(scope_of("zone", "b"), Trigger.OPERATOR_VIEW).performed is True
    assert led.request(scope_of("zone", "a"), Trigger.SUBTASK_DEMAND).performed is True


# --- 결과와 기록 ------------------------------------------------------------


def test_a_refresh_that_found_nothing_says_so_instead_of_claiming_success():
    led, _ = ledger()

    decision = led.request(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW, work=lambda: [])

    assert decision.performed is True
    assert decision.reason == REASON_NO_WORK


def test_a_refresh_records_what_it_touched_and_how_long_it_took():
    led, _ = ledger()

    decision = led.request(scope_of("zone", "z1"), Trigger.MISSION_ASSIGNED,
                           requested_by="admin", work=lambda: ["go1", "ep"])

    assert decision.reason == REASON_PERFORMED
    assert decision.record.items == ("go1", "ep")
    assert decision.record.requested_by == "admin"
    assert decision.record.duration_ms is not None, "관리 기능 자체의 비용도 재야 한다"


def test_history_keeps_the_order_requests_arrived_in():
    led, clock = ledger()
    led.request(scope_of("zone", "a"), Trigger.OPERATOR_VIEW)
    clock[0] += 1
    led.request(scope_of("zone", "b"), Trigger.MISSION_ASSIGNED)

    assert [r.scope for r in led.history()] == ["zone:a", "zone:b"]


def test_a_multi_zone_mission_decides_and_records_each_zone_separately():
    led, _ = ledger()

    decisions = led.request_many(
        [scope_of("zone", "a"), scope_of("zone", "b")], Trigger.MISSION_ASSIGNED,
        requested_by="admin", work=lambda scope: [scope])

    assert [d.scope for d in decisions] == ["zone:a", "zone:b"]
    assert all(d.performed for d in decisions)
    assert led.as_of(scope_of("zone", "b")) is not None


# --- 실패가 번지지 않는다 ---------------------------------------------------


def test_a_failing_refresh_is_reported_and_leaves_the_previous_value_alone():
    led, clock = ledger()
    led.request(scope_of("zone", "z1"), Trigger.MISSION_ASSIGNED, work=lambda: ["a"])
    first_at = led.as_of(scope_of("zone", "z1"))
    clock[0] += 1

    def boom():
        raise RuntimeError("camera gone")

    decision = led.request(scope_of("zone", "z1"), Trigger.MISSION_ASSIGNED, work=boom)

    assert decision.performed is False
    assert decision.reason == f"{REASON_FAILED}:RuntimeError"
    assert led.as_of(scope_of("zone", "z1")) == first_at


# --- 화면이 '언제 기준'을 적는 데 쓰는 묶음 ---------------------------------


def test_status_distinguishes_all_three_states_in_one_call():
    led, clock = ledger()
    led.request(scope_of("zone", "fresh"), Trigger.OPERATOR_VIEW)
    led.request(scope_of("zone", "old"), Trigger.OPERATOR_VIEW)
    clock[0] += led.stale_after_s + 1
    led.request(scope_of("zone", "fresh"), Trigger.MISSION_ASSIGNED)

    status = led.status(["zone:fresh", "zone:old", "zone:never"])

    assert status["zone:fresh"]["freshness"] == Freshness.FRESH.value
    assert status["zone:old"]["freshness"] == Freshness.STALE.value
    assert status["zone:never"] == {"as_of": None, "age_s": None,
                                   "freshness": Freshness.NEVER.value}


def test_scope_names_are_built_not_hand_written():
    assert scope_of("zone", "N4-1F-W") == "zone:N4-1F-W"
    assert scope_of("map") == "map"


def test_would_perform_answers_without_performing():
    led, _ = ledger()
    led.request(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW)

    assert led.would_perform(scope_of("zone", "z1"), Trigger.OPERATOR_VIEW) is False
    assert led.would_perform(scope_of("zone", "z2"), Trigger.OPERATOR_VIEW) is True
