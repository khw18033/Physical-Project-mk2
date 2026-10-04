"""GPU(torch · CUDA) 백프로젝션 · 리플렉터 없는 자동 초점 — 파이프라인의 `--former` · `--focuser` 자리에 꽂는다.

  --former  sar_image.gpu:backproject_gpu     `backprojection.backproject_fast` 와 같은 영상(규약 · 32비트 원점 옮기기)을 GPU 로
  --focuser sar_image.gpu:entropy_focus       레이더 팀 `cansar_flight.py --af` 의 자동 초점을 옮긴 것:
                                              영상에서 가장 밝은 곳 둘레 ±8 m 창의 **엔트로피**(흐릴수록 크다)를 줄이도록
                                              궤적을 매듭 K 개(선형 보간)로 진행 · 옆 방향으로 옮긴다(Adam). 리플렉터 좌표를 **쓰지 않는다**.

torch 가 없거나 CUDA 가 없으면 backproject_gpu 는 CPU 판(backproject_fast)으로, entropy_focus 는 torch CPU 로 돈다(느리다).
레이더 팀 판과 다른 점: 3차원(ENU) 위치 · 우리 위상 규약 exp(+j4πR/λ) · 매듭 수 · 반복 수 · 창 크기를 인자로.
기본값을 바꿨다(가짜 CANSAR · RTK 사인파 오차 3 cm 옆 + 2 cm 위 · 주기 8 s 로 비교 — af_compare.py):
  그쪽 기본 lr 0.05 m 는 파장(5.45 cm)만 해서 한 걸음에 최적점을 건너뛴다 → lr 0.003, 매듭 16, 120 번.
  결과(리플렉터 중앙값): 초점 없음 위치 오차 0.156 m · PSLR −3.6 dB → 엔트로피 0.04 m · −16 dB (오차 없을 때 −32 dB).
  창 하나 · 수평 보정만이라 높이 오차는 다 못 지운다 — 창 여러 개 · 높이 성분은 다음 일.
"""

from __future__ import annotations

import math

import numpy as np

from .backprojection import backproject_fast, line_grid


def _torch():
    try:
        import torch
    except ImportError:
        return None, None
    return torch, ("cuda" if torch.cuda.is_available() else "cpu")


def _bp_torch(torch, rc_t, r0: float, dr: float, pos_t, grid_t, k: float, chunk: int):  # noqa: ANN001, ANN202
    """rc_t (N, M) complex64 · pos_t (N, 3) · grid_t (P, 3) float32 → (P,) complex64. 미분 가능."""
    m = rc_t.shape[1]
    out = torch.zeros(grid_t.shape[0], dtype=torch.complex64, device=grid_t.device)
    for lo in range(0, pos_t.shape[0], chunk):
        p = pos_t[lo:lo + chunk]                                         # (B, 3)
        d = grid_t[None, :, :] - p[:, None, :]                           # (B, P, 3)
        R = torch.sqrt((d * d).sum(-1))                                  # (B, P)
        idx = (R - r0) / dr
        ok = (idx >= 0) & (idx < m - 1)
        i0 = idx.detach().clamp(0, m - 2).floor().long()
        frac = (idx - i0.to(idx.dtype)).clamp(0, 1)
        rows = rc_t[lo:lo + chunk]                                       # (B, M)
        s = torch.gather(rows, 1, i0) * (1 - frac) + torch.gather(rows, 1, i0 + 1) * frac
        v = s * torch.exp(1j * k * R)
        out = out + torch.where(ok, v, torch.zeros_like(v)).sum(0)
    return out


