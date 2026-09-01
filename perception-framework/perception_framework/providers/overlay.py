"""Secure overlay network providers (current deployment: Tailscale).

implements: AI-C-17, AI-C-12, AI-O-04

원칙 #10: 구역 엣지와 서버 사이의 모든 구간은 공개 인터넷을 경유하지 않고 보안
오버레이 네트워크 위에서만 연결한다. AI-C-17은 그 오버레이의 *제품*이 아니라
"연결 가능 여부와 피어 상태를 공통 인터페이스로 조회할 수 있어야 한다"만 요구하므로,
Tailscale CLI 호출은 이 파일 밖으로 나가지 않는다.

Overlay state is deliberately a third, separate signal: a device may have
a healthy task session inside its own zone while the overlay to the server
is down, and those two situations call for different responses (AI-O-04).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum


class OverlayState(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    UNAVAILABLE = "UNAVAILABLE"  # 오버레이 자체가 이 노드에 설치/구성되지 않음


@dataclass(frozen=True)
class PeerStatus:
    peer_id: str
    online: bool
    addresses: tuple[str, ...] = ()


class TailscaleOverlayProvider:
    """NetworkOverlayProvider backed by the Tailscale CLI.

    Uses the CLI rather than a client library so a 말단 that never joins
    the overlay carries no extra runtime dependency (원칙 #12, AI-B-10).
    Every probe failure degrades to DISCONNECTED/UNAVAILABLE instead of
    raising: losing the overlay must reduce remote capability, not crash
    the node (AI-C-17, AI-C-11).
    """

    def __init__(self, *, binary: str = "tailscale", timeout_s: int = 5) -> None:
        self._binary = binary
        self._timeout_s = timeout_s

    # --- NetworkOverlayProvider -----------------------------------------
    def is_connected(self) -> bool:
        return self.state() is OverlayState.CONNECTED

    def can_reach(self, peer_id: str) -> bool:
        peer = self.peers().get(peer_id)
        return bool(peer and peer.online)

    def peers(self) -> dict[str, PeerStatus]:
        status = self._status()
        if not status:
            return {}
        result: dict[str, PeerStatus] = {}
        for entry in (status.get("Peer") or {}).values():
            peer_id = _peer_name(entry)
            if not peer_id:
                continue
            result[peer_id] = PeerStatus(
                peer_id=peer_id,
                online=bool(entry.get("Online")),
                addresses=tuple(entry.get("TailscaleIPs") or ()),
            )
        return result

    # --- extra state, kept out of the Protocol ---------------------------
    def state(self) -> OverlayState:
        if shutil.which(self._binary) is None:
            return OverlayState.UNAVAILABLE
        status = self._status()
        if status is None:
            return OverlayState.UNAVAILABLE
        backend = str(status.get("BackendState", "")).lower()
        return OverlayState.CONNECTED if backend == "running" else OverlayState.DISCONNECTED

    def self_id(self) -> str | None:
        status = self._status() or {}
        return _peer_name(status.get("Self") or {})

    def _status(self) -> dict | None:
        try:
            proc = subprocess.run(
                [self._binary, "status", "--json"],
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        try:
            return json.loads(proc.stdout)
        except ValueError:
            return None


def _peer_name(entry: dict) -> str | None:
    name = entry.get("HostName") or entry.get("DNSName")
    return str(name).rstrip(".") if name else None


class StaticOverlayProvider:
    """Overlay provider for deployments that are already inside one trusted
    network segment, and for tests.

    Exists so "no overlay product installed" is an expressible, valid
    configuration rather than a missing dependency (AI-C-11).
    """

    def __init__(self, *, connected: bool = True, peers: dict[str, bool] | None = None) -> None:
        self._connected = connected
        self._peers = dict(peers or {})

    def is_connected(self) -> bool:
        return self._connected

    def can_reach(self, peer_id: str) -> bool:
        return self._connected and bool(self._peers.get(peer_id, False))

    def peers(self) -> dict[str, PeerStatus]:
        return {peer: PeerStatus(peer, online and self._connected) for peer, online in self._peers.items()}

    # --- test hooks -------------------------------------------------------
    def set_connected(self, value: bool) -> None:
        self._connected = value

    def set_peer(self, peer_id: str, online: bool) -> None:
        self._peers[peer_id] = online


class OverlayAwareRemoteGate:
    """Decides whether a remote-hosted optional capability may be selected.

    Three inputs stay distinct on purpose (AI-O-04, AI-C-17):
      - the backend's integrated device availability (AI-C-10),
      - the overlay's own reachability to that peer,
      - the capability's local health, checked by the registry.

    Only the combination gates selection; none of them is re-derived here.
    """

    def __init__(self, overlay) -> None:
        self._overlay = overlay

    def may_select(self, peer_id: str, backend_integrated_available: bool) -> bool:
        if not backend_integrated_available:
            return False
        if not self._overlay.is_connected():
            return False
        return self._overlay.can_reach(peer_id)

    def unavailable_reason(self, peer_id: str, backend_integrated_available: bool) -> str | None:
        """Why a remote capability is excluded — distinguishable causes so
        an overlay outage is never misreported as a dead device."""
        if not backend_integrated_available:
            return "device_unavailable"
        if not self._overlay.is_connected():
            return "overlay_disconnected"
        if not self._overlay.can_reach(peer_id):
            return "peer_unreachable"
        return None
