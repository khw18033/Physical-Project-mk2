"""자원 예약(lease)과 fencing token — **둘이 같은 가속기를 동시에 잡지 않게.**

implements: AI-B-04 (실행 노드 자원 등록·배치), AI-B-06 (자원 상태 기반 재구성),
            AI-L-10 (하드웨어·임무 조건 기반 모델 배정)
관련: AI-C-20 (중복 실행 금지), AI-B-05 (복구), AI-C-05 (없으면 축소), AI-O-05
tests: tests/test_reservation.py

## 메우는 구멍

`runtime/placement.py` 는 **배정**을 한다 — 어느 노드가 조건에 맞는지 고른다.
그런데 고른 뒤에 **잡지는 않는다.** 모델 하나를 한 노드에 올릴 때는 보이지 않던
구멍이고, 다중 모델·다중 노드로 가는 순간 둘이 같은 GPU 를 동시에 고른다.
배정은 둘 다 성공하고 실행에서 하나가 메모리 부족으로 죽는다 — 그 실패는
**배정 로그 어디에도 이유가 없다.**

## 왜 토큰이 필요한가 — "만료됐다" 는 양쪽이 다르게 안다

점유자가 멈춰 있는 동안 lease 가 만료되고 다른 쪽이 같은 자원을 잡았다고 하자.
멈춰 있던 쪽이 깨어나 **자기가 아직 주인인 줄 알고** 쓰기 시작하면 둘이 겹친다.
그래서 자원마다 **단조 증가하는 번호**(fencing token)를 주고, 자원을 실제로 쓰는
쪽이 "내가 본 마지막 번호보다 작은 요청은 거절" 하게 한다. 시계를 믿지 않고
**번호를 믿는다.**

    lease = ledger.acquire("gpu-0", holder="deploy-7", ttl_s=30)
    ...
    guard.admit("gpu-0", lease.token)      # 더 큰 번호가 왔으면 옛 주인은 거절된다

## 잡지 못한 것은 **사유를 낸다**

"실패" 하나로 접으면 운영자가 「자원이 없다」와 「남이 쓰고 있다」와 「선언이
없다」를 구분할 수 없다. 셋은 할 일이 다르다(AI-O-05 의 세 상태와 같은 규칙).

## 확정된 것만 해제한다

`HELD → ACTIVE → RELEASED` 다. 아직 확정되지 않은 예약(HELD)을 바깥에서 해제하면
"잡은 줄 알고 쓰기 시작한" 쪽이 남는다. 만료는 해제와 **다른 상태**이고, 만료된
lease 로 한 일은 되돌려지지 않는다 — 되돌릴 수 있는 척하지 않는다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

#: lease 상태. 만료는 해제와 **다른 사실**이다.
HELD = "held"
ACTIVE = "active"
RELEASED = "released"
EXPIRED = "expired"

#: 거절 사유 어휘. 문구가 아니라 **토큰**이다 — 화면이 이걸로 분기한다.
REASON_UNDECLARED = "resource_not_declared"
REASON_HELD_BY_OTHER = "held_by_another_holder"
REASON_CAPACITY = "capacity_exhausted"
REASON_UNKNOWN_LEASE = "unknown_lease"
REASON_NOT_ACTIVE = "lease_not_active"
REASON_STALE_TOKEN = "stale_fencing_token"


@dataclass(frozen=True)
class Lease:
    """자원 하나에 대한 점유. `token` 이 시계보다 믿을 만한 것이다."""

    resource_id: str
    holder: str
    token: int
    state: str
    granted_at: float
    expires_at: float

    def is_live(self, now: float | None = None) -> bool:
        at = time.time() if now is None else now
        return self.state in (HELD, ACTIVE) and at < self.expires_at


@dataclass(frozen=True)
class Refusal:
    """잡지 못했다. **왜**가 함께 온다."""

    resource_id: str
    reason: str
    held_by: str | None = None
    retry_after_s: float | None = None


@dataclass(frozen=True)
class ResourceSlot:
    """예약할 수 있는 자원 하나. **선언이다** — 관측이 아니다(AI-C-18).

    `capacity` 가 1 보다 크면 그만큼 동시에 쥘 수 있다. 가속기는 보통 1 이고,
    대역폭·동시 추론 슬롯처럼 나눠 쓰는 것은 그 수만큼이다.
    """

    resource_id: str
    capacity: int = 1
    tags: frozenset[str] = field(default_factory=frozenset)


class ReservationLedger:
    """예약 장부. **판정하지 않는다** — 누가 적합한지는 선택기가 이미 정했다.

    여기는 "그 선택을 실제로 잡을 수 있는가" 하나만 답한다. 적합성과 점유를 한
    곳에서 하면, 자원이 바빠서 못 쓰는 것과 조건이 안 맞아서 못 쓰는 것이 같은
    실패가 된다.
    """

    def __init__(self, slots: tuple[ResourceSlot, ...] = (), *,
                 clock: Callable[[], float] | None = None) -> None:
        self._slots = {slot.resource_id: slot for slot in slots}
        self._leases: dict[str, list[Lease]] = {}
        self._token = 0
        self._clock = clock or time.time
        #: 거절을 센다. 「예약 충돌 0건」을 **주장이 아니라 측정**으로 만든다.
        self.conflicts: list[Refusal] = []

    # --- 선언 -------------------------------------------------------------
    def declare(self, slot: ResourceSlot) -> None:
        """자원을 장부에 들인다. 새 가속기는 **선언 한 줄**이고 코드 변경이 아니다."""
        self._slots[slot.resource_id] = slot

    def declared(self) -> tuple[str, ...]:
        return tuple(sorted(self._slots))

    # --- 잡기 -------------------------------------------------------------
    def acquire(self, resource_id: str, *, holder: str, ttl_s: float = 30.0
                ) -> Lease | Refusal:
        """잡거나, **왜 못 잡았는지**를 돌려준다. 예외를 던지지 않는다."""
        now = self._clock()
        slot = self._slots.get(resource_id)
        if slot is None:
            return self._refuse(Refusal(resource_id, REASON_UNDECLARED))

        live = self._live(resource_id, now)
        if any(lease.holder == holder for lease in live):
            # 같은 주인의 재요청은 **새 점유가 아니다** — 기한만 늘린다(AI-C-20 멱등성)
            return self._renew_in_place(resource_id, holder, ttl_s, now)
        if len(live) >= slot.capacity:
            oldest = min(live, key=lambda lease: lease.expires_at)
            return self._refuse(Refusal(
                resource_id,
                REASON_HELD_BY_OTHER if slot.capacity == 1 else REASON_CAPACITY,
                held_by=oldest.holder,
                retry_after_s=max(0.0, oldest.expires_at - now)))

        self._token += 1
        lease = Lease(resource_id, holder, self._token, HELD, now, now + ttl_s)
        self._leases.setdefault(resource_id, []).append(lease)
        return lease

    def confirm(self, lease: Lease) -> Lease | Refusal:
        """HELD → ACTIVE. **확정된 것만 해제할 수 있다.**"""
        return self._transition(lease, HELD, ACTIVE)

    def release(self, lease: Lease) -> Lease | Refusal:
        """ACTIVE → RELEASED. 확정 전이면 거절한다 — 잡은 줄 아는 쪽이 남는다."""
        return self._transition(lease, ACTIVE, RELEASED)

    def renew(self, lease: Lease, ttl_s: float = 30.0) -> Lease | Refusal:
        now = self._clock()
        current = self._find(lease)
        if current is None:
            return self._refuse(Refusal(lease.resource_id, REASON_UNKNOWN_LEASE))
        if not current.is_live(now):
            return self._refuse(Refusal(lease.resource_id, REASON_NOT_ACTIVE))
        return self._replace(current, expires_at=now + ttl_s)

    # --- 보기 -------------------------------------------------------------
    def holders(self, resource_id: str) -> tuple[str, ...]:
        return tuple(lease.holder for lease in self._live(resource_id, self._clock()))

    def free_capacity(self, resource_id: str) -> int | None:
        """몇 개 더 잡을 수 있나. **선언이 없으면 0 이 아니라 None 이다.**"""
        slot = self._slots.get(resource_id)
        if slot is None:
            return None
        return max(0, slot.capacity - len(self._live(resource_id, self._clock())))

    def expire_due(self) -> tuple[Lease, ...]:
        """기한이 지난 것을 만료로 적는다. **해제와 다른 상태로 남는다.**"""
        now = self._clock()
        expired: list[Lease] = []
        for resource_id, leases in self._leases.items():
            for index, lease in enumerate(leases):
                if lease.state in (HELD, ACTIVE) and now >= lease.expires_at:
                    gone = Lease(lease.resource_id, lease.holder, lease.token,
                                 EXPIRED, lease.granted_at, lease.expires_at)
                    leases[index] = gone
                    expired.append(gone)
        return tuple(expired)

    def snapshot(self) -> dict[str, dict[str, object]]:
        """운영 화면이 읽는 모양. 선언된 자원은 **비어 있어도 빠지지 않는다**(AI-O-05)."""
        now = self._clock()
        out: dict[str, dict[str, object]] = {}
        for resource_id, slot in sorted(self._slots.items()):
            live = self._live(resource_id, now)
            out[resource_id] = {
                "capacity": slot.capacity,
                "held": len(live),
                "holders": [lease.holder for lease in live],
                "tags": sorted(slot.tags),
            }
        return out

    # --- 내부 -------------------------------------------------------------
    def _refuse(self, refusal: Refusal) -> Refusal:
        self.conflicts.append(refusal)
        return refusal

    def _live(self, resource_id: str, now: float) -> list[Lease]:
        return [lease for lease in self._leases.get(resource_id, ())
                if lease.is_live(now)]

    def _find(self, lease: Lease) -> Lease | None:
        for current in self._leases.get(lease.resource_id, ()):
            if current.token == lease.token:
                return current
        return None

    def _replace(self, current: Lease, *, state: str | None = None,
                 expires_at: float | None = None) -> Lease:
        made = Lease(current.resource_id, current.holder, current.token,
                     state or current.state, current.granted_at,
                     current.expires_at if expires_at is None else expires_at)
        leases = self._leases[current.resource_id]
        leases[leases.index(current)] = made
        return made

    def _transition(self, lease: Lease, expected: str, to: str) -> Lease | Refusal:
        current = self._find(lease)
        if current is None:
            return self._refuse(Refusal(lease.resource_id, REASON_UNKNOWN_LEASE))
        if current.state != expected:
            return self._refuse(Refusal(lease.resource_id, REASON_NOT_ACTIVE,
                                        held_by=current.holder))
        return self._replace(current, state=to)

    def _renew_in_place(self, resource_id: str, holder: str, ttl_s: float,
                        now: float) -> Lease:
        current = next(lease for lease in self._live(resource_id, now)
                       if lease.holder == holder)
        return self._replace(current, expires_at=now + ttl_s)


class FencingGuard:
    """자원을 **실제로 쓰는 쪽**의 문지기. 시계가 아니라 번호를 본다.

    `providers/k3s.py` 나 장치 어댑터처럼 진짜 작업을 하는 자리 앞에 둔다. 멈춰
    있다 깨어난 옛 주인이 자기가 아직 주인인 줄 알고 들어와도, 그 사이에 더 큰
    번호가 지나갔으면 거절된다.
    """

    def __init__(self) -> None:
        self._highest: dict[str, int] = {}
        #: 막아 낸 횟수. 「중복 실행 0건」의 측정값이 여기서 나온다.
        self.fenced: list[tuple[str, int, int]] = []

    def admit(self, resource_id: str, token: int) -> bool:
        """들여보낼지. 본 적 있는 번호보다 **작으면** 거절한다."""
        highest = self._highest.get(resource_id)
        if highest is not None and token < highest:
            self.fenced.append((resource_id, token, highest))
            return False
        self._highest[resource_id] = token
        return True

    def highest_seen(self, resource_id: str) -> int | None:
        return self._highest.get(resource_id)


def refusal_reason(outcome: Lease | Refusal) -> str | None:
    """잡혔으면 None, 아니면 사유 토큰. 화면이 분기하는 자리."""
    return None if isinstance(outcome, Lease) else outcome.reason
