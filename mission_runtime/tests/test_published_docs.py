"""implements: AI-C-15
tests: 공개 문서의 상대 링크가 공개 트리 안에서 실제로 열리는가,
       그리고 README 의 설치 자가 점검 서술이 `tools/preflight.py` 와 어긋나지 않는가

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


# ── README 가 자가 점검과 어긋나지 않게 ────────────────────────────────────
#
# README 의 「이 기계에서 무엇이 되고 무엇이 안 되는가」 절은 `tools/preflight.py` 가
# 실제로 내는 것을 설명한다. 둘 중 하나만 바뀌면 받는 사람은 **설명되지 않은 줄**이나
# **없는 줄의 설명**을 읽는다. 그래서 어긋남을 눈이 아니라 시험이 잡는다.
#
# 수(數)는 기계마다 다르므로 고정하지 않는다 — 고정하는 것은 **어휘와 모양**이다.


def _readme() -> str:
    return (PACKAGE_DIR / "README.md").read_text(encoding="utf-8")


def _preflight():
    """`tools/preflight.py` 는 패키지 모듈이 아니라 도구다 — 그 자리에서 읽는다."""
    import sys

    tools = str(PACKAGE_DIR / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import preflight  # noqa: PLC0415

    return preflight


def test_the_readme_explains_every_section_the_self_check_reports():
    """설명되지 않은 절이 생기면 받는 쪽이 그 줄을 해석할 근거가 없다."""
    readme = _readme()

    missing = [section["title"] for section in _preflight().report()["sections"]
               if section["title"].split("—")[0].strip() not in readme]

    assert missing == [], f"README 가 설명하지 않는 자가 점검 절: {missing}"


def test_the_readme_legend_matches_the_marks_the_renderer_prints():
    """표 왼쪽 칸이 화면에 찍히는 기호와 달라지면 범례가 거짓이 된다."""
    readme = _readme()

    for status, mark in _preflight()._MARK.items():
        assert f"`[{mark}]`" in readme, f"{status} 의 기호 [{mark}] 가 README 범례에 없다"


def test_the_readme_quotes_the_summary_line_in_the_shape_the_tool_prints():
    """세 수를 한 줄에 **따로** 적는 모양이 요점이다 — 합치면 "선택 두 개 꺼짐"과
    "핵심이 막힘"이 같아진다(AI-C-05). 수는 기계마다 다르므로 모양만 고정한다."""
    preflight = _preflight()
    rendered = preflight.render(preflight.report())
    printed = next(line for line in rendered.splitlines() if line.startswith("정상 "))

    quoted = re.findall(r"정상 \d+ · 축소 \d+ · 막힘 \d+", _readme())

    assert quoted, "README 가 요약 줄을 인용하지 않는다"
    assert re.sub(r"\d+", "N", quoted[0]) == re.sub(r"\d+", "N", printed)


def test_the_readme_names_the_supported_way_to_decline_the_accelerator():
    """숨기는 쪽(`CUDA_VISIBLE_DEVICES=""`)은 **예외 없이 틀린 값**을 낸다. 변수
    이름이 바뀌었는데 README 가 옛 이름을 들고 있으면 문서가 함정을 권한다."""
    from mission_runtime.ondevice.rpn_propose import NO_GPU_ENV

    readme = _readme()

    assert NO_GPU_ENV in readme, "가속기를 거절하는 지원된 길이 README 에 없다"
    assert "CUDA_VISIBLE_DEVICES" in readme, "함정을 이름으로 적어 둬야 피할 수 있다"


def test_the_readme_carries_the_licence_fact_the_self_check_warns_about():
    """라이센스는 받는 쪽의 선택이고, 설치 시점과 README 둘 다 그것을 알 자리다."""
    row = next(c for c in _preflight()._optional().checks if "AGPL" in c.name)

    assert "AGPL-3.0" in row.name
    assert "AGPL-3.0" in _readme(), "자가 점검이 경고하는 라이센스 사실이 README 에 없다"
