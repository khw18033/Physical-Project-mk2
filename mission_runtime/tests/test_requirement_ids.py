"""`implements:` 가 적는 요구사항 ID 가 실제로 있는 ID 인지 본다.

implements: AI-C-01 (이름의 주인을 한 곳에 둔다)
관련: CLAUDE.md §5(흡수·이관 이력), §7(요구사항 추적 규칙)
tests: 폐기 ID 를 적은 자리가 없는지 · 검사가 비어 돌지 않는지 · 흡수 이력을
       서술하는 문장은 건드리지 않는지

## 왜 이 시험이 생겼는가 (2026-11-04)

CLAUDE.md §5 가 못 박는다 — "비어 있는 과거 번호(AI-E-03, AI-B-07, AI-C-09/11/12/
14/17, AI-D 계열)는 **재사용하지 않는다** — 흡수·이관 이력이 있는 번호를 되쓰면
추적이 끊긴다."

그런데 `implements:` 에 그 번호들이 **86 곳** 남아 있었다. 되쓴 것이 아니라 흡수
**전에** 적은 것이 그대로 남은 것이지만 결과는 같다: 요구사항에서 코드로 거꾸로
찾을 때 `AI-C-05` 로 찾으면 `AI-C-11` 로 적힌 32 개 모듈이 **보이지 않는다**. §7 의
추적 규칙이 그 자리에서 깨진다.

가장 많았던 `AI-C-11`(선택 기능·의존성 격리 → `AI-C-05` 로 흡수)이 32 곳,
`AI-C-12`(인프라 제공자 추상화 → `AI-C-04`)가 18 곳이었다.

## 폐기 번호를 코드에 적는 이유가 하나 남는다

**흡수 이력을 서술하는 문장.** `decision/info_request.py` 가 "이 모듈은 원래 구
요구사항 AI-D-03 을 구현했었다" 를 적고 있고 그 문장의 요점이 바로 옛 번호다.
그런 줄은 고치지 않는다 — 그래서 이 검사는 `implements:`/`관련:` 선언만 보고,
이력을 서술하는 줄(`이관`·`흡수`·`구 AI-`·`옛 AI-`·`재사용`)은 건너뛴다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = PACKAGE_ROOT.parent / "CLAUDE.md"

#: CLAUDE.md §5 가 "재사용하지 않는다" 고 적은 번호들. 각 줄에 **무엇으로 흡수됐는지**
#: 를 함께 둔다 — 고치는 사람이 어디로 옮길지 이 표에서 읽는다.
RETIRED: dict[str, str] = {
    "AI-E-03": "AI-E-02",   # 구 AI-E-02 + AI-E-03 → 신 AI-E-02 (보정 lifecycle)
    "AI-B-07": "AI-B-05",   # 장애 복구·롤백 → 실행 기능 생명주기·장애 복구
    "AI-C-09": "AI-C-04",   # 선택형 외부·고비용 기능 연동 → 외부 기술·제공자 어댑터
    "AI-C-11": "AI-C-05",   # 선택 기능·의존성 격리 → 핵심·선택 기능 및 의존성 격리
    "AI-C-12": "AI-C-04",   # 인프라 제공자 추상화 → 외부 기술·제공자 어댑터
    "AI-C-14": "AI-C-06",   # 데이터 유형별 경로 분리 → 데이터 유형별 전송 경계
    "AI-C-17": "AI-C-04",   # 보안 오버레이 → AI-C-04 의 Security Provider 항목
    # AI-D 계열은 가시화로 이관됐고 **번호를 되쓰지 않는다**: 서브태스크 산출은
    # 2026-11-02 에 AI 로 돌아오면서 AI-B-14·AI-B-15 를 새로 받았고, AI-D-03 의
    # 실질 기능(추가 정보 요청)은 AI-S-05 다.
    "AI-D-01": "AI-B-14",
    "AI-D-02": "AI-B-14",
    "AI-D-03": "AI-S-05",
    "AI-D-04": "AI-B-14",
    # §5 의 "비어 있는 과거 번호(...)" 문장에는 **없지만** 같은 §5 가 "AI-R-03/04는
    # AI-R-02와 신규 AI-C-19로 흡수" 라고 적는다. 문장 하나를 정본으로 삼았다가
    # 놓쳤고, 아래 `_defined_requirement_ids` 기반 검사가 잡아 줬다.
    "AI-R-03": "AI-R-02",   # 위험 판단 결과·권고 출력 → AI-R-02
    "AI-R-04": "AI-S-05",   # 관측·분석 수준 조정 요청 → AI-S-05
}

#: 선언 줄. `implements:` 와 `관련:` 둘 다 요구사항을 가리키는 선언이다.
DECLARATION = re.compile(r"(implements:|관련:)")
#: 흡수 이력을 **서술하는** 줄 — 그 문장의 요점이 옛 번호다.
HISTORY = re.compile(r"이관|흡수|구 AI-|옛 AI-|재사용|retired|superseded")
ID = re.compile(r"AI-[A-Z]-\d{2}")

SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules"}


def _source_files() -> list[Path]:
    return sorted(
        p for p in PACKAGE_ROOT.rglob("*.py")
        if not SKIP_DIRS & set(p.relative_to(PACKAGE_ROOT).parts)
    )


def _declared_ids(path: Path) -> list[tuple[int, str]]:
    """선언 줄에 적힌 ID 들. `(줄번호, ID)`.

    선언은 여러 줄에 걸칠 수 있어서(`implements: A,\\n            B`) 선언 줄
    다음부터 ID 로 시작하는 들여쓴 줄까지를 같은 선언으로 본다.
    """
    out: list[tuple[int, str]] = []
    in_declaration = False
    for number, line in enumerate(path.read_text(encoding="utf-8",
                                                 errors="replace").splitlines(), 1):
        if DECLARATION.search(line):
            in_declaration = True
        elif in_declaration and not re.match(r"^\s*AI-[A-Z]-\d{2}", line):
            in_declaration = False
        if not in_declaration or HISTORY.search(line):
            continue
        out.extend((number, found) for found in ID.findall(line))
    return out


def _defined_requirement_ids() -> set[str] | None:
    """CLAUDE.md §5 가 `#### AI-X-NN` 표제로 **정의한** 요구사항들. 없으면 `None`.

    표제를 읽는 이유: 요구사항 정의서가 정본이고 이 파일이 그것을 베껴 적으면 두
    곳이 어긋난다(AI-C-01 과 같은 규칙).
    """
    if not CLAUDE_MD.is_file():
        return None
    text = CLAUDE_MD.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"^#### (AI-[A-Z]-\d{2})", text, re.M))


def test_claude_md_defines_the_number_of_requirements_it_claims():
    """§5 가 "61 개" 라고 적고 표제도 61 개인지. 어긋나면 **둘 중 하나가 낡았다.**"""
    defined = _defined_requirement_ids()
    if defined is None:
        pytest.skip("CLAUDE.md 는 공개 트리 밖이다")
    assert len(defined) == 61, (
        f"`#### AI-X-NN` 표제가 {len(defined)}개다. 요구사항이 늘거나 줄었으면 §5 의 "
        "개수 서술과 이 수를 함께 고친다"
    )


@pytest.fixture(scope="module")
def declarations() -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []
    for path in _source_files():
        found.extend((path, number, rid) for number, rid in _declared_ids(path))
    return found


def test_the_check_actually_reads_declarations(declarations):
    """선언을 하나도 못 읽으면 이 시험은 **비어 돌면서 통과한다.**"""
    assert len(declarations) > 300, (
        f"요구사항 선언을 {len(declarations)}개만 읽었다 — §0 의 표기가 바뀌었다면 "
        "DECLARATION 과 _declared_ids 를 함께 고쳐야 한다"
    )


def test_no_declaration_cites_an_id_that_is_not_a_requirement(declarations):
    """선언이 **CLAUDE.md 가 정의한 61 개 밖**의 ID 를 가리키지 않는지.

    위의 폐기 목록보다 강한 검사다 — 목록을 유지하지 않고도 폐기·오타·날조를 모두
    잡는다. 폐기 목록을 남겨 두는 이유는 다른 것이다: 걸린 ID 를 **어디로 옮길지**
    알려 주는 것(그래서 아래 메시지가 후속 ID 를 함께 낸다).

    실제로 이 검사가 폐기 목록이 놓친 둘을 더 잡았다. §5 의 "비어 있는 과거
    번호(...)" 문장은 AI-R-03·AI-R-04 를 **열거하지 않는데**(같은 §5 의 다른 문단이
    "AI-R-03/04는 AI-R-02와 신규 AI-C-19로 흡수" 라고 적는다), 그 둘이 선언에 네 곳
    남아 있었다. 문장 하나를 정본으로 삼으면 그 문장이 빠뜨린 것은 영원히 안 보인다.
    """
    defined = _defined_requirement_ids()
    if defined is None:
        pytest.skip("CLAUDE.md 는 공개 트리 밖이다 — 그 배치에서는 이 확인만 skip")

    stray = []
    for path, number, rid in declarations:
        if rid in defined:
            continue
        where = f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{number}"
        hint = (f"{RETIRED[rid]} 로 적는다" if rid in RETIRED
                else "CLAUDE.md §5 에 그런 요구사항이 없다")
        stray.append(f"{where} — {rid}: {hint}")

    assert not stray, (
        "CLAUDE.md 가 정의하지 않은 요구사항 ID 로 선언한 자리가 있다. 흡수 "
        "**이력을 서술하는** 문장이면 그 줄에 사유(`흡수`·`구 AI-` 등)를 적으면 "
        f"검사에서 빠진다:\n  " + "\n  ".join(stray)
    )


def test_no_declaration_cites_a_retired_requirement_id(declarations):
    """폐기된 번호로 선언하면 **요구사항에서 코드를 거꾸로 찾을 수 없다**(§7).

    `AI-C-05` 로 찾는 사람에게 `AI-C-11` 로 적힌 모듈은 보이지 않는다. 되쓴 것이
    아니라 흡수 전에 적은 것이 남은 것이어도 결과는 같다.
    """
    stale = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{number} — "
        f"{rid} 는 폐기됐다, {RETIRED[rid]} 로 적는다"
        for path, number, rid in declarations if rid in RETIRED
    ]

    assert not stale, (
        "폐기된 요구사항 ID 로 선언한 자리가 있다(CLAUDE.md §5). 위 표의 후속 "
        "ID 로 바꾼다 — 흡수 **이력을 서술하는** 문장이면 그 줄에 사유를 적으면 "
        f"검사에서 빠진다:\n  " + "\n  ".join(stale)
    )


@pytest.mark.skipif(not CLAUDE_MD.is_file(),
                    reason="CLAUDE.md 는 공개 트리 밖이다 — 그 배치에서는 이 확인만 skip")
def test_the_retired_list_matches_what_claude_md_says():
    """표를 **코드에만** 두면 CLAUDE.md 가 바뀔 때 조용히 어긋난다.

    §5 가 열거한 문장에서 번호를 뽑아 위 표와 맞춘다. 새 번호가 폐기되는 날 이
    시험이 먼저 깨지고, 그러면 표를 고치는 것이 할 일로 남는다.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8", errors="replace")
    sentence = re.search(r"비어 있는 과거 번호\(([^)]+)\)", text)
    assert sentence, "§5 의 '비어 있는 과거 번호(...)' 문장을 찾지 못했다"

    listed = set()
    for token in re.findall(r"AI-[A-Z]-\d{2}(?:/\d{2})*", sentence.group(1)):
        head, *rest = token.split("/")
        listed.add(head)
        prefix = head.rsplit("-", 1)[0]
        listed.update(f"{prefix}-{tail}" for tail in rest)

    missing = sorted(listed - set(RETIRED))
    assert not missing, (
        f"CLAUDE.md §5 가 폐기로 적은 번호가 이 파일의 표에 없다: {missing}. "
        "표에 후속 ID 와 함께 추가한다"
    )
