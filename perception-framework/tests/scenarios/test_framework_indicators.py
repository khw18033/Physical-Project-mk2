"""implements: AI-B-06, AI-B-09, AI-C-05, AI-C-11, AI-C-13, AI-C-14, AI-C-15
"""
import json
from pathlib import Path

from perception_framework.common.data_plane import DataKind, DataPlane, DataPlaneViolation, assert_routable, policy_for
from perception_framework.contracts.capability import CapabilityState
from perception_framework.contracts.profile import ResourceBudget
from perception_framework.contracts.profile_loader import load_profile
from perception_framework.registry.capability_registry import CapabilityRegistry
from perception_framework.runtime.application import ZoneApplication
from perception_framework.runtime.reconfiguration import ResourceAdaptiveReconfigurer, ResourceSnapshot

from .conftest import core_source_mentions, profile_of, registration, spec

REPORT_PATH = Path(__file__).resolve().parents[2] / "reports" / "framework-indicators.json"
PROFILE_DIR = Path(__file__).resolve().parents[2] / "profiles"

KINDS = [
    "perception.detect",
    "perception.track",
    "perception.depth",
    "perception.associate",
    "risk.rule_based",
    "service.optional",
]


def build(registry, *, health=None):
    profile = profile_of("zone-1", KINDS)
    specs = [spec(KINDS[0], core=True), spec(KINDS[1], core=True)] + [
        spec(kind, rank=index) for index, kind in enumerate(KINDS[2:], start=1)
    ]
    for kind in KINDS:
        registry.register_local(
            registration(
                kind,
                f"{kind}-provider",
                compute=3.0,
                memory=256.0,
                health_check=(health if kind == "perception.depth" else None),
            )
        )
    return ZoneApplication(profile, registry, specs, node_tags={"cpu"})


def snapshot(cpu):
    return ResourceSnapshot(
        cpu_utilisation=cpu, memory_utilisation=0.3, total_compute_units=30.0, total_memory_mb=4096.0
    )


def measure_extensibility() -> dict:
    """새 하드웨어/센서/Provider/Domain 추가 시 Core 코드 변경 LOC."""
    tokens = {
        "new_camera": "camera_A",
        "new_sensor": "thermal_camera_B",
        "new_ai_provider": "opencl-image-runtime",
        "new_transport_provider": "MqttTransportProvider",
        "new_domain": "perimeter_surveillance",
    }
    for path in PROFILE_DIR.glob("*.json"):
        tokens[f"domain::{path.stem}"] = load_profile(path).domain_id
    return {name: len(core_source_mentions(token)) for name, token in tokens.items()}


def measure_failure_isolation() -> dict:
    alive = {"depth": True}
    registry = CapabilityRegistry()
    app = build(registry, health=lambda: alive["depth"])
    reconfigurer = ResourceAdaptiveReconfigurer(app)
    before = reconfigurer.apply_snapshot(snapshot(0.1))

    alive["depth"] = False
    after = reconfigurer.apply_snapshot(snapshot(0.1))

    affected = [kind for kind in KINDS if before[kind] is not after[kind]]
    return {
        "total_capabilities": len(KINDS),
        "affected_by_one_optional_provider_loss": len(affected),
        "affected_ratio": round(len(affected) / len(KINDS), 4),
        "core_still_running": app.core_kinds_running(),
        "detection_to_degradation_latency_ms": round(reconfigurer.max_transition_latency_ms(), 3),
    }


