"""Shared fixtures/helpers for the small number of tests that still need a
hand-built `ZoneApplication` (real-infra integration tests that don't fit
`simulator/scenarios/*.json` — see `simulator/README.md` for what does).
"""

from pathlib import Path

import pytest

from mission_runtime.contracts.capability import CapabilityRequirement
from mission_runtime.contracts.profile import (
    CompatibilityProfile,
    DeploymentProfile,
    ResourceBudget,
    ResourceCost,
)
from mission_runtime.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from mission_runtime.runtime.application import CapabilitySpec, ZoneApplication

PACKAGE_DIR = Path(__file__).resolve().parents[1]
CORE_DIRS = ["perception", "decision", "risk", "runtime", "execution", "registry", "selection", "contracts"]

#: 패키지 **자신의** 모듈 디렉터리. 2026-11-02 재배치로 프로젝트 루트와 패키지 루트가
#: 같아졌다 — 그래서 루트를 통째로 훑으면 `tests/`·`tools/`·`docs/` 까지 들어온다.
#: 경계 시험("이 모듈만 그 라이브러리를 import 한다")이 그걸 훑으면 시험 코드 자신의
#: import 를 위반으로 읽는다. 패키지 모듈만 보도록 자리를 한 곳에 적어 둔다.
MODULE_DIRS: tuple[str, ...] = (
    "collection", "common", "continual", "contracts", "decision", "edge", "execution",
    "integration", "observability", "ondevice", "perception", "planning", "providers",
    "reference", "registry", "risk", "runtime", "selection", "simulation",
)


def package_py_files() -> list[Path]:
    """패키지가 배포하는 `.py` 전부(최상위 모듈 + 서브패키지). 시험·도구는 뺀다."""
    files = sorted(PACKAGE_DIR.glob("*.py"))
    for name in MODULE_DIRS:
        files.extend(sorted((PACKAGE_DIR / name).rglob("*.py")))
    return files


def package_modules_importing(token: str) -> list[str]:
    """`token` 을 import 하는 패키지 모듈의 경로(프로젝트 루트 기준 상대)."""
    hits = []
    for path in package_py_files():
        text = path.read_text(encoding="utf-8")
        if any(line.strip().startswith(("import ", "from ")) and token in line
               for line in text.splitlines()):
            hits.append(str(path.relative_to(PACKAGE_DIR)))
    return hits


def registration(
    kind: str,
    provider_id: str,
    *,
    priority: int = 50,
    compute: float = 1.0,
    memory: float = 64.0,
    hw_tags: tuple = (),
    preferred: tuple = (),
    requirement: CapabilityRequirement | None = None,
    health_check=None,
    version: str = "1",
) -> ProviderRegistration:
    return ProviderRegistration(
        capability_kind=kind,
        provider_id=provider_id,
        version=version,
        compatibility=CompatibilityProfile(
            required_hw_tags=hw_tags,
            preferred_hw_tags=preferred,
            priority=priority,
            cost=ResourceCost(compute_units=compute, memory_mb=memory),
        ),
        requirement=requirement or CapabilityRequirement(),
        health_check=health_check,
    )


def profile_of(domain_id: str, kinds, *, node_tags=("cpu",), rule_set_id=None) -> DeploymentProfile:
    return DeploymentProfile(
        domain_id=domain_id,
        active_capability_kinds=tuple(kinds),
        rule_set_id=rule_set_id,
        node_tags=tuple(node_tags),
    )


def spec(kind: str, *, core: bool = False, rank: int = 0, requirement=None) -> CapabilitySpec:
    return CapabilitySpec(
        kind=kind,
        is_core=core,
        degrade_rank=rank,
        requirement=requirement or CapabilityRequirement(),
    )


def build_app(profile, registry, specs, node_tags=None) -> ZoneApplication:
    return ZoneApplication(profile, registry, specs, node_tags=node_tags)


