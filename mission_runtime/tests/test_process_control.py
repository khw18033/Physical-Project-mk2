"""선언된 실행 단위를 실제로 세우는 provider — `providers/process_control.py`.

implements: AI-B-03, AI-B-05, AI-C-04, AI-C-05, AI-C-19
tests: **명령줄은 망에서 오지 않는다** · 두 번 띄우지 않는다 · 멈춘 것을 멈추는 것은
       실패가 아니다 · 띄웠다 ≠ 준비됐다 · 재시작한 게이트웨이가 다시 띄우지 않는다 ·
       선언이 없는 배치는 정상이다
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from mission_runtime.execution.control import TargetStatus
from mission_runtime.providers.adapters import ControlProvider
from mission_runtime.providers.process_control import (
    KIND_COMPOSE,
    KIND_PROCESS,
    REASON_DEPENDENCY,
    REASON_NO_EXECUTABLE,
    REASON_NOT_DECLARED,
    REASON_UNSUPPORTED,
    ProcessControlProvider,
    StackDeclarationError,
    StackUnit,
    load_units,
    unit_from_mapping,
)

DECLARED = Path(__file__).resolve().parents[1] / "config" / "stack_units.example.json"


def sleeper(unit_id: str = "sleeper", seconds: int = 30, **over) -> StackUnit:
    return StackUnit(unit_id=unit_id, kind=KIND_PROCESS,
                     argv=(sys.executable, "-c", f"import time; time.sleep({seconds})"),
                     **over)


def provider(tmp_path: Path, *units: StackUnit) -> ProcessControlProvider:
    made = ProcessControlProvider({u.unit_id: u for u in units},
                                  state_dir=tmp_path / "state")
    return made


def stop_all(made: ProcessControlProvider) -> None:
    for unit_id in made.declared():
        made.request("stop", unit_id, requested_by="test")


# --------------------------------------------------------------- 경계

def test_it_satisfies_the_same_control_contract_as_the_cluster_provider():
    """같은 계약이면 상위 코드는 **어디서 도는지 모른다**(AI-B-11)."""
    assert isinstance(ProcessControlProvider(), ControlProvider)


def test_a_unit_name_that_is_not_declared_is_refused(tmp_path: Path):
    """**이 모듈의 가장 중요한 경계.** 망에서 오는 것은 이름뿐이다."""
    made = provider(tmp_path)
    result = made.request("start", "rm -rf /", requested_by="attacker")
    assert result.accepted is False
    assert result.rejection_reason == REASON_NOT_DECLARED


def test_there_is_no_way_to_hand_this_module_a_command_line():
    """argv 를 바깥에서 받으면 쓰기 계약 하나가 **원격 코드 실행 창구**가 된다."""
    import inspect

    from mission_runtime.providers import process_control

    source = inspect.getsource(process_control.ProcessControlProvider._dispatch)
    assert "params" not in source.split("def _dispatch")[1].split(")")[1], \
        "_dispatch 가 params 를 쓰면 명령줄이 망에서 들어올 길이 생긴다"


def test_an_unsupported_command_is_named(tmp_path: Path):
    made = provider(tmp_path, sleeper())
    result = made.request("delete-everything", "sleeper")
    assert result.accepted is False
    assert REASON_UNSUPPORTED in (result.rejection_reason or "")


def test_the_audit_log_and_the_trace_log_stay_separate(tmp_path: Path):
    """업무상 책임 추적과 기술 추적은 목적이 다르다(AI-B-03)."""
    made = provider(tmp_path, sleeper())
    made.request("stop", "sleeper", requested_by="operator-7")

    assert made.audit_log[-1].requested_by == "operator-7"
    assert made.trace_log[-1].latency_ms >= 0.0
    assert not hasattr(made.trace_log[-1], "requested_by")


# --------------------------------------------------------------- 선언

def test_a_process_unit_without_a_command_line_blows_up_at_load():
    with pytest.raises(StackDeclarationError):
        StackUnit(unit_id="x", kind=KIND_PROCESS)


def test_a_compose_unit_without_a_file_blows_up_at_load():
    with pytest.raises(StackDeclarationError):
        StackUnit(unit_id="x", kind=KIND_COMPOSE)


def test_an_unknown_kind_blows_up_rather_than_being_guessed():
    with pytest.raises(StackDeclarationError):
        unit_from_mapping({"unit_id": "x", "kind": "systemd"})


def test_a_dependency_on_an_undeclared_unit_blows_up(tmp_path: Path):
    path = tmp_path / "units.json"
    path.write_text(json.dumps({"units": [
        {"unit_id": "a", "kind": "process", "argv": ["true"],
         "depends_on": ["ghost"]}]}), encoding="utf-8")
    with pytest.raises(StackDeclarationError):
        load_units(path)


def test_no_declaration_file_is_an_empty_set_not_an_error(tmp_path: Path):
    """띄울 것이 없는 기계가 있다 — 그때 이 계층은 그냥 비어 있어야 한다(AI-C-05)."""
    assert load_units(tmp_path / "nope.json") == {}
    assert ProcessControlProvider().is_available() is False


def test_the_shipped_declaration_loads_and_names_the_data_stream_units():
    """`data_stream` 도 **가시화 명령으로** 뜬다 — 백엔드 기계에서 손으로 치지 않는다."""
    units = load_units(DECLARED)
    assert {"integration-stack", "data-stream-redis",
            "data-stream-server", "data-stream-vision"} <= set(units)
    assert units["data-stream-server"].depends_on == ("data-stream-redis",)
    assert units["integration-stack"].kind == KIND_COMPOSE


def test_the_declaration_never_hardcodes_an_interpreter_name(tmp_path: Path):
    """`python` 이 없는 기계가 있다(이 기계가 그렇다 — `python3` 와 venv 만 있다).
    절대 경로를 박으면 기계를 옮길 때마다 선언을 고쳐야 한다. 그래서 **자리표** 하나다."""
    from mission_runtime.providers.process_control import PLACEHOLDER_PYTHON

    units = load_units(DECLARED)
    for unit in units.values():
        if unit.kind == KIND_PROCESS:
            assert unit.argv[0] == PLACEHOLDER_PYTHON, unit.unit_id

    made = provider(tmp_path, StackUnit(
        unit_id="placeheld", kind=KIND_PROCESS,
        argv=(PLACEHOLDER_PYTHON, "-c", "import time; time.sleep(5)")))
    try:
        assert made.request("start", "placeheld").accepted is True
    finally:
        stop_all(made)


def test_only_the_declared_placeholder_is_expanded(tmp_path: Path):
    """임의 환경변수를 전개하면 선언이 기계의 환경에 **조용히** 의존한다."""
    made = provider(tmp_path, StackUnit(unit_id="x", kind=KIND_PROCESS,
                                        argv=("echo", "$HOME", "${python}")))
    assert made._expand("$HOME") == "$HOME"            # noqa: SLF001
    assert made._expand("${python}") == sys.executable  # noqa: SLF001


def test_a_running_unit_with_an_open_port_reads_as_ready_at_once(tmp_path: Path):
    """조회(`snapshot()`)는 기한 0 으로 묻는다 — 그때 묻지 않으면 떠 있는 단위가
    영원히 "준비 안 됨" 으로 그려진다(2026-11-20 실측)."""
    import socket as _socket

    held = _socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    try:
        made = provider(tmp_path, sleeper(ready_port=port))
        assert made.wait_ready("sleeper", timeout_s=0.0) is True
        assert {row["unit_id"]: row for row in made.snapshot()}["sleeper"]["ready"] is True
    finally:
        held.close()


def test_every_declared_command_line_points_inside_the_package():
    """선언이 기계 밖의 경로를 가리키면 **기계를 옮기면 깨진다.**"""
    units = load_units(DECLARED)
    for unit in units.values():
        for item in unit.argv[1:]:
            if item.endswith(".py"):
                assert not item.startswith("/"), (unit.unit_id, item)
        if unit.compose_file:
            assert not unit.compose_file.startswith("/"), unit.unit_id


# --------------------------------------------------------------- 실제로 띄운다

def test_a_declared_process_actually_starts_and_stops(tmp_path: Path):
    made = provider(tmp_path, sleeper())
    try:
        assert made.get_status("sleeper") is TargetStatus.STOPPED
        assert made.request("start", "sleeper").accepted is True
        assert made.get_status("sleeper") is TargetStatus.RUNNING
        assert made.request("stop", "sleeper").accepted is True
        assert made.get_status("sleeper") is TargetStatus.STOPPED
    finally:
        stop_all(made)


def test_starting_twice_does_not_start_two(tmp_path: Path):
    """같은 요청이 다시 와도 **물리적으로 다시 실행되지 않는다**(AI-C-20 과 같은 규칙)."""
    made = provider(tmp_path, sleeper())
    try:
        made.request("start", "sleeper")
        first = (made._state / "sleeper.pid").read_text()      # noqa: SLF001
        assert made.request("start", "sleeper").accepted is True
        assert (made._state / "sleeper.pid").read_text() == first  # noqa: SLF001
    finally:
        stop_all(made)


def test_a_stopped_unit_reads_as_stopped_at_once(tmp_path: Path):
    """죽은 자식을 거두지 않으면 **좀비**로 남고, 좀비에게 `kill(pid, 0)` 은
    성공한다 — 거두지 않으면 멈춘 단위가 10 초 동안 RUNNING 으로 보인다."""
    made = provider(tmp_path, sleeper())
    try:
        made.request("start", "sleeper")
        started = time.time()
        made.request("stop", "sleeper")
        assert made.get_status("sleeper") is TargetStatus.STOPPED
        assert time.time() - started < 5.0, "멈추는 데 기한만큼 기다렸다 = 거두지 않았다"
    finally:
        stop_all(made)


def test_stopping_something_already_stopped_is_accepted(tmp_path: Path):
    """멈춘 것을 멈추라는 요청은 실패가 아니다."""
    made = provider(tmp_path, sleeper())
    result = made.request("stop", "sleeper")
    assert result.accepted is True and result.final_status is TargetStatus.STOPPED


def test_a_missing_executable_is_named_not_swallowed(tmp_path: Path):
    made = provider(tmp_path, StackUnit(unit_id="ghost", kind=KIND_PROCESS,
                                        argv=("definitely-not-on-this-machine",)))
    result = made.request("start", "ghost")
    assert result.accepted is False
    assert REASON_NO_EXECUTABLE in (result.rejection_reason or "")


def test_a_unit_whose_dependency_is_down_is_refused_with_the_name(tmp_path: Path):
    made = provider(tmp_path, sleeper("base"), sleeper("top", depends_on=("base",)))
    result = made.request("start", "top")
    assert result.accepted is False
    assert result.rejection_reason == f"{REASON_DEPENDENCY}:base"


def test_a_dependency_that_is_up_lets_the_unit_start(tmp_path: Path):
    made = provider(tmp_path, sleeper("base"), sleeper("top", depends_on=("base",)))
    try:
        made.request("start", "base")
        assert made.request("start", "top").accepted is True
    finally:
        stop_all(made)


def test_a_restarted_gateway_adopts_what_is_already_running(tmp_path: Path):
    """pid 를 상태 뿌리에 적는 이유. 기억만 들고 있으면 게이트웨이가 다시 떴을 때
    **이미 돌고 있는 것을 또 띄운다.**"""
    first = provider(tmp_path, sleeper())
    try:
        first.request("start", "sleeper")
        second = provider(tmp_path, sleeper())           # 새 프로세스가 같은 선언을 읽는다
        assert second.get_status("sleeper") is TargetStatus.RUNNING
        pid = (tmp_path / "state" / "sleeper.pid").read_text()
        assert second.request("start", "sleeper").accepted is True
        assert (tmp_path / "state" / "sleeper.pid").read_text() == pid
    finally:
        stop_all(first)


def test_output_goes_to_a_log_under_the_state_root(tmp_path: Path):
    """로그를 설치 트리에 쓰면 **설치된 패키지를 고치는 것**이 된다."""
    made = provider(tmp_path, StackUnit(
        unit_id="talker", kind=KIND_PROCESS,
        argv=(sys.executable, "-c", "print('안녕'); import time; time.sleep(5)")))
    try:
        made.request("start", "talker")
        log = tmp_path / "state" / "talker.log"
        deadline = time.time() + 5.0
        while time.time() < deadline and not (log.is_file() and log.stat().st_size):
            time.sleep(0.1)
        assert "안녕" in log.read_text(encoding="utf-8")
    finally:
        stop_all(made)


# --------------------------------------------------------------- 준비 상태

def test_started_is_not_ready(tmp_path: Path):
    """`accepted=True` 는 "띄웠다" 이고 준비 상태는 다른 축이다(AI-B-05)."""
    made = provider(tmp_path, sleeper(ready_port=59999))
    try:
        assert made.request("start", "sleeper").accepted is True
        assert made.wait_ready("sleeper", timeout_s=0.5) is False
    finally:
        stop_all(made)


def test_a_unit_that_declares_no_port_is_unmeasured_not_unready(tmp_path: Path):
    """묻지 않은 것은 `None` 이다 — 거짓으로 적으면 "안 떴다" 로 읽힌다(AI-O-05)."""
    made = provider(tmp_path, sleeper())
    assert made.wait_ready("sleeper", timeout_s=0.0) is None


# --------------------------------------------------------------- 보기

def test_a_declared_unit_that_is_down_is_still_in_the_view(tmp_path: Path):
    """목록에서 빼면 **선언한 적 없는 것**과 같아 보인다(AI-O-05)."""
    made = provider(tmp_path, sleeper())
    rows = {row["unit_id"]: row for row in made.snapshot()}
    assert rows["sleeper"]["status"] == "STOPPED"
    assert rows["sleeper"]["ready"] is None


def test_the_view_says_why_a_unit_stopped(tmp_path: Path):
    """**이 계약을 만든 목적이 걸려 있는 자리.** 사유가 백엔드 기계의 로그 안에만
    있으면, 그 기계에 들어가지 않으려고 만든 계약이 그 기계에 들어가게 만든다."""
    made = provider(tmp_path, StackUnit(
        unit_id="dier", kind=KIND_PROCESS,
        argv=(sys.executable, "-c",
              "import sys; print('주소가 없습니다'); sys.exit(3)")))
    made.request("start", "dier")
    deadline = time.time() + 5.0
    while time.time() < deadline and made.get_status("dier") is TargetStatus.RUNNING:
        time.sleep(0.1)

    row = {r["unit_id"]: r for r in made.snapshot()}["dier"]
    assert row["status"] == "STOPPED"
    assert row["exit_code"] == 3
    assert row["last_output"] == "주소가 없습니다"


def test_a_unit_never_started_has_no_exit_code_rather_than_zero(tmp_path: Path):
    """0 은 "정상으로 끝났다" 이고 **띄운 적 없다** 와 다른 사실이다."""
    made = provider(tmp_path, sleeper())
    row = {r["unit_id"]: r for r in made.snapshot()}["sleeper"]
    assert row["exit_code"] is None and row["last_output"] is None


def test_the_view_carries_no_command_line(tmp_path: Path):
    """화면에 argv 를 내보내면 **다음 사람이 그것을 고쳐 보내려 한다.**"""
    made = provider(tmp_path, sleeper())
    for row in made.snapshot():
        assert "argv" not in row and "compose_file" not in row


def test_the_state_root_is_outside_the_install_tree(tmp_path: Path, monkeypatch):
    from mission_runtime.providers.process_control import state_root

    monkeypatch.setenv("MISSION_RUNTIME_STATE", str(tmp_path / "declared"))
    assert state_root() == tmp_path / "declared" / "stack"
    monkeypatch.delenv("MISSION_RUNTIME_STATE")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert state_root() == tmp_path / "xdg" / "mission_runtime" / "stack"


def test_it_never_issues_a_physical_command():
    """프로세스를 띄우는 것과 로봇을 움직이는 것은 **다른 일**이다(AI-C-19)."""
    import inspect

    from mission_runtime.providers import process_control

    source = inspect.getsource(process_control)
    for word in ("PhysicalCommand", "move_to", "emergency_stop", "mqtt"):
        assert word not in source, f"제어 경계를 넘는다: {word}"


@pytest.mark.skipif(os.name != "posix", reason="프로세스 그룹 종료는 POSIX 다")
def test_stopping_kills_the_whole_group_not_just_the_parent(tmp_path: Path):
    """자식을 남기면 포트를 쥔 손자가 남아 **다시 띄울 수 없다.**"""
    made = provider(tmp_path, StackUnit(
        unit_id="parent", kind=KIND_PROCESS,
        argv=(sys.executable, "-c",
              "import subprocess, sys, time; "
              "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
              "time.sleep(30)")))
    try:
        made.request("start", "parent")
        time.sleep(1.0)
        made.request("stop", "parent")
        assert made.get_status("parent") is TargetStatus.STOPPED
    finally:
        stop_all(made)
