"""드론 상태판 텔레메트리 수집기 — 진짜 MAVLink 바이트를 파서에 넣고 스냅샷을 본다."""

from __future__ import annotations

import pytest
from pymavlink.dialects.v20 import common as M

from fc_watch.collector import FcTelemetry, px4_mode
from fc_watch.fake_fc import FakeFc


def feed(tel, msgs):
    for m in msgs:
        tel.on_message(m)


def test_snapshot_from_fake_fc():
    now = [1790000000.0]
    tel = FcTelemetry(clock=lambda: now[0])
    fc = FakeFc()
    fc.say(M.MAV_SEVERITY_WARNING, "Preflight Fail: Yaw estimate error")
    feed(tel, fc.frame(t=1790000000.0, lat=37.5665, lon=126.978, alt_rel=20.0, vn=2.83, ve=2.83, vd=0.0,
                       yaw_deg=45.0, mode="OFFBOARD", home=(37.5660, 126.9775)))
    now[0] = 1790000000.5
    s = tel.snapshot()
    assert s["mode"] == "OFFBOARD" and s["armed"] is True and s["landed_state"] == "IN_AIR"
    assert s["link"]["heartbeat_age_s"] == 0.5 and s["link"]["fc_sysid"] == 1
    assert s["attitude"]["yaw_deg"] == pytest.approx(45.0, abs=0.1)
    assert s["hud"]["groundspeed"] == pytest.approx(4.0, abs=0.01)
    assert s["position"]["lat"] == pytest.approx(37.5665, abs=1e-6) and s["position"]["alt_rel_m"] == 20.0
    assert s["home"]["lat"] == pytest.approx(37.5660, abs=1e-6)
    assert s["gps"]["fix"] == "RTK_FIXED" and s["gps"]["satellites"] == 27 and s["gps"]["hdop"] == 0.62
    assert s["rtk"]["baseline_m"] == pytest.approx(144.25, abs=0.1)
    assert len(s["battery"]["cells_v"]) == 4 and s["battery"]["voltage_v"] == 15.9
    assert set(s["ekf"]) >= {"vel", "pos", "ver", "mag", "ter"} and s["ekf"]["pos"] < 0.5
    assert s["vibration"]["z"] > 0 and s["rc"]["rssi"] == 87
    names = {x["name"] for x in s["sensors"]}
    assert {"3D_GYRO", "3D_ACCEL", "3D_MAG", "GPS", "RC_RECEIVER"} <= names
    assert all(x["healthy"] for x in s["sensors"])
    assert s["clock_offset_s"] == pytest.approx(0.04, abs=0.001)   # 가짜 FC 의 GPS 시각은 0.04 s 뒤처져 있다
    assert s["console"][-1]["severity"] == "WARNING" and "Yaw" in s["console"][-1]["text"]


def test_unhealthy_gps_and_other_senders_ignored():
    tel = FcTelemetry()
    feed(tel, FakeFc(sysid=1).frame(t=1.0, lat=37.0, lon=127.0, alt_rel=0, vn=0, ve=0, vd=0, yaw_deg=0,
                                    mode="HOLD", armed=False, fix_type=1))
    gps = next(x for x in tel.snapshot()["sensors"] if x["name"] == "GPS")
    assert gps["healthy"] is False
    # QGC(255) 가 보낸 HEARTBEAT 는 FC 상태가 아니다
    qgc = M.MAVLink(None, srcSystem=255, srcComponent=190)
    raw = M.MAVLink_heartbeat_message(M.MAV_TYPE_GCS, M.MAV_AUTOPILOT_INVALID, 0, 0, 0, 3).pack(qgc)
    feed(tel, M.MAVLink(None).parse_buffer(raw))
    assert tel.snapshot()["mode"] == "AUTO.LOITER" and tel.snapshot()["armed"] is False


def test_missing_values_are_none_not_zero():
    s = FcTelemetry().snapshot()
    assert s["attitude"] is None and s["gps"] is None and s["link"]["heartbeat_age_s"] is None


def test_nan_from_fc_becomes_null_json():
    """PX4 는 대기속도 센서가 없으면 airspeed=NaN — `NaN` 이 JSON 에 섞이면 브라우저가 보고를 통째로 버렸다(261006 실측)."""
    import json
    tel = FcTelemetry()
    tel.on_message(M.MAVLink_vfr_hud_message(float("nan"), 0.0, 236, 0, 10.0, 0.01))
    tel.d["battery"] = {"voltage_v": 16.2, "temperature_c": float("inf"), "cells_v": [4.05, float("nan")]}
    s = tel.snapshot()
    assert s["hud"]["airspeed"] is None and s["hud"]["groundspeed"] == 0.0
    assert s["battery"]["temperature_c"] is None and s["battery"]["cells_v"] == [4.05, None]
    json.loads(json.dumps(s, allow_nan=False))


@pytest.mark.parametrize("cm, name", [(6 << 16, "OFFBOARD"), ((4 << 16) | (3 << 24), "AUTO.LOITER"),
                                      ((4 << 16) | (5 << 24), "AUTO.RTL"), (3 << 16, "POSCTL")])
def test_px4_mode_names(cm, name):
    assert px4_mode(cm) == name


def test_long_statustext_chunks_joined():
    tel = FcTelemetry()
    fc = M.MAVLink(None, srcSystem=1, srcComponent=1)
    p = M.MAVLink(None)
    feed(tel, p.parse_buffer(M.MAVLink_heartbeat_message(2, M.MAV_AUTOPILOT_PX4, 0, 0, 3, 3).pack(fc)))
    a = "A" * 50
    raw = (M.MAVLink_statustext_message(3, a.encode(), 7, 0).pack(fc)
           + M.MAVLink_statustext_message(3, b"tail", 7, 1).pack(fc))
    feed(tel, p.parse_buffer(raw))
    assert tel.snapshot()["console"][-1]["text"] == a + "tail"


def test_wind_estimate_meteorological_direction():
    """PX4 WIND_COV 는 바람이 불어 가는 쪽 벡터다. 표시는 불어 오는 쪽 — 북으로 3 m/s 불어 가면 남풍(180°)."""
    tel = FcTelemetry()
    fc = M.MAVLink(None, srcSystem=1, srcComponent=1)
    p = M.MAVLink(None)
    feed(tel, p.parse_buffer(M.MAVLink_heartbeat_message(2, M.MAV_AUTOPILOT_PX4, 0, 0, 3, 3).pack(fc)))
    raw = M.MAVLink_wind_cov_message(0, 3.0, 0.0, 0.0, 0.1, 0.1, 0.0, 0.5, 0.5).pack(fc)
    feed(tel, p.parse_buffer(raw))
    w = tel.snapshot()["wind"]
    assert w["speed_mps"] == 3.0 and w["from_deg"] == 180.0
