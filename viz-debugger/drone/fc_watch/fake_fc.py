"""시험 · 화면 연습용 가짜 FC — 시뮬레이터 상태를 **진짜 MAVLink 바이트**로 만든다.

수집기를 「바이트 → pymavlink 파서 → on_message」 길 그대로 시험하려는 것이다. PX4 가 아니다.
"""

from __future__ import annotations

import math
import random

from pymavlink.dialects.v20 import common as M

PX4_POSCTL = 3 << 16
PX4_OFFBOARD = 6 << 16
PX4_AUTO_LOITER = (4 << 16) | (3 << 24)
PX4_AUTO_RTL = (4 << 16) | (5 << 24)
MODE_CODE = {"OFFBOARD": PX4_OFFBOARD, "HOLD": PX4_AUTO_LOITER, "GOTO": PX4_AUTO_LOITER,
             "RTL": PX4_AUTO_RTL, "POSCTL": PX4_POSCTL}


class FakeFc:
    def __init__(self, sysid: int = 1, seed: int = 0) -> None:
        self.mav = M.MAVLink(None, srcSystem=sysid, srcComponent=1)
        self.parser = M.MAVLink(None)
        self.rng = random.Random(seed)
        self.texts: list[tuple[int, str]] = []

    def _bytes(self, msgs) -> bytes:  # noqa: ANN001
        return b"".join(m.pack(self.mav) for m in msgs)

    def frame(self, *, t: float, lat: float, lon: float, alt_rel: float, vn: float, ve: float, vd: float,
              yaw_deg: float, mode: str, armed: bool = True, fix_type: int = 6, sats: int = 27,
              battery_v: float = 15.9, battery_pct: int = 78, home: tuple[float, float] | None = None,
              clock_offset_s: float = 0.04, rtcm_ok: bool = True) -> list:
        """한 순간의 메시지 묶음 → 파서를 지난 pymavlink 메시지들."""
        r = self.rng
        gs = math.hypot(vn, ve)
        roll = math.radians(r.gauss(0, 1.2))
        pitch = math.radians(-min(12.0, gs * 2.0) + r.gauss(0, 0.6))
        base_mode = (M.MAV_MODE_FLAG_SAFETY_ARMED if armed else 0) | M.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        present = 1 | 2 | 4 | 8 | 32 | 1024 | 2048 | 8192 | 16384 | 32768 | 65536 | (1 << 21) | (1 << 25)
        healthy = present if fix_type >= 3 else present & ~32
        msgs = [
            M.MAVLink_heartbeat_message(M.MAV_TYPE_QUADROTOR, M.MAV_AUTOPILOT_PX4, base_mode,
                                        MODE_CODE.get(mode, PX4_AUTO_LOITER), M.MAV_STATE_ACTIVE, 3),
            M.MAVLink_attitude_message(int(t * 1000) & 0xFFFFFFFF, roll, pitch, math.radians(yaw_deg), 0, 0, 0),
            M.MAVLink_vfr_hud_message(gs, gs, int(yaw_deg) % 360, 48 if armed else 0, alt_rel, -vd),
            M.MAVLink_global_position_int_message(int(t * 1000) & 0xFFFFFFFF, int(lat * 1e7), int(lon * 1e7),
                                                  int((alt_rel + 85) * 1000), int(alt_rel * 1000),
                                                  int(vn * 100), int(ve * 100), int(vd * 100), int(yaw_deg * 100)),
            M.MAVLink_gps_raw_int_message(int(t * 1e6), fix_type, int(lat * 1e7), int(lon * 1e7),
                                          int((alt_rel + 85) * 1000), 62 if fix_type >= 5 else 95, 110,
                                          int(gs * 100), int(yaw_deg * 100), sats),
            M.MAVLink_sys_status_message(present, present, healthy, 312, int(battery_v * 1000),
                                         1240, battery_pct, 0, 0, 0, 0, 0, 0),
            M.MAVLink_battery_status_message(0, 0, 1, 3120, [int(battery_v / 4 * 1000) + r.randint(-6, 6)
                                                            for _ in range(4)] + [65535] * 6,
                                             1240, 820, -1, battery_pct),
            M.MAVLink_estimator_status_message(int(t * 1e6), 0x3F, 0.08 + r.random() * 0.05, 0.05 + r.random() * 0.04,
                                               0.12, 0.10 + r.random() * 0.05, 0.0, 0.0, 0.02, 0.03),
            M.MAVLink_vibration_message(int(t * 1e6), 6 + r.random() * 3, 6 + r.random() * 3, 9 + r.random() * 4, 0, 0, 0),
            M.MAVLink_extended_sys_state_message(0, 2 if armed else 1),
            M.MAVLink_rc_channels_message(int(t * 1000) & 0xFFFFFFFF, 16, *([1500] * 18), 220),
            M.MAVLink_system_time_message(int((t - clock_offset_s) * 1e6), int(t * 1000) & 0xFFFFFFFF),
        ]
        if rtcm_ok and fix_type >= 5:
            msgs.append(M.MAVLink_gps_rtk_message(0, 0, 2300, int(t * 1000) % 604800000, 0, 1, sats - 3, 0,
                                                  120000, -80000, 3000, 12, 1))
        if home is not None:
            msgs.append(M.MAVLink_home_position_message(int(home[0] * 1e7), int(home[1] * 1e7), 85000,
                                                        0, 0, 0, [1, 0, 0, 0], 0, 0, 0))
        for sev, text in self.texts:
            msgs.append(M.MAVLink_statustext_message(sev, text.encode()[:50]))
        self.texts.clear()
        return self.parser.parse_buffer(self._bytes(msgs)) or []

    def say(self, severity: int, text: str) -> None:
        self.texts.append((severity, text))
