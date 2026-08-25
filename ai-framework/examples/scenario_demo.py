"""최종 데모: 하드웨어 없이 프레임워크의 5가지 성질을 한 흐름으로 보여준다.

실행:  PYTHONPATH=. python3 examples/scenario_demo.py

이 데모는 정확도를 보여주지 않는다. 보여주는 것은 다음 다섯 질문에 대한 답이다.
  ① 새로운 것을 꽂아도 핵심 코드를 안 고치는가?
  ② 일부 기능이 없어져도 나머지가 계속 도는가?
  ③ 실행 환경이 바뀌면 자동으로 재구성되는가?
  ④ 로봇·감시·하천이 동일 프레임워크로 돌아가는가?
  ⑤ 전송·관측·제어 계층이 서로 섞이지 않는가?
  ⑥ 폐쇄망·보안 오버레이·서버/엣지 제어면 경계가 상위 로직 밖에 있는가?
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_framework.common.data_plane import DataKind, DataPlaneViolation
from ai_framework.contracts.capability import CapabilityRequirement
from ai_framework.contracts import data_dictionary as dd
from ai_framework.contracts.profile import CompatibilityProfile, ResourceCost
from ai_framework.contracts.profile_loader import load_profile
from ai_framework.execution.control import LocalControlSupervisor
from ai_framework.providers.fakes import (
    InMemoryObservabilityProvider,
    InMemoryTransportProvider,
    SyntheticMediaSourceProvider,
)
from ai_framework.providers.overlay import OverlayAwareRemoteGate, StaticOverlayProvider
from ai_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from ai_framework.runtime.airgap import AirgapPolicy, AssetRef, AssetResolver, ExternalDependency
from ai_framework.runtime.application import CapabilitySpec, ZoneApplication
from ai_framework.runtime.clusters import ClusterBinding, MultiClusterControlProvider, PlacementRequest
from ai_framework.runtime.reconfiguration import ResourceAdaptiveReconfigurer, ResourceSnapshot
from ai_framework.simulation.backend import BackendAvailabilityIntegrator
from ai_framework.simulation.sources import ScriptedSeriesSource
from ai_framework.simulation.terminals import VirtualRiverTerminal, VirtualRobotTerminal

PROFILE_DIR = Path(__file__).resolve().parents[1] / "profiles"
TOTAL_COMPUTE, TOTAL_MEMORY = 30.0, 4096.0

SPECS = [
    CapabilitySpec("safety.local_judgment", is_core=True),
    CapabilitySpec("perception.detect", is_core=True, degrade_rank=0),
    CapabilitySpec("perception.track", degrade_rank=1),
    CapabilitySpec("perception.associate", degrade_rank=2),
    CapabilitySpec("decision.subtask_generate", degrade_rank=3),
    CapabilitySpec("decision.subtask_validate", degrade_rank=4),
    CapabilitySpec("media.video_input", degrade_rank=5),
    CapabilitySpec("risk.state_machine", degrade_rank=6),
    CapabilitySpec("risk.rule_based", degrade_rank=7),
    CapabilitySpec("observation.adaptive", degrade_rank=8),
]


def banner(number: int, title: str) -> None:
    print("\n" + "=" * 72)
    print(f"{number}. {title}")
    print("=" * 72)


def register(registry, kind, provider_id, *, compute=3.0, hw_tags=(), health=None, priority=50):
    registry.register_local(
        ProviderRegistration(
            capability_kind=kind,
            provider_id=provider_id,
            version="1",
            compatibility=CompatibilityProfile(
                required_hw_tags=hw_tags,
                priority=priority,
                cost=ResourceCost(compute_units=compute, memory_mb=256.0),
            ),
            requirement=CapabilityRequirement(),
            health_check=health,
        )
    )


def show(app) -> None:
    for kind, state in sorted(app.snapshot().items()):
        print(f"    {kind:32s} {state}")


def snapshot(cpu: float) -> ResourceSnapshot:
    return ResourceSnapshot(cpu, 0.3, TOTAL_COMPUTE, TOTAL_MEMORY)


# ---------------------------------------------------------------- 1 ~ 4
banner(1, "Robot Profile로 시스템 실행 (AI-C-15)")
registry = CapabilityRegistry()
robot_profile = load_profile(PROFILE_DIR / "robot.json")
print(f"  도메인: {robot_profile.domain_id}")
print(f"  활성 capability: {list(robot_profile.active_capability_kinds)}")

banner(2, "가상 Robot + Camera 자동 등록 (AI-C-04, AI-C-10)")
transport = InMemoryTransportProvider()
observability = InMemoryObservabilityProvider()
media = SyntheticMediaSourceProvider("virtual_camera_01", frames=[b"frame"] * 10)
robot = VirtualRobotTerminal(
    "virtual_robot_01", transport, observability=observability, media_source=media
)
robot.start()
register(registry, "safety.local_judgment", "onboard-safety", compute=2.0)
register(registry, "perception.detect", "cpu-detector", compute=4.0)
register(registry, "perception.track", "iou-tracker", compute=3.0)
register(registry, "decision.subtask_generate", "planner", compute=3.0)
register(registry, "decision.subtask_validate", "validator", compute=2.0)
register(registry, "media.video_input", "virtual_camera_01", compute=1.0)
print(f"  등록된 capability kind 수: {len(registry.known_capability_kinds())}")

banner(3, "Capability Registry가 기능 탐색 → 실행 구성 결정 (AI-B-01, AI-C-13)")
app = ZoneApplication(robot_profile, registry, SPECS, node_tags={"cpu"})
reconfigurer = ResourceAdaptiveReconfigurer(app, observability)
reconfigurer.apply_snapshot(snapshot(0.20))
show(app)

banner(4, "인지·추적 실행 + 데이터 경로 분리 확인 (AI-C-14)")
robot.publish_observation("robot_position", [1.0, 2.0])
robot.report_metric("cpu_usage", 22.0)
robot.report_event("optional_capability_lost", "warning", {"kind": "perception.depth"})
robot.send_media_frame()
print(f"  업무 평면(MQTT)   : {[t for t, _, _ in transport.published]}")
print(f"  관측 평면(metric) : {[n for n, _, _ in observability.metrics]}")
print(f"  관측 평면(event)  : {[e.name for e in observability.events if e.name != 'capability_state_changed']}")
print(f"  미디어 평면       : {robot.sent_media_frames} frame(s) — 업무 payload에는 픽셀 없음")
try:
    robot.publish_observation("camera_frame", "pixels", kind=DataKind.VIDEO_FRAME)
except DataPlaneViolation as exc:
    print(f"  영상의 업무 평면 진입 시도 → 거부됨: {exc}")

# ---------------------------------------------------------------- 5 ~ 7
banner(5, "선택 Provider 강제 종료 → 해당 기능만 축소 (AI-C-11, AI-B-07)")
tracker_alive = {"ok": True}
registry.unregister_local("perception.track", "iou-tracker")
register(registry, "perception.track", "iou-tracker", compute=3.0, health=lambda: tracker_alive["ok"])
reconfigurer.apply_snapshot(snapshot(0.20))
tracker_alive["ok"] = False
reconfigurer.apply_snapshot(snapshot(0.20))
show(app)
print(f"  핵심 기능 유지 여부: {app.core_kinds_running()}")

banner(6, "CPU 강제 포화 → 선택 기능 자동 축소 (AI-B-06)")
tracker_alive["ok"] = True
reconfigurer.apply_snapshot(snapshot(0.20))
before = app.snapshot()
reconfigurer.apply_snapshot(snapshot(0.75))
show(app)
print(f"  축소 전 실행 수 {sum(1 for s in before.values() if s != 'DISABLED')}"
      f" → 축소 후 {len(app.running_kinds())}, 핵심 유지 {app.core_kinds_running()}")
reconfigurer.apply_snapshot(snapshot(0.20))
print(f"  자원 회복 후 복구 완료: 실행 {len(app.running_kinds())}개")

banner(7, "새 Camera Provider 동적 추가 → Core 수정 없이 활성화 (AI-B-09)")
register(registry, "media.video_input", "thermal_camera_B", compute=1.0, priority=10)
reconfigurer.apply_snapshot(snapshot(0.20))
resolution = app.resolve(snapshot(0.20).to_budget())["media.video_input"]
print(f"  media.video_input 담당 provider: {resolution.provider.provider_id}")
print("  (핵심 코드 변경 0줄 — 등록만 했다)")

# ---------------------------------------------------------------- 8 ~ 12
banner(8, "Robot Profile 종료")
print(f"  종료 시점 실행 기능: {len(app.running_kinds())}개")

banner(9, "River Profile로 변경 — 프로그램은 그대로 (AI-C-15)")
river_profile = load_profile(PROFILE_DIR / "river.json")
river_registry = CapabilityRegistry()
register(river_registry, "risk.state_machine", "risk-fsm", compute=2.0)
register(river_registry, "risk.rule_based", "threshold-rules", compute=2.0)
register(river_registry, "perception.detect", "cpu-detector", compute=4.0)
register(river_registry, "observation.adaptive", "adaptive-observer", compute=1.0)
river_app = ZoneApplication(river_profile, river_registry, SPECS, node_tags={"cpu"})
river_reconfigurer = ResourceAdaptiveReconfigurer(river_app, observability)
river_reconfigurer.apply_snapshot(snapshot(0.20))
print(f"  도메인: {river_profile.domain_id}")
show(river_app)

banner(10, "가상 수위 Sensor 등록 (CSV/스크립트 replay)")
river_transport = InMemoryTransportProvider()
river_terminal = VirtualRiverTerminal(
    "virtual_river_01",
    river_transport,
    sources={
        "water_level": ScriptedSeriesSource("water_level", [1.1, 1.8, 2.4, 3.1]),
        "rainfall": ScriptedSeriesSource("rainfall", [0.0, 5.0, 22.0, 40.0]),
    },
)
river_terminal.start()
for _ in range(4):
    print(f"    {river_terminal.pump_once()}")

banner(11, "동일 Framework에서 Risk 기능 활성화 (AI-R-01)")
from ai_framework.risk.fsm import RiskAnalysisFsm, RiskEvent  # noqa: E402

fsm = RiskAnalysisFsm(registered_event_kinds={"water_level", "rainfall"})
for level in (1.1, 2.4, 3.1):
    state = fsm.process(RiskEvent("water_level", level))
    print(f"    water_level={level} → 위험 분석 상태 {state.value}")

banner(12, "위험 상황 → 관측 수준 상향 + 제어 명령은 백엔드 책임 (AI-R-03/04)")
backend = BackendAvailabilityIntegrator()
backend.report("virtual_river_01", task_transport_alive=True, observability_alive=False)
verdict = backend.verdict("virtual_river_01")
print(f"  백엔드 통합 판정: availability={verdict.availability.value}, observability={verdict.observability.value}")
print("  (관측만 죽었을 뿐 업무 세션은 살아 있으므로 UNAVAILABLE 아님 — AI-O-04)")
river_transport.subscribe(river_terminal.command_topic, lambda payload: None)
river_transport.publish(
    river_terminal.command_topic,
    json.dumps({"command_id": "c-1", "command": "CLOSE_FLOOD_WALL", "params": {}}).encode(),
)
print(f"  제어 명령 실행 결과: {[(r.outcome.value, r.reason) for r in river_terminal.command_log]}")
print(f"  액추에이터 상태: flood_wall={river_terminal.state.get('flood_wall')}")

# ---------------------------------------------------------------- 13 ~ 15
banner(13, "공통 데이터 사전으로 payload 이름 확인 (AI-C-01)")
sample_payload = dd.assert_known(
    {
        dd.DEVICE_ID: "virtual_river_01",
        dd.OBSERVED_AT: 1720000000.0,
        dd.OBSERVATION_NAME: "water_level",
        dd.OBSERVATION_VALUE: 3.1,
        dd.RISK_STATE: fsm.state.value,
    }
)
print(f"  사전에 등록된 payload field: {list(sample_payload)}")
print(f"  관측 평면 field 예: {dd.TRACE_ID}, {dd.OVERLAY_STATE}")

banner(14, "폐쇄망 배치 검증 + 선택 외부 서비스만 축소 (AI-C-16)")
resolver = AssetResolver(
    base_locations={
        "image": "https://registry.internal.example/ai",
        "model": "https://artifacts.internal.example/models",
        "generic": "/var/lib/ai-framework/assets",
    },
    internal_hosts=frozenset({"registry.internal.example", "artifacts.internal.example"}),
    internal_suffixes=frozenset({".internal"}),
)
model = resolver.resolve(AssetRef("risk-rules", kind="model", version="2"))
policy = AirgapPolicy(resolver)
verdict = policy.evaluate(
    "river-risk-worker",
    [
        ExternalDependency("kafka://server.internal:9092", optional=False),
        ExternalDependency("https://api.external-ai.example/v1", purpose="optional-vlm", optional=True),
    ],
)
print(f"  내부 모델 위치: {model.location}")
print(f"  배치 가능: {verdict.placeable}, 비활성화된 선택 의존성: {list(verdict.disabled_optional)}")

banner(15, "보안 오버레이 + 서버/엣지 제어면 라우팅 (AI-C-17, AI-B-11)")
overlay = StaticOverlayProvider(connected=True, peers={"server-1": True})
gate = OverlayAwareRemoteGate(overlay)
print(f"  server-1 원격 기능 선택 가능: {gate.may_select('server-1', backend_integrated_available=True)}")
overlay.set_connected(False)
print(f"  오버레이 단절 사유: {gate.unavailable_reason('server-1', backend_integrated_available=True)}")

server_plane = LocalControlSupervisor()
edge_plane = LocalControlSupervisor()
control = MultiClusterControlProvider(
    [
        ClusterBinding("server-cluster", server_plane, frozenset({"server", "central"})),
        ClusterBinding("edge-cluster-a", edge_plane, frozenset({"zone-edge", "local"})),
    ]
)
control.request("start", "central-aggregator", {"placement": PlacementRequest(frozenset({"server"}))})
control.request("start", "zone-risk-worker", {"placement": PlacementRequest(frozenset({"zone-edge"}))})
print(f"  central-aggregator 배치: {control.cluster_of('central-aggregator')}")
print(f"  zone-risk-worker 배치: {control.cluster_of('zone-risk-worker')}")

# ---------------------------------------------------------------- 16
banner(16, "코드 diff 확인 — Core code 변경 0")
indicators = Path(__file__).resolve().parents[2] / "reports" / "framework-indicators.json"
if indicators.exists():
    data = json.loads(indicators.read_text(encoding="utf-8"))
    for name, loc in data["extensibility_core_loc_changed"].items():
        print(f"    {name:28s} core LOC 변경 = {loc}")
    print(f"    잘못된 평면 라우팅 건수     = {data['transport_integrity']['wrong_plane_routing_count']}")
    print(
        f"    선택 provider 1개 소실 영향 = "
        f"{data['failure_isolation']['affected_by_one_optional_provider_loss']}"
        f" / {data['failure_isolation']['total_capabilities']}"
    )
else:
    print("    (지표 파일 없음 — `pytest tests/scenarios/test_framework_indicators.py` 실행 후 생성)")

print("\n" + "=" * 72)
print("데모 끝. 자동 검증은 `pytest -q tests/scenarios` 로 실행한다.")
print("=" * 72)
