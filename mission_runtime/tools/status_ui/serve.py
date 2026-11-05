"""Local review panel for capability resolution / placement (stdlib only).

implements: AI-C-05, AI-C-13, AI-C-18, AI-B-04, AI-B-06, AI-O-02 (review tooling)

This is a *review tool*, not the production UI — the production UI belongs
to the visualization team (capability·상태 UI 연동 설계 노트(비공개)
§3-4, AI-C-19). It exists so the project owner can look at what the
framework now computes without reading test output:

- P1 `ZoneApplication.resolve()` per node, with every considered candidate
  and why it lost (`CapabilityResolution.alternatives`),
- P2 the controlled reason vocabulary (`STATE_CHANGE_REASONS`),
- P3 providers loaded from a JSON manifest (`registry/manifest.py`),
- P4 placement actions / `nodeSelector` (`runtime/placement.py`),
- the *residency* axis: for one registered device, which capability kinds
  were chosen to live **on that device** and why — `runtime/residency.py`
  over a `DevicePurposeProfile` plus the device's link characteristics,
  with a what-if for "the link degrades" (AI-N-03, AI-C-15, AI-B-10),
- the *device* axis: registering a real terminal by address + credential,
  deploying exactly what the residency decision chose onto it, and reading
  liveness/readiness/board-state back — all through the `ControlProvider`
  boundary (`providers/device_control.py`), so nothing here knows SSH
  (AI-C-04, AI-B-03, AI-B-05),
- the *function* axis: which user-level functions are possible right now
  across the whole fleet, what resources each needs per tier, and — for
  an unavailable one — the minimal supplement per tier. A device is just
  one provider; the page is organised by function, resource and tier
  (role), not by node name. Function availability is
  `TaskIntent.evaluate_availability()` (contracts/capability_contract.py,
  AI-C-18) over the set of kinds some node actually serves,
- the 2nd-round additions (장비 bring-up 계획 노트(비공개)
  §3): per function the tiers that can carry it *alone* (`solo_roles`) or
  *together* (`combo_roles`), a precomputed failure `trace` (function →
  kind → tier reason → best candidate → missing tags), per-node *freshness*
  from `RuntimeInstance.health_checked_at` (hw_smoke reports and in-memory
  probes — never an invented timestamp), and an in-memory
  `ExecutionPlanLog` (`runtime/execution_plan.py`) so one placement request
  is one `plan_id` with an opaque `requester` slot.

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
import os
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

# `tools/` is not a package; when run as a script the framework package must
# already be importable (pip install -e . in mission_runtime/).
_FRAMEWORK_DIR = Path(__file__).resolve().parents[2]
if str(_FRAMEWORK_DIR) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK_DIR))

from mission_runtime.contracts.capability import CapabilityRequirement, CapabilityState  # noqa: E402
from mission_runtime.contracts.capability_contract import RuntimeInstance, TaskIntent  # noqa: E402
from mission_runtime.contracts.data_dictionary import (  # noqa: E402
    CAPABILITY_RESIDENCIES,
    HOST_PROBE_ID,
    HOST_PROBE_STATUS,
    LINK_POSTURES,
    MEASUREMENT_SOURCE,
    STATE_CHANGE_REASONS,
    state_change_reason_token,
)
from mission_runtime.contracts.profile import (  # noqa: E402
    OUTAGE_BEHAVIORS,
    DeploymentProfile,
    DevicePurposeProfile,
    LinkProfile,
    ResourceBudget,
)
from mission_runtime.contracts.profile_loader import (  # noqa: E402
    link_profile_from_dict,
    load_device_purposes,
    profile_from_dict,
)
from mission_runtime.runtime.residency import (  # noqa: E402
    LINK_POSTURE_REASONS,
    RESIDENCY_REASONS,
    RESIDENCY_VIOLATIONS,
    decide_residency,
)
from mission_runtime.execution.control import LocalControlSupervisor  # noqa: E402
from mission_runtime.providers.k3s import K3sControlProvider  # noqa: E402
from mission_runtime.registry.capability_registry import CapabilityRegistry  # noqa: E402
#: 후보별 거절 사유의 어휘는 선택기가 소유한다 — 문자열을 박아 두면 그쪽이
#: 바뀔 때 이 파일이 조용히 틀린다(AI-C-01).
from mission_runtime.selection.selector import (  # noqa: E402
    REASON_OVER_BUDGET as SELECTOR_REASON_OVER_BUDGET,
)
from mission_runtime.registry.manifest import (  # noqa: E402
    ProviderManifest,
    load_provider_manifest,
    register_all,
    registrations_from_dict,
)
from mission_runtime.runtime.application import (  # noqa: E402
    CapabilityResolution,
    CapabilitySpec,
    ZoneApplication,
)
from mission_runtime.runtime.placement import PlacementReconciler, node_selector_for  # noqa: E402
from mission_runtime.providers.device_control import (  # noqa: E402
    DeviceChannelError,
    open_channel,
    supported_access_methods,
)
from mission_runtime.providers.link_probe import (  # noqa: E402
    link_profile_from,
    probe_icmp,
)
from mission_runtime.providers.ondevice_bootstrap import bootstrap_key_auth  # noqa: E402
from mission_runtime.registry.device_registry import (  # noqa: E402
    AUTH_KEY,
    AUTH_PASSWORD,
    CredentialStore,
    DeviceCredential,
    DeviceRegistration,
    DeviceRegistry,
    DeviceRegistryError,
)
from mission_runtime.runtime.device_deployment import (  # noqa: E402
    DEFAULT_UNIT_SOURCE,
    DeviceDeployment,
    plan_device_units,
)
from mission_runtime.runtime.execution_plan import (  # noqa: E402
    ExecutionPlan,
    ExecutionPlanLog,
    Requester,
    build_plan,
)
# 종합상황정보 Dashboard 의 구역 계약. 판정은 전부 이 모듈들이 이미 하고 있고,
# 이 파일은 **선언 데이터를 그 자료형으로 옮겨 한 스냅샷으로 내보내는 일만** 한다 —
# 같은 사실을 여기서 다시 판정하면 두 화면이 서로 다른 답을 말한다(AI-O-06).
from mission_runtime.execution.external_request import (  # noqa: E402
    ExternalRequest,
    ExternalRequestLog,
    FinalVerdict,
    RequestReason,
    RequestStage,
    StageTransition,
)
from mission_runtime.execution.task_graph import (  # noqa: E402
    GraphInvalid,
    NodeState,
    ReferenceEdge,
    TaskGraph,
    TaskNode,
)
from mission_runtime.integration.status_wire import (  # noqa: E402
    measurement_to_wire,
    status_snapshot_payload,
)
from mission_runtime.observability.dashboard_view import (  # noqa: E402
    ConditionItem,
    DashboardSnapshot,
    EventKind,
    EventRecord,
    MissionSummary,
    NodeVerdict,
    Region,
    Severity,
    SourceState,
    severity_from_wire,
)
from mission_runtime.observability.layered_metrics import (  # noqa: E402
    SOURCE_DECLARED,
    AcceleratorInstance,
    BoardResources,
    Direction,
    Indicator,
    LayeredResourceView,
    Measurement,
    ServiceRuntime,
    TargetBaseline,
    UnitMismatch,
)
# L1 계층의 실측. 선언된 가속기 개체 **같은 자리에** 이 기계에서 읽은 값을 입힌다 —
# 목록을 늘리거나 줄이지 않고, 못 읽은 칸은 0 이 아니라 미측정으로 남는다(AI-O-05).
from mission_runtime.observability.host_resources import (  # noqa: E402
    HostReadout,
    HostResourceReader,
    resolve_probes,
    undeclared_probes,
    with_host_measurements,
)
# 임계 감시. [E] 의 경고 사건과 [G] 의 자원 조건이 **한 판정**에서 나온다 —
# 따로 구현하면 어긋난다(기능정의서 §4.4·§4.7).
from mission_runtime.observability.resource_watch import (  # noqa: E402
    ResourceWatch,
    WatchTarget,
    WatchTargetInvalid,
    threshold_events,
    with_measured_resource_conditions,
)

UI_DIR = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_LABELS_FILENAME = "status_ui.labels.json"
# CPU 사용률 표본 구간. 간격 없이 읽으면 psutil 규약상 **첫 호출이 의미 없는 0.0** 이고
# 그 0 을 실측으로 내보내면 유휴와 "아직 못 쟀다"가 같아진다(기능정의서 §4.4). 조회
# 한 번에 이만큼만 머문다 — 관측이 응답을 세우지 않는 선이다(AI-O-01).
HOST_CPU_SAMPLE_S = 0.1
# Placement commands the page can show; the labels file must name each.
PLACEMENT_COMMANDS = ("start", "stop", "in_process")
# Device-axis actions the page can ask for. Everything here is expressible as
# one control-provider call or one local measurement; nothing re-judges.
DEVICE_COMMANDS = ("deploy", "stop", "rollback", "refresh", "probe_link", "remove")
# Where a generated control keypair goes when the config names none. Owner-only
# and outside the repo — a key inside a work tree eventually gets committed.
DEFAULT_CONTROL_KEY = "~/.ssh/id_pf_control"
#: 쓸 수 있는 상태의 뿌리를 가리키는 환경변수. `tools/fms_console/overlay.py` 의
#: `STATE_ROOT_ENV` 와 **같은 이름**이다 — 자리를 옮기는 변수가 둘이면 시험·배포가
#: 한쪽만 옮기고 나머지는 옛 자리에 계속 쓴다.
STATE_ROOT_ENV = "MISSION_RUNTIME_STATE"
#: unit 패킹 작업장의 이름. 자리는 바뀌어도 이름은 고정이라 사람이 찾을 수 있다.
UNIT_STAGING_DIR_NAME = "unit_staging"


def default_unit_staging_root() -> Path:
    """unit 을 패킹할 작업장의 기본 자리. **호출할 때** 정한다.

    `$MISSION_RUNTIME_STATE` → `$XDG_STATE_HOME/mission_runtime` →
    `~/.local/state/mission_runtime` 순서이고 그 아래 `unit_staging/` 이다
    (`tools/fms_console/overlay.py::state_root` 와 같은 규약).

    왜 `tempfile.gettempdir()/pf_status_ui_units` 를 쓰지 않는가: 그것은 호스트에
    **하나뿐인 고정 이름**이라 그 기계의 모든 실행이 같은 칸을 쓴다. 패킹은
    `runtime/device_deployment.py::build_unit_source` 가 대상 디렉터리를 `rmtree`
    한 뒤 복사하는 방식이라, 두 번째 실행이 첫 번째의 작업장을 **지우는** 경쟁이
    된다 — 실측으로 두 프로세스가 같은 자리를 쓰면 240 회 중 47 회가
    `FileNotFoundError` · `Directory not empty` 로 깨졌고, 깨진 쪽은 자기 잘못이
    아닌 실패를 본다. 자리를 상태 디렉터리로 옮기면 배포·시험이 **환경변수 하나로**
    그 자리를 격리할 수 있다(`tests/conftest.py::_isolated_state_root` 가 쓰는 길).

    자리를 옮기는 것이 같은 사용자의 동시 실행까지 안전하게 만들지는 않는다 —
    그것은 `build_unit_source` 가 임시 자리에 짓고 원자적으로 바꿔 끼워야 하는
    별개의 일이다. 여기서 끊는 것은 **호스트 공용 고정 자리**라는 의존이다.
    """
    override = os.environ.get(STATE_ROOT_ENV)
    if override:
        return Path(override) / UNIT_STAGING_DIR_NAME
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "mission_runtime" / UNIT_STAGING_DIR_NAME
    return Path.home() / ".local" / "state" / "mission_runtime" / UNIT_STAGING_DIR_NAME


# What-if override key that applies to every node (per-node keys merge on top).
OVERRIDE_ALL = "*"
# function_id recorded on a plan when the request named no function — a
# placement is per node and serves every function at once.
PLAN_ALL_FUNCTIONS = "*"
# How long a passed hw_smoke probe at each level counts as fresh. Mirrors
# `tools/hw_smoke/smoke.py::LEVEL_TTL_S` (a test keeps the two equal); copied
# rather than imported so the panel still loads when the harness is absent.
HW_SMOKE_LEVEL_TTL_S: dict[int, float] = {1: 60.0, 2: 300.0, 3: 600.0}
# TTL of an in-memory device probe (link probe / state read) — a ping-class
# observation, same as hw_smoke L1.
DEVICE_PROBE_TTL_S = 60.0
# Freshness sources, so the page can say *where* "last verified" came from.
FRESHNESS_HW_SMOKE = "hw_smoke"
FRESHNESS_DEVICE_PROBE = "device_probe"
FRESHNESS_INJECTED = "injected"

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
    (capability·상태 UI 연동 설계 노트(비공개) §3-2). Consumers may
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
    # What this registered device is *for* — a purpose_id from the device
    # purposes file. `None` means the node declares no purpose and simply has
    # no residency view; every other panel behaves exactly as before, because
    # a device without a declared purpose must not break the page (AI-C-05).
    purpose: str | None = None
    # This device's own link characteristics, overriding whatever the purpose
    # declares. Measured or declared — the framework never assumes which
    # (AI-N-03).
    link: LinkProfile | None = None
    # `"verified": false` in the config marks a node whose model/options the
    # source document still lists as [확인] (2026-09-28 decision: one flag, not
    # a status vocabulary). It changes no resolution — only the "미검증 장비
    # 포함" note on a function card. Default True: an ordinary node needs no
    # extra field.
    verified: bool = True

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "role": self.role,
            "tags": list(self.tags),
            "budget": _budget_to_dict(self.budget),
            "purpose": self.purpose,
            "link": _link_to_dict(self.link) if self.link is not None else None,
            "verified": self.verified,
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
    device_purposes_path: Path | None = None
    # The device axis is entirely optional. Without these the page behaves
    # exactly as before and simply has no device panel — a review config that
    # names no hardware must still work (AI-C-05).
    devices_path: Path | None = None
    credentials_path: Path | None = None
    control_key_path: str = DEFAULT_CONTROL_KEY
    staging_dir: Path | None = None
    # Directory of `tools/hw_smoke` JSON reports (relative to the config).
    # Optional; a missing directory is simply "nothing verified yet".
    hw_smoke_reports: Path | None = None
    purposes: dict = field(default_factory=dict)
    # 종합상황정보 Dashboard 구역 B~I 의 선언(L1 가속기 개체·L2 서비스·작업 그래프·
    # 판정·외부 요청·소스). 전부 선택이다 — 선언이 없는 배치에서는 해당 구역만
    # 미수신으로 나오고 다른 구역은 그대로 동작한다(문서 §3 요구사항 5, AI-C-05).
    dashboard: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict, repr=False)

    def purpose_for(self, node_id: str) -> DevicePurposeProfile | None:
        """The purpose profile of one registered device, or `None` when the
        node declares none / the id is unknown. Never raises: a node without a
        purpose is a normal configuration, not an error."""
        node = self.node(node_id)
        if node.purpose is None:
            return None
        return self.purposes.get(node.purpose)

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

    purposes: dict = {}
    purposes_path: Path | None = None
    def _optional_path(key: str) -> Path | None:
        ref = raw.get(key)
        if ref is None:
            return None
        if not isinstance(ref, str) or not ref:
            raise UiConfigError(f"{key}: must be a non-empty path string")
        return (path.parent / ref).resolve()

    devices_path = _optional_path("devices")
    credentials_path = _optional_path("device_credentials")
    staging_dir = _optional_path("unit_staging_dir")
    hw_smoke_reports = _optional_path("hw_smoke_reports")
    control_key = raw.get("control_key", DEFAULT_CONTROL_KEY)
    if not isinstance(control_key, str) or not control_key:
        raise UiConfigError("control_key: must be a non-empty path string")

    purposes_ref = raw.get("device_purposes")
    if purposes_ref is not None:
        if not isinstance(purposes_ref, str) or not purposes_ref:
            raise UiConfigError("device_purposes: must be a non-empty path string")
        purposes_path = (path.parent / purposes_ref).resolve()
        try:
            purposes = load_device_purposes(purposes_path)
        except (ValueError, OSError) as error:
            raise UiConfigError(f"device_purposes: {error}") from error
    for node in nodes:
        if node.purpose is not None and node.purpose not in purposes:
            # A purpose id that resolves to nothing is a typo, not a degraded
            # mode — surface it at load time (같은 이유로 profile_loader가
            # 모르는 키를 거부한다).
            raise UiConfigError(f"nodes.{node.node_id}.purpose: unknown purpose_id:{node.purpose}")

    functions: tuple[FunctionConfig, ...] = ()
    if raw.get("functions") is not None:
        functions = tuple(_function_from(i, entry) for i, entry in enumerate(_list(raw, "functions")))
        function_ids = [f.function_id for f in functions]
        if len(set(function_ids)) != len(function_ids):
            raise UiConfigError("functions: duplicate function_id")

    dashboard = raw.get("dashboard")
    if dashboard is not None and not isinstance(dashboard, dict):
        raise UiConfigError("dashboard: must be a JSON object")
    # 조립은 로드 시점에 한 번 검증한다 — 잘못된 선언이 화면 요청 때까지 숨어
    # 있으면 운영 중에 500 으로 터진다.
    declared_snapshot = build_dashboard_snapshot(dashboard or {})
    declared_watch = build_resource_watch(dashboard or {})
    # 감시 선언도 로드 시점에 맞춰 본다. 단위가 어긋난 기준선은 그래프 위 실제 값
    # 위치를 정할 수 없고(§4.5), 요청 시점에 터지면 상태 조회가 500 이 된다.
    declared_ids = {a.instance_id for a in declared_snapshot.resources.accelerators}
    for target in declared_watch.targets:
        if target.accelerator_id is not None and target.accelerator_id not in declared_ids:
            raise UiConfigError(
                f"dashboard.watch: {target.item_id} watches unknown accelerator "
                f"{target.accelerator_id!r}"
            )
    try:
        declared_watch.evaluate(declared_snapshot.resources)
    except UnitMismatch as error:
        raise UiConfigError(f"dashboard.watch: {error}") from error

    return UiConfig(
        path=path,
        providers_manifest=manifest_path,
        profile=profile,
        specs=specs,
        nodes=nodes,
        functions=functions,
        labels_path=labels_path,
        device_purposes_path=purposes_path,
        purposes=purposes,
        devices_path=devices_path,
        credentials_path=credentials_path,
        control_key_path=control_key,
        staging_dir=staging_dir,
        hw_smoke_reports=hw_smoke_reports,
        dashboard=dashboard or {},
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
    purpose = entry.get("purpose")
    if purpose is not None and (not isinstance(purpose, str) or not purpose):
        raise UiConfigError(f"{where}.purpose: must be a non-empty string")
    link = entry.get("link")
    if link is not None:
        try:
            link = link_profile_from_dict(link)
        except ValueError as error:
            raise UiConfigError(f"{where}.link: {error}") from error
    verified = entry.get("verified", True)
    if not isinstance(verified, bool):
        raise UiConfigError(f"{where}.verified: must be a boolean")
    return NodeConfig(
        node_id=entry["node_id"],
        label=str(entry.get("label", entry["node_id"])),
        tags=_str_tuple(where, "tags", entry.get("tags", ())),
        budget=_budget_from(where, entry.get("budget", {})),
        role=role,
        purpose=purpose,
        link=link,
        verified=verified,
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


def _link_to_dict(link: LinkProfile) -> dict:
    """A link profile as JSON. Every measurement may legitimately be absent
    (AI-N-03), so `None` is a value here, never a missing key."""
    return {
        "source": link.source,
        "quality": link.quality,
        "stability": link.stability,
        "declared_posture": link.declared_posture,
        "samples": link.samples,
        "observed_at": link.observed_at,
    }


def _budget_to_dict(budget: ResourceBudget) -> dict:
    return {
        "compute_units": budget.compute_units,
        "memory_mb": budget.memory_mb,
        "max_latency_ms": budget.max_latency_ms,
    }


# --- 종합상황정보 Dashboard 구역 B~I 의 선언 → 계약 자료형 ----------------------
#
# implements: AI-O-05 (계층별 자원·서비스 지표 관측), AI-O-06 (통합 운영 상태 뷰),
#             AI-B-12 (작업 그래프 실행 상태 관리), AI-B-13 (외부 개발 요청)
#
# 기능정의서(`internal/docs-dev/20260928-종합상황정보_Dashboard_기능정의서_2.docx`)
# §3 요구사항 2: "서비스–가속기 배치 정보는 런타임에 수신되어야 하며, 화면에 고정
# 값으로 기술되어서는 안 된다. 가속기가 추가·교체되거나 서비스 배치가 변경되어도
# 화면 구조 변경 없이 반영되어야 한다." 그래서 가속기·서비스·노드는 **등록 데이터**로
# 받고 이 파일에는 벤더 열거형도 도메인 분기도 두지 않는다(절대 준수 원칙 #1·#3).
#
# 판정은 여기서 하지 않는다. 미측정/충족/미달 3값은 `TargetBaseline.evaluate`,
# 유휴 가속기는 `LayeredResourceView.idle_accelerators`, 구역 가용성은
# `DashboardSnapshot.region_state` 가 이미 낸다 — 이 블록은 옮기기만 한다.

#: 선언에서 측정값이 빠진 자리의 기본 단위. 단위를 모르면 목표 기준선을 같은 축에
#: 올릴 수 없어 `UnitMismatch` 가 되므로 자리마다 단위를 고정해 둔다.
DASHBOARD_UNITS: dict[str, str] = {
    "utilization": "ratio",
    "temperature": "celsius",
    "memory_utilization": "ratio",
    "power": "watt",
}


def _dash_obj(where: str, raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise UiConfigError(f"{where}: must be a JSON object")
    return raw


def _dash_text(where: str, raw: Any, *, required: bool = False) -> str | None:
    if raw is None:
        if required:
            raise UiConfigError(f"{where}: required")
        return None
    if not isinstance(raw, str) or not raw:
        raise UiConfigError(f"{where}: must be a non-empty string")
    return raw


def _dash_time(where: str, raw: Any) -> float | None:
    """epoch 초. 없으면 None 이고 **지금 시각으로 메우지 않는다** — 문서 §5 의
    "마지막 수신 시각과 단절 사실을 명시"는 시각을 지어내면 지킬 수 없다."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise UiConfigError(f"{where}: must be epoch seconds (number)")
    return float(raw)


