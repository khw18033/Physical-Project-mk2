"""DEVS atomic model wrapping the registry/profile/resource-reconfiguration
family of framework-property checks (what used to be the flat-event
scenarios s01~s04, domain-*.json).

implements: AI-B-01, AI-B-04, AI-B-06, AI-B-07, AI-C-05, AI-C-10, AI-C-11,
AI-C-13, AI-C-15

This model reacts to every "control" input synchronously (its own
`_cur_state` deadline stays `Infinite`, it never becomes independently
imminent) — so unlike `PhysicalCommandDeviceNode` it does not need a real
output-timing state machine. What it gains from being a DEVS model instead
of a plain Python loop is a real simulated-time axis: a scenario can place
a `resource_snapshot` at t=5 and a `register_provider` at t=8 and see them
apply in that order relative to *other* nodes' events in the same
simulation, instead of an arbitrary fixed sequence.
"""

from __future__ import annotations

from pyjevsim.behavior_model import BehaviorModel
from pyjevsim.definition import Infinite

from perception_framework.contracts.profile_loader import profile_from_dict
from perception_framework.providers.fakes import InMemoryObservabilityProvider
from perception_framework.registry.capability_registry import CapabilityRegistry
from perception_framework.runtime.application import ZoneApplication
from perception_framework.runtime.reconfiguration import ResourceAdaptiveReconfigurer, ResourceSnapshot

from .common import HealthBoard, build_registration, build_spec

_AMPLE_COMPUTE = 100.0
_AMPLE_MEMORY = 8192.0


class RegistryNode(BehaviorModel):
    def __init__(self, name: str, *, profile: dict, capabilities: list[dict],
                 providers: list[dict], budget: dict | None = None) -> None:
        super().__init__(name)
        self.insert_input_port("control")
        self.insert_output_port("capability_state")
        self.init_state("IDLE")
        self.insert_state("IDLE", Infinite)

        self._health_board = HealthBoard()
        self.registry = CapabilityRegistry()
        for entry in providers:
            self.registry.register_local(build_registration(entry, self._health_board))
            if "health_ref" in entry:
                self._health_board.set(entry["health_ref"], alive=True)

        deployment_profile = profile_from_dict(profile)
        specs = [build_spec(c) for c in capabilities]
        node_tags = set(profile.get("node_tags", ())) or None
        self.app = ZoneApplication(deployment_profile, self.registry, specs, node_tags=node_tags)
        self.observability = InMemoryObservabilityProvider()
        self.reconfigurer = ResourceAdaptiveReconfigurer(self.app, self.observability)

        self._snapshot = ResourceSnapshot(
            cpu_utilisation=0.0, memory_utilisation=0.0,
            total_compute_units=(budget or {}).get("compute_units", _AMPLE_COMPUTE),
            total_memory_mb=(budget or {}).get("memory_mb", _AMPLE_MEMORY),
        )

        # Populated by _resolve_now(); consumed directly by runner.py's
        # expectation checker, not via the DEVS port (this node never
        # becomes independently imminent, so its output() never fires
        # for these — the registry/profile family has no natural
        # "simulated delay" of its own, only reactions to explicit events).
        self.trace: list[dict] = []
        self.last_states: dict = {}
        self.last_resolutions: dict = {}
        self._resolve_now()

    def ext_trans(self, port, msg) -> None:
        for op in msg.retrieve():
            self._apply(op)
        self._resolve_now()

    def output(self, md) -> None:
        return  # see class docstring - this node never self-schedules

    def int_trans(self) -> None:
        return

    def _apply(self, op: dict) -> None:
        kind = op["op"]
        if kind == "register_provider":
            self.registry.register_local(build_registration(op, self._health_board))
            if "health_ref" in op:
                self._health_board.set(op["health_ref"], alive=True)
        elif kind == "unregister_provider":
            self.registry.unregister_local(op["kind"], op["provider_id"])
        elif kind == "resource_snapshot":
            self._snapshot = ResourceSnapshot(
                cpu_utilisation=op["cpu"], memory_utilisation=op.get("memory", 0.3),
                total_compute_units=op.get("total_compute_units", self._snapshot.total_compute_units),
                total_memory_mb=op.get("total_memory_mb", self._snapshot.total_memory_mb),
                max_latency_ms=op.get("max_latency_ms", self._snapshot.max_latency_ms),
            )
        elif kind == "set_node_tags":
            self.app.set_node_tags(set(op["tags"]))
        elif kind == "set_health":
            self._health_board.set(op["ref"], alive=op.get("alive", True), raises=op.get("raise", False))
        else:
            raise ValueError(f"unknown control op: {kind!r}")
        self.trace.append({"direction": "in", "port": "control", "payload": op})

    def _resolve_now(self) -> None:
        self.last_states = self.reconfigurer.apply_snapshot(self._snapshot)
        self.last_resolutions = self.app.resolve(self._snapshot.to_budget())
