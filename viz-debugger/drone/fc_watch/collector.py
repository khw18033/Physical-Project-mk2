"""FC 의 MAVLink 를 읽어 「드론 상태판」이 그릴 것을 모은다. **보내지 않는다(수신 전용).**

MicoConfigurator · QGC 의 상태 화면이 쓰는 메시지들이다:
  HEARTBEAT(모드·arm) · ATTITUDE · VFR_HUD(속도·상승률·헤딩·스로틀) · GLOBAL_POSITION_INT · HOME_POSITION
  GPS_RAW_INT(fix·위성·HDOP·정확도) · GPS_RTK/GPS2_RTK · SYS_STATUS(센서 건강·배터리·통신 손실)
  BATTERY_STATUS(셀 전압·온도) · ESTIMATOR_STATUS(EKF 비율 → POS·VEL·MAG·TER·VER) · VIBRATION
  EXTENDED_SYS_STATE(착지 상태) · RC_CHANNELS(RSSI) · STATUSTEXT(메시지 콘솔) · SYSTEM_TIME(시계 오차)

값이 아직 안 왔으면 None 이다 — 0 으로 채우지 않는다.
"""

from __future__ import annotations

import math
import time
from collections import deque
from typing import Any

from pymavlink import mavutil

M = mavutil.mavlink

# PX4 custom_mode → 사람이 읽는 모드 (드론 에이전트의 flight.mode 와 같은 꼴: AUTO.LOITER)
PX4_MAIN = {1: "MANUAL", 2: "ALTCTL", 3: "POSCTL", 4: "AUTO", 5: "ACRO", 6: "OFFBOARD", 7: "STABILIZED", 8: "RATTITUDE"}
PX4_AUTO = {1: "READY", 2: "TAKEOFF", 3: "LOITER", 4: "MISSION", 5: "RTL", 6: "LAND", 8: "FOLLOW_TARGET", 9: "PRECLAND"}

