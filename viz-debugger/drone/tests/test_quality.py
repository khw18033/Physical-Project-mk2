"""CAP_ACK · 자동 선행 트리거 · 품질 판정 · 재비행 · 궤적 기록."""

from __future__ import annotations

import asyncio
import csv
import json

from sar_pass.capture import CaptureFlag
from sar_pass.mission import CONTROL_HZ, SarMission
from sar_pass.vehicle import SimClock, SimVehicle
from sitl.fake_cansar import FakeCansarTick
from test_mission import LAT0, LON0, make_plan


def build(tmp_path, ack=True, poll_s=0.5, proc_s=0.1, base=None, radar=True, **plan_over):
    plan = make_plan(**plan_over)
    sim = SimVehicle(LAT0, LON0, clock=SimClock(start=1_790_000_000.0))
    sim.clock_offset_s = 0.05
    cap = CaptureFlag(tmp_path / "CAP_ON", install_handlers=False, ack_path=(tmp_path / "CAP_ACK") if ack else None)
    if ack and radar:
        sim.clock._tick.append(FakeCansarTick(sim.clock, cap.path, cap.ack_path, poll_s=poll_s, proc_s=proc_s, seed=3))
    statuses = []
    m = SarMission(sim, plan, cap, statuses.append, tmp_path / "passes.jsonl", traj_dir=tmp_path / "traj",
                   base_provider=(lambda: base) if base else None)
    return plan, sim, cap, m, statuses


def test_ack_latency_measured_and_lead_learned(tmp_path):
    plan, sim, cap, m, st = build(tmp_path, poll_s=0.8, proc_s=0.2, extra_passes=3)
    assert asyncio.run(m.run()) == "done", (m.error, [r.reasons for r in m.records])
    first = m.records[0]
    assert first.ack_start_unix is not None and first.ack_on_latency_s >= 0.2      # 레이더 지연이 재졌다
    assert first.cap_lead_s == 0.0                                                # 첫 패스는 지연을 몰랐다
    later = [r for r in m.records if r.pass_no > 1]
    assert all(r.cap_lead_s > 0 for r in later)                                   # 그 뒤는 배운 만큼 미리 켠다
    for r in m.records:
        if r.valid:
            assert abs(r.eff_start_along_m) <= plan.q_edge_m                      # 실제 기록이 구간 시작에 맞다
            assert r.eff_end_along_m >= plan.line.length_m - plan.q_edge_m
            assert r.ack_end_unix is not None and r.ack_off_latency_s is not None
    assert m.valid_passes == 2
    assert not cap.path.exists() and not cap.ack_path.exists()


def test_rtk_drop_invalidates_and_refly(tmp_path):
    plan, sim, cap, m, st = build(tmp_path, ack=False)

    def degrade(_dt):
        sim.gps_fix = "RTK_FLOAT" if (cap.is_on and m.pass_no == 1) else "RTK_FIXED"

    sim.clock._tick.append(degrade)
    assert asyncio.run(m.run()) == "done"
    assert [r.valid for r in m.records] == [False, True, True]
    assert any("RTK" in x for x in m.records[0].reasons)
    assert st[-1]["valid_passes"] == 2 and st[-1]["max_attempts"] == 4


def test_incomplete_when_retries_exhausted(tmp_path):
    plan, sim, cap, m, st = build(tmp_path, ack=False, extra_passes=0)

    def degrade(_dt):
        if cap.is_on:
            sim.gps_fix = "RTK_FLOAT"

    sim.clock._tick.append(degrade)
    assert asyncio.run(m.run()) == "incomplete"
    assert m.valid_passes == 0 and len(m.records) == 2
    assert st[-1]["state"] == "incomplete"


def test_missing_ack_invalidates(tmp_path):
    plan, sim, cap, m, st = build(tmp_path, ack=True, radar=False, extra_passes=0)   # 레이더가 꺼져 있다
    assert asyncio.run(m.run()) == "incomplete"
    assert all("레이더 확인(CAP_ACK) 없음" in r.reasons for r in m.records)


