"""Runnable walkthrough of the currently-implemented AI framework features.

pytest tells you pass/fail; this script prints *what actually happens*
so it's easy to see the behavior with your own eyes. Run:

    cd ai-framework
    python examples/demo.py

Each section is independent and prints its own before/after so you can
read top to bottom.
"""

from __future__ import annotations

import sys

if sys.stdout.encoding is None or sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console default codepage otherwise mangles Korean output

import numpy as np
import cv2

from ai_framework.contracts.capability import CapabilityRequirement
from ai_framework.contracts.profile import CompatibilityProfile, ResourceBudget, ResourceCost
from ai_framework.decision.subtask import SubtaskGenerator, ZoneRule
from ai_framework.decision.validator import SubtaskValidator, ValidationContext
from ai_framework.edge.calibration import CameraCalibrator
from ai_framework.perception.tracking import Detection, IouTracker
from ai_framework.providers.fakes import StubAIRuntimeProvider
from ai_framework.reference.local_safety import LocalSafetyJudge
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from ai_framework.risk.fsm import RiskAnalysisFsm, RiskEvent
from ai_framework.selection.selector import CapabilitySelector


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def add_provider(registry: CapabilityRegistry, kind: str, provider_id: str = "p") -> None:
    registry.register_local(
        ProviderRegistration(capability_kind=kind, provider_id=provider_id, version="1")
    )


# ---------------------------------------------------------------------------
section("1. AI-N-01 로컬 안전 판단 -- 선택 기능이 하나씩 사라질 때")
# ---------------------------------------------------------------------------
registry = CapabilityRegistry()
judge = LocalSafetyJudge(registry)

print("영상 입력조차 없음 ->", judge.judge().state.value)

add_provider(registry, "media.video_input")
print("영상만 있음        ->", judge.judge().state.value)

for kind in ("perception.classify", "perception.track", "perception.distance"):
    add_provider(registry, kind)
print("전체 기능 다 있음  ->", judge.judge().state.value)

registry.unregister_local("perception.distance", "p")
print("거리추정 기능 소실 ->", judge.judge().state.value, "(크래시 없이 한 단계만 저하)")

registry.unregister_local("media.video_input", "p")
print("영상 입력 소실     ->", judge.judge().state.value, "(필수 입력 소실 -> 보수적 고정 상태)")


# ---------------------------------------------------------------------------
section("2. AI-D-01/02 서브태스크 생성 + 검증")
# ---------------------------------------------------------------------------
zone_rules = {
    "zone-a": ZoneRule("zone-a", allowed_actions=("inspect",)),
    "zone-b": ZoneRule("zone-b", forbidden_conditions=("flooded",), allowed_actions=("inspect",)),
}
subtasks = SubtaskGenerator().generate(("inspect",), zone_rules, active_conditions={"flooded"})
print(f"생성된 서브태스크: {[(s.zone_id, s.action) for s in subtasks]}")
print("  (zone-b는 flooded 조건이 활성화돼 있어 생성되지 않음)")

ctx = ValidationContext(
    known_zone_ids={"zone-a"},
    active_conditions=set(),
    known_facts=set(),  # 아직 아무 사전조건도 확인되지 않음
    robot_resources={"battery_pct": 80},
)
result = SubtaskValidator().validate(subtasks[0], ctx)
print(f"검증 결과: executable={result.executable}, missing_evidence={result.missing_evidence}")
print("  (전제조건이 아직 확인되지 않아 실행 불가로 표시 + 필요한 근거를 알려줌)")


# ---------------------------------------------------------------------------
section("3. AI-S-01 객체 추적 -- IOU 기반, 가려짐에도 ID 유지")
# ---------------------------------------------------------------------------
tracker = IouTracker(max_missed_frames=1)
t1 = tracker.update([Detection(box=(0, 0, 10, 10))])
print(f"frame 1: track_id={t1[0].track_id}, box={t1[0].box}")

t2 = tracker.update([])  # 잠깐 가려짐 (탐지 실패)
print(f"frame 2 (탐지 없음): 현재 추적 중인 트랙 수={len(t2)} (아직 유지)")

t3 = tracker.update([Detection(box=(2, 2, 12, 12))])
print(f"frame 3: track_id={t3[0].track_id} (frame 1과 동일 ID 유지됨)")


