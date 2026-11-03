"""implements: AI-L-03, AI-S-08
covers: declared data is never overwritten, edits survive a restart, a reset is
        recorded rather than erased, anonymous edits are refused
"""

import json
import sys
from pathlib import Path

import pytest

CONSOLE_DIR = Path(__file__).resolve().parents[1] / "tools" / "fms_console"
if str(CONSOLE_DIR) not in sys.path:
    sys.path.insert(0, str(CONSOLE_DIR))

from overlay import (  # noqa: E402
    ACTION_RESET,
    ACTION_SET,
    KIND_CUE_CORRECTION,
    KIND_PLACEMENT,
    KIND_SURVEY,
    KNOWN_KINDS,
    OVERLAY_FORMAT_VERSION,
    EditEntry,
    OperatorOverlay,
    OverlayError,
)


@pytest.fixture()
def overlay(tmp_path):
    return OperatorOverlay(path=tmp_path / "edits.json")


# --- 없는 장부는 오류가 아니다 ----------------------------------------------


def test_a_missing_file_is_an_empty_ledger_not_an_error(tmp_path):
    board = OperatorOverlay(path=tmp_path / "never-written.json")

    assert board.entries() == ()
    assert board.stats()["exists"] is False


def test_a_corrupt_file_is_refused_rather_than_silently_emptied(tmp_path):
    path = tmp_path / "edits.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(OverlayError):
        OperatorOverlay(path=path)


def test_a_file_without_an_entries_list_is_refused(tmp_path):
    path = tmp_path / "edits.json"
    path.write_text(json.dumps({"format_version": "1"}), encoding="utf-8")

    with pytest.raises(OverlayError):
        OperatorOverlay(path=path)


# --- 수정은 디스크에 남고 재시작을 견딘다 -----------------------------------


def test_an_edit_survives_a_restart(tmp_path):
    path = tmp_path / "edits.json"
    first = OperatorOverlay(path=path)
    first.record(KIND_PLACEMENT, "mt4", {"at": {"x": 20.0, "y": 30.0}},
                 actor="admin", reason="현장 실측", scope="N4-2F-W")

    restarted = OperatorOverlay(path=path)

    assert restarted.current_payloads(KIND_PLACEMENT)["mt4"]["at"] == {"x": 20.0, "y": 30.0}
    assert restarted.current_payloads(KIND_PLACEMENT)["mt4"]["actor"] == "admin"


def test_the_latest_edit_wins_and_the_earlier_one_is_kept(overlay):
    overlay.record(KIND_PLACEMENT, "mt4", {"at": {"x": 1.0, "y": 1.0}}, actor="admin")
    overlay.record(KIND_PLACEMENT, "mt4", {"at": {"x": 2.0, "y": 2.0}}, actor="admin")

    assert overlay.current_payloads(KIND_PLACEMENT)["mt4"]["at"] == {"x": 2.0, "y": 2.0}
    assert len(overlay.history(KIND_PLACEMENT, "mt4")) == 2, "이력이 덮여 사라지면 되짚을 수 없다"


def test_the_file_is_written_atomically_leaving_no_temporary_behind(tmp_path):
    path = tmp_path / "edits.json"
    board = OperatorOverlay(path=path)
    board.record(KIND_SURVEY, "z/wall", {"value": 1.0}, actor="admin")

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != path.name]

    assert leftovers == []
    assert json.loads(path.read_text(encoding="utf-8"))["format_version"] == OVERLAY_FORMAT_VERSION


# --- 되돌림은 삭제가 아니다 -------------------------------------------------


def test_a_reset_restores_the_declared_value_but_keeps_the_trail(overlay):
    overlay.record(KIND_PLACEMENT, "pi6", {"at": {"x": 9.0, "y": 9.0}}, actor="admin")

    overlay.reset(KIND_PLACEMENT, "pi6", actor="admin", reason="선언으로 복귀")

    assert "pi6" not in overlay.current_payloads(KIND_PLACEMENT)
    trail = overlay.history(KIND_PLACEMENT, "pi6")
    assert [row["action"] for row in trail] == [ACTION_SET, ACTION_RESET]


