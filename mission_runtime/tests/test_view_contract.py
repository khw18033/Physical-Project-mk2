"""implements: AI-O-06 (통합 운영 상태 뷰 제공)
관련: AI-C-01 (공통 데이터 규약), AI-C-15 (가시화·DT 엔진은 선택 소비자), AI-C-19 (AI
판단·권한·책임 경계), AI-C-02 (좌표계 경계), AI-C-05 (선택 기능 부재는 장애가 아니다)
tests: (a) 실제 서비스의 실제 GET 응답이 `schemas/view_*.schema.json` 을 통과한다,
(b) 조회 경로로는 아무것도 바꿀 수 없다(POST → 405), (c) 어떤 응답에도 색·픽셀·폰트·
도형 같은 표현 칸이 없다, (d) 전역 좌표는 자기 칸 밖으로 새어 나오지 않고, 경계
재합의가 선언되지 않은 현장에는 그 칸 자체가 없다, (e) 모르는 칸이
양방향으로 살아남는다, (f) 계약 판이 **문서가 아니라 응답으로** 실려 온다, (g) 두
언어의 키 집합이 같다, (h) never·stale·fresh 가 모두 표현되고 서로 다르다, (i) 권한
표는 데이터로 오고 서버도 같은 판정을 한다, (j) 아직 연결되지 않은 끝점은 503 으로
"기능 없음"을 말한다.

이 파일이 지키는 것은 **가시화 절반을 독립적으로 교체할 수 있다**는 성질이다. 다른
팀이 React 든 Unity WebGL 이든 다른 뷰어를 우리 파이썬을 읽지 않고 만들 수 있어야
하고, 그러려면 경계가 문서(`docs/view-contract.md`)와 기계검사(이 파일)로 **둘 다**
고정되어 있어야 한다. 문서만 있으면 코드가 조용히 멀어지고, 시험만 있으면 바깥 팀이
무엇을 믿어도 되는지 알 수 없다.

서비스는 `tools/fms_console/serve.py::build_service` 가 쓰는 것과 **같은 실제 설정**
으로 세우고 가짜 payload 를 만들지 않는다 — 계약이 지키는 대상은 실제로 나가는 응답
이기 때문이다. `tools/status_ui/serve.py` 와 `tools/fms_console/serve.py` 는 진입 파일
이름이 둘 다 `serve.py` 라서 `import serve` 는 먼저 올라온 쪽을 집는다. 그래서 이름이
아니라 **경로로** 싣는다(fms_console 쪽 `_load_status_ui()` 와 같은 수법).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = PROJECT_ROOT / "schemas"
CONSOLE_SERVE = PROJECT_ROOT / "tools" / "fms_console" / "serve.py"
UI_CONFIG = PROJECT_ROOT / "config" / "status_ui.fms.example.json"
DOMAIN_PROFILE = PROJECT_ROOT / "profiles" / "domains.example.json"
GOAL_KINDS = PROJECT_ROOT / "profiles" / "goal_kinds.example.json"

#: 신선·노후의 경계. 계약은 숫자(`last_seen_age_s`)만 내고 경계는 배포가 정한다 —
#: 이 값은 **이 시험이 쓰는 경계**일 뿐이고 서버가 강요하는 값이 아니다.
STALE_AFTER_S = 60.0


#: 콘솔 모듈을 import 할 수 있게 그 디렉터리를 경로에 둔다. `Caller` 는 시험이 쓰는
#: 권한 계산과 **같은 것**이어야 하므로 가짜를 만들지 않고 그대로 들여온다.
if str(CONSOLE_SERVE.parent) not in sys.path:
    sys.path.insert(0, str(CONSOLE_SERVE.parent))

from accounts import Caller  # noqa: E402

# ---------------------------------------------------------------------------
# 실제 서비스 세우기
# ---------------------------------------------------------------------------


def _load_console_serve():
    """`tools/fms_console/serve.py` 를 경로로 싣는다(이름 충돌을 피한다)."""
    name = "fms_console_serve_under_view_contract_test"
    if name in sys.modules:
        return sys.modules[name]
    for candidate in (PROJECT_ROOT.parent,):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))

    spec = importlib.util.spec_from_file_location(name, CONSOLE_SERVE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # `from __future__ import annotations` + dataclass 는 exec 전에 모듈이
    # sys.modules 에 있어야 필드 타입을 해소할 수 있다.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def console():
    return _load_console_serve()


@pytest.fixture(scope="module")
def service(console):
    """`build_service` 가 쓰는 것과 같은 실제 설정. 가짜 데이터를 넣지 않는다."""
    return console.build_service(
        ui_config=UI_CONFIG,
        zone_profile=DOMAIN_PROFILE,
        goal_kinds=GOAL_KINDS,
        with_fleet=True,
    )


@pytest.fixture(scope="module")
def base_url(console, service):
    """실제 HTTP 로 띄운다 — 조회·제어 분리는 메서드와 상태 코드의 성질이라
    서비스 객체를 직접 부르면 확인할 수 없다."""
    console.FmsHandler.service = service
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), console.FmsHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = httpd.server_address[0], httpd.server_address[1]
        base = f"http://{host}:{port}"
        # 조회에도 권한이 필요해졌으므로 시험은 실제 문으로 들어와 둔다. 계정 파일이
        # 없는 예시 자세라 비밀번호 없이 역할을 고를 수 있다.
        _SESSION.clear()
        _assume(base, "admin")
        yield base
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# HTTP 도우미
# ---------------------------------------------------------------------------


#: 지금 요청에 붙일 세션 토큰. 역할을 고른 뒤 채워진다.
_SESSION: dict[str, str] = {}


def _assume(base: str, account_id: str) -> str:
    """예시 자세에서 **예시 계정**을 골라 세션을 받는다.

    `?role=` 질의 인자로 권한을 올리는 길은 2026-11-03 에 없어졌다 — 질의 문자열은
    접근 로그와 브라우저 이력에 남아 토큰이 비밀이 아니게 되고, 애초에 그것은 권한
    검사가 아니라 보기 편의였다. 그래서 시험도 실제 문으로 들어온다.

    고르는 것이 역할에서 계정으로 바뀐 이유는 따로다(2026-11-03 오후): 역할을
    고르면 관리자가 **한 사람에게** 부여한 능력이 그 사람에게 생기지 않는다.
    """
    status, headers, body = _request("POST", f"{base}/api/assume",
                                     {"account": account_id}, token="")
    assert status == 200, (status, body)
    # 토큰은 **본문에 담기지 않는다** — 쿠키로만 나간다. 본문에 실으면 페이지
    # 스크립트가 읽을 수 있고, HttpOnly 로 막은 의미가 사라진다.
    cookie = headers.get("Set-Cookie") or ""
    token = cookie.split(";", 1)[0].partition("=")[2]
    assert token, f"Set-Cookie 에 토큰이 없다: {cookie!r}"
    _SESSION["token"] = token
    return token


def _request(method: str, url: str, body: dict | None = None, *,
             token: str | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data else {}
    bearer = _SESSION.get("token") if token is None else token
    if bearer:
        # 헤더로 보낸다 — 쿠키도 서버가 받지만 시험이 쿠키 항아리를 들고 다닐 이유는 없다.
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, dict(response.headers), json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        return error.code, dict(error.headers), json.loads(raw) if raw else None


def _get(base: str, path: str, **query):
    query.setdefault("locale", "en")
    parts = "&".join(f"{k}={v}" for k, v in query.items() if v is not None)
    return _request("GET", f"{base}{path}?{parts}")


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def validators() -> dict[str, Draft202012Validator]:
    registry = Registry()
    schemas = {}
    for path in sorted(SCHEMA_DIR.glob("view_*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name.removeprefix("view_").removesuffix(".schema.json")] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return {
        name: Draft202012Validator(schema, registry=registry)
        for name, schema in schemas.items()
    }


@pytest.fixture(scope="module")
def hub() -> dict:
    return json.loads((SCHEMA_DIR / "view_snapshot.schema.json").read_text(encoding="utf-8"))


def _assert_valid(validator: Draft202012Validator, payload, tag: str) -> None:
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, (
        f"{tag} does not satisfy the published view contract: "
        + "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors[:5])
    )


@pytest.fixture(scope="module")
def payloads(base_url, service) -> dict[str, object]:
    """한 번 받아 여러 시험이 같은 응답을 본다. 전수다 — 도메인·구역·로봇·그래프를
    하나만 보면 다른 배치 모양에서 깨지는 칸을 놓친다."""
    out: dict[str, object] = {}
    status, _, boot = _get(base_url, "/api/bootstrap")
    assert status == 200
    out["bootstrap"] = boot
    status, _, scene = _get(base_url, "/api/scene")
    assert status == 200
    out["scene"] = scene

    domains, zones, robots, graphs, recommendations = {}, {}, {}, {}, {}
    for domain_id in service.fleet.domain_ids():
        status, _, body = _get(base_url, "/api/domain", id=domain_id)
        assert status == 200, (domain_id, body)
        domains[domain_id] = body
    for zone_id in service.fleet.zone_ids():
        status, _, body = _get(base_url, "/api/zone", id=zone_id)
        assert status == 200, (zone_id, body)
        zones[zone_id] = body
    goal_kinds = [entry["function_id"] for entry in service.fleet.functions]
    for node_id in sorted(service.fleet.facts):
        status, _, body = _get(base_url, "/api/robot", id=node_id)
        assert status == 200, (node_id, body)
        robots[node_id] = body
        status, _, body = _get(base_url, "/api/recommend", robot=node_id)
        assert status == 200, (node_id, body)
        recommendations[node_id] = body
        zone_id = service.fleet.declared_zone_of(node_id)
        if zone_id is None:
            continue
        for goal_kind in goal_kinds:
            status, _, body = _get(
                base_url, "/api/subtasks", robot=node_id, zone=zone_id, function=goal_kind)
            assert status == 200, (node_id, goal_kind, body)
            graphs[f"{node_id}|{goal_kind}"] = body

    out["domains"] = domains
    out["zones"] = zones
    out["robots"] = robots
    out["recommendations"] = recommendations
    out["subtask_graphs"] = graphs
    return out


# ---------------------------------------------------------------------------
# (a) 실제 응답이 공표한 스키마를 통과한다
# ---------------------------------------------------------------------------


def test_every_get_payload_satisfies_its_published_schema(payloads, validators):
    """바깥 팀은 우리 파이썬이 아니라 이 스키마를 읽는다. 스키마와 실제 응답이
    갈라지면 그 팀의 뷰어가 우리 쪽 변경 없이 깨진다 — 그 틈을 여기서 막는다."""
    _assert_valid(validators["bootstrap"], payloads["bootstrap"], "/api/bootstrap")
    _assert_valid(validators["scene"], payloads["scene"], "/api/scene")
    for domain_id, body in payloads["domains"].items():
        _assert_valid(validators["domain"], body, f"/api/domain?id={domain_id}")
    for zone_id, body in payloads["zones"].items():
        _assert_valid(validators["zone"], body, f"/api/zone?id={zone_id}")
    for node_id, body in payloads["robots"].items():
        _assert_valid(validators["robot"], body, f"/api/robot?id={node_id}")
    for node_id, body in payloads["recommendations"].items():
        _assert_valid(validators["recommendations"], body, f"/api/recommend?robot={node_id}")
    for tag, body in payloads["subtask_graphs"].items():
        _assert_valid(validators["subtask_graph"], body, f"/api/subtasks[{tag}]")


def test_the_whole_view_assembles_into_one_snapshot(payloads, validators, hub):
    """AI-O-06 은 "소스별 개별 조회가 아니라 하나의 통합 스냅샷"을 요구한다. 지금 전송은
    끝점이 여러 개지만 **모양은 한 덩어리로 묶을 수 있어야** 한다 — 그래야 HTTP 가 아닌
    전송(한 번에 한 장을 밀어 주는 구독 채널)으로 옮길 때 계약을 다시 쓰지 않는다."""
    snapshot = {
        "view_contract_version": hub["x-view-contract-version"],
        "bootstrap": payloads["bootstrap"],
        "scene": payloads["scene"],
        "domains": list(payloads["domains"].values()),      # type: ignore[union-attr]
        "zones": list(payloads["zones"].values()),          # type: ignore[union-attr]
        "robots": list(payloads["robots"].values()),        # type: ignore[union-attr]
        "subtask_graphs": list(payloads["subtask_graphs"].values()),  # type: ignore[union-attr]
    }

    _assert_valid(validators["snapshot"], snapshot, "composed view snapshot")


def test_the_robots_inside_a_zone_use_the_same_shape_as_the_robot_endpoint(payloads, validators):
    """같은 사실을 두 모양으로 내면 뷰어가 두 갈래 코드를 들고 가야 한다 —
    AI-O-06 이 "같은 사실이 여러 표시 영역에 나타나는 경우 한 출처에서 파생"하라고
    요구하는 이유가 그것이다."""
    seen = 0
    for zone_id, zone in payloads["zones"].items():
        for robot in zone["robots"]:
            _assert_valid(validators["robot"], robot, f"/api/zone?id={zone_id} robots[]")
            seen += 1
    assert seen, "no zone carried a robot — the fixture would not be proving anything"


def test_error_bodies_are_controlled_tokens_not_sentences(base_url, validators, console):
    """오류 본문이 문장이면 뷰어가 그것을 화면에 그대로 띄우고, 그 순간 서버가
    표시 문구를 정하게 된다. 토큰만 내고 문구는 뷰어의 문자열표에서 만든다."""
    for path, query, expected in (
        ("/api/zone", {"id": "no-such-zone"}, 404),
        ("/api/robot", {"id": "no-such-robot"}, 404),
        ("/api/domain", {}, 400),
        ("/api/bootstrap", {"locale": "no-such-locale"}, 400),
    ):
        status, _, body = _get(base_url, path, **query)
        assert status == expected, (path, query, status, body)
        _assert_valid(validators["error"], body, f"{path} error body")
        assert re.fullmatch(r"[a-z0-9_]+", body["error"]), body

    # 예시 자세(계정 파일 없음)에서는 토큰 없이도 **조회가 열려 있다** — 그래야 역할
    # 선택 화면 자체가 뜬다. 처음에 이 자리에서 401 을 기대했고 그것이 틀렸다:
    # 로그인 폼을 띄울 화면조차 막으면 들어올 길이 없다.
    status, _, body = _request("GET", f"{base_url}/api/bootstrap?locale=en", token="")
    assert status == 200, (status, body)

    # 열려 있는 것은 조회뿐이다. 바꾸는 일은 역할을 고른 뒤에만 된다.
    status, _, body = _request("POST", f"{base_url}/api/command",
                               {"robot": "x", "action": "stop"}, token="")
    assert status == 403, (status, body)
    assert body["error"] == f"missing_permission:{console.PERM_COMMAND}"
    _assert_valid(validators["error"], body, "403 body")

    # 403 의 사유에는 **빠진 능력 이름**이 붙는다. 콜론 뒤가 붙어도 토큰 어휘다.
    # `user1` 은 조회만 들고 시작하는 예시 계정이다.
    viewer_token = _assume(base_url, "user1")
    status, _, body = _request("POST", f"{base_url}/api/command",
                               {"robot": "x", "action": "stop"}, token=viewer_token)
    assert status == 403, (status, body)
    assert re.fullmatch(r"[a-z0-9_]+:[a-z0-9_]+", body["error"]), body
    _assume(base_url, "admin")


# ---------------------------------------------------------------------------
# (b) 조회와 제어는 다른 계약이다
# ---------------------------------------------------------------------------


_GET_PATHS = ("/api/bootstrap", "/api/scene", "/api/domain", "/api/zone", "/api/robot",
              "/api/recommend", "/api/subtasks", "/api/explain", "/api/twin", "/api/object",
              "/api/candidates", "/api/transit", "/api/mission", "/api/failure",
              "/api/spatial", "/api/overlay", "/api/lineage", "/api/deployment",
              "/api/calibration", "/api/approval")


@pytest.mark.parametrize("path", _GET_PATHS)
def test_no_get_path_can_change_anything(base_url, path, validators):
    """AI-O-06: "상태 뷰는 조회 전용이어야 하며 이 경로를 통해 실행 상태를 변경하는
    수단을 제공해서는 안 된다." 관찰이 실행에 개입할 수 없다는 것은 문서의 약속이
    아니라 메서드 차원의 성질이어야 한다 — 그래서 조회 경로의 POST 는 본문을 읽기도
    전에 405 로 끊긴다."""
    status, _, body = _request("POST", f"{base_url}{path}?role=admin", {"anything": "at all"})

    assert status == 405, (path, status, body)
    assert body["error"] == "read_only_path"
    _assert_valid(validators["error"], body, f"POST {path}")


def test_control_is_a_separate_explicitly_listed_set_of_calls(base_url, console):
    """제어는 숨은 질의 인자가 아니라 **목록에 적힌 세 경로**다. 그 목록이 조회
    경로와 겹치면 위의 405 보장이 사라지므로 겹치지 않음을 함께 고정한다."""
    assert set(console._ROUTES_POST) == {
        # 세션을 만드는 셋. 권한을 요구할 수 없다 — 요구하면 들어올 길이 없다.
        "/api/login", "/api/logout", "/api/assume",
        # 상태를 바꾸는 것들. 각자 필요한 능력만 요구한다.
        "/api/command", "/api/correction", "/api/placement", "/api/survey",
        "/api/detection", "/api/pose", "/api/account",
        # 사람이 만든 정답. 조회로 두면 관찰이 학습 후보를 만들게 된다.
        "/api/label",
        # 배포 네 가지. 조회(`/api/deployment`·`/api/calibration`·`/api/approval`)와
        # **다른 경로**인 것이 요점이다 — 같은 경로로 읽고 쓰면 위의 405 보장이
        # 그 경로에서만 사라진다.
        "/api/join", "/api/join-step", "/api/camera-info", "/api/training",
        "/api/model",
        # 임무를 한 걸음 **진행시키는** 길. 계획 읽기(`GET /api/mission`)와 이름이
        # 겹치지 않는 것이 요점이다 — 읽는 이름과 쓰는 이름이 같으면 위의 405 보장이
        # 그 경로에서 사라진다.
        "/api/mission-run",
    }
    assert not set(console._ROUTES_POST) & set(_GET_PATHS)

    # 제어 경로에 GET 을 보내면 조회 계약이 아니므로 404 다 — 조회로 읽히지 않는다.
    for path in console._ROUTES_POST:
        status, _, _body = _get(base_url, path)
        assert status == 404, (path, status)


# ---------------------------------------------------------------------------
# (c)(d) 서버는 뜻만 낸다 — 표현도 전역 좌표도 내지 않는다
# ---------------------------------------------------------------------------


#: 표현 결정을 가리키는 낱말. 키를 낱말 단위로 쪼개 비교한다 — 부분문자열로 보면
#: `fulfilled` 이 `fill` 에 걸리는 식으로 엉뚱한 칸을 잡는다.
PRESENTATION_WORDS = frozenset({
    "color", "colors", "colour", "colours", "fill", "stroke", "font", "fonts",
    "px", "pixel", "pixels", "opacity", "css", "style", "styles", "stylesheet",
    "theme", "icon", "icons", "sprite", "shape", "shapes", "marker", "glyph",
    "rgb", "rgba", "hsl", "zindex", "margin", "padding", "viewbox", "dasharray",
    "tooltip", "cursor", "animation", "gradient", "texture", "material", "mesh",
})

#: 전역 좌표를 가리키는 낱말. AI-C-02 는 2026-11-03 개정으로 전역 변환을 AI 소유로
#: 옮겼지만, 그 숫자가 **이 계약으로 나가는** 것은 그 현장에서 경계 재합의가 기록된
#: 뒤다(AI-C-19). 선언되지 않은 현장에서 이 낱말이 새어 나오면 같은 사실을 두 곳이
#: 권위 있게 말하게 되고, 그때부터 화면과 트윈이 어긋난다.
GLOBAL_COORDINATE_WORDS = frozenset({
    "lat", "latitude", "lon", "lng", "longitude", "utm", "epsg", "wgs84",
    "easting", "northing", "mgrs", "geohash", "altitude_msl",
})

#: 전역 숫자가 **정당하게 사는 유일한 칸**. 그 내용은 낱말 검사에서 훑지 않는다 —
#: 훑으면 그 칸의 존재 자체가 금지된다. 대신 그 칸이 **언제** 나올 수 있는지를
#: 형제 시험(`test_a_site_that_declared_the_re_agreement_...`)이 고정한다.
GLOBAL_CELL = frozenset({"at_global"})


def _keys(node, *, skip: frozenset[str] = frozenset()) -> set[str]:
    """payload 안의 모든 칸 이름. `skip` 에 적힌 칸의 **내용**은 들어가지 않는다."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(str(key))
            if key in skip:
                continue
            found |= _keys(value, skip=skip)
    elif isinstance(node, list):
        for item in node:
            found |= _keys(item, skip=skip)
    return found


