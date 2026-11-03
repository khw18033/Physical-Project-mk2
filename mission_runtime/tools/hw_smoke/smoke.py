"""Connection smoke harness — "which registered devices are reachable, and how
far do they work" — as a pure, injectable core (no network in tests).

implements: AI-B-04, AI-B-09, AI-O-04, AI-C-10, AI-C-18 (review/bring-up tooling)

Plan: 장비 bring-up 계획 노트(비공개) §2-2.
Three levels, run in order, stopping at the first failure:

* **L1 도달** — the registered address resolves and answers ICMP. The
  measurement is `providers/link_probe.py::LinkMeasurement`, unchanged: the
  same probe `tools/status_ui/serve.py::probe_device_link` runs.
* **L2 신원·계층** — SSH login works and the device *is what the registry
  says*: a fixed POSIX-sh probe script is run through `SshRunner` and its
  output is turned into **observed tags** by the `TAG_RULES` data table, then
  compared with `DeviceRegistration.node_tags`. AI-B-09: 새 구성은 검증되기
  전에는 정상 선택 후보로 간주하지 않는다 — a registered tag the device does
  not exhibit is `tag_mismatch`, and the missing list is part of the result.
  `providers/compute.py::discover_node_tags()` cannot be reused here because
  it probes the *local* node; for a remote device the tags must come from
  remote shell output.
* **L3 기능** — one real function per device kind (a captured frame for a
  camera). Kinds without a probe provider yet answer `not_implemented`, which
  is **not** ok: the harness never fakes a pass (CLAUDE.md: never fabricate
  results).

Two boundaries matter:

* A result is an *observation*, never an availability verdict. `ProbeResult`
  converts to a `RuntimeInstance` (healthy/health_ttl/health_checked_at) so
  the status UI can show freshness, but the backend still owns the device's
  final availability (원칙 #15, AI-O-04).
* Reason tokens are the closed vocabulary `DEVICE_PROBE_REASONS` in the data
  dictionary — separate from `STATE_CHANGE_REASONS`, because "does the
  device answer" and "can this capability run" are different questions.
  `tests/test_data_dictionary.py` proves the constants here stay inside it.

This module lives in `tools/`, so it may name device-side commands
(`rpicam-still` is what a Raspberry Pi camera stack ships); nothing under
`mission_runtime/` imports it.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from mission_runtime.contracts import data_dictionary as dd
from mission_runtime.contracts.capability_contract import RuntimeInstance
from mission_runtime.providers import ondevice_ssh
from mission_runtime.providers.link_probe import LinkMeasurement, probe_icmp
from mission_runtime.providers.ondevice_ssh import SshRunner
from mission_runtime.registry.device_registry import DeviceCredential, DeviceRegistration, DeviceRegistry

# --- vocabulary (owned by the data dictionary; the strings are fixed here) ---
PROBE_REACHABLE = "reachable"
PROBE_DNS_UNRESOLVED = "dns_unresolved"
PROBE_HOST_UNREACHABLE = "host_unreachable"
PROBE_SSH_REFUSED = "ssh_refused"
PROBE_AUTH_FAILED = "auth_failed"
PROBE_COMMAND_FAILED = "command_failed"
PROBE_TAG_MISMATCH = "tag_mismatch"
PROBE_NO_CAMERA = "no_camera"
PROBE_NO_FRAME = "no_frame"
PROBE_NO_HEARTBEAT = "no_heartbeat"
PROBE_NOT_IMPLEMENTED = "not_implemented"

LEVEL_REACH = 1
LEVEL_IDENTITY = 2
LEVEL_FUNCTION = 3
LEVELS = (LEVEL_REACH, LEVEL_IDENTITY, LEVEL_FUNCTION)

#: How long a passed probe at each level counts as fresh for the status UI
#: (`RuntimeInstance.health_ttl`). A ping is cheap and goes stale fast; a
#: captured frame is strong evidence and may be trusted longer.
LEVEL_TTL_S: dict[int, float] = {LEVEL_REACH: 60.0, LEVEL_IDENTITY: 300.0, LEVEL_FUNCTION: 600.0}

#: Tag prefixes L2 can actually observe over a shell. Only registered tags in
#: this set can be *contradicted*; `accel.*`, `tier.*`, `thermal.*` and the
#: like are declarations the probe has no way to check, so their absence from
#: the observed set is not a mismatch (AI-C-18: 모든 항목이 항상 존재한다고
#: 가정하지 않는다).
OBSERVABLE_TAG_PREFIXES: tuple[str, ...] = ("arch.", "sensor.camera.", "runtime.")

#: (section, exact token, tag). A section is one `@name` block of the probe
#: script's output; a token is one whitespace-separated word of that block
#: (camera model names are extracted first, see `_camera_models`). Adding a
#: sensor or an architecture is a row here, never a code change (원칙 #7).
TAG_RULES: tuple[tuple[str, str, str], ...] = (
    ("arch", "aarch64", "arch.arm64"),
    ("arch", "arm64", "arch.arm64"),
    ("arch", "armv7l", "arch.arm32"),
    ("arch", "x86_64", "arch.x86_64"),
    ("cameras", "imx708_wide", "sensor.camera.imx708_wide"),
    ("cameras", "imx708", "sensor.camera.imx708"),
    ("cameras", "imx219", "sensor.camera.imx219"),
    ("cameras", "imx477", "sensor.camera.imx477"),
    ("cameras", "imx296", "sensor.camera.imx296"),
    ("cameras", "ov5647", "sensor.camera.ov5647"),
    ("python3", "python3", "runtime.python3"),
)
#: Every node that answers a shell has a CPU; `compute.cpu` is the same
#: unconditional tag `discover_node_tags()` starts from.
ALWAYS_OBSERVED_TAGS: frozenset[str] = frozenset({"compute.cpu"})

#: One POSIX-sh line per fact, each guarded so a missing tool prints nothing
#: instead of aborting the script. `@section` markers make the output
#: parseable without caring about line counts. The trailing `true` keeps the
#: exit status about *logging in*, not about the last optional tool.
IDENTITY_PROBE_SCRIPT = (
    "echo @arch; uname -m; "
    "echo @nproc; nproc 2>/dev/null; "
    "echo @cameras; for c in rpicam-hello libcamera-hello; do "
    "command -v $c >/dev/null 2>&1 && { $c --list-cameras 2>&1 | head -20; break; }; done; "
    "echo @video; ls /dev/video* 2>/dev/null; "
    "echo @python3; command -v python3; "
    "echo @end; true"
)

#: Capture one small frame, print `<bytes> <mtime>` on success. Tool output
#: goes to a log so stdout stays parseable; the log tail is printed on
#: failure so `no_camera` can be told apart from `no_frame`. The script's own
#: exit status is forced to 0 so a nonzero return can only mean "ssh/login
#: failed" — the capture verdict is read from the output, never the code.
FRAME_PROBE_SCRIPT = (
    "f=/tmp/hw_smoke.jpg; l=/tmp/hw_smoke.log; rm -f $f; "
    "for c in rpicam-still libcamera-still; do command -v $c >/dev/null 2>&1 || continue; "
    "$c -n -t 500 --width 640 --height 480 -o $f >$l 2>&1; break; done; "
    "if [ -s $f ]; then echo @frame; stat -c '%s %Y' $f; "
    "else echo @fail; if [ -f $l ]; then tail -5 $l; "
    "else echo 'capture tool not found: rpicam-still/libcamera-still'; fi; fi; true"
)

_CAMERA_LINE = re.compile(r"^\s*\d+\s*:\s*(\S+)\s*\[", re.MULTILINE)

#: Which L3 probe a device gets, decided by tags in this order (first match
#: wins — a 360 camera also carries a `sensor.camera.` prefix and must not
#: fall into the still-frame probe).
PROBE_KIND_CAMERA_360 = "camera_360_stream"
PROBE_KIND_UAV = "uav_heartbeat"
PROBE_KIND_ROBOT = "robot_uplink"
PROBE_KIND_CAMERA = "camera_frame"
PROBE_KIND_NONE = "none"


def probe_kind_for(tags: Iterable[str]) -> str:
    tags = set(tags)
    if any(t.startswith("sensor.camera.360") for t in tags):
        return PROBE_KIND_CAMERA_360
    if "platform.uav" in tags or "tier.uav" in tags:
        return PROBE_KIND_UAV
    if "tier.ugv" in tags:
        return PROBE_KIND_ROBOT
    if any(t.startswith("sensor.camera.") for t in tags):
        return PROBE_KIND_CAMERA
    return PROBE_KIND_NONE


# --- result ------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    """One level's outcome for one device. `ok` is exactly `reason == reachable`;
    `measured` carries whatever was actually read (never a fabricated value)."""

    device_id: str
    level: int
    ok: bool
    reason: str
    measured: dict
    probed_at: float

    def as_dict(self) -> dict:
        return {
            dd.DEVICE_ID: self.device_id,
            dd.DEVICE_PROBE_LEVEL: self.level,
            "ok": self.ok,
            dd.DEVICE_PROBE_REASON: self.reason,
            "measured": self.measured,
            dd.PROBED_AT: self.probed_at,
        }


def _default_ssh_factory(device: DeviceRegistration, credential: DeviceCredential | None) -> SshRunner:
    return SshRunner(device, credential, connect_timeout_s=10, command_timeout_s=60)


def _default_resolve(address: str) -> list[str]:
    infos = socket.getaddrinfo(address, None)
    return sorted({info[4][0] for info in infos})


class SmokeRunner:
    """Runs L1→L2→L3 per device. Every side effect is a constructor argument
    so tests substitute fakes: `icmp(address, count=...)` → `LinkMeasurement`,
    `resolve(address)` → list of IPs (raises `OSError` when unresolved),
    `ssh_factory(device, credential)` → something with `.run(command,
    timeout=...)` returning a `CompletedProcess`, `clock()` → epoch seconds."""

    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        icmp: Callable[..., LinkMeasurement] = probe_icmp,
        resolve: Callable[[str], list[str]] = _default_resolve,
        ssh_factory: Callable[[DeviceRegistration, DeviceCredential | None], Any] = _default_ssh_factory,
        clock: Callable[[], float] = time.time,
        icmp_count: int = 5,
    ) -> None:
        self._registry = registry
        self._icmp = icmp
        self._resolve = resolve
        self._ssh_factory = ssh_factory
        self._clock = clock
        self._icmp_count = icmp_count

    # --- L1 -----------------------------------------------------------------
    def run_l1(self, device: DeviceRegistration) -> ProbeResult:
        now = self._clock()
        try:
            addresses = self._resolve(device.address)
        except OSError as error:
            return ProbeResult(device.device_id, LEVEL_REACH, False, PROBE_DNS_UNRESOLVED,
                               {"address": device.address, "error": str(error)}, now)
        measurement = self._icmp(device.address, count=self._icmp_count, interval_s=0.2)
        measured = measurement.as_dict()
        measured["resolved"] = list(addresses)
        if not measurement.measured or measurement.received == 0:
            # "재봤고 전부 실패" and "재지 못했다" both stop here; the raw
            # measurement (with its own `reason`) says which.
            return ProbeResult(device.device_id, LEVEL_REACH, False, PROBE_HOST_UNREACHABLE, measured, now)
        return ProbeResult(device.device_id, LEVEL_REACH, True, PROBE_REACHABLE, measured, now)

    # --- L2 -----------------------------------------------------------------
    def _run_remote(self, device: DeviceRegistration, script: str, timeout: int) -> tuple[subprocess.CompletedProcess | None, str | None, dict]:
        """Run `script` on the device. Returns (proc, failure_reason, detail)."""
        credential = self._registry.credential_for(device.device_id)
        detail: dict = {"credential": credential.redacted() if credential else None}
        try:
            runner = self._ssh_factory(device, credential)
            proc = runner.run(script, timeout=timeout)
        except ondevice_ssh._AuthUnavailable as error:
            detail["error"] = error.reason
            return None, PROBE_AUTH_FAILED, detail
        except subprocess.TimeoutExpired:
            detail["error"] = "timeout"
            return None, PROBE_SSH_REFUSED, detail
        except OSError as error:
            detail["error"] = str(error)
            return None, PROBE_SSH_REFUSED, detail
        if proc.returncode == 0:
            return proc, None, detail
        detail["returncode"] = proc.returncode
        detail["stderr"] = (proc.stderr or "").strip()[-500:]
        return proc, _ssh_failure_reason(proc), detail

    def run_l2(self, device: DeviceRegistration) -> ProbeResult:
        now = self._clock()
        proc, failure, detail = self._run_remote(device, IDENTITY_PROBE_SCRIPT, timeout=60)
        if failure is not None:
            return ProbeResult(device.device_id, LEVEL_IDENTITY, False, failure, detail, now)
        sections = parse_sections(proc.stdout or "")
        observed = observed_tags(sections)
        registered = set(device.node_tags)
        checkable = {t for t in registered if t.startswith(OBSERVABLE_TAG_PREFIXES)}
        missing = sorted(checkable - observed)
        measured = {
            **detail,
            "arch": " ".join(sections.get("arch", ())),
            "nproc": " ".join(sections.get("nproc", ())),
            "cameras": _camera_models(sections.get("cameras", ())),
            "video_devices": [w for line in sections.get("video", ()) for w in line.split()],
            "python3": " ".join(sections.get("python3", ())),
            "observed": sorted(observed),
            "registered": sorted(registered),
            "checked": sorted(checkable),
            "missing": missing,
            "unregistered": sorted(observed - registered),
        }
        if missing:
            return ProbeResult(device.device_id, LEVEL_IDENTITY, False, PROBE_TAG_MISMATCH, measured, now)
        return ProbeResult(device.device_id, LEVEL_IDENTITY, True, PROBE_REACHABLE, measured, now)

    # --- L3 -----------------------------------------------------------------
    def run_l3(self, device: DeviceRegistration) -> ProbeResult:
        now = self._clock()
        kind = probe_kind_for(device.node_tags)
        base = {"probe_kind": kind}
        if kind == PROBE_KIND_CAMERA:
            return self._probe_camera_frame(device, now, base)
        if kind == PROBE_KIND_UAV:
            base["note"] = "MAVLink HEARTBEAT probe is a later provider (px4_mavsdk_robot); nothing was measured"
        elif kind == PROBE_KIND_ROBOT:
            base["note"] = "capability uplink via physical_command_gateway; no probe provider yet, nothing was measured"
        elif kind == PROBE_KIND_CAMERA_360:
            base["note"] = "360 live-stream ingest adapter does not exist yet; nothing was measured"
        else:
            base["note"] = "no L3 probe for these tags"
        return ProbeResult(device.device_id, LEVEL_FUNCTION, False, PROBE_NOT_IMPLEMENTED, base, now)

    def _probe_camera_frame(self, device: DeviceRegistration, now: float, base: dict) -> ProbeResult:
        proc, failure, detail = self._run_remote(device, FRAME_PROBE_SCRIPT, timeout=90)
        measured = {**base, **detail}
        if failure is not None:
            return ProbeResult(device.device_id, LEVEL_FUNCTION, False, failure, measured, now)
        sections = parse_sections(proc.stdout or "")
        frame = sections.get("frame", ())
        if frame:
            parts = frame[0].split()
            size = _int_or_none(parts[0]) if parts else None
            mtime = _int_or_none(parts[1]) if len(parts) > 1 else None
            measured.update({"frame_bytes": size, "frame_mtime": mtime, "frame_path": "/tmp/hw_smoke.jpg"})
            if size:
                return ProbeResult(device.device_id, LEVEL_FUNCTION, True, PROBE_REACHABLE, measured, now)
            return ProbeResult(device.device_id, LEVEL_FUNCTION, False, PROBE_NO_FRAME, measured, now)
        tail = "\n".join(sections.get("fail", ()))
        measured["capture_log"] = tail[-500:]
        measured["frame_bytes"] = 0
        if "no cameras available" in tail.lower():
            return ProbeResult(device.device_id, LEVEL_FUNCTION, False, PROBE_NO_CAMERA, measured, now)
        return ProbeResult(device.device_id, LEVEL_FUNCTION, False, PROBE_NO_FRAME, measured, now)

    # --- orchestration ------------------------------------------------------
    def run(self, levels: int = LEVEL_FUNCTION, device_ids: Iterable[str] | None = None) -> list[ProbeResult]:
        """L1 then L2 then L3 per device, stopping at the first failure. An
        unknown id is a config error (ValueError), not a result."""
        if levels not in LEVELS:
            raise ValueError(f"levels must be one of {LEVELS}, got {levels!r}")
        if device_ids is None:
            devices = self._registry.devices()
        else:
            devices = []
            for device_id in device_ids:
                device = self._registry.get(device_id)
                if device is None:
                    raise ValueError(f"unknown device: {device_id}")
                devices.append(device)
        steps = {LEVEL_REACH: self.run_l1, LEVEL_IDENTITY: self.run_l2, LEVEL_FUNCTION: self.run_l3}
        results: list[ProbeResult] = []
        for device in devices:
            for level in LEVELS:
                if level > levels:
                    break
                result = steps[level](device)
                results.append(result)
                if not result.ok:
                    break
        return results


# --- parsing --------------------------------------------------------------------


def parse_sections(output: str) -> dict[str, tuple[str, ...]]:
    """`@name` marker lines split the script output into named blocks."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in output.splitlines():
        line = raw.rstrip()
        if line.startswith("@") and " " not in line.strip():
            current = line.strip()[1:]
            sections.setdefault(current, [])
            continue
        if current is not None and line.strip():
            sections[current].append(line.strip())
    return {name: tuple(lines) for name, lines in sections.items()}


