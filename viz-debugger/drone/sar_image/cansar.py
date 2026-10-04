"""CANSAR-2(레이더 팀) 원시 → 거리 압축 — 우리 파이프라인(RTK 궤적 · 레버암 · 리플렉터 · 변위)에 넣는 어댑터.

레이더 팀 `cansar_flight.py`(2026-10-04 받음)의 「스윕별 프로파일」 · 「시각」 부분을 그대로 옮겼다. 그쪽 코드가 바뀌면 여기 상수부터 맞춘다.

  원시   iq_N.bin   int16 4열 (안테나 I, Q, 기준 I, Q). 0x5A5A 표시 행 다음 행 = 부대역 번호 s(0~7),
                    표시 뒤 W0..W1 행이 그 부대역 처프(50 MHz, 100 µs, 480 kHz 표본).
                    부대역 8개 중심 5.525 + 0.046·s GHz → 이어 붙이면 5.50 ~ 5.87 GHz(≈ 370 MHz → 거리 해상도 ≈ 0.40 m)
         meta_N.txt t_start= · t_end= (SDR 가동 시간 초)
  시각   <로그>/events.csv 의 start 행: pi_epoch − sdr_uptime = 오프셋 → 스윕 k 시각 = t_start + k·(t_end−t_start)/스윕수 + 오프셋
         (Pi 시계 — 우리 비행 기록과 같은 시계다)
  처리   안테나 / 기준(송신 경로가 빠진 전달 함수) → 주파수 순으로 정렬 · 균일 보간 → conj · Hann → FFT → 거리 프로파일.
         그쪽 프로파일 위상은 +4π·FMIN·R/c 다. 우리 규약은 exp(−j4πR/λ) 이므로 켤레를 돌려주고 λ = c/FMIN 을 쓴다
         (`example_radar_cansar.json` 의 wavelength_m).

그쪽 코드와 다른 점(일부러):
  - 빛의 속도: 그쪽은 c = 3e8, 여기는 299 792 458 m/s — 0.07 % 차이가 25 m 에서 위상 수 rad(개구 안에서 0.3 rad 남짓 흐려짐).
  - 거리 축을 4 배 촘촘히(0 채우기) — 백프로젝션 보간 오차를 줄인다. 해상도는 그대로.
  - 부대역 순서가 0~7 로 돌지 않는 곳(표시 행이 빠짐)을 세어 `notes` 에 남긴다. 그쪽은 그대로 짝지어 뒤 스윕이 다 밀린다.

로그 폴더는 원시 옆에서 찾는다: 환경변수 CANSAR_LOGS_ROOT → 원시 폴더/../cansar_logs → 원시 폴더/cansar_logs → /home/physical/cansar_logs.
그 안의 passes.csv 에 N 이 있는 폴더를 고른다(그쪽 cansar_quick.py 와 같은 규칙).
"""

from __future__ import annotations

import csv
import math
import os
import re
from pathlib import Path

import numpy as np

from .radar import C, RadarConfig

# ── 레이더 팀 cansar_flight.py 의 상수 (2026-10-04) ─────────────────────────
FS = 480e3
BW = 50e6
TP = 100e-6
K = BW / TP
SUBF = {i: 5.525e9 + 0.046e9 * i for i in range(8)}
W0, W1 = 8, 53
L = W1 - W0
NF = 4096
MARK = 0x5A5A
ROFF_M = 0.4               # 그쪽 기본 --roff (내부 지연 보정)
PAD = 4                    # 거리 축 0 채우기 배수

_t = np.arange(L) / FS
_FQ = np.concatenate([SUBF[s] - BW / 2 + K * _t for s in range(8)])
_ORDER = np.argsort(_FQ)
_F = _FQ[_ORDER]
FU = np.linspace(_F.min(), _F.max(), NF)
FMIN = float(FU[0])
DFU = float(FU[1] - FU[0])
WAVELENGTH_M = C / FMIN
# 균일 주파수로의 선형 보간 — 모든 스윕에 같은 자리 · 무게
_I0 = np.clip(np.searchsorted(_F, FU, side="right") - 1, 0, _F.size - 2)
_W = ((FU - _F[_I0]) / np.maximum(_F[_I0 + 1] - _F[_I0], 1e-9)).clip(0, 1)

_NAME = re.compile(r"iq_(\d+)\.bin$")


def capture_no(path: str | Path) -> int | None:
    m = _NAME.search(str(path))
    return int(m.group(1)) if m else None


def read_meta(path: str | Path) -> dict[str, str]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.strip().split("=", 1)
            out[k.strip()] = v.strip()
    return out


