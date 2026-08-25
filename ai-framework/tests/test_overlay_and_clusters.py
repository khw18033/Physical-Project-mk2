"""tests for: AI-C-17, AI-B-11, AI-O-04, AI-C-12
covers: overlay abstraction and separate signal, server/edge control planes
        behind one contract, control-plane loss does not stop the rest
"""

import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

from ai_framework.execution.control import LocalControlSupervisor, TargetStatus
from ai_framework.providers.adapters import ControlProvider, NetworkOverlayProvider
from ai_framework.providers.overlay import (
    OverlayAwareRemoteGate,
    OverlayState,
    StaticOverlayProvider,
    TailscaleOverlayProvider,
)
from ai_framework.runtime.clusters import ClusterBinding, MultiClusterControlProvider, PlacementRequest

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "ai_framework"

# --- AI-C-17 overlay abstraction ------------------------------------------


def test_both_overlay_implementations_satisfy_the_protocol():
    assert isinstance(StaticOverlayProvider(), NetworkOverlayProvider)
    assert isinstance(TailscaleOverlayProvider(), NetworkOverlayProvider)


def test_overlay_product_name_appears_only_in_its_own_module():
    """AI-C-17: 상위 코드는 특정 오버레이 제품 API에 의존하지 않는다."""
    offenders = []
    for path in PACKAGE_DIR.rglob("*.py"):
        with open(path, "rb") as handle:
            for token in tokenize.tokenize(handle.readline):
                if token.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                if "tailscale" in token.string.lower() and path.name != "overlay.py":
                    offenders.append(f"{path.name}:{token.start[0]}")
    assert offenders == []


def test_missing_overlay_binary_reports_unavailable_rather_than_raising():
    provider = TailscaleOverlayProvider(binary="tailscale-does-not-exist")

    assert provider.state() is OverlayState.UNAVAILABLE
    assert provider.is_connected() is False
    assert provider.peers() == {}
    assert provider.can_reach("server-1") is False


def test_static_overlay_expresses_a_deployment_without_any_overlay_product():
    provider = StaticOverlayProvider(connected=True, peers={"server-1": True})

    assert provider.is_connected() is True
    assert provider.can_reach("server-1") is True
    assert provider.can_reach("unknown-peer") is False


def test_overlay_loss_is_reported_separately_from_device_availability():
    """AI-O-04: 오버레이 단절과 장치 사용 불가를 구분해서 보고한다."""
    overlay = StaticOverlayProvider(connected=True, peers={"server-1": True})
    gate = OverlayAwareRemoteGate(overlay)

    assert gate.may_select("server-1", True) is True
    assert gate.unavailable_reason("server-1", True) is None

    overlay.set_connected(False)
    assert gate.may_select("server-1", True) is False
    assert gate.unavailable_reason("server-1", True) == "overlay_disconnected"

    overlay.set_connected(True)
    assert gate.unavailable_reason("server-1", False) == "device_unavailable"

    overlay.set_peer("server-1", False)
    assert gate.unavailable_reason("server-1", True) == "peer_unreachable"


@pytest.mark.skipif(shutil.which("tailscale") is None, reason="tailscale CLI not installed")
def test_real_tailscale_status_is_readable_when_installed():
    provider = TailscaleOverlayProvider()

    state = provider.state()

    assert state in tuple(OverlayState)
    assert isinstance(provider.peers(), dict)


# --- AI-B-11 server + edge control planes ---------------------------------


def two_cluster_router():
    server = LocalControlSupervisor()
    edge = LocalControlSupervisor()
    router = MultiClusterControlProvider(
        [
            ClusterBinding("server", server, frozenset({"server", "central"})),
            ClusterBinding("edge-a", edge, frozenset({"zone-edge", "gpu"})),
        ]
    )
    return router, server, edge


def test_router_satisfies_the_same_control_contract_as_a_single_plane():
    router, _, _ = two_cluster_router()

    assert isinstance(router, ControlProvider)
    assert isinstance(LocalControlSupervisor(), ControlProvider)


def test_placement_decides_the_cluster_and_callers_never_name_one():
    router, server, edge = two_cluster_router()

    router.request("start", "central-aggregator", {"placement": PlacementRequest(frozenset({"server"}))})
    router.request("start", "zone-perception", {"placement": PlacementRequest(frozenset({"zone-edge"}))})

    assert router.cluster_of("central-aggregator") == "server"
    assert router.cluster_of("zone-perception") == "edge-a"
    assert server.get_status("central-aggregator") is TargetStatus.RUNNING
    assert edge.get_status("zone-perception") is TargetStatus.RUNNING


def test_preferred_tags_rank_but_never_exclude():
    router, _, _ = two_cluster_router()

    binding = router.select_cluster(PlacementRequest(preferred_tags=frozenset({"gpu"})))

    assert binding.cluster_id == "edge-a"
    # 선호 조건이 어디에도 없더라도 배치 자체는 가능하다.
    assert router.select_cluster(PlacementRequest(preferred_tags=frozenset({"tpu"}))) is not None


def test_unsatisfiable_required_tag_is_rejected_not_crashed():
    router, _, _ = two_cluster_router()

    result = router.request("start", "x", {"placement": PlacementRequest(frozenset({"mainframe"}))})

    assert result.accepted is False
    assert result.rejection_reason == "no_available_control_plane"


def test_one_control_plane_going_down_leaves_the_other_usable():
    """AI-B-11: 한쪽 제어면이 사용 불가여도 나머지는 계속 동작한다."""

    class DeadPlane(LocalControlSupervisor):
        def is_available(self):
            return False

    server, edge = DeadPlane(), LocalControlSupervisor()
    router = MultiClusterControlProvider(
        [
            ClusterBinding("server", server, frozenset({"server"})),
            ClusterBinding("edge-a", edge, frozenset({"zone-edge"})),
        ]
    )

    assert router.available_clusters() == ["edge-a"]
    edge_result = router.request("start", "zone-perception", {"placement": PlacementRequest(frozenset({"zone-edge"}))})
    server_result = router.request("start", "central-aggregator", {"placement": PlacementRequest(frozenset({"server"}))})

    assert edge_result.accepted is True
    assert server_result.accepted is False
    assert server_result.rejection_reason == "no_available_control_plane"


def test_already_placed_units_keep_their_cluster_across_commands():
    router, _, edge = two_cluster_router()
    router.request("start", "zone-perception", {"placement": PlacementRequest(frozenset({"zone-edge"}))})

    router.request("restart", "zone-perception")

    assert router.cluster_of("zone-perception") == "edge-a"
    assert edge.get_status("zone-perception") is TargetStatus.RUNNING


def test_audit_and_trace_stay_separate_in_the_router_too():
    router, _, _ = two_cluster_router()

    router.request("start", "x", {"placement": PlacementRequest(frozenset({"server"}))}, requested_by="op-9")

    assert router.audit_log[0].requested_by == "op-9"
    assert router.trace_log[0].latency_ms >= 0


def test_kubectl_context_targeting_keeps_clusters_independent():
    """서버·엣지 클러스터는 별개 클러스터다 (원칙 #11 개정)."""
    from ai_framework.providers.k3s import K3sControlProvider

    server_plane = K3sControlProvider(namespace="aif-server", kubectl="kubectl-missing")
    edge_plane = K3sControlProvider(namespace="aif-edge", kubectl="kubectl-missing")

    assert server_plane._namespace != edge_plane._namespace
    assert server_plane.is_available() is False  # 없는 CLI -> 예외 아닌 False
