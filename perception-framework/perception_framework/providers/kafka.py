"""Real Kafka `TransportProvider` for the 구역 엣지 ↔ 서버 backbone.

implements: AI-C-06, AI-C-04, AI-C-12, AI-C-14, AI-O-03

원칙 #11: 엣지에는 Kafka 서버를 설치하지 않는다. This module is a Kafka
*client*, used by edge processes to talk to the server's broker (and by
the bridge in `bridge.py`) — it never starts or assumes a local broker.

원칙 #17: Kafka는 장기 저장소가 아니다. `replay_reference()` therefore
returns a short-term offset pointer meant for reproduction inside the
retention window only (AI-O-03), not a durable record locator.

Same Protocol as `fakes.InMemoryTransportProvider` and
`mqtt.MqttTransportProvider`; `kafka-python` may only be imported here.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from perception_framework.common.data_plane import DataKind, DataPlane, assert_routable, policy_for

# Framework-level delivery vocabulary -> Kafka producer acks. Kept as the
# same three names MQTT uses so callers never learn which backend they got.
_ACKS_MAP = {"at_most_once": 0, "at_least_once": "all", "exactly_once": "all"}


@dataclass(frozen=True)
class ReplayReference:
    """Short-term pointer into the transport log (AI-O-03).

    Valid only while the record is inside Kafka's retention window; long
    term reproduction must use a business store or archive reference
    instead (원칙 #17).
    """

    topic: str
    partition: int
    offset: int


class KafkaTransportProvider:
    """TransportProvider backed by a Kafka broker.

    Failures never propagate to callers: a backbone outage degrades the
    edge to local operation, it does not crash it (AI-C-11, AI-N-01).
    """

    def __init__(
        self,
        bootstrap_servers: str = "127.0.0.1:9092",
        *,
        client_id: str = "perception-framework",
        group_id: str | None = None,
        consumer_timeout_ms: int = 1000,
    ) -> None:
        self._bootstrap = bootstrap_servers
        self._client_id = client_id
        self._group_id = group_id or f"{client_id}-group"
        self._consumer_timeout_ms = consumer_timeout_ms
        self._producer = None
        self._consumers: list = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._connected = False
        self.last_replay_reference: ReplayReference | None = None

    # --- lifecycle -----------------------------------------------------
    def connect(self, timeout_s: float = 10.0) -> bool:
        from kafka import KafkaProducer  # local import: only this module knows the client library
        from kafka.errors import KafkaError

        try:
            self._producer = KafkaProducer(
                bootstrap_servers=self._bootstrap,
                client_id=self._client_id,
                acks="all",
                api_version_auto_timeout_ms=int(timeout_s * 1000),
                request_timeout_ms=int(timeout_s * 1000),
            )
            self._connected = self._producer.bootstrap_connected()
        except (KafkaError, Exception):
            self._connected = False
        return self._connected

    def close(self) -> None:
        self._stop.set()
        for consumer in self._consumers:
            try:
                consumer.close()
            except Exception:
                pass
        for thread in self._threads:
            thread.join(timeout=3)
        if self._producer is not None:
            try:
                self._producer.close(timeout=3)
            except Exception:
                pass
        self._connected = False

    # --- TransportProvider ---------------------------------------------
    def publish(self, topic: str, payload: bytes, *, qos: str = "at_least_once") -> None:
        if self._producer is None:
            return
        try:
            future = self._producer.send(topic, payload)
            self._connected = True
            if _ACKS_MAP.get(qos) != 0:
                # Delivery-guaranteed data waits for the broker ack and keeps
                # the resulting offset as a short-term replay pointer.
                metadata = future.get(timeout=10)
                self.last_replay_reference = ReplayReference(
                    metadata.topic, metadata.partition, metadata.offset
                )
        except Exception:
            self._connected = False
            return

    def subscribe(self, topic: str, handler: Callable[[bytes], None]) -> None:
        from kafka import KafkaConsumer

        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=self._bootstrap,
                group_id=self._group_id,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                consumer_timeout_ms=self._consumer_timeout_ms,
            )
        except Exception:
            return

        self._consumers.append(consumer)

        def pump() -> None:
            while not self._stop.is_set():
                try:
                    for record in consumer:
                        if self._stop.is_set():
                            break
                        try:
                            handler(record.value)
                        except Exception:
                            # One subscriber failing must not stop the others
                            # or the transport itself (AI-C-11).
                            continue
                except Exception:
                    break

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        self._threads.append(thread)

    def is_connected(self) -> bool:
        """Whether this client can currently reach the broker.

        `bootstrap_connected()` alone is not a liveness signal: the client
        closes its bootstrap socket once cluster metadata is cached, so it
        goes False on a perfectly healthy producer. Callers that gate on
        this (the edge bridge does) would then silently drop traffic, so
        the cached state from the last successful connect/send is used as
        the fallback.
        """
        if self._producer is None:
            return False
        try:
            if self._producer.bootstrap_connected():
                return True
        except Exception:
            return False
        return self._connected

    # --- data-plane guard ----------------------------------------------
    def publish_task_data(self, topic: str, payload: bytes, kind: DataKind) -> None:
        """Publish with an explicit plane check (AI-C-14).

        Media payloads are refused outright — 영상 픽셀은 별도 미디어 경로를
        사용한다 (금지 사항).
        """
        assert_routable(kind, DataPlane.TASK)
        policy = policy_for(kind)
        self.publish(topic, payload, qos="at_least_once" if policy.delivery_guaranteed else "at_most_once")