def _words(key: str) -> set[str]:
    return {part for part in re.split(r"[^A-Za-z0-9]+", key.lower()) if part}


#: 내용을 훑지 않는 칸. `strings` 는 **번역문 자체**이고 `facts_vocabulary` 는 사실
#: 토큰의 뜻풀이다 — 표시 문구가 정당하게 사는 유일한 자리다. 둘의 키는 뷰어가 쓰는
#: 문자열 id 이므로 표현 낱말 검사의 대상이 아니다. 색·배치·글꼴은 둘 중 어디에도
#: 없고, 그것이 "문자열표는 표현이 아니다"의 뜻이다.
_TEXT_RESOURCES = frozenset({"strings", "facts_vocabulary"})


def _iter_payloads(payloads: dict[str, object]):
    """끝점 응답 하나하나를 (이름, 본문) 으로 낸다. `payloads` 묶음의 사전 키(id·goal
    kind 를 이어 붙인 시험용 이름)는 응답의 일부가 아니므로 훑지 않는다."""
    yield "/api/bootstrap", payloads["bootstrap"]
    yield "/api/scene", payloads["scene"]
    for group, path in (("domains", "/api/domain"), ("zones", "/api/zone"),
                        ("robots", "/api/robot"), ("recommendations", "/api/recommend"),
                        ("subtask_graphs", "/api/subtasks")):
        for tag, body in payloads[group].items():  # type: ignore[union-attr]
            yield f"{path}[{tag}]", body


