"""비행체 면 — 임무 코드는 이 면만 안다.

실물은 `mavsdk_vehicle.MavsdkVehicle`(PX4), 시험과 연습은 `SimVehicle`. 시계도 같이 갈아 끼운다 —
시뮬레이터는 `sleep` 이 실제로 기다리지 않고 시뮬레이션 시간을 민다.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Protocol

from .geometry import LocalFrame


@dataclass
class Telemetry:
    lat: float | None
    lon: float | None
    rel_alt_m: float | None
    vel_n: float
    vel_e: float
    vel_d: float
    yaw_deg: float | None
    armed: bool
    in_air: bool
    flight_mode: str
    gps_fix: str  # NO_GPS · NO_FIX · FIX_2D · FIX_3D · FIX_DGPS · RTK_FLOAT · RTK_FIXED
    satellites: int = 0
    # 이 컴퓨터 시계 − FC 의 GPS 시각(초). None 은 모름(FC 가 아직 GPS 시각을 안 줬다).
    clock_offset_s: float | None = None
    # 궤적 기록용 — 영상 형성(움직임 보정)에 자세와 해발고도가 필요하다. 모르면 None.
    roll_deg: float | None = None
    pitch_deg: float | None = None
    alt_amsl_m: float | None = None
    ned: tuple[float, float, float] | None = None   # PX4 로컬 위치(EKF 원점 기준) — 궤적 기록용
    battery_pct: float | None = None                 # 남은 배터리 % (0~100). 모르면 None
    home: tuple[float, float] | None = None          # 홈 위경도 — 복귀 거리 계산용

    @property
    def ground_speed(self) -> float:
        return math.hypot(self.vel_n, self.vel_e)


class Clock(Protocol):
    def now(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...


class WallClock:
    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class Vehicle(Protocol):
    clock: Clock

    async def telemetry(self) -> Telemetry: ...
    async def goto(self, lat: float, lon: float, rel_alt_m: float, yaw_deg: float) -> None: ...
    async def start_offboard(self, yaw_deg: float) -> None: ...
    async def set_velocity(self, vel_n: float, vel_e: float, vel_d: float, yaw_deg: float) -> None: ...
    async def track(self, lat: float, lon: float, rel_alt_m: float,
                    vel_n: float, vel_e: float, vel_d: float, yaw_deg: float) -> None: ...
    async def stop_offboard(self) -> None: ...
    async def hold(self) -> None: ...
    async def return_to_launch(self) -> None: ...
    # 선택: PX4 파라미터 읽기. 없으면 None 을 돌려준다(시뮬레이터).
    async def get_param_int(self, name: str) -> int | None: ...
    async def get_param_float(self, name: str) -> float | None: ...
    # 선택: 패스 동안 지오펜스. 없으면 건너뛴다
    async def set_fence(self, points: list[tuple[float, float]]) -> None: ...
    async def restore_fence(self) -> None: ...


# ── 시뮬레이터 ────────────────────────────────────────────────────────────────


class SimClock:
    """`sleep` 이 기다리지 않고 시간을 민다. 시작값은 실제 시각 — 로그 시각이 그럴듯하게 나온다."""

    def __init__(self, start: float | None = None, step_s: float = 0.02, realtime: bool = False) -> None:
        self.t = time.time() if start is None else start
        self.step_s = step_s
        self.realtime = realtime  # 화면 연습용 — 실제 시간으로 흘린다
        self._tick: list = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        remaining = max(0.0, seconds)
        while remaining > 1e-9:
            dt = min(self.step_s, remaining)
            self.t += dt
            remaining -= dt
            for tick in self._tick:
                tick(dt)
            if self.realtime:
                await asyncio.sleep(dt)
        await asyncio.sleep(0)


@dataclass
class SimVehicle:
    """1차 지연 속도 응답을 가진 점 질량. PX4 를 흉내 내지 않고 임무 논리만 시험한다."""

    home_lat: float
    home_lon: float
    clock: SimClock = field(default_factory=SimClock)
    rel_alt_m: float = 20.0
    in_air: bool = True
    armed: bool = True
    gps_fix: str = "RTK_FIXED"
    max_speed: float = 8.0
    max_accel: float = 1.5
    tau_s: float = 0.4
    mode: str = "HOLD"
    vel_noise: float = 0.0   # 돌풍 흉내 — 매 걸음 속도에 더하는 표준편차(m/s)
    battery_pct: float | None = 90.0
    battery_drain_pct_s: float = 0.08     # X500 이 20 분 남짓 나는 정도
    clock_offset_s: float | None = 0.0
    seed: int = 0

    def __post_init__(self) -> None:
        self.frame = LocalFrame(self.home_lat, self.home_lon)
        self.n = 0.0
        self.e = 0.0
        self.vn = self.ve = self.vd = 0.0
        self.yaw = 0.0
        self._cmd = (0.0, 0.0, 0.0)
        self._goto: tuple[float, float, float] | None = None
        self.clock._tick.append(self._step)
        self.history: list[tuple[float, str]] = []
        import random
        self._rng = random.Random(self.seed)

    # 시뮬레이션 한 걸음
    def _step(self, dt: float) -> None:
        if self.mode == "GOTO" and self._goto is not None:
            tn, te, talt = self._goto
            dn, de, dz = tn - self.n, te - self.e, talt - self.rel_alt_m
            dist = math.hypot(dn, de)
            speed = min(self.max_speed * 0.6, dist * 0.8)
            cn, ce = ((dn / dist) * speed, (de / dist) * speed) if dist > 1e-6 else (0.0, 0.0)
            self._cmd = (cn, ce, -dz * 0.8)
        elif self.mode in ("HOLD", "RTL"):
            self._cmd = (0.0, 0.0, 0.0)
        # 1차 지연 + 가속 한계
        for axis in range(3):
            cur = (self.vn, self.ve, self.vd)[axis]
            want = self._cmd[axis]
            dv = (want - cur) * min(1.0, dt / self.tau_s)
            dv = max(-self.max_accel * dt, min(self.max_accel * dt, dv))
            if axis == 0:
                self.vn += dv
            elif axis == 1:
                self.ve += dv
            else:
                self.vd += dv
        if self.vel_noise > 0:
            self.vn += self._rng.gauss(0.0, self.vel_noise) * math.sqrt(dt)
            self.ve += self._rng.gauss(0.0, self.vel_noise) * math.sqrt(dt)
        if self.battery_pct is not None and self.in_air:
            self.battery_pct = max(0.0, self.battery_pct - self.battery_drain_pct_s * dt)
        self.n += self.vn * dt
        self.e += self.ve * dt
        self.rel_alt_m -= self.vd * dt
        if self.fence is not None:
            from .fence import inside
            lat, lon = self.frame.to_global(self.n, self.e)
            if not inside(self.fence, lat, lon):
                self.fence_breaches += 1

    async def telemetry(self) -> Telemetry:
        lat, lon = self.frame.to_global(self.n, self.e)
        return Telemetry(
            lat=lat, lon=lon, rel_alt_m=self.rel_alt_m,
            vel_n=self.vn, vel_e=self.ve, vel_d=self.vd, yaw_deg=self.yaw,
            armed=self.armed, in_air=self.in_air, flight_mode=self.mode,
            gps_fix=self.gps_fix, satellites=24, clock_offset_s=self.clock_offset_s,
            roll_deg=0.0, pitch_deg=-min(12.0, math.hypot(self.vn, self.ve) * 2.0), alt_amsl_m=self.rel_alt_m + 85.0,
            ned=(self.n, self.e, -self.rel_alt_m), battery_pct=self.battery_pct, home=(self.home_lat, self.home_lon),
        )

    async def goto(self, lat: float, lon: float, rel_alt_m: float, yaw_deg: float) -> None:
        n, e = self.frame.to_local(lat, lon)
        self._goto = (n, e, rel_alt_m)
        self.yaw = yaw_deg
        self.mode = "GOTO"
        self.history.append((self.clock.now(), "goto"))

    async def start_offboard(self, yaw_deg: float) -> None:
        self.mode = "OFFBOARD"
        self.yaw = yaw_deg
        self.history.append((self.clock.now(), "offboard"))

    async def set_velocity(self, vel_n: float, vel_e: float, vel_d: float, yaw_deg: float) -> None:
        if self.mode != "OFFBOARD":
            return
        self._cmd = (vel_n, vel_e, vel_d)
        self.yaw = yaw_deg

    async def track(self, lat: float, lon: float, rel_alt_m: float,
                    vel_n: float, vel_e: float, vel_d: float, yaw_deg: float) -> None:
        """PX4 위치 제어기 흉내 — 속도 앞먹임 + 위치 오차 비례."""
        if self.mode != "OFFBOARD":
            return
        n, e = self.frame.to_local(lat, lon)
        kp = 1.0
        cn = vel_n + kp * (n - self.n)
        ce = vel_e + kp * (e - self.e)
        cd = vel_d - kp * (rel_alt_m - self.rel_alt_m)
        lim = self.max_speed
        self._cmd = (max(-lim, min(lim, cn)), max(-lim, min(lim, ce)), max(-2.0, min(2.0, cd)))
        self.yaw = yaw_deg

    async def stop_offboard(self) -> None:
        if self.mode == "OFFBOARD":
            self.mode = "HOLD"
        self.history.append((self.clock.now(), "offboard_stop"))

    async def hold(self) -> None:
        self.mode = "HOLD"
        self.history.append((self.clock.now(), "hold"))

    async def return_to_launch(self) -> None:
        self.mode = "RTL"
        self.history.append((self.clock.now(), "rtl"))

    params: dict = field(default_factory=dict)

    async def get_param_int(self, name: str) -> int | None:
        return self.params.get(name)

    async def get_param_float(self, name: str) -> float | None:
        v = self.params.get(name)
        return None if v is None else float(v)

    # 지오펜스 흉내 — 올린 울타리와, 울타리 밖에 나간 적이 있는지(시험이 본다)
    fence: list | None = None
    fence_breaches: int = 0
    fence_history: list = field(default_factory=list)

    async def set_fence(self, points: list[tuple[float, float]]) -> None:
        self.fence_history.append(("set", list(points)))
        self.fence = list(points)

    async def restore_fence(self) -> None:
        self.fence_history.append(("restore", None))
        self.fence = None