def sweeps(iq_path: str | Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """→ 안테나 (8, n, L) · 기준 (8, n, L) complex64 · 정보. n = 부대역마다 모인 스윕 수의 최솟값."""
    d = np.fromfile(iq_path, dtype=np.int16).reshape(-1, 4)
    mk = np.flatnonzero(d[:, 0] == MARK)
    if mk.size:
        mk = mk[np.concatenate([[True], np.diff(mk) > 10])]
    mk = mk[:-1]                                         # 그쪽과 같이 마지막 표시는 쓰지 않는다
    mk = mk[mk + W1 <= d.shape[0]]
    s = d[np.minimum(mk + 1, d.shape[0] - 1), 0].astype(np.int64)
    good = (s >= 0) & (s <= 7)
    mk, s = mk[good], s[good]
    # 0,1,…,7 로 돌지 않는 곳 — 표시 행이 빠졌거나 부대역이 건너뛰었다
    breaks = int(np.count_nonzero(np.diff(s) % 8 != 1)) if s.size > 1 else 0
    rows = mk[:, None] + np.arange(W0, W1)[None, :]
    g = d[rows].astype(np.float32)                       # (블록, L, 4)
    ant_all = (g[..., 0] + 1j * g[..., 1]).astype(np.complex64)
    ref_all = (g[..., 2] + 1j * g[..., 3]).astype(np.complex64)
    counts = [int(np.count_nonzero(s == b)) for b in range(8)]
    n = min(counts) if counts else 0
    if n == 0:
        raise ValueError(f"{iq_path}: 부대역 표시(0x5A5A)를 못 찾았다 — 원시 형식이 바뀌었나")
    A = np.stack([ant_all[s == b][:n] for b in range(8)])
    R = np.stack([ref_all[s == b][:n] for b in range(8)])
    return A, R, {"blocks": int(mk.size), "per_subband": counts, "sweeps": n, "order_breaks": breaks}


def profiles(A: np.ndarray, R: np.ndarray, rmax: float = 80.0, roff: float = ROFF_M, demean: bool = True,
             pad: int = PAD) -> tuple[np.ndarray, np.ndarray]:
    """(8, n, L) → 거리 축 (M,) · 프로파일 (n, M) — 그쪽 규약(위상 +4π·FMIN·R/c, 그쪽 c 대신 실제 c)."""
    n = A.shape[1]
    Z = (A / np.where(np.abs(R) > 0, R, 1)).transpose(1, 0, 2).reshape(n, -1)[:, _ORDER]
    zu = Z[:, _I0] * (1 - _W) + Z[:, _I0 + 1] * _W
    nf = NF * pad
    P = np.fft.fft(np.conj(zu) * np.hanning(NF)[None, :], nf, axis=1)
    rax = np.fft.fftfreq(nf, DFU) * C / 2
    m = (rax >= 0) & (rax < rmax + 5)
    r = rax[m] - roff
    prof = P[:, m].astype(np.complex64)
    if demean:
        prof = prof - prof.mean(0, keepdims=True)        # 정지 성분(직접 누설 · 기체) 빼기 — 그쪽 --demean
    return r, prof


def find_logs(iq_path: str | Path, n: int | None = None) -> Path | None:
    p = Path(iq_path).resolve()
    n = capture_no(p) if n is None else n
    roots = [os.environ.get("CANSAR_LOGS_ROOT"), p.parent.parent / "cansar_logs", p.parent / "cansar_logs",
             Path("/home/physical/cansar_logs")]
    for root in roots:
        if not root or not Path(root).is_dir():
            continue
        for pc in sorted(Path(root).glob("*/passes.csv"), key=lambda q: q.stat().st_mtime, reverse=True):
            try:
                with pc.open(encoding="utf-8") as f:
                    if any(r.get("n") == str(n) for r in csv.DictReader(f)):
                        return pc.parent
            except OSError:
                continue
    return None


def pass_row(logdir: Path, n: int) -> dict | None:
    try:
        with (logdir / "passes.csv").open(encoding="utf-8") as f:
            return next((r for r in csv.DictReader(f) if r.get("n") == str(n)), None)
    except OSError:
        return None


def time_offset(logdir: Path, t_start: float, t0_pi: float | None) -> tuple[float, dict]:
    """events.csv 의 start 행 → pi_epoch − sdr_uptime. passes.csv 의 t0 가 있으면 그것과 가장 가까운 행(그쪽 규칙)."""
    with (logdir / "events.csv").open(encoding="utf-8") as f:
        starts = [r for r in csv.DictReader(f) if r.get("event") == "start"]
    if not starts:
        raise ValueError(f"{logdir}/events.csv 에 start 행이 없다")
    if t0_pi is not None:
        e = min(starts, key=lambda r: abs(float(r["pi_epoch"]) - t0_pi))
        how = "passes.csv t0"
    else:
        before = [r for r in starts if float(r["sdr_uptime"]) <= t_start + 1.0]
        e = max(before, key=lambda r: float(r["sdr_uptime"])) if before else starts[0]
        how = "t_start 직전 start"
    off = float(e["pi_epoch"]) - float(e["sdr_uptime"])
    return off, {"offset_s": off, "event_pi_epoch": float(e["pi_epoch"]), "event_sdr_uptime": float(e["sdr_uptime"]), "matched_by": how}


def load(iq_path: str | Path, rmax: float = 80.0, roff: float = ROFF_M, demean: bool = True) -> dict:
    """원시 한 파일 → {t (Pi epoch), range, rc (우리 규약), info}."""
    iq_path = Path(iq_path)
    n_cap = capture_no(iq_path)
    meta = read_meta(iq_path.with_name(f"meta_{n_cap}.txt"))
    t0s, t1s = float(meta["t_start"]), float(meta["t_end"])
    A, R, info = sweeps(iq_path)
    r, prof = profiles(A, R, rmax=rmax, roff=roff, demean=demean)
    logdir = find_logs(iq_path, n_cap)
    if logdir is None:
        raise ValueError(f"passes.csv 에 #{n_cap} 이 있는 로그 폴더(cansar_logs)를 못 찾았다 — CANSAR_LOGS_ROOT 로 알려 준다")
    row = pass_row(logdir, n_cap) or {}
    off, tinfo = time_offset(logdir, t0s, float(row["t0"]) if row.get("t0") else None)
    n = prof.shape[0]
    prf_eff = n / (t1s - t0s)
    t = t0s + np.arange(n) / prf_eff + off
    info.update(tinfo, capture=n_cap, logdir=str(logdir), prf_eff_hz=round(prf_eff, 2), verdict=row.get("verdict"),
                fmin_hz=FMIN, range_bin_m=float(r[1] - r[0]))
    return {"t": t, "range": r, "rc": np.conj(prof), "info": info}


def cansar_iq(raw_path: str, radar: RadarConfig):  # noqa: ANN201
    """어댑터 규약 `load(raw, radar) -> (t, range_axis, rc)`. 거리 범위는 radar.json 의 range_max_m(없으면 80 m)."""
    out = load(raw_path, rmax=float(radar.range_max_m or 80.0))
    keep = out["range"] >= float(radar.range_min_m or 0.0)
    return out["t"], out["range"][keep], out["rc"][:, keep]


cansar_iq.accepts = lambda path: _NAME.search(str(path)) is not None  # type: ignore[attr-defined]


# ── 가짜 CANSAR-2 비행 (형식 · 시각 맞추기 시험용) ─────────────────────────
def write_fake(work: str | Path, n_cap: int, radar: RadarConfig, traj, origin, targets: list[np.ndarray],  # noqa: ANN001
               meta_in: dict | None = None, rows_per_block: int = 64, idle_rows: int = 1536, sdr_t0: float = 1000.0,
               noise: float = 3.0, amp: float = 400.0, seed: int = 0, t_window: tuple[float, float] | None = None,
               internal_delay_m: float = ROFF_M) -> dict:
    """work/flight/iq_N.bin · meta_N.txt + work/cansar_logs/<이름>/{mav,events,passes}.csv — 그쪽 형식 그대로.

    스윕 = 부대역 0~7 블록(rows_per_block 행) + 쉬는 행. 한 스윕은 한 시각(그쪽 가정). mav.csv 는 궤적을 LOCAL_POSITION_NED 로.
    internal_delay_m: 케이블 · 회로 지연(거리로) — 그쪽 --roff 가 빼는 값. 실제 장비처럼 넣어 둔다.
    """
    from .attitude import lever_arm, phase_center
    from .simulate import beam_weight

    work = Path(work)
    fdir, ldir = work / "flight", work / "cansar_logs" / f"fake_{n_cap}"
    fdir.mkdir(parents=True, exist_ok=True)
    ldir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    t_cap0, t_cap1 = t_window or traj.capture_window()
    sweep_rows = 8 * rows_per_block + idle_rows
    prf = FS / sweep_rows
    n = int((t_cap1 - t_cap0) * prf)
    t_pi = t_cap0 + np.arange(n) / prf
    st = traj.at(origin, t_pi)
    lever, _ = lever_arm(radar, meta_in)
    pos = phase_center(np.stack([st["e"], st["n"], st["u"]], axis=1), st["yaw"], st["pitch"], st["roll"], lever)
    data = np.zeros((n * sweep_rows + rows_per_block, 4), dtype=np.int16)
    ref_ph = rng.uniform(0, 2 * np.pi, size=(8, L))
    ref = (amp * 2.5 * np.exp(1j * ref_ph)).astype(np.complex64)            # 기준 채널(송신 경로) — 부대역마다 다른 전달 함수
    for s in range(8):
        f = SUBF[s] - BW / 2 + K * _t                                       # (L,)
        H = np.zeros((n, L), dtype=np.complex128)
        for tg in targets:
            Rr = np.linalg.norm(pos - tg[None, :], axis=1) + internal_delay_m
            w = beam_weight(radar, pos, st["yaw"], st["roll"], tg, st["pitch"])
            H += w[:, None] * np.exp(-4j * np.pi * f[None, :] * Rr[:, None] / C)
        H += 0.3                                                            # 직접 누설(정지 성분) — demean 이 지운다
        ant = H * ref[s][None, :] + noise * (rng.standard_normal((n, L)) + 1j * rng.standard_normal((n, L)))
        base = np.arange(n) * sweep_rows + s * rows_per_block
        data[base, 0] = MARK
        data[base + 1, 0] = s
        rows = base[:, None] + np.arange(W0, W1)[None, :]
        data[rows, 0] = np.clip(np.round(ant.real), -20000, 20000)
        data[rows, 1] = np.clip(np.round(ant.imag), -20000, 20000)
        data[rows, 2] = np.round(ref[s].real)[None, :]
        data[rows, 3] = np.round(ref[s].imag)[None, :]
    data[n * sweep_rows, 0] = MARK                                         # 끝 표시(그쪽은 마지막 표시를 안 쓴다)
    iq = fdir / f"iq_{n_cap}.bin"
    data.tofile(iq)
    sdr_start = sdr_t0 + 0.37                                                # SDR 가동 시간 기준 캡처 시작
    off = t_cap0 - sdr_start
    (fdir / f"meta_{n_cap}.txt").write_text(f"t_start={sdr_start:.6f}\nt_end={sdr_start + n / prf:.6f}\nfs={FS:.0f}\n", encoding="utf-8")
    with (ldir / "events.csv").open("w", newline="", encoding="utf-8") as f:
        w_ = csv.writer(f)
        w_.writerow(["event", "pi_epoch", "sdr_uptime"])
        w_.writerow(["start", f"{sdr_t0 + off:.6f}", f"{sdr_t0:.6f}"])
        w_.writerow(["stop", f"{sdr_start + n / prf + off + 0.2:.6f}", f"{sdr_start + n / prf + 0.2:.6f}"])
    allp = traj.enu(origin)
    with (ldir / "mav.csv").open("w", newline="", encoding="utf-8") as f:
        w_ = csv.writer(f)
        w_.writerow(["msg", "pi_epoch", "f1", "f2", "f3", "f4", "f5", "f6"])
        for i, tt in enumerate(traj.t):
            w_.writerow(["LOCAL_POSITION_NED", f"{tt:.4f}", f"{allp[i, 1]:.4f}", f"{allp[i, 0]:.4f}", f"{-allp[i, 2]:.4f}", 0, 0, 0])
            w_.writerow(["ATTITUDE", f"{tt:.4f}", f"{math.radians(traj.roll[i]):.5f}", f"{math.radians(traj.pitch[i]):.5f}",
                         f"{math.radians(((traj.yaw[i] + 180) % 360) - 180):.5f}", 0, 0, 0])
    with (ldir / "passes.csv").open("w", newline="", encoding="utf-8") as f:
        w_ = csv.writer(f)
        w_.writerow(["n", "t0", "dur_s", "MBps", "pos_hz", "v_mean", "v_std", "alt_mean", "track_deg", "straight", "yaw_std_deg", "verdict"])
        w_.writerow([n_cap, f"{t_cap0:.3f}", f"{n / prf:.2f}", f"{iq.stat().st_size / 1e6 / (n / prf):.2f}", 10, 4.0, 0.05, 20.0, 45, 0.99, 0.5, "OK"])
    return {"iq": str(iq), "logdir": str(ldir), "sweeps": n, "prf_hz": prf, "bytes": iq.stat().st_size, "offset_s": off}


__all__ = ["FMIN", "WAVELENGTH_M", "cansar_iq", "find_logs", "load", "profiles", "sweeps", "write_fake"]
