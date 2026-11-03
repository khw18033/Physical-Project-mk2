"""implements: AI-N-02, AI-B-05, AI-C-19, AI-C-20, AI-C-05, AI-B-10
covers: 출처 없는 임무 거부, 버전·delta·검증 실패 시 last-known-good, 재시작
        후 임무·진행 복원, 중단(INTERRUPTED)과 실패(FAILED)의 구분, 발급자가
        허가한 항목만 링크 없이 재개, 유효기한·안전정지가 자율을 막는 것,
        중복 실행 방지는 여전히 CommandExecutionSupervisor의 몫이라는 것

각 주장은 그 주장이 깨지는 반대 케이스와 함께 확인한다.
"""

from __future__ import annotations

import sqlite3

import pytest

from mission_runtime.contracts.physical_command import Command, ExecutionStatus
from mission_runtime.execution.command_execution import CommandExecutionSupervisor
from mission_runtime.execution.mission import MissionItemOutcome, MissionStatus
from mission_runtime.ondevice.mission_cache import (
    BLOCKED_DEADLINE_PASSED,
    BLOCKED_SAFETY_SUSPENDED,
    CachedItemState,
    CachedMissionItem,
    MissionAutonomy,
    MissionCache,
    MissionDelivery,
    PROGRESS_KEPT,
    PROGRESS_RESET_CONTENT_CHANGED,
    REJECT_MISSING_ORIGIN_COMMAND,
    REJECT_NO_BASELINE,
    REJECT_VALIDATION_FAILED,
    REJECT_VERSION_NOT_NEWER,
    RESTORED_LAST_KNOWN_GOOD,
    INTERRUPTED_BY_RESTART,
    MISSION_ACCEPTED,
    MISSION_UNCHANGED,
    describe,
)

OK = MissionItemOutcome.SUCCEEDED
AUTO = MissionAutonomy.AUTONOMOUS_WHEN_CACHED
NEEDS_CMD = MissionAutonomy.REQUIRES_FRESH_COMMAND


def items(**overrides) -> tuple[CachedMissionItem, ...]:
    """발급자가 보낸 임무 항목. 도메인 이름이 아니라 전부 데이터다."""
    return (
        CachedMissionItem("leg.1", autonomy=AUTO, order_index=0, action="move",
                          parameters={"to": "p1"}),
        CachedMissionItem("leg.2", autonomy=AUTO, order_index=1, action="move",
                          parameters=overrides.get("leg2_params", {"to": "p2"})),
        CachedMissionItem("effector.engage", autonomy=NEEDS_CMD, order_index=2,
                          action="engage"),
        CachedMissionItem("record.detail", required=False, order_index=3, action="record"),
    )


def delivery(version=1, full=True, its=None, **kwargs) -> MissionDelivery:
    return MissionDelivery(
        mission_id=kwargs.pop("mission_id", "m-1"),
        version=version,
        full=full,
        items=its if its is not None else items(),
        origin_command_id=kwargs.pop("origin_command_id", "cmd-1"),
        approved_by=kwargs.pop("approved_by", "operator-7"),
        **kwargs,
    )


# --- AI-C-19: 캐시는 임무를 만들지 않는다 -------------------------------------


def test_a_mission_without_an_originating_command_is_refused():
    """AI-C-19: 승인·발급 출처가 없는 임무는 말단 캐시에 들어올 수 없다."""
    cache = MissionCache()

    result = cache.apply(delivery(origin_command_id=""))

    assert result.accepted is False
    assert result.reason == REJECT_MISSING_ORIGIN_COMMAND
    assert cache.active_mission is None


def test_the_same_mission_with_an_originating_command_is_accepted():
    """반대 케이스: 출처가 붙어 있으면 같은 내용이 그대로 들어온다."""
    cache = MissionCache()

    result = cache.apply(delivery())

    assert result.accepted is True
    assert result.reason.startswith(MISSION_ACCEPTED)
    assert cache.active_mission.origin_command_id == "cmd-1"
    assert cache.active_mission.approved_by == "operator-7"


# --- AI-N-02: 버전·delta·검증 실패 --------------------------------------------


def test_a_delta_before_any_baseline_is_rejected():
    cache = MissionCache()

    result = cache.apply(delivery(version=1, full=False))

    assert result.accepted is False
    assert result.reason == REJECT_NO_BASELINE


