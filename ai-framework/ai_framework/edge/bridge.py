"""Bidirectional 말단↔서버 bridge running on the 구역 엣지.

implements: AI-C-06, AI-C-14, AI-B-10

원칙 #11: "엣지에는 Kafka 서버를 설치하지 않는다. 엣지는 MQTT Broker와 서버 Kafka를
연결하는 양방향 Bridge를 둔다. 서버에는 MQTT Broker를 두지 않는다."

The bridge is written against the `TransportProvider` Protocol on both
sides, so it is not actually an "MQTT-to-Kafka" component in code — it
is an "uplink transport to downlink transport" component. Tests exercise
it with two in-memory fakes as well as with the real broker pair, and the
class itself cannot tell the difference. That is the requirement
(AI-C-06: AI 로직은 MQTT·Kafka API를 직접 호출하지 않는다).
"""

from __future__ import annotations

import hashlib
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from ai_framework.common.data_plane import DataKind, DataPlane, policy_for


@dataclass(frozen=True)
class TopicRoute:
    """One mapping between a device-side topic and a server-side topic.

    `kind` decides the delivery policy applied on the far side, so control
    commands keep their stricter contract across the hop (AI-C-14).
    """

    device_topic: str
    server_topic: str
    kind: DataKind

    def __post_init__(self) -> None:
        if policy_for(self.kind).plane is not DataPlane.TASK:
            # Only task-plane data crosses this bridge. Observability has
            # its own path and media pixels never touch either (원칙 #10).
            raise ValueError(f"{self.kind.value} does not belong on the task bridge")


@dataclass
class BridgeStats:
    uplink: int = 0
    downlink: int = 0
    dropped: dict[str, int] = field(default_factory=dict)


class EdgeTransportBridge:
    """Forwards task/control messages between the device-side and
    server-side transports.

    Neither side is required to be healthy for the bridge to start: if the
    server link is down, device-side traffic is counted as dropped and the
    edge keeps operating locally rather than failing (AI-C-11, AI-N-01).
    """

    def __init__(
        self,
        device_transport,
        server_transport,
        routes: list[TopicRoute],
        *,
        echo_memory: int = 1024,
    ) -> None:
        self._device = device_transport
        self._server = server_transport
        self._routes = list(routes)
        self.stats = BridgeStats()
        # Both sides are subscribed to the topics this bridge also
        # publishes to, so without a guard every forwarded message comes
        # straight back and is forwarded again — an infinite loop that
        # would saturate both brokers. Remember what we just emitted and
        # refuse to re-forward it.
        self._lock = threading.Lock()
        self._echoes: deque[str] = deque(maxlen=echo_memory)
        self._echo_set: set[str] = set()

    def start(self) -> None:
        for route in self._routes:
            self._device.subscribe(route.device_topic, self._uplink_handler(route))
            self._server.subscribe(route.server_topic, self._downlink_handler(route))

    def _uplink_handler(self, route: TopicRoute) -> Callable[[bytes], None]:
        """말단 → 엣지 → 서버 (업무 데이터)."""

        def handler(payload: bytes) -> None:
            if self._is_own_echo(route.device_topic, payload):
                return
            if not self._server.is_connected():
                self._count_drop("server_link_down")
                return
            self._remember(route.server_topic, payload)
            self._server.publish(route.server_topic, payload, qos=self._qos(route))
            self.stats.uplink += 1

        return handler

    def _downlink_handler(self, route: TopicRoute) -> Callable[[bytes], None]:
        """서버 → 엣지 → 말단 (제어 명령)."""

        def handler(payload: bytes) -> None:
            if self._is_own_echo(route.server_topic, payload):
                return
            if not self._device.is_connected():
                self._count_drop("device_link_down")
                return
            self._remember(route.device_topic, payload)
            self._device.publish(route.device_topic, payload, qos=self._qos(route))
            self.stats.downlink += 1

        return handler

    def _qos(self, route: TopicRoute) -> str:
        return "at_least_once" if policy_for(route.kind).delivery_guaranteed else "at_most_once"

    @staticmethod
    def _fingerprint(topic: str, payload: bytes) -> str:
        return f"{topic}:{hashlib.sha256(payload).hexdigest()}"

    def _remember(self, topic: str, payload: bytes) -> None:
        key = self._fingerprint(topic, payload)
        with self._lock:
            if len(self._echoes) == self._echoes.maxlen and self._echoes:
                self._echo_set.discard(self._echoes[0])
            self._echoes.append(key)
            self._echo_set.add(key)

    def _is_own_echo(self, topic: str, payload: bytes) -> bool:
        """True when this exact message is one the bridge itself emitted.

        Consumed once: a genuine retransmission of the same payload later
        is forwarded normally.
        """
        key = self._fingerprint(topic, payload)
        with self._lock:
            if key not in self._echo_set:
                return False
            self._echo_set.discard(key)
            try:
                self._echoes.remove(key)
            except ValueError:
                pass
            return True

    def _count_drop(self, reason: str) -> None:
        self.stats.dropped[reason] = self.stats.dropped.get(reason, 0) + 1