def _camera_models(lines: Iterable[str]) -> list[str]:
    return _CAMERA_LINE.findall("\n".join(lines))


def observed_tags(sections: dict[str, tuple[str, ...]]) -> set[str]:
    """Apply `TAG_RULES` to the parsed probe output. Tokens are exact words,
    so `imx708_wide` does not also light up `imx708`."""
    tokens: dict[str, set[str]] = {}
    for name, lines in sections.items():
        if name == "cameras":
            tokens[name] = set(_camera_models(lines))
        else:
            tokens[name] = {w for line in lines for w in line.split()}
    if tokens.get("python3"):
        tokens["python3"].add("python3")  # `command -v` prints a path; the fact is "python3 exists"
    tags = set(ALWAYS_OBSERVED_TAGS)
    for section, token, tag in TAG_RULES:
        if token in tokens.get(section, ()):
            tags.add(tag)
    return tags


def _ssh_failure_reason(proc: subprocess.CompletedProcess) -> str:
    """Nonzero exit → probe vocabulary, through the provider's own mapping.

    Exit 255 is ssh's own failure; anything else came from the remote shell,
    which means login worked and the *script* failed. Auth is checked on the
    text *before* the exit code: a rejected credential is also exit 255, and
    `reject_reason_for` folds that into "unreachable" — for deployment that
    is the right verdict (the unit did not get there), for a smoke probe the
    distinction is the whole point."""
    stderr = (proc.stderr or "").lower()
    if "permission denied" in stderr or "authentication failed" in stderr or "host key verification failed" in stderr:
        return PROBE_AUTH_FAILED
    if ondevice_ssh.reject_reason_for(proc) == ondevice_ssh.REASON_NOT_PERMITTED:
        return PROBE_AUTH_FAILED
    if proc.returncode == 255 or "connection" in stderr or "timed out" in stderr:
        return PROBE_SSH_REFUSED
    return PROBE_COMMAND_FAILED


