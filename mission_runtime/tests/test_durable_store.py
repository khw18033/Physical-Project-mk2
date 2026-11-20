"""내구 저장과 Outbox 의 계약 — `providers/durable_store.py`.

implements: AI-B-05, AI-L-08, AI-O-03, AI-C-04, AI-C-16
tests: 사실과 발행 예약이 **한 커밋** · 예외면 둘 다 안 쓰인다 · 재시작을 넘는다 ·
       보낸 뒤에만 지운다 · 실패하면 순서를 지키려 멈춘다 · 중복은 받는 쪽이 접는다 ·
       재시작해도 번호를 되쓰지 않는다
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mission_runtime.providers.durable_store import (
    DURABILITY_PROCESS,
    DURABILITY_RESTART,
    DurableStoreProvider,
    InboxDeduplicator,
    InMemoryDurableStore,
    OutboxPublisher,
    SqliteDurableStore,
)


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    """두 구현이 **같은 계약**을 만족해야 한다 — 그게 provider 경계의 뜻이다."""
    if request.param == "memory":
        made = InMemoryDurableStore()
    else:
        made = SqliteDurableStore(str(tmp_path / "store.db"))
    yield made
    if hasattr(made, "close"):
        made.close()


def test_both_implementations_satisfy_the_same_protocol(store):
    assert isinstance(store, DurableStoreProvider)


def test_a_fact_and_its_announcement_land_in_one_commit(store):
    """상태는 바뀌었는데 아무도 모르거나, 알렸는데 상태가 없는 경로를 없앤다."""
    with store.transaction() as tx:
        tx.put("deployment", "d-1", {"version": "v2", "scope": "zone-a"})
        tx.enqueue("deployment.applied", aggregate_id="d-1", payload={"version": "v2"})

    assert store.get("deployment", "d-1") == {"version": "v2", "scope": "zone-a"}
    events = store.drain()
    assert len(events) == 1
    assert events[0].event_type == "deployment.applied"
    assert events[0].aggregate_id == "d-1"


def test_an_exception_writes_neither_the_fact_nor_the_announcement(store):
    """**반쯤 적힌 상태를 만들지 않는다.** 둘 다 없거나 둘 다 있다."""
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            tx.put("deployment", "d-2", {"version": "v3"})
            tx.enqueue("deployment.applied", aggregate_id="d-2")
            raise RuntimeError("배치 도중 터졌다")

    assert store.get("deployment", "d-2") is None
    assert all(e.aggregate_id != "d-2" for e in store.drain())


def test_the_store_says_what_it_guarantees_not_whether_it_exists(store):
    """"있다/없다" 가 아니라 **무엇을 보장하는가**. 받는 쪽이 그걸로 판단한다."""
    assert store.durability in (DURABILITY_PROCESS, DURABILITY_RESTART)
    if isinstance(store, InMemoryDurableStore):
        assert store.durability == DURABILITY_PROCESS
    else:
        assert store.durability == DURABILITY_RESTART


def test_sqlite_survives_a_restart_and_memory_says_it_does_not(tmp_path: Path):
    """AI-B-05 의 last-known-good 가 말뿐이 아니게 되는 자리."""
    path = str(tmp_path / "restart.db")
    first = SqliteDurableStore(path)
    with first.transaction() as tx:
        tx.put("last_known_good", "svc-a", {"version": "v1"})
        tx.enqueue("deployment.applied", aggregate_id="svc-a")
    first.close()

    second = SqliteDurableStore(path)                     # 프로세스가 죽었다 다시 떴다
    assert second.get("last_known_good", "svc-a") == {"version": "v1"}
    assert len(second.drain()) == 1, "아직 안 보낸 사건도 남아 있어야 한다"
    second.close()

    volatile = InMemoryDurableStore()
    with volatile.transaction() as tx:
        tx.put("last_known_good", "svc-a", {"version": "v1"})
    assert volatile.durability == DURABILITY_PROCESS      # 넘지 못한다고 **말한다**


def test_a_restarted_store_does_not_reuse_sequence_numbers(tmp_path: Path):
    """번호를 되쓰면 받는 쪽의 중복 접기가 **거짓**이 된다 — 다른 사건이 같은 id 가 된다."""
    path = str(tmp_path / "seq.db")
    first = SqliteDurableStore(path)
    with first.transaction() as tx:
        tx.enqueue("a", aggregate_id="x")
        tx.enqueue("b", aggregate_id="x")
    first_ids = [e.event_id for e in first.drain()]
    first.close()

    second = SqliteDurableStore(path)
    with second.transaction() as tx:
        tx.enqueue("c", aggregate_id="x")
    all_ids = [e.event_id for e in second.drain()]
    second.close()

    assert len(set(all_ids)) == len(all_ids), f"식별자가 겹친다: {all_ids}"
    assert set(first_ids) < set(all_ids)


# --------------------------------------------------------------- 발행

def test_the_publisher_deletes_only_what_it_actually_sent(store):
    """보내기 전에 지우면 그 사이에 죽었을 때 사건이 **사라진다**."""
    with store.transaction() as tx:
        tx.enqueue("one", aggregate_id="a")
        tx.enqueue("two", aggregate_id="a")

    sent: list[dict] = []
    publisher = OutboxPublisher(send=lambda wire: sent.append(wire) or True)
    moved = publisher.pump(store)

    assert moved == 2
    assert len(sent) == 2
    assert store.drain() == ()


def test_a_failed_send_keeps_the_event_and_stops_so_order_survives(store):
    """뒤를 먼저 보내면 받는 쪽이 보는 순서가 뒤집힌다 — 그래서 **멈춘다**."""
    with store.transaction() as tx:
        tx.enqueue("first", aggregate_id="a")
        tx.enqueue("second", aggregate_id="a")

    publisher = OutboxPublisher(send=lambda wire: False)
    assert publisher.pump(store) == 0
    remaining = store.drain()
    assert len(remaining) == 2, "실패한 것은 남아 있어야 한다"
    assert remaining[0].event_type == "first"


def test_a_throwing_transport_is_a_degrade_not_a_crash(store):
    """발행 실패가 저장을 멈추면 안 된다(AI-C-05)."""
    with store.transaction() as tx:
        tx.enqueue("boom", aggregate_id="a")

    def explode(_wire):
        raise ConnectionError("브로커가 없다")

    publisher = OutboxPublisher(send=explode)
    assert publisher.pump(store) == 0                      # 예외가 밖으로 나오지 않는다
    assert len(store.drain()) == 1


def test_at_least_once_becomes_exactly_once_at_the_receiver():
    """같은 사건을 두 번 보내도 **물리 동작은 한 번**이다(AI-C-20 과 같은 규칙)."""
    inbox = InboxDeduplicator()
    wire = {"event_id": "evt-7-d1", "type": "deployment.applied"}

    assert inbox.accept(wire) is True
    assert inbox.accept(wire) is False, "두 번째는 처리하지 않는다"
    assert inbox.accept({"event_id": "evt-8-d1"}) is True


def test_an_event_without_an_identifier_is_not_silently_dropped():
    """접을 근거가 없는 것을 접으면 **보낸 적 없는 일이** 된다."""
    inbox = InboxDeduplicator()
    assert inbox.accept({"type": "no-id"}) is True
    assert inbox.accept({"type": "no-id"}) is True


def test_listing_facts_of_one_kind_does_not_leak_another(store):
    with store.transaction() as tx:
        tx.put("deployment", "d-1", {"v": 1})
        tx.put("assignment", "a-1", {"v": 2})

    kinds = dict(store.list("deployment"))
    assert kinds == {"d-1": {"v": 1}}
    assert dict(store.list("assignment")) == {"a-1": {"v": 2}}
