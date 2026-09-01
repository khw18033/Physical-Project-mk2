"""implements: AI-B-06, AI-C-10, AI-C-11, AI-N-01, AI-O-04
"""
from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState
from perception_framework.observability.availability import AvailabilitySignals, RemoteFeatureGate, SignalStatus
from perception_framework.providers.fakes import InMemoryTransportProvider
from perception_framework.providers.serialization import SerializationPolicy
from perception_framework.reference.local_safety import LocalSafetyJudge, SafetyState
from perception_framework.runtime.reconfiguration import ResourceAdaptiveReconfigurer, ResourceSnapshot
from perception_framework.simulation.terminals import VirtualRobotTerminal

from .conftest import build_app, profile_of, registration, spec

def _cmd(command_id: str) -> bytes:
    """AI-C-07: encode with the policy-selected format, not a literal JSON blob."""
    serializer = SerializationPolicy.default().serializer_for("control")
    return serializer.encode({"command_id": command_id, "command": "START_TASK"})


BUDGET = ResourceSnapshot(
    cpu_utilisation=0.1, memory_utilisation=0.2, total_compute_units=50.0, total_memory_mb=4096.0
)


def robot_app(registry, *, node_tags={"cpu"}):
    """말단에서 도는 구성: 로컬 안전은 core, 원격 보조 기능은 optional."""
    profile = profile_of("zone-1", ["safety.local_judgment", "perception.detect", "remote.analysis"])
    specs = [
        spec("safety.local_judgment", core=True),
        spec("perception.detect", core=True),
        spec("remote.analysis", rank=2),
    ]
    return build_app(profile, registry, specs, node_tags=node_tags)


def test_s5_terminal_stops_answering_when_partitioned(registry):
    transport = InMemoryTransportProvider()
    robot = VirtualRobotTerminal("virtual_robot_01", transport)
    robot.start()
    transport.publish(robot.command_topic, _cmd("c1"))
    assert robot.command_log

    robot.go_offline()
    robot.command_log.clear()
    transport.publish(robot.command_topic, _cmd("c2"))

    assert robot.command_log == []  # MQTT session lost 와 동일한 관측


def test_s5_local_safety_stays_active_while_remote_capabilities_are_dropped(registry):
    """로봇 측: Edge unavailable -> 원격 선택 기능만 비활성, Local Safety는 ACTIVE."""
    registry.register_local(registration("safety.local_judgment", "local-safety"))
    registry.register_local(registration("perception.detect", "onboard-detect"))
    remote_reachable = {"ok": True}
    registry.register_local(
        registration("remote.analysis", "edge-analysis", health_check=lambda: remote_reachable["ok"])
    )
    app = robot_app(registry)
    reconfigurer = ResourceAdaptiveReconfigurer(app)
    reconfigurer.apply_snapshot(BUDGET)

    remote_reachable["ok"] = False  # network partition to the edge
    states = reconfigurer.apply_snapshot(BUDGET)

    assert states["remote.analysis"] is CapabilityState.DISABLED
    assert states["safety.local_judgment"] is CapabilityState.ACTIVE
    assert app.core_kinds_running()


def test_s5_onboard_safety_judge_keeps_producing_a_state_without_any_network():
    """AI-N-01: 외부 네트워크·엣지 기능이 없어도 로컬 안전 판단은 계속된다."""
    from perception_framework.registry.capability_registry import CapabilityRegistry

    local_only = CapabilityRegistry()
    local_only.register_local(registration("media.video_input", "onboard-camera"))
    judge = LocalSafetyJudge(local_only)

    verdict = judge.judge()

    # 선택 기능(분류·추적·거리추정)이 하나도 없어도 판단은 계속 나오고,
    # 다만 축소된 상태로 표시된다.
    assert verdict.capability_state is CapabilityState.DEGRADED
    assert verdict.state is not SafetyState.SAFE_STOP


