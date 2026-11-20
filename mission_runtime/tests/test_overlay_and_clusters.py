"""implements: AI-C-04, AI-B-11, AI-O-04
covers: overlay abstraction and separate signal, server/edge control planes
        behind one contract, control-plane loss does not stop the rest
"""

import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

from mission_runtime.execution.control import LocalControlSupervisor, TargetStatus
from mission_runtime.providers.adapters import ControlProvider, NetworkOverlayProvider
from mission_runtime.providers.overlay import (
    OverlayAwareRemoteGate,
    OverlayState,
    StaticOverlayProvider,
    TailscaleOverlayProvider,
)
from mission_runtime.runtime.clusters import ClusterBinding, MultiClusterControlProvider, PlacementRequest

PACKAGE_DIR = Path(__file__).resolve().parents[1]

# --- AI-C-04 overlay abstraction ------------------------------------------


def test_both_overlay_implementations_satisfy_the_protocol():
    assert isinstance(StaticOverlayProvider(), NetworkOverlayProvider)
    assert isinstance(TailscaleOverlayProvider(), NetworkOverlayProvider)


def test_overlay_product_name_appears_only_in_its_own_module():
    """AI-C-04: 상위 코드는 특정 오버레이 제품 API에 의존하지 않는다."""
    from conftest import package_py_files

    offenders = []
    for path in package_py_files():
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
    from mission_runtime.providers.k3s import K3sControlProvider

    server_plane = K3sControlProvider(namespace="aif-server", kubectl="kubectl-missing")
    edge_plane = K3sControlProvider(namespace="aif-edge", kubectl="kubectl-missing")

    assert server_plane._namespace != edge_plane._namespace
    assert server_plane.is_available() is False  # 없는 CLI -> 예외 아닌 False


# --------------------------------------------------------------- 안내할 주소
# `--host 0.0.0.0` 으로 열어 둔 게이트웨이가 안내문에도 `0.0.0.0` 을 적으면 다른
# 노트북이 그 주소로 붙을 수 없다(2026-11-20 실측 — 안내문을 그대로 따르면 실패한다).

def test_a_concrete_bind_address_is_advertised_as_it_is():
    from mission_runtime.providers.overlay import advertised_host

    assert advertised_host("127.0.0.1") == ("127.0.0.1", None)
    assert advertised_host("192.168.1.10") == ("192.168.1.10", None)


def test_a_wildcard_bind_is_advertised_as_the_overlay_address():
    """듣는 주소가 아니라 **붙는 주소**를 적는다. 그 주소를 아는 쪽은 오버레이다."""
    from mission_runtime.providers.overlay import (
        StaticOverlayProvider,
        advertised_host,
    )

    overlay = StaticOverlayProvider(addresses=("100.83.37.9", "fd7a:115c::1"))
    assert advertised_host("0.0.0.0", overlay) == ("100.83.37.9", "overlay")


def test_ipv4_comes_first_and_ipv6_is_bracketed():
    from mission_runtime.providers.overlay import (
        StaticOverlayProvider,
        advertised_host,
    )

    only_v6 = StaticOverlayProvider(addresses=("fd7a:115c::1",))
    assert advertised_host("::", only_v6) == ("[fd7a:115c::1]", "overlay")


def test_without_an_overlay_no_address_is_invented():
    """오버레이 제품이 없는 배치는 정상이다(AI-C-05). 그때 주소를 **지어내면**
    운영자가 공개 인터넷 쪽 주소로 붙을 수 있다(원칙 #10)."""
    from mission_runtime.providers.overlay import (
        HOST_UNKNOWN,
        StaticOverlayProvider,
        advertised_host,
    )

    assert advertised_host("0.0.0.0") == (HOST_UNKNOWN, None)
    assert advertised_host("0.0.0.0", StaticOverlayProvider()) == (HOST_UNKNOWN, None)


def test_an_overlay_that_cannot_be_asked_is_unknown_not_empty():
    """물어볼 수 없는 것은 "주소가 없다" 가 아니라 "모른다" 다."""
    from mission_runtime.providers.overlay import HOST_UNKNOWN, advertised_host

    class Exploding:
        def self_addresses(self):
            raise OSError("tailscaled 가 죽었다")

    assert advertised_host("0.0.0.0", Exploding()) == (HOST_UNKNOWN, None)


def test_the_tailscale_provider_reads_its_addresses_from_the_status_it_already_parses():
    """`ip addr` 를 따로 읽지 않는다 — 같은 사실의 주인이 둘이 되면 한쪽이
    오버레이 밖 주소를 안내한다."""
    from mission_runtime.providers.overlay import TailscaleOverlayProvider

    provider = TailscaleOverlayProvider()
    provider._status = lambda: {                      # noqa: SLF001
        "Self": {"HostName": "box",
                 "TailscaleIPs": ["fd7a:115c::1", "100.83.37.9"]}}
    assert provider.self_addresses() == ("100.83.37.9", "fd7a:115c::1")


def test_an_unavailable_tailscale_reports_no_address_rather_than_raising():
    from mission_runtime.providers.overlay import TailscaleOverlayProvider

    provider = TailscaleOverlayProvider(binary="tailscale-not-installed")
    provider._status = lambda: None                   # noqa: SLF001
    assert provider.self_addresses() == ()
