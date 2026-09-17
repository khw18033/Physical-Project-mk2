"""DEVS atomic model for orchestrated deployment lifecycle (AI-B-02/03/05/
08/11) — same timed-state-machine shape as `physical_command_device.py`
(single active target, `_goto(name, deadline)`), because apply/ready here
genuinely take simulated time the same way accept/exec does for a physical
command.

implements: AI-B-02, AI-B-03, AI-B-05, AI-B-08, AI-B-11

Default mode uses `apply_delay_s`/`ready_delay_s` supplied by the scenario
from an actual measurement (this environment's real K3s: `kubectl apply`
~0.26s, ready ~2.1s — see the design report) rather than touching a live
cluster during an automated pytest run; `simulator/runner.py`'s own module
docstring already draws this line ("Scenarios needing a real ... broker...
stay as ordinary pytest under tests/") and a live `kubectl` call inside a
DEVS transition would make the fast scenario suite depend on cluster state.

`use_real_k3s=True` is available for a deliberate, separately-run
demonstration against a real cluster (`providers/k3s.py::K3sControlProvider`,
the same class `tests/test_k3s_control.py` exercises for real) — it is never
enabled by scenarios under `simulator/scenarios/` that `tests/
test_scenarios.py` runs automatically.
"""

from __future__ import annotations

from pyjevsim.behavior_model import BehaviorModel
from pyjevsim.definition import Infinite
from pyjevsim.system_message import SysMessage


class ClusterControlNode(BehaviorModel):
    def __init__(
        self, name: str, *, apply_delay_s: float = 0.26, ready_delay_s: float = 2.1,
        use_real_k3s: bool = False, namespace: str = "default",
    ) -> None:
        super().__init__(name)
        self.insert_input_port("control")
        self.insert_output_port("state")
        self.init_state("IDLE")
        self.insert_state("IDLE", Infinite)

        self._apply_delay_s = apply_delay_s
        self._ready_delay_s = ready_delay_s
        self._real: object | None = None
        if use_real_k3s:
            from perception_framework.providers.k3s import K3sControlProvider
            self._real = K3sControlProvider(namespace=namespace)

        self._active: dict | None = None  # {"target_id", "image", "phase": "applying"|"ready"}
        self._extra_outputs: list[dict] = []

        self.trace: list[dict] = []
        self.last_resolutions: dict = {}  # unused here; runner.py reads it unconditionally
        self.last_states: dict = {}  # target_id -> "RUNNING"|"STOPPED"

    def _goto(self, name: str, deadline: float) -> None:
        self._cur_state = name
        self.update_state(name, deadline)

    def ext_trans(self, port, msg) -> None:
        for op in msg.retrieve():
            self.trace.append({"direction": "in", "port": port, "payload": op})
            kind = op["op"]
            if kind == "deploy":
                if self._active is None:
                    self._active = {"target_id": op["target_id"], "image": op.get("image", "unspecified"), "phase": "applying"}
                    self._goto("APPLYING", self._apply_delay_s)
                else:
                    self._extra_outputs.append({"target_id": op["target_id"], "status": "REJECTED", "reason": "one_active_deploy_at_a_time"})
            elif kind == "stop":
                self.last_states[op["target_id"]] = "STOPPED"
                self._extra_outputs.append({"target_id": op["target_id"], "status": "STOPPED"})
            else:
                raise ValueError(f"unknown control op: {kind!r}")

    def output(self, md) -> None:
        emitted = False
        if self._cur_state == "APPLYING" and self._active is not None:
            payload = {"target_id": self._active["target_id"], "status": "ACCEPTED", "image": self._active["image"]}
            self._emit(md, payload)
            emitted = True
        elif self._cur_state == "READY" and self._active is not None:
            if self._real is not None:
                result = self._real.request("start", self._active["target_id"], {"image": self._active["image"]})
                status = "RUNNING" if result.accepted else "REJECTED"
            else:
                status = "RUNNING"
            self.last_states[self._active["target_id"]] = status
            self._emit(md, {"target_id": self._active["target_id"], "status": status})
            emitted = True
        for extra in self._extra_outputs:
            self._emit(md, extra)
        self._extra_outputs.clear()
        if not emitted and not self._extra_outputs:
            return

    def _emit(self, md, payload: dict) -> None:
        out = SysMessage(self.get_name(), "state")
        out.insert(payload)
        md.insert_message(out)
        self.trace.append({"direction": "out", "port": "state", "payload": payload})

    def int_trans(self) -> None:
        if self._cur_state == "APPLYING" and self._active is not None:
            self._active["phase"] = "ready"
            self._goto("READY", self._ready_delay_s)
        elif self._cur_state == "READY":
            self._active = None
            self._goto("IDLE", Infinite)
        else:
            self._goto("IDLE", Infinite)
