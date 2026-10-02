"""RTK 보정 전달 — RTCM3 프레임 고르기 · GPS_RTCM_DATA 조각내기 · 노트북→Pi UDP 왕복."""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest
from pymavlink.dialects.v20 import common as mavlink2

from rtk_relay import base_sender
from rtk_relay.fc_injector import run
from rtk_relay.inject import CHUNK, PymavlinkInjector, RtcmInjector, reassemble
from rtk_relay.rtcm3 import Framer, crc24q, make_1005, make_frame, message_type, parse_base_station
from rtk_relay.stats import RtcmStats

BASE = (36.3507, 127.2986, 85.123)   # 한밭대 근처 — 어디든 상관없다


def msm(mt: int, size: int) -> bytes:
    """메시지 번호만 맞춘 흉내 프레임."""
    body = bytes([(mt >> 4) & 0xFF, (mt & 0x0F) << 4]) + os.urandom(size - 2)
    return make_frame(body)


def test_crc24q_known_vector():
    # RTCM 표준 예 — 빈 입력은 0, "123456789" 는 0xCDE703
    assert crc24q(b"") == 0
    assert crc24q(b"123456789") == 0xCDE703


def test_framer_picks_valid_frames_from_noise_and_chunks():
    frames = [make_1005(7, *BASE), msm(1077, 300), msm(1087, 120), msm(1230, 12)]
    stream = b"$GNGGA,garbage*7F\r\n" + frames[0] + b"\xd3\x00" + frames[1] + b"xx" + frames[2] + frames[3]
    broken = bytearray(msm(1097, 50))
    broken[10] ^= 0xFF                                      # CRC 가 깨진 프레임
    stream += bytes(broken)
    f = Framer()
    got = []
    for i in range(0, len(stream), 37):                     # 조각조각 넣는다
        got += list(f.feed(stream[i:i + 37]))
    assert got == frames
    assert f.bad_crc >= 1
    assert [message_type(x) for x in got] == [1005, 1077, 1087, 1230]


def test_1005_base_position_roundtrip():
    base = parse_base_station(make_1005(42, *BASE))
    assert base is not None and base.station_id == 42
    lat, lon, alt = base.lla
    assert lat == pytest.approx(BASE[0], abs=1e-7) and lon == pytest.approx(BASE[1], abs=1e-7)
    assert alt == pytest.approx(BASE[2], abs=1e-3)


@pytest.mark.parametrize("size", [10, 174, 180, 181, 400, 714])
def test_fragmentation_matches_gps_rtcm_data_rules(size):
    sent = []
    inj = RtcmInjector(lambda flags, n, data: sent.append((flags, n, data)))
    frame = os.urandom(size)
    assert inj.send_frame(frame)
    assert all(len(d) == CHUNK for _f, _n, d in sent)
    if size <= CHUNK:
        assert len(sent) == 1 and sent[0][0] & 1 == 0
    else:
        assert len(sent) == -(-size // CHUNK)
        assert all(f & 1 for f, _n, _d in sent)
        assert [(f >> 1) & 3 for f, _n, _d in sent] == list(range(len(sent)))
        assert len({f >> 3 for f, _n, _d in sent}) == 1      # 한 프레임 = 같은 시퀀스
    assert reassemble(sent) == [frame]


def test_oversize_frame_dropped_and_sequence_wraps():
    sent = []
    inj = RtcmInjector(lambda *a: sent.append(a))
    assert not inj.send_frame(os.urandom(721))
    assert inj.dropped_oversize == 1 and sent == []
    for _ in range(40):
        inj.send_frame(b"x")
    assert {f >> 3 for f, _n, _d in sent} == set(range(32))


def test_pymavlink_encoding_is_valid_gps_rtcm_data():
    class Sink:
        def __init__(self):
            self.buf = b""

        def write(self, b):
            self.buf += b

    sink = Sink()
    mav = mavlink2.MAVLink(sink, srcSystem=252, srcComponent=191)
    inj = PymavlinkInjector(type("M", (), {"mav": mav})())
    frame = msm(1077, 400)
    inj.send_frame(frame)
    parser = mavlink2.MAVLink(None)
    msgs = [m for m in parser.parse_buffer(sink.buf) or [] if m.get_type() == "GPS_RTCM_DATA"]
    assert len(msgs) == 3
    assert reassemble([(m.flags, m.len, bytes(m.data)) for m in msgs]) == [frame]


def test_laptop_to_pi_udp_end_to_end(tmp_path):
    frames = [make_1005(3, *BASE)] + [msm(1077, 250), msm(1087, 160), msm(1230, 10)] * 5
    rec = tmp_path / "base.rtcm"
    rec.write_bytes(b"noise" + b"".join(frames))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    sent = []
    statuses = []
    inj = RtcmInjector(lambda *a: sent.append(a))
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("stats", run(("127.0.0.1", port), inj, None,
                                                                         statuses.append, stop_after_s=3.0)))
    t.start()
    time.sleep(0.3)
    assert base_sender.main(["--file", str(rec), "--to", f"127.0.0.1:{port}", "--rate", "50", "--quiet"]) == 0
    t.join()

    assert reassemble(sent) == frames
    stats: RtcmStats = result["stats"]
    assert stats.base is not None and stats.base.station_id == 3
    last = statuses[-1]
    assert last["frames"] == len(frames) and last["types"]["1077"] == 5
    assert last["base"]["station_id"] == 3 and last["sender"].startswith("127.0.0.1:")


def test_stats_receiving_then_stale():
    now = [1000.0]
    s = RtcmStats(clock=lambda: now[0])
    assert s.snapshot()["receiving"] is False and s.snapshot()["age_s"] is None
    s.note(msm(1077, 20))
    assert s.receiving()
    now[0] += 5
    snap = s.snapshot()
    assert snap["receiving"] is False and snap["age_s"] == 5.0
    assert "끊김" in s.line()
