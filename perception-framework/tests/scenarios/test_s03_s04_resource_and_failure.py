"""implements: AI-B-06, AI-B-07, AI-C-05, AI-C-11, AI-C-13, AI-O-02
"""
from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState
from perception_framework.providers.fakes import InMemoryObservabilityProvider
from perception_framework.runtime.reconfiguration import ResourceAdaptiveReconfigurer, ResourceSnapshot

from .conftest import build_app, profile_of, registration, spec

NODE = {"cpu"}
TOTAL_COMPUTE, TOTAL_MEMORY = 30.0, 4096.0


def four_capability_app(registry):
    """Core perception + tracking + additional analysis + optional service."""
    profile = profile_of(
        "zone-1",
        ["perception.detect", "perception.track", "perception.additional_analysis", "service.optional"],
    )
    specs = [
        spec("perception.detect", core=True),
        spec("perception.track", core=True, rank=0),
        spec("perception.additional_analysis", rank=1),
        spec("service.optional", rank=2),
    ]
    registry.register_local(registration("perception.detect", "detect-1", compute=4.0, memory=256))
    registry.register_local(registration("perception.track", "track-1", compute=3.0, memory=256))
    registry.register_local(
        registration("perception.additional_analysis", "analysis-1", compute=5.0, memory=512)
    )
    registry.register_local(registration("service.optional", "optional-1", compute=5.0, memory=512))
    return build_app(profile, registry, specs, node_tags=NODE)


def snapshot(cpu: float, memory: float = 0.4) -> ResourceSnapshot:
    """`cpu` is the load from *other* workloads, i.e. what is left over for
    these capabilities is (1 - cpu). Total declared cost of the four
    capabilities below is 17 units of 30."""
    return ResourceSnapshot(
        cpu_utilisation=cpu,
        memory_utilisation=memory,
        total_compute_units=TOTAL_COMPUTE,
        total_memory_mb=TOTAL_MEMORY,
    )


def test_s3_healthy_node_runs_every_declared_capability(registry):
    app = four_capability_app(registry)
    reconfigurer = ResourceAdaptiveReconfigurer(app)

    states = reconfigurer.apply_snapshot(snapshot(cpu=0.30))

    assert all(state is CapabilityState.ACTIVE for state in states.values())


def test_s3_cpu_saturation_sheds_optional_capabilities_lowest_priority_first(registry):
    app = four_capability_app(registry)
    observability = InMemoryObservabilityProvider()
    reconfigurer = ResourceAdaptiveReconfigurer(app, observability)
    reconfigurer.apply_snapshot(snapshot(cpu=0.30))

    states = reconfigurer.apply_snapshot(snapshot(cpu=0.75))  # 남은 여유 7.5 units

    # 핵심 기능은 유지, 선택 기능은 우선순위가 낮은 것부터 축소 (AI-B-06).
    assert states["perception.detect"] is CapabilityState.ACTIVE
    assert states["perception.track"] is CapabilityState.ACTIVE
    assert states["service.optional"] is CapabilityState.DISABLED
    assert app.core_kinds_running()
    # 상태 변화는 개별 사건으로 남는다 (AI-O-02).
    assert any(e.name == "capability_state_changed" for e in observability.events)


def test_s3_recovery_restores_the_shed_capabilities(registry):
    app = four_capability_app(registry)
    reconfigurer = ResourceAdaptiveReconfigurer(app)
    reconfigurer.apply_snapshot(snapshot(cpu=0.30))
    reconfigurer.apply_snapshot(snapshot(cpu=0.75))
    assert reconfigurer.degradation_count() >= 1

    states = reconfigurer.apply_snapshot(snapshot(cpu=0.30))

    assert all(state is CapabilityState.ACTIVE for state in states.values())
    assert reconfigurer.recovery_count() >= 1


def test_s3_extreme_saturation_reports_core_as_disabled_rather_than_hiding_it(registry):
    """자원이 정말 없으면 핵심 기능도 배치할 수 없다. 그 사실을 숨기지 않고
    DISABLED + 사유로 드러내는 것이 요구되는 동작이다 (AI-B-04, AI-O-02)."""
    app = four_capability_app(registry)
    observability = InMemoryObservabilityProvider()
    reconfigurer = ResourceAdaptiveReconfigurer(app, observability)
    reconfigurer.apply_snapshot(snapshot(cpu=0.30))

    states = reconfigurer.apply_snapshot(snapshot(cpu=0.97))  # 남은 여유 0.9 units

    assert states["perception.detect"] is CapabilityState.DISABLED
    assert not app.core_kinds_running()
    errors = [e for e in observability.events if e.severity == "error"]
    assert any(e.payload["capability_kind"] == "perception.detect" for e in errors)


