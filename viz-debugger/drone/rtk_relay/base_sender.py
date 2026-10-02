"""노트북 쪽 — 베이스 수신기(USB 시리얼)의 RTCM3 를 Pi 로 UDP 전송한다.

  python -m rtk_relay.base_sender --port COM5 --baud 115200 --to 192.168.43.10:14660   (Windows)
  python -m rtk_relay.base_sender --port /dev/ttyACM0 --to pi5.local:14660              (Linux)
  python -m rtk_relay.base_sender --file base.rtcm --to 127.0.0.1:14660                 (기록 재생 — 시험용)

베이스는 미리 RTCM3 를 내보내도록 설정돼 있어야 한다(u-blox 면 u-center 에서 Survey-in 또는 고정 좌표 +
1005 · 1077 · 1087 · 1097 · 1127 · 1230 출력). CRC 가 맞는 프레임만 보낸다. 다른 출력(NMEA 등)이 섞여도 걸러진다.

**QGC 의 RTK 기능과 같이 쓰지 않는다** — 둘 다 같은 베이스를 열 수 없고, 같이 넣으면 FC 에 보정이 두 번 들어간다.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

from .rtcm3 import Framer
from .stats import RtcmStats


def parse_addr(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    return host or "127.0.0.1", int(port)


def open_source(args: argparse.Namespace):  # noqa: ANN201
    if args.file:
        return open(args.file, "rb")
    import serial  # pyserial

    return serial.Serial(args.port, args.baud, timeout=0.2)


def reopen_serial(args: argparse.Namespace):  # noqa: ANN201
    """USB 가 빠졌다 꽂히면 다시 연다 — 2초마다 시도. 그 사이 보정은 끊기지만 스크립트는 안 죽는다."""
    while True:
        try:
            src = open_source(args)
            print(f"[base_sender] {args.port} 다시 열었다", flush=True)
            return src
        except OSError as exc:
            print(f"[base_sender] {args.port} 열기 실패 ({exc}) — 2초 뒤 다시", flush=True)
            time.sleep(2.0)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rtk_relay.base_sender", description="베이스 RTCM3 → Pi (UDP)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--port", help="베이스 시리얼 포트 (COM5, /dev/ttyACM0 …)")
    src.add_argument("--file", help="RTCM3 기록 파일 재생 (시험용)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--to", required=True, help="Pi 주소 host:port (fc_injector 의 --listen 과 같은 포트)")
    p.add_argument("--rate", type=float, default=1.0, help="--file 재생 속도(초당 프레임 묶음 간격 조절용)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    dest = parse_addr(args.to)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    framer = Framer()
    stats = RtcmStats()
    source = open_source(args)
    last_print = 0.0
    print(f"[base_sender] {args.port or args.file} → udp://{dest[0]}:{dest[1]}", flush=True)
    send_errors = 0
    try:
        while True:
            try:
                chunk = source.read(1024)
            except OSError as exc:            # serial.SerialException 도 OSError 다 — USB 빠짐
                print(f"[base_sender] 베이스 읽기 실패 ({exc})", flush=True)
                source.close()
                source = reopen_serial(args)
                continue
            if not chunk:
                if args.file:
                    break
                continue
            for frame in framer.feed(chunk):
                # 프레임 하나 = UDP 데이터그램 하나 (최대 1029 바이트 — MTU 안쪽)
                try:
                    sock.sendto(frame, dest)
                except OSError as exc:
                    # 핫스팟이 끊기면 Windows 는 sendto 에서 「네트워크 연결 불가」를 던진다.
                    # 여기서 죽으면 와이파이가 돌아와도 보정이 영영 안 간다 — 세고 넘어간다.
                    send_errors += 1
                    if send_errors in (1, 10) or send_errors % 100 == 0:
                        print(f"[base_sender] 전송 실패 {send_errors}회 ({exc}) — 와이파이가 돌아오면 저절로 이어진다", flush=True)
                    continue
                if send_errors:
                    print(f"[base_sender] 전송 다시 됨 (그동안 {send_errors}개 버림)", flush=True)
                    send_errors = 0
                stats.note(frame)
                if args.file:
                    time.sleep(0.02 / max(args.rate, 1e-3))
            now = time.time()
            if not args.quiet and now - last_print >= 5.0:
                last_print = now
                print(f"[base_sender] {stats.line()} · CRC 불량 {framer.bad_crc}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
    print(f"[base_sender] 끝 — 프레임 {stats.frames}개 · {stats.bytes} B · CRC 불량 {framer.bad_crc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