def test_an_edit_after_a_reset_becomes_active_again(overlay):
    overlay.record(KIND_PLACEMENT, "pi6", {"at": {"x": 1.0, "y": 1.0}}, actor="admin")
    overlay.reset(KIND_PLACEMENT, "pi6", actor="admin")
    overlay.record(KIND_PLACEMENT, "pi6", {"at": {"x": 3.0, "y": 3.0}}, actor="admin")

    assert overlay.current_payloads(KIND_PLACEMENT)["pi6"]["at"] == {"x": 3.0, "y": 3.0}


# --- 거절하는 것 -------------------------------------------------------------


def test_an_edit_with_no_author_is_refused(overlay):
    """누가 고쳤는지 모르는 수정은 되짚을 수 없다(AI-L-03)."""
    with pytest.raises(OverlayError):
        overlay.record(KIND_PLACEMENT, "pi6", {"at": {"x": 1.0, "y": 1.0}}, actor="")


def test_an_unknown_kind_is_refused_rather_than_stored(overlay):
    with pytest.raises(OverlayError):
        overlay.record("whatever_new_thing", "x", {}, actor="admin")

    assert overlay.entries() == ()


def test_an_empty_target_is_refused(overlay):
    with pytest.raises(OverlayError):
        overlay.record(KIND_PLACEMENT, "", {"at": {}}, actor="admin")


def test_a_reset_also_requires_an_author(overlay):
    with pytest.raises(OverlayError):
        overlay.reset(KIND_PLACEMENT, "pi6", actor="")


# --- 종류별로 갈라서 읽는다 -------------------------------------------------


def test_kinds_do_not_leak_into_each_other(overlay):
    overlay.record(KIND_PLACEMENT, "pi6", {"at": {"x": 1.0, "y": 1.0}}, actor="admin")
    overlay.record(KIND_SURVEY, "N4-1F-W/wall", {"value": 29.4}, actor="admin")
    overlay.record(KIND_CUE_CORRECTION, "obj-1", {"cue_name": "semantic_class"}, actor="admin")

    assert set(overlay.current(KIND_PLACEMENT)) == {"pi6"}
    assert set(overlay.current(KIND_SURVEY)) == {"N4-1F-W/wall"}
    assert set(overlay.current(KIND_CUE_CORRECTION)) == {"obj-1"}


def test_history_is_in_the_order_the_edits_arrived(overlay):
    overlay.record(KIND_PLACEMENT, "a", {"at": {}}, actor="admin", reason="first")
    overlay.record(KIND_PLACEMENT, "a", {"at": {}}, actor="admin", reason="second")

    assert [row["reason"] for row in overlay.history(KIND_PLACEMENT, "a")] == ["first", "second"]


def test_stats_report_every_known_kind_even_when_unused(overlay):
    overlay.record(KIND_PLACEMENT, "pi6", {"at": {}}, actor="admin")

    active = overlay.stats()["active_by_kind"]

    assert set(active) == set(KNOWN_KINDS), "쓰지 않은 종류를 생략하면 0 과 '없다'가 섞인다"
    assert active[KIND_PLACEMENT] == 1
    assert active[KIND_SURVEY] == 0


def test_an_entry_round_trips_through_its_dict_form():
    entry = EditEntry(kind=KIND_PLACEMENT, target_id="pi6", action=ACTION_SET,
                      actor="admin", reason="r", edited_at=1.0,
                      payload={"at": {"x": 1.0, "y": 2.0}}, scope="z")

    assert EditEntry.from_dict(entry.as_dict()) == entry


def test_an_entry_missing_a_required_field_is_refused():
    with pytest.raises(OverlayError):
        EditEntry.from_dict({"kind": KIND_PLACEMENT, "target_id": "x"})


def test_deferred_writes_only_touch_the_disk_on_flush(tmp_path):
    path = tmp_path / "edits.json"
    board = OperatorOverlay(path=path, autosave=False)

    board.record(KIND_PLACEMENT, "pi6", {"at": {}}, actor="admin")

    assert path.exists() is False
    assert board.stats()["pending_write"] is True
    board.flush()
    assert path.exists() is True
