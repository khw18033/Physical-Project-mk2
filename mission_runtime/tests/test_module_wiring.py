"""계약은 있는데 아무도 부르지 않는 상태를 **시험 실패로** 만든다.

implements: AI-C-10 (기능·자원 등록·탐색 — 등록된 것이 실제로 쓰이는가),
            AI-B-09 (신규 확장 등록·호환성 검증 — 검증 전에는 선택 후보가 아니다)
관련: AI-C-04 (provider 경계 — adapter 를 상위가 이름으로 부르면 안 된다),
      AI-C-05 (선택 기능 결손은 정상, 그러나 '선언된 비활성' 과 '세우는 코드 없음' 은 다르다),
      AI-C-19 (다른 파트가 소유한 사실의 대역을 프레임워크가 부르면 주인이 둘이 된다)
tests: 이 파일 자체가 검출기다. 예외는 `config/module_wiring.json` 이 선언한다.

왜 이 시험이 있는가
-------------------
2026-11-04 하루에 여섯 번, 모듈이 올바르게 쓰이고 추적표에 **완료**로 적히고도
어떤 운영 코드도 부르지 않는 상태로 남았다. 그 상태는 시험을 통과한다 — 시험이
모듈을 직접 import 해서 돌리기 때문이다. 사람이 알아채야 했던 것을 여기서 깨뜨린다.

무엇을 "불렀다"로 세는가 — 그리고 왜 문자열 일치가 정직하지 않은가
------------------------------------------------------------------
`grep` 으로 모듈 이름을 찾으면 **주석 안의 단어**가 호출로 세어진다. 실제로 그
일이 일어났다: `perception/temporal_alignment.py` 의 docstring 이
"(AI-S-01, `perception/tracking.py`)" 라고 적고 있어서 문자열 일치는
`perception/tracking.py` 를 "불린 것" 으로 셌다. 그래서 여기서는 AST 로 **import
문만** 센다. 네 가지 모양을 모두 해소한다.

1. 절대 import — `from mission_runtime.x.y import z`, `import mission_runtime.x.y`.
2. 상대 import — `from . import y`, `from ..x import y` (level 을 풀어 올라간다).
3. 패키지 안의 모듈 import — `from mission_runtime.x import y` 에서 `x.y` 가
   모듈이면 그것을 가리킨 것으로 센다.
4. **스크립트형 import** — `tools/fms_console/serve.py` 는 자기 디렉터리를
   `sys.path` 에 넣고 `from overlay import ...` 로 형제를 부른다. 이름 그대로는
   어느 패키지도 아니므로, 미해소 이름의 첫 조각을 **그 파일의 디렉터리**와
   패키지 루트에 대해 한 번 더 찾는다. 이 모양을 빠뜨리면 콘솔이 부르는 모듈
   전부가 거짓 공백으로 올라온다.

함수 안의 늦은 import 는 **센다**. `providers/`·`edge/` 는 선택 의존성을 일부러
생성자 안에서 import 하고, 그것도 진짜 간선이다 — `ast.walk` 가 깊이에 상관없이
방문하므로 따로 할 일이 없다.

문자열로 늦게 여는 것 두 가지는 다르게 다룬다.

* `importlib.import_module("고정 문자열")` — 리터럴이면 간선으로 센다.
* `importlib.import_module(변수)` — 가리키는 곳을 **코드가 모른다**. 그 값의
  출처는 선언이므로, `config/`·`profiles/`·`deploy/` 의 파일에 적힌
  `mission_runtime.…` 토큰을 **선언 도달**로 따로 센다. `edge/detector_catalog.py`
  가 `provider_path` 를 그렇게 열기 때문에 `edge/yoloe_provider.py` 는 이 경로로만
  닿는다. 선언이 고르는 것을 "아무도 안 부른다" 로 적으면 AI-C-04 를 지킨 쪽이
  결함으로 보인다.

패키지 `__init__.py` 의 재수출은 **호출이 아니다**. `continual/__init__.py` 가
다섯 모듈을 재수출하지만 그 패키지를 부르는 운영 모듈이 없으면 다섯은 여전히
아무도 부르지 않는 것이다. 그래서 `__init__` 은 통과 지점으로만 취급한다 —
자기 자신이 닿아 있을 때만 자기가 import 한 것을 닿게 한다.

무엇이 "원래 혼자 서 있는 것" 인가 — 규칙과 선언을 어떻게 나눴는가
------------------------------------------------------------------
`tools/`(사람이 돌리는 콘솔·명령), `services/`·`deploy/`(장치에 올라가는 배포
단위)는 그래프의 **잎**이다. "콘솔을 누가 import 하나" 는 답이 없는 질문이라
요구 대상에서 규칙으로 뺀다. 그러나 디렉터리를 조용히 빼면 그 안의 진짜 공백이
숨는다 — 그래서 잎에도 조건을 건다: **`if __name__ == "__main__"` 를 가지거나
자기 트리 안에서 import 되어야 한다.** 둘 다 아니면 그것은 진입점도 라이브러리도
아니고 요구 대상이다. 이 조건이 실제로 하나를 잡았다
(`services/edge-node/tracking.py` — `perception/tracking.py` 의 사본).

반대로 프레임워크 모듈의 `__main__` 블록은 면제 사유가 **아니다**. 라이브러리에
붙은 진단용 진입점은 "이 capability 가 운영에 배선됐다" 의 증거가 아니다
(`runtime/environment_profile.py` 가 그 모양이고, 그 모듈은 콘솔이 실제로 부르기
때문에 통과한다 — `__main__` 때문이 아니다).

예외에 사유가 없으면 같은 눈가림이 자리만 옮긴 것이다
-----------------------------------------------------
그래서 예외는 코드가 아니라 `config/module_wiring.json` 에 선언하고, 줄마다
`kind` 와 `reason` 을 요구한다. `deferred` 는 `wired_by` 까지 요구한다 — 무엇이
생기면 이 줄이 사라지는지 적지 않은 "아직 안 했다" 는 추적되지 않는다. 그리고
**낡은 예외도 실패다**: 배선된 모듈이 장부에 남아 있으면 장부가 거짓이 된다.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = PACKAGE_ROOT.name
LEDGER_PATH = PACKAGE_ROOT / "config" / "module_wiring.json"

#: 벤더 트리. 우리가 쓴 코드가 아니므로 요구 대상도 아니고 간선을 세지도 않는다.
VENDORED = ("third_party", "node_modules", "__pycache__")

#: 그래프의 잎 — 사람이 돌리는 명령과 장치에 올라가는 배포 단위.
ENTRY_TREES = ("tools", "services", "deploy")

#: 선언이 모듈 경로를 적는 자리. `importlib.import_module(변수)` 의 값이 여기서 온다.
DECLARATION_TREES = ("config", "profiles", "deploy")

#: 선언 파일 안에서도 **산문은 선언이 아니다.** 이 키들의 값에 적힌 모듈 이름은
#: 설명이고 배치가 고르는 값이 아니다 — 세면 `grep` 과 같은 거짓 호출이 돌아온다.
#: 이 장부 자신이 그 증거다: `wired_by` 에 모듈 이름을 적는 순간 그 모듈이
#: "선언으로 닿는다" 가 되어 예외가 스스로를 지웠다.
PROSE_KEYS = frozenset({
    "$comment", "$cut", "comment", "notes", "note", "reason", "wired_by",
    "description", "method", "label", "detail", "rationale",
})

#: 생성된 코드. 사람이 쓴 모듈의 규약(§7 `implements:`)을 요구하지 않는다.
GENERATED_SUFFIXES = ("_pb2.py", "_pb2_grpc.py")

KNOWN_KINDS = frozenset({"adapter", "reference", "mock", "experiment", "deferred"})

IMPLEMENTS = re.compile(r"implements:")
MODULE_TOKEN = re.compile(rf"{PACKAGE}\.[A-Za-z0-9_.]+")


# ---------------------------------------------------------------------------
# 그래프
# ---------------------------------------------------------------------------


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE_ROOT).parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][: -len(".py")]
    return ".".join([PACKAGE] + parts)


def _source_files() -> list[Path]:
    return [
        path
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if not set(path.parts) & set(VENDORED)
    ]


class WiringGraph:
    """import 간선 + 선언 도달. 판정하지 않고 사실만 모은다."""

    def __init__(self) -> None:
        #: 장부의 `deferred` 목록 — 처음 물을 때 한 번 읽는다.
        self._deferred: frozenset[str] | None = None
        self.modules: dict[str, Path] = {_module_name(p): p for p in _source_files()}
        self.paths: dict[str, str] = {
            name: path.relative_to(PACKAGE_ROOT).as_posix()
            for name, path in self.modules.items()
        }
        self._by_name: dict[str, str] = {v: k for k, v in self.paths.items()}
        # 스크립트형 import 해소용: 디렉터리 -> {파일 이름(stem): 모듈 이름}
        self._siblings: dict[Path, dict[str, str]] = {}
        for name, path in self.modules.items():
            self._siblings.setdefault(path.parent, {})[path.stem] = name

        self.imports: dict[str, set[str]] = {
            name: self._resolve(path) for name, path in self.modules.items()
        }
        self.importers: dict[str, set[str]] = {name: set() for name in self.modules}
        for source, targets in self.imports.items():
            for target in targets:
                if target != source:
                    self.importers[target].add(source)

        self.declared: dict[str, set[str]] = self._declarations()

    # -- import 문 읽기 ---------------------------------------------------

    def _references(self, path: Path) -> set[str]:
        """이 파일이 적은 import 대상 이름 전부(미해소 상태)."""
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        me = _module_name(path)
        raw: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                raw.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    # 상대 import. `__init__.py` 는 자기가 곧 패키지다.
                    base = me if path.name == "__init__.py" else me.rsplit(".", 1)[0]
                    for _ in range(node.level - 1):
                        base = base.rsplit(".", 1)[0] if "." in base else base
                    module = f"{base}.{node.module}" if node.module else base
                else:
                    module = node.module or ""
                if not module:
                    continue
                raw.add(module)
                # `from pkg import mod` — 이름 하나가 모듈일 수 있다.
                raw.update(f"{module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Call):
                func = node.func
                called = (
                    func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name)
                    else ""
                )
                if called in {"import_module", "__import__"}:
                    # 리터럴만. 변수는 코드가 가리키는 곳을 모르므로 선언 쪽에서 센다.
                    raw.update(
                        arg.value for arg in node.args
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    )
        return raw

    def _resolve(self, path: Path) -> set[str]:
        resolved: set[str] = set()
        for target in self._references(path):
            if target in self.modules:
                resolved.add(target)
                continue
            head = target.split(".")[0]
            # 스크립트형: 자기 디렉터리가 sys.path 에 들어가 있다.
            sibling = self._siblings.get(path.parent, {}).get(head)
            if sibling is not None:
                resolved.add(sibling)
                continue
            # 패키지 루트 자체가 sys.path 에 들어가 있는 경우.
            rooted = f"{PACKAGE}.{target}"
            if rooted in self.modules:
                resolved.add(rooted)
        return resolved

    # -- 선언 도달 --------------------------------------------------------

    def _narrow(self, token: str) -> str:
        """`mission_runtime.edge.x:Class` 처럼 뒤가 붙어 오므로 모듈까지 좁힌다."""
        name = token
        while name and name not in self.modules:
            name = name.rsplit(".", 1)[0] if "." in name else ""
        return name

    def _declaration_strings(self, node: object) -> list[str]:
        """선언 문서에서 **값으로** 적힌 문자열만. 산문 키는 건너뛴다."""
        out: list[str] = []
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, list):
            for item in node:
                out += self._declaration_strings(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and (key.startswith("$") or key in PROSE_KEYS):
                    continue
                out += self._declaration_strings(value)
        return out

    def _declarations(self) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for tree in DECLARATION_TREES:
            base = PACKAGE_ROOT / tree
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.suffix in {".py", ".pyc"}:
                    continue
                if path == LEDGER_PATH:
                    # 이 장부는 선언이 아니라 **장부**다. 자기 사유에 적은 모듈
                    # 이름을 선언으로 세면 예외가 스스로를 지운다.
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:  # pragma: no cover - 읽히지 않는 자산은 선언이 아니다
                    continue
                if path.suffix == ".json":
                    try:
                        values = self._declaration_strings(json.loads(text))
                    except ValueError:  # pragma: no cover - 깨진 JSON 은 다른 시험의 몫
                        values = [text]
                else:
                    values = [text]
                for value in values:
                    for token in MODULE_TOKEN.findall(value):
                        name = self._narrow(token)
                        if name:
                            found.setdefault(name, set()).add(
                                path.relative_to(PACKAGE_ROOT).as_posix()
                            )
        return found

    # -- 분류 -------------------------------------------------------------

    def is_test(self, name: str) -> bool:
        return name == f"{PACKAGE}.tests" or name.startswith(f"{PACKAGE}.tests.")

    def is_entry_tree(self, name: str) -> bool:
        return any(name.startswith(f"{PACKAGE}.{tree}.") for tree in ENTRY_TREES)

    def is_package(self, name: str) -> bool:
        return self.modules[name].name == "__init__.py"

    def production_importers(self, name: str) -> set[str]:
        """테스트가 아닌 import 주체. `__init__` 은 자기가 닿아 있을 때만 센다."""
        out: set[str] = set()
        for source in self.importers[name]:
            if self.is_test(source):
                continue
            if self.is_package(source) and not self._package_reached(source):
                continue
            out.add(source)
        return out

    def _package_reached(self, package: str) -> bool:
        """패키지 `__init__` 자신이 운영 쪽에서 닿는가(재수출을 호출로 세지 않기 위해)."""
        seen: set[str] = set()
        frontier = [package]
        while frontier:
            current = frontier.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in self.declared or self.is_entry_tree(current):
                return True
            for source in self.importers[current]:
                if self.is_test(source):
                    continue
                if self.is_package(source):
                    frontier.append(source)
                    continue
                return True
        return False

    def deferred_modules(self) -> frozenset[str]:
        """장부가 `deferred` 로 적은 모듈들의 import 이름.

        장부를 다시 적지 않고 **읽는다** — 같은 사실을 두 곳에 두면 한쪽만 고쳐진다.
        """
        if self._deferred is None:
            try:
                ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                # 장부를 못 읽는 것은 **다른 시험의 실패**다. 여기서 조용히 빈
                # 집합으로 두면 그 실패가 이 판정까지 흐린다.
                ledger = {"exceptions": []}
            names = set()
            for entry in ledger.get("exceptions", ()):
                if entry.get("kind") != "deferred":
                    continue
                path = str(entry.get("path") or "")
                if path.endswith(".py"):
                    names.add(f"{PACKAGE}." + path[: -len(".py")].replace("/", "."))
            self._deferred = frozenset(names)
        return self._deferred

    def framework_modules(self) -> list[str]:
        """배선을 요구하는 집합 — 잎 트리와 패키지 `__init__`, 테스트를 뺀 전부."""
        return [
            name
            for name in sorted(self.modules)
            if not self.is_test(name)
            and not self.is_entry_tree(name)
            and not self.is_package(name)
        ]

    def entry_tree_modules(self) -> list[str]:
        return [
            name
            for name in sorted(self.modules)
            if self.is_entry_tree(name) and not self.is_package(name)
        ]

    def has_main_guard(self, name: str) -> bool:
        text = self.modules[name].read_text(encoding="utf-8", errors="replace")
        return 'if __name__ ==' in text

    def wired(self, name: str) -> bool:
        """운영 쪽에서 닿는가. **지연 모듈이 부르는 것은 닿는 것이 아니다.**

        2026-11-04: 전에는 한 홉만 봤다 — 운영 파일 하나가 import 하면 배선된
        것으로 셌다. 그러면 지연 모듈 사슬이 **마지막 한 줄 뒤에 숨는다**: 사슬을
        한 곳으로 묶는 조립 모듈을 하나 더하면 그 모듈만 장부에 남고 아래 전부가
        목록에서 빠지는데, 아무도 그 조립 모듈을 부르지 않으므로 **실제로 도는
        코드는 하나도 늘지 않았다.** 실제로 `planning/driving_plan.py` 를 더한
        순간 `path_candidates` 와 `hazard_field` 두 줄이 낡은 예외로 떴고, 그
        순간이 이 구멍이 드러난 자리다.

        그래서 `deferred` 로 선언된 모듈의 import 는 세지 않는다. `adapter` ·
        `reference` · `mock` · `experiment` 는 **센다** — 그쪽은 '불러서는 안 되는
        것' 이고 지연된 공백이 아니므로, 그것들이 무엇을 쓰는지는 정상 사실이다.
        """
        if name in self.declared:
            return True
        return bool(self.production_importers(name) - self.deferred_modules())

    def unwired(self) -> list[str]:
        """운영 쪽에서 아무도 부르지 않는 모듈 — 프레임워크 전부 + 잎 트리의 고아."""
        out = [name for name in self.framework_modules() if not self.wired(name)]
        for name in self.entry_tree_modules():
            if self.wired(name) or self.has_main_guard(name):
                continue
            tree = name.split(".")[1]
            in_tree = any(
                source.startswith(f"{PACKAGE}.{tree}.")
                for source in self.production_importers(name)
            )
            if not in_tree:
                out.append(name)
        return sorted(out)


@pytest.fixture(scope="module")
def graph() -> WiringGraph:
    return WiringGraph()


@pytest.fixture(scope="module")
def ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def declared_exceptions(ledger: dict) -> dict[str, dict]:
    return {entry["path"]: entry for entry in ledger["exceptions"]}


# ---------------------------------------------------------------------------
# 검출기가 눈을 뜨고 있는지부터 확인한다
# ---------------------------------------------------------------------------


def test_graph_counts_the_four_import_shapes(graph: WiringGraph) -> None:
    """해소가 조용히 망가지면 "전부 배선됨" 이 되어 검출기가 무용해진다.

    그래서 네 모양 각각에 대해 **지금 사실인 간선 하나씩**을 고정한다.
    """
    # 1) 절대 import
    assert f"{PACKAGE}.contracts.profile" in graph.imports[f"{PACKAGE}.selection.selector"]
    # 2) 패키지 안의 모듈 import — `collection/__init__.py` 가
    #    `from mission_runtime.collection.sampler import ...` 로 부른다
    assert f"{PACKAGE}.collection.sampler" in graph.imports[f"{PACKAGE}.collection"]
    #    상대 import(`from .dgs import ...`)도 같은 모양으로 해소된다
    assert f"{PACKAGE}.continual.dgs" in graph.imports[f"{PACKAGE}.continual"]
    # 3) 스크립트형 형제 import — 콘솔이 `from overlay import ...` 로 부른다
    console = f"{PACKAGE}.tools.fms_console.serve"
    assert f"{PACKAGE}.tools.fms_console.overlay" in graph.imports[console]
    # 4) 선언 도달 — `edge/detector_catalog.py` 가 변수로 늦게 여는 자리
    assert f"{PACKAGE}.edge.yoloe_provider" in graph.declared


def test_graph_sees_a_known_wired_module(graph: WiringGraph) -> None:
    """콘솔이 실제로 부르는 모듈은 배선으로 세어져야 한다."""
    assert graph.wired(f"{PACKAGE}.runtime.refresh")
    assert graph.wired(f"{PACKAGE}.registry.onboarding")


def test_package_reexport_is_not_a_call(graph: WiringGraph) -> None:
    """`__init__.py` 재수출만으로 배선됐다고 말하지 않는다.

    `continual/__init__.py` 는 `dgs` 를 재수출하지만 그 패키지를 부르는 운영
    모듈이 없다 — 재수출은 통과 지점이고 호출이 아니다.
    """
    dgs = f"{PACKAGE}.continual.dgs"
    assert f"{PACKAGE}.continual" in graph.importers[dgs]
    assert not graph.wired(dgs)


def test_main_guard_does_not_excuse_a_framework_module(graph: WiringGraph) -> None:
    """라이브러리에 붙은 진단 진입점은 배선의 증거가 아니다."""
    name = f"{PACKAGE}.runtime.environment_profile"
    assert graph.has_main_guard(name)
    # 이 모듈은 콘솔이 실제로 부르기 때문에 통과한다 — `__main__` 때문이 아니다.
    assert graph.production_importers(name)


# ---------------------------------------------------------------------------
# 본 검출: 부르는 곳 없는 모듈은 선언된 예외여야 한다
# ---------------------------------------------------------------------------


def test_every_unwired_module_is_a_declared_exception(
    graph: WiringGraph, declared_exceptions: dict[str, dict]
) -> None:
    """운영 코드가 부르지 않는 모듈은 `config/module_wiring.json` 에 사유와 함께 있어야 한다."""
    undeclared = []
    for name in graph.unwired():
        path = graph.paths[name]
        if path in declared_exceptions:
            continue
        text = graph.modules[name].read_text(encoding="utf-8", errors="replace")
        undeclared.append(
            f"{path} ({'implements: 있음' if IMPLEMENTS.search(text) else 'implements: 없음'})"
        )
    assert not undeclared, (
        "운영 코드가 부르지 않는 모듈이 장부에 없다. 배선하거나, "
        f"`config/module_wiring.json` 에 kind·reason(·wired_by)과 함께 적는다:\n  "
        + "\n  ".join(undeclared)
    )


def test_no_stale_exception(
    graph: WiringGraph, declared_exceptions: dict[str, dict]
) -> None:
    """배선된 모듈이 장부에 남아 있으면 장부가 거짓이다 — 지워야 한다."""
    unwired = {graph.paths[name] for name in graph.unwired()}
    stale = sorted(path for path in declared_exceptions if path not in unwired)
    assert not stale, (
        "이제 배선된(또는 사라진) 모듈이 예외로 남아 있다. "
        f"`config/module_wiring.json` 에서 지운다:\n  " + "\n  ".join(stale)
    )


def test_every_exception_carries_a_reason(
    graph: WiringGraph, ledger: dict, declared_exceptions: dict[str, dict]
) -> None:
    """사유 없는 예외는 같은 눈가림이 자리만 옮긴 것이다."""
    problems: list[str] = []
    for path, entry in sorted(declared_exceptions.items()):
        if not (PACKAGE_ROOT / path).is_file():
            problems.append(f"{path}: 그런 파일이 없다")
            continue
        if entry.get("kind") not in KNOWN_KINDS:
            problems.append(f"{path}: kind={entry.get('kind')!r} 는 `kinds` 에 없다")
        if len((entry.get("reason") or "").strip()) < 20:
            problems.append(f"{path}: reason 이 비었거나 한 마디뿐이다")
        if entry.get("kind") == "deferred" and len((entry.get("wired_by") or "").strip()) < 10:
            problems.append(f"{path}: deferred 인데 wired_by 가 없다 — 추적되지 않는다")
    assert not problems, "\n  ".join([""] + problems)
    assert set(ledger["kinds"]) == KNOWN_KINDS
    assert len(declared_exceptions) == len(ledger["exceptions"]), "같은 경로가 두 번 적혀 있다"


def test_contract_modules_name_a_requirement(graph: WiringGraph) -> None:
    """`contracts/` 의 계약 모듈은 어느 요구사항의 몫인지 적는다(§7).

    배선 검출과 같은 뿌리의 규칙이다 — 어느 요구사항도 가리키지 않는 계약은
    누가 왜 부르는지도 설명되지 않는다.
    """
    missing = [
        graph.paths[name]
        for name in graph.framework_modules()
        if name.startswith(f"{PACKAGE}.contracts.")
        and not graph.paths[name].endswith(GENERATED_SUFFIXES)
        and not IMPLEMENTS.search(
            graph.modules[name].read_text(encoding="utf-8", errors="replace")
        )
    ]
    assert not missing, f"implements: 줄이 없는 계약 모듈: {missing}"
