"""재동기화 커서의 계약 — `integration/event_cursor.py`.

implements: AI-O-06, AI-C-06, AI-C-03, AI-C-20
tests: 빠진 구간을 **말한다** · 뒤로 간 번호는 손실이 아니라 세대 교체다 ·
       중복은 버린다 · 쌓인 것은 순서대로만 나온다 · 미수신은 0 이 아니다
"""
from __future__ import annotations

from mission_runtime.integration.event_cursor import (
    CONTINUOUS,
    Cursor,
    DUPLICATE,
    EventCursor,
    GAP,
    NEVER_RECEIVED,
    RESET,
    resume_query,
)


def env(seq: int, boot: str = "b1", **extra) -> dict:
    return {"seq": seq, "boot_id": boot, "channel": "state", **extra}


def test_a_fresh_cursor_has_never_received_rather_than_zero():
    """**0 이면 「처음부터 다 받았는데 아무것도 없었다」로 읽힌다**(AI-O-06)."""
    cursor = EventCursor()
    assert cursor.cursor.is_fresh is True
    assert cursor.freshness() == NEVER_RECEIVED
    assert resume_query(cursor.cursor) == {}, "0 을 보내면 처음부터 다시 받는다"


def test_contiguous_sequence_flows_straight_through():
    cursor = EventCursor()
    assert cursor.receive(env(1)).state == CONTINUOUS
    delivery = cursor.receive(env(2))
    assert delivery.state == CONTINUOUS
    assert delivery.deliver[0]["seq"] == 2
    assert cursor.cursor.seq == 2


def test_a_skip_names_the_missing_range_instead_of_guessing():
    """「놓쳤다」만으로는 **무엇을** 다시 달라고 할지 알 수 없다."""
    cursor = EventCursor()
    cursor.receive(env(1))
    delivery = cursor.receive(env(5))

    assert delivery.state == GAP
    assert (delivery.missing_from, delivery.missing_to) == (2, 4)
    assert delivery.deliver == (), "빈 자리를 건너뛰고 내보내지 않는다"
    assert cursor.gaps_seen == [(2, 4)]


def test_a_backfilled_range_comes_out_in_order():
    """뒤를 먼저 내면 받는 쪽의 상태가 **거꾸로 간다**."""
    cursor = EventCursor()
    cursor.receive(env(1))
    cursor.receive(env(5))                                  # 2~4 가 빈다

    out = cursor.accept_backfill([env(3), env(2), env(4)])  # 순서 섞어서 넣어도
    assert [e["seq"] for e in out] == [2, 3, 4, 5]          # 순서대로 나온다
    assert cursor.cursor.seq == 5


def test_a_partial_backfill_waits_instead_of_leaking_a_hole():
    cursor = EventCursor()
    cursor.receive(env(1))
    cursor.receive(env(5))
    out = cursor.accept_backfill([env(3), env(4)])          # 2 가 아직 없다
    assert out == (), "빈 자리가 남아 있으면 아무것도 내지 않는다"
    assert cursor.accept_backfill([env(2)])[0]["seq"] == 2


def test_a_sequence_going_backwards_is_a_new_generation_not_a_loss():
    """발행자가 재시작하면 번호가 1 부터 다시 간다. 그걸 손실로 읽으면 **없는 구간을
    영원히 조른다.**"""
    cursor = EventCursor()
    cursor.receive(env(10, boot="b1"))
    delivery = cursor.receive(env(1, boot="b2"))

    assert delivery.state == RESET
    assert delivery.needs_snapshot is True
    assert delivery.reason == "publisher_restarted"
    assert cursor.resets_seen == 1


def test_the_same_boot_id_with_a_lower_number_is_a_duplicate_not_a_reset():
    """같은 세대에서 작은 번호가 오면 그건 재전달이다(AI-C-20)."""
    cursor = EventCursor()
    cursor.receive(env(1))
    cursor.receive(env(2))
    delivery = cursor.receive(env(2))

    assert delivery.state == DUPLICATE
    assert delivery.deliver == ()
    assert cursor.duplicates_dropped == 1


def test_a_snapshot_discards_the_pending_pieces():
    """스냅샷이 더 새것이다 — 조각을 들고 있으면 과거를 현재 위에 덮는다."""
    cursor = EventCursor()
    cursor.receive(env(1))
    cursor.receive(env(9))                                   # 2~8 이 빈다
    assert cursor.pending

    cursor.adopt_snapshot(boot_id="b1", seq=20)
    assert cursor.pending == {}
    assert cursor.cursor.seq == 20


def test_too_many_pending_pieces_asks_for_a_snapshot_instead_of_hoarding():
    """무한정 쌓으면 메모리가 늘고 화면은 영원히 과거에 머문다."""
    cursor = EventCursor(max_pending=3)
    cursor.receive(env(1))
    for seq in (5, 6, 7):
        cursor.receive(env(seq))
    delivery = cursor.receive(env(8))

    assert delivery.state == RESET
    assert delivery.reason == "too_many_pending"


def test_an_envelope_without_a_sequence_passes_through_unjudged():
    """번호가 없는 봉투는 순서를 **말하지 않는다** — 없는 판정을 지어내지 않는다."""
    cursor = EventCursor()
    delivery = cursor.receive({"channel": "metrics"})
    assert delivery.state == CONTINUOUS
    assert delivery.deliver and delivery.reason == "no_sequence"


def test_the_cursor_round_trips_through_a_query():
    cursor = Cursor(boot_id="b1", seq=42)
    assert Cursor.from_query(cursor.as_query()) == cursor
    assert Cursor.from_query(None).is_fresh is True


def test_the_cursor_knows_no_transport():
    """WS 든 SSE 든 같은 판정이어야 한다 — 전송을 알면 그 둘이 갈린다(AI-C-06)."""
    import inspect

    from mission_runtime.integration import event_cursor

    source = inspect.getsource(event_cursor)
    for word in ("websocket", "WebSocket", "requests.", "socket.", "http.client"):
        assert word not in source, f"전송을 안다: {word}"
