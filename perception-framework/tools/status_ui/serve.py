"""Local review panel for capability resolution / placement (stdlib only).

implements: AI-C-05, AI-C-13, AI-C-18, AI-B-04, AI-B-06, AI-O-02 (review tooling)

This is a *review tool*, not the production UI — the production UI belongs
to the visualization team (docs/ai/design/capability-ui-orchestration-plan.md
§3-4, AI-C-19). It exists so the project owner can look at what the
framework now computes without reading test output:

- P1 `ZoneApplication.resolve()` per node, with every considered candidate
  and why it lost (`CapabilityResolution.alternatives`),
- P2 the controlled reason vocabulary (`STATE_CHANGE_REASONS`),
- P3 providers loaded from a JSON manifest (`registry/manifest.py`),
- P4 placement actions / `nodeSelector` (`runtime/placement.py`),
- the *function* axis: which user-level functions are possible right now
  across the whole fleet, what resources each needs per tier, and — for
  an unavailable one — the minimal supplement per tier. A device is just
  one provider; the page is organised by function, resource and tier
  (role), not by node name. Function availability is
  `TaskIntent.evaluate_availability()` (contracts/capability_contract.py,
  AI-C-18) over the set of kinds some node actually serves.

Nothing here re-judges anything. Every number and word on the page comes
from `CapabilityRegistry`, `ZoneApplication.resolve()`,
`TaskIntent.evaluate_availability()` and `PlacementReconciler`; the only
thing this module *adds* is a display grade (`derive_grade`) that is
explicitly derived, never stored, and never fed back into the framework.
Device availability is not touched at all (원칙 #15: 장치 최종 가용성은
백엔드가 판정한다).

API responses are language-neutral: ids only. Human labels (ko/en) live in
a separate labels file served by `/api/labels`; identity, permission and
per-audience filtering are deliberately out of scope here so they can be
designed on top of these additive payloads later.

Layout: `load_ui_config` + `StatusService` are pure and testable without
sockets; `make_server` wraps them in `http.server`. No third-party
dependency and no external resource — the page must render inside a closed
network (AI-C-16).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

# `tools/` is not a package; when run as a script the framework package must
# already be importable (pip install -e . in perception-framework/).
_FRAMEWORK_DIR = Path(__file__).resolve().parents[2]
if str(_FRAMEWORK_DIR) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK_DIR))

from perception_framework.contracts.capability import CapabilityRequirement, CapabilityState  # noqa: E402
from perception_framework.contracts.capability_contract import TaskIntent  # noqa: E402
from perception_framework.contracts.data_dictionary import (  # noqa: E402
    STATE_CHANGE_REASONS,
    state_change_reason_token,
)
from perception_framework.contracts.profile import DeploymentProfile, ResourceBudget  # noqa: E402
from perception_framework.contracts.profile_loader import profile_from_dict  # noqa: E402
from perception_framework.execution.control import LocalControlSupervisor  # noqa: E402
from perception_framework.providers.k3s import K3sControlProvider  # noqa: E402
from perception_framework.registry.capability_registry import CapabilityRegistry  # noqa: E402
from perception_framework.registry.manifest import (  # noqa: E402
    ProviderManifest,
    load_provider_manifest,
    register_all,
)
from perception_framework.runtime.application import (  # noqa: E402
    CapabilityResolution,
    CapabilitySpec,
    ZoneApplication,
)
from perception_framework.runtime.placement import PlacementReconciler, node_selector_for  # noqa: E402

UI_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_LABELS_FILENAME = "status_ui.labels.json"
# Placement commands the page can show; the labels file must name each.
PLACEMENT_COMMANDS = ("start", "stop", "in_process")
# What-if override key that applies to every node (per-node keys merge on top).
OVERRIDE_ALL = "*"

# --- display grade (derived, never a framework state) -----------------------

GRADE_READY = "READY"
GRADE_DEGRADED = "DEGRADED"
GRADE_MISSING = "MISSING"
GRADE_STALE = "STALE"
GRADE_BLOCKED = "BLOCKED"

_MISSING_TOKENS = frozenset({"missing_required", "no_provider_registered"})
_STALE_TOKENS = frozenset({"runtime_instance_unhealthy_or_expired", "input_too_stale", "deadline_exceeded"})

GRADE_DESCRIPTIONS: dict[str, str] = {
    GRADE_READY: "ACTIVE — 필수·선택 조건 모두 충족, provider 선택됨",
    GRADE_DEGRADED: "DEGRADED — 필수 조건은 충족, 선택 의존 kind 결손(축소 운용)",
    GRADE_MISSING: "DISABLED + missing_required | no_provider_registered — 있어야 할 것이 없다",
    GRADE_STALE: "DISABLED + runtime_instance_unhealthy_or_expired | input_too_stale | deadline_exceeded — 있지만 지금 쓸 수 없다",
    GRADE_BLOCKED: "DISABLED + 그 외 사유(over budget, tag mismatch, egress gate, core_capability_unplaced …) — 조건이 막는다",
}


def derive_grade(state: CapabilityState | str, reason: str) -> str:
    """Display grade for one (CapabilityState, reason) pair.

    This grade is **derived for display only**. It is not a framework state:
    the framework has exactly three (ACTIVE / DEGRADED / DISABLED) and the
    isolation rule "optional 결손은 DEGRADED까지만" is expressed in those
    three. BLOCKED / MISSING / STALE are all DISABLED — they differ only in
    *why*, which the controlled reason vocabulary already carries
    (docs/ai/design/capability-ui-orchestration-plan.md §3-2). Consumers may
    re-derive a different grade from the same inputs; nothing stores this one.
    """
    value = state.value if isinstance(state, CapabilityState) else str(state)
    if value == CapabilityState.ACTIVE.value:
        return GRADE_READY
    if value == CapabilityState.DEGRADED.value:
        return GRADE_DEGRADED
    token = state_change_reason_token(reason or "")
    if token in _MISSING_TOKENS:
        return GRADE_MISSING
    if token in _STALE_TOKENS:
        return GRADE_STALE
    return GRADE_BLOCKED


# --- configuration ----------------------------------------------------------


class UiConfigError(ValueError):
    pass


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    label: str
    tags: tuple[str, ...]
    budget: ResourceBudget
    # Tier of the node (ondevice / edge / server / …). A free string, never
    # validated against an enum: a new tier is a new string plus a label
    # (원칙 #1 — no vendor/tier enum in the framework or in this tool).
    role: str = "unspecified"

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "role": self.role,
            "tags": list(self.tags),
            "budget": _budget_to_dict(self.budget),
        }


@dataclass(frozen=True)
class FunctionConfig:
    """A user-level function expressed only as capability kinds — the same
    shape as `TaskIntent(required_capabilities, optional_capabilities)`.
    Labels are *not* here (they belong to the labels file), so the config
    stays language-neutral."""

    function_id: str
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]

    def intent(self) -> TaskIntent:
        return TaskIntent(
            required_capabilities=self.required_capabilities,
            optional_capabilities=self.optional_capabilities,
        )

    def to_dict(self) -> dict:
        return {
            "function_id": self.function_id,
            "required_capabilities": list(self.required_capabilities),
            "optional_capabilities": list(self.optional_capabilities),
        }


@dataclass(frozen=True)
class UiConfig:
    path: Path
    providers_manifest: Path
    profile: DeploymentProfile
    specs: tuple[CapabilitySpec, ...]
    nodes: tuple[NodeConfig, ...]
    functions: tuple[FunctionConfig, ...] = ()
    labels_path: Path | None = None
    raw: dict = field(default_factory=dict, repr=False)

    def node(self, node_id: str) -> NodeConfig:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise UiConfigError(f"unknown_node:{node_id}")

    def spec(self, kind: str) -> CapabilitySpec | None:
        for spec in self.specs:
            if spec.kind == kind:
                return spec
        return None

    def roles(self) -> list[str]:
        """Distinct node roles in first-seen order (the tier sections)."""
        seen: list[str] = []
        for node in self.nodes:
            if node.role not in seen:
                seen.append(node.role)
        return seen


def load_ui_config(path: str | Path) -> UiConfig:
    """Read `config/status_ui*.json`. `providers_manifest` (and the optional
    `labels` file, default `status_ui.labels.json` next to the config) are
    resolved relative to the config file; the `deployment` object goes
    through `profile_from_dict` unchanged (so its unknown-key rejection
    still applies), `capabilities` become `CapabilitySpec`s, `nodes` become
    `NodeConfig`s (with a free-string `role`), `functions` (optional) become
    `FunctionConfig`s."""
    path = Path(path).resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise UiConfigError(f"{path}: not valid JSON: {error}") from error
    if not isinstance(raw, dict):
        raise UiConfigError(f"{path}: top level must be a JSON object")

    manifest_ref = raw.get("providers_manifest")
    if not isinstance(manifest_ref, str) or not manifest_ref:
        raise UiConfigError("providers_manifest: must be a non-empty path string")
    manifest_path = (path.parent / manifest_ref).resolve()

    labels_ref = raw.get("labels", DEFAULT_LABELS_FILENAME)
    if not isinstance(labels_ref, str) or not labels_ref:
        raise UiConfigError("labels: must be a non-empty path string")
    labels_path = (path.parent / labels_ref).resolve()

    deployment = raw.get("deployment")
    if not isinstance(deployment, dict):
        raise UiConfigError("deployment: must be a JSON object (DeploymentProfile fields)")
    profile = profile_from_dict(deployment)

    specs = tuple(_spec_from(i, entry) for i, entry in enumerate(_list(raw, "capabilities")))
    nodes = tuple(_node_from(i, entry) for i, entry in enumerate(_list(raw, "nodes")))
    if not nodes:
        raise UiConfigError("nodes: at least one node is required")
    ids = [n.node_id for n in nodes]
    if len(set(ids)) != len(ids):
        raise UiConfigError("nodes: duplicate node_id")

    functions: tuple[FunctionConfig, ...] = ()
    if raw.get("functions") is not None:
        functions = tuple(_function_from(i, entry) for i, entry in enumerate(_list(raw, "functions")))
        function_ids = [f.function_id for f in functions]
        if len(set(function_ids)) != len(function_ids):
            raise UiConfigError("functions: duplicate function_id")

    return UiConfig(
        path=path,
        providers_manifest=manifest_path,
        profile=profile,
        specs=specs,
        nodes=nodes,
        functions=functions,
        labels_path=labels_path,
        raw=raw,
    )


def _list(raw: dict, key: str) -> list:
    value = raw.get(key)
    if not isinstance(value, list):
        raise UiConfigError(f"{key}: must be a JSON array")
    return value


def _spec_from(index: int, entry: Any) -> CapabilitySpec:
    where = f"capabilities[{index}]"
    if not isinstance(entry, dict) or not isinstance(entry.get("kind"), str) or not entry["kind"]:
        raise UiConfigError(f"{where}: needs a non-empty 'kind'")
    requirement = entry.get("requirement", {})
    if not isinstance(requirement, dict):
        raise UiConfigError(f"{where}.requirement: must be a JSON object")
    return CapabilitySpec(
        kind=entry["kind"],
        is_core=bool(entry.get("is_core", False)),
        requirement=CapabilityRequirement(
            required=_str_tuple(where, "requirement.required", requirement.get("required", ())),
            optional=_str_tuple(where, "requirement.optional", requirement.get("optional", ())),
        ),
        degrade_rank=int(entry.get("degrade_rank", 0)),
    )


def _node_from(index: int, entry: Any) -> NodeConfig:
    where = f"nodes[{index}]"
    if not isinstance(entry, dict) or not isinstance(entry.get("node_id"), str) or not entry["node_id"]:
        raise UiConfigError(f"{where}: needs a non-empty 'node_id'")
    role = entry.get("role", "unspecified")
    if not isinstance(role, str) or not role:
        raise UiConfigError(f"{where}.role: must be a non-empty string")
    return NodeConfig(
        node_id=entry["node_id"],
        label=str(entry.get("label", entry["node_id"])),
        tags=_str_tuple(where, "tags", entry.get("tags", ())),
        budget=_budget_from(where, entry.get("budget", {})),
        role=role,
    )


def _function_from(index: int, entry: Any) -> FunctionConfig:
    where = f"functions[{index}]"
    if not isinstance(entry, dict) or not isinstance(entry.get("function_id"), str) or not entry["function_id"]:
        raise UiConfigError(f"{where}: needs a non-empty 'function_id'")
    return FunctionConfig(
        function_id=entry["function_id"],
        required_capabilities=_str_tuple(where, "required_capabilities", entry.get("required_capabilities", ())),
        optional_capabilities=_str_tuple(where, "optional_capabilities", entry.get("optional_capabilities", ())),
    )


def _str_tuple(where: str, key: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise UiConfigError(f"{where}.{key}: must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise UiConfigError(f"{where}.{key}: must be a list of strings")
    return tuple(value)


def _budget_from(where: str, raw: Any, base: ResourceBudget | None = None) -> ResourceBudget:
    """`base` supplies defaults so a what-if may override only one field."""
    if not isinstance(raw, dict):
        raise UiConfigError(f"{where}.budget: must be a JSON object")
    defaults = base or ResourceBudget(compute_units=0.0, memory_mb=0.0)
    try:
        return ResourceBudget(
            compute_units=float(raw.get("compute_units", defaults.compute_units)),
            memory_mb=float(raw.get("memory_mb", defaults.memory_mb)),
            max_latency_ms=(
                None
                if raw.get("max_latency_ms", defaults.max_latency_ms) is None
                else float(raw.get("max_latency_ms", defaults.max_latency_ms))
            ),
        )
    except (TypeError, ValueError) as error:
        raise UiConfigError(f"{where}.budget: numbers expected ({error})") from error


def _budget_to_dict(budget: ResourceBudget) -> dict:
    return {
        "compute_units": budget.compute_units,
        "memory_mb": budget.memory_mb,
        "max_latency_ms": budget.max_latency_ms,
    }


# --- control provider selection ---------------------------------------------


def select_control(mode: str, namespace: str = "default") -> tuple[Any, dict]:
    """`local` → LocalControlSupervisor; `k3s` → K3sControlProvider if an
    orchestrator answers, otherwise the local supervisor with the fallback
    recorded (AI-B-05: 오케스트레이터가 없어도 진행). Never raises on a
    missing kubectl."""
    info = {"requested": mode, "active": "local", "reason": None, "namespace": namespace}
    if mode == "k3s":
        try:
            candidate = K3sControlProvider(namespace=namespace)
            available = candidate.is_available()
        except Exception as error:  # kubectl present but broken, timeouts, ...
            available = False
            info["reason"] = f"orchestrator_error:{type(error).__name__}"
        if available:
            info["active"] = "k3s"
            return candidate, info
        info["reason"] = info["reason"] or "orchestrator_unavailable"
    elif mode != "local":
        info["reason"] = f"unknown_control_mode:{mode}"
    return LocalControlSupervisor(), info


# --- service ------------------------------------------------------------------


class StatusService:
    """Everything the HTTP layer exposes, callable without sockets.

    One base `CapabilityRegistry` is built from the manifest once; every
    `resolve` works on a fresh registry copy so provider exclusion in a
    what-if never mutates shared state. One `PlacementReconciler` per node
    (created lazily) keeps that node's bound providers between applies.
    """

    def __init__(
        self,
        config: UiConfig,
        *,
        control_mode: str = "local",
        namespace: str = "default",
        control: Any | None = None,
        manifest: ProviderManifest | None = None,
    ) -> None:
        self.config = config
        self.manifest = manifest or load_provider_manifest(config.providers_manifest)
        self.registry = CapabilityRegistry()
        register_all(self.manifest, self.registry)
        self._control_mode = control_mode
        self._namespace = namespace
        self._injected_control = control
        self.events: list[dict] = []
        self._events_lock = threading.Lock()
        self._reconcilers: dict[str, PlacementReconciler] = {}
        self.control: Any = None
        self.control_info: dict = {}
        self._install_control()

    # --- event sink (the reconciler's `observability`) -----------------------
    def record_event(self, name: str, severity: str, payload: dict | None = None) -> None:
        entry = {"ts": time.time(), "name": name, "severity": severity, "payload": payload or {}}
        with self._events_lock:
            self.events.append(entry)
            if len(self.events) > 500:
                del self.events[: len(self.events) - 500]

    def record_metric(self, name: str, value: float, tags: dict | None = None) -> None:
        # Metrics are not part of this review tool; accepted so any provider
        # that emits them does not fail on this sink.
        return None

    def _install_control(self) -> None:
        if self._injected_control is not None:
            self.control = self._injected_control
            self.control_info = {
                "requested": "injected", "active": "injected", "reason": None, "namespace": self._namespace,
            }
            return
        self.control, self.control_info = select_control(self._control_mode, self._namespace)
        if self.control_info.get("reason"):
            self.record_event("control_fallback", "warning", dict(self.control_info))

    def reset(self) -> None:
        """Forget bound providers, events and the control provider's state."""
        self._reconcilers.clear()
        with self._events_lock:
            self.events.clear()
        self._install_control()
        self.record_event("reset", "info", {"control": self.control_info.get("active")})

    # --- describe ------------------------------------------------------------
    def describe(self) -> dict:
        return {
            "config_path": str(self.config.path),
            "providers_manifest": str(self.config.providers_manifest),
            "deployment": {
                "domain_id": self.config.profile.domain_id,
                "active_capability_kinds": list(self.config.profile.active_capability_kinds),
                "closed_network": self.config.profile.closed_network,
                "rule_set_id": self.config.profile.rule_set_id,
            },
            "capabilities": [
                {
                    "kind": s.kind,
                    "is_core": s.is_core,
                    "degrade_rank": s.degrade_rank,
                    "required": list(s.requirement.required),
                    "optional": list(s.requirement.optional),
                }
                for s in self.config.specs
            ],
            "nodes": [n.to_dict() for n in self.config.nodes],
            "roles": self.config.roles(),
            "functions": [f.to_dict() for f in self.config.functions],
            "providers": [self._provider_to_dict(r) for r in self.manifest.registrations],
            "all_tags": self.all_tags(),
            "control": dict(self.control_info),
            "labels_path": str(self.config.labels_path) if self.config.labels_path else None,
            "labels_missing": self.labels_missing(),
        }

    # --- labels (ko/en) --------------------------------------------------------
    def labels(self) -> dict:
        """The labels file as-is (read on every call so an edit shows up
        without a restart). Missing file → an empty skeleton, never an
        error: the page falls back to raw ids."""
        path = self.config.labels_path
        if path is None or not path.is_file():
            return {"languages": [], "ui": {}, "capability_kinds": {}, "functions": {},
                    "states": {}, "grades": {}, "reasons": {}, "roles": {}, "commands": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise UiConfigError(f"{path}: not valid JSON: {error}") from error
        if not isinstance(data, dict):
            raise UiConfigError(f"{path}: top level must be a JSON object")
        return data

    def label_ids(self) -> dict[str, list[str]]:
        """Every id the page can show, per labels section — what the labels
        file must cover in every declared language."""
        kinds: set[str] = set(self.config.profile.active_capability_kinds)
        kinds.update(s.kind for s in self.config.specs)
        kinds.update(r.capability_kind for r in self.manifest.registrations)
        for function in self.config.functions:
            kinds.update(function.required_capabilities)
            kinds.update(function.optional_capabilities)
        return {
            "capability_kinds": sorted(kinds),
            "functions": [f.function_id for f in self.config.functions],
            "states": [s.value for s in CapabilityState],
            "grades": list(GRADE_DESCRIPTIONS),
            "reasons": list(STATE_CHANGE_REASONS),
            "roles": self.config.roles(),
            "commands": list(PLACEMENT_COMMANDS),
        }

    def labels_missing(self) -> list[str]:
        """`"<section>.<id>.<lang>"` for every id/language pair the labels
        file does not cover (plus `ui.<key>.<lang>` for a ui key that lacks
        a language). Empty means complete."""
        labels = self.labels()
        languages = [lang for lang in labels.get("languages", []) if isinstance(lang, str)]
        missing: list[str] = []

        def check(section: str, ident: str, entry: Any, *subkeys: str) -> None:
            for lang in languages:
                node = entry
                for sub in subkeys:
                    node = node.get(sub) if isinstance(node, dict) else None
                value = node.get(lang) if isinstance(node, dict) else None
                if not isinstance(value, str) or not value:
                    missing.append(".".join((section, ident, *subkeys, lang)))

        for section, ids in self.label_ids().items():
            table = labels.get(section) or {}
            for ident in ids:
                entry = table.get(ident) if isinstance(table, dict) else None
                if section == "functions":
                    check(section, ident, entry or {}, "label")
                    check(section, ident, entry or {}, "description")
                else:
                    check(section, ident, entry or {})
        ui = labels.get("ui") or {}
        if isinstance(ui, dict):
            for key, entry in ui.items():
                check("ui", key, entry or {})
        return missing

    def all_tags(self) -> list[str]:
        """Union of node tags and every required/preferred tag any provider
        declares — the checkbox set for the what-if panel."""
        tags: set[str] = set()
        for node in self.config.nodes:
            tags.update(node.tags)
        for reg in self.manifest.registrations:
            tags.update(reg.compatibility.required_hw_tags)
            tags.update(reg.compatibility.preferred_hw_tags)
            tags.update(reg.compatibility.required_runtime_tags)
        return sorted(tags)

    def vocabulary(self) -> dict:
        return {
            "state_change_reasons": list(STATE_CHANGE_REASONS),
            "grades": dict(GRADE_DESCRIPTIONS),
            "capability_states": [s.value for s in CapabilityState],
        }

    def _provider_to_dict(self, reg) -> dict:
        comp = reg.compatibility
        return {
            "capability_kind": reg.capability_kind,
            "provider_id": reg.provider_id,
            "version": reg.version,
            "required_hw_tags": list(comp.required_hw_tags),
            "preferred_hw_tags": list(comp.preferred_hw_tags),
            "required_runtime_tags": list(comp.required_runtime_tags),
            "cost": {"compute_units": comp.cost.compute_units, "memory_mb": comp.cost.memory_mb},
            "priority": comp.priority,
            "deployable": reg.provider_id in self.manifest.deployment_params,
            "deployment": self.manifest.deployment_params.get(reg.provider_id),
        }

    # --- resolve -------------------------------------------------------------
    def _registry_without(self, exclude_providers) -> CapabilityRegistry:
        excluded = set(exclude_providers or ())
        registry = CapabilityRegistry()
        for reg in self.manifest.registrations:
            if reg.provider_id not in excluded:
                registry.register_local(reg)
        return registry

    def _effective(self, node_id: str, tags, budget) -> tuple[NodeConfig, set[str], ResourceBudget]:
        node = self.config.node(node_id)
        effective_tags = set(node.tags) if tags is None else set(_str_tuple("whatif", "tags", tags))
        effective_budget = node.budget if budget is None else _budget_from("whatif", budget, base=node.budget)
        return node, effective_tags, effective_budget

    def _resolve_raw(
        self, node_id: str, *, tags=None, budget=None, exclude_providers=()
    ) -> tuple[NodeConfig, set[str], ResourceBudget, dict[str, CapabilityResolution]]:
        node, effective_tags, effective_budget = self._effective(node_id, tags, budget)
        registry = self._registry_without(exclude_providers)
        app = ZoneApplication(self.config.profile, registry, list(self.config.specs), node_tags=effective_tags)
        return node, effective_tags, effective_budget, app.resolve(effective_budget)

    def resolve(self, node_id: str, *, tags=None, budget=None, exclude_providers=()) -> dict:
        """JSON-able resolution table for one node (optionally under what-if
        overrides). `rows` follow `active_capability_kinds` order."""
        node, effective_tags, effective_budget, resolutions = self._resolve_raw(
            node_id, tags=tags, budget=budget, exclude_providers=exclude_providers
        )
        rows = [
            self._row(kind, resolutions[kind])
            for kind in self.config.profile.active_capability_kinds
            if kind in resolutions
        ]
        return {
            "node_id": node.node_id,
            "label": node.label,
            "role": node.role,
            "tags": sorted(effective_tags),
            "budget": _budget_to_dict(effective_budget),
            "exclude_providers": sorted(set(exclude_providers or ())),
            "rows": rows,
        }

    def _row(self, kind: str, res: CapabilityResolution) -> dict:
        spec = self.config.spec(kind)
        provider = res.provider
        token = state_change_reason_token(res.reason)
        return {
            "kind": kind,
            "is_core": bool(spec and spec.is_core),
            "degrade_rank": spec.degrade_rank if spec else 0,
            "requirement": {
                "required": list(spec.requirement.required) if spec else [],
                "optional": list(spec.requirement.optional) if spec else [],
            },
            "state": res.state.value,
            "derived_grade": derive_grade(res.state, res.reason),
            "provider_id": provider.provider_id if provider else None,
            "provider_version": provider.version if provider else None,
            "reason": res.reason,
            "reason_token": token,
            "reason_data": _reason_data(res.reason),
            "alternatives": [
                {
                    "provider_id": alt.provider_id,
                    "reason": alt.reason,
                    "reason_token": state_change_reason_token(alt.reason),
                    "reason_data": _reason_data(alt.reason),
                }
                for alt in res.alternatives
            ],
            "cost": (
                {
                    "compute_units": provider.compatibility.cost.compute_units,
                    "memory_mb": provider.compatibility.cost.memory_mb,
                }
                if provider
                else None
            ),
            "priority": provider.compatibility.priority if provider else None,
            "required_hw_tags": list(provider.compatibility.required_hw_tags) if provider else [],
            "node_selector": _selector_or_none(provider),
            "deployable": bool(provider and provider.provider_id in self.manifest.deployment_params),
        }

    # --- what-if -------------------------------------------------------------
    def whatif(self, node_id: str, *, tags=None, budget=None, exclude_providers=()) -> dict:
        baseline = self.resolve(node_id)
        override = self.resolve(node_id, tags=tags, budget=budget, exclude_providers=exclude_providers)
        before = {row["kind"]: row for row in baseline["rows"]}
        diff = []
        for row in override["rows"]:
            prev = before.get(row["kind"])
            entry = {
                "kind": row["kind"],
                "before_state": prev["state"] if prev else None,
                "after_state": row["state"],
                "before_provider": prev["provider_id"] if prev else None,
                "after_provider": row["provider_id"],
            }
            entry["changed"] = (
                entry["before_state"] != entry["after_state"]
                or entry["before_provider"] != entry["after_provider"]
            )
            diff.append(entry)
        return {"node_id": node_id, "baseline": baseline, "override": override, "diff": diff}

    # --- fleet / functions (function axis) ------------------------------------
    def _node_overrides(self, overrides) -> dict[str, dict]:
        """Normalise `{node_id: {tags?, budget?, exclude_providers?}}`. The
        key `"*"` supplies defaults for every node; a per-node entry merges
        on top of it. Unknown node ids raise `unknown_node:<id>`."""
        if overrides is None:
            overrides = {}
        if not isinstance(overrides, dict):
            raise UiConfigError("overrides: must be a JSON object keyed by node_id")
        for node_id, entry in overrides.items():
            if not isinstance(entry, dict):
                raise UiConfigError(f"overrides.{node_id}: must be a JSON object")
            if node_id != OVERRIDE_ALL:
                self.config.node(node_id)  # validates
        common = overrides.get(OVERRIDE_ALL, {})
        normalised: dict[str, dict] = {}
        for node in self.config.nodes:
            merged = dict(common)
            merged.update(overrides.get(node.node_id, {}))
            entry: dict = {}
            if merged.get("tags") is not None:
                entry["tags"] = merged["tags"]
            if merged.get("budget") is not None:
                entry["budget"] = merged["budget"]
            exclude = merged.get("exclude_providers")
            if exclude is not None:
                if isinstance(exclude, str) or not isinstance(exclude, list):
                    raise UiConfigError(f"overrides.{node.node_id}.exclude_providers: must be a list of provider_id strings")
                entry["exclude_providers"] = tuple(str(p) for p in exclude)
            normalised[node.node_id] = entry
        return normalised

    def fleet(self, overrides=None) -> dict:
        """Resolve every node (optionally under per-node what-if overrides).

        `served[kind]` lists only the nodes whose row for that kind is
        ACTIVE or DEGRADED, **sorted by the choice rule** used for the
        resource summary: lowest provider `priority` number first, then
        lowest cost (compute_units, memory_mb), then config node order —
        so `served[kind][0]` is the serving entry a function is charged
        for (each kind counted once).
        """
        per_node = self._node_overrides(overrides)
        nodes = []
        for index, node in enumerate(self.config.nodes):
            resolved = self.resolve(node.node_id, **per_node[node.node_id])
            resolved["index"] = index
            nodes.append(resolved)

        served: dict[str, list[dict]] = {}
        for resolved in nodes:
            for row in resolved["rows"]:
                if row["state"] not in (CapabilityState.ACTIVE.value, CapabilityState.DEGRADED.value):
                    continue
                if not row["provider_id"]:
                    continue
                served.setdefault(row["kind"], []).append(
                    {
                        "node_id": resolved["node_id"],
                        "role": resolved["role"],
                        "provider_id": row["provider_id"],
                        "priority": row["priority"],
                        "cost": dict(row["cost"]) if row["cost"] else {"compute_units": 0.0, "memory_mb": 0.0},
                        "required_hw_tags": list(row["required_hw_tags"]),
                        "state": row["state"],
                        "reason": row["reason"],
                        "_index": resolved["index"],
                    }
                )
        for kind, entries in served.items():
            entries.sort(key=_serving_choice_key)
            for entry in entries:
                del entry["_index"]
        for resolved in nodes:
            del resolved["index"]
        return {"overrides": {k: _jsonable_override(v) for k, v in per_node.items()}, "nodes": nodes, "served": served}

    def functions(self, overrides=None) -> dict:
        """The function axis: for every configured function, its state from
        `TaskIntent.evaluate_availability(set(kinds some node serves))`,
        the per-kind required/optional rows, the resources it would take per
        tier and, when a required kind is missing, the minimal supplement
        per tier.

        Resource rule (also documented on `fleet()`): a kind is counted once,
        charged to `served[kind][0]` — the serving node whose provider has
        the lowest `priority` number, then the lowest cost, then the earliest
        config order. Both required and optional kinds that are served are
        summed (the function running with everything available); `by_kind`
        lets a consumer recompute a required-only figure.

        Supplement rule: for each missing required kind and each role, one
        entry taken from that role's first node (config order) that has a
        reason; the reason is the *best-ranked alternative's* reason
        (lowest provider priority among `alternatives`) when the node
        considered candidates, otherwise the node's aggregate reason —
        "GPU tag missing" is more actionable than "nothing fit the budget".
        """
        fleet = self.fleet(overrides)
        served = fleet["served"]
        rows_by_node: dict[str, dict[str, dict]] = {
            n["node_id"]: {row["kind"]: row for row in n["rows"]} for n in fleet["nodes"]
        }
        excluded_by_node = {
            n["node_id"]: set(n["exclude_providers"]) for n in fleet["nodes"]
        }
        available = {kind for kind, entries in served.items() if entries}
        active_kinds = set(self.config.profile.active_capability_kinds)
        roles = self.config.roles()
        priority_of = {reg.provider_id: reg.compatibility.priority for reg in self.manifest.registrations}

        def why_for(kind: str) -> list[dict]:
            out = []
            for node in self.config.nodes:
                row = rows_by_node[node.node_id].get(kind)
                if row is not None:
                    if row["state"] in (CapabilityState.ACTIVE.value, CapabilityState.DEGRADED.value):
                        continue
                    out.append(
                        {
                            "node_id": node.node_id,
                            "role": node.role,
                            "reason": row["reason"],
                            "reason_token": row["reason_token"],
                            "reason_data": row["reason_data"],
                            "alternatives": list(row["alternatives"]),
                        }
                    )
                    continue
                # Kind is not activated in the deployment profile: nothing
                # was resolved. Report the one fact the registry knows.
                has_provider = any(
                    reg.capability_kind == kind and reg.provider_id not in excluded_by_node[node.node_id]
                    for reg in self.manifest.registrations
                )
                reason = None if has_provider else "no_provider_registered"
                out.append(
                    {
                        "node_id": node.node_id,
                        "role": node.role,
                        "reason": reason,
                        "reason_token": state_change_reason_token(reason) if reason else None,
                        "reason_data": None,
                        "alternatives": [],
                    }
                )
            return out

        def kind_row(kind: str) -> dict:
            entries = served.get(kind, [])
            return {
                "kind": kind,
                "activated": kind in active_kinds,
                "served_by": [
                    {k: v for k, v in e.items() if k in ("node_id", "role", "provider_id", "priority", "cost", "state")}
                    for e in entries
                ],
                "missing": not entries,
                "why": why_for(kind),
            }

        result = []
        for function in self.config.functions:
            state = function.intent().evaluate_availability(available)
            required_rows = [kind_row(k) for k in function.required_capabilities]
            optional_rows = [kind_row(k) for k in function.optional_capabilities]

            # resources: charge each served kind once to served[kind][0]
            by_role: dict[str, dict[str, float]] = {}
            by_kind: list[dict] = []
            hw_tags: set[str] = set()
            for is_required, kinds in ((True, function.required_capabilities), (False, function.optional_capabilities)):
                for kind in kinds:
                    entries = served.get(kind)
                    if not entries:
                        continue
                    chosen = entries[0]
                    bucket = by_role.setdefault(chosen["role"], {"compute_units": 0.0, "memory_mb": 0.0})
                    bucket["compute_units"] += float(chosen["cost"]["compute_units"])
                    bucket["memory_mb"] += float(chosen["cost"]["memory_mb"])
                    hw_tags.update(chosen["required_hw_tags"])
                    by_kind.append(
                        {
                            "kind": kind,
                            "required": is_required,
                            "role": chosen["role"],
                            "node_id": chosen["node_id"],
                            "provider_id": chosen["provider_id"],
                            "priority": chosen["priority"],
                            "cost": dict(chosen["cost"]),
                        }
                    )

            # supplement: per missing required kind × role
            supplement: list[dict] = []
            first_missing_reason: str | None = None
            for row in required_rows:
                if not row["missing"]:
                    continue
                for role in roles:
                    picked = _supplement_reason(row["why"], role, priority_of)
                    supplement.append({"kind": row["kind"], "role": role, **picked})
                    if first_missing_reason is None and picked["reason"]:
                        first_missing_reason = picked["reason"]
                if first_missing_reason is None:
                    first_missing_reason = f"missing_required:{row['kind']}"

            synthetic_reason = "selected" if state is not CapabilityState.DISABLED else (first_missing_reason or "")
            result.append(
                {
                    "function_id": function.function_id,
                    "state": state.value,
                    "derived_grade": derive_grade(state, synthetic_reason),
                    "reason": synthetic_reason,
                    "reason_token": state_change_reason_token(synthetic_reason) if synthetic_reason else None,
                    "required": required_rows,
                    "optional": optional_rows,
                    "resources": {
                        "by_role": by_role,
                        "by_kind": by_kind,
                        "required_hw_tags": sorted(hw_tags),
                    },
                    "supplement": supplement,
                }
            )
        return {"overrides": fleet["overrides"], "nodes": fleet["nodes"], "served": served, "functions": result}

    def whatif_functions(self, overrides) -> dict:
        before = self.functions()
        after = self.functions(overrides)
        before_by_id = {f["function_id"]: f for f in before["functions"]}
        diff = []
        for entry in after["functions"]:
            prev = before_by_id.get(entry["function_id"])
            diff.append(
                {
                    "function_id": entry["function_id"],
                    "before_state": prev["state"] if prev else None,
                    "after_state": entry["state"],
                    "changed": (prev["state"] if prev else None) != entry["state"],
                }
            )
        return {"before": before, "after": after, "diff": diff}

    # --- placement (P4) ------------------------------------------------------
    def _reconciler(self, node_id: str) -> PlacementReconciler:
        self.config.node(node_id)  # validates
        if node_id not in self._reconcilers:
            self._reconcilers[node_id] = PlacementReconciler(
                self.control,
                deployment_params=self.manifest.deployment_params,
                observability=self,
                requested_by=f"status_ui:{node_id}",
            )
        return self._reconcilers[node_id]

    def apply_placement(self, node_id: str, *, tags=None, budget=None, exclude_providers=()) -> list[dict]:
        _, _, _, resolutions = self._resolve_raw(
            node_id, tags=tags, budget=budget, exclude_providers=exclude_providers
        )
        actions = self._reconciler(node_id).apply(resolutions)
        return [
            {
                "kind": a.kind,
                "provider_id": a.provider_id,
                "command": a.command,
                "accepted": a.accepted,
                "rejection_reason": a.rejection_reason,
            }
            for a in actions
        ]

    def placement_state(self, node_id: str, *, audit_tail: int = 20) -> dict:
        reconciler = self._reconciler(node_id)
        by_id = {reg.provider_id: reg for reg in self.manifest.registrations}
        bound = []
        for kind in self.config.profile.active_capability_kinds:
            provider_id = reconciler.bound_provider(kind)
            if provider_id is None:
                continue
            reg = by_id.get(provider_id)
            bound.append(
                {
                    "kind": kind,
                    "provider_id": provider_id,
                    "node_selector": _selector_or_none(reg),
                    "deployable": reconciler.is_deployable(provider_id),
                    "status": _status_of(self.control, provider_id) if reconciler.is_deployable(provider_id) else None,
                }
            )
        audit = list(getattr(self.control, "audit_log", ()))[-audit_tail:]
        return {
            "node_id": node_id,
            "control": dict(self.control_info),
            "bound": bound,
            "audit_log": [
                {
                    "command": e.command,
                    "target_id": e.target_id,
                    "requested_by": e.requested_by,
                    "at": e.at,
                }
                for e in audit
            ],
        }

    def recent_events(self, limit: int = 200) -> list[dict]:
        with self._events_lock:
            return list(self.events[-limit:])


def _reason_data(reason: str) -> str | None:
    parts = (reason or "").split(":", 1)
    return parts[1] if len(parts) == 2 else None


def _serving_choice_key(entry: dict) -> tuple:
    """Sort key of `fleet()['served'][kind]`: lowest provider priority
    number, then lowest cost (compute_units, memory_mb), then config order."""
    priority = entry.get("priority")
    cost = entry.get("cost") or {}
    return (
        priority if priority is not None else float("inf"),
        float(cost.get("compute_units", 0.0)),
        float(cost.get("memory_mb", 0.0)),
        entry.get("_index", 0),
    )


def _jsonable_override(entry: dict) -> dict:
    out = dict(entry)
    if "exclude_providers" in out:
        out["exclude_providers"] = list(out["exclude_providers"])
    return out


def _supplement_reason(why: list[dict], role: str, priority_of=None) -> dict:
    """One `{reason, reason_token, reason_data, provider_id, node_id}` for a
    role: the first node of that role (in `why` order) with any reason. The
    best-ranked alternative's reason wins over the node's aggregate reason
    (see `StatusService.functions`). No node of that role → all None."""
    priority_of = priority_of or {}
    fallback: dict | None = None
    for entry in why:
        if entry["role"] != role:
            continue
        alternatives = [a for a in entry.get("alternatives", []) if a.get("reason")]
        if alternatives:
            # stable sort: provider priority number ascending, selector order otherwise
            best = sorted(alternatives, key=lambda a: priority_of.get(a["provider_id"], float("inf")))[0]
            return {
                "reason": best["reason"],
                "reason_token": best["reason_token"],
                "reason_data": best["reason_data"],
                "provider_id": best["provider_id"],
                "node_id": entry["node_id"],
            }
        if entry.get("reason") and fallback is None:
            fallback = {
                "reason": entry["reason"],
                "reason_token": entry["reason_token"],
                "reason_data": entry["reason_data"],
                "provider_id": None,
                "node_id": entry["node_id"],
            }
    return fallback or {"reason": None, "reason_token": None, "reason_data": None, "provider_id": None, "node_id": None}


def _selector_or_none(reg) -> dict | None:
    if reg is None:
        return None
    try:
        selector = node_selector_for(reg.compatibility)
    except ValueError as error:
        return {"error": str(error)}
    return selector or None


def _status_of(control, target_id: str) -> str | None:
    try:
        status = control.get_status(target_id)
    except Exception:
        return None
    return getattr(status, "value", str(status))


# --- HTTP layer ----------------------------------------------------------------


class StatusHandler(BaseHTTPRequestHandler):
    """Thin JSON front for `StatusService`. `service` and `ui_dir` are bound
    with `functools.partial` in `make_server`."""

    server_version = "status-ui/0.1"

    def __init__(self, *args, service: StatusService, ui_dir: Path, **kwargs) -> None:
        self.service = service
        self.ui_dir = ui_dir
        super().__init__(*args, **kwargs)

    # quiet by default; `--verbose` re-enables the access log
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        if getattr(self.server, "verbose", False):
            super().log_message(format, *args)

    # --- routing -----------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                self._send_file(self.ui_dir / "index.html", "text/html; charset=utf-8")
            elif url.path == "/api/config":
                self._send_json(self.service.describe())
            elif url.path == "/api/vocabulary":
                self._send_json(self.service.vocabulary())
            elif url.path == "/api/labels":
                self._send_json(self.service.labels())
            elif url.path == "/api/fleet":
                self._send_json(self.service.fleet())
            elif url.path == "/api/functions":
                self._send_json(self.service.functions())
            elif url.path == "/api/resolve":
                self._send_json(self.service.resolve(self._node_id(query)))
            elif url.path == "/api/placement":
                self._send_json(self.service.placement_state(self._node_id(query)))
            elif url.path == "/api/events":
                self._send_json({"events": self.service.recent_events()})
            else:
                self._send_json({"error": "not_found", "path": url.path}, HTTPStatus.NOT_FOUND)
        except UiConfigError as error:
            self._send_json({"error": str(error)}, self._status_for(error))
        except Exception as error:  # a review tool must show the failure, not die
            self._send_json({"error": f"{type(error).__name__}: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        try:
            body = self._read_json()
            if url.path == "/api/whatif":
                self._send_json(self.service.whatif(self._node_id(body), **self._overrides(body)))
            elif url.path == "/api/functions/whatif":
                self._send_json(self.service.whatif_functions(body.get("overrides") or {}))
            elif url.path == "/api/placement":
                node_id = self._node_id(body)
                actions = self.service.apply_placement(node_id, **self._overrides(body))
                self._send_json({"node_id": node_id, "actions": actions, "state": self.service.placement_state(node_id)})
            elif url.path == "/api/reset":
                self.service.reset()
                self._send_json({"ok": True, "control": self.service.control_info})
            else:
                self._send_json({"error": "not_found", "path": url.path}, HTTPStatus.NOT_FOUND)
        except UiConfigError as error:
            self._send_json({"error": str(error)}, self._status_for(error))
        except Exception as error:
            self._send_json({"error": f"{type(error).__name__}: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    # --- helpers -------------------------------------------------------------------
    @staticmethod
    def _status_for(error: UiConfigError) -> HTTPStatus:
        return HTTPStatus.NOT_FOUND if str(error).startswith("unknown_node:") else HTTPStatus.BAD_REQUEST

    @staticmethod
    def _node_id(source: dict) -> str:
        node_id = source.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise UiConfigError("node_id: required")
        return node_id

    @staticmethod
    def _overrides(body: dict) -> dict:
        overrides: dict = {}
        if body.get("tags") is not None:
            overrides["tags"] = body["tags"]
        if body.get("budget") is not None:
            overrides["budget"] = body["budget"]
        exclude = body.get("exclude_providers")
        if exclude is not None:
            if isinstance(exclude, str) or not isinstance(exclude, list):
                raise UiConfigError("exclude_providers: must be a list of provider_id strings")
            overrides["exclude_providers"] = tuple(str(p) for p in exclude)
        return overrides

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise UiConfigError(f"body: not valid JSON ({error})") from error
        if not isinstance(body, dict):
            raise UiConfigError("body: must be a JSON object")
        return body

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._send_json({"error": "ui_file_missing", "path": str(path)}, HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def make_server(
    service: StatusService,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    ui_dir: Path = UI_DIR,
    verbose: bool = False,
) -> ThreadingHTTPServer:
    """Bound but not yet serving. `port=0` picks a free port — read it back
    from `server.server_address[1]`."""
    handler = partial(StatusHandler, service=service, ui_dir=ui_dir)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.verbose = verbose  # type: ignore[attr-defined]
    return server


def server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/"


# --- CLI -------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capability 상태 패널 (검토용) — 로컬 stdlib HTTP 서버",
    )
    parser.add_argument("--config", required=True, help="config/status_ui*.json 경로")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="0이면 빈 포트를 고른다")
    parser.add_argument("--control", choices=("local", "k3s"), default="local")
    parser.add_argument("--namespace", default="default", help="--control k3s일 때 네임스페이스")
    parser.add_argument("--verbose", action="store_true", help="HTTP access log 출력")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_ui_config(args.config)
        service = StatusService(config, control_mode=args.control, namespace=args.namespace)
    except (UiConfigError, ValueError, OSError) as error:
        print(f"status_ui: {error}", file=sys.stderr)
        return 2

    server = make_server(service, host=args.host, port=args.port, verbose=args.verbose)
    control = service.control_info
    note = f" (요청 {control['requested']} → 실제 {control['active']}: {control['reason']})" if control.get("reason") else ""
    print(f"status_ui: {server_url(server)}  control={control['active']}{note}", flush=True)
    print(f"status_ui: config={config.path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
