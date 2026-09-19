# -*- coding: utf-8 -*-
"""프롬프트의 **한국어 판을 떠 둔다** (260919 · 영문화 5단계 L3).

## 왜 이 파일이 있나

영어 판을 나란히 들이면서 `prompt.py` 의 구조를 손댄다. 그때 **한국어 프롬프트가 한 글자도
안 달라져야 한다** — 6~10단계의 베이스라인 숫자(`score:generation`)가 그 프롬프트로 나온
것이고, 문장이 한 자라도 바뀌면 그 숫자들과 앞으로 잴 숫자를 같은 표에 놓을 수 없다.

「안 바꿨다」는 주장이 아니라 **대조**여야 한다. 그래서 고치기 **전에** 떠서 파일로 남기고,
`verify:gen-prompt` 가 매번 다시 만들어 그 파일과 맞춰 본다.

## 왜 골고루 뜨나

판마다 규칙이 갈린다(`rules_for`). 한 가지만 떠 두면 다른 판에서 벌어진 차이를 못 본다 —
장비 목록 유무(7단계 A/B) · 단계 종류(8단계 D) · 태스크(10단계 E) · 분기(분기와루프 G) 를
켜고 끈 조합을 담는다.

    python gen-lab/goldset/prompt_golden.py          # 대조 (다르면 종료 코드 1)
    python gen-lab/goldset/prompt_golden.py --write  # 다시 뜬다 (일부러 바꿨을 때만)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gen-lab"))

from server import prompt as prompt_builder  # noqa: E402

GOLDEN = Path(__file__).with_name("prompt-ko.golden.json")

#: 켜고 끄는 조합. 이름이 곧 「어느 판인가」다.
CASES = [
    ("base", {}),
    ("equipment", {"equipment": True}),
    ("node_kinds", {"node_kinds": True}),
    ("tasks", {"tasks": True, "equipment": True}),
    ("branch", {"branch": True, "equipment": True}),
    ("tasks_branch", {"tasks": True, "branch": True, "equipment": True}),
    ("all", {"equipment": True, "node_kinds": True, "tasks": True, "branch": True}),
]

UTTERANCE = "503호에서 복도에 있는 엘리베이터 앞까지 이동해줘."
MISSION_ID = "MSN-GOLDEN-01"

EXAMPLE = {
    "mission_id": "MSN-EXAMPLE-01",
    "utterance": {"text": "예시 발화"},
    "milestones": [
        {"milestone_id": "MS-A", "title": "출발 준비", "order": 0, "status": "pending", "assigned_targets": [], "tasks": []},
    ],
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def built() -> dict:
    # 규칙을 끼우는 자리는 **문장 머리**로 찾는다(`_insert_after`). 규칙의 첫 낱말을 바꾸면
    # 그 자리를 못 찾아 터지는데, 역추적만 뜨면 원인이 안 보인다 — 무슨 일인지 적어 준다.
    places = load(ROOT / "places" / "places.json")
    equipment = load(ROOT / "equipment" / "equipment.json")
    out = {}
    for name, flags in CASES:
        out[name] = prompt_builder.build(
            utterance=UTTERANCE,
            mission_id=MISSION_ID,
            places=places,
            examples=[EXAMPLE],
            equipment=equipment if flags.get("equipment") else None,
            node_kinds=flags.get("node_kinds", False),
            tasks=flags.get("tasks", False),
            branch=flags.get("branch", False),
        )
    return out


def main() -> int:
    try:
        now = built()
    except StopIteration:
        print("❌ 규칙을 끼우는 자리를 못 찾았다 — 규칙의 **첫 낱말**을 바꾸면 그 자리가 사라진다")
        print("   (`ANCHORS` 가 문장 머리로 찾는다. 바꿨다면 그 표의 값도 같이 고쳐라)")
        return 1
    except Exception as err:  # noqa: BLE001 — 무엇이든 읽을 수 있게 적는다
        print(f"❌ 프롬프트를 못 만들었다 — {type(err).__name__}: {err}")
        return 1
    if "--write" in sys.argv:
        GOLDEN.write_text(json.dumps(now, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"떠 뒀다 — {GOLDEN.name} · 판 {len(now)}가지")
        return 0

    if not GOLDEN.exists():
        print(f"❌ {GOLDEN.name} 이 없다 — 먼저 --write 로 떠라")
        return 1

    before = load(GOLDEN)
    bad = []
    for name in sorted(set(before) | set(now)):
        if name not in before:
            bad.append(f"{name}: 떠 둔 것에 없는 판이다 — 판을 늘렸으면 --write 로 다시 떠라")
            continue
        if name not in now:
            bad.append(f"{name}: 판이 사라졌다")
            continue
        for part in ("system", "user"):
            if before[name][part] != now[name][part]:
                bad.append(f"{name}.{part}: 한국어 프롬프트가 달라졌다 — 베이스라인 숫자와 같은 표에 못 놓는다")
    if bad:
        print("❌ 프롬프트 대조 실패\n- " + "\n- ".join(bad))
        return 1
    print(f"✅ 한국어 프롬프트 {len(now)}가지가 떠 둔 것과 **글자까지 같다**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
