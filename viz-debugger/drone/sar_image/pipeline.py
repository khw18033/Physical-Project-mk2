"""패스 하나 → 영상 묶음. 데이터 서버의 「영상 만들기」 버튼과 자동 영상이 이것을 부른다.

    <비행>/images/pass02/
        image.json       상태 · 걸린 시간 · 레버암 · 리플렉터별 판정 · 전체 영상의 지도 꼭짓점
        cr1.png …        리플렉터 둘레 (촘촘히) — 안테나가 리플렉터를 봤나 · 초점이 맞나
        full.png         선 전체 (축 · 눈금 있는 그림)
        full_map.png     지도에 겹칠 영상 (축 없음, 어두운 곳은 투명) — 꼭짓점은 image.json 의 full.corners

순서: 리플렉터 둘레를 먼저(수 초) 만들어 image.json 에 쓰고, 전체 영상은 그다음(수십 초). 화면은 image.json 을
다시 읽어 나오는 대로 보여 준다. 영상 계산은 노트북에서 한다 — Pi 는 비행 중 50 Hz 제어를 하므로.
"""

from __future__ import annotations

import importlib
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import numpy as np

from .attitude import lever_arm, phase_center, tilt_motion_mm
from .autofocus import apply_correction, estimate_phase_error, estimate_phase_error_multi, estimate_trajectory_error
from .backprojection import backproject_fast, line_grid, peak_metrics
from .coverage import predicted_history, summarize_history, swath_ground_ranges
from .radar import RadarConfig
from .trajectory import Origin, Trajectory

Adapter = Callable[[str, RadarConfig], tuple[np.ndarray, np.ndarray, np.ndarray]]


def load_adapter(spec: str) -> Adapter:
    mod, _, fn = spec.partition(":")
    return getattr(importlib.import_module(mod), fn or "load")


def frame(traj: Trajectory, meta: dict) -> tuple[Origin, float, float, float]:
    """원점 = 계획 선 시작점(지면). → (원점, 방위, 길이, 비행 높이)."""
    plan = meta.get("plan") or {}
    if plan:
        o = Origin(plan["start_lat"], plan["start_lon"], traj.ground_h)
        end = o.enu(plan["end_lat"], plan["end_lon"], traj.ground_h)
    else:
        idx = np.flatnonzero(traj.capture)
        o = Origin(float(traj.lat[idx[0]]), float(traj.lon[idx[0]]), traj.ground_h)
        end = o.enu(traj.lat[idx[-1]], traj.lon[idx[-1]], traj.ground_h)
    heading = math.degrees(math.atan2(end[0], end[1])) % 360
    return o, heading, float(math.hypot(end[0], end[1])), float(np.median(traj.h[traj.capture]) - traj.ground_h)


def along_cross(p: np.ndarray, heading: float) -> tuple[float, float]:
    hd = math.radians(heading)
    ue, un = math.sin(hd), math.cos(hd)
    return float(p[0] * ue + p[1] * un), float(p[0] * un - p[1] * ue)


def load_raw(files: list[Path], radar: RadarConfig, adapter: Adapter) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """원시 파일 여러 개 → 시각 순으로 이어 붙인다. 거리 축은 모두 같아야 한다."""
    parts = [adapter(str(f), radar) for f in files]
    if not parts:
        raise ValueError("이 패스에 맞는 레이더 원시 파일이 없다")
    rng = parts[0][1]
    for _, r, _ in parts[1:]:
        if r.shape != rng.shape or not np.allclose(r, rng):
            raise ValueError("원시 파일마다 거리 축이 다르다 — 어댑터를 확인한다")
    t = np.concatenate([np.asarray(p[0], dtype=float) for p in parts])
    rc = np.concatenate([p[2] for p in parts])
    order = np.argsort(t, kind="stable")
    return t[order], rng, rc[order]


def _db(img: np.ndarray, ref: float | None = None) -> np.ndarray:
    a = np.abs(img)
    return 20 * np.log10(a / max(ref or a.max(), 1e-30) + 1e-12)


