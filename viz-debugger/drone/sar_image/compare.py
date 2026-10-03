"""같은 선을 두 번 난 패스 비교 — 기준선(두 궤적의 간격) · 일치도(coherence) · 밝기 변화.

두 패스의 영상은 같은 격자(계획 선 기준 along × cross)로 만들어지므로 픽셀끼리 바로 견준다.

  일치도 γ = |Σ a·b*| / sqrt(Σ|a|² Σ|b|²)  (창 안에서) — 1 에 가까우면 위상까지 같다(간섭 · 변화 탐지의 바탕)
  밝기 변화 = 20 log10(|b| / |a|)  (창 평균)

기준선이 크면(수직 방향으로 파장 대비 크게) 일치도가 떨어지는 것이 정상이다 — 그래서 함께 적는다.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np


def _box(x: np.ndarray, w: int) -> np.ndarray:
    """w×w 이동 합 (가장자리는 있는 만큼)."""
    k = np.ones(w)
    y = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, x)
    return np.apply_along_axis(lambda c: np.convolve(c, k, "same"), 0, y)


def coherence(a: np.ndarray, b: np.ndarray, win: int = 5) -> np.ndarray:
    num = _box(a * np.conj(b), win)
    den = np.sqrt(_box(np.abs(a) ** 2, win) * _box(np.abs(b) ** 2, win))
    return np.abs(num) / np.maximum(den, 1e-30)


def baseline(csv_a: Path, csv_b: Path, length_m: float) -> dict:
    """캡처 구간 안에서 두 궤적의 간격 — 횡(cross) · 높이 차이의 평균 · 흔들림."""
    def load(p: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        rows = [r for r in csv.DictReader(p.open(encoding="utf-8")) if r.get("along_m") not in (None, "")]
        al = np.array([float(r["along_m"]) for r in rows])
        cr = np.array([float(r["cross_m"]) for r in rows])
        h = np.array([float(r["alt_rel_m"] or "nan") for r in rows])
        o = np.argsort(al)
        return al[o], cr[o], h[o]

    a_al, a_cr, a_h = load(csv_a)
    b_al, b_cr, b_h = load(csv_b)
    grid = np.linspace(0, length_m, 200)
    dcr = np.interp(grid, b_al, b_cr) - np.interp(grid, a_al, a_cr)
    dh = np.interp(grid, b_al, b_h) - np.interp(grid, a_al, a_h)
    return {"cross_mean_m": round(float(dcr.mean()), 3), "cross_std_m": round(float(dcr.std()), 3),
            "height_mean_m": round(float(np.nanmean(dh)), 3), "height_std_m": round(float(np.nanstd(dh)), 3)}


def compare_passes(dir_a: Path, dir_b: Path, out_dir: Path, flight_dir: Path, win: int = 5) -> dict:
    ja = json.loads((dir_a / "image.json").read_text(encoding="utf-8"))
    jb = json.loads((dir_b / "image.json").read_text(encoding="utf-8"))
    a = np.load(dir_a / "full.npy")
    b = np.load(dir_b / "full.npy")
    if a.shape != b.shape or ja["full"]["along_m"] != jb["full"]["along_m"] or ja["full"]["cross_m"] != jb["full"]["cross_m"]:
        raise ValueError("두 패스의 영상 격자가 다르다 — 같은 선 · 같은 설정으로 만든 영상만 견준다")
    g = coherence(a, b, win)
    amp_a = np.sqrt(_box(np.abs(a) ** 2, win))
    amp_b = np.sqrt(_box(np.abs(b) ** 2, win))
    change = 20 * np.log10(np.maximum(amp_b, 1e-30) / np.maximum(amp_a, 1e-30))
    bright = amp_a > np.percentile(amp_a, 90)          # 밝은 곳(리플렉터 · 구조물)에서의 일치도가 의미 있다
    al, cr = ja["full"]["along_m"], ja["full"]["cross_m"]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), dpi=110)
    ext = [al[0], al[1], cr[1], cr[0]]
    im0 = axes[0].imshow(g, extent=ext, vmin=0, vmax=1, cmap="viridis", aspect="auto")
    axes[0].set_title(f"coherence (window {win}×{win})", fontsize=9)
    fig.colorbar(im0, ax=axes[0])
    im1 = axes[1].imshow(np.where(bright | (amp_b > np.percentile(amp_b, 90)), change, np.nan), extent=ext, vmin=-10, vmax=10,
                         cmap="RdBu_r", aspect="auto")
    axes[1].set_title("brightness change B vs A (dB, bright areas)", fontsize=9)
    fig.colorbar(im1, ax=axes[1])
    for ax in axes:
        ax.set_xlabel("along-track (m)")
        ax.set_ylabel("cross-track (m)")
    fig.tight_layout()
    fig.savefig(out_dir / "compare.png")
    plt.close(fig)
    length = float(al[1]) - 5.0
    body = {"schema": "sar-compare-0.1", "a": ja["traj_csv"], "b": jb["traj_csv"], "png": "compare.png",
            "coherence_bright_median": round(float(np.median(g[bright])), 3),
            "coherence_all_median": round(float(np.median(g)), 3),
            "baseline": baseline(flight_dir / ja["traj_csv"], flight_dir / jb["traj_csv"], max(length, 1.0)),
            "note": "기준선(두 궤적의 간격)이 크면 일치도가 떨어지는 것이 정상이다"}
    (out_dir / "compare.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return body


__all__ = ["baseline", "coherence", "compare_passes"]
