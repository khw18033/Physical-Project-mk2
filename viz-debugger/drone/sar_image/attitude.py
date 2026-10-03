"""기체 자세 · 레버암 — 「GPS 가 알려준 점」에서 「레이더 안테나 위상중심」으로.

좌표계 (PX4 와 같다)
  기체(FRD)  x 앞 · y 오른쪽 · z 아래.  자세는 오일러 ZYX (yaw → pitch → roll), 도.
  지역(ENU)  e 동 · n 북 · u 위.       영상 · 궤적 계산은 모두 이것.

레버암이란: 위치가 보고되는 점(GPS 안테나 또는 FC)에서 레이더 안테나 위상중심까지의 거리 · 방향(기체 기준).
기체가 기울면 그 벡터가 함께 돈다. 0.2 m 아래에 단 안테나는 롤 2° 에 옆으로 7 mm 움직인다 — X대역
λ/8(≈4 mm)보다 크다. 그래서 펄스마다 그 순간 자세로 돌려 더한다.

어느 점이 보고되나 (PX4)
  EKF2_GPS_POS_X/Y/Z 를 실측값으로 넣었으면 → EKF 가 안테나 오프셋을 빼고 **FC(IMU)** 위치를 낸다.
  0 으로 두었으면(기본값)           → EKF 는 안테나가 FC 에 있다고 보므로 보고 위치 ≈ **GPS 안테나** 위치.
"""

from __future__ import annotations

import numpy as np


def rot_ned_from_frd(yaw_deg, pitch_deg, roll_deg) -> np.ndarray:  # noqa: ANN001
    """(..., 3, 3) — 기체(FRD) 벡터를 NED 로. R = Rz(yaw) · Ry(pitch) · Rx(roll)."""
    y, p, r = (np.radians(np.asarray(v, dtype=float)) for v in (yaw_deg, pitch_deg, roll_deg))
    y, p, r = np.broadcast_arrays(y, p, r)
    cy, sy, cp, sp, cr, sr = np.cos(y), np.sin(y), np.cos(p), np.sin(p), np.cos(r), np.sin(r)
    R = np.empty(y.shape + (3, 3))
    R[..., 0, 0] = cy * cp
    R[..., 0, 1] = cy * sp * sr - sy * cr
    R[..., 0, 2] = cy * sp * cr + sy * sr
    R[..., 1, 0] = sy * cp
    R[..., 1, 1] = sy * sp * sr + cy * cr
    R[..., 1, 2] = sy * sp * cr - cy * sr
    R[..., 2, 0] = -sp
    R[..., 2, 1] = cp * sr
    R[..., 2, 2] = cp * cr
    return R


def frd_to_enu(v_frd, yaw_deg, pitch_deg, roll_deg) -> np.ndarray:  # noqa: ANN001
    """기체 기준 벡터(들) → ENU. v_frd: (3,) 또는 (..., 3)."""
    R = rot_ned_from_frd(yaw_deg, pitch_deg, roll_deg)
    ned = np.einsum("...ij,...j->...i", R, np.asarray(v_frd, dtype=float))
    return np.stack([ned[..., 1], ned[..., 0], -ned[..., 2]], axis=-1)


def lever_arm(radar, meta: dict | None = None) -> tuple[np.ndarray, list[str]]:  # noqa: ANN001
    """보고 위치 → 안테나 위상중심 (FRD, m) 과 주의 문구.

    radar.json
      antenna_offset_m   FC(IMU) → 레이더 안테나 위상중심 [앞, 오른쪽, 아래]
      gnss_offset_m      FC(IMU) → GPS 안테나 [앞, 오른쪽, 아래] (= PX4 EKF2_GPS_POS_X/Y/Z 에 넣는 값)
      position_ref       auto | gnss | imu — 보고 위치가 어느 점인가. auto 면 비행 기록의 EKF2_GPS_POS 로 판단
    """
    notes: list[str] = []
    ant = np.asarray(radar.antenna_offset_m or [0.0, 0.0, 0.0], dtype=float)
    gnss = None if radar.gnss_offset_m is None else np.asarray(radar.gnss_offset_m, dtype=float)
    ekf = (meta or {}).get("ekf2_gps_pos")
    ref = radar.position_ref
    if ref == "auto":
        if ekf is None:
            ref = "gnss"
            notes.append("비행 기록에 EKF2_GPS_POS 가 없다 — 보고 위치를 GPS 안테나로 본다(PX4 기본값 0 일 때와 같다)")
        else:
            ref = "imu" if any(abs(float(v)) > 1e-6 for v in ekf) else "gnss"
    if ref == "imu":
        if ekf is not None and gnss is not None and np.abs(np.asarray(ekf, dtype=float) - gnss).max() > 0.01:
            notes.append(f"EKF2_GPS_POS {list(ekf)} 와 radar.json gnss_offset_m {gnss.tolist()} 가 1 cm 넘게 다르다 — 한쪽을 고친다")
        return ant, notes
    if gnss is None:
        if ant.any():
            notes.append("gnss_offset_m 을 모른다 — GPS 안테나가 FC 바로 위라고 보고 계산했다. 실측해서 radar.json 에 넣는다")
        gnss = np.zeros(3)
    return ant - gnss, notes


def phase_center(pos_enu: np.ndarray, yaw_deg, pitch_deg, roll_deg, lever_frd: np.ndarray) -> np.ndarray:  # noqa: ANN001
    """보고 위치(ENU) + 그 순간 자세로 돌린 레버암 → 안테나 위상중심(ENU)."""
    lever_frd = np.asarray(lever_frd, dtype=float)
    if not lever_frd.any():
        return np.asarray(pos_enu, dtype=float)
    return np.asarray(pos_enu, dtype=float) + frd_to_enu(lever_frd, yaw_deg, pitch_deg, roll_deg)


def tilt_motion_mm(lever_frd, roll_deg, pitch_deg) -> float:  # noqa: ANN001
    """자세 흔들림 때문에 안테나가 움직인 크기(평균 둘레 표준편차, mm) — 보정이 얼마나 중요한지 보여 준다."""
    lever_frd = np.asarray(lever_frd, dtype=float)
    if not lever_frd.any():
        return 0.0
    d = frd_to_enu(lever_frd, np.zeros_like(np.asarray(roll_deg, dtype=float)), pitch_deg, roll_deg)
    return float(np.sqrt(((d - d.mean(axis=0)) ** 2).sum(axis=1).mean()) * 1000.0)


__all__ = ["frd_to_enu", "lever_arm", "phase_center", "rot_ned_from_frd", "tilt_motion_mm"]
