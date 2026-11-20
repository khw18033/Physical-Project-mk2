"""설치 자가 점검 — 받는 사람이 **띄우기 전에** 무엇이 되는지 알게 한다.

이 묶음이 지키는 것 넷.

1. **축소를 막힘으로 적지 않는다.** 선택 기능 결손은 정상 상태다(AI-C-05). 전부
   빨갛게 칠하면 받는 사람이 "내 환경에선 안 되는구나" 로 읽고 그만두는데,
   실제로는 핵심이 전부 도는 경우가 대부분이다.
2. **판정을 새로 하지 않는다.** 환경 사실·device 선택·탐지기 조달은 각자 소유자가
   있고 이 도구는 모은다 — 두 곳에서 판정하면 설치 화면과 운영 화면이 다른 말을 한다.
3. **nvidia-smi 의 세 상태를 섞지 않는다.** 없는 것 · 있는데 답하지 못하는 것
   (드라이버 충돌의 관측 모양) · 답해서 0개라고 말한 것.
4. **조용히 틀리는 함정을 막힘으로 잡는다.** `CUDA_VISIBLE_DEVICES=""` 는 되는
   것처럼 보이면서 틀린 값을 낸다.

implements: AI-C-05, AI-B-04, AI-C-16, AI-B-01, AI-O-05
tests: degraded vs blocked, exit code, three GPU states, the silent-wrong trap
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "tools"))

import preflight  # noqa: E402

from mission_runtime.runtime.environment_profile import EnvironmentFacts, GpuProbe  # noqa: E402


def _facts(**over) -> EnvironmentFacts:
    body = dict(os_name="Linux", kernel_release="6.1.0", proc_version="Linux version 6.1.0",
                in_container=False, wsl_interop=False,
                gpu_probe=GpuProbe.TOOL_ABSENT, gpu_count=None, gpu_probe_detail="")
    body.update(over)
    return EnvironmentFacts(**body)


# ── 축소와 막힘은 다른 사실이다 ─────────────────────────────────────────────

def test_an_optional_gap_does_not_block_starting():
    """**이 시험이 이 파일의 요점이다.** 선택 결손으로 시작을 막으면 AI-C-05 위반이다."""
    body = preflight.report()

    optional = [c for s in body["sections"] for c in s["checks"]
                if c["status"] == preflight.STATUS_DEGRADED]
    assert body["can_start"] or body["blocking"], "막힘이 없으면 시작할 수 있어야 한다"
    if optional:
        assert all(name not in body["blocking"] for name in (c["name"] for c in optional))


def test_the_summary_keeps_the_three_counts_apart():
    """축소와 막힘을 한 수로 합치면 "다 되는데 두 개 꺼짐" 과 "핵심이 막힘" 이 같아진다."""
    summary = preflight.report()["summary"]

    assert set(summary) == {"ok", "degraded", "blocked"}
    assert all(isinstance(v, int) for v in summary.values())


def test_the_exit_code_is_nonzero_only_when_a_core_check_is_blocked(capsys):
    """선택 결손으로 0 이 아니면 설치 스크립트가 정상 배치를 거부한다."""
    code = preflight.main([])
    body = preflight.report()

    captured = capsys.readouterr().out
    assert code == (0 if body["can_start"] else 1)
    assert "정상" in captured and "축소" in captured and "막힘" in captured


def test_every_non_ok_check_says_what_is_lost():
    """사유 없는 경고는 받는 쪽이 할 일을 모른다."""
    for section in preflight.report()["sections"]:
        for check in section["checks"]:
            if check["status"] != preflight.STATUS_OK:
                assert check.get("impact") or check.get("detail"), check


def test_the_json_form_is_machine_readable(capsys):
    import json

    preflight.main(["--json"])

    body = json.loads(capsys.readouterr().out)
    assert "can_start" in body and "sections" in body


# ── 가속기 세 상태 ──────────────────────────────────────────────────────────

def test_a_driver_that_answers_nothing_is_blocked_with_the_known_remedy():
    """**드라이버 충돌의 관측 모양이 이것이다** — 도구는 있고 답을 못 한다.

    "가속기가 없다" 와 합치면 받는 쪽이 할 일을 모른다. 전자는 할 일이 없고
    후자는 WSL·Docker 로 옮기는 일이 있다.
    """
    section = preflight._accelerator(
        _facts(gpu_probe=GpuProbe.TOOL_FAILED, gpu_probe_detail="rc=1"))

    gpu = next(c for c in section.checks if c.name == "NVIDIA GPU")
    assert gpu.status == preflight.STATUS_BLOCKED
    assert "WSL" in gpu.remedy or "Docker" in gpu.remedy
    assert "CPU" in gpu.impact, "느리지만 동작한다는 사실을 함께 적는다"


def test_an_absent_tool_is_degraded_not_blocked():
    """가속기가 없는 기계는 **정상 배치**다 — 핵심 기능은 그대로 돈다."""
    section = preflight._accelerator(_facts(gpu_probe=GpuProbe.TOOL_ABSENT))

    gpu = next(c for c in section.checks if c.name == "NVIDIA GPU")
    assert gpu.status == preflight.STATUS_DEGRADED


def test_a_tool_that_answered_zero_is_a_third_state():
    """답해서 0개라고 말한 것은 도구가 없는 것과 다른 사실이다(AI-B-01)."""
    absent = preflight._accelerator(_facts(gpu_probe=GpuProbe.TOOL_ABSENT))
    answered = preflight._accelerator(
        _facts(gpu_probe=GpuProbe.ANSWERED, gpu_count=0, gpu_probe_detail="rc=0:lines=0"))

    absent_gpu = next(c for c in absent.checks if c.name == "NVIDIA GPU")
    answered_gpu = next(c for c in answered.checks if c.name == "NVIDIA GPU")
    assert absent_gpu.detail != answered_gpu.detail, "두 사실이 구분돼야 한다"


def test_the_device_this_run_will_use_comes_from_the_owning_module():
    """화면이 말하는 device 와 provider 가 고르는 device 가 달라서는 안 된다."""
    from mission_runtime.ondevice.rpn_propose import default_device

    section = preflight._accelerator(_facts(gpu_probe=GpuProbe.ANSWERED, gpu_count=1))

    row = next(c for c in section.checks if "device" in c.name)
    assert row.detail == default_device()


# ── 조용히 틀리는 함정 ──────────────────────────────────────────────────────

def test_hiding_the_gpu_with_an_empty_variable_is_reported_as_blocked(monkeypatch):
    """**되는 것처럼 보이면서 틀린 값을 낸다** — 안 되는 것보다 나쁘다.

    CUDA 휠이 깔린 기계에서 이렇게 숨기면 NVBLAS 가 CPU BLAS 를 가로챈다
    (local/demo/CLAUDE.md 실측). 그래서 축소가 아니라 막힘이다.
    """
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")

    section = preflight._accelerator(_facts(gpu_probe=GpuProbe.ANSWERED, gpu_count=1))

    trap = next(c for c in section.checks if "CUDA_VISIBLE_DEVICES" in c.name)
    assert trap.status == preflight.STATUS_BLOCKED
    assert "MISSION_RUNTIME_NO_GPU" in trap.remedy, "대안을 함께 적는다"


def test_the_declared_no_gpu_path_is_not_treated_as_a_trap(monkeypatch):
    """선언으로 끄는 쪽은 계산을 바꾸지 않는다 — 막힘이 아니다."""
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.setenv("MISSION_RUNTIME_NO_GPU", "1")

    section = preflight._accelerator(_facts(gpu_probe=GpuProbe.ANSWERED, gpu_count=1))

    trap = next(c for c in section.checks if "CUDA_VISIBLE_DEVICES" in c.name)
    device = next(c for c in section.checks if "device" in c.name)
    assert trap.status == preflight.STATUS_OK
    assert device.detail == "cpu"
    assert "노드 태그는" in device.impact, "태그는 사실을 그대로 말한다는 것을 적는다"


# ── 라이센스를 설치 시점에 알린다 ──────────────────────────────────────────

def test_the_agpl_detector_dependency_is_named_with_its_licence():
    """라이센스는 받는 쪽의 선택이고, 설치 시점이 그것을 알 자리다."""
    section = preflight._optional()

    row = next(c for c in section.checks if "AGPL" in c.name)
    assert "AGPL-3.0" in row.name
    if row.status != preflight.STATUS_OK:
        assert "네트워크" in row.remedy, "왜 중요한지를 함께 적는다"


# ── 플랫폼 결손은 미측정이다 ───────────────────────────────────────────────

def test_a_missing_sensor_path_is_degraded_and_says_it_is_unmeasured():
    """센서가 없으면 그 값이 0 이 아니라 미측정으로 나간다(AI-O-05)."""
    section = preflight._platform(_facts())

    for check in section.checks:
        if check.status == preflight.STATUS_DEGRADED:
            assert "미측정" in check.impact or "비활성" in check.impact, check
            assert not check.remedy, "받는 쪽이 할 일이 없으면 처방을 지어내지 않는다"
