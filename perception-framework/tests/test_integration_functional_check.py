"""One integrated functional check across the framework's core modules.

implements: AI-C-01, AI-C-02, AI-C-03, AI-C-04, AI-C-05, AI-C-06, AI-C-07,
AI-C-08, AI-C-09, AI-C-10, AI-C-11, AI-C-13, AI-C-14, AI-C-16, AI-C-20,
AI-B-01, AI-B-03, AI-B-04, AI-B-06, AI-B-07, AI-B-09, AI-O-02, AI-R-01,
AI-S-01, DT-01/DT-03 (mock)

This replaces the large flat `tests/test_*.py` collection (모듈 단위 검증
~80개 파일). Those files tested real, narrow behaviour (hash stability,
SQLite restart recovery, wildcard topic matching, real broker round-trips,
...) that a declarative JSON scenario (`simulator/scenarios/`,
`tests/test_scenarios.py`) cannot express naturally — so instead of
deleting that coverage outright, it is consolidated here into **one
integrated functional check**: every check below still exercises real
behaviour through the real module, but they all run as part of a single
pytest test, and a failure names exactly which check broke instead of
requiring 80 separate files to keep passing.

Scope: this file currently covers the registry/selection/profile layer,
the physical command contract end-to-end (contract -> supervisor ->
hardware adapter -> MQTT gateway -> Protobuf wire), risk FSM, tracking,
data-plane/data-dictionary contracts, frame/time reference, coordinate
frame boundaries, execution control, and the digital-twin mock. It does
not (yet) re-cover every one of the ~80 removed files' individual
assertions — the intent (계속 재사용 가능하도록) is that more checks are
added here the same way, not that this file is a one-time, closed set.

Real network integrations (MQTT/Kafka real broker, OTel collector, K3s
cluster) are intentionally NOT duplicated here — those stay as their own
focused integration tests under `tests/` (see `tests/test_mqtt_transport.py`-
style files kept alongside this one) because they need a live external
process and a skip-if-unavailable guard that does not fit a fast unit-style
check list.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from perception_framework.common.coordinates import CoordinateFrame, SpatialValue, to_camera_local, to_global
from perception_framework.common.data_plane import (
    DataKind, DataPlane, DataPlaneViolation, assert_routable, is_control_data, policy_for,
)
from perception_framework.common.timing import DerivedResult, FrameReferenceFactory, TimeSyncState, in_local_order
from perception_framework.contracts import data_dictionary as dd
from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState
from perception_framework.contracts.physical_command import (
    Capability, CancelCommandRequest, CancelCommandResponse, Command, CommandAcceptance, CommandResult,
    CommandStatus, ExecutionStatus, Failure, Rejection, RejectionCode, TERMINAL_STATUSES, payload_fingerprint,
)
from perception_framework.contracts.profile import CompatibilityProfile, DeploymentProfile, ResourceBudget, ResourceCost
from perception_framework.contracts.profile_loader import is_capability_active, profile_from_dict
from perception_framework.execution.command_execution import CommandExecutionSupervisor
from perception_framework.execution.control import LocalControlSupervisor, TargetStatus
from perception_framework.execution.hardware_adapter import HardwareAdapterHandler
from perception_framework.execution.physical_command_gateway import (
    PhysicalCommandGateway, downlink_topic, uplink_topic,
)
from perception_framework.perception.tracking import Detection, IouTracker
from perception_framework.providers.fakes import InMemoryObservabilityProvider, InMemoryTransportProvider
from perception_framework.providers.physical_command_protobuf import PhysicalCommandProtobufSerializerProvider
from perception_framework.registry.capability_registry import CapabilityRegistry, ProviderRegistration
from perception_framework.risk.fsm import RiskAnalysisFsm, RiskAnalysisState, RiskEvent
from perception_framework.selection.selector import CapabilitySelector
from perception_framework.simulation.digital_twin import CameraPose, GlobalCoordinateService, PlacedObservation, build_observation_map


@dataclass
class _Check:
    name: str
    passed: bool
    detail: str = ""


class _Recorder:
    def __init__(self) -> None:
        self.checks: list[_Check] = []

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        self.checks.append(_Check(name, bool(condition), detail))

    def run(self, section: str, fn) -> None:
        """A section that raises must not hide the sections after it - one
        crashing check is reported as a single failed check, not a full
        stop (AI-C-11, mirrored from the framework's own failure-isolation
        rule for provider health checks)."""
        try:
            fn(self)
        except Exception as error:  # noqa: BLE001 - intentional catch-all here
            self.check(section, False, f"raised {error!r}")


# --- registry / selection / profile --------------------------------------

def _check_capability_registry(r: _Recorder) -> None:
    registry = CapabilityRegistry()
    registry.register_local(ProviderRegistration("perception.detect", "cam-1", "1"))
    r.check("registry.register_and_query", len(registry.available_providers("perception.detect")) == 1)
    r.check("registry.missing_capability_returns_empty", registry.available_providers("nothing.here") == [])

    def _raise():
        raise RuntimeError("probe crashed")

    registry.register_local(ProviderRegistration("perception.depth", "depth-1", "1", health_check=_raise))
    r.check(
        "registry.raising_health_check_is_treated_as_unhealthy_not_a_crash",
        registry.available_providers("perception.depth") == [],
    )

    registry.merge_remote_snapshot(
        {"perception.detect": {"cam-remote": ProviderRegistration("perception.detect", "cam-remote", "1")}}
    )
    ids_after_remote = {p.provider_id for p in registry.available_providers("perception.detect")}
    r.check("registry.local_and_remote_both_visible", ids_after_remote == {"cam-1", "cam-remote"})

    registry.register_local(ProviderRegistration("perception.detect", "cam-remote", "2"))
    only = [p for p in registry.available_providers("perception.detect") if p.provider_id == "cam-remote"]
    r.check(
        "registry.local_registration_overrides_stale_remote_entry_with_same_id",
        len(only) == 1 and only[0].version == "2",
    )

    registry.unregister_local("perception.detect", "cam-1")
    r.check(
        "registry.unregister_local_removes_provider",
        "cam-1" not in {p.provider_id for p in registry.available_providers("perception.detect")},
    )


def _check_selector(r: _Recorder) -> None:
    registry = CapabilityRegistry()
    registry.register_local(ProviderRegistration(
        "perception.detect", "cheap", "1",
        compatibility=CompatibilityProfile(priority=10, cost=ResourceCost(compute_units=1.0, memory_mb=32.0)),
    ))
    registry.register_local(ProviderRegistration(
        "perception.detect", "expensive", "1",
        compatibility=CompatibilityProfile(priority=50, cost=ResourceCost(compute_units=5.0, memory_mb=32.0)),
    ))
    selector = CapabilitySelector(registry)
    budget = ResourceBudget(compute_units=100.0, memory_mb=1024.0)
    picked = selector.select("perception.detect", {"cpu"}, budget)
    r.check("selector.picks_lowest_priority_number_first", picked.provider is not None and picked.provider.provider_id == "cheap")

    empty = CapabilitySelector(CapabilityRegistry()).select("nothing.registered", {"cpu"}, budget)
    r.check(
        "selector.no_candidates_returns_none_not_an_exception",
        empty.provider is None and empty.reason == "no_provider_registered",
    )

    degrade = selector.select_with_degrade(["missing.kind", "perception.detect"], {"cpu"}, budget)
    r.check("selector.select_with_degrade_falls_through_to_next_kind", degrade.provider is not None and degrade.provider.provider_id == "cheap")


def _check_profile_loader(r: _Recorder) -> None:
    profile = profile_from_dict({
        "domain_id": "check-domain",
        "active_capability_kinds": ["perception.detect", "risk.rule_based"],
        "node_tags": ["cpu"],
    })
    r.check("profile.from_dict_round_trips_domain_id", profile.domain_id == "check-domain")
    r.check("profile.is_capability_active_true_for_listed_kind", is_capability_active(profile, "perception.detect"))
    r.check("profile.is_capability_active_false_for_unlisted_kind", not is_capability_active(profile, "perception.track"))


# --- physical command contract end-to-end ---------------------------------

def _check_physical_command_contract(r: _Recorder) -> None:
    r.check("physical_command.execution_status_has_no_rejected_member", "REJECTED" not in ExecutionStatus.__members__)

    try:
        CommandResult("c-1", ExecutionStatus.ACCEPTED, time.time())
        non_terminal_rejected = False
    except ValueError:
        non_terminal_rejected = True
    r.check("physical_command.command_result_rejects_non_terminal_status", non_terminal_rejected)

    cmd = Command("c-2", "robot1", "navigate.relative", {"distance": 1.0})
    cmd_same = Command("c-2", "robot1", "navigate.relative", {"distance": 1.0}, correlation_id="different")
    cmd_diff = Command("c-2", "robot1", "navigate.relative", {"distance": 2.0})
    r.check(
        "physical_command.payload_fingerprint_ignores_correlation_id",
        payload_fingerprint(cmd) == payload_fingerprint(cmd_same),
    )
    r.check(
        "physical_command.payload_fingerprint_changes_with_parameters",
        payload_fingerprint(cmd) != payload_fingerprint(cmd_diff),
    )

    capability = Capability("navigate.relative", "1.0", "schema://p", "schema://r", required_resources=("mobility.base",))
    r.check(
        "physical_command.capability_maps_required_resources_to_compatibility_profile",
        capability.compatibility_profile().required_runtime_tags == ("mobility.base",),
    )


def _check_command_execution_supervisor(r: _Recorder) -> None:
    supervisor = CommandExecutionSupervisor(handler=lambda cmd: (True, {"ok": True}, None))
    acceptance = supervisor.submit(Command("c-3", "robot1", "navigate.relative", {}))
    result = supervisor.get_result("c-3")
    r.check(
        "command_execution.accepted_command_runs_to_succeeded",
        acceptance.accepted and result is not None and result.status is ExecutionStatus.SUCCEEDED,
    )

    retry_acceptance = supervisor.submit(Command("c-3", "robot1", "navigate.relative", {}))
    r.check(
        "command_execution.same_command_id_and_payload_is_a_retry_not_a_reexecution",
        retry_acceptance == acceptance,
    )

    conflict_acceptance = supervisor.submit(Command("c-3", "robot1", "navigate.relative", {"distance": 5.0}))
    r.check(
        "command_execution.same_command_id_different_payload_is_rejected_as_conflict",
        not conflict_acceptance.accepted and conflict_acceptance.rejection.code == RejectionCode.ALREADY_EXISTS,
    )

    supervisor.submit(Command("c-4", "robot1", "navigate.relative", {}, deadline=time.time() - 1))
    r.check(
        "command_execution.command_past_its_deadline_is_rejected",
        supervisor.get_status("c-4") is None,
    )

    blocking = CommandExecutionSupervisor(handler=lambda cmd: (time.sleep(0.05), (True, None, None))[1])
    blocking.submit_async(Command("c-5", "robot1", "navigate.relative", {}))
    cancel = blocking.cancel(CancelCommandRequest("c-5"))
    blocking.wait("c-5", timeout=1.0)
    final = blocking.get_result("c-5")
    r.check(
        "command_execution.cancel_during_execution_wins_over_a_late_success",
        cancel.accepted and final is not None and final.status is ExecutionStatus.CANCELED,
    )
    blocking.close()
    supervisor.close()


def _check_hardware_adapter(r: _Recorder) -> None:
    class _FakeDeviceProvider:
        def capabilities(self):
            return [Capability("navigate.relative", "1.0", "s://p", "s://r")]

        def execute(self, command):
            return True, {"moved": True}, None

        def cancel(self, command_id):
            return True

    handler = HardwareAdapterHandler(_FakeDeviceProvider())
    supported = handler(Command("c-6", "robot1", "navigate.relative", {}))
    r.check("hardware_adapter.supported_action_is_executed", supported == (True, {"moved": True}, None))
    unsupported = handler(Command("c-7", "robot1", "fly", {}))
    r.check("hardware_adapter.unsupported_action_is_rejected_not_executed", unsupported[0] is False)


def _check_physical_command_gateway(r: _Recorder) -> None:
    transport = InMemoryTransportProvider()
    serializer = PhysicalCommandProtobufSerializerProvider()
    registry = CapabilityRegistry()
    gateway = PhysicalCommandGateway(transport, serializer, registry=registry)
    gateway.attach("robot1")

    r.check("physical_command_gateway.topics_follow_interface_spec_convention",
            downlink_topic("robot1") == "terminal/robot1/downlink" and uplink_topic("robot1") == "terminal/robot1/uplink")

    gateway.send_command("robot1", Command("c-8", "robot1", "navigate.relative", {}))
    r.check("physical_command_gateway.send_command_publishes_to_downlink",
            len(transport.published) == 1 and transport.published[0][0] == "terminal/robot1/downlink")

    def device_reply(obj):
        transport.publish(uplink_topic("robot1"), serializer.encode(obj))

    device_reply(CommandAcceptance("c-8", True, time.time()))
    device_reply(CommandResult("c-8", ExecutionStatus.SUCCEEDED, time.time(), result={"moved": True}))
    result = gateway.wait_for_result("c-8", timeout=1.0)
    r.check("physical_command_gateway.success_flow_reaches_wait_for_result",
            result is not None and result.status is ExecutionStatus.SUCCEEDED)

    device_reply(Capability("navigate.relative", "1.0", "s://p", "s://r", required_resources=("mobility.base",)))
    registered = registry.available_providers("hardware.action.navigate.relative")
    r.check("physical_command_gateway.capability_announcement_registers_into_capability_registry",
            len(registered) == 1 and registered[0].provider_id == "robot1")

    transport.publish(uplink_topic("robot1"), b"not a valid protobuf envelope")
    r.check("physical_command_gateway.malformed_uplink_does_not_crash_the_gateway",
            gateway.get_acceptance("c-8") is not None)


def _check_protobuf_binding(r: _Recorder) -> None:
    serializer = PhysicalCommandProtobufSerializerProvider()
    command = Command("c-9", "robot1", "navigate.relative", {"distance": 1.0}, deadline=time.time() + 30)
    decoded = serializer.decode(serializer.encode(command))
    r.check(
        "protobuf_binding.command_round_trips_through_the_wire",
        decoded["message_type"] == "command" and decoded["payload"]["command_id"] == "c-9",
    )


# --- risk / perception -----------------------------------------------------

def _check_risk_fsm(r: _Recorder) -> None:
    inactive = RiskAnalysisFsm(set())
    r.check("risk_fsm.no_registered_event_kind_means_inactive", inactive.state is RiskAnalysisState.INACTIVE)

    fsm = RiskAnalysisFsm({"water_level"})
    r.check("risk_fsm.starts_normal_when_a_kind_is_registered", fsm.state is RiskAnalysisState.NORMAL)
    fsm.process(RiskEvent("unregistered_kind", severity=1.0))
    r.check("risk_fsm.unregistered_event_kind_is_ignored_not_an_error", fsm.state is RiskAnalysisState.NORMAL)
    fsm.process(RiskEvent("water_level", severity=0.9))
    r.check("risk_fsm.high_severity_enters_alert", fsm.state is RiskAnalysisState.ALERT)
    fsm.process(RiskEvent("water_level", severity=0.1))
    r.check("risk_fsm.alert_falls_to_recovery_before_normal", fsm.state is RiskAnalysisState.RECOVERY)


def _check_tracking(r: _Recorder) -> None:
    tracker = IouTracker()
    first = tracker.update([Detection((0.0, 0.0, 10.0, 10.0), label="person")])
    r.check("tracking.first_frame_creates_one_track", len(first) == 1)
    moved = tracker.update([Detection((1.0, 1.0, 11.0, 11.0), label="person")])
    r.check(
        "tracking.overlapping_detection_next_frame_keeps_the_same_track_id",
        len(moved) == 1 and moved[0].track_id == first[0].track_id,
    )
    empty = tracker.update([])
    r.check("tracking.frame_with_no_detections_does_not_raise", isinstance(empty, list))


# --- common contracts (data plane / data dictionary / timing / coordinates)

def _check_data_plane(r: _Recorder) -> None:
    r.check("data_plane.every_kind_has_exactly_one_plane", all(policy_for(kind).plane is not None for kind in DataKind))
    try:
        assert_routable(DataKind.VIDEO_FRAME, DataPlane.TASK)
        media_on_task_rejected = False
    except DataPlaneViolation:
        media_on_task_rejected = True
    r.check("data_plane.video_pixels_cannot_be_routed_over_the_task_plane", media_on_task_rejected)
    r.check("data_plane.control_command_is_marked_as_control_data", is_control_data(DataKind.CONTROL_COMMAND))
    r.check(
        "data_plane.device_liveness_is_not_summarizable",
        policy_for(DataKind.HEARTBEAT).summarizable is False,
    )


def _check_data_dictionary(r: _Recorder) -> None:
    r.check(
        "data_dictionary.every_entry_has_a_unique_name",
        len(dd._ENTRIES) == len(dd.DATA_DICTIONARY),
    )
    try:
        dd.spec_for("not_a_real_field_name")
        unknown_lookup_failed_closed = False
    except dd.UnknownFieldError:
        unknown_lookup_failed_closed = True
    r.check("data_dictionary.unknown_spec_lookup_fails_closed", unknown_lookup_failed_closed)
    r.check(
        "data_dictionary.unknown_fields_reports_ad_hoc_names",
        dd.unknown_fields({dd.DEVICE_ID: "x", "made_up_field": 1}) == ("made_up_field",),
    )


def _check_timing(r: _Recorder) -> None:
    clock = iter([100.0, 90.0, 110.0, 120.0])  # a backwards jump in the middle
    factory = FrameReferenceFactory("cam-1", clock=lambda: next(clock))
    refs = [factory.next_reference(f"f{i}") for i in range(3)]
    results = [DerivedResult(reference=ref, payload=None) for ref in refs]
    ordered = in_local_order(list(reversed(results)))
    r.check(
        "timing.local_order_survives_a_backwards_clock_jump",
        [item.reference.frame_id for item in ordered] == ["f0", "f1", "f2"],
    )
    factory.set_sync_state(TimeSyncState.DEGRADED)
    degraded_ref = factory.next_reference("f3")
    r.check("timing.degraded_sync_marks_the_reference_unfit_for_fusion", not degraded_ref.supports_cross_node_fusion())


def _check_coordinates(r: _Recorder) -> None:
    image_value = SpatialValue((100.0, 50.0), CoordinateFrame.IMAGE, "cam-1")
    unlifted = to_camera_local(image_value, None)
    r.check("coordinates.missing_calibration_keeps_image_frame_instead_of_failing", unlifted.frame is CoordinateFrame.IMAGE)
    lifted = to_camera_local(image_value, object(), profile_version="v1")
    r.check("coordinates.calibration_present_lifts_to_camera_local", lifted.frame is CoordinateFrame.CAMERA_LOCAL)
    try:
        to_global(image_value)
        refused = False
    except NotImplementedError:
        refused = True
    r.check("coordinates.global_transform_is_refused_inside_ai", refused)


# --- execution control / digital twin mock ---------------------------------

def _check_local_control_supervisor(r: _Recorder) -> None:
    supervisor = LocalControlSupervisor()
    started = supervisor.request("start", "unit-1")
    r.check("control.start_command_is_accepted", started.accepted and started.final_status is TargetStatus.RUNNING)
    unknown_restart = supervisor.request("restart", "unit-does-not-exist")
    r.check("control.restart_of_unknown_target_is_rejected_with_a_reason", not unknown_restart.accepted and unknown_restart.rejection_reason == "unknown_target")
    unsupported = supervisor.request("teleport", "unit-1")
    r.check("control.unsupported_command_is_rejected_not_raised", not unsupported.accepted)
    r.check(
        "control.audit_log_and_trace_log_are_kept_separate",
        len(supervisor.audit_log) == 3 and len(supervisor.trace_log) == 3 and supervisor.audit_log is not supervisor.trace_log,
    )


def _check_digital_twin_mock(r: _Recorder) -> None:
    service = GlobalCoordinateService()
    service.register_camera(CameraPose("cam-1", x_m=0.0, z_m=0.0, height_m=3.0))
    center = SpatialValue((960.0, 540.0), CoordinateFrame.IMAGE, "cam-1")
    global_point = service.to_global(center)
    r.check("digital_twin.registered_camera_transforms_image_point_to_global_frame", global_point.frame is CoordinateFrame.GLOBAL)

    try:
        service.to_global(SpatialValue((0.0, 0.0), CoordinateFrame.IMAGE, "unregistered-cam"))
        invented_position = True
    except KeyError:
        invented_position = False
    r.check("digital_twin.unregistered_source_refuses_to_invent_a_global_position", not invented_position)

    observation_map = build_observation_map(service, [
        PlacedObservation("entity-1", "cam-1", center, evidence_sufficient=True),
    ])
    r.check("digital_twin.observation_map_groups_placements_by_entity", "entity-1" in observation_map.by_entity())


CHECK_SECTIONS = (
    ("capability_registry", _check_capability_registry),
    ("selector", _check_selector),
    ("profile_loader", _check_profile_loader),
    ("physical_command_contract", _check_physical_command_contract),
    ("command_execution_supervisor", _check_command_execution_supervisor),
    ("hardware_adapter", _check_hardware_adapter),
    ("physical_command_gateway", _check_physical_command_gateway),
    ("protobuf_binding", _check_protobuf_binding),
    ("risk_fsm", _check_risk_fsm),
    ("tracking", _check_tracking),
    ("data_plane", _check_data_plane),
    ("data_dictionary", _check_data_dictionary),
    ("timing", _check_timing),
    ("coordinates", _check_coordinates),
    ("local_control_supervisor", _check_local_control_supervisor),
    ("digital_twin_mock", _check_digital_twin_mock),
)


def run_all_checks() -> list[_Check]:
    recorder = _Recorder()
    for section_name, fn in CHECK_SECTIONS:
        recorder.run(section_name, fn)
    return recorder.checks


def test_integrated_functional_check():
    checks = run_all_checks()
    failed = [c for c in checks if not c.passed]

    report_lines = [f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}" + (f" — {c.detail}" if c.detail else "") for c in checks]
    print("\n".join(report_lines))

    assert not failed, (
        f"{len(failed)}/{len(checks)} checks failed:\n"
        + "\n".join(f"  FAIL: {c.name}" + (f" — {c.detail}" if c.detail else "") for c in failed)
    )
