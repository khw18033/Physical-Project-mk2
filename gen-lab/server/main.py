"""gen-lab 서버 — 생성 서비스. **지금은 스텁이다.**

`stt-lab` 과 같은 모양의 FastAPI 다. npm·Vite·node_modules 가 없고, 실행은
`python -m server.main` (gen-lab/ 에서), 포트는 8802 다 — 목 게이트웨이(8790)·
대시보드(5173/8787~8788)·STT(8801)·stt-lab(8799) 과 겹치지 않는다.

## 왜 스텁인가 — 모델이 아직 안 정해졌다

지시서 §4 가 「모델 후보를 둘 이상 같은 정답셋으로 잰다」고 적었고 그 결정이 아직 없다.
엔진 없이 세우는 이유는 그 앞의 것들이 **엔진과 무관하게 정해져야 하기 때문**이다 —
경계(어디까지가 서비스인가) · 계약(무엇을 주고받는가) · 꺼짐(없으면 무엇이 꺼지는가).
엔진을 먼저 붙이면 그 셋이 엔진 모양에 맞춰 굳는다.

**스텁이 실제로 하는 일은 하나다 — 계약 검증.**
받은 문법 지문을 기록하고, 고정 응답을 `contracts/mission.schema.json` 으로 검증해
결과를 그대로 돌려준다. 검증이 실패하면 그 사실을 숨기지 않는다.

## 목임을 감추지 않는다

`/generate/health` 가 `engine: "stub"` 을 돌려주고, 응답의 `extra.stub` 이 `true` 다.
화면은 그것을 그대로 적는다 (`renderMode` 의 목 배지와 같은 규칙).

## 엔진을 붙일 때

`engines/` 에 파일 하나를 더하고 `_load_engine()` 이 그것을 고르게 한다.
이 파일에 엔진 이름이 나오면 안 된다 (`stt-lab/server/main.py` 와 같은 규칙 — REQ-1302).
그때 **문법도 여기서 다시 뽑아 클라이언트가 보낸 지문과 대조해야 한다.** 지금은 스텁이라
받은 지문을 되돌려 주기만 한다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

LAB_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = LAB_ROOT.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"
GOLDSET_DIR = LAB_ROOT / "goldset"
PORT = int(os.environ.get("VIZ_GENERATE_PORT", "8802"))

# 브라우저에서 직접 부른다. 개발 서버(5174)와 포트가 다르므로 출처를 열어 둔다.
# 127.0.0.1 바인딩이라 이 목록 밖에서는 애초에 닿지 않는다.
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5174",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]

app = FastAPI(title="gen-lab", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 계약 ------------------------------------------------------------------


def _load_contracts() -> Dict[str, Any]:
    """`contracts/` 를 통째로 읽어 `$id` 로 찾을 수 있게 한다.

    **복사본을 두지 않는다.** 계약을 gen-lab 안에 베껴 두면 저장소가 계속 피해 온
    「두 벌이 조용히 갈라진다」가 그대로 난다. 저장소 루트의 원본을 읽는다.
    """
    by_id: Dict[str, Any] = {}
    for path in sorted(CONTRACTS_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        by_id[schema.get("$id", path.name)] = schema
    return by_id


CONTRACTS = _load_contracts()


def _validate(instance: Any, schema: Any, path: str = "$") -> List[str]:
    """`contracts/` 가 실제로 쓰는 문법만 다루는 최소 검증기.

    `jsonschema` 패키지를 끌어오지 않는다 — 이 서비스의 의존성은 FastAPI 뿐이고,
    검증 하나 때문에 늘리면 「띄우려면 먼저 설치해야 한다」가 는다.
    범위는 `viz-debugger/scripts/lib/json-schema.mjs` 와 같다(같은 계약을 본다).

    못 다루는 키워드는 **조용히 넘기지 않고** 오류 목록에 적는다.
    """
    errors: List[str] = []

    def type_of(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        return "object"

    def matches(actual: str, expected: str) -> bool:
        if expected == "number":
            return actual in ("number", "integer")
        return actual == expected

    def walk(value: Any, node: Any, root: Any, at: str) -> None:
        known = {
            "$schema", "$id", "$comment", "title", "description", "$defs",
            "type", "required", "properties", "additionalProperties", "items",
            "$ref", "enum", "anyOf",
            "minLength", "minimum", "maximum", "minItems", "uniqueItems",
        }
        for key in node:
            if key not in known:
                errors.append(f"{at}: 다루지 않는 키워드 '{key}'")

        ref = node.get("$ref")
        if ref is not None:
            if ref.startswith("#/$defs/"):
                target = root.get("$defs", {}).get(ref[len("#/$defs/"):])
                if target is None:
                    errors.append(f"{at}: $ref 를 못 찾았다 — {ref}")
                    return
                walk(value, target, root, at)
            else:
                target = CONTRACTS.get(ref)
                if target is None:
                    errors.append(f"{at}: $ref 파일을 못 찾았다 — {ref}")
                    return
                walk(value, target, target, at)
            return

        if "anyOf" in node:
            branch_errors = []
            for branch in node["anyOf"]:
                sub = _validate(value, {**branch, "$defs": root.get("$defs")}, at)
                if not sub:
                    return
                branch_errors.append(" / ".join(sub))
            errors.append(f"{at}: anyOf 의 어느 가지도 통과하지 않았다 — {' | '.join(branch_errors)}")
            return

        actual = type_of(value)
        if "type" in node:
            expected = node["type"] if isinstance(node["type"], list) else [node["type"]]
            if not any(matches(actual, one) for one in expected):
                errors.append(f"{at}: 타입이 {actual} 다 — {'|'.join(expected)} 여야 한다")
                return

        if "enum" in node and value not in node["enum"]:
            errors.append(f"{at}: '{value}' 는 허용 목록에 없다")
        if "minLength" in node and isinstance(value, str) and len(value) < node["minLength"]:
            errors.append(f"{at}: 길이 {len(value)} — 최소 {node['minLength']}")
        if "minimum" in node and isinstance(value, (int, float)) and not isinstance(value, bool) and value < node["minimum"]:
            errors.append(f"{at}: {value} < 최소 {node['minimum']}")
        if "maximum" in node and isinstance(value, (int, float)) and not isinstance(value, bool) and value > node["maximum"]:
            errors.append(f"{at}: {value} > 최대 {node['maximum']}")

        if actual == "array":
            if "minItems" in node and len(value) < node["minItems"]:
                errors.append(f"{at}: 원소 {len(value)}개 — 최소 {node['minItems']}")
            if node.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
                errors.append(f"{at}: 중복 원소가 있다")
            if "items" in node:
                for index, item in enumerate(value):
                    walk(item, node["items"], root, f"{at}[{index}]")
            return

        if actual == "object":
            for key in node.get("required", []):
                if key not in value:
                    errors.append(f"{at}: 필수 항목 '{key}' 가 없다")
            if node.get("additionalProperties") is False and "properties" in node:
                for key in value:
                    if key not in node["properties"]:
                        errors.append(f"{at}: 계약에 없는 항목 '{key}'")
            for key, sub in node.get("properties", {}).items():
                if key in value:
                    walk(value[key], sub, root, f"{at}.{key}")

    walk(instance, schema, schema, path)
    return errors


# --- 고정 응답 -------------------------------------------------------------


def _fixed_mission(utterance: str) -> Dict[str, Any]:
    """스텁의 고정 응답. **정답셋을 베껴 오지 않는다.**

    정답셋(`goldset/`)을 그대로 돌려주면 채점기가 만점을 내고, 그 만점이 「스텁이라서」인지
    「모델이 잘해서」인지 구별되지 않는다. 그래서 **계약만 만족하는 최소 임무 하나**를
    돌려준다 — 스키마 축은 통과하고 나머지 축은 낮게 나오는 것이 스텁의 정직한 모습이다.
    """
    return {
        "mission_id": "MSN-STUB-0001",
        "utterance": {
            "audio_ref": None,
            "text": utterance,
            "engine": "stub",
            # 7.8 utterance.confidence 계약은 260906 에 닫혔다 — `confidence` 를 남기고
            # `confidence_signals` 세 자리를 열었다. 스텁은 **저작된 문장**이라 인식 수치가
            # 없으므로 대본과 같은 규칙으로 1 을 쓰고 `confidence_signals` 를 **넣지 않는다**
            # (그 필드가 required 가 아닌 이유가 이 경우다).
            "confidence": 1,
        },
        "milestones": [
            {
                "milestone_id": "MS-A",
                "title": "생성 서비스 스텁 — 엔진이 붙지 않았습니다",
                "order": 0,
                "status": "pending",
                "assigned_targets": [],
                "tasks": [],
            }
        ],
    }


# --- 면 --------------------------------------------------------------------


class GenerateRequest(BaseModel):
    utterance: str
    grammar: Optional[Dict[str, Any]] = None
    places: Optional[Any] = None
    examples: List[Any] = []
    model: Optional[str] = None


@app.get("/generate/health")
def health() -> Dict[str, Any]:
    """무엇이 떠 있는가. **목임을 감추지 않는다** — 엔진 자리에 `stub` 이 적힌다."""
    return {
        "engine": "stub",
        "model": None,
        "why": "모델이 아직 정해지지 않았습니다 (지시서 §4 의 모델 후보 비교 대기). "
               "요청을 받아 계약 검증만 하고 고정 응답을 돌려줍니다.",
        "contracts": sorted(CONTRACTS.keys()),
        "goldset_missions": len(list((GOLDSET_DIR / "missions").glob("*.json"))) if (GOLDSET_DIR / "missions").exists() else 0,
    }


@app.post("/generate/mission")
def generate_mission(request: GenerateRequest) -> JSONResponse:
    """발화 하나 → 임무 객체. 스텁은 **검증만** 한다."""
    started = time.perf_counter()
    mission = _fixed_mission(request.utterance)
    errors = _validate(mission, CONTRACTS["mission.schema.json"])
    grammar = request.grammar or {}
    body = {
        "mission": mission,
        "engine": "stub",
        "model": request.model or "none",
        # 클라이언트가 계약에서 뽑아 보낸 문법. **여기서 강제하지는 않는다** — 엔진이 없다.
        # 엔진이 붙으면 이 지문을 서비스가 다시 뽑은 것과 대조해야 한다.
        "grammar": (
            {
                "source": grammar.get("source"),
                "digest": grammar.get("digest"),
                "bytes": len(grammar.get("text") or ""),
            }
            if grammar
            else None
        ),
        "schema_checked": True,
        "schema_errors": errors,
        "elapsed_sec": round(time.perf_counter() - started, 6),
        "extra": {
            "stub": True,
            "why": "엔진이 붙지 않았습니다. 이 응답은 계약을 만족하는 최소 임무이지 생성 결과가 아닙니다.",
            "places_given": request.places is not None,
            "examples_given": len(request.examples),
            "grammar_enforced": False,
        },
    }
    # 스텁의 고정 응답이 계약을 어기면 그건 계약이 바뀐 것이다. 숨기지 않고 500 으로 낸다.
    status = 200 if not errors else 500
    if errors:
        body["error"] = "스텁의 고정 응답이 계약을 통과하지 못했습니다 — 계약이 바뀌었는지 확인하세요"
    return JSONResponse(body, status_code=status)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
