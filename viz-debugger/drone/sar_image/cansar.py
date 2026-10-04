"""레이더 팀(cansar, CANSAR-2) 원시 → 거리 압축 어댑터. 형식 · 상수는 레이더 팀 `cansar_flight.py`(10/4 받음)에서 옮겼다.

Pi 에 레이더가 남기는 것 (`cansar_quick.py` 기준):

  ~/flight/iq_<N>.bin       int16 × 4 열 [안테나 I, Q, 기준(ref) I, Q] — 표본화 480 kHz
  ~/flight/meta_<N>.txt     key=value 줄. t_start · t_end = 기록 첫 · 끝 표본의 **SDR 부팅 후 초**(sdr_uptime)
  ~/cansar_logs/<시각>/events.csv   event · pi_epoch · sdr_uptime — `start` 행이 두 시계(Pi · SDR)를 잇는다
  ~/cansar_logs/<시각>/passes.csv   n(=N) · t0(Pi 시각) … — 이 캡처가 어느 로그 폴더의 것인지

파형: 부대역 8 개(중심 5.525 + 0.046·s GHz, s = 0…7)를 차례로 50 MHz · 100 µs 처프로 훑는다. 부대역마다 표지 행
(0 열 = 0x5A5A) 다음 행 0 열이 부대역 번호이고, 표지 + 8 ~ +53 행(45 표본)이 그 부대역의 자료다. 표본 i 의 주파수는
f = 중심 − 25 MHz + (50 MHz / 100 µs)·i / 480 kHz. 안테나 ÷ 기준 = 그 주파수에서의 응답 H(f) ∝ exp(−j4πfR/c)
(기준 채널이 같은 LO 를 거쳐 LO 위상 · 처프가 지워진다). 8 부대역을 이으면 약 368 MHz → 거리 해상도 약 0.41 m.

레이더 팀 처리와 다른 점 (같은 자료, 더 맞게):
  - 거리 압축: 팀은 H(f) 를 4096 칸 균일 격자로 **선형 보간**한 뒤 FFT 한다. 표본 간격이 1.04 MHz 라 거리 R 에서
    이웃 표본 위상차가 4π·1.04 MHz·R/c(30 m 에서 1.3 rad, 60 m 에서 2.6 rad)여서 보간이 먼 표적을 깎는다.
    여기서는 실제 주파수 그대로 직접 합한다(비균일 DFT, 보간 없음) — rc(R) = Σ w·H(f)·exp(+j4π(f − fc)R/c).
    중심 fc 기준이라 봉우리 위상이 exp(−j4πR/λ)(λ = radar.json 의 wavelength_m)로 우리 백프로젝션의 약속과 같고,
    봉우리 둘레 위상이 평평해 백프로젝션의 선형 보간이 봉우리를 깎지 않는다.
  - 스윕 묶기: 팀은 부대역마다 따로 쌓아 개수 최솟값으로 자른다 — 가운데 부대역 하나가 빠지면 그 뒤로 스윕끼리 섞인다.
    여기서는 부대역 0…7 이 차례로 다 있는 스윕만 쓴다.
  - 시각: 팀은 스윕이 기록 시간에 고르게 퍼졌다고 본다(t0 + k·(t1 − t0)/N). 여기서는 스윕의 **파일 안 행 위치**로
    시각을 매긴다(t_start + 행 / 전체 행 · (t_end − t_start)) — 망가진 스윕을 버려도 뒤 시각이 밀리지 않는다.
    시각은 스윕 가운데(멈춤-이동 근사). 두 방식은 빠짐이 없으면 같다.

시각 기준: 돌려주는 시각은 **Pi 시각**(time.time())이다(`load.time_ref = "pi"`). 파이프라인이 패스 메타의
offset_pi_minus_fc_s 로 FC GPS 시각으로 바꾼다. Pi 시계는 `install.sh --with-gpstime` 으로 GPS 에 맞춰 둔다.

Pi 에서 쓰기 (패스마다 거리 압축으로 줄여 노트북에 보낸다 — events.csv 가 Pi 에 있으므로 Pi 에서 줄이는 게 맞다):

    python -m sar_data --flights /home/physical/sar_logs --radar /home/physical/flight --radar-glob 'iq_*.bin' \\
        --reduce-adapter sar_image.cansar:load --radar-json /home/physical/radar.json

로그 폴더는 `CANSAR_LOGS`(환경 변수, `:` 로 여럿) → 원시 옆 · 위 폴더의 cansar_logs → /home/physical/cansar_logs 순으로 찾는다.
안테나 케이블 · 내부 지연 `CANSAR_ROFF_M`(기본 0.4 m, 팀 값) 은 거리에서 뺀다.
"""

