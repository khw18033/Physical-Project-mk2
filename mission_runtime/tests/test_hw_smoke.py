"""implements: AI-B-04, AI-B-09, AI-O-04, AI-C-10, AI-C-18
covers: connection smoke harness (tools/hw_smoke) with every side effect
        faked — L1 dns/unreachable, L2 tag mismatch with the missing list,
        auth failure mapping, L3 frame capture with byte count, L3
        not_implemented is NOT ok, stop-at-first-failure, RuntimeInstance
        freshness (ttl/healthy), report JSON keys, reason vocabulary closed,
        and the CLI's override/adhoc parsing.

No network: `resolve`, `icmp` and `ssh_factory` are constructor arguments.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability_contract import RuntimeInstance
from mission_runtime.providers.link_probe import METHOD_ICMP, REASON_PROBE_UNAVAILABLE, LinkMeasurement
from mission_runtime.registry.device_registry import (
    CredentialStore,
    DeviceCredential,
    DeviceRegistration,
    DeviceRegistry,
)

_FRAMEWORK_DIR = Path(__file__).resolve().parents[1]
if str(_FRAMEWORK_DIR) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK_DIR))

from tools.hw_smoke import run as cli  # noqa: E402
from tools.hw_smoke import smoke  # noqa: E402

CAMERA = DeviceRegistration(
    device_id="cam-a", address="cam-a.example", username="u", credential_id="c1",
    node_tags=frozenset({"compute.cpu", "arch.arm64", "sensor.camera.imx708", "runtime.python3",
                         "accel.edgetpu_usb", "tier.fixed_camera"}),
)
UAV = DeviceRegistration(
    device_id="uav-a", address="uav-a.example", username="u", credential_id="c1",
    node_tags=frozenset({"compute.cpu", "arch.arm64", "platform.uav", "runtime.python3"}),
)
ROBOT = DeviceRegistration(
    device_id="ugv-a", address="ugv-a.example", username="u", credential_id="c1",
    node_tags=frozenset({"compute.cpu", "tier.ugv", "sensor.camera.go1_front"}),
)

GOOD_IDENTITY = (
    "@arch\naarch64\n@nproc\n4\n@cameras\n"
    "Available cameras\n-----------------\n"
    "0 : imx708 [4608x2592 10-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx708@1a)\n"
    "    Modes: 'SRGGB10_CSI2P' : 1536x864 [120.13 fps - (768, 432)/3072x1728 crop]\n"
    "@video\n/dev/video0\n/dev/video1\n@python3\n/usr/bin/python3\n@end\n"
)
WIDE_IDENTITY = GOOD_IDENTITY.replace("0 : imx708 [", "0 : imx708_wide [")


def ok_ping(address, **_):
    return LinkMeasurement(address, METHOD_ICMP, sent=5, received=5, rtt_min_ms=3.0, rtt_avg_ms=4.0,
                           rtt_max_ms=6.0, rtt_mdev_ms=1.0, rtt_samples_ms=(3.0, 4.0, 4.0, 3.0, 6.0))


def dead_ping(address, **_):
    return LinkMeasurement(address, METHOD_ICMP, sent=5, received=0)


def no_tool_ping(address, **_):
    return LinkMeasurement(address, METHOD_ICMP, reason=REASON_PROBE_UNAVAILABLE)


def resolves(address):
    return ["192.0.2.5"]


def unresolvable(address):
    raise OSError("[Errno -2] Name or service not known")


class FakeSsh:
    """Answers each script with a canned CompletedProcess, keyed by which
    probe script it is. Records what ran."""

    def __init__(self, identity=None, frame=None, *, raise_=None):
        self.identity = identity
        self.frame = frame
        self.raise_ = raise_
        self.commands: list[str] = []
        self.credentials: list = []

    def factory(self, device, credential):
        self.credentials.append(credential)
        return self

    def run(self, command, *, timeout=None, stdin=None):
        self.commands.append(command)
        if self.raise_ is not None:
            raise self.raise_
        if command == smoke.IDENTITY_PROBE_SCRIPT:
            return self.identity
        if command == smoke.FRAME_PROBE_SCRIPT:
            return self.frame
        raise AssertionError(f"unexpected script: {command!r}")


def proc(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


def registry_with(*devices, credential=True):
    store = CredentialStore("/nonexistent/creds.json", strict_permissions=True)
    if credential:
        store.put(DeviceCredential("c1", "key", key_path="~/.ssh/id_test"))
    registry = DeviceRegistry(store)
    for device in devices:
        registry.register(device)
    return registry


def runner(*devices, icmp=ok_ping, resolve=resolves, ssh=None, clock=lambda: 1000.0):
    ssh = ssh or FakeSsh(proc(GOOD_IDENTITY), proc("@frame\n48211 1727500000\n"))
    return smoke.SmokeRunner(registry_with(*devices), icmp=icmp, resolve=resolve,
                             ssh_factory=ssh.factory, clock=clock), ssh


# --- L1 -----------------------------------------------------------------------


def test_l1_unresolved_name_is_dns_unresolved_and_pings_nothing():
    pinged = []
    r, _ = runner(CAMERA, resolve=unresolvable, icmp=lambda a, **k: pinged.append(a) or ok_ping(a))
    result = r.run_l1(CAMERA)
    assert (result.level, result.ok, result.reason) == (1, False, "dns_unresolved")
    assert result.measured["address"] == "cam-a.example"
    assert pinged == []


def test_l1_total_loss_is_host_unreachable_with_the_raw_measurement():
    r, _ = runner(CAMERA, icmp=dead_ping)
    result = r.run_l1(CAMERA)
    assert (result.ok, result.reason) == (False, "host_unreachable")
    assert result.measured["sent"] == 5 and result.measured["received"] == 0
    assert result.measured["loss_fraction"] == 1.0
    assert result.measured["resolved"] == ["192.0.2.5"]


def test_l1_unmeasurable_link_is_not_reported_as_reachable():
    r, _ = runner(CAMERA, icmp=no_tool_ping)
    result = r.run_l1(CAMERA)
    assert result.ok is False
    assert result.measured["reason"] == REASON_PROBE_UNAVAILABLE  # the raw "could not measure" survives


def test_l1_pass_carries_link_measurement_fields():
    r, _ = runner(CAMERA)
    result = r.run_l1(CAMERA)
    assert (result.ok, result.reason, result.probed_at) == (True, "reachable", 1000.0)
    assert result.measured["rtt_avg_ms"] == 4.0 and result.measured["loss_fraction"] == 0.0


# --- L2 -----------------------------------------------------------------------


def test_l2_tag_mismatch_reports_exactly_the_missing_observable_tags():
    wrong = DeviceRegistration(
        device_id="cam-w", address="h", username="u", credential_id="c1",
        node_tags=frozenset({"compute.cpu", "arch.x86_64", "sensor.camera.imx708_wide", "runtime.python3",
                             "accel.edgetpu_usb"}),  # accel.* is not observable, must not count
    )
    r, ssh = runner(wrong)
    result = r.run_l2(wrong)
    assert (result.ok, result.reason) == (False, "tag_mismatch")
    assert result.measured["missing"] == ["arch.x86_64", "sensor.camera.imx708_wide"]
    assert "accel.edgetpu_usb" not in result.measured["checked"]
    assert set(result.measured["observed"]) == {"compute.cpu", "arch.arm64", "sensor.camera.imx708", "runtime.python3"}
    assert result.measured["cameras"] == ["imx708"]
    assert ssh.commands == [smoke.IDENTITY_PROBE_SCRIPT]


def test_l2_wide_camera_does_not_also_satisfy_the_plain_model_tag():
    sections = smoke.parse_sections(WIDE_IDENTITY)
    observed = smoke.observed_tags(sections)
    assert "sensor.camera.imx708_wide" in observed
    assert "sensor.camera.imx708" not in observed


def test_l2_pass_lists_unregistered_observed_tags_without_failing():
    fewer = DeviceRegistration(device_id="cam-f", address="h", username="u", credential_id="c1",
                               node_tags=frozenset({"compute.cpu", "arch.arm64"}))
    r, _ = runner(fewer)
    result = r.run_l2(fewer)
    assert (result.ok, result.reason) == (True, "reachable")
    assert result.measured["unregistered"] == ["runtime.python3", "sensor.camera.imx708"]
    assert result.measured["nproc"] == "4"
    assert result.measured["video_devices"] == ["/dev/video0", "/dev/video1"]


def test_l2_permission_denied_maps_to_auth_failed():
    ssh = FakeSsh(proc("", "u@h: Permission denied (publickey,password).", rc=255))
    r, _ = runner(CAMERA, ssh=ssh)
    result = r.run_l2(CAMERA)
    assert (result.ok, result.reason) == (False, "auth_failed")
    assert result.measured["returncode"] == 255
    assert result.measured["credential"] == {"credential_id": "c1", "auth_method": "key", "has_secret": False,
                                             "key_path": "~/.ssh/id_test"}


def test_l2_connection_refused_maps_to_ssh_refused():
    ssh = FakeSsh(proc("", "ssh: connect to host h port 22: Connection refused", rc=255))
    r, _ = runner(CAMERA, ssh=ssh)
    assert r.run_l2(CAMERA).reason == "ssh_refused"


def test_l2_ssh_timeout_exception_maps_to_ssh_refused():
    ssh = FakeSsh(raise_=subprocess.TimeoutExpired("ssh", 60))
    r, _ = runner(CAMERA, ssh=ssh)
    result = r.run_l2(CAMERA)
    assert result.reason == "ssh_refused" and result.measured["error"] == "timeout"


def test_l2_remote_script_failure_is_command_failed_not_unreachable():
    ssh = FakeSsh(proc("", "sh: syntax error", rc=2))
    r, _ = runner(CAMERA, ssh=ssh)
    assert r.run_l2(CAMERA).reason == "command_failed"


def test_l2_missing_password_material_is_auth_failed():
    from mission_runtime.providers.ondevice_ssh import _AuthUnavailable

    ssh = FakeSsh(raise_=_AuthUnavailable("credential_missing"))
    r, _ = runner(CAMERA, ssh=ssh)
    result = r.run_l2(CAMERA)
    assert (result.reason, result.measured["error"]) == ("auth_failed", "credential_missing")


# --- L3 -----------------------------------------------------------------------


def test_l3_camera_frame_ok_with_byte_count_and_timestamp():
    r, ssh = runner(CAMERA)
    result = r.run_l3(CAMERA)
    assert (result.ok, result.reason, result.level) == (True, "reachable", 3)
    assert result.measured["probe_kind"] == "camera_frame"
    assert result.measured["frame_bytes"] == 48211
    assert result.measured["frame_mtime"] == 1727500000
    assert ssh.commands == [smoke.FRAME_PROBE_SCRIPT]


def test_l3_no_cameras_available_is_no_camera():
    ssh = FakeSsh(frame=proc("@fail\nERROR: *** no cameras available ***\n"))
    r, _ = runner(CAMERA, ssh=ssh)
    result = r.run_l3(CAMERA)
    assert (result.ok, result.reason) == (False, "no_camera")
    assert result.measured["frame_bytes"] == 0
    assert "no cameras available" in result.measured["capture_log"]


def test_l3_capture_without_a_file_is_no_frame():
    ssh = FakeSsh(frame=proc("@fail\nERROR: pipeline stalled\n"))
    r, _ = runner(CAMERA, ssh=ssh)
    assert r.run_l3(CAMERA).reason == "no_frame"


def test_l3_zero_byte_frame_is_no_frame():
    ssh = FakeSsh(frame=proc("@frame\n0 1727500000\n"))
    r, _ = runner(CAMERA, ssh=ssh)
    result = r.run_l3(CAMERA)
    assert (result.ok, result.reason, result.measured["frame_bytes"]) == (False, "no_frame", 0)


def test_l3_uav_is_not_implemented_and_not_ok_and_runs_nothing():
    r, ssh = runner(UAV)
    result = r.run_l3(UAV)
    assert (result.ok, result.reason) == (False, "not_implemented")
    assert result.measured["probe_kind"] == "uav_heartbeat"
    assert ssh.commands == []


def test_l3_robot_bridge_is_not_implemented_with_the_gateway_note():
    r, ssh = runner(ROBOT)
    result = r.run_l3(ROBOT)
    assert (result.ok, result.reason) == (False, "not_implemented")
    assert result.measured["probe_kind"] == "robot_uplink"
    assert "physical_command_gateway" in result.measured["note"]
    assert ssh.commands == []


def test_probe_kind_precedence():
    assert smoke.probe_kind_for({"sensor.camera.360", "compute.cpu"}) == "camera_360_stream"
    assert smoke.probe_kind_for({"tier.uav", "sensor.camera.uav"}) == "uav_heartbeat"
    assert smoke.probe_kind_for({"tier.ugv", "sensor.camera.go1_front"}) == "robot_uplink"
    assert smoke.probe_kind_for({"sensor.camera.imx708"}) == "camera_frame"
    assert smoke.probe_kind_for({"compute.cpu"}) == "none"


# --- orchestration ------------------------------------------------------------


def test_run_stops_at_first_failure_per_device():
    r, ssh = runner(CAMERA, UAV, icmp=lambda a, **k: dead_ping(a) if a.startswith("uav") else ok_ping(a))
    results = r.run(3, ["cam-a", "uav-a"])
    assert [(x.device_id, x.level, x.ok) for x in results] == [
        ("cam-a", 1, True), ("cam-a", 2, True), ("cam-a", 3, True),
        ("uav-a", 1, False),
    ]
    assert len(ssh.commands) == 2  # identity + frame for cam-a only


def test_run_stops_after_l2_tag_mismatch():
    ssh = FakeSsh(proc(WIDE_IDENTITY))
    r, _ = runner(CAMERA, ssh=ssh)
    results = r.run(3, ["cam-a"])
    assert [(x.level, x.reason) for x in results] == [(1, "reachable"), (2, "tag_mismatch")]
    assert ssh.commands == [smoke.IDENTITY_PROBE_SCRIPT]


def test_run_honours_the_requested_depth():
    r, ssh = runner(CAMERA)
    assert [x.level for x in r.run(1, ["cam-a"])] == [1]
    assert ssh.commands == []


def test_run_defaults_to_every_registered_device():
    r, _ = runner(CAMERA, UAV)
    assert {x.device_id for x in r.run(1)} == {"cam-a", "uav-a"}


def test_run_unknown_device_is_a_config_error():
    r, _ = runner(CAMERA)
    with pytest.raises(ValueError, match="unknown device"):
        r.run(1, ["ghost"])
    with pytest.raises(ValueError):
        r.run(4, ["cam-a"])


# --- consumers ------------------------------------------------------------------


def test_runtime_instances_take_ttl_and_health_from_the_deepest_level():
    now = 1000.0
    results = [
        smoke.ProbeResult("cam-a", 1, True, "reachable", {}, now),
        smoke.ProbeResult("cam-a", 2, True, "reachable", {}, now),
        smoke.ProbeResult("cam-a", 3, True, "reachable", {}, now),
        smoke.ProbeResult("uav-a", 1, True, "reachable", {}, now),
        smoke.ProbeResult("uav-a", 2, False, "auth_failed", {}, now),
        smoke.ProbeResult("ugv-a", 1, False, "host_unreachable", {}, now),
    ]
    instances = smoke.to_runtime_instances(results)
    assert set(instances) == {"cam-a", "uav-a", "ugv-a"}
    cam = instances["cam-a"]
    assert isinstance(cam, RuntimeInstance)
    assert (cam.healthy, cam.health_ttl, cam.health_checked_at) == (True, 600.0, now)
    assert cam.is_selectable(now=now + 599) and not cam.is_selectable(now=now + 601)
    uav = instances["uav-a"]
    assert (uav.healthy, uav.health_ttl) == (False, 300.0)
    assert not uav.is_selectable(now=now)
    assert (instances["ugv-a"].healthy, instances["ugv-a"].health_ttl) == (False, 60.0)
    assert cam.deployment_ref == "hw_smoke:L3:reachable"


def test_report_json_uses_dictionary_names_and_is_written_under_the_stamp_dir(tmp_path):
    results = [
        smoke.ProbeResult("cam-a", 1, True, "reachable", {"rtt_avg_ms": 4.0}, 1000.0),
        smoke.ProbeResult("cam-a", 2, False, "tag_mismatch", {"missing": ["arch.x86_64"]}, 1001.0),
    ]
    path = smoke.write_report(results, tmp_path / "out" / "x.json", clock=lambda: 2000.0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"generated_at", "results", "summary"}
    assert payload["generated_at"] == 2000.0
    first = payload["results"][0]
    assert set(first) == {dd.DEVICE_ID, dd.DEVICE_PROBE_LEVEL, "ok", dd.DEVICE_PROBE_REASON, "measured", dd.PROBED_AT}
    assert first[dd.DEVICE_PROBE_LEVEL] == 1 and first[dd.PROBED_AT] == 1000.0
    assert payload["summary"]["cam-a"] == {
        dd.DEVICE_PROBE_LEVEL: 2, "ok": False, dd.DEVICE_PROBE_REASON: "tag_mismatch", dd.PROBED_AT: 1001.0,
    }
    # default location: reports/hw_smoke/<YYYYMMDD-HHMM>.json, dir created
    assert smoke.REPORT_DIR == _FRAMEWORK_DIR / "reports" / "hw_smoke"


def test_every_harness_reason_constant_is_in_the_dictionary_vocabulary():
    constants = {v for k, v in vars(smoke).items() if k.startswith("PROBE_") and not k.startswith("PROBE_KIND") and isinstance(v, str)}
    assert constants
    assert constants <= set(dd.DEVICE_PROBE_REASONS)
    assert set(dd.DEVICE_PROBE_REASONS).isdisjoint(set(dd.STATE_CHANGE_REASONS) - {"reachable"})


def test_reason_is_never_a_free_string_in_results():
    r, ssh = runner(CAMERA, UAV, ROBOT)
    ssh.identity = proc("", "Permission denied", rc=255)
    reasons = {x.reason for x in r.run(3)}
    assert reasons <= set(dd.DEVICE_PROBE_REASONS)


# --- CLI ------------------------------------------------------------------------


def test_cli_parses_adhoc_and_override_without_touching_config(tmp_path):
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps({"devices": [CAMERA.as_dict()]}), encoding="utf-8")
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"credentials": [{"credential_id": "c1", "auth_method": "key"}]}), encoding="utf-8")
    creds.chmod(0o600)
    args = cli.argparse.Namespace(
        devices=str(devices), credentials=str(creds), password_env="",
        address_override=["cam-a=cam-a.overlay.example"],
        adhoc=["cam-b=physical@cam-b.overlay.example:2222:tags=compute.cpu,sensor.camera.imx708_wide:cred=c1"],
    )
    registry = cli.build_registry(args)
    assert registry.get("cam-a").address == "cam-a.overlay.example"
    assert registry.get("cam-a").node_tags == CAMERA.node_tags
    adhoc = registry.get("cam-b")
    assert (adhoc.username, adhoc.port, adhoc.credential_id) == ("physical", 2222, "c1")
    assert adhoc.node_tags == {"compute.cpu", "sensor.camera.imx708_wide"}
    assert json.loads(devices.read_text())["devices"][0]["address"] == "cam-a.example"  # untouched
    with pytest.raises(cli.CliError):
        cli.parse_adhoc("bad")
    with pytest.raises(cli.CliError):
        cli.parse_adhoc("x=nouser")
    with pytest.raises(cli.CliError):
        cli.parse_override("noequals")


def test_cli_config_error_exits_nonzero_but_device_failure_does_not(tmp_path, monkeypatch):
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps({"devices": [CAMERA.as_dict()]}), encoding="utf-8")
    creds = tmp_path / "creds.json"
    creds.write_text(json.dumps({"credentials": []}), encoding="utf-8")
    creds.chmod(0o600)
    assert cli.main(["--devices", str(devices), "--credentials", str(creds), "--only", "ghost", "--no-report"]) == 2
    assert cli.main(["--devices", str(tmp_path / "missing.json"), "--credentials", str(creds), "--no-report"]) == 2

    class Fake(smoke.SmokeRunner):
        def __init__(self, registry, **_):
            super().__init__(registry, icmp=dead_ping, resolve=resolves, clock=lambda: 1.0)

    monkeypatch.setattr(smoke, "SmokeRunner", Fake)
    assert cli.main(["--devices", str(devices), "--credentials", str(creds), "--level", "3", "--no-report"]) == 0


def test_table_renders_one_row_per_device_with_level_columns():
    results = [
        smoke.ProbeResult("cam-a", 1, True, "reachable", {"rtt_avg_ms": 4.2, "rtt_mdev_ms": 0.5, "loss_fraction": 0.0}, 1.0),
        smoke.ProbeResult("cam-a", 2, False, "tag_mismatch", {"missing": ["arch.x86_64"]}, 1.0),
        smoke.ProbeResult("uav-a", 1, False, "dns_unresolved", {}, 1.0),
    ]
    table = cli.render_table(results, ["cam-a", "uav-a"])
    lines = table.splitlines()
    assert lines[0].split() == ["device", "L1", "reach", "L2", "identity", "L3", "function"]
    assert "cam-a" in lines[2] and "4.2ms±0.5 0% loss" in lines[2] and "missing=arch.x86_64" in lines[2]
    assert "uav-a" in lines[3] and "FAIL dns_unresolved" in lines[3]


def test_default_report_path_never_overwrites_a_same_minute_report(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "REPORT_DIR", tmp_path)
    results = [smoke.ProbeResult("cam-a", 1, True, "reachable", {}, 1000.0)]
    first = smoke.write_report(results, clock=lambda: 1000.0)
    second = smoke.write_report(results, clock=lambda: 1000.0)
    assert first.parent == tmp_path and first.name.endswith(".json")
    assert second != first and second.exists() and first.exists()
    assert second.name == first.stem + "-1.json"


# --- the real scripts, through a local shell ------------------------------------
# Like tests/test_ondevice_ssh.py: the network hop is the only thing removed.
# What is under test is that the POSIX-sh strings actually run and produce
# output the parser reads — the part a fake cannot catch.

import platform
import shutil


class LocalShRunner:
    def __init__(self):
        self.commands = []

    def factory(self, device, credential):
        return self

    def run(self, command, *, timeout=None, stdin=None):
        self.commands.append(command)
        return subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=timeout or 60)


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh")
def test_identity_script_runs_locally_and_yields_this_machines_arch_tag():
    sh = LocalShRunner()
    r = smoke.SmokeRunner(registry_with(CAMERA), icmp=ok_ping, resolve=resolves, ssh_factory=sh.factory, clock=lambda: 1.0)
    result = r.run_l2(CAMERA)
    assert result.reason in {"reachable", "tag_mismatch"}  # depends on the local box, but never a transport failure
    assert result.measured["arch"] == platform.machine()
    expected_arch = {tag for section, token, tag in smoke.TAG_RULES if section == "arch" and token == platform.machine()}
    assert expected_arch <= set(result.measured["observed"])
    if shutil.which("python3"):
        assert "runtime.python3" in result.measured["observed"]
    assert "compute.cpu" in result.measured["observed"]


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh")
def test_frame_script_without_a_capture_tool_is_no_frame_not_command_failed():
    if shutil.which("rpicam-still") or shutil.which("libcamera-still"):
        pytest.skip("a real capture tool is present; this test covers the tool-less path")
    sh = LocalShRunner()
    r = smoke.SmokeRunner(registry_with(CAMERA), icmp=ok_ping, resolve=resolves, ssh_factory=sh.factory, clock=lambda: 1.0)
    result = r.run_l3(CAMERA)
    assert (result.ok, result.reason) == (False, "no_frame")
    assert "capture tool not found" in result.measured["capture_log"]