def _dash_measurement(where: str, raw: Any, unit: str) -> Measurement:
    """측정 1건.

    문서 §4.4: "서비스가 대기 상태여서 지표가 산출되지 않는 경우, **0이 아니라
    측정 없음**으로 표시해야 한다." 그래서 선언이 없거나 `value` 가 null 이면
    `Measurement.not_measured` 이고 0 을 채우지 않는다.

    선언에서 온 숫자는 `source=declared` 로 표시한다 — 이 칸에 나중에 실측이 들어올
    수 있고, 소비자가 둘을 **추측 없이** 가를 수 있어야 한다(AI-O-05). 값이 없는
    자리에는 출처를 적지 않는다: 아무도 채우지 않았다는 것이 사실이다.
    """
    if raw is None:
        return Measurement.not_measured(unit)
    if isinstance(raw, bool):
        raise UiConfigError(f"{where}: must be a number, an object or null")
    if isinstance(raw, (int, float)):
        return Measurement(float(raw), unit, source=SOURCE_DECLARED)
    body = _dash_obj(where, raw)
    declared = body.get("unit", unit)
    if not isinstance(declared, str) or not declared:
        raise UiConfigError(f"{where}.unit: must be a non-empty string")
    value = body.get("value")
    if value is None:
        return Measurement.not_measured(declared)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UiConfigError(f"{where}.value: must be a number or null")
    return Measurement(float(value), declared, at=_dash_time(f"{where}.at", body.get("at")),
                       source=SOURCE_DECLARED)


