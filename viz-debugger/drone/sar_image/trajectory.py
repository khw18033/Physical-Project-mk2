"""패스 궤적 CSV(sar_pass 가 남긴 50 Hz) → 지역 ENU 배열 · 시각 보간.

ENU 원점은 고르는 값이다(보통 첫 리플렉터나 베이스). 수백 m 안쪽이라 평면 근사로 충분하다(오차 mm 수준).
높이는 해발(alt_amsl_m)이 있으면 그것, 없으면 이륙점 기준 상대고도를 쓴다 — 어느 쪽인지 `height_ref` 에 적는다.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

R_EARTH = 6_378_137.0


@dataclass
class Origin:
    lat: float
    lon: float
    h: float = 0.0

    def enu(self, lat, lon, h):  # noqa: ANN001, ANN201
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        e = np.radians(lon - self.lon) * R_EARTH * math.cos(math.radians(self.lat))
        n = np.radians(lat - self.lat) * R_EARTH
        return np.stack([e, n, np.asarray(h, dtype=float) - self.h], axis=-1)

    def latlon(self, e: float, n: float) -> tuple[float, float]:
        return (self.lat + math.degrees(n / R_EARTH),
                self.lon + math.degrees(e / (R_EARTH * math.cos(math.radians(self.lat)))))


@dataclass
class Trajectory:
    t: np.ndarray          # 초 (FC GPS 시각이 있으면 그것, 없으면 파이 시각)
    lat: np.ndarray
    lon: np.ndarray
    h: np.ndarray          # 해발 또는 상대고도 (height_ref)
    yaw: np.ndarray        # deg
    roll: np.ndarray
    pitch: np.ndarray
    capture: np.ndarray    # bool — 레이더가 실제로 기록 중이던 표본 (cap_ack, 없으면 cap_on)
    time_ref: str          # "fc_gps" | "pi"
    height_ref: str        # "amsl" | "rel_home"
    ground_h: float        # 지면 높이 추정 (같은 기준) — 이륙점 높이
    source: str = ""

    @classmethod
    def load_csv(cls, path: str | Path) -> "Trajectory":
        rows = list(csv.DictReader(Path(path).open(encoding="utf-8")))
        if not rows:
            raise ValueError(f"빈 궤적: {path}")

        def col(name: str, default: float = math.nan) -> np.ndarray:
            out = []
            for r in rows:
                v = r.get(name, "")
                out.append(float(v) if v not in ("", "None", None) else default)
            return np.asarray(out, dtype=float)

        t_fc = col("t_fc")
        use_fc = np.isfinite(t_fc).all()
        amsl = col("alt_amsl_m")
        rel = col("alt_rel_m")
        use_amsl = np.isfinite(amsl).all()
        h = amsl if use_amsl else rel
        ground = float(np.nanmedian(amsl - rel)) if use_amsl else 0.0
        ack = col("cap_ack", 0.0)
        on = col("cap_on", 0.0)
        capture = (ack > 0.5) if (ack > 0.5).any() else (on > 0.5)
        return cls(
            t=t_fc if use_fc else col("t_pi"), lat=col("lat"), lon=col("lon"), h=h,
            yaw=col("yaw_deg", 0.0), roll=col("roll_deg", 0.0), pitch=col("pitch_deg", 0.0),
            capture=capture, time_ref="fc_gps" if use_fc else "pi",
            height_ref="amsl" if use_amsl else "rel_home", ground_h=ground, source=str(path),
        )

    def capture_window(self) -> tuple[float, float]:
        idx = np.flatnonzero(self.capture)
        if idx.size == 0:
            raise ValueError("이 궤적에 레이더 기록 구간(cap_ack/cap_on)이 없다")
        return float(self.t[idx[0]]), float(self.t[idx[-1]])

    def enu(self, origin: Origin) -> np.ndarray:
        return origin.enu(self.lat, self.lon, self.h)

    def at(self, origin: Origin, times: np.ndarray) -> dict[str, np.ndarray]:
        """주어진 시각들의 위치(ENU) · 자세 — 선형 보간 (yaw 는 감아 돌기 처리)."""
        p = self.enu(origin)
        out = {k: np.interp(times, self.t, p[:, i]) for i, k in enumerate(("e", "n", "u"))}
        yaw_unwrapped = np.degrees(np.unwrap(np.radians(self.yaw)))
        out["yaw"] = np.interp(times, self.t, yaw_unwrapped) % 360.0
        out["roll"] = np.interp(times, self.t, self.roll)
        out["pitch"] = np.interp(times, self.t, self.pitch)
        return out
