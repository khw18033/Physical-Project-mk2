"""FC 텔레메트리를 화면으로 — 수신 전용.  `python -m fc_watch --fc tcp:127.0.0.1:5760 --mqtt 127.0.0.1:1883`

MQTT `zoneA/drone/<id>/fcx` (JSON, 5 Hz, 마지막 값 retained)로 낸다. 화면의 「드론 상태판」 노드가 읽는다.
보정 주입기(`rtk_relay.fc_injector --telemetry`)에 같이 태우면 TCP 연결 하나로 둘 다 한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone

from .collector import FcTelemetry

log = logging.getLogger("fc_watch")

SOURCE_SYSTEM = 253   # 수신만 하지만 연결에는 이름이 필요하다 — QGC 255 · MAVSDK 245 · rtk_relay 252 와 다르게


class FcxPublisher:
    """스냅샷을 5 Hz 로 MQTT 에. retained 로 두어 늦게 붙은 화면도 마지막 상태를 바로 받는다."""

    def __init__(self, host: str, port: int, device_id: str = "x500-001", zone: str = "zoneA",
                 period_s: float = 0.2) -> None:
        import paho.mqtt.client as mqtt

        self.topic = f"{zone}/drone/{device_id}/fcx"
        self.device_id, self.zone, self.period_s = device_id, zone, period_s
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fc-watch-{device_id}")
        self.client.connect_async(host, port)
        self.client.loop_start()
        self._last = 0.0

    def maybe_publish(self, tel: FcTelemetry) -> None:
        now = time.time()
        if now - self._last < self.period_s:
            return
        self._last = now
        body = {**tel.snapshot(), "schema_version": "fcx-0.1", "channel": "fcx", "source_id": self.device_id,
                "zone_id": self.zone,
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")}
        self.client.publish(self.topic, json.dumps(body, ensure_ascii=False), qos=0, retain=True)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="fc_watch", description="FC MAVLink → 화면 드론 상태판 (수신 전용)")
    p.add_argument("--fc", default="tcp:127.0.0.1:5760", help="pymavlink 주소 (기본: mavlink-router TCP 5760)")
    p.add_argument("--mqtt", required=True, help="host:port")
    p.add_argument("--device", default="x500-001")
    p.add_argument("--zone", default="zoneA")
    args = p.parse_args(argv)

    from pymavlink import mavutil

    master = mavutil.mavlink_connection(args.fc, source_system=SOURCE_SYSTEM, source_component=191, autoreconnect=True)
    host, _, port = args.mqtt.partition(":")
    pub = FcxPublisher(host, int(port or 1883), args.device, args.zone)
    tel = FcTelemetry()
    log.info("FC %s 를 읽어 %s 로 낸다", args.fc, pub.topic)
    try:
        while True:
            msg = master.recv_match(blocking=True, timeout=0.2)
            if msg is not None:
                tel.on_message(msg)
            pub.maybe_publish(tel)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
