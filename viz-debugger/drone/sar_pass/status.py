"""SAR 상태를 GUI 로 — MQTT `zoneA/drone/<id>/sar` (JSON, retained).

GUI(`viz-debugger/src/physical/sarFeed.ts`)가 이 토픽을 듣는다. 모양은 `drone/README.md` 「화면 ↔ 드론 규약」.
retained 로 두는 이유: 늦게 붙은 화면도 마지막 상태(특히 「캡처 중」)를 즉시 받아야 한다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger("sar_pass.status")


def sar_topic(zone: str, entity_type: str, device_id: str) -> str:
    return f"{zone}/{entity_type}/{device_id}/sar"


class MqttStatusPublisher:
    def __init__(self, host: str = "127.0.0.1", port: int = 1883, device_id: str = "x500-001",
                 zone: str = "zoneA", entity_type: str = "drone", node_id: str = "pi3") -> None:
        import paho.mqtt.client as mqtt

        self.topic = sar_topic(zone, entity_type, device_id)
        self.device_id, self.zone, self.node_id = device_id, zone, node_id
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sar-pass-{device_id}")
        self.client.connect_async(host, port)
        self.client.loop_start()

    def __call__(self, status: dict) -> None:
        body = {
            **status,
            "source_id": self.device_id,
            "node_id": self.node_id,
            "zone_id": self.zone,
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
        }
        self.client.publish(self.topic, json.dumps(body, ensure_ascii=False), qos=0, retain=True)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


class PrintStatus:
    """브로커 없이 돌릴 때 — 상태가 바뀔 때만 한 줄."""

    def __init__(self) -> None:
        self._last = None

    def __call__(self, status: dict) -> None:
        key = (status["state"], status["pass"], status["capturing"])
        if key != self._last:
            self._last = key
            log.info("[status] %s pass=%s/%s capturing=%s", *key[:2], status["passes_total"], key[2])
