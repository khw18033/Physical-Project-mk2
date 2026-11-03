"""말단 로봇 어댑터의 계약 시험 — 로봇 없이 전부 돈다.

implements: AI-C-20, AI-C-19, AI-C-04, AI-C-05, AI-B-03, AI-B-05, AI-N-02, AI-N-03
tests: 멱등 재전달, 거부 vs ABORTED, 취소 수락 vs CANCELED 도달, 유효기한 만료,
       autonomy 값별 링크 단절 동작, 긴급정지 경로, 미선언·결손 와이어 필드

시험의 판정 기준을 로그가 아니라 **물리 실행 횟수**(`backend.executed`)에 두었다.
AI-C-20 §5-1이 요구하는 것이 "같은 응답을 보냈는가"가 아니라 "물리 동작을 다시
실행하지 않았는가"이기 때문이다.
"""

from __future__ import annotations

import threading

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.physical_command import (
    CancelCommandRequest,
    Capability,
    Command,
    ExecutionStatus,
    RejectionCode,
)
from mission_runtime.execution import robot_adapter as ra
from mission_runtime.execution.mission import MissionItemOutcome
from mission_runtime.execution.robot_adapter import (
    RobotCommandRejected,
    TerminalRobotAdapter,
)
from mission_runtime.ondevice.mission_cache import (
    CachedMissionItem,
    MissionAutonomy,
    MissionCache,
    MissionDelivery,
)
from mission_runtime.providers.adapters import RobotControlBackend
from mission_runtime.providers.fakes import FakeRobotBackend

AUTO = MissionAutonomy.AUTONOMOUS_WHEN_CACHED
NEEDS_CMD = MissionAutonomy.REQUIRES_FRESH_COMMAND


def adapter(backend=None, **kwargs) -> TerminalRobotAdapter:
    return TerminalRobotAdapter(
        backend or FakeRobotBackend(), device_id="terminal-test", **kwargs
    )


def command(command_id="cmd-1", action="move", **kwargs) -> Command:
    return Command(command_id=command_id, target="robot-test", action=action, **kwargs)


# --- 경계: 이 어댑터는 무엇을 소유하지 않는가 (AI-C-19, AI-C-04) --------------


def test_fake_backend_satisfies_the_declared_protocol():
    assert isinstance(FakeRobotBackend(), RobotControlBackend)


def test_no_vendor_name_leaks_into_the_adapter_or_the_contract():
    """벤더 이름이 나타나도 되는 자리는 providers/ 안쪽뿐이다(원칙 #1·#2, AI-C-04)."""
    import inspect

    from mission_runtime.contracts import physical_command
    from mission_runtime.execution import command_execution

    for module in (ra, physical_command, command_execution):
        source = inspect.getsource(module).lower()
        for vendor in ("unitree", "go1", "robomaster", "rospy", "rclpy"):
            assert vendor not in source, f"{vendor} leaked into {module.__name__}"


