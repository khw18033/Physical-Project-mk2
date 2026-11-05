"""`파일.py::이름` 꼴 주석 참조가 실제로 가리키는 것이 있는지 본다.

implements: AI-C-01 (공통 데이터 규약 — 이름의 주인을 한 곳에 둔다)
관련: §0 코드 작성 규약(주석이 모듈·식별자를 가리키는 스타일), AI-L-08 (역추적)
tests: 깨진 참조가 하나도 없는지 · 참조가 실제로 세어지는지(검사가 비어 돌지 않는지)

## 왜 이 시험이 생겼는가 (2026-11-04)

`registry/onboarding.py` 의 머리말이 "어긋남은 `runtime/environment_profile.py::
report_attachment_conflicts` 가 보고한다" 고 적고 있었고 **그 함수는 없었다.**
이름이 저장소 전체에서 그 docstring 한 줄에만 있었다.

`config/module_wiring.json` 이 잡는 결함("모듈은 있는데 아무도 안 부른다")과 같은
종류인데 **장부가 볼 수 없는 자리**에 있다. 이 저장소의 주석은 설계 근거를 모듈
이름으로 가리키는 스타일이라(§0) 그런 참조가 140 개를 넘고, 하나가 썩으면 다음
사람이 없는 함수를 찾아 헤맨다. 사람이 알아채는 일이었던 것을 시험으로 바꾼다.

같은 날 이 검사로 둘을 더 찾았다 — `contracts/profile.py` 가 자기가 정의한 클래스의
메서드를 **다른 파일에서** 찾고 있었고(실제 이름은 모듈 함수
`thresholds_from_transition_policy`), `common/coordinates.py` 가 공통 사전의 없는
칸(`COORDINATE_REASONS`)을 등록처로 적고 있었다(실제는 `FRAME_REFUSAL_REASON`).

## 느슨하게 보는 자리

거짓 양성이 하나라도 나면 이 시험은 꺼진다. 그래서 다음은 **있는 것으로 센다**:

- 인스턴스 속성(`self.x = ...`). `wire_gaps` 가 그 경우이고, 모듈 최상위에 없지만
  분명히 존재한다.
- `import` 로 그 모듈에 들어온 이름. 그 파일을 읽는 사람에게는 보이는 이름이다.
- 점 이름은 **머리만** 본다(`A.b.c` → `A`). 속성 체인까지 좇으면 타입 추론이 되고,
  이 시험의 목적은 "가리키는 것이 아예 없는" 경우를 잡는 것이다.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parent

#: `경로/파일.py::이름` 꼴. 이 저장소가 설계 근거를 가리킬 때 쓰는 표기다.
REFERENCE = re.compile(r"([A-Za-z0-9_./-]+\.py)::([A-Za-z_][A-Za-z0-9_.]*)")
#: §7 이 요구하는 `tests:` 줄. 그 줄이 가리키는 시험 파일이 없으면 "이 요구사항은
#: 이 시험이 보장한다" 가 **확인할 수 없는 주장**이 된다.
TESTS_LINE = re.compile(r"^\s*tests:\s*(.+(?:\n\s{4,}\S[^\n]*)*)", re.M)
TEST_FILE = re.compile(r"tests/[A-Za-z0-9_./-]+\.py")

#: 검사에서 빼는 자리. **이름이 아니라 사유로 적는다.**
SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules"}


def _source_files() -> list[Path]:
    return sorted(
        p for p in PACKAGE_ROOT.rglob("*.py")
        if not SKIP_DIRS & set(p.relative_to(PACKAGE_ROOT).parts)
    )


def _defined_names(path: Path) -> frozenset[str] | None:
    """그 파일을 읽는 사람에게 **보이는** 이름 전부. 파싱 실패는 `None`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError):
        return None
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.add(target.id)
                # 인스턴스 속성도 존재하는 이름이다 — `self.wire_gaps` 가 그 경우다.
                elif isinstance(target, ast.Attribute):
                    out.add(target.attr)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                out.add(node.target.id)
            elif isinstance(node.target, ast.Attribute):
                out.add(node.target.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                out.add(alias.asname or alias.name.split(".")[0])
    return frozenset(out)


def _resolve(rel: str, referrer: Path) -> Path | None:
    """주석에 적힌 경로를 실제 파일로. 형제 파일 표기도 받는다.

    같은 디렉터리의 파일을 `open_vocabulary.py` 처럼 짧게 적는 자리가 많고, 그것은
    사람이 읽기에 더 분명하므로 표기를 바꾸라고 하지 않는다 — 검사가 맞춘다.
    """
    for base in (PACKAGE_ROOT, REPO_ROOT, referrer.parent):
        candidate = base / rel
        if candidate.is_file():
            return candidate
    # `edge/foo.py` 로 적었는데 실제로는 `perception/foo.py` 인 경우까지 좇지는
    # 않는다 — 그것은 **틀린 참조**이고 이 시험이 잡아야 하는 쪽이다.
    return None


def _prose(path: Path) -> str:
    """주석 + docstring 만. **임의 문자열은 보지 않는다.**

    이유: `tests/test_execution_profile.py` 는 `evidence_refs=("…py::E",)` 처럼
    pytest 노드 id 모양의 **시험 데이터**를 들고 있다. 그것은 설계 근거를 가리키는
    주석이 아니므로 깨진 참조로 세면 거짓 양성이고, 거짓 양성이 하나라도 나오면
    이 시험은 꺼진다. 검사는 자기가 검사한다고 적은 것만 봐야 한다.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    chunks: list[str] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                chunks.append(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return "\n".join(chunks)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                chunks.append(doc)
    return "\n".join(chunks)


@pytest.fixture(scope="module")
def references() -> list[tuple[Path, str, str]]:
    found: list[tuple[Path, str, str]] = []
    for path in _source_files():
        for rel, name in REFERENCE.findall(_prose(path)):
            found.append((path, rel, name))
    return found


def test_the_check_actually_finds_references(references):
    """참조가 0 개면 이 시험은 **비어 돌면서 통과한다.** 그쪽이 더 나쁘다."""
    assert len(references) > 100, (
        f"`파일.py::이름` 참조가 {len(references)}개뿐이다 — 표기가 바뀌었다면 "
        "REFERENCE 를 고쳐야 하고, 고치지 않으면 이 검사는 아무것도 보지 않는다"
    )


def test_every_doc_reference_points_at_something_that_exists(references):
    """주석이 가리키는 모듈·식별자가 실제로 있는가.

    깨진 참조는 **읽는 사람을 없는 함수로 보낸다.** `registry/onboarding.py` 가 없는
    `report_attachment_conflicts` 를 가리키고 있었고, 그 함수가 하기로 되어 있던
    일(부착 선언과 역할 태그의 어긋남 보고)은 아무도 하지 않았다.
    """
    cache: dict[Path, frozenset[str] | None] = {}
    broken: list[str] = []
    for referrer, rel, name in references:
        where = referrer.relative_to(PACKAGE_ROOT).as_posix()
        target = _resolve(rel, referrer)
        if target is None:
            broken.append(f"{where}: `{rel}::{name}` — 그 파일이 없다")
            continue
        if target not in cache:
            cache[target] = _defined_names(target)
        names = cache[target]
        if names is None:
            continue            # 파싱되지 않는 파일은 **다른 시험의 실패**다
        head = name.split(".")[0]
        if head not in names:
            broken.append(
                f"{where}: `{rel}::{name}` — 그 파일에 `{head}` 가 없다")

    assert not broken, (
        "주석이 없는 것을 가리킨다. 참조를 고치거나, 가리키는 것을 만든다:\n  "
        + "\n  ".join(sorted(broken))
    )


def test_every_tests_line_names_a_test_file_that_exists():
    """§7 의 `tests:` 줄이 **없는 시험 파일**을 가리키지 않는지.

    `implements:` 가 "이 코드가 그 요구사항을 구현한다" 이면 `tests:` 는 "그것을 이
    시험이 보장한다" 다. 가리키는 파일이 없으면 뒤쪽 주장은 확인할 수 없고, 추적표가
    그 모듈을 근거로 완료를 적고 있으면 **확인할 수 없는 완료**가 된다.

    실제로 걸렸다: `risk/adjustment.py` 가 `tests/test_edge_perception_loop.py` 를
    가리켰는데 같은 작업에서 만들어진 파일 이름은 `tests/test_perception_loop.py`
    였다. 이름을 한 글자 틀린 것이 아니라, 모듈이 **예정된** 시험을 가리키고 있었다.
    """
    broken: list[str] = []
    for path in _source_files():
        if "tests" in path.relative_to(PACKAGE_ROOT).parts:
            continue        # 시험 파일 자신의 `tests:` 줄은 자기 설명이다
        for match in TESTS_LINE.finditer(_prose(path)):
            for ref in TEST_FILE.findall(match.group(1)):
                if not (PACKAGE_ROOT / ref).is_file():
                    broken.append(
                        f"{path.relative_to(PACKAGE_ROOT).as_posix()}: "
                        f"`tests: {ref}` — 그런 시험 파일이 없다")

    assert not broken, (
        "`tests:` 줄이 없는 파일을 가리킨다. 시험을 만들거나, 줄을 실제 파일로 "
        f"고친다:\n  " + "\n  ".join(sorted(set(broken)))
    )

