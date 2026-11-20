"""Secure overlay network providers (current deployment: Tailscale).

implements: AI-C-04,  AI-O-04

원칙 #10: 구역 엣지와 서버 사이의 모든 구간은 공개 인터넷을 경유하지 않고 보안
오버레이 네트워크 위에서만 연결한다. AI-C-04은 그 오버레이의 *제품*이 아니라
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
    the node (AI-C-04, AI-C-05).
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

    def self_addresses(self) -> tuple[str, ...]:
        """이 기계가 **오버레이에서 가지는 주소들**. IPv4 가 앞이다.

        여기 있는 이유: 다른 기계가 붙는 주소를 아는 쪽은 오버레이다. 도구가
        `ip addr` 를 따로 읽으면 같은 사실에 주인이 둘이 되고, 그 둘은 공개
        인터넷을 경유하지 않는다는 규칙(원칙 #10)을 서로 다르게 지킨다 —
        오버레이 밖 주소를 안내하는 쪽이 생긴다.
        """
        self_block = (self._status() or {}).get("Self") or {}
        addresses = [str(value) for value in self_block.get("TailscaleIPs") or ()]
        return tuple(sorted(addresses, key=lambda value: (":" in value, value)))

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
    configuration rather than a missing dependency (AI-C-05).
    """

    def __init__(self, *, connected: bool = True, peers: dict[str, bool] | None = None,
                 addresses: tuple[str, ...] = ()) -> None:
        self._connected = connected
        self._peers = dict(peers or {})
        self._addresses = tuple(addresses)

    def is_connected(self) -> bool:
        return self._connected

    def can_reach(self, peer_id: str) -> bool:
        return self._connected and bool(self._peers.get(peer_id, False))

    def peers(self) -> dict[str, PeerStatus]:
        return {peer: PeerStatus(peer, online and self._connected) for peer, online in self._peers.items()}

    # --- test hooks -------------------------------------------------------
    def set_connected(self, value: bool) -> None:
        self._connected = value

    def self_addresses(self) -> tuple[str, ...]:
        """선언된 주소. 오버레이 제품이 깔려 있지 않은 배치가 정상이므로 기본은
        **빈 튜플**이고 그것이 "모른다" 다 — 빈 문자열이나 `0.0.0.0` 이 아니다."""
        return self._addresses

    def set_peer(self, peer_id: str, online: bool) -> None:
        self._peers[peer_id] = online


class OverlayAwareRemoteGate:
    """Decides whether a remote-hosted optional capability may be selected.

    Three inputs stay distinct on purpose (AI-O-04, AI-C-04):
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


#: 모든 인터페이스에 붙는다는 뜻의 주소들. 이 값으로 **안내하면 안 된다** —
#: 듣는 주소이고 붙는 주소가 아니다.
WILDCARD_HOSTS: frozenset[str] = frozenset({"0.0.0.0", "::", "*", ""})
#: 주소를 알 수 없을 때 안내문에 넣는 자리표. 거짓 주소를 적지 않는다.
HOST_UNKNOWN = "<이 기계의 오버레이 주소>"


def advertised_host(bind_host: str, overlay=None) -> tuple[str, str | None]:
    """안내문에 적을 주소와 그 출처.

    `--host 0.0.0.0` 으로 열어 둔 게이트웨이가 안내문에도 `0.0.0.0` 을 적으면,
    **다른 노트북이 그 주소로 붙을 수 없다**(실측 2026-11-20: 안내문을 그대로
    따르면 실패한다). 그렇다고 아무 인터페이스 주소나 적을 수도 없다 — 구역 엣지와
    서버 사이는 공개 인터넷을 경유하지 않고 **보안 오버레이 위에서만** 연결한다
    (원칙 #10). 그래서 와일드카드일 때 안내하는 주소는 오버레이가 말하는 것이고,
    오버레이를 쓸 수 없으면 주소를 **지어내지 않고** 자리표를 넣는다.

    돌려주는 둘째 값은 출처다(`overlay` 또는 `None`) — 안내문이 "어디서 온
    주소인가" 를 말할 수 있어야 운영자가 틀린 망에 붙지 않는다.
    """
    if bind_host not in WILDCARD_HOSTS:
        return bind_host, None
    addresses = ()
    if overlay is not None:
        try:
            addresses = tuple(overlay.self_addresses())
        except Exception:                                       # noqa: BLE001
            # 오버레이를 물어볼 수 없는 것은 "주소가 없다" 가 아니라 "모른다" 다.
            addresses = ()
    for address in addresses:
        if ":" not in address:                                  # IPv4 를 먼저 쓴다
            return address, "overlay"
    if addresses:
        return f"[{addresses[0]}]", "overlay"                    # IPv6 는 괄호로
    return HOST_UNKNOWN, None
