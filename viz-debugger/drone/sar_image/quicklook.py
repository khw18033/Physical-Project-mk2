"""패스 직후 빠른 확인 — 거리-시간 그림 위에 리플렉터의 예상 거리 곡선, 그리고 레이더 시각 오프셋 추정.

거리 압축 데이터 |rc(t, R)| 를 그대로 그리면 리플렉터는 「가까워졌다 멀어지는」 곡선으로 보인다.
궤적(+레버암)으로 계산한 예상 곡선이 그 위에 얹히면 안테나가 리플렉터를 봤고 시각 · 위치가 맞는 것이다.
영상을 만들기 전에 몇 초 만에 답이 나온다.

시각 오프셋: 레이더가 찍은 펄스 시각에 dt 를 더해야 궤적 시각과 맞는다고 보고, 그 dt 를 데이터에서 찾는다.
  1) 거친 단계 ±1 s — 예상 곡선을 따라 |rc| 를 더한 값(비간섭)이 가장 큰 dt
  2) 고운 단계 ±40 ms — 리플렉터 자리 영상 값 |Σ rc(R)·e^{jkR}|(간섭, 백프로젝션 한 점)이 가장 큰 dt
리플렉터마다 따로 구해 서로 맞으면(차이 2 ms 안) 믿는다. CAP_ACK 지연 측정의 검산이다.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .attitude import phase_center
from .trajectory import Origin, Trajectory


def antenna_positions(traj: Trajectory, origin: Origin, t: np.ndarray, lever: np.ndarray) -> np.ndarray:
    st = traj.at(origin, t)
    return phase_center(np.stack([st["e"], st["n"], st["u"]], axis=1), st["yaw"], st["pitch"], st["roll"], lever)


def _sample(rc: np.ndarray, rng: np.ndarray, R: np.ndarray) -> np.ndarray:
    idx = (R - rng[0]) / (rng[1] - rng[0])
    ok = (idx >= 0) & (idx < rng.size - 1)
    i0 = np.clip(np.floor(idx).astype(np.int64), 0, rng.size - 2)
    fr = idx - i0
    rows = np.arange(rc.shape[0])
    s = rc[rows, i0] * (1 - fr) + rc[rows, i0 + 1] * fr
    return np.where(ok, s, 0)


def estimate_time_offset(t: np.ndarray, rng: np.ndarray, rc: np.ndarray, traj: Trajectory, origin: Origin,
                         lever: np.ndarray, reflector: np.ndarray, wavelength_m: float,
                         coarse_s: float = 1.0, fine_s: float = 0.04) -> dict:
    """리플렉터 하나로 dt(초) — 레이더 시각 + dt = 궤적 시각."""
    k = 4 * math.pi / wavelength_m
    lo, hi = float(traj.t[0]), float(traj.t[-1])

    def positions(dt: float) -> tuple[np.ndarray, np.ndarray]:
        tt = t + dt
        m = (tt >= lo) & (tt <= hi)
        return antenna_positions(traj, origin, tt[m], lever), m

    coarse = np.arange(-coarse_s, coarse_s + 1e-9, 0.01)
    score_c = []
    for dt in coarse:
        p, m = positions(dt)
        R = np.linalg.norm(p - reflector[None, :], axis=1)
        score_c.append(float(np.abs(_sample(rc[m], rng, R)).sum()) if m.any() else 0.0)
    dt0 = float(coarse[int(np.argmax(score_c))])
    fine = dt0 + np.arange(-fine_s, fine_s + 1e-9, 0.0005)
    score_f = []
    for dt in fine:
        p, m = positions(dt)
        R = np.linalg.norm(p - reflector[None, :], axis=1)
        score_f.append(float(np.abs((_sample(rc[m], rng, R) * np.exp(1j * k * R)).sum())) if m.any() else 0.0)
    j = int(np.argmax(score_f))
    dt1 = float(fine[j])
    if 0 < j < len(fine) - 1:                         # 꼭짓점 포물선 보간
        a, b, c = score_f[j - 1], score_f[j], score_f[j + 1]
        den = a - 2 * b + c
        if den < 0:
            dt1 += 0.5 * (a - c) / den * 0.0005
    # 보정하면 리플렉터 자리 밝기가 얼마나 오르나 (dt = 0 대비)
    p, m = positions(0.0)
    R = np.linalg.norm(p - reflector[None, :], axis=1)
    s0 = float(np.abs((_sample(rc[m], rng, R) * np.exp(1j * k * R)).sum())) if m.any() else 0.0
    gain = score_f[j] / max(s0, 1e-30)
    return {"dt_s": round(dt1, 5), "coarse_dt_s": round(dt0, 3), "focus_gain_db": round(20 * math.log10(max(gain, 1e-30)), 2)}


def estimate_range_bias(t: np.ndarray, rng: np.ndarray, rc: np.ndarray, traj: Trajectory, origin: Origin,
                        lever: np.ndarray, reflector: np.ndarray, window_m: float = 1.5) -> dict | None:
    """리플렉터 하나로 거리 치우침(m) — 레이더가 잰 거리 − 궤적으로 계산한 거리. 레이더 내부 지연(roff) 보정값.

    펄스마다 예상 거리 ±window_m 안에서 |rc| 봉우리를 찾아(포물선 보간) 예상과의 차이를 모으고, 밝은 절반의 중앙값을 쓴다.
    + 면 레이더가 실제보다 멀게 잰다 → 어댑터의 roff 를 그만큼 **늘린다**. 시각 오프셋을 먼저 고친 뒤에 부른다."""
    lo, hi = float(traj.t[0]), float(traj.t[-1])
    m = (t >= lo) & (t <= hi)
    if m.sum() < 20:
        return None
    p = antenna_positions(traj, origin, t[m], lever)
    R = np.linalg.norm(p - reflector[None, :], axis=1)
    dr = float(rng[1] - rng[0])
    half = max(2, int(round(window_m / dr)))
    a = np.abs(rc[m])
    i_pred = np.round((R - rng[0]) / dr).astype(int)
    ok = (i_pred - half >= 1) & (i_pred + half < rng.size - 1)
    if ok.sum() < 20:
        return None
    rows = np.flatnonzero(ok)
    idx = i_pred[rows, None] + np.arange(-half, half + 1)[None, :]
    seg = a[rows[:, None], idx]
    j = np.argmax(seg, axis=1)
    pk = seg[np.arange(rows.size), j]
    jj = np.clip(j, 1, seg.shape[1] - 2)
    y0, y1, y2 = seg[np.arange(rows.size), jj - 1], seg[np.arange(rows.size), jj], seg[np.arange(rows.size), jj + 1]
    den = y0 - 2 * y1 + y2
    frac = np.where(den < 0, 0.5 * (y0 - y2) / np.where(den < 0, den, -1), 0.0)
    r_meas = rng[idx[np.arange(rows.size), jj]] + frac * dr
    bias = r_meas - R[rows]
    bright = pk >= np.median(pk)                       # 빔 안 · 밝은 펄스만
    b = bias[bright]
    return {"bias_m": round(float(np.median(b)), 4), "spread_m": round(float(np.percentile(b, 75) - np.percentile(b, 25)), 4),
            "pulses": int(b.size)}


def combine_offsets(per: list[dict], agree_s: float = 0.002) -> dict | None:
    if not per:
        return None
    dts = np.array([p["dt_s"] for p in per])
    med = float(np.median(dts))
    spread = float(dts.max() - dts.min())
    return {"dt_s": round(med, 5), "spread_s": round(spread, 5), "reflectors": len(per),
            "consistent": bool(len(per) >= 2 and spread <= agree_s) if len(per) > 1 else None}


def rangetime_png(path: Path, t: np.ndarray, rng: np.ndarray, rc: np.ndarray, curves: list[tuple[str, np.ndarray, np.ndarray, np.ndarray]],
                  capture: tuple[float, float] | None, title: str, max_cols: int = 2000, dyn_db: float = 35.0) -> None:
    """가로 = 시간(패스 시작부터 초), 세로 = 경사거리. curves: (이름, t, R, 빔 안 여부)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    step = max(1, t.size // max_cols)
    a = np.abs(rc[::step]).astype(np.float32)
    db = 20 * np.log10(a / max(float(a.max()), 1e-30) + 1e-9)
    t0 = float(t[0])
    fig, ax = plt.subplots(figsize=(8.5, 4.2), dpi=120)
    ax.imshow(db.T, origin="lower", aspect="auto", cmap="magma", vmin=-dyn_db, vmax=0,
              extent=[0, float(t[-1] - t0), float(rng[0]), float(rng[-1])])
    colors = ["#21d4fd", "#3df07a", "#ffd400", "#ff7ad9", "#ffffff", "#ff9f43"]
    for i, (name, tc, R, inb) in enumerate(curves):
        col = colors[i % len(colors)]
        ax.plot(tc - t0, np.where(inb, R, np.nan), "--", color=col, lw=1.4, label=f"{name} (predicted)")
        ax.plot(tc - t0, np.where(~inb, R, np.nan), ":", color=col, lw=0.8, alpha=0.6)
    if capture is not None:
        for x in capture:
            ax.axvline(x - t0, color="#ffffff", lw=0.8, alpha=0.5)
    ax.set_xlabel("time since first pulse (s)")
    ax.set_ylabel("slant range (m)")
    ax.set_title(title, fontsize=9)
    if curves:
        ax.legend(loc="upper right", fontsize=7, framealpha=0.5)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
