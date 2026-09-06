"""프롬프트를 만드는 **유일한 자리** (`VZ-G-01` 베이스라인 · 지시서 §4).

## 왜 서비스가 만드는가

부르는 쪽이 프롬프트 문자열을 통째로 넘기게 하면, 같은 정답셋을 재는 두 사람이 서로 다른
프롬프트로 재고도 그 사실을 모른다. **측정의 조건이 코드에 있어야** 숫자가 비교된다.
부르는 쪽이 고르는 것은 **재료**다 — 장소 위상과 few-shot 예시. 그 둘을 어떻게 문장으로
펴는지는 여기 한 곳에 있다.

## 부르는 쪽이 고르는 것 — few-shot 누출을 막는 자리

**채점 대상인 편은 예시에서 뺀다**(지시서 §4-3). 그 선택은 부르는 쪽이 한다 —
서비스는 어느 편이 채점 대상인지 모르기 때문이다. 뺐는지 검사하는 것이
`verify:no-leak` 이고, 이 파일은 **받은 예시를 그대로 싣기만 한다.**

## 기하를 읽지 않는다

좌표를 든 층(§1 에서 갈라 둔 기하 파일)을 여는 경로가 이 파일에도, gen-lab 어디에도
없다. 좌표를 보면 모델이 503호 전용이 된다.

`verify:places` 4번 검사가 `gen-lab/server/` 와 `src/generate/` 를 훑어 **그 파일 이름이
나오는지**를 본다 — 주석이라도 잡는다. 문자열은 언젠가 코드가 되기 때문이고, 그래서
여기서도 파일 이름을 적지 않고 「기하 파일」이라고만 쓴다. (3단계에 `verify:no-stt` 가
같은 이유로 `LlmClient` 의 주석을 잡았다.)
"""

from __future__ import annotations

import json
from typing import Any, Optional

#: 마일스톤이 지켜야 하는 것. **화면에도 보고서에도 이 문장 그대로 쓴다** —
#: 규칙을 두 벌로 적으면 모델이 지킨 규칙과 사람이 채점한 규칙이 갈라진다.
RULES = [
    "출력은 JSON 객체 하나다. 설명·주석·코드펜스를 붙이지 않는다.",
    # 첫 실측에서 4B 가 20건 전부 마일스톤 하나로 답했다 — 발화를 그대로 옮겨 적은 것이다.
    # 개수를 알려주지 않고 **할 일이 무엇인지**만 적는다. 개수를 주면 그것은 정답 누출이다.
    "마일스톤은 여러 개다. 임무를 **사람이 중간에 확인할 수 있는 단위**로 나눈다 — 발화 한 줄을 마일스톤 하나로 옮겨 적는 것은 분리가 아니다.",
    "마일스톤은 **무엇을 이루는가**를 적는다. 어떻게 이루는지는 적지 않는다.",
    "로봇 기종·모델명(예: 사족보행 로봇의 제품명)을 쓰지 않는다. 어떤 장비가 하는지는 assigned_targets 로만 적는다.",
    "좌표를 쓰지 않는다. (x, y, z) 나 절대 위치를 적으면 그 마일스톤은 이 건물 전용이 된다.",
    "속도·가속도·모터 파라미터를 쓰지 않는다. 그것은 실행이 정하는 값이다.",
    "임무 자체의 조건(시간·수위·거리 임계처럼 발화가 요구한 것)은 적어도 된다. 금지되는 것은 구현 파라미터다.",
    "장소는 아래 [장소] 목록에 있는 이름만 쓴다. 목록에 없는 방 번호·층·시설을 만들면 실패다.",
    "tasks 는 빈 배열 [] 로 둔다. 태스크 분해는 다음 단계가 한다.",
    "status 는 모두 \"pending\", order 는 0 부터 1 씩 는다.",
    "mission_id 와 utterance 는 아래 [요청] 에 준 값을 그대로 옮긴다.",
]


def render_places(places: Any) -> str:
    """`places.json` → 프롬프트에 실을 장소 위상.

    **좌표는 애초에 `places.json` 에 없다.** 층을 나눈 것이 여기서 값을 한다 —
    실수로 좌표를 실을 방법 자체가 없다.
    """
    if not places:
        return "(장소 목록이 주어지지 않았습니다 — 그라운딩 없이 돕니다.)"
    entries = places.get("places", []) if isinstance(places, dict) else list(places)
    by_id = {entry["place_id"]: entry for entry in entries}
    lines = []
    for entry in entries:
        neighbours = [by_id[pid]["label"] for pid in entry.get("adjacent", []) if pid in by_id]
        floor = entry.get("floor")
        head = f"{entry['label']} ({entry['kind']}, {floor}층)" if floor is not None else f"{entry['label']} ({entry['kind']})"
        alias = [a for a in entry.get("aliases", []) if a != entry["label"]]
        if alias:
            head += f" [별칭: {', '.join(alias)}]"
        lines.append(f"- {head}" + (f" ↔ {' · '.join(neighbours)}" if neighbours else " ↔ (연결 예정)"))
    return "\n".join(lines)


def render_example(example: Any) -> str:
    """few-shot 한 편. **정답 JSON 을 그대로 보인다.**

    말로 설명한 예시는 형식을 가르치지 못한다 — 형식 안정성이 이 프롬프트의 첫 목표이고,
    그것은 모양을 보여야 옮는다.
    """
    utterance = example.get("utterance", {})
    shown = {
        "mission_id": example.get("mission_id"),
        "utterance": utterance,
        "milestones": example.get("milestones", []),
    }
    return (
        f"발화: {utterance.get('text', '')}\n"
        f"출력:\n{json.dumps(shown, ensure_ascii=False, indent=2)}"
    )


SYSTEM = (
    "너는 사람의 한국어 발화를 **마일스톤 목록**으로 나누는 임무 계획기다.\n"
    "마일스톤은 임무를 사람이 확인할 수 있는 단계로 자른 것이고, 각 단계는 추상적이어야 한다.\n"
    "출력은 계약(JSON 스키마)을 만족하는 JSON 객체 하나뿐이다."
)


def build(
    utterance: str,
    mission_id: str,
    places: Any = None,
    examples: Optional[list[Any]] = None,
    utterance_meta: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    """(system, user) 두 문자열. **엔진의 대화 틀은 엔진이 씌운다** (`engines/`)."""
    examples = examples or []
    parts = [
        "[규칙]",
        "\n".join(f"{i + 1}. {rule}" for i, rule in enumerate(RULES)),
        "",
        "[장소] 이 목록 밖의 장소를 만들면 실패다.",
        render_places(places),
    ]
    if examples:
        parts += ["", f"[예시] {len(examples)}편. 같은 형식으로 낸다."]
        parts += [render_example(example) for example in examples]
    meta = utterance_meta or {"audio_ref": None, "text": utterance, "engine": "script", "confidence": 1}
    parts += [
        "",
        "[요청]",
        f"mission_id: {mission_id}",
        f"utterance: {json.dumps(meta, ensure_ascii=False)}",
        f"발화: {utterance}",
        "",
        "위 발화의 마일스톤을 JSON 으로 내라.",
    ]
    return {"system": SYSTEM, "user": "\n".join(parts)}
