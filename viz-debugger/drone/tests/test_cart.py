"""수레 시험 — 사람이 미는 수레(시뮬레이터)로 패스 3번. 비행 명령은 하나도 안 나가야 한다."""

import asyncio
import json
import math

from sar_pass.capture import CaptureFlag
from sar_pass.cart import CartSession, cart_plan
from sar_pass.geometry import LocalFrame
from sar_pass.vehicle import SimClock, SimVehicle

LAT0, LON0 = 37.5665, 126.9780


def test_cart_three_walks(tmp_path):
    hd, length = 45.0, 30.0
    s_lat, s_lon = LocalFrame(LAT0, LON0).to_global(10.0, 0.0)
    e_lat, e_lon = LocalFrame(s_lat, s_lon).to_global(length * math.cos(math.radians(hd)), length * math.sin(math.radians(hd)))
    plan = cart_plan(s_lat, s_lon, e_lat, e_lon, passes=3)
    clock = SimClock(start=1e6)
    cart = SimVehicle(LAT0, LON0, clock=clock, rel_alt_m=0.3, in_air=False, armed=False, mode="WALK", max_accel=3.0)
    un, ue = math.cos(math.radians(hd)), math.sin(math.radians(hd))
    person = {"dir": -1}

    def push(dt):          # 사람: 시작점 뒤 5 m 까지 물러났다가, 1.2 m/s 로 끝점 너머까지 밀고, 다시 돌아온다
        lat, lon = cart.frame.to_global(cart.n, cart.e)
        along, cross = plan.line.along_cross(lat, lon)
        if person["dir"] < 0 and along < -5:
            person["dir"] = 1
        elif person["dir"] > 0 and along > length + 3:
            person["dir"] = -1
        v = 1.2 if person["dir"] > 0 else 2.0
        side = -0.5 * cross                        # 선 쪽으로 조금씩
        cart._cmd = (person["dir"] * v * un - side * ue, person["dir"] * v * ue + side * un, 0.0)
        cart.yaw = hd if person["dir"] > 0 else (hd + 180) % 360

    clock._tick.append(push)
    statuses = []
    cap = CaptureFlag(tmp_path / "CAP_ON", install_handlers=False)
    s = CartSession(cart, plan, cap, statuses.append, tmp_path / "passes.jsonl", traj_dir=tmp_path / "flight_1")
    s.v.start_offboard = s.v.set_velocity = s.v.goto = None     # 비행 명령을 부르면 TypeError 로 드러난다
    outcome = asyncio.run(s.run())
    assert outcome == "done" and len(s.records) == 3 and not cap.is_on
    for r in s.records:
        assert r.captured and r.eff_start_along_m < 0.5 and r.eff_end_along_m > length - 0.5
        assert 1.0 < r.mean_speed_mps < 1.4
    # 걷는 동안 기수가 바뀌어도(되돌아갈 때) 캡처 구간만 판정한다
    assert s.valid_passes >= 2, [r.reasons for r in s.records]
    metas = sorted((tmp_path / "flight_1").glob("pass*.json"))
    assert len(metas) == 3 and json.loads(metas[0].read_text())["plan"]["speed_mps"] == 1.2
    assert {"transit", "capture", "decel"} <= {x["state"] for x in statuses} and statuses[-1]["state"] == "done"
