"""FMS 조회 계약은 **한 표에서** 나온다 — 콘솔과 게이트웨이가 같은 답을 한다.

implements: AI-O-06, AI-C-19, AI-C-06
tests: same table for both renderers, error shape matches the schema, read-only
       port refuses writes, missing service degrades without stopping
"""
from __future__ import annotations

import json
import pathlib

import pytest

from integration.fms_view_api import (
    ALLOWED_METHODS,
    VIEW_ROUTES,
    FmsViewApi,
    ViewApiUnavailable,
    build_view_api,
)

_PKG = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def view_api():
    try:
        return build_view_api(
            ui_config=_PKG / "config" / "status_ui.json",
            zone_profile=_PKG / "profiles" / "domains.json",
            goal_kinds=_PKG / "profiles" / "goal_kinds.example.json",
            with_fleet=False)
    except ViewApiUnavailable as error:                         # pragma: no cover
        pytest.skip(f"콘솔 서비스를 세우지 못했다 — {error}")


def _body(api, route, query=None):
    status, raw = api.answer(route, query or {})
    return status, json.loads(raw.decode("utf-8"))


def test_the_route_list_is_the_services_not_a_chosen_subset():
    """고르면 그 고름이 또 하나의 판정이 된다 — 앱이 새 화면을 만들 때마다
    우리 코드를 고쳐야 한다(원칙 #7).

    **부분집합이 아니라 같아야 한다**(2026-11-05). 전에는 `<=` 였고, 그래서 서비스가
    답하는 경로 넷(`/api/samples` · `/api/label/tasks` · `/api/label/task` ·
    `/api/accounts`)이 이 목록에 없는 것을 이 시험이 통과시켰다. 라벨 검수와 계정
    관리가 게이트웨이에서 통째로 닿지 않았고 아무도 몰랐다.
    """
    import sys

    from integration.fms_view_api import _load_console

    module = _load_console()
    assert set(VIEW_ROUTES) == set(module._ROUTES_GET), (
        "조회 목록이 서비스의 선언과 어긋난다 — "
        f"여기만: {sorted(set(VIEW_ROUTES) - set(module._ROUTES_GET))}, "
        f"서비스만: {sorted(set(module._ROUTES_GET) - set(VIEW_ROUTES))}")
    assert "/api/media" not in VIEW_ROUTES, "픽셀은 JSON 계약으로 나가지 않는다(AI-C-08)"
    assert sys is not None


def test_scene_answers_and_carries_the_contract_shape(view_api):
    status, body = _body(view_api, "/api/scene")
    assert status == 200
    assert "domains" in body and "space" in body


def test_an_unknown_route_is_404_not_a_guess(view_api):
    status, body = _body(view_api, "/api/not-a-thing")
    assert status == 404
    assert body == {"error": "unknown_route"}


def test_the_error_shape_is_the_schema_shape(view_api):
    """`{"error": "<토큰>"}` 하나다. 모양이 갈리면 같은 오류에 두 모양이 생긴다."""
    status, body = _body(view_api, "/api/twin")
    assert status == 400
    assert body == {"error": "zone_required"}, (
        f"schemas/view_error.schema.json 과 다른 모양이다: {body}")
    assert set(body) == {"error"} and isinstance(body["error"], str)


def test_a_missing_required_argument_keeps_the_services_reason(view_api):
    status, body = _body(view_api, "/api/zone")
    assert status == 400
    # 사유를 지어내지 않는다 — 서비스가 든 토큰 그대로다.
    assert body == {"error": "id_required"}


def test_the_query_name_mapping_is_not_redone_here(view_api):
    """`id` → `zone_id` 같은 짝짓기는 콘솔의 표가 한다. 여기서 다시 적지 않는다."""
    status, body = _body(view_api, "/api/zone", {"id": ["zone-503"]})
    assert status == 200
    assert body.get("zone_id") == "zone-503"


def test_recommend_needs_robot_and_says_so(view_api):
    status, body = _body(view_api, "/api/recommend")
    assert status == 400
    assert body == {"error": "robot_required"}


def test_a_gateway_without_a_commander_says_it_cannot_command(view_api):
    """**옳은 차이다.** 조회 포트는 명령 경로를 들고 있지 않다(AI-C-19).

    콘솔은 명령자를 들고 있어 `command_vocabulary: []`(있는데 비었다)를 낸다.
    게이트웨이는 **그 칸을 아예 내지 않는다** — 「칸 없음」이고, view-contract
    §3.2 가 「칸 없음 · null · 0 은 서로 다른 뜻」이라고 못박은 그 첫째다. 빈
    배열로 채우면 「명령할 수 있는데 할 말이 없다」로 읽힌다.
    """
    status, body = _body(view_api, "/api/bootstrap")
    assert status == 200
    assert body["commanding_available"] is False

    status, robot = _body(view_api, "/api/robot", {"id": ["ep-001"]})
    assert status == 200
    assert "command_vocabulary" not in robot, (
        "명령 경로가 없는데 어휘 칸을 냈다 — 빈 배열은 「있는데 비었다」로 읽힌다")


def test_read_only_is_declared_not_assumed():
    assert "GET" in ALLOWED_METHODS
    assert "POST" not in ALLOWED_METHODS and "PUT" not in ALLOWED_METHODS