def test_no_payload_carries_a_presentation_decision(payloads):
    """뷰어가 바뀌어도 서버가 그대로여야 하는 이유는 서버가 **무엇인지**만 말하고
    **어떻게 보일지**는 말하지 않기 때문이다. 색 하나가 응답에 들어오는 순간 그 색을
    쓰지 않는 뷰어(예: Unity 머티리얼)는 계약의 일부를 버려야 하고, 버린 칸은 다음
    변경에서 조용히 어긋난다."""
    offenders = {}
    for name, body in _iter_payloads(payloads):
        for key in _keys(body, skip=_TEXT_RESOURCES):
            bad = _words(key) & PRESENTATION_WORDS
            if bad:
                offenders[f"{name}:{key}"] = sorted(bad)
    assert not offenders, (
        "presentation-shaped keys appeared in read-only payloads; colour, pixels, "
        f"typography, icon and shape choices belong to the viewer: {offenders}"
    )


def test_no_payload_claims_a_global_coordinate(payloads):
    """전역 좌표는 **자기 칸 밖에서는 나오지 않는다**.

    AI-C-02 는 2026-11-03 개정으로 전역 변환을 AI 소유로 옮겼지만 같은 사실을
    백엔드(BE-C-04)·디지털 트윈(DT-03)이 아직 authoritative 로 적고 있고, AI-C-19 가
    경계 재합의를 선행 조건으로 둔다. 그래서 재합의가 선언되지 않은 현장 — 실제 현장
    둘이 그 상태다 — 에서는 전역 낱말이 어느 칸에도 없어야 한다.

    선언된 현장에서도 전역 숫자는 `at_global` **하나**에만 산다. 로컬 자리 칸에 섞여
    들어가면 AI-C-02 의 마지막 문장("로컬 값과 전역 값은 같은 칸에 담지 않는다")이
    깨지고, 그 칸을 받는 쪽은 단위와 기준을 추측하게 된다. 이 시험은 그 칸의 내용만
    비껴가고 **나머지 전부**를 본다.
    """
    offenders = {}
    for name, body in _iter_payloads(payloads):
        for key in _keys(body, skip=_TEXT_RESOURCES | GLOBAL_CELL):
            bad = _words(key) & GLOBAL_COORDINATE_WORDS
            if bad:
                offenders[f"{name}:{key}"] = sorted(bad)
    assert not offenders, f"global-coordinate keys leaked into the view contract: {offenders}"


