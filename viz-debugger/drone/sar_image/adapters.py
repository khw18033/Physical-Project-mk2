"""레이더 원시 → 거리 압축 어댑터. **레이더 팀이 형식에 맞춰 하나 쓰면 `form` 이 영상을 만든다.**

규약 (`python -m sar_image form --adapter 모듈:함수`):

    def load(raw_path: str, radar: RadarConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return pulse_times,   # (N,)  펄스(처프)마다의 시각 — 궤적 CSV 와 **같은 시각 기준** (t_fc: FC GPS UTC 초)
               range_axis,    # (M,)  균일 간격 경사거리 m
               rc             # (N,M) 복소 거리 압축 데이터

시각을 맞추는 것이 가장 중요하다. 레이더가 자기 시계로 찍는다면, CAP_ACK 에 적힌 기록 시작 시각(파이 시계)과
메타의 시계 오차(offset_pi_minus_fc_s)로 FC GPS 시각으로 바꾼다: t_fc = t_pi − offset.

아래 `fmcw_dechirped_npz` 는 **예시**다 — FMCW 레이더가 디처프(beat) 신호를 .npz 로 남긴다고 가정했다.
"""

from __future__ import annotations

import numpy as np

from .radar import C, RadarConfig


def fmcw_dechirped_npz(raw_path: str, radar: RadarConfig, oversample: int = 8):  # noqa: ANN201
    """예시 FMCW: npz 안에 beat[N, S](복소), t[N](t_fc), fs(표본화 Hz), slope(Hz/s).

    빠른 시간은 **처프 가운데 기준**이라고 본다(가운데에서 위상 −4πR/λ). 거리 FFT 를 `oversample` 배로 늘려
    백프로젝션의 선형 보간이 봉우리를 깎지 않게 하고, FFT 가 0 번 표본 기준으로 붙이는 위상 기울기
    exp(−jπ f (S−1)/fs) 를 되돌린다 — 이게 남으면 거리마다 위상이 달라져 초점이 안 맞는다.
    레이더의 기준(처프 시작 · 가운데)이 다르면 이 한 줄이 바뀐다.
    """
    z = np.load(raw_path)
    beat = z["beat"]
    t = np.asarray(z["t"], dtype=float)
    fs = float(z["fs"])
    slope = float(z["slope"])
    s = beat.shape[1]
    n_fft = int(2 ** np.ceil(np.log2(s * oversample)))
    win = np.hanning(s).astype(np.float32)
    spec = np.fft.fft(beat * win[None, :], n=n_fft, axis=1)[:, : n_fft // 2]
    f = np.fft.fftfreq(n_fft, 1 / fs)[: n_fft // 2]
    spec *= np.exp(1j * np.pi * f * (s - 1) / fs)[None, :].astype(np.complex64)
    spec /= win.sum()
    rng = C * f / (2 * slope)
    keep = (rng >= (radar.range_min_m or 0)) & (rng <= (radar.range_max_m or rng.max()))
    return t, rng[keep], spec[:, keep].astype(np.complex64)
