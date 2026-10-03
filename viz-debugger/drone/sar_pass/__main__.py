"""SAR 패스 실행기.

  # 실기체 (pi3 에서, 조종기로 이륙해 둔 뒤)
  python -m sar_pass run --start 37.5665,126.9780 --end 37.5671,126.9786 \
      --alt 20 --speed 4 --passes 2 --gap 10 --mqtt 127.0.0.1:1883

  # 시뮬레이터 (화면 연습 — 실제 시간으로 흘리고 MQTT 로 상태를 보낸다)
  python -m sar_pass sim --mqtt 127.0.0.1:1883 --cap /tmp/CAP_ON

  # 비행 전 점검 (날지 않는다)
  python -m sar_pass check --connect udpin://0.0.0.0:14540 --mqtt 127.0.0.1:1883

  # 비행이 끝날 때마다 FC 의 .ulg 를 그 비행 폴더로 (상주)
  python -m sar_pass ulog --watch --connect tcp://127.0.0.1:5760 --log-dir /home/physical/sar_logs

  # 파이 시계를 FC 의 GPS 시각에 맞춘다 (핫스팟에 인터넷이 없을 때)
  sudo python -m sar_pass timesync --connect udpin://0.0.0.0:14540 --apply

Ctrl-C · SIGTERM 은 중단이다 — CAP_ON 을 지우고 hold(또는 --rtl-on-abort 면 RTL).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import signal
import sys
from pathlib import Path

from .capture import DEFAULT_CAP_PATH, CaptureFlag
from .geometry import LocalFrame
from .mission import CROSS_TOL, HEADING_TOL, SPEED_TOL, STABLE_HOLD_S, SarMission, SarPlan
from .status import MqttStatusPublisher, PrintStatus, RtcmBaseListener


def latlon(text: str) -> tuple[float, float]:
    lat, lon = (float(x) for x in text.split(","))
    return lat, lon


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sar_pass", description="SAR 직선 패스 실행기")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "sim", "cart"):
        s = sub.add_parser(name, help="수레 시험 — 드론 없이 사람이 밀며 선을 지난다(비행 명령 없음)" if name == "cart" else None)
        s.add_argument("--start", type=latlon, help="캡처 시작점 lat,lon")
        s.add_argument("--end", type=latlon, help="캡처 끝점 lat,lon")
        s.add_argument("--heading", type=float, help="--end 대신: 진행 방향(°, 북=0)")
        s.add_argument("--length", type=float, default=80.0, help="--end 대신: 캡처 구간 길이(m)")
        s.add_argument("--alt", type=float, default=20.0)
        s.add_argument("--speed", type=float, default=4.0)
        s.add_argument("--passes", type=int, default=2)
        s.add_argument("--gap", type=float, default=10.0)
        s.add_argument("--lead-in", type=float, default=0.0)
        s.add_argument("--no-rtk", action="store_true", help="RTK Fixed 없이도 시작한다")
        s.add_argument("--rtl-on-abort", action="store_true")
        s.add_argument("--rtl-on-done", action="store_true")
        s.add_argument("--cap", type=Path, default=DEFAULT_CAP_PATH)
        s.add_argument("--log-dir", type=Path, default=Path("sar_logs"))
        s.add_argument("--mqtt", help="host:port — 주면 GUI 로 상태를 보낸다")
        s.add_argument("--device", default="x500-001")
        s.add_argument("--zone", default="zoneA")
        g = s.add_argument_group("등속 판정 · 시계 (실비행 로그를 보고 조정)")
        g.add_argument("--speed-tol", type=float, default=SPEED_TOL, help="속도 허용(m/s)")
        g.add_argument("--heading-tol", type=float, default=HEADING_TOL, help="yaw 허용(°)")
        g.add_argument("--cross-tol", type=float, default=CROSS_TOL, help="횡오차 허용(m)")
        g.add_argument("--stable-hold", type=float, default=STABLE_HOLD_S, help="위 조건 유지 시간(s)")
        g.add_argument("--allow-clock-skew", action="store_true", help="시계 오차가 커도 시작한다(기록에 남김)")
        q = s.add_argument_group("품질 판정 · 재비행 · 레이더 확인")
        q.add_argument("--q-cross", type=float, default=1.0, help="캡처 중 횡오차 허용(m)")
        q.add_argument("--q-speed", type=float, default=0.3, help="캡처 중 속도 오차 허용(m/s, 0.5 s 평균)")
        q.add_argument("--q-alt", type=float, default=0.5, help="캡처 중 고도 오차 허용(m)")
        q.add_argument("--q-heading", type=float, default=3.0, help="캡처 중 yaw 오차 허용(°)")
        q.add_argument("--q-edge", type=float, default=2.0, help="실제 기록이 구간 끝에서 모자라도 되는 거리(m)")
        q.add_argument("--extra-passes", type=int, default=2, help="무효 패스를 다시 날 최대 횟수")
        q.add_argument("--cap-ack", type=Path, help="레이더 확인 파일 경로 (예: /home/physical/CAP_ACK)")
        q.add_argument("--cap-lead", type=float, help="미리 켜고 끄는 시간(s). 안 주면 잰 레이더 지연으로 자동")
        q.add_argument("--min-battery", type=float, default=30.0, help="다음 패스 + 복귀 뒤에도 남아야 할 배터리 %%")
    sub.choices["run"].add_argument("--connect", default="udpin://0.0.0.0:14540", help="MAVSDK 주소")
    sub.choices["cart"].add_argument("--connect", default="udpin://0.0.0.0:14540", help="MAVSDK 주소 (수레에 실은 FC)")
    sub.choices["cart"].add_argument("--cart-cross-tol", type=float, default=3.0, help="수레: 선에서 이만큼 안이면 캡처를 건다(m)")
    ts = sub.add_parser("timesync", help="파이 시계와 FC(GPS) 시각의 차이를 재고, --apply 면 맞춘다")
    ts.add_argument("--connect", default="udpin://0.0.0.0:14540")
    ts.add_argument("--apply", action="store_true", help="시계를 실제로 바꾼다 (root 필요)")
    c = sub.add_parser("check", help="비행 전 점검 — 날지 않는다")
    c.add_argument("--cap", type=Path, default=DEFAULT_CAP_PATH)
    c.add_argument("--connect", help="MAVSDK 주소 (주면 FC · GPS · 시계 오차까지 본다)")
    c.add_argument("--mqtt", help="host:port")
    c.add_argument("--service", default="cansar.service")
    c.add_argument("--cap-ack", type=Path, help="레이더 확인 파일 경로")
    u = sub.add_parser("ulog", help="FC 의 .ulg 를 그 비행 폴더로 받는다 (--watch 면 시동이 꺼질 때마다)")
    u.add_argument("--connect", default="tcp://127.0.0.1:5760", help="패스 비행(14540)과 다른 끝점")
    u.add_argument("--log-dir", type=Path, default=Path("sar_logs"))
    u.add_argument("--watch", action="store_true")
    u.add_argument("--grpc-port", type=int, default=50052)
    return p


def make_plan(a: argparse.Namespace, here: tuple[float, float] | None) -> SarPlan:
    start = a.start or here
    if start is None:
        raise SystemExit("--start 가 필요하다")
    if a.end is not None:
        end = a.end
    elif a.heading is not None:
        frame = LocalFrame(*start)
        end = frame.to_global(a.length * math.cos(math.radians(a.heading)),
                              a.length * math.sin(math.radians(a.heading)))
    else:
        raise SystemExit("--end 또는 --heading 이 필요하다")
    return SarPlan(
        start_lat=start[0], start_lon=start[1], end_lat=end[0], end_lon=end[1],
        alt_m=a.alt, speed_mps=a.speed, passes=a.passes, gap_s=a.gap, lead_in_m=a.lead_in,
        require_rtk=not a.no_rtk,
        on_abort="rtl" if a.rtl_on_abort else "hold", on_done="rtl" if a.rtl_on_done else "hold",
        speed_tol=a.speed_tol, heading_tol=a.heading_tol, cross_tol=a.cross_tol, stable_hold_s=a.stable_hold,
        allow_clock_skew=a.allow_clock_skew,
        q_cross_m=a.q_cross, q_speed_mps=a.q_speed, q_alt_m=a.q_alt, q_heading_deg=a.q_heading, q_edge_m=a.q_edge,
        extra_passes=a.extra_passes, cap_lead_s=a.cap_lead, min_battery_pct=a.min_battery,
    )


async def amain(a: argparse.Namespace) -> int:
    if a.cmd == "check":
        from .check import report, run_checks

        return report(await run_checks(a.cap, a.connect, a.mqtt, a.service, a.cap_ack))
    if a.cmd == "ulog":
        from .ulog import run as ulog_run

        return await ulog_run(a.connect, a.log_dir, a.watch, a.grpc_port)
    if a.cmd == "timesync":
        from .timesync import timesync

        return await timesync(a.connect, a.apply)
    if a.cmd == "sim":
        from .vehicle import SimClock, SimVehicle

        start = a.start or (37.5665, 126.9780)
        vehicle = SimVehicle(start[0], start[1], clock=SimClock(realtime=True), vel_noise=0.1)
        a.start = start
    else:
        from .mavsdk_vehicle import MavsdkVehicle

        vehicle = MavsdkVehicle(a.connect)
        await vehicle.connect()

    tel = await vehicle.telemetry()
    here = (tel.lat, tel.lon) if tel.lat is not None and tel.lon is not None else None
    plan = make_plan(a, here)
    if a.cmd == "cart":
        from .cart import cart_plan
        plan = cart_plan(plan.start_lat, plan.start_lon, plan.end_lat, plan.end_lon, passes=a.passes,
                         require_rtk=not a.no_rtk, q_cross_m=a.q_cross, q_edge_m=a.q_edge)
        problems = [] if plan.line.length_m >= 5 else [f"선이 너무 짧다 ({plan.line.length_m:.1f} m)"]
    else:
        problems = plan.problems()
    if problems:
        logging.error("계획이 조건에 안 맞는다: %s", "; ".join(problems))
        return 2

    sink = PrintStatus()
    publisher = None
    base_listener = None
    if a.mqtt:
        host, _, port = a.mqtt.partition(":")
        publisher = MqttStatusPublisher(host, int(port or 1883), device_id=a.device, zone=a.zone)
        base_listener = RtcmBaseListener(host, int(port or 1883), device_id=a.device, zone=a.zone)

        def both(status: dict) -> None:
            publisher(status)
            sink(status)

        status_sink = both
    else:
        status_sink = sink

    cap = CaptureFlag(a.cap, install_handlers=False, ack_path=a.cap_ack)  # 신호는 아래에서 중단으로 받는다
    a.log_dir.mkdir(parents=True, exist_ok=True)
    stamp = int(vehicle.clock.now())
    if a.cmd == "cart":
        from .cart import CartSession
        mission_cls, extra = CartSession, {"cross_tol_m": a.cart_cross_tol}
    else:
        mission_cls, extra = SarMission, {}
    mission = mission_cls(vehicle, plan, cap, status_sink, a.log_dir / f"sar_passes_{stamp}.jsonl", **extra,
                         traj_dir=a.log_dir / f"flight_{stamp}",
                         base_provider=None if base_listener is None else base_listener.base)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: (cap.off("signal"), mission.abort()))

    logging.info("계획: %.1f m · %.0f° · %.1f m/s · %d회 · 간격 %.0f s · lead-in %.1f m",
                 plan.line.length_m, plan.line.heading_deg, plan.speed_mps, plan.passes, plan.gap_s,
                 plan.effective_lead_in_m)
    try:
        outcome = await mission.run()
    finally:
        cap.off("exit")
        if publisher is not None:
            publisher.close()
    for w in mission.warnings:
        logging.warning("주의: %s", w)
    for r in mission.records:
        logging.info("PASS %d %s start=%s end=%s (FC %s~%s) 레이더지연=%s 실제기록=%s~%s m worst_fix=%s %s",
                     r.pass_no, "유효" if r.valid else "무효", r.start_unix, r.end_unix, r.fc_start_unix, r.fc_end_unix,
                     r.ack_on_latency_s, r.eff_start_along_m, r.eff_end_along_m, r.worst_fix, "; ".join(r.reasons))
    logging.info("결과 %s %s", outcome, mission.message or mission.error or "")
    return 0 if outcome == "done" else 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(asyncio.run(amain(build_parser().parse_args())))


if __name__ == "__main__":
    main()
