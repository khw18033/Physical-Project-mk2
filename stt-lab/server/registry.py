"""registry.json 에서 명령 어휘와 시험 발화를 뽑아낸다 (REQ-1304).

호칭 사전을 여기서 새로 만들지 않는다. `display_name` 과 `aliases[]` 가 원천이고,
이 하네스는 그걸 읽기만 한다 — F13이 실제로 쓸 어휘와 같은 것으로 측정해야
측정값이 의미가 있기 때문이다.

**복사본을 두지 않는다.** `../web-dashboard/mock-gateway/registry.json` 를 실행 시점에
읽는다. 복사해 두면 원본이 바뀔 때 조용히 어긋나고, 그 어긋남은 CER이 왜 나빠졌는지를
설명할 수 없게 만든다. 경로는 `STT_LAB_REGISTRY` 로 바꿀 수 있다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# stt-lab/server/registry.py → stt-lab/
LAB_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = LAB_ROOT.parent / "web-dashboard" / "mock-gateway" / "registry.json"

# 발화 문장 틀. 늘리기 쉬우라고 상수로 뺐다.
# 키는 대상 종류이고, `entity:<entity_type>` 이 있으면 그쪽이 우선이다.
UTTERANCE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "zone": (
        "{name} 로봇 상태 보여줘",
        "{name} 화면으로 이동",
        "{name} 알람 확인해줘",
    ),
    "node": (
        "{name} 지표 열어줘",
        "{name} 상태 알려줘",
    ),
    "entity": (
        "{name} 상태 보여줘",
        "{name} 어디 있어",
    ),
    "entity:robot": (
        "{name} 정지",
        "{name} 상태 보여줘",
        "{name} 원점으로 복귀",
    ),
    "entity:sensor": (
        "{name} 값 보여줘",
        "{name} 최근 추이 열어줘",
    ),
    "entity:camera": (
        "{name} 영상 띄워줘",
        "{name} 상태 보여줘",
    ),
    "entity:actuator": (
        "{name} 열어",
        "{name} 닫아",
        "{name} 상태 보여줘",
    ),
    "entity:edge_node": (
        "{name} 지표 열어줘",
    ),
}

# 한 대상당 몇 개의 호칭으로 문장을 만들지. display_name 하나만 쓰면 alias 인식을
# 측정할 수 없고, 전부 쓰면 목록이 수백 줄이 되어 읽을 수가 없다.
NAMES_PER_TARGET = 2


def registry_path() -> Path:
    override = os.environ.get("STT_LAB_REGISTRY")
    return Path(override).expanduser().resolve() if override else DEFAULT_REGISTRY_PATH


_cache: dict[str, Any] = {"mtime": None, "path": None, "data": None}


def load_registry() -> dict[str, Any]:
    """원본을 읽는다. mtime이 바뀌면 다시 읽는다 — 서버를 껐다 켜지 않아도 되게."""
    path = registry_path()
    if not path.exists():
        raise FileNotFoundError(
            f"registry.json 을 찾을 수 없다: {path}\n"
            "web-dashboard 옆에서 실행하고 있는지, 아니면 STT_LAB_REGISTRY 를 지정했는지 확인할 것."
        )
    mtime = path.stat().st_mtime
    if _cache["data"] is None or _cache["mtime"] != mtime or _cache["path"] != str(path):
        _cache.update(
            {"mtime": mtime, "path": str(path), "data": json.loads(path.read_text(encoding="utf-8"))}
        )
    return _cache["data"]


def _targets(reg: dict[str, Any]) -> list[dict[str, Any]]:
    """zone/node/entity 를 (kind, id, display_name, aliases, entity_type) 로 평탄화한다."""
    out: list[dict[str, Any]] = []
    for kind, singular in (("zones", "zone"), ("nodes", "node"), ("entities", "entity")):
        for item in reg.get(kind, []):
            display = item.get("display_name")
            if not display:
                continue
            out.append(
                {
                    "kind": singular,
                    "id": item.get("id"),
                    "display_name": display,
                    "aliases": [a for a in item.get("aliases", []) if a],
                    "entity_type": item.get("entity_type"),
                    "zone": item.get("zone"),
                }
            )
    return out


def vocabulary() -> dict[str, Any]:
    """hotwords 어휘 + 각 어휘가 어디서 왔는지.

    어디서 왔는지를 같이 내보내는 이유: hotwords를 켰을 때 인식이 좋아졌다면
    어떤 항목 덕분인지 알아야 REQ-1304의 확장점을 어떻게 채울지 정할 수 있다.
    """
    reg = load_registry()
    terms: list[dict[str, str]] = []
    seen: set[str] = set()
    for target in _targets(reg):
        for field, value in [("display_name", target["display_name"])] + [
            ("alias", a) for a in target["aliases"]
        ]:
            if value in seen:
                continue
            seen.add(value)
            terms.append(
                {
                    "term": value,
                    "field": field,
                    "kind": target["kind"],
                    "source_id": target["id"] or "",
                    "entity_type": target["entity_type"] or "",
                }
            )
    return {
        "registry_path": str(registry_path()),
        "registry_version": reg.get("registry_version"),
        "count": len(terms),
        "terms": terms,
        "hotwords": hotwords_string(terms),
    }


def hotwords_string(terms: list[dict[str, str]] | None = None) -> str:
    """faster-whisper 의 `hotwords` 에 그대로 넘길 한 줄.

    `initial_prompt` 와 합치지 않는다. hotwords 는 이 어휘 쪽으로 디코딩을 편향시키는
    것이고, initial_prompt 는 문맥·문체를 유도하는 것이라 목적이 다르다.
    """
    if terms is None:
        terms = vocabulary()["terms"]
    return ", ".join(t["term"] for t in terms)


def _speakable(name: str) -> str:
    """읽어서 녹음할 이름으로 다듬는다.

    `display_name` 에는 화면용 괄호 주석이 붙어 있다(`엣지 노드 A (자기 관측)`).
    그대로 읽으면 정답 문장이 부자연스러워져서 CER이 모델 성능이 아니라
    문장 어색함을 재게 된다. 괄호만 떼고 나머지는 원본 그대로 둔다.
    """
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def utterance_presets() -> dict[str, Any]:
    """registry 조합으로 시험 발화 문장을 자동 생성한다.

    읽고 녹음하면 정답 텍스트가 이미 정해져 있으므로 CER이 바로 나온다.
    사람이 문장을 매번 지어내면 정답이 흔들려 모델 간 비교가 안 된다.
    """
    reg = load_registry()
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for target in _targets(reg):
        key = f"{target['kind']}:{target['entity_type']}" if target["entity_type"] else target["kind"]
        templates = UTTERANCE_TEMPLATES.get(key) or UTTERANCE_TEMPLATES.get(target["kind"], ())
        names = ([target["display_name"]] + target["aliases"])[:NAMES_PER_TARGET]
        for name in names:
            spoken = _speakable(name)
            for template in templates:
                text = template.format(name=spoken)
                if text in seen:
                    continue
                seen.add(text)
                items.append(
                    {
                        "text": text,
                        "target_id": target["id"] or "",
                        "target_kind": target["kind"],
                        "name_used": spoken,
                        "template": template,
                    }
                )
    return {"count": len(items), "items": items}
