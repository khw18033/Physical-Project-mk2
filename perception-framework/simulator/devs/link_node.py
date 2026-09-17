"""DEVS atomic model for one communication channel (MQTT/Kafka/K3s-API
style), delaying a relayed message by a *measured* real round-trip time
instead of an idealized zero-latency coupling.

implements: (timing stand-in for) AI-C-06, AI-N-03, AI-O-01
tests: simulator scenarios needing communication latency in the timeline

Structurally this mirrors `physical_command_device.py::PhysicalCommandDeviceNode`
on purpose — single active in-flight relay + an opportunistically-flushed
extra queue for anything that arrives while one is already in flight — the
same shape already proven against pyjevsim's documented timing pitfalls
(`simulator/devs/README.md`) rather than a new, unverified concurrent-timer
design. `rtt_ms` must be supplied by the scenario from an actual measurement
(a real Mosquitto/Kafka/K3s round trip), not invented (AI-B-01).

`drop_rate` optionally models a QoS0-style lossy channel: a relay is
silently dropped instead of delivered with that probability, seeded for
reproducibility.
"""

from __future__ import annotations

import random

from pyjevsim.behavior_model import BehaviorModel
from pyjevsim.definition import Infinite
from pyjevsim.system_message import SysMessage


class LinkNode(BehaviorModel):
    def __init__(self, name: str, *, rtt_ms: float, drop_rate: float = 0.0, seed: int = 0) -> None:
        super().__init__(name)
        self.insert_input_port("in")
        self.insert_output_port("out")
        self.init_state("IDLE")
        self.insert_state("IDLE", Infinite)

        self._rtt_s = rtt_ms / 1000.0
        self._drop_rate = drop_rate
        self._rng = random.Random(seed)

        self._in_flight: dict | None = None
        self._pending: list[dict] = []
        self.trace: list[dict] = []

    def _goto(self, name: str, deadline: float) -> None:
        self._cur_state = name
        self.update_state(name, deadline)

    def ext_trans(self, port, msg) -> None:
        for payload in msg.retrieve():
            self.trace.append({"direction": "in", "port": port, "payload": payload})
            entry = {"payload": payload, "dropped": self._rng.random() < self._drop_rate}
            if self._in_flight is None:
                self._in_flight = entry
                self._goto("RELAYING", self._rtt_s)
            else:
                self._pending.append(entry)

    def output(self, msg) -> None:
        if self._cur_state != "RELAYING" or self._in_flight is None:
            return
        entry = self._in_flight
        if not entry["dropped"]:
            out = SysMessage(self.get_name(), "out")
            out.insert(entry["payload"])
            msg.insert_message(out)
            self.trace.append({"direction": "out", "port": "out", "payload": entry["payload"]})
        else:
            self.trace.append({"direction": "out", "port": "out", "payload": {"dropped": True}})

    def int_trans(self) -> None:
        self._in_flight = None
        if self._pending:
            self._in_flight = self._pending.pop(0)
            self._goto("RELAYING", self._rtt_s)
        else:
            self._goto("IDLE", Infinite)
