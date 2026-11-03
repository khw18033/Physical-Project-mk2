"""`ControlProvider` for a 말단 that runs no orchestrator control plane.

implements: AI-B-11, AI-B-03, AI-B-04, AI-B-05, AI-B-02, AI-B-10, AI-C-10, AI-C-04

Why this provider has to exist
------------------------------
절대 준수 원칙 #11: "말단은 오케스트레이터 제어면을 필수 설치 대상으로 요구하지
않는다." AI-B-10 says the same in resource terms: 말단은 브로커·수집기·중앙
저장소·오케스트레이터 제어면 같은 서버형 미들웨어를 기본 설치 대상으로 요구하지
않는다. `providers/k3s.py` therefore **cannot** be the answer for a Raspberry Pi
terminal: using it would mean installing a K3s agent (and with it a container
runtime and a control-plane connection) on exactly the node the requirements
forbid it on. The requirement is not "use a lighter orchestrator" — it is that
the *execution-control contract* must be satisfiable without one at all.

AI-B-11 states the resulting shape explicitly: 각 실행영역에서 실제 사용하는
오케스트레이터와 실행 방식은 provider로 분리하고, 중앙 서버와 모든 엣지가 동일한
오케스트레이터를 설치해야 한다는 전제를 두어서는 안 된다. So this module
implements the *same* `ControlProvider` Protocol as `K3sControlProvider` and
`LocalControlSupervisor`, with the same rejection vocabulary, and plugs into
`runtime/clusters.py::MultiClusterControlProvider` as one more
`ClusterBinding`. Upper-layer placement code cannot tell which one it got —
which is the entire point.

What is on the device
---------------------
One shell script (`ondevice_agent.sh`), a per-unit directory, and either a
`systemd --user` unit or a setsid/pidfile supervisor. No daemon of ours, no
broker, no collector, no agent process polling anything. Control is
request-scoped SSH.

Health is three separate readings, never one
--------------------------------------------
AI-B-05: 프로세스의 시작·liveness·readiness와 실제 장치의 운용 상태·안전 상태를
구분해야 하며 하나를 다른 상태의 근거로 대체해서는 안 된다. `UnitHealth`
therefore carries `liveness`, `readiness` and `device_state` as three fields
that are allowed to disagree. A frequency-capped Pi running a perfectly
healthy process is `ALIVE` + `READY` + `THROTTLED`; collapsing that into one
"healthy" boolean would hide the failure a health contract exists to surface.

Credentials
-----------
AI-B-02: 자격증명·비밀정보를 이미지에 포함해서는 안 된다. Secrets come from
`registry/device_registry.py::CredentialStore` (a git-ignored local file), are
never written into an artifact, never appear in `audit_log`/`trace_log`, and
never reach a subprocess argv — a password is handed to `sshpass -e` through
the environment, which is why key auth is installed on first contact and used
from then on.
"""

from __future__ import annotations

import hashlib
import io
import os
import shlex
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from mission_runtime.execution.control import AuditEntry, ControlResult, TargetStatus, TraceEntry
from mission_runtime.registry.device_registry import (
    AUTH_KEY,
    AUTH_PASSWORD,
    DeviceCredential,
    DeviceRegistration,
)

AGENT_SCRIPT_PATH = Path(__file__).with_name("ondevice_agent.sh")
DEFAULT_ROOT = "~/pf_units"

#: Rejection vocabulary. The first block mirrors `providers/k3s.py` word for
#: word so a caller handling one provider's reasons already handles this
#: one's (AI-B-11: 동일한 실행 제어 계약).
REASON_UNKNOWN_TARGET = "unknown_target"
REASON_TARGET_NOT_FOUND = "target_not_found"
REASON_NOT_PERMITTED = "not_permitted"
REASON_UPDATE_REJECTED = "update_rejected"
REASON_ROLLBACK_UNAVAILABLE = "rollback_unavailable"
#: ...and this block is what an SSH-reached terminal can additionally say.
REASON_DEVICE_UNREACHABLE = "device_unreachable"
REASON_DEVICE_TIMEOUT = "device_timeout"
REASON_NO_ACTIVE_VERSION = "no_active_version"
REASON_CHECKSUM_MISMATCH = "checksum_mismatch"
REASON_TRANSFER_FAILED = "transfer_failed"
REASON_MISSING_ARTIFACT = "missing_artifact"
REASON_NO_PREVIOUS_VERSION = "no_previous_version"
REASON_AGENT_MISSING = "agent_not_installed"
REASON_CREDENTIAL_MISSING = "credential_missing"

