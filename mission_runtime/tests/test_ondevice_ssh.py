"""implements: AI-B-11, AI-B-03, AI-B-05, AI-B-02, AI-B-10, AI-C-10, AI-C-04
covers: same ControlProvider contract as K3s/standalone, unreachable device
        rejects instead of raising, liveness/readiness/device-state stay three
        separate readings, throttle decoding, deterministic artifact identity,
        checksum/transfer failure leaves the running version untouched,
        rollback to last-known-good, agent-install idempotence, credentials
        never reaching argv or the audit/trace logs, usable as one more
        `ClusterBinding`, and `ModelDeploymentManager` driving it unchanged.

Most tests run the **real** `ondevice_agent.sh` through a local-shell runner
with `$HOME` pointed at a tmp dir: the script is the part that is easy to get
wrong, so exercising the fake instead would test nothing. Real-device tests
are gated on `PF_ONDEVICE_TEST_DEVICE`, the way `tests/test_k3s_control.py`
gates on a reachable cluster.
"""

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from mission_runtime.execution.control import LocalControlSupervisor, TargetStatus
from mission_runtime.providers.adapters import ControlProvider, ModelDeploymentProvider
from mission_runtime.providers.k3s import K3sControlProvider
from mission_runtime.providers.ondevice_ssh import (
    AGENT_SCRIPT_PATH,
    DeviceState,
    Liveness,
    OnDeviceArtifactDeployment,
    OnDeviceSshControlProvider,
    Readiness,
    decode_throttle_flags,
    pack_unit_artifact,
)
from mission_runtime.registry.device_registry import (
    AUTH_PASSWORD,
    CredentialStore,
    DeviceCredential,
    DeviceRegistration,
    DeviceRegistry,
)
from mission_runtime.runtime.clusters import ClusterBinding, MultiClusterControlProvider, PlacementRequest
from mission_runtime.runtime.model_deployment import (
    ModelDeploymentManager,
    ModelDeploymentRequest,
    ModelDeploymentStatus,
)

SECRET = "not-a-real-password"

DEVICE = DeviceRegistration(
    device_id="terminal-a",
    address="192.0.2.11",
    username="physical",
    credential_id="c1",
    node_tags=frozenset({"platform.terminal", "compute.cpu"}),
)


# --- test doubles ---------------------------------------------------------


