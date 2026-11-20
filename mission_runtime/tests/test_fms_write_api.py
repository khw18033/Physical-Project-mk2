"""쓰기 계약은 조회와 **다른 계약이다** — 같은 포트에 있어도 섞이지 않는다.

implements: AI-O-06, AI-C-19, AI-C-06, AI-L-03, AI-L-06
tests: read and write names never overlap, a read path refuses writes before
       reading the body, the token comes only from Authorization, login puts it
       in the body and not in a cookie, the permission table is the service's,
       a declaration that drifts from the service refuses to stand
"""
from __future__ import annotations

import json
import pathlib

import pytest

from integration.fms_view_api import VIEW_ROUTES, ViewApiUnavailable, _load_console
from integration.fms_write_api import (
    ALLOWED_METHODS,
    WRITE_ROUTES,
    FmsWriteApi,
    WriteApiUnavailable,
    build_write_api,
    token_from,
)

_PKG = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def service_module():
    return _load_console()


@pytest.fixture(scope="module")
def write_api(service_module):
    try:
        service = service_module.build_service(
            ui_config=_PKG / "config" / "status_ui.json",
            zone_profile=_PKG / "profiles" / "domains.json",
            goal_kinds=_PKG / "profiles" / "goal_kinds.example.json",
            with_fleet=False)
    except Exception as error:                                  # noqa: BLE001
        pytest.skip(f"서비스를 세우지 못했다 — {error}")
    return build_write_api(service, service_module)


def _post(api, route, body=None, *, token=None):
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    raw = json.dumps(body if body is not None else {}).encode("utf-8")
    status, out = api.answer(route, raw, headers)
    return status, json.loads(out.decode("utf-8"))


# ---------------------------------------------------------------------------
# 조회와 쓰기는 섞이지 않는다 (AI-O-06)
# ---------------------------------------------------------------------------


def test_reading_names_and_writing_names_never_overlap():
    """읽는 이름과 쓰는 이름이 겹치면 "조회로 바꿨다" 가 가능해진다.

    AI-O-06: 상태 뷰는 조회 전용이어야 하며 이 경로를 통해 실행 상태를 변경하는
    수단을 제공해서는 안 된다.
    """
    assert not set(WRITE_ROUTES) & set(VIEW_ROUTES), (
        sorted(set(WRITE_ROUTES) & set(VIEW_ROUTES)))
    assert "GET" not in ALLOWED_METHODS, "GET 으로는 아무것도 바뀌지 않는다"


def test_a_read_path_refuses_a_write_with_the_contracts_own_word(write_api):
    """조회 경로에 POST 하면 405 다. 어휘는 **계약이 소유한다**."""
    status, body = _post(write_api, "/api/scene")
    assert status == 405
    assert body == {"error": "read_only_path"}


def test_the_write_api_does_not_claim_read_paths(write_api):
    for route in VIEW_ROUTES:
        assert not write_api.handles(route), route
    for route in WRITE_ROUTES:
        assert write_api.handles(route), route


# ---------------------------------------------------------------------------
# 선언이 서비스와 어긋나면 **세우지 않는다**
# ---------------------------------------------------------------------------


def test_a_declaration_that_drifts_from_the_service_refuses_to_stand(service_module):
    """조용히 좁은 쪽을 쓰면 기능 하나가 **말없이** 사라진다.

    실제로 조회 쪽에서 그렇게 넷이 빠져 있었다(`/api/samples` ·
    `/api/label/tasks` · `/api/label/task` · `/api/accounts`). 라우터가 선언을
    보지 않고 넘겼으므로 콘솔 화면에서는 돌았고, 선언을 믿는 자리에서만 닿지
    않았다 — 라벨 검수(AI-L-03)와 계정 관리가 통째로.
    """
    class Drifted:
        write_payload = service_module.write_payload
        ApiError = service_module.ApiError
        NotAWriteRoute = service_module.NotAWriteRoute
        _ROUTES_POST = tuple(WRITE_ROUTES) + ("/api/invented",)

    with pytest.raises(WriteApiUnavailable) as raised:
        build_write_api(object(), Drifted)
    assert "/api/invented" in str(raised.value)


def test_a_service_without_the_table_is_refused_rather_than_guessed():
    class Empty:
        pass

    with pytest.raises(WriteApiUnavailable):
        build_write_api(object(), Empty)


# ---------------------------------------------------------------------------
# 세션은 Authorization 에서만 온다
# ---------------------------------------------------------------------------


def test_the_token_comes_only_from_the_authorization_header():
    assert token_from({"authorization": "Bearer abc"}) == "abc"
    assert token_from({"Authorization": "Bearer abc"}) == "abc"
    # 질의 문자열은 접근 로그와 브라우저 이력에 남는다 — 거기서 받지 않는다.
    assert token_from({"x-token": "abc"}) is None
    # **쿠키를 보지 않는다.** 교차 출처 쿠키를 허용하면 운영자가 방문한 아무
    # 사이트가 그 브라우저로 명령을 보낼 수 있다(CSRF).
    assert token_from({"cookie": "fms_session=abc"}) is None
    assert token_from({"authorization": "abc"}) is None, "Bearer 가 아니면 받지 않는다"
    assert token_from({"authorization": "Bearer   "}) is None