def test_a_delta_merges_only_the_items_it_carries():
    cache = MissionCache()
    cache.apply(delivery())

    changed = CachedMissionItem("leg.2", autonomy=AUTO, order_index=1, action="move",
                                parameters={"to": "p2-revised"})
    result = cache.apply(delivery(version=2, full=False, its=(changed,)))

    assert result.accepted is True
    assert cache.active_version == 2
    assert {i.item_id for i in cache.active_mission.items} == {
        "leg.1", "leg.2", "effector.engage", "record.detail"
    }
    assert cache.active_mission.item("leg.2").parameters == {"to": "p2-revised"}


def test_a_failed_validation_leaves_the_last_good_mission_untouched():
    """AI-N-02: 검증 실패 시 기존 정상 구성을 유지한다."""
    cache = MissionCache(validate_fn=lambda mission: mission.version != 2)
    cache.apply(delivery())

    result = cache.apply(delivery(version=2, full=True))

    assert result.accepted is False
    assert result.reason == REJECT_VALIDATION_FAILED
    assert cache.active_version == 1
    assert cache.active_mission.item("leg.2").parameters == {"to": "p2"}


def test_a_mission_with_no_required_item_is_rejected_by_the_existing_spec_rule():
    """임무 선언 규칙은 `execution/mission.py`가 소유한다 — 여기서 복제하지 않는다."""
    optional_only = (CachedMissionItem("record.detail", required=False),)

    assert MissionCache().apply(delivery(its=optional_only)).accepted is False


def test_an_older_version_never_overwrites_a_newer_one():
    cache = MissionCache()
    cache.apply(delivery(version=5))

    result = cache.apply(delivery(version=4))

    assert result.accepted is False
    assert result.reason.startswith(REJECT_VERSION_NOT_NEWER)
    assert cache.active_version == 5


def test_redelivering_the_same_version_does_not_rewind_progress():
    """전달 경로가 같은 버전을 두 번 흘려도 진행이 되감기면 안 된다."""
    cache = MissionCache()
    cache.apply(delivery())
    cache.complete("leg.1", OK, command_id="cmd-1")

    result = cache.apply(delivery())

    assert result.accepted is True
    assert result.reason.startswith(MISSION_UNCHANGED)
    assert cache.snapshot().completed() == ("leg.1",)


# --- 버전 갱신 시 진행 이월 ----------------------------------------------------


def test_progress_is_kept_when_the_item_content_is_unchanged():
    cache = MissionCache()
    cache.apply(delivery())
    cache.complete("leg.1", OK)

    result = cache.apply(delivery(version=2, full=True))

    assert f"{PROGRESS_KEPT}:leg.1" in result.progress_notes
    assert cache.snapshot().completed() == ("leg.1",)


def test_progress_is_reset_when_the_item_content_changed():
    """내용이 바뀐 항목의 DONE을 물려받으면 하지 않은 일을 했다고 말하게 된다."""
    cache = MissionCache()
    cache.apply(delivery())
    cache.complete("leg.2", OK)

    changed = items(leg2_params={"to": "somewhere-else"})
    result = cache.apply(delivery(version=2, full=True, its=changed))

    assert f"{PROGRESS_RESET_CONTENT_CHANGED}:leg.2" in result.progress_notes
    assert "leg.2" not in cache.snapshot().completed()


# --- AI-B-05: 재시작 -----------------------------------------------------------


def test_after_a_restart_with_the_link_still_down_the_terminal_can_still_answer(tmp_path):
    """링크가 끊긴 채 프로세스가 재시작돼도 임무·완료·잔여를 답할 수 있어야 한다."""
    path = tmp_path / "mission.db"
    cache = MissionCache(path)
    cache.apply(delivery())
    cache.complete("leg.1", OK, command_id="cmd-1")
    cache.begin("leg.2", command_id="cmd-1")
    cache.close()

    revived = MissionCache(path)          # 링크는 여전히 없다. 디스크만 있다.
    snapshot = revived.snapshot()

    assert snapshot.mission_id == "m-1" and snapshot.version == 1
    assert snapshot.origin_command_id == "cmd-1"
    assert snapshot.completed() == ("leg.1",)
    assert set(snapshot.outstanding()) == {"leg.2", "effector.engage", "record.detail"}
    assert snapshot.process_restarts == 1


