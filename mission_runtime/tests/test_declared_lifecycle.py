"""선언된 업무 수명주기의 계약 — `contracts/declared_lifecycle.py`.

implements: AI-C-15, AI-C-01, AI-C-19, AI-L-03, AI-B-12
tests: 틀린 선언은 **적재 시점에** 터진다 · 요청자는 자기 요청을 승인하지 못한다 ·
       요청과 자산은 서로를 끌고 가지 않는다 · 코어에 업무 단어가 없다 ·
       작성자 없는 전이는 거절된다
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.declared_lifecycle import (
    REASON_DUPLICATE_INSTANCE,
    REASON_MISSING_FIELD,
    REASON_NEEDS_APPROVAL,
    REASON_NO_ACTOR,
    REASON_NO_EVIDENCE,
    REASON_NOT_DECLARED,
    REASON_SELF_APPROVAL,
    REASON_TERMINAL,
    REASON_UNKNOWN_LIFECYCLE,
    REASON_WRONG_STATE,
    Instance,
    LifecycleError,
    LifecycleRefusal,
    LifecycleRegistry,
    declaration_from_mapping,
    load_lifecycles,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "profiles" / "lifecycles.logistics.example.json"


def minimal(**over) -> dict:
    raw = {
        "lifecycle_id": "req",
        "initial": "open",
        "states": ["open", "done"],
        "terminal": ["done"],
        "transitions": [{"name": "finish", "from": "open", "to": "done"}],
    }
    raw.update(over)
    return raw


def registry(**over) -> LifecycleRegistry:
    made = LifecycleRegistry(clock=lambda: 1000.0)
    made.declare(declaration_from_mapping(minimal(**over)))
    return made


# --------------------------------------------------------------- 선언 검증

def test_an_initial_state_that_is_not_in_the_states_blows_up():
    with pytest.raises(LifecycleError):
        declaration_from_mapping(minimal(initial="nope"))


def test_a_transition_pointing_at_an_undeclared_state_blows_up():
    """조용히 좁은 쪽을 쓰면 **전이 하나가 말없이 사라진다.**"""
    with pytest.raises(LifecycleError):
        declaration_from_mapping(minimal(
            transitions=[{"name": "finish", "from": "open", "to": "ghost"}]))


def test_a_terminal_state_with_a_way_out_is_not_terminal():
    """둘 다 적어 두면 어느 쪽이 참인지 코드와 화면이 다르게 읽는다."""
    with pytest.raises(LifecycleError):
        declaration_from_mapping(minimal(
            states=["open", "done"], terminal=["done"],
            transitions=[{"name": "finish", "from": "open", "to": "done"},
                         {"name": "reopen", "from": "done", "to": "open"}]))


def test_a_state_no_transition_can_reach_blows_up():
    """닿을 수 없는 상태는 **의도한 흐름이 빠졌다**는 신호다."""
    with pytest.raises(LifecycleError):
        declaration_from_mapping(minimal(states=["open", "done", "orphan"]))


def test_duplicate_transition_names_blow_up():
    with pytest.raises(LifecycleError):
        declaration_from_mapping(minimal(
            transitions=[{"name": "finish", "from": "open", "to": "done"},
                         {"name": "finish", "from": "open", "to": "done"}]))


def test_a_lifecycle_with_no_transitions_blows_up():
    with pytest.raises(LifecycleError):
        declaration_from_mapping(minimal(states=["open"], terminal=[],
                                         transitions=[]))


def test_a_missing_required_key_names_the_key():
    with pytest.raises(LifecycleError) as raised:
        declaration_from_mapping({"lifecycle_id": "x", "initial": "a"})
    assert "states" in str(raised.value)


# --------------------------------------------------------------- 예시 선언

def test_the_shipped_example_file_loads():
    """새 현장의 업무 흐름은 **파일 한 장**이다(AI-C-15)."""
    made = load_lifecycles(EXAMPLE)
    assert set(made) == {"outbound_request", "pallet_asset"}
    assert made["outbound_request"].is_terminal("closed")
    assert made["pallet_asset"].is_terminal("retired")


def test_the_example_puts_approval_on_a_transition_not_on_a_state():
    made = load_lifecycles(EXAMPLE)
    gated = [t.name for t in made["outbound_request"].transitions
             if t.requires_approval]
    assert gated == ["approve", "reject"]
    assert all(not t.requires_approval for t in made["pallet_asset"].transitions), \
        "승인은 요청의 규칙이고 자산의 규칙이 아니다"


def test_the_core_knows_none_of_the_domain_words():
    """**이 모듈이 선언으로 만들어진 이유.** 업무 단어가 코어에 들어오면
    두 번째 현장에서 분기문이 생긴다(절대 준수 원칙 #3)."""
    import inspect

    from mission_runtime.contracts import declared_lifecycle

    source = inspect.getsource(declared_lifecycle)
    for word in ("pallet", "파렛트", "outbound", "picking", "carrier",
                 "warehouse", "in_transit", "restock"):
        assert word not in source, f"도메인 단어가 코어에 있다: {word}"


# --------------------------------------------------------------- 시작

def test_a_change_with_no_author_is_refused():
    """원본 선언과 사람이 고친 값이 끝까지 구분되어야 한다(AI-L-03)."""
    made = registry()
    assert isinstance(made.start("req", "R-1", actor="", evidence_ref="ev"),
                      LifecycleRefusal)
    assert made.refusals[-1].reason == REASON_NO_ACTOR

    outcome = made.start("req", "R-1", actor="op", evidence_ref="")
    assert isinstance(outcome, LifecycleRefusal) and outcome.reason == REASON_NO_EVIDENCE


def test_an_undeclared_lifecycle_is_refused_with_its_name():
    made = registry()
    outcome = made.start("nope", "R-1", actor="op", evidence_ref="ev")
    assert isinstance(outcome, LifecycleRefusal)
    assert outcome.reason == REASON_UNKNOWN_LIFECYCLE and outcome.detail == "nope"


def test_the_same_instance_id_twice_is_refused_not_restarted():
    """다시 시작하면 **앞선 진행이 사라진다.**"""
    made = registry()
    made.start("req", "R-1", actor="op", evidence_ref="ev")
    outcome = made.start("req", "R-1", actor="op", evidence_ref="ev")
    assert isinstance(outcome, LifecycleRefusal)
    assert outcome.reason == REASON_DUPLICATE_INSTANCE


def test_starting_records_who_asked():
    made = registry()
    opened = made.start("req", "R-1", actor="requester", evidence_ref="ev")
    assert isinstance(opened, Instance)
    assert opened.state == "open" and opened.requested_by == "requester"


# --------------------------------------------------------------- 전이

def test_a_transition_that_was_never_declared_is_refused():
    made = registry()
    made.start("req", "R-1", actor="op", evidence_ref="ev")
    outcome = made.advance("R-1", "teleport", actor="op", evidence_ref="ev")
    assert isinstance(outcome, LifecycleRefusal)
    assert outcome.reason == REASON_NOT_DECLARED


def test_a_declared_transition_from_the_wrong_state_is_refused():
    made = LifecycleRegistry()
    made.declare(declaration_from_mapping(minimal(
        states=["open", "mid", "done"], terminal=["done"],
        transitions=[{"name": "step", "from": "open", "to": "mid"},
                     {"name": "finish", "from": "mid", "to": "done"}])))
    made.start("req", "R-1", actor="op", evidence_ref="ev")

    outcome = made.advance("R-1", "finish", actor="op", evidence_ref="ev")
    assert isinstance(outcome, LifecycleRefusal)
    assert outcome.reason == REASON_WRONG_STATE


def test_a_terminal_instance_does_not_move_again():
    made = registry()
    made.start("req", "R-1", actor="op", evidence_ref="ev")
    made.advance("R-1", "finish", actor="op", evidence_ref="ev")

    outcome = made.advance("R-1", "finish", actor="op", evidence_ref="ev")
    assert isinstance(outcome, LifecycleRefusal) and outcome.reason == REASON_TERMINAL


def test_a_required_value_that_did_not_come_is_named():
    made = LifecycleRegistry()
    made.declare(declaration_from_mapping(minimal(
        transitions=[{"name": "finish", "from": "open", "to": "done",
                      "requires": ["carrier"]}])))
    made.start("req", "R-1", actor="op", evidence_ref="ev")

    outcome = made.advance("R-1", "finish", actor="op", evidence_ref="ev")
    assert isinstance(outcome, LifecycleRefusal)
    assert outcome.reason == REASON_MISSING_FIELD and outcome.detail == "carrier"

    moved = made.advance("R-1", "finish", actor="op", evidence_ref="ev",
                         values={"carrier": "truck-2"})
    assert isinstance(moved, Instance) and moved.state == "done"
    assert moved.history[-1].values["carrier"] == "truck-2"


def test_advancing_returns_a_new_instance_and_leaves_the_old_snapshot_alone():
    """화면이 들고 있는 스냅샷을 제자리에서 바꿀 수 없다(AI-B-12 와 같은 규칙)."""
    made = registry()
    before = made.start("req", "R-1", actor="op", evidence_ref="ev")
    after = made.advance("R-1", "finish", actor="op", evidence_ref="ev")

    assert before.state == "open" and after.state == "done"
    assert len(after.history) == len(before.history) + 1


# --------------------------------------------------------------- 승인

def approval_registry() -> LifecycleRegistry:
    made = LifecycleRegistry(clock=lambda: 1000.0)
    made.declare(declaration_from_mapping(minimal(
        transitions=[{"name": "finish", "from": "open", "to": "done",
                      "requires_approval": True}])))
    made.start("req", "R-1", actor="requester", evidence_ref="ev")
    return made


def test_a_gated_transition_without_an_approver_is_refused():
    outcome = approval_registry().advance("R-1", "finish", actor="requester",
                                          evidence_ref="ev")
    assert isinstance(outcome, LifecycleRefusal)
    assert outcome.reason == REASON_NEEDS_APPROVAL


def test_the_requester_cannot_approve_their_own_request():
    """같은 이름이 양쪽에 적히면 그 승인 기록은 **아무것도 보증하지 않는다.**"""
    outcome = approval_registry().advance("R-1", "finish", actor="requester",
                                          evidence_ref="ev",
                                          approved_by="requester")
    assert isinstance(outcome, LifecycleRefusal)
    assert outcome.reason == REASON_SELF_APPROVAL


def test_the_actor_cannot_approve_themselves_even_if_someone_else_asked():
    outcome = approval_registry().advance("R-1", "finish", actor="clerk",
                                          evidence_ref="ev", approved_by="clerk")
    assert isinstance(outcome, LifecycleRefusal)
    assert outcome.reason == REASON_SELF_APPROVAL


def test_an_approval_by_another_person_passes_and_is_recorded():
    moved = approval_registry().advance("R-1", "finish", actor="clerk",
                                        evidence_ref="ev", approved_by="manager")
    assert isinstance(moved, Instance) and moved.state == "done"
    assert moved.history[-1].approved_by == "manager"
    assert moved.history[-1].actor == "clerk", "실행한 사람과 승인한 사람은 다른 칸이다"


# --------------------------------------------------------------- 독립 수명주기

def linked_pair() -> LifecycleRegistry:
    """예시 선언 그대로 요청 하나와 자산 하나를 연결한다."""
    made = LifecycleRegistry(load_lifecycles(EXAMPLE), clock=lambda: 1000.0)
    made.start("outbound_request", "REQ-1", actor="requester", evidence_ref="ev-1")
    made.start("pallet_asset", "PAL-7", actor="op", evidence_ref="ev-2")
    made.link("REQ-1", "PAL-7")
    return made


def test_linking_is_mutual_and_readable_from_both_sides():
    made = linked_pair()
    assert [other.instance_id for other in made.linked("REQ-1")] == ["PAL-7"]
    assert [other.instance_id for other in made.linked("PAL-7")] == ["REQ-1"]


def test_closing_the_request_does_not_move_the_asset():
    """**이것이 둘을 나눈 이유다.** 합치면 "요청은 끝났는데 물건이 어디 있는지" 를
    적을 칸이 없어진다."""
    made = linked_pair()
    made.advance("REQ-1", "approve", actor="clerk", evidence_ref="ev",
                 approved_by="manager", values={"asset_ref": "PAL-7"})
    made.advance("REQ-1", "pick", actor="clerk", evidence_ref="ev")
    made.advance("REQ-1", "ship", actor="clerk", evidence_ref="ev",
                 values={"carrier": "truck-2"})
    made.advance("REQ-1", "close", actor="clerk", evidence_ref="ev")

    assert made.get("REQ-1").state == "closed"
    assert made.get("PAL-7").state == "stored", "요청이 자산을 끌고 가지 않는다"
    assert made.linked("PAL-7")[0].state == "closed", "참조는 끊기지 않는다"


def test_moving_the_asset_does_not_move_the_request():
    made = linked_pair()
    made.advance("PAL-7", "allocate", actor="op", evidence_ref="ev",
                 values={"request_ref": "REQ-1"})
    made.advance("PAL-7", "dispatch", actor="op", evidence_ref="ev")

    assert made.get("PAL-7").state == "in_transit"
    assert made.get("REQ-1").state == "requested"


def test_a_retired_asset_leaves_the_request_history_intact():
    made = linked_pair()
    for name, values in (("allocate", {"request_ref": "REQ-1"}), ("dispatch", {}),
                         ("arrive", {}), ("inspect", {}),
                         ("retire", {"reason_text": "파손"})):
        made.advance("PAL-7", name, actor="op", evidence_ref="ev", values=values)

    assert made.get("PAL-7").state == "retired"
    assert made.available("PAL-7") == (), "종결이면 할 수 있는 일이 없다"
    assert made.available("REQ-1"), "요청은 아직 할 일이 남아 있다"


# --------------------------------------------------------------- 보기

def test_the_view_lists_what_can_be_done_but_does_not_choose():
    """버튼을 만드는 것은 화면이고 **고르는 것은 사람**이다(AI-C-19)."""
    made = linked_pair()
    names = {t.name for t in made.available("REQ-1")}
    assert names == {"approve", "reject"}


def test_the_snapshot_says_whether_a_state_is_terminal():
    made = linked_pair()
    rows = made.snapshot()
    assert rows["REQ-1"][dd.WORK_LIFECYCLE_STATE] == "requested"
    assert rows["REQ-1"]["terminal"] is False
    assert rows["REQ-1"][dd.LINKED_INSTANCES] == ["PAL-7"]
    assert rows["REQ-1"][dd.WORK_LIFECYCLE_ID] == "outbound_request"


def test_refusals_are_counted_so_zero_rejections_is_a_measurement():
    made = registry()
    made.advance("ghost", "finish", actor="op", evidence_ref="ev")
    assert len(made.refusals) == 1
