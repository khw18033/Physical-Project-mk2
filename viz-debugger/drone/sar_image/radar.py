"""레이더 · 안테나 설정 — `radar.json` 하나. 레이더 팀이 값을 채운다.

모르는 값은 `null` 로 두면 그 값이 필요한 계산만 「모름」으로 빠진다(지어 채우지 않는다).
`example_radar.json` 의 숫자는 **예시**다 — 실제 레이더와 다르다.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

C = 299_792_458.0


@dataclass
class RadarConfig:
    # 신호
    wavelength_m: float | None = None       # 중심 파장 (영상 형성에 필수)
    bandwidth_hz: float | None = None       # 대역폭 → 거리 해상도 c/2B
    prf_hz: float | None = None             # 펄스(처프) 반복 주파수
    range_min_m: float | None = None        # 기록하는 경사거리 범위
    range_max_m: float | None = None
    # 안테나 (기체 기준)
    side: str = "right"                     # right | left — 진행 방향 기준 어느 쪽을 보나
    depression_deg: float | None = None     # 수평에서 내려다보는 각 (빔 중심)
    el_beamwidth_deg: float | None = None   # 고도 방향 3 dB 빔폭
    az_beamwidth_deg: float | None = None   # 방위 방향 3 dB 빔폭
    squint_deg: float = 0.0                 # 앞(+)/뒤(-)로 비스듬히 단 각
    antenna_offset_m: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])  # 기체 중심 → 위상중심 [앞, 오른쪽, 아래]
    note: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "RadarConfig":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def side_sign(self) -> float:
        return 1.0 if self.side == "right" else -1.0

    @property
    def range_resolution_m(self) -> float | None:
        return None if not self.bandwidth_hz else C / (2.0 * self.bandwidth_hz)

    def missing(self, *names: str) -> list[str]:
        return [n for n in names if getattr(self, n) is None]


def az_resolution_m(wavelength_m: float, slant_range_m: float, aperture_m: float) -> float:
    """방위 해상도 ≈ λR / 2L (스트립맵, 처리한 개구 L)."""
    return wavelength_m * slant_range_m / (2.0 * max(aperture_m, 1e-9))


def aperture_length_m(slant_range_m: float, az_beamwidth_deg: float) -> float:
    """빔이 한 점을 비추는 동안 지나가는 거리 = 합성 개구 길이."""
    return 2.0 * slant_range_m * math.tan(math.radians(az_beamwidth_deg) / 2.0)