def test_trajectory_csv_and_meta(tmp_path):
    base = {"station_id": 0, "lat": 37.56, "lon": 126.97, "alt_m": 88.0}
    plan, sim, cap, m, st = build(tmp_path, base=base)
    sim.params["EKF2_HGT_REF"] = 0
    assert asyncio.run(m.run()) == "done"
    r = m.records[0]
    rows = list(csv.DictReader((tmp_path / "traj" / r.traj_csv).open()))
    cap_rows = [x for x in rows if x["phase"] == "capture"]
    dur = float(cap_rows[-1]["t_pi"]) - float(cap_rows[0]["t_pi"])
    assert len(cap_rows) >= dur * CONTROL_HZ * 0.95                             # 50 Hz
    assert abs(float(rows[0]["t_pi"]) - float(rows[0]["t_fc"]) - 0.05) < 1e-3     # FC GPS 시각 = 파이 − 오차
    assert {"roll_deg", "pitch_deg", "alt_amsl_m", "ned_n", "cap_ack"} <= set(rows[0])
    meta = json.loads((tmp_path / "traj" / r.meta_json).read_text())
    assert meta["base_station"] == base and meta["ekf2_hgt_ref"] == 0
    assert meta["pass"]["valid"] is True and meta["clock"]["offset_pi_minus_fc_s"] == 0.05
    assert any("EKF2_HGT_REF" in w for w in m.warnings)


def test_quality_uses_capture_window_only(tmp_path):
    """가속 · 감속 구간의 큰 속도 차이는 품질에 안 들어간다."""
    plan, sim, cap, m, st = build(tmp_path, ack=False)
    assert asyncio.run(m.run()) == "done"
    for r in m.records:
        assert r.valid and r.max_speed_err_mps < plan.q_speed_mps and r.max_cross_track_m < plan.q_cross_m


def test_low_battery_stops_before_next_pass(tmp_path):
    plan, sim, cap, m, st = build(tmp_path, ack=False)
    sim.battery_pct = 52.0
    sim.battery_drain_pct_s = 0.25          # 빨리 닳는 배터리
    assert asyncio.run(m.run()) == "incomplete"
    assert "배터리" in (m.message or "")
    assert 0 < len(m.records) < 2                  # 첫 패스는 했고 둘째는 시작하지 않았다
    assert st[-1]["battery"]["need_pct"] > 0
    assert sim.mode in ("HOLD", "RTL") and not cap.path.exists()


def test_enough_battery_flies_all(tmp_path):
    plan, sim, cap, m, st = build(tmp_path, ack=False)
    sim.battery_pct = 95.0
    assert asyncio.run(m.run()) == "done"
    assert st[-1]["battery"]["battery_pct"] < 95.0


def test_course_error_is_separate_from_yaw():
    """기수는 정확해도 옆으로 흔들리며 날면 진행 방향 오차가 잡힌다(0.5 s 평균이라 순간 잡음은 걸러진다)."""
    import math

    from sar_pass.mission import course_error_deg

    hd = 45.0
    rows = []
    for i in range(500):                     # 10 s, 50 Hz — 4 m/s 로 가며 옆 속도가 ±0.5 m/s 로 0.2 Hz 흔들림
        t = i * 0.02
        side = 0.5 * math.sin(2 * math.pi * 0.2 * t)
        un, ue = math.cos(math.radians(hd)), math.sin(math.radians(hd))
        rows.append({"t_pi": t, "vn": 4 * un - side * ue, "ve": 4 * ue + side * un})
    err = course_error_deg(rows, hd)
    assert 6.0 < err < 7.2                   # atan(0.5/4) = 7.1°, 평균 창이 조금 깎는다
    jitter = [{**r, "vn": r["vn"] + (0.3 if i % 2 else -0.3)} for i, r in enumerate(rows[:100])]
    straight = [{**r, "vn": 4 * math.cos(math.radians(hd)) + (0.3 if i % 2 else -0.3),
                 "ve": 4 * math.sin(math.radians(hd))} for i, r in enumerate(jitter)]
    assert course_error_deg(straight, hd) < 0.5          # 순간 잡음만 있으면 거의 0
    assert course_error_deg([], hd) is None
