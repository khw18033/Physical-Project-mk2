"""자동 초점 방법 견주기 — 같은 패스를 「없음 · 리플렉터 · 엔트로피(리플렉터 없이)」로 만들어 리플렉터 품질을 표로.

논문 ① 「리플렉터로 검증한, 리플렉터 없는 자동 초점」의 표를 바로 만든다. 리플렉터는 **재기만** 하고
엔트로피 방법에는 알려 주지 않는다(그 방법은 영상만 본다).

  python -m sar_image.af_compare --traj flight_x/pass02_x.csv --raw iq_163150.bin \\
      --radar sar_image/example_radar_cansar.json --adapter sar_image.cansar:cansar_iq \\
      --cr 37.5664,126.9782 --cr … --out af_cmp/

결과: out/af_compare.json · af_compare.csv · af_compare.md · 방법별 영상 폴더(none/ · reflector/ · entropy/).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from .pipeline import form_pass
from .radar import RadarConfig
from .trajectory import R_EARTH, Origin, Trajectory

METHODS = ("none", "reflector", "entropy")
COLS = ("contrast_db", "offset_m", "res_along_m", "res_cross_m", "pslr_db", "islr_db")


def perturb(traj: Trajectory, origin: Origin, heading_deg: float, cross_m: float = 0.03, up_m: float = 0.02,
            period_s: float = 8.0, along_m: float = 0.0) -> Trajectory:
    """시험용 — 실제로 난 궤적이 기록(RTK)과 사인파로 어긋난 것. 기록은 그대로 두고 이것으로 가짜 원시를 만든다."""
    p = traj.enu(origin)
    hd = math.radians(heading_deg)
    ph = 2 * math.pi * (traj.t - traj.t[0]) / period_s
    dc, du, da = cross_m * np.sin(ph), up_m * np.sin(0.7 * ph + 1.0), along_m * np.sin(1.3 * ph + 2.0)
    e = p[:, 0] + dc * math.cos(hd) + da * math.sin(hd)
    n = p[:, 1] - dc * math.sin(hd) + da * math.cos(hd)
    lat = origin.lat + np.degrees(n / R_EARTH)
    lon = origin.lon + np.degrees(e / (R_EARTH * math.cos(math.radians(origin.lat))))
    return replace(traj, lat=lat, lon=lon, h=traj.h + du)


def _row(method: str, rec: dict) -> dict:
    m = rec.get("after_af") if method != "none" and rec.get("after_af") else rec
    return {"method": method, "reflector": rec["name"], "found": bool(rec.get("found")),
            **{k: m.get(k) for k in COLS}}


def run(traj_csv: Path, raw_files: list[Path], radar: RadarConfig, adapter: str, reflectors: list, out: Path,
        methods: tuple[str, ...] = METHODS, former: str | None = None, focuser_kw: dict | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rows, runs = [], {}
    for method in methods:
        t0 = time.time()
        kw: dict = {"former": former}
        if method == "none":
            kw["autofocus"] = False
        elif method == "entropy":
            from .gpu import entropy_focus
            kw["focuser"] = (lambda *a, **k: entropy_focus(*a, **{**k, **(focuser_kw or {})}))
        body = form_pass(traj_csv, raw_files, radar, adapter, out / method, reflectors=reflectors, full=False, **kw)
        runs[method] = {"autofocus": body.get("autofocus"), "seconds": round(time.time() - t0, 1)}
        rows += [_row(method, r) for r in body["reflectors"]]
    summary = {}
    for method in methods:
        sel = [r for r in rows if r["method"] == method and r["found"]]
        summary[method] = {k: (round(float(np.median([r[k] for r in sel if r[k] is not None])), 4)
                               if any(r[k] is not None for r in sel) else None) for k in COLS}
        summary[method]["found"] = f"{len(sel)}/{sum(1 for r in rows if r['method'] == method)}"
    res = {"schema": "sar-afcmp-0.1", "traj_csv": traj_csv.name, "runs": runs, "rows": rows, "median": summary}
    (out / "af_compare.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out / "af_compare.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["method", "reflector", "found", *COLS])
        w.writeheader()
        w.writerows(rows)
    lines = ["| 방법 | 찾음 | 대비 dB | 위치 오차 m | 진행 해상도 m | 옆 해상도 m | PSLR dB | ISLR dB | 시간 s |", "|---|---|---|---|---|---|---|---|---|"]
    for method in methods:
        s = summary[method]
        lines.append(f"| {method} | {s['found']} | " + " | ".join("—" if s[k] is None else f"{s[k]:g}" for k in COLS)
                     + f" | {runs[method]['seconds']} |")
    (out / "af_compare.md").write_text("리플렉터 중앙값 (자동 초점 뒤)\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sar_image.af_compare", description="자동 초점 방법 견주기(없음 · 리플렉터 · 엔트로피)")
    ap.add_argument("--traj", type=Path, required=True)
    ap.add_argument("--raw", type=Path, nargs="+", required=True)
    ap.add_argument("--radar", type=Path, required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--cr", action="append", default=[], help="lat,lon[,h] — 여러 번")
    ap.add_argument("--out", type=Path, default=Path("af_compare"))
    ap.add_argument("--former", help="예: sar_image.gpu:backproject_gpu")
    ap.add_argument("--methods", default=",".join(METHODS))
    a = ap.parse_args(argv)
    crs = []
    for s in a.cr:
        v = [float(x) for x in s.split(",")]
        crs.append((v[0], v[1], v[2] if len(v) > 2 else None))
    res = run(a.traj, a.raw, RadarConfig.load(a.radar), a.adapter, crs, a.out, tuple(a.methods.split(",")), a.former)
    print((a.out / "af_compare.md").read_text(encoding="utf-8"))
    print({k: v["seconds"] for k, v in res["runs"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
