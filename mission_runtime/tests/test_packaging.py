"""낯선 사람이 이 패키지만 받았을 때 그것이 혼자 설 수 있는가.

implements: AI-B-02 (실행환경 패키징·재현성), AI-C-16 (폐쇄망 배포 경계),
            AI-C-05 (선택 조건의 부재는 장애가 아니다)
tests: 선언된 패키지 목록의 완전성, 설치 배포물의 데이터 포함 여부,
       쓰기 가능한 상태의 자리, 자산 뿌리 부재 시의 축소, 실행 코드의 절대경로 부재

## 왜 시험이 필요한가

이 저장소는 `mission_runtime/` 만 공개한다. 그런데 개발은 그 **옆에** `local/`(자산)과
`internal/`(내부 기록)이 있는 배치에서 한다. 그래서 "패키지 바깥을 집는 코드"가
개발 중에는 전부 멀쩡하게 보이고, 공개본에서만 깨진다. 눈으로는 구분되지 않는다 —
개발 배치에서 돌려 보는 것으로는 절대 드러나지 않기 때문이다.

여기 있는 시험은 그 차이를 코드로 고정한다. 실제로 clone 해서 돌려 보는 실험을
대신하지는 못하지만, 한 번 고친 것이 다시 돌아오는 것은 막는다.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tokenize
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
PYPROJECT = PACKAGE_DIR / "pyproject.toml"
MANIFEST = PACKAGE_DIR / "MANIFEST.in"

#: 설치본에서도 반드시 손에 쥐어야 하는 데이터 트리. 코드만 있어도 못 돌고 이것만
#: 있어도 못 돈다 — 계약·프로파일·설정은 코드의 일부다.
REQUIRED_DATA_DIRS = ("schemas", "profiles", "config", "specs")

tomllib = pytest.importorskip("tomllib", reason="pyproject 를 읽으려면 tomllib(>=3.11) 가 필요하다")


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 선언된 패키지 목록
# ---------------------------------------------------------------------------


def test_every_module_directory_is_declared_as_a_package(pyproject):
    """`packages` 는 손으로 적는 목록이다 — 그래서 새 서브패키지를 만들고 한 줄
    적는 것을 잊으면, 개발 트리에서는 import 되고 설치본에서만 사라진다.

    자동 탐색에 맡길 수 없는 이유는 pyproject 주석에 있다(프로젝트 루트가 패키지
    루트라서 탐색이 루트를 보지 못한다). 맡길 수 없으면 확인해야 한다.
    """
    declared = set(pyproject["tool"]["setuptools"]["packages"])

    actual = set()
    for init in PACKAGE_DIR.rglob("__init__.py"):
        relative = init.parent.relative_to(PACKAGE_DIR)
        parts = relative.parts
        # 시험·도구는 배포 대상이 아니다. `.venv` 는 받은 사람의 기계에서 생긴다.
        if parts and parts[0] in ("tests", "tools", ".venv", "third_party"):
            continue
        actual.add("mission_runtime" + "".join(f".{part}" for part in parts))

    assert actual <= declared, f"packages 목록에서 빠진 서브패키지: {sorted(actual - declared)}"

    # 목록에 더 있는 것은 데이터만 담은 디렉터리여야 한다(코드 없이 `.json`·`.md` 만).
    # 코드 디렉터리를 데이터로 착각해 적으면 `.py` 가 조용히 배포물에서 빠진다.
    for extra in sorted(declared - actual):
        directory = PACKAGE_DIR / Path(*extra.split(".")[1:])
        assert directory.is_dir(), f"선언만 있고 자리가 없다: {extra}"
        assert not (directory / "__init__.py").exists(), (
            f"{extra} 는 코드 패키지인데 데이터로 적혀 있다")


# ---------------------------------------------------------------------------
# 배포물이 데이터를 담는가
# ---------------------------------------------------------------------------


def test_wheel_package_data_covers_the_contracts_and_profiles(pyproject):
    """wheel 에 `schemas/`·`profiles/`·`config/`·`specs/` 가 들어가는가.

    `jsonschema` 는 **core 의존성**이다. 즉 스키마 검증은 선택 기능이 아니다. 그런데
    검증할 스키마 파일이 배포물에 없으면 그 core 기능이 설치본에서만 없어진다 —
    선택 기능의 정상적인 부재(AI-C-05)와 전혀 다른 일이고, 그 둘을 섞으면 실제
    고장이 "원래 그런 것"으로 읽힌다.
    """
    package_data = pyproject["tool"]["setuptools"]["package-data"]
    globs = package_data.get("mission_runtime", [])
    for directory in REQUIRED_DATA_DIRS:
        assert any(glob.startswith(f"{directory}/") for glob in globs), (
            f"{directory}/ 가 wheel package-data 에서 빠졌다")


def test_sdist_manifest_carries_what_a_clone_needs():
    """sdist 는 폐쇄망 조달 경로가 될 수 있다(AI-C-16) — 그러려면 혼자 완전해야 한다.

    setuptools 기본 sdist 는 패키지 `.py` 와 README 뿐이다. 그 기본값으로 올리면
    받은 사람은 스키마도, 예시 프로파일도, 콘솔도 없는 패키지를 쥔다.
    """
    assert MANIFEST.is_file(), "MANIFEST.in 이 없으면 sdist 는 .py 와 README 뿐이다"
    body = MANIFEST.read_text(encoding="utf-8")
    for directory in (*REQUIRED_DATA_DIRS, "docs", "tools", "deploy"):
        assert f"recursive-include {directory} " in body, f"{directory}/ 가 sdist 에서 빠졌다"


def test_no_credential_shaped_file_is_shipped():
    """자격증명·비밀정보는 배포물에 들어가지 않는다(AI-B-02).

    `.env.example` 은 예시이므로 괜찮고, 실제 값이 들어가는 `.env`/`.env.local` 은
    sdist 에서 빠져야 한다. 예시와 실물을 이름으로 가르는 규약을 배포물에서도 지킨다.
    """
    body = MANIFEST.read_text(encoding="utf-8")
    assert "global-exclude" in body and ".env" in body


# ---------------------------------------------------------------------------
# 쓰기 가능한 상태의 자리
# ---------------------------------------------------------------------------


def _load_by_path(name: str, path: Path):
    """`tools/` 아래의 스크립트를 패키지 아닌 상태로 싣는다(이름 충돌을 피한다)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def overlay_module():
    return _load_by_path(
        "fms_overlay_under_packaging_test",
        PACKAGE_DIR / "tools" / "fms_console" / "overlay.py")