def backproject_gpu(rc: np.ndarray, range_axis: np.ndarray, positions: np.ndarray, wavelength_m: float,
                    grid: np.ndarray, weights: np.ndarray | None = None, chunk: int | None = None, **ctx) -> np.ndarray:
    """`backproject_fast` 와 같은 결과(complex64). GPU 가 없으면 그것을 그대로 부른다."""
    torch, dev = _torch()
    if torch is None or dev != "cuda" or weights is not None:
        return backproject_fast(rc, range_axis, positions, wavelength_m, grid, weights, **ctx)
    shape = grid.shape[:-1]
    g64 = np.asarray(grid, dtype=np.float64).reshape(-1, 3)
    center = g64.mean(axis=0)
    with torch.no_grad():
        g = torch.tensor((g64 - center).astype(np.float32), device=dev)
        p = torch.tensor((np.asarray(positions, np.float64) - center).astype(np.float32), device=dev)
        r = torch.tensor(np.ascontiguousarray(rc, dtype=np.complex64), device=dev)
        # (B × P) 한 덩어리가 GPU 메모리 1 GB 남짓이 되게
        chunk = chunk or max(1, int(4e7 // max(g.shape[0], 1)))
        img = _bp_torch(torch, r, float(range_axis[0]), float(range_axis[1] - range_axis[0]), p, g,
                        4.0 * math.pi / wavelength_m, chunk)
        return img.cpu().numpy().reshape(shape)


def _entropy(torch, img):  # noqa: ANN001, ANN202
    p = img.abs() ** 2
    p = p / p.sum()
    return -(p * torch.log(p + 1e-20)).sum()


def entropy_focus(rc: np.ndarray, range_axis: np.ndarray, positions: np.ndarray, wavelength_m: float,
                  reflectors=None, heading_deg: float = 0.0, radar=None, knots: int = 16, iters: int = 120,  # noqa: ANN001
                  lr: float = 0.003, half_window_m: float = 8.0, res_m: float = 0.1, search_step_m: float = 0.25,
                  center: tuple[float, float] | None = None, **ctx) -> dict:
    """리플렉터 없는 자동 초점 — {"positions", "method", 엔트로피 전 · 후, 최대 이동} (pipeline 의 focuser 규약).

    1) 계획 선 기준 영상(거칠게)에서 가장 밝은 점을 찾는다(center 를 주면 그곳)
    2) 그 둘레 ±half_window_m 창을 res_m 격자로, 궤적 보정(진행 · 옆, 매듭 knots 개)을 Adam 으로 iters 번
    3) 엔트로피가 가장 낮았던 보정을 돌려준다
    """
    torch, dev = _torch()
    if torch is None:
        raise RuntimeError("entropy_focus 에는 torch 가 필요하다 — uv pip install torch")
    pos64 = np.asarray(positions, np.float64)
    hd = math.radians(heading_deg)
    ua = np.array([math.sin(hd), math.cos(hd), 0.0])                     # 진행 방향(ENU)
    uc = np.array([math.cos(hd), -math.sin(hd), 0.0])                    # 오른쪽
    # 1) 찾기 — 계획 선(원점 = 선 시작) 기준 along · cross
    if center is None:
        al = pos64 @ ua
        side = getattr(radar, "side_sign", 1.0) if radar is not None else 1.0
        h = float(np.median(pos64[:, 2]))
        rmax = float(range_axis[-1])
        far = math.sqrt(max(rmax ** 2 - h ** 2, 1.0))
        along = np.arange(al.min() - 5, al.max() + 5, search_step_m)
        cross = side * np.arange(1.0, far, search_step_m)
        g, _ = line_grid((0.0, 0.0), heading_deg, along, cross)
        step = max(1, pos64.shape[0] // 1500)                              # 찾기는 펄스를 솎아도 된다
        coarse = np.abs(backproject_gpu(rc[::step], range_axis, pos64[::step], wavelength_m, g))
        iy, ix = np.unravel_index(int(np.argmax(coarse)), coarse.shape)
        center = (float(along[ix]), float(cross[iy]))
    ca, cc = center
    wa = np.arange(ca - half_window_m, ca + half_window_m, res_m)
    wc = np.arange(cc - half_window_m, cc + half_window_m, res_m)
    gw, _ = line_grid((0.0, 0.0), heading_deg, wa, wc)
    origin = gw.reshape(-1, 3).mean(axis=0)
    n = pos64.shape[0]
    g_t = torch.tensor((gw.reshape(-1, 3) - origin).astype(np.float32), device=dev)
    p_t = torch.tensor((pos64 - origin).astype(np.float32), device=dev)
    rc_t = torch.tensor(np.ascontiguousarray(rc, dtype=np.complex64), device=dev)
    ua_t = torch.tensor(ua.astype(np.float32), device=dev)
    uc_t = torch.tensor(uc.astype(np.float32), device=dev)
    tau = torch.linspace(0, 1, n, device=dev)
    kn = torch.linspace(0, 1, knots, device=dev)
    W = torch.clamp(1 - torch.abs(tau[:, None] - kn[None, :]) * (knots - 1), min=0)    # (n, K) 선형 보간 기저
    par = torch.zeros(2, knots, device=dev, requires_grad=True)                          # 진행 · 옆 [m]
    opt = torch.optim.Adam([par], lr=lr)
    k = 4.0 * math.pi / wavelength_m
    r0, dr = float(range_axis[0]), float(range_axis[1] - range_axis[0])
    chunk = max(1, int(1.0e7 // g_t.shape[0]))
    best = None
    first = None
    from torch.utils.checkpoint import checkpoint

    def part(lo: int, p_chunk):  # noqa: ANN001, ANN202
        return _bp_torch(torch, rc_t[lo:lo + chunk], r0, dr, p_chunk, g_t, k, chunk)

    for _ in range(iters):
        du, dv = W @ par[0], W @ par[1]
        p = p_t + du[:, None] * ua_t[None, :] + dv[:, None] * uc_t[None, :]
        # 덩어리마다 다시 계산(checkpoint) — 모든 펄스의 중간값을 들고 있지 않아 GPU 메모리가 덩어리 하나만큼만 든다
        # (서버 GPU 를 다른 사람과 나눠 쓴다 — 남은 메모리 7 GB 에서도 돈다)
        img = sum(checkpoint(part, lo, p[lo:lo + chunk], use_reentrant=False) for lo in range(0, n, chunk))
        e = _entropy(torch, img)
        ev = float(e.item())
        first = ev if first is None else first
        if best is None or ev < best[0]:
            best = (ev, par.detach().clone())
        opt.zero_grad()
        e.backward()
        opt.step()
    par_b = best[1]
    du = (W @ par_b[0]).cpu().numpy().astype(np.float64)
    dv = (W @ par_b[1]).cpu().numpy().astype(np.float64)
    new = pos64 + du[:, None] * ua[None, :] + dv[:, None] * uc[None, :]
    return {"positions": new, "method": "entropy_knots", "entropy_before": round(first, 5), "entropy_after": round(best[0], 5),
            "max_shift_m": round(float(np.max(np.hypot(du, dv))), 4), "window_center_along_m": round(ca, 2),
            "window_center_cross_m": round(cc, 2), "knots": knots, "iters": iters, "device": dev}


__all__ = ["backproject_gpu", "entropy_focus"]
