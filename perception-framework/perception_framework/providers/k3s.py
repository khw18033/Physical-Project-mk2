"""Orchestrator `ControlProvider` backed by a Kubernetes/K3s cluster.

implements: AI-B-03, AI-B-05, AI-B-07, AI-C-12

원칙 #2 / AI-B-02: K3s는 배포·관리 provider일 뿐이고, 기능 로직은 K3s 없이도
독립 실행 가능해야 한다. 따라서 이 모듈은 `LocalControlSupervisor`와 **동일한
ControlProvider 계약**을 구현하며, 상위 실행관리 코드는 둘 중 무엇이 주입됐는지
알 필요가 없다.

AI-B-07: health 계약을 오케스트레이터와 분리해 K3s가 없는 실행환경에서도 동일한
장애 판단을 사용한다 — 따라서 오케스트레이터를 쓸 수 없을 때는 예외가 아니라
`ControlResult(accepted=False, rejection_reason=...)`을 돌려주고, 호출자는
standalone supervisor로 계속 갈 수 있다.

업무 명령 이력(audit)과 기술 처리 경로·지연(trace)은 목적이 달라 분리 보관한다
(AI-B-03, 원칙 #16).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time

from perception_framework.execution.control import AuditEntry, ControlResult, TargetStatus, TraceEntry


class K3sControlProvider:
    """Drives workloads through the cluster API using the `kubectl` CLI.

    The CLI is used rather than a Python client so that no additional
    runtime dependency is imposed on a 말단 node that may never deploy
    anything (AI-B-10, 원칙 #12).
    """

    def __init__(
        self,
        namespace: str = "default",
        *,
        kubectl: str = "kubectl",
        timeout_s: int = 30,
        name_prefix: str = "aif-",
    ) -> None:
        self._namespace = namespace
        self._kubectl = kubectl
        self._timeout_s = timeout_s
        self._prefix = name_prefix
        self.audit_log: list[AuditEntry] = []
        self.trace_log: list[TraceEntry] = []

    # --- availability ---------------------------------------------------
    def is_available(self) -> bool:
        """Whether an orchestrator is usable right now.

        A temporarily unavailable orchestrator must not stop already
        running core functions (AI-B-05) — callers check this and fall
        back to standalone control instead of failing.
        """
        if shutil.which(self._kubectl) is None:
            return False
        return self._run(["version", "-o", "json"], timeout=5).returncode == 0

    # --- ControlProvider -------------------------------------------------
    def request(
        self,
        command: str,
        target_id: str,
        params: dict | None = None,
        *,
        requested_by: str = "unknown",
    ) -> ControlResult:
        start = time.time()
        self.audit_log.append(AuditEntry(command, target_id, requested_by, start))
        params = params or {}

        try:
            if command == "start":
                result = self._start(target_id, params)
            elif command == "stop":
                result = self._stop(target_id)
            elif command == "restart":
                stopped = self._stop(target_id)
                result = self._start(target_id, params) if stopped.accepted else stopped
            else:
                result = ControlResult(False, None, rejection_reason=f"unsupported_command:{command}")
        except Exception as exc:  # orchestrator failure is a rejection, not a crash
            result = ControlResult(False, None, rejection_reason=f"orchestrator_error:{type(exc).__name__}")

        self.trace_log.append(TraceEntry(command, target_id, (time.time() - start) * 1000, start))
        return result

    def get_status(self, target_id: str) -> TargetStatus:
        proc = self._run(
            ["get", "deployment", self._name(target_id), "-o", "json", "-n", self._namespace]
        )
        if proc.returncode != 0:
            return TargetStatus.STOPPED
        try:
            ready = json.loads(proc.stdout).get("status", {}).get("readyReplicas", 0)
        except (ValueError, AttributeError):
            return TargetStatus.STOPPED
        return TargetStatus.RUNNING if ready else TargetStatus.STOPPED

    # --- version lifecycle (AI-B-05, AI-B-07) ----------------------------
    def update_image(self, target_id: str, image: str) -> ControlResult:
        """Point every container of the target at `image`.

        The container name is read from the deployment rather than assumed to
        match the deployment name. Assuming it meant this provider could only
        update workloads it had created itself: a deployment made elsewhere —
        which is the normal case for anything already running in a cluster —
        was rejected with `update_rejected` and its rollout/rollback path
        became unreachable through this API.
        """
        name = self._name(target_id)
        containers = self._container_names(target_id)
        if not containers:
            return ControlResult(False, None, rejection_reason="target_not_found")
        args = ["set", "image", f"deployment/{name}"]
        args += [f"{container}={image}" for container in containers]
        args += ["-n", self._namespace]
        proc = self._run(args)
        if proc.returncode != 0:
            return ControlResult(False, None, rejection_reason="update_rejected")
        return ControlResult(True, self.get_status(target_id))

    def _container_names(self, target_id: str) -> list[str]:
        proc = self._run([
            "get", "deployment", self._name(target_id), "-n", self._namespace,
            "-o", "jsonpath={.spec.template.spec.containers[*].name}",
        ])
        if proc.returncode != 0:
            return []
        return proc.stdout.split()

    def rollback(self, target_id: str) -> ControlResult:
        """Return to the last known-good revision (AI-B-07)."""
        proc = self._run(
            ["rollout", "undo", f"deployment/{self._name(target_id)}", "-n", self._namespace]
        )
        if proc.returncode != 0:
            return ControlResult(False, None, rejection_reason="rollback_unavailable")
        return ControlResult(True, self.get_status(target_id))

    def wait_ready(self, target_id: str, timeout_s: int = 60) -> bool:
        proc = self._run(
            [
                "rollout",
                "status",
                f"deployment/{self._name(target_id)}",
                "-n",
                self._namespace,
                f"--timeout={timeout_s}s",
            ],
            timeout=timeout_s + 10,
        )
        return proc.returncode == 0

    # --- internals --------------------------------------------------------
    def _start(self, target_id: str, params: dict) -> ControlResult:
        image = params.get("image")
        if not image:
            return ControlResult(False, None, rejection_reason="missing_image")

        name = self._name(target_id)
        if self._run(["get", "deployment", name, "-n", self._namespace]).returncode == 0:
            scaled = self._run(
                ["scale", "deployment", name, "--replicas=1", "-n", self._namespace]
            )
            if scaled.returncode != 0:
                return ControlResult(False, None, rejection_reason="scale_rejected")
            return ControlResult(True, TargetStatus.RUNNING)

        base = ["create", "deployment", name, f"--image={image}", "-n", self._namespace]
        # `--` ends kubectl's own flags, so anything after it belongs to the
        # container. Flags must go in before it or they are silently handed to
        # the workload as arguments.
        command = list(params.get("command") or ())
        tail = ["--", *command] if command else []
        args = base + tail

        # A placement decision that never reaches the workload is not a
        # placement: without this the selector chose a node correctly and the
        # pod still landed wherever the scheduler liked, including nodes the
        # selection had ruled out (AI-B-04).
        #
        # The constraint goes in at creation, not as a patch afterwards.
        # Patching works, but it leaves a window in which an unconstrained pod
        # is already running — a briefly-ignored placement is still an ignored
        # placement.
        placement = params.get("node_selector")
        if not placement:
            created = self._run(args)
            if created.returncode != 0:
                return ControlResult(False, None,
                                     rejection_reason=_reject_reason(created.stderr))
            return ControlResult(True, TargetStatus.RUNNING)

        rendered = self._run(base + ["--dry-run=client", "-o", "json"] + tail)
        if rendered.returncode != 0:
            return ControlResult(False, None, rejection_reason=_reject_reason(rendered.stderr))
        try:
            manifest = json.loads(rendered.stdout)
            manifest["spec"]["template"]["spec"]["nodeSelector"] = dict(placement)
        except (ValueError, KeyError):
            return ControlResult(False, None, rejection_reason="placement_not_applied")
        applied = self._run(["apply", "-n", self._namespace, "-f", "-"],
                            stdin=json.dumps(manifest))
        if applied.returncode != 0:
            return ControlResult(False, None, rejection_reason=_reject_reason(applied.stderr))
        return ControlResult(True, TargetStatus.RUNNING)

    def _stop(self, target_id: str) -> ControlResult:
        name = self._name(target_id)
        if self._run(["get", "deployment", name, "-n", self._namespace]).returncode != 0:
            return ControlResult(False, None, rejection_reason="unknown_target")
        scaled = self._run(["scale", "deployment", name, "--replicas=0", "-n", self._namespace])
        if scaled.returncode != 0:
            return ControlResult(False, None, rejection_reason="scale_rejected")
        return ControlResult(True, TargetStatus.STOPPED)

    def delete(self, target_id: str) -> None:
        self._run(
            ["delete", "deployment", self._name(target_id), "-n", self._namespace, "--ignore-not-found"]
        )

    def _name(self, target_id: str) -> str:
        return f"{self._prefix}{target_id}".lower().replace("_", "-")

    def _run(self, args: list[str], timeout: int | None = None,
             stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self._kubectl, *args],
            capture_output=True,
            text=True,
            input=stdin,
            timeout=timeout or self._timeout_s,
        )


def _reject_reason(stderr: str) -> str:
    lowered = (stderr or "").lower()
    if "already exists" in lowered:
        return "already_exists"
    if "forbidden" in lowered or "unauthorized" in lowered:
        return "not_permitted"
    if "connection refused" in lowered or "unable to connect" in lowered:
        return "orchestrator_unavailable"
    return "create_rejected"