def _domains_by_release(payloads) -> tuple[dict, dict]:
    """공표된 도메인 장면을 전역 숫자가 나가는 것과 안 나가는 것으로 가른다."""
    released, withheld = {}, {}
    for domain_id, body in payloads["domains"].items():      # type: ignore[union-attr]
        if body["geo"].get("coordinates_in_view_contract"):
            released[domain_id] = body
        else:
            withheld[domain_id] = body
    return released, withheld


def _global_cells(node) -> list[dict]:
    """payload 안의 모든 `at_global` 블록."""
    found: list[dict] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "at_global":
                found.append(value)
            else:
                found += _global_cells(value)
    elif isinstance(node, list):
        for item in node:
            found += _global_cells(item)
    return found


def test_a_site_that_has_not_declared_the_re_agreement_carries_no_global_block(payloads):
    """재합의가 선언되지 않은 현장이 **기본값**이고, 그 기본값은 오늘과 같다.

    숫자가 나가지 않는 것으로 끝나지 않는다 — 무엇이 없어서인지가 사유 토큰으로 와야
    그 현장이 다음에 무엇을 해야 하는지 알 수 있다(AI-C-05: 선택 계층의 부재는 사유가
    있는 상태이고 고장이 아니다).
    """
    _released, withheld = _domains_by_release(payloads)
    assert withheld, "선언되지 않은 현장이 하나는 있어야 이 성질을 보일 수 있다"

    known_reasons = {"no_datum", "datum_unverified", "accuracy_unmeasured",
                     "boundary_not_reagreed"}
    for domain_id, body in withheld.items():
        assert not _global_cells(body), f"{domain_id} leaked a global block"
        geo = body["geo"]
        reason = geo.get("coordinates_withheld_reason", geo.get("reason"))
        assert reason in known_reasons, (domain_id, reason)
        # 로컬 그림은 그대로다 — 전역 계층이 꺼진 것이 지도를 끄지 않는다.
        assert body["zones"], domain_id
        assert body["space"]["unit"], domain_id


