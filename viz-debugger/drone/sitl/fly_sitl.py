"""PX4 SITL(SIH) 위에서 sar_pass 를 실제로 돌린다 — 이륙부터 패스 · 착륙까지.

  # 1) PX4 SITL 을 띄워 둔다 (README 「PX4 SITL 로 시험」)
  # 2) 이 스크립트
  python -m sitl.fly_sitl --passes 2 --heading 45 --length 80 --cap /tmp/sitl/CAP_ON --log-dir /tmp/sitl/logs

실기체와 다른 점은 둘뿐이다: 이륙을 이 스크립트가 한다(실기체는 조종기로), GPS 가 RTK 가 아니다(--no-rtk).
나머지(오프보드 진입 · goto · 모드 보고 · 오프보드 해제)는 진짜 PX4 코드가 돈다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
from pathlib import Path

from sar_pass.capture import CaptureFlag
from sar_pass.geometry import LocalFrame
from sar_pass.mavsdk_vehicle import MavsdkVehicle
from sar_pass.mission import SarMission, SarPlan

log = logging.getLogger("sitl")


async def takeoff(v: MavsdkVehicle, alt_m: float) -> None:
    sysm = v.system
    async for health in sysm.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            break
    await sysm.action.set_takeoff_altitude(alt_m)
    await sysm.action.arm()
    await sysm.action.takeoff()
    for _ in range(600):
        tel = await v.telemetry()
        if tel.in_air and tel.rel_alt_m is not None and tel.rel_alt_m > alt_m - 0.7:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(2.0)
    log.info("이륙 완료 %.1f m", (await v.telemetry()).rel_alt_m)


async def amain(a: argparse.Namespace) -> int:
    v = MavsdkVehicle(a.connect)
    await v.connect(timeout_s=60)
    await takeoff(v, a.alt)
    tel = await v.telemetry()
    # 시작점은 이륙점에서 남서쪽으로 조금 떨어진 곳 — 첫 이동(transit)도 시험한다
    frame = LocalFrame(tel.lat, tel.lon)
    s_lat, s_lon = frame.to_global(-15.0, -10.0)
    e_lat, e_lon = LocalFrame(s_lat, s_lon).to_global(a.length * math.cos(math.radians(a.heading)),
                                                      a.length * math.sin(math.radians(a.heading)))
    plan = SarPlan(start_lat=s_lat, start_lon=s_lon, end_lat=e_lat, end_lon=e_lon, alt_m=a.alt,
                   speed_mps=a.speed, passes=a.passes, gap_s=10.0, require_rtk=False, on_done="rtl")
    for k, val in a.extra or []:
        setattr(plan, k, type(getattr(plan, k))(val))
    a.log_dir.mkdir(parents=True, exist_ok=True)
    a.cap.parent.mkdir(parents=True, exist_ok=True)
    statuses: list[dict] = []
    cap = CaptureFlag(a.cap, install_handlers=False,
                      ack_path=a.cap.parent / "CAP_ACK" if a.fake_cansar else None)
    mission = SarMission(v, plan, cap, statuses.append, a.log_dir / "passes.jsonl", traj_dir=a.log_dir)
    tasks = []
    if a.fake_cansar:
        from sitl.fake_cansar import run_fake_cansar
        tasks.append(asyncio.create_task(run_fake_cansar(cap.path, cap.ack_path, poll_s=a.cansar_poll)))
    outcome = await mission.run()
    for t in tasks:
        t.cancel()
    summary = {
        "outcome": outcome, "message": mission.message, "error": mission.error, "warnings": mission.warnings,
        "passes": [r.public() for r in mission.records],
        "states": list(dict.fromkeys(s["state"] for s in statuses)),
    }
    (a.log_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # 착륙까지 기다린다
    for _ in range(900):
        if not (await v.telemetry()).in_air:
            break
        await asyncio.sleep(0.2)
    await v.close()
    return 0 if outcome == "done" else 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--connect", default="udpin://0.0.0.0:14540")
    p.add_argument("--alt", type=float, default=20.0)
    p.add_argument("--speed", type=float, default=4.0)
    p.add_argument("--passes", type=int, default=2)
    p.add_argument("--heading", type=float, default=45.0)
    p.add_argument("--length", type=float, default=80.0)
    p.add_argument("--cap", type=Path, default=Path("/tmp/sitl/CAP_ON"))
    p.add_argument("--log-dir", type=Path, default=Path("/tmp/sitl/logs"))
    p.add_argument("--fake-cansar", action="store_true", help="CAP_ON 을 보고 지연 뒤 CAP_ACK 를 쓰는 흉내 레이더")
    p.add_argument("--cansar-poll", type=float, default=0.5)
    p.add_argument("--set", dest="extra", nargs=2, action="append", metavar=("FIELD", "VALUE"))
    sys.exit(asyncio.run(amain(p.parse_args())))


if __name__ == "__main__":
    main()
