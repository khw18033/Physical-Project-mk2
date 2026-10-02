"""시간 영역 백프로젝션 (BP) — 궤적이 휘어도 맞는 SAR 영상 형성.

입력은 **거리 압축된** 펄스들(복소수, 펄스 × 거리 칸)이다. 레이더마다 원시 형식이 다르므로(FMCW 디처프 ·
펄스 압축 …) 그 앞단은 어댑터(`adapters.py`)가 맡고, 여기는 형식을 모른다.

    영상(x) = Σ_펄스 rc_n( R_n(x) ) · exp(+j 4π R_n(x) / λ),   R_n(x) = |x − p_n|

p_n 은 그 펄스 순간의 안테나 위상중심 — 궤적 CSV 를 펄스 시각으로 보간한 것이다(FC GPS 시각 기준).
드론 궤적의 흔들림을 따로 보정하지 않아도 되는 것이 BP 의 장점이다 — 실제 위치로 거리를 재기 때문이다.
"""

from __future__ import annotations

import math

import numpy as np


def line_grid(start_en: tuple[float, float], heading_deg: float, along: np.ndarray, cross: np.ndarray,
              u: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """선(시작점 · 방위) 기준 격자 → ENU 점들 (len(cross), len(along), 3) 와 그 축. cross + 가 진행 방향 오른쪽."""
    h = math.radians(heading_deg)
    ue, un = math.sin(h), math.cos(h)
    re, rn = un, -ue          # 오른쪽 단위벡터 (e, n)
    A, X = np.meshgrid(along, cross)
    e = start_en[0] + A * ue + X * re
    n = start_en[1] + A * un + X * rn
    return np.stack([e, n, np.full_like(e, u)], axis=-1), np.stack([A, X], axis=-1)


def backproject(rc: np.ndarray, range_axis: np.ndarray, positions: np.ndarray, wavelength_m: float,
                grid: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """rc: (N, M) 복소 · range_axis: (M,) 균일 간격 m · positions: (N, 3) ENU · grid: (..., 3) → 복소 영상(...)."""
    shape = grid.shape[:-1]
    g = grid.reshape(-1, 3)
    img = np.zeros(g.shape[0], dtype=np.complex128)
    r0 = float(range_axis[0])
    dr = float(range_axis[1] - range_axis[0])
    k = 4.0 * math.pi / wavelength_m
    m = rc.shape[1]
    for n in range(rc.shape[0]):
        R = np.sqrt(((g - positions[n]) ** 2).sum(axis=1))
        idx = (R - r0) / dr
        i0 = np.floor(idx).astype(np.int64)
        frac = idx - i0
        ok = (i0 >= 0) & (i0 < m - 1)
        i0c = np.clip(i0, 0, m - 2)
        s = rc[n, i0c] * (1 - frac) + rc[n, i0c + 1] * frac
        s = np.where(ok, s, 0)
        w = 1.0 if weights is None else weights[n]
        img += w * s * np.exp(1j * k * R)
    return img.reshape(shape)


def peak_metrics(img: np.ndarray, along: np.ndarray, cross: np.ndarray) -> dict:
    """가장 밝은 점의 위치와 −3 dB 폭(방위 · 거리 방향). 점 표적(리플렉터)의 초점 품질을 잰다."""
    a = np.abs(img)
    iy, ix = np.unravel_index(int(np.argmax(a)), a.shape)
    peak = a[iy, ix]

    def width(profile: np.ndarray, axis: np.ndarray, i: int) -> float:
        half = peak / math.sqrt(2)
        lo = i
        while lo > 0 and profile[lo] >= half:
            lo -= 1
        hi = i
        while hi < profile.size - 1 and profile[hi] >= half:
            hi += 1
        # 선형 보간으로 경계
        def cross_at(j0: int, j1: int) -> float:
            p0, p1 = profile[j0], profile[j1]
            if p1 == p0:
                return float(axis[j0])
            return float(axis[j0] + (half - p0) * (axis[j1] - axis[j0]) / (p1 - p0))
        left = cross_at(lo, lo + 1) if lo < i else float(axis[i])
        right = cross_at(hi - 1, hi) if hi > i else float(axis[i])
        return abs(right - left)

    pslr = None
    prof = a[iy, :]
    if prof.size > 5:
        # 주엽 밖 가장 큰 옆엽 (방위 방향)
        j = ix
        while j > 0 and prof[j - 1] < prof[j]:
            j -= 1
        k = ix
        while k < prof.size - 1 and prof[k + 1] < prof[k]:
            k += 1
        side = np.concatenate([prof[:j], prof[k + 1:]])
        if side.size:
            pslr = 20 * math.log10(max(side.max(), 1e-30) / peak)
    return {
        "peak_along_m": float(along[ix]), "peak_cross_m": float(cross[iy]),
        "res_along_m": width(a[iy, :], along, ix), "res_cross_m": width(a[:, ix], cross, iy),
        "pslr_db": None if pslr is None else round(pslr, 1),
    }