def test_a_site_that_declared_the_re_agreement_puts_the_global_value_in_its_own_block(
    payloads, validators
):
    """선언된 현장에서는 전역 값이 **로컬 값 옆의 자기 블록**으로 온다.

    확인하는 것은 셋이다. (a) 두 값이 같은 칸에 섞이지 않는다 — 전역 블록에 `x`/`y`
    가 없고 로컬 칸에 위경도가 없다(AI-C-02). (b) 전역 블록이 **재료의 선언된
    정확도**를 들고 다닌다 — 그 숫자가 로컬 실측보다 정확한 척할 수 없어야 한다.
    (c) 그 현장이 네 조건을 실제로 전부 만족했다 — 합의 기록이 블록에 있고 datum 이
    검증됐고 정확도가 선언됐다.
    """
    released, _withheld = _domains_by_release(payloads)
    assert released, (
        "배포된 선언에 재합의가 기록된 현장이 하나는 있어야 이 경로가 실제 데이터로 "
        "지나간다 — 없으면 이 시험은 아무것도 지키지 않는다"
    )

    for domain_id, body in released.items():
        geo = body["geo"]
        assert "coordinates_withheld_reason" not in geo, domain_id
        agreement = geo["boundary_agreement"]
        assert agreement["subject"] == "global_coordinate_ownership"
        assert {"ai", "backend"} <= set(agreement["agreed_by"]), agreement
        assert agreement["agreed_at"] and agreement["supersedes"]
        assert agreement["document"].get("url") or agreement["document"].get("name")
        # 예시 현장의 합의는 예시로 표시된다 — 예시 데이터가 실제 합의처럼 읽히면
        # 이 계약이 막으려는 것을 그대로 저지른다.
        assert agreement["example"] is bool(body["site"].get("example"))
        assert geo["datum"]["verified"] is True
        assert geo["datum"]["accuracy_state"] == "declared"

        cells = _global_cells(body)
        assert cells, f"{domain_id} declared the re-agreement but carried no global block"
        for cell in cells:
            assert set(cell) >= {"lat", "lon", "crs", "verified", "accuracy_m",
                                 "accuracy_state", "datum_id", "derived_from"}
            # (a) 같은 칸에 담지 않는다.
            assert "x" not in cell and "y" not in cell and "at" not in cell
            # (b) 재료의 확신을 그대로 들고 온다. 미측정은 이 칸에 올 수 없다.
            assert cell["accuracy_state"] == "declared"
            assert isinstance(cell["accuracy_m"], (int, float)) and cell["accuracy_m"] > 0
            assert cell["verified"] is True
            assert cell["datum_id"] == geo["datum"]["datum_id"]
            # 재료가 살던 프레임은 말하되 로컬 숫자는 복사하지 않는다.
            assert cell["derived_from"]["kind"] == "site_local"
            assert cell["derived_from"]["domain_id"] == domain_id
            assert "x" not in cell["derived_from"]

        for zone in body["zones"]:
            for row in list(zone["infrastructure"]) + list(zone["robots"]):
                if row.get("at") is None:
                    # 자리를 모르는 장치는 전역 블록도 없다 — 원점으로 올리지 않는다.
                    assert "at_global" not in row, (domain_id, row)
                    continue
                assert set(row["at"]) == {"x", "y"}, (domain_id, row)
                assert "at_global" in row, (domain_id, row)

    # 블록이 더해져도 공표한 스키마를 그대로 통과한다 — 바깥 팀이 읽는 것이 그것이다.
    for domain_id, body in released.items():
        _assert_valid(validators["domain"], body, f"/api/domain?id={domain_id}")


