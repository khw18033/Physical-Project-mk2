"""DEVS atomic model wrapping the real `OtlpObservabilityProvider` — when
`endpoint` points at a real OTel Collector (this environment already has one
running, see `deploy/integration/docker-compose.yml`), metrics/events this
node emits during a simulated run are genuinely exported over OTLP, not
faked. When no collector is reachable, `.start()` returns False and every
call becomes a local-only no-op (never raises) — the same optional-collector
degradation `OtlpObservabilityProvider` already guarantees (AI-C-05).

implements: AI-O-01, AI-O-02, AI-O-03, AI-O-04

Synchronous reactive, same posture as `registry_node.py`: emitting a
metric/event has no simulated processing delay of its own.
"""

from __future__ import annotations

from pyjevsim.behavior_model import BehaviorModel
from pyjevsim.definition import Infinite

from perception_framework.providers.otel import OtelConfig, OtlpObservabilityProvider


class ObservabilityNode(BehaviorModel):
    def __init__(self, name: str, *, endpoint: str = "http://127.0.0.1:4317",
                 service_name: str = "perception-framework-sim") -> None:
        super().__init__(name)
        self.insert_input_port("control")
        self.insert_output_port("state")
        self.init_state("IDLE")
        self.insert_state("IDLE", Infinite)

        self.provider = OtlpObservabilityProvider(OtelConfig(endpoint=endpoint, service_name=service_name))
        self._collector_reachable = self.provider.start()

        self.trace: list[dict] = []
        self.last_resolutions: dict = {}  # unused here; runner.py reads it unconditionally
        self.last_states: dict = {"collector_reachable": self._collector_reachable, "critical_event_count": 0}

    def ext_trans(self, port, msg) -> None:
        for op in msg.retrieve():
            self._apply(op)
            self.trace.append({"direction": "in", "port": port, "payload": op})

    def output(self, md) -> None:
        return

    def int_trans(self) -> None:
        return

    def _apply(self, op: dict) -> None:
        kind = op["op"]
        if kind == "emit_metric":
            self.provider.record_metric(op["name"], op["value"], op.get("tags"))
        elif kind == "emit_event":
            self.provider.record_event(op["name"], op["severity"], op.get("payload"))
            self.last_states["critical_event_count"] = len(self.provider.critical_events())
        elif kind == "flush":
            self.provider.flush(timeout_ms=op.get("timeout_ms", 5000))
        else:
            raise ValueError(f"unknown control op: {kind!r}")

    def shutdown(self) -> None:
        self.provider.shutdown()
