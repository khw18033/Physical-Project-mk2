"""SAR 패스 임무 — 시뮬레이터로 요구 조건을 확인한다.

CAP_ON 이 「등속 캡처 구간 동안만」 있고, 어떤 끝(완료 · 중단 · 예외 · 조종기 개입)에서도 지워지는지.
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from sar_pass.capture import CaptureFlag
from sar_pass.geometry import PassLine
from sar_pass.mission import MIN_GAP_S, SarMission, SarPlan
from sar_pass.vehicle import SimClock, SimVehicle

LAT0, LON0 = 37.5665, 126.9780


def make_plan(**over) -> SarPlan:
    # 북동쪽(45°)으로 80 m
    line = PassLine(LAT0, LON0, LAT0, LON0)
    end = line.frame.to_global(80 * math.cos(math.radians(45)), 80 * math.sin(math.radians(45)))
    base = dict(start_lat=LAT0, start_lon=LON0, end_lat=end[0], end_lon=end[1],
                alt_m=20.0, speed_mps=4.0, passes=2, gap_s=10.0)
    base.update(over)
    return SarPlan(**base)


class Recorder:
    """CAP_ON 의 존재를 매 상태 보고마다가 아니라 **매 시뮬레이션 걸음**마다 기록한다."""

    def __init__(self, sim: SimVehicle, cap: CaptureFlag, plan: SarPlan) -> None:
        self.samples: list[tuple[float, bool, float, float, float, float]] = []
        self.sim, self.cap, self.plan = sim, cap, plan
        sim.clock._tick.append(self._tick)

    def _tick(self, _dt: float) -> None:
        tel_lat, tel_lon = self.sim.frame.to_global(self.sim.n, self.sim.e)
        along, cross = self.plan.line.along_cross(tel_lat, tel_lon)
        speed = math.hypot(self.sim.vn, self.sim.ve)
        self.samples.append((self.sim.clock.now(), self.cap.is_on, along, speed, self.sim.rel_alt_m, cross))


def setup(tmp_path, **plan_over):
    plan = make_plan(**plan_over)
    sim = SimVehicle(LAT0, LON0, clock=SimClock(start=1_000_000.0))
    cap = CaptureFlag(tmp_path / "CAP_ON", install_handlers=False)
    statuses: list[dict] = []
    mission = SarMission(sim, plan, cap, status_sink=statuses.append, pass_log_path=tmp_path / "passes.jsonl")
    rec = Recorder(sim, cap, plan)
    return plan, sim, cap, mission, rec, statuses


def capture_windows(samples):
    windows, start = [], None
    for t, on, *_ in samples:
        if on and start is None:
            start = t
        elif not on and start is not None:
            windows.append((start, t))
            start = None
    return windows


def test_two_passes_capture_only_at_constant_speed(tmp_path):
    plan, sim, cap, mission, rec, statuses = setup(tmp_path)
    outcome = asyncio.run(mission.run())

    assert outcome == "done", mission.error
    assert not cap.path.exists()
    windows = capture_windows(rec.samples)
    assert len(windows) == 2

    on_samples = [s for s in rec.samples if s[1]]
    length = plan.line.length_m
    for _t, _on, along, speed, alt, cross in on_samples:
        assert -0.5 <= along <= length + 0.5          # 캡처 구간 밖에서는 안 켜져 있다
        assert abs(speed - plan.speed_mps) <= 0.3      # 등속
        assert abs(alt - plan.alt_m) <= 1.0
        assert abs(cross) <= 2.0

    # 패스 간격 ≥ 10 s
    assert windows[1][0] - windows[0][1] >= MIN_GAP_S

    # 같은 방향 — 두 패스 모두 along 이 늘어나는 방향으로 캡처
    for start, end in windows:
        inside = [s for s in on_samples if start <= s[0] <= end]
        assert inside[-1][2] > inside[0][2]

    # 로그: 패스마다 시작/끝 시각과 번호
    lines = [json.loads(x) for x in (tmp_path / "passes.jsonl").read_text().splitlines()]
    assert [(x["event"], x["pass"]) for x in lines] == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]
    assert all(isinstance(x["time"], float) for x in lines)

    final = statuses[-1]
    assert final["state"] == "done" and final["capturing"] is False
    assert [p["captured"] for p in final["passes"]] == [True, True]
    assert sim.mode == "HOLD"


def test_abort_during_capture_removes_flag_and_rtl(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path, on_abort="rtl")

    def abort_when_capturing(_dt):
        if cap.is_on and mission.pass_no == 1:
            mission.abort()

    sim.clock._tick.append(abort_when_capturing)
    outcome = asyncio.run(mission.run())

    assert outcome == "aborted"
    assert not cap.path.exists()
    assert sim.mode == "RTL"
    assert mission.records[0].end_unix is not None   # 열린 패스도 끝 시각이 남는다


def test_exception_mid_capture_removes_flag(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)
    original = sim.set_velocity
    calls = {"n": 0}

    async def flaky(*a, **kw):
        if cap.is_on:
            calls["n"] += 1
            if calls["n"] > 20:
                raise RuntimeError("링크 끊김 흉내")
        return await original(*a, **kw)

    sim.set_velocity = flaky  # type: ignore[method-assign]
    outcome = asyncio.run(mission.run())

    assert outcome == "failed"
    assert "링크 끊김" in (mission.error or "")
    assert not cap.path.exists()


def test_pilot_override_removes_flag(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)

    def take_over(_dt):
        if cap.is_on:
            sim.mode = "POSCTL"

    sim.clock._tick.append(take_over)
    outcome = asyncio.run(mission.run())

    assert outcome == "aborted"
    assert "조종기" in (mission.message or "")
    assert not cap.path.exists()


def test_preflight_requires_rtk_fixed(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)
    sim.gps_fix = "RTK_FLOAT"
    outcome = asyncio.run(mission.run())
    assert outcome == "failed"
    assert "RTK" in (mission.error or "")
    assert not any(on for _t, on, *_ in rec.samples)


@pytest.mark.parametrize("over, word", [
    (dict(speed_mps=6.0), "속도"),
    (dict(passes=1), "패스"),
    (dict(gap_s=5.0), "간격"),
])
def test_plan_rules(tmp_path, over, word):
    plan = make_plan(**over)
    assert any(word in p for p in plan.problems())


def test_short_line_rejected():
    plan = make_plan()
    short = PassLine(LAT0, LON0, *PassLine(LAT0, LON0, LAT0, LON0).frame.to_global(40, 0))
    plan = SarPlan(start_lat=short.start_lat, start_lon=short.start_lon, end_lat=short.end_lat, end_lon=short.end_lon)
    assert any("캡처 구간" in p for p in plan.problems())


def test_from_params_numeric_map():
    plan = make_plan()
    p = SarPlan.from_params({
        "start_lat": plan.start_lat, "start_lon": plan.start_lon, "end_lat": plan.end_lat, "end_lon": plan.end_lon,
        "alt_m": 20, "speed_mps": 4, "passes": 3, "gap_s": 12, "require_rtk": 0, "rtl_on_abort": 1,
    })
    assert p.passes == 3 and p.require_rtk is False and p.on_abort == "rtl" and p.on_done == "hold"


def test_capture_flag_watchdog(tmp_path):
    import time
    cap = CaptureFlag(tmp_path / "CAP_ON", install_handlers=False)
    cap.on(max_on_s=0.2)
    assert cap.is_on
    time.sleep(0.5)
    assert not cap.is_on


def test_capture_flag_requires_absolute_path():
    with pytest.raises(ValueError):
        CaptureFlag("relative/CAP_ON", install_handlers=False)  # type: ignore[arg-type]


def test_gusty_flight_still_captures_within_tolerance(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)
    sim.vel_noise = 0.15
    outcome = asyncio.run(mission.run())
    assert outcome == "done", mission.error
    assert len(capture_windows(rec.samples)) == 2
    assert all(r.captured for r in mission.records)
    # 등속 판정은 들어설 때 걸고, 캡처 중 흔들림은 기록으로 남긴다
    for r in mission.records:
        assert r.max_speed_err_mps < 1.0
        assert r.max_cross_track_m < 2.5
    assert not cap.path.exists()


def test_pilot_override_during_transit(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)
    fired = {"done": False}

    def take_over(_dt):
        if mission.state == "transit" and not fired["done"]:
            fired["done"] = True
            sim.mode = "POSCTL"

    sim.clock._tick.append(take_over)
    assert asyncio.run(mission.run()) == "aborted"
    assert not any(on for _t, on, *_ in rec.samples)


# ── 시계 · RTK 기록 · 판정 기준 (261002 추가) ──────────────────────────────────

def test_clock_skew_refuses_start(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)
    sim.clock_offset_s = 3.5
    assert asyncio.run(mission.run()) == "failed"
    assert "시계" in (mission.error or "")
    assert not any(on for _t, on, *_ in rec.samples)


def test_clock_skew_allowed_is_logged(tmp_path):
    plan, sim, cap, mission, rec, st = setup(tmp_path, allow_clock_skew=True)
    sim.clock_offset_s = 3.5
    assert asyncio.run(mission.run()) == "done"
    assert any("시계" in w for w in st[-1]["warnings"])
    r = mission.records[0]
    assert r.fc_start_unix == pytest.approx(r.start_unix - 3.5, abs=1e-3)
    assert st[-1]["clock_offset_s"] == 3.5


def test_unknown_clock_warns_but_flies(tmp_path):
    plan, sim, cap, mission, rec, st = setup(tmp_path)
    sim.clock_offset_s = None
    assert asyncio.run(mission.run()) == "done"
    assert mission.records[0].fc_start_unix is None
    assert st[-1]["clock_offset_s"] is None and st[-1]["warnings"]


def test_worst_fix_during_capture_is_recorded(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)

    def degrade(_dt):
        if cap.is_on and mission.pass_no == 1:
            sim.gps_fix = "RTK_FLOAT"
        elif mission.pass_no == 2:
            sim.gps_fix = "RTK_FIXED"

    sim.clock._tick.append(degrade)
    assert asyncio.run(mission.run()) == "done"
    assert mission.records[0].worst_fix == "RTK_FLOAT"
    assert mission.records[1].worst_fix == "RTK_FIXED"


def test_tolerances_are_tunable(tmp_path):
    # 아주 거친 바람 + 지나치게 빡빡한 기준 → 등속을 못 잡아 캡처 없음. 기준을 풀면 잡는다.
    plan, sim, cap, mission, rec, _ = setup(tmp_path, speed_tol=0.01, stable_hold_s=3.0)
    sim.vel_noise = 0.6
    asyncio.run(mission.run())
    tight = [r.captured for r in mission.records]

    (tmp_path / "loose").mkdir()
    plan, sim, cap, mission, rec, _ = setup(tmp_path / "loose", speed_tol=0.5, stable_hold_s=0.5)
    sim.vel_noise = 0.6
    assert asyncio.run(mission.run()) == "done"
    assert not all(tight)
    assert all(r.captured for r in mission.records)
    assert not cap.path.exists()


def test_tolerance_params_from_command():
    plan = make_plan()
    p = SarPlan.from_params({"start_lat": plan.start_lat, "start_lon": plan.start_lon, "end_lat": plan.end_lat,
                             "end_lon": plan.end_lon, "speed_tol": 0.35, "stable_hold_s": 0.5})
    assert p.speed_tol == 0.35 and p.stable_hold_s == 0.5 and p.problems() == []
    assert any("판정 기준" in x for x in SarPlan(**{**make_plan().__dict__, "speed_tol": 3.0}).problems())


def test_cap_dir_missing_fails_before_flight(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)
    mission.cap = CaptureFlag(tmp_path / "no_such_dir" / "CAP_ON", install_handlers=False)
    assert asyncio.run(mission.run()) == "failed"
    assert "CAP_ON" in (mission.error or "")
    assert sim.history == [] or all(h[1] != "goto" for h in sim.history)   # 움직이기 전에 멈췄다


def test_stale_cap_on_is_cleared_at_preflight(tmp_path):
    plan, sim, cap, mission, rec, _ = setup(tmp_path)
    cap.path.touch()                      # 지난 비행이 남긴 파일
    assert asyncio.run(mission.run()) == "done"
    first = next(i for i, s in enumerate(rec.samples) if s[2] > -1e9)
    assert rec.samples[first][1] is False  # 첫 걸음부터 꺼져 있다
