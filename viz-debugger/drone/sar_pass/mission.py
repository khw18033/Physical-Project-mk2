"""SAR 직선 패스 임무.

[비행 조건]
- 고도 일정(기본 20 m), 직선 캡처 구간 60 m 이상, 그 구간에서 3~5 m/s 등속.
  가속·감속은 캡처 구간 밖(앞 lead-in · 뒤 lead-out)에서 한다.
- 캡처 구간 동안 yaw 는 진행 방향으로 고정.
- 같은 선을 같은 방향으로 2회 이상 — **품질 기준을 넘은 「유효」 패스로 센다.** 무효면 그 자리에서 다시 난다.

[제어]
- **속도 명령 + 우리 쪽 보정**: 진행 방향 = 목표 속도 + 적분(anti-windup), 옆 = 횡오차 비례, 위아래 = 고도 비례.
  PX4 SITL(2026-10-02)에서 셋을 비교했다:
    ① 속도만 → 3.9 m/s 에 머묾(정상상태 오차)   ② 앞서 가는 위치 기준점 → 출발 지연을 메우느라 4.6 m/s 과속
    ③ 선 위로 내린 위치 + 속도 앞먹임 → 텔레메트리 지연만큼 목표점이 뒤에 찍혀 브레이크가 걸림
  ①에 적분을 더한 지금 방식이 가장 빨리 · 정확히 등속에 들어갔다. 진행 방향 위치는 PX4 에 넘기지 않는다.
- 등속 판정은 0.5 s 이동평균 속도로 한다 — 순간 흔들림에 판정이 끊기지 않게.

[캡처]
- 등속에 들어선 직후 CAP_ON 생성, 캡처 구간 끝(감속 시작 전)에 삭제.
- 레이더가 CAP_ACK 를 주면(capture.py) 실제 시작·멈춤 시각과 지연을 잰다. 잰 지연만큼 **미리 켜고 미리 끈다**
  (자동 선행 트리거) — 실제 기록 구간이 캡처 구간과 맞도록.
- 중단 · RTL · 예외 · 조종기 개입에도 `finally` 에서 삭제. 패스 사이 최소 `gap_s`(≥10 s).

[기록]
- 패스마다 번호 · 시작/끝 시각(파이 시계와 FC GPS 시각) · 품질 판정을 남긴다.
- 패스마다 50 Hz 궤적 CSV 와 메타데이터 JSON(계획 · 품질 · 시계 오차 · 베이스 좌표 · EKF2_HGT_REF)을 남긴다.

한 패스의 흐름:  transit(lead-in 점으로) → gap(간격 채우기) → accel → capture → decel → (다음 패스)
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import os
import statistics
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .capture import CaptureFlag
from .geometry import PassLine, angle_diff_deg, lead_in_m
from .version import software_version
from .vehicle import Telemetry, Vehicle

log = logging.getLogger("sar_pass.mission")

# 요구 조건의 경계값 — GUI(`src/sar/plan.ts`)와 같은 숫자다.
MIN_LINE_M = 60.0
MIN_SPEED = 3.0
MAX_SPEED = 5.0
MIN_PASSES = 2
MIN_GAP_S = 10.0

# 「등속이다」 판정 — 기본값. 실비행 로그를 보고 계획마다 바꿀 수 있다(`SarPlan.speed_tol` 등).
SPEED_TOL = 0.2      # m/s (0.5 s 이동평균)
HEADING_TOL = 5.0    # deg
CROSS_TOL = 2.0      # m
STABLE_HOLD_S = 1.0  # 위 조건이 이만큼 이어져야 등속으로 본다
SPEED_AVG_S = 0.5    # 이동평균 창
# 선 복귀: 횡오차 1 m 당 옆 속도 (m/s). SITL 비교(각 3~4 패스, 바람 없음):
#   0.8 → 진행 방향 오차 5.5~6.3° · 횡 0.62~0.68 m / 0.5 → 3.4~4.7° · 0.49~0.67 m / 0.3 → 2.6~2.8° · 0.66~0.97 m
# 0.8 은 선 위로 세게 당겨 좌우로 흔들고, 0.3 은 선에서 밀려난다. 실기체에서 바람과 함께 다시 본다.
CROSS_KP = 0.5
# SITL(게인 0.5): 가속 중 덜 붙은 채 캡처가 시작돼 첫 몇 m 횡오차 1.1~1.4 m 가 나왔다 → 멀 때는 0.8, 캡처는 0.5 m 안에서만
CROSS_KP_FAR = 0.8
CROSS_NEAR_M = 0.5

# 이 컴퓨터 시계와 FC 의 GPS 시각 차이가 이보다 크면 시작하지 않는다 — 패스 시각을 .ulg · 레이더와 맞출 수 없다.
MAX_CLOCK_OFFSET_S = 1.0

# GPS fix 의 좋고 나쁨 차례 — 캡처 중 가장 나빴던 것을 패스 기록에 남긴다.
FIX_ORDER = ("NO_GPS", "NO_FIX", "FIX_2D", "FIX_3D", "FIX_DGPS", "RTK_FLOAT", "RTK_FIXED")

CONTROL_HZ = 50.0     # 제어 · 궤적 기록 주기
SETTLE_S = 5.0        # 가속 뒤 등속 안정에 주는 시간 (SITL: 2·3 s 로는 모자랐다). 모자라면 적응형으로 늘린다
MAX_EXTRA_LEAD_M = 80.0  # 적응형으로 더할 수 있는 가속 구간의 상한
MAX_CAP_LEAD_S = 1.0  # 자동 선행 트리거의 상한
ACK_WAIT_S = 3.0      # 레이더 확인을 이만큼 기다린다

PILOT_MODES = ("POSCTL", "ALTCTL", "MANUAL", "STABILIZED", "ACRO", "RTL", "LAND")

TRAJ_FIELDS = ["t_pi", "t_fc", "lat", "lon", "alt_rel_m", "alt_amsl_m", "ned_n", "ned_e", "ned_d",
               "vn", "ve", "vd", "speed", "speed_avg", "roll_deg", "pitch_deg", "yaw_deg",
               "along_m", "cross_m", "ref_along_m", "ref_speed", "gps_fix", "phase", "cap_on", "cap_ack"]


def course_error_deg(rows: list[dict], line_heading_deg: float, window_s: float = SPEED_AVG_S) -> float | None:
    """실제 진행 방향 오차의 최댓값 — 속도 벡터(vn, ve)를 `window_s` 로 평균해 순간 잡음을 걷어 낸다.
    기수(yaw)가 정확해도 선 복귀 제어가 좌우로 흔들면 커진다(SITL: yaw 0.3° · 진행 방향 최대 9°)."""
    pts = [(r["t_pi"], r["vn"], r["ve"]) for r in rows if r.get("vn") is not None and r.get("ve") is not None]
    if len(pts) < 2:
        return None
    worst, j, sn, se = 0.0, 0, 0.0, 0.0
    for i, (t, vn, ve) in enumerate(pts):
        sn += vn
        se += ve
        while pts[j][0] < t - window_s:
            sn -= pts[j][1]
            se -= pts[j][2]
            j += 1
        if t - pts[0][0] < 0.9 * window_s:              # 창이 다 차기 전에는 평균이 아니다 — 판정하지 않는다
            continue
        if math.hypot(sn, se) / (i - j + 1) < 0.5:      # 거의 서 있으면 방향이 의미 없다
            continue
        worst = max(worst, abs(angle_diff_deg(math.degrees(math.atan2(se, sn)), line_heading_deg)))
    return round(worst, 2)


# ── 재처리용 기록: 규약은 map<string, double> 라 목록 · 사전을 숫자 키로 펼쳐 싣는다 ─────────────
MAX_REFLECTORS = 32
RADAR_PARAM_KEYS = {   # 파라미터 키 → radar.json 칸
    "ant_wavelength_m": "wavelength_m", "ant_bandwidth_hz": "bandwidth_hz", "ant_prf_hz": "prf_hz",
    "ant_range_min_m": "range_min_m", "ant_range_max_m": "range_max_m", "ant_depression_deg": "depression_deg",
    "ant_el_bw_deg": "el_beamwidth_deg", "ant_az_bw_deg": "az_beamwidth_deg",
}


def reflectors_from_params(p: dict[str, float]) -> list:
    """cr_n · cr{i}_lat · cr{i}_lon · cr{i}_h(없으면 지면) → [[lat, lon, h|None], …]."""
    out = []
    for i in range(min(int(round(p.get("cr_n", 0))), MAX_REFLECTORS)):
        lat, lon = p.get(f"cr{i}_lat"), p.get(f"cr{i}_lon")
        if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
            continue
        h = p.get(f"cr{i}_h")
        out.append([float(lat), float(lon), None if h is None or not math.isfinite(h) else float(h)])
    return out


def radar_from_params(p: dict[str, float]) -> dict | None:
    """ant_* · ant_side(+1 오른쪽 / −1 왼쪽) · ant_off_* · gnss_off_* → radar.json 모양. 하나도 없으면 None."""
    if not any(k.startswith(("ant_", "gnss_off_")) for k in p):
        return None
    out: dict = {k2: float(p[k]) for k, k2 in RADAR_PARAM_KEYS.items() if k in p}
    if "ant_side" in p:
        out["side"] = "left" if p["ant_side"] < 0 else "right"
    if all(f"ant_off_{a}" in p for a in "frd"):
        out["antenna_offset_m"] = [float(p[f"ant_off_{a}"]) for a in "frd"]
    if all(f"gnss_off_{a}" in p for a in "frd"):
        out["gnss_offset_m"] = [float(p[f"gnss_off_{a}"]) for a in "frd"]
    return out


def fix_rank(fix: str | None) -> int:
    return FIX_ORDER.index(fix) if fix in FIX_ORDER else -1


class MissionAborted(Exception):
    pass


class LowBattery(Exception):
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
    passes: int = 2                # 필요한 **유효** 패스 수
    gap_s: float = 10.0
    lead_in_m: float = 0.0         # 0 이면 속도에서 계산
    accel_mps2: float = 1.0
    require_rtk: bool = True
    on_abort: str = "hold"         # hold | rtl
    on_done: str = "hold"          # hold | rtl
    speed_tol: float = SPEED_TOL
    heading_tol: float = HEADING_TOL
    cross_tol: float = CROSS_TOL
    stable_hold_s: float = STABLE_HOLD_S
    max_clock_offset_s: float = MAX_CLOCK_OFFSET_S
    allow_clock_skew: bool = False
    # 품질 판정 (캡처 구간 안에서) — 넘으면 무효, 다시 난다
    q_cross_m: float = 1.0
    q_speed_mps: float = 0.3
    q_alt_m: float = 0.5
    q_heading_deg: float = 3.0
    q_course_deg: float = 10.0     # 실제 진행 방향(0.5 s 평균 속도 벡터)이 선과 벌어진 각 — 옆으로 미끄러지며 난 정도
    cross_kp: float = CROSS_KP     # 선 복귀 게인 — SITL 비교용으로만 바꾼다(화면에서는 안 보낸다)
    q_edge_m: float = 2.0          # 실제 기록이 구간 시작보다 늦게 · 끝보다 일찍 끝난 허용 거리
    extra_passes: int = 2          # 무효 패스를 다시 날 수 있는 최대 횟수
    cap_lead_s: float | None = None  # None 이면 잰 레이더 지연으로 자동
    min_battery_pct: float = 30.0    # 다음 패스 + 홈 복귀 뒤에도 이만큼은 남아야 시작한다
    # 재처리용 기록 — 비행 제어에는 안 쓴다. 화면이 보낸 리플렉터 [lat, lon, h|None] 와 안테나(radar.json 모양)
    geofence: bool = True            # 패스 동안 울타리를 올리고 끝나면 원래대로 (sar_pass/fence.py)
    fence_margin_m: float = 15.0
    reflectors: list = field(default_factory=list)
    radar: dict | None = None

    @property
    def line(self) -> PassLine:
        return PassLine(self.start_lat, self.start_lon, self.end_lat, self.end_lon)

    @property
    def effective_lead_in_m(self) -> float:
        auto = lead_in_m(self.speed_mps, self.accel_mps2, settle_s=SETTLE_S)
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
        if not (10 <= self.min_battery_pct <= 80):
            out.append("min_battery_pct 는 10~80")
        if not (0 <= self.extra_passes <= 10):
            out.append("extra_passes 는 0~10")
        if self.cap_lead_s is not None and not (0 <= self.cap_lead_s <= MAX_CAP_LEAD_S):
            out.append(f"cap_lead_s 는 0~{MAX_CAP_LEAD_S}")
        return out

    # 명령 규약은 map<string, double> 이다 — 문자열·참거짓을 숫자로 싣는다.
    @classmethod
    def from_params(cls, p: dict[str, float]) -> "SarPlan":
        def need(key: str) -> float:
            if key not in p:
                raise ValueError(f"파라미터 {key} 가 없다")
            return float(p[key])

        kw: dict[str, Any] = dict(
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
        for key in ("q_cross_m", "q_speed_mps", "q_alt_m", "q_heading_deg", "q_course_deg", "q_edge_m"):
            if key in p:
                kw[key] = float(p[key])
        if "extra_passes" in p:
            kw["extra_passes"] = int(round(p["extra_passes"]))
        if "min_battery_pct" in p:
            kw["min_battery_pct"] = float(p["min_battery_pct"])
        if "cap_lead_s" in p and p["cap_lead_s"] >= 0:
            kw["cap_lead_s"] = float(p["cap_lead_s"])
        if "geofence" in p:
            kw["geofence"] = bool(round(p["geofence"]))
        kw["reflectors"] = reflectors_from_params(p)
        kw["radar"] = radar_from_params(p)
        return cls(**kw)


@dataclass
class PassRecord:
    pass_no: int                       # 몇 번째 시도인가 (1, 2, 3 …)
    start_unix: float | None = None    # CAP_ON 을 만든 시각 (요청)
    end_unix: float | None = None      # CAP_ON 을 지운 시각 (요청)
    captured: bool = False
    along_at_start_m: float | None = None
    mean_speed_mps: float | None = None
    max_speed_err_mps: float = 0.0
    max_cross_track_m: float = 0.0
    max_alt_err_m: float = 0.0
    max_heading_err_deg: float = 0.0
    max_course_err_deg: float | None = None   # 진행 방향(속도 벡터) − 선 방위. 기수(yaw)와 따로 본다
    # 같은 순간을 FC 의 GPS 시각으로도 — `start_unix − 시계 오차`. 오차를 몰랐으면 None.
    fc_start_unix: float | None = None
    fc_end_unix: float | None = None
    # 캡처 중 가장 나빴던 fix. RTK_FIXED 가 아니었던 순간이 있으면 그 패스 데이터는 의심한다.
    worst_fix: str | None = None
    # 레이더 확인(CAP_ACK) — 실제 기록 시작 · 멈춤
    ack_start_unix: float | None = None
    ack_end_unix: float | None = None
    ack_on_latency_s: float | None = None
    ack_off_latency_s: float | None = None
    cap_lead_s: float = 0.0            # 이 패스에 쓴 선행 트리거
    lead_in_m: float | None = None     # 이 패스에 쓴 가속 구간(적응형 포함)
    # 실제 기록 구간(ACK 가 있으면 ACK 기준, 없으면 요청 기준)이 선 위 어디서 어디까지였나
    eff_start_along_m: float | None = None
    eff_end_along_m: float | None = None
    valid: bool | None = None
    reasons: list[str] = field(default_factory=list)
    traj_csv: str | None = None
    meta_json: str | None = None
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
        traj_dir: Path | None = None,
        base_provider: Callable[[], dict | None] | None = None,
    ) -> None:
        self.v = vehicle
        self.plan = plan
        self.cap = cap
        self.sink = status_sink
        self.pass_log_path = pass_log_path
        self.traj_dir = traj_dir
        self.base_provider = base_provider
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
        self.hgt_ref: int | None = None
        self.gps_pos: list[float] | None = None   # EKF2_GPS_POS_X/Y/Z — FC 가 아는 GPS 안테나 위치(기체 앞·오른쪽·아래 m)
        self._on_latencies: list[float] = []
        self._off_latencies: list[float] = []
        self.extra_lead_m = 0.0     # 적응형 가속 구간 — 등속이 늦게 잡힌 만큼 다음 패스 앞을 늘린다
        self._battery_log: list[tuple[float, float]] = []
        self.battery_estimate: dict | None = None
        self.pi_health: dict | None = None
        self.fence: list | None = None

    # ── 바깥에서 부르는 것 ──────────────────────────────────────────────────
    def abort(self) -> None:
        self._abort.set()

    @property
    def valid_passes(self) -> int:
        return sum(1 for r in self.records if r.valid)

    async def run(self) -> str:
        """끝난 상태(done · incomplete · aborted · failed)를 돌려준다. CAP_ON 은 어떤 경로로든 지워진다."""
        outcome = "failed"
        try:
            problems = self.plan.problems()
            if problems:
                raise PreflightFailed("; ".join(problems))
            await self._preflight()
            attempt = 0
            limit = self.plan.passes + self.plan.extra_passes
            while self.valid_passes < self.plan.passes and attempt < limit:
                await self._check_battery()
                attempt += 1
                await self._fly_pass(attempt)
            if self.valid_passes >= self.plan.passes:
                outcome = "done"
                self.message = f"유효 패스 {self.valid_passes}/{self.plan.passes} (시도 {attempt}회)"
            else:
                outcome = "incomplete"
                self.message = f"유효 패스 {self.valid_passes}/{self.plan.passes} — 시도 {attempt}회를 다 썼다"
        except LowBattery as exc:
            outcome = "incomplete"
            self.message = f"배터리 때문에 멈췄다 — {exc} (유효 {self.valid_passes}/{self.plan.passes})"
            log.warning(self.message)
        except MissionAborted:
            outcome = "aborted"
            self.message = "사람이 중단했다"
        except PilotOverride as exc:
            outcome = "aborted"
            self.message = f"조종기 개입 — {exc}"
        except PreflightFailed as exc:
            outcome = "failed"
            self.error = f"비행 전 점검 실패: {exc}"
            log.warning(self.error)
        except Exception as exc:  # noqa: BLE001
            outcome = "failed"
            self.error = f"{type(exc).__name__}: {exc}"
            log.exception("SAR 임무 예외")
        finally:
            # **무엇이 일어났든 캡처부터 끈다.** 아래 비행 명령이 던져도 이미 지워져 있다.
            self.cap.off(f"finally · {outcome}")
            # 신호 처리기·중단 명령이 먼저 지웠어도 열린 패스는 여기서 닫는다 — 끝 시각이 빠지면 안 된다.
            self._close_open_record("중단으로 캡처 종료")
            await self._restore_fence()        # RTL 이 울타리 밖 홈으로 가므로 먼저 되돌린다
            await self._after(outcome)
            self.state = outcome
            # 마지막 보고는 hold/RTL 로 바뀐 뒤의 값으로 — 안 그러면 화면에 OFFBOARD 가 남는다.
            try:
                await self.v.clock.sleep(0.3)
                await self._tel()
            except Exception:  # noqa: BLE001
                pass
            self._publish(force=True)
        return outcome

    # ── 단계 ────────────────────────────────────────────────────────────────
    async def _preflight(self) -> None:
        self._set_state("preflight")
        # 캡처 파일 자리부터 — 비행 중 첫 캡처 순간에 「폴더가 없다」로 실패하면 늦다.
        parent = self.cap.path.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise PreflightFailed(f"CAP_ON 자리({parent})가 없거나 쓸 수 없다")
        # 지난 비행이 남긴 CAP_ON · CAP_ACK 는 지우고 시작한다.
        if self.cap.off("비행 전 정리"):
            self.warnings.append("지난 비행의 CAP_ON 이 남아 있어 지웠다")
        if self.cap.clear_stale_ack():
            self.warnings.append("지난 비행의 CAP_ACK 가 남아 있어 지웠다")
        # 이 컴퓨터(Pi) 자체 — 뜨거워 CPU 를 늦추면 50 Hz 제어가 흔들리고, 디스크가 차면 기록이 끊긴다
        from fc_watch.pihealth import snapshot as pi_snapshot
        pi = pi_snapshot(self.traj_dir.parent if self.traj_dir is not None else None)
        self.pi_health = pi
        th = pi.get("throttled") or {}
        if pi["level"] == "bad":
            why = []
            if pi.get("cpu_temp_c") is not None and pi["cpu_temp_c"] >= 80:
                why.append(f"CPU {pi['cpu_temp_c']} °C")
            if th.get("now"):
                why.append("지금 CPU 를 늦추는 중(스로틀링)")
            if th.get("undervolt"):
                why.append("전압 부족 — 전원 · 케이블 확인")
            if pi.get("disk_free_gb") is not None and pi["disk_free_gb"] < 1:
                why.append(f"디스크 남은 용량 {pi['disk_free_gb']} GB")
            raise PreflightFailed("비행 컴퓨터 상태가 나쁘다: " + " · ".join(why or ["알 수 없음"]))
        if pi["level"] == "warn":
            self.warnings.append(f"비행 컴퓨터 주의 — CPU {pi.get('cpu_temp_c')} °C · 디스크 {pi.get('disk_free_gb')} GB"
                                 + (" · 부팅 뒤 스로틀링이 있었다" if th.get("since_boot") else ""))
            log.warning(self.warnings[-1])
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
                   f"(허용 ±{self.plan.max_clock_offset_s} s) — `python -m sar_pass timesync --apply` 로 맞추고 시작한다")
            if not self.plan.allow_clock_skew:
                raise PreflightFailed(msg)
            self.warnings.append(msg)
            log.warning(msg)
        # 높이 기준 — RTK 를 쓰는데 기압계 기준이면 몇 분 사이 0.5~1 m 가 흔들린다.
        getter = getattr(self.v, "get_param_int", None)
        self.hgt_ref = await getter("EKF2_HGT_REF") if getter is not None else None
        if self.plan.require_rtk and self.hgt_ref is not None and self.hgt_ref != 1:
            self.warnings.append(f"EKF2_HGT_REF={self.hgt_ref} (1=GNSS 가 아니다) — 고도가 기압계 기준이라 패스마다 흔들릴 수 있다")
            log.warning(self.warnings[-1])
        # GPS 안테나 위치(레버암) — 영상 처리가 「보고된 위치가 GPS 안테나인가 FC 인가」를 이것으로 가른다.
        fgetter = getattr(self.v, "get_param_float", None)
        if fgetter is not None:
            xyz = [await fgetter(f"EKF2_GPS_POS_{a}") for a in "XYZ"]
            self.gps_pos = None if any(v is None for v in xyz) else [round(float(v), 4) for v in xyz]
        if self.cap.ack_path is None:
            self.warnings.append("레이더 확인(CAP_ACK) 경로가 없다 — 실제 기록 시각은 모르고 요청 시각만 남는다")
        await self._arm_fence(tel)

    async def _check_battery(self) -> None:
        """다음 패스 + 홈 복귀에 쓸 배터리를 **비행 중 잰 소모율**로 어림한다. 모자라면 시작하지 않는다."""
        tel = await self._tel()
        if tel.battery_pct is None:
            return
        now = self.v.clock.now()
        self._battery_log.append((now, tel.battery_pct))
        rate = 0.08                                   # 처음 값 (X500 이 20 분 남짓) — 잰 값이 생기면 그것
        if len(self._battery_log) >= 2 and now - self._battery_log[0][0] > 20:
            t0, b0 = self._battery_log[0]
            rate = max(0.02, (b0 - tel.battery_pct) / (now - t0))
        p, line = self.plan, self.plan.line
        lead = p.effective_lead_in_m + self.extra_lead_m
        pass_s = (line.length_m + 2 * lead) / p.speed_mps + 2 * p.speed_mps / p.accel_mps2 + p.gap_s + 20.0
        home_s = 0.0
        if tel.home is not None and tel.lat is not None:
            from .geometry import LocalFrame
            n, e = LocalFrame(*tel.home).to_local(tel.lat, tel.lon)
            far = math.hypot(n, e) + line.length_m + 2 * lead
            home_s = far / 5.0 + p.alt_m / 1.0 + 15.0         # 5 m/s 로 돌아와 1 m/s 로 내린다 + 여유
        need = rate * (pass_s + home_s)
        self.battery_estimate = {"battery_pct": round(tel.battery_pct, 1), "drain_pct_s": round(rate, 4),
                                 "next_pass_s": round(pass_s, 1), "home_s": round(home_s, 1), "need_pct": round(need, 1)}
        if tel.battery_pct - need < p.min_battery_pct:
            raise LowBattery(f"남은 {tel.battery_pct:.0f}% − 다음 패스·복귀 {need:.0f}% < 예비 {p.min_battery_pct:.0f}%")

    def _lead_s(self) -> float:
        """이번 패스의 선행 트리거(초). 지정이 없으면 잰 레이더 지연의 중앙값."""
        if self.plan.cap_lead_s is not None:
            return self.plan.cap_lead_s
        if not self._on_latencies:
            return 0.0
        return max(0.0, min(MAX_CAP_LEAD_S, statistics.median(self._on_latencies)))

    def _off_lead_s(self) -> float:
        if self.plan.cap_lead_s is not None:
            return self.plan.cap_lead_s
        if not self._off_latencies:
            return 0.0
        return max(0.0, min(MAX_CAP_LEAD_S, statistics.median(self._off_latencies)))

    async def _fly_pass(self, n: int) -> PassRecord:
        plan, line = self.plan, self.plan.line
        heading = line.heading_deg
        length = line.length_m
        lead = plan.effective_lead_in_m + self.extra_lead_m
        self.pass_no = n
        record = PassRecord(pass_no=n, lead_in_m=round(lead, 1))
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
        on_lead_m = self._lead_s() * plan.speed_mps
        off_lead_m = self._off_lead_s() * plan.speed_mps
        record.cap_lead_s = round(self._lead_s(), 3)
        self._set_state("accel")
        await self.v.start_offboard(heading)
        dt = 1.0 / CONTROL_HZ
        tel = await self._tel()
        s_ref, _ = line.along_cross(tel.lat, tel.lon)  # type: ignore[arg-type]
        v_ref = 0.0
        v_int = 0.0      # 속도 적분 보정 (PX4 정상상태 오차를 지운다)
        stable_since: float | None = None
        speeds: deque[tuple[float, float]] = deque()
        un, ue = line.unit
        max_on = length / plan.speed_mps * 1.5 + 10.0
        rows: list[dict] = []
        off_requested_at: float | None = None
        prev = self.v.clock.now()
        next_tick = prev
        try:
            while True:
                self._check_abort()
                tel = await self._tel()
                self._check_pilot(tel)
                along, cross = line.along_cross(tel.lat, tel.lon)  # type: ignore[arg-type]
                gs = tel.ground_speed
                now = self.v.clock.now()
                # **실제로 흐른 시간**으로 기준점을 민다. 고정 dt 로 밀면 루프가 늦게 돌 때 기준점이 느려진다
                # (PX4 SITL 2026-10-02: 45.8 Hz 로 돌아 기준점이 3.7 m/s 로 움직였다).
                step = min(max(now - prev, 0.0), 0.2)
                prev = now
                speeds.append((now, gs))
                while speeds and now - speeds[0][0] > SPEED_AVG_S:
                    speeds.popleft()
                gs_avg = sum(x for _t, x in speeds) / len(speeds)
                alt_err = (tel.rel_alt_m or 0.0) - plan.alt_m
                hdg_err = abs(angle_diff_deg(tel.yaw_deg or 0.0, heading))

                # 기준점: 가속 → 등속 → 감속. 기체에서 너무 멀어지지 않게 묶는다.
                if self.state in ("accel", "capture"):
                    v_ref = min(plan.speed_mps, v_ref + plan.accel_mps2 * step)
                else:
                    v_ref = max(0.0, v_ref - plan.accel_mps2 * step)
                # 적분은 목표 속도에 다다른 뒤, 오차가 작을 때만 쌓는다(anti-windup) — 가속 지연을 쌓으면 과속으로 돌려준다.
                err = plan.speed_mps - gs_avg
                if v_ref >= plan.speed_mps and self.state in ("accel", "capture") and abs(err) < 0.5:
                    v_int = max(-0.4, min(0.4, v_int + 0.8 * err * step))
                elif self.state == "decel":
                    v_int = 0.0
                v_cmd = max(0.0, v_ref + v_int)
                s_ref = along
                # 선 위로 끌어당김 — 멀면 세게(빨리 붙게), 가까우면 약하게(좌우로 흔들지 않게)
                kp = plan.cross_kp if abs(cross) < CROSS_NEAR_M else max(plan.cross_kp, CROSS_KP_FAR)
                c_corr = max(-1.5, min(1.5, -kp * cross))
                vel_d = max(-1.0, min(1.0, 0.8 * alt_err))          # 고도 유지
                await self.v.set_velocity(un * v_cmd - ue * c_corr, ue * v_cmd + un * c_corr, vel_d, heading)

                # 캡처는 선 위에 붙은 뒤에만 — 품질 기준(q_cross_m)의 절반 안. 느슨하면 캡처 첫 몇 m 가 무효가 된다
                stable_now = (abs(gs_avg - plan.speed_mps) <= plan.speed_tol and hdg_err <= plan.heading_tol
                              and abs(cross) <= min(plan.cross_tol, 0.5 * plan.q_cross_m))
                stable_since = (stable_since if stable_since is not None else now) if stable_now else None
                stable = stable_since is not None and now - stable_since >= plan.stable_hold_s

                ack = self.cap.read_ack()
                if self.state == "accel":
                    if along >= length - off_lead_m:
                        record.note = "등속에 못 들어선 채 캡처 구간을 지났다 — 캡처 없음"
                        log.warning("패스 %d: %s", n, record.note)
                        self._set_state("decel")
                    elif along >= -on_lead_m and stable:
                        self.cap.on(max_on_s=max_on)
                        record.captured = True
                        record.start_unix = now
                        record.fc_start_unix = self._fc_time(now)
                        record.along_at_start_m = round(along, 2)
                        self._log_pass_event(record, "start")
                        self._set_state("capture")
                elif self.state == "capture":
                    record._speed_sum += gs
                    record._speed_n += 1
                    if ack is not None and record.ack_start_unix is None and ack >= (record.start_unix or 0) - 0.5:
                        record.ack_start_unix = ack
                        record.ack_on_latency_s = round(ack - (record.start_unix or ack), 3)
                        self._on_latencies.append(max(0.0, record.ack_on_latency_s))
                    if along >= length - off_lead_m:
                        # **감속 전에 끈다.** (선행 트리거만큼 미리)
                        self.cap.off(f"패스 {n} 끝")
                        record.end_unix = now
                        record.fc_end_unix = self._fc_time(now)
                        record.mean_speed_mps = round(record._speed_sum / max(1, record._speed_n), 3)
                        self._last_cap_off = now
                        off_requested_at = now
                        self._log_pass_event(record, "end")
                        self._set_state("decel")
                elif self.state == "decel":
                    if record.ack_start_unix is None and ack is not None and record.start_unix is not None:
                        record.ack_start_unix = ack       # 늦게 온 시작 확인
                        record.ack_on_latency_s = round(ack - record.start_unix, 3)
                    if (off_requested_at is not None and record.ack_start_unix is not None
                            and record.ack_end_unix is None and ack is None):
                        record.ack_end_unix = now          # 레이더가 ACK 를 지운 것을 본 순간
                        record.ack_off_latency_s = round(now - off_requested_at, 3)
                        self._off_latencies.append(record.ack_off_latency_s)
                    ack_settled = (self.cap.ack_path is None or record.ack_end_unix is not None
                                   or off_requested_at is None or now - off_requested_at > ACK_WAIT_S)
                    if v_ref <= 0.0 and gs < 0.3 and ack_settled:
                        break

                row = self._row(tel, now, along, cross, gs, gs_avg, self.state, ack)
                row["ref_along_m"], row["ref_speed"] = round(s_ref, 3), round(v_cmd, 3)
                rows.append(row)
                self._publish(tel=tel, along=along, cross=cross)
                # 다음 틱 시각까지만 잔다 — 처리 시간만큼 주기가 늘어지지 않게
                next_tick = max(next_tick + dt, self.v.clock.now())
                await self.v.clock.sleep(max(0.0, next_tick - self.v.clock.now()))
        finally:
            await self.v.stop_offboard()
            self._judge(record, rows)
            self._write_traj(record, rows)
        # 적응형 가속 구간: 캡처 요청이 「켤 자리」보다 늦었으면 그만큼(+여유 5 m) 다음 패스의 앞을 늘린다.
        late = (record.along_at_start_m if record.captured else length) + on_lead_m
        if late > 0.5:
            self.extra_lead_m = min(MAX_EXTRA_LEAD_M, self.extra_lead_m + late + 5.0)
            log.info("등속이 %.1f m 늦게 잡혔다 — 다음 패스 가속 구간 +%.1f m (합 %.1f m)",
                     late, late + 5.0, plan.effective_lead_in_m + self.extra_lead_m)
        return record

    # ── 품질 판정 ───────────────────────────────────────────────────────────
    def _judge(self, record: PassRecord, rows: list[dict]) -> None:
        plan = self.plan
        length = plan.line.length_m
        reasons: list[str] = []
        if not record.captured:
            reasons.append("캡처 안 됨")
        # 실제 기록 구간: ACK 가 있으면 ACK, 없으면 요청
        t0 = record.ack_start_unix if record.ack_start_unix is not None else record.start_unix
        t1 = record.ack_end_unix if record.ack_end_unix is not None else record.end_unix
        if self.cap.ack_path is not None and record.captured and record.ack_start_unix is None:
            reasons.append("레이더 확인(CAP_ACK) 없음")
        window = [r for r in rows if t0 is not None and t1 is not None and t0 <= r["t_pi"] <= t1]
        if window:
            record.eff_start_along_m = round(window[0]["along_m"], 2)
            record.eff_end_along_m = round(window[-1]["along_m"], 2)
            if record.eff_start_along_m > plan.q_edge_m:
                reasons.append(f"기록 시작이 {record.eff_start_along_m:.1f} m 늦다 (허용 {plan.q_edge_m} m)")
            if record.eff_end_along_m < length - plan.q_edge_m:
                reasons.append(f"기록 끝이 {length - record.eff_end_along_m:.1f} m 이르다 (허용 {plan.q_edge_m} m)")
            # 캡처 구간(0~length) 안의 표본으로 품질을 본다
            inside = [r for r in window if 0.0 <= r["along_m"] <= length] or window
            record.max_cross_track_m = max(abs(r["cross_m"]) for r in inside)
            record.max_speed_err_mps = max(abs(r["speed_avg"] - plan.speed_mps) for r in inside)
            record.max_alt_err_m = max(abs((r["alt_rel_m"] or 0) - plan.alt_m) for r in inside)
            record.max_heading_err_deg = max(abs(angle_diff_deg(r["yaw_deg"] or 0, plan.line.heading_deg)) for r in inside)
            record.max_course_err_deg = course_error_deg(inside, plan.line.heading_deg)
            worst = min((r["gps_fix"] for r in inside), key=fix_rank)
            record.worst_fix = worst
            if record.max_cross_track_m > plan.q_cross_m:
                reasons.append(f"횡오차 {record.max_cross_track_m:.2f} m > {plan.q_cross_m}")
            if record.max_speed_err_mps > plan.q_speed_mps:
                reasons.append(f"속도 오차 {record.max_speed_err_mps:.2f} m/s > {plan.q_speed_mps}")
            if record.max_alt_err_m > plan.q_alt_m:
                reasons.append(f"고도 오차 {record.max_alt_err_m:.2f} m > {plan.q_alt_m}")
            if record.max_heading_err_deg > plan.q_heading_deg:
                reasons.append(f"yaw 오차 {record.max_heading_err_deg:.1f}° > {plan.q_heading_deg}")
            if record.max_course_err_deg is not None and record.max_course_err_deg > plan.q_course_deg:
                reasons.append(f"진행 방향 오차 {record.max_course_err_deg:.1f}° > {plan.q_course_deg} (옆으로 흔들리며 날았다)")
            if plan.require_rtk and worst != "RTK_FIXED":
                reasons.append(f"캡처 중 RTK 가 {worst} 로 떨어졌다")
        elif record.captured:
            reasons.append("기록 구간의 궤적이 없다")
        record.reasons = reasons
        record.valid = not reasons
        log.info("PASS %d %s %s", record.pass_no, "유효" if record.valid else "무효", "; ".join(reasons))

    # ── 궤적 · 메타데이터 ───────────────────────────────────────────────────
    def _row(self, tel: Telemetry, now: float, along: float, cross: float, gs: float, gs_avg: float,
             phase: str, ack: float | None) -> dict:
        ned = tel.ned or (None, None, None)
        return {
            "t_pi": round(now, 4), "t_fc": self._fc_time4(now),
            "lat": tel.lat, "lon": tel.lon, "alt_rel_m": tel.rel_alt_m, "alt_amsl_m": tel.alt_amsl_m,
            "ned_n": ned[0], "ned_e": ned[1], "ned_d": ned[2],
            "vn": round(tel.vel_n, 3), "ve": round(tel.vel_e, 3), "vd": round(tel.vel_d, 3),
            "speed": round(gs, 3), "speed_avg": round(gs_avg, 3),
            "roll_deg": tel.roll_deg, "pitch_deg": tel.pitch_deg, "yaw_deg": tel.yaw_deg,
            "along_m": round(along, 3), "cross_m": round(cross, 3), "gps_fix": tel.gps_fix,
            "phase": phase, "cap_on": int(self.cap.is_on), "cap_ack": int(ack is not None),
        }

    def _write_traj(self, record: PassRecord, rows: list[dict]) -> None:
        if self.traj_dir is None or not rows:
            return
        try:
            self.traj_dir.mkdir(parents=True, exist_ok=True)
            stamp = int(rows[0]["t_pi"])
            base = self.traj_dir / f"pass{record.pass_no:02d}_{stamp}"
            csv_path = base.with_suffix(".csv")
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=TRAJ_FIELDS)
                w.writeheader()
                w.writerows(rows)
            record.traj_csv = csv_path.name
            meta_path = base.with_suffix(".json")
            record.meta_json = meta_path.name
            base_station = None
            if self.base_provider is not None:
                try:
                    base_station = self.base_provider()
                except Exception:  # noqa: BLE001
                    base_station = None
            meta = {
                "schema": "sar-pass-meta-0.1",
                "pass": record.public(),
                "plan": {k: v for k, v in asdict(self.plan).items()},
                "line": {"length_m": round(self.plan.line.length_m, 3), "heading_deg": round(self.plan.line.heading_deg, 3),
                         "lead_in_m": round(self.plan.effective_lead_in_m, 2)},
                "clock": {"offset_pi_minus_fc_s": self.clock_offset_s,
                          "note": "t_fc = t_pi - offset. t_fc 는 FC 가 GPS 로 맞춘 UTC(초)"},
                "ekf2_hgt_ref": self.hgt_ref,
                "ekf2_gps_pos": self.gps_pos,
                "base_station": base_station,
                "cap": {"path": str(self.cap.path), "ack_path": None if self.cap.ack_path is None else str(self.cap.ack_path),
                        "measured_on_latencies_s": self._on_latencies, "measured_off_latencies_s": self._off_latencies},
                "control_hz": CONTROL_HZ,
                "traj_csv": csv_path.name,
                "warnings": self.warnings,
                # 재처리용 — 이 비행을 무엇으로 찍었나
                "reflectors": [{"lat": r[0], "lon": r[1], "h": r[2]} for r in self.plan.reflectors],
                "radar_config": self.plan.radar,
                "software": software_version(),
                "companion": self.pi_health,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001 — 기록 실패가 비행 · 캡처를 멈추지 않는다
            log.exception("궤적 기록 실패")

    async def _arm_fence(self, tel: Telemetry) -> None:
        if not self.plan.geofence:
            return
        setter = getattr(self.v, "set_fence", None)
        if setter is None:
            return
        from .fence import fence_polygon
        poly = fence_polygon(self.plan, tel.lat, tel.lon)
        try:
            await setter(poly)
            self.fence = poly
            log.info("지오펜스 %d 꼭짓점 올림 (여유 %.0f m)", len(poly), self.plan.fence_margin_m)
        except Exception as exc:  # noqa: BLE001 — 울타리를 못 올려도 비행은 막지 않는다(기록만)
            self.warnings.append(f"지오펜스를 못 올렸다: {exc}")
            log.warning(self.warnings[-1])
            return
        getter = getattr(self.v, "get_param_int", None)
        action = await getter("GF_ACTION") if getter is not None else None
        if action == 0:
            self.warnings.append("지오펜스를 올렸지만 GF_ACTION=0(아무것도 안 함)이다 — QGC 에서 2(Hold) 이상으로 둔다")
            log.warning(self.warnings[-1])

    async def _restore_fence(self) -> None:
        if self.fence is None:
            return
        restorer = getattr(self.v, "restore_fence", None)
        try:
            if restorer is not None:
                await restorer()
            log.info("지오펜스를 원래대로 되돌렸다")
        except Exception:  # noqa: BLE001
            self.warnings.append("지오펜스를 원래대로 못 되돌렸다 — QGC 에서 확인한다")
            log.exception(self.warnings[-1])
        self.fence = None

    async def _after(self, outcome: str) -> None:
        mode = self.plan.on_done if outcome in ("done", "incomplete") else self.plan.on_abort
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

    def _fc_time4(self, local: float) -> float | None:
        return None if self.clock_offset_s is None else round(local - self.clock_offset_s, 4)

    def _close_open_record(self, note: str) -> None:
        for record in self.records:
            if record.captured and record.end_unix is None:
                record.end_unix = self.v.clock.now()
                record.fc_end_unix = self._fc_time(record.end_unix)
                record.note = note
                if record.valid is None:
                    record.valid = False
                    record.reasons = [note]
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
            "schema_version": "sar-0.2",
            "channel": "sar",
            "state": self.state,
            "pass": self.pass_no,
            "passes_total": p.passes,
            "valid_passes": self.valid_passes,
            "max_attempts": p.passes + p.extra_passes,
            "capturing": self.cap.is_on,
            "cap_ack": None if self.cap.ack_path is None else self.cap.read_ack() is not None,
            "cap_lead_s": round(self._lead_s(), 3),
            "plan": {
                "start_lat": p.start_lat, "start_lon": p.start_lon, "end_lat": p.end_lat, "end_lon": p.end_lon,
                "alt_m": p.alt_m, "speed_mps": p.speed_mps, "passes": p.passes, "gap_s": p.gap_s,
                "lead_in_m": round(p.effective_lead_in_m, 1), "length_m": round(p.line.length_m, 1),
                "heading_deg": round(p.line.heading_deg, 1), "require_rtk": p.require_rtk,
                "speed_tol": p.speed_tol, "heading_tol": p.heading_tol, "cross_tol": p.cross_tol,
                "stable_hold_s": p.stable_hold_s,
                "q_cross_m": p.q_cross_m, "q_speed_mps": p.q_speed_mps, "q_alt_m": p.q_alt_m,
                "q_heading_deg": p.q_heading_deg, "q_edge_m": p.q_edge_m, "extra_passes": p.extra_passes,
            },
            "clock_offset_s": None if self.clock_offset_s is None else round(self.clock_offset_s, 3),
            "ekf2_hgt_ref": self.hgt_ref,
            "battery": self.battery_estimate,
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
