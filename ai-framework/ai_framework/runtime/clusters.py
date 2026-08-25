"""Routing execution control across the server and edge control planes.

implements: AI-B-11, AI-B-03, AI-B-05, AI-C-12

원칙 #11(개정): 오케스트레이션은 서버와 구역 엣지 양쪽에 제어면을 둔다. 두 클러스터는
별개이며 "상위 코드는 어느 클러스터를 쓰는지 알 필요가 없다".

So this router implements the same ControlProvider contract as both
`LocalControlSupervisor` and `K3sControlProvider`, and decides the target
cluster from *placement data*, never from a hardcoded name. A caller says
"start this execution unit"; where it lands is a deployment concern.

AI-B-11 also requires that one control plane being unusable must not stop
what is already running elsewhere — so an unreachable cluster produces a
rejection for new requests only, and `available_clusters()` lets the
caller re-place work rather than fail globally.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_framework.execution.control import AuditEntry, ControlResult, TargetStatus, TraceEntry


@dataclass(frozen=True)
class ClusterBinding:
    """One control plane this deployment may place work on.

    `tags` describe what the cluster offers (e.g. "server", "zone-edge",
    "gpu"); placement matches against these instead of against a cluster
    name, so adding a third cluster changes data only.
    """

    cluster_id: str
    provider: object
    tags: frozenset[str] = field(default_factory=frozenset)

    def is_available(self) -> bool:
        checker = getattr(self.provider, "is_available", None)
        if checker is None:
            return True
        try:
            return bool(checker())
        except Exception:
            return False


@dataclass(frozen=True)
class PlacementRequest:
    """Where an execution unit needs to run, expressed as conditions."""

    required_tags: frozenset[str] = field(default_factory=frozenset)
    preferred_tags: frozenset[str] = field(default_factory=frozenset)


class MultiClusterControlProvider:
    """ControlProvider that fans out to several control planes."""

    def __init__(self, bindings: list[ClusterBinding]) -> None:
        self._bindings = list(bindings)
        self._placed: dict[str, str] = {}  # target_id -> cluster_id
        self.audit_log: list[AuditEntry] = []
        self.trace_log: list[TraceEntry] = []

    # --- placement --------------------------------------------------------
    def available_clusters(self) -> list[str]:
        return [b.cluster_id for b in self._bindings if b.is_available()]

    def select_cluster(self, placement: PlacementRequest | None = None) -> ClusterBinding | None:
        placement = placement or PlacementRequest()
        candidates = [
            b
            for b in self._bindings
            if b.is_available() and placement.required_tags.issubset(b.tags)
        ]
        if not candidates:
            return None
        # Preferred tags rank, never exclude — same rule as provider
        # selection (AI-B-04).
        return max(candidates, key=lambda b: len(placement.preferred_tags & b.tags))

    def cluster_of(self, target_id: str) -> str | None:
        return self._placed.get(target_id)

    # --- ControlProvider ---------------------------------------------------
    def request(
        self,
        command: str,
        target_id: str,
        params: dict | None = None,
        *,
        requested_by: str = "unknown",
    ) -> ControlResult:
        import time

        started = time.time()
        self.audit_log.append(AuditEntry(command, target_id, requested_by, started))
        params = dict(params or {})
        placement = params.pop("placement", None)

        binding = self._binding_for(target_id, placement)
        if binding is None:
            result = ControlResult(False, None, rejection_reason="no_available_control_plane")
        else:
            result = binding.provider.request(command, target_id, params, requested_by=requested_by)
            if result.accepted and command in ("start", "restart"):
                self._placed[target_id] = binding.cluster_id
            elif result.accepted and command == "stop":
                self._placed.pop(target_id, None)

        self.trace_log.append(TraceEntry(command, target_id, (time.time() - started) * 1000, started))
        return result

    def get_status(self, target_id: str) -> TargetStatus:
        cluster_id = self._placed.get(target_id)
        for binding in self._bindings:
            if cluster_id is not None and binding.cluster_id != cluster_id:
                continue
            if not binding.is_available():
                continue
            status = binding.provider.get_status(target_id)
            if status is TargetStatus.RUNNING:
                return status
        return TargetStatus.STOPPED

    def _binding_for(self, target_id: str, placement) -> ClusterBinding | None:
        cluster_id = self._placed.get(target_id)
        if cluster_id is not None:
            for binding in self._bindings:
                if binding.cluster_id == cluster_id and binding.is_available():
                    return binding
        return self.select_cluster(placement)
