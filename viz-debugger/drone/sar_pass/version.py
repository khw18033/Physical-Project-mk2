"""이 코드의 버전 — 비행 기록에 같이 남겨 몇 달 뒤에도 「어느 코드로 찍었나」를 안다.

git 저장소 안에서 돌면(Pi 에 clone + `pip install -e`) 커밋 번호와 고친 채 돌았는지를, 아니면 패키지 버전만 적는다.
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path


@functools.lru_cache(maxsize=1)
def software_version() -> dict:
    here = Path(__file__).resolve().parent
    out: dict = {"package": "sar-pass"}
    try:
        from importlib.metadata import version
        out["package_version"] = version("sar-pass")
    except Exception:  # noqa: BLE001
        out["package_version"] = None
    try:
        def git(*a: str) -> str:
            return subprocess.run(["git", "-C", str(here), *a], capture_output=True, text=True, timeout=3, check=True).stdout.strip()
        out["git_commit"] = git("rev-parse", "--short=10", "HEAD")
        out["git_branch"] = git("rev-parse", "--abbrev-ref", "HEAD")
        out["git_dirty"] = bool(git("status", "--porcelain", "--untracked-files=no", "--", str(here.parent)))
    except Exception:  # noqa: BLE001 — git 이 없거나 저장소 밖
        out["git_commit"] = None
    return out
