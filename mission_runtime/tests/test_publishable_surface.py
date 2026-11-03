"""implements: AI-B-02, AI-C-16
tests: secret-shaped literals in the published file list, developer-machine paths,
       content from the never-published trees, tracked build/run artefacts

공개 범위는 `.gitignore` 가 아니라 **푸시 범위**가 정한다 — `mission_runtime/` 만
올린다(CLAUDE.md §0). 그래서 이 파일이 보는 것은 작업 트리가 아니라
`git ls-files mission_runtime` 다. 작업 트리를 훑으면 커밋되지 않은 현장 설정과
가중치까지 세면서 정작 **추적되고 있는** 한 줄을 놓친다.

AI-B-02 는 "자격증명·비밀정보를 이미지에 포함해서는 안 된다"고 적는다. 이미지는
`COPY . .` 로 이 목록을 그대로 담으므로, 목록이 깨끗한지 보는 것이 이미지가
깨끗한지 보는 것보다 먼저다.

## 왜 `_PENDING_*` 가 있나

지금 트리에는 이미 들어가 있는 결손이 있다(internal/reports/ 의 공개 준비 점검 가
파일·줄·고칠 내용을 적는다). 그것을 기다리며 시험을 끄면 **새** 결손도 함께
통과하므로, 아는 자리만 적어 두고 그 밖에서 하나라도 나오면 실패하게 둔다.
비교를 부분집합으로 두는 이유는 자리를 고치는 쪽이 이 파일을 함께 고치지
않아도 시험이 깨지지 않게 하기 위해서다 — 목록을 줄이는 일은
그 점검 보고서의 체크리스트가 가진다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_DIR.parent

#: 공개 푸시 대상. 이 접두사 밖은 백업 저장소에만 남는다(CLAUDE.md §0).
PUBLISHED_PREFIX = "mission_runtime/"

#: 절대 공개하지 않는 트리. 여기 것이 공개 목록에 섞여 있으면 그 자체로 사고다 —
#: `internal/` 은 내부 보고·조달, `local/` 은 데이터셋·가중치·운영자 장부다.
#: 미발표 연구가 사는 트리의 **이름**은 그 자체가 단서이므로 공개 범위 밖의
#: 목록에서 읽는다(`UNPUBLISHED_SIGNATURE_LIST`).
NEVER_PUBLISHED_TREES = ("internal/", "local/")

#: 미발표 연구를 특정하는 어휘를 적어 둔 자리. **이 파일에 적지 않는다** —
#: 이 시험은 공개 트리에 있고, 그런 낱말들이 한자리에 모여 있는 것 자체가 그
#: 연구가 무엇을 하는지 말한다. 파일 이동이 아니라 어휘를 보는 판단은 그대로
#: 두되(주석 한 줄로 착상이 드러나는 쪽이 코드가 복사되는 쪽보다 흔하다),
#: 그 어휘는 공개 범위 밖에 둔다.
#:
#: 목록이 없는 체크아웃에서는 이 검사만 skip 되고 나머지는 그대로 돈다. 일반적인
#: ReID 서술(AI-S-02 가 선택 capability 로 요구하는 것)은 우리 요구사항의 말이므로
#: 애초에 목록에 넣지 않는다.
UNPUBLISHED_SIGNATURE_LIST = (
    REPO_ROOT / "internal" / "docs-dev" / "ai" / "unpublished-signatures.json")


def _unpublished(key: str) -> tuple[str, ...]:
    import json

    if not UNPUBLISHED_SIGNATURE_LIST.exists():
        return ()
    body = json.loads(UNPUBLISHED_SIGNATURE_LIST.read_text(encoding="utf-8"))
    return tuple(body.get(key, ()))

#: 형태만으로 비밀이라고 말할 수 있는 것들. "password" 같은 낱말은 넣지 않는다 —
#: 요구사항 인용과 거절 사유 토큰에 숱하게 나오므로 거짓 경보만 만들고, 그러면
#: 시험이 꺼진다. 고엔트로피 접두사가 붙은 실제 발급 형식만 본다.
SECRET_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PEM private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("kubeconfig embedded key", re.compile(r"^\s*client-key-data:\s*\S", re.MULTILINE)),
)

#: 이 기계의 홈 경로. 코드 기본값이나 데이터에 박히면 남의 기계에서는 존재하지
#: 않는 자리를 가리킨다. 자리 표시자로 쓰는 이름과 장치 기본 계정은 뺀다 —
#: `/home/pi` 는 라즈베리파이의 실제 배포 경로이고 개발자 유출이 아니다.
HOME_PATH = re.compile(r"/home/([a-z][a-z0-9_.-]{1,31})/")
HOME_PATH_PLACEHOLDERS = frozenset({
    "user", "username", "youruser", "your-user", "me", "someone",
    "pi", "ubuntu", "operator", "edge", "device",
})

#: 개인 메일 주소. 공개 저장소에 남으면 수집 대상이 된다. 프로젝트 연락처나
#: 예시 도메인(RFC 2606)은 유출이 아니다.
PERSONAL_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@(gmail|naver|hanmail|daum|outlook|hotmail|yahoo|icloud)\.[A-Za-z.]{2,}\b")

#: 생성물·기계 상태는 추적하지 않는다. 추적되면 체크아웃마다 충돌하고
#: 이미지에도 그대로 들어간다.
GENERATED_PATH_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bytecode cache", re.compile(r"(^|/)__pycache__/|\.py[co]$")),
    ("packaging metadata", re.compile(r"\.egg-info(/|$)|(^|/)\.eggs/")),
    ("pytest cache", re.compile(r"(^|/)\.pytest_cache/")),
    ("node dependency tree", re.compile(r"(^|/)node_modules/")),
    ("JS build output", re.compile(r"(^|/)(dist|\.vite)/")),
    ("model weights", re.compile(r"\.(onnx|pt|pth|safetensors|tflite|engine|caffemodel)$")),
    ("virtualenv", re.compile(r"(^|/)\.venv/")),
)

#: 아직 고치지 못한 자리. 각 항목의 파일·줄·고칠 내용은
#: internal/reports/ 의 공개 준비 점검 에 있다. 이 목록 **밖**에서 나오면 실패한다.
_PENDING_HOME_PATHS = frozenset({
    "mission_runtime/config/device_appearance_classes.example.json",
    "mission_runtime/execution/robot_adapter.py",
    "mission_runtime/providers/quadruped_sdk_robot.py",
})
_PENDING_PERSONAL_EMAILS = frozenset({
    "mission_runtime/tools/appearance/fetch_references.py",
})
#: 비어 있는 것이 정상이다. 둘 다 2026-11-03 에 추적에서 뺐다 — collector 가
#: 바인드 마운트로 덧붙이고 지표 덤프는 돌 때마다 다시 재므로, 추적하면 실행
#: 노이즈가 커밋에 섞인다. `.gitignore` 가 자리를 막는다.
_PENDING_RUN_ARTEFACTS: frozenset[str] = frozenset()

#: 실행 중 산출돼 추적되면 안 되는 자리. 경로 규칙으로는 못 잡는다 —
#: 확장자가 평범한 `.json` 이고 디렉터리 이름만 다르다.
RUN_ARTEFACT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("collector output", re.compile(r"/artifacts/.*\.json$")),
    ("measured indicator dump", re.compile(r"(^|/)reports/.*\.json$")),
)


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(REPO_ROOT), *args),
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout


@pytest.fixture(scope="module")
def published_paths() -> list[str]:
    """git 이 실제로 올릴 경로. 작업 트리가 아니라 색인을 묻는다."""
    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("git 색인을 읽을 수 없다 — 공개 목록이 아니라 체크아웃만 있다")
    paths = [line for line in _git("ls-files", PUBLISHED_PREFIX.rstrip("/")).splitlines() if line]
    assert paths, "공개 목록이 비어 있다 — 경로 접두사가 바뀌었는지 본다"
    return paths


@pytest.fixture(scope="module")
def published_texts(published_paths: list[str]) -> list[tuple[str, str]]:
    """공개 목록의 텍스트 내용. 이진 파일은 NUL 로 걸러 건너뛴다."""
    out: list[tuple[str, str]] = []
    for rel in published_paths:
        blob = (REPO_ROOT / rel).read_bytes() if (REPO_ROOT / rel).is_file() else b""
        if b"\x00" in blob[:8192]:
            continue
        out.append((rel, blob.decode("utf-8", errors="replace")))
    return out


def _hits(texts, pattern: re.Pattern[str], *, accept=lambda m: True) -> dict[str, int]:
    """패턴에 걸린 파일 → 첫 줄 번호."""
    found: dict[str, int] = {}
    for rel, text in texts:
        for match in pattern.finditer(text):
            if accept(match):
                found[rel] = text.count("\n", 0, match.start()) + 1
                break
    return found


# --- 비밀 ------------------------------------------------------------------

@pytest.mark.parametrize("label,pattern", SECRET_SHAPES, ids=[s[0] for s in SECRET_SHAPES])
def test_no_secret_shaped_literal_is_published(published_texts, label, pattern):
    """AI-B-02: 자격증명은 저장소에도, 그것을 그대로 담는 이미지에도 없어야 한다."""
    assert not _hits(published_texts, pattern), (
        f"{label} 형태가 공개 목록에 있다. 지우는 것으로 끝나지 않는다 — "
        f"이력에 남으므로 해당 비밀을 폐기·재발급한다: {_hits(published_texts, pattern)}"
    )


def test_the_credential_example_carries_no_real_secret(published_texts):
    """설정 예시는 **자리**만 보여 준다. 실제 값이 들어오면 예시가 비밀이 된다."""
    example = dict(published_texts).get("mission_runtime/config/device_credentials.example.json")
    assert example is not None, "자격증명 예시가 공개 목록에서 사라졌다"
    assert '"secret": "REPLACE_ME"' in example, (
        "예시의 secret 이 자리 표시자가 아니다 — 실제 값이 커밋됐는지 본다"
    )


# --- 이 기계의 자취 --------------------------------------------------------

def test_no_new_developer_home_path_is_published(published_texts):
    """남의 기계에 없는 경로는 기본값이 될 수 없다. 아는 자리 밖에서 나오면 실패다."""
    def not_a_placeholder(match: re.Match[str]) -> bool:
        return match.group(1) not in HOME_PATH_PLACEHOLDERS

    found = _hits(published_texts, HOME_PATH, accept=not_a_placeholder)
    new = {k: v for k, v in found.items() if k not in _PENDING_HOME_PATHS}
    assert not new, (
        "개발 기계의 홈 경로가 새로 들어왔다. 상대 경로나 설정값으로 바꾼다: " + repr(new)
    )


def test_no_new_personal_email_is_published(published_texts):
    """공개 저장소의 개인 주소는 수집 대상이 된다 — 프로젝트 연락처를 쓴다."""
    found = _hits(published_texts, PERSONAL_EMAIL)
    new = {k: v for k, v in found.items() if k not in _PENDING_PERSONAL_EMAILS}
    assert not new, "개인 메일 주소가 새로 들어왔다: " + repr(new)


# --- 공개하지 않는 트리 ----------------------------------------------------

def test_no_path_from_a_never_published_tree_is_in_the_list(published_paths):
    """`internal/` `local/` 과 비공개 목록이 적은 트리는 백업에만 남는다(CLAUDE.md §0)."""
    trees = (*NEVER_PUBLISHED_TREES, *_unpublished("never_published_trees"))
    strays = [p for p in published_paths
              if any(f"/{tree}" in f"/{p}" for tree in trees)]
    assert not strays, "공개 목록에 비공개 트리의 경로가 있다: " + repr(strays)


def test_no_unpublished_research_signature_leaks_into_the_published_tree(published_texts):
    """다른 사람의 미발표 연구는 코드뿐 아니라 **착상**도 새면 안 된다.

    주석 한 줄이 접근법을 알려 주는 쪽이 파일이 복사되는 쪽보다 흔하므로
    파일 이동이 아니라 그 연구를 특정하는 어휘를 본다. 어휘 자체는 공개 범위
    밖에 있고(`UNPUBLISHED_SIGNATURE_LIST`), 그래서 어휘를 하나씩 매개변수로
    펼치지 않는다 — 펼치면 **시험 이름에 그 낱말이 찍힌다.**
    """
    signatures = _unpublished("signatures")
    if not signatures:
        pytest.skip("비공개 어휘 목록이 이 체크아웃에 없다 — 공개 트리만 있는 상태다")
    found: dict[str, dict[str, int]] = {}
    for index, signature in enumerate(signatures):
        needle = signature.lower()
        hits = {rel: text.lower().count(needle) for rel, text in published_texts
                if needle in text.lower()}
        if hits:
            # 실패 메시지에도 낱말을 적지 않는다. 자리와 번호만 적으면 목록을
            # 가진 사람은 찾을 수 있고, 로그만 본 사람에게는 새지 않는다.
            found[f"signature[{index}]"] = hits
    assert not found, (
        "미발표 연구를 특정하는 어휘가 공개 목록에 있다 — 번호는 "
        f"{UNPUBLISHED_SIGNATURE_LIST.name} 의 순서다: {found}")


# --- 생성물·기계 상태 ------------------------------------------------------

@pytest.mark.parametrize("label,pattern", GENERATED_PATH_RULES,
                         ids=[r[0] for r in GENERATED_PATH_RULES])
def test_no_generated_artefact_is_tracked(published_paths, label, pattern):
    """생성물을 추적하면 체크아웃마다 어긋나고 이미지에도 그대로 들어간다."""
    tracked = [p for p in published_paths if pattern.search(p)]
    assert not tracked, f"{label} 가 추적되고 있다: {tracked}"


@pytest.mark.parametrize("label,pattern", RUN_ARTEFACT_RULES,
                         ids=[r[0] for r in RUN_ARTEFACT_RULES])
def test_no_new_run_artefact_is_tracked(published_paths, label, pattern):
    """실행하면 다시 쓰이는 파일은 선언이 아니라 **상태**다 — 추적하지 않는다."""
    tracked = [p for p in published_paths if pattern.search(p)]
    new = [p for p in tracked if p not in _PENDING_RUN_ARTEFACTS]
    assert not new, f"{label} 가 새로 추적되고 있다: {new}"


# --- 이미지 경계 -----------------------------------------------------------

def test_dockerignore_excludes_every_never_published_tree():
    """이미지는 `COPY . .` 다. 빌드 컨텍스트에서 빼는 자리는 여기 한 곳뿐이므로
    비공개 트리와 캐시가 전부 적혀 있어야 한다(AI-B-02)."""
    ignore = (PACKAGE_DIR / ".dockerignore").read_text(encoding="utf-8")
    lines = {line.strip() for line in ignore.splitlines()
             if line.strip() and not line.startswith("#")}
    for required in ("local", "internal", ".venv", ".git", "reports",
                     "**/__pycache__", "third_party/*/node_modules"):
        assert required in lines, f".dockerignore 에 {required!r} 가 없다"


def test_dockerignore_keeps_real_credential_files_out_of_the_build_context():
    """예시 파일은 운영자에게 `config/device_credentials.json` 을 **같은 자리에**
    만들라고 적는다. `COPY . .` 는 그것을 이미지에 넣으므로, 만들어지기 전에
    빼 둔다 — 비밀이 이미지에 들어간 뒤에 알아차리는 일이 없어야 한다(AI-B-02)."""
    ignore = (PACKAGE_DIR / ".dockerignore").read_text(encoding="utf-8")
    lines = {line.strip() for line in ignore.splitlines() if line.strip()}
    assert "config/*credentials*.json" in lines
    assert "!config/*.example.json" in lines, (
        "예시까지 빼면 시험이 읽는 설정이 이미지에서 사라진다"
    )