def test_s3_optional_capabilities_do_not_consume_headroom_a_core_one_needs(registry):
    """핵심 기능이 배치되지 못한 상태에서 선택 기능이 자원을 쓰면 안 된다 (AI-B-06).

    Regression: 데모에서 core perception이 DISABLED인데 optional tracking이
    남은 여유로 계속 실행되는 상태가 발견됐다."""
    app = four_capability_app(registry)
    reconfigurer = ResourceAdaptiveReconfigurer(app)

    states = reconfigurer.apply_snapshot(snapshot(cpu=0.90))  # 남은 여유 3.0 < detect 4.0

    assert states["perception.detect"] is CapabilityState.DISABLED
    assert all(
        states[kind] is CapabilityState.DISABLED
        for kind in ("perception.additional_analysis", "service.optional")
    )


def test_s3_core_capabilities_are_never_shed_before_optional_ones(registry):
    app = four_capability_app(registry)
    reconfigurer = ResourceAdaptiveReconfigurer(app)

    states = reconfigurer.apply_snapshot(snapshot(cpu=0.70))

    running_optional = [
        kind
        for kind in ("perception.additional_analysis", "service.optional")
        if states[kind] is not CapabilityState.DISABLED
    ]
    if states["perception.detect"] is CapabilityState.DISABLED:
        assert not running_optional, "an optional capability outlived a core one"


# --- Scenario 4 — provider failure isolation ------------------------------


def test_s4_killing_an_optional_provider_disables_only_dependent_capabilities(registry):
    """depth 죽음 -> perception/tracking/decision은 계속 ACTIVE."""
    alive = {"depth": True}
    profile = profile_of(
        "zone-1",
        ["perception.detect", "perception.track", "perception.depth", "perception.environment_map"],
    )
    specs = [
        spec("perception.detect", core=True),
        spec("perception.track", core=True),
        spec("perception.depth", rank=1),
        # This capability *requires* depth, so it must go DISABLED with it.
        spec(
            "perception.environment_map",
            rank=2,
            requirement=CapabilityRequirement(required=("perception.depth",)),
        ),
    ]
    registry.register_local(registration("perception.detect", "detect-1"))
    registry.register_local(registration("perception.track", "track-1"))
    registry.register_local(
        registration("perception.depth", "depth-1", health_check=lambda: alive["depth"])
    )
    registry.register_local(registration("perception.environment_map", "mapper-1"))
    app = build_app(profile, registry, specs, node_tags=NODE)
    reconfigurer = ResourceAdaptiveReconfigurer(app)
    reconfigurer.apply_snapshot(snapshot(cpu=0.1))

    alive["depth"] = False  # kill the optional provider process
    states = reconfigurer.apply_snapshot(snapshot(cpu=0.1))

    assert states["perception.detect"] is CapabilityState.ACTIVE
    assert states["perception.track"] is CapabilityState.ACTIVE
    assert states["perception.depth"] is CapabilityState.DISABLED
    assert states["perception.environment_map"] is CapabilityState.DISABLED
    # 전체 재시작이 아니라 기능 단위 격리 (AI-C-11, AI-B-07).
    assert app.core_kinds_running()


def test_s4_failure_blast_radius_is_measured_and_small(registry):
    """지표: 선택 provider 1개 제거 시 영향받은 기능 수 / 전체 기능 수."""
    alive = {"depth": True}
    kinds = [
        "perception.detect",
        "perception.track",
        "perception.depth",
        "perception.associate",
        "risk.rule_based",
        "service.optional",
    ]
    profile = profile_of("zone-1", kinds)
    specs = [spec(kinds[0], core=True), spec(kinds[1], core=True)] + [
        spec(kind, rank=index) for index, kind in enumerate(kinds[2:], start=1)
    ]
    for kind in kinds:
        health = (lambda: alive["depth"]) if kind == "perception.depth" else None
        registry.register_local(registration(kind, f"{kind}-provider", health_check=health))
    app = build_app(profile, registry, specs, node_tags=NODE)
    reconfigurer = ResourceAdaptiveReconfigurer(app)
    before = reconfigurer.apply_snapshot(snapshot(cpu=0.1))

    alive["depth"] = False
    after = reconfigurer.apply_snapshot(snapshot(cpu=0.1))

    affected = [k for k in kinds if before[k] is not after[k]]
    assert affected == ["perception.depth"], affected
    assert len(affected) / len(kinds) <= 1 / 6


def test_s4_a_providers_own_health_probe_exploding_does_not_break_the_registry(registry):
    def exploding_probe():
        raise RuntimeError("probe crashed")

    registry.register_local(registration("perception.detect", "detect-1"))
    registry.register_local(registration("perception.depth", "depth-1", health_check=exploding_probe))

    # 등록·조회 자체가 죽지 않고, 문제 provider만 후보에서 빠진다 (AI-B-07).
    assert registry.available_providers("perception.depth") == []
    assert len(registry.available_providers("perception.detect")) == 1