def _dash_trend(where: str, raw: Any, unit: str) -> tuple[Measurement, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise UiConfigError(f"{where}: must be a JSON array")
    return tuple(
        _dash_measurement(f"{where}[{i}]", entry, unit) for i, entry in enumerate(raw)
    )


def _dash_target(where: str, raw: Any) -> TargetBaseline | None:
    """목표 기준선. 없는 지표도 정상이다 — 모든 지표에 목표가 있지는 않다."""
    if raw is None:
        return None
    body = _dash_obj(where, raw)
    value = body.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UiConfigError(f"{where}.value: must be a number")
    unit = _dash_text(f"{where}.unit", body.get("unit"), required=True)
    raw_dir = _dash_text(f"{where}.direction", body.get("direction"), required=True)
    try:
        direction = Direction(str(raw_dir).upper())
    except ValueError as error:
        allowed = [d.value for d in Direction]
        raise UiConfigError(f"{where}.direction: must be one of {allowed}") from error
    return TargetBaseline(value=float(value), direction=direction, unit=unit)


def _dash_indicator(where: str, raw: Any, *, service_id: str | None,
                    accelerator_id: str | None) -> Indicator:
    body = _dash_obj(where, raw)
    name = _dash_text(f"{where}.name", body.get("name"), required=True)
    measurement = _dash_measurement(f"{where}.measurement", body.get("measurement"),
                                    _dash_text(f"{where}.unit", body.get("unit")) or "1")
    return Indicator(
        name=str(name),
        measurement=measurement,
        service_id=service_id,
        accelerator_id=accelerator_id,
        target=_dash_target(f"{where}.target", body.get("target")),
        trend=_dash_trend(f"{where}.trend", body.get("trend"), measurement.unit),
    )


def _dash_accelerator(index: int, raw: Any) -> AcceleratorInstance:
    """Layer 1 가속기 **개체** 1개.

    문서 §1.2·§4.4 는 같은 종류가 여러 개인 구성(외장 NPU ×3)을 전제한다. 그래서
    종류(`kind`)가 아니라 `instance_id` 가 개체를 가른다 — 종류로만 식별하면 동종
    가속기 사이의 부하 편중을 볼 수 없다(AI-O-05).

    선택 항목 `host_probe` 는 **이 개체를 어느 계측 지점이 재는가**를 선언한다. 코드가
    종류·벤더 라벨로 추측하지 않는다(원칙 #1). 지목이 없는 개체는 선언값으로 남고,
    실측이 되든 안 되든 **목록에서 빠지지 않는다**(§4.1 완전성).
    """
    where = f"dashboard.accelerators[{index}]"
    body = _dash_obj(where, raw)
    _dash_text(f"{where}.host_probe", body.get("host_probe"))   # 형식만 확인
    return AcceleratorInstance(
        instance_id=str(_dash_text(f"{where}.instance_id", body.get("instance_id"), required=True)),
        kind=str(_dash_text(f"{where}.kind", body.get("kind"), required=True)),
        attachment=_dash_text(f"{where}.attachment", body.get("attachment")),
        vendor_label=_dash_text(f"{where}.vendor_label", body.get("vendor_label")),
        utilization=_dash_measurement(f"{where}.utilization", body.get("utilization"),
                                      DASHBOARD_UNITS["utilization"]),
        temperature=_dash_measurement(f"{where}.temperature", body.get("temperature"),
                                      DASHBOARD_UNITS["temperature"]),
    )


def _dash_service(index: int, raw: Any) -> ServiceRuntime:
    """Layer 2 서비스 1개. 배치 가속기를 **반드시** 함께 들고 있다(문서 §4.4)."""
    where = f"dashboard.services[{index}]"
    body = _dash_obj(where, raw)
    accelerator_id = _dash_text(f"{where}.accelerator_id", body.get("accelerator_id"))
    raw_indicators = body.get("indicators") or []
    if not isinstance(raw_indicators, list):
        raise UiConfigError(f"{where}.indicators: must be a JSON array")
    return ServiceRuntime(
        service_id=str(_dash_text(f"{where}.service_id", body.get("service_id"), required=True)),
        accelerator_id=accelerator_id,
        role=_dash_text(f"{where}.role", body.get("role")),
        model_name=_dash_text(f"{where}.model", body.get("model")),
        model_version=_dash_text(f"{where}.model_version", body.get("model_version")),
        indicators=tuple(
            _dash_indicator(f"{where}.indicators[{i}]", entry,
                            service_id=str(body.get("service_id")),
                            accelerator_id=accelerator_id)
            for i, entry in enumerate(raw_indicators)
        ),
    )


def _dash_board(raw: Any) -> BoardResources:
    if raw is None:
        return BoardResources()
    body = _dash_obj("dashboard.board", raw)
    _dash_text("dashboard.board.host_probe", body.get("host_probe"))   # 형식만 확인
    power = _dash_measurement("dashboard.board.power", body.get("power"),
                              DASHBOARD_UNITS["power"])
    return BoardResources(
        memory_utilization=_dash_measurement(
            "dashboard.board.memory_utilization", body.get("memory_utilization"),
            DASHBOARD_UNITS["memory_utilization"]),
        power=power,
        power_trend=_dash_trend("dashboard.board.power_trend", body.get("power_trend"),
                                power.unit),
    )


def _dash_node(index: int, raw: Any) -> TaskNode:
    """[C] 작업 노드 1개. 상태는 문서 §4.2 의 6종만 받는다.

    AI-B-12: 작업 그래프의 생성은 외부(가시화)의 계약이고 우리는 **소비**한다.
    그래서 생성 주체의 원본 상태 문자열을 `source_status` 로 함께 보존한다 — 표시
    어휘로 환산한 뒤에도 원본이 남아야 환산이 손실이 되지 않는다.
    """
    where = f"dashboard.task_nodes[{index}]"
    body = _dash_obj(where, raw)
    raw_state = body.get("state", NodeState.PENDING.value)
    try:
        state = NodeState(str(raw_state).upper())
    except ValueError as error:
        allowed = [s.value for s in NodeState]
        raise UiConfigError(f"{where}.state: must be one of {allowed}") from error
    progress = body.get("progress_ratio")
    if progress is not None and (isinstance(progress, bool) or not isinstance(progress, (int, float))):
        raise UiConfigError(f"{where}.progress_ratio: must be a number or null")
    attempt = body.get("attempt", 1)
    if isinstance(attempt, bool) or not isinstance(attempt, int):
        raise UiConfigError(f"{where}.attempt: must be an integer")
    return TaskNode(
        node_id=str(_dash_text(f"{where}.node_id", body.get("node_id"), required=True)),
        title=str(_dash_text(f"{where}.title", body.get("title")) or ""),
        state=state,
        service_id=_dash_text(f"{where}.service_id", body.get("service_id")),
        accelerator_id=_dash_text(f"{where}.accelerator_id", body.get("accelerator_id")),
        state_changed_at=_dash_time(f"{where}.state_changed_at", body.get("state_changed_at")),
        started_at=_dash_time(f"{where}.started_at", body.get("started_at")),
        estimated_completion_at=_dash_time(f"{where}.estimated_completion_at",
                                           body.get("estimated_completion_at")),
        progress_ratio=None if progress is None else float(progress),
        input_command=_dash_text(f"{where}.input_command", body.get("input_command")),
        order_after=_str_tuple(where, "order_after", body.get("order_after") or []),
        depends_on=_str_tuple(where, "depends_on", body.get("depends_on") or []),
        parallel_group=_dash_text(f"{where}.parallel_group", body.get("parallel_group")),
        attempt=attempt,
        origin_node_id=_dash_text(f"{where}.origin_node_id", body.get("origin_node_id")),
        external_request_id=_dash_text(f"{where}.external_request_id",
                                       body.get("external_request_id")),
        source_status=_dash_text(f"{where}.source_status", body.get("source_status")),
        target_device_id=_dash_text(f"{where}.target_device_id", body.get("target_device_id")),
        node_kind=_dash_text(f"{where}.node_kind", body.get("node_kind")),
    )


def _dash_edge(index: int, raw: Any) -> ReferenceEdge:
    where = f"dashboard.reference_edges[{index}]"
    body = _dash_obj(where, raw)
    return ReferenceEdge(
        from_node_id=str(_dash_text(f"{where}.from", body.get("from"), required=True)),
        to_node_id=str(_dash_text(f"{where}.to", body.get("to"), required=True)),
        kind=str(_dash_text(f"{where}.kind", body.get("kind"), required=True)),
        when=_dash_text(f"{where}.when", body.get("when")),
    )


def _dash_conditions(where: str, raw: Any) -> tuple[ConditionItem, ...]:
    """[G] 조건 목록. 항목 단위로 들고 오고 집계는 만들지 않는다.

    문서 §4.7: "각 조건은 상태가 개별 항목 단위로 표시되어야 하며, 요약 수치만
    제공해서는 안 된다." 판정할 근거가 없으면 `satisfied` 가 None 이고 그것이
    "미확인"이다 — False(미충족)와 같은 칸에 담지 않는다.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise UiConfigError(f"{where}: must be a JSON array")
    items: list[ConditionItem] = []
    for i, entry in enumerate(raw):
        body = _dash_obj(f"{where}[{i}]", entry)
        satisfied = body.get("satisfied")
        if satisfied is not None and not isinstance(satisfied, bool):
            raise UiConfigError(f"{where}[{i}].satisfied: must be true, false or null")
        items.append(ConditionItem(
            item_id=str(_dash_text(f"{where}[{i}].item_id", body.get("item_id"), required=True)),
            satisfied=satisfied,
            reason_token=_dash_text(f"{where}[{i}].reason_token", body.get("reason_token")),
        ))
    return tuple(items)


def _dash_verdict(index: int, raw: Any) -> NodeVerdict:
    where = f"dashboard.verdicts[{index}]"
    body = _dash_obj(where, raw)
    return NodeVerdict(
        node_id=str(_dash_text(f"{where}.node_id", body.get("node_id"), required=True)),
        completion=_dash_conditions(f"{where}.completion", body.get("completion")),
        failure=_dash_conditions(f"{where}.failure", body.get("failure")),
        resource=_dash_conditions(f"{where}.resource", body.get("resource")),
        escalated_request_id=_dash_text(f"{where}.escalated_request_id",
                                        body.get("escalated_request_id")),
    )


def _dash_event(where: str, raw: Any) -> EventRecord:
    body = _dash_obj(where, raw)
    raw_severity = str(body.get("severity", Severity.INFO.value))
    try:
        severity = Severity(raw_severity.upper())
    except ValueError as error:
        allowed = [s.value for s in Severity]
        raise UiConfigError(f"{where}.severity: must be one of {allowed}") from error
    try:
        kind = EventKind(str(body.get("kind", EventKind.EXECUTION.value)).upper())
    except ValueError as error:
        allowed = [k.value for k in EventKind]
        raise UiConfigError(f"{where}.kind: must be one of {allowed}") from error
    attempt = body.get("attempt")
    if attempt is not None and (isinstance(attempt, bool) or not isinstance(attempt, int)):
        raise UiConfigError(f"{where}.attempt: must be an integer or null")
    return EventRecord(
        at=_dash_time(f"{where}.at", body.get("at")),
        severity=severity,
        kind=kind,
        message=str(body.get("message") or ""),
        node_id=_dash_text(f"{where}.node_id", body.get("node_id")),
        attempt=attempt,
        external_request_id=_dash_text(f"{where}.external_request_id",
                                       body.get("external_request_id")),
    )


def _dash_request(index: int, raw: Any) -> ExternalRequest:
    """[I] 외부 기능 요청 1건 (문서 §4.9, AI-B-13).

    요청 식별자의 발급 주체는 외부에 있으므로(AI-B-13) 선언에 없으면 지어내지 않고
    거부한다. 3단계(서버 처리)에 담당자·빌드 상태 같은 칸이 없는 것은 누락이 아니라
    요구다 — "서버 내부 프로세스는 가시화하지 않는다".
    """
    where = f"dashboard.external_requests[{index}]"
    body = _dash_obj(where, raw)
    try:
        reason = RequestReason(str(body.get("reason", "")).upper())
    except ValueError as error:
        allowed = [r.value for r in RequestReason]
        raise UiConfigError(f"{where}.reason: must be one of {allowed}") from error
    try:
        verdict = FinalVerdict(str(body.get("verdict", FinalVerdict.PENDING.value)).upper())
    except ValueError as error:
        allowed = [v.value for v in FinalVerdict]
        raise UiConfigError(f"{where}.verdict: must be one of {allowed}") from error
    raw_stages = body.get("stages") or []
    if not isinstance(raw_stages, list):
        raise UiConfigError(f"{where}.stages: must be a JSON array")
    transitions: list[StageTransition] = []
    for i, entry in enumerate(raw_stages):
        stage_body = _dash_obj(f"{where}.stages[{i}]", entry)
        try:
            stage = RequestStage(str(stage_body.get("stage", "")).upper())
        except ValueError as error:
            allowed = [s.value for s in RequestStage]
            raise UiConfigError(f"{where}.stages[{i}].stage: must be one of {allowed}") from error
        transitions.append(StageTransition(
            stage=stage, at=_dash_time(f"{where}.stages[{i}].at", stage_body.get("at"))))
    count = body.get("re_execution_count", 0)
    if isinstance(count, bool) or not isinstance(count, int):
        raise UiConfigError(f"{where}.re_execution_count: must be an integer")
    return ExternalRequest(
        request_id=str(_dash_text(f"{where}.request_id", body.get("request_id"), required=True)),
        reason=reason,
        reason_detail=str(body.get("reason_detail") or ""),
        origin_node_id=str(_dash_text(f"{where}.origin_node_id",
                                      body.get("origin_node_id"), required=True)),
        requested_at=_dash_time(f"{where}.requested_at", body.get("requested_at")),
        transitions=tuple(transitions),
        deployment_version=_dash_text(f"{where}.deployment_version",
                                      body.get("deployment_version")),
        re_execution_count=count,
        re_executed_nodes=_str_tuple(where, "re_executed_nodes",
                                     body.get("re_executed_nodes") or []),
        verdict=verdict,
        re_request_of=_dash_text(f"{where}.re_request_of", body.get("re_request_of")),
    )


def _dash_source(index: int, raw: Any) -> SourceState:
    """문서 §3 의 소스 1개와 그것이 먹이는 구역.

    `last_received_at` 가 없으면 **한 번도 받은 적이 없다**는 뜻이다. 문서 §5 는
    "한 번도 수신하지 않은 상태와 수신했으나 오래된 상태를 구분"하라고 요구하므로
    시각을 지어내 채우지 않는다.
    """
    where = f"dashboard.sources[{index}]"
    body = _dash_obj(where, raw)
    feeds: list[Region] = []
    for value in _str_tuple(where, "feeds", body.get("feeds") or []):
        try:
            feeds.append(Region(value))
        except ValueError as error:
            allowed = [r.value for r in Region]
            raise UiConfigError(f"{where}.feeds: must be one of {allowed}") from error
    return SourceState(
        source_id=str(_dash_text(f"{where}.source_id", body.get("source_id"), required=True)),
        layer=str(_dash_text(f"{where}.layer", body.get("layer"), required=True)),
        last_received_at=_dash_time(f"{where}.last_received_at", body.get("last_received_at")),
        feeds=tuple(feeds),
    )


def _dash_list(raw: dict, key: str) -> list:
    value = raw.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise UiConfigError(f"dashboard.{key}: must be a JSON array")
    return value


def _tag_source(wire: Any, measurement: Measurement) -> None:
    """측정 1건 옆에 **그 숫자가 어디서 왔는지** 적는다 (AI-O-05, AI-C-01).

    출처가 없으면 칸도 없다 — 아무도 채우지 않은 자리에 이름을 붙이지 않는다.
    값의 유무(`value` 칸)와 다른 축이라 둘을 한 칸에 합치지 않는다.
    """
    if isinstance(wire, dict) and measurement.source is not None:
        wire[MEASUREMENT_SOURCE] = measurement.source


def _tag_value_provenance(payload: dict, resources: LayeredResourceView, *,
                          probe_by_instance: Mapping[str, str] | None = None,
                          board_probe: str | None = None) -> None:
    """조립된 스냅샷의 측정 칸마다 출처를 붙인다.

    implements: AI-O-05 (실측과 선언의 구분), AI-O-06 (한 출처에서 파생)

    와이어 모양(`integration/status_wire.py`)은 값·단위·시각만 싣는다 — 출처는 그
    모양에 **덧붙이는 한 칸**이고, 어느 계측기가 돌았는지 아는 쪽은 조립하는 이쪽이다.
    판정을 새로 하지 않는다: 전부 `Measurement.source` 를 읽어 옮긴다.
    """
    by_id = {a.instance_id: a for a in resources.accelerators}
    for entry in payload.get("accelerators", ()):
        accelerator = by_id.get(entry.get("accelerator_instance_id"))
        if accelerator is None:
            continue
        _tag_source(entry.get("utilization"), accelerator.utilization)
        _tag_source(entry.get("temperature"), accelerator.temperature)
        probe_id = (probe_by_instance or {}).get(accelerator.instance_id)
        if probe_id is not None:
            entry[HOST_PROBE_ID] = probe_id
    board_wire = payload.get("board")
    if isinstance(board_wire, dict):
        _tag_source(board_wire.get("memory_utilization"), resources.board.memory_utilization)
        _tag_source(board_wire.get("power"), resources.board.power)
        for wire, sample in zip(board_wire.get("power_trend") or (),
                                resources.board.power_trend):
            _tag_source(wire, sample)
        if board_probe is not None:
            board_wire[HOST_PROBE_ID] = board_probe
    # L2 서비스 지표도 같은 축으로 적는다 — 지금 이 값들은 전부 선언이고, 그 사실이
    # 응답에 드러나야 "L1 은 실측, L2 는 아직 선언"이라는 상태를 화면이 말할 수 있다.
    services = {s.service_id: s for s in resources.services}
    for service_wire in payload.get("services", ()):
        service = services.get(service_wire.get("service_id"))
        if service is None:
            continue
        indicators = {i.name: i for i in service.indicators}
        for indicator_wire in service_wire.get("indicators") or ():
            indicator = indicators.get(indicator_wire.get("indicator_name"))
            if indicator is None:
                continue
            _tag_source(indicator_wire.get("measurement"), indicator.measurement)
            for wire, sample in zip(indicator_wire.get("trend") or (), indicator.trend):
                _tag_source(wire, sample)


def dashboard_host_probes(raw: Any) -> tuple[dict[str, str], str | None]:
    """선언이 지목한 계측 지점. `(개체 id → probe id, 보드 probe id)`.

    implements: AI-O-05

    **선언이 정본이다.** 어느 개체를 실제로 잴 수 있는지는 기계가 알지만, 어느 선언이
    그 개체를 가리키는지는 선언만 안다 — 코드가 `kind == "gpu"` 같은 분기로 추측하면
    새 하드웨어가 올 때마다 핵심 코드를 고쳐야 한다(AI-O-05, 원칙 #1).

    지목이 없으면 여기에 들어오지 않는다. 그래도 개체 id 가 계측 지점 id 와 같으면
    `with_host_measurements` 가 그 둘을 잇는다 — 그 판정은 한 곳(`probe_for`)에만 둔다.
    """
    body = raw if isinstance(raw, dict) else {}
    probes: dict[str, str] = {}
    for entry in body.get("accelerators") or ():
        if not isinstance(entry, dict):
            continue
        instance_id, probe = entry.get("instance_id"), entry.get("host_probe")
        if isinstance(instance_id, str) and isinstance(probe, str) and instance_id and probe:
            probes[instance_id] = probe
    board = (body.get("board") or {}).get("host_probe") if isinstance(body.get("board"), dict) \
        else None
    return probes, board if isinstance(board, str) and board else None


def build_dashboard_snapshot(raw: Any) -> DashboardSnapshot:
    """선언 1건을 조회 전용 스냅샷으로 옮긴다.

    빈 선언(`{}`)도 정상이다 — 작업 그래프를 아직 받지 못한 배치에서는 L3 구역만
    `region_available: false` 가 되고 나머지 구역은 그대로 나온다(문서 §3 요구사항
    5, AI-C-05). 구역을 지우지 않고 비었다는 사실을 적는 것이 요구다.
    """
    body = _dash_obj("dashboard", raw if raw is not None else {})
    mission_body = _dash_obj("dashboard.mission", body.get("mission") or {})
    mission = MissionSummary(
        mission_id=str(mission_body.get("mission_id") or "unassigned"),
        utterance=_dash_text("dashboard.mission.utterance_text",
                             mission_body.get("utterance_text")),
        status=_dash_text("dashboard.mission.mission_status", mission_body.get("mission_status")),
        accepted_at=_dash_time("dashboard.mission.accepted_at", mission_body.get("accepted_at")),
    )
    nodes = tuple(_dash_node(i, e) for i, e in enumerate(_dash_list(body, "task_nodes")))
    edges = tuple(_dash_edge(i, e) for i, e in enumerate(_dash_list(body, "reference_edges")))
    pinned = _dash_text("dashboard.pinned_task_node_id", body.get("pinned_task_node_id"))
    try:
        graph = TaskGraph(mission_id=mission.mission_id, nodes=nodes,
                          pinned_node_id=pinned, reference_edges=edges)
    except GraphInvalid as error:
        raise UiConfigError(f"dashboard.task_nodes: {error}") from error
    try:
        resources = LayeredResourceView(
            accelerators=tuple(
                _dash_accelerator(i, e) for i, e in enumerate(_dash_list(body, "accelerators"))),
            services=tuple(
                _dash_service(i, e) for i, e in enumerate(_dash_list(body, "services"))),
            board=_dash_board(body.get("board")),
        )
    except ValueError as error:
        raise UiConfigError(f"dashboard.accelerators/services: {error}") from error
    requests_raw = _dash_list(body, "external_requests")
    log = ExternalRequestLog(
        mission_id=mission.mission_id,
        requests=tuple(_dash_request(i, e) for i, e in enumerate(requests_raw)),
    )
    window = body.get("event_window", 50)
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise UiConfigError("dashboard.event_window: must be an integer >= 1")
    try:
        return DashboardSnapshot(
            mission=mission,
            graph=graph,
            resources=resources,
            events=tuple(
                _dash_event(f"dashboard.events[{i}]", e)
                for i, e in enumerate(_dash_list(body, "events"))),
            verdicts=tuple(
                _dash_verdict(i, e) for i, e in enumerate(_dash_list(body, "verdicts"))),
            external_requests=log,
            sources=tuple(
                _dash_source(i, e) for i, e in enumerate(_dash_list(body, "sources"))),
            event_window=window,
        )
    except ValueError as error:
        raise UiConfigError(f"dashboard: {error}") from error


def build_resource_watch(raw: Any) -> ResourceWatch:
    """선언된 임계 감시 대상(`dashboard.watch[]`) → `ResourceWatch`.

    implements: AI-O-05 (계층별 자원 관측), AI-O-02 (이상 사건 기록)

    기능정의서 §4.4: "임계값 초과 시 해당 항목이 경고 상태로 전환되며, **이벤트/알람
    (D)에 기록된다**" · "감시 대상은 **구성 가능해야 한다**". 그래서 어느 가속기의
    어느 값을 어떤 기준으로 볼지가 등록 데이터이고 코드에 없다. 감시 선언이 없는
    배치도 정상이다 — 그때는 경고 사건이 생기지 않는다(AI-C-05).

    임계 자체는 `TargetBaseline` 을 그대로 쓴다. 지표(E′)와 자원(E)이 서로 다른 기준
    표현을 쓰면 화면이 두 어휘를 배워야 한다.
    """
    body = _dash_obj("dashboard", raw if raw is not None else {})
    targets = []
    for index, entry in enumerate(_dash_list(body, "watch")):
        where = f"dashboard.watch[{index}]"
        item = _dash_obj(where, entry)
        target = _dash_target(f"{where}.target", item.get("target"))
        if target is None:
            raise UiConfigError(f"{where}.target: required — 감시에는 기준이 있어야 한다")
        try:
            targets.append(WatchTarget(
                item_id=str(_dash_text(f"{where}.item_id", item.get("item_id"),
                                       required=True)),
                field=str(_dash_text(f"{where}.field", item.get("field"), required=True)),
                target=target,
                accelerator_id=_dash_text(f"{where}.accelerator_instance_id",
                                          item.get("accelerator_instance_id")),
            ))
        except WatchTargetInvalid as error:
            raise UiConfigError(f"{where}: {error}") from error
    return ResourceWatch.of(targets)


def _watch_to_payload(result) -> dict:
    """[E]/[G] 임계 감시 판정 1건을 응답 칸으로 옮긴다.

    implements: AI-O-05, AI-O-06

    기준값을 함께 내는 이유는 기능정의서 §3 요구사항 3 이다 — "판정 조건(G)의
    기준값은 지식·경험 메모리에 정의된 성공 기준·제약에서 유래하며, **화면에
    하드코딩되지 않아야 한다**." 기준을 보내지 않으면 화면은 임계 초과를 스스로
    정할 수밖에 없고 그 순간 기준이 두 곳에 산다.

    같은 판정이 세 자리로 나간다 — [D] 의 `RESOURCE` 사건, 노드의 자원 조건([G]),
    그리고 이 목록. **한 번 평가해 셋으로 보내므로** 서로 어긋날 자리가 없다
    (§4.7 "자원 조건은 리소스 현황(E)의 Layer 1 계측값과 일관되어야 한다").

    `accelerator_instance_id` 칸의 부재는 **보드 전체 값**이라는 뜻이다. 보드 값에
    가속기 id 를 붙이면 "어느 가속기의 보드 메모리"라는 말이 된다.
    """
    body = {
        "condition_item_id": result.target.item_id,
        "measured_field": result.target.field,
        "measurement": measurement_to_wire(result.measurement),
        "target": {"value": result.target.target.value,
                   "direction": result.target.target.direction.value,
                   "unit": result.target.target.unit},
        "target_meet_state": result.meet_state.value,
        "condition_reason": result.reason_token,
    }
    if result.target.accelerator_id is not None:
        body["accelerator_instance_id"] = result.target.accelerator_id
    _tag_source(body["measurement"], result.measurement)
    return body


def live_event_records(events: list[dict]) -> tuple[EventRecord, ...]:
    """패널이 스스로 적은 사건을 [D] 의 사건으로 옮긴다.

    와이어 어휘(info/warning/critical)와 화면 등급(INFO/WARN/ERROR)은 서로 다른
    어휘이고 한쪽으로 합치지 않는다 — `severity_from_wire` 로 변환만 한다. 모르는
    등급은 버리지 않고 INFO 로 두되, 사건 자체를 잃지 않는 편이 낫다(AI-O-02:
    외부 수집기가 없어도 로컬 오류 기록은 남아야 한다).
    """
    records: list[EventRecord] = []
    for entry in events:
        if not isinstance(entry, dict):
            continue
        try:
            severity = severity_from_wire(str(entry.get("severity", "info")))
        except ValueError:
            severity = Severity.INFO
        payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
        records.append(EventRecord(
            at=_dash_time("event.at", entry.get("at")) if isinstance(
                entry.get("at"), (int, float)) else None,
            severity=severity,
            kind=EventKind.EXECUTION,
            message=str(entry.get("name") or ""),
            node_id=str(payload.get("task_node_id")) if payload.get("task_node_id") else None,
        ))
    return tuple(records)


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
        runtime_instances: dict[str, RuntimeInstance] | None = None,
        plan_capacity: int = 200,
        clock=time.time,
        host_reader: Any | None = None,
    ) -> None:
        self.config = config
        self.manifest = manifest or load_provider_manifest(config.providers_manifest)
        self.registry = CapabilityRegistry()
        register_all(self.manifest, self.registry)
        self._control_mode = control_mode
        self._namespace = namespace
        self._injected_control = control
        self._clock = clock
        # L1 실측기. 하나를 들고 재사용한다 — 전력은 두 시점의 차분이고 CPU 사용률도
        # 직전 표본이 있어야 뜻이 있다(AI-O-05). `host_reader=False` 로 끌 수 있고,
        # 끄면 선언값만 나간다(실측 경로가 없는 배치도 정상이다, AI-C-05).
        self._host_reader = (
            HostResourceReader(cpu_interval_s=HOST_CPU_SAMPLE_S)
            if host_reader is None else (host_reader or None)
        )
        self.events: list[dict] = []
        self._events_lock = threading.Lock()
        self._reconcilers: dict[str, PlacementReconciler] = {}
        self.control: Any = None
        self.control_info: dict = {}
        self._install_control()
        # --- freshness (AI-O-04: an observation, never an availability verdict)
        # node_id/device_id -> RuntimeInstance. Three sources, kept apart in
        # `_freshness_source`: injected by the caller, the newest hw_smoke
        # report, and probes this process ran. Nothing here is ever given a
        # timestamp the code made up — no instance means "미검증".
        self.runtime_instances: dict[str, RuntimeInstance] = {}
        self._freshness_source: dict[str, str] = {}
        for node_id, instance in (runtime_instances or {}).items():
            self._note_instance(node_id, instance, FRESHNESS_INJECTED)
        self.hw_smoke_info: dict = {"reports_dir": None, "report": None, "devices": 0, "reason": None}
        self._load_hw_smoke_report()
        # --- execution plans (§3-1) — in-memory window, the backend owns storage
        self._plan_capacity = plan_capacity
        self.plans = ExecutionPlanLog(capacity=plan_capacity)
        # --- device axis ----------------------------------------------------
        self._staging_root = Path(config.staging_dir or default_unit_staging_root())
        self._deployments: dict[str, DeviceDeployment] = {}
        self._device_plans: dict[str, dict] = {}
        self._device_bootstrap: dict[str, dict] = {}
        self.devices: DeviceRegistry | None = None
        self.device_info: dict = {"configured": False, "reason": "no_devices_file", "devices_path": None}
        self._install_devices()

    # --- event sink (the reconciler's `observability`) -----------------------
    @property
    def mode(self) -> str:
        """`view`(조회 전용, 기본) 또는 `review`(조회+제어, 검토 도구)."""
        return getattr(self, "_mode", MODE_VIEW)

    def set_mode(self, mode: str) -> None:
        if mode not in (MODE_VIEW, MODE_REVIEW):
            raise ValueError(f"unknown mode: {mode!r}")
        self._mode = mode

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

    # --- freshness (RuntimeInstance.health_checked_at) ------------------------
    def _note_instance(self, node_id: str, instance: RuntimeInstance, source: str) -> None:
        self.runtime_instances[node_id] = instance
        self._freshness_source[node_id] = source

    def note_probe(self, node_id: str, *, healthy: bool, checked_at: float, ttl_s: float = DEVICE_PROBE_TTL_S,
                   deployment_ref: str = "device_probe") -> RuntimeInstance:
        """Record one observation this process actually made (a link probe, a
        state read). `checked_at` is the observation time the caller measured —
        this method never substitutes `now` for it."""
        instance = RuntimeInstance(
            instance_id=node_id, deployment_ref=deployment_ref,
            healthy=bool(healthy), health_ttl=float(ttl_s), health_checked_at=float(checked_at),
        )
        self._note_instance(node_id, instance, FRESHNESS_DEVICE_PROBE)
        return instance

    def _load_hw_smoke_report(self) -> None:
        """Newest `*.json` under `hw_smoke_reports` → one RuntimeInstance per
        device (deepest level reached decides healthy/ttl, `probed_at` is the
        checked time). Tolerates both the dictionary field names
        (`device_probe_level` / `device_probe_reason`) and the short ones
        (`level` / `reason`). A missing directory, an unreadable file or a
        report without `results` is *not* an error: it is "nothing verified"."""
        directory = self.config.hw_smoke_reports
        self.hw_smoke_info = {
            "reports_dir": str(directory) if directory else None, "report": None, "devices": 0, "reason": None,
        }
        if directory is None:
            self.hw_smoke_info["reason"] = "not_configured"
            return
        if not directory.is_dir():
            self.hw_smoke_info["reason"] = "reports_dir_missing"
            return
        reports = sorted(directory.glob("*.json"), key=lambda p: (p.stat().st_mtime, p.name))
        if not reports:
            self.hw_smoke_info["reason"] = "no_reports"
            return
        newest = reports[-1]
        try:
            payload = json.loads(newest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.hw_smoke_info["reason"] = f"report_unreadable:{type(error).__name__}"
            self.record_event("hw_smoke_report_unreadable", "warning", {"path": str(newest)})
            return
        instances = runtime_instances_from_report(payload)
        for device_id, instance in instances.items():
            self._note_instance(device_id, instance, FRESHNESS_HW_SMOKE)
        self.hw_smoke_info.update({"report": str(newest), "devices": len(instances)})
        if not instances:
            self.hw_smoke_info["reason"] = "no_results"

    def freshness_for(self, node_id: str, *, now: float | None = None) -> dict | None:
        """`{healthy, checked_at, age_s, ttl_s, fresh, source}` or `None` when
        nothing ever verified this node. `fresh` is `RuntimeInstance.is_selectable`
        (healthy *and* inside the TTL); `healthy` alone is the probe verdict."""
        instance = self.runtime_instances.get(node_id)
        if instance is None:
            return None
        now = self._clock() if now is None else now
        return {
            "healthy": instance.healthy,
            "checked_at": instance.health_checked_at,
            "age_s": max(0.0, now - instance.health_checked_at),
            "ttl_s": instance.health_ttl,
            "fresh": instance.is_selectable(now=now),
            "source": self._freshness_source.get(node_id, FRESHNESS_INJECTED),
            "deployment_ref": instance.deployment_ref,
        }

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

    # --- device registry (AI-C-10, AI-B-04) ---------------------------------
    def _install_devices(self) -> None:
        """Load the device registry, or record why there is none.

        A missing or unreadable devices/credentials file is **not** a startup
        failure: the rest of the page must render (AI-C-05). The reason is
        kept so the panel can say what is missing instead of being blank.
        """
        path = self.config.devices_path
        self.device_info = {
            "configured": False,
            "reason": None,
            "devices_path": str(path) if path else None,
            "credentials_path": str(self.config.credentials_path) if self.config.credentials_path else None,
            "access_methods": list(supported_access_methods()),
        }
        if path is None:
            self.device_info["reason"] = "no_devices_file"
            return
        try:
            credentials_path = self.config.credentials_path or (
                self.config.path.parent / "device_credentials.json"
            )
            self.device_info["credentials_path"] = str(credentials_path)
            store = CredentialStore(credentials_path, strict_permissions=True)
        except DeviceRegistryError as error:
            # A group/world-readable credential file is refused, and staying
            # refused is the point — the framework must not be the reason a
            # secret became readable (AI-B-02).
            self.device_info["reason"] = f"credential_store_rejected:{error}"
            self.record_event("device_registry_unavailable", "warning", dict(self.device_info))
            return
        registry = DeviceRegistry(store)
        if path.exists():
            try:
                registry.load(path)
            except DeviceRegistryError as error:
                self.device_info["reason"] = f"devices_file_rejected:{error}"
                self.record_event("device_registry_unavailable", "warning", dict(self.device_info))
                return
        self.devices = registry
        self.device_info["configured"] = True
        self._sync_device_nodes()

    def _sync_device_nodes(self) -> None:
        """Make every registered device visible as a node, and vice versa.

        The two halves were written independently: a node in the review config
        declares a `purpose`, a registration declares `purpose_id`. Whichever
        one is filled in wins, and neither is required — a device registered
        before anyone said what it is for is a normal state, it simply has no
        residency plan yet.
        """
        if self.devices is None:
            return
        nodes = {node.node_id: node for node in self.config.nodes}
        changed = False
        for device in self.devices.devices():
            node = nodes.get(device.device_id)
            purpose = device.purpose_id or (node.purpose if node else None) or None
            if purpose is not None and purpose not in self.config.purposes:
                # An unknown purpose id is a typo, not a degraded mode; leave
                # the device without a plan rather than guessing.
                purpose = None
            if node is None:
                nodes[device.device_id] = NodeConfig(
                    node_id=device.device_id,
                    label=device.address,
                    tags=tuple(sorted(device.node_tags)),
                    budget=_purpose_budget(self.config.purposes.get(purpose)),
                    role=device.role or "ugv",
                    purpose=purpose,
                )
                changed = True
            elif node.purpose != purpose and purpose is not None:
                nodes[device.device_id] = replace(node, purpose=purpose)
                changed = True
        if changed:
            self.config = replace(self.config, nodes=tuple(nodes.values()))

    def reset(self) -> None:
        """Forget bound providers, events and the control provider's state."""
        self._reconcilers.clear()
        self._deployments.clear()
        self._device_plans.clear()
        self.plans = ExecutionPlanLog(capacity=self._plan_capacity)
        with self._events_lock:
            self.events.clear()
        self._install_control()
        self.record_event("reset", "info", {"control": self.control_info.get("active")})

    # --- describe ------------------------------------------------------------
    def describe(self) -> dict:
        return {
            "config_path": str(self.config.path),
            "providers_manifest": str(self.config.providers_manifest),
            "devices": dict(self.device_info),
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
            "nodes": [
                {**n.to_dict(), "freshness": self.freshness_for(n.node_id)} for n in self.config.nodes
            ],
            "roles": self.config.roles(),
            "hw_smoke": dict(self.hw_smoke_info),
            "plan_capacity": self._plan_capacity,
            "device_purposes_path": (
                str(self.config.device_purposes_path) if self.config.device_purposes_path else None
            ),
            "device_purposes": [
                {
                    "purpose_id": pr.purpose_id,
                    "description": pr.description,
                    "node_tags": list(pr.node_tags),
                    "preferred_node_tags": list(pr.preferred_node_tags),
                    "budget": _budget_to_dict(pr.budget) if pr.budget else None,
                    "link": _link_to_dict(pr.link),
                    "kinds": list(pr.kinds()),
                }
                for pr in self.config.purposes.values()
            ],
            "functions": [f.to_dict() for f in self.config.functions],
            "providers": [self._provider_to_dict(r) for r in self.manifest.registrations],
            "all_tags": self.all_tags(),
            "mode": self.mode,
            "mutating_paths": sorted(MUTATING_PATHS),
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
                    "states": {}, "grades": {}, "reasons": {}, "roles": {}, "commands": {},
                    "purposes": {}, "residencies": {}, "link_postures": {},
                    "residency_reasons": {}, "outage_behaviors": {}}
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
            # Empty when no device purposes are configured, so a config that
            # does not use the residency axis needs no extra labels.
            "purposes": sorted(self.config.purposes),
            "residencies": list(CAPABILITY_RESIDENCIES) if self.config.purposes else [],
            "link_postures": list(LINK_POSTURES) if self.config.purposes else [],
            "residency_reasons": (
                list(LINK_POSTURE_REASONS) + list(RESIDENCY_REASONS) + list(RESIDENCY_VIOLATIONS)
                if self.config.purposes
                else []
            ),
            "outage_behaviors": list(OUTAGE_BEHAVIORS) if self.config.purposes else [],
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
            # The residency axis has its own closed vocabulary: "왜 이 기능이
            # 이 장치 안에 있는가"는 "왜 이 기능이 지금 돌 수 있는가"와 다른
            # 질문이라 어휘를 합치지 않는다.
            "residencies": list(CAPABILITY_RESIDENCIES),
            "link_postures": list(LINK_POSTURES),
            "link_posture_reasons": list(LINK_POSTURE_REASONS),
            "residency_reasons": list(RESIDENCY_REASONS),
            "residency_violations": list(RESIDENCY_VIOLATIONS),
            "outage_behaviors": list(OUTAGE_BEHAVIORS),
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
            "verified": node.verified,
            "freshness": self.freshness_for(node.node_id),
            "rows": rows,
        }

    def _row(self, kind: str, res: CapabilityResolution, spec=None) -> dict:
        # `spec` lets a caller supply the declaration this kind was resolved
        # under (the residency view resolves against a device purpose, not the
        # page-level `capabilities` list). Default keeps every existing call
        # identical.
        spec = spec if spec is not None else self.config.spec(kind)
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

    # --- residency (device axis: what lives ON this device, and why) ----------
    def _effective_link(self, node_id: str, link=None) -> tuple[LinkProfile | None, str]:
        """Which link characteristics this decision uses, and where they came
        from. Precedence: what-if > the registered device > the purpose's own
        declaration. Returning the origin matters because "measured on this
        device" and "assumed from the purpose" are different claims."""
        if link is not None:
            if not isinstance(link, dict):
                raise UiConfigError("link: must be a JSON object")
            try:
                return link_profile_from_dict(link), "whatif"
            except ValueError as error:
                raise UiConfigError(f"link: {error}") from error
        node = self.config.node(node_id)
        if node.link is not None:
            return node.link, "node"
        return None, "purpose"

    def residency(self, node_id: str, *, link=None, tags=None, budget=None, exclude_providers=()) -> dict:
        """For one registered device: which capability kinds were chosen to
        live on it, why, what serves the rest from the edge, and what happens
        to each during a comms outage.

        The placement decision itself is `runtime/residency.py`; the
        on-device rows are then run through the *existing*
        `ZoneApplication.resolve()` so budget, tags and optional-dependency
        degradation stay the one mechanism they already were (AI-C-05,
        AI-B-04, AI-C-13). Nothing is re-judged here.
        """
        node, effective_tags, effective_budget = self._effective(node_id, tags, budget)
        purpose = self.config.purpose_for(node_id)
        link_profile, link_origin = self._effective_link(node_id, link)

        if purpose is None:
            # A device with no declared purpose is a normal configuration.
            return {
                "node_id": node.node_id, "label": node.label, "role": node.role,
                "purpose": None, "link": None, "link_origin": link_origin,
                "rows": [], "violations": [], "outage": None,
                "node_tags": {"missing_required": [], "missing_preferred": []},
            }

        plan = decide_residency(purpose, link=link_profile)
        resolutions = self._resolve_residency(
            purpose, plan, effective_tags, effective_budget, exclude_providers
        )

        rows = []
        for decision in plan.decisions:
            spec = purpose.spec(decision.kind)
            resolved = resolutions.get(decision.kind)
            rows.append(
                {
                    "kind": decision.kind,
                    "placement": decision.placement.value,
                    "policy": decision.policy.value,
                    "reason": decision.reason,
                    "reason_token": state_change_reason_token(decision.reason),
                    "reason_data": _reason_data(decision.reason),
                    "survives_outage": decision.survives_outage,
                    "quality_is_safety_affecting": decision.quality_is_safety_affecting,
                    "outage_behavior": decision.outage_behavior,
                    "edge_service": decision.edge_service,
                    "local_fallback_kind": decision.local_fallback_kind,
                    "edge_payload": spec.edge_payload if spec else "metadata",
                    "min_link_quality": spec.min_link_quality if spec else None,
                    "is_core": bool(spec and spec.is_core),
                    "degrade_rank": spec.degrade_rank if spec else 0,
                    # Only on-device kinds go through resolution; an edge kind
                    # is not this device's to run, so it has no state here.
                    "resolution": (
                        self._row(decision.kind, resolved, spec=_spec_of(purpose, decision.kind))
                        if resolved is not None
                        else None
                    ),
                }
            )

        node_tags = set(effective_tags)
        return {
            "node_id": node.node_id, "label": node.label, "role": node.role,
            "tags": sorted(node_tags),
            "budget": _budget_to_dict(effective_budget),
            "purpose": {
                "purpose_id": purpose.purpose_id,
                "description": purpose.description,
                "node_tags": list(purpose.node_tags),
                "preferred_node_tags": list(purpose.preferred_node_tags),
                "budget": _budget_to_dict(purpose.budget) if purpose.budget else None,
            },
            "link": {
                **_link_to_dict(link_profile if link_profile is not None else purpose.link),
                "posture": plan.link.posture.value,
                "reason": plan.link.reason,
                "reason_token": state_change_reason_token(plan.link.reason),
                "reason_data": _reason_data(plan.link.reason),
                "permits_remote": plan.link.permits_remote,
            },
            "link_origin": link_origin,
            "rows": rows,
            "ondevice_kinds": list(plan.ondevice_kinds),
            "edge_kinds": list(plan.edge_kinds),
            "violations": [
                {
                    "violation": v,
                    "violation_token": state_change_reason_token(v),
                    "kind": _reason_data(v),
                }
                for v in plan.violations
            ],
            "outage": {k: list(v) for k, v in plan.outage_survival_report().items()},
            # AI-B-04: a required tag the device lacks removes only the
            # providers that need it; a preferred one never removes anything.
            "node_tags": {
                "missing_required": sorted(t for t in purpose.node_tags if t not in node_tags),
                "missing_preferred": sorted(t for t in purpose.preferred_node_tags if t not in node_tags),
            },
        }

    def _resolve_residency(self, purpose, plan, tags, budget, exclude_providers=()) -> dict[str, CapabilityResolution]:
        """Run the on-device half of the plan through the existing resolver."""
        specs = plan.capability_specs(purpose)
        if not specs:
            return {}
        profile = plan.ondevice_profile(self.config.profile)
        app = ZoneApplication(profile, self._registry_without(exclude_providers), specs, node_tags=set(tags))
        return app.resolve(budget)

    def residency_whatif(self, node_id: str, *, link=None, tags=None, budget=None, exclude_providers=()) -> dict:
        """Same device, different link — the "링크가 나빠지면" question.

        Only the link changes; the purpose data is untouched, which is what
        makes the diff readable as "this moved because of the link" rather
        than "someone edited the profile".
        """
        baseline = self.residency(node_id)
        override = self.residency(
            node_id, link=link, tags=tags, budget=budget, exclude_providers=exclude_providers
        )
        before = {row["kind"]: row for row in baseline["rows"]}
        diff = []
        for row in override["rows"]:
            prev = before.get(row["kind"])
            entry = {
                "kind": row["kind"],
                "before_placement": prev["placement"] if prev else None,
                "after_placement": row["placement"],
                "before_reason": prev["reason"] if prev else None,
                "after_reason": row["reason"],
            }
            entry["changed"] = entry["before_placement"] != entry["after_placement"]
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

        Tier rules (2nd-round UI, plan §3 "단독 수행 가능 장비 / 조합"):
        `roles_by_kind[kind]` = roles with at least one node serving the kind
        (ACTIVE/DEGRADED), config role order. `solo_roles` = roles that serve
        **every** required kind by themselves (a function with no required
        kinds has every role as solo — vacuous, documented). `combo_roles` =
        greedy set cover over required kinds: repeatedly take the role that
        covers the most still-uncovered required kinds, ties broken by config
        role order, until all are covered; if some required kind is served by
        no role at all the cover is impossible and `combo_roles` is `[]`
        (the `trace` says why). A solo role is therefore always its own combo.

        `trace` (failure trace) exists for every non-ACTIVE function: one
        entry per (missing kind × role) — required kinds first, then missing
        optional kinds — with the same reason pick as `supplement`, plus
        `best_candidate` (that provider) and `missing_tags` (the
        `required_hw_tag_missing:<a,b>` / `required_runtime_tag_missing`
        data split on commas). "What would fix it" is exactly
        `missing_tags` at `role`; the page composes `tag @ role` from data.

        `unverified_nodes`: charged serving nodes (`served[kind][0]`) whose
        config says `verified: false` or that have no freshness record — the
        function may run on hardware nobody has verified yet.
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
        node_order = {n.node_id: i for i, n in enumerate(self.config.nodes)}
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

            # tiers: which roles carry the function alone / together
            roles_by_kind = {
                kind: [role for role in roles if any(e["role"] == role for e in served.get(kind, []))]
                for kind in function.required_capabilities
            }
            solo_roles, combo_roles = solo_and_combo_roles(roles, roles_by_kind)

            # failure trace: one drill path per (missing kind × role)
            trace: list[dict] = []
            if state is not CapabilityState.ACTIVE:
                for is_required, rows_ in ((True, required_rows), (False, optional_rows)):
                    for row in rows_:
                        if not row["missing"]:
                            continue
                        for role in roles:
                            picked = _supplement_reason(row["why"], role, priority_of)
                            trace.append(
                                {
                                    "kind": row["kind"],
                                    "required": is_required,
                                    "role": role,
                                    "node_id": picked["node_id"],
                                    "reason": picked["reason"],
                                    "reason_token": picked["reason_token"],
                                    "reason_data": picked["reason_data"],
                                    "best_candidate": picked["provider_id"],
                                    "missing_tags": _missing_tags(picked["reason_token"], picked["reason_data"]),
                                }
                            )

            # verification: charged serving nodes nobody verified
            unverified: list[str] = []
            for entry in by_kind:
                node_id = entry["node_id"]
                if node_id in unverified:
                    continue
                node = self.config.node(node_id)
                if not node.verified or self.freshness_for(node_id) is None:
                    unverified.append(node_id)
            unverified.sort(key=node_order.__getitem__)

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
                    "roles_by_kind": roles_by_kind,
                    "solo_roles": solo_roles,
                    "combo_roles": combo_roles,
                    "trace": trace,
                    "unverified_nodes": unverified,
                }
            )
        return {"overrides": fleet["overrides"], "nodes": fleet["nodes"], "served": served, "functions": result}

    # ── 선언 축 what-if: 기능 하나를 들이면 어디에 들어가나 ─────────────────
    #
    # 위의 `whatif_*` 는 **노드 축**이다("이 노드에 태그·예산을 더하면"). 이 메서드는
    # **선언 축**이다("이 기능을 선언하면"). 둘이 다른 질문이라서 따로 있다.
    #
    # `registry/capability_proposal.py::PlacementOracle` 의 구현이고, 그 모듈이
    # 요구하는 것은 **이 서비스가 이미 내는 답**뿐이다 — 새 판정을 여기서 만들면
    # 배치의 정본이 둘이 되고 두 화면이 다른 답을 말한다(CLAUDE.md).

    def assess_proposal(self, function_row, provider_rows) -> list[dict]:
        """제안을 얹은 **임시 설정**으로 노드마다 해소해 본다. 파일은 고치지 않는다.

        같은 로더(`registrations_from_dict`)로 제안 provider 를 등록 자료형으로
        바꾸는 이유: 제안이 여기서 통과하면 그 줄을 선언 파일에 그대로 붙였을 때도
        통과해야 한다. 따로 검증하면 "미리보기는 됐는데 적용하면 거절" 이 생긴다.

        비용이 미측정인 제안은 **여기까지 오지 않는다** — `capability_proposal.assess`
        가 그 앞에서 막는다(AI-B-01). 그 순서가 뒤집히면 미측정 비용이 0 으로 읽힌
        배치 답이 먼저 나오고 운영자는 그 답을 기억한 채 경고를 읽는다.
        """
        kinds = tuple(dict.fromkeys(
            list(function_row.get("required_capabilities") or ())
            + list(function_row.get("optional_capabilities") or ())))
        if not kinds:
            return []

        extra = registrations_from_dict({"providers": list(provider_rows)})
        manifest = replace(
            self.manifest,
            registrations=self.manifest.registrations + extra.registrations)

        # 제안한 kind 를 활성 목록에 **더한다**. 이미 활성인 kind 는 그대로 둔다 —
        # 순서를 바꾸면 `served[kind][0]` 의 선택 결과가 흔들린다.
        active = tuple(self.config.profile.active_capability_kinds)
        added = tuple(k for k in kinds if k not in active)
        specs = tuple(self.config.specs) + tuple(
            CapabilitySpec(kind=k, is_core=False,
                           requirement=CapabilityRequirement(required=(), optional=()))
            for k in added if self.config.spec(k) is None)
        proposed = replace(
            self.config,
            profile=replace(self.config.profile,
                            active_capability_kinds=active + added),
            specs=specs,
            functions=self.config.functions,
        )

        service = StatusService(proposed, manifest=manifest,
                                control_mode="local", clock=self._clock)
        required = frozenset(function_row.get("required_capabilities") or ())
        out: list[dict] = []
        for node in proposed.nodes:
            resolved = service.resolve(node.node_id)
            rows = {row["kind"]: row for row in resolved["rows"]}
            out.append(_proposal_verdict(node.node_id, rows, required, kinds))
        # 정본의 선택 규칙과 **같은 순서**로 낸다 — 쓸 수 있는 것 먼저, 그 다음 비용,
        # 그 다음 선언 순서. 여기서 다른 규칙을 쓰면 추천이 화면과 어긋난다.
        order = {state: index for index, state in enumerate(("ACTIVE", "DEGRADED"))}
        out.sort(key=lambda row: (
            order.get(row["state"], 9),
            (row["cost"] or {}).get("compute_units", float("inf")),
            (row["cost"] or {}).get("memory_mb", float("inf")),
            [n.node_id for n in proposed.nodes].index(row["node_id"]),
        ))
        return out

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

    def place(
        self,
        node_id: str,
        *,
        tags=None,
        budget=None,
        exclude_providers=(),
        function_id: str | None = None,
        requester: Requester | None = None,
        correlation_id: str | None = None,
    ) -> ExecutionPlan:
        """resolve → reconciler.apply → **one `ExecutionPlan`** in the log.

        The plan is the envelope, not a decision: resolution and placement are
        the same two calls as before, tied under one `plan_id` so the
        Executions tab (and an audit reader) can say "these actions came from
        that request". `function_id` defaults to `"*"` — a placement is per
        node and serves every function at once. `requester` is carried
        opaquely (§3 "요청자 자리").
        """
        _, _, _, resolutions = self._resolve_raw(
            node_id, tags=tags, budget=budget, exclude_providers=exclude_providers
        )
        actions = self._reconciler(node_id).apply(resolutions)
        plan = build_plan(
            function_id or PLAN_ALL_FUNCTIONS,
            resolutions,
            actions,
            correlation_id=correlation_id,
            requester=requester,
            node_id=node_id,
            clock=self._clock,
        )
        self.plans.record(plan)
        self.record_event(
            "execution_plan_recorded", "info",
            {"plan_id": plan.plan_id, "correlation_id": correlation_id, "function_id": plan.function_id,
             "node_id": node_id, "requester": plan.as_dict()["requester"], "actions": len(actions)},
        )
        return plan

    def apply_placement(self, node_id: str, *, tags=None, budget=None, exclude_providers=(), **plan_fields) -> list[dict]:
        """Actions of one `place()` call, in the shape `/api/placement` returns."""
        plan = self.place(node_id, tags=tags, budget=budget, exclude_providers=exclude_providers, **plan_fields)
        return [_action_dict(a) for a in plan.placement_actions]

    # --- execution plans (§3-1) --------------------------------------------------
    def plan_summaries(self, *, limit: int = 20, correlation_id: str | None = None) -> dict:
        """Newest-first summaries. `correlation_id` narrows to one request chain."""
        if correlation_id is not None:
            plans = tuple(reversed(self.plans.by_correlation(correlation_id)))
        else:
            plans = self.plans.latest(limit)
        return {
            "count": len(self.plans),
            "capacity": self._plan_capacity,
            "correlation_id": correlation_id,
            "plans": [self._plan_summary(p) for p in plans[:limit]],
        }

    def plan_detail(self, plan_id: str) -> dict:
        plan = self.plans.get(plan_id)
        if plan is None:
            raise UiConfigError(f"unknown_plan:{plan_id}")
        role = None
        try:
            role = self.config.node(plan.node_id).role if plan.node_id else None
        except UiConfigError:
            role = None
        return {**plan.as_dict(), "node_role": role, **self._plan_counts(plan)}

    def _plan_summary(self, plan: ExecutionPlan) -> dict:
        data = plan.as_dict()
        role = None
        if plan.node_id:
            try:
                role = self.config.node(plan.node_id).role
            except UiConfigError:
                role = None
        return {
            "plan_id": data["plan_id"],
            "correlation_id": data["correlation_id"],
            "function_id": data["function_id"],
            "node_id": data["node_id"],
            "node_role": role,
            "created_at": data["created_at"],
            "requester": data["requester"],
            "served_kinds": list(plan.served_kinds),
            "unserved_kinds": list(plan.unserved_kinds),
            **self._plan_counts(plan),
        }

    @staticmethod
    def _plan_counts(plan: ExecutionPlan) -> dict:
        accepted = sum(1 for a in plan.placement_actions if a.accepted)
        return {
            "actions": len(plan.placement_actions),
            "accepted": accepted,
            "rejected": len(plan.placement_actions) - accepted,
        }

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

    # --- device axis: register -> decide -> deploy -> manage -----------------
    # 이 절이 두 반쪽을 잇는 지점이다. 위쪽(residency)은 "무엇이 이 장치 안에
    # 있어야 하는가"를 이미 답했고, 아래쪽 provider는 "그것을 거기 두는 방법"을
    # 이미 안다. 여기서 새로 판정하는 것은 하나도 없다 — 계획은
    # `runtime/device_deployment.py`가 세우고, 제어 호출은 기존
    # `PlacementReconciler`가 내며, 행동 목록은 `/api/placement`와 같은 모양으로
    # 나간다(AI-B-03의 감사 기록도 같은 sink를 쓴다).

    def _require_devices(self) -> DeviceRegistry:
        if self.devices is None:
            raise UiConfigError(f"device_registry_unavailable:{self.device_info.get('reason')}")
        return self.devices

    def _deployment(self, device_id: str) -> DeviceDeployment:
        """One `DeviceDeployment` per device, kept so it remembers what is up.

        Reusing it is what makes a second identical deploy issue zero control
        calls: the reconciler's binding table is the memory (AI-B-05 — 배포와
        상태 변경은 같은 lifecycle 안에 있어야 한다).
        """
        registry = self._require_devices()
        if device_id in self._deployments:
            return self._deployments[device_id]
        device = registry.get(device_id)
        if device is None:
            raise UiConfigError(f"unknown_device:{device_id}")
        try:
            channel = open_channel(
                device, registry.credential_for(device_id), observability=self
            )
        except DeviceChannelError as error:
            raise UiConfigError(str(error)) from error
        deployment = DeviceDeployment(
            channel=channel,
            staging_dir=self._staging_root / device_id,
            unit_source=DEFAULT_UNIT_SOURCE,
            observability=self,
            requested_by="status_ui",
        )
        self._deployments[device_id] = deployment
        return deployment

    def device_rows(self) -> dict:
        """Every registered device, with what it is for and what it holds.

        Secrets are structurally absent: a registration only ever carried a
        credential *reference*, and `DeviceCredential.redacted()` is the only
        credential view this method can produce (AI-B-02).
        """
        if self.devices is None:
            return {"configured": False, "info": dict(self.device_info), "devices": []}
        rows = []
        for device in self.devices.devices():
            credential = self.devices.credential_for(device.device_id)
            node = next((n for n in self.config.nodes if n.node_id == device.device_id), None)
            rows.append(
                {
                    **device.as_dict(),
                    "credential": credential.redacted() if credential else None,
                    "purpose": (node.purpose if node else None) or device.purpose_id or None,
                    "node_known": node is not None,
                    "link": _link_to_dict(node.link) if node and node.link is not None else None,
                    "plan": self._device_plans.get(device.device_id),
                    "bootstrap": self._device_bootstrap.get(device.device_id),
                    "state": self._deployments[device.device_id].state()
                    if device.device_id in self._deployments
                    else None,
                }
            )
        return {
            "configured": True,
            "info": dict(self.device_info),
            "purposes": sorted(self.config.purposes),
            "commands": list(DEVICE_COMMANDS),
            "devices": rows,
        }

    def register_device(
        self,
        *,
        device_id: str,
        address: str,
        username: str,
        purpose: str | None = None,
        password: str | None = None,
        key_path: str | None = None,
        node_tags=None,
        role: str = "ugv",
        port: int = 22,
        access_method: str = "ssh",
        label: str | None = None,
    ) -> dict:
        """"주소 + 자격증명 + 목적"으로 장치 하나를 등록한다.

        비밀번호를 주면 그것으로 **한 번만** 접속해 키를 심고 이후 등록을 키로
        바꾼다(`providers/ondevice_bootstrap.py`). 비밀번호는 등록 객체에도,
        저장 파일에도, 이벤트에도 들어가지 않는다 — 여기서 그 값을 다시
        만지는 코드는 부트스트랩 호출 한 줄뿐이다(AI-B-02).
        """
        registry = self._require_devices()
        for name, value in (("device_id", device_id), ("address", address), ("username", username)):
            if not isinstance(value, str) or not value:
                raise UiConfigError(f"{name}: required")
        if purpose is not None and purpose not in self.config.purposes:
            raise UiConfigError(f"unknown purpose_id:{purpose}")
        if access_method not in supported_access_methods():
            raise UiConfigError(f"unsupported_access_method:{access_method}")
        tags = tuple(_str_tuple("register", "node_tags", node_tags or []))

        credential = DeviceCredential(
            credential_id=f"{device_id}-key",
            auth_method=AUTH_KEY,
            key_path=key_path or self.config.control_key_path,
        )
        if password:
            # A password-only registration still needs *a* credential to exist
            # before bootstrap can reach the device.
            credential = DeviceCredential(
                credential_id=f"{device_id}-bootstrap", auth_method=AUTH_PASSWORD, secret=password
            )
        try:
            registry.register_address(
                device_id,
                address,
                username,
                credential=credential,
                node_tags=frozenset(tags),
                role=role,
                purpose_id=purpose or "",
                port=int(port),
                access_method=access_method,
            )
        except DeviceRegistryError as error:
            raise UiConfigError(str(error)) from error

        bootstrap: dict | None = None
        if password:
            result = bootstrap_key_auth(
                registry,
                device_id,
                password=password,
                key_path=key_path or self.config.control_key_path,
            )
            bootstrap = result.as_dict()
            self._device_bootstrap[device_id] = bootstrap
            self.record_event(
                "device_key_bootstrap",
                "info" if result.ok else "warning",
                {"device_id": device_id, **{k: v for k, v in bootstrap.items() if k != "device_id"}},
            )
        # Only the non-secret half is persisted; the credential store writes
        # itself with owner-only permissions and is git-ignored.
        if self.config.devices_path is not None:
            registry.save(self.config.devices_path)
        registry.save_credentials()

        node = NodeConfig(
            node_id=device_id,
            label=label or f"{device_id} · {address}",
            tags=tags,
            budget=_purpose_budget(self.config.purposes.get(purpose)),
            role=role,
            purpose=purpose,
        )
        others = tuple(n for n in self.config.nodes if n.node_id != device_id)
        self.config = replace(self.config, nodes=others + (node,))
        self._deployments.pop(device_id, None)  # credential may have rotated
        self.record_event(
            "device_registered",
            "info",
            {"device_id": device_id, "purpose": purpose, "access_method": access_method},
        )
        return {
            "device_id": device_id,
            "bootstrap": bootstrap,
            "residency": self.residency(device_id) if purpose else None,
            "devices": self.device_rows(),
        }

    def device_plan(self, device_id: str, *, link=None) -> dict:
        """What *would* be deployed. Pure computation — touches no device."""
        node, tags, budget = self._effective(device_id, None, None)
        purpose = self.config.purpose_for(device_id)
        if purpose is None:
            raise UiConfigError(f"device_has_no_purpose:{device_id}")
        link_profile, _origin = self._effective_link(device_id, link)
        plan = decide_residency(purpose, link=link_profile)
        resolutions = self._resolve_residency(purpose, plan, tags, budget)
        unit_plan = plan_device_units(device_id, purpose, plan, resolutions)
        return {"plan": unit_plan, "resolutions": resolutions, "residency": plan}

    def device_command(
        self, device_id: str, command: str, *, unit_id: str | None = None, link=None,
        function_id: str | None = None, requester: Requester | None = None, correlation_id: str | None = None,
    ) -> dict:
        """One device action, answered in `/api/placement`'s shape.

        Every branch here is on the *command*, never on the device or its
        domain (절대 준수 원칙 #3). What differs between a drone and a fixed
        camera is only the plan the purpose data produced. A `deploy` is also
        recorded as an `ExecutionPlan` (same envelope as `place()`), and any
        command that read the device's reachability notes that observation as
        this device's freshness.
        """
        if command not in DEVICE_COMMANDS:
            raise UiConfigError(f"unknown_device_command:{command}")
        registry = self._require_devices()
        if registry.get(device_id) is None:
            raise UiConfigError(f"unknown_device:{device_id}")

        actions: list[dict] = []
        extra: dict = {}
        if command == "deploy":
            # `link` lets the page deploy what the *degraded-link* plan says
            # without waiting for the link to actually degrade — the same
            # what-if the residency panel already offers, carried through to
            # the device so the survival set can be staged in advance.
            computed = self.device_plan(device_id, link=link)
            deployment = self._deployment(device_id)
            prepared, applied = deployment.apply(computed["plan"], computed["resolutions"])
            self._device_plans[device_id] = prepared.as_dict()
            actions = [_action_dict(a) for a in applied]
            plan = build_plan(
                function_id or PLAN_ALL_FUNCTIONS, computed["resolutions"], applied,
                correlation_id=correlation_id, requester=requester, node_id=device_id, clock=self._clock,
            )
            self.plans.record(plan)
            extra["plan_id"] = plan.plan_id
            self.record_event(
                "execution_plan_recorded", "info",
                {"plan_id": plan.plan_id, "correlation_id": correlation_id, "function_id": plan.function_id,
                 "node_id": device_id, "requester": plan.as_dict()["requester"], "actions": len(applied)},
            )
        elif command == "stop":
            actions = [_action_dict(a) for a in self._deployment(device_id).stop_all()]
        elif command == "rollback":
            if not unit_id:
                raise UiConfigError("unit_id: required for rollback")
            result = self._deployment(device_id).rollback(unit_id)
            accepted = bool(getattr(result, "accepted", False))
            actions = [
                {
                    "kind": _unit_kind(self._device_plans.get(device_id), unit_id),
                    "provider_id": unit_id,
                    "command": "rollback",
                    "accepted": accepted,
                    "rejection_reason": None if accepted else getattr(result, "rejection_reason", "unsupported"),
                }
            ]
            self.record_event(
                "device_rollback", "info" if accepted else "warning",
                {"device_id": device_id, "unit_id": unit_id,
                 "accepted": accepted, "reason": actions[0]["rejection_reason"]},
            )
        elif command == "remove":
            if not unit_id:
                raise UiConfigError("unit_id: required for remove")
            self._deployment(device_id).remove(unit_id)
        elif command == "probe_link":
            extra["link"] = self.probe_device_link(device_id)
        # "refresh" falls through: the state read below is the whole answer.

        state = None
        if device_id in self._deployments:
            state = self._deployments[device_id].state()
            reachable = self._deployments[device_id].channel.is_available()
            state["reachable"] = reachable
            # We just asked the channel; that is a real observation with a real time.
            self.note_probe(device_id, healthy=bool(reachable), checked_at=self._clock(),
                            deployment_ref=f"device_probe:{command}")
        return {
            "device_id": device_id,
            "command": command,
            "actions": actions,
            "plan": self._device_plans.get(device_id),
            "state": state,
            "freshness": self.freshness_for(device_id),
            **extra,
        }

    def probe_device_link(self, device_id: str, *, count: int = 20) -> dict:
        """Measure this device's link and let the measurement drive placement.

        Three outcomes, deliberately distinct (AI-N-03 forbids assuming a
        metric exists):

        * measured, packets came back -> a quality/stability the placement uses;
        * measured, nothing came back -> quality 0.0. We *did* observe, and the
          observation was total loss, so the conservative reading is correct
          even when the real cause is a host that drops ICMP — `source` records
          the method so the claim stays inspectable;
        * could not measure at all (no probe tool) -> `None`, and the node keeps
          whatever link declaration it already had. "We could not measure" and
          "the link is poor" must not collapse into the same number.
        """
        registry = self._require_devices()
        device = registry.get(device_id)
        if device is None:
            raise UiConfigError(f"unknown_device:{device_id}")
        measurement = probe_icmp(device.address, count=count, interval_s=0.2)
        probed_at = self._clock()
        profile = link_profile_from(measurement)
        applied = False
        if measurement.measured:
            # Measured (even total loss) is an observation; "could not measure"
            # is not, and leaves freshness untouched (AI-N-03).
            self.note_probe(device_id, healthy=measurement.received > 0, checked_at=probed_at,
                            deployment_ref="device_probe:probe_link")
        if profile is not None:
            nodes = []
            for node in self.config.nodes:
                nodes.append(replace(node, link=profile) if node.node_id == device_id else node)
            self.config = replace(self.config, nodes=tuple(nodes))
            applied = True
        self.record_event(
            "device_link_probed",
            "info" if applied else "warning",
            {"device_id": device_id, "measurement": measurement.as_dict(), "applied": applied},
        )
        return {
            "measurement": measurement.as_dict(),
            "profile": _link_to_dict(profile) if profile is not None else None,
            "applied": applied,
            "freshness": self.freshness_for(device_id),
        }

    def recent_events(self, limit: int = 200) -> list[dict]:
        with self._events_lock:
            return list(self.events[-limit:])

    # --- 종합상황정보 Dashboard (구역 B~I) ------------------------------------

    def dashboard(self, *, now: float | None = None, pin: str | None = None) -> dict:
        """구역 B~I 를 **한 스냅샷**으로 낸다. 조회 전용이다.

        implements: AI-O-06 (통합 운영 상태 뷰 제공), AI-O-05 (계층별 지표),
                    AI-B-12 (작업 그래프 실행 상태), AI-B-13 (외부 개발 요청)

        기능정의서 §3 요구사항 1: "화면은 소스별로 개별 조회하는 것이 아니라
        **통합된 상태 뷰를 구독**하여 갱신되어야 한다." §5 상태 일관성: "동일한
        사실이 여러 구역에 표시될 경우 값이 상충하지 않아야 한다." 구역별로 따로
        조회하면 두 요구를 함께 지킬 수 없으므로 한 번에 조립한다.

        같은 사실은 **한 출처에서 파생**시킨다 — 상태별 노드 수는 그래프에서
        (`state_counts`), 유휴 가속기는 자원 뷰에서(`idle_accelerators`),
        구역 가용성은 소스 수신 상태에서(`region_state`). 이 메서드는 그 판정을
        다시 하지 않는다.

        `pin` 은 기준 노드 고정이고 **관찰 방식의 변경**이다(문서 §1.1) — 실행
        상태를 바꾸지 않으므로 조회 경로에 둔다.
        """
        snapshot = build_dashboard_snapshot(self.config.dashboard)
        # [E] L1 은 **선언이 아니라 계측**이어야 한다(문서 §4.4). 선언된 개체 목록은
        # 그대로 두고 그 자리에 이 기계에서 읽은 값을 입힌다 — 못 읽은 칸은 0 이 아니라
        # 미측정으로 남고, 지목된 계측 지점이 없으면 선언값이 선언이라고 적힌 채 남는다.
        stamp = time.time() if now is None else now
        readout, probe_status = self._host_readout()
        probe_by_instance: dict[str, str] = {}
        board_probe: str | None = None
        unclaimed: tuple[str, ...] = ()
        if readout is not None:
            declared_probes, board_probe = dashboard_host_probes(self.config.dashboard)
            probe_by_instance = resolve_probes(snapshot.resources, readout, declared_probes)
            # 계측기가 찾았는데 아무 선언도 가리키지 않는 계측 지점. 목록은 선언이
            # 소유하므로 여기서 개체를 더하지 않지만, 조용히 버리면 "이 기계에
            # 가속기가 없다"와 "있는데 선언되지 않았다"가 같아진다(§4.4 완전성).
            unclaimed = undeclared_probes(snapshot.resources, readout, declared_probes)
            snapshot = replace(snapshot, resources=with_host_measurements(
                snapshot.resources, readout,
                probe_by_instance=declared_probes, board_probe=board_probe,
            ))
        # [E] 임계 감시 → [D] 경고 사건 + [G] 자원 조건. **한 판정에서 둘**이다
        # (§4.4 "임계값 초과 시 … 이벤트/알람(D)에 기록된다", §4.7 "자원 조건은
        # 리소스 현황(E)의 Layer 1 계측값과 일관되어야 한다"). 실측을 입힌 **뒤에**
        # 평가해야 선언 숫자가 아니라 계측값이 임계와 비교된다.
        watch = build_resource_watch(self.config.dashboard)
        watch_results = watch.evaluate(snapshot.resources)
        if watch_results:
            # **한 번 평가하고 세 군데로 보낸다** — [D] 경고 사건, [G] 자원 조건,
            # 그리고 기준값을 들고 가는 `resource_watch[]`. 같은 입력을 두 번
            # 판정하면 세 자리가 서로 어긋날 수 있다(AI-O-06 상태 일관성).
            conditions = tuple(r.as_condition() for r in watch_results)
            snapshot = replace(
                snapshot,
                events=snapshot.events + threshold_events(watch_results, at=stamp),
                verdicts=tuple(
                    with_measured_resource_conditions(v, conditions)
                    for v in snapshot.verdicts
                ),
            )
        # [D] 구역은 선언 사건과 패널이 실제로 적은 사건을 함께 본다. 실행 중에
        # 생긴 사건을 빼면 화면은 "그래프에 드러나지 않는 미세한 상태 변화"를
        # 추적할 수 없다(문서 §4.3).
        live = live_event_records(self.recent_events())
        if live:
            snapshot = replace(snapshot, events=snapshot.events + live)
        if pin is not None:
            try:
                snapshot = snapshot.pin(pin or None)
            except GraphInvalid as error:
                raise UiConfigError(f"unknown_task_node:{pin}") from error
        payload = status_snapshot_payload(snapshot, now=stamp)
        # [E] 임계 감시의 판정. **채널 본문이 아니라 이 조립 층에서** 낸다 — 와이어
        # 어휘는 공통 데이터 사전(AI-C-01)에 등재한 이름만 쓰고, `resource_watch` ·
        # `measured_field` 는 아직 등재되지 않았다. 등재되면 채널 본문으로 옮긴다
        # (`docs/integration-handover.md` 에 적어 둔다). 그때까지 구독 채널은 사건과
        # 자원 조건으로 같은 판정을 전달한다 — 판정이 빠지는 것이 아니라 기준 숫자가
        # HTTP 조회에만 있는 상태다.
        payload["resource_watch"] = [_watch_to_payload(r) for r in watch_results]
        counts = snapshot.state_counts()
        resources = snapshot.resources
        # 집계·유휴·미측정은 **파생값**이라는 사실이 드러나도록 따로 담는다. 화면이
        # 다시 계산하지 않아도 되고, 계산해도 같은 답이 나온다.
        payload["derived"] = {
            "task_node_total": counts.total,
            "task_node_counts_by_state": dict(counts.by_state),
            "task_nodes_needing_attention": counts.attention,
            "accelerator_placement": {
                instance_id: list(service_ids)
                for instance_id, service_ids in resources.placement().items()
            },
            "idle_accelerator_instance_ids": [
                a.instance_id for a in resources.idle_accelerators()
            ],
            "unmeasured_accelerator_instance_ids": list(resources.unmeasured_accelerators()),
            # 실측으로 사용률을 얻은 개체. 위 미측정 목록의 여집합이 **아니다** —
            # 선언된 숫자만 있는 개체는 둘 중 어디에도 들지 않는다(AI-O-05).
            "measured_accelerator_instance_ids": list(resources.host_measured_accelerators()),
            # 계측기가 찾았으나 선언에 없는 계측 지점. 비어 있으면 선언이 이 기계에서
            # 읽히는 것을 다 덮었다는 뜻이고, 비어 있지 않으면 **목록이 불완전하다**는
            # 사실이다 — 메우는 길은 선언 추가다(§3 요구사항 2, §4.4).
            "undeclared_accelerator_probe_ids": list(unclaimed),
            # 못 읽은 칸의 사유. 관측 실패는 응답을 멈추지 않고 여기 남는다(AI-O-01).
            HOST_PROBE_STATUS: dict(probe_status),
            "not_measured_indicator_names": [
                i.name for i in resources.not_measured_indicators()
            ],
            "unmet_indicator_names": [i.name for i in resources.unmet_indicators()],
            "unavailable_region_ids": [r.value for r in snapshot.unavailable_regions()],
            "has_external_requests": snapshot.has_external_requests(),
            "mission_elapsed_s": snapshot.mission.elapsed_s(stamp),
        }
        _tag_value_provenance(payload, resources,
                              probe_by_instance=probe_by_instance, board_probe=board_probe)
        return payload

    def _host_readout(self) -> tuple[HostReadout | None, dict[str, str]]:
        """이 기계를 한 번 읽는다. **어떤 실패도 상태 조회를 멈추지 않는다.**

        AI-O-01: "외부 관측 기능 장애가 실제 기능 실행을 중단시키지 않아야 한다."
        계측기 자체가 터지면 그 사실만 사유로 남기고 나머지 구역은 그대로 나간다
        (AI-C-05: 선택 구성요소 결손은 축소이지 실패가 아니다).
        """
        if self._host_reader is None:
            return None, {"host_reader": "tool_missing"}
        try:
            readout = self._host_reader.readout()
        except Exception as error:      # noqa: BLE001 — 관측이 응답을 세우지 않는다
            return None, {"host_reader": f"tool_failed:{type(error).__name__}"}
        return readout, dict(readout.probe_status)


