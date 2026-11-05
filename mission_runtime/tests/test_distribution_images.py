"""받아서 띄우는 길 — 이미지 셋이 **서로 다른 세 이유로** 갈려 있는지 고정한다.

왜 셋인가
---------
GPU 필요 여부와 AGPL 의존성 여부는 **독립된 두 축**이다. 합치면 탐지기만 필요한
사람이 CUDA 런타임의 대가를, GPU 만 필요한 사람이 AGPL 의 대가를 함께 치른다.

라이센스는 아직 정해지지 않았다
-------------------------------
그래서 이 묶음은 라이센스를 **주장하지 않는다.** 고정하는 것은 분리뿐이다 —
`ultralytics` 가 기본 이미지에 없고 전용 대상에만 있다는 사실. 나중에 어느 쪽으로
정해도 이미지를 다시 설계하지 않는다.

implements: AI-B-02 (실행환경 패키징·재현성), AI-C-15 (배포 프로파일), AI-C-16
관련: AI-C-05, AI-B-10, AI-B-11
tests: three targets, no vendor runtime in base, real-site declarations excluded,
       credentials excluded, preflight as healthcheck
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

DOCKERFILE = PROJECT_DIR / "Dockerfile"
DOCKERIGNORE = PROJECT_DIR / ".dockerignore"
COMPOSE = PROJECT_DIR / "docker-compose.yml"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def stage_instructions() -> dict[str, list[str]]:
    """단계별 **지시문만**. 주석은 뺀다 — 검사해야 하는 것은 이미지에 들어가는
    것이고, 왜 그렇게 했는지는 주석이 말한다. 섞어서 자르면 설명이 들어 있는
    것만으로 시험이 통과하거나 깨진다(실제로 한 번 깨졌다)."""
    stages: dict[str, list[str]] = {}
    current = ""
    for raw in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("FROM ") and " AS " in line:
            current = line.split(" AS ")[1].strip()
            stages[current] = [line]
            continue
        if current:
            stages[current].append(line)
    return stages


@pytest.fixture(scope="module")
def ignored() -> list[str]:
    return [line.strip() for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


@pytest.fixture(scope="module")
def compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


# ── 세 대상 ─────────────────────────────────────────────────────────────────

def test_the_three_build_targets_exist_and_are_named(dockerfile):
    stages = {line.split(" AS ")[1].strip()
              for line in dockerfile.splitlines()
              if line.startswith("FROM ") and " AS " in line}

    assert stages == {"cpu", "cuda", "detectors"}


def test_the_base_image_carries_no_vendor_accelerator_runtime(stage_instructions):
    """**원칙 #1.** 기본 이미지가 벤더를 가리키면 그것을 쓰는 모든 배치가 따라간다."""
    cpu = " ".join(stage_instructions["cpu"]).lower()

    for vendor in ("nvidia", "cuda", "rocm", "openvino"):
        assert vendor not in cpu, f"기본 이미지에 {vendor} 가 들어간다"


def test_the_agpl_dependency_is_only_in_its_own_target(stage_instructions, dockerfile):
    """라이센스는 아직 정하지 않았다 — 고정하는 것은 **분리**뿐이다."""
    for stage in ("cpu", "cuda"):
        joined = " ".join(stage_instructions[stage])
        assert "ultralytics" not in joined, (
            f"{stage} 대상에 AGPL 의존성이 들어가면 분리가 사라진다")
    assert "ultralytics" in " ".join(stage_instructions["detectors"])
    assert "AGPL-3.0" in dockerfile, "왜 분리했는지가 파일 안에 적혀 있어야 한다"


def test_the_gpu_target_says_the_driver_is_not_in_the_image(dockerfile):
    """Docker 가 **고쳐 주지 않는** 자리다. 적어 두지 않으면 받는 쪽이 헤맨다.

    주석에서 찾는다 — 이것은 이미지에 들어가는 것이 아니라 받는 사람에게 하는
    말이고, 그 말이 사라지지 않게 고정하는 것이 이 시험의 목적이다.
    """
    comments = "\n".join(line for line in dockerfile.splitlines()
                          if line.strip().startswith("#"))

    assert "드라이버" in comments
    assert "호스트" in comments


def test_the_detector_target_does_not_also_require_a_gpu(stage_instructions):
    """두 축이 독립이다 — 탐지기가 필요한 사람이 GPU 까지 필요한 것은 아니다."""
    assert stage_instructions["detectors"][0].startswith("FROM cpu "), (
        f"cpu 위에 얹어야 한다: {stage_instructions['detectors'][0]}")


# ── 이미지에 들어가지 않는 것 ───────────────────────────────────────────────

