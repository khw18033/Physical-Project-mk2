"""Pi 쪽 — 노트북이 UDP 로 보낸 RTCM3 를 GPS_RTCM_DATA 로 감싸 FC(PX4)에 넣는다.

  python -m rtk_relay.fc_injector --listen 0.0.0.0:14660 --fc tcp:127.0.0.1:5760 --mqtt 127.0.0.1:1883

- FC 쪽 길은 Pi 팀 mavlink-router 의 **TCP 5760**(QGC 가 붙는 곳)이다. 라우터는 TCP 손님을 여럿 받으므로
  설정을 바꿀 필요가 없다. GPS_RTCM_DATA 는 대상이 없는(브로드캐스트) 메시지라 라우터가 FC 로 넘긴다.
- PX4 는 받은 보정을 GPS 드라이버로 그대로 흘린다(별도 파라미터 없음). fix 가 RTK Float/Fixed 로 오르는 것은
  화면의 「RTK 상태」(드론 에이전트의 gps.fix_type)로 확인한다.
- 상태를 MQTT `zoneA/drone/<id>/rtcm`(retained, 1초마다)로 낸다 — 화면 「RTK 상태」 노드가 「보정 수신 중/끊김」을 그린다.
- **QGC 의 RTK 기능과 같이 쓰지 않는다** (보정이 두 번 들어간다).
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import time
from datetime import datetime, timezone

from .inject import PymavlinkInjector, RtcmInjector
from .rtcm3 import Framer
from .stats import RtcmStats

log = logging.getLogger("rtk_relay.fc_injector")

# MAVLink 에서 이 프로그램의 이름 — QGC(255) · MAVSDK(245) 와 겹치지 않게.
SOURCE_SYSTEM = 252
SOURCE_COMPONENT = 191   # MAV_COMP_ID_ONBOARD_COMPUTER


def parse_addr(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    return host or "0.0.0.0", int(port)


class StatusPublisher:
    def __init__(self, host: str, port: int, device_id: str, zone: str, entity_type: str = "drone") -> None:
        import paho.mqtt.client as mqtt

        self.topic = f"{zone}/{entity_type}/{device_id}/rtcm"
        self.device_id, self.zone = device_id, zone
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"rtk-relay-{device_id}")
        self.client.connect_async(host, port)
        self.client.loop_start()

    def __call__(self, body: dict) -> None:
        body = {**body, "schema_version": "rtcm-0.1", "channel": "rtcm", "source_id": self.device_id,
                "zone_id": self.zone,
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")}
        self.client.publish(self.topic, json.dumps(body, ensure_ascii=False), qos=0, retain=True)


def connect_fc(url: str):  # noqa: ANN201
    from pymavlink import mavutil

    log.info("FC 연결 %s (sysid %d)", url, SOURCE_SYSTEM)
    return mavutil.mavlink_connection(url, source_system=SOURCE_SYSTEM, source_component=SOURCE_COMPONENT,
                                      autoreconnect=True)


def run(listen: tuple[str, int] | None, injector: RtcmInjector, master=None, publish=None,  # noqa: ANN001
        stop_after_s: float | None = None, on_fc_message=None, tick=None, external: str | None = None) -> RtcmStats:
    """listen 이 None 이면 보정은 받지도 넣지도 않는다 — 다른 프로그램(레이더 브리지 cansar_pi.py)이 넣는 중.
    그래도 FC 메시지는 읽어 상태판 텔레메트리를 내고, 화면에는 「보정은 다른 곳에서」(mode=external)를 알린다."""
    sock = None
    if listen is not None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(listen)
        sock.settimeout(0.2)
    framers: dict[tuple[str, int], Framer] = {}
    stats = RtcmStats()
    started = time.time()
    last_status = 0.0
    last_print = 0.0
    sender: str | None = None
    if sock is not None:
        log.info("UDP %s:%d 에서 보정을 기다린다", *listen)
    else:
        log.info("보정 중계 끔 — %s 가 FC 에 넣는다. 상태판 텔레메트리만 낸다", external or "다른 프로그램")
    try:
        while stop_after_s is None or time.time() - started < stop_after_s:
            if sock is None:
                data, addr = b"", None
                if master is None:
                    time.sleep(0.2)
            else:
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    data, addr = b"", None
            if addr is not None:
                sender = f"{addr[0]}:{addr[1]}"
                framer = framers.setdefault(addr, Framer())
                for frame in framer.feed(data):      # 받은 쪽에서도 CRC 를 다시 본다
                    if injector.send_frame(frame):
                        stats.note(frame)
            if master is not None:
                # 라우터가 FC 메시지를 TCP 로도 밀어준다 — 읽어 비우지 않으면 버퍼가 차서 끊긴다.
                # `--telemetry` 면 버리지 않고 상태판 수집기(fc_watch)에 넘긴다 — TCP 연결 하나로 둘 다.
                while (msg := master.recv_msg()) is not None:
                    if on_fc_message is not None:
                        on_fc_message(msg)
            if tick is not None:
                tick()
            now = time.time()
            if now - last_status >= 1.0:
                last_status = now
                if publish is not None:
                    try:
                        publish({**stats.snapshot(), "sender": sender, "mode": "external" if sock is None else "relay",
                                 "external": external if sock is None else None,
                                 "injected_messages": injector.sent_messages,
                                 "dropped_oversize": injector.dropped_oversize,
                                 "bad_crc": sum(f.bad_crc for f in framers.values())})
                    except Exception:  # noqa: BLE001
                        log.exception("상태 보고 실패")
            if now - last_print >= 5.0:
                last_print = now
                log.info("%s · FC 로 %d 메시지", stats.line(), injector.sent_messages)
    finally:
        if sock is not None:
            sock.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="rtk_relay.fc_injector", description="UDP RTCM3 → GPS_RTCM_DATA → FC")
    p.add_argument("--listen", default="0.0.0.0:14660",
                   help="노트북이 보내는 UDP 포트. 'none' 이면 보정 중계를 끈다(레이더 브리지가 넣을 때) — 텔레메트리는 그대로")
    p.add_argument("--fc", default="tcp:127.0.0.1:5760",
                   help="pymavlink 주소. 기본은 mavlink-router TCP 5760. 'none' 이면 FC 에 안 넣고 세기만 한다")
    p.add_argument("--mqtt", help="host:port — 주면 화면에 「보정 수신 중/끊김」을 보낸다")
    p.add_argument("--device", default="x500-001")
    p.add_argument("--zone", default="zoneA")
    p.add_argument("--telemetry", action="store_true",
                   help="FC 메시지로 「드론 상태판」 텔레메트리(fcx)도 낸다 (--mqtt 필요)")
    args = p.parse_args(argv)

    master = None
    if args.fc == "none":
        injector = RtcmInjector(lambda *_: None)
    else:
        master = connect_fc(args.fc)
        injector = PymavlinkInjector(master)
    publish = None
    if args.mqtt:
        host, _, port = args.mqtt.partition(":")
        publish = StatusPublisher(host, int(port or 1883), args.device, args.zone)
    on_fc_message = tick = None
    if args.telemetry and args.mqtt and master is not None:
        from fc_watch.__main__ import FcxPublisher
        from fc_watch.collector import FcTelemetry

        tel = FcTelemetry()
        fcx = FcxPublisher(host, int(port or 1883), args.device, args.zone)
        on_fc_message = tel.on_message
        tick = lambda: fcx.maybe_publish(tel)  # noqa: E731
    try:
        off = args.listen.strip().lower() in ("none", "off", "")
        run(None if off else parse_addr(args.listen), injector, master, publish, on_fc_message=on_fc_message, tick=tick,
            external="레이더 브리지(cansar.service)" if off else None)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