# ---------------------------------------------------------------------------
section("4. AI-R-01 위험 분석 FSM -- 등록된 이벤트만 인식, 상태 전이")
# ---------------------------------------------------------------------------
fsm = RiskAnalysisFsm({"water_level"})
for severity in (0.1, 0.5, 0.9, 0.1, 0.1):
    state = fsm.process(RiskEvent("water_level", severity))
    print(f"severity={severity:.1f} -> {state.value}")
print("등록 안 된 센서 이벤트 주입 ->", fsm.process(RiskEvent("unregistered_sensor", 0.99)).value, "(무시됨)")


# ---------------------------------------------------------------------------
section("5. AI-B-08/AI-C-04 Provider 교체 -- 상위 코드는 그대로")
# ---------------------------------------------------------------------------
def call_upper_layer(runtime, capability_kind, inputs):
    return runtime.infer(capability_kind, inputs)


local_model = StubAIRuntimeProvider(("perception.classify",), lambda k, x: f"local-result({x})")
remote_model = StubAIRuntimeProvider(("perception.classify",), lambda k, x: f"remote-result({x})")
print("로컬 provider  :", call_upper_layer(local_model, "perception.classify", "frame#1"))
print("원격 provider  :", call_upper_layer(remote_model, "perception.classify", "frame#1"))
print("  (같은 call_upper_layer 함수가 provider만 바뀌어도 그대로 동작)")


# ---------------------------------------------------------------------------
section("6. AI-B-01/04/06/AI-C-13 자원 기반 provider 선택 + 단계적 축소")
# ---------------------------------------------------------------------------
sel_registry = CapabilityRegistry()
sel_registry.register_local(
    ProviderRegistration(
        "risk.timeseries_model", "heavy", "1",
        compatibility=CompatibilityProfile(priority=1, cost=ResourceCost(compute_units=100)),
    )
)
sel_registry.register_local(
    ProviderRegistration(
        "risk.rule_based", "cheap", "1",
        compatibility=CompatibilityProfile(priority=1, cost=ResourceCost(compute_units=1)),
    )
)
selector = CapabilitySelector(sel_registry)
result = selector.select_with_degrade(
    ["risk.timeseries_model", "risk.rule_based"], node_tags=set(), budget=ResourceBudget(5, 64)
)
print(f"예산 부족(5 unit) -> 선택된 provider: {result.provider.provider_id} ({result.reason})")
print("  (고비용 timeseries 모델은 예산 초과라 자동으로 저렴한 규칙기반으로 축소)")


# ---------------------------------------------------------------------------
section("7. AI-E-02 카메라 캘리브레이션 -- 실제 카메라 없이 합성 데이터로 검증")
# ---------------------------------------------------------------------------
K_true = np.array([[800.0, 0, 320.0], [0, 800.0, 240.0], [0, 0, 1.0]])
dist_true = np.array([0.05, -0.03, 0.0, 0.0, 0.0])

rng = np.random.default_rng(0)
objp = np.zeros((6 * 9, 3), np.float32)
objp[:, :2] = np.mgrid[0:6, 0:9].T.reshape(-1, 2) * 0.03
objp[:, 0] -= objp[:, 0].mean()
objp[:, 1] -= objp[:, 1].mean()

object_points, image_points = [], []
for _ in range(12):
    rvec = rng.uniform(-0.2, 0.2, size=3)
    tvec = np.array([rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05), rng.uniform(0.5, 0.9)])
    imgp, _ = cv2.projectPoints(objp, rvec, tvec, K_true, dist_true)
    object_points.append(objp)
    image_points.append(imgp.reshape(-1, 2).astype(np.float32))

estimate = CameraCalibrator(max_acceptable_rms=1.0).estimate(object_points, image_points, (640, 480))
print(f"실제 초점거리 fx={K_true[0,0]:.1f} vs 복원된 fx={estimate.camera_matrix[0,0]:.3f}")
print(f"재투영 오차 RMS={estimate.reprojection_error_rms:.6f}px, stable={estimate.stable}")

print("\n" + "=" * 70)
print("데모 끝. 실제 자동 검증은 `pytest -q`로 실행하세요 (110개 테스트).")
print("=" * 70)
