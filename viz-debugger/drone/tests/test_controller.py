"""에이전트가 부르는 면 — 규약의 숫자 파라미터로 시작 · 중단."""

import asyncio

from sar_pass.capture import CaptureFlag
from sar_pass.controller import SarController
from sar_pass.vehicle import SimClock, SimVehicle

from test_mission import LAT0, LON0, make_plan


def params(**over):
    p = make_plan()
    base = {"start_lat": p.start_lat, "start_lon": p.start_lon, "end_lat": p.end_lat, "end_lon": p.end_lon,
            "alt_m": 20.0, "speed_mps": 4.0, "passes": 2.0, "gap_s": 10.0, "require_rtk": 1.0}
    base.update(over)
    return base


def make(tmp_path):
    cap = CaptureFlag(tmp_path / "CAP_ON", install_handlers=False)
    sim = SimVehicle(LAT0, LON0, clock=SimClock(start=1e6))

    async def factory():
        return sim

    return SarController(factory, cap, log_dir=tmp_path), cap, sim


def test_start_runs_and_rejects_second(tmp_path):
    async def go():
        c, cap, _ = make(tmp_path)
        first = await c.handle("sar_start", params())
        second = await c.handle("sar_start", params())
        outcome = await c.wait()
        return first, second, outcome, cap.is_on

    first, second, outcome, on = asyncio.run(go())
    assert first["accepted"] and not second["accepted"] and second["code"] == "ALREADY_RUNNING"
    assert outcome == "done" and on is False


def test_invalid_params_rejected(tmp_path):
    async def go():
        c, *_ = make(tmp_path)
        return await c.handle("sar_start", params(speed_mps=7.0)), await c.handle("sar_start", {"alt_m": 20.0})

    bad_speed, missing = asyncio.run(go())
    assert bad_speed["code"] == "INVALID_ARGUMENT" and "속도" in bad_speed["message"]
    assert missing["code"] == "INVALID_ARGUMENT"


def test_abort_clears_flag_immediately(tmp_path):
    async def go():
        c, cap, sim = make(tmp_path)
        await c.handle("sar_start", params())
        while not cap.is_on:
            await asyncio.sleep(0)      # 시간은 임무가 민다 — 여기서 또 밀면 시뮬레이터 시간이 두 배로 흐른다
        reply = await c.handle("sar_abort", {})
        on_right_after = cap.is_on
        return reply, on_right_after, await c.wait()

    reply, on_after, outcome = asyncio.run(go())
    assert reply["accepted"] and on_after is False and outcome == "aborted"


def test_abort_after_external_unlink_still_logs_end(tmp_path):
    """신호 처리기가 먼저 지운 경우 — 끊긴 패스도 끝 시각이 남는다."""
    async def go():
        c, cap, sim = make(tmp_path)
        await c.handle("sar_start", params())
        while not cap.is_on:
            await asyncio.sleep(0)      # 시간은 임무가 민다 — 여기서 또 밀면 시뮬레이터 시간이 두 배로 흐른다
        cap.off("signal")
        c.mission.abort()
        await c.wait()
        return c.mission.records

    records = asyncio.run(go())
    assert records[0].captured and records[0].end_unix is not None


def test_unknown_action(tmp_path):
    c, *_ = make(tmp_path)
    assert asyncio.run(c.handle("arm", {}))["code"] == "UNIMPLEMENTED"
