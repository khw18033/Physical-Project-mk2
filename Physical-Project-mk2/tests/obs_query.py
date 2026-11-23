"""관측 저장소 조회 헬퍼 (테스트 전용) — Prometheus·Loki·Tempo 를 표준 `urllib` 로만 본다.

`requests` 같은 새 의존성을 만들지 않는다(지시서 9-A). `conftest.py` 의 fixture 와 관측 테스트가
같이 쓴다. 백엔드 코드는 이 파일을 import 하지 않는다 — 질의 프록시(BE-Q-01)는 Phase 5/6 이다.

implements: BE-S-02 (검증 수단)
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, List


def http_get(url: str, timeout: float = 5.0) -> str:
    """GET 본문(문자열). 실패는 예외 그대로 — 호출부가 skip 으로 바꾸거나 재시도한다."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - 테스트 전용 로컬 조회
        return resp.read().decode("utf-8", errors="replace")


def http_get_json(url: str, timeout: float = 5.0) -> Any:
    return json.loads(http_get(url, timeout))


def prom_query(prometheus_url: str, expr: str) -> List[dict]:
    """instant query → `result` 목록. 표본이 없으면 빈 목록."""
    data = http_get_json(prometheus_url + "/api/v1/query?" + urllib.parse.urlencode({"query": expr}))
    return data["data"]["result"]


def prom_scalar(prometheus_url: str, expr: str) -> float:
    """단일 값 질의(`sum(...)` 등). 표본이 없으면 0.0."""
    result = prom_query(prometheus_url, expr)
    return float(result[0]["value"][1]) if result else 0.0


def counter_delta(before: float, after: float) -> float:
    """counter 의 증가분 — **리셋을 `rate()`와 같은 규칙으로 처리한다.**

    counter 는 프로세스와 수명을 같이 해 재기동하면 0 부터 다시 센다(지시서 6-4-a). 게다가 Collector 의
    prometheus exporter 는 옛 프로세스의 마지막 값을 5분간 계속 내보내므로, 재기동 직후에는 `before` 가
    옛 값·`after` 가 새 프로세스 값이 된다. `after < before` 면 리셋이 있었던 것이고 그때 증가분은 `after`
    자체다(2026-09-16 실측: 재기동 뒤 rejected before=옛값, after=1 로 테스트가 헛되이 실패했다).
    """
    return after if after < before else after - before


def wait_until(predicate: Callable[[], bool], timeout: float, interval: float = 2.0) -> bool:
    """조건이 참이 될 때까지 기다린다. export(15s) + scrape(5s) 를 덮는 상한을 호출부가 준다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