def test_an_item_cut_off_by_a_restart_is_interrupted_not_failed(tmp_path):
    """AI-B-05: 프로세스 생사와 임무 성패는 다른 값이다."""
    path = tmp_path / "mission.db"
    cache = MissionCache(path)
    cache.apply(delivery())
    cache.begin("leg.1")
    cache.close()

    revived = MissionCache(path)
    states = {p.item_id: p.state for p in revived.snapshot().progress}

    assert states["leg.1"] is CachedItemState.INTERRUPTED
    assert states["leg.1"] is not CachedItemState.DONE
    assert INTERRUPTED_BY_RESTART in revived.snapshot().restore_reason
    # 그리고 그것이 임무 실패로 번역되지 않는다.
    assert revived.verdict().status is MissionStatus.NOT_RUN
    assert revived.verdict().status is not MissionStatus.FAILED


def test_a_genuinely_failed_required_item_does_fail_the_mission(tmp_path):
    """반대 케이스: 실행해 보고 실패한 것은 NOT_RUN이 아니라 FAILED다."""
    cache = MissionCache(tmp_path / "mission.db")
    cache.apply(delivery())
    for item_id in ("leg.1", "leg.2", "effector.engage"):
        cache.complete(item_id, OK if item_id != "leg.2" else MissionItemOutcome.FAILED)

    assert cache.verdict().status is MissionStatus.FAILED


def test_an_unreadable_active_version_falls_back_to_the_last_known_good(tmp_path):
    """AI-N-02의 last-known-good은 재시작 복원에도 적용된다."""
    path = tmp_path / "mission.db"
    cache = MissionCache(path)
    cache.apply(delivery(version=1))
    cache.apply(delivery(version=2))
    cache.close()

    db = sqlite3.connect(path)
    db.execute("UPDATE mission_content SET delivery = ? WHERE version = 2", ("{not json",))
    db.commit()
    db.close()

    revived = MissionCache(path)

    assert revived.active_version == 1
    assert revived.snapshot().restore_reason.startswith(RESTORED_LAST_KNOWN_GOOD)


# --- AI-C-19: 자율 경계 --------------------------------------------------------


def test_only_items_the_issuer_marked_may_continue_without_the_link():
    cache = MissionCache()
    cache.apply(delivery())

    snapshot = cache.snapshot()

    assert set(snapshot.resumable_without_link) == {"leg.1", "leg.2"}
    assert "effector.engage" in snapshot.blocked_pending_command
    # 두 목록의 합집합은 항상 미완료 전체다 — 조용히 사라지는 항목이 없다.
    assert set(snapshot.resumable_without_link) | set(snapshot.blocked_pending_command) == set(
        snapshot.outstanding()
    )


def test_an_item_that_says_nothing_about_autonomy_defaults_to_waiting():
    """말하지 않은 것을 '해도 된다'로 읽으면 AI가 자율 범위를 스스로 넓히게 된다."""
    silent = (
        CachedMissionItem("leg.1", action="move"),
        CachedMissionItem("leg.2", action="move"),
    )
    cache = MissionCache()
    cache.apply(delivery(its=silent))

    assert cache.resumable_without_link() == ()
    assert set(cache.blocked_pending_command()) == {"leg.1", "leg.2"}


def test_a_passed_deadline_stops_autonomous_continuation():
    cache = MissionCache(clock=lambda: 1_000.0)
    cache.apply(delivery(deadline=900.0))

    snapshot = cache.snapshot()

    assert snapshot.resumable_without_link == ()
    assert snapshot.autonomy_block_reason.startswith(BLOCKED_DEADLINE_PASSED)
    assert set(snapshot.blocked_pending_command) == set(snapshot.outstanding())


def test_before_the_deadline_the_same_mission_is_still_resumable():
    cache = MissionCache(clock=lambda: 800.0)
    cache.apply(delivery(deadline=900.0))

    assert set(cache.resumable_without_link()) == {"leg.1", "leg.2"}


# --- AI-C-20: 긴급정지은 네트워크 경로에 의존하지 않는다 -----------------------


