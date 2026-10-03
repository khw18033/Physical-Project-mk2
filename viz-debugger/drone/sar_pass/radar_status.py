"""레이더 상태 → 화면 (MQTT `zoneA/drone/<id>/radar`, JSON, retained, 1 Hz). 레이더(cansar) 쪽이 이것을 불러 쓴다.

    from sar_pass.radar_status import RadarStatusPublisher
    pub = RadarStatusPublisher("127.0.0.1", 1883, device_id="x500-001")
    ...
    pub.update(state="recording", recording=True, file="cap_0003.bin", pulses_per_s=199.8, dropped=0,
               buffer_pct=12.5, temp_c=48.0, time_source="pps", pps_locked=True)   # 1 초마다 (바뀐 칸만 줘도 된다)
    pub.close()

규약 전체는 `RADAR_INTERFACE.md`. 화면(viz-debugger `src/physical/radarFeed.ts`)이 이 모양을 읽는다.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

SCHEMA = "radar-0.1"
STATES = ("idle", "armed", "recording", "error")
FIELDS = ("state", "recording", "file", "pulses_per_s", "dropped", "buffer_pct", "temp_c", "time_source", "pps_locked",
          "last_error", "disk_free_gb", "files_this_flight")


def radar_topic(device_id: str, zone: str = "zoneA", entity_type: str = "drone") -> str:
    return f"{zone}/{entity_type}/{device_id}/radar"


def make_body(device_id: str, **fields) -> dict:  # noqa: ANN003
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(f"규약에 없는 칸: {sorted(unknown)}")
    if "state" in fields and fields["state"] not in STATES:
        raise ValueError(f"state 는 {STATES} 중 하나")
    return {"schema_version": SCHEMA, "channel": "radar", "source_id": device_id, **fields, "time": time.time(),
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")}


class RadarStatusPublisher:
    """마지막 값을 기억해 두고 1 초마다(또는 update 때) 낸다. 레이더 프로그램이 멎으면 화면이 「끊김」으로 안다."""

    def __init__(self, host: str = "127.0.0.1", port: int = 1883, device_id: str = "x500-001", zone: str = "zoneA",
                 period_s: float = 1.0, client=None) -> None:  # noqa: ANN001
        self.topic = radar_topic(device_id, zone)
        self.device_id = device_id
        self.period_s = period_s
        self.state: dict = {"state": "idle", "recording": False}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        if client is None:
            import paho.mqtt.client as mqtt
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"radar-status-{device_id}")
            client.connect_async(host, port)
            client.loop_start()
        self.client = client
        threading.Thread(target=self._loop, name="radar-status", daemon=True).start()

    def update(self, **fields) -> dict:  # noqa: ANN003
        with self._lock:
            body = make_body(self.device_id, **{**self.state, **fields})
            self.state.update(fields)
        self.client.publish(self.topic, json.dumps(body, ensure_ascii=False), qos=0, retain=True)
        return body

    def _loop(self) -> None:
        while not self._stop.wait(self.period_s):
            self.update()

    def close(self) -> None:
        self._stop.set()
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass
