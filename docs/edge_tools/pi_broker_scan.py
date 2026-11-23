#!/usr/bin/env python3
"""파이 브로커 읽기 점검 (2026-11-20) — 엣지 (가) 브리지 설계 전에 쓴다.

각 파이의 Mosquitto(1883)에 **구독자로만** 붙어 정한 초 동안 어떤 토픽이 흐르는지 센다.
아무것도 발행하지 않는다. 결과는 표준출력으로만 낸다(파일은 부르는 쪽이 남긴다).

주소는 데이터 스트림의 hosts.local.json 을 그대로 읽는다(소스 이름 → 파이 주소).
실행 (WSL, data_stream 폴더에서 데이터 스트림 venv 로):
  ./venv/bin/python "<이 파일>" --seconds 20
"""
import argparse
import json
import os
import threading
import time
from collections import OrderedDict

import paho.mqtt.client as mqtt

# 데이터 스트림 가이드의 소스 이름 → 기기 (브로커가 있는 것만 — pi6 · pi11~13 은 브로커가 없다)
TARGETS = [("robot1", "pi7"), ("robot2", "pi1"), ("drone", "pi3"), ("drone2", "ds5"), ("a2", "pi10")]
SAMPLE_LAST = {"status", "state", "heartbeat"}   # 이 채널만 첫 건을 보여 준다(frame 같은 큰 것은 안 찍는다)
SAMPLE_CHARS = 400


def make_client(cid):
    if hasattr(mqtt, "CallbackAPIVersion"):                      # paho-mqtt 2.x
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid, clean_session=True)
    return mqtt.Client(client_id=cid, clean_session=True)        # paho-mqtt 1.x


def rc_failed(rc):
    failed = getattr(rc, "is_failure", None)
    return bool(failed) if failed is not None else rc != 0


def scan(name, dev, host, port, seconds):
    print("=" * 72)
    print("== %s (%s) %s:%d" % (name, dev, host, port), flush=True)
    stats = OrderedDict()
    info = {"connected": "응답 없음", "version": None}
    lock = threading.Lock()
    cli = make_client("edge-scan-%s-%d" % (name, os.getpid()))

    def on_connect(client, userdata, flags, rc, *rest):
        if rc_failed(rc):
            info["connected"] = "거부 (%s)" % rc
            return
        info["connected"] = "붙음"
        client.subscribe([("#", 0), ("$SYS/broker/version", 0)])

    def on_message(client, userdata, msg):
        if msg.topic == "$SYS/broker/version":
            info["version"] = msg.payload.decode("utf-8", "replace")
            return
        with lock:
            s = stats.get(msg.topic)
            if s is None:
                s = stats[msg.topic] = {"n": 0, "retained": 0, "max_bytes": 0, "sample": None}
            s["n"] += 1
            if msg.retain:
                s["retained"] += 1
            s["max_bytes"] = max(s["max_bytes"], len(msg.payload))
            if s["sample"] is None and msg.topic.rsplit("/", 1)[-1] in SAMPLE_LAST:
                try:
                    s["sample"] = msg.payload.decode("utf-8")[:SAMPLE_CHARS]
                except UnicodeDecodeError:
                    s["sample"] = "(이진 %d B)" % len(msg.payload)

    cli.on_connect = on_connect
    cli.on_message = on_message
    t0 = time.time()
    try:
        cli.connect(host, port, keepalive=30)
    except Exception as e:  # 이름 못 풂 · 거부 · 시간 초과
        print("접속 실패: %s: %s" % (type(e).__name__, e), flush=True)
        return
    cli.loop_start()
    time.sleep(seconds)
    cli.loop_stop()
    try:
        cli.disconnect()
    except Exception:
        pass
    print("접속: %s · 브로커 판: %s · 들은 시간 %.0f초" % (info["connected"], info["version"], time.time() - t0))
    with lock:
        items = list(stats.items())
    if not items:
        print("(받은 토픽 없음)", flush=True)
        return
    print("%7s %7s %9s  %s" % ("건수", "retain", "최대 B", "토픽"))
    for topic, s in items:
        print("%7d %7d %9d  %s" % (s["n"], s["retained"], s["max_bytes"], topic))
    for topic, s in items:
        if s["sample"]:
            print("--- 첫 건 %s" % topic)
            print(s["sample"])
    print("", flush=True)


def main():
    ap = argparse.ArgumentParser(description="파이 브로커 읽기 점검 (발행 없음)")
    ap.add_argument("--hosts", default="hosts.local.json", help="데이터 스트림의 주소 파일 (기본 %(default)s)")
    ap.add_argument("--seconds", type=float, default=20.0, help="브로커마다 들을 초 (기본 %(default)s)")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()
    with open(args.hosts, encoding="utf-8") as f:
        hosts = json.load(f)
    print("주소 파일: %s" % os.path.abspath(args.hosts))
    for name, dev in TARGETS:
        host = hosts.get(name)
        if not host:
            print("=" * 72)
            print("== %s (%s) 주소 없음 — hosts 파일에 이 이름이 비어 있다" % (name, dev), flush=True)
            continue
        scan(name, dev, host, args.port, args.seconds)


if __name__ == "__main__":
    main()
