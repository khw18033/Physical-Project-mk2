"""백엔드를 한 줄로 세우고 내리는 길 — `tools/backend.sh`.

implements: AI-B-02 (재현 가능한 실행), AI-B-05 (lifecycle), AI-C-05 (없으면 그 조각만)
tests: 상태는 **켜지 않고** 답한다 · 자리는 설치 트리 밖이다 · 컨테이너가 먼저다 ·
       호스트 권한은 **기본이 아니다** · 주소를 하나만 적지 않는다
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]
SCRIPT = PKG / "tools" / "backend.sh"
COMPOSE = PKG / "deploy" / "backend" / "docker-compose.yml"
HOST_CONTROL = PKG / "deploy" / "backend" / "docker-compose.host-control.yml"


def run(*args: str, env: dict | None = None, timeout: int = 90):
    merged = {**os.environ, "MISSION_RUNTIME_STATE": env.pop("STATE", "/tmp/nope")} if env else dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=PKG, env=merged,
                          capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def state(tmp_path: Path) -> dict:
    return {"MISSION_RUNTIME_STATE": str(tmp_path / "state")}


# --------------------------------------------------------------- 모양

def test_the_script_is_executable_and_parses():
    assert SCRIPT.is_file()
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_an_unknown_verb_prints_the_usage_and_refuses(state):
    done = run("fly", env=state)
    assert done.returncode == 2
    assert "start" in done.stdout and "stop" in done.stdout


def test_status_answers_without_starting_anything(state):
    """상태를 묻는 것이 **켜는 일이 되면** 안 된다 — 묻기만 하는 길이 있어야 한다."""
    done = run("status", env=state)
    assert done.returncode == 0
    assert "멈춰 있다" in done.stdout or "exited" in done.stdout.lower()


def test_the_state_root_is_outside_the_install_tree(state, tmp_path: Path):
    """설치 트리에 pid·로그를 쓰면 설치된 패키지를 고치는 것이 되고 `git pull` 이 충돌한다."""
    run("status", env=state)
    assert str(tmp_path) in run("status", env=state).stdout
    assert not (PKG / "backend.pid").exists()
    assert not list(PKG.glob("*.pid"))


# --------------------------------------------------------------- 컨테이너

def test_the_compose_file_declares_both_ports_the_viz_reads():
    """가시화가 읽는 자리는 둘이다 — 하나만 띄우면 화면의 한 칸이 조용히 빈다."""
    text = COMPOSE.read_text(encoding="utf-8")
    assert '"8899:8899"' in text, "게이트웨이 — /registry · WS · FMS 조회"
    assert '"8765:8765"' in text, "capability — 가시화 「기능」 카드의 원천"


def test_the_containers_come_back_after_a_reboot():
    """"명령어 하나로 **상시** 실행" 이 뜻하는 것이 이것이다."""
    text = COMPOSE.read_text(encoding="utf-8")
    assert text.count("restart: unless-stopped") >= 1


def test_declarations_are_mounted_rather_than_baked_into_the_image():
    """현장 값을 바꾸려고 이미지를 다시 굽지 않는다(AI-B-02: 비밀은 이미지에 넣지 않는다)."""
    text = COMPOSE.read_text(encoding="utf-8")
    assert "../../config:/app/config:ro" in text
    assert "../../profiles:/app/profiles:ro" in text


def test_the_image_is_rebuilt_when_the_source_is_newer():
    """있다는 것만 보면 2 주 전 이미지로 오늘 코드를 돌린다 — 실제로 그렇게 돼서
    컨테이너가 "모르는 깃발" 로 재시작 루프에 빠졌다(2026-11-22)."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "image_is_fresh" in text
    assert "git ls-files" in text, "소스 쪽 기준은 추적되는 파일의 최신 수정 시각이다"


def test_a_machine_without_docker_still_gets_a_backend():
    """도커가 없는 기계도 정상이다 — 그 조각만 다르고 그렇다고 말한다(AI-C-05)."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "AIF_MODE" in text and "bare" in text
    assert "프로세스로" in text


# --------------------------------------------------------------- 권한 경계

def test_host_docker_and_k3s_are_not_mounted_by_default():
    """소켓을 얹는 것은 그 컨테이너에 **호스트 root** 를 주는 일이다. 기본이 아니다."""
    assert "docker.sock" not in COMPOSE.read_text(encoding="utf-8")
    assert "docker.sock" in HOST_CONTROL.read_text(encoding="utf-8")


def test_the_host_control_overlay_is_opt_in_by_one_name():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'AIF_HOST_CONTROL:-0' in text, "기본값이 꺼짐이어야 한다"
    assert "host-control.yml" in text


def test_the_overlay_says_what_it_gives_away():
    """위험을 적지 않은 스위치는 **눌러 보고 알게 된다.**"""
    text = HOST_CONTROL.read_text(encoding="utf-8")
    assert "호스트 root" in text


# --------------------------------------------------------------- 주소

def test_status_prints_more_than_one_address_when_bound_to_everything(state):
    """듣는 주소 하나에 **붙는 주소가 둘**일 수 있다. 하나만 적으면 반드시 한쪽이
    못 붙는다 — 오버레이 주소만 적어 윈도 브라우저가 못 열었다(2026-11-22)."""
    done = run("status", env={**state, "AIF_HOST": "0.0.0.0"})
    assert "localhost" in done.stdout
    assert "VITE_GATEWAY" in done.stdout or "capability" in done.stdout


def test_the_advertised_address_is_not_hardcoded():
    """기계를 옮기면 주소도 따라가야 한다 — 스크립트에 주소를 박지 않는다."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "100.83." not in text, "이 기계의 오버레이 주소가 박혀 있다"
    assert "advertised_host" in text, "주소는 오버레이 provider 가 답한다"
