"""배포 점검 스크립트의 계약 — `tools/install_check.sh`.

implements: AI-B-02 (실행환경 패키징·재현성), AI-C-05 (선택 결손은 축소),
            AI-C-16 (폐쇄망 배포 경계)
tests: 문법이 선다 · --help 가 0 으로 끝난다 · 폐쇄망에서 wheelhouse 가 없으면 사유와
       함께 거절한다 · 이 폴더 **밖**을 전제하지 않는다 · 안내 문서와 같은 명령을 적는다

왜 전체 실행을 시험하지 않는가: 그 스크립트는 설치·시험·기동을 **실제로** 하고, 그것을
시험 안에서 또 돌리면 같은 일을 두 번 하면서 네트워크와 포트까지 요구한다. 여기서
고정하는 것은 **계약**이다 — 받는 사람이 기대는 자리(인자·거절 사유·경로 전제)가
말없이 바뀌지 않게 한다.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "install_check.sh"
GUIDE = ROOT / "docs" / "guides" / "deployment.md"

needs_bash = pytest.mark.skipif(
    subprocess.run(["which", "bash"], capture_output=True).returncode != 0,
    reason="bash 가 이 기계에 없다",
)


def test_the_script_is_there_and_runnable():
    assert SCRIPT.is_file(), "배포 점검 스크립트가 없다"
    assert os.access(SCRIPT, os.X_OK), "실행 권한이 없다 — chmod +x"


@needs_bash
def test_it_parses():
    """문법 오류는 받는 사람의 첫 명령에서 터진다. 여기서 먼저 잡는다."""
    done = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@needs_bash
def test_help_exits_clean():
    done = subprocess.run(["bash", str(SCRIPT), "--help"], capture_output=True, text=True,
                          cwd=ROOT, timeout=30)
    assert done.returncode == 0
    assert "install_check" in done.stdout or "배포 점검" in done.stdout


@needs_bash
def test_an_unknown_flag_is_refused_rather_than_guessed(tmp_path):
    done = subprocess.run(["bash", str(SCRIPT), "--nope"], capture_output=True, text=True,
                          cwd=ROOT, timeout=30)
    assert done.returncode != 0
    assert "모르는 인자" in done.stdout or "모르는 인자" in done.stderr


@needs_bash
def test_airgap_without_a_wheelhouse_says_why_and_where(tmp_path):
    """폐쇄망에서 바퀴 자리가 없으면 **사유와 자리**를 함께 낸다(AI-C-16).

    "설치 실패" 한 줄만 내면 받는 쪽은 자리를 어디로 줘야 하는지 알 수 없다.
    """
    env = dict(os.environ, MISSION_RUNTIME_WHEELHOUSE=str(tmp_path / "없는자리"),
               MISSION_RUNTIME_VENV=str(tmp_path / "venv"))
    done = subprocess.run(["bash", str(SCRIPT), "--offline", "--skip-tests"],
                          capture_output=True, text=True, cwd=ROOT, timeout=300, env=env)
    out = done.stdout + done.stderr
    assert done.returncode != 0
    assert "wheelhouse" in out and "없는자리" in out
    assert "MISSION_RUNTIME_WHEELHOUSE" in out


def test_it_never_assumes_anything_outside_this_folder():
    """`mission_runtime/` 만 받은 기계가 전제다 — 상위 디렉터리를 가리키면 그 기계에서
    없는 자리를 읽는다. 저장소 개발 배치의 `../.venv`·`../local` 이 그 유혹이다."""
    text = SCRIPT.read_text(encoding="utf-8")
    offenders = [line.strip() for line in text.splitlines()
                 if re.search(r"(^|[\s\"'=])\.\./", line) and not line.lstrip().startswith("#")]
    assert not offenders, "폴더 밖을 가리킨다: %s" % offenders


def test_the_guide_and_the_script_agree_on_the_first_command():
    """문서에 적힌 첫 명령이 실제 자리와 다르면 받는 사람의 첫 줄에서 막힌다."""
    assert GUIDE.is_file(), "배포 안내 문서가 없다"
    guide = GUIDE.read_text(encoding="utf-8")
    assert "bash tools/install_check.sh" in guide
    for flag in ("--extras", "--skip-tests", "--offline"):
        assert flag in guide, f"안내에 {flag} 가 없다"
        assert flag in SCRIPT.read_text(encoding="utf-8"), f"스크립트에 {flag} 가 없다"