def test_the_real_site_declarations_do_not_ship(ignored):
    """이미지에 들어가면 받는 사람이 **우리 현장의 구역·좌표·장치 식별자**를 함께 받는다."""
    for real in ("profiles/domains.json", "config/status_ui.json"):
        assert real in ignored, f"{real} 이 이미지에 들어간다"


def test_the_example_declarations_still_ship(ignored):
    """예시까지 빼면 받아서 띄울 수 있는 것이 없다."""
    assert "!profiles/*.example.json" in ignored
    assert "!config/*.example.json" in ignored
    assert (PROJECT_DIR / "profiles" / "domains.example.json").is_file()
    assert (PROJECT_DIR / "config" / "status_ui.fms.example.json").is_file()


def test_credentials_and_operator_edits_do_not_ship(ignored):
    """자격증명은 이미지에 넣지 않는다(AI-B-02). 사람이 고친 값도 굽지 않는다."""
    assert any("credentials" in line for line in ignored)
    assert "fms_overlay" in ignored


def test_model_weights_and_internal_records_do_not_ship(ignored):
    assert "local" in ignored and "internal" in ignored


# ── 자가 점검이 상태 확인이다 ───────────────────────────────────────────────

def test_the_healthcheck_runs_the_self_check(dockerfile):
    """태그만 세면 "모듈이 import 된다" 까지만 알 수 있다 — "이 환경에서 무엇이
    되는가" 는 호스트가 무엇을 넘겼는지에 달려 있고 띄워 보고 물어야 안다."""
    healthchecks = [line for line in dockerfile.splitlines() if "preflight.py" in line]

    assert len(healthchecks) >= 2, "cpu·cuda 두 대상 모두 자가 점검으로 확인한다"


# ── compose ─────────────────────────────────────────────────────────────────

def test_the_default_profile_brings_up_console_and_broker(compose):
    """받아서 치는 명령 하나가 `docker compose up` 이어야 한다."""
    default = {name for name, body in compose["services"].items()
               if not body.get("profiles")}

    assert default == {"console", "broker"}


def test_each_variant_sits_behind_its_own_profile(compose):
    services = compose["services"]

    assert services["console-gpu"]["profiles"] == ["gpu"]
    assert services["console-detectors"]["profiles"] == ["detectors"]
    assert services["preflight"]["profiles"] == ["preflight"]


def test_the_declarations_are_passed_explicitly_not_left_to_defaults(compose):
    """콘솔 기본값은 아직 우리 현장 파일을 가리키고 그 파일은 이미지에 없다 —
    기본값에 기대면 받는 쪽에서 없는 파일을 찾는다."""
    for name in ("console", "console-gpu", "console-detectors"):
        command = compose["services"][name]["command"]
        assert "--ui-config" in command and "example" in command, name
        assert "--zone-profile" in command and "example" in command, name


def test_the_broker_is_an_edge_service_not_a_terminal_one(compose):
    """브로커·수집기는 구역 엣지에 둔다(AI-B-10 · 원칙 #12). compose 가 엣지
    한 대를 세우는 모양이고, 말단에 같은 것을 올리는 구성이 아니다."""
    assert "broker" in compose["services"]
    assert (PROJECT_DIR / "deploy" / "mosquitto.conf").is_file()


def test_the_detector_variant_declines_the_accelerator_by_declaration(compose):
    """숨기는 쪽(`CUDA_VISIBLE_DEVICES=""`)을 쓰지 않는다 — 그것은 NVBLAS 를 통해
    예외 없이 틀린 값을 낸다."""
    env = compose["services"]["console-detectors"]["environment"]

    assert env.get("MISSION_RUNTIME_NO_GPU") == "1"
    assert "CUDA_VISIBLE_DEVICES" not in env


def test_operator_edits_live_on_a_volume_not_in_the_image(compose):
    """되돌림도 삭제가 아니라 기록이다(AI-L-03) — 재시작으로 사라지면 안 된다."""
    assert "overlay" in compose.get("volumes", {})
    for name in ("console", "console-gpu", "console-detectors"):
        mounts = compose["services"][name]["volumes"]
        assert any("overlay" in str(m) for m in mounts), name


def test_no_service_claims_a_licence(compose):
    """라이센스는 아직 정해지지 않았다. 배포 설정이 그것을 **선점하지 않는다.**"""
    text = COMPOSE.read_text(encoding="utf-8")

    assert "정해지지 않았" in text, "정하지 않았다는 사실을 적어 둔다"
    for claim in ("SPDX-License-Identifier", "license:"):
        assert claim not in text, f"{claim} 이 라이센스를 선점한다"
