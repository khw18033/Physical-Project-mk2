"""공간 그래프 통행·충전 예약의 계약 — `runtime/space_reservation.py`.

implements: AI-B-04, AI-B-06, AI-C-02, AI-C-05, AI-C-19, AI-O-05
tests: 방향이 수용량을 이긴다 · 중간에 막히면 **하나도 쥐지 않는다** · 지나온 칸을
       놓는다 · 충전기는 태그다 · 프레임이 겹치면 적재 시점에 터진다 ·
       점유의 주인은 장부 하나다 · 예약은 명령이 아니다
"""
from __future__ import annotations

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.runtime.reservation import (
    REASON_CAPACITY,
    REASON_HELD_BY_OTHER,
    Lease,
    Refusal,
    ReservationLedger,
)
from mission_runtime.runtime.space_reservation import (
    CHARGER_TAG,
    REASON_EMPTY_ROUTE,
    REASON_HEAD_ON,
    REASON_NOT_A_CHARGER,
    REASON_NOT_ADJACENT,
    REASON_UNKNOWN_NODE,
    GraphEdge,
    GraphNode,
    SpaceGraph,
    SpaceGraphError,
    TrafficReservation,
    edge_resource,
    node_resource,
)


def corridor(**over) -> SpaceGraph:
    """a — b — c 한 줄 복도. 가장 작은데 **마주 섬이 일어나는** 모양이다."""
    graph = SpaceGraph(over.pop("frame_id", "site-local"))
    for node_id in ("a", "b", "c"):
        graph.declare_node(GraphNode(node_id, capacity=over.pop(f"cap_{node_id}", 1)))
    graph.declare_edge(GraphEdge("a", "b", capacity=over.pop("cap_ab", 1)))
    graph.declare_edge(GraphEdge("b", "c", capacity=over.pop("cap_bc", 1)))
    return graph


# --------------------------------------------------------------- 선언

def test_an_edge_to_a_place_that_was_never_declared_is_refused_at_load():
    """없는 자리로 가는 길을 받아 두면 **경로 검증은 통과하고 실행만 실패한다.**"""
    graph = SpaceGraph("site-local", nodes=[GraphNode("a")])
    with pytest.raises(SpaceGraphError):
        graph.declare_edge(GraphEdge("a", "nowhere"))


def test_an_edge_from_a_place_to_itself_is_refused():
    graph = SpaceGraph("site-local", nodes=[GraphNode("a")])
    with pytest.raises(SpaceGraphError):
        graph.declare_edge(GraphEdge("a", "a"))


def test_the_same_place_name_in_another_frame_blows_up_at_declaration_time():
    """창고 둘이 모두 `dock-1` 을 선언하고 한 장부에 들어오면 서로 관계 없는 두
    자리가 같은 자원으로 점유를 다툰다 — 그 실패는 로그에 이유가 없다(AI-C-02)."""
    ledger = ReservationLedger()
    TrafficReservation(corridor(frame_id="site-A"), ledger)

    with pytest.raises(SpaceGraphError) as raised:
        TrafficReservation(corridor(frame_id="site-B"), ledger)
    assert "frame" in str(raised.value)


def test_two_graphs_in_the_same_frame_share_the_ledger_without_complaint():
    """같은 현장을 두 조각으로 선언하는 것은 **정상**이다."""
    ledger = ReservationLedger()
    TrafficReservation(corridor(frame_id="site-A"), ledger)
    TrafficReservation(corridor(frame_id="site-A"), ledger)
    assert node_resource("a") in ledger.declared()


def test_a_charger_is_a_tag_not_a_type():
    """벤더 열거형이 아니라 선언 데이터다(AI-C-18) — 새 충전기는 한 줄이다."""
    graph = corridor()
    graph.declare_node(GraphNode("dock", tags=frozenset({CHARGER_TAG})))
    assert graph.chargers() == ("dock",)


# --------------------------------------------------------------- 경로 검증

def test_a_route_of_one_place_is_not_a_route():
    traffic = TrafficReservation(corridor())
    outcome = traffic.hold_route(["a"], holder="r1")
    assert isinstance(outcome, Refusal) and outcome.reason == REASON_EMPTY_ROUTE


