"""FC 의 GPS 시각 → chrony (SOCK refclock). PPS 와 짝을 지어 Pi 시계를 µs 수준으로 맞춘다.

GPS 는 FC 에 붙어 있어 Pi 에는 NMEA 가 없다. 그래서
  · 「지금이 몇 초인가」 는 FC 가 MAVLink SYSTEM_TIME 으로 알려 주는 GPS 시각(수 ms 흔들림)으로,
  · 「초가 바뀌는 순간」 은 GPS 모듈의 PPS 핀 → Pi GPIO 로 받는다(µs).
chrony 설정 (deploy/pi/pps/chrony-sar.conf):
    refclock SOCK /run/chrony.fc.sock refid FC  noselect poll 2
    refclock PPS  /dev/pps0           refid PPS lock FC prefer poll 2

    python -m sar_pass chrony-fc --connect tcp:127.0.0.1:5760          # sar-chrony.service 가 띄운다

PPS 선이 없으면 FC 시각만으로도 chrony 가 맞춘다(noselect 를 지우면) — `sar_pass timesync` 의 상주판이다.
"""

from __future__ import annotations

import logging
import socket
import struct
import time

log = logging.getLogger("sar_pass.chrony_fc")

SOCK_MAGIC = 0x534F434B
# chrony refclock_sock.c 의 struct sock_sample (64 비트 리눅스): timeval(tv_sec, tv_usec) · double offset · int pulse · int leap · int pad · int magic
SAMPLE = struct.Struct("@qqdiiii")


def pack_sample(local_s: float, offset_s: float) -> bytes:
    """local_s 순간에 「참 시각 − 이 컴퓨터 시각」 = offset_s 였다."""
    sec = int(local_s)
    usec = int(round((local_s - sec) * 1e6))
    if usec >= 1_000_000:
        sec, usec = sec + 1, usec - 1_000_000
    return SAMPLE.pack(sec, usec, offset_s, 0, 0, 0, SOCK_MAGIC)


class ChronySock:
    def __init__(self, path: str = "/run/chrony.fc.sock") -> None:
        self.path = path
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

    def send(self, local_s: float, offset_s: float) -> bool:
        try:
            self.s.sendto(pack_sample(local_s, offset_s), self.path)
            return True
        except OSError as exc:          # chrony 가 아직 안 떴거나 설정이 없다
            log.debug("chrony 소켓 %s: %s", self.path, exc)
            return False


def run(connect: str, sock_path: str, min_interval_s: float = 0.5) -> int:
    from pymavlink import mavutil

    m = mavutil.mavlink_connection(connect, source_system=254, source_component=192, autoreconnect=True)
    out = ChronySock(sock_path)
    log.info("FC %s 의 GPS 시각을 chrony(%s) 로 낸다", connect, sock_path)
    last = 0.0
    sent = 0
    asked = 0.0
    while True:
        # 링크 설정에 따라 SYSTEM_TIME 을 안 보내는 FC 도 있다(SITL 의 GCS 링크) — 1 Hz 로 보내 달라고 30 초마다 다시 청한다
        if time.time() - asked > 30 and m.target_system:
            m.mav.command_long_send(m.target_system, m.target_component or 1,
                                    mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                                    mavutil.mavlink.MAVLINK_MSG_ID_SYSTEM_TIME, 1_000_000, 0, 0, 0, 0, 0)
            asked = time.time()
        msg = m.recv_match(type=["SYSTEM_TIME", "HEARTBEAT"], blocking=True, timeout=5)
        if msg is None or msg.get_type() != "SYSTEM_TIME":
            continue
        local = time.time()
        if msg.time_unix_usec < 1_600_000_000_000_000 or local - last < min_interval_s:
            continue                    # GPS 시각을 아직 모른다 · 너무 잦다
        last = local
        if out.send(local, msg.time_unix_usec / 1e6 - local):
            sent += 1
            if sent % 120 == 1:
                log.info("chrony 로 %d 번 냈다 (지금 오차 %+.3f s)", sent, msg.time_unix_usec / 1e6 - local)