def test_coordinates_say_which_plane_they_live_in(payloads):
    """좌표만 주고 평면을 말하지 않으면 뷰어가 단위를 추측한다. 도메인마다 `unit` 이
    다르므로(meter / index) 추측은 반드시 틀린다."""
    assert payloads["scene"]["space"]["unit"]
    for zone_id, zone in payloads["zones"].items():
        assert zone["space"]["unit"], zone_id
        for robot in zone["robots"]:
            at = robot.get("at")
            if at is not None:
                assert set(at) >= {"x", "y"}, (zone_id, robot["node_id"])


# ---------------------------------------------------------------------------
# (e) 모르는 칸은 양쪽이 통과시킨다
# ---------------------------------------------------------------------------


def test_a_viewer_may_receive_fields_it_has_never_heard_of(payloads, validators):
    """우리가 칸을 **더하는** 변경은 뷰어를 깨지 않아야 한다. 그래야 가시화 팀이 우리
    배포 주기에 묶이지 않는다. 스키마가 모르는 칸을 거절하면 그 성질이 사라진다
    (통합데이터규약 R12 — 받는 쪽은 모르는 칸을 통과시킨다)."""
    grown = copy.deepcopy(payloads["zones"])
    for zone in grown.values():
        zone["some_future_zone_field"] = {"added": "in a later minor version"}
        for robot in zone["robots"]:
            robot["some_future_robot_field"] = 1
            for verdict in robot["functions"]:
                verdict["some_future_verdict_field"] = ["a", "b"]
        for item in zone["infrastructure"]:
            item["some_future_device_field"] = None
    for zone_id, zone in grown.items():
        _assert_valid(validators["zone"], zone, f"grown /api/zone?id={zone_id}")

    grown_graph = copy.deepcopy(next(iter(payloads["subtask_graphs"].values())))
    grown_graph["some_future_graph_field"] = True
    for node in grown_graph["nodes"]:
        node["some_future_node_field"] = {"x": 1}
    _assert_valid(validators["subtask_graph"], grown_graph, "grown subtask graph")


def test_the_server_tolerates_fields_it_has_never_heard_of(base_url, service):
    """반대 방향도 같아야 한다. 뷰어가 자기 쪽 칸을 덧붙여 보냈을 때 서버가 거절하면
    뷰어는 우리 쪽 판올림을 기다려야 하고, 그 기다림이 경계를 썩게 한다.

    자리 수정은 조회가 아니라 **별도 제어 계약**이라 POST 로만 되고, 그래서 이 시험은
    제어 경로에서 돈다. 끝에 선언된 자리로 되돌려 다른 시험이 보는 상태를 바꾸지 않는다.
    """
    zone_id = next(z for z in service.fleet.zone_ids() if service.fleet.movable_devices(z))
    device_id = service.fleet.movable_devices(zone_id)[0]
    try:
        status, _, body = _request(
            "POST", f"{base_url}/api/placement?role=admin",
            {
                "device_id": device_id,
                "zone_id": zone_id,
                "at": {"x": 1.5, "y": 2.5},
                "reason": "view contract round trip",
                "sent_by_a_future_viewer": {"renderer": "unity-webgl", "build": 42},
            },
        )
        assert status == 202, (status, body)
        assert body["device_id"] == device_id
        assert body["at"] == {"x": 1.5, "y": 2.5}
        assert body["at_origin"] == "operator_edit"
    finally:
        status, _, _body = _request(
            "POST", f"{base_url}/api/placement?role=admin",
            {"device_id": device_id, "zone_id": zone_id, "reset": True})
        assert status == 202
    assert service.fleet.placement_origin(device_id) == "declared"


def test_unknown_query_parameters_do_not_break_a_read(base_url, validators):
    """뷰어가 자기 추적용 인자를 붙이는 일은 흔하다. 서버가 그것을 오류로 보면
    뷰어는 질의 문자열까지 우리와 맞춰야 한다."""
    status, _, body = _get(base_url, "/api/scene", renderer="unity-webgl", cache_buster="7")

    assert status == 200
    _assert_valid(validators["scene"], body, "/api/scene with unknown query")


# ---------------------------------------------------------------------------
# (f) 계약 판은 응답으로 실려 온다
# ---------------------------------------------------------------------------


