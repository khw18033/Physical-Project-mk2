"""코너리플렉터가 「정말 보이는가」 — 비행 전(계획 선) · 비행 후(실제 궤적) 둘 다.

① 관측 띠: 고도 h, 내려다보는 각 δ, 고도 방향 빔폭 β_e 이면 지상 거리
     가까운 쪽 = h / tan(δ + β_e/2),  먼 쪽 = h / tan(δ - β_e/2)  (δ - β_e/2 ≤ 0 이면 거리 창이 끝을 정한다)
② 경사거리 R = √(h² + g²) 이 레이더 거리 창 안에 있어야 한다.
③ 합성 개구 L = 2R·tan(β_a/2) — 리플렉터가 실제 기록 구간 양 끝에서 L/2 이상 안쪽이어야 개구가 다 찬다.
④ 비행 후: 실제 궤적 · 자세(롤은 내려다보는 각을, yaw 는 빔 방향을 바꾼다)로 시각마다 빔 안에 있었는지 센다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from .radar import RadarConfig, aperture_length_m, az_resolution_m
from .trajectory import Origin, Trajectory


@dataclass
class LineCoverage:
    """계획 선(직선 · 고도 h) 기준 판정."""
    reflector: str
    side_ok: bool
    ground_range_m: float          # 선에서 옆으로 (+ 가 안테나 쪽)
    along_m: float                 # 선 시작에서 앞으로
    slant_range_m: float
    look_down_deg: float           # 리플렉터를 내려다보는 각
    in_elevation_beam: bool | None
    in_range_window: bool | None
    aperture_m: float | None
    aperture_fraction: float | None  # 기록 구간 안에 들어오는 개구의 비율 (1 이면 다 찼다)
    range_res_m: float | None
    az_res_m: float | None
    ok: bool | None
    why: list[str]

    def public(self) -> dict:
        return asdict(self)


def swath_ground_ranges(radar: RadarConfig, h: float) -> tuple[float | None, float | None]:
    if radar.depression_deg is None or radar.el_beamwidth_deg is None:
        return None, None
    hi = radar.depression_deg + radar.el_beamwidth_deg / 2
    lo = radar.depression_deg - radar.el_beamwidth_deg / 2
    near = h / math.tan(math.radians(min(hi, 89.9)))
    far = h / math.tan(math.radians(lo)) if lo > 0.5 else math.inf
    if radar.range_max_m is not None and radar.range_max_m > h:
        far = min(far, math.sqrt(radar.range_max_m ** 2 - h ** 2))
    if radar.range_min_m is not None and radar.range_min_m > h:
        near = max(near, math.sqrt(radar.range_min_m ** 2 - h ** 2))
    return near, far


def line_coverage(radar: RadarConfig, start: tuple[float, float], end: tuple[float, float], h: float,
                  reflector: tuple[float, float, float], name: str = "CR",
                  rec_start_m: float = 0.0, rec_end_m: float | None = None) -> LineCoverage:
    """start/end/reflector 는 같은 ENU 평면의 (e, n) / (e, n, u). h 는 비행 고도(리플렉터 높이 기준이 아니라 같은 기준)."""
    se, sn = start
    ee, en = end
    length = math.hypot(ee - se, en - sn)
    ue, un = (ee - se) / length, (en - sn) / length
    re, rn, ru = reflector
    de, dn = re - se, rn - sn
    along = de * ue + dn * un
    right = de * un - dn * ue                  # 진행 방향 오른쪽이 +
    g = right * radar.side_sign                # 안테나 쪽이 +
    dh = h - ru
    slant = math.hypot(g, dh)
    look = math.degrees(math.atan2(dh, abs(g))) if g != 0 else 90.0
    why: list[str] = []
    side_ok = g > 0
    if not side_ok:
        why.append("리플렉터가 안테나 반대쪽에 있다")
    in_el = None
    if radar.depression_deg is not None and radar.el_beamwidth_deg is not None:
        in_el = side_ok and abs(look - radar.depression_deg) <= radar.el_beamwidth_deg / 2
        if not in_el and side_ok:
            near, far = swath_ground_ranges(radar, dh)
            why.append(f"고도 방향 빔 밖 — 내려다보는 각 {look:.1f}° (빔 {radar.depression_deg - radar.el_beamwidth_deg/2:.1f}~"
                       f"{radar.depression_deg + radar.el_beamwidth_deg/2:.1f}°), 지상거리 {g:.1f} m 는 띠 {near:.1f}~{far:.1f} m 밖")
    in_rng = None
    if radar.range_min_m is not None and radar.range_max_m is not None:
        in_rng = radar.range_min_m <= slant <= radar.range_max_m
        if not in_rng:
            why.append(f"경사거리 {slant:.1f} m 가 기록 범위 {radar.range_min_m}~{radar.range_max_m} m 밖")
    ap = frac = az_res = None
    rec_end = length if rec_end_m is None else rec_end_m
    if radar.az_beamwidth_deg is not None:
        ap = aperture_length_m(slant, radar.az_beamwidth_deg)
        lo, hi = along - ap / 2, along + ap / 2
        covered = max(0.0, min(hi, rec_end) - max(lo, rec_start_m))
        frac = covered / ap if ap > 0 else 0.0
        if frac < 0.999:
            why.append(f"합성 개구 {ap:.1f} m 중 {frac*100:.0f}% 만 기록 구간에 든다 — 리플렉터를 구간 가운데 쪽으로 "
                       f"(앞뒤 끝에서 {ap/2:.1f} m 이상 안쪽)")
        if radar.wavelength_m is not None:
            az_res = az_resolution_m(radar.wavelength_m, slant, ap * max(frac, 1e-3))
    rng_res = radar.range_resolution_m
    flags = [side_ok, in_el, in_rng, None if frac is None else frac >= 0.999]
    ok = None if any(f is None for f in flags) else all(flags)  # type: ignore[arg-type]
    if any(f is False for f in flags):
        ok = False
    return LineCoverage(name, side_ok, round(g, 2), round(along, 2), round(slant, 2), round(look, 2), in_el, in_rng,
                        None if ap is None else round(ap, 2), None if frac is None else round(frac, 3),
                        None if rng_res is None else round(rng_res, 4), None if az_res is None else round(az_res, 4), ok, why)


def antenna_angles(radar: RadarConfig, d: np.ndarray, yaw_deg: np.ndarray, roll_deg: np.ndarray,
                   pitch_deg: np.ndarray | float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """안테나 좌표계에서 본 표적 방향 — (방위 오프셋, 고도 오프셋) 도. 빔폭은 이 두 각으로 판정한다.

    안테나는 기체에 고정되어 오른쪽(또는 왼쪽)을 `depression` 만큼 내려다본다. 빔 방향을 기체 기준(FRD)으로
    만든 뒤 **그 순간 자세 3축(yaw · pitch · roll)으로 돌린다.** 오른쪽으로 기울면(롤 +) 오른쪽 보기 안테나는
    더 내려다보고, 앞으로 숙이면(피치 −) 빔이 뒤쪽으로 비스듬해진다(SITL 에서 등속 중 피치 −22° 를 봤다).
    방위각은 **안테나 면(기울어진 면)에서** 잰다 — 수평면에서 재면 개구가 짧게 잡힌다
    (예: 경사 28 m · 빔 30° 에서 수평면 10.7 m vs 실제 15.2 m).
    """
    from .attitude import frd_to_enu

    s = radar.side_sign
    dep = math.radians(radar.depression_deg or 0.0)
    sq = math.radians(radar.squint_deg)
    h = np.array([math.sin(sq), s * math.cos(sq), 0.0])          # 빔의 기체 수평 방향
    down = np.array([0.0, 0.0, 1.0])
    b = math.cos(dep) * h + math.sin(dep) * down                 # 빔 중심 (FRD)
    f = np.array([math.cos(sq), -s * math.sin(sq), 0.0])        # 방위 축 (빔에 수직, 앞쪽)
    u = math.sin(dep) * h - math.cos(dep) * down                 # 빔에 수직, 위쪽
    yaw = np.asarray(yaw_deg, dtype=float)
    roll = np.broadcast_to(np.asarray(roll_deg, dtype=float), yaw.shape)
    pitch = np.broadcast_to(np.asarray(pitch_deg, dtype=float), yaw.shape)
    B, F, U = (frd_to_enu(v, yaw, pitch, roll) for v in (b, f, u))
    db = (d * B).sum(-1)
    az = np.degrees(np.arctan2((d * F).sum(-1), db))
    el = np.degrees(np.arctan2((d * U).sum(-1), db))
    return az, -el      # el + 는 빔 중심보다 아래(더 내려다봄)


def predicted_history(radar: RadarConfig, traj: Trajectory, origin: Origin, reflector_enu: np.ndarray,
                      only_capture: bool = True, meta: dict | None = None) -> dict[str, np.ndarray]:
    """실제 궤적으로 시각별 예상 경사거리와 「빔 안」 여부. 레이더 거리-시간 영상에 겹쳐 볼 쌍곡선이다.
    위치는 레버암을 자세로 돌려 더한 **안테나 위상중심**이다(`attitude.lever_arm`)."""
    from .attitude import lever_arm, phase_center

    lever, _ = lever_arm(radar, meta)
    p = phase_center(traj.enu(origin), traj.yaw, traj.pitch, traj.roll, lever)
    d = reflector_enu[None, :] - p
    rng = np.linalg.norm(d, axis=1)
    horiz = np.hypot(d[:, 0], d[:, 1])
    look_down = np.degrees(np.arctan2(-d[:, 2], horiz))
    az_off, el_off = antenna_angles(radar, d, traj.yaw, traj.roll, traj.pitch)
    in_beam = (d * 0).sum(-1) == 0
    if radar.az_beamwidth_deg is not None:
        in_beam &= np.abs(az_off) <= radar.az_beamwidth_deg / 2
    if radar.depression_deg is not None and radar.el_beamwidth_deg is not None:
        in_beam &= np.abs(el_off) <= radar.el_beamwidth_deg / 2
    if radar.range_min_m is not None and radar.range_max_m is not None:
        in_beam &= (rng >= radar.range_min_m) & (rng <= radar.range_max_m)
    keep = traj.capture if only_capture else np.ones_like(in_beam)
    return {"t": traj.t[keep], "range_m": rng[keep], "in_beam": in_beam[keep], "az_off_deg": az_off[keep],
            "look_down_deg": look_down[keep]}


def summarize_history(h: dict[str, np.ndarray]) -> dict:
    if h["t"].size == 0:
        return {"samples": 0}
    i = int(np.argmin(h["range_m"]))
    inb = h["in_beam"]
    return {
        "samples": int(h["t"].size),
        "closest_range_m": round(float(h["range_m"][i]), 3),
        "closest_time": round(float(h["t"][i]), 4),
        "in_beam_fraction": round(float(inb.mean()), 3),
        "in_beam_seconds": round(float(inb.sum() * np.median(np.diff(h["t"])) if h["t"].size > 1 else 0.0), 2),
        "seen": bool(inb.any()),
    }