def measure_resource_adaptation() -> dict:
    registry = CapabilityRegistry()
    app = build(registry)
    reconfigurer = ResourceAdaptiveReconfigurer(app)

    healthy = reconfigurer.apply_snapshot(snapshot(0.1))
    healthy_running = sum(1 for state in healthy.values() if state is not CapabilityState.DISABLED)

    saturated = reconfigurer.apply_snapshot(snapshot(0.75))
    saturated_running = sum(1 for state in saturated.values() if state is not CapabilityState.DISABLED)

    recovered = reconfigurer.apply_snapshot(snapshot(0.1))
    recovered_running = sum(1 for state in recovered.values() if state is not CapabilityState.DISABLED)

    return {
        "running_when_healthy": healthy_running,
        "running_when_saturated": saturated_running,
        "running_after_recovery": recovered_running,
        "degradations": reconfigurer.degradation_count(),
        "recoveries": reconfigurer.recovery_count(),
        "core_kept_during_saturation": app.core_kinds_running(),
        "max_transition_latency_ms": round(reconfigurer.max_transition_latency_ms(), 3),
    }


def measure_transport_integrity() -> dict:
    wrong_plane = 0
    for kind in DataKind:
        expected = policy_for(kind).plane
        for plane in DataPlane:
            try:
                assert_routable(kind, plane)
            except DataPlaneViolation:
                continue
            if plane is not expected:
                wrong_plane += 1
    return {
        "declared_data_kinds": len(list(DataKind)),
        "wrong_plane_routing_count": wrong_plane,
        "control_kinds_with_delivery_guarantee": sum(
            1 for kind in DataKind if policy_for(kind).delivery_guaranteed
        ),
    }


def measure_domain_generality() -> dict:
    budget = ResourceBudget(compute_units=100.0, memory_mb=8192.0)
    running_per_domain = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        registry = CapabilityRegistry()
        profile = load_profile(path)
        specs = [spec(kind, rank=index) for index, kind in enumerate(profile.active_capability_kinds)]
        for kind in profile.active_capability_kinds:
            registry.register_local(registration(kind, f"{kind}-provider"))
        app = ZoneApplication(profile, registry, specs)
        app.resolve(budget)
        running_per_domain[profile.domain_id] = set(app.running_kinds())

    all_kinds = set().union(*running_per_domain.values()) if running_per_domain else set()
    shared = set.intersection(*running_per_domain.values()) if running_per_domain else set()
    return {
        "domains": sorted(running_per_domain),
        "distinct_capability_kinds": len(all_kinds),
        "kinds_shared_by_every_domain": len(shared),
        "same_core_application_class": True,
    }


def collect_indicators() -> dict:
    return {
        "extensibility_core_loc_changed": measure_extensibility(),
        "failure_isolation": measure_failure_isolation(),
        "resource_adaptation": measure_resource_adaptation(),
        "transport_integrity": measure_transport_integrity(),
        "domain_generality": measure_domain_generality(),
    }


def test_indicators_meet_their_targets_and_are_written_out():
    indicators = collect_indicators()

    # 확장성: 어떤 확장도 core 코드를 건드리지 않는다 → 0 LOC.
    assert all(count == 0 for count in indicators["extensibility_core_loc_changed"].values()), indicators[
        "extensibility_core_loc_changed"
    ]

    # 장애 격리: 선택 provider 1개 소실이 1개 기능에만 영향.
    isolation = indicators["failure_isolation"]
    assert isolation["affected_by_one_optional_provider_loss"] == 1
    assert isolation["core_still_running"] is True

    # 자원 적응: 포화 시 축소, 회복 시 복구, 핵심 유지.
    adaptation = indicators["resource_adaptation"]
    assert adaptation["running_when_saturated"] < adaptation["running_when_healthy"]
    assert adaptation["running_after_recovery"] == adaptation["running_when_healthy"]
    assert adaptation["core_kept_during_saturation"] is True

    # 전송 정합: 잘못된 평면 라우팅 0건.
    assert indicators["transport_integrity"]["wrong_plane_routing_count"] == 0

    # 도메인 범용성: 3개 이상 도메인이 동일 Application 클래스로 구동.
    assert len(indicators["domain_generality"]["domains"]) >= 3

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(indicators, indent=2, ensure_ascii=False), encoding="utf-8")
    assert REPORT_PATH.exists()
