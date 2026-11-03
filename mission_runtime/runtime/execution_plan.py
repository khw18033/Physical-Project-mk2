"""One request → one identifiable plan: what was resolved and what was placed.

implements: AI-B-03, AI-C-13, AI-O-02, AI-O-03, AI-C-19

Until now a request's outcome was scattered: `ZoneApplication.resolve()`
returned a table, `PlacementReconciler.apply()` returned actions, and the two
were never tied together under one identifier. A consumer (the status UI's
execution view, an audit reader, the 2026-09-28 "재선택 트레이스") could see
*a* resolution and *some* placement actions but not "these are the result of
that request". This module is the missing envelope, and deliberately nothing
more:

- It records; it does not decide. Resolution stays in `runtime/application.py`,
  placement in `runtime/placement.py`. Wrapping their outputs is the whole job.
- It is in-memory only. Durable storage of execution history is the backend's
  (AI-O-03: 업무 저장소·아카이브 참조는 백엔드), so the log keeps the last N plans
  for the running process and nothing else.
- `requester` is a slot, not a policy. Who may request what is the owner's
  authentication/authorisation design (decided 2026-09-21); here the role and
  id are carried as opaque strings so that design can plug in without changing
  this record.
- Everything in `as_dict()` is an id or a reason token — no display strings —
  so the JSON stays language-neutral (labels are the UI's job).
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from mission_runtime.runtime.application import CapabilityResolution
from mission_runtime.runtime.placement import PlacementAction


@dataclass(frozen=True)
class Requester:
    """Who asked. `role` is free text (`operator`, `edge`, `server`, …) — the
    vocabulary and its permissions belong to the owner's auth design."""

    role: str
    id: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    function_id: str
    created_at: float
    resolutions: tuple[CapabilityResolution, ...]
    placement_actions: tuple[PlacementAction, ...]
    correlation_id: str | None = None
    requester: Requester | None = None
    node_id: str | None = None

    @property
    def served_kinds(self) -> tuple[str, ...]:
        return tuple(r.kind for r in self.resolutions if r.provider is not None)

    @property
    def unserved_kinds(self) -> tuple[str, ...]:
        return tuple(r.kind for r in self.resolutions if r.provider is None)

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "correlation_id": self.correlation_id,
            "function_id": self.function_id,
            "node_id": self.node_id,
            "created_at": self.created_at,
            "requester": None if self.requester is None else {"role": self.requester.role, "id": self.requester.id},
            "resolutions": [
                {
                    "kind": r.kind,
                    "state": r.state.value,
                    "provider_id": None if r.provider is None else r.provider.provider_id,
                    "reason": r.reason,
                    "alternatives": [{"provider_id": a.provider_id, "reason": a.reason} for a in r.alternatives],
                }
                for r in self.resolutions
            ],
            "placement_actions": [
                {
                    "kind": a.kind,
                    "provider_id": a.provider_id,
                    "command": a.command,
                    "accepted": a.accepted,
                    "rejection_reason": a.rejection_reason,
                }
                for a in self.placement_actions
            ],
        }


def build_plan(
    function_id: str,
    resolutions: Mapping[str, CapabilityResolution] | Iterable[CapabilityResolution],
    placement_actions: Iterable[PlacementAction] = (),
    *,
    correlation_id: str | None = None,
    requester: Requester | None = None,
    node_id: str | None = None,
    clock=time.time,
    plan_id: str | None = None,
) -> ExecutionPlan:
    """Wrap a `resolve()` table (or its values) and the reconciler's actions."""
    values = resolutions.values() if isinstance(resolutions, Mapping) else resolutions
    return ExecutionPlan(
        plan_id=plan_id or f"plan-{uuid.uuid4().hex[:12]}",
        function_id=function_id,
        created_at=clock(),
        resolutions=tuple(values),
        placement_actions=tuple(placement_actions),
        correlation_id=correlation_id,
        requester=requester,
        node_id=node_id,
    )


class ExecutionPlanLog:
    """Last-N plans of this process, newest last. Not a store — a window."""

    def __init__(self, capacity: int = 200) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._plans: "OrderedDict[str, ExecutionPlan]" = OrderedDict()

    def record(self, plan: ExecutionPlan) -> ExecutionPlan:
        self._plans[plan.plan_id] = plan
        while len(self._plans) > self._capacity:
            self._plans.popitem(last=False)
        return plan

    def get(self, plan_id: str) -> ExecutionPlan | None:
        return self._plans.get(plan_id)

    def latest(self, n: int = 20) -> tuple[ExecutionPlan, ...]:
        return tuple(list(self._plans.values())[-n:][::-1])

    def by_correlation(self, correlation_id: str) -> tuple[ExecutionPlan, ...]:
        return tuple(p for p in self._plans.values() if p.correlation_id == correlation_id)

    def __len__(self) -> int:
        return len(self._plans)