def _purpose_budget(purpose) -> ResourceBudget:
    """A node's budget defaults to what its purpose declared it can afford.

    `ResourceBudget(0, 0)` when nothing is declared — unmeasured, which the
    resolver already treats as "cannot afford anything" rather than silently
    unlimited.
    """
    declared = getattr(purpose, "budget", None) if purpose is not None else None
    return declared or ResourceBudget(compute_units=0.0, memory_mb=0.0)


def _unit_kind(plan: dict | None, unit_id: str) -> str:
    """Which capability a deployed unit serves, from the last applied plan.

    Falls back to the unit id: naming the unit is still more useful than an
    empty column when the plan is not in hand (a service restarted between
    the deploy and the rollback, say).
    """
    for unit in (plan or {}).get("units", ()):
        if unit.get("unit_id") == unit_id:
            return unit.get("kind") or unit_id
    return unit_id


def _action_dict(action) -> dict:
    """A `PlacementAction` in the shape `/api/placement` already returns."""
    return {
        "kind": action.kind,
        "provider_id": action.provider_id,
        "command": action.command,
        "accepted": action.accepted,
        "rejection_reason": action.rejection_reason,
    }


def _spec_of(purpose, kind: str) -> CapabilitySpec | None:
    """The purpose's declaration for one kind, in the shape `_row` expects."""
    declared = purpose.spec(kind)
    if declared is None:  # pragma: no cover - rows come from the purpose
        return None
    return CapabilitySpec(
        kind=declared.kind,
        is_core=declared.is_core,
        requirement=declared.requirement,
        degrade_rank=declared.degrade_rank,
    )


