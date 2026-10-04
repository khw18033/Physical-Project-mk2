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
from .quicklook import combine_offsets, estimate_time_offset, rangetime_png
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
    if files and all(str(f).endswith(".rc.npz") for f in files):
        from .adapters import rc_npz                       # Pi 가 줄여 보낸 거리 압축 파일 — 형식이 정해져 있다
        adapter = rc_npz
    accepts = getattr(adapter, "accepts", None)
    if accepts is not None:
        files = [f for f in files if accepts(f)]
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
    # 어두운 곳도 옅게 깔아 영상이 덮는 구역이 지도에서 보이게 하고, 밝은 곳(리플렉터 · 구조물)은 흰 노랑으로 또렷하게
    rgba[..., 0] = 0.08 + 0.92 * v
    rgba[..., 1] = 0.10 + 0.85 * v
    rgba[..., 2] = 0.16 + 0.40 * v
    rgba[..., 3] = 0.38 + 0.62 * v ** 0.8
    # 가장자리 테두리 — 영상 구역 경계
    rgba[:2, :, :] = rgba[-2:, :, :] = (1.0, 0.85, 0.2, 0.9)
    rgba[:, :2, :] = rgba[:, -2:, :] = (1.0, 0.85, 0.2, 0.9)
    plt.imsave(path, rgba)


def point_target_quality(img: np.ndarray, along: np.ndarray, cross: np.ndarray, m: dict) -> dict:
    """점 표적 품질 — SCR (위성 SAR 검교정 관례, CoRAL · GECORIS):
    SCR = 봉우리 세기 / 둘레 바닥(주엽 상자 밖, ±6 해상도 안) 평균 세기 — 리플렉터가 바닥보다 얼마나 밝은가.
    ISLR 은 뺐다: 넓은 빔 드론 SAR 의 점 표적은 나비넥타이 모양으로 퍼져 축 정렬 상자로 재면 뜻이 흐려진다
    (예시 X대역 · 깨끗한 합성 신호에서도 +2 dB 가 나왔다). 옆엽은 PSLR 로 본다.
    """
    p = np.abs(img) ** 2
    ia = int(np.argmin(np.abs(along - m["peak_along_m"])))
    ic = int(np.argmin(np.abs(cross - m["peak_cross_m"])))
    da = max(along[1] - along[0], 1e-9)
    dc = max(cross[1] - cross[0], 1e-9) if cross.size > 1 else 1.0
    ra = max(m.get("res_along_m") or da, da)
    rcx = max(m.get("res_cross_m") or dc, dc)
    A, C = np.meshgrid(np.arange(along.size), np.arange(cross.size))
    main = (np.abs(A - ia) * da <= 2 * ra) & (np.abs(C - ic) * dc <= 2 * rcx)
    near = (np.abs(A - ia) * da <= 6 * ra) & (np.abs(C - ic) * dc <= 6 * rcx)
    clutter = p[near & ~main]
    out: dict = {}
    out["scr_db"] = round(10 * math.log10(float(p[ic, ia]) / max(float(clutter.mean()), 1e-30)), 1) if clutter.size else None
    return out


def write_kmz(path: Path, img: np.ndarray, corners: list[tuple[float, float]], name: str, reflectors: list[dict],
              dyn_db: float = 35.0) -> None:
    """구글어스 · QGIS 에서 바로 여는 KMZ — 회색 영상(GroundOverlay, gx:LatLonQuad) + 리플렉터 표식."""
    import io
    import zipfile
    from xml.sax.saxutils import escape

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    v = np.clip((_db(img) + dyn_db) / dyn_db, 0, 1)
    buf = io.BytesIO()
    plt.imsave(buf, v, cmap="gray", vmin=0, vmax=1, format="png")
    # 그림의 왼쪽 위 = row0col0. LatLonQuad 는 왼쪽 아래부터 반시계 — (rowEnd col0, rowEnd colEnd, row0 colEnd, row0 col0)
    quad = [corners[3], corners[2], corners[1], corners[0]]
    coords = " ".join(f"{lo:.9f},{la:.9f},0" for la, lo in quad)
    marks = "".join(
        f"<Placemark><name>{escape(r['name'])}{' ✓' if r.get('found') else ' ✕'}</name>"
        f"<Point><coordinates>{r['lon']:.9f},{r['lat']:.9f},0</coordinates></Point></Placemark>" for r in reflectors)
    kml = (f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">'
           f"<Document><name>{escape(name)}</name><GroundOverlay><name>{escape(name)}</name><Icon><href>image.png</href></Icon>"
           f"<gx:LatLonQuad><coordinates>{coords}</coordinates></gx:LatLonQuad></GroundOverlay>{marks}</Document></kml>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
        z.writestr("image.png", buf.getvalue())


def _write(out: Path, body: dict) -> None:
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)