def test_operator_edits_default_to_a_place_outside_the_install_tree(overlay_module, monkeypatch):
    """운영자 수정 장부가 설치 트리 안에 떨어지면 안 된다.

    옛 기본값은 `../local/fms_overlay/operator_edits.json` 이었다 — **상대 경로**라
    프로세스의 작업 디렉터리를 따라가고, 설치본에서 `..` 는 `site-packages/` 다.
    즉 `pip install` 한 사람이 값 하나를 고치면 그것이 설치물 안에 쓰였다.
    """
    monkeypatch.delenv(overlay_module.STATE_ROOT_ENV, raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    default = overlay_module.default_overlay_path()

    assert default.is_absolute(), f"기본 자리가 상대 경로다: {default}"
    assert PACKAGE_DIR not in default.parents, f"설치 트리 안에 쓴다: {default}"
    assert PACKAGE_DIR.parent not in default.parents, f"패키지 옆에 쓴다: {default}"


def test_the_state_root_can_be_pointed_elsewhere(overlay_module, monkeypatch, tmp_path):
    """자리를 환경변수 하나로 옮길 수 있어야 한다 — 폐쇄망·컨테이너에서는 홈
    디렉터리가 쓰기 가능하지 않을 수 있다(AI-C-16)."""
    monkeypatch.setenv(overlay_module.STATE_ROOT_ENV, str(tmp_path / "state"))
    assert (tmp_path / "state") in overlay_module.default_overlay_path().parents


def test_an_absent_ledger_is_an_empty_ledger_not_an_error(overlay_module, tmp_path):
    """파일이 없는 것은 "아직 아무도 고치지 않았다"다(AI-C-05)."""
    overlay = overlay_module.OperatorOverlay(path=tmp_path / "never" / "written.json")
    assert overlay.entries() == ()
    assert overlay.stats()["exists"] is False
    # 읽기만 했을 뿐인데 디렉터리를 만들어서는 안 된다 — 조회가 쓰기를 하면 안 된다.
    assert not (tmp_path / "never").exists()


# ---------------------------------------------------------------------------
# 자산 뿌리의 부재
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def console_module():
    return _load_by_path(
        "fms_console_serve_under_packaging_test",
        PACKAGE_DIR / "tools" / "fms_console" / "serve.py")


def test_the_asset_root_is_not_guessed_from_the_parent_directory(console_module, monkeypatch):
    """자산 뿌리를 `패키지의 부모 / local` 로 **무조건** 적으면, 설치본에서 그것이
    `site-packages/local` 이다 — 패키지가 아닌 남의 디렉터리를 자산 뿌리로 집는다.

    개발 배치에는 그 `local/` 이 실제로 있으므로 그때는 쓰고, 없으면 뿌리가 없는
    것으로 둔다. 없는 뿌리는 선언된 선택 조건이다.
    """
    monkeypatch.delenv(console_module.ASSET_ROOT_ENV, raising=False)
    resolved = console_module._resolve_asset_root()
    if resolved is not None:
        assert resolved.is_dir(), "없는 자리를 자산 뿌리로 집었다"


def test_an_explicit_asset_root_is_honoured_even_when_it_is_missing(console_module, monkeypatch, tmp_path):
    """사람이 명시한 자리는 없더라도 그대로 쓴다 — 조용히 다른 곳을 집으면 "왜
    자산을 못 찾느냐"를 추적할 길이 사라진다."""
    missing = tmp_path / "nowhere"
    monkeypatch.setenv(console_module.ASSET_ROOT_ENV, str(missing))
    assert console_module._resolve_asset_root() == missing


def test_samples_tell_an_absent_root_apart_from_an_empty_one(console_module, monkeypatch):
    """`samples: {}` 가 "사진이 없다"인지 "사진 뿌리가 없다"인지 구분되어야 한다.

    둘을 한 값으로 뭉치면 설정 실수와 정상 축소가 같은 화면으로 보인다(AI-O-06).
    """
    monkeypatch.setattr(console_module, "_APPEARANCE_ROOT", None)
    service = console_module.FmsService.__new__(console_module.FmsService)
    # 분류기만 있으면 되는 조회다 — fleet 을 세우지 않는다.
    service._appearance = _UnavailableClassifier()
    body = console_module.FmsService.appearance_samples(service)

    assert body["available"] is False
    assert body["reason"], "없다고만 하고 왜 없는지는 말하지 않는다"
    assert body["samples"] == {}
    assert body["samples_root"] is None
    assert body["samples_root_present"] is False


class _UnavailableClassifier:
    """근거 경로가 없는 분류기. 실제 모델 없이 축소 경로만 보기 위한 것."""

    available = False
    unavailable_reason = "no_embedding_model_available"
    unfit_classes: dict = {}


# ---------------------------------------------------------------------------
# 이 기계의 흔적
# ---------------------------------------------------------------------------


def test_no_absolute_home_path_in_executable_code():
    """`/home/<사람>/...` 가 **실행되는 코드**에 들어가면 그 코드는 이 기계에서만 돈다.

    주석·docstring 의 출처 인용은 이 시험이 보지 않는다 — 그것은 읽을 사람에게 남긴
    참조이고 동작을 바꾸지 않는다. 토큰 단위로 걸러서 그 둘을 섞지 않는다.
    """
    offenders = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        parts = path.relative_to(PACKAGE_DIR).parts
        if parts[0] in (".venv", "third_party", "build", "dist"):
            continue
        if "__pycache__" in parts:
            continue
        with open(path, "rb") as handle:
            try:
                for token in tokenize.tokenize(handle.readline):
                    if token.type in (tokenize.COMMENT, tokenize.STRING):
                        continue
                    if "/home/" in token.string:
                        offenders.append(f"{path.relative_to(PACKAGE_DIR)}:{token.start[0]}")
            except (tokenize.TokenError, SyntaxError):  # pragma: no cover
                continue
    assert offenders == [], f"실행 코드의 절대 홈 경로: {offenders}"


def test_nothing_in_the_package_reaches_the_network_at_import_time():
    """폐쇄망에서 기동할 수 있어야 한다(AI-C-16) — import 가 밖으로 나가면 못 한다.

    감사 후크로 실제 연결 시도를 잡는다. "그런 코드가 없어 보인다"가 아니라
    "이 실행에서 나가지 않았다"를 본다.
    """
    import pkgutil

    import mission_runtime

    touched: list[tuple[str, str]] = []

    def hook(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "urllib.Request"):
            touched.append((event, str(args)[:160]))

    sys.addaudithook(hook)

    failures = []
    names = [m.name for m in pkgutil.walk_packages(mission_runtime.__path__, "mission_runtime.")]
    assert names, "패키지를 하나도 훑지 못했다"
    for name in names:
        before = len(touched)
        try:
            importlib.import_module(name)
        except Exception as error:  # noqa: BLE001 - 어느 모듈이 왜인지를 전부 모아 보고한다
            failures.append(f"{name}: {type(error).__name__}: {error}")
        if len(touched) > before:
            failures.append(f"{name}: network {touched[before:]}")
    assert failures == [], f"import 가 실패하거나 밖으로 나갔다: {failures}"


def test_the_test_suite_does_not_write_to_the_real_user_state_directory():
    """conftest 의 세션 고정이 실제로 걸려 있는가.

    걸려 있지 않으면 `pytest` 한 번으로 사람의 `~/.local/state/` 에 장부가 생기고,
    다음 실행이 그것을 **읽은 채로** 시작한다 — 보이지 않는 의존이다.
    """
    root = os.environ.get("MISSION_RUNTIME_STATE")
    assert root, "conftest 의 `_isolated_state_root` 가 걸리지 않았다"
    assert Path.home() / ".local" / "state" / "mission_runtime" != Path(root)
