"""가짜 레이더 원시 파일 — 실제 레이더 없이 「원시 → 어댑터 → 영상 → 화면」 전체를 시험한다.

`adapters.fmcw_dechirped_npz` 의 예시 형식(FMCW 디처프 beat)으로 쓴다:

    beat[N, S] complex64   펄스(처프)마다 S 표본. 빠른 시간은 **처프 가운데 기준**(가운데에서 위상 = −4πR/λ)
    t[N]       float64     펄스 시각 — 궤적 CSV 와 같은 기준(t_fc, FC GPS UTC 초)
    fs, slope  float       표본화 주파수 Hz · 처프 기울기 Hz/s (대역폭 B = slope · S / fs)

신호는 리플렉터마다 beat = 빔무게 · exp(−j4πR/λ) · exp(j2π f_b t),  f_b = 2 · slope · R / c.
위치는 레버암까지 넣은 안테나 위상중심이다(`attitude.phase_center`). 잡음 · 클러터 · 다중 반사는 없다.

    python -m sar_image fakeraw --traj pass02.csv --radar radar.json --cr 37.56672,126.97812 --out radar/pass02.npz
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .attitude import lever_arm, phase_center
from .radar import C, RadarConfig
from .simulate import beam_weight, pulse_times
from .trajectory import Origin, Trajectory


def write_fmcw_npz(out: str | Path, radar: RadarConfig, traj: Trajectory, origin: Origin, targets: list[np.ndarray],
                   meta: dict | None = None, samples: int = 512, noise: float = 0.05, seed: int = 0) -> dict:
    need = radar.missing("wavelength_m", "bandwidth_hz", "prf_hz")
    if need:
        raise ValueError(f"radar.json 에 {', '.join(need)} 가 필요하다")
    rmax = radar.range_max_m or 100.0
    # 가장 먼 거리의 beat 주파수 2·B·R/(c·T) 가 표본화 주파수 S/T 의 0.45 배 안에 들어야 한다 → S 만으로 정해진다
    need_s = 2 * radar.bandwidth_hz * rmax / (C * 0.45)  # type: ignore[operator]
    if samples < need_s:
        raise ValueError(f"표본 {samples} 개로는 {rmax} m 까지 못 담는다 — {math.ceil(need_s)} 개 이상")
    t_chirp = min(0.5e-3, 0.5 / radar.prf_hz)  # type: ignore[operator]
    fs = samples / t_chirp
    slope = radar.bandwidth_hz / t_chirp  # type: ignore[operator]
    t = pulse_times(traj, radar.prf_hz)  # type: ignore[arg-type]
    st = traj.at(origin, t)
    lever, _ = lever_arm(radar, meta)
    pos = phase_center(np.stack([st["e"], st["n"], st["u"]], axis=1), st["yaw"], st["pitch"], st["roll"], lever)
    tf = (np.arange(samples) - (samples - 1) / 2) / fs        # 처프 가운데 기준
    k = 4 * math.pi / radar.wavelength_m  # type: ignore[operator]
    beat = np.zeros((t.size, samples), dtype=np.complex64)
    for tg in targets:
        R = np.linalg.norm(pos - tg[None, :], axis=1)
        w = beam_weight(radar, pos, st["yaw"], st["roll"], tg, st["pitch"])
        fb = 2 * slope * R / C
        beat += (w * np.exp(-1j * k * R))[:, None].astype(np.complex64) * np.exp(2j * np.pi * fb[:, None] * tf[None, :]).astype(np.complex64)
    if noise > 0:
        g = np.random.default_rng(seed)
        beat += (noise * (g.standard_normal(beat.shape) + 1j * g.standard_normal(beat.shape)) / math.sqrt(2)).astype(np.complex64)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, beat=beat, t=t, fs=fs, slope=slope)
    return {"file": str(out), "pulses": int(t.size), "samples": samples, "fs_hz": fs, "slope_hz_s": slope,
            "bytes": out.stat().st_size, "t0": float(t[0]), "t1": float(t[-1])}