def test_a_place_that_was_never_declared_is_named_in_the_refusal():
    traffic = TrafficReservation(corridor())
    outcome = traffic.hold_route(["a", "ghost"], holder="r1")
    assert isinstance(outcome, Refusal)
    assert outcome.reason == REASON_UNKNOWN_NODE
    assert outcome.resource_id == node_resource("ghost")


def test_a_jump_between_places_with_no_edge_is_refused_not_interpolated():
    """없는 길을 "가장 비슷한 길" 로 바꾸면 **로봇이 벽으로 간다.**"""
    traffic = TrafficReservation(corridor())
    outcome = traffic.hold_route(["a", "c"], holder="r1")
    assert isinstance(outcome, Refusal) and outcome.reason == REASON_NOT_ADJACENT


def test_driving_the_wrong_way_down_a_oneway_edge_is_refused():
    graph = SpaceGraph("site-local", nodes=[GraphNode("a"), GraphNode("b")])
    graph.declare_edge(GraphEdge("a", "b", oneway=True))
    traffic = TrafficReservation(graph)

    assert not isinstance(traffic.hold_route(["a", "b"], holder="r1"), Refusal)
    outcome = traffic.hold_route(["b", "a"], holder="r2")
    assert isinstance(outcome, Refusal) and outcome.reason == REASON_NOT_ADJACENT


def test_a_oneway_edge_has_no_neighbor_backwards():
    graph = SpaceGraph("site-local", nodes=[GraphNode("a"), GraphNode("b")])
    graph.declare_edge(GraphEdge("a", "b", oneway=True))
    assert graph.neighbors("a") == ("b",)
    assert graph.neighbors("b") == ()


# --------------------------------------------------------------- 통행

def test_holding_a_route_takes_both_the_places_and_the_segments():
    """자리만 잡고 구간을 안 잡으면 **복도에서 스친다.**"""
    traffic = TrafficReservation(corridor())
    hold = traffic.hold_route(["a", "b", "c"], holder="r1")

    assert not isinstance(hold, Refusal)
    assert set(hold.resource_ids) == {
        node_resource("a"), node_resource("b"), node_resource("c"),
        edge_resource("a", "b"), edge_resource("b", "c")}


def test_each_square_carries_its_own_fencing_token():
    """실제로 들어가는 쪽은 **자기 칸의 번호**를 본다."""
    traffic = TrafficReservation(corridor())
    hold = traffic.hold_route(["a", "b"], holder="r1")
    assert hold.token_for(node_resource("a")) >= 1
    assert hold.token_for("edge:nope") is None


def test_an_opposing_route_is_refused_even_when_capacity_remains():
    """**이 모듈이 있는 이유.** 수용량 2 인 복도를 양쪽에서 들어오면 둘 다
    통과 판정이 나지만 실제로는 마주 서서 둘 다 못 간다."""
    traffic = TrafficReservation(corridor(cap_ab=2, cap_a=2, cap_b=2))
    assert not isinstance(traffic.hold_route(["a", "b"], holder="r1"), Refusal)

    outcome = traffic.hold_route(["b", "a"], holder="r2")
    assert isinstance(outcome, Refusal)
    assert outcome.reason == REASON_HEAD_ON and outcome.held_by == "r1"


def test_the_same_direction_fits_as_many_as_the_declaration_allows():
    """방향이 같으면 막지 않는다 — 막으면 선언한 수용량이 거짓이 된다."""
    traffic = TrafficReservation(corridor(cap_ab=2, cap_a=2, cap_b=2))
    assert not isinstance(traffic.hold_route(["a", "b"], holder="r1"), Refusal)
    assert not isinstance(traffic.hold_route(["a", "b"], holder="r2"), Refusal)

    third = traffic.hold_route(["a", "b"], holder="r3")
    assert isinstance(third, Refusal) and third.reason == REASON_CAPACITY