def test_the_contract_version_is_served_not_only_documented(base_url, hub):
    """문서에만 적힌 판은 뷰어가 실행 중에 읽을 수 없다. 뷰어가 **거부하거나 맞출 수**
    있으려면 판이 응답에 실려야 한다. 지금 서비스는 HTTP `Server` 머리로 그 값을 내고,
    이 시험이 그 값과 공표한 스키마의 판을 같게 묶는다 — 한쪽만 올리면 여기서 깨진다.
    """
    declared = hub["x-view-contract-version"]
    assert re.fullmatch(r"\d+\.\d+", declared), declared

    status, headers, body = _get(base_url, "/api/bootstrap")
    assert status == 200
    match = re.search(r"FMS/(\d+\.\d+)", headers.get("Server", ""))
    assert match, f"no contract version in the response headers: {headers.get('Server')!r}"
    assert match.group(1) == declared, (
        "the served contract version and the published schema disagree; a viewer that "
        "trusts one of them is wrong"
    )

    # 본문 칸은 아직 서비스가 내지 않는다(전송이 HTTP 가 아닌 뷰어를 위해 요청해 둔
    # 자리다). 내기 시작하면 머리와 같은 값이어야 한다.
    if "view_contract_version" in body:
        assert body["view_contract_version"] == declared


def test_every_published_endpoint_schema_points_at_the_one_hub(hub):
    """모양을 두 곳에 적으면 두 곳이 갈라진다. 끝점 파일은 허브의 $defs 를 가리키는
    얇은 포장이어야 한다."""
    hub_id = hub["$id"]
    wrappers = sorted(
        path for path in SCHEMA_DIR.glob("view_*.schema.json")
        if path.name != "view_snapshot.schema.json"
    )
    assert len(wrappers) >= 8
    for path in wrappers:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$ref"].startswith(f"{hub_id}#/$defs/"), path.name
        target = schema["$ref"].split("#/$defs/")[1]
        assert target in hub["$defs"], (path.name, target)


# ---------------------------------------------------------------------------
# (g) 언어는 뷰어가 늘린다
# ---------------------------------------------------------------------------


def test_both_locales_carry_exactly_the_same_keys(base_url):
    """한쪽에만 있는 키는 화면에서 빈칸이나 영어 잔재로 나타난다. 새 언어를 더하는
    뷰어는 이 키 집합을 그대로 채우면 되고 파이썬을 고칠 필요가 없다 — 그 약속이
    성립하려면 기존 언어들이 먼저 같은 집합이어야 한다."""
    tables = {}
    for locale in ("en", "ko"):
        status, _, body = _get(base_url, "/api/bootstrap", locale=locale)
        assert status == 200
        assert body["locale"] == locale
        assert locale in body["locales"]
        tables[locale] = body["strings"]

    assert set(tables["en"]) == set(tables["ko"]), {
        "only_en": sorted(set(tables["en"]) - set(tables["ko"])),
        "only_ko": sorted(set(tables["ko"]) - set(tables["en"])),
    }
    assert tables["en"] and all(isinstance(v, str) and v for v in tables["en"].values())
    assert tables["en"] != tables["ko"], "two locales with identical values is a missing translation"


# ---------------------------------------------------------------------------
# (h) never · stale · fresh 는 서로 다른 세 가지다
# ---------------------------------------------------------------------------


def _freshness(age_s, *, stale_after_s: float = STALE_AFTER_S) -> str:
    """`docs/view-contract.md` 가 적은 규칙 그대로. 뷰어가 구현할 대상이 이것이다."""
    if age_s is None:
        return "never"
    return "stale" if age_s > stale_after_s else "fresh"


def test_never_received_is_not_the_same_as_old_which_is_not_the_same_as_current(
    base_url, service, validators
):
    """AI-O-06: "한 번도 수신하지 않은 상태와 수신했으나 오래된 상태를 구분해야 한다."

    세 상태가 **같은 칸의 서로 다른 값**으로 표현될 수 있어야 하고, 특히 `never` 가
    0 으로 적혀서는 안 된다 — 0 은 "방금 받았다"는 아는 사실이라, 둘을 같게 적으면
    죽은 장치가 가장 싱싱한 장치로 보인다.
    """
    discovery = service.fleet.discovery
    # 세 상태를 **한 노드**에서 본다 — 서로 다른 노드로 보면 "그 노드가 원래 그런 것"
    # 과 "상태가 달라진 것"을 구분할 수 없다.
    node_id = next(
        candidate for candidate in sorted(service.fleet.facts)
        if candidate in discovery.actions and service.fleet.declared_zone_of(candidate)
    )
    saved_actions = dict(discovery.actions)
    saved_last_seen = dict(discovery.last_seen)
    try:
        status, _, fresh = _get(base_url, "/api/robot", id=node_id)
        assert status == 200
        discovery.note(node_id, saved_actions[node_id], at=time.time() - 3600.0)
        status, _, stale = _get(base_url, "/api/robot", id=node_id)
        assert status == 200
        # 공지가 끊긴다. 선언은 남고 탐지만 지워지므로 "한 번도 받지 않은" 자리로
        # 되돌아간다 — 이 계약은 과거의 나이를 들고 있지 않다.
        discovery.forget(node_id)
        status, _, never = _get(base_url, "/api/robot", id=node_id)
        assert status == 200
    finally:
        discovery.actions.clear()
        discovery.actions.update(saved_actions)
        discovery.last_seen.clear()
        discovery.last_seen.update(saved_last_seen)

    for tag, body in (("never", never), ("stale", stale), ("fresh", fresh)):
        _assert_valid(validators["robot"], body, f"/api/robot ({tag})")

    assert never["last_seen_age_s"] is None
    assert never["last_seen_age_s"] != 0, "never-received must not be written as zero"
    assert never["presence"] == "declared"

    assert isinstance(fresh["last_seen_age_s"], (int, float))
    assert fresh["last_seen_age_s"] <= STALE_AFTER_S
    assert fresh["presence"] in ("discovered", "unexpected")

    assert isinstance(stale["last_seen_age_s"], (int, float))
    assert stale["last_seen_age_s"] > STALE_AFTER_S

    classified = {_freshness(body["last_seen_age_s"]) for body in (never, stale, fresh)}
    assert classified == {"never", "stale", "fresh"}