def test_s5_backend_verdict_is_consumed_not_recomputed():
    """AI-C-10: AI는 백엔드 통합 가용성 판정을 소비만 한다."""
    gate = RemoteFeatureGate()

    assert gate.may_select_remote_capability(True) is True
    assert gate.may_select_remote_capability(False) is False


# --- Scenario 14 — multi-zone failure isolation ---------------------------


def zone_app(registry, zone_id):
    profile = profile_of(zone_id, ["perception.detect", "risk.rule_based"])
    specs = [spec("perception.detect", core=True), spec("risk.rule_based", rank=1)]
    return build_app(profile, registry, specs, node_tags={"cpu"})


def test_s14_one_edge_failing_does_not_affect_the_other_zones():
    """Edge B 강제 종료 -> Zone A/C는 ACTIVE, Zone B만 UNAVAILABLE."""
    from perception_framework.registry.capability_registry import CapabilityRegistry

    zones = {}
    for zone_id in ("edge-A", "edge-B", "edge-C"):
        registry = CapabilityRegistry()
        registry.register_local(registration("perception.detect", f"{zone_id}-detect"))
        registry.register_local(registration("risk.rule_based", f"{zone_id}-risk"))
        app = zone_app(registry, zone_id)
        app.resolve(BUDGET.to_budget())
        zones[zone_id] = (registry, app)

    # Edge B dies: every provider it hosted disappears at once.
    registry_b, app_b = zones["edge-B"]
    registry_b.unregister_local("perception.detect", "edge-B-detect")
    registry_b.unregister_local("risk.rule_based", "edge-B-risk")
    app_b.resolve(BUDGET.to_budget())

    assert app_b.running_kinds() == ()
    for zone_id in ("edge-A", "edge-C"):
        _, app = zones[zone_id]
        app.resolve(BUDGET.to_budget())
        assert app.core_kinds_running(), f"{zone_id} was affected by edge-B failure"


def test_s14_remote_capability_from_a_dead_zone_is_excluded_immediately(registry):
    """AI-C-11: 백엔드가 사용 불가로 판정한 장치의 선택 기능은 즉시 후보에서 제외."""
    device_available = {"edge-B": True}
    registry.register_local(registration("perception.detect", "local-detect"))
    registry.register_local(
        registration(
            "remote.analysis", "edge-B-analysis", health_check=lambda: device_available["edge-B"]
        )
    )
    profile = profile_of("zone-A", ["perception.detect", "remote.analysis"])
    specs = [spec("perception.detect", core=True), spec("remote.analysis", rank=1)]
    app = build_app(profile, registry, specs, node_tags={"cpu"})
    assert app.resolve(BUDGET.to_budget())["remote.analysis"].state is CapabilityState.ACTIVE

    device_available["edge-B"] = False
    resolved = app.resolve(BUDGET.to_budget())

    assert resolved["remote.analysis"].state is CapabilityState.DISABLED
    assert resolved["perception.detect"].state is CapabilityState.ACTIVE


def test_s14_signal_classification_distinguishes_the_two_planes():
    """AI-O-04: 업무 평면과 관측 평면의 불일치를 구분해서 표현한다."""
    assert AvailabilitySignals(True, False).status is SignalStatus.TASK_TRANSPORT_ONLY
    assert AvailabilitySignals(False, True).status is SignalStatus.OBSERVABILITY_ONLY
    assert AvailabilitySignals(True, True).status is SignalStatus.BOTH_PRESENT
    assert AvailabilitySignals(False, False).status is SignalStatus.NEITHER_PRESENT


def test_s14_optional_capability_requirement_is_declared_not_assumed():
    requirement = CapabilityRequirement(required=("media.video_input",), optional=("perception.depth",))

    assert requirement.evaluate({"media.video_input"}) is CapabilityState.DEGRADED
    assert requirement.evaluate({"media.video_input", "perception.depth"}) is CapabilityState.ACTIVE
    assert requirement.evaluate(set()) is CapabilityState.DISABLED
