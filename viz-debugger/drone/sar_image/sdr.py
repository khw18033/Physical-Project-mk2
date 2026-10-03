"""SDR(Zynq-7020 + AD9361) 원시 IQ → 거리 압축 — 정합 필터. 레이더 팀이 형식을 정하면 이 파일만 맞춘다.

AD9361 은 받은 신호를 디처프하지 않고 **복소 기저대역 IQ** 로 준다. 송신 처프를 알면 정합 필터(받은 것 ⊛ 보낸 것의 켤레)로
거리 압축이 된다. 표적 지연 τ 의 출력 위상은 exp(−j2π f_c τ) = exp(−j4πR/λ) — 백프로젝션이 기대하는 것과 같다.

제안 형식 — 원시 파일 하나 + 옆에 같은 이름의 `.json`:

  <name>.npy   complex64 또는 int16 (…, 2)  IQ
  <name>.json  {
      "layout":   "gated" | "stream",
      "fs_hz":    표본화 주파수,            "fc_hz": 중심 주파수,
      "t0_unix":  0 번 표본(gated 면 pulse_idx 0 의 처프 시작)의 시각 — UNIX 초, UTC,
      "t0_source":"pps" | "pi"   (PPS 로 맞춘 시각인가, Pi 시계로 찍은 것인가),
      "chirp":    {"bandwidth_hz": B, "duration_s": Tp, "prf_hz": PRF, "direction": "up" | "down"},
      "stream":   {"first_chirp_sample": 첫 처프가 시작하는 표본 번호,
                   "dropped": [[빠지기 시작한 표본 번호(빠짐이 없었을 때의 번호), 빠진 개수], …]},
      "gated":    {"pulse_idx": "같은 이름의 _idx.npy (FPGA 펄스 계수)", "window_start_sample": 처프 시작 기준 창 시작}
  }

  layout = gated  : 펄스마다 처프 시작부터 S 표본만 기록 (N, S). FPGA 가 잘라 주면 데이터가 수백 배 준다.
  layout = stream : 끊김 없는 연속 IQ. PRI(= fs / PRF) 마다 잘라 쓴다. **표본이 빠지면 그 뒤 시각이 전부 밀린다** —
                    빠진 곳을 `dropped` 에 적어 주면 고쳐 쓴다. 표본 수가 시계다: t = t0 + n / fs.

펄스 시각 = t0 + (처프 시작 표본) / fs + Tp / 2  (처프 가운데 — 멈춤-이동 근사).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .radar import C, RadarConfig


def chirp(fs: float, bandwidth: float, duration: float, direction: str = "up") -> np.ndarray:
    """복소 기저대역 선형 처프 −B/2 → +B/2 (down 이면 반대)."""
    n = max(2, int(round(duration * fs)))
    t = np.arange(n) / fs - duration / 2
    k = (bandwidth / duration) * (1 if direction == "up" else -1)
    return np.exp(1j * np.pi * k * t * t).astype(np.complex64)


def _iq(a: np.ndarray) -> np.ndarray:
    if np.iscomplexobj(a):
        return a.astype(np.complex64, copy=False)
    if a.ndim >= 1 and a.shape[-1] == 2:
        return (a[..., 0].astype(np.float32) + 1j * a[..., 1].astype(np.float32)).astype(np.complex64)
    raise ValueError("IQ 는 complex 또는 마지막 축이 (I, Q) 인 정수 배열이어야 한다")


def matched_filter(pulses: np.ndarray, ref: np.ndarray, fs: float, r_min: float, r_max: float,
                   oversample: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """(N, S) 펄스 → (N, M) 거리 압축 · 경사거리 축. FFT 로 상관하고 oversample 배 보간해 거리 칸을 촘촘히 한다."""
    n, s = pulses.shape
    L = int(2 ** math.ceil(math.log2(s + ref.size)))
    Lo = L * oversample
    R = np.conj(np.fft.fft(ref, L))
    out = np.zeros((n, Lo), dtype=np.complex64)
    for i0 in range(0, n, 512):          # 메모리 · 속도 — 512 펄스씩
        X = np.fft.fft(pulses[i0:i0 + 512], L, axis=1) * R[None, :]
        Xo = np.zeros((X.shape[0], Lo), dtype=np.complex64)
        h = L // 2
        Xo[:, :h] = X[:, :h]
        Xo[:, Lo - (L - h):] = X[:, h:]
        out[i0:i0 + 512] = np.fft.ifft(Xo, axis=1) * oversample / ref.size
    lag_s = np.arange(Lo) / (fs * oversample)
    rng = C * lag_s / 2
    keep = (rng >= r_min) & (rng <= r_max)
    return rng[keep], out[:, keep]


def load_meta(raw_path: str | Path) -> dict:
    p = Path(raw_path)
    return json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))


def iq_npy(raw_path: str, radar: RadarConfig):  # noqa: ANN201
    """어댑터 규약 `load(raw, radar) -> (t, range_axis, rc)` — 위 제안 형식."""
    meta = load_meta(raw_path)
    fs = float(meta["fs_hz"])
    ch = meta["chirp"]
    B, Tp, prf = float(ch["bandwidth_hz"]), float(ch["duration_s"]), float(ch["prf_hz"])
    ref = chirp(fs, B, Tp, ch.get("direction", "up"))
    data = _iq(np.load(raw_path, mmap_mode="r"))
    t0 = float(meta["t0_unix"])
    r_min = radar.range_min_m if radar.range_min_m is not None else 0.0
    r_max = radar.range_max_m if radar.range_max_m is not None else 200.0
    if meta.get("layout", "gated") == "gated":
        g = meta.get("gated", {})
        idx_path = Path(raw_path).with_name(Path(raw_path).stem + "_idx.npy")
        idx = np.load(idx_path) if idx_path.exists() else np.arange(data.shape[0])
        pulses = np.asarray(data)
        start = idx.astype(np.float64) * (fs / prf) + float(g.get("window_start_sample", 0))
        t = t0 + start / fs + Tp / 2
    else:
        st = meta.get("stream", {})
        pri = fs / prf
        first = int(st.get("first_chirp_sample", 0))
        flat = np.asarray(data).reshape(-1)
        dropped = sorted(st.get("dropped", []))
        ideal_len = flat.size + sum(c for _, c in dropped)              # 빠짐이 없었다면의 길이 — 펄스 수는 이것으로
        n_pulses = int((ideal_len - first) // pri) + 1
        win = int(round(Tp * fs)) + int(math.ceil(2 * r_max / C * fs)) + 4
        pulses = np.zeros((n_pulses, win), dtype=np.complex64)
        t = np.zeros(n_pulses)
        keep = np.ones(n_pulses, dtype=bool)
        for k in range(n_pulses):
            true_start = first + int(round(k * pri))                  # 빠짐이 없을 때의 표본 번호
            lost_before = sum(c for at, c in dropped if at + c <= true_start)
            pos = true_start - lost_before                            # 파일 안의 실제 자리
            hit = any(at < true_start + win and at + c > true_start for at, c in dropped)   # 창이 빠진 곳에 걸림
            if hit or pos + win > flat.size or pos < 0:
                keep[k] = False                                       # 창 안에 빠진 곳이 있으면 버린다
                continue
            pulses[k] = flat[pos:pos + win]
            t[k] = t0 + true_start / fs + Tp / 2
        pulses, t = pulses[keep], t[keep]
    rng, rc = matched_filter(pulses, ref, fs, r_min, r_max)
    return t, rng, rc


def write_fake(out: str | Path, radar: RadarConfig, traj, origin, targets: list[np.ndarray], meta_in: dict | None = None,  # noqa: ANN001
               fs: float = 61.44e6, layout: str = "gated", t0_error_s: float = 0.0, noise: float = 0.05, seed: int = 0,
               drop: tuple[int, int] | None = None, max_pulses: int | None = None) -> dict:
    """가짜 SDR 원시(제안 형식) — 궤적에 맞춘 리플렉터 메아리. 시험 · 레이더 팀 형식 맞추기용."""
    from .attitude import lever_arm, phase_center
    from .simulate import beam_weight, pulse_times

    B, prf = float(radar.bandwidth_hz), float(radar.prf_hz)  # type: ignore[arg-type]
    Tp = min(4e-6, 0.5 / prf)
    fc = C / float(radar.wavelength_m)  # type: ignore[arg-type]
    ref = chirp(fs, B, Tp)
    t_mid = pulse_times(traj, prf)
    if max_pulses is not None and t_mid.size > max_pulses:     # 시험용 — 가운데만
        c = t_mid.size // 2
        t_mid = t_mid[c - max_pulses // 2:c - max_pulses // 2 + max_pulses]
    lever, _ = lever_arm(radar, meta_in)
    st = traj.at(origin, t_mid)
    pos = phase_center(np.stack([st["e"], st["n"], st["u"]], axis=1), st["yaw"], st["pitch"], st["roll"], lever)
    r_max = radar.range_max_m or 100.0
    win = ref.size + int(math.ceil(2 * r_max / C * fs)) + 8
    rng = np.random.default_rng(seed)
    pulses = (noise * (rng.standard_normal((t_mid.size, win)) + 1j * rng.standard_normal((t_mid.size, win))) / math.sqrt(2)).astype(np.complex64)
    n_idx = np.arange(win)
    for tg in targets:
        R = np.linalg.norm(pos - tg[None, :], axis=1)
        w = beam_weight(radar, pos, st["yaw"], st["roll"], tg, st["pitch"])
        tau = 2 * R / C
        for k in np.flatnonzero(w > 1e-3):
            # 처프를 지연 τ 만큼 늦춘 것(분수 표본은 주파수 영역 위상으로) · 반송파 위상 exp(−j2π f_c τ)
            d = tau[k] * fs
            spec = np.fft.fft(ref, win) * np.exp(-2j * np.pi * np.fft.fftfreq(win) * d)
            pulses[k] += (w[k] * np.exp(-2j * np.pi * fc * tau[k]) * np.fft.ifft(spec)).astype(np.complex64)
    pri = fs / prf
    idx = np.round((t_mid - t_mid[0]) * prf).astype(np.int64)
    t0_true = t_mid[0] - Tp / 2
    meta = {"layout": layout, "fs_hz": fs, "fc_hz": fc, "t0_unix": t0_true + t0_error_s, "t0_source": "pps",
            "chirp": {"bandwidth_hz": B, "duration_s": Tp, "prf_hz": prf, "direction": "up"}}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if layout == "gated":
        meta["gated"] = {"window_start_sample": 0}
        np.save(out, pulses)
        np.save(out.with_name(out.stem + "_idx.npy"), idx)
    else:
        total = int(idx[-1] * pri) + win + 16
        flat = (noise * (rng.standard_normal(total) + 1j * rng.standard_normal(total)) / math.sqrt(2)).astype(np.complex64)
        for k, i in enumerate(idx):
            s0 = int(round(i * pri))
            flat[s0:s0 + win] = pulses[k]
        dropped = []
        if drop is not None:
            at, cnt = drop
            flat = np.concatenate([flat[:at], flat[at + cnt:]])
            dropped = [[at, cnt]]
        meta["stream"] = {"first_chirp_sample": 0, "dropped": dropped}
        np.save(out, flat)
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"file": str(out), "pulses": int(t_mid.size), "window": win, "bytes": out.stat().st_size, "fc_hz": fc}


# 데이터 서버 · 파이프라인이 「이 파일이 원시 본체인가」를 묻는다 — 옆 파일(.json · _idx.npy)은 본체가 아니다
iq_npy.accepts = lambda path: str(path).endswith(".npy") and not str(path).endswith("_idx.npy")  # type: ignore[attr-defined]
