"""FMS 화면이 쓰던 **쓰기 계약**을 가시화 앱이 보는 한 자리에서 받는다.

implements: AI-O-06, AI-C-19, AI-C-06, AI-L-03, AI-L-06
tests: tests/test_fms_write_api.py

## 왜 생겼나 (2026-11-05)

FMS 콘솔을 지우기로 했다 — 웹은 가시화 앱 하나다. 그런데 "비개발자가 웹에서 하는
네 가지"(장치 들이기 · 카메라 정보 입력 후 보정 · 확인된 후보로 학습 · 기기별 모델
교체)와 라벨 검수·운영자 정정·임무 진행은 전부 콘솔 `FmsHandler.do_POST` 안에만
있었다. 그 handler 를 지우면 그 기능들이 **어느 웹에서도** 닿지 않는다.

그래서 표를 HTTP 밖으로 꺼내(`write_payload`) 이 모듈이 게이트웨이 쪽 전송만
입힌다. **새 판정을 만들지 않는다** — 권한 표도 상태 코드도 서비스가 소유한다.

## 조회와 섞지 않는다

AI-O-06 은 "상태 뷰는 조회 전용이어야 하며 이 경로를 통해 실행 상태를 변경하는
수단을 제공해서는 안 된다" 고 적는다. 그래서 같은 프로세스에 있어도 **다른 계약**
이다 — 경로 이름이 겹치지 않고(`WRITE_ROUTES` ∩ `VIEW_ROUTES` = ∅, 시험이 고정한다),
조회 경로로 들어온 쓰기는 본문을 읽고도 거절하지 않고 405 로 끊는다.

## 세션은 쿠키가 아니라 Bearer 다

콘솔 페이지는 같은 출처라 HttpOnly 쿠키가 맞았다. 가시화 앱은 **다른 출처**이고,
쿠키를 교차 출처로 쓰려면 `Access-Control-Allow-Origin` 에 정확한 출처를 적고
자격증명을 허용해야 한다 — 그 순간 운영자가 방문한 아무 사이트가 그 브라우저로
명령을 보낼 수 있다(CSRF). Bearer 토큰은 그 사이트가 **얻을 수 없으므로** 같은
공격이 성립하지 않는다. 그래서 이 자리는 **쿠키를 보지 않는다**: 토큰은
`Authorization: Bearer` 에서만 읽고, 로그인 응답 본문에 `session_token` 으로 낸다.

같은 사실(세션)을 두 전송이 자기 방식으로 싣는 것이고 판정이 갈라지는 것이 아니다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

#: 가시화 앱에 여는 **쓰기** 경로. 콘솔의 `_ROUTES_POST` 그대로다 — 고르면 그 고름이
#: 또 하나의 판정이 되고, 앱이 새 화면을 만들 때마다 우리 코드를 고쳐야 한다(원칙 #7).
WRITE_ROUTES: tuple[str, ...] = (
    "/api/login", "/api/logout", "/api/assume", "/api/account",
    "/api/command", "/api/correction", "/api/placement", "/api/survey",
    "/api/detection", "/api/pose", "/api/label", "/api/join",
    "/api/join-step", "/api/camera-info", "/api/training", "/api/model",
    "/api/mission-run", "/api/trial-run", "/api/threshold",
    # 선언된 실행 단위를 세우고 내린다(AI-B-03). **단위 이름만 받는다** — 명령줄은
    # 선언에만 있고 망에서 오지 않는다(`providers/process_control.py`).
    "/api/stack",
)

#: 쓰기 계약이 받는 메서드. GET 으로는 아무것도 바뀌지 않는다.
ALLOWED_METHODS = ("POST", "OPTIONS")

#: 세션 토큰을 받는 머리. **쿠키는 보지 않는다**(머리글 참고).
AUTH_HEADER = "authorization"
AUTH_PREFIX = "Bearer "


class WriteApiUnavailable(RuntimeError):
    """쓰기 계약을 세우지 못했다. **그 조각만** 꺼진다(AI-C-05)."""


@dataclass
class _Parsed:
    """`write_payload` 가 보는 것은 `parsed.path` 하나다 — 그만 넘긴다."""

    path: str


def token_from(headers: dict) -> str | None:
    """`Authorization: Bearer …` 에서만 토큰을 꺼낸다.

    질의 인자로는 받지 않는다 — 질의 문자열은 접근 로그와 브라우저 이력에 그대로
    남고, 그러면 토큰이 비밀이 아니게 된다. 쿠키도 받지 않는다(머리글 참고).
    """
    raw = ""
    for key, value in headers.items():
        if str(key).lower() == AUTH_HEADER:
            raw = str(value)
            break
    if not raw.startswith(AUTH_PREFIX):
        return None
    return raw[len(AUTH_PREFIX):].strip() or None


@dataclass
class FmsWriteApi:
    """`FmsService` 의 쓰기 계약을 가시화 앱이 닿는 자리로 옮긴다."""

    service: Any
    #: 콘솔에서 꺼낸 **정본 표**. 이 자리가 권한·상태 코드를 다시 적지 않는 이유다.
    write_payload: Callable[..., Any]
    api_error: type[Exception]
    not_a_write_route: type[Exception]
    locale: str = "ko"

    def handles(self, path: str) -> bool:
        return path.split("?")[0] in WRITE_ROUTES

    def answer(self, path: str, body: bytes,
               headers: dict) -> tuple[int, bytes]:
        """쓰기 한 건에 답한다. 돌려주는 것은 `(status, body)` 다.

        세션을 만든 요청이면 토큰을 **본문에** 싣는다 — 이 자리는 쿠키를 쓰지
        않으므로(머리글) 앱이 그것을 받아 다음 요청의 Bearer 로 쓴다.
        """
        route = path.split("?")[0]
        try:
            parsed_body = json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, self._error("body_not_json")
        try:
            outcome = self.write_payload(
                self.service, _Parsed(route), parsed_body,
                token=token_from(headers), locale=self.locale)
        except self.not_a_write_route:
            # 조회 경로로는 아무것도 바꿀 수 없다 — AI-O-06.
            return 405, self._error("read_only_path")
        except self.api_error as error:                         # noqa: BLE001
            status = getattr(error, "status", 400)
            reason = getattr(error, "reason", None) or str(error)
            return int(status), self._error(reason)
        except Exception as error:                              # noqa: BLE001
            # 조용히 200 을 내지 않는다 — 빈 성공은 고장을 숨긴다.
            return 500, self._error(f"subsystem_failed:{type(error).__name__}")

        payload = dict(outcome.payload)
        if outcome.session_token is not None:
            payload["session_token"] = outcome.session_token
        return int(outcome.status), json.dumps(
            payload, ensure_ascii=False).encode("utf-8")

    # ── 내부 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _error(reason: str) -> bytes:
        """`schemas/view_error.schema.json` **그대로** — `{"error": "<토큰>"}`."""
        return json.dumps({"error": reason}, ensure_ascii=False).encode("utf-8")


def build_write_api(service, module) -> FmsWriteApi:
    """조회 계약과 **같은 서비스 객체**로 쓰기 계약을 세운다.

    두 번째 서비스를 만들지 않는다 — 만들면 운영자가 고친 값이 한쪽에만 보이고,
    같은 사실에 주인이 둘이 된다(view-contract §3.6).
    """
    for name in ("write_payload", "ApiError", "NotAWriteRoute"):
        if not hasattr(module, name):
            raise WriteApiUnavailable(f"서비스 모듈에 {name} 이 없다")
    declared = set(getattr(module, "_ROUTES_POST", ()))
    if declared and set(WRITE_ROUTES) != declared:
        # 두 목록이 어긋나면 어느 쪽이 정본인지 알 수 없다. 세우지 않는다.
        raise WriteApiUnavailable(
            "쓰기 경로 선언이 서비스와 어긋난다 — "
            f"여기만: {sorted(set(WRITE_ROUTES) - declared)}, "
            f"서비스만: {sorted(declared - set(WRITE_ROUTES))}")
    return FmsWriteApi(service=service, write_payload=module.write_payload,
                       api_error=module.ApiError,
                       not_a_write_route=module.NotAWriteRoute)