def _reason_data(reason: str) -> str | None:
    parts = (reason or "").split(":", 1)
    return parts[1] if len(parts) == 2 else None


_TAG_LIST_TOKENS = frozenset({"required_hw_tag_missing", "required_runtime_tag_missing"})



def _proposal_verdict(node_id: str, rows: dict, required: frozenset[str],
                      kinds: tuple[str, ...]) -> dict:
    """노드 하나의 판정 — **되는 이유도, 안 되는 이유도, 할 일이 무엇인지도 적는다.**

    상태는 필수 kind 들의 **최악**이다. 선택 kind 결손은 DEGRADED 까지만 내리고
    (AI-C-05) 그 사실이 사유에 남는다.

    왜 후보별 사유까지 읽는가
    -------------------------
    요약 토큰 `no_compatible_provider_within_budget` 은 **두 사실을 한 칸에** 담는다
    (공통 사전이 직접 "providers exist, none fit tags/budget" 이라고 적는다). 그
    둘은 운영자가 할 일이 다르다 — 하드웨어를 들이는 것과 예산을 늘리는 것. 다행히
    선택기는 후보마다 `over_budget` / `required_hw_tag_missing:<태그>` 를 이미 내고
    `_row()` 가 그것을 `alternatives` 로 싣는다. 그래서 **판정을 새로 하지 않고 이미
    나온 판정을 읽어** 둘을 가른다.
    """
    worst, reason = "ACTIVE", ""
    missing: list[str] = []
    over_budget: list[str] = []
    rank = {"ACTIVE": 0, "DEGRADED": 1, "DISABLED": 2}
    for kind in kinds:
        row = rows.get(kind)
        if row is None:
            # 활성 목록에 더했는데도 해소 표에 없다 — 선언이 그 kind 를 모른다.
            if kind in required:
                worst, reason = "DISABLED", f"kind_not_resolved:{kind}"
            continue
        state = str(row.get("state") or "DISABLED")
        if kind not in required and state == "DISABLED":
            # 선택 기능 결손은 정상적인 축소다. 전체를 끌어내리지 않는다.
            if rank[worst] < rank["DEGRADED"]:
                worst, reason = "DEGRADED", f"optional_absent:{kind}"
            continue
        if rank[state] > rank[worst]:
            token = row.get("reason_token") or row.get("reason") or ""
            worst, reason = state, f"{kind}:{token}"
        if state == "DISABLED" and kind in required:
            missing.extend(_missing_tags(row.get("reason_token"), row.get("reason_data")))
            for alternative in row.get("alternatives") or ():
                alt_token = str(alternative.get("reason_token") or "")
                if alt_token == SELECTOR_REASON_OVER_BUDGET:
                    over_budget.append(kind)
                else:
                    missing.extend(_missing_tags(alt_token,
                                                 alternative.get("reason_data")))
    usable = worst in ("ACTIVE", "DEGRADED")
    return {
        "node_id": node_id,
        "state": worst,
        "reason": reason,
        "missing_tags": sorted(set(missing)),
        # 예산이 모자란 kind 들. **없는 태그와 다른 칸**이다 — 할 일이 다르다.
        "over_budget_kinds": sorted(set(over_budget)),
        # **쓸 수 있을 때만 비용을 낸다.** 둘 수 없는 노드에 부분 합을 적으면
        # "여기서는 이만큼 든다" 로 읽히는데, 그 수는 올라가지 못한 몫이 빠진 수다.
        "cost": _proposal_cost(rows, required) if usable else None,
    }