#: Raspberry Pi `vcgencmd get_throttled` bit meanings. Decoded here rather
#: than on the device so the mapping is unit-testable without hardware; the
#: raw value is always kept alongside, because a bit we have not named yet
#: must not silently disappear.
THROTTLE_BITS: dict[int, str] = {
    0: "under_voltage_now",
    1: "arm_frequency_capped_now",
    2: "currently_throttled",
    3: "soft_temperature_limit_now",
    16: "under_voltage_occurred",
    17: "arm_frequency_capped_occurred",
    18: "throttling_occurred",
    19: "soft_temperature_limit_occurred",
}
#: Bits that mean "the device is degraded *right now*" as opposed to "it was,
#: at some point since boot". Only the former may change `device_state`.
_ACTIVE_THROTTLE_BITS = (0, 1, 2, 3)


class Liveness(str, Enum):
    """Is the unit's process running? (AI-B-05 startup/liveness)"""

    ALIVE = "ALIVE"
    STARTING = "STARTING"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"


class Readiness(str, Enum):
    """Has the unit declared itself able to serve? (AI-B-05 readiness)

    A unit signals this by touching `$PF_READY_FILE`. Absence is
    `NOT_READY`, not `DEAD` — a starting unit is neither.
    """

    READY = "READY"
    NOT_READY = "NOT_READY"
    UNKNOWN = "UNKNOWN"


class DeviceState(str, Enum):
    """The *device's* operational state, independent of any unit on it.

    Kept separate on purpose (AI-B-05). `THROTTLED` here says the board is
    frequency-capped or under-volted now; it says nothing about whether the
    process is alive, and the process being alive says nothing about this.
    """

    NOMINAL = "NOMINAL"
    THROTTLED = "THROTTLED"
    UNREACHABLE = "UNREACHABLE"
    UNKNOWN = "UNKNOWN"


def decode_throttle_flags(raw: str | None) -> tuple[str, ...]:
    """`"0xe0006"` -> the named conditions it encodes.

    An unparseable or empty reading yields `()` — "we did not measure" must
    never be reported as "nothing is wrong"; the caller distinguishes the two
    via `UnitHealth.device_state == UNKNOWN`.
    """
    if not raw:
        return ()
    try:
        value = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 0)
    except (ValueError, TypeError):
        return ()
    flags = [name for bit, name in sorted(THROTTLE_BITS.items()) if value & (1 << bit)]
    unnamed = value & ~sum(1 << bit for bit in THROTTLE_BITS)
    if unnamed:
        flags.append(f"unknown_bits:{unnamed:#x}")
    return tuple(flags)


def _is_actively_throttled(raw: str | None) -> bool:
    if not raw:
        return False
    try:
        value = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 0)
    except (ValueError, TypeError):
        return False
    return any(value & (1 << bit) for bit in _ACTIVE_THROTTLE_BITS)


@dataclass(frozen=True)
class UnitHealth:
    """Three independent readings plus what produced them.

    `reachable=False` means we learned nothing this round: liveness and
    readiness are `UNKNOWN` rather than `DEAD`/`NOT_READY`, because a lost
    link is not evidence that a unit stopped (AI-B-05, AI-O-04: 업무 전송은
    가능하지만 관측 지표가 누락된 경우와 그 반대를 구분할 수 있어야 한다).
    """

    unit_id: str
    device_id: str
    reachable: bool
    liveness: Liveness = Liveness.UNKNOWN
    readiness: Readiness = Readiness.UNKNOWN
    device_state: DeviceState = DeviceState.UNKNOWN
    active_version: str | None = None
    previous_version: str | None = None
    backend: str | None = None
    temperature_c: float | None = None
    throttle_raw: str | None = None
    throttle_flags: tuple[str, ...] = ()
    ready_age_s: float | None = None
    load1: float | None = None
    mem_available_kb: int | None = None
    reason: str | None = None

    def as_status(self) -> TargetStatus:
        """The coarse `ControlProvider` view. Deliberately lossy — callers
        that need the distinction ask for `UnitHealth`, not this."""
        return TargetStatus.RUNNING if self.liveness is Liveness.ALIVE else TargetStatus.STOPPED


