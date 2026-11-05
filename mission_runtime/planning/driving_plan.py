"""The one place the driving-path chain is assembled.

implements: AI-B-14 (서브태스크 산출의 capability 접지 — 계획을 공통 계약으로만 승격)
관련: AI-R-02 (위험도·근거·권고), AI-S-03 (근거 충분도), AI-C-19 (판단·권한 경계),
      AI-C-02 (로봇 로컬 좌표), AI-C-13 (교체 가능한 정책)
tests: tests/test_driving_plan.py

왜 조립을 한 곳에 두는가
------------------------
사슬은 넷이다 — `planning/path_candidates.py::generate` 가 후보를 만들고,
`risk/hazard_field.py::HazardField` 가 근거를 탐침 질의로 바꾸고,
`risk/path_evaluation.py` 가 채점하고, `path_candidates.choose` 가 고른다. 호출자가
이 넷을 직접 이으면 **이을 때마다 세 가지 결정을 다시 한다**: 어느 채점기를 쓰는가,
차선 기준을 주는가, 거절을 무엇으로 바꾸는가. 두 호출자가 서로 다르게 결정하면 같은
스캔에서 두 답이 나온다.

`risk/hazard_field.py::scored_candidates` 가 같은 이유로 이미 한 칸을 묶어 두었고
(그 docstring: "호출자가 직접 조립하면 여전히 성립하므로, 조립을 여기 한 곳에 둔다"),
이 모듈은 그 위의 남은 칸들을 같은 규칙으로 묶는다.

**판정을 새로 하지 않는다.** 이 모듈에 임계값도 가중치도 없다 — 위험은 `risk/`,
커버리지는 `ScanCoverage`, 고르는 규칙은 `choose` 가 소유하고 여기서는 순서만
정한다(`tools/fms_console/` 가 "판정을 하지 않는다" 와 같은 자리).

고르지 않는 것도 산출이다
-------------------------
거절은 예외가 아니라 `reason` 을 가진 같은 모양의 답이다. 사유가 넷으로 갈리고 넷은
**다음에 할 일이 서로 다르다**:

- `scan_coverage_undeclared` — 무엇을 봤는지 모른다. 커버리지를 선언해야 한다.
- `evidence_insufficient` — 본 자리의 근거가 약하다. 같은 자리를 더 좋은 근거로.
- `path_under_observed` — 근거는 좋은데 그 경로를 따라 본 자리가 적다. 그 방향을 더.
- `candidates_not_separated` — 봤는데 비슷하다. 더 봐도 안 갈린다.

넷을 한 사유로 뭉개면 운영자가 스캔을 더 해야 할 때와 더 해도 소용없을 때를 구분하지
못한다(AI-S-03).

경로를 정하는 것과 움직이라고 명령하는 것은 다른 일이다
-------------------------------------------------------
2026-11-04 개정으로 주행 경로 계획은 AI 몫이 됐지만 **물리 명령 발급과 액추에이터
제어는 여전히 AI 소유가 아니다**(AI-C-19). 이 모듈이 내는 것은 후보와 사유이고,
그것을 명령으로 바꾸는 쪽은 제어 경계를 거친다. 그래서 산출에 `authority` 가 붙어
나가고 값은 하나뿐이다.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from mission_runtime.planning.path_candidates import (
    choose,
    generate,
    path_lengths,
    plan_payload,
)
from mission_runtime.risk.hazard_field import HazardField, ScanCoverage, scored_candidates

#: 이 산출로 할 수 있는 것. 값이 하나뿐인 이유가 요점이다 — AI 는 권고만 낸다
#: (AI-C-19). 칸을 두는 이유는 소비자가 "이것으로 명령을 내도 되는가" 를 추측하지
#: 않게 하는 것이고, 이 값이 늘어나는 날은 경계가 다시 바뀌는 날이다.
AUTHORITY_ADVISORY = "advisory_only"


def plan_drive(
    goal_local_xy: tuple[float, float] | None,
    evidences: Sequence[Any],
    taxonomy: Any,
    *,
    scorer: Callable[[Mapping[str, float]], Any],
    coverage: ScanCoverage | None = None,
    waypoints: Mapping[str, tuple[float, float]] | None = None,
    tie_break_by_length: bool = True,
) -> dict:
    """근거 · 커버리지 · 목표 → 화면과 하드웨어가 그대로 읽는 한 덩어리.

    `coverage=None` 은 **"무엇을 봤는지 모른다"** 이고 "전부 봤다" 가 아니다. 그
    상태에서는 후보끼리 비교가 성립하지 않아 `scored_candidates` 가 거절하고, 이
    함수는 그 거절을 후보 목록과 **함께** 낸다 — 후보를 지우면 운영자가 "경로가
    아예 없다" 와 "비교를 못 한다" 를 구분할 수 없다.

    `tie_break_by_length=False` 를 주면 위험으로 갈리지 않을 때 고르지 않는다. 기본이
    True 인 이유는 실제로 한 번 깨끗한 바닥에서 멈췄기 때문이고, 길이로 골랐다는
    사실은 `choice.tie_break_by` 에 남아 위험으로 고른 것과 섞이지 않는다.
    """
    candidates = generate(goal_local_xy, waypoints=waypoints)
    field = HazardField(list(evidences), taxonomy, coverage=coverage)
    evaluations, refusal = scored_candidates(candidates, field, scorer)

    if refusal is not None:
        # 비교가 성립하지 않는다. `plan_payload` 에 빈 평가를 주면 그 쪽이
        # `no_candidate` 로 적어 **후보가 없다는 뜻**이 되므로, 사유를 여기서 덮어쓴다.
        payload = plan_payload(goal_local_xy, (), waypoints=waypoints)
        payload["choice"] = {"candidate_id": None, "decided": False,
                             "considered": len(candidates), "reason": refusal}
    else:
        tie_break = path_lengths(candidates) if tie_break_by_length else None
        payload = plan_payload(goal_local_xy, evaluations, waypoints=waypoints)
        payload["choice"] = choose(evaluations, tie_break=tie_break).as_payload()

    payload["authority"] = AUTHORITY_ADVISORY
    # 자리를 못 찾은 근거는 **세어서 낸다.** 위험으로 만들지도, 없던 일로 하지도
    # 않는다 — 운영자가 "장애물이 없다" 와 "장애물을 어디에 둘지 몰랐다" 를
    # 구분해야 한다(AI-S-04).
    payload["evidence"] = {
        "located": len(field.located),
        "unlocatable": field.unlocatable_count,
        "unlocatable_reasons": dict(field.unlocatable_reasons),
        "coverage_declared": bool(coverage is not None and coverage.is_declared),
    }
    return payload
