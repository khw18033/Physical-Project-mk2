"""Data-driven scenario runner, DEVS edition: turns one JSON scenario file
into a `pyjevsim.SysExecutor` topology (nodes + port couplings), replays a
timed stimulus schedule against it, then checks declared expectations
against each node's resulting state/trace.

implements: AI-B-01, AI-B-04, AI-B-06, AI-B-07, AI-B-09, AI-C-04, AI-C-05,
AI-C-10, AI-C-11, AI-C-13, AI-C-15, AI-C-20
tests: tests/test_scenarios.py (parametrized over scenarios/*.json)

Both `simulation.py` (human-readable narration) and `tests/test_scenarios.py`
(pytest assertions) call `run()` and read the same `ScenarioResult`, so a
scenario file is simultaneously a demo input and a regression check
(하나의 시나리오 = 시뮬레이터 입력 + 자동 검증 입력).

Timing note: reading a DEVS model's own `self.global_time` inside its
transition methods is unreliable in pyjevsim (it lags one scheduling round
behind - see `simulator/devs/README.md`), so this runner never trusts it.
Instead it steps `SysExecutor.simulate()` one checkpoint at a time (every
distinct stimulus `at` plus `run_until`) and reads `SysExecutor.
get_global_time()` — which *is* authoritative — right after each step, to
timestamp whatever new trace entries appeared during that interval. This
gives checkpoint-resolution timestamps, which is all `trace_contains`'s
`at_or_before` needs.

Scope note (unchanged from the pre-DEVS runner): this covers the registry/
profile/resource family (`registry_node`) and, newly, the physical-command
device lifecycle (`physical_command_device`). Scenarios needing a real
MQTT/Kafka broker, calibration files or a command supervisor's SQLite state
stay as ordinary pytest under `tests/`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyjevsim.definition import ExecutionType
from pyjevsim.system_executor import SysExecutor

from perception_framework.execution.conformance import check_provider_conformance

from devs.cluster_control_node import ClusterControlNode
from devs.common import HealthBoard, build_registration, core_source_mentions
from devs.learning_pipeline_node import LearningPipelineNode
from devs.link_node import LinkNode
from devs.observability_node import ObservabilityNode
from devs.perception_risk_node import PerceptionRiskNode
from devs.physical_command_device import PhysicalCommandDeviceNode
from devs.registry_node import RegistryNode

_NODE_TYPES = {
    "registry_node": RegistryNode,
    "physical_command_device": PhysicalCommandDeviceNode,
    "link_node": LinkNode,
    "perception_risk_node": PerceptionRiskNode,
    "observability_node": ObservabilityNode,
    "cluster_control_node": ClusterControlNode,
    "learning_pipeline_node": LearningPipelineNode,
}


@dataclass
class Checkpoint:
    time: float
    label: str
    node_states: dict[str, dict] = field(default_factory=dict)       # node_id -> last_states snapshot
    node_resolutions: dict[str, dict] = field(default_factory=dict)  # node_id -> last_resolutions snapshot


@dataclass
class ScenarioResult:
    scenario_id: str
    description: str
    nodes: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)  # flattened, checkpoint-timestamped, across all nodes
    check_failures: list[str] = field(default_factory=list)

    def checkpoint(self, ref: str | float) -> Checkpoint:
        for cp in self.checkpoints:
            if cp.label == ref or cp.time == ref:
                return cp
        raise KeyError(f"no checkpoint {ref!r} (have {[(c.label, c.time) for c in self.checkpoints]})")

    @property
    def passed(self) -> bool:
        return not self.check_failures


def load_scenario(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_node(cfg: dict):
    node_type = cfg["type"]
    cls = _NODE_TYPES.get(node_type)
    if cls is None:
        raise ValueError(f"unknown node type: {node_type!r} (known: {sorted(_NODE_TYPES)})")
    kwargs = {k: v for k, v in cfg.items() if k not in ("id", "type")}
    return cls(cfg["id"], **kwargs)


def run(scenario: dict) -> ScenarioResult:
    se = SysExecutor(1, ex_mode=ExecutionType.V_TIME)

    nodes: dict[str, Any] = {}
    for node_cfg in scenario.get("nodes", []):
        node = _build_node(node_cfg)
        nodes[node_cfg["id"]] = node
        se.register_entity(node)

    for coupling in scenario.get("couplings", []):
        src_id, src_port = coupling["from"]
        dst_id, dst_port = coupling["to"]
        se.coupling_relation(nodes[src_id], src_port, nodes[dst_id], dst_port)

    stimuli = sorted(scenario.get("stimuli", []), key=lambda s: s["at"])
    ext_ports: dict[tuple[str, str], str] = {}
    for stim in stimuli:
        key = (stim["target"], stim["port"])
        if key not in ext_ports:
            ext_port_name = f"ext__{stim['target']}__{stim['port']}"
            se.insert_input_port(ext_port_name)
            se.coupling_relation(None, ext_port_name, nodes[stim["target"]], stim["port"])
            ext_ports[key] = ext_port_name

    for stim in stimuli:
        ext_port_name = ext_ports[(stim["target"], stim["port"])]
        se.insert_external_event(ext_port_name, stim["msg"], scheduled_time=stim["at"])

    result = ScenarioResult(scenario_id=scenario.get("id", "unnamed"), description=scenario.get("description", ""), nodes=nodes)

    # pyjevsim's `simulate(_time)` loop exits as soon as `global_time` reaches
    # its target, which can be *before* `handle_external_input_event()` has
    # run again to actually pop and deliver an event scheduled for exactly
    # that instant (that happens on the *next* schedule() round). Advancing
    # a hair past each checkpoint forces that round to run, so an event
    # scheduled for exactly this checkpoint's time is reliably delivered
    # before state is captured. Verified empirically - see simulator/devs/README.md.
    _FLUSH_EPS = 1e-6

    run_until = scenario.get("run_until", 0.0)
    checkpoint_times = sorted({0.0, *(s["at"] for s in stimuli), run_until})
    trace_lengths: dict[str, int] = {node_id: 0 for node_id in nodes}

    for checkpoint_time in checkpoint_times:
        se.simulate(checkpoint_time + _FLUSH_EPS - se.get_global_time())
        label = next((s.get("label") for s in stimuli if s["at"] == checkpoint_time), str(checkpoint_time))
        cp = Checkpoint(time=checkpoint_time, label=label)
        for node_id, node in nodes.items():
            if hasattr(node, "last_states"):
                cp.node_states[node_id] = dict(node.last_states)
                cp.node_resolutions[node_id] = dict(node.last_resolutions)
            new_entries = node.trace[trace_lengths[node_id]:]
            for entry in new_entries:
                result.trace.append({"time": checkpoint_time, "node": node_id, **entry})
            trace_lengths[node_id] = len(node.trace)
        result.checkpoints.append(cp)

    _check_expectations(scenario.get("expectations", []), result)
    return result


def _check_expectations(expectations: list[dict], result: ScenarioResult) -> None:
    for exp in expectations:
        etype = exp["type"]
        try:
            if etype == "capability_state":
                cp = result.checkpoint(exp.get("after", result.checkpoints[-1].time))
                states = cp.node_states.get(exp["node"], {})
                for kind, expected in exp["state"].items():
                    actual = states.get(kind)
                    actual_value = actual.value if actual is not None else "DISABLED"
                    if actual_value != expected:
                        result.check_failures.append(
                            f"[{exp['node']}@{cp.label}] capability_state[{kind}] expected {expected}, got {actual_value}"
                        )
            elif etype == "provider_id":
                cp = result.checkpoint(exp.get("after", result.checkpoints[-1].time))
                resolutions = cp.node_resolutions.get(exp["node"], {})
                for kind, expected in exp["provider"].items():
                    resolution = resolutions.get(kind)
                    actual = resolution.provider.provider_id if resolution and resolution.provider else None
                    if actual != expected:
                        result.check_failures.append(
                            f"[{exp['node']}@{cp.label}] provider[{kind}] expected {expected!r}, got {actual!r}"
                        )
            elif etype == "reason":
                cp = result.checkpoint(exp.get("after", result.checkpoints[-1].time))
                resolutions = cp.node_resolutions.get(exp["node"], {})
                for kind, expected in exp["reason"].items():
                    actual = resolutions[kind].reason if kind in resolutions else None
                    if actual != expected:
                        result.check_failures.append(
                            f"[{exp['node']}@{cp.label}] reason[{kind}] expected {expected!r}, got {actual!r}"
                        )
            elif etype == "core_kinds_running":
                node = result.nodes[exp["node"]]
                actual = node.app.core_kinds_running()
                if actual != exp["value"]:
                    result.check_failures.append(f"[{exp['node']}] core_kinds_running expected {exp['value']}, got {actual}")
            elif etype == "degradation_count_at_least":
                node = result.nodes[exp["node"]]
                if node.reconfigurer.degradation_count() < exp["value"]:
                    result.check_failures.append(
                        f"[{exp['node']}] degradation_count {node.reconfigurer.degradation_count()} < {exp['value']}"
                    )
            elif etype == "recovery_count_at_least":
                node = result.nodes[exp["node"]]
                if node.reconfigurer.recovery_count() < exp["value"]:
                    result.check_failures.append(
                        f"[{exp['node']}] recovery_count {node.reconfigurer.recovery_count()} < {exp['value']}"
                    )
            elif etype == "event_logged":
                node = result.nodes[exp["node"]]
                matches = [
                    e for e in node.observability.events
                    if e.name == exp["name"]
                    and (exp.get("severity") is None or e.severity == exp["severity"])
                    and all(e.payload.get(k) == v for k, v in exp.get("payload_contains", {}).items())
                ]
                if not matches:
                    result.check_failures.append(f"[{exp['node']}] no observability event matched {exp}")
            elif etype == "conformance":
                node = result.nodes[exp["node"]]
                registration = build_registration(exp["provider"], HealthBoard())
                report = check_provider_conformance(registration, node.registry)
                if report.passed != exp.get("must_pass", True):
                    result.check_failures.append(
                        f"[{exp['node']}] conformance for {exp['provider']['provider_id']}: {report.failures}"
                    )
            elif etype == "source_scan":
                dirs = tuple(exp["dirs"]) if "dirs" in exp else None
                for token in exp["forbidden_tokens"]:
                    hits = core_source_mentions(token) if dirs is None else core_source_mentions(token, dirs)
                    if hits:
                        result.check_failures.append(f"core code mentions {token!r}: {hits}")
            elif etype == "latency_budget":
                # Checks a delivery latency in the simulated timeline
                # against a budget by diffing the matching "in"/"out" trace
                # entries' *checkpoint* timestamps -- real delivery happens
                # at whatever simulated instant the DEVS model's own
                # deadline fires, but this runner only samples state at
                # checkpoints (stimuli "at" times + run_until; see the
                # module docstring), so the observed value here is always
                # >= the model's true internal latency, never less. A
                # scenario wanting a tight check needs a checkpoint (a
                # stimulus "at" or `run_until`) placed close to the
                # expected real latency -- this is a deliberately
                # pessimistic bound, not a precise measurement.
                in_entries = [e for e in result.trace if e["node"] == exp["node"] and e["direction"] == "in"]
                out_entries = [e for e in result.trace if e["node"] == exp["node"] and e["direction"] == "out"]
                if not in_entries or not out_entries:
                    result.check_failures.append(f"[{exp['node']}] latency_budget: no in/out trace entries to measure")
                else:
                    observed = out_entries[-1]["time"] - in_entries[0]["time"]
                    if observed > exp["max_s"]:
                        result.check_failures.append(
                            f"[{exp['node']}] latency_budget exceeded: {observed}s > {exp['max_s']}s"
                        )
            elif etype == "accuracy_floor":
                # Not a live model inference inside the simulator (out of
                # scope for a DEVS timing model) -- checks the *measured*
                # accuracy this provider registration was seeded with
                # (`measured_accuracy` on `build_registration`, itself from a
                # real run against real images) against a floor, so a
                # scenario cannot silently regress the number it depends on.
                node = result.nodes[exp["node"]]
                providers = node.registry.available_providers(exp["kind"])
                matched = next((p for p in providers if p.provider_id == exp["provider_id"]), None)
                measured = getattr(matched, "measured_accuracy", None) if matched else None
                if measured is None:
                    result.check_failures.append(
                        f"[{exp['node']}] accuracy_floor: no measured_accuracy recorded for {exp['provider_id']}"
                    )
                elif measured < exp["min"]:
                    result.check_failures.append(
                        f"[{exp['node']}] accuracy_floor: {exp['provider_id']} measured {measured} < {exp['min']}"
                    )
            elif etype == "node_state":
                # Generic last_states probe for the newer atomic models
                # (perception_risk_node/observability_node/
                # cluster_control_node/learning_pipeline_node) -- walks
                # `exp["path"]` (a list of dict keys) into that node's
                # `last_states` snapshot at the given checkpoint, unwraps a
                # trailing `.value` if the leaf is an Enum, and compares
                # against `exp["expected"]`. Kept separate from
                # `capability_state` (which is specific to RegistryNode's
                # CapabilityState enum and its own resolution machinery).
                cp = result.checkpoint(exp.get("after", result.checkpoints[-1].time))
                states = cp.node_states.get(exp["node"], {})
                value = states
                for key in exp["path"]:
                    if not isinstance(value, dict) or key not in value:
                        value = None
                        break
                    value = value[key]
                actual = getattr(value, "value", value)
                if actual != exp["expected"]:
                    result.check_failures.append(
                        f"[{exp['node']}@{cp.label}] node_state{exp['path']} expected {exp['expected']!r}, got {actual!r}"
                    )
            elif etype == "trace_contains":
                at_or_before = exp.get("at_or_before")
                payload_contains = exp.get("payload_contains", {})
                matches = [
                    entry for entry in result.trace
                    if entry["node"] == exp["node"]
                    and entry["port"] == exp["port"]
                    and entry["direction"] == exp.get("direction", "out")
                    and entry["payload"].get("message_type") == exp.get("message_type")
                    and (at_or_before is None or entry["time"] <= at_or_before)
                    and all(entry["payload"].get("payload", {}).get(k) == v for k, v in payload_contains.items())
                ]
                if not matches:
                    result.check_failures.append(f"no trace entry matched {exp}")
            else:
                result.check_failures.append(f"unknown expectation type: {etype!r}")
        except Exception as error:  # a malformed expectation must not hide the others
            result.check_failures.append(f"expectation {exp} raised {error!r}")
