"""점 표적(코너리플렉터) 신호를 실제 비행 궤적으로 합성한다 — 영상 형성 · 커버리지 판정을 레이더 없이 시험하는 용도.

거리 압축 뒤의 모양만 만든다: 펄스마다 경사거리 R 에 sinc(2B(r−R)/c) 봉우리 · 위상 exp(−j4πR/λ) · 빔 무게.
실제 레이더의 잡음 · 다중 반사 · 클러터는 없다(시험용).
"""

from __future__ import annotations

import math

import numpy as np

from .radar import C, RadarConfig
from .trajectory import Origin, Trajectory


def pulse_times(traj: Trajectory, prf_hz: float, only_capture: bool = True) -> np.ndarray:
    t0, t1 = traj.capture_window() if only_capture else (float(traj.t[0]), float(traj.t[-1]))
    return np.arange(t0, t1, 1.0 / prf_hz)


def beam_weight(radar: RadarConfig, pos: np.ndarray, yaw: np.ndarray, roll: np.ndarray, target: np.ndarray,
                pitch: np.ndarray | float = 0.0) -> np.ndarray:
    """가우시안 근사 빔 무게 (3 dB 폭 = 빔폭). 각도는 판정과 같은 안테나 좌표계(`coverage.antenna_angles`)."""
    from .coverage import antenna_angles

    az_off, el_off = antenna_angles(radar, target[None, :] - pos, yaw, roll, pitch)
    w = np.ones(pos.shape[0])
    ln2 = math.log(2)
    if radar.az_beamwidth_deg:
        w *= np.exp(-4 * ln2 * (az_off / radar.az_beamwidth_deg) ** 2)
    if radar.depression_deg is not None and radar.el_beamwidth_deg:
        w *= np.exp(-4 * ln2 * (el_off / radar.el_beamwidth_deg) ** 2)
    return w


def synthesize(radar: RadarConfig, traj: Trajectory, origin: Origin, targets: list[np.ndarray],
               range_axis: np.ndarray, noise: float = 0.0, seed: int = 0,
               lever_frd: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """→ (펄스 시각, 안테나 위상중심 (N,3), 거리 압축 데이터 (N,M)).

    `lever_frd` 를 주면 신호는 **보고 위치 + 자세로 돈 레버암**(실제 안테나)에서 나온다. 돌려주는 위치도 그 점이다.
    영상에 보고 위치를 그대로 쓰면 무엇을 잃는지 시험할 때 쓴다."""
    need = radar.missing("wavelength_m", "bandwidth_hz", "prf_hz")
    if need:
        raise ValueError(f"radar.json 에 {', '.join(need)} 가 필요하다")
    t = pulse_times(traj, radar.prf_hz)  # type: ignore[arg-type]
    st = traj.at(origin, t)
    pos = np.stack([st["e"], st["n"], st["u"]], axis=1)
    if lever_frd is not None:
        from .attitude import phase_center
        pos = phase_center(pos, st["yaw"], st["pitch"], st["roll"], lever_frd)
    rc = np.zeros((t.size, range_axis.size), dtype=np.complex128)
    k = 4 * math.pi / radar.wavelength_m  # type: ignore[operator]
    for tg in targets:
        R = np.linalg.norm(pos - tg[None, :], axis=1)
        w = beam_weight(radar, pos, st["yaw"], st["roll"], tg, st["pitch"])
        rc += (w[:, None] * np.sinc(2 * radar.bandwidth_hz * (range_axis[None, :] - R[:, None]) / C)  # type: ignore[operator]
               * np.exp(-1j * k * R)[:, None])
    if noise > 0:
        rng = np.random.default_rng(seed)
        rc += noise * (rng.standard_normal(rc.shape) + 1j * rng.standard_normal(rc.shape)) / math.sqrt(2)
    return t, pos, rc