def test_a_route_blocked_halfway_leaves_nothing_held():
    """**전부 아니면 전무.** 셋 중 둘만 쥐고 기다리면 마주 오는 쪽이 남은 하나를
    쥐고 서로를 기다린다 — 그 교착은 어느 쪽 로그에도 이유가 없다."""
    traffic = TrafficReservation(corridor())
    traffic.hold_route(["b", "c"], holder="blocker")

    outcome = traffic.hold_route(["a", "b", "c"], holder="r1")
    assert isinstance(outcome, Refusal) and outcome.reason == REASON_HELD_BY_OTHER
    assert "r1" not in traffic.ledger.holders(node_resource("a")), "쥐고 있으면 교착이다"
    assert traffic.ledger.free_capacity(node_resource("a")) == 1


def test_two_crossing_routes_cannot_deadlock_because_the_order_is_fixed():
    """잡는 순서가 정렬 순이면 **순환 대기가 구조적으로 생기지 않는다.**

    한쪽은 전부 잡고 다른 쪽은 아무것도 못 잡는다 — 둘이 서로를 기다리는 상태가
    만들어지지 않는다는 것이 요점이고, 누가 이기는지는 요점이 아니다.
    """
    graph = SpaceGraph("site-local")
    for node_id in ("n", "s", "e", "w", "x"):
        graph.declare_node(GraphNode(node_id))
    for a, b in (("n", "x"), ("x", "s"), ("w", "x"), ("x", "e")):
        graph.declare_edge(GraphEdge(a, b))
    traffic = TrafficReservation(graph)

    first = traffic.hold_route(["n", "x", "s"], holder="r1")
    second = traffic.hold_route(["w", "x", "e"], holder="r2")

    held = [outcome for outcome in (first, second) if not isinstance(outcome, Refusal)]
    refused = [outcome for outcome in (first, second) if isinstance(outcome, Refusal)]
    assert len(held) == 1 and len(refused) == 1
    assert traffic.ledger.holders(node_resource("x")) == (held[0].holder,)


def test_releasing_a_route_lets_the_next_one_through():
    """안 놓으면 그 길은 **영원히 비지 않는다.**"""
    traffic = TrafficReservation(corridor())
    hold = traffic.hold_route(["a", "b"], holder="r1")
    traffic.release(hold)

    assert traffic.ledger.holders(node_resource("a")) == ()
    assert not isinstance(traffic.hold_route(["b", "a"], holder="r2"), Refusal)


def test_releasing_the_part_already_driven_lets_the_one_behind_in():
    """긴 경로를 끝까지 쥐고 있으면 **뒤차가 10 분을 기다린다.**"""
    traffic = TrafficReservation(corridor())
    hold = traffic.hold_route(["a", "b", "c"], holder="r1")

    shortened = traffic.release_passed(hold, now_at="b")
    assert not isinstance(shortened, Refusal)
    assert shortened.route == ("b", "c")
    assert traffic.ledger.holders(node_resource("a")) == ()
    assert traffic.ledger.holders(node_resource("b")) == ("r1",), "서 있는 자리는 쥔다"
    assert traffic.ledger.holders(edge_resource("b", "c")) == ("r1",)


def test_a_position_outside_the_route_is_refused_rather_than_guessed():
    """위치는 **받아서 쓰는 값**이다 — 우리가 authoritative 하게 알지 못한다."""
    traffic = TrafficReservation(corridor())
    hold = traffic.hold_route(["a", "b"], holder="r1")
    outcome = traffic.release_passed(hold, now_at="c")
    assert isinstance(outcome, Refusal) and outcome.reason == REASON_UNKNOWN_NODE


def test_confirming_happens_before_entering_not_when_planning():
    traffic = TrafficReservation(corridor())
    hold = traffic.hold_route(["a", "b"], holder="r1")
    confirmed = traffic.confirm(hold)
    assert not isinstance(confirmed, Refusal)
    assert all(lease.state == "active" for lease in confirmed.leases)


# --------------------------------------------------------------- 충전

def test_a_charger_is_held_through_the_same_ledger_with_no_new_judgement():
    graph = corridor()
    graph.declare_node(GraphNode("dock", tags=frozenset({CHARGER_TAG})))
    traffic = TrafficReservation(graph)

    lease = traffic.hold_charger("dock", holder="r1")
    assert isinstance(lease, Lease) and lease.resource_id == node_resource("dock")