def _int_or_none(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --- consumers ------------------------------------------------------------------


def highest_results(results: Iterable[ProbeResult]) -> dict[str, ProbeResult]:
    """The deepest level reached per device (its result decides freshness)."""
    best: dict[str, ProbeResult] = {}
    for result in results:
        current = best.get(result.device_id)
        if current is None or result.level > current.level:
            best[result.device_id] = result
    return best


def to_runtime_instances(results: Iterable[ProbeResult]) -> dict[str, RuntimeInstance]:
    """Freshness for the status UI: healthy iff the deepest level attempted
    passed; TTL grows with the level; `health_checked_at` is the observation
    time. This is *not* the device's availability (원칙 #15) — it is how old
    the last successful probe is."""
    instances: dict[str, RuntimeInstance] = {}
    for device_id, result in highest_results(results).items():
        instances[device_id] = RuntimeInstance(
            instance_id=device_id,
            deployment_ref=f"hw_smoke:L{result.level}:{result.reason}",
            healthy=result.ok,
            health_ttl=LEVEL_TTL_S[result.level],
            health_checked_at=result.probed_at,
        )
    return instances


REPORT_DIR = Path(__file__).resolve().parents[2] / "reports" / "hw_smoke"


def report_payload(results: Iterable[ProbeResult], *, generated_at: float | None = None) -> dict:
    results = list(results)
    return {
        "generated_at": generated_at if generated_at is not None else time.time(),
        "results": [r.as_dict() for r in results],
        "summary": {
            device_id: {
                dd.DEVICE_PROBE_LEVEL: r.level,
                "ok": r.ok,
                dd.DEVICE_PROBE_REASON: r.reason,
                dd.PROBED_AT: r.probed_at,
            }
            for device_id, r in highest_results(results).items()
        },
    }


def write_report(results: Iterable[ProbeResult], path: str | Path | None = None, *, clock: Callable[[], float] = time.time) -> Path:
    """JSON under `reports/hw_smoke/<YYYYMMDD-HHMM>.json` (git-ignored)."""
    now = clock()
    if path is None:
        stamp = time.strftime("%Y%m%d-%H%M", time.localtime(now))
        path = REPORT_DIR / f"{stamp}.json"
        # Two runs in the same minute (e.g. one per device) must not overwrite
        # each other: a report is evidence, and evidence is not replaced.
        suffix = 1
        while path.exists():
            path = REPORT_DIR / f"{stamp}-{suffix}.json"
            suffix += 1
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report_payload(results, generated_at=now), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