def form_pass(traj_csv: Path, raw_files: list[Path], radar: RadarConfig, adapter: Adapter | str,
              out_dir: Path, reflectors: list[tuple[float, float, float | None]] | None = None,
              full: bool = True, autofocus: bool = True, full_step: tuple[float, float] = (0.05, 0.1),
              workers: int | None = None, time_offset: float | str | None = "auto",
              former: Callable | str | None = None, focuser: Callable | str | None = None,
              af_exclude: set[int] | list[int] | None = None) -> dict:
    """영상 묶음을 만든다. 실패해도 image.json 에 사유를 남기고 예외는 다시 던진다.

    time_offset: 레이더 시각에 더할 초. "auto" 면 리플렉터 둘 이상이 2 ms 안에서 같은 값을 가리킬 때만 그 값을 쓴다
    (하나뿐이면 알리기만 한다). 숫자면 그 값, None 이면 0.

    former · focuser: 팀의 영상 · 자동 초점 코드를 꽂는 자리("모듈:함수" 또는 함수). README 「영상 코드 꽂기」.
      former(rc, range_axis, positions, wavelength_m, grid, **ctx) -> 복소 영상 (grid.shape[:-1])
      focuser(rc, range_axis, positions, wavelength_m, reflectors, **ctx) -> {"rc"?, "positions"?, "method"?, ...}
      ctx 에는 t(펄스 시각) · radar · traj · origin · heading_deg · workers 가 들어간다. 안 쓰는 것은 **ctx 로 받아 버린다.

    af_exclude: 자동 초점 · 시각 추정에 **쓰지 않을** 리플렉터 번호(1 부터). 변위 시험에서 일부러 움직인 리플렉터는
    여기 넣는다 — 안 넣으면 자동 초점이 그 리플렉터를 제자리로 끌어와 변위가 지워진다(displacement.py).
    """
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
        if isinstance(former, str):
            body["former"] = former
            former = load_adapter(former)
        if isinstance(focuser, str):
            body["focuser"] = focuser
            focuser = load_adapter(focuser)
        form_fn = former or backproject_fast
        meta_path = traj_csv.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        traj = Trajectory.load_csv(traj_csv)
        o, heading, length, h = frame(traj, meta)
        t0 = time.perf_counter()
        t, rng, rc = load_raw(raw_files, radar, adapter)
        body["timings_s"]["load"] = round(time.perf_counter() - t0, 2)
        cw = traj.capture_window()
        lever, notes = lever_arm(radar, meta)
        body["notes"] += notes
        flown = meta.get("radar_config") or {}
        for k in ("antenna_offset_m", "gnss_offset_m", "depression_deg", "side", "wavelength_m"):
            if k in flown and flown[k] != getattr(radar, k, None):
                body["notes"].append(f"radar.json 의 {k} 가 비행 때({flown[k]})와 다르다 — 지금 값({getattr(radar, k, None)})으로 만들었다")
        body["lever_frd_m"] = lever.round(4).tolist()
        body["flight_alt_m"] = round(h, 2)
        lam = radar.wavelength_m
        if lam is None:
            raise ValueError("radar.json 에 wavelength_m 이 필요하다")
        crs = [o.enu(lat, lon, o.h if hh is None else hh) for lat, lon, hh in reflectors or []]
        excl = {int(i) for i in (af_exclude or [])}
        if excl:
            body["af_exclude"] = sorted(excl)

        # ── 0) 빠른 확인: 거리-시간 그림 + 예상 곡선, 레이더 시각 오프셋 ─────────────
        t0 = time.perf_counter()
        curves, per = [], []
        for i, cr in enumerate(crs, 1):
            ph = predicted_history(radar, traj, o, cr, only_capture=False, meta=meta)
            keep = (ph["t"] >= t[0] - 1) & (ph["t"] <= t[-1] + 1)
            curves.append((f"CR{i}", ph["t"][keep], ph["range_m"][keep], ph["in_beam"][keep]))
            in_win = ph["in_beam"] & (ph["t"] >= t[0]) & (ph["t"] <= t[-1])
            if in_win.sum() >= 10 and i not in excl:
                try:
                    est = estimate_time_offset(t, rng, rc, traj, o, lever, cr, lam)
                    per.append({"name": f"CR{i}", **est})
                except Exception as exc:  # noqa: BLE001
                    body["notes"].append(f"CR{i} 시각 추정 실패: {exc}")
        rangetime_png(out_dir / "rangetime.png", t, rng, rc, curves, cw, f"range-time · {traj_csv.stem} (dashed = predicted from trajectory)")
        comb = combine_offsets([p for p in per if p["focus_gain_db"] > -0.5])
        applied = 0.0
        if isinstance(time_offset, (int, float)) and not isinstance(time_offset, bool):
            applied = float(time_offset)
        elif time_offset == "auto" and comb is not None and comb["consistent"] and 0.0005 <= abs(comb["dt_s"]) < 1.0:
            # 0.5 ms 아래는 4 m/s 에서 2 mm — 고쳐도 영상이 안 바뀐다. 굳이 손대지 않는다
            applied = comb["dt_s"]
        body["quicklook"] = {"png": "rangetime.png", "time_offset": {"per_reflector": per, "combined": comb,
                                                                    "applied_s": applied, "mode": str(time_offset)}}
        if applied:
            t = t + applied
            body["notes"].append(f"레이더 시각에 {applied * 1000:+.1f} ms 를 더했다 (리플렉터로 추정)")
            inside = (t >= traj.t[0]) & (t <= traj.t[-1])
            t, rc = t[inside], rc[inside]
        body["timings_s"]["quicklook"] = round(time.perf_counter() - t0, 2)
        _write(status_path, body)
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
        body["tilt_motion_mm"] = round(tilt_motion_mm(lever, st["roll"], st["pitch"]), 2)
        pos = phase_center(np.stack([st["e"], st["n"], st["u"]], axis=1), st["yaw"], st["pitch"], st["roll"], lever)
        ctx = {"t": t, "radar": radar, "traj": traj, "origin": o, "heading_deg": heading, "workers": workers}

        # ── 1) 리플렉터 둘레 — 촘촘히, 먼저 ─────────────────────────────────
        t0 = time.perf_counter()
        seen_crs: list[np.ndarray] = []
        seen_contrast: list[float] = []
        for i, cr in enumerate(crs, 1):
            a_c, c_c = along_cross(cr, heading)
            hist = summarize_history(predicted_history(radar, traj, o, cr, meta=meta))
            along = np.arange(a_c - 0.6, a_c + 0.6, 0.004)
            cross = np.arange(c_c - 1.5, c_c + 1.5, 0.05)
            g, _ = line_grid((0.0, 0.0), heading, along, cross)
            img = form_fn(rc, rng, pos, lam, g, **ctx)
            m = peak_metrics(img, along, cross)
            # 리플렉터 자리의 밝기 vs 둘레 바닥(중앙값) — 리플렉터가 실제로 찍혔는지
            a = np.abs(img)
            contrast = 20 * math.log10(max(a.max(), 1e-30) / max(float(np.median(a)), 1e-30))
            off = math.hypot(m["peak_along_m"] - a_c, m["peak_cross_m"] - c_c)
            found = contrast > 15 and off < 0.75
            q = point_target_quality(img, along, cross, m)
            rec = {"name": f"CR{i}", "lat": reflectors[i - 1][0], "lon": reflectors[i - 1][1],  # type: ignore[index]
                   "along_m": round(a_c, 3), "cross_m": round(c_c, 3), "found": found,
                   "contrast_db": round(contrast, 1), "offset_m": round(off, 3),
                   "in_beam_s": hist.get("in_beam_seconds"), "png": f"cr{i}.png", **q,
                   **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}}
            _png(out_dir / f"cr{i}.png", img, along, cross,
                 f"CR{i} · {'found' if found else 'NOT found'} · contrast {contrast:.0f} dB · res {m['res_along_m']*100:.1f} cm", [(a_c, c_c)])
            rec["af_used"] = found and i not in excl
            if found and i not in excl:
                seen_crs.append(cr)
                seen_contrast.append(contrast)
            body["reflectors"].append(rec)
            _write(status_path, body)
        body["timings_s"]["reflectors"] = round(time.perf_counter() - t0, 2)

        # ── 2) 자동 초점 (찍힌 리플렉터로) — 3차원 → 이어 붙이기 → 하나 순으로 내려간다 ──────────
        rc_used, pos_used, af = rc, pos, None
        if autofocus and focuser is not None:
            # 팀의 자동 초점 — 리플렉터가 없어도(데이터 기반 방식) 부른다
            out = focuser(rc, rng, pos, lam, seen_crs, **ctx) or {}
            rc_used = out.get("rc", rc)
            pos_used = out.get("positions", pos)
            af = {"method": str(out.get("method", "plugin")), "reflectors": len(seen_crs),
                  **{k: v for k, v in out.items() if k not in ("rc", "positions", "method") and isinstance(v, (int, float, str, bool))}}
        elif autofocus and seen_crs:
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

        # ── 2.5) 리플렉터 **측량 자리 그 한 점**의 복소값 — 패스끼리 위상을 견줘 mm 변위를 잰다(displacement.py).
        # 봉우리가 아니라 측량 자리를 쓴다: 백프로젝션 영상의 위상은 점을 1 cm 옮겨도 2 rad 넘게 돈다 — 두 패스가 **같은 점**이어야 한다.
        # **자동 초점 전** 데이터로 잰다: 자동 초점은 패스마다 위상 기준을 따로 잡아 패스끼리 위상이 어긋난다(시험으로 확인).
        # 궤적 오차는 displacement.py 가 움직이지 않은 리플렉터들로 평면을 맞춰 지운다.
        for cr, rec in zip(crs, body["reflectors"]):
            g1 = np.asarray(cr, dtype=np.float64).reshape(1, 1, 3)        # 측량한 3차원 점 그대로
            v = complex(np.asarray(form_fn(rc, rng, pos, lam, g1, **ctx)).reshape(-1)[0])
            rec["phase_rad"] = round(math.atan2(v.imag, v.real), 5)
            rec["amp_db"] = round(20 * math.log10(max(abs(v), 1e-30)), 2)

        # ── 3) 선 전체 ──────────────────────────────────────────────────────
        if full:
            t0 = time.perf_counter()
            # 격자는 **계획 고도**로 정하고 격자 간격에 맞춰 반올림한다 — 같은 선의 패스는 같은 격자가 되어 서로 견줄 수 있다
            h_grid = float((meta.get("plan") or {}).get("alt_m") or round(h))
            near, far = swath_ground_ranges(radar, h_grid)
            near = 0.0 if near is None else near
            far = 40.0 if far is None or not math.isfinite(far) else far
            near = math.floor(near / full_step[1]) * full_step[1]
            far = math.ceil(far / full_step[1]) * full_step[1]
            s = radar.side_sign
            c_lo, c_hi = (near, far) if s > 0 else (-far, -near)
            along = -5.0 + full_step[0] * np.arange(int(round((length + 10.0) / full_step[0])))
            cross = c_lo + full_step[1] * np.arange(int(round((c_hi - c_lo) / full_step[1])))
            g, _ = line_grid((0.0, 0.0), heading, along, cross)
            img = form_fn(rc_used, rng, pos_used, lam, g, **ctx)
            _png(out_dir / "full.png", img, along, cross, f"SAR · {traj_csv.stem} · {t.size} pulses",
                 [(r["along_m"], r["cross_m"]) for r in body["reflectors"]])
            _map_png(out_dir / "full_map.png", img)
            np.save(out_dir / "full.npy", img.astype(np.complex64))      # 패스끼리 비교(compare.py)용 복소 영상
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
                            "corner_order": "row0col0, row0colEnd, rowEndcolEnd, rowEndcol0 (row = cross ↑, col = along ↑)",
                            "kmz": "image.kmz"}
            write_kmz(out_dir / "image.kmz", img, corners, f"SAR {traj_csv.stem}", body["reflectors"])
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
