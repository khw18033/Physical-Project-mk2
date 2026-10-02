"""PX4 실기체 — MAVSDK(gRPC 래퍼, `mavsdk-grpc`).

pi3 의 mavlink-router 에 이 프로세스용 UDP 끝점을 하나 더 열어 두고 거기에 붙는다
(기본 `udpin://0.0.0.0:14540`). Pi 의 mavlink-router 가 이미 열어 둔 MAVSDK 제어 끝점이다
— 14541 은 linkmon, 14542 는 detect, 14543 은 드론 에이전트(drone-node)가 쓴다. 14540 은 「한 번에 하나」라
SAR 비행 중에는 점검 스크립트(check_link 등)를 같이 돌리지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import time

try:  # 새 이름이 먼저다. 옛 설치(mavsdk<4)도 받는다.
    import mavsdk_grpc as mavsdk
    from mavsdk_grpc.offboard import OffboardError, VelocityNedYaw
except ImportError:  # pragma: no cover
    import mavsdk  # type: ignore[no-redef]
    from mavsdk.offboard import OffboardError, VelocityNedYaw  # type: ignore[no-redef]

from .vehicle import Telemetry, WallClock

log = logging.getLogger("sar_pass.mavsdk")

_MODE = {"RETURN_TO_LAUNCH": "RTL"}


class MavsdkVehicle:
    def __init__(self, system_address: str = "udpin://0.0.0.0:14540") -> None:
        self.address = system_address
        self.clock = WallClock()
        self.system = mavsdk.System()
        self._lat = self._lon = self._rel = self._amsl = None
        self._vel = (0.0, 0.0, 0.0)
        self._yaw: float | None = None
        self._armed = False
        self._in_air = False
        self._mode = "UNKNOWN"
        self._fix = "NO_GPS"
        self._sats = 0
        self._clock_offset: float | None = None
        self._tasks: list[asyncio.Task] = []

    async def connect(self, timeout_s: float = 30.0) -> None:
        async def connect_and_wait() -> None:
            # `System.connect` 자체가 FC 를 찾을 때까지 기다린다 — 시한을 그 바깥에 건다.
            await self.system.connect(system_address=self.address)
            async for state in self.system.core.connection_state():
                if state.is_connected:
                    return

        try:
            await asyncio.wait_for(connect_and_wait(), timeout_s)
        except BaseException:
            # 못 붙었으면 띄운 mavsdk_server 를 내린다 — 남으면 프로세스가 안 끝나고 포트를 쥔다.
            self._stop_server()
            raise
        log.info("PX4 연결됨 %s", self.address)
        t = self.system.telemetry
        self._tasks = [
            asyncio.create_task(self._pump(t.position(), self._on_position)),
            asyncio.create_task(self._pump(t.velocity_ned(), self._on_velocity)),
            asyncio.create_task(self._pump(t.heading(), self._on_heading)),
            asyncio.create_task(self._pump(t.armed(), self._on_armed)),
            asyncio.create_task(self._pump(t.in_air(), self._on_in_air)),
            asyncio.create_task(self._pump(t.flight_mode(), self._on_mode)),
            asyncio.create_task(self._pump(t.gps_info(), self._on_gps)),
            asyncio.create_task(self._pump(t.unix_epoch_time(), self._on_epoch)),
        ]
        # 첫 위치가 올 때까지 잠깐 기다린다 — 없으면 임무가 비행 전 점검에서 거절한다.
        for _ in range(50):
            if self._lat is not None:
                break
            await asyncio.sleep(0.1)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._stop_server()

    def _stop_server(self) -> None:
        try:
            self.system._stop_mavsdk_server()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    async def _pump(stream, handler) -> None:  # noqa: ANN001
        try:
            async for item in stream:
                handler(item)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            log.exception("텔레메트리 스트림이 끊겼다")

    def _on_position(self, p) -> None:  # noqa: ANN001
        self._lat, self._lon = p.latitude_deg, p.longitude_deg
        self._rel, self._amsl = p.relative_altitude_m, p.absolute_altitude_m

    def _on_velocity(self, v) -> None:  # noqa: ANN001
        self._vel = (v.north_m_s, v.east_m_s, v.down_m_s)

    def _on_heading(self, h) -> None:  # noqa: ANN001
        self._yaw = h.heading_deg

    def _on_armed(self, a: bool) -> None:
        self._armed = a

    def _on_in_air(self, a: bool) -> None:
        self._in_air = a

    def _on_mode(self, m) -> None:  # noqa: ANN001
        self._mode = _MODE.get(m.name, m.name)

    def _on_gps(self, g) -> None:  # noqa: ANN001
        self._fix = g.fix_type.name
        self._sats = g.num_satellites

    def _on_epoch(self, time_us: int) -> None:
        # FC 가 GPS 로 맞춘 UTC. 0 이나 옛 값이면 아직 GPS 시각이 없다는 뜻이다 — 모름으로 둔다.
        if time_us > 1_600_000_000_000_000:  # 2020-09 이후만 믿는다
            self._clock_offset = time.time() - time_us / 1e6

    # ── Vehicle 면 ───────────────────────────────────────────────────────────
    async def telemetry(self) -> Telemetry:
        return Telemetry(
            lat=self._lat, lon=self._lon, rel_alt_m=self._rel,
            vel_n=self._vel[0], vel_e=self._vel[1], vel_d=self._vel[2], yaw_deg=self._yaw,
            armed=self._armed, in_air=self._in_air, flight_mode=self._mode,
            gps_fix=self._fix, satellites=self._sats, clock_offset_s=self._clock_offset,
        )

    async def goto(self, lat: float, lon: float, rel_alt_m: float, yaw_deg: float) -> None:
        if self._amsl is None or self._rel is None:
            raise RuntimeError("고도 기준(AMSL)을 아직 모른다")
        amsl = self._amsl - self._rel + rel_alt_m
        await self.system.action.goto_location(lat, lon, amsl, yaw_deg)

    async def start_offboard(self, yaw_deg: float) -> None:
        # PX4 는 오프보드 진입 전에 설정값이 이미 흐르고 있어야 한다.
        await self.system.offboard.set_velocity_ned(VelocityNedYaw(0.0, 0.0, 0.0, yaw_deg))
        try:
            await self.system.offboard.start()
        except OffboardError as exc:
            raise RuntimeError(f"오프보드 진입 실패: {exc._result.result}") from exc
        # 모드 보고가 OFFBOARD 로 바뀔 때까지 기다린다 — 안 그러면 첫 틱에 「조종기 개입」으로 읽는다.
        for _ in range(30):
            if self._mode == "OFFBOARD":
                return
            await asyncio.sleep(0.1)
        raise RuntimeError(f"오프보드로 안 바뀌었다 (지금 {self._mode})")

    async def set_velocity(self, vel_n: float, vel_e: float, vel_d: float, yaw_deg: float) -> None:
        await self.system.offboard.set_velocity_ned(VelocityNedYaw(vel_n, vel_e, vel_d, yaw_deg))

    async def stop_offboard(self) -> None:
        try:
            await self.system.offboard.stop()
        except OffboardError:
            log.warning("오프보드 종료 실패 — 이미 다른 모드일 수 있다")

    async def hold(self) -> None:
        await self.system.action.hold()

    async def return_to_launch(self) -> None:
        await self.system.action.return_to_launch()
