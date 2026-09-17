"""Placement bridge: capability resolution -> execution-control start/stop.

implements: AI-B-04, AI-B-03, AI-B-06, AI-C-05, AI-C-13, AI-O-02

`ZoneApplication.resolve()` decides *which* provider serves each capability
kind; `ResourceAdaptiveReconfigurer` re-runs that decision when resources
move (observe -> re-resolve -> event). This module is the other half of the
loop — bind -> deploy: it turns a resolution table into the minimal set of
`ControlProvider` calls that makes the running workloads match it.

Two things are deliberately kept out of here (원칙 #1, #2):

- No orchestrator knowledge. The reconciler only ever calls the
  `ControlProvider` Protocol (`request("start"|"stop", target_id, params)`);
  whether that is `LocalControlSupervisor`, `K3sControlProvider` or
  something else is the caller's provider choice (AI-B-03, AI-B-11).
- No vendor enum. A provider's placement constraint is its free-form
  `required_hw_tags`; `node_selector_for` maps them 1:1 to labels using the
  K8s NFD/Device-Plugin naming convention the tags already follow
  (docs/ai/design/external-technology-decisions.md §11.5).

AI-B-04: "기능 배치 시 필수 자원과 선호 자원을 구분하고 ... 선호 자원이 없으면
호환 가능한 일반 자원으로 대체". Hence only *required* tags become scheduling
constraints. A preferred tag turned into a `nodeSelector` label would exclude
every node that could still run the provider — preference is a ranking term
in the selector, never a constraint here.

AI-C-05: one rejected placement is one rejected action. The loop continues
with the next kind, and the rejected kind simply stays unbound so the next
`apply` retries it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from perception_framework.contracts.profile import CompatibilityProfile
from perception_framework.runtime.application import CapabilityResolution

LABEL_PREFIX = "aif.io/"

# Kubernetes label *name* segment: 1–63 chars of [A-Za-z0-9._-], starting and
# ending alphanumeric. The tags this framework already uses (`compute.gpu`,
# `platform.uav`, `sensor.sonar`) satisfy it unchanged.
_LABEL_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,61}[A-Za-z0-9])?$")

IN_PROCESS = "in_process"


def node_selector_for(profile: CompatibilityProfile) -> dict[str, str]:
    """One `aif.io/<tag>: "true"` label per **required** hardware tag.

    Preferred tags are never included (AI-B-04). Raises `ValueError` for a
    tag that is not a legal label name, so a typo in a registration surfaces
    at bind time rather than as an orchestrator rejection later.
    """
    selector: dict[str, str] = {}
    for tag in profile.required_hw_tags:
        if not isinstance(tag, str) or not _LABEL_NAME.match(tag):
            raise ValueError(f"invalid_placement_tag:{tag!r}")
        selector[f"{LABEL_PREFIX}{tag}"] = "true"
    return selector


@dataclass(frozen=True)
class PlacementAction:
    """One control call (or in-process acknowledgement) the reconciler made."""

    kind: str
    provider_id: str
    command: str  # "start" | "stop" | "in_process"
    accepted: bool
    rejection_reason: str | None = None


class PlacementReconciler:
    """Makes the deployed workloads match a resolution table, one kind at a time.

    `deployment_params` maps provider_id -> the params the control provider
    needs to start it (at least `image`; optionally `command`, ...). A
    provider absent from it runs in this very process — it is never started
    or stopped through the control provider, only acknowledged once as an
    `in_process` action so the caller can see it was considered.
    """

    def __init__(
        self,
        control,
        *,
        deployment_params: Mapping[str, dict] | None = None,
        observability=None,
        requested_by: str = "placement_reconciler",
    ) -> None:
        self._control = control
        self._deployment_params: dict[str, dict] = {
            pid: dict(params) for pid, params in (deployment_params or {}).items()
        }
        self._observability = observability
        self._requested_by = requested_by
        self._bound: dict[str, str] = {}

    # --- queries -----------------------------------------------------------
    def bound_provider(self, kind: str) -> str | None:
        return self._bound.get(kind)

    def is_deployable(self, provider_id: str) -> bool:
        return provider_id in self._deployment_params

    # --- reconcile ---------------------------------------------------------
    def apply(self, resolutions: Mapping[str, CapabilityResolution]) -> tuple[PlacementAction, ...]:
        """Diff `resolutions` against the last applied binding and act on it.

        Per kind: unchanged -> no call; provider swapped -> stop old, start
        new; went to `provider is None` (or vanished from the table) -> stop
        old; newly appeared -> start. A rejected start leaves the kind
        unbound and touches nothing else (AI-C-05).
        """
        actions: list[PlacementAction] = []

        desired: dict[str, str | None] = {
            kind: (res.provider.provider_id if res.provider is not None else None)
            for kind, res in resolutions.items()
        }
        # A kind the deployment no longer resolves at all is desired-absent:
        # the table *is* the desired state, so its workload must go too.
        for kind in list(self._bound):
            desired.setdefault(kind, None)

        for kind, new_pid in desired.items():
            old_pid = self._bound.get(kind)
            if new_pid == old_pid:
                continue

            if old_pid is not None:
                self._bound.pop(kind, None)
                if self.is_deployable(old_pid):
                    actions.append(self._stop(kind, old_pid))

            if new_pid is None:
                continue

            if not self.is_deployable(new_pid):
                self._bound[kind] = new_pid
                actions.append(self._report(PlacementAction(kind, new_pid, IN_PROCESS, True)))
                continue

            action = self._start(kind, new_pid, resolutions[kind].provider.compatibility)
            if action.accepted:
                self._bound[kind] = new_pid
            actions.append(action)

        return tuple(actions)

    # --- control calls -----------------------------------------------------
    def _start(self, kind: str, provider_id: str, compatibility: CompatibilityProfile) -> PlacementAction:
        params = dict(self._deployment_params[provider_id])
        try:
            selector = node_selector_for(compatibility)
        except ValueError as exc:
            # A malformed tag is this provider's problem alone; it must not
            # stop the loop for the other kinds (AI-C-05).
            return self._report(PlacementAction(kind, provider_id, "start", False, str(exc)))
        if selector:
            params["node_selector"] = selector
        return self._request(kind, provider_id, "start", params)

    def _stop(self, kind: str, provider_id: str) -> PlacementAction:
        # A rejected stop (e.g. `unknown_target`) still unbinds the kind: the
        # desired state no longer contains it, and re-issuing the stop on the
        # next apply would only repeat the same rejection.
        return self._request(kind, provider_id, "stop", None)

    def _request(self, kind: str, provider_id: str, command: str, params: dict | None) -> PlacementAction:
        try:
            result = self._control.request(
                command, provider_id, params, requested_by=self._requested_by
            )
        except Exception as exc:  # a provider that raises is a rejection, not a crash
            return self._report(
                PlacementAction(kind, provider_id, command, False, f"control_error:{type(exc).__name__}")
            )
        accepted = bool(getattr(result, "accepted", False))
        reason = None if accepted else getattr(result, "rejection_reason", None) or "rejected"
        return self._report(PlacementAction(kind, provider_id, command, accepted, reason))

    # --- reporting (AI-O-02) ------------------------------------------------
    def _report(self, action: PlacementAction) -> PlacementAction:
        if self._observability is None:
            return action
        try:
            self._observability.record_event(
                "placement_applied",
                "info" if action.accepted else "warning",
                {
                    "capability_kind": action.kind,
                    "provider_id": action.provider_id,
                    "command": action.command,
                    "accepted": action.accepted,
                    "rejection_reason": action.rejection_reason,
                },
            )
        except Exception:
            # 관측 실패가 배치 자체를 막아서는 안 된다 (AI-O-01).
            pass
        return action