def test_a_local_safety_stop_needs_no_link_and_silences_every_autonomous_item(tmp_path):
    cache = MissionCache(tmp_path / "mission.db")
    cache.apply(delivery())
    assert cache.resumable_without_link()      # 정지 전에는 이어서 할 수 있었다

    cache.suspend_for_safety("obstacle_within_stopping_distance")

    snapshot = cache.snapshot()
    assert snapshot.safety_suspended is True
    assert snapshot.resumable_without_link == ()
    assert snapshot.autonomy_block_reason == BLOCKED_SAFETY_SUSPENDED


def test_a_safety_stop_survives_a_restart_and_only_an_explicit_call_clears_it(tmp_path):
    path = tmp_path / "mission.db"
    cache = MissionCache(path)
    cache.apply(delivery())
    cache.suspend_for_safety("obstacle_within_stopping_distance")
    cache.close()

    revived = MissionCache(path)
    assert revived.safety_suspended is True
    assert revived.resumable_without_link() == ()

    revived.clear_safety_suspension("operator_cleared_at_console")
    assert set(revived.resumable_without_link()) == {"leg.1", "leg.2"}


# --- 중복 실행 방지는 여기가 아니다 --------------------------------------------


def test_command_deduplication_stays_with_the_execution_supervisor(tmp_path):
    """AI-C-20의 재전달 idempotency는 `CommandExecutionSupervisor`의 몫이다.

    캐시가 두 번째 idempotency 저장소를 만들면 두 판정이 어긋나는 순간 어느
    쪽이 참인지 말할 수 없게 된다. 그래서 여기서는 같은 command_id가 두 번
    와도 물리 실행이 한 번뿐이라는 사실만 확인하고, 캐시는 진행 기록만 맡는다.
    """
    runs: list[str] = []
    cache = MissionCache(tmp_path / "mission.db")
    cache.apply(delivery())

    def handler(command):
        runs.append(command.command_id)
        cache.begin("leg.1", command_id=command.command_id)
        cache.complete("leg.1", OK, command_id=command.command_id)
        return True, None, None

    supervisor = CommandExecutionSupervisor(handler, state_path=tmp_path / "commands.db")
    command = Command("cmd-1", target="terminal-a", action="move", parameters={"to": "p1"})
    first = supervisor.submit(command)
    second = supervisor.submit(command)          # 재전달
    supervisor.close()

    assert first.accepted and second.accepted
    assert runs == ["cmd-1"]                     # 물리 실행은 한 번뿐
    assert supervisor.get_status("cmd-1") is ExecutionStatus.SUCCEEDED
    assert cache.snapshot().completed() == ("leg.1",)
    # 캐시에는 명령 수락·중복 판정 API가 없다.
    assert not hasattr(cache, "submit")
    assert not hasattr(cache, "accept")


def test_progress_may_only_be_recorded_for_declared_items():
    cache = MissionCache()
    cache.apply(delivery())

    with pytest.raises(ValueError):
        cache.complete("never.declared", OK)


# --- 운영 표시 ------------------------------------------------------------------


def test_describe_names_what_is_autonomous_and_what_is_waiting():
    cache = MissionCache()
    cache.apply(delivery())

    line = describe(cache.snapshot())

    assert "m-1@v1" in line and "autonomous=" in line and "needs_command=" in line


def test_describe_says_so_when_there_is_no_cached_mission():
    assert describe(MissionCache().snapshot()) == "no cached mission"


# --- AI-B-10: 말단 경량 ---------------------------------------------------------


def test_the_cache_needs_nothing_but_a_file():
    """브로커·수집기·오케스트레이터를 끌어오지 않는다(AI-B-10)."""
    import inspect

    from mission_runtime.ondevice import mission_cache

    source = inspect.getsource(mission_cache)
    body = source.split('"""', 2)[-1]
    for term in ("mqtt", "kafka", "otel", "k3s", "requests", "redis"):
        assert term not in body.lower(), f"{term} leaked into the on-device cache"


def test_every_mission_cache_reason_is_in_the_dictionary_vocabulary():
    """모듈이 문자열을 정하고 사전이 어휘를 소유한다(residency와 같은 규약)."""
    from mission_runtime.contracts import data_dictionary as dd
    from mission_runtime.ondevice import mission_cache

    assert set(mission_cache.MISSION_CACHE_REASONS) <= set(dd.MISSION_CACHE_REASONS)
    assert set(dd.MISSION_AUTONOMY_VALUES) == {a.value for a in MissionAutonomy}
    assert set(dd.MISSION_ITEM_STATES) == {s.value for s in CachedItemState}