FIX_NAMES = {0: "NO_GPS", 1: "NO_FIX", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED", 7: "STATIC", 8: "PPP"}
LANDED = {0: "UNDEFINED", 1: "ON_GROUND", 2: "IN_AIR", 3: "TAKEOFF", 4: "LANDING"}
SEVERITY = {0: "EMERGENCY", 1: "ALERT", 2: "CRITICAL", 3: "ERROR", 4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG"}

# SYS_STATUS 센서 비트 → 짧은 이름 (pymavlink 의 열거형에서 그대로 꺼낸다 — 표를 손으로 적지 않는다)
SENSOR_BITS = {k: v.name.replace("MAV_SYS_STATUS_SENSOR_", "").replace("MAV_SYS_STATUS_", "")
               for k, v in M.enums["MAV_SYS_STATUS_SENSOR"].items() if k and k & (k - 1) == 0 and k < (1 << 31)}


def px4_mode(custom_mode: int) -> str:
    main = (custom_mode >> 16) & 0xFF
    sub = (custom_mode >> 24) & 0xFF
    name = PX4_MAIN.get(main, f"MODE_{main}")
    if main == 4:
        return f"AUTO.{PX4_AUTO.get(sub, sub)}"
    return name


def _r(v: Any, nd: int = 2) -> Any:
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(v, nd)


def _finite(v: Any) -> Any:
    """NaN · ±inf → None. PX4 는 「없음」을 NaN 으로 보낸다(대기속도 센서가 없으면 VFR_HUD.airspeed).
    json.dumps 는 그걸 `NaN` 그대로 쓰는데 JSON 이 아니라서 브라우저 JSON.parse 가 **보고 전체를** 버린다."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_finite(x) for x in v]
    return v


class FcTelemetry:
    def __init__(self, fc_sysid: int | None = None, clock=time.time, console_len: int = 100) -> None:  # noqa: ANN001
        self.clock = clock
        self.fc_sysid = fc_sysid           # None 이면 첫 autopilot heartbeat 의 sysid 로 정한다
        self.d: dict[str, Any] = {}
        self.at: dict[str, float] = {}     # 메시지 종류별 마지막 수신 시각
        self.console: deque[dict] = deque(maxlen=console_len)
        self._st_chunks: dict[int, list[str]] = {}
        self.msg_count = 0
        self._rate: deque[float] = deque()

    # ── 받기 ─────────────────────────────────────────────────────────────────
    def on_message(self, msg) -> None:  # noqa: ANN001, C901
        mtype = msg.get_type()
        if mtype == "BAD_DATA":
            return
        src = msg.get_srcSystem()
        if mtype == "HEARTBEAT" and self.fc_sysid is None and msg.autopilot != M.MAV_AUTOPILOT_INVALID:
            self.fc_sysid = src
        if self.fc_sysid is not None and src != self.fc_sysid:
            return                         # QGC · MAVSDK · 우리 자신이 보낸 것은 FC 상태가 아니다
        if mtype == "HEARTBEAT" and msg.autopilot == M.MAV_AUTOPILOT_INVALID:
            return                         # 같은 sysid 의 짐벌·카메라 등
        now = self.clock()
        self.at[mtype] = now
        self.msg_count += 1
        self._rate.append(now)
        while self._rate and now - self._rate[0] > 5.0:
            self._rate.popleft()
        d = self.d

        if mtype == "HEARTBEAT":
            d["armed"] = bool(msg.base_mode & M.MAV_MODE_FLAG_SAFETY_ARMED)
            d["mode"] = px4_mode(msg.custom_mode) if msg.autopilot == M.MAV_AUTOPILOT_PX4 else f"CUSTOM_{msg.custom_mode}"
            d["system_status"] = msg.system_status
        elif mtype == "ATTITUDE":
            import math
            d["roll_deg"], d["pitch_deg"] = math.degrees(msg.roll), math.degrees(msg.pitch)
            d["yaw_deg"] = math.degrees(msg.yaw) % 360
        elif mtype == "VFR_HUD":
            d.update(groundspeed=msg.groundspeed, airspeed=msg.airspeed, climb=msg.climb,
                     heading=msg.heading, throttle=msg.throttle)
        elif mtype == "GLOBAL_POSITION_INT":
            d.update(lat=msg.lat / 1e7, lon=msg.lon / 1e7, alt_rel_m=msg.relative_alt / 1000,
                     alt_msl_m=msg.alt / 1000, vx=msg.vx / 100, vy=msg.vy / 100, vz=msg.vz / 100)
        elif mtype == "HOME_POSITION":
            d["home"] = {"lat": msg.latitude / 1e7, "lon": msg.longitude / 1e7, "alt_msl_m": msg.altitude / 1000}
        elif mtype == "GPS_RAW_INT":
            d["gps"] = {
                "fix_type": msg.fix_type, "fix": FIX_NAMES.get(msg.fix_type, str(msg.fix_type)),
                "satellites": None if msg.satellites_visible == 255 else msg.satellites_visible,
                "hdop": None if msg.eph == 65535 else msg.eph / 100,
                "vdop": None if msg.epv == 65535 else msg.epv / 100,
                "h_acc_m": (getattr(msg, "h_acc", 0) or None) and msg.h_acc / 1000,
                "v_acc_m": (getattr(msg, "v_acc", 0) or None) and msg.v_acc / 1000,
                "lat": msg.lat / 1e7 if msg.fix_type >= 2 else None,
                "lon": msg.lon / 1e7 if msg.fix_type >= 2 else None,
            }
        elif mtype in ("GPS_RTK", "GPS2_RTK"):
            import math
            d["rtk"] = {
                "baseline_m": math.sqrt(msg.baseline_a_mm ** 2 + msg.baseline_b_mm ** 2 + msg.baseline_c_mm ** 2) / 1000,
                "accuracy_mm": msg.accuracy, "iar_hypotheses": msg.iar_num_hypotheses,
                "rtk_rate": msg.rtk_rate, "nsats": msg.nsats, "health": msg.rtk_health,
            }
        elif mtype == "SYS_STATUS":
            present, enabled, health = (msg.onboard_control_sensors_present, msg.onboard_control_sensors_enabled,
                                        msg.onboard_control_sensors_health)
            sensors = []
            for bit, name in sorted(SENSOR_BITS.items()):
                if present & bit:
                    sensors.append({"name": name, "enabled": bool(enabled & bit), "healthy": bool(health & bit)})
            d["sensors"] = sensors
            d["load_pct"] = msg.load / 10
            d["drop_rate_pct"] = msg.drop_rate_comm / 100
            d["battery"] = {**d.get("battery", {}),
                            "voltage_v": None if msg.voltage_battery == 65535 else msg.voltage_battery / 1000,
                            "current_a": None if msg.current_battery == -1 else msg.current_battery / 100,
                            "remaining_pct": None if msg.battery_remaining == -1 else msg.battery_remaining}
        elif mtype == "BATTERY_STATUS":
            cells = [v / 1000 for v in msg.voltages if v not in (65535, 0)]
            d["battery"] = {**d.get("battery", {}), "cells_v": cells,
                            "temperature_c": None if msg.temperature == 32767 else msg.temperature / 100,
                            "consumed_mah": None if msg.current_consumed == -1 else msg.current_consumed}
        elif mtype == "ESTIMATOR_STATUS":
            # QGC · MicoConfigurator 의 EKF 표시와 같은 기준: 비율 < 0.5 좋음, < 1.0 주의, 그 이상 나쁨
            d["ekf"] = {"vel": msg.vel_ratio, "pos": msg.pos_horiz_ratio, "ver": msg.pos_vert_ratio,
                        "mag": msg.mag_ratio, "ter": msg.hagl_ratio, "flags": msg.flags,
                        "gps_glitch": bool(msg.flags & 1024), "accel_error": bool(msg.flags & 2048),
                        "pos_h_acc_m": msg.pos_horiz_accuracy, "pos_v_acc_m": msg.pos_vert_accuracy}
        elif mtype == "VIBRATION":
            d["vibration"] = {"x": msg.vibration_x, "y": msg.vibration_y, "z": msg.vibration_z,
                              "clipping": [msg.clipping_0, msg.clipping_1, msg.clipping_2]}
        elif mtype == "WIND_COV":
            # PX4 EKF 가 추정한 바람(땅 기준, 바람이 **불어 가는** 방향 벡터). 표시는 기상 관례 — 불어 **오는** 방향.
            import math as _m
            vn, ve = msg.wind_x, msg.wind_y
            if _m.isfinite(vn) and _m.isfinite(ve):
                d["wind"] = {"speed_mps": round(_m.hypot(vn, ve), 2), "from_deg": round((_m.degrees(_m.atan2(ve, vn)) + 180) % 360, 1),
                             "vn": round(vn, 2), "ve": round(ve, 2),
                             "var_h": None if not _m.isfinite(msg.var_horiz) else round(msg.var_horiz, 3)}
        elif mtype == "EXTENDED_SYS_STATE":
            d["landed_state"] = LANDED.get(msg.landed_state, str(msg.landed_state))
        elif mtype == "RC_CHANNELS":
            d["rc"] = {"rssi": None if msg.rssi == 255 else round(msg.rssi / 254 * 100), "channels": msg.chancount}
        elif mtype == "SYSTEM_TIME":
            if msg.time_unix_usec > 1_600_000_000_000_000:
                d["clock_offset_s"] = self.clock() - msg.time_unix_usec / 1e6
        elif mtype == "STATUSTEXT":
            self._statustext(msg, now)

    def _statustext(self, msg, now: float) -> None:  # noqa: ANN001
        text = msg.text if isinstance(msg.text, str) else msg.text.decode(errors="replace")
        text = text.rstrip("\x00")
        mid = getattr(msg, "id", 0) or 0
        if mid:   # 긴 문장은 조각(chunk_seq)으로 온다 — 모아서 하나로
            parts = self._st_chunks.setdefault(mid, [])
            parts.append(text)
            if len(text) == 50:
                return
            text = "".join(self._st_chunks.pop(mid))
        self.console.append({"t": round(now, 3), "severity": SEVERITY.get(msg.severity, str(msg.severity)),
                             "level": msg.severity, "text": text})

    # ── 내보내기 ─────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        now = self.clock()
        hb = self.at.get("HEARTBEAT")
        d = self.d
        att = {"roll_deg": _r(d.get("roll_deg"), 1), "pitch_deg": _r(d.get("pitch_deg"), 1),
               "yaw_deg": _r(d.get("yaw_deg"), 1)} if "roll_deg" in d else None
        return _finite({
            "link": {"heartbeat_age_s": None if hb is None else round(now - hb, 2),
                     "msgs_per_s": round(len(self._rate) / 5.0, 1), "fc_sysid": self.fc_sysid},
            "armed": d.get("armed"), "mode": d.get("mode"), "landed_state": d.get("landed_state"),
            "attitude": att,
            "hud": {k: _r(d.get(k)) for k in ("groundspeed", "airspeed", "climb", "heading", "throttle")}
            if "groundspeed" in d else None,
            "position": {"lat": d.get("lat"), "lon": d.get("lon"), "alt_rel_m": _r(d.get("alt_rel_m")),
                         "alt_msl_m": _r(d.get("alt_msl_m")),
                         "vn": _r(d.get("vx")), "ve": _r(d.get("vy")), "vd": _r(d.get("vz"))}
            if "lat" in d else None,
            "home": d.get("home"),
            "gps": d.get("gps"), "rtk": d.get("rtk"),
            "battery": d.get("battery"),
            "sensors": d.get("sensors"), "load_pct": d.get("load_pct"), "drop_rate_pct": d.get("drop_rate_pct"),
            "ekf": d.get("ekf"), "vibration": d.get("vibration"), "rc": d.get("rc"), "wind": d.get("wind"),
            "clock_offset_s": _r(d.get("clock_offset_s"), 3),
            "console": list(self.console)[-30:],
            "time": now,
        })
