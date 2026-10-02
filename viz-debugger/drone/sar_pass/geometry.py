"""SAR 패스 기하 — 위경도 ↔ 시작점 기준 지역 좌표(북·동, m).

패스 하나는 수백 m 안쪽이라 평면 근사(등장방형)로 충분하다. 오차는 1 km 에서 수 mm 수준이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_378_137.0


@dataclass(frozen=True)
class LocalFrame:
    """원점(위경도) 기준의 북(N)·동(E) 평면."""

    lat0: float
    lon0: float

    def to_local(self, lat: float, lon: float) -> tuple[float, float]:
        north = math.radians(lat - self.lat0) * EARTH_RADIUS_M
        east = math.radians(lon - self.lon0) * EARTH_RADIUS_M * math.cos(math.radians(self.lat0))
        return north, east

    def to_global(self, north: float, east: float) -> tuple[float, float]:
        lat = self.lat0 + math.degrees(north / EARTH_RADIUS_M)
        lon = self.lon0 + math.degrees(east / (EARTH_RADIUS_M * math.cos(math.radians(self.lat0))))
        return lat, lon


@dataclass(frozen=True)
class PassLine:
    """캡처 구간 하나. 시작 → 끝 방향으로만 난다(같은 선 · 같은 방향 반복)."""

    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float

    @property
    def frame(self) -> LocalFrame:
        return LocalFrame(self.start_lat, self.start_lon)

    @property
    def end_local(self) -> tuple[float, float]:
        return self.frame.to_local(self.end_lat, self.end_lon)

    @property
    def length_m(self) -> float:
        n, e = self.end_local
        return math.hypot(n, e)

    @property
    def heading_deg(self) -> float:
        """진행 방향. 북=0°, 동=90° (PX4 yaw 와 같은 기준)."""
        n, e = self.end_local
        return math.degrees(math.atan2(e, n)) % 360.0

    @property
    def unit(self) -> tuple[float, float]:
        n, e = self.end_local
        length = math.hypot(n, e)
        return n / length, e / length

    def along_cross(self, lat: float, lon: float) -> tuple[float, float]:
        """(진행 방향 거리, 오른쪽 + 횡오차). 시작점이 0, 끝점이 length_m 이다."""
        n, e = self.frame.to_local(lat, lon)
        un, ue = self.unit
        along = n * un + e * ue
        cross = -n * ue + e * un
        return along, cross

    def point_at(self, along_m: float) -> tuple[float, float]:
        """선 위(연장선 포함) along_m 지점의 위경도."""
        un, ue = self.unit
        return self.frame.to_global(un * along_m, ue * along_m)


def lead_in_m(speed_mps: float, accel_mps2: float, settle_s: float) -> float:
    """가속 거리 + 등속 안정 구간. 캡처 시작점 앞에 이만큼 비워 둔다."""
    return speed_mps ** 2 / (2.0 * accel_mps2) + speed_mps * settle_s


def angle_diff_deg(a: float, b: float) -> float:
    """a - b 를 -180~180 으로."""
    return (a - b + 180.0) % 360.0 - 180.0
