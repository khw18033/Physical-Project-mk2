"""Scenario 1 — 새 센서/Provider Hot Plug
Scenario 2 — 실행 노드 환경 변경

tests for: AI-B-09, AI-C-04, AI-C-10, AI-C-12, AI-C-15, AI-B-01, AI-B-04
question: ① 새로운 것을 꽂아도 핵심 코드를 안 고치는가?
          ③ 실행 환경이 바뀌면 자동으로 재구성되는가?
"""

from ai_framework.contracts.capability import CapabilityState
from ai_framework.contracts.profile import ResourceBudget
from ai_framework.execution.conformance import check_provider_conformance

from .conftest import build_app, core_source_mentions, profile_of, registration, spec

# The "new hardware" introduced mid-run. Defined only here — in a real
# deployment it would live in an adapter package plus a manifest.
NEW_SENSOR_KIND = "sensor.thermal"
NEW_SENSOR_PROVIDER = "thermal_camera_B"


def test_s1_new_sensor_is_discovered_while_the_system_is_running(registry, ample_budget):
    profile = profile_of(
        "zone-1",
        ["perception.detect", "risk.rule_based", NEW_SENSOR_KIND],
    )
    specs = [
        spec("perception.detect", core=True),
        spec("risk.rule_based", rank=1),
        spec(NEW_SENSOR_KIND, rank=2),
    ]
    registry.register_local(registration("perception.detect", "camera_A"))
    registry.register_local(registration("risk.rule_based", "water_level_A"))
    app = build_app(profile, registry, specs, node_tags={"cpu"})

    before = app.resolve(ample_budget)
    assert before[NEW_SENSOR_KIND].state is CapabilityState.DISABLED
    assert before["perception.detect"].state is CapabilityState.ACTIVE

    # --- hot plug: only a registration happens, nothing is restarted ---
    registry.register_local(registration(NEW_SENSOR_KIND, NEW_SENSOR_PROVIDER))
    after = app.resolve(ample_budget)

    assert after[NEW_SENSOR_KIND].state is CapabilityState.ACTIVE
    assert after[NEW_SENSOR_KIND].provider.provider_id == NEW_SENSOR_PROVIDER
    # 기존 기능은 영향 없이 계속 실행 중 (AI-C-11).
    assert after["perception.detect"].state is CapabilityState.ACTIVE
    assert after["risk.rule_based"].state is CapabilityState.ACTIVE


def test_s1_new_provider_passes_the_same_conformance_gate(registry):
    """AI-B-09: 운영 등록 전 공통 인터페이스·격리 규칙 충족을 검증한다."""
    registry.register_local(registration("perception.detect", "camera_A"))

    report = check_provider_conformance(registration(NEW_SENSOR_KIND, NEW_SENSOR_PROVIDER), registry)

    assert report.passed, report.failures


def test_s1_core_code_never_mentions_the_new_hardware():
    """성공 조건: 기존 코드 수정 0줄. 정적으로 고정한다."""
    for token in (NEW_SENSOR_PROVIDER, "thermal", "camera_A", "water_level_A"):
        assert core_source_mentions(token) == [], f"core code references {token!r}"


def test_s1_removing_the_new_sensor_again_leaves_the_rest_running(registry, ample_budget):
    profile = profile_of("zone-1", ["perception.detect", NEW_SENSOR_KIND])
    specs = [spec("perception.detect", core=True), spec(NEW_SENSOR_KIND, rank=1)]
    registry.register_local(registration("perception.detect", "camera_A"))
    registry.register_local(registration(NEW_SENSOR_KIND, NEW_SENSOR_PROVIDER))
    app = build_app(profile, registry, specs, node_tags={"cpu"})
    app.resolve(ample_budget)

    registry.unregister_local(NEW_SENSOR_KIND, NEW_SENSOR_PROVIDER)
    after = app.resolve(ample_budget)

    assert after[NEW_SENSOR_KIND].state is CapabilityState.DISABLED
    assert app.core_kinds_running()


# --- Scenario 2 — node environment change --------------------------------


def test_s2_same_request_lands_on_cpu_or_accelerator_node_without_code_change(registry, ample_budget):
    """상위 코드는 'perception'만 요청하고, CPU인지 가속기인지 모른다."""
    profile = profile_of("zone-1", ["perception.detect"])
    specs = [spec("perception.detect", core=True)]
    registry.register_local(
        registration("perception.detect", "provider_A_cpu", priority=50, compute=2.0, hw_tags=("cpu",))
    )
    registry.register_local(
        registration("perception.detect", "provider_B_accel", priority=10, compute=1.0, hw_tags=("accel",))
    )

    edge_a = build_app(profile, registry, specs, node_tags={"cpu"})  # CPU=4, RAM=8GB, 가속기 없음
    edge_b = build_app(profile, registry, specs, node_tags={"cpu", "accel"})  # 가속기 보유

    on_a = edge_a.resolve(ample_budget)["perception.detect"]
    on_b = edge_b.resolve(ample_budget)["perception.detect"]

    assert on_a.provider.provider_id == "provider_A_cpu"
    assert on_b.provider.provider_id == "provider_B_accel"
    # 두 경우 모두 상위에서는 동일한 capability_kind 하나만 요청했다.
    assert on_a.kind == on_b.kind == "perception.detect"


def test_s2_node_upgraded_in_place_switches_provider_on_next_resolve(registry, ample_budget):
    profile = profile_of("zone-1", ["perception.detect"])
    specs = [spec("perception.detect", core=True)]
    registry.register_local(registration("perception.detect", "provider_A_cpu", priority=50, hw_tags=("cpu",)))
    registry.register_local(
        registration("perception.detect", "provider_B_accel", priority=10, hw_tags=("accel",))
    )
    app = build_app(profile, registry, specs, node_tags={"cpu"})
    assert app.resolve(ample_budget)["perception.detect"].provider.provider_id == "provider_A_cpu"

    app.set_node_tags({"cpu", "accel"})  # 하드웨어 교체/추가

    assert app.resolve(ample_budget)["perception.detect"].provider.provider_id == "provider_B_accel"


def test_s2_insufficient_node_keeps_the_capability_unplaced_not_crashed(registry):
    profile = profile_of("zone-1", ["perception.detect"])
    specs = [spec("perception.detect", core=True)]
    registry.register_local(registration("perception.detect", "heavy", compute=64.0, memory=8192.0))
    app = build_app(profile, registry, specs, node_tags={"cpu"})

    resolved = app.resolve(ResourceBudget(compute_units=2.0, memory_mb=512.0))

    # 필수 조건을 만족하는 노드가 없으면 해당 기능만 미배치 상태 (AI-B-04).
    assert resolved["perception.detect"].state is CapabilityState.DISABLED
    assert resolved["perception.detect"].reason == "no_compatible_provider_within_budget"