@dataclass(frozen=True)
class ArtifactPackage:
    """A packed unit artifact plus the identity that makes it reproducible."""

    path: Path
    version: str
    sha256: str
    source_dir: Path | None = None


def pack_unit_artifact(
    source_dir: str | Path,
    dest_dir: str | Path,
    *,
    version: str | None = None,
) -> ArtifactPackage:
    """Pack a unit's code+config into a deterministic `.tar.gz`.

    AI-B-02: 실행 이미지와 외부 구성은 버전과 식별 가능한 무결성 정보를 유지한다.
    Determinism is the point of every option below — sorted entries, zeroed
    mtime/uid/gid/uname/gname, and a gzip header with no timestamp — so the
    same source tree always produces the same sha256, and `version` defaults
    to that digest. Two deploys claiming one version therefore cannot differ,
    and "is what is on the device what I built?" is answerable by comparison
    rather than by trust.
    """
    source = Path(source_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"artifact source is not a directory: {source}")
    if not (source / "run.sh").is_file():
        raise FileNotFoundError(f"artifact source has no run.sh entrypoint: {source}")

    def _normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.mtime = 0
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        # Preserve only the executable bit; local umask must not travel.
        info.mode = 0o755 if info.mode & 0o100 else 0o644
        return info

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for path in sorted(source.rglob("*"), key=lambda p: str(p.relative_to(source))):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                continue
            archive.add(path, arcname=str(path.relative_to(source)), recursive=False, filter=_normalise)

    import gzip

    compressed = gzip.compress(raw.getvalue(), compresslevel=6, mtime=0)
    digest = hashlib.sha256(compressed).hexdigest()
    resolved_version = version or f"sha256-{digest[:16]}"

    destination = Path(dest_dir)
    destination.mkdir(parents=True, exist_ok=True)
    out = destination / f"{resolved_version}.tar.gz"
    out.write_bytes(compressed)
    return ArtifactPackage(path=out, version=resolved_version, sha256=digest, source_dir=source)


class SshRunner:
    """Runs one command on one device. The only place `ssh`/`scp` is named.

    Not a session: every call is a fresh connection attempt, so a dropped
    link degrades the *next* request instead of leaving a half-dead handle
    behind. `ControlMultiplexing` is available via `extra_opts` for
    deployments that want it, but nothing here depends on it.
    """

    def __init__(
        self,
        device: DeviceRegistration,
        credential: DeviceCredential | None = None,
        *,
        connect_timeout_s: int = 10,
        command_timeout_s: int = 60,
        ssh: str = "ssh",
        scp: str = "scp",
        strict_host_key_checking: str = "accept-new",
        extra_opts: tuple[str, ...] = (),
    ) -> None:
        self._device = device
        self._credential = credential
        self._connect_timeout_s = connect_timeout_s
        self._command_timeout_s = command_timeout_s
        self._ssh = ssh
        self._scp = scp
        self._strict = strict_host_key_checking
        self._extra = tuple(extra_opts)

    @property
    def device(self) -> DeviceRegistration:
        return self._device

    @property
    def credential(self) -> DeviceCredential | None:
        return self._credential

    def with_credential(self, credential: DeviceCredential) -> "SshRunner":
        return SshRunner(
            self._device,
            credential,
            connect_timeout_s=self._connect_timeout_s,
            command_timeout_s=self._command_timeout_s,
            ssh=self._ssh,
            scp=self._scp,
            strict_host_key_checking=self._strict,
            extra_opts=self._extra,
        )

    # --- command construction -------------------------------------------
    def _base_opts(self) -> list[str]:
        opts = [
            "-o", f"ConnectTimeout={self._connect_timeout_s}",
            "-o", f"StrictHostKeyChecking={self._strict}",
            "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=3",
        ]
        method = self._credential.auth_method if self._credential else AUTH_KEY
        if method == AUTH_PASSWORD:
            # BatchMode must stay off or sshpass has no prompt to answer.
            opts += ["-o", "BatchMode=no", "-o", "PubkeyAuthentication=no",
                     "-o", "PreferredAuthentications=password,keyboard-interactive"]
        else:
            opts += ["-o", "BatchMode=yes"]
            if self._credential and self._credential.key_path:
                opts += ["-o", "IdentitiesOnly=yes", "-i", os.path.expanduser(self._credential.key_path)]
        return opts + list(self._extra)

    def _wrap_password(self, argv: list[str]) -> tuple[list[str], dict[str, str] | None]:
        """Password auth goes through `sshpass -e`, i.e. the environment.

        Never `sshpass -p <secret>`: argv is world-readable in `/proc` on the
        controlling host, which would defeat the credential store entirely
        (AI-B-02).
        """
        method = self._credential.auth_method if self._credential else AUTH_KEY
        if method != AUTH_PASSWORD:
            return argv, None
        if not self._credential or self._credential.secret is None:
            raise _AuthUnavailable(REASON_CREDENTIAL_MISSING)
        if shutil.which("sshpass") is None:
            raise _AuthUnavailable("password_auth_unavailable:sshpass_missing")
        env = dict(os.environ)
        env["SSHPASS"] = self._credential.secret
        return ["sshpass", "-e", *argv], env

    def run(self, command: str, *, timeout: int | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
        argv = [
            self._ssh,
            *self._base_opts(),
            "-p", str(self._device.port),
            f"{self._device.username}@{self._device.address}",
            command,
        ]
        argv, env = self._wrap_password(argv)
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            input=stdin,
            env=env,
            timeout=timeout or self._command_timeout_s,
        )

    def put(self, local_path: str | Path, remote_path: str, *, timeout: int | None = None) -> subprocess.CompletedProcess:
        argv = [
            self._scp,
            *self._base_opts(),
            "-P", str(self._device.port),
            str(local_path),
            f"{self._device.username}@{self._device.address}:{remote_path}",
        ]
        argv, env = self._wrap_password(argv)
        return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout or self._command_timeout_s)

    def put_content(self, content: str, remote_path: str, *, mode: str = "644", timeout: int | None = None):
        """Write a small file by streaming it over stdin.

        Used for the agent script itself: it avoids a second `scp`
        round-trip on a link where every round-trip costs 125ms.
        """
        quoted = _sh_path(remote_path)
        command = f"mkdir -p $(dirname {quoted}) && cat > {quoted} && chmod {mode} {quoted}"
        return self.run(command, stdin=content, timeout=timeout)


