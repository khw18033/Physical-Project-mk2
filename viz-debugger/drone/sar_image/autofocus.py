"""리플렉터 기준 자동 초점 — RTK 로는 모자란 궤적 정밀도를 리플렉터로 메운다.

X대역(λ≈3 cm)에서 초점이 맞으려면 시선 방향 위치 오차가 λ/8 ≈ 4 mm 안이어야 한다. RTK 는 보통 1~2 cm 라
그대로 쓰면 리플렉터 봉우리가 8~13 dB 떨어지고 엉뚱한 자리에 맺힌다(sar_image 시험, 2026-10-02).

위치를 아는 리플렉터는 펄스마다 「있어야 할 위상」을 알려 준다:
    φ_err(n) = arg( rc_n(R̂_n) · exp(+j 4π R̂_n / λ) )      R̂_n = 궤적으로 계산한 리플렉터까지 거리
이 φ_err 가 궤적 오차가 만든 위상이다. 아주 짧게(기본 5 펄스) 평활해 잡음만 덜고 모든 펄스에서 빼면,
리플렉터 둘레의 장면도 같이 초점이 맞는다(오차가 장면 안에서 거의 같다고 볼 수 있는 범위에서 — 수십 m).
평활을 길게 잡으면 실제 오차까지 지운다 — 2 cm 오차 시험에서 101 펄스는 −10 dB, 5 펄스는 −1.3 dB 까지 회복.

한계: 리플렉터가 빔 안에 있는 펄스에서만 잴 수 있다. 그 밖의 펄스는 가장 가까운 잰 값으로 이어 붙인다.
리플렉터가 클러터보다 충분히 밝아야 한다(삼면체 리플렉터를 쓰는 이유).
"""

from __future__ import annotations

import math

import numpy as np