def test_a_full_charger_says_when_it_frees_up_instead_of_just_failing():
    """"실패" 하나로 접으면 운영자가 **기다릴지 다른 데로 갈지** 모른다."""
    graph = corridor()
    graph.declare_node(GraphNode("dock", tags=frozenset({CHARGER_TAG})))
    traffic = TrafficReservation(graph)

    traffic.hold_charger("dock", holder="r1", ttl_s=600.0)
    outcome = traffic.hold_charger("dock", holder="r2")
    assert isinstance(outcome, Refusal)
    assert outcome.reason == REASON_HELD_BY_OTHER
    assert outcome.retry_after_s and outcome.retry_after_s > 0


def test_a_place_that_is_not_a_charger_cannot_be_held_for_a_charging_term():
    """충전 기한은 통행 기한보다 훨씬 길다 — 아무 자리나 그 기한으로 쥐면
    **그 길이 10 분 막힌다.**"""
    traffic = TrafficReservation(corridor())
    outcome = traffic.hold_charger("b", holder="r1")
    assert isinstance(outcome, Refusal) and outcome.reason == REASON_NOT_A_CHARGER


def test_two_bays_at_one_dock_are_a_capacity_not_two_names():
    graph = corridor()
    graph.declare_node(GraphNode("dock", capacity=2, tags=frozenset({CHARGER_TAG})))
    traffic = TrafficReservation(graph)

    assert isinstance(traffic.hold_charger("dock", holder="r1"), Lease)
    assert isinstance(traffic.hold_charger("dock", holder="r2"), Lease)
    assert isinstance(traffic.hold_charger("dock", holder="r3"), Refusal)


# --------------------------------------------------------------- 경계

def test_the_ledger_is_the_only_owner_of_occupancy():
    """방향 색인은 **파생**이다. 장부에서 사라진 점유의 방향은 따라 사라진다 —
    같은 사실을 두 곳이 각자 적으면 어긋나는 날 둘이 다른 답을 말한다."""
    now = [1000.0]
    ledger = ReservationLedger(clock=lambda: now[0])
    traffic = TrafficReservation(corridor(), ledger)
    traffic.hold_route(["a", "b"], holder="r1", ttl_s=5.0)

    now[0] += 10.0                                    # lease 가 만료됐다
    ledger.expire_due()

    assert traffic.occupancy()[edge_resource("a", "b")].get(dd.ROUTE_DIRECTION) is None
    assert not isinstance(traffic.hold_route(["b", "a"], holder="r2"), Refusal)


def test_a_declared_place_with_nobody_on_it_is_still_in_the_view():
    """배치된 것이 없는 자리를 목록에서 빼면 **유휴와 고장이 같아 보인다**(AI-O-05)."""
    traffic = TrafficReservation(corridor())
    snapshot = traffic.occupancy()
    assert node_resource("c") in snapshot
    assert snapshot[node_resource("c")]["held"] == 0


def test_an_undeclared_place_is_none_not_zero():
    """미측정 ≠ 0. 없는 자리의 여유를 0 으로 적으면 **꽉 찬 것처럼 보인다.**"""
    traffic = TrafficReservation(corridor())
    assert traffic.free_at("ghost") is None
    assert traffic.free_at("a") == 1


def test_a_reservation_is_not_a_command():
    """쥐었다고 로봇이 움직이지 않는다 — 명령 발급은 우리 것이 아니다(AI-C-19)."""
    import inspect

    from mission_runtime.runtime import space_reservation

    source = inspect.getsource(space_reservation)
    for word in ("PhysicalCommand", "execute(", "publish(", "import paho", "mqtt"):
        assert word not in source, f"제어 경계를 넘는다: {word}"


def test_refusals_are_counted_so_zero_conflicts_is_a_measurement():
    traffic = TrafficReservation(corridor())
    traffic.hold_route(["a", "b"], holder="r1")
    traffic.hold_route(["b", "a"], holder="r2")
    assert [refusal.reason for refusal in traffic.refusals] == [REASON_HEAD_ON]
