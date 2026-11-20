"""FMS 화면이 쓰던 조회 계약을 **가시화 앱이 보는 한 자리**에서 낸다.

implements: AI-O-06, AI-C-19, AI-C-06
tests: tests/test_fms_view_api.py

## 왜 생겼나 (2026-11-05)

FMS 콘솔(`tools/view_service/`)은 디지털 트윈 맵·추천 임무·서브태스크 접지·계층별
지표·장치 관리를 낸다. 그런데 그것이 **별도 웹으로 떠 있었다** — 가시화 앱은
게이트웨이(`/registry` 와 채널)만 보고 있고, 콘솔의 `/api/*` 는 다른 포트에 있으며
`serve.py` 는 CORS 헤더를 붙이지 않는다. 그래서 운영자가 두 화면을 오가야 했다.

그것은 설계가 의도한 모양이 아니다. 콘솔은 **판정을 하지 않는다** — 다른 모듈이
내는 값을 모아 한 스냅샷으로 낼 뿐이고(CLAUDE.md §0), 맵도 데이터와 렌더러가
갈라져 있다. 즉 콘솔은 *렌더러 하나*이고, 같은 계약을 가시화 앱이 읽으면 그 앱
안에서 같은 화면이 선다.

이 모듈은 **새 답을 만들지 않는다.** `FmsService` 가 이미 내는 답을 가시화 앱이
닿는 자리로 옮기기만 한다. 같은 질문에 두 곳이 다른 답을 하면 안 되므로
(view-contract §3.6 「같은 사실은 한 곳에서 나온다」) 서비스 **객체 하나**를
공유한다 — 설정을 두 번 읽어 두 개를 만들지 않는다.

## 조회만이다

여기서 여는 것은 **GET 뿐이다.** 제어는 다른 계약이고(view-contract §2), 명령
발급은 우리 소유가 아니다(AI-C-19). 조회 경로로 들어온 POST 는 본문을 읽기 전에
405 다 — 읽고 나서 거절하면 "읽기는 했다" 가 된다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

#: 가시화 앱에 여는 조회 경로. 콘솔의 `_ROUTES_GET` 중 **화면이 쓰는 것만** 고른
#: 것이 아니라 그대로다 — 고르면 그 고름이 또 하나의 판정이 되고, 앱이 새 화면을
#: 만들 때마다 우리 코드를 고쳐야 한다(원칙 #7).
VIEW_ROUTES: tuple[str, ...] = (
    # 선언된 실행 단위가 **지금 서 있는가**. 조회 전용이고 바꾸는 것은
    # `/api/stack`(쓰기)이다 — 읽는 이름과 쓰는 이름이 겹치지 않는다(AI-O-06).
    "/api/services",
    "/api/bootstrap", "/api/scene", "/api/domain", "/api/zone", "/api/robot",
    "/api/recommend", "/api/subtasks", "/api/explain", "/api/twin",
    "/api/object", "/api/candidates", "/api/transit", "/api/mission",
    "/api/failure", "/api/spatial", "/api/overlay", "/api/lineage",
    "/api/deployment", "/api/calibration", "/api/approval", "/api/dashboard",
    "/api/evidence-kinds", "/api/background", "/api/trial",
    # 아래 넷은 `view_payload` 가 처음부터 답했는데 **선언 어디에도 없었다** —
    # 콘솔 라우터는 선언을 보지 않고 넘겼으므로 콘솔 화면에서는 돌았고, 선언을
    # 믿는 이 자리에서만 닿지 않았다. 라벨 검수(AI-L-03)와 계정 관리가 통째로
    # 빠져 있었고, 콘솔을 지우면 그대로 사라질 뻔했다.
    "/api/samples", "/api/label/tasks", "/api/label/task", "/api/accounts",
)

#: 조회 계약은 **읽기 전용이다**. 이 응답에 쓰기 경로를 섞지 않는다.
ALLOWED_METHODS = ("GET", "HEAD", "OPTIONS")

#: 앱이 다른 포트에서 돌므로 교차 출처다. 조회만 여는 자리라 넓게 열어도 권한이
#: 넓어지지 않는다 — 쓰기 경로는 여기 없다.
CORS_HEADERS: tuple[tuple[str, str], ...] = (
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", ", ".join(ALLOWED_METHODS)),
    ("Access-Control-Allow-Headers", "Content-Type"),
    ("Access-Control-Max-Age", "600"),
)


#: 응답 머리에 실을 서버 이름의 틀. 판은 **서비스가 가진 값**을 넣는다 — 여기
#: 숫자를 적으면 공표한 스키마의 판과 어긋날 수 있고, 그것을 믿은 뷰어가 틀린다.
SERVER_NAME_TEMPLATE = "FMS/{version}"


class ViewApiUnavailable(RuntimeError):
    """서비스를 세우지 못했다. **그 조각만** 꺼진다(AI-C-05)."""


@dataclass
class _Parsed:
    """`view_payload` 가 보는 것은 `parsed.path` 하나다 — 그만 넘긴다."""

    path: str


@dataclass
class FmsViewApi:
    """`FmsService` 를 가시화 앱의 조회 경로로 옮긴다. 판정을 더하지 않는다."""

    service: Any
    #: 콘솔에서 꺼낸 **정본 표**. 이 자리가 짝짓기를 다시 적지 않는 이유다.
    view_payload: Callable[..., Any]
    #: 서비스가 던지는 `ApiError` 의 자리. 상태 코드를 여기서 지어내지 않는다.
    api_error: type[Exception]
    not_a_view_route: type[Exception]
    #: 조회만 하는 호출자. 쓰기 권한을 들고 있지 않다(AI-C-19).
    caller: Any = None
    locale: str = "ko"
    #: 서비스를 실은 모듈. 쓰기 계약이 **같은 모듈·같은 서비스**를 쓰도록 들고
    #: 있는다 — 두 번째를 만들면 운영자가 고친 값이 한쪽에만 보인다.
    module: Any = None

    def handles(self, path: str) -> bool:
        return path.split("?")[0] in VIEW_ROUTES

    def unknown_path(self) -> tuple[int, bytes]:
        """없는 경로의 답. **어휘는 이 계약이 소유한다.**

        전송 provider(`providers/ws_server.py`)는 아무것도 못 찾으면 자기 낱말
        `not_found` 로 답한다. 그것을 그대로 내보내면 같은 사실에 두 이름이 생기고,
        뷰어는 "버전이 낮아 아직 없는 기능"과 "고장"을 가르려고 보던 토큰을 잃는다.
        """
        return 404, self._error("unknown_path", "")

    def server_name(self) -> str | None:
        """`Server:` 머리에 실을 값. 판을 모르면 **적지 않는다.**"""
        version = getattr(self.module, "VIEW_CONTRACT_VERSION", None)
        if not version:
            return None
        return SERVER_NAME_TEMPLATE.format(version=version)

    def caller_for(self, headers: dict | None):
        """요청마다 호출자를 푼다 — **기동 시점에 굳히지 않는다.**

        전에는 `self.caller`(익명, `may_view` 만) 하나로 모든 조회에 답했다. 그래서
        가시화 앱이 로그인해도 권한이 걸린 조회 여섯(`/api/object` 추론 근거 ·
        `/api/failure` · `/api/overlay` · `/api/accounts` · `/api/label/tasks` ·
        `/api/label/task`)이 영원히 403 이었다. 토큰이 없으면 전과 같은 익명
        호출자이고, 그 익명이 조회를 못 하는 설치에서는 애초에 서지 않는다.

        쿠키는 보지 않는다 — 쓰기 계약과 같은 이유다(`fms_write_api` 머리글).
        """
        from integration.fms_write_api import token_from   # noqa: PLC0415

        token = token_from(headers or {})
        if token is None:
            return self.caller
        return self.service.accounts.caller(token)

    def locale_for(self, query: dict[str, list[str]]) -> str:
        """`?locale=` 을 **서비스의 표로** 검사해 쓴다. 표를 여기 베끼지 않는다.

        전에는 기동 시점의 `self.locale` 하나로 모든 응답을 냈다. 그래서 앱이
        `?locale=en` 으로 물어도 한국어 묶음이 돌아왔고, 두 언어의 키 집합이 같은지
        확인할 길이 없었다(뷰어가 세 번째 언어를 덮는 길 — view-contract §8 — 이
        그 키 집합에 기대어 있다).
        """
        values = (query or {}).get("locale") or []
        wanted = values[0] if values else None
        if wanted is None:
            return self.locale
        known = getattr(self.module, "STRINGS", None)
        if known is not None and wanted not in known:
            raise self.api_error(400, "unknown_locale")
        return wanted

    def answer(self, path: str, query: dict[str, list[str]],
               headers: dict | None = None) -> tuple[int, bytes]:
        """한 건에 답한다. 돌려주는 것은 `(status, body)` 다.

        **짝짓기를 여기서 하지 않는다** — 콘솔에서 꺼낸 `view_payload()` 하나가
        질의 이름과 서비스 인자를 잇는 정본이고, 이 자리는 그것을 부를 뿐이다.

        사유도 지어내지 않는다. 서비스가 든 `ApiError` 의 코드와 사유를 그대로
        옮기고, 모르는 예외는 500 과 예외 이름으로 남긴다(조용히 200 을 내지 않는다).
        """
        route = path.split("?")[0]
        try:
            body = self.view_payload(self.service, _Parsed(route), query,
                                     caller=self.caller_for(headers),
                                     locale=self.locale_for(query))
        except self.not_a_view_route:
            return 404, self._error("unknown_route", route)
        except self.api_error as error:                         # noqa: BLE001
            status = getattr(error, "status", 400)
            reason = getattr(error, "reason", None) or str(error)
            return int(status), self._error(reason, route)
        except Exception as error:                              # noqa: BLE001
            return 500, self._error(f"{type(error).__name__}", route)
        return 200, json.dumps(body, ensure_ascii=False).encode("utf-8")

    # ── 내부 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _error(reason: str, route: str) -> bytes:  # noqa: ARG004
        """`schemas/view_error.schema.json` **그대로** — `{"error": "<토큰>"}`.

        처음에 `{"error": {"reason": …, "route": …}}` 로 냈다가 고쳤다. 콘솔과
        모양이 달라지는 순간, 같은 오류에 두 모양이 생긴다 — 이 모듈이 없애려던
        결함을 바로 그 자리에서 새로 만드는 것이다. 경로는 요청한 쪽이 이미 안다.
        """
        return json.dumps({"error": reason}, ensure_ascii=False).encode("utf-8")


def _invoke(method: Callable, kwargs: dict, locale: str):
    """서비스 메서드가 받는 인자만 넘긴다.

    메서드마다 받는 이름이 달라서(`zone`·`robot`·`goal` …) 질의를 통째로 넘기면
    `TypeError` 가 난다. 받는 것만 추려 넘기고, `locale` 은 받는 메서드에만 준다 —
    **없는 인자를 지어 주지 않는다.**
    """
    import inspect

    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method()
    accepted = set(signature.parameters)
    passed = {k: v for k, v in kwargs.items() if k in accepted}
    if "locale" in accepted:
        passed["locale"] = locale
    return method(**passed)


#: 콘솔 모듈을 싣는 이름. **`serve` 로 싣지 않는다** — `tools/status_ui/serve.py` 가
#: 이미 그 이름을 쓰고 있어서 먼저 실린 쪽이 이긴다. 실제로 그렇게 깨졌다.
_CONSOLE_MODULE = "mission_runtime_view_service_serve"


def _load_console():
    """콘솔 모듈을 **경로로** 싣는다. 이름이 겹치는 자리라 경로가 정본이다."""
    import importlib.util
    import sys
    from pathlib import Path

    existing = sys.modules.get(_CONSOLE_MODULE)
    if existing is not None:
        return existing

    console_dir = Path(__file__).resolve().parents[1] / "tools" / "view_service"
    path = console_dir / "service.py"
    if not path.is_file():
        raise ViewApiUnavailable(f"콘솔 모듈이 없다 — {path}")
    # 콘솔은 같은 폴더의 이웃 모듈(`fleet.py` 등)을 평범한 import 로 가져온다.
    if str(console_dir) not in sys.path:
        sys.path.insert(0, str(console_dir))
    spec = importlib.util.spec_from_file_location(_CONSOLE_MODULE, path)
    if spec is None or spec.loader is None:
        raise ViewApiUnavailable(f"콘솔 모듈을 싣지 못했다 — {path}")
    module = importlib.util.module_from_spec(spec)
    # **exec 전에 등록한다.** 늦게 등록하면 모듈 전역이 중간에 회수돼
    # `'NoneType' object has no attribute '__dict__'` 가 난다(전에 겪었다).
    sys.modules[_CONSOLE_MODULE] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:                                  # noqa: BLE001
        del sys.modules[_CONSOLE_MODULE]
        raise ViewApiUnavailable(f"{type(error).__name__}: {error}") from error
    return module


def build_view_api(*, ui_config, zone_profile, goal_kinds,
                   broker: tuple[str, int] | None = None,
                   with_fleet: bool = False,
                   overlay_path=None, accounts_path=None,
                   stack_units_path=None) -> FmsViewApi:
    """서비스 모듈과 **같은 빌더**로 서비스를 세운다. 설정을 다시 해석하지 않는다.

    `with_fleet` 은 기본으로 끈다 — 게이트웨이는 듣는 쪽이고, 장치를 세우는 것은
    장치 러너의 일이다. 두 프로세스가 같은 device_id 로 서면 같은 downlink 에
    둘이 답한다.

    `overlay_path`·`accounts_path` 는 FMS 콘솔을 지우면서 이리로 왔다 — 운영자
    수정 장부와 계정 파일의 자리를 고를 길이 사라지면 안 된다(AI-L-03).
    """
    module = _load_console()

    try:
        service = module.build_service(
            ui_config=ui_config, zone_profile=zone_profile, goal_kinds=goal_kinds,
            with_fleet=with_fleet, broker=broker,
            overlay_path=overlay_path, accounts_path=accounts_path,
            stack_units_path=stack_units_path)
    except ViewApiUnavailable:
        raise
    except Exception as error:                                  # noqa: BLE001
        # 설정이 없거나 깨졌으면 **그 조각만** 꺼진다 — 게이트웨이는 그대로 뜬다
        # (AI-C-05). 머리글에 그렇게 적어 놓고 import 예외만 감싸고 있었다.
        raise ViewApiUnavailable(f"{type(error).__name__}: {error}") from error
    declared = set(getattr(module, "_ROUTES_GET", ()))
    if declared and set(VIEW_ROUTES) != declared:
        # 두 목록이 어긋나면 어느 쪽이 정본인지 알 수 없다. 조용히 좁은 쪽을
        # 쓰면 기능 하나가 말없이 사라진다(실제로 넷이 그렇게 빠져 있었다).
        raise ViewApiUnavailable(
            "조회 경로 선언이 서비스와 어긋난다 — "
            f"여기만: {sorted(set(VIEW_ROUTES) - declared)}, "
            f"서비스만: {sorted(declared - set(VIEW_ROUTES))}")
    return FmsViewApi(service=service, view_payload=module.view_payload,
                      api_error=module.ApiError,
                      not_a_view_route=module.NotAViewRoute,
                      caller=_view_caller(module, service),
                      module=module)


def _view_caller(module, service):
    """조회 권한만 든 호출자. **쓰기 권한을 들고 있지 않다**(AI-C-19).

    계정이 없는 설치에서는 조회가 열려 있고, 계정이 생기면 익명 조회가 닫힌다 —
    그 판정은 `AccountStore` 가 하고 여기서 다시 하지 않는다.
    """
    caller = service.accounts.caller(None)
    if not caller.may(module.PERM_VIEW):
        # 계정이 하나라도 생기면 익명 조회가 닫힌다. 그때는 **열지 않는다** —
        # 권한을 우회하는 뒷문을 만들면 콘솔의 판정이 의미를 잃는다.
        raise ViewApiUnavailable("익명 조회가 닫혀 있다 — 계정이 설정된 설치다")
    return caller