def estimate_phase_error(rc: np.ndarray, range_axis: np.ndarray, positions: np.ndarray, wavelength_m: float,
                         reflector: np.ndarray, smooth_pulses: int = 5, min_rel_amp: float = 0.2) -> dict:
    R = np.linalg.norm(positions - reflector[None, :], axis=1)
    idx = (R - range_axis[0]) / (range_axis[1] - range_axis[0])
    i0 = np.clip(np.floor(idx).astype(int), 0, range_axis.size - 2)
    frac = idx - i0
    s = rc[np.arange(rc.shape[0]), i0] * (1 - frac) + rc[np.arange(rc.shape[0]), i0 + 1] * frac
    z = s * np.exp(1j * 4 * math.pi * R / wavelength_m)
    amp = np.abs(z)
    good = amp >= min_rel_amp * amp.max()
    if good.sum() < 10:
        raise ValueError("리플렉터가 빔 안에 충분히 들지 않았다 — 자동 초점을 할 수 없다")
    # 이웃한 펄스 사이 위상 차를 펼쳐(unwrap) 누적 — 순간 잡음보다 차분이 안정적이다
    zg = z[good]
    dphi = np.angle(zg[1:] * np.conj(zg[:-1]))
    phi_good = np.concatenate([[np.angle(zg[0])], np.angle(zg[0]) + np.cumsum(dphi)])
    k = max(3, smooth_pulses | 1)
    pad = np.pad(phi_good, (k // 2, k // 2), mode="edge")
    phi_smooth = np.convolve(pad, np.ones(k) / k, mode="valid")
    n = np.arange(rc.shape[0])
    phi = np.interp(n, n[good], phi_smooth)
    phi -= phi[good].mean()
    return {"phase_err": phi, "measured": good, "los_err_m": phi * wavelength_m / (4 * math.pi)}


def apply_correction(rc: np.ndarray, phase_err: np.ndarray) -> np.ndarray:
    return rc * np.exp(-1j * phase_err)[:, None]


def estimate_phase_error_multi(rc: np.ndarray, range_axis: np.ndarray, positions: np.ndarray, wavelength_m: float,
                               reflectors: list[np.ndarray], smooth_pulses: int = 5, min_rel_amp: float = 0.2) -> dict:
    """여러 리플렉터를 이어 붙인다 — 리플렉터 하나는 자기가 빔 안에 있던 펄스만 재므로, 선을 따라 개구 길이보다
    촘촘히(예: 개구의 0.8배 간격) 놓고 겹치는 펄스에서 상수 위상을 맞춰 잇는다. 겹치는 곳은 세기로 가중 평균.

    리플렉터마다 시선 방향이 조금 달라 같은 궤적 오차도 조금 다른 위상이 된다 — 선에서 같은 쪽 · 비슷한 거리에 두면 작다.
    """
    n = rc.shape[0]
    phi = np.zeros(n)
    wsum = np.zeros(n)
    have = np.zeros(n, dtype=bool)
    ests = []
    for cr in reflectors:
        try:
            ests.append(estimate_phase_error(rc, range_axis, positions, wavelength_m, cr, smooth_pulses, min_rel_amp))
        except ValueError:
            continue
    if not ests:
        raise ValueError("빔 안에 충분히 든 리플렉터가 없다 — 자동 초점을 할 수 없다")
    # 측정 구간이 이른 것부터 이어 붙인다
    ests.sort(key=lambda e: int(np.flatnonzero(e["measured"])[0]))
    for e in ests:
        m = e["measured"]
        p = e["phase_err"]
        overlap = m & have
        if overlap.any():
            cur = phi[overlap] / wsum[overlap]
            p = p + float(np.mean(np.angle(np.exp(1j * (cur - p[overlap])))))   # 상수 위상을 앞선 것에 맞춘다
        elif have.any():
            # 겹침이 없으면 앞선 구간 끝 값에 잇는다 (이음매에서 위상이 튀지 않게)
            last = int(np.flatnonzero(have)[-1])
            first = int(np.flatnonzero(m)[0])
            p = p + (phi[last] / wsum[last] - p[first])
        w = m.astype(float)
        phi += p * w
        wsum += w
        have |= m
    out = np.zeros(n)
    idx = np.arange(n)
    out[have] = phi[have] / wsum[have]
    out = np.interp(idx, idx[have], out[have])
    out -= out[have].mean()
    return {"phase_err": out, "measured": have, "los_err_m": out * wavelength_m / (4 * math.pi), "used": len(ests)}


def estimate_trajectory_error(rc: np.ndarray, range_axis: np.ndarray, positions: np.ndarray, wavelength_m: float,
                              reflectors: list[np.ndarray], min_rel_amp: float = 0.2, min_visible: int = 4,
                              iterations: int = 60) -> dict:
    """리플렉터 **4개 이상**으로 궤적 오차를 3차원으로 추정한다 → 보정한 궤적으로 영상을 만들면 리플렉터가 아닌 곳도 맞는다.

    위상 하나는 시선 방향 한 성분만 알려 준다(φ_i = k·u_i·δp + c_i). 그래서 리플렉터 하나 기준 보정은 그 둘레 몇 m 에서만
    맞는다(2 cm 오차 · 경사 28 m 에서 약 3 m). 리플렉터마다 모르는 상수 c_i 가 하나씩 있어, 펄스당 미지수 3개(δp)에
    리플렉터 3개로는 c 가 정해지지 않는다 — **동시에 보이는 리플렉터가 4개 이상**이어야 풀린다.
    δp(펄스마다) 와 c(리플렉터마다)를 번갈아 최소제곱으로 푼다.

    시험(예시 X대역 · 2 cm RTK 오차 · 경사 28 m): 표적 시선 방향 잔차 3개 7.7 mm → 4개 2.9 mm (λ/8 = 3.9 mm).
    현장 배치: 삼면체 넷 이상을 몇 m 간격(개구보다 좁게)으로, 지상거리도 서로 다르게 — 모두가 한꺼번에 빔에 들어오게.
    4개 이상이 동시에 안 보이는 펄스는 가장 가까운 추정값으로 잇는다.
    """
    k = 4 * math.pi / wavelength_m
    n = rc.shape[0]
    phis, us, ms = [], [], []
    for cr in reflectors:
        d = positions - cr[None, :]
        R = np.linalg.norm(d, axis=1)
        idx = (R - range_axis[0]) / (range_axis[1] - range_axis[0])
        i0 = np.clip(np.floor(idx).astype(int), 0, range_axis.size - 2)
        frac = idx - i0
        s = rc[np.arange(n), i0] * (1 - frac) + rc[np.arange(n), i0 + 1] * frac
        z = s * np.exp(1j * k * R)
        m = np.abs(z) >= min_rel_amp * np.abs(z).max()
        ph = np.full(n, np.nan)
        ii = np.flatnonzero(m)
        if ii.size:
            ph[ii] = np.unwrap(np.angle(z[ii]))
        phis.append(ph)
        us.append(d / R[:, None])
        ms.append(m)
    Ph, U, M = np.array(phis), np.array(us), np.array(ms)
    J = np.flatnonzero(M.sum(0) >= max(4, min_visible))
    if J.size < 10:
        raise ValueError(f"리플렉터 {max(4, min_visible)}개 이상이 동시에 빔 안에 든 펄스가 거의 없다 — 배치를 좁혀라")
    # 푼 구간이 짧으면 나머지는 그 값으로 메워질 뿐이다 — 시간에 따라 흔들리는 오차는 오히려 나빠진다(CANSAR 가짜 · 3 cm 사인파:
    # 4715 펄스 중 132 만 풀려 위치 오차 0.16 → 0.81 m). 리플렉터가 하나라도 보이는 펄스의 절반은 풀려야 쓴다
    seen = int(M.any(0).sum())
    if J.size < 0.5 * seen:
        raise ValueError(f"리플렉터 {max(4, min_visible)}개가 동시에 보이는 펄스가 {J.size}/{seen} 뿐 — 이어 붙이기로 내려간다")
    c = np.array([np.nanmean(Ph[i]) if np.isfinite(Ph[i]).any() else 0.0 for i in range(len(reflectors))])
    est = np.zeros((n, 3))
    for _ in range(iterations):
        for j in J:
            rows = np.flatnonzero(M[:, j])
            est[j] = np.linalg.lstsq(k * U[rows, j, :], Ph[rows, j] - c[rows], rcond=None)[0]
        for i in range(len(reflectors)):
            jj = J[M[i, J]]
            if jj.size:
                c[i] = np.mean(Ph[i, jj] - k * (U[i, jj, :] * est[jj]).sum(1))
    solved = np.zeros(n, dtype=bool)
    solved[J] = True
    idx = np.arange(n)
    err = np.stack([np.interp(idx, J, est[J, i]) for i in range(3)], axis=1)
    err -= err[J].mean(axis=0)
    return {"pos_err": err, "solved": solved, "corrected_positions": positions - err, "visible_counts": M.sum(0)}