def test_the_adapter_never_constructs_a_command():
    """AI는 물리 명령을 발급하지 않는다(AI-C-19).

    주석이 아니라 **호출 그래프**로 확인한다: 모듈 어디에도 `Command(...)` 호출
    노드가 없어야 한다. `CommandAcceptance`/`CommandResult`/`CancelCommandRequest`
    는 명령이 아니라 그에 대한 *응답*이므로 생성해도 된다.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ra))
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "Command" not in constructed


# --- §5-1 멱등 재전달 ----------------------------------------------------------


def test_redelivered_command_id_does_not_execute_the_physical_action_twice():
    backend = FakeRobotBackend()
    a = adapter(backend)

    first = a.submit(command())
    second = a.submit(command())

    assert first.accepted and second.accepted
    assert first.accepted_at == second.accepted_at, "이전 수락을 그대로 돌려줘야 한다"
    assert backend.count_of("cmd-1") == 1, "물리 동작이 두 번 실행됐다"
    assert ra.REDELIVERED in a.reasons()


def test_same_command_id_with_different_payload_is_rejected_as_already_exists():
    backend = FakeRobotBackend()
    a = adapter(backend)
    a.submit(command(parameters={"distance": 1.0}))

    conflicting = a.submit(command(parameters={"distance": 9.0}))

    assert conflicting.accepted is False
    assert conflicting.rejection.code == RejectionCode.ALREADY_EXISTS
    assert backend.count_of("cmd-1") == 1


def test_redelivery_after_the_backend_went_unready_still_replays_the_old_acceptance():
    """수락된 id 는 심사를 다시 거치지 않는다 — §5-1 은 "이전에 보냈던 수락을 그대로"다."""
    backend = FakeRobotBackend()
    a = adapter(backend)
    first = a.submit(command())

    backend.ready = False
    replay = a.submit(command())

    assert replay.accepted is True
    assert replay.accepted_at == first.accepted_at
    assert backend.count_of("cmd-1") == 1


def test_a_rejected_command_id_is_not_remembered_and_is_re_admitted_when_ready():
    """거부는 아무것도 실행하지 않았으므로 기억하지 않는다(HW 구현도 같다)."""
    backend = FakeRobotBackend(ready=False, not_ready_reason="battery_too_low")
    a = adapter(backend)
    rejected = a.submit(command())
    assert rejected.accepted is False

    backend.ready = True
    retried = a.submit(command())

    assert retried.accepted is True
    assert backend.count_of("cmd-1") == 1


# --- 거부(수락 결과) vs ABORTED(실행 상태) — AI-C-20 --------------------------


def test_rejection_is_not_an_execution_state_at_all():
    backend = FakeRobotBackend(ready=False, not_ready_reason="sdk_not_running")
    a = adapter(backend)

    acceptance = a.submit(command())

    assert acceptance.accepted is False
    assert acceptance.rejection.code == RejectionCode.FAILED_PRECONDITION
    assert a.get_status("cmd-1") is None, "거부된 명령은 실행 상태에 들어가지 않는다"
    assert a.get_result("cmd-1") is None, "거부 뒤에 CommandResult 가 따라오지 않는다"
    assert backend.executed == []


def test_failure_after_acceptance_is_aborted_not_rejected():
    backend = FakeRobotBackend(failing_actions=("move",))
    a = adapter(backend)

    acceptance = a.submit(command())
    result = a.get_result("cmd-1")

    assert acceptance.accepted is True, "실행 실패는 수락 여부와 다른 축이다"
    assert result.status is ExecutionStatus.ABORTED
    assert result.failure is not None and "move_failed" in result.failure.message


def test_backend_exception_aborts_the_command_without_killing_the_adapter():
    backend = FakeRobotBackend(raising_actions=("move",))
    a = adapter(backend)

    a.submit(command())
    result = a.get_result("cmd-1")

    assert result.status is ExecutionStatus.ABORTED
    assert "backend_error" in result.failure.message
    assert a.submit(command("cmd-2")).accepted is True, "어댑터가 계속 살아 있어야 한다"


def test_backend_may_reject_before_acceptance_through_the_optional_validate_hook():
    class ValidatingBackend(FakeRobotBackend):
        def validate(self, action, parameters):
            self.validated.append((action, dict(parameters)))
            if parameters.get("distance", 0) > 5:
                raise RobotCommandRejected(RejectionCode.INVALID_ARGUMENT, "distance_out_of_range")

    backend = ValidatingBackend()
    a = adapter(backend)

    acceptance = a.submit(command(parameters={"distance": 42.0}))

    assert acceptance.accepted is False
    assert acceptance.rejection.code == RejectionCode.INVALID_ARGUMENT
    assert backend.executed == []
    assert backend.validated == [("move", {"distance": 42.0})]


# --- §5-4 미선언 action ---------------------------------------------------------


def test_an_undeclared_action_is_rejected_before_any_execute_logic():
    backend = FakeRobotBackend(actions=("move",))
    a = adapter(backend)

    acceptance = a.submit(command(action="detonate"))

    assert acceptance.accepted is False
    assert acceptance.rejection.code == RejectionCode.UNIMPLEMENTED
    assert backend.executed == []


def test_an_under_declared_capability_is_still_usable_and_only_counted():
    """와이어가 action 이름만 싣는 오늘(§8-3 P7)도 거부가 아니라 정상 경로다."""
    backend = FakeRobotBackend(actions=("move",), fully_declared=False)
    a = adapter(backend)

    declared = a.capabilities()

    assert declared[0].is_fully_declared() is False
    assert a.wire_gaps[ra.WIRE_GAP_CAPABILITY_UNDER_DECLARED] == 1
    assert a.submit(command()).accepted is True


def test_a_missing_correlation_id_is_counted_not_invented():
    a = adapter()
    a.submit(command())
    assert a.wire_gaps[ra.WIRE_GAP_COMMAND_CORRELATION_ID] == 1

    a.submit(command("cmd-2", correlation_id="trace-abc"))
    assert a.wire_gaps[ra.WIRE_GAP_COMMAND_CORRELATION_ID] == 1


def test_unknown_parameters_are_passed_through_rather_than_dropped():
    """어댑터는 파라미터 schema 를 모른다(와이어에 없다). 조용히 버리지 않는다."""
    backend = FakeRobotBackend()
    a = adapter(backend)

    a.submit(command(parameters={"distance": 1.0, "unknown_to_us": 7.0}))

    assert backend.executed[0][1] == {"distance": 1.0, "unknown_to_us": 7.0}


# --- §5-2 유효기한 --------------------------------------------------------------


def test_an_expired_deadline_is_rejected_and_never_starts():
    backend = FakeRobotBackend()
    a = adapter(backend)

    acceptance = a.submit(command(deadline=100.0), now=101.0)

    assert acceptance.accepted is False
    assert acceptance.rejection.code == RejectionCode.FAILED_PRECONDITION
    assert backend.executed == []
    assert a.get_status("cmd-1") is None


def test_the_deadline_is_checked_before_the_undeclared_action_check():
    """HW 장치 구현과 같은 순서 — 같은 입력에 두 구현이 다른 코드를 내면 안 된다."""
    a = adapter(FakeRobotBackend(actions=("move",)))

    acceptance = a.submit(command(action="nope", deadline=100.0), now=101.0)

    assert acceptance.rejection.code == RejectionCode.FAILED_PRECONDITION


def test_a_future_deadline_is_accepted():
    a = adapter()
    assert a.submit(command(deadline=1_000.0), now=1.0).accepted is True


# --- §5-3 취소: 수락 ≠ CANCELED 도달 ---------------------------------------------


def test_cancel_acceptance_is_distinct_from_reaching_canceled():
    gate = threading.Event()
    backend = FakeRobotBackend(gate=gate)
    a = adapter(backend)
    a.submit_async(command())
    while a.get_status("cmd-1") is not ExecutionStatus.EXECUTING:
        pass

    response = a.cancel(CancelCommandRequest("cmd-1"))

    assert response.accepted is True, "취소 절차에 들어갔다"
    assert a.get_result("cmd-1") is None, "아직 CANCELED 에 도달하지 않았다"
    assert a.get_status("cmd-1") is ExecutionStatus.CANCELING
    assert backend.stop_requests == ["cmd-1"]

    gate.set()
    result = a.wait("cmd-1", timeout=5.0)
    assert result.status is ExecutionStatus.CANCELED, "취소가 완료보다 우선한다"
    a.close()


def test_cancel_wins_over_a_success_that_lands_at_the_same_time():
    gate = threading.Event()
    backend = FakeRobotBackend(gate=gate)
    a = adapter(backend)
    a.submit_async(command())
    while a.get_status("cmd-1") is not ExecutionStatus.EXECUTING:
        pass
    a.cancel(CancelCommandRequest("cmd-1"))
    gate.set()

    result = a.wait("cmd-1", timeout=5.0)

    assert result.status is ExecutionStatus.CANCELED
    assert result.status is not ExecutionStatus.SUCCEEDED
    a.close()


def test_cancelling_an_already_terminal_command_is_refused_with_a_reason():
    a = adapter()
    a.submit(command())

    response = a.cancel(CancelCommandRequest("cmd-1"))

    assert response.accepted is False
    assert response.reason == "already_terminal:SUCCEEDED"


def test_cancelling_an_unknown_command_id_is_refused():
    response = adapter().cancel(CancelCommandRequest("never-seen"))
    assert response.accepted is False
    assert response.reason == "unknown_command_id"


def test_a_backend_that_cannot_stop_refuses_the_cancel_rather_than_pretending():
    gate = threading.Event()
    backend = FakeRobotBackend(gate=gate, stop_supported=False)
    a = adapter(backend)
    a.submit_async(command())
    while a.get_status("cmd-1") is not ExecutionStatus.EXECUTING:
        pass

    response = a.cancel(CancelCommandRequest("cmd-1"))

    assert response.accepted is False
    assert response.reason == "adapter_cancel_rejected"
    gate.set()
    assert a.wait("cmd-1", timeout=5.0).status is ExecutionStatus.SUCCEEDED
    a.close()


# --- 긴급정지: 일반 취소와 다른 경로 (AI-C-20 §7) ---------------------------------


def test_emergency_stop_reaches_the_backend_without_any_transport():
    backend = FakeRobotBackend()
    a = adapter(backend)

    outcome = a.emergency_stop("obstacle_within_braking_distance")

    assert backend.emergency_stops == ["obstacle_within_braking_distance"]
    assert outcome.latched is True and outcome.backend_reached is True
    # 어댑터는 transport 를 참조조차 하지 않는다 — 안전 경로가 네트워크와 독립임을
    # 구조로 보인다.
    assert not hasattr(a, "_transport")


def test_emergency_stop_is_not_an_ordinary_cancel():
    """취소는 그 명령 하나를, 긴급정지는 새 명령 수용 자체를 막는다."""
    backend = FakeRobotBackend()
    a = adapter(backend)
    a.emergency_stop("estop")

    acceptance = a.submit(command("cmd-after-estop"))

    assert acceptance.accepted is False
    assert acceptance.rejection.code == RejectionCode.FAILED_PRECONDITION
    assert "emergency stop latched" in acceptance.rejection.message
    assert backend.executed == []
    assert backend.stop_requests == [], "긴급정지는 취소 경로를 타지 않는다"


def test_emergency_stop_moves_in_flight_commands_to_canceling():
    gate = threading.Event()
    backend = FakeRobotBackend(gate=gate)
    a = adapter(backend)
    a.submit_async(command())
    while a.get_status("cmd-1") is not ExecutionStatus.EXECUTING:
        pass

    outcome = a.emergency_stop("estop")

    assert outcome.canceling_command_ids == ("cmd-1",)
    gate.set()
    assert a.wait("cmd-1", timeout=5.0).status is ExecutionStatus.CANCELED
    a.close()


def test_an_unreachable_stop_path_still_latches_and_says_so():
    backend = FakeRobotBackend(emergency_stop_reachable=False)
    a = adapter(backend)

    outcome = a.emergency_stop("estop")

    assert outcome.backend_reached is False
    assert outcome.latched is True, "닿았는지 모를 때 명령을 계속 받는 쪽이 더 위험하다"
    assert ra.ESTOP_BACKEND_UNREACHABLE in outcome.notes


def test_a_raising_stop_path_does_not_prevent_the_latch():
    class ExplodingBackend(FakeRobotBackend):
        def emergency_stop(self, reason):
            raise OSError("serial port gone")

    a = adapter(ExplodingBackend())
    outcome = a.emergency_stop("estop")

    assert outcome.latched is True and outcome.backend_reached is False
    assert a.emergency_stopped is True


def test_clearing_the_latch_is_explicit_and_local():
    backend = FakeRobotBackend()
    a = adapter(backend)
    a.emergency_stop("estop")

    a.clear_emergency_stop("operator_confirmed_area_clear")

    assert a.emergency_stopped is False
    assert a.submit(command("cmd-2")).accepted is True
    assert any(r.startswith(ra.ESTOP_CLEARED) for r in a.reasons())


def test_emergency_stop_suspends_the_mission_cache_too(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(items=(CachedMissionItem("a", autonomy=AUTO, action="move"),)))
    a = adapter(mission_cache=cache)

    a.emergency_stop("estop")

    assert cache.safety_suspended is True
    assert cache.resumable_without_link() == ()
    cache.close()


# --- 링크 단절 + autonomy (AI-C-19, AI-N-02) ------------------------------------


def _delivery(version=1, items=(), **kwargs) -> MissionDelivery:
    return MissionDelivery(
        mission_id="m-1", version=version, full=True, items=tuple(items),
        origin_command_id=kwargs.pop("origin_command_id", "cmd-approved"), **kwargs,
    )


def test_autonomous_when_cached_items_are_executed_during_link_loss(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(items=(
        CachedMissionItem("scan", autonomy=AUTO, action="move", parameters={"d": 1.0}),
    )))
    backend = FakeRobotBackend(actions=("move",))
    a = adapter(backend, mission_cache=cache)

    outcomes = a.resume_without_link()

    assert [o.item_id for o in outcomes] == ["scan"]
    assert outcomes[0].executed is True
    assert outcomes[0].outcome is MissionItemOutcome.SUCCEEDED
    assert backend.executed == [("move", {"d": 1.0}, "cmd-approved")], \
        "승인한 명령의 id 를 달고 가야 한다"
    cache.close()


def test_requires_fresh_command_items_are_never_touched_during_link_loss(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(items=(
        CachedMissionItem("scan", autonomy=NEEDS_CMD, action="move"),
    )))
    backend = FakeRobotBackend(actions=("move",))
    a = adapter(backend, mission_cache=cache)

    outcomes = a.resume_without_link()

    assert backend.executed == []
    assert [o.executed for o in outcomes] == [False]
    assert outcomes[0].reason.startswith(ra.RESUME_BLOCKED_PENDING_COMMAND)
    cache.close()


def test_a_mixed_mission_resumes_only_the_permitted_half(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(items=(
        CachedMissionItem("allowed", autonomy=AUTO, action="move"),
        CachedMissionItem("blocked", autonomy=NEEDS_CMD, action="move"),
    )))
    backend = FakeRobotBackend(actions=("move",))
    a = adapter(backend, mission_cache=cache)

    a.resume_without_link()

    assert [row[2] for row in backend.executed] == ["cmd-approved"]
    assert len(backend.executed) == 1
    cache.close()


def test_an_item_missing_autonomy_defaults_to_the_conservative_value(tmp_path):
    """와이어에 autonomy 자리가 없는 오늘 실제로 일어나는 경우."""
    cache = MissionCache(tmp_path / "m.sqlite")
    item = CachedMissionItem("scan", action="move")   # autonomy 를 주지 않았다
    assert item.autonomy is NEEDS_CMD
    cache.apply(_delivery(items=(item,)))
    backend = FakeRobotBackend(actions=("move",))
    a = adapter(backend, mission_cache=cache)

    a.resume_without_link()

    assert backend.executed == []
    cache.close()


def test_ingesting_a_mission_from_a_wire_without_an_autonomy_slot_counts_the_gap(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    a = adapter(mission_cache=cache)

    a.ingest_mission(
        _delivery(items=(CachedMissionItem("scan", action="move"),)),
        autonomy_on_wire=False,
    )

    assert a.wire_gaps[ra.WIRE_GAP_MISSION_AUTONOMY] == 1
    assert a.resume_without_link() == (
        ra.ResumeOutcome("scan", f"{ra.RESUME_BLOCKED_PENDING_COMMAND}:scan", False),
    )
    cache.close()


def test_a_resumed_item_whose_action_is_undeclared_is_not_attempted(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(items=(CachedMissionItem("scan", autonomy=AUTO, action="fly"),)))
    backend = FakeRobotBackend(actions=("move",))
    a = adapter(backend, mission_cache=cache)

    outcomes = a.resume_without_link()

    assert backend.executed == []
    assert outcomes[0].reason.startswith(ra.RESUME_ACTION_NOT_DECLARED)
    cache.close()


def test_a_failed_resume_records_failed_not_interrupted(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(items=(CachedMissionItem("scan", autonomy=AUTO, action="move"),)))
    a = adapter(FakeRobotBackend(actions=("move",), failing_actions=("move",)),
                mission_cache=cache)

    outcomes = a.resume_without_link()

    assert outcomes[0].outcome is MissionItemOutcome.FAILED
    assert cache.snapshot().completed() == ("scan",), "끝났다는 사실 자체는 남는다"
    cache.close()


def test_resume_is_idempotent_because_done_items_drop_out(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(items=(CachedMissionItem("scan", autonomy=AUTO, action="move"),)))
    backend = FakeRobotBackend(actions=("move",))
    a = adapter(backend, mission_cache=cache)

    a.resume_without_link()
    a.resume_without_link()

    assert len(backend.executed) == 1
    cache.close()


def test_resume_without_a_mission_cache_says_so_instead_of_guessing():
    a = adapter()
    assert a.resume_without_link() == ()
    assert ra.RESUME_NO_MISSION_CACHE in a.reasons()


def test_a_mission_past_its_deadline_resumes_nothing(tmp_path):
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(
        items=(CachedMissionItem("scan", autonomy=AUTO, action="move"),), deadline=100.0,
    ))
    backend = FakeRobotBackend(actions=("move",))
    a = adapter(backend, mission_cache=cache)

    a.resume_without_link(now=101.0)

    assert backend.executed == []
    cache.close()


# --- 링크·구역 연계 (AI-N-03) ----------------------------------------------------


def test_link_posture_and_zone_are_reported_but_not_acted_on():
    from mission_runtime.ondevice.link_handover import LinkPosture

    class Entry:
        zone_id = "zone-b"
        requires_config_refresh = True

    a = adapter(link_posture=lambda: LinkPosture.LOCAL_ONLY)
    a.note_zone_entry(Entry())

    status = a.status()
    assert status["link_posture"] == "local_only"
    assert status["zone_id"] == "zone-b"
    assert status["zone_requires_config_refresh"] is True


def test_a_broken_link_probe_does_not_break_status():
    def exploding():
        raise OSError("no radio")

    assert adapter(link_posture=exploding).status()["link_posture"] is None


def test_zone_change_does_not_silently_invalidate_a_cached_mission(tmp_path):
    """구역↔임무 정합은 아직 합의되지 않은 계약이다 — 어댑터가 정하지 않는다."""
    cache = MissionCache(tmp_path / "m.sqlite")
    cache.apply(_delivery(items=(CachedMissionItem("scan", autonomy=AUTO, action="move"),)))
    a = adapter(FakeRobotBackend(actions=("move",)), mission_cache=cache)

    class Entry:
        zone_id = "zone-b"
        requires_config_refresh = True

    a.note_zone_entry(Entry())

    assert cache.active_mission is not None
    assert cache.resumable_without_link() == ("scan",)
    cache.close()


# --- 벤더 backend 미가용이 정상 경로다 (AI-C-05) ---------------------------------


def test_the_vendor_backend_module_imports_without_any_sdk_present():
    from mission_runtime.providers.quadruped_sdk_robot import QuadrupedSdkRobotBackend

    backend = QuadrupedSdkRobotBackend(
        sdk_module="a_vendor_sdk_that_is_not_installed", declared_actions=("move",)
    )

    assert backend.available is False
    ready, reason = backend.readiness()
    assert ready is False and "sdk_module_unavailable" in reason
    assert backend.declared_actions() == (), "없는 SDK 로 기능을 선언하지 않는다"


def test_an_unavailable_vendor_backend_rejects_commands_and_keeps_the_rest_alive():
    from mission_runtime.providers.quadruped_sdk_robot import QuadrupedSdkRobotBackend

    a = adapter(QuadrupedSdkRobotBackend(sdk_module="nope", declared_actions=("move",)))

    acceptance = a.submit(command())

    assert acceptance.accepted is False
    assert acceptance.rejection.code == RejectionCode.UNIMPLEMENTED
    assert a.status()["declared_actions"] == []


def test_the_vendor_backend_refuses_to_pretend_it_can_execute():
    from mission_runtime.providers.quadruped_sdk_robot import (
        QuadrupedSdkRobotBackend,
        RobotBackendUnavailable,
    )

    backend = QuadrupedSdkRobotBackend(sdk_module="json", declared_actions=("move",))
    assert backend.available is True
    ready, reason = backend.readiness()
    assert ready is False and reason.startswith("command_path_not_implemented")
    with pytest.raises(RobotBackendUnavailable):
        backend.execute("move", {}, command_id="cmd-1")
    assert backend.emergency_stop("x") is False, "소프트웨어가 안전장치를 자처하지 않는다"


# --- 지속성 (AI-B-05) -----------------------------------------------------------


def test_a_restart_does_not_re_execute_an_already_delivered_command(tmp_path):
    state = tmp_path / "commands.sqlite"
    backend = FakeRobotBackend()
    first = adapter(backend, state_path=state)
    first.submit(command())
    first.close()

    second = adapter(backend, state_path=state)
    replay = second.submit(command())

    assert replay.accepted is True
    assert backend.count_of("cmd-1") == 1, "재시작 후 재전달이 다시 실행됐다"
    second.close()


# --- 데이터 사전 등록 (AI-C-01) ---------------------------------------------------


def test_every_reason_token_the_adapter_emits_is_registered():
    emitted = {
        value.split(":", 1)[0]
        for name, value in vars(ra).items()
        if name.isupper() and isinstance(value, str) and value.startswith("robot_")
    }
    assert emitted <= set(dd.ROBOT_ADAPTER_REASONS), emitted - set(dd.ROBOT_ADAPTER_REASONS)
    assert set(dd.ROBOT_ADAPTER_REASONS) == emitted, set(dd.ROBOT_ADAPTER_REASONS) - emitted


def test_the_reason_field_is_in_the_dictionary():
    spec = dd.spec_for(dd.ROBOT_ADAPTER_REASON)
    assert spec.plane is dd.DataPlane.OBSERVABILITY
    assert "말단 로봇 어댑터" in spec.produced_by


def test_capability_declared_by_the_backend_is_passed_through_unchanged():
    declared = (Capability(name="move", version="3", parameter_schema="p", result_schema="r"),)
    a = adapter(FakeRobotBackend(actions=declared))
    assert a.capabilities() == declared
    assert a.wire_gaps[ra.WIRE_GAP_CAPABILITY_UNDER_DECLARED] == 0
