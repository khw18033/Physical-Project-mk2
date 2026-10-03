"""GPS 간섭 지상 시험 — 레이더를 켜고 끄기를 번갈아 하며 GPS 위성 수 · 정확도 · RTK 를 비교한다. **날지 않는다.**

    python -m sar_pass emi --connect tcp:127.0.0.1:5760 --cap /home/physical/CAP_ON --cycles 4 --period 30 --out emi.json

레이더는 CAP_ON 이 있을 때 기록(송신)한다고 본다 — 이 도구가 CAP_ON 을 켰다 껐다 한다. 레이더 송신을 손으로 켜고 끄려면 --manual
(화면에 「지금 켜세요 / 끄세요」를 띄우고 Enter 를 기다린다).

판정(꺼짐 대비 켜짐): 평균 위성 수 2 개 넘게 줄거나 · 수평 정확도가 30 % 넘게 나빠지거나 · RTK Fixed 비율이 10 %p 넘게 줄면 「간섭 의심」.
기체 · 레이더 · 안테나를 비행 때와 같은 자리에 두고, 하늘이 트인 곳에서 한다. 결과는 비행 폴더 옆에 남겨 두면 나중에 견줄 수 있다.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from pathlib import Path

log = logging.getLogger("sar_pass.emi")

FIX = {0: "NO_GPS", 1: "NO_FIX", 2: "FIX_2D", 3: "FIX_3D", 4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED"}
SATS_DROP, ACC_WORSE, RTK_DROP = 2.0, 0.30, 0.10


def summarize(samples: list[dict]) -> dict | None:
    """samples: {"sats", "h_acc_m"|None, "fix"} 목록 → 평균 · 비율."""
    if not samples:
        return None
    acc = [s["h_acc_m"] for s in samples if s.get("h_acc_m") is not None]
    return {"n": len(samples), "sats_mean": round(statistics.fmean(s["sats"] for s in samples), 2),
            "sats_min": min(s["sats"] for s in samples),
            "h_acc_m_mean": round(statistics.fmean(acc), 3) if acc else None,
            "rtk_fixed_frac": round(sum(1 for s in samples if s["fix"] == "RTK_FIXED") / len(samples), 3)}


def verdict(off: dict | None, on: dict | None) -> dict:
    if off is None or on is None:
        return {"suspect": None, "reasons": ["한쪽 구간에 표본이 없다"]}
    reasons = []
    if off["sats_mean"] - on["sats_mean"] > SATS_DROP:
        reasons.append(f"위성 수 {off['sats_mean']:.1f} → {on['sats_mean']:.1f}")
    if off["h_acc_m_mean"] and on["h_acc_m_mean"] and on["h_acc_m_mean"] > off["h_acc_m_mean"] * (1 + ACC_WORSE):
        reasons.append(f"수평 정확도 {off['h_acc_m_mean']:.3f} → {on['h_acc_m_mean']:.3f} m")
    if off["rtk_fixed_frac"] - on["rtk_fixed_frac"] > RTK_DROP:
        reasons.append(f"RTK Fixed 비율 {off['rtk_fixed_frac']:.0%} → {on['rtk_fixed_frac']:.0%}")
    return {"suspect": bool(reasons), "reasons": reasons}


def run(connect: str, cap_path: Path | None, cycles: int, period_s: float, out: Path | None, manual: bool = False) -> int:
    from pymavlink import mavutil

    from .capture import CaptureFlag

    cap = None if manual or cap_path is None else CaptureFlag(cap_path, install_handlers=False)
    m = mavutil.mavlink_connection(connect, source_system=254, source_component=193, autoreconnect=True)
    phases: dict[str, list] = {"off": [], "on": []}
    timeline = []
    try:
        for c in range(cycles):
            for phase in ("off", "on"):
                if manual:
                    input(f"[{c + 1}/{cycles}] 레이더 송신을 {'켜고' if phase == 'on' else '끄고'} Enter ")
                elif phase == "on":
                    cap.on(max_on_s=period_s + 10)       # type: ignore[union-attr]
                else:
                    cap.off("emi 시험")                   # type: ignore[union-attr]
                log.info("[%d/%d] 레이더 %s — %.0f 초 잰다", c + 1, cycles, "켜짐" if phase == "on" else "꺼짐", period_s)
                t_end = time.time() + period_s
                settle = time.time() + min(3.0, period_s / 5)         # 바뀐 직후 몇 초는 버린다
                while time.time() < t_end:
                    msg = m.recv_match(type="GPS_RAW_INT", blocking=True, timeout=2)
                    if msg is None or time.time() < settle:
                        continue
                    s = {"t": time.time(), "phase": phase, "sats": msg.satellites_visible,
                         "h_acc_m": (msg.h_acc / 1000.0) if getattr(msg, "h_acc", 0) else None, "fix": FIX.get(msg.fix_type, str(msg.fix_type))}
                    phases[phase].append(s)
                    timeline.append(s)
    finally:
        if cap is not None:
            cap.off("emi 끝")
    off, on = summarize(phases["off"]), summarize(phases["on"])
    v = verdict(off, on)
    report = {"schema": "sar-emi-0.1", "connect": connect, "cycles": cycles, "period_s": period_s, "manual": manual,
              "off": off, "on": on, "verdict": v, "finished_unix": time.time()}
    print(json.dumps({k: report[k] for k in ("off", "on", "verdict")}, ensure_ascii=False, indent=2))
    if out is not None:
        out.write_text(json.dumps({**report, "samples": timeline}, ensure_ascii=False, indent=1), encoding="utf-8")
        log.info("결과 %s", out)
    if v["suspect"]:
        log.warning("간섭 의심: %s — 안테나 사이 거리 · 차폐 · 레이더 출력을 확인하고 날기 전에 다시 잰다", " · ".join(v["reasons"]))
    return 1 if v["suspect"] else 0