class LocalShellRunner:
    """Runs the provider's own command strings locally, with a fake `$HOME`.

    This is not a mock of the protocol: the commands, the agent script, the
    symlink flips and the supervisor are all the real ones. Only the network
    hop is removed, which is exactly the part a Pi would add.
    """

    def __init__(self, home: Path, *, fail_put: bool = False, corrupt_put: bool = False) -> None:
        self.home = home
        self.home.mkdir(parents=True, exist_ok=True)
        self.fail_put = fail_put
        self.corrupt_put = corrupt_put
        self.commands: list[str] = []

    @property
    def device(self):
        return DEVICE

    def _env(self):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env.pop("PF_ROOT", None)
        env.pop("PF_BACKEND", None)
        return env

    def run(self, command, *, timeout=None, stdin=None):
        self.commands.append(command)
        return subprocess.run(
            ["bash", "-c", command], capture_output=True, text=True,
            input=stdin, env=self._env(), timeout=timeout or 60,
        )

    def _local(self, remote_path: str) -> Path:
        return Path(remote_path.replace("~/", f"{self.home}/", 1))

    def put(self, local_path, remote_path, *, timeout=None):
        if self.fail_put:
            return subprocess.CompletedProcess([], 1, "", "ssh: connect to host: Connection refused")
        destination = self._local(remote_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = Path(local_path).read_bytes()
        if self.corrupt_put:
            payload = payload[: len(payload) // 2]  # what a dropped link leaves
        destination.write_bytes(payload)
        return subprocess.CompletedProcess([], 0, "", "")

    def put_content(self, content, remote_path, *, mode="644", timeout=None):
        destination = self._local(remote_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        destination.chmod(int(mode, 8))
        return subprocess.CompletedProcess([], 0, "", "")


class DeadRunner:
    """Every call behaves like a host that is simply not there."""

    device = DEVICE

    def run(self, command, *, timeout=None, stdin=None):
        return subprocess.CompletedProcess([], 255, "", "ssh: connect to host 192.0.2.11: No route to host")

    def put(self, local_path, remote_path, *, timeout=None):
        return subprocess.CompletedProcess([], 1, "", "ssh: connect to host 192.0.2.11: No route to host")

    def put_content(self, content, remote_path, *, mode="644", timeout=None):
        return self.run("")


class ScriptedRunner:
    """Returns a canned health payload; used for state-combination tests."""

    device = DEVICE

    def __init__(self, health_payload: dict) -> None:
        self._payload = health_payload

    def run(self, command, *, timeout=None, stdin=None):
        if " health " in command:
            return subprocess.CompletedProcess([], 0, json.dumps(self._payload) + "\n", "")
        if "sha256sum" in command:
            return subprocess.CompletedProcess([], 0, "", "")
        return subprocess.CompletedProcess([], 0, "ok:done\n", "")

    def put(self, *a, **k):
        return subprocess.CompletedProcess([], 0, "", "")

    def put_content(self, *a, **k):
        return subprocess.CompletedProcess([], 0, "", "")


@pytest.fixture
def unit_source(tmp_path):
    """A minimal but genuinely runnable unit."""
    source = tmp_path / "unit_src"
    source.mkdir()
    (source / "run.sh").write_text(
        '#!/usr/bin/env bash\n'
        'echo "up $(cat version.txt)"\n'
        'touch "$PF_READY_FILE"\n'
        'trap "rm -f $PF_READY_FILE; exit 0" TERM INT\n'
        'while true; do sleep 0.2; done\n'
    )
    (source / "run.sh").chmod(0o755)
    (source / "version.txt").write_text("v1")
    (source / "unit.config.json").write_text(json.dumps({"target_hz": 5.0}))
    return source


@pytest.fixture
def local_provider(tmp_path):
    runner = LocalShellRunner(tmp_path / "device_home")
    provider = OnDeviceSshControlProvider(DEVICE, runner=runner, backend="script")
    yield provider
    provider.delete("unit-a")


# --- contract parity (AI-B-11) -------------------------------------------


def test_the_terminal_provider_satisfies_the_same_control_contract():
    """AI-B-11: 복수 실행영역을 동일한 실행 제어 계약으로 관리한다.

    절대 준수 원칙 #11 / AI-B-10 forbid requiring an orchestrator control
    plane on a 말단, which is exactly why K3s cannot serve this node — so the
    contract has to be satisfiable without one.
    """
    terminal = OnDeviceSshControlProvider(DEVICE, runner=DeadRunner())

    assert isinstance(terminal, ControlProvider)
    assert isinstance(K3sControlProvider(), ControlProvider)
    assert isinstance(LocalControlSupervisor(), ControlProvider)


def test_the_terminal_provider_needs_no_orchestrator_on_the_device(local_provider, unit_source, tmp_path):
    """What lands on the device is one shell script and a unit directory."""
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", package, restart=False)

    home = local_provider.runner.home
    installed = {str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()}

    assert "pf_units/.pf_agent.sh" in installed
    assert not any("kube" in name or "containerd" in name or "docker" in name for name in installed)


def test_unreachable_device_rejects_instead_of_raising():
    provider = OnDeviceSshControlProvider(DEVICE, runner=DeadRunner())

    assert provider.is_available() is False
    for result in (
        provider.request("start", "unit-a"),
        provider.request("stop", "unit-a"),
        provider.rollback("unit-a"),
    ):
        assert result.accepted is False
        assert result.rejection_reason == "device_unreachable"


def test_unsupported_command_is_rejected_with_a_reason(local_provider):
    result = local_provider.request("teleport", "unit-a")

    assert result.accepted is False
    assert result.rejection_reason == "unsupported_command:teleport"


def test_status_of_an_unreachable_device_is_stopped_not_an_exception():
    provider = OnDeviceSshControlProvider(DEVICE, runner=DeadRunner())

    assert provider.get_status("unit-a") is TargetStatus.STOPPED


# --- health: three readings, never one (AI-B-05) --------------------------


def test_a_throttled_board_running_a_healthy_unit_reports_all_three():
    """AI-B-05: 프로세스 liveness·readiness와 장치 운용 상태를 구분한다.

    0xe0006 is the value pi6 actually reports once it heats up. A unit that
    is alive and ready on a frequency-capped board must say all three things
    at once, or the capping is invisible.
    """
    provider = OnDeviceSshControlProvider(DEVICE, runner=ScriptedRunner({
        "unit": "unit-a", "backend": "systemd", "liveness": "ALIVE", "readiness": "READY",
        "ready_age_s": 3, "version": "v2", "previous_version": "v1",
        "device": {"temperature_c": 87.3, "throttled": "0xe0006", "load1": 4.0, "mem_available_kb": 7000000},
    }))

    health = provider.health("unit-a")

    assert health.liveness is Liveness.ALIVE
    assert health.readiness is Readiness.READY
    assert health.device_state is DeviceState.THROTTLED
    assert health.temperature_c == 87.3
    assert "currently_throttled" in health.throttle_flags
    assert health.as_status() is TargetStatus.RUNNING


def test_a_started_but_not_yet_ready_unit_is_alive_and_not_ready():
    provider = OnDeviceSshControlProvider(DEVICE, runner=ScriptedRunner({
        "liveness": "ALIVE", "readiness": "NOT_READY", "ready_age_s": None,
        "version": "v1", "previous_version": "", "backend": "script",
        "device": {"temperature_c": 55.0, "throttled": "0x0"},
    }))

    health = provider.health("unit-a")

    assert (health.liveness, health.readiness) == (Liveness.ALIVE, Readiness.NOT_READY)
    assert health.device_state is DeviceState.NOMINAL


def test_an_unreachable_device_reports_unknown_not_dead():
    """AI-O-04: 관측이 없는 것과 죽은 것은 다른 사건이다.

    A lost link is not evidence that a unit stopped, so liveness must not
    fall to DEAD just because we could not ask.
    """
    provider = OnDeviceSshControlProvider(DEVICE, runner=DeadRunner())

    health = provider.health("unit-a")

    assert health.reachable is False
    assert health.liveness is Liveness.UNKNOWN
    assert health.readiness is Readiness.UNKNOWN
    assert health.device_state is DeviceState.UNREACHABLE
    assert health.reason == "device_unreachable"


def test_an_unmeasured_throttle_reading_is_unknown_not_nominal():
    provider = OnDeviceSshControlProvider(DEVICE, runner=ScriptedRunner({
        "liveness": "ALIVE", "readiness": "READY", "device": {"temperature_c": None, "throttled": ""},
    }))

    assert provider.health("unit-a").device_state is DeviceState.UNKNOWN


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0x0", ()),
        ("0xe0006", ("arm_frequency_capped_now", "currently_throttled",
                     "arm_frequency_capped_occurred", "throttling_occurred",
                     "soft_temperature_limit_occurred")),
        ("0x50000", ("under_voltage_occurred", "throttling_occurred")),
        ("", ()),
        (None, ()),
        ("not-hex", ()),
    ],
)
def test_throttle_flag_decoding(raw, expected):
    assert decode_throttle_flags(raw) == expected


def test_an_unnamed_throttle_bit_is_surfaced_rather_than_dropped():
    flags = decode_throttle_flags("0x100000")

    assert flags == ("unknown_bits:0x100000",)


def test_only_current_throttle_bits_change_device_state():
    """0xe0000 is "it happened since boot", not "it is happening"."""
    historical = OnDeviceSshControlProvider(DEVICE, runner=ScriptedRunner({
        "liveness": "ALIVE", "readiness": "READY", "device": {"throttled": "0xe0000"},
    }))

    health = historical.health("unit-a")
    assert health.device_state is DeviceState.NOMINAL
    assert "throttling_occurred" in health.throttle_flags  # history is still reported


# --- artifact identity (AI-B-02) -----------------------------------------


def test_packing_the_same_source_twice_yields_the_same_digest(unit_source, tmp_path):
    """AI-B-02: 실행 이미지와 외부 구성은 버전과 무결성 정보를 유지한다."""
    first = pack_unit_artifact(unit_source, tmp_path / "a")
    second = pack_unit_artifact(unit_source, tmp_path / "b")

    assert first.sha256 == second.sha256
    assert first.version == second.version == f"sha256-{first.sha256[:16]}"


def test_changing_only_the_config_changes_the_version(unit_source, tmp_path):
    """Config travels inside the artifact, so version covers code AND config."""
    before = pack_unit_artifact(unit_source, tmp_path / "a")
    (unit_source / "unit.config.json").write_text(json.dumps({"target_hz": 2.0}))
    after = pack_unit_artifact(unit_source, tmp_path / "b")

    assert before.sha256 != after.sha256


def test_a_source_without_an_entrypoint_is_refused(tmp_path):
    source = tmp_path / "no_entry"
    source.mkdir()
    (source / "unit.py").write_text("print('hi')")

    with pytest.raises(FileNotFoundError, match="run.sh"):
        pack_unit_artifact(source, tmp_path / "staging")


def test_an_artifact_carries_no_credential(unit_source, tmp_path):
    (unit_source / "unit.config.json").write_text(json.dumps({"target_hz": 5.0}))
    package = pack_unit_artifact(unit_source, tmp_path / "staging")

    assert SECRET.encode() not in package.path.read_bytes()


# --- full lifecycle against the real agent script -------------------------


def test_deploy_start_status_ready_stop(local_provider, unit_source, tmp_path):
    package = pack_unit_artifact(unit_source, tmp_path / "staging")

    result = local_provider.deploy_artifact("unit-a", package)

    assert result.accepted is True
    assert local_provider.get_status("unit-a") is TargetStatus.RUNNING
    assert local_provider.wait_ready("unit-a", timeout_s=15, poll_s=0.3) is True

    health = local_provider.health("unit-a")
    assert health.liveness is Liveness.ALIVE
    assert health.readiness is Readiness.READY
    assert health.active_version == package.version
    assert health.backend == "script"

    assert local_provider.request("stop", "unit-a").accepted is True
    assert local_provider.get_status("unit-a") is TargetStatus.STOPPED
    # Version survives a stop: stopping is not uninstalling.
    assert local_provider.versions("unit-a")[0] == package.version


def test_starting_without_any_deployed_version_is_rejected(local_provider):
    result = local_provider.request("start", "unit-a")

    assert result.accepted is False
    assert result.rejection_reason == "no_active_version"


def test_update_keeps_the_previous_version_for_rollback(local_provider, unit_source, tmp_path):
    """AI-B-05: 새 버전 적용 실패 시 마지막 정상 버전으로 복구할 수 있어야 한다."""
    v1 = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", v1)
    (unit_source / "version.txt").write_text("v2")
    v2 = pack_unit_artifact(unit_source, tmp_path / "staging")

    assert local_provider.update_artifact("unit-a", v2).accepted is True

    active, previous, all_versions = local_provider.versions("unit-a")
    assert active == v2.version
    assert previous == v1.version
    assert set(all_versions) == {v1.version, v2.version}


def test_rollback_returns_to_the_last_known_good_version(local_provider, unit_source, tmp_path):
    v1 = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", v1)
    (unit_source / "version.txt").write_text("v2")
    v2 = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.update_artifact("unit-a", v2)

    assert local_provider.rollback("unit-a").accepted is True

    active, previous, _ = local_provider.versions("unit-a")
    assert active == v1.version
    assert previous == v2.version  # rollback is itself reversible
    assert local_provider.wait_ready("unit-a", timeout_s=15, poll_s=0.3) is True


def test_rollback_without_a_previous_version_says_so(local_provider, unit_source, tmp_path):
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", package)

    result = local_provider.rollback("unit-a")

    assert result.accepted is False
    assert result.rejection_reason == "no_previous_version"


def test_pruning_keeps_only_the_active_and_previous_versions(local_provider, unit_source, tmp_path):
    for label in ("v1", "v2", "v3"):
        (unit_source / "version.txt").write_text(label)
        local_provider.deploy_artifact("unit-a", pack_unit_artifact(unit_source, tmp_path / "staging"))

    local_provider.prune("unit-a")

    active, previous, all_versions = local_provider.versions("unit-a")
    assert set(all_versions) == {active, previous}


# --- failure mid-deploy leaves the running version alone ------------------


def test_a_corrupted_transfer_is_refused_and_the_running_version_survives(
    local_provider, unit_source, tmp_path
):
    """The pi2 case: a link that drops mid-copy leaves a truncated file.

    The device verifies the checksum before anything touches `current`, so a
    failed update cannot produce a stopped unit (AI-B-05).
    """
    good = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", good)
    local_provider.wait_ready("unit-a", timeout_s=15, poll_s=0.3)
    (unit_source / "version.txt").write_text("v2")
    new = pack_unit_artifact(unit_source, tmp_path / "staging")

    local_provider.runner.corrupt_put = True
    result = local_provider.deploy_artifact("unit-a", new)
    local_provider.runner.corrupt_put = False

    assert result.accepted is False
    assert result.rejection_reason == "checksum_mismatch"
    assert local_provider.versions("unit-a")[0] == good.version
    assert local_provider.get_status("unit-a") is TargetStatus.RUNNING
    assert local_provider.health("unit-a").readiness is Readiness.READY


def test_a_rejected_partial_upload_is_not_left_on_the_device(local_provider, unit_source, tmp_path):
    good = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", good, restart=False)
    (unit_source / "version.txt").write_text("v2")
    new = pack_unit_artifact(unit_source, tmp_path / "staging")

    local_provider.runner.corrupt_put = True
    local_provider.deploy_artifact("unit-a", new)
    local_provider.runner.corrupt_put = False

    incoming = local_provider.runner.home / "pf_units" / "unit-a" / "incoming"
    assert list(incoming.glob("*")) == []


def test_a_retry_after_a_failed_transfer_succeeds(local_provider, unit_source, tmp_path):
    good = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", good)
    (unit_source / "version.txt").write_text("v2")
    new = pack_unit_artifact(unit_source, tmp_path / "staging")

    local_provider.runner.corrupt_put = True
    local_provider.deploy_artifact("unit-a", new)
    local_provider.runner.corrupt_put = False

    assert local_provider.deploy_artifact("unit-a", new).accepted is True
    assert local_provider.versions("unit-a")[0] == new.version


def test_a_transport_failure_is_reported_as_a_transfer_failure(local_provider, unit_source, tmp_path):
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.runner.fail_put = True

    result = local_provider.deploy_artifact("unit-a", package)

    assert result.accepted is False
    assert result.rejection_reason == "transfer_failed"


def test_a_missing_local_artifact_is_refused_before_any_connection(local_provider, tmp_path):
    from mission_runtime.providers.ondevice_ssh import ArtifactPackage

    ghost = ArtifactPackage(path=tmp_path / "nope.tar.gz", version="v1", sha256="0" * 64)

    result = local_provider.deploy_artifact("unit-a", ghost)

    assert result.rejection_reason == "missing_artifact"
    assert local_provider.runner.commands == []


# --- agent install ---------------------------------------------------------


def test_the_agent_is_pushed_once_and_then_only_when_it_changes(local_provider, unit_source, tmp_path):
    """On a 125ms link every avoidable round-trip is real deploy latency."""
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", package, restart=False)

    local_provider._agent_installed = False  # force a fresh check, not a fresh push
    before = len(local_provider.runner.commands)
    local_provider.install_agent()
    probe_only = local_provider.runner.commands[before:]

    assert len(probe_only) == 1
    assert "sha256sum" in probe_only[0]


def test_a_modified_agent_script_is_replaced(local_provider, unit_source, tmp_path):
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", package, restart=False)
    installed = local_provider.runner.home / "pf_units" / ".pf_agent.sh"
    installed.write_text("#!/bin/bash\nexit 0\n")

    local_provider._agent_installed = False
    local_provider.install_agent()

    assert installed.read_text() == AGENT_SCRIPT_PATH.read_text()


# --- credentials never leak (AI-B-02) --------------------------------------


def test_a_password_never_reaches_the_process_argv(tmp_path, monkeypatch):
    """`sshpass -p <secret>` would publish the secret in /proc — so the
    runner uses `sshpass -e` and the environment instead."""
    from mission_runtime.providers.ondevice_ssh import SshRunner

    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/sshpass")
    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = SshRunner(DEVICE, DeviceCredential("c1", AUTH_PASSWORD, secret=SECRET))
    runner.run("true")

    assert SECRET not in " ".join(captured["argv"])
    assert captured["argv"][:2] == ["sshpass", "-e"]
    assert captured["env"]["SSHPASS"] == SECRET


def test_password_auth_without_sshpass_is_a_rejection_not_a_crash(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    provider = OnDeviceSshControlProvider(DEVICE, DeviceCredential("c1", AUTH_PASSWORD, secret=SECRET))

    result = provider.request("start", "unit-a")

    assert result.accepted is False
    assert result.rejection_reason == "password_auth_unavailable:sshpass_missing"
    assert provider.is_available() is False


def test_no_credential_appears_in_the_audit_or_trace_logs(local_provider, unit_source, tmp_path):
    """AI-B-03: audit(책임 추적)과 trace(지연 추적)는 목적이 다르므로 분리 보관하고,
    어느 쪽도 비밀정보를 담지 않는다."""
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", package)
    local_provider.request("stop", "unit-a", requested_by="operator-1")

    combined = " ".join(str(e) for e in [*local_provider.audit_log, *local_provider.trace_log])

    assert SECRET not in combined
    assert local_provider.audit_log[-1].requested_by == "operator-1"
    assert len(local_provider.audit_log) == len(local_provider.trace_log)
    # Two logs, two shapes — the trace carries latency, the audit carries who.
    assert not hasattr(local_provider.audit_log[-1], "latency_ms")
    assert local_provider.trace_log[-1].latency_ms >= 0


# --- one more execution region (AI-B-11) -----------------------------------


def test_a_terminal_is_just_another_cluster_binding(local_provider, unit_source, tmp_path):
    """AI-B-11: 중앙 서버와 모든 엣지가 동일한 오케스트레이터를 설치해야 한다는
    전제를 두어서는 안 된다 — the router cannot tell the difference."""
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", package)
    router = MultiClusterControlProvider([
        ClusterBinding("zone-edge", K3sControlProvider(kubectl="kubectl-does-not-exist"), frozenset({"zone-edge"})),
        ClusterBinding("terminal-a", local_provider, frozenset({"platform.terminal", "compute.cpu"})),
    ])

    selected = router.select_cluster(PlacementRequest(required_tags=frozenset({"platform.terminal"})))
    result = router.request("restart", "unit-a")

    assert selected.cluster_id == "terminal-a"
    assert result.accepted is True
    assert router.cluster_of("unit-a") == "terminal-a"
    assert router.get_status("unit-a") is TargetStatus.RUNNING
    assert "terminal-a" in router.available_clusters()


def test_one_unreachable_region_does_not_stop_another(local_provider, unit_source, tmp_path):
    """AI-B-11: 한 실행영역의 제어면이 사용할 수 없어도 다른 영역은 계속 동작한다."""
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    local_provider.deploy_artifact("unit-a", package)
    dead = OnDeviceSshControlProvider(DEVICE, runner=DeadRunner())
    router = MultiClusterControlProvider([
        ClusterBinding("terminal-dead", dead, frozenset({"platform.terminal", "dead"})),
        ClusterBinding("terminal-a", local_provider, frozenset({"platform.terminal"})),
    ])

    assert router.available_clusters() == ["terminal-a"]
    assert router.request("restart", "unit-a").accepted is True


# --- ModelDeploymentProvider reuse ----------------------------------------


def test_the_artifact_deployment_satisfies_the_model_deployment_contract(local_provider):
    deployment = OnDeviceArtifactDeployment(local_provider)

    assert isinstance(deployment, ModelDeploymentProvider)


def test_the_deployment_manager_drives_a_terminal_unchanged(local_provider, unit_source, tmp_path):
    """Reusing `ModelDeploymentManager` means "validate before activate" is
    enforced in one place, not re-implemented for terminals."""
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    deployment = OnDeviceArtifactDeployment(local_provider)
    deployment.register_package("ref-1", package)
    manager = ModelDeploymentManager(deployment)

    result = manager.deploy(ModelDeploymentRequest(
        deployment_id="d1", model_id="unit-a", model_version=package.version,
        artifact_ref="ref-1", checksum=package.sha256, target_node_id=DEVICE.device_id,
    ))

    assert result.status is ModelDeploymentStatus.APPLIED
    assert local_provider.versions("unit-a")[0] == package.version


def test_a_checksum_disagreement_is_caught_before_activation(local_provider, unit_source, tmp_path):
    package = pack_unit_artifact(unit_source, tmp_path / "staging")
    deployment = OnDeviceArtifactDeployment(local_provider)
    deployment.register_package("ref-1", package)
    manager = ModelDeploymentManager(deployment)

    result = manager.deploy(ModelDeploymentRequest(
        deployment_id="d1", model_id="unit-a", model_version="v1",
        artifact_ref="ref-1", checksum="0" * 64, target_node_id=DEVICE.device_id,
    ))

    assert result.status is ModelDeploymentStatus.FAILED
    assert result.reason == "artifact_validation_failed"
    assert local_provider.versions("unit-a") == (None, None, ())


def test_a_deployment_aimed_at_another_device_is_refused(local_provider):
    deployment = OnDeviceArtifactDeployment(local_provider)

    assert deployment.download("ref-1", "some-other-device") is False
    assert deployment.current_version("unit-a", "some-other-device") is None
    assert deployment.rollback("unit-a", "v1", "some-other-device") is False


# --- observability is optional (AI-O-02) -----------------------------------


def test_a_failing_observability_provider_does_not_affect_control(local_provider, unit_source, tmp_path):
    class Exploding:
        def record_event(self, *a, **k):
            raise RuntimeError("collector down")

    provider = OnDeviceSshControlProvider(
        DEVICE, runner=local_provider.runner, backend="script", observability=Exploding()
    )

    result = provider.request("start", "unit-a")  # rejected -> would emit an event

    assert result.rejection_reason == "no_active_version"  # and no exception escaped


def test_rejections_are_reported_as_structured_events(local_provider):
    from mission_runtime.providers.fakes import InMemoryObservabilityProvider

    sink = InMemoryObservabilityProvider()
    provider = OnDeviceSshControlProvider(
        DEVICE, runner=local_provider.runner, backend="script", observability=sink
    )

    provider.request("start", "unit-a")

    rejected = [e for e in sink.events if e.name == "ondevice_control_rejected"]
    assert rejected and rejected[0].payload["reason"] == "no_active_version"
    assert rejected[0].payload["device_id"] == DEVICE.device_id
    assert SECRET not in str(rejected[0].payload)


# --- real device, opt-in ----------------------------------------------------
#
# `PF_ONDEVICE_TEST_DEVICE=pi6 pytest tests/test_ondevice_ssh.py -q`
# Needs config/devices.json + config/device_credentials.json (both git-ignored).

REAL_DEVICE = os.environ.get("PF_ONDEVICE_TEST_DEVICE")
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
needs_device = pytest.mark.skipif(
    not REAL_DEVICE or not (CONFIG_DIR / "devices.json").exists(),
    reason="set PF_ONDEVICE_TEST_DEVICE and provide config/devices.json to run against real hardware",
)


@pytest.fixture
def real_provider():
    store = CredentialStore(CONFIG_DIR / "device_credentials.json")
    registry = DeviceRegistry(store)
    registry.load(CONFIG_DIR / "devices.json")
    device = registry.get(REAL_DEVICE)
    if device is None:
        pytest.skip(f"{REAL_DEVICE} not in config/devices.json")
    provider = OnDeviceSshControlProvider(device, registry.credential_for(REAL_DEVICE), command_timeout_s=90)
    unit = f"selftest-{uuid.uuid4().hex[:8]}"
    yield provider, unit
    provider.delete(unit)  # never leave a unit behind on real hardware


@needs_device
def test_real_device_full_lifecycle(real_provider, tmp_path):
    provider, unit = real_provider
    source = Path(__file__).resolve().parents[1] / "deploy" / "ondevice_unit"
    package = pack_unit_artifact(source, tmp_path / "staging")

    assert provider.is_available() is True
    assert provider.deploy_artifact(unit, package).accepted is True
    assert provider.wait_ready(unit, timeout_s=60, poll_s=2.0) is True

    health = provider.health(unit)
    assert health.liveness is Liveness.ALIVE
    assert health.readiness is Readiness.READY
    assert health.active_version == package.version
    # The board's own state is read regardless of how the unit is doing.
    assert health.device_state in (DeviceState.NOMINAL, DeviceState.THROTTLED)
    assert health.temperature_c is not None

    assert provider.request("stop", unit, requested_by="pytest").accepted is True
    assert provider.health(unit).liveness is Liveness.DEAD


@needs_device
def test_real_device_update_and_rollback(real_provider, tmp_path):
    provider, unit = real_provider
    source = tmp_path / "unit_src"
    shutil.copytree(Path(__file__).resolve().parents[1] / "deploy" / "ondevice_unit", source)
    v1 = pack_unit_artifact(source, tmp_path / "staging")
    provider.deploy_artifact(unit, v1)

    config = json.loads((source / "unit.config.json").read_text())
    config["target_hz"] = 2.0
    (source / "unit.config.json").write_text(json.dumps(config))
    v2 = pack_unit_artifact(source, tmp_path / "staging")

    assert provider.update_artifact(unit, v2).accepted is True
    assert provider.versions(unit)[:2] == (v2.version, v1.version)

    assert provider.rollback(unit).accepted is True
    assert provider.versions(unit)[:2] == (v1.version, v2.version)
    assert provider.wait_ready(unit, timeout_s=60, poll_s=2.0) is True


@needs_device
def test_real_device_refuses_a_corrupted_artifact_and_keeps_running(real_provider, tmp_path):
    from mission_runtime.providers.ondevice_ssh import ArtifactPackage

    provider, unit = real_provider
    source = Path(__file__).resolve().parents[1] / "deploy" / "ondevice_unit"
    good = pack_unit_artifact(source, tmp_path / "staging")
    provider.deploy_artifact(unit, good)
    provider.wait_ready(unit, timeout_s=60, poll_s=2.0)

    truncated = tmp_path / "truncated.tar.gz"
    truncated.write_bytes(good.path.read_bytes()[: good.path.stat().st_size // 2])
    bad = ArtifactPackage(path=truncated, version="v-truncated", sha256=good.sha256)

    result = provider.deploy_artifact(unit, bad)

    assert result.accepted is False
    assert result.rejection_reason == "checksum_mismatch"
    assert provider.versions(unit)[0] == good.version
    assert provider.get_status(unit) is TargetStatus.RUNNING
