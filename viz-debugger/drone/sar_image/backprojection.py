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


def backproject_fast(rc: np.ndarray, range_axis: np.ndarray, positions: np.ndarray, wavelength_m: float,
                     grid: np.ndarray, weights: np.ndarray | None = None, workers: int | None = None,
                     block_px: int = 65_536, **_ctx) -> np.ndarray:
    """`backproject` 와 같은 영상을 32비트 · 여러 코어로. 결과는 complex64.

    32비트의 유효숫자는 7자리라 **좌표가 크면 영상이 깨진다**(UTM 수백만 m → 0.5 m 오차 · 피크 −19 dB 를 확인했다).
    그래서 64비트일 때 영상 중심을 빼서 수십 m 단위로 옮긴 뒤 32비트로 바꾼다 — 거리는 평행이동에 안 변하므로
    부르는 쪽이 어떤 좌표를 넘겨도 안전하다. 64비트 `backproject` 와의 차이는 시험이 −50 dB 아래로 묶는다.
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    shape = grid.shape[:-1]
    g64 = np.asarray(grid, dtype=np.float64).reshape(-1, 3)
    center = g64.mean(axis=0)
    g = (g64 - center).astype(np.float32)
    p = (np.asarray(positions, dtype=np.float64) - center).astype(np.float32)
    rcf = np.ascontiguousarray(rc, dtype=np.complex64)
    w = None if weights is None else np.asarray(weights, dtype=np.float32)
    r0 = np.float32(range_axis[0])
    inv_dr = np.float32(1.0 / float(range_axis[1] - range_axis[0]))
    k = np.float32(4.0 * math.pi / wavelength_m)
    m = rcf.shape[1]
    out = np.zeros(g.shape[0], dtype=np.complex64)

    def run(lo: int, hi: int) -> None:
        gx, gy, gz = (np.ascontiguousarray(g[lo:hi, i]) for i in range(3))
        acc = np.zeros(hi - lo, dtype=np.complex64)
        for n in range(rcf.shape[0]):
            dx = gx - p[n, 0]
            dy = gy - p[n, 1]
            dz = gz - p[n, 2]
            R = np.sqrt(dx * dx + dy * dy + dz * dz)
            idx = (R - r0) * inv_dr
            ok = (idx >= 0) & (idx < m - 1)
            i0 = np.clip(idx, 0, m - 2).astype(np.int32)
            frac = idx - i0
            row = rcf[n]
            s = row[i0] * (1 - frac) + row[i0 + 1] * frac
            ph = k * R
            v = s * (np.cos(ph) + 1j * np.sin(ph)).astype(np.complex64)
            if w is not None:
                v *= w[n]
            acc += np.where(ok, v, 0)
        out[lo:hi] = acc

    n_px = g.shape[0]
    # 8 개를 넘기면 메모리 대역폭에 막혀 오히려 느려진다(96 코어 서버에서 32 개가 8 개보다 느렸다)
    workers = workers or min(os.cpu_count() or 1, 8)
    blocks = [(lo, min(lo + block_px, n_px)) for lo in range(0, n_px, block_px)]
    if workers <= 1 or len(blocks) == 1:
        for lo, hi in blocks:
            run(lo, hi)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(lambda b: run(*b), blocks))
    return out.reshape(shape)


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