def core_source_mentions(token: str) -> list[str]:
    """Occurrences of `token` in *executable* core code (AI-B-09, 원칙 #1/#3/#7)."""
    import tokenize

    hits = []
    for directory in CORE_DIRS:
        for path in (PACKAGE_DIR / directory).rglob("*.py"):
            with open(path, "rb") as handle:
                for tok in tokenize.tokenize(handle.readline):
                    if tok.type in (tokenize.COMMENT, tokenize.STRING):
                        continue
                    if token in tok.string:
                        hits.append(f"{directory}/{path.name}:{tok.start[0]}: {tok.string}")
    return hits


@pytest.fixture
def registry() -> CapabilityRegistry:
    return CapabilityRegistry()


@pytest.fixture
def ample_budget() -> ResourceBudget:
    return ResourceBudget(compute_units=100.0, memory_mb=8192.0)


# -- 실제 자산(모델·가중치·데이터셋)이 있는 곳 ---------------------------------
# 2026-11-02 재분류: 공개 트리에는 코드·계약·문서만 두고, 대용량 자산은 공개하지
# 않는 `local/` 로 분리했다. 자산 경로를 시험마다 적으면 재분류가 또 있을 때 "자산이
# 없다"는 skip 으로 조용히 번진다 — 그 skip 은 실패처럼 보이지 않아서 더 위험하다.
# 그래서 자리를 한 곳에서 정하고, 다른 기계에서는 환경변수로 가리킬 수 있게 둔다.

import os as _os

ASSET_ROOT_ENV = "MISSION_RUNTIME_ASSETS"


def asset_root() -> Path:
    """실제 모델·데이터셋 뿌리. `MISSION_RUNTIME_ASSETS` 로 바꿀 수 있다.

    공개 트리만 clone 한 사람에게는 `parents[2]/local` 이 존재하지 않는다 — 그것이
    정상이다. 자리가 없는 것은 "그 묶음만 skip" 이고, 아래 `asset_root_present()`
    하나로 그 사실을 묻는다. 자리를 시험마다 따로 적으면 재분류가 또 있을 때 어떤
    시험은 skip 되고 어떤 시험은 실패한다.
    """
    override = _os.environ.get(ASSET_ROOT_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "local"


def asset_root_present() -> bool:
    """자산 뿌리가 실제로 있는가. `skipif` 가 이 한 줄만 보면 된다."""
    return asset_root().is_dir()


def asset_path(*parts: str) -> Path:
    return asset_root().joinpath(*parts)


def demo_asset_path(*parts: str) -> Path:
    """실제 로봇 데모(physical_demo)에서 가져온 모델·스캔 자산."""
    return asset_root().joinpath("physical_demo_assets", *parts)


# -- 시험이 사람의 상태 디렉터리에 쓰지 않게 한다 ------------------------------
# 운영자 수정 장부(`tools/fms_console/overlay.py`)의 기본 자리는 사용자 상태
# 디렉터리다. 시험이 그 기본값을 그대로 쓰면 `pytest` 를 한 번 돌린 것만으로 사람의
# `~/.local/state/` 에 장부가 생기고, 다음 실행이 **그것을 읽은 채로** 시작한다 —
# 시험 결과가 지난 실행에 의존하게 되는 것이고, 그 의존은 눈에 보이지 않는다.
# 그래서 세션마다 임시 자리를 가리킨다. 자리를 정하는 환경변수가 하나라서 이 한
# 줄로 콘솔을 in-process 로 세우는 시험과 subprocess 로 띄우는 시험이 모두 덮인다.


@pytest.fixture(scope="session", autouse=True)
def _isolated_state_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("mission_runtime_state")
    previous = _os.environ.get("MISSION_RUNTIME_STATE")
    _os.environ["MISSION_RUNTIME_STATE"] = str(root)
    try:
        yield root
    finally:
        if previous is None:
            _os.environ.pop("MISSION_RUNTIME_STATE", None)
        else:
            _os.environ["MISSION_RUNTIME_STATE"] = previous