from __future__ import annotations

import csv
import logging
import math
import os
import re
from pathlib import Path

import numpy as np

from .radar import C, RadarConfig

log = logging.getLogger("sar_image.cansar")

# ── 파형 (cansar_flight.py) ──────────────────────────────────────────────────
FS = 480e3            # 표본화 Hz
BW = 50e6             # 부대역 처프 대역폭
TP = 100e-6           # 처프 길이
SUB0 = 5.525e9        # 부대역 0 중심
SUB_STEP = 46e6       # 부대역 간격
N_SUB = 8
W0, W1 = 8, 53        # 표지 기준 자료 행
MARK = 0x5A5A
ROFF_M = 0.4          # 내부 지연(거리로) — 팀 기본값
DEFAULT_LOGS = Path("/home/physical/cansar_logs")
L = W1 - W0


def frequencies() -> np.ndarray:
    """(8, 45) — 부대역 s 의 표본 i 주파수 Hz."""
    i = np.arange(L)
    return np.stack([SUB0 + SUB_STEP * s - BW / 2 + (BW / TP) * i / FS for s in range(N_SUB)])


def band() -> tuple[float, float, float]:
    """(가장 낮은 · 높은 주파수, 가운데) Hz — radar.json 의 wavelength_m · bandwidth_hz 를 이것으로 채운다."""
    f = frequencies()
    return float(f.min()), float(f.max()), float((f.min() + f.max()) / 2)


def read_meta(path: str | Path) -> dict[str, str]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.strip().split("=", 1)
            out[k.strip()] = v.strip()
    return out


def capture_no(iq_path: str | Path) -> str:
    m = re.fullmatch(r"iq_(\d+)\.bin", Path(iq_path).name)
    if not m:
        raise ValueError(f"cansar 원시 이름이 아니다(iq_<번호>.bin): {iq_path}")
    return m.group(1)


