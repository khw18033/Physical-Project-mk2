"""SAR 직선 패스 임무.

[비행 조건]
- 고도 일정(기본 20 m), 직선 캡처 구간 60 m 이상, 그 구간에서 3~5 m/s 등속.
  가속·감속은 캡처 구간 밖(앞 lead-in · 뒤 lead-out)에서 한다.
- 캡처 구간 동안 yaw 는 진행 방향으로 고정.
- 같은 선을 같은 방향으로 2회 이상.

[캡처]
- 등속에 들어선 직후 CAP_ON 생성, 캡처 구간 끝(감속 시작 전)에 삭제.
- 중단 · RTL · 예외 · 조종기 개입에도 `finally` 에서 삭제.
- 한 패스 끝(삭제)과 다음 패스 시작(생성) 사이는 최소 `gap_s`(≥10 s).

[로그]
- 패스마다 번호와 시작/끝 시각(time.time())을 남긴다.

한 패스의 흐름:  transit(lead-in 점으로) → gap(간격 채우기) → accel → capture → decel → (다음 패스)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .capture import CaptureFlag
from .geometry import PassLine, angle_diff_deg, lead_in_m
from .vehicle import Telemetry, Vehicle

log = logging.getLogger("sar_pass.mission")

# 요구 조건의 경계값 — GUI(`src/sar/plan.ts`)와 같은 숫자다.
MIN_LINE_M = 60.0
MIN_SPEED = 3.0
MAX_SPEED = 5.0
MIN_PASSES = 2
MIN_GAP_S = 10.0

# 「등속이다」 판정 — 기본값. 실비행 로그를 보고 계획마다 바꿀 수 있다(`SarPlan.speed_tol` 등).
SPEED_TOL = 0.2      # m/s
HEADING_TOL = 5.0    # deg
CROSS_TOL = 2.0      # m
STABLE_HOLD_S = 1.0  # 위 조건이 이만큼 이어져야 등속으로 본다

# 이 컴퓨터 시계와 FC 의 GPS 시각 차이가 이보다 크면 시작하지 않는다 — 패스 시각을 .ulg · 레이더와 맞출 수 없다.
MAX_CLOCK_OFFSET_S = 1.0

# GPS fix 의 좋고 나쁨 차례 — 캡처 중 가장 나빴던 것을 패스 기록에 남긴다.
FIX_ORDER = ("NO_GPS", "NO_FIX", "FIX_2D", "FIX_3D", "FIX_DGPS", "RTK_FLOAT", "RTK_FIXED")


def fix_rank(fix: str) -> int:
    return FIX_ORDER.index(fix) if fix in FIX_ORDER else -1

CONTROL_HZ = 20.0

PILOT_MODES = ("POSCTL", "ALTCTL", "MANUAL", "STABILIZED", "ACRO", "RTL", "LAND")


class MissionAborted(Exception):
    pass


class PilotOverride(Exception):
    pass


class PreflightFailed(Exception):
    pass


@dataclass
class SarPlan:
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    alt_m: float = 20.0
    speed_mps: float = 4.0
    passes: int = 2
    gap_s: float = 10.0
    lead_in_m: float = 0.0       # 0 이면 속도에서 계산
    accel_mps2: float = 1.0
    require_rtk: bool = True
    on_abort: str = "hold"       # hold | rtl
    on_done: str = "hold"        # hold | rtl
    speed_tol: float = SPEED_TOL
    heading_tol: float = HEADING_TOL
    cross_tol: float = CROSS_TOL
    stable_hold_s: float = STABLE_HOLD_S
    max_clock_offset_s: float = MAX_CLOCK_OFFSET_S
    allow_clock_skew: bool = False

    @property
    def line(self) -> PassLine:
        return PassLine(self.start_lat, self.start_lon, self.end_lat, self.end_lon)

    @property
    def effective_lead_in_m(self) -> float:
        auto = lead_in_m(self.speed_mps, self.accel_mps2, settle_s=2.0)
        return max(self.lead_in_m, auto)

    def problems(self) -> list[str]:
        """요구 조건 위반. 비어 있어야 비행한다."""
        out: list[str] = []
        length = self.line.length_m
        if length < MIN_LINE_M:
            out.append(f"캡처 구간 {length:.1f} m < {MIN_LINE_M:.0f} m")
        if not (MIN_SPEED <= self.speed_mps <= MAX_SPEED):
            out.append(f"속도 {self.speed_mps} m/s 가 {MIN_SPEED}~{MAX_SPEED} 밖")
        if self.passes < MIN_PASSES:
            out.append(f"패스 {self.passes}회 < {MIN_PASSES}회")
        if self.gap_s < MIN_GAP_S:
            out.append(f"패스 간격 {self.gap_s} s < {MIN_GAP_S:.0f} s")
        if not (5.0 <= self.alt_m <= 120.0):
            out.append(f"고도 {self.alt_m} m 가 5~120 밖")
        if self.on_abort not in ("hold", "rtl") or self.on_done not in ("hold", "rtl"):
            out.append("on_abort/on_done 은 hold 또는 rtl")
        if not (0 < self.speed_tol <= 1.0 and 0 < self.heading_tol <= 30 and 0 < self.cross_tol <= 10
                and 0 <= self.stable_hold_s <= 5):
            out.append("등속 판정 기준이 범위 밖 (speed_tol ≤1 · heading_tol ≤30 · cross_tol ≤10 · stable_hold_s ≤5)")
        return out

    # 명령 규약은 map<string, double> 이다 — 문자열·참거짓을 숫자로 싣는다.
    @classmethod
    def from_params(cls, p: dict[str, float]) -> "SarPlan":
        def need(key: str) -> float:
            if key not in p:
                raise ValueError(f"파라미터 {key} 가 없다")
            return float(p[key])

        return cls(
            start_lat=need("start_lat"), start_lon=need("start_lon"),
            end_lat=need("end_lat"), end_lon=need("end_lon"),
            alt_m=float(p.get("alt_m", 20.0)),
            speed_mps=float(p.get("speed_mps", 4.0)),
            passes=int(round(p.get("passes", 2))),
            gap_s=float(p.get("gap_s", 10.0)),
            lead_in_m=float(p.get("lead_in_m", 0.0)),
            require_rtk=bool(round(p.get("require_rtk", 1))),
            on_abort="rtl" if round(p.get("rtl_on_abort", 0)) else "hold",
            on_done="rtl" if round(p.get("rtl_on_done", 0)) else "hold",
            speed_tol=float(p.get("speed_tol", SPEED_TOL)),
            heading_tol=float(p.get("heading_tol", HEADING_TOL)),
            cross_tol=float(p.get("cross_tol", CROSS_TOL)),
            stable_hold_s=float(p.get("stable_hold_s", STABLE_HOLD_S)),
            allow_clock_skew=bool(round(p.get("allow_clock_skew", 0))),
        )


@dataclass
class PassRecord:
    pass_no: int
    start_unix: float | None = None
    end_unix: float | None = None
    captured: bool = False
    along_at_start_m: float | None = None
    mean_speed_mps: float | None = None
    max_speed_err_mps: float = 0.0
    max_cross_track_m: float = 0.0
    max_alt_err_m: float = 0.0
    max_heading_err_deg: float = 0.0
    # 같은 순간을 FC 의 GPS 시각으로도 — `start_unix − 시계 오차`. 오차를 몰랐으면 None.
    fc_start_unix: float | None = None
    fc_end_unix: float | None = None
    # 캡처 중 가장 나빴던 fix. RTK_FIXED 가 아니었던 순간이 있으면 그 패스 데이터는 의심한다.
    worst_fix: str | None = None
    note: str = ""
    _speed_sum: float = field(default=0.0, repr=False)
    _speed_n: int = field(default=0, repr=False)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("_speed_sum")
        d.pop("_speed_n")
        d["duration_s"] = (
            round(self.end_unix - self.start_unix, 3)
            if self.start_unix is not None and self.end_unix is not None else None
        )
        return d


StatusSink = Callable[[dict], None]


class SarMission:
    def __init__(
        self,
        vehicle: Vehicle,
        plan: SarPlan,
        cap: CaptureFlag,
        status_sink: StatusSink | None = None,
        pass_log_path: Path | None = None,
    ) -> None:
        self.v = vehicle
        self.plan = plan
        self.cap = cap
        self.sink = status_sink
        self.pass_log_path = pass_log_path
        self.state = "idle"
        self.pass_no = 0
        self.records: list[PassRecord] = []
        self.message: str | None = None
        self.error: str | None = None
        self._abort = asyncio.Event()
        self._last_cap_off: float | None = None
        self._last_tel: Telemetry | None = None
        self._last_publish = 0.0
        self.clock_offset_s: float | None = None
        self.warnings: list[str] = []

    # ── 바깥에서 부르는 것 ──────────────────────────────────────────────────
    def abort(self) -> None:
        self._abort.set()

    async def run(self) -> str:
        """끝난 상태(done · aborted · failed)를 돌려준다. CAP_ON 은 어떤 경로로든 지워진다."""
        outcome = "failed"
        try:
            problems = self.plan.problems()
            if problems:
                raise PreflightFailed("; ".join(problems))
            await self._preflight()
            for n in range(1, self.plan.passes + 1):
                await self._fly_pass(n)
            outcome = "done"
            self.message = f"{self.plan.passes}회 패스 완료"
        except MissionAborted:
            outcome = "aborted"
            self.message = "사람이 중단했다"
        except PilotOverride as exc:
            outcome = "aborted"
            self.message = f"조종기 개입 — {exc}"
        except PreflightFailed as exc:
            outcome = "failed"
            self.error = f"비행 전 점검 실패: {exc}"
        except Exception as exc:  # noqa: BLE001
            outcome = "failed"
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("SAR 임무 예외")
        finally:
            # **무엇이 일어났든 캡처부터 끈다.** 아래 비행 명령이 던져도 이미 지워져 있다.
            self.cap.off(f"finally · {outcome}")
            # 신호 처리기·중단 명령이 먼저 지웠어도 열린 패스는 여기서 닫는다 — 끝 시각이 빠지면 안 된다.
            self._close_open_record("중단으로 캡처 종료")
            await self._after(outcome)
            self.state = outcome
            self._publish(force=True)
        return outcome

    # ── 단계 ────────────────────────────────────────────────────────────────
    async def _preflight(self) -> None:
        self._set_state("preflight")
        # 캡처 파일 자리부터 — 비행 중 첫 캡처 순간에 「폴더가 없다」로 실패하면 늦다.
        parent = self.cap.path.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise PreflightFailed(f"CAP_ON 자리({parent})가 없거나 쓸 수 없다")
        # 지난 비행이 남긴 CAP_ON 은 지우고 시작한다 — 남아 있으면 이동 중에도 캡처된다.
        if self.cap.off("비행 전 정리"):
            self.warnings.append("지난 비행의 CAP_ON 이 남아 있어 지웠다")
        tel = await self._tel()
        if tel.lat is None or tel.lon is None:
            raise PreflightFailed("위치가 없다")
        if not tel.armed or not tel.in_air:
            raise PreflightFailed("이륙한 상태가 아니다 — 조종기로 이륙 후 시작한다")
        if self.plan.require_rtk and tel.gps_fix != "RTK_FIXED":
            raise PreflightFailed(f"RTK Fixed 가 아니다 (지금 {tel.gps_fix})")
        self.clock_offset_s = tel.clock_offset_s
        if tel.clock_offset_s is None:
            self.warnings.append("FC 의 GPS 시각을 아직 못 받아 시계 오차를 모른다 — 패스 시각은 이 컴퓨터 시계 기준이다")
            log.warning(self.warnings[-1])
        elif abs(tel.clock_offset_s) > self.plan.max_clock_offset_s:
            msg = (f"이 컴퓨터 시계가 FC(GPS) 시각과 {tel.clock_offset_s:+.2f} s 어긋난다 "
                   f"(허용 ±{self.plan.max_clock_offset_s} s) — 시계를 맞추고 시작한다 (chrony/NTP)")
            if not self.plan.allow_clock_skew:
                raise PreflightFailed(msg)
            self.warnings.append(msg)
            log.warning(msg)

    async def _fly_pass(self, n: int) -> None:
        plan, line = self.plan, self.plan.line
        heading = line.heading_deg
        length = line.length_m
        lead = plan.effective_lead_in_m
        self.pass_no = n
        record = PassRecord(pass_no=n)
        self.records.append(record)

        # 1. lead-in 점으로
        self._set_state("transit")
        lat, lon = line.point_at(-lead)
        await self.v.goto(lat, lon, plan.alt_m, heading)
        await self._wait_arrival(lat, lon, plan.alt_m, heading, timeout_s=180.0)

        # 2. 앞 패스와의 간격 (캡처 끝 → 다음 캡처 시작). 가속 시간만큼은 덜 기다려도 된다.
        if self._last_cap_off is not None:
            self._set_state("gap")
            accel_time = lead / plan.speed_mps
            while self.v.clock.now() - self._last_cap_off + accel_time < plan.gap_s:
                self._check_abort()
                await self.v.clock.sleep(0.2)
                self._publish()

        # 3~5. 가속 → 캡처 → 감속
        self._set_state("accel")
        await self.v.start_offboard(heading)
        dt = 1.0 / CONTROL_HZ
        v_cmd = 0.0
        stable_since: float | None = None
        un, ue = line.unit
        max_on = length / plan.speed_mps * 1.5 + 10.0
        try:
            while True:
                self._check_abort()
                tel = await self._tel()
                self._check_pilot(tel)
                along, cross = line.along_cross(tel.lat, tel.lon)  # type: ignore[arg-type]
                gs = tel.ground_speed
                alt_err = (tel.rel_alt_m or 0.0) - plan.alt_m
                hdg_err = abs(angle_diff_deg(tel.yaw_deg or 0.0, heading))
                now = self.v.clock.now()

                if self.state in ("accel", "capture"):
                    v_cmd = min(plan.speed_mps, v_cmd + plan.accel_mps2 * dt)
                else:  # decel
                    v_cmd = max(0.0, v_cmd - plan.accel_mps2 * dt)

                # 선 위로 끌어당기는 횡방향 보정, 고도 보정
                k_cross, k_alt = 0.6, 0.8
                c_corr = max(-1.5, min(1.5, -k_cross * cross))
                vel_n = un * v_cmd + (-ue) * c_corr
                vel_e = ue * v_cmd + un * c_corr
                vel_d = max(-1.0, min(1.0, k_alt * alt_err))
                await self.v.set_velocity(vel_n, vel_e, vel_d, heading)

                stable_now = (
                    abs(gs - plan.speed_mps) <= plan.speed_tol and hdg_err <= plan.heading_tol
                    and abs(cross) <= plan.cross_tol
                )
                if stable_now:
                    stable_since = stable_since if stable_since is not None else now
                else:
                    stable_since = None
                stable = stable_since is not None and now - stable_since >= plan.stable_hold_s

                if self.state == "accel":
                    if along >= length:
                        record.note = "등속에 못 들어선 채 캡처 구간을 지났다 — 캡처 없음"
                        log.warning("패스 %d: %s", n, record.note)
                        self._set_state("decel")
                    elif along >= 0.0 and stable:
                        self.cap.on(max_on_s=max_on)
                        record.captured = True
                        record.start_unix = now
                        record.fc_start_unix = self._fc_time(now)
                        record.worst_fix = tel.gps_fix
                        record.along_at_start_m = round(along, 2)
                        self._log_pass_event(record, "start")
                        self._set_state("capture")
                elif self.state == "capture":
                    record._speed_sum += gs
                    record._speed_n += 1
                    record.max_speed_err_mps = max(record.max_speed_err_mps, abs(gs - plan.speed_mps))
                    record.max_cross_track_m = max(record.max_cross_track_m, abs(cross))
                    record.max_alt_err_m = max(record.max_alt_err_m, abs(alt_err))
                    record.max_heading_err_deg = max(record.max_heading_err_deg, hdg_err)
                    if fix_rank(tel.gps_fix) < fix_rank(record.worst_fix or "RTK_FIXED"):
                        record.worst_fix = tel.gps_fix
                    if along >= length:
                        # **감속 전에 끈다.**
                        self.cap.off(f"패스 {n} 끝")
                        record.end_unix = now
                        record.fc_end_unix = self._fc_time(now)
                        record.mean_speed_mps = round(record._speed_sum / max(1, record._speed_n), 3)
                        self._last_cap_off = now
                        self._log_pass_event(record, "end")
                        self._set_state("decel")
                elif self.state == "decel" and v_cmd <= 0.0 and gs < 0.3:
                    break

                self._publish(tel=tel, along=along, cross=cross)
                await self.v.clock.sleep(dt)
        finally:
            await self.v.stop_offboard()

    async def _after(self, outcome: str) -> None:
        mode = self.plan.on_done if outcome == "done" else self.plan.on_abort
        try:
            if mode == "rtl":
                self._set_state("returning")
                await self.v.return_to_launch()
            else:
                await self.v.hold()
        except Exception:  # noqa: BLE001
            log.exception("임무 뒤 %s 실패", mode)

    # ── 도우미 ──────────────────────────────────────────────────────────────
    async def _tel(self) -> Telemetry:
        tel = await self.v.telemetry()
        self._last_tel = tel
        return tel

    async def _wait_arrival(self, lat: float, lon: float, alt: float, heading: float, timeout_s: float) -> None:
        line = self.plan.line
        target_along, target_cross = line.along_cross(lat, lon)
        deadline = self.v.clock.now() + timeout_s
        settled_since: float | None = None
        while True:
            self._check_abort()
            tel = await self._tel()
            # goto 는 PX4 에서 HOLD 로 보인다. 조종 모드 · RTL · LAND 로 바뀌었으면 사람이 개입한 것이다.
            if tel.flight_mode in PILOT_MODES:
                raise PilotOverride(f"이동 중 모드가 {tel.flight_mode}")
            along, cross = line.along_cross(tel.lat, tel.lon)  # type: ignore[arg-type]
            dist = math.hypot(along - target_along, cross - target_cross)
            ok = dist < 1.5 and abs((tel.rel_alt_m or 0) - alt) < 1.0 and tel.ground_speed < 0.4
            now = self.v.clock.now()
            settled_since = (settled_since or now) if ok else None
            if settled_since is not None and now - settled_since >= 1.0:
                return
            if now > deadline:
                raise TimeoutError(f"lead-in 점 도착 시한 초과 (남은 거리 {dist:.1f} m)")
            self._publish(tel=tel, along=along, cross=cross)
            await self.v.clock.sleep(0.2)

    def _check_abort(self) -> None:
        if self._abort.is_set():
            raise MissionAborted()

    def _check_pilot(self, tel: Telemetry) -> None:
        if tel.flight_mode != "OFFBOARD":
            raise PilotOverride(f"오프보드가 풀렸다 (지금 {tel.flight_mode})")

    def _fc_time(self, local: float) -> float | None:
        return None if self.clock_offset_s is None else round(local - self.clock_offset_s, 3)

    def _close_open_record(self, note: str) -> None:
        for record in self.records:
            if record.captured and record.end_unix is None:
                record.end_unix = self.v.clock.now()
                record.fc_end_unix = self._fc_time(record.end_unix)
                record.note = note
                self._log_pass_event(record, "end")

    def _set_state(self, state: str) -> None:
        if state != self.state:
            log.info("상태 %s → %s (패스 %d)", self.state, state, self.pass_no)
        self.state = state
        self._publish(force=True)

    def _log_pass_event(self, record: PassRecord, edge: str) -> None:
        stamp = record.start_unix if edge == "start" else record.end_unix
        log.info("PASS %d %s t=%.3f", record.pass_no, edge.upper(), stamp or 0.0)
        if self.pass_log_path is not None:
            self.pass_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.pass_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"event": edge, "pass": record.pass_no, "time": stamp,
                                    **({"record": record.public()} if edge == "end" else {})},
                                   ensure_ascii=False) + "\n")

    # ── 상태 보고 (GUI 의 `sar` 채널) ─────────────────────────────────────
    def status(self, tel: Telemetry | None = None, along: float | None = None, cross: float | None = None) -> dict:
        tel = tel or self._last_tel
        p = self.plan
        live = None
        if tel is not None:
            heading = p.line.heading_deg
            live = {
                "ground_speed_mps": round(tel.ground_speed, 2),
                "alt_rel_m": None if tel.rel_alt_m is None else round(tel.rel_alt_m, 2),
                "yaw_deg": None if tel.yaw_deg is None else round(tel.yaw_deg, 1),
                "heading_err_deg": None if tel.yaw_deg is None else round(angle_diff_deg(tel.yaw_deg, heading), 1),
                "along_m": None if along is None else round(along, 1),
                "cross_track_m": None if cross is None else round(cross, 2),
                "gps_fix": tel.gps_fix,
                "flight_mode": tel.flight_mode,
            }
        return {
            "schema_version": "sar-0.1",
            "channel": "sar",
            "state": self.state,
            "pass": self.pass_no,
            "passes_total": p.passes,
            "capturing": self.cap.is_on,
            "plan": {
                "start_lat": p.start_lat, "start_lon": p.start_lon, "end_lat": p.end_lat, "end_lon": p.end_lon,
                "alt_m": p.alt_m, "speed_mps": p.speed_mps, "passes": p.passes, "gap_s": p.gap_s,
                "lead_in_m": round(p.effective_lead_in_m, 1), "length_m": round(p.line.length_m, 1),
                "heading_deg": round(p.line.heading_deg, 1), "require_rtk": p.require_rtk,
                "speed_tol": p.speed_tol, "heading_tol": p.heading_tol, "cross_tol": p.cross_tol,
                "stable_hold_s": p.stable_hold_s,
            },
            "clock_offset_s": None if self.clock_offset_s is None else round(self.clock_offset_s, 3),
            "warnings": list(self.warnings),
            "live": live,
            "passes": [r.public() for r in self.records],
            "message": self.message,
            "error": self.error,
            "time": self.v.clock.now(),
        }

    def _publish(self, force: bool = False, **kw) -> None:
        if self.sink is None:
            return
        now = self.v.clock.now()
        if not force and now - self._last_publish < 0.5:
            return
        self._last_publish = now
        try:
            self.sink(self.status(**kw))
        except Exception:  # noqa: BLE001 — 보고가 실패해도 비행·캡처 논리는 멈추지 않는다
            log.exception("상태 보고 실패")