def _proposal_cost(rows: dict, required: frozenset[str]) -> dict | None:
    """필수 kind 들이 고른 provider 비용의 합. 하나도 못 읽으면 `None`(미측정)."""
    total: dict | None = None
    for kind in sorted(required):
        chosen = (rows.get(kind) or {}).get("cost")
        if not isinstance(chosen, dict):
            continue
        total = total or {"compute_units": 0.0, "memory_mb": 0.0}
        total["compute_units"] += float(chosen.get("compute_units") or 0.0)
        total["memory_mb"] += float(chosen.get("memory_mb") or 0.0)
    return total

def _missing_tags(reason_token: str | None, reason_data: str | None) -> list[str]:
    """The tag list behind `required_hw_tag_missing:<a,b>` (selector.py joins
    the missing tags with commas). Empty for any other reason — a budget or
    a missing provider is not fixed by a tag."""
    if reason_token not in _TAG_LIST_TOKENS or not reason_data:
        return []
    return [t for t in reason_data.split(",") if t]


def solo_and_combo_roles(roles: list[str], roles_by_kind: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Which tiers carry a function alone, and the smallest greedy team.

    `solo`: every role (config order) present in `roles_by_kind[k]` for every
    required kind `k`. `combo`: greedy set cover — pick the role covering the
    most still-uncovered kinds (ties → config order), repeat; `[]` when some
    kind is served by no role, because then no team covers it. Deterministic
    by construction: the only inputs are the ordered role list and the
    per-kind served roles (rule documented in `StatusService.functions`).
    """
    kinds = list(roles_by_kind)
    solo = [role for role in roles if all(role in roles_by_kind[k] for k in kinds)]
    if any(not roles_by_kind[k] for k in kinds):
        return solo, []
    uncovered = set(kinds)
    combo: list[str] = []
    while uncovered:
        best_role, best_gain = None, 0
        for role in roles:
            gain = sum(1 for k in uncovered if role in roles_by_kind[k])
            if gain > best_gain:
                best_role, best_gain = role, gain
        if best_role is None:  # pragma: no cover - guarded by the emptiness check above
            return solo, []
        combo.append(best_role)
        uncovered = {k for k in uncovered if best_role not in roles_by_kind[k]}
    return solo, combo


def runtime_instances_from_report(payload: Any) -> dict[str, RuntimeInstance]:
    """`tools/hw_smoke` report JSON → `{device_id: RuntimeInstance}`.

    Reads `results[]` rows shaped either as the data dictionary names them
    (`device_probe_level`, `device_probe_reason`, `probed_at`) or with the
    short names (`level`, `reason`). The deepest level per device decides:
    `healthy = ok`, `health_ttl = HW_SMOKE_LEVEL_TTL_S[level]`,
    `health_checked_at = probed_at`. A row without a numeric `probed_at` is
    skipped — freshness is never given a made-up time. Anything malformed →
    `{}`, never an exception (a bad report must not stop the page).
    """
    if not isinstance(payload, dict):
        return {}
    results = payload.get("results")
    if not isinstance(results, list):
        return {}
    best: dict[str, tuple[int, bool, float, str]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        device_id = row.get("device_id")
        level = row.get("device_probe_level", row.get("level"))
        probed_at = row.get("probed_at")
        if not isinstance(device_id, str) or not device_id:
            continue
        if not isinstance(level, int) or isinstance(level, bool):
            continue
        if not isinstance(probed_at, (int, float)) or isinstance(probed_at, bool):
            continue
        reason = row.get("device_probe_reason", row.get("reason"))
        ok = bool(row.get("ok", False))
        current = best.get(device_id)
        if current is None or level > current[0]:
            best[device_id] = (level, ok, float(probed_at), str(reason) if reason is not None else "")
    return {
        device_id: RuntimeInstance(
            instance_id=device_id,
            deployment_ref=f"hw_smoke:L{level}:{reason}",
            healthy=ok,
            health_ttl=HW_SMOKE_LEVEL_TTL_S.get(level, HW_SMOKE_LEVEL_TTL_S[1]),
            health_checked_at=probed_at,
        )
        for device_id, (level, ok, probed_at, reason) in best.items()
    }


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


#: 실행 상태를 **바꾸는** POST 경로. 조회 전용 모드에서는 이 경로만 막는다.
#: what-if 계열은 가상 조건 비교라 상태를 바꾸지 않으므로 조회에 속한다
#: (기능정의서 §1.1 "모든 조작은 관찰 방식의 변경에 한정된다", AI-O-06).
MUTATING_PATHS: frozenset[str] = frozenset({
    "/api/placement",
    "/api/devices",
    "/api/devices/command",
    "/api/reset",
})

#: 조회 **전용** 경로 — 어느 모드에서도 POST 를 받지 않는다. 기능정의서 §5 "조회
#: 전용 원칙": "화면의 어떠한 조작도 자율행동체의 실행 상태를 변경하지 않아야 한다."
#: 거부는 본문을 읽기 **전에** 한다 — 본문을 먼저 읽으면 거부한 요청의 내용이
#: 처리 경로에 들어온다(AI-O-06: 조회 계약과 제어 계약을 같은 경로에 두지 않는다).
QUERY_ONLY_PATHS: frozenset[str] = frozenset({
    "/api/dashboard",
})

#: 조회 전용 모드에서 변경 요청을 거부한 사유. 화면은 토큰으로 라벨을 찾는다.
REASON_READ_ONLY = "read_only_mode"

#: 조회 전용 경로에 제어를 시도했을 때의 사유 토큰.
REASON_QUERY_ONLY = "query_only_path"

#: 기본은 조회 전용이다 — 운영 화면이 요구하는 쪽을 기본값으로 둔다. 제어까지 쓰려면
#: `--mode review` 로 명시해야 하고, 그 모드는 검토 도구로서만 의도된 것이다.
MODE_VIEW = "view"
MODE_REVIEW = "review"


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
            elif url.path == "/api/residency":
                self._send_json(self.service.residency(self._node_id(query)))
            elif url.path == "/api/devices":
                self._send_json(self.service.device_rows())
            elif url.path == "/api/events":
                self._send_json({"events": self.service.recent_events()})
            elif url.path == "/api/dashboard":
                # 구역 B~I 한 장. `pin` 은 기준 노드 고정이고 관찰 방식의 변경이라
                # 조회에 속한다(기능정의서 §1.1·§2 핵심 상호작용 원칙).
                self._send_json(self.service.dashboard(pin=query.get("pin")))
            elif url.path == "/api/plans":
                self._send_json(
                    self.service.plan_summaries(
                        limit=self._limit(query), correlation_id=query.get("correlation_id") or None
                    )
                )
            elif url.path.startswith("/api/plans/"):
                self._send_json(self.service.plan_detail(url.path[len("/api/plans/"):]))
            else:
                self._send_json({"error": "not_found", "path": url.path}, HTTPStatus.NOT_FOUND)
        except UiConfigError as error:
            self._send_json({"error": str(error)}, self._status_for(error))
        except Exception as error:  # a review tool must show the failure, not die
            self._send_json({"error": f"{type(error).__name__}: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        if url.path in QUERY_ONLY_PATHS:
            # 본문을 읽기 전에 거부한다. 상태 뷰 계약으로는 실행 상태를 바꿀 수
            # 없고, 제어가 필요한 기능은 별도 계약으로 제공한다(AI-O-06).
            self._send_json(
                {"error": REASON_QUERY_ONLY, "path": url.path, "allowed_methods": ["GET"]},
                HTTPStatus.METHOD_NOT_ALLOWED,
            )
            return
        if url.path in MUTATING_PATHS and self.service.mode == MODE_VIEW:
            # 조회 계약과 제어 계약을 같은 경로에 두지 않는다(AI-O-06). 거부는
            # 사유 토큰으로 돌려주고 어느 모드여야 하는지 함께 알린다.
            self._send_json(
                {
                    "error": REASON_READ_ONLY,
                    "path": url.path,
                    "mode": self.service.mode,
                    "required_mode": MODE_REVIEW,
                },
                HTTPStatus.METHOD_NOT_ALLOWED,
            )
            return
        try:
            body = self._read_json()
            if url.path == "/api/whatif":
                self._send_json(self.service.whatif(self._node_id(body), **self._overrides(body)))
            elif url.path == "/api/functions/whatif":
                self._send_json(self.service.whatif_functions(body.get("overrides") or {}))
            elif url.path == "/api/functions/propose":
                # **선언 축 what-if.** 위의 둘은 노드 축이다("이 노드에 태그·예산을
                # 더하면"). 이쪽은 "이 기능을 선언하면 어디에 들어가나" 이고, 그
                # 둘은 다른 질문이다.
                #
                # POST 인 이유는 바꾸기 때문이 아니라 **본문이 필요해서**다 —
                # 이 경로는 아무것도 바꾸지 않는다(선언 파일을 고치지 않는다).
                # 적용은 사람이 하는 별개의 행위다(AI-C-19, AI-L-03).
                from mission_runtime.registry.capability_proposal import (  # noqa: PLC0415
                    ProposalError,
                    assess,
                    proposal_from_dict,
                )

                try:
                    proposal = proposal_from_dict(body.get("proposal") or body)
                except ProposalError as error:
                    # 선언이 규약에 맞지 않는 것과 "둘 곳이 없는" 것은 다른 종류다.
                    self._send_json({"error": str(error),
                                     "reason": "declaration_invalid"}, status=400)
                    return
                self._send_json(assess(proposal, self.service).as_payload())
            elif url.path == "/api/residency":
                self._send_json(
                    self.service.residency(self._node_id(body), link=body.get("link"), **self._overrides(body))
                )
            elif url.path == "/api/residency/whatif":
                self._send_json(
                    self.service.residency_whatif(
                        self._node_id(body), link=body.get("link"), **self._overrides(body)
                    )
                )
            elif url.path == "/api/placement":
                node_id = self._node_id(body)
                plan = self.service.place(node_id, **self._overrides(body), **self._plan_fields(body))
                self._send_json(
                    {
                        "node_id": node_id,
                        "plan_id": plan.plan_id,
                        "correlation_id": plan.correlation_id,
                        "actions": [_action_dict(a) for a in plan.placement_actions],
                        "state": self.service.placement_state(node_id),
                    }
                )
            elif url.path == "/api/devices":
                self._send_json(self.service.register_device(**self._registration(body)))
            elif url.path == "/api/devices/command":
                device_id = self._device_id(body)
                command = body.get("command")
                if not isinstance(command, str) or not command:
                    raise UiConfigError("command: required")
                self._send_json(
                    self.service.device_command(
                        device_id, command, unit_id=body.get("unit_id"), link=body.get("link"),
                        **self._plan_fields(body),
                    )
                )
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
        text = str(error)
        not_found = text.startswith(
            ("unknown_node:", "unknown_device:", "unknown_plan:", "unknown_task_node:")
        )
        return HTTPStatus.NOT_FOUND if not_found else HTTPStatus.BAD_REQUEST

    @staticmethod
    def _limit(query: dict, default: int = 20, maximum: int = 500) -> int:
        raw = query.get("limit")
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError as error:
            raise UiConfigError("limit: must be an integer") from error
        if value < 1:
            raise UiConfigError("limit: must be >= 1")
        return min(value, maximum)

    @staticmethod
    def _plan_fields(body: dict) -> dict:
        """`function_id`, `requester {role, id?}`, `correlation_id` — the plan
        envelope's identity slots. Shape is checked, values are not: who may
        request what is the owner's auth design (§3 "요청자 자리"), so the
        role and id are carried as opaque strings."""
        fields: dict = {}
        function_id = body.get("function_id")
        if function_id is not None:
            if not isinstance(function_id, str) or not function_id:
                raise UiConfigError("function_id: must be a non-empty string")
            fields["function_id"] = function_id
        correlation_id = body.get("correlation_id")
        if correlation_id is not None:
            if not isinstance(correlation_id, str) or not correlation_id:
                raise UiConfigError("correlation_id: must be a non-empty string")
            fields["correlation_id"] = correlation_id
        requester = body.get("requester")
        if requester is not None:
            if not isinstance(requester, dict) or not isinstance(requester.get("role"), str) or not requester["role"]:
                raise UiConfigError("requester: must be {role: str, id?: str}")
            rid = requester.get("id")
            if rid is not None and not isinstance(rid, str):
                raise UiConfigError("requester.id: must be a string")
            fields["requester"] = Requester(role=requester["role"], id=rid)
        return fields

    @staticmethod
    def _node_id(source: dict) -> str:
        node_id = source.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise UiConfigError("node_id: required")
        return node_id

    @staticmethod
    def _device_id(source: dict) -> str:
        device_id = source.get("device_id")
        if not isinstance(device_id, str) or not device_id:
            raise UiConfigError("device_id: required")
        return device_id

    @staticmethod
    def _registration(body: dict) -> dict:
        """Registration fields, whitelisted.

        Whitelisting rather than forwarding `**body` keeps a stray key from
        reaching the registry, and keeps `password` a field this layer names
        exactly once — it is read here and handed straight to the bootstrap,
        never logged, echoed or stored (AI-B-02).
        """
        allowed = (
            "device_id", "address", "username", "purpose", "password",
            "key_path", "node_tags", "role", "port", "access_method", "label",
        )
        unknown = sorted(set(body) - set(allowed))
        if unknown:
            raise UiConfigError(f"unknown registration field(s): {', '.join(unknown)}")
        return {key: body[key] for key in allowed if key in body and body[key] is not None}

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
    parser.add_argument(
        "--mode", choices=(MODE_VIEW, MODE_REVIEW), default=MODE_VIEW,
        help="view=조회 전용(기본), review=조회+제어(검토 도구)",
    )
    parser.add_argument("--control", choices=("local", "k3s"), default="local")
    parser.add_argument("--namespace", default="default", help="--control k3s일 때 네임스페이스")
    parser.add_argument("--verbose", action="store_true", help="HTTP access log 출력")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_ui_config(args.config)
        service = StatusService(config, control_mode=args.control, namespace=args.namespace)
        service.set_mode(args.mode)
    except (UiConfigError, ValueError, OSError) as error:
        print(f"status_ui: {error}", file=sys.stderr)
        return 2

    server = make_server(service, host=args.host, port=args.port, verbose=args.verbose)
    control = service.control_info
    note = f" (요청 {control['requested']} → 실제 {control['active']}: {control['reason']})" if control.get("reason") else ""
    print(
        f"status_ui: {server_url(server)}  mode={service.mode}  "
        f"control={control['active']}{note}",
        flush=True,
    )
    if service.mode == MODE_VIEW:
        print("status_ui: 조회 전용 — 배치·배포·중지·롤백 요청은 405로 거부한다", flush=True)
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