def test_login_hands_the_token_back_in_the_body_not_in_a_cookie(write_api):
    """콘솔 페이지는 같은 출처라 HttpOnly 쿠키가 맞았다. 가시화 앱은 다른
    출처이고, 그래서 본문에 싣고 앱이 Bearer 로 돌려준다."""
    status, body = _post(write_api, "/api/assume", {"account": "admin"})
    if status == 403:
        pytest.skip("계정이 설정된 설치 — 예시 자세가 닫혀 있다")
    assert status == 200, body
    assert body.get("session_token"), body
    assert "may_issue_command" in body["permissions"]


def test_an_unknown_example_account_is_refused_with_a_reason(write_api):
    status, body = _post(write_api, "/api/assume", {"account": "nobody-here"})
    assert status == 400
    assert "error" in body and isinstance(body["error"], str)


# ---------------------------------------------------------------------------
# 권한은 경로마다 다르고 표는 서비스의 것이다
# ---------------------------------------------------------------------------


def test_every_write_route_except_the_session_ones_has_its_own_permission(
        service_module):
    """하나의 큰 권한으로 묶으면 GT 만 만들 사람에게 로봇을 움직일 권한이 간다."""
    table = service_module._POST_PERMISSIONS
    session_routes = {"/api/login", "/api/logout", "/api/assume"}
    assert set(table) | session_routes == set(WRITE_ROUTES), (
        sorted(set(WRITE_ROUTES) - (set(table) | session_routes)))
    # 승인·적용은 학습을 돌린 사람과 다른 능력이어야 한다(AI-L-06).
    assert table["/api/training"] != table["/api/model"]
    # 돌려 보는 것과 적용하는 것도 다른 능력이다.
    assert table["/api/trial-run"] != table["/api/threshold"]


def test_a_write_without_the_capability_is_refused_and_says_which_one(write_api):
    status, body = _post(write_api, "/api/command",
                         {"robot": "go1-001", "action": "ping"})
    assert status in (401, 403), (status, body)
    reason = body["error"]
    assert reason == "login_required" or reason.startswith("missing_permission:")


def test_the_capability_actually_opens_the_path(write_api):
    """능력을 들고 오면 권한 검사를 통과한다 — 그 다음 거절은 **다른 사유**다.

    여기서는 게이트웨이에 명령 경로가 없어 503 `no_command_path` 가 맞다.
    권한 거절(403)과 경로 부재(503)를 한 칸에 담으면 "권한을 주면 될 것" 으로
    읽힌다(AI-C-05).
    """
    status, body = _post(write_api, "/api/assume", {"account": "admin"})
    if status != 200:
        pytest.skip("예시 자세가 닫혀 있다")
    token = body["session_token"]
    status, body = _post(write_api, "/api/command",
                         {"robot": "go1-001", "action": "ping"}, token=token)
    assert status != 403, (status, body)
    if status >= 400:
        assert not str(body["error"]).startswith("missing_permission")


# ---------------------------------------------------------------------------
# 오류 모양은 스키마 하나다
# ---------------------------------------------------------------------------


def test_a_body_that_is_not_json_is_named_as_such(write_api):
    status, out = write_api.answer("/api/command", b"{not json", {})
    assert status == 400
    assert json.loads(out.decode("utf-8")) == {"error": "body_not_json"}


def test_a_body_that_is_not_an_object_is_refused(write_api):
    status, out = write_api.answer("/api/command", b"[1, 2]", {})
    body = json.loads(out.decode("utf-8"))
    assert status == 400
    assert body == {"error": "body_must_be_object"}


def test_the_error_body_is_the_flat_token_shape(write_api):
    """`{"error": "<토큰>"}` 하나다 — `schemas/view_error.schema.json`.

    모양이 조회와 갈리면 같은 오류에 두 모양이 생기고, 뷰어는 어느 쪽을 읽어야
    할지 알 수 없다.
    """
    schema = json.loads(
        (_PKG / "schemas" / "view_snapshot.schema.json").read_text(encoding="utf-8"))
    shape = schema["$defs"]["error"]
    status, body = _post(write_api, "/api/scene")
    assert status == 405
    assert set(body) == {"error"}
    assert isinstance(body["error"], str)
    assert shape["properties"]["error"]["type"] == "string"


def test_an_unknown_subsystem_failure_is_named_not_silently_successful():
    """조용히 200 을 내면 빈 성공이 고장을 숨긴다."""
    class Boom(Exception):
        pass

    def exploding(*_args, **_kwargs):
        raise Boom("nope")

    api = FmsWriteApi(service=None, write_payload=exploding,
                      api_error=ValueError, not_a_write_route=LookupError)
    status, out = api.answer("/api/command", b"{}", {})
    assert status == 500
    assert json.loads(out.decode("utf-8")) == {"error": "subsystem_failed:Boom"}


def test_the_write_api_and_the_view_api_share_one_service(service_module):
    """두 번째 서비스를 만들면 운영자가 고친 값이 한쪽에만 보인다."""
    from integration.fms_view_api import build_view_api

    try:
        view = build_view_api(
            ui_config=_PKG / "config" / "status_ui.json",
            zone_profile=_PKG / "profiles" / "domains.json",
            goal_kinds=_PKG / "profiles" / "goal_kinds.example.json",
            with_fleet=False)
    except ViewApiUnavailable as error:                         # pragma: no cover
        pytest.skip(f"조회 계약을 세우지 못했다 — {error}")
    write = build_write_api(view.service, view.module)
    assert write.service is view.service
    assert view.module is service_module
