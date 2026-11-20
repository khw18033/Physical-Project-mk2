"""선언된 실행 단위를 **실제로** 세우고 내리는 ControlProvider.

implements: AI-B-03 (실행 제어), AI-B-05 (lifecycle·health 분리), AI-C-04 (provider 경계)
관련: AI-C-19 (이것은 물리 명령이 아니다), AI-B-11 (여러 실행영역 같은 계약),
      AI-C-05 (없으면 그 단위만 비활성), AI-C-16 (폐쇄망 — 내부 자산만 띄운다)
tests: tests/test_process_control.py

## 왜 필요한가

`execution/control.py::LocalControlSupervisor` 는 **상태만 적는** 대역이다(이름이
그렇게 말한다 — "a fake stand-in"). `providers/k3s.py` 는 클러스터에 올린다. 그
사이가 비어 있었다: **이 기계에서 프로세스와 docker compose 를 실제로 세우는 쪽**.

그 공백 때문에 운영이 이렇게 돌고 있었다 — 백엔드 기계에 사람이 들어가 `make up`,
`python server_stream_multi_source.py`, `python vision_infer.py` 를 손으로 친다.
가시화에서 내린 결정이 **사람의 손을 거쳐야** 실행되므로, 운영자가 둘(화면 앞 사람과
백엔드 기계 앞 사람)이 된다.

## 망에서 받는 것은 **단위 이름뿐이다**

이 모듈의 가장 중요한 경계다. `request()` 는 선언된 `unit_id` 만 받고 **명령줄을
받지 않는다.** argv 를 바깥에서 받으면 쓰기 계약 하나가 원격 코드 실행 창구가 된다.
무엇을 띄울 수 있는지는 `config/stack_units*.json` 선언이 정하고, 그 파일은 기계에
있다 — 망에 없다.

## 멱등하다

같은 `start` 를 두 번 받으면 **두 번 띄우지 않는다**(AI-C-20 의 멱등성 규칙과 같은
이유 — 같은 요청이 다시 와도 물리적으로 다시 실행되지 않아야 한다). 이미 돌고 있으면
수락하고 상태를 그대로 돌려준다. `stop` 도 이미 멈춰 있으면 수락이다 — 멈춘 것을
멈추라는 요청은 실패가 아니다.

## 프로세스가 살아 있는지는 **물어서** 안다

띄운 뒤 pid 를 상태 뿌리에 적고(`$MISSION_RUNTIME_STATE/stack/<unit>.pid`), 상태를
물을 때마다 그 pid 가 살아 있는지 본다. 게이트웨이가 다시 떠도 같은 파일을 읽어
**이미 돌고 있는 것을 다시 띄우지 않는다.** compose 단위는 우리가 pid 를 들고 있지
않으므로 `docker compose ps` 에 **물어본다** — 우리 기억이 아니라 도커의 답이 정본이다.

## 띄웠다 ≠ 준비됐다

`ControlResult(accepted=True)` 는 "띄웠다" 이고 준비 상태는 `wait_ready()` 가 따로
답한다(AI-B-05: 프로세스 시작과 readiness 를 같은 사실로 보지 않는다).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from mission_runtime.execution.control import (
    AuditEntry,
    ControlResult,
    TargetStatus,
    TraceEntry,
)

#: 단위의 종류. 벤더 열거형이 아니라 **띄우는 방법**의 종류다.
KIND_PROCESS = "process"
KIND_COMPOSE = "compose"
KINDS = (KIND_PROCESS, KIND_COMPOSE)

#: 선언이 쓸 수 있는 **닫힌 자리표**. 지금 하나뿐이다: 백엔드를 돌리는 그
#: 인터프리터. `"python"` 을 선언에 박으면 그 이름이 없는 기계에서 깨지고(실측
#: 2026-11-20: 이 기계에는 `python` 이 없고 `python3` 와 venv 만 있다), 절대
#: 경로를 박으면 기계를 옮길 때마다 선언을 고쳐야 한다. **임의 환경변수 전개는
#: 하지 않는다** — 선언에 적힌 것만 풀리고 그 목록이 이것이다.
PLACEHOLDER_PYTHON = "${python}"

#: 거절 사유 어휘. 문구가 아니라 토큰이고 화면이 이걸로 분기한다.
REASON_NOT_DECLARED = "unit_not_declared"
REASON_UNSUPPORTED = "unsupported_command"
REASON_NO_EXECUTABLE = "executable_not_found"
REASON_NO_DOCKER = "docker_not_available"
REASON_START_FAILED = "start_failed"
REASON_STOP_FAILED = "stop_failed"
REASON_DEPENDENCY = "dependency_not_running"
REASON_MISSING_FILE = "declared_file_missing"

#: 수락 사유. 거절과 섞지 않는다 — "이미 돌고 있다" 는 성공이다.
REASON_STARTED = "started"
REASON_ALREADY_RUNNING = "already_running"
REASON_STOPPED = "stopped"
REASON_ALREADY_STOPPED = "already_stopped"


class StackDeclarationError(ValueError):
    """선언이 잘못됐다. **적재 시점에 터진다** — 조용히 좁은 쪽을 쓰면 단위 하나가
    말없이 사라지고, 사라진 것을 운영자는 "안 눌렸다" 로 읽는다."""


def state_root() -> Path:
    """pid·로그를 두는 자리. 저장소가 아니라 **상태 뿌리**다(overlay 장부와 같은 규칙)."""
    explicit = os.environ.get("MISSION_RUNTIME_STATE")
    if explicit:
        return Path(explicit) / "stack"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "mission_runtime" / "stack"


@dataclass(frozen=True)
class StackUnit:
    """띄울 수 있는 것 하나. **전부 선언이고 판정이 없다.**

    `argv` 는 선언에만 있다 — 망에서 오지 않는다. 그것이 이 자료형의 존재 이유다.
    """

    unit_id: str
    kind: str
    label: Mapping[str, str] = field(default_factory=dict)
    #: process: 실행할 명령줄. compose: 쓰지 않는다.
    argv: tuple[str, ...] = ()
    #: compose: compose 파일 자리. process: 쓰지 않는다.
    compose_file: str | None = None
    #: compose 의 프로파일(선택). 선언에 없으면 기본 서비스만 뜬다.
    profiles: tuple[str, ...] = ()
    #: 둘 다: 어디서 돌릴까(패키지 뿌리 기준 상대 경로).
    cwd: str | None = None
    #: 넘겨줄 환경변수. **값이 선언에 있다** — 비밀은 여기 적지 않는다(AI-B-02).
    env: Mapping[str, str] = field(default_factory=dict)
    #: 준비됐는지 보는 방법. 지금은 포트 하나뿐이고 없으면 **묻지 않는다**(미측정).
    ready_port: int | None = None
    #: 먼저 서 있어야 하는 단위들.
    depends_on: tuple[str, ...] = ()
    #: 사람이 읽는 메모. 어느 판정에도 쓰이지 않는다.
    note: str = ""

    def __post_init__(self) -> None:
        if not self.unit_id:
            raise StackDeclarationError("unit_id 가 비어 있다")
        if self.kind not in KINDS:
            raise StackDeclarationError(f"모르는 kind {self.kind!r} — {KINDS} 중 하나다")
        if self.kind == KIND_PROCESS and not self.argv:
            raise StackDeclarationError(f"{self.unit_id}: process 단위에 argv 가 없다")
        if self.kind == KIND_COMPOSE and not self.compose_file:
            raise StackDeclarationError(
                f"{self.unit_id}: compose 단위에 compose_file 이 없다")


def unit_from_mapping(raw: Mapping[str, Any]) -> StackUnit:
    for key in ("unit_id", "kind"):
        if not raw.get(key):
            raise StackDeclarationError(f"선언에 {key} 가 없다: {dict(raw)}")
    return StackUnit(
        unit_id=str(raw["unit_id"]),
        kind=str(raw["kind"]),
        label=dict(raw.get("label") or {}),
        argv=tuple(str(item) for item in raw.get("argv") or ()),
        compose_file=None if raw.get("compose_file") in (None, "") else str(raw["compose_file"]),
        profiles=tuple(str(item) for item in raw.get("profiles") or ()),
        cwd=None if raw.get("cwd") in (None, "") else str(raw["cwd"]),
        env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
        ready_port=None if raw.get("ready_port") in (None, "") else int(raw["ready_port"]),
        depends_on=tuple(str(item) for item in raw.get("depends_on") or ()),
        note=str(raw.get("note") or raw.get("$comment") or ""),
    )


def load_units(path: str | Path) -> dict[str, StackUnit]:
    """선언 파일을 읽는다. **파일이 없으면 빈 묶음**이고 예외가 아니다.

    선언이 없는 배치는 정상이다 — 띄울 것이 없는 기계가 있고, 그곳에서 이 계층은
    그냥 비어 있어야 한다(AI-C-05).
    """
    file = Path(path)
    if not file.is_file():
        return {}
    raw = json.loads(file.read_text(encoding="utf-8"))
    rows = raw["units"] if isinstance(raw, dict) and "units" in raw else raw
    made: dict[str, StackUnit] = {}
    for row in rows:
        unit = unit_from_mapping(row)
        if unit.unit_id in made:
            raise StackDeclarationError(f"단위 이름이 겹친다: {unit.unit_id}")
        made[unit.unit_id] = unit
    for unit in made.values():
        for needed in unit.depends_on:
            if needed not in made:
                raise StackDeclarationError(
                    f"{unit.unit_id} 가 선언되지 않은 단위에 기댄다: {needed}")
    return made


class ProcessControlProvider:
    """선언된 단위를 이 기계에서 세우고 내린다. `ControlProvider` 계약 그대로다.

    `root` 는 상대 경로(`cwd` · `compose_file`)의 기준이고 기본은 패키지 뿌리다.
    `docker` 는 compose 를 부르는 명령이며 없으면 compose 단위만 비활성이다.
    """

    def __init__(self, units: Mapping[str, StackUnit] | None = None, *,
                 root: Path | None = None, docker: str = "docker",
                 state_dir: Path | None = None, timeout_s: int = 90) -> None:
        self._units = dict(units or {})
        self._root = Path(root) if root else Path(__file__).resolve().parents[1]
        self._docker = docker
        self._state = Path(state_dir) if state_dir else state_root()
        self._timeout_s = timeout_s
        #: 업무상 책임 추적과 기술 추적을 **따로** 둔다(AI-B-03).
        self.audit_log: list[AuditEntry] = []
        self.trace_log: list[TraceEntry] = []
        self._started: dict[str, subprocess.Popen] = {}

    # --- 선언 -------------------------------------------------------------
    def declare(self, unit: StackUnit) -> None:
        self._units[unit.unit_id] = unit

    def declared(self) -> tuple[str, ...]:
        return tuple(sorted(self._units))

    def unit(self, unit_id: str) -> StackUnit | None:
        return self._units.get(unit_id)

    def is_available(self) -> bool:
        """띄울 수 있는 단위가 하나라도 있나. **빈 선언은 정상**이고 그때는 False 다."""
        return bool(self._units)

    # --- ControlProvider --------------------------------------------------
    def request(self, command: str, target_id: str, params: dict | None = None, *,
                requested_by: str = "unknown") -> ControlResult:
        started = time.time()
        self.audit_log.append(AuditEntry(command, target_id, requested_by, started))
        try:
            return self._dispatch(command, target_id)
        finally:
            self.trace_log.append(
                TraceEntry(command, target_id, (time.time() - started) * 1000, started))

    def _dispatch(self, command: str, target_id: str) -> ControlResult:
        unit = self._units.get(target_id)
        if unit is None:
            # **망에서 온 이름이 선언에 없으면 그걸로 끝이다.** argv 를 받지 않는다.
            return ControlResult(False, None, rejection_reason=REASON_NOT_DECLARED)
        if command == "start":
            return self._start(unit)
        if command == "stop":
            return self._stop(unit)
        if command == "restart":
            self._stop(unit)
            return self._start(unit)
        return ControlResult(False, None,
                             rejection_reason=f"{REASON_UNSUPPORTED}:{command}")

    def get_status(self, target_id: str) -> TargetStatus:
        unit = self._units.get(target_id)
        if unit is None:
            return TargetStatus.STOPPED
        if unit.kind == KIND_COMPOSE:
            return (TargetStatus.RUNNING if self._compose_running(unit)
                    else TargetStatus.STOPPED)
        return (TargetStatus.RUNNING if self._alive(unit) else TargetStatus.STOPPED)

    def wait_ready(self, target_id: str, timeout_s: float = 20.0) -> bool | None:
        """준비됐나. **묻지 않은 것은 `None`** 이다 — 거짓이 아니다(AI-O-05).

        포트를 선언하지 않은 단위는 준비 여부를 물을 방법이 없고, 그 사실을 거짓으로
        적으면 "안 떴다" 로 읽힌다.
        """
        unit = self._units.get(target_id)
        if unit is None or unit.ready_port is None:
            return None
        # **한 번은 반드시 묻는다.** 기한 0 을 "묻지 않는다" 로 두면 조회 화면
        # (`snapshot()` 이 0 으로 부른다)이 떠 있는 단위를 영원히 "준비 안 됨" 으로
        # 그린다 — 실제로 그랬다(2026-11-20: redis 가 떠 있는데 ready=False).
        deadline = time.time() + timeout_s
        while True:
            if self._port_open(unit.ready_port):
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.25)

    # --- 보기 -------------------------------------------------------------
    def snapshot(self) -> list[dict[str, Any]]:
        """운영 화면이 읽는 모양. **선언된 단위는 멈춰 있어도 빠지지 않는다**(AI-O-05)."""
        rows: list[dict[str, Any]] = []
        for unit_id in sorted(self._units):
            unit = self._units[unit_id]
            status = self.get_status(unit_id)
            rows.append({
                "unit_id": unit_id,
                "kind": unit.kind,
                "label": dict(unit.label),
                "status": status.value,
                "ready": self.wait_ready(unit_id, timeout_s=0.0),
                "ready_port": unit.ready_port,
                "depends_on": list(unit.depends_on),
                "log_path": str(self._log_of(unit)) if unit.kind == KIND_PROCESS else None,
                # **왜 멈췄는지를 화면이 읽을 수 있어야 한다.** 그러지 않으면
                # 운영자는 "눌렀는데 아무 일도 없다" 만 보고, 사유는 백엔드 기계의
                # 로그 파일 안에 남는다 — 그 기계에 들어가지 않으려고 이 계약을
                # 만든 것이므로 그러면 목적이 사라진다. 파일을 여는 길은 열지
                # 않는다: **마지막 한 줄**만, 길이를 잘라 싣는다.
                "exit_code": self._exit_code(unit),
                "last_output": self._last_line(unit),
                "note": unit.note,
            })
        return rows

    # --- 내부: process ----------------------------------------------------
    def _start(self, unit: StackUnit) -> ControlResult:
        if self.get_status(unit.unit_id) is TargetStatus.RUNNING:
            # **두 번 띄우지 않는다.** 같은 요청이 다시 온 것은 실패가 아니다.
            return ControlResult(True, TargetStatus.RUNNING,
                                 rejection_reason=None)
        for needed in unit.depends_on:
            if self.get_status(needed) is not TargetStatus.RUNNING:
                return ControlResult(False, None,
                                     rejection_reason=f"{REASON_DEPENDENCY}:{needed}")
        if unit.kind == KIND_COMPOSE:
            return self._compose(unit, up=True)

        argv = [self._expand(item) for item in unit.argv]
        if shutil.which(argv[0]) is None and not Path(argv[0]).exists():
            return ControlResult(False, None,
                                 rejection_reason=f"{REASON_NO_EXECUTABLE}:{argv[0]}")
        workdir = self._resolve(unit.cwd) if unit.cwd else self._root
        if not workdir.is_dir():
            return ControlResult(False, None,
                                 rejection_reason=f"{REASON_MISSING_FILE}:{unit.cwd}")
        log = self._log_of(unit)
        log.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = log.open("ab")
            process = subprocess.Popen(                      # noqa: S603
                argv, cwd=str(workdir), stdout=handle, stderr=subprocess.STDOUT,
                # **버퍼를 끈다.** 파이프로 보낸 파이썬 출력은 기본으로 블록
                # 버퍼링이라 로그가 한참 비어 있고, 빈 로그를 운영자는 "안 떴다"
                # 로 읽는다(게이트웨이에서 같은 일을 겪어 `python -u` 를 붙였다).
                # 선언이 같은 이름을 적었으면 **선언이 이긴다**.
                env={"PYTHONUNBUFFERED": "1", **os.environ, **unit.env},
                start_new_session=True)
        except OSError as error:
            return ControlResult(False, None,
                                 rejection_reason=f"{REASON_START_FAILED}:{error.errno}")
        self._started[unit.unit_id] = process
        self._write_pid(unit, process.pid)
        return ControlResult(True, TargetStatus.RUNNING)

    def _stop(self, unit: StackUnit) -> ControlResult:
        if unit.kind == KIND_COMPOSE:
            if not self._compose_running(unit):
                return ControlResult(True, TargetStatus.STOPPED)
            return self._compose(unit, up=False)
        pid = self._pid_of(unit)
        if not self._alive(unit):
            # 멈춘 것을 멈추라는 요청은 **실패가 아니다.**
            self._clear_pid(unit)
            return ControlResult(True, TargetStatus.STOPPED)
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as error:
                return ControlResult(False, None,
                                     rejection_reason=f"{REASON_STOP_FAILED}:{error.errno}")
        handle = self._started.get(unit.unit_id)
        if handle is not None:
            # **거둬 준다(reap).** 죽은 자식을 거두지 않으면 좀비로 남고, 좀비에게
            # `kill(pid, 0)` 은 **성공한다** — 그래서 거두지 않으면 멈춘 단위가
            # 10 초 동안 RUNNING 으로 보인다(이 결함을 시험 시간이 먼저 알려 줬다).
            try:
                handle.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                pass
        deadline = time.time() + 10.0
        while time.time() < deadline and self._alive(unit):
            time.sleep(0.2)
        if self._alive(unit):
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                pass
        self._clear_pid(unit)
        self._started.pop(unit.unit_id, None)
        return ControlResult(True, TargetStatus.STOPPED)

    # --- 내부: compose ----------------------------------------------------
    def _compose(self, unit: StackUnit, *, up: bool) -> ControlResult:
        if shutil.which(self._docker) is None:
            return ControlResult(False, None, rejection_reason=REASON_NO_DOCKER)
        file = self._resolve(unit.compose_file or "")
        if not file.is_file():
            return ControlResult(False, None,
                                 rejection_reason=f"{REASON_MISSING_FILE}:{unit.compose_file}")
        args = self._compose_args(unit, file)
        args += ["up", "-d"] if up else ["down"]
        done = self._run(args)
        if done.returncode != 0:
            reason = REASON_START_FAILED if up else REASON_STOP_FAILED
            tail = (done.stderr or "").strip().splitlines()[-1:] or [""]
            return ControlResult(False, None, rejection_reason=f"{reason}:{tail[0][:120]}")
        return ControlResult(True, TargetStatus.RUNNING if up else TargetStatus.STOPPED)

    def _compose_args(self, unit: StackUnit, file: Path) -> list[str]:
        args = [self._docker, "compose", "-f", str(file)]
        for profile in unit.profiles:
            args += ["--profile", profile]
        return args

    def _compose_running(self, unit: StackUnit) -> bool:
        """**도커에게 묻는다.** 우리 기억이 아니라 도커의 답이 정본이다."""
        if shutil.which(self._docker) is None:
            return False
        file = self._resolve(unit.compose_file or "")
        if not file.is_file():
            return False
        done = self._run(self._compose_args(unit, file) + ["ps", "--quiet"])
        return done.returncode == 0 and bool(done.stdout.strip())

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(args, capture_output=True, text=True,  # noqa: S603
                                  timeout=self._timeout_s, cwd=str(self._root))
        except (OSError, subprocess.SubprocessError) as error:
            return subprocess.CompletedProcess(args, 1, "", str(error))

    def _exit_code(self, unit: StackUnit) -> int | None:
        """끝났으면 그 코드. **`None` 은 "돌고 있다" 또는 "띄운 적 없다"** 이고 0 이
        아니다 — 0 은 "정상으로 끝났다" 이고 그 둘과 다른 사실이다."""
        handle = self._started.get(unit.unit_id)
        return None if handle is None else handle.poll()

    def _last_line(self, unit: StackUnit, limit: int = 200) -> str | None:
        """로그의 **마지막 한 줄**. 파일을 여는 길은 열지 않는다."""
        if unit.kind != KIND_PROCESS:
            return None
        log = self._log_of(unit)
        if not log.is_file():
            return None
        try:
            tail = log.read_bytes()[-4096:].decode("utf-8", "replace")
        except OSError:
            return None
        lines = [line.strip() for line in tail.splitlines() if line.strip()]
        return lines[-1][:limit] if lines else None

    @staticmethod
    def _expand(item: str) -> str:
        """선언의 자리표를 푼다. **닫힌 목록이다** — 하나뿐이고 늘리는 것은 계약
        변경이다. 임의 환경변수를 전개하면 선언이 기계의 환경에 조용히 의존한다."""
        import sys  # noqa: PLC0415

        return item.replace(PLACEHOLDER_PYTHON, sys.executable)

    # --- 내부: 자리와 pid --------------------------------------------------
    def _resolve(self, relative: str) -> Path:
        path = Path(relative)
        return path if path.is_absolute() else (self._root / path)

    def _log_of(self, unit: StackUnit) -> Path:
        return self._state / f"{unit.unit_id}.log"

    def _pid_file(self, unit: StackUnit) -> Path:
        return self._state / f"{unit.unit_id}.pid"

    def _write_pid(self, unit: StackUnit, pid: int) -> None:
        file = self._pid_file(unit)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(str(pid), encoding="utf-8")

    def _clear_pid(self, unit: StackUnit) -> None:
        self._pid_file(unit).unlink(missing_ok=True)

    def _pid_of(self, unit: StackUnit) -> int | None:
        file = self._pid_file(unit)
        if not file.is_file():
            return None
        try:
            return int(file.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    def _alive(self, unit: StackUnit) -> bool:
        """그 단위가 지금 돌고 있나.

        우리가 띄운 자식이면 **그 핸들에 묻는다** — 그쪽이 정본이다. 다른 프로세스가
        띄워 둔 것(게이트웨이 재시작 뒤)은 pid 파일로만 알 수 있고, 그때는 좀비를
        걸러야 한다: 죽었지만 거두어지지 않은 프로세스에게 `kill(pid, 0)` 은
        성공하므로, 그것만 보면 **멈춘 것이 돌고 있는 것으로 보인다.**
        """
        handle = self._started.get(unit.unit_id)
        if handle is not None:
            return handle.poll() is None
        return self._pid_alive(self._pid_of(unit))

    @staticmethod
    def _pid_alive(pid: int | None) -> bool:
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True          # 남의 것이지만 살아 있다
        # 좀비는 신호를 받지만 **돌고 있지 않다**. 리눅스에서는 상태를 읽어 가른다.
        stat = Path(f"/proc/{pid}/stat")
        if stat.is_file():
            try:
                fields = stat.read_text(encoding="utf-8").rsplit(") ", 1)[-1].split()
                if fields and fields[0] == "Z":
                    return False
            except OSError:
                pass
        return True

    @staticmethod
    def _port_open(port: int, host: str = "127.0.0.1") -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            return False