def test_the_freshness_states_are_part_of_the_published_contract(hub):
    """뷰어가 세 상태를 그릴 수 있어야 하므로 세 값이 스키마에 적혀 있어야 한다."""
    assert hub["$defs"]["freshness_state"]["enum"] == ["never", "stale", "fresh"]
    assert "null" in hub["$defs"]["freshness_age"]["type"], (
        "the never-received case must be expressible in the same field as the age"
    )


def test_a_missing_measurement_is_left_out_rather_than_filled_with_zero(payloads, service):
    """같은 규칙이 자원 칸에도 적용된다 — 미측정을 0 으로 채우면 뷰어가 "자원 없음"
    으로 그리고 재어 보니 0 인 것과 아예 재지 못한 것이 한 칸에 섞인다."""
    for node_id, robot in payloads["robots"].items():
        resources = robot["resources"]
        fact = service.fleet.facts[node_id]
        for key in ("compute_units", "memory_mb"):
            if getattr(fact, key) is None:
                assert key not in resources, (node_id, key)
            else:
                assert isinstance(resources[key], (int, float)), (node_id, key)
        assert isinstance(resources["tags"], list)


# ---------------------------------------------------------------------------
# (i) 권한 표는 데이터로 온다 — 그리고 진짜 차단은 서버가 한다
# ---------------------------------------------------------------------------


def test_the_role_table_is_data_and_the_server_enforces_the_same_table(base_url):
    """역할 이름을 뷰어에 박으면 역할이 늘 때 뷰어를 고쳐야 한다. 그래서 표를 데이터로
    낸다. 그리고 그 표는 **뷰어의 편의**다 — 뷰어가 버튼을 감추지 않아도 서버가
    403 으로 끊는다. 운영의 최종 차단은 백엔드가 역할·범위로 하고 이 표가 그것을
    대신하지 않는다(AI-C-19)."""
    admin_token = _assume(base_url, "admin")
    status, _, admin = _get(base_url, "/api/bootstrap")
    assert status == 200
    user_token = _assume(base_url, "user1")
    status, _, user = _get(base_url, "/api/bootstrap")
    assert status == 200

    # 표 자체는 누가 묻든 같다 — 뷰어가 캐시해도 되는 데이터다.
    assert admin["roles"] == user["roles"], "the role table must not depend on who asks"
    assert set(admin["roles"]) >= {"viewer", "labeler", "operator", "developer", "admin"}

    # 반면 **내 능력**은 누구인지에 달려 있다. 그것이 권한이 역할 이름이 아니라
    # 능력이라는 말의 실질이다.
    assert "may_issue_command" in admin["identity"]["permissions"]
    assert "may_issue_command" not in user["identity"]["permissions"]
    assert admin["identity"]["actor"] != user["identity"]["actor"]

    # 그리고 그 표는 뷰어의 편의다 — 뷰어가 버튼을 감추지 않아도 서버가 끊는다.
    status, _, body = _request("POST", f"{base_url}/api/command",
                               {"robot": "whatever", "action": "stop"},
                               token=user_token)
    assert status == 403, (status, body)
    assert body["error"] == "missing_permission:may_issue_command"

    # 관리자 토큰으로는 같은 요청이 권한에서 막히지 않는다(로봇 이름에서 막힌다).
    status, _, body = _request("POST", f"{base_url}/api/command",
                               {"robot": "whatever", "action": "stop"},
                               token=admin_token)
    assert status == 404, (status, body)
    assert body["error"] == "unknown_robot", "권한이 아니라 대상에서 막혀야 한다"

    # 자리 수정도 같은 모양이다 — 능력 이름이 사유에 그대로 나온다.
    status, _, body = _request("POST", f"{base_url}/api/placement",
                               {"device_id": "x", "zone_id": "y"},
                               token=user_token)
    assert status == 403, (status, body)
    assert body["error"] == "missing_permission:may_edit_placement"


def test_an_absent_path_is_announced_as_absent_not_as_an_error(base_url, payloads, validators):
    """AI-C-05: 선택 기능의 부재는 장애가 아니다. 뷰어가 503 `not_wired_yet` 과
    `no_evidence_path` 를 "고장"으로 그리면 멀쩡한 축소 배치가 장애로 읽힌다."""
    boot = payloads["bootstrap"]
    assert isinstance(boot["evidence_available"], bool)
    assert isinstance(boot["commanding_available"], bool)

    # `evidence_available` 는 **실제 가용성과 일치해야** 한다. 분류 사전·모델이 없는
    # 노드에서는 `/api/explain` 이 503 `no_evidence_path:<사유>` 를 내고, 있는 노드에서는
    # 인자를 빠뜨린 요청이 400 이다. 어느 쪽이든 "없다"를 "고장"으로 그리면 안 된다.
    status, _, body = _get(base_url, "/api/explain")
    if boot["evidence_available"]:
        assert status == 400, (status, body)
        assert body["error"] == "class_and_file_required"
    else:
        assert status == 503, (status, body)
        assert body["error"].startswith("no_evidence_path")
        assert boot["evidence_reason"], "비활성이면 그 사유를 적어야 한다"
    _assert_valid(validators["error"], body, "/api/explain error body")

    # 아예 없는 경로는 404 로 "그런 것은 없다" 라고 말한다 — 503(있으나 지금 못 쓴다)과
    # 구분되어야 뷰어가 "버전이 낮아 아직 없는 기능"과 "고장"을 가를 수 있다.
    status, _, body = _get(base_url, "/api/no_such_thing")
    assert status == 404, (status, body)
    assert body["error"] == "unknown_path"
    _assert_valid(validators["error"], body, "unknown path body")