def _png(path: Path, img: np.ndarray, along: np.ndarray, cross: np.ndarray, title: str,
         marks: list[tuple[float, float]], dyn_db: float = 40.0) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=120)
    im = ax.imshow(_db(img), extent=[along[0], along[-1], cross[-1], cross[0]], vmin=-dyn_db, vmax=0, cmap="gray", aspect="auto")
    for a_, c_ in marks:
        if along[0] <= a_ <= along[-1] and min(cross[0], cross[-1]) <= c_ <= max(cross[0], cross[-1]):
            ax.plot(a_, c_, "o", mfc="none", mec="#ff3b3b", ms=14, mew=1.5)
    ax.set_xlim(along[0], along[-1])
    ax.set_ylim(cross[-1], cross[0])
    ax.set_xlabel("along-track (m)")
    ax.set_ylabel("cross-track, + = right (m)")
    ax.set_title(title, fontsize=9)
    fig.colorbar(im, ax=ax, label="dB")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def _map_png(path: Path, img: np.ndarray, dyn_db: float = 30.0) -> None:
    """지도 겹침용 — 행 0 = cross 최소. 어두운 곳은 투명해서 위성 사진이 비친다."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    v = np.clip((_db(img) + dyn_db) / dyn_db, 0, 1)
    rgba = np.zeros(v.shape + (4,), dtype=np.float32)
    rgba[..., 0] = 1.0
    rgba[..., 1] = 0.95
    rgba[..., 2] = 0.55
    rgba[..., 3] = v ** 1.5
    plt.imsave(path, rgba)


def _write(out: Path, body: dict) -> None:
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)


def form_pass(traj_csv: Path, raw_files: list[Path], radar: RadarConfig, adapter: Adapter | str,
              out_dir: Path, reflectors: list[tuple[float, float, float | None]] | None = None,
              full: bool = True, autofocus: bool = True, full_step: tuple[float, float] = (0.05, 0.1),
              workers: int | None = None) -> dict:
    """영상 묶음을 만든다. 실패해도 image.json 에 사유를 남기고 예외는 다시 던진다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "image.json"
    started = time.time()
    body: dict = {"schema": "sar-image-0.1", "state": "running", "started_unix": started, "traj_csv": traj_csv.name,
                  "raw_files": [f.name for f in raw_files], "radar": asdict(radar), "reflectors": [], "full": None,
                  "timings_s": {}, "notes": []}
    _write(status_path, body)
    try:
        if isinstance(adapter, str):
            adapter = load_adapter(adapter)
        meta_path = traj_csv.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        traj = Trajectory.load_csv(traj_csv)
        o, heading, length, h = frame(traj, meta)
        t0 = time.perf_counter()
        t, rng, rc = load_raw(raw_files, radar, adapter)
        body["timings_s"]["load"] = round(time.perf_counter() - t0, 2)
        cw = traj.capture_window()
        inside = (t >= traj.t[0]) & (t <= traj.t[-1])
        if not inside.any():
            raise ValueError(f"레이더 펄스 시각({t[0]:.1f}~{t[-1]:.1f})이 궤적 시각({traj.t[0]:.1f}~{traj.t[-1]:.1f})과 안 겹친다 — "
                             "시각 기준(t_fc)을 어댑터에서 맞춘다")
        if (~inside).any():
            body["notes"].append(f"궤적 밖 펄스 {int((~inside).sum())}개는 뺐다")
            t, rc = t[inside], rc[inside]
        body["pulses"] = int(t.size)
        body["radar_window_s"] = [float(t[0]), float(t[-1])]
        body["capture_window_s"] = [cw[0], cw[1]]
        st = traj.at(o, t)
        lever, notes = lever_arm(radar, meta)
        body["notes"] += notes
        body["lever_frd_m"] = lever.round(4).tolist()
        body["tilt_motion_mm"] = round(tilt_motion_mm(lever, st["roll"], st["pitch"]), 2)
        pos = phase_center(np.stack([st["e"], st["n"], st["u"]], axis=1), st["yaw"], st["pitch"], st["roll"], lever)
        lam = radar.wavelength_m
        if lam is None:
            raise ValueError("radar.json 에 wavelength_m 이 필요하다")

        # ── 1) 리플렉터 둘레 — 촘촘히, 먼저 ─────────────────────────────────
        crs = []
        for lat, lon, hh in reflectors or []:
            crs.append(o.enu(lat, lon, o.h if hh is None else hh))
        t0 = time.perf_counter()
        seen_crs: list[np.ndarray] = []
        seen_contrast: list[float] = []
        for i, cr in enumerate(crs, 1):
            a_c, c_c = along_cross(cr, heading)
            hist = summarize_history(predicted_history(radar, traj, o, cr, meta=meta))
            along = np.arange(a_c - 0.6, a_c + 0.6, 0.004)
            cross = np.arange(c_c - 1.5, c_c + 1.5, 0.05)
            g, _ = line_grid((0.0, 0.0), heading, along, cross)
            img = backproject_fast(rc, rng, pos, lam, g, workers=workers)
            m = peak_metrics(img, along, cross)
            # 리플렉터 자리의 밝기 vs 둘레 바닥(중앙값) — 리플렉터가 실제로 찍혔는지
            a = np.abs(img)
            contrast = 20 * math.log10(max(a.max(), 1e-30) / max(float(np.median(a)), 1e-30))
            off = math.hypot(m["peak_along_m"] - a_c, m["peak_cross_m"] - c_c)
            found = contrast > 15 and off < 0.75
            rec = {"name": f"CR{i}", "lat": reflectors[i - 1][0], "lon": reflectors[i - 1][1],  # type: ignore[index]
                   "along_m": round(a_c, 3), "cross_m": round(c_c, 3), "found": found,
                   "contrast_db": round(contrast, 1), "offset_m": round(off, 3),
                   "in_beam_s": hist.get("in_beam_seconds"), "png": f"cr{i}.png",
                   **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}}
            _png(out_dir / f"cr{i}.png", img, along, cross,
                 f"CR{i} · {'found' if found else 'NOT found'} · contrast {contrast:.0f} dB · res {m['res_along_m']*100:.1f} cm", [(a_c, c_c)])
            if found:
                seen_crs.append(cr)
                seen_contrast.append(contrast)
            body["reflectors"].append(rec)
            _write(status_path, body)
        body["timings_s"]["reflectors"] = round(time.perf_counter() - t0, 2)

        # ── 2) 자동 초점 (찍힌 리플렉터로) — 3차원 → 이어 붙이기 → 하나 순으로 내려간다 ──────────
        rc_used, pos_used, af = rc, pos, None
        if autofocus and seen_crs:
            tried = []
            order = sorted(range(len(seen_crs)), key=lambda i: -seen_contrast[i])
            if len(seen_crs) >= 4:
                try:
                    te = estimate_trajectory_error(rc, rng, pos, lam, seen_crs)
                    pos_used = te["corrected_positions"]
                    af = {"method": "trajectory_3d", "reflectors": len(seen_crs), "solved_pulses": int(te["solved"].sum())}
                except ValueError as exc:
                    tried.append(f"3차원: {exc}")
            if af is None and len(seen_crs) >= 2:
                try:
                    fe = estimate_phase_error_multi(rc, rng, pos, lam, [seen_crs[i] for i in order])
                    rc_used = apply_correction(rc, fe["phase_err"])
                    af = {"method": "stitched", "reflectors": int(fe.get("used", len(seen_crs))),
                          "note": "선을 따라 리플렉터마다 잰 위상을 이었다 — 리플렉터와 비슷한 거리에서 잘 맞는다"}
                except ValueError as exc:
                    tried.append(f"이어 붙이기: {exc}")
            if af is None:
                try:
                    fe = estimate_phase_error(rc, rng, pos, lam, seen_crs[order[0]])
                    rc_used = apply_correction(rc, fe["phase_err"])
                    af = {"method": "single_reflector", "reflectors": 1,
                          "note": "그 리플렉터 둘레 몇 m 만 맞는다 — 장면 전체는 리플렉터 4개 이상을 동시에 빔 안에"}
                except ValueError as exc:
                    tried.append(f"하나: {exc}")
                    af = {"method": "none"}
            if tried:
                af["fallbacks"] = tried
        body["autofocus"] = af

        # ── 3) 선 전체 ──────────────────────────────────────────────────────
        if full:
            t0 = time.perf_counter()
            near, far = swath_ground_ranges(radar, h)
            near = 0.0 if near is None else near
            far = 40.0 if far is None or not math.isfinite(far) else far
            s = radar.side_sign
            c_lo, c_hi = (near, far) if s > 0 else (-far, -near)
            along = np.arange(-5.0, length + 5.0, full_step[0])
            cross = np.arange(c_lo, c_hi, full_step[1])
            g, _ = line_grid((0.0, 0.0), heading, along, cross)
            img = backproject_fast(rc_used, rng, pos_used, lam, g, workers=workers)
            _png(out_dir / "full.png", img, along, cross, f"SAR · {traj_csv.stem} · {t.size} pulses",
                 [(r["along_m"], r["cross_m"]) for r in body["reflectors"]])
            _map_png(out_dir / "full_map.png", img)
            np.save(out_dir / "full_db.npy", _db(img).astype(np.float16))
            corners = []
            for a_, c_ in ((along[0], cross[0]), (along[-1], cross[0]), (along[-1], cross[-1]), (along[0], cross[-1])):
                hd = math.radians(heading)
                e = a_ * math.sin(hd) + c_ * math.cos(hd)
                n = a_ * math.cos(hd) - c_ * math.sin(hd)
                corners.append(o.latlon(e, n))
            body["full"] = {"png": "full.png", "map_png": "full_map.png", "rows": int(cross.size), "cols": int(along.size),
                            "along_m": [float(along[0]), float(along[-1])], "cross_m": [float(cross[0]), float(cross[-1])],
                            "step_m": list(full_step), "heading_deg": round(heading, 3),
                            "corners": [{"lat": la, "lon": lo} for la, lo in corners],
                            "corner_order": "row0col0, row0colEnd, rowEndcolEnd, rowEndcol0 (row = cross ↑, col = along ↑)"}
            body["timings_s"]["full"] = round(time.perf_counter() - t0, 2)
        body["state"] = "done"
    except Exception as exc:
        body["state"] = "failed"
        body["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        body["finished_unix"] = time.time()
        body["timings_s"]["total"] = round(body["finished_unix"] - started, 2)
        _write(status_path, body)
    return body
