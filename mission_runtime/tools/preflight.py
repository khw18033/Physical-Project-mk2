#!/usr/bin/env python3
"""Install-time self-check — what will work on this machine, and what will not.

implements: AI-C-05 (선택 기능 결손은 축소), AI-B-04 (자원 등록), AI-C-16 (폐쇄망 경계)
관련: AI-B-01 (미측정 구분), AI-O-05, AI-C-05, AI-B-10, AI-C-13

처음 받는 사람이 **띄우기 전에** 이 명령 하나로 알아야 하는 것: 무엇이 그대로
돌고, 무엇이 축소되고, 무엇이 아예 안 되는가. 그리고 **왜** 그런가.

    python3 tools/preflight.py            # 사람이 읽는 표
    python3 tools/preflight.py --json     # 기계가 읽는 한 덩어리

판정을 새로 하지 않는다
-----------------------
환경 사실과 프로파일 해소는 `runtime/environment_profile.py` 가 소유하고, 가속기
선택은 `ondevice/rpn_propose.py::default_device()` 가, 탐지기 조달 가능성은
`edge/detector_catalog.py` 가 소유한다. 이 도구는 그 답을 **모아서** 한 장으로 낸다
— 같은 판정을 두 곳에서 하면 설치 화면과 운영 화면이 다른 말을 한다(CLAUDE.md §0).

세 상태를 쓴다
--------------
``ok``
    그대로 된다.
``degraded``
    **그 기능만** 줄어들고 나머지는 돈다. 결손이 정상 상태인 경우다(AI-C-05) —
    예: 전력 센서가 없으면 전력이 "미측정" 으로 나가고 0 으로 채우지 않는다.
``blocked``
    그 기능을 쓸 수 없다. 무엇을 하면 되는지 함께 적는다.

``degraded`` 를 ``blocked`` 로 적지 않는 것이 이 도구의 요점이다. 전부 빨갛게
칠하면 받는 사람이 "이건 내 환경에서 안 되는구나" 로 읽고 그만두는데, 실제로는
핵심 기능이 전부 도는 경우가 대부분이다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR.parent))

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_BLOCKED = "blocked"


@dataclass
class Check:
    """점검 한 줄. **무엇을 잃는지와 어떻게 얻는지**를 함께 든다."""

    name: str
    status: str
    detail: str = ""
    #: 이것이 없으면 무엇이 줄어드는가. `ok` 면 빈 문자열이다.
    impact: str = ""
    #: 어떻게 얻는가. 모르면 빈 문자열이고 추측을 적지 않는다.
    remedy: str = ""
    #: 이 줄이 어느 요구사항의 경계인가 — 사람이 근거를 찾아갈 수 있게.
    requirement: str = ""

    def as_dict(self) -> dict:
        body = {"name": self.name, "status": self.status}
        for key in ("detail", "impact", "remedy", "requirement"):
            value = getattr(self, key)
            if value:
                body[key] = value
        return body


@dataclass
class Section:
    title: str
    checks: list[Check] = field(default_factory=list)


# ── 코어 ────────────────────────────────────────────────────────────────────

def _core() -> Section:
    section = Section("핵심 — 이것이 되면 관제 시스템이 뜬다")
    section.checks.append(Check(
        "Python", STATUS_OK if sys.version_info >= (3, 10) else STATUS_BLOCKED,
        detail=".".join(str(v) for v in sys.version_info[:3]),
        impact="" if sys.version_info >= (3, 10) else "아무것도 돌지 않는다",
        remedy="" if sys.version_info >= (3, 10) else "Python 3.10 이상",
    ))
    for module, label, remedy in (
        ("jsonschema", "jsonschema (계약 검증)", 'pip install -e "."'),
        ("numpy", "numpy", 'pip install -e "."'),
        ("cv2", "opencv (영상 입력)", 'pip install -e "."'),
        ("google.protobuf", "protobuf (직렬화)", 'pip install -e "."'),
    ):
        present = _importable(module)
        section.checks.append(Check(
            label, STATUS_OK if present else STATUS_BLOCKED,
            impact="" if present else "핵심 기능이 뜨지 않는다",
            remedy="" if present else remedy))
    return section


# ── 플랫폼 ──────────────────────────────────────────────────────────────────

def _platform(facts) -> Section:
    section = Section("플랫폼 — 리눅스 계측 경로")
    section.checks.append(Check(
        "운영체제", STATUS_OK, detail=f"{facts.os_name} {facts.kernel_release or ''}".strip(),
        requirement="AI-B-04"))
    if facts.wsl_interop:
        # WSL 인지가 중요한 이유: 네이티브 리눅스에서 드라이버가 충돌하는 경우
        # 여기가 권장 경로다(아래 가속기 절과 묶인다).
        section.checks.append(Check(
            "WSL", STATUS_OK, detail="WSL interop 감지됨 — 가속기 절을 함께 보라",
            requirement="AI-C-15"))
    for label, path, impact, requirement in (
        ("CPU 온도", "/sys/class/thermal", "온도가 '미측정' 으로 나간다(0 이 아니다)", "AI-O-05"),
        ("소비 전력", "/sys/class/powercap", "전력이 '미측정' 으로 나간다", "AI-O-05"),
        ("무선 링크 품질", "/proc/net/wireless", "링크 기반 실행 전환이 비활성", "AI-N-03"),
    ):
        present = Path(path).exists()
        section.checks.append(Check(
            label, STATUS_OK if present else STATUS_DEGRADED,
            detail=path,
            impact="" if present else impact,
            # 센서가 없는 커널·WSL 은 흔하다. 받는 쪽이 할 일이 없으므로 처방도 없다.
            remedy="", requirement=requirement))
    return section


# ── 가속기 ──────────────────────────────────────────────────────────────────

def _accelerator(facts) -> Section:
    """**이 절이 이 도구를 만든 이유다.**

    세 상태를 섞지 않는다 — 도구가 없는 것, 있는데 답하지 못하는 것(드라이버
    충돌의 관측 모양), 답해서 0개라고 말한 것. 섞으면 "왜 GPU 를 안 쓰는가" 를
    끝까지 추적할 수 없다(AI-B-01·AI-O-05).
    """
    from mission_runtime.ondevice.rpn_propose import NO_GPU_ENV, default_device, gpu_use_declined
    from mission_runtime.runtime.environment_profile import GpuProbe

    section = Section("가속기 — GPU 가 필요한 기능")
    probe = facts.gpu_probe
    if probe is GpuProbe.ANSWERED and (facts.gpu_count or 0) > 0:
        section.checks.append(Check(
            "NVIDIA GPU", STATUS_OK,
            detail=f"nvidia-smi 응답, {facts.gpu_count}개",
            requirement="AI-B-04"))
    elif probe is GpuProbe.TOOL_FAILED:
        section.checks.append(Check(
            "NVIDIA GPU", STATUS_BLOCKED,
            detail=f"nvidia-smi 가 있는데 답하지 못한다 ({facts.gpu_probe_detail})",
            impact="GPU 가속 기능이 전부 CPU 로 내려간다. 느리지만 **동작은 한다**",
            # 이것이 현장에서 확인된 모양이다.
            remedy="네이티브 리눅스에서 드라이버가 충돌하는 알려진 경우다. GPU 가 "
                   "필요하면 Windows 의 Docker Desktop 또는 WSL2 에서 띄운다",
            requirement="AI-C-15"))
    elif probe is GpuProbe.TOOL_ABSENT:
        section.checks.append(Check(
            "NVIDIA GPU", STATUS_DEGRADED,
            detail="nvidia-smi 가 없다 — 이 기계에 NVIDIA 가속기가 없다는 뜻이다",
            impact="GPU 가속 기능이 CPU 로 내려간다. 핵심 기능은 그대로 돈다",
            remedy="필요 없으면 할 일이 없다", requirement="AI-C-05"))
    else:
        section.checks.append(Check(
            "NVIDIA GPU", STATUS_DEGRADED,
            detail=f"가속기 0개 (probe={getattr(probe, 'value', probe)})",
            impact="GPU 가속 기능이 CPU 로 내려간다", requirement="AI-C-05"))

    section.checks.append(Check(
        "이번 실행이 쓸 device", STATUS_OK, detail=default_device(),
        impact=("" if not gpu_use_declined()
                else f"{NO_GPU_ENV} 가 켜져 있어 가속기를 쓰지 않는다 — "
                     "노드 태그는 가속기가 있다고 그대로 보고한다"),
        requirement="AI-B-04"))

    # **조용히 틀리는 함정.** 되는 것처럼 보이는 것이 안 되는 것보다 나쁘다.
    section.checks.append(Check(
        "CUDA_VISIBLE_DEVICES 숨김", STATUS_BLOCKED if _cuda_hidden() else STATUS_OK,
        detail="빈 값으로 설정됨" if _cuda_hidden() else "설정되지 않음",
        impact=("CUDA 휠이 깔린 기계에서 GPU 를 이렇게 숨기면 NVBLAS 가 CPU BLAS 를 "
                "가로채 **예외 없이 틀린 값**을 낸다"
                if _cuda_hidden() else ""),
        remedy=("이 변수를 지우고, 가속기를 쓰지 않으려면 "
                f"{NO_GPU_ENV}=1 을 쓴다 — 그쪽은 고르는 쪽만 바꾸고 계산을 바꾸지 않는다"
                if _cuda_hidden() else ""),
        requirement="AI-B-01"))
    return section


# ── 선택 기능 ───────────────────────────────────────────────────────────────

def _optional() -> Section:
    section = Section("선택 기능 — 없으면 그 기능만 꺼진다(AI-C-05)")
    for module, label, impact, remedy in (
        ("paho.mqtt", "MQTT 전송", "말단↔엣지 업무·제어 경로가 비활성",
         'pip install -e ".[mqtt]"'),
        ("kafka", "Kafka 전송", "중앙 ingest 경로가 비활성", 'pip install -e ".[kafka]"'),
        ("redis", "Redis 스트림 입력", "데모 스택의 탐지 입력이 비활성",
         'pip install -e ".[redis]"'),
        ("opentelemetry", "OpenTelemetry 관측", "관측 내보내기가 비활성",
         'pip install -e ".[otel]"'),
        ("onnxruntime", "ONNX 추론", "ONNX 기반 인지·깊이 provider 가 비활성",
         "pip install onnxruntime"),
        ("torch", "PyTorch", "torch 기반 provider 가 비활성", "pip install torch"),
    ):
        present = _importable(module)
        section.checks.append(Check(
            label, STATUS_OK if present else STATUS_DEGRADED,
            impact="" if present else impact,
            remedy="" if present else remedy, requirement="AI-C-05"))

    # ultralytics 는 **라이센스가 다르다**. 그 사실을 설치 시점에 알린다.
    present = _importable("ultralytics")
    section.checks.append(Check(
        "ultralytics 탐지기(AGPL-3.0)", STATUS_OK if present else STATUS_DEGRADED,
        detail="설치됨" if present else "설치되지 않음",
        impact="" if present else "YOLO-World·YOLOE·FastSAM provider 가 비활성",
        remedy=("" if present else
                "pip install ultralytics — **AGPL-3.0 이다.** 이 패키지를 쓰는 "
                "서비스를 네트워크로 제공하면 그 결합 저작물에 소스 공개 의무가 "
                "따른다. 기본 배포에 넣지 않은 이유가 그것이고, 쓰기로 하는 것은 "
                "받는 쪽의 선택이다"),
        requirement="AI-C-16"))
    return section


def _tools() -> Section:
    section = Section("외부 도구 — 그 경로만 비활성")
    for binary, label, impact, remedy in (
        ("kubectl", "kubectl (오케스트레이터 배치)",
         "K3s 실행영역 배치가 비활성. 로컬 supervisor 로 그대로 돈다",
         "k3s 또는 kubectl 설치"),
        ("mosquitto", "mosquitto (로컬 브로커)",
         "실제 브로커 통합 시험만 skip", "apt install mosquitto"),
        ("ssh", "ssh (말단 배포)", "원격 말단 배포·링크 측정이 비활성", "openssh-client"),
        ("docker", "docker (이미지 빌드)", "컨테이너 패키징이 비활성", "docker 설치"),
    ):
        present = shutil.which(binary) is not None
        section.checks.append(Check(
            label, STATUS_OK if present else STATUS_DEGRADED,
            impact="" if present else impact,
            remedy="" if present else remedy, requirement="AI-B-11"))
    return section


def _assets() -> Section:
    """모델 가중치. **없는 것이 정상 상태다** — 받는 쪽이 자기 것을 쓴다."""
    section = Section("모델 자산 — 없으면 그 provider 만 비활성")
    try:
        from mission_runtime.edge.detector_catalog import characteristics
    except ImportError:
        section.checks.append(Check(
            "탐지기 카탈로그", STATUS_DEGRADED, detail="선언을 읽을 수 없다",
            impact="어떤 탐지기를 쓸 수 있는지 알 수 없다", requirement="AI-C-18"))
        return section

    root = _asset_root()
    if root is None:
        section.checks.append(Check(
            "자산 뿌리", STATUS_DEGRADED, detail="설정되지 않음",
            impact="선언된 가중치를 찾지 않는다 — 탐지 provider 가 비활성",
            remedy="MISSION_RUNTIME_ASSETS 로 가중치 뿌리를 가리킨다",
            requirement="AI-C-16"))
        return section
    for row in characteristics(asset_root=root):
        present = row.get("weights_present")
        if present is None:
            status, detail = STATUS_DEGRADED, "로컬 경로가 선언되지 않음(허브 스냅샷)"
        elif present:
            status, detail = STATUS_OK, str(row.get("weights", {}).get("path", ""))
        else:
            status, detail = STATUS_DEGRADED, "선언된 가중치가 이 노드에 없다"
        section.checks.append(Check(
            f"탐지기 {row.get('implementation_ref')}", status, detail=detail,
            impact="" if status == STATUS_OK else "그 후보만 선택에서 빠진다",
            remedy="" if status == STATUS_OK else "가중치를 자산 뿌리에 둔다",
            requirement="AI-C-18"))
        if row.get("outbound_network_required"):
            section.checks.append(Check(
                f"  └ {row.get('implementation_ref')} 외부 연결",
                STATUS_DEGRADED, detail="이 후보는 나가는 연결이 필요하다",
                impact="폐쇄망 배치에서는 쓸 수 없다",
                remedy="자산을 내부 저장소에서 조달한다", requirement="AI-C-16"))
    return section


# ── 조립 ────────────────────────────────────────────────────────────────────

def report() -> dict:
    from mission_runtime.runtime.environment_profile import observe_environment

    facts = observe_environment()
    sections = [_core(), _platform(facts), _accelerator(facts),
                _optional(), _tools(), _assets()]
    rows = [c for s in sections for c in s.checks]
    blocked = [c for c in rows if c.status == STATUS_BLOCKED]
    return {
        "sections": [{"title": s.title, "checks": [c.as_dict() for c in s.checks]}
                     for s in sections],
        # 요약은 세 수다. 핵심이 막힌 것과 선택이 줄어든 것을 한 수로 합치지 않는다.
        "summary": {
            "ok": sum(1 for c in rows if c.status == STATUS_OK),
            "degraded": sum(1 for c in rows if c.status == STATUS_DEGRADED),
            "blocked": len(blocked),
        },
        # **핵심이 막혔는가.** 선택 기능 결손은 여기 들어오지 않는다(AI-C-05).
        "can_start": not blocked,
        "blocking": [c.name for c in blocked],
    }


_MARK = {STATUS_OK: "o", STATUS_DEGRADED: "~", STATUS_BLOCKED: "x"}


def render(body: dict) -> str:
    lines: list[str] = []
    for section in body["sections"]:
        lines.append("")
        lines.append(section["title"])
        lines.append("-" * len(section["title"]))
        for check in section["checks"]:
            mark = _MARK.get(check["status"], "?")
            detail = f"  {check['detail']}" if check.get("detail") else ""
            lines.append(f"  [{mark}] {check['name']}{detail}")
            if check.get("impact"):
                lines.append(f"        줄어드는 것: {check['impact']}")
            if check.get("remedy"):
                lines.append(f"        얻는 방법:   {check['remedy']}")
    summary = body["summary"]
    lines.append("")
    lines.append(f"정상 {summary['ok']} · 축소 {summary['degraded']} · 막힘 {summary['blocked']}")
    if body["can_start"]:
        lines.append("핵심 기능은 그대로 뜬다. '축소' 는 그 기능만 꺼지는 정상 상태다.")
    else:
        lines.append("먼저 해결해야 하는 것: " + ", ".join(body["blocking"]))
    return "\n".join(lines)


def _importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _cuda_hidden() -> bool:
    import os

    return "CUDA_VISIBLE_DEVICES" in os.environ and not os.environ["CUDA_VISIBLE_DEVICES"].strip()


def _asset_root():
    import os

    override = os.environ.get("MISSION_RUNTIME_ASSETS")
    if override:
        return Path(override)
    default = PROJECT_DIR.parent / "local"
    return default if default.is_dir() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="기계가 읽는 한 덩어리")
    args = parser.parse_args(argv)

    body = report()
    print(json.dumps(body, ensure_ascii=False, indent=2) if args.json else render(body))
    # 핵심이 막혔을 때만 0 이 아니다. 선택 기능 결손으로 실패하면 설치 스크립트가
    # 정상 배치를 거부한다.
    return 0 if body["can_start"] else 1


if __name__ == "__main__":
    sys.exit(main())