def _sh_path(path: str) -> str:
    """Quote a remote path while still letting a leading `~/` expand.

    `shlex.quote("~/pf_units")` yields `'~/pf_units'`, which the remote shell
    treats as a *literal* directory named `~` — the first real deploy created
    exactly that on the device. Quoting the tail and letting `$HOME` expand
    keeps the injection safety and restores the meaning.
    """
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path)


class _AuthUnavailable(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def reject_reason_for(proc: subprocess.CompletedProcess) -> str:
    """Map an ssh/scp failure onto the shared rejection vocabulary."""
    stderr = (proc.stderr or "").lower()
    if proc.returncode == 255 or "connection refused" in stderr or "no route to host" in stderr:
        return REASON_DEVICE_UNREACHABLE
    if "timed out" in stderr or "timeout" in stderr:
        return REASON_DEVICE_TIMEOUT
    if "permission denied" in stderr or "authentication failed" in stderr:
        return REASON_NOT_PERMITTED
    if "host key verification failed" in stderr:
        return REASON_NOT_PERMITTED
    return REASON_DEVICE_UNREACHABLE


def _agent_reason(proc: subprocess.CompletedProcess) -> str:
    """The agent's own `error:<reason>` line, when it produced one."""
    for stream in (proc.stdout, proc.stderr):
        for line in (stream or "").splitlines():
            line = line.strip()
            if line.startswith("error:"):
                return line[len("error:"):]
    return reject_reason_for(proc)


class OnDeviceSshControlProvider:
    """ControlProvider for a terminal reached over SSH (AI-B-03, AI-B-11).

    `target_id` is the *unit* id — the deployable function — exactly as with
    `K3sControlProvider`, where it names a deployment. One provider instance
    binds one device; several devices are several bindings in
    `MultiClusterControlProvider`, which is how "복수 실행영역" is expressed
    without any region knowing about the others (AI-B-11).
    """

    def __init__(
        self,
        device: DeviceRegistration,
        credential: DeviceCredential | None = None,
        *,
        runner: SshRunner | None = None,
        root: str = DEFAULT_ROOT,
        backend: str = "auto",
        command_timeout_s: int = 60,
        transfer_timeout_s: int = 300,
        observability=None,
    ) -> None:
        self._device = device
        self._root = root
        self._backend = backend
        self._runner = runner or SshRunner(device, credential, command_timeout_s=command_timeout_s)
        self._transfer_timeout_s = transfer_timeout_s
        self._observability = observability
        self._agent_installed = False
        self.audit_log: list[AuditEntry] = []
        self.trace_log: list[TraceEntry] = []

    # --- identity ---------------------------------------------------------
    @property
    def device_id(self) -> str:
        return self._device.device_id

    @property
    def runner(self) -> SshRunner:
        return self._runner

    def _agent_path(self) -> str:
        return f"{self._root}/.pf_agent.sh"

    def _agent_cmd(self, *args: str) -> str:
        parts = " ".join(shlex.quote(a) for a in args)
        return (
            f"PF_ROOT={_sh_path(self._root)} PF_BACKEND={shlex.quote(self._backend)} "
            f"/bin/bash {_sh_path(self._agent_path())} {parts}"
        )

    # --- availability (AI-B-05) -------------------------------------------
    def is_available(self) -> bool:
        """Whether the device answers right now.

        Mirrors `K3sControlProvider.is_available`: a `False` here must make
        the caller re-place work, never crash. An unreachable terminal is an
        ordinary operating condition (AI-C-05).
        """
        try:
            return self._runner.run("true", timeout=15).returncode == 0
        except (subprocess.TimeoutExpired, OSError, _AuthUnavailable):
            return False

    def install_agent(self, *, force: bool = False) -> ControlResult:
        """Put the supervisor script on the device, once.

        Re-pushed only when its digest differs, so the common case is a
        single `sha256sum` round-trip — on a 125ms link that difference is
        the whole deploy budget.
        """
        if self._agent_installed and not force:
            return ControlResult(True, None)
        try:
            script = AGENT_SCRIPT_PATH.read_text(encoding="utf-8")
        except OSError:
            return ControlResult(False, None, rejection_reason=REASON_AGENT_MISSING)
        digest = hashlib.sha256(script.encode("utf-8")).hexdigest()

        try:
            if not force:
                probe = self._runner.run(
                    f"sha256sum {_sh_path(self._agent_path())} 2>/dev/null | cut -d' ' -f1"
                )
                if probe.returncode == 0 and probe.stdout.strip() == digest:
                    self._agent_installed = True
                    return ControlResult(True, None)
                if probe.returncode != 0 and probe.returncode != 1:
                    return ControlResult(False, None, rejection_reason=reject_reason_for(probe))
            written = self._runner.put_content(script, self._agent_path(), mode="755")
        except _AuthUnavailable as exc:
            return ControlResult(False, None, rejection_reason=exc.reason)
        except subprocess.TimeoutExpired:
            return ControlResult(False, None, rejection_reason=REASON_DEVICE_TIMEOUT)
        except OSError as exc:
            return ControlResult(False, None, rejection_reason=f"ssh_error:{type(exc).__name__}")

        if written.returncode != 0:
            return ControlResult(False, None, rejection_reason=reject_reason_for(written))
        self._agent_installed = True
        return ControlResult(True, None)

    def _agent(self, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess | ControlResult:
        installed = self.install_agent()
        if not installed.accepted:
            return installed
        try:
            return self._runner.run(self._agent_cmd(*args), timeout=timeout)
        except _AuthUnavailable as exc:
            return ControlResult(False, None, rejection_reason=exc.reason)
        except subprocess.TimeoutExpired:
            return ControlResult(False, None, rejection_reason=REASON_DEVICE_TIMEOUT)
        except OSError as exc:
            return ControlResult(False, None, rejection_reason=f"ssh_error:{type(exc).__name__}")

    # --- ControlProvider ---------------------------------------------------
    def request(
        self,
        command: str,
        target_id: str,
        params: dict | None = None,
        *,
        requested_by: str = "unknown",
    ) -> ControlResult:
        start = time.time()
        # 업무상 책임 추적(audit)과 기술 처리 경로·지연(trace)은 분리 보관한다
        # (AI-B-03, 원칙 #16). Neither log ever receives a credential.
        self.audit_log.append(AuditEntry(command, target_id, requested_by, start))
        params = params or {}

        try:
            if command == "start":
                result = self._start(target_id, params)
            elif command == "stop":
                result = self._stop(target_id)
            elif command == "restart":
                result = self._simple("restart", target_id)
            else:
                result = ControlResult(False, None, rejection_reason=f"unsupported_command:{command}")
        except Exception as exc:  # a device failure is a rejection, not a crash
            result = ControlResult(False, None, rejection_reason=f"device_error:{type(exc).__name__}")

        self.trace_log.append(TraceEntry(command, target_id, (time.time() - start) * 1000, start))
        self._emit(command, target_id, result)
        return result

    def get_status(self, target_id: str) -> TargetStatus:
        proc = self._agent("status", target_id)
        if isinstance(proc, ControlResult) or proc.returncode != 0:
            return TargetStatus.STOPPED
        return TargetStatus.RUNNING if "ok:RUNNING" in proc.stdout else TargetStatus.STOPPED

    # --- health (AI-B-05, AI-O-04) -----------------------------------------
    def health(self, target_id: str) -> UnitHealth:
        """Three independent readings. See the module docstring."""
        import json

        proc = self._agent("health", target_id)
        if isinstance(proc, ControlResult):
            return UnitHealth(
                target_id, self.device_id, reachable=False,
                device_state=DeviceState.UNREACHABLE, reason=proc.rejection_reason,
            )
        if proc.returncode != 0:
            reason = _agent_reason(proc)
            unreachable = reason in (REASON_DEVICE_UNREACHABLE, REASON_DEVICE_TIMEOUT, REASON_NOT_PERMITTED)
            return UnitHealth(
                target_id, self.device_id,
                reachable=not unreachable,
                device_state=DeviceState.UNREACHABLE if unreachable else DeviceState.UNKNOWN,
                reason=reason,
            )

        line = next((ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")), "")
        try:
            payload = json.loads(line)
        except ValueError:
            return UnitHealth(target_id, self.device_id, reachable=True, reason="unparseable_health")

        device = payload.get("device") or {}
        throttle_raw = device.get("throttled") or None
        flags = decode_throttle_flags(throttle_raw)
        if throttle_raw is None:
            device_state = DeviceState.UNKNOWN
        elif _is_actively_throttled(throttle_raw):
            device_state = DeviceState.THROTTLED
        else:
            device_state = DeviceState.NOMINAL

        return UnitHealth(
            unit_id=target_id,
            device_id=self.device_id,
            reachable=True,
            liveness=_enum_or(Liveness, payload.get("liveness")),
            readiness=_enum_or(Readiness, payload.get("readiness")),
            device_state=device_state,
            active_version=payload.get("version") or None,
            previous_version=payload.get("previous_version") or None,
            backend=payload.get("backend") or None,
            temperature_c=_float_or_none(device.get("temperature_c")),
            throttle_raw=throttle_raw,
            throttle_flags=flags,
            ready_age_s=_float_or_none(payload.get("ready_age_s")),
            load1=_float_or_none(device.get("load1")),
            mem_available_kb=_int_or_none(device.get("mem_available_kb")),
        )

    def wait_ready(self, target_id: str, timeout_s: int = 60, poll_s: float = 1.0) -> bool:
        """Readiness, not liveness — the distinction AI-B-05 insists on.

        Mirrors `K3sControlProvider.wait_ready`'s signature so the two are
        interchangeable to a caller.
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.health(target_id).readiness is Readiness.READY:
                return True
            time.sleep(poll_s)
        return False

    # --- artifact lifecycle (AI-B-02, AI-B-05) ------------------------------
    def deploy_artifact(
        self,
        target_id: str,
        package: ArtifactPackage,
        *,
        activate: bool = True,
        restart: bool = True,
    ) -> ControlResult:
        """Push -> verify on device -> stage -> flip `current`, in that order.

        The ordering is the rollback guarantee. Nothing touches `current`
        until the device itself has confirmed the checksum of a fully
        received file, so a link that drops mid-transfer (the pi2 case)
        leaves the previously running version active and untouched — a
        failed update must not be able to produce a stopped unit
        (AI-B-05: 새 버전 적용 실패 시 마지막 정상 버전으로 복구).
        """
        if not package.path.is_file():
            return ControlResult(False, None, rejection_reason=REASON_MISSING_ARTIFACT)

        ensured = self._agent("ensure", target_id)
        if isinstance(ensured, ControlResult):
            return ensured
        if ensured.returncode != 0:
            return ControlResult(False, None, rejection_reason=_agent_reason(ensured))

        remote = f"{self._root}/{target_id}/incoming/{package.version}.tar.gz"
        try:
            sent = self._runner.put(package.path, remote, timeout=self._transfer_timeout_s)
        except _AuthUnavailable as exc:
            return ControlResult(False, None, rejection_reason=exc.reason)
        except subprocess.TimeoutExpired:
            # Timed out mid-copy: the partial file stays in `incoming/` and is
            # deleted by the next `stage`, which will refuse it on checksum.
            return ControlResult(False, None, rejection_reason=REASON_DEVICE_TIMEOUT)
        except OSError as exc:
            return ControlResult(False, None, rejection_reason=f"ssh_error:{type(exc).__name__}")
        if sent.returncode != 0:
            reason = reject_reason_for(sent)
            return ControlResult(
                False, None,
                rejection_reason=reason if reason != REASON_DEVICE_UNREACHABLE else REASON_TRANSFER_FAILED,
            )

        staged = self._agent("stage", target_id, package.version, package.sha256, timeout=self._transfer_timeout_s)
        if isinstance(staged, ControlResult):
            return staged
        if staged.returncode != 0:
            return ControlResult(False, None, rejection_reason=_agent_reason(staged))

        if not activate:
            return ControlResult(True, self.get_status(target_id))

        activated = self._agent("activate", target_id, package.version)
        if isinstance(activated, ControlResult):
            return activated
        if activated.returncode != 0:
            return ControlResult(False, None, rejection_reason=_agent_reason(activated))

        if not restart:
            return ControlResult(True, self.get_status(target_id))
        return self.request("restart", target_id, requested_by="deploy_artifact")

    def update_artifact(self, target_id: str, package: ArtifactPackage) -> ControlResult:
        """`K3sControlProvider.update_image`'s counterpart for a terminal."""
        result = self.deploy_artifact(target_id, package)
        if result.accepted or result.rejection_reason in (
            REASON_DEVICE_UNREACHABLE, REASON_DEVICE_TIMEOUT, REASON_TRANSFER_FAILED,
            REASON_CHECKSUM_MISMATCH, REASON_NOT_PERMITTED,
        ):
            return result
        return ControlResult(False, None, rejection_reason=REASON_UPDATE_REJECTED)

    def rollback(self, target_id: str, *, restart: bool = True) -> ControlResult:
        """Return to the last known-good version (AI-B-05)."""
        proc = self._agent("rollback", target_id)
        if isinstance(proc, ControlResult):
            return proc
        if proc.returncode != 0:
            reason = _agent_reason(proc)
            if reason in (REASON_NO_PREVIOUS_VERSION, "previous_version_missing"):
                return ControlResult(False, None, rejection_reason=REASON_NO_PREVIOUS_VERSION)
            if reason in (REASON_DEVICE_UNREACHABLE, REASON_DEVICE_TIMEOUT):
                return ControlResult(False, None, rejection_reason=reason)
            return ControlResult(False, None, rejection_reason=REASON_ROLLBACK_UNAVAILABLE)
        if not restart:
            return ControlResult(True, self.get_status(target_id))
        return self.request("restart", target_id, requested_by="rollback")

    def versions(self, target_id: str) -> tuple[str | None, str | None, tuple[str, ...]]:
        """`(active, previous, all_staged)` — the evidence a rollback exists."""
        proc = self._agent("versions", target_id)
        if isinstance(proc, ControlResult) or proc.returncode != 0:
            return (None, None, ())
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("ok:")), "ok:||")
        body = line[len("ok:"):]
        active, _, rest = body.partition("|")
        previous, _, staged = rest.partition("|")
        return (active or None, previous or None, tuple(v for v in staged.split(",") if v))

    def delete(self, target_id: str) -> None:
        """Stop and remove a unit. Never leaves a unit behind after a test."""
        self._agent("remove", target_id)

    def prune(self, target_id: str) -> None:
        self._agent("prune", target_id)

    # --- internals ---------------------------------------------------------
    def _start(self, target_id: str, params: dict) -> ControlResult:
        package = params.get("artifact")
        if package is not None:
            if not isinstance(package, ArtifactPackage):
                return ControlResult(False, None, rejection_reason="invalid_artifact_param")
            return self.deploy_artifact(target_id, package)
        return self._simple("start", target_id)

    def _stop(self, target_id: str) -> ControlResult:
        proc = self._agent("stop", target_id)
        if isinstance(proc, ControlResult):
            return proc
        if proc.returncode != 0:
            reason = _agent_reason(proc)
            return ControlResult(False, None, rejection_reason=reason)
        return ControlResult(True, TargetStatus.STOPPED)

    def _simple(self, command: str, target_id: str) -> ControlResult:
        proc = self._agent(command, target_id)
        if isinstance(proc, ControlResult):
            return proc
        if proc.returncode != 0:
            return ControlResult(False, None, rejection_reason=_agent_reason(proc))
        status = TargetStatus.STOPPED if command == "stop" else TargetStatus.RUNNING
        return ControlResult(True, status)

    def _emit(self, command: str, target_id: str, result: ControlResult) -> None:
        """Structured event for a rejection (AI-O-02).

        Optional: an absent or failing observability provider must never
        affect control (AI-O-02: 외부 수집기가 일시적으로 사용할 수 없어도
        로컬 오류 기록은 남아야 한다 — the audit/trace logs above are that
        local record).
        """
        if self._observability is None or result.accepted:
            return
        try:
            self._observability.record_event(
                "ondevice_control_rejected",
                "warning",
                {
                    "device_id": self.device_id,
                    "unit_id": target_id,
                    "command": command,
                    "reason": result.rejection_reason,
                },
            )
        except Exception:
            pass


def _enum_or(enum_cls, value):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return enum_cls.UNKNOWN


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class OnDeviceArtifactDeployment:
    """`ModelDeploymentProvider` shape over the same SSH control path.

    implements: AI-B-02, AI-B-05, HW-R-10

    Lets `runtime/model_deployment.py::ModelDeploymentManager` drive a
    terminal unchanged — it already enforces "validate before activate, and
    restore the previous version on activation failure", which is exactly
    this provider's on-device guarantee. Reusing it means the terminal path
    does not re-implement that ordering in a second place.

    Identifier mapping: `model_id` is the unit id (the deployable thing),
    `target_node_id` is the device id. A call naming a different device is
    refused rather than silently retargeted.
    """

    def __init__(self, control: OnDeviceSshControlProvider, *, staging_dir: str | Path | None = None) -> None:
        self._control = control
        self._staging = Path(staging_dir) if staging_dir else None
        self._packages: dict[str, ArtifactPackage] = {}

    def register_package(self, artifact_ref: str, package: ArtifactPackage) -> None:
        """Bind a logical artifact_ref to a packed artifact.

        The manager only ever passes strings around; resolving one to bytes
        is a provider concern, which is what keeps the manager free of any
        filesystem or transfer knowledge.
        """
        self._packages[artifact_ref] = package

    def _package_for(self, artifact_ref: str) -> ArtifactPackage | None:
        if artifact_ref in self._packages:
            return self._packages[artifact_ref]
        candidate = Path(artifact_ref)
        if candidate.is_dir():
            staging = self._staging or candidate.parent
            package = pack_unit_artifact(candidate, staging)
            self._packages[artifact_ref] = package
            return package
        return None

    def _wrong_device(self, target_node_id: str) -> bool:
        return target_node_id != self._control.device_id

    # --- ModelDeploymentProvider ------------------------------------------
    def current_version(self, model_id: str, target_node_id: str) -> str | None:
        if self._wrong_device(target_node_id):
            return None
        active, _, _ = self._control.versions(model_id)
        return active

    def download(self, artifact_ref: str, target_node_id: str) -> bool:
        """Pack + push only. Staging and activation stay in later steps so a
        failure here cannot have touched `current`."""
        if self._wrong_device(target_node_id):
            return False
        return self._package_for(artifact_ref) is not None

    def validate(self, artifact_ref: str, checksum: str, target_node_id: str) -> bool:
        if self._wrong_device(target_node_id):
            return False
        package = self._package_for(artifact_ref)
        if package is None:
            return False
        # Local integrity gate: a packed artifact whose digest disagrees with
        # the request never leaves this host. The device re-checks after
        # transfer, because a link is exactly where corruption happens.
        return not checksum or package.sha256 == checksum

    def activate(self, model_id: str, model_version: str, artifact_ref: str, target_node_id: str) -> bool:
        if self._wrong_device(target_node_id):
            return False
        package = self._package_for(artifact_ref)
        if package is None:
            return False
        return self._control.deploy_artifact(model_id, package).accepted

    def rollback(self, model_id: str, model_version: str, target_node_id: str) -> bool:
        if self._wrong_device(target_node_id):
            return False
        return self._control.rollback(model_id).accepted
