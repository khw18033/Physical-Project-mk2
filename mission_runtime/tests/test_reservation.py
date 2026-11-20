"""예약과 fencing 의 계약 — `runtime/reservation.py`.

implements: AI-B-04, AI-B-06, AI-L-10, AI-C-20
tests: 둘이 같은 가속기를 못 잡는다 · 거절은 **사유**를 낸다 · 같은 주인의 재요청은
       새 점유가 아니다 · 확정된 것만 해제된다 · 만료는 해제와 다른 상태다 ·
       깨어난 옛 주인은 번호로 막힌다 · 선언 없는 자원은 0 이 아니라 모름이다
"""
from __future__ import annotations

import pytest

from mission_runtime.runtime.reservation import (
    ACTIVE,
    EXPIRED,
    HELD,
    REASON_CAPACITY,
    REASON_HELD_BY_OTHER,
    REASON_NOT_ACTIVE,
    REASON_UNDECLARED,
    RELEASED,
    FencingGuard,
    Lease,
    Refusal,
    ReservationLedger,
    ResourceSlot,
    refusal_reason,
)


class FakeClock:
    """시계를 손에 쥔다 — 만료를 **기다리지 않고** 재현한다."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ledger(clock: FakeClock) -> ReservationLedger:
    return ReservationLedger(
        (ResourceSlot("gpu-0", tags=frozenset({"compute.gpu"})),
         ResourceSlot("npu-0", capacity=2)),
        clock=clock)


# --------------------------------------------------------------- 경합

def test_two_deployments_cannot_hold_the_same_accelerator(ledger):
    """**이것이 이 모듈이 있는 이유다.** 배정 둘이 같은 GPU 를 고르면 하나는 막힌다."""
    first = ledger.acquire("gpu-0", holder="deploy-a")
    second = ledger.acquire("gpu-0", holder="deploy-b")

    assert isinstance(first, Lease)
    assert isinstance(second, Refusal)
    assert second.reason == REASON_HELD_BY_OTHER
    assert second.held_by == "deploy-a"


def test_a_refusal_says_which_of_three_things_went_wrong(ledger):
    """「자원이 없다」·「남이 쓴다」·「선언이 없다」는 **할 일이 다르다**."""
    assert refusal_reason(ledger.acquire("ghost", holder="x")) == REASON_UNDECLARED

    ledger.acquire("gpu-0", holder="a")
    assert refusal_reason(ledger.acquire("gpu-0", holder="b")) == REASON_HELD_BY_OTHER

    ledger.acquire("npu-0", holder="a")
    ledger.acquire("npu-0", holder="b")
    assert refusal_reason(ledger.acquire("npu-0", holder="c")) == REASON_CAPACITY


def test_a_refusal_says_when_it_is_worth_trying_again(ledger, clock):
    ledger.acquire("gpu-0", holder="a", ttl_s=30)
    refusal = ledger.acquire("gpu-0", holder="b")
    assert isinstance(refusal, Refusal)
    assert refusal.retry_after_s == pytest.approx(30.0)


def test_a_shared_slot_admits_up_to_its_declared_capacity(ledger):
    """가속기는 보통 1 이지만 동시 추론 슬롯처럼 나눠 쓰는 것이 있다."""
    assert isinstance(ledger.acquire("npu-0", holder="a"), Lease)
    assert isinstance(ledger.acquire("npu-0", holder="b"), Lease)
    assert isinstance(ledger.acquire("npu-0", holder="c"), Refusal)


def test_the_same_holder_asking_twice_is_not_a_second_hold(ledger, clock):
    """재전달은 **새 점유가 아니다** — AI-C-20 의 멱등성과 같은 규칙이다."""
    first = ledger.acquire("gpu-0", holder="deploy-a", ttl_s=10)
    clock.advance(5)
    again = ledger.acquire("gpu-0", holder="deploy-a", ttl_s=10)

    assert isinstance(again, Lease)
    assert again.token == first.token, "번호가 늘면 새 점유다"
    assert again.expires_at > first.expires_at, "기한만 늘어야 한다"
    assert ledger.holders("gpu-0") == ("deploy-a",)


# --------------------------------------------------------------- 수명주기

def test_only_a_confirmed_lease_can_be_released(ledger):
    """확정 전에 해제하면 **잡은 줄 알고 쓰기 시작한 쪽**이 남는다."""
    lease = ledger.acquire("gpu-0", holder="a")
    assert lease.state == HELD

    too_early = ledger.release(lease)
    assert isinstance(too_early, Refusal)
    assert too_early.reason == REASON_NOT_ACTIVE

    confirmed = ledger.confirm(lease)
    assert confirmed.state == ACTIVE
    assert ledger.release(confirmed).state == RELEASED


def test_an_expiry_is_not_a_release(ledger, clock):
    """만료된 lease 로 한 일은 되돌려지지 않는다 — 되돌릴 수 있는 척하지 않는다."""
    lease = ledger.acquire("gpu-0", holder="a", ttl_s=10)
    ledger.confirm(lease)
    clock.advance(11)

    expired = ledger.expire_due()
    assert len(expired) == 1
    assert expired[0].state == EXPIRED
    assert expired[0].state != RELEASED


def test_an_expired_hold_frees_the_resource_for_someone_else(ledger, clock):
    ledger.acquire("gpu-0", holder="a", ttl_s=10)
    clock.advance(11)
    assert isinstance(ledger.acquire("gpu-0", holder="b"), Lease)


def test_renewing_a_dead_lease_is_refused_not_resurrected(ledger, clock):
    lease = ledger.acquire("gpu-0", holder="a", ttl_s=10)
    clock.advance(11)
    ledger.expire_due()
    assert isinstance(ledger.renew(lease), Refusal)


# --------------------------------------------------------------- fencing

def test_a_woken_old_holder_is_stopped_by_the_number_not_the_clock():
    """시계는 양쪽이 다르게 읽는다. **번호는 하나다.**"""
    clock = FakeClock()
    ledger = ReservationLedger((ResourceSlot("gpu-0"),), clock=clock)
    guard = FencingGuard()

    old = ledger.acquire("gpu-0", holder="slow", ttl_s=10)
    assert guard.admit("gpu-0", old.token) is True        # 옛 주인이 한 번 들어갔다

    clock.advance(11)
    ledger.expire_due()
    new = ledger.acquire("gpu-0", holder="fast", ttl_s=10)
    assert guard.admit("gpu-0", new.token) is True

    # 멈춰 있던 옛 주인이 깨어나 자기가 아직 주인인 줄 안다
    assert guard.admit("gpu-0", old.token) is False
    assert guard.fenced == [("gpu-0", old.token, new.token)]


def test_the_guard_counts_what_it_blocked_so_zero_is_a_measurement():
    """「중복 실행 0건」이 **주장이 아니라 측정**이 되는 자리."""
    guard = FencingGuard()
    guard.admit("gpu-0", 5)
    assert guard.fenced == []
    guard.admit("gpu-0", 3)
    assert len(guard.fenced) == 1
    assert guard.highest_seen("gpu-0") == 5


def test_the_ledger_counts_conflicts_too(ledger):
    ledger.acquire("gpu-0", holder="a")
    ledger.acquire("gpu-0", holder="b")
    ledger.acquire("gpu-0", holder="c")
    assert len(ledger.conflicts) == 2


# --------------------------------------------------------------- 보기

def test_an_undeclared_resource_has_no_capacity_not_zero_capacity(ledger):
    """**미선언은 0 이 아니다**(AI-O-05). 0 이면 「가득 찼다」로 읽힌다."""
    assert ledger.free_capacity("ghost") is None
    assert ledger.free_capacity("gpu-0") == 1


def test_a_declared_but_idle_resource_stays_in_the_snapshot(ledger):
    """배치된 것이 없는 가속기도 목록에서 빠지지 않는다(AI-O-05)."""
    snapshot = ledger.snapshot()
    assert set(snapshot) == {"gpu-0", "npu-0"}
    assert snapshot["gpu-0"]["held"] == 0
    assert snapshot["gpu-0"]["tags"] == ["compute.gpu"]


def test_a_new_accelerator_is_a_declaration_not_a_code_change(ledger):
    ledger.declare(ResourceSlot("gpu-1", tags=frozenset({"compute.gpu"})))
    assert "gpu-1" in ledger.declared()
    assert isinstance(ledger.acquire("gpu-1", holder="a"), Lease)
