"""비행 보고서 (HTML 한 장) — 데이터 서버가 `/api/flights/<id>/report.html` 로 내준다. 팀원에게 그대로 공유한다.

패스마다 판정 · 사유 · 실제 기록 구간 · 품질 수치 · 레이더 지연 · 레이더 파일, 그리고 궤적 그림(캡처 구간 빨강).
외부 파일 · 스크립트 없이 한 장으로 끝난다(현장에서 인터넷이 없어도 열린다).
"""

from __future__ import annotations

import csv
import html
import json
import math
import time
from pathlib import Path


def _track_svg(csv_path: Path, length_m: float | None, width: int = 640, height: int = 220) -> str:
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    # 레이더 확인(cap_ack)이 있으면 그것이 실제 기록 구간, 없으면 요청(cap_on)
    flag = "cap_ack" if any(r.get("cap_ack") == "1" for r in rows) else "cap_on"
    pts = [(float(r["along_m"]), float(r["cross_m"]), r.get(flag) == "1") for r in rows if r.get("along_m") not in (None, "")]
    if not pts:
        return ""
    a0 = min(p[0] for p in pts) - 2
    a1 = max(p[0] for p in pts) + 2
    cmax = max(1.0, max(abs(p[1]) for p in pts) * 1.3)
    sx = (width - 60) / (a1 - a0)
    sy = (height - 40) / (2 * cmax)
    X = lambda a: 40 + (a - a0) * sx  # noqa: E731
    Y = lambda c: height / 2 + c * sy  # noqa: E731
    segs = []
    cur: list[str] = []
    cur_cap = None
    for a, c, cap in pts[:: max(1, len(pts) // 1500)]:
        if cur_cap is None or cap != cur_cap:
            if cur:
                segs.append((cur, cur_cap))
            cur = cur[-1:] if cur else []
            cur_cap = cap
        cur.append(f"{X(a):.1f},{Y(c):.1f}")
    if cur:
        segs.append((cur, cur_cap))
    parts = [f'<svg viewBox="0 0 {width} {height}" class="trk" role="img" aria-label="track">',
             f'<line x1="40" y1="{height/2}" x2="{width-20}" y2="{height/2}" class="axis"/>']
    if length_m:
        parts.append(f'<rect x="{X(0):.1f}" y="10" width="{X(length_m)-X(0):.1f}" height="{height-30}" class="seg"/>')
        parts.append(f'<text x="{X(0)+3:.1f}" y="22" class="lab">0 m</text><text x="{X(length_m)-34:.1f}" y="22" class="lab">{length_m:.0f} m</text>')
    for pl, cap in segs:
        parts.append(f'<polyline points="{" ".join(pl)}" class="{"cap" if cap else "fly"}"/>')
    parts.append(f'<text x="4" y="{Y(cmax*0.9):.1f}" class="lab">+{cmax*0.9:.1f} m</text><text x="4" y="{Y(-cmax*0.9):.1f}" class="lab">-{cmax*0.9:.1f} m</text>')
    parts.append("</svg>")
    return "".join(parts)


def flight_report(flight_dir: Path, radar_passes: list[dict] | None = None) -> str:
    metas = []
    for mp in sorted(flight_dir.glob("pass*.json")):
        try:
            metas.append(json.loads(mp.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    radar_by_pass = {p["pass_no"]: p for p in (radar_passes or [])}
    plan = metas[0]["plan"] if metas else {}
    line = metas[0].get("line", {}) if metas else {}
    valid = sum(1 for m in metas if m["pass"].get("valid"))
    esc = html.escape
    f = lambda v, d=2: "—" if v is None else (f"{v:.{d}f}" if isinstance(v, (int, float)) else esc(str(v)))  # noqa: E731
    rows, figs = [], []
    for m in metas:
        p = m["pass"]
        ok = p.get("valid")
        radar = radar_by_pass.get(p.get("pass_no"), {})
        rows.append(
            f"<tr class={'ok' if ok else 'bad'}><td>{p.get('pass_no')}</td>"
            f"<td>{'✓ 유효' if ok else '✕ 무효'}<small>{esc(' · '.join(p.get('reasons') or []))}</small></td>"
            f"<td>{f(p.get('eff_start_along_m'),1)} ~ {f(p.get('eff_end_along_m'),1)} m</td>"
            f"<td>{f(p.get('mean_speed_mps'))} m/s</td><td>{f(p.get('max_speed_err_mps'))}</td><td>{f(p.get('max_cross_track_m'))}</td>"
            f"<td>{f(p.get('max_alt_err_m'))}</td><td>{f(p.get('max_heading_err_deg'),1)}°<small>진행 {f(p.get('max_course_err_deg'),1)}°</small></td><td>{esc(str(p.get('worst_fix') or '—'))}</td>"
            f"<td>{f(p.get('ack_on_latency_s'))} s<small>미리 켬 {f(p.get('cap_lead_s'))} s</small></td>"
            f"<td>{len(radar.get('radar_files', []))}개</td>"
            f"<td><small>FC {f(p.get('fc_start_unix'),3)}<br>~ {f(p.get('fc_end_unix'),3)}</small></td></tr>")
        csv_name = m.get("traj_csv")
        if csv_name and (flight_dir / csv_name).exists():
            figs.append(f"<figure><figcaption>패스 {p.get('pass_no')} — 진행 방향 위치(가로) · 횡오차(세로, 확대) · 빨강 = 레이더 기록 중</figcaption>"
                        f"{_track_svg(flight_dir / csv_name, line.get('length_m'))}</figure>")
    warnings = sorted({w for m in metas for w in m.get("warnings", [])})
    base = metas[0].get("base_station") if metas else None
    clock = metas[0].get("clock", {}).get("offset_pi_minus_fc_s") if metas else None
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(flight_dir.name.split("_")[-1]))) if flight_dir.name.startswith("flight_") else flight_dir.name
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SAR 비행 보고서 {esc(started)}</title>
<style>
:root{{color-scheme:light;--ink:#17202b;--mut:#5d6b7a;--ok:#168f50;--bad:#c62f35;--line:#e1e5eb}}
body{{margin:0;padding:24px 16px;font-family:system-ui,"Noto Sans KR",sans-serif;color:var(--ink);background:#f6f7f9}}
main{{max-width:1100px;margin:0 auto;display:grid;gap:16px}}
section{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
h1{{font-size:20px;margin:0}} h2{{font-size:15px;margin:0 0 8px}}
.kpi{{display:flex;flex-wrap:wrap;gap:18px}} .kpi div{{display:grid}} .kpi b{{font-size:22px}} .kpi small{{color:var(--mut)}}
table{{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
td small{{display:block;color:var(--mut)}} tr.bad td:nth-child(2){{color:var(--bad)}} tr.ok td:nth-child(2){{color:var(--ok)}}
.trk{{width:100%;height:auto;max-height:240px;background:#fbfcfd;border:1px solid var(--line);border-radius:6px}}
.trk .axis{{stroke:#cbd3dc;stroke-dasharray:4 4}} .trk .seg{{fill:#1f8a4d14;stroke:#1f8a4d;stroke-dasharray:3 3}}
.trk .fly{{fill:none;stroke:#1768c5;stroke-width:1.5}} .trk .cap{{fill:none;stroke:#c62f35;stroke-width:2.5}} .trk .lab{{font-size:10px;fill:var(--mut)}}
figure{{margin:0 0 10px}} figcaption{{font-size:12px;color:var(--mut);margin-bottom:4px}}
ul{{margin:0;padding-left:18px}} .wrap{{overflow-x:auto}}
</style></head><body><main>
<section><h1>SAR 비행 보고서 — {esc(started)}</h1>
<div class="kpi">
 <div><small>유효 패스</small><b style="color:{'var(--ok)' if valid >= (plan.get('passes') or 0) else 'var(--bad)'}">{valid} / {plan.get('passes', '—')}</b></div>
 <div><small>시도</small><b>{len(metas)}</b></div>
 <div><small>캡처 구간</small><b>{f(line.get('length_m'),1)} m</b></div>
 <div><small>방위</small><b>{f(line.get('heading_deg'),1)}°</b></div>
 <div><small>고도 · 속도</small><b>{f(plan.get('alt_m'),0)} m · {f(plan.get('speed_mps'),1)} m/s</b></div>
 <div><small>시계 (파이 − FC GPS)</small><b>{f(clock,3)} s</b></div>
</div></section>
<section class="wrap"><h2>패스</h2><table><thead><tr><th>#</th><th>판정</th><th>실제 기록 구간</th><th>평균 속도</th><th>속도 오차</th><th>횡오차</th><th>고도 오차</th><th>yaw · 진행 방향</th><th>RTK 최저</th><th>레이더 지연</th><th>레이더 파일</th><th>FC GPS 시각</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<small>품질 기준: 횡 {f(plan.get('q_cross_m'),1)} m · 속도 {f(plan.get('q_speed_mps'))} m/s · 고도 {f(plan.get('q_alt_m'),1)} m · yaw {f(plan.get('q_heading_deg'),1)}° · 진행 방향 {f(plan.get('q_course_deg'),1)}° · 기록 끝 여유 {f(plan.get('q_edge_m'),1)} m</small></section>
<section><h2>궤적</h2>{''.join(figs) or '<p>궤적 파일이 없습니다</p>'}</section>
<section><h2>기준 · 주의</h2><ul>
<li>캡처 구간 시작 {f(plan.get('start_lat'),7)}, {f(plan.get('start_lon'),7)} → 끝 {f(plan.get('end_lat'),7)}, {f(plan.get('end_lon'),7)}</li>
<li>베이스(RTCM 1005): {esc(json.dumps(base, ensure_ascii=False)) if base else '모름'}</li>
<li>EKF2_HGT_REF: {f(metas[0].get('ekf2_hgt_ref') if metas else None, 0)}</li>
{''.join(f'<li>{esc(w)}</li>' for w in warnings)}
</ul></section>
</main></body></html>"""
