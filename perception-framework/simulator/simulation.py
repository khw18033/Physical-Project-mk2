"""Single runnable entry point for every framework-property scenario.

implements: AI-B-01, AI-B-04, AI-B-06, AI-B-09, AI-C-04, AI-C-05, AI-C-10,
AI-C-11, AI-C-13, AI-C-15

실행:  PYTHONPATH=. python3 simulator/simulation.py [시나리오 경로]
       인자를 생략하면 실행할 시나리오 경로를 키보드로 입력받는다.

하드웨어 없이 프레임워크의 성질(선택 기능 축소, provider 교체, 도메인 전환,
장애 격리 등)을 확인하는 데모이자, 같은 JSON 파일이 `tests/test_scenarios.py`에서
pytest 자동 검증 입력으로도 쓰인다 — 시나리오 하나를 만들면 시연과 회귀 검증을
동시에 얻는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from runner import load_scenario, run

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"


def _prompt_for_scenario_path() -> Path:
    available = sorted(SCENARIO_DIR.glob("*.json"))
    print("사용 가능한 시나리오:")
    for path in available:
        print(f"  {path.relative_to(Path(__file__).resolve().parent)}")
    raw = input("실행할 시나리오 경로 (scenarios/ 기준 상대경로 또는 절대경로): ").strip()
    candidate = Path(raw)
    if not candidate.is_absolute() and not candidate.exists():
        candidate = SCENARIO_DIR / raw
    return candidate


def narrate(result) -> None:
    print(f"\n=== {result.scenario_id} (시뮬레이션 시간 축, pyjevsim) ===")
    if result.description:
        print(result.description)

    for cp in result.checkpoints:
        print(f"\n-- t={cp.time:g} ({cp.label}) --")
        for node_id, states in cp.node_states.items():
            if not states:
                continue
            print(f"  [{node_id}]")
            resolutions = cp.node_resolutions.get(node_id, {})
            for kind, state in states.items():
                resolution = resolutions.get(kind)
                provider = resolution.provider.provider_id if resolution and resolution.provider else "-"
                reason = resolution.reason if resolution else "-"
                print(f"    {kind:33s} {state.value:9s} provider={provider:20s} reason={reason}")

    if result.trace:
        print("\n-- 메시지/이벤트 trace (시간순) --")
        for entry in result.trace:
            arrow = "->" if entry["direction"] == "out" else "<-"
            print(f"  t={entry['time']:g} [{entry['node']}] {arrow} {entry['port']}: {entry['payload']}")

    for node_id, node in result.nodes.items():
        events = getattr(node, "observability", None)
        if events and events.events:
            print(f"\n-- [{node_id}] 관측 이벤트 --")
            for event in events.events:
                print(f"  [{event.severity}] {event.name}: {event.payload}")

    print()
    if result.passed:
        print(f"결과: PASS ({len(result.checkpoints)} checkpoint 모두 기대값 일치)")
    else:
        print(f"결과: FAIL — {len(result.check_failures)}건 불일치")
        for failure in result.check_failures:
            print(f"  - {failure}")


def main() -> int:
    if len(sys.argv) > 1:
        scenario_path = Path(sys.argv[1])
    else:
        scenario_path = _prompt_for_scenario_path()

    if not scenario_path.exists():
        print(f"시나리오 파일을 찾을 수 없다: {scenario_path}")
        return 1

    scenario = load_scenario(scenario_path)
    result = run(scenario)
    narrate(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
