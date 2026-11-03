"""implements: AI-C-15
tests: 공개 문서의 상대 링크가 공개 트리 안에서 실제로 열리는가

왜 시험으로 두는가
------------------
`docs/` 는 이 저장소를 처음 읽는 사람이 가장 먼저 여는 곳이고, 공개되는 것은
`mission_runtime/` 뿐이다. 그래서 문서가 `internal/`(내부 기록)이나 개인 노트 보관소
같은 **공개되지 않는 자리**를 링크하면 읽는 사람에게는 그냥 깨진 링크이고, 더 나쁘게는
"접근할 수 없는 근거"만 남는다. 사람이 눈으로 검사하면 다음에 문서를 늘릴 때 또
깨지므로, 깨지는 순간 CI 가 알려 주게 둔다.

실제로 한 번 깨져 있었다: 추적표가 `internal/docs-dev/` 로 옮겨간 뒤에도 세 문서가
예전 자리를 링크하고 있었고, 기술 경계 문서 11곳이 개인 Obsidian 노트를 가리켰다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
DOC_DIRS = ("docs",)

#: `[글자](링크)` 중 링크만. 앵커(`#...`)와 질의는 떼고 본다.
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

#: 바깥을 가리키는 것은 시험 대상이 아니다 — 그것은 깨진 링크가 아니라 인용이다.
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for name in DOC_DIRS:
        files.extend(sorted((PACKAGE_DIR / name).rglob("*.md")))
    files.append(PACKAGE_DIR / "README.md")
    return [f for f in files if f.is_file()]


def _relative_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out = []
    for target in _LINK.findall(text):
        if target.startswith(_EXTERNAL_PREFIXES):
            continue
        out.append(target.split("#", 1)[0].split("?", 1)[0])
    return [t for t in out if t]


def test_there_are_documents_to_check():
    """시험이 아무 파일도 못 찾고 통과하는 상태를 막는다."""
    assert len(_markdown_files()) >= 4


@pytest.mark.parametrize("doc", _markdown_files(), ids=lambda p: p.name)
def test_every_relative_link_opens_inside_the_published_tree(doc: Path):
    broken = []
    for target in _relative_links(doc):
        resolved = (doc.parent / target).resolve()
        if not resolved.exists():
            broken.append(target)
            continue
        # 존재하더라도 공개 범위 밖이면 읽는 사람에게는 없는 것과 같다.
        if PACKAGE_DIR.resolve() not in resolved.parents and resolved != PACKAGE_DIR.resolve():
            broken.append(f"{target} (공개 범위 밖)")

    assert broken == [], f"{doc.relative_to(PACKAGE_DIR)} 의 링크가 열리지 않는다: {broken}"
