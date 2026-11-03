"""implements: AI-O-06, AI-O-05, AI-L-10, AI-C-04, AI-C-15
covers: 가시화 파트가 **코드 변경 없이** 우리 상태를 화면에 올릴 수 있는가.

가시화는 컴포넌트 디스크립터와 데이터소스 선언을 읽어 파이프라인(소스 → 변환 →
렌더러)으로 화면을 조립한다. 그래서 우리가 보낼 수 있는 것을 그 계약으로 **선언**해
두면 화면 조립이 기계적인 일이 되고, 선언이 없으면 매번 사람이 물어봐야 한다.

이 시험이 고정하는 것 셋.
  1. 우리 선언이 그쪽 계약(vendored 사본)을 지킨다.
  2. 선언한 필드 이름이 **실제 와이어에 있는 이름**이다 — 선언만 맞고 메시지가 다른
     이름을 쓰면 화면은 빈 칸을 그린다.
  3. `representationHint` 가 그쪽 코어 렌더러 타입이고, 그 렌더러가 우리 필드 타입을
     받는다 — 아니면 파이프라인 검증기가 조립 단계에서 거부한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dashboard_example import example_message

VIZ_DIR = Path(__file__).parents[1] / "schemas" / "viz"
VENDOR_DIR = VIZ_DIR / "vendor"

#: 가시화 코어 내장 렌더러와 그것이 받는 필드 타입(renderer.schema.json 의 설명이
#: 꼽은 여섯 종). 확장 렌더러를 쓰면 그쪽 등록이 선행해야 하므로 내장만 쓴다.
CORE_RENDERERS: dict[str, set[str]] = {
    "text": {"string", "number", "boolean", "enum"},
    "table": {"array", "object"},
    "graph": {"number", "object"},
    "image": {"string", "binary-stream"},
    "video-stream": {"binary-stream"},
    "audio": {"binary-stream"},
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_load(VENDOR_DIR / f"{name}.schema.json"))


COMPONENT_FILES = sorted(VIZ_DIR.glob("component-*.json"))


def test_there_is_something_to_declare():
    assert COMPONENT_FILES, "컴포넌트 디스크립터가 하나도 없으면 아래 시험이 공허하다"


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=lambda p: p.stem)
def test_each_component_declaration_satisfies_the_visualization_contract(path: Path):
    _validator("component-descriptor").validate(_load(path))


def test_the_datasource_declaration_satisfies_the_visualization_contract():
    _validator("datasource").validate(_load(VIZ_DIR / "datasource-ai-status.json"))


def test_we_do_not_promise_range_queries_we_cannot_serve():
    """스냅샷은 현재 상태다. 이력 보관은 백엔드 책임이므로 구간 질의를 약속하지 않는다.

    약속해 두면 화면이 그래프 렌더러를 구간 질의로 붙이고, 그 질의는 런타임에 실패한다.
    """
    source = _load(VIZ_DIR / "datasource-ai-status.json")
    assert source["capabilities"] == {
        "instantQuery": True, "rangeQuery": False, "streaming": True
    }


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=lambda p: p.stem)
def test_every_hint_is_a_core_renderer_that_accepts_that_field_type(path: Path):
    for field in _load(path)["fields"]:
        hint = field.get("representationHint")
        if hint is None:
            continue
        assert hint in CORE_RENDERERS, f"{field['name']}: 확장 렌더러 {hint!r} 는 그쪽 등록이 먼저다"
        assert field["type"] in CORE_RENDERERS[hint], (
            f"{field['name']}: {hint} 렌더러는 {field['type']} 타입을 받지 않는다"
        )


def _wire_names() -> dict[str, set[str]]:
    """실제 메시지에 있는 이름을, 선언과 맞댈 묶음별로 모은다."""
    message = example_message()
    out: dict[str, set[str]] = {}
    for section in ("accelerators", "services", "task_nodes", "external_requests",
                    "model_assignments"):
        names: set[str] = set()
        for item in message[section]:
            names |= set(item)
        out[section] = names
    return out


#: 디스크립터 ↔ 스냅샷 묶음. 이름이 다르면 화면은 조용히 빈 칸을 그린다.
SECTION_OF = {
    "ai-accelerator": "accelerators",
    "ai-service": "services",
    "ai-task-node": "task_nodes",
    "ai-external-request": "external_requests",
    "ai-model-assignment": "model_assignments",
}


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=lambda p: p.stem)
def test_declared_field_names_exist_on_the_wire(path: Path):
    """선언한 이름이 메시지에 실제로 있는 이름이어야 한다.

    `required: true` 로 선언한 필드는 예제의 **모든** 항목에 있어야 한다 — 가시화 쪽
    코어가 값 누락 시 컴포넌트 등록을 거부하기 때문이다(REQ-102). 선택 필드는 예제에
    한 번이라도 나오면 된다.
    """
    descriptor = _load(path)
    wire = _wire_names()[SECTION_OF[descriptor["id"]]]
    message = example_message()
    items = message[SECTION_OF[descriptor["id"]]]

    for field in descriptor["fields"]:
        name = field["name"]
        if field["required"]:
            missing = [i.get("task_node_id", i.get("service_id", "?"))
                       for i in items if name not in i]
            assert not missing, f"{name}: required 인데 {missing} 항목에 없다"
        else:
            assert name in wire, f"{name}: 어느 항목에도 없는 이름을 선언했다"


@pytest.mark.parametrize("path", COMPONENT_FILES, ids=lambda p: p.stem)
def test_declared_types_match_the_values_actually_sent(path: Path):
    """타입까지 맞춰야 렌더러 선택이 성립한다. 숫자라고 선언하고 문자열을 보내지 않는다."""
    python_type = {
        "string": str, "number": (int, float), "boolean": bool,
        "object": dict, "array": list, "enum": str,
    }
    descriptor = _load(path)
    items = example_message()[SECTION_OF[descriptor["id"]]]
    for field in descriptor["fields"]:
        expected = python_type[field["type"]]
        for item in items:
            if field["name"] not in item:
                continue
            value = item[field["name"]]
            assert isinstance(value, expected) and not (
                field["type"] == "number" and isinstance(value, bool)
            ), f"{field['name']}: {field['type']} 로 선언했는데 {type(value).__name__} 이 왔다"
            if field["type"] == "enum":
                assert value in field["enumValues"], f"{field['name']}: {value!r} 가 어휘 밖이다"


def test_the_vendored_copies_are_not_edited():
    """사본을 고치면 "그쪽 계약을 지킨다"는 말이 거짓이 된다.

    고쳐야 할 이유가 생기면 그쪽 계약을 RFC 로 바꾸는 것이 순서다. 여기서는 사본이
    그쪽 $id 를 그대로 들고 있는지만 본다 — 우리 것으로 바꿔 적지 않았다는 뜻이다.
    """
    for name in ("component-descriptor", "datasource", "renderer"):
        schema = _load(VENDOR_DIR / f"{name}.schema.json")
        assert schema["$id"].startswith("https://hybrid-dt-framework/")
