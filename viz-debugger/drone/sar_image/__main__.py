"""SAR 영상 도구 — 코너리플렉터 확인 · 예상 거리 이력 · 영상 형성(시뮬레이션 · 실제).

  # 리플렉터가 보일까? (계획 선 또는 비행한 패스로)
  python -m sar_image coverage --traj pass02.csv --radar radar.json --cr 37.56672,126.97812 --cr 37.56690,126.97830

  # 레이더 거리-시간 영상에 겹쳐 볼 예상 쌍곡선 CSV
  python -m sar_image predict --traj pass02.csv --radar radar.json --cr 37.56672,126.97812 --out cr1_range.csv

  # 레이더 없이 시험: 이 궤적으로 리플렉터 신호를 합성해 영상을 만든다 (+ RTK 수준 오차 · 자동 초점)
  python -m sar_image simulate --traj pass02.csv --radar radar.json --cr 37.56672,126.97812 --pos-error-mm 20 --autofocus --png out.png

  # 실제 영상: 레이더 원시 → 어댑터(거리 압축) → 백프로젝션
  python -m sar_image form --traj pass02.csv --radar radar.json --raw radar/pass02 --adapter mymod:load --png img.png [--autofocus-cr lat,lon]
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from pathlib import Path

import numpy as np

from .autofocus import apply_correction, estimate_phase_error
from .backprojection import backproject, line_grid, peak_metrics
from .coverage import line_coverage, predicted_history, summarize_history
from .radar import RadarConfig
from .simulate import synthesize
from .trajectory import Origin, Trajectory


def latlonh(text: str) -> tuple[float, float, float | None]:
    parts = [float(x) for x in text.split(",")]
    return parts[0], parts[1], parts[2] if len(parts) > 2 else None


def load_pass(traj_path: Path) -> tuple[Trajectory, dict]:
    traj = Trajectory.load_csv(traj_path)
    meta_path = traj_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return traj, meta


def frame_for(traj: Trajectory, meta: dict) -> tuple[Origin, tuple[float, float], float, float, float]:
    """원점 = 계획 선 시작점(지면 높이). → (원점, 선 끝 (e,n), 방위, 길이, 비행 높이)."""
    plan = meta.get("plan") or {}
    if plan:
        o = Origin(plan["start_lat"], plan["start_lon"], traj.ground_h)
        end = o.enu(plan["end_lat"], plan["end_lon"], traj.ground_h)[:2]
    else:   # 메타가 없으면 기록 구간의 처음 · 끝으로 선을 잡는다
        idx = np.flatnonzero(traj.capture)
        o = Origin(float(traj.lat[idx[0]]), float(traj.lon[idx[0]]), traj.ground_h)
        end = o.enu(traj.lat[idx[-1]], traj.lon[idx[-1]], traj.ground_h)[:2]
    heading = math.degrees(math.atan2(end[0], end[1])) % 360
    length = float(math.hypot(end[0], end[1]))
    h = float(np.median(traj.h[traj.capture]) - traj.ground_h)
    return o, (float(end[0]), float(end[1])), heading, length, h


def reflectors(args_cr: list[str], o: Origin) -> list[np.ndarray]:
    out = []
    for text in args_cr:
        lat, lon, h = latlonh(text)
        out.append(o.enu(lat, lon, o.h if h is None else h))
    return out


def along_cross(p: np.ndarray, heading: float) -> tuple[float, float]:
    hd = math.radians(heading)
    ue, un = math.sin(hd), math.cos(hd)
    return float(p[0] * ue + p[1] * un), float(p[0] * un - p[1] * ue)


def cmd_coverage(a: argparse.Namespace) -> int:
    radar = RadarConfig.load(a.radar)
    traj, meta = load_pass(a.traj)
    o, end, heading, length, h = frame_for(traj, meta)
    p = (meta.get("pass") or {})
    rs, re_ = p.get("eff_start_along_m") or 0.0, p.get("eff_end_along_m") or length
    report = []
    for i, cr in enumerate(reflectors(a.cr, o), 1):
        cov = line_coverage(radar, (0.0, 0.0), end, h, tuple(cr), f"CR{i}", rs, re_)
        hist = summarize_history(predicted_history(radar, traj, o, cr))
        report.append({"plan": cov.public(), "flown": hist})
        verdict = "✓ 보인다" if cov.ok and hist.get("seen") else ("✕ 안 보인다" if cov.ok is False or not hist.get("seen") else "? 모름")
        print(f"CR{i}: {verdict} · 지상거리 {cov.ground_range_m} m · 경사 {cov.slant_range_m} m · 진행 {cov.along_m} m · "
              f"개구 {cov.aperture_m} m ({(cov.aperture_fraction or 0)*100:.0f}%) · 빔 안 {hist.get('in_beam_seconds')} s")
        for w in cov.why:
            print(f"   - {w}")
    if a.json:
        Path(a.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def cmd_predict(a: argparse.Namespace) -> int:
    radar = RadarConfig.load(a.radar)
    traj, meta = load_pass(a.traj)
    o, *_ = frame_for(traj, meta)
    cr = reflectors(a.cr, o)[0]
    h = predicted_history(radar, traj, o, cr, only_capture=not a.all)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(f"t_{traj.time_ref},range_m,in_beam,az_off_deg,look_down_deg\n")
        for row in zip(h["t"], h["range_m"], h["in_beam"], h["az_off_deg"], h["look_down_deg"]):
            f.write(f"{row[0]:.4f},{row[1]:.4f},{int(row[2])},{row[3]:.3f},{row[4]:.3f}\n")
    print(json.dumps(summarize_history(h), ensure_ascii=False))
    return 0


def _image(radar: RadarConfig, rc: np.ndarray, rng_axis: np.ndarray, pos: np.ndarray, heading: float,
           center: tuple[float, float], half_along: float, half_cross: float, step_along: float, step_cross: float):
    along = np.arange(center[0] - half_along, center[0] + half_along, step_along)
    cross = np.arange(center[1] - half_cross, center[1] + half_cross, step_cross)
    grid, _ = line_grid((0.0, 0.0), heading, along, cross, 0.0)
    return backproject(rc, rng_axis, pos, radar.wavelength_m, grid), along, cross  # type: ignore[arg-type]


def _save_png(path: str, img: np.ndarray, along: np.ndarray, cross: np.ndarray, title: str, marks: list[tuple[float, float]]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    db = 20 * np.log10(np.abs(img) / max(np.abs(img).max(), 1e-30) + 1e-12)
    fig, ax = plt.subplots(figsize=(7, 5), dpi=130)
    im = ax.imshow(db, extent=[along[0], along[-1], cross[-1], cross[0]], vmin=-40, vmax=0, cmap="gray", aspect="auto")
    for a_, c_ in marks:
        ax.plot(a_, c_, "o", mfc="none", mec="#ff3b3b", ms=14, mew=1.5)
    ax.set_xlabel("along-track (m)")
    ax.set_ylabel("cross-track, + = right (m)")
    ax.set_title(title, fontsize=9)
    fig.colorbar(im, ax=ax, label="dB")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def cmd_simulate(a: argparse.Namespace) -> int:
    radar = RadarConfig.load(a.radar)
    traj, meta = load_pass(a.traj)
    o, end, heading, length, h = frame_for(traj, meta)
    crs = reflectors(a.cr, o)
    rng_axis = np.arange(radar.range_min_m or 1.0, radar.range_max_m or 100.0, 0.05)
    t, pos, rc = synthesize(radar, traj, o, crs, rng_axis, noise=a.noise)
    pos_used = pos
    if a.pos_error_mm > 0:
        rng = np.random.default_rng(a.seed)
        dt, tau, sig = 1 / radar.prf_hz, 2.0, a.pos_error_mm / 1000  # type: ignore[operator]
        aa = math.exp(-dt / tau)
        err = np.zeros_like(pos)
        w = rng.standard_normal(pos.shape) * sig * math.sqrt(1 - aa * aa)
        for i in range(1, len(t)):
            err[i] = aa * err[i - 1] + w[i]
        pos_used = pos + err
    if a.autofocus:
        fe = estimate_phase_error(rc, rng_axis, pos_used, radar.wavelength_m, crs[0])  # type: ignore[arg-type]
        rc = apply_correction(rc, fe["phase_err"])
    ac = along_cross(crs[0], heading)
    img, along, cross = _image(radar, rc, rng_axis, pos_used, heading, ac, a.half_along, a.half_cross, a.step_along, a.step_cross)
    m = peak_metrics(img, along, cross)
    print(json.dumps({"pulses": int(t.size), "reflector_along_cross": [round(ac[0], 3), round(ac[1], 3)],
                      "pos_error_mm": a.pos_error_mm, "autofocus": a.autofocus, **m}, ensure_ascii=False))
    if a.png:
        _save_png(a.png, img, along, cross, f"simulated · {Path(a.traj).name} · σ={a.pos_error_mm} mm · autofocus={a.autofocus}", [ac])
    return 0


def cmd_form(a: argparse.Namespace) -> int:
    """실제 영상. 어댑터는 `load(raw_path, radar) -> (pulse_times[N] (궤적과 같은 시각 기준), range_axis[M], rc[N,M] 복소)`."""
    radar = RadarConfig.load(a.radar)
    traj, meta = load_pass(a.traj)
    o, end, heading, length, h = frame_for(traj, meta)
    mod, _, fn = a.adapter.partition(":")
    load = getattr(importlib.import_module(mod), fn or "load")
    t, rng_axis, rc = load(a.raw, radar)
    st = traj.at(o, np.asarray(t))
    pos = np.stack([st["e"], st["n"], st["u"]], axis=1)
    if a.autofocus_cr:
        cr = reflectors([a.autofocus_cr], o)[0]
        fe = estimate_phase_error(rc, rng_axis, pos, radar.wavelength_m, cr)  # type: ignore[arg-type]
        rc = apply_correction(rc, fe["phase_err"])
    center = (length / 2, a.center_cross)
    img, along, cross = _image(radar, rc, rng_axis, pos, heading, center, length / 2 + 5, a.half_cross, a.step_along, a.step_cross)
    np.save(Path(a.png).with_suffix(".npy"), img)
    _save_png(a.png, img, along, cross, f"SAR · {Path(a.traj).name}", [])
    print(json.dumps({"pulses": int(np.asarray(t).size), "image": a.png}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sar_image", description="SAR 영상 도구")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("coverage", "predict", "simulate", "form"):
        s = sub.add_parser(name)
        s.add_argument("--traj", type=Path, required=True, help="sar_pass 의 passNN_*.csv (옆의 .json 도 읽는다)")
        s.add_argument("--radar", type=Path, required=True, help="radar.json")
    sub.choices["coverage"].add_argument("--cr", action="append", required=True, help="리플렉터 lat,lon[,해발 m]")
    sub.choices["coverage"].add_argument("--json")
    sub.choices["predict"].add_argument("--cr", action="append", required=True)
    sub.choices["predict"].add_argument("--out", required=True)
    sub.choices["predict"].add_argument("--all", action="store_true", help="기록 구간 밖도 낸다")
    s = sub.choices["simulate"]
    s.add_argument("--cr", action="append", required=True)
    s.add_argument("--noise", type=float, default=0.02)
    s.add_argument("--pos-error-mm", type=float, default=0.0, help="궤적에 더할 저주파 위치 오차 (RTK ≈ 10~20)")
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--autofocus", action="store_true", help="첫 리플렉터로 자동 초점")
    s.add_argument("--png")
    for s in (sub.choices["simulate"], sub.choices["form"]):
        s.add_argument("--half-along", type=float, default=1.2)
        s.add_argument("--half-cross", type=float, default=1.0)
        s.add_argument("--step-along", type=float, default=0.004)
        s.add_argument("--step-cross", type=float, default=0.025)
    f = sub.choices["form"]
    f.add_argument("--raw", required=True)
    f.add_argument("--adapter", required=True, help="module:function — 레이더 원시 → 거리 압축")
    f.add_argument("--autofocus-cr", help="자동 초점 기준 리플렉터 lat,lon[,h]")
    f.add_argument("--center-cross", type=float, default=20.0)
    f.add_argument("--png", required=True)
    a = p.parse_args(argv)
    return {"coverage": cmd_coverage, "predict": cmd_predict, "simulate": cmd_simulate, "form": cmd_form}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