def test_handles_only_claims_the_declared_routes(view_api):
    assert view_api.handles("/api/scene")
    assert view_api.handles("/api/zone?id=zone-503")
    assert not view_api.handles("/registry")
    assert not view_api.handles("/api/command")   # 쓰기는 여기 없다


def test_an_unbuildable_service_degrades_with_a_reason():
    with pytest.raises(ViewApiUnavailable):
        build_view_api(ui_config=_PKG / "config" / "does-not-exist.json",
                       zone_profile=_PKG / "profiles" / "domains.json",
                       goal_kinds=_PKG / "profiles" / "goal_kinds.example.json",
                       with_fleet=False)


def test_a_broken_service_is_500_not_a_silent_200():
    class _Boom:
        accounts = None

    def boom(*args, **kwargs):
        raise RuntimeError("terrible")

    api = FmsViewApi(service=_Boom(), view_payload=boom,
                     api_error=ValueError, not_a_view_route=LookupError)
    status, raw = api.answer("/api/scene", {})
    assert status == 500
    assert json.loads(raw.decode("utf-8")) == {"error": "RuntimeError"}


# ---------------------------------------------------------------------------
# 2026-11-05 — FMS 를 지우면서 드러난 결함 넷을 고정한다
# ---------------------------------------------------------------------------


def test_a_permission_gated_read_answers_instead_of_crashing(view_api):
    """**403 과 500 은 다른 사실이다.**

    `view_payload` 를 `do_GET` 에서 꺼낼 때 `self._require(...)` 가 여섯 줄 그대로
    따라와 모듈 수준에서 `self` 를 찾다 `NameError` 가 났다. 바깥의
    `except Exception` 이 그것을 500 `subsystem_failed:NameError` 로 덮어서,
    권한이 걸린 조회 여섯이 **콘솔에서도** 조용히 깨져 있었다.
    """
    for route, query in (("/api/overlay", {}),
                         ("/api/object", {"id": ["whatever"]}),
                         ("/api/failure", {"subject": ["whatever"]}),
                         ("/api/accounts", {}),
                         ("/api/label/tasks", {}),
                         ("/api/label/task", {"frame": ["x"]}),
                         # 이것은 경로 표가 아니라 **서비스가 안에서** 막는다.
                         # 같은 403 이라도 자리가 다르다는 사실을 함께 고정한다.
                         ("/api/lineage", {"id": ["x"]})):
        status, body = _body(view_api, route, query)
        assert status != 500, (route, status, body)
        assert "NameError" not in json.dumps(body), (route, body)


def test_a_logged_in_reader_is_not_frozen_out_by_the_startup_caller(view_api):
    """호출자를 **요청마다** 푼다 — 기동 시점에 굳히면 로그인한 사람도 403 이다.

    그래서 추론 근거 역추적(`/api/object`)·원인 추적(`/api/failure`)·운영자 수정
    장부(`/api/overlay`)가 가시화 앱에서 영원히 닫혀 있었다.
    """
    from integration.fms_write_api import build_write_api

    write = build_write_api(view_api.service, view_api.module)
    status, out = write.answer("/api/assume", b'{"account": "admin"}',
                               {"content-type": "application/json"})
    if status != 200:
        pytest.skip("예시 자세가 닫혀 있다 — 계정이 설정된 설치다")
    token = json.loads(out.decode("utf-8"))["session_token"]
    headers = {"Authorization": f"Bearer {token}"}

    anonymous, _ = _body(view_api, "/api/overlay")
    assert anonymous == 403, "토큰 없이 열려 있으면 권한 검사가 의미를 잃는다"

    status, raw = view_api.answer("/api/overlay", {}, headers)
    assert status == 200, raw
    assert view_api.caller_for(headers) is not view_api.caller


def test_the_requested_locale_is_honoured_and_an_unknown_one_is_refused(view_api):
    """`?locale=` 을 무시하면 뷰어는 자기 표가 쓰이고 있다고 착각한다."""
    status, body = _body(view_api, "/api/bootstrap", {"locale": ["en"]})
    assert status == 200
    assert body["locale"] == "en"
    status, body = _body(view_api, "/api/bootstrap", {"locale": ["ja"]})
    assert status == 400
    assert body == {"error": "unknown_locale"}
    # 묻지 않으면 기본 언어다 — 거절하지 않는다.
    status, body = _body(view_api, "/api/bootstrap")
    assert status == 200 and body["locale"] == view_api.locale


def test_the_absent_path_word_belongs_to_the_contract_not_the_transport(view_api):
    """`not_found` 와 `unknown_path` 가 같은 사실의 두 이름이 되면, 뷰어는
    "아직 없는 기능" 과 "고장" 을 가르려고 보던 토큰을 잃는다."""
    status, body = view_api.unknown_path()
    assert status == 404
    assert json.loads(body.decode("utf-8")) == {"error": "unknown_path"}


def test_the_contract_version_is_available_for_the_response_header(view_api):
    """판이 문서에만 있으면 뷰어가 자기 기대와 맞출 길이 없다."""
    import re

    name = view_api.server_name()
    assert name and re.fullmatch(r"FMS/\d+\.\d+", name), name
    hub = json.loads(
        (_PKG / "schemas" / "view_snapshot.schema.json").read_text(encoding="utf-8"))
    assert name.endswith(hub["x-view-contract-version"]), (
        "머리에 실을 판과 공표한 스키마의 판이 **같아야** 한다")
