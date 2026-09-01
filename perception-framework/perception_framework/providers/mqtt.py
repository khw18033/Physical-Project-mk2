"""Real MQTT `TransportProvider` — the first concrete replacement for a
fake, proving upper-layer code does not change when infrastructure does.

implements: AI-C-06, AI-C-04, AI-C-12, AI-C-14

AI-C-06 / 원칙 #10: 말단↔구역 엣지 업무·제어·하트비트는 현재 배포에서 MQTT를
사용한다. 다만 "AI 로직은 MQTT·Kafka API를 직접 호출하지 않고 동일한 업무 메시지
계약을 사용해야 한다" — so this module is the *only* place `paho` may be
imported, and it implements exactly the same Protocol as
`fakes.InMemoryTransportProvider`.

QoS mapping keeps the framework's vocabulary ("at_most_once" /
"at_least_once" / "exactly_once") rather than MQTT's numeric levels, so
a Kafka or DDS implementation can honour the same contract later.
"""

from __future__ import annotations

import threading
from typing import Callable

from perception_framework.common.data_plane import DataKind, DataPlane, assert_routable, policy_for

_QOS_MAP = {"at_most_once": 0, "at_least_once": 1, "exactly_once": 2}


class MqttTransportProvider:
    """TransportProvider backed by an MQTT broker.

    Connection failures never raise out of `publish`/`subscribe`: a
    transport outage must degrade the caller, not crash it (AI-C-11).
    Callers observe the outage through `is_connected()`.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1883,
        *,
        client_id: str = "",
        keepalive: int = 30,
        last_will_topic: str | None = None,
        last_will_payload: bytes = b"offline",
    ) -> None:
        import paho.mqtt.client as mqtt  # local import: only this module may know the client library

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv5,
        )
        self._host = host
        self._port = port
        self._keepalive = keepalive
        self._connected = threading.Event()
        self._handlers: dict[str, list[Callable[[bytes], None]]] = {}

        if last_will_topic is not None:
            # Device-death signal must stay an individual state, never be
            # folded into a metric summary (원칙 #14, AI-O-04).
            self._client.will_set(last_will_topic, last_will_payload, qos=1, retain=True)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # --- lifecycle -----------------------------------------------------
    def connect(self, timeout_s: float = 5.0) -> bool:
        try:
            self._client.connect(self._host, self._port, keepalive=self._keepalive)
        except Exception:
            return False
        self._client.loop_start()
        return self._connected.wait(timeout_s)

    def close(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self._connected.clear()

    # --- TransportProvider ---------------------------------------------
    def publish(self, topic: str, payload: bytes, *, qos: str = "at_least_once") -> None:
        try:
            self._client.publish(topic, payload, qos=_QOS_MAP.get(qos, 1))
        except Exception:
            return

    def subscribe(self, topic: str, handler: Callable[[bytes], None]) -> None:
        self._handlers.setdefault(topic, []).append(handler)
        try:
            self._client.subscribe(topic, qos=1)
        except Exception:
            return

    def is_connected(self) -> bool:
        return self._connected.is_set()

    # --- data-plane guard ----------------------------------------------
    def publish_task_data(self, topic: str, payload: bytes, kind: DataKind) -> None:
        """Publish with an explicit plane check.

        Refuses media payloads outright so video pixels can never reach a
        task/observability message path (금지 사항, AI-C-14).
        """
        assert_routable(kind, DataPlane.TASK)
        policy = policy_for(kind)
        qos = "at_least_once" if policy.delivery_guaranteed else "at_most_once"
        self.publish(topic, payload, qos=qos)

    # --- callbacks ------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            return
        self._connected.set()
        for topic in self._handlers:
            client.subscribe(topic, qos=1)

    def _on_disconnect(self, client, userdata, *args, **kwargs) -> None:
        self._connected.clear()

    def _on_message(self, client, userdata, message) -> None:
        for topic, handlers in self._handlers.items():
            if _topic_matches(topic, message.topic):
                for handler in handlers:
                    try:
                        handler(message.payload)
                    except Exception:
                        # One subscriber's failure must not stop the others
                        # or the transport itself (AI-C-11).
                        continue


def _topic_matches(subscription: str, topic: str) -> bool:
    """MQTT wildcard match for dispatching to locally kept handlers."""
    if subscription == topic:
        return True
    sub_parts = subscription.split("/")
    top_parts = topic.split("/")
    for i, part in enumerate(sub_parts):
        if part == "#":
            return True
        if i >= len(top_parts):
            return False
        if part != "+" and part != top_parts[i]:
            return False
    return len(sub_parts) == len(top_parts)