def parse_sweeps(iq_path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """→ 안테나 (n, 8, 45) · 기준 (n, 8, 45) complex64 · 스윕 가운데 행 (n,) · 진단.

    부대역 0…7 이 차례로 다 있고 자료 행이 다 있는 스윕만 쓴다."""
    d = np.fromfile(iq_path, dtype=np.int16)
    d = d[: d.size // 4 * 4].reshape(-1, 4)
    rows = d.shape[0]
    mk = np.flatnonzero(d[:, 0] == MARK)
    if mk.size:
        mk = mk[np.concatenate([[True], np.diff(mk) > 10])]
    mk = mk[mk + W1 <= rows]
    sub = d[np.minimum(mk + 1, rows - 1), 0].astype(int)
    starts = [j for j in range(mk.size - N_SUB + 1) if np.array_equal(sub[j:j + N_SUB], np.arange(N_SUB))]
    # 겹치지 않게 — 한 표지는 한 스윕에만
    used, picked = -1, []
    for j in starts:
        if j > used:
            picked.append(j)
            used = j + N_SUB - 1
    n = len(picked)
    ant = np.zeros((n, N_SUB, L), np.complex64)
    ref = np.zeros((n, N_SUB, L), np.complex64)
    centre = np.zeros(n)
    for k, j in enumerate(picked):
        for s in range(N_SUB):
            g = d[mk[j + s] + W0: mk[j + s] + W1].astype(np.float32)
            ant[k, s] = g[:, 0] + 1j * g[:, 1]
            ref[k, s] = g[:, 2] + 1j * g[:, 3]
        centre[k] = (mk[j] + W0 + mk[j + N_SUB - 1] + W1) / 2
    gaps = np.diff(centre) if n > 1 else np.array([])
    info = {"rows": rows, "markers": int(mk.size), "sweeps": n,
            "dropped_markers": int(mk.size - n * N_SUB),
            "rows_per_sweep": float(np.median(gaps)) if gaps.size else None,
            "irregular_gaps": int((np.abs(gaps - np.median(gaps)) > 0.5 * np.median(gaps)).sum()) if gaps.size else 0}
    return ant, ref, centre, info


def _log_dirs(iq_path: Path) -> list[Path]:
    out = [Path(p) for p in os.environ.get("CANSAR_LOGS", "").split(":") if p]
    for up in (iq_path.parent, iq_path.parent.parent, iq_path.parent.parent.parent):
        out.append(up / "cansar_logs")
        out.append(up)
    out.append(DEFAULT_LOGS)
    seen, dirs = set(), []
    for base in out:
        if not base.is_dir():
            continue
        for ev in [base / "events.csv", *sorted(base.glob("*/events.csv"))]:
            if ev.is_file() and ev.parent not in seen:
                seen.add(ev.parent)
                dirs.append(ev.parent)
    return dirs


def _rows(path: Path) -> list[dict]:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def clock_offset(iq_path: str | Path, t_start_sdr: float, max_gap_s: float = 10.0) -> tuple[float, str]:
    """→ (pi_epoch − sdr_uptime, 어디서 찾았나). 같은 캡처 번호가 passes.csv 에 있는 로그 폴더를 먼저 보고,
    그 안에서(없으면 모든 폴더에서) `start` 행 중 sdr_uptime 이 기록 첫 표본 시각과 가장 가까운 것을 쓴다."""
    iq_path = Path(iq_path)
    no = capture_no(iq_path)
    dirs = _log_dirs(iq_path)
    own = [d for d in dirs if any(r.get("n") == no for r in _rows(d / "passes.csv"))]
    best = None
    for d in own or dirs:
        for r in _rows(d / "events.csv"):
            if r.get("event") != "start":
                continue
            try:
                pe, su = float(r["pi_epoch"]), float(r["sdr_uptime"])
            except (KeyError, TypeError, ValueError):
                continue
            gap = abs(su - t_start_sdr)
            if gap <= max_gap_s and (best is None or gap < best[0]):
                best = (gap, pe - su, f"{d.name}/events.csv (start, sdr_uptime {su:.3f})")
    if best is None:
        where = ", ".join(str(d) for d in dirs) or "없음"
        raise ValueError(f"cansar 시계 짝(events.csv 의 start 행)을 못 찾았다 — 캡처 {no}, t_start {t_start_sdr:.3f}. "
                         f"찾아본 로그 폴더: {where}. CANSAR_LOGS 로 알려 준다")
    if best[0] > 2.0:
        log.warning("캡처 %s: start 행과 기록 첫 표본이 %.1f s 떨어져 있다 — 다른 캡처의 행일 수 있다", no, best[0])
    return best[1], best[2]


def clock_fit(iq_path: str | Path, t_start_sdr: float, t_end_sdr: float, margin_s: float = 3.0) -> dict | None:
    """캡처 중 1 초마다 남긴 `clock` 행(드론 쪽 제안 브리지, radar_team/cansar_pi.py)으로 Pi 시각 = a + b·SDR 시각 을 맞춘다.

    start 행 하나보다 낫다: 행마다 SSH 왕복 · uptime 0.01 s 눈금 오차가 평균으로 줄고, SDR 시계가 흐르는 것(b ≠ 1)도 잡는다.
    행이 셋 안 되면 None(→ start 행 하나로)."""
    iq_path = Path(iq_path)
    no = capture_no(iq_path)
    dirs = _log_dirs(iq_path)
    own = [d for d in dirs if any(r.get("n") == no for r in _rows(d / "passes.csv"))]
    for d in own or dirs:
        pts = []
        for r in _rows(d / "events.csv"):
            if r.get("event") != "clock":
                continue
            try:
                pe, su = float(r["pi_epoch"]), float(r["sdr_uptime"])
            except (KeyError, TypeError, ValueError):
                continue
            if t_start_sdr - margin_s <= su <= t_end_sdr + margin_s:
                pts.append((su, pe))
        if len(pts) >= 3:
            su, pe = np.array(pts).T
            x = su - t_start_sdr                                     # 기울기를 작은 수로 — 정밀도
            b, a0 = np.polyfit(x, pe - su, 1)                        # pi − sdr = a0 + b·x  (b = 시계 흐름)
            res = (pe - su) - (a0 + b * x)
            return {"a0": float(a0), "drift": float(b), "t_ref": float(t_start_sdr), "rows": len(pts),
                    "resid_ms": round(float(np.std(res)) * 1000, 2), "from": f"{d.name}/events.csv (clock {len(pts)}행)"}
    return None


def range_compress(ant: np.ndarray, ref: np.ndarray, fc: float, r_axis: np.ndarray, roff: float = ROFF_M,
                   demean: bool = True) -> np.ndarray:
    """(n, 8, 45) → (n, M). 실제 주파수로 직접 합한다(보간 없음). 봉우리 위상 exp(−j4πR/λ), λ = c/fc."""
    f = frequencies().reshape(-1)
    order = np.argsort(f)
    f = f[order]
    with np.errstate(divide="ignore", invalid="ignore"):
        H = (ant / ref).reshape(ant.shape[0], -1)[:, order]
    H = np.where(np.isfinite(H) & (np.abs(ref.reshape(ref.shape[0], -1)[:, order]) > 0), H, 0).astype(np.complex64)
    if demean:
        H = H - H.mean(axis=0, keepdims=True)           # 정지 성분(송수신 새는 것) 제거 — 팀 --demean
    w = np.hanning(f.size + 2)[1:-1]
    w = w / w.sum()
    r_app = np.asarray(r_axis, dtype=np.float64) + roff  # 레이더가 재는 거리 = 실제 + 내부 지연
    E = np.exp(1j * 4 * np.pi * (f - fc)[:, None] * r_app[None, :] / C).astype(np.complex64) * w[:, None].astype(np.float32)
    out = np.empty((H.shape[0], r_app.size), np.complex64)
    for i0 in range(0, H.shape[0], 2048):
        out[i0:i0 + 2048] = H[i0:i0 + 2048] @ E
    return out


def load(raw_path: str, radar: RadarConfig, demean: bool = True):  # noqa: ANN201
    """어댑터 규약 `load(raw, radar) -> (t, range_axis, rc)`. t 는 Pi 시각(스윕 가운데)."""
    p = Path(raw_path)
    no = capture_no(p)
    meta_path = p.with_name(f"meta_{no}.txt")
    if not meta_path.exists():
        raise ValueError(f"{meta_path.name} 이 없다 — iq 파일과 같은 폴더에 둔다")
    meta = read_meta(meta_path)
    t0s, t1s = float(meta["t_start"]), float(meta["t_end"])
    ant, ref, centre, info = parse_sweeps(p)
    if info["sweeps"] < 2:
        raise ValueError(f"{p.name}: 온전한 스윕이 {info['sweeps']} 개 — 형식(표지 0x5A5A · 부대역 0…7)을 확인한다")
    t_sdr = t0s + centre / info["rows"] * (t1s - t0s)
    fit = clock_fit(p, t0s, t1s)
    if fit is not None:                                         # 1 초마다 시계 짝 → 직선(흐름까지)
        t = t_sdr + fit["a0"] + fit["drift"] * (t_sdr - fit["t_ref"])
        off, src = fit["a0"], fit["from"] + f" · 잔차 {fit['resid_ms']} ms · 흐름 {fit['drift'] * 1e6:+.1f} ppm"
    else:
        off, src = clock_offset(p, t0s)
        t = t_sdr + off
    lo, hi, mid = band()
    fc = C / radar.wavelength_m if radar.wavelength_m else mid
    res = C / (2 * (hi - lo))
    r_min = radar.range_min_m if radar.range_min_m is not None else 2.0
    r_max = radar.range_max_m if radar.range_max_m is not None else 80.0
    rng = np.arange(r_min, r_max, res / 8)
    roff = float(os.environ.get("CANSAR_ROFF_M", ROFF_M))
    rc = range_compress(ant, ref, fc, rng, roff=roff, demean=demean)
    rate = info["rows"] / max(t1s - t0s, 1e-9)
    info.update({"clock_offset_s": off, "clock_from": src, "rows_per_s": rate, "duration_s": t1s - t0s,
                 "sweeps_per_s": info["sweeps"] / max(t1s - t0s, 1e-9)})
    log.info("cansar %s: 스윕 %d (표지 %d, 버림 %d) · %.1f 스윕/s · 행 %.0f/s(표본화 %.0f) · 시계 %s",
             p.name, info["sweeps"], info["markers"], info["dropped_markers"], info["sweeps_per_s"], rate, FS, src)
    if abs(rate - FS) > 0.02 * FS:
        log.warning("cansar %s: 파일 행 수 / 기록 시간 = %.0f/s 가 표본화 %.0f 와 다르다 — 중간에 끊긴 곳이 있으면 시각이 어긋난다",
                    p.name, rate, FS)
    load.last_info = info  # type: ignore[attr-defined]
    return t, rng, rc


def load_keep_static(raw_path: str, radar: RadarConfig):  # noqa: ANN201
    """정지 성분을 빼지 않는다(벽 · 바닥처럼 늘 같은 것을 보고 싶을 때)."""
    return load(raw_path, radar, demean=False)


for _fn in (load, load_keep_static):
    _fn.accepts = lambda path: re.fullmatch(r"iq_\d+\.bin", Path(path).name) is not None  # type: ignore[attr-defined]
    _fn.time_ref = "pi"  # type: ignore[attr-defined]


def write_fake(out_dir: str | Path, no: int, radar: RadarConfig, times_pi: np.ndarray, positions: np.ndarray,
               targets: list[np.ndarray], weights: np.ndarray | None = None, sdr_offset_s: float = 1.7e9,
               rows_gap: int = 6, noise: float = 2.0, seed: int = 0, drop_marker_at: int | None = None,
               roff: float = ROFF_M) -> dict:
    """가짜 cansar 원시(iq_N.bin · meta_N.txt · cansar_logs/<N>/events.csv · passes.csv). 시험 · 대조용.

    times_pi (n,) 스윕 가운데 Pi 시각 · positions (n, 3) 안테나 위상중심 ENU. 스윕 간격은 고르다고 본다.
    sdr_offset_s = pi_epoch − sdr_uptime. drop_marker_at 을 주면 그 스윕의 부대역 3 표지를 지워 망가뜨린다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    f = frequencies()
    per_sub = W1 + rows_gap
    per_sweep = N_SUB * per_sub
    n = times_pi.size
    rows = np.zeros((n * per_sweep, 4), np.int16)
    lo_phase = rng.uniform(0, 2 * np.pi, (N_SUB, L))
    refv = 3000 * np.exp(1j * lo_phase)
    w = np.ones((len(targets), n)) if weights is None else weights
    for k in range(n):
        H = np.zeros((N_SUB, L), np.complex128)
        for j, tg in enumerate(targets):
            R = float(np.linalg.norm(positions[k] - tg)) + roff
            H += w[j, k] * np.exp(-1j * 4 * np.pi * f * R / C)
        a = H * refv * 0.3 + noise * (rng.standard_normal((N_SUB, L)) + 1j * rng.standard_normal((N_SUB, L)))
        base = k * per_sweep
        for s in range(N_SUB):
            r0 = base + s * per_sub
            if not (drop_marker_at == k and s == 3):
                rows[r0, 0] = MARK
            rows[r0 + 1, 0] = s
            g = rows[r0 + W0: r0 + W1]
            g[:, 0], g[:, 1] = np.round(a[s].real), np.round(a[s].imag)
            g[:, 2], g[:, 3] = np.round(refv[s].real), np.round(refv[s].imag)
    dt = float(np.median(np.diff(times_pi)))      # 스윕 하나 = per_sweep 행
    t_rows = per_sweep / dt                        # 행/s (가짜에서는 FS 가 아니어도 된다)
    centre_row = (W0 + (N_SUB - 1) * per_sub + W1) / 2
    t_start_pi = float(times_pi[0]) - centre_row / t_rows
    t_start = t_start_pi - sdr_offset_s
    t_end = t_start + rows.shape[0] / t_rows
    iq = out_dir / f"iq_{no}.bin"
    rows.tofile(iq)
    (out_dir / f"meta_{no}.txt").write_text(f"n={no}\nt_start={t_start:.6f}\nt_end={t_end:.6f}\nfs={FS:.0f}\n", encoding="utf-8")
    logs = out_dir / "cansar_logs" / f"log_{no}"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "events.csv").write_text("event,pi_epoch,sdr_uptime\n"
                                     f"start,{t_start_pi - 0.2:.6f},{t_start - 0.2:.6f}\n"
                                     f"stop,{t_start_pi + rows.shape[0] / t_rows:.6f},{t_end:.6f}\n", encoding="utf-8")
    (logs / "passes.csv").write_text(f"n,t0,dur_s\n{no},{t_start_pi:.3f},{t_end - t_start:.2f}\n", encoding="utf-8")
    return {"iq": str(iq), "sweeps": n, "rows": int(rows.shape[0]), "bytes": iq.stat().st_size}


# ── 10/4 같은 날 다른 세션이 따로 만든 것과 합침 ───────────────────────────────────
# quick-look 실행(sar_data/quick.py) · GPU · 자동 초점 견주기 · 시험이 쓰는 이름과, 비행 하나(원시 + 레이더 팀 로그 폴더
# mav.csv · events.csv · passes.csv)를 통째로 흉내 내는 가짜 — 레이더 팀 cansar_quick.py 가 그대로 돈다.

cansar_iq = load                                    # 예전 이름(설정 파일 · 문서) — 같은 어댑터
WAVELENGTH_M = C / band()[2]


def load_info(raw_path: str | Path, radar: RadarConfig | None = None) -> dict:
    """→ {t (Pi 시각), range, rc, info} — 진단까지 한 번에."""
    from .radar import RadarConfig as _RC

    radar = radar or _RC(wavelength_m=WAVELENGTH_M, range_min_m=2.0, range_max_m=80.0)
    t, rng, rc = load(str(raw_path), radar)
    return {"t": t, "range": rng, "rc": rc, "info": dict(load.last_info)}  # type: ignore[attr-defined]


def write_fake_flight(work: str | Path, n_cap: int, radar: RadarConfig, traj, origin, targets: list[np.ndarray],  # noqa: ANN001
                      meta_in: dict | None = None, rows_per_block: int = 64, idle_rows: int = 1536, sdr_t0: float = 1000.0,
                      noise: float = 3.0, amp: float = 400.0, seed: int = 0, t_window: tuple[float, float] | None = None,
                      internal_delay_m: float = ROFF_M) -> dict:
    """work/flight/iq_N.bin · meta_N.txt + work/cansar_logs/fake_N/{mav,events,passes}.csv — 레이더 팀 형식 그대로.

    traj 는 드론 쪽 비행 기록(시각이 FC GPS 면 meta_in 의 clock.offset_pi_minus_fc_s 로 Pi 시각으로 옮겨 쓴다 —
    레이더 로그는 Pi 시계다). 스윕 = 부대역 0~7 블록(rows_per_block 행) + 쉬는 행, 시각은 스윕 가운데(load 와 같은 약속).
    internal_delay_m: 케이블 · 회로 지연(거리로) — 그쪽 --roff 가 빼는 값.
    """
    from .attitude import lever_arm, phase_center
    from .simulate import beam_weight

    work = Path(work)
    fdir, ldir = work / "flight", work / "cansar_logs" / f"fake_{n_cap}"
    fdir.mkdir(parents=True, exist_ok=True)
    ldir.mkdir(parents=True, exist_ok=True)
    rng_ = np.random.default_rng(seed)
    off_pi = 0.0
    if getattr(traj, "time_ref", "") == "fc_gps":
        off_pi = float(((meta_in or {}).get("clock") or {}).get("offset_pi_minus_fc_s") or 0.0)
    t_cap0, t_cap1 = t_window or traj.capture_window()                       # FC(또는 기록) 시각
    sweep_rows = N_SUB * rows_per_block + idle_rows
    prf = FS / sweep_rows
    n = int((t_cap1 - t_cap0) * prf)
    t_rec = t_cap0 + np.arange(n) / prf                                      # 스윕 가운데, 기록 시각
    st = traj.at(origin, t_rec)
    lever, _ = lever_arm(radar, meta_in)
    pos = phase_center(np.stack([st["e"], st["n"], st["u"]], axis=1), st["yaw"], st["pitch"], st["roll"], lever)
    f_all = frequencies()
    data = np.zeros((n * sweep_rows + rows_per_block, 4), dtype=np.int16)
    ref = (amp * 2.5 * np.exp(1j * rng_.uniform(0, 2 * np.pi, size=(N_SUB, L)))).astype(np.complex64)
    for s in range(N_SUB):
        f = f_all[s]
        H = np.zeros((n, L), dtype=np.complex128)
        for tg in targets:
            Rr = np.linalg.norm(pos - tg[None, :], axis=1) + internal_delay_m
            w = beam_weight(radar, pos, st["yaw"], st["roll"], tg, st["pitch"])
            H += w[:, None] * np.exp(-4j * np.pi * f[None, :] * Rr[:, None] / C)
        H += 0.3                                                             # 직접 누설(정지 성분)
        ant = H * ref[s][None, :] + noise * (rng_.standard_normal((n, L)) + 1j * rng_.standard_normal((n, L)))
        base = np.arange(n) * sweep_rows + s * rows_per_block
        data[base, 0] = MARK
        data[base + 1, 0] = s
        rows = base[:, None] + np.arange(W0, W1)[None, :]
        data[rows, 0] = np.clip(np.round(ant.real), -20000, 20000)
        data[rows, 1] = np.clip(np.round(ant.imag), -20000, 20000)
        data[rows, 2] = np.round(ref[s].real)[None, :]
        data[rows, 3] = np.round(ref[s].imag)[None, :]
    data[n * sweep_rows, 0] = MARK
    iq = fdir / f"iq_{n_cap}.bin"
    data.tofile(iq)
    centre_row = (W0 + (N_SUB - 1) * rows_per_block + W1) / 2
    t_start_pi = t_cap0 + off_pi - centre_row / FS                           # 0 번 행의 Pi 시각
    sdr_start = sdr_t0 + 0.37
    off = t_start_pi - sdr_start                                             # pi_epoch − sdr_uptime
    t_end = sdr_start + data.shape[0] / FS
    (fdir / f"meta_{n_cap}.txt").write_text(f"t_start={sdr_start:.6f}\nt_end={t_end:.6f}\nfs={FS:.0f}\n", encoding="utf-8")
    with (ldir / "events.csv").open("w", newline="", encoding="utf-8") as fh:
        w_ = csv.writer(fh)
        w_.writerow(["event", "pi_epoch", "sdr_uptime"])
        w_.writerow(["start", f"{sdr_t0 + off:.6f}", f"{sdr_t0:.6f}"])
        w_.writerow(["stop", f"{t_end + off + 0.2:.6f}", f"{t_end + 0.2:.6f}"])
    allp = traj.enu(origin)
    with (ldir / "mav.csv").open("w", newline="", encoding="utf-8") as fh:
        w_ = csv.writer(fh)
        w_.writerow(["msg", "pi_epoch", "f1", "f2", "f3", "f4", "f5", "f6"])
        for i, tt in enumerate(traj.t):
            tp = tt + off_pi
            w_.writerow(["LOCAL_POSITION_NED", f"{tp:.4f}", f"{allp[i, 1]:.4f}", f"{allp[i, 0]:.4f}", f"{-allp[i, 2]:.4f}", 0, 0, 0])
            w_.writerow(["ATTITUDE", f"{tp:.4f}", f"{math.radians(traj.roll[i]):.5f}", f"{math.radians(traj.pitch[i]):.5f}",
                         f"{math.radians(((traj.yaw[i] + 180) % 360) - 180):.5f}", 0, 0, 0])
    with (ldir / "passes.csv").open("w", newline="", encoding="utf-8") as fh:
        w_ = csv.writer(fh)
        w_.writerow(["n", "t0", "dur_s", "MBps", "pos_hz", "v_mean", "v_std", "alt_mean", "track_deg", "straight", "yaw_std_deg", "verdict"])
        w_.writerow([n_cap, f"{t_cap0 + off_pi:.3f}", f"{n / prf:.2f}", f"{iq.stat().st_size / 1e6 / (n / prf):.2f}", 10, 4.0, 0.05,
                     20.0, 45, 0.99, 0.5, "OK"])
    return {"iq": str(iq), "logdir": str(ldir), "sweeps": n, "prf_hz": prf, "bytes": iq.stat().st_size, "offset_s": off,
            "offset_pi_minus_fc_s": off_pi}


def capture_window(iq_path: str | Path) -> dict | None:
    """원시 파일을 열지 않고 캡처 구간(Pi 시각)을 — meta_N.txt 의 SDR 시각 + events.csv 시계 짝.
    데이터 서버가 드론 패스와 짝지을 때 쓴다(파일 수정 시각보다 정확하다). passes.csv 에 레이더 팀이 CAP_ON 의
    `pass` · `flight` 를 같이 적어 두면 그것도 돌려준다(그러면 시각 없이 바로 짝짓는다). 못 구하면 None."""
    p = Path(iq_path)
    try:
        no = capture_no(p)
        meta = read_meta(p.with_name(f"meta_{no}.txt"))
        t0s, t1s = float(meta["t_start"]), float(meta["t_end"])
        off, _ = clock_offset(p, t0s)
    except (OSError, KeyError, ValueError):
        return None
    out = {"start": t0s + off, "end": t1s + off, "capture": no}
    for d in _log_dirs(p):
        row = next((r for r in _rows(d / "passes.csv") if r.get("n") == no), None)
        if row:
            if row.get("pass"):
                out["pass"] = row["pass"]
            if row.get("flight"):
                out["flight"] = row["flight"]
            break
    return out
