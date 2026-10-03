/**
 * src/sar/coverage.ts (261002 신설 — 드론 파트 · 코너리플렉터 배치)
 *
 * **리플렉터를 여기 두면 레이더가 볼까** — 드론 쪽 `drone/sar_image/coverage.py` 의 `line_coverage` 와 **같은 식**이다.
 *   관측 띠: 가까운 쪽 = h / tan(δ + β_e/2), 먼 쪽 = h / tan(δ − β_e/2)   (δ 내려다보는 각, β_e 고도 빔폭)
 *   경사거리 R = √(h² + g²) 가 기록 거리 안 · 합성 개구 L = 2R·tan(β_a/2) 가 캡처 구간 안에 다 들어야 한다.
 * `verify:sar` 가 같은 숫자를 낸다는 것을 대조한다.
 */

import { toLocal, type LatLon } from './plan.ts';

export type AntennaDraft = {
  side: 'right' | 'left';
  depressionDeg: number;
  elBeamwidthDeg: number;
  azBeamwidthDeg: number;
  rangeMinM: number;
  rangeMaxM: number;
  /** 영상 도구용 — 화면 판정에는 안 쓴다 */
  wavelengthM: number | null;
  bandwidthHz: number | null;
  prfHz: number | null;
  /** 레버암 (m, 기체 기준 앞 · 오른쪽 · 아래) — FC 에서 레이더 안테나 / GPS 안테나까지. drone/sar_image/attitude.py */
  antFwdM: number | null;
  antRightM: number | null;
  antDownM: number | null;
  gnssFwdM: number | null;
  gnssRightM: number | null;
  gnssDownM: number | null;
};

/** 예시 값 — 레이더 팀이 실제 사양으로 바꾼다 (drone/sar_image/example_radar.json 과 같다). */
export function defaultAntenna(): AntennaDraft {
  return { side: 'right', depressionDeg: 45, elBeamwidthDeg: 40, azBeamwidthDeg: 30, rangeMinM: 5, rangeMaxM: 60,
    wavelengthM: 0.03123, bandwidthHz: 300e6, prfHz: 200,
    antFwdM: 0, antRightM: 0, antDownM: 0, gnssFwdM: null, gnssRightM: null, gnssDownM: null };
}

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

export function swathGroundRanges(a: AntennaDraft, h: number): { near: number; far: number } {
  const hi = a.depressionDeg + a.elBeamwidthDeg / 2;
  const lo = a.depressionDeg - a.elBeamwidthDeg / 2;
  let near = h / Math.tan(rad(Math.min(hi, 89.9)));
  let far = lo > 0.5 ? h / Math.tan(rad(lo)) : Infinity;
  if (a.rangeMaxM > h) far = Math.min(far, Math.sqrt(a.rangeMaxM ** 2 - h ** 2));
  if (a.rangeMinM > h) near = Math.max(near, Math.sqrt(a.rangeMinM ** 2 - h ** 2));
  return { near, far };
}

export type ReflectorCheck = {
  ok: boolean;
  groundRangeM: number;   // + 가 안테나 쪽
  alongM: number;
  slantRangeM: number;
  lookDownDeg: number;
  apertureM: number;
  apertureFraction: number;
  /** 사유 — 사전 키와 치환값 */
  why: { key: string; vars?: Record<string, string | number> }[];
};

export function checkReflector(a: AntennaDraft, start: LatLon, end: LatLon, h: number, cr: LatLon): ReflectorCheck {
  const e = toLocal(start, end);
  const length = Math.hypot(e.n, e.e) || 1;
  const un = e.n / length;
  const ue = e.e / length;
  const d = toLocal(start, cr);
  const along = d.n * un + d.e * ue;
  const right = d.e * un - d.n * ue;          // 진행 방향 오른쪽 +
  const g = right * (a.side === 'right' ? 1 : -1);
  const slant = Math.hypot(g, h);
  const look = g !== 0 ? deg(Math.atan2(h, Math.abs(g))) : 90;
  const why: ReflectorCheck['why'] = [];
  let ok = true;
  if (g <= 0) { ok = false; why.push({ key: 'cr.why.side' }); }
  else if (Math.abs(look - a.depressionDeg) > a.elBeamwidthDeg / 2) {
    ok = false;
    const { near, far } = swathGroundRanges(a, h);
    why.push({ key: 'cr.why.elevation', vars: { g: g.toFixed(1), near: near.toFixed(1), far: Number.isFinite(far) ? far.toFixed(1) : '∞' } });
  }
  if (!(slant >= a.rangeMinM && slant <= a.rangeMaxM)) {
    ok = false;
    why.push({ key: 'cr.why.range', vars: { r: slant.toFixed(1), min: a.rangeMinM, max: a.rangeMaxM } });
  }
  const ap = 2 * slant * Math.tan(rad(a.azBeamwidthDeg) / 2);
  const covered = Math.max(0, Math.min(along + ap / 2, length) - Math.max(along - ap / 2, 0));
  const frac = ap > 0 ? covered / ap : 0;
  if (frac < 0.999) {
    ok = false;
    why.push({ key: 'cr.why.aperture', vars: { ap: ap.toFixed(1), pct: Math.round(frac * 100), half: (ap / 2).toFixed(1) } });
  }
  return { ok, groundRangeM: g, alongM: along, slantRangeM: slant, lookDownDeg: look, apertureM: ap, apertureFraction: frac, why };
}

/** 지도에 그릴 관측 띠(캡처 구간을 따라 안테나 쪽 near~far) — 위경도 다각형. */
export function swathPolygon(a: AntennaDraft, start: LatLon, end: LatLon, h: number): LatLon[] | null {
  const { near, far } = swathGroundRanges(a, h);
  const f = Number.isFinite(far) ? far : Math.max(near + 1, (a.rangeMaxM ** 2 - h ** 2) ** 0.5 || near + 50);
  const e = toLocal(start, end);
  const length = Math.hypot(e.n, e.e);
  if (!(length > 0)) return null;
  const un = e.n / length;
  const ue = e.e / length;
  const s = a.side === 'right' ? 1 : -1;
  const rn = -ue * s;     // 안테나 쪽 단위벡터 (n, e)
  const re = un * s;
  const pt = (al: number, g: number) => {
    const n = un * al + rn * g;
    const ee = ue * al + re * g;
    const lat = start.lat + deg(n / 6_378_137);
    const lon = start.lon + deg(ee / (6_378_137 * Math.cos(rad(start.lat))));
    return { lat, lon };
  };
  return [pt(0, near), pt(length, near), pt(length, f), pt(0, f)];
}

/** sar_image 용 radar.json — 화면에서 고른 값 그대로. */
export function radarJson(a: AntennaDraft): string {
  return JSON.stringify({
    note: 'exported from the GUI - check against the real radar specs',
    wavelength_m: a.wavelengthM, bandwidth_hz: a.bandwidthHz, prf_hz: a.prfHz,
    range_min_m: a.rangeMinM, range_max_m: a.rangeMaxM, side: a.side, depression_deg: a.depressionDeg,
    el_beamwidth_deg: a.elBeamwidthDeg, az_beamwidth_deg: a.azBeamwidthDeg, squint_deg: 0,
    antenna_offset_m: [a.antFwdM ?? 0, a.antRightM ?? 0, a.antDownM ?? 0],
    // GPS 안테나 위치는 셋 다 재야 쓴다 — 하나라도 비면 「모름」(null)
    gnss_offset_m: a.gnssFwdM == null || a.gnssRightM == null || a.gnssDownM == null ? null : [a.gnssFwdM, a.gnssRightM, a.gnssDownM],
    position_ref: 'auto',
  }, null, 2);
}

// ── 실시간 빔 (비행 중) — drone/sar_image/attitude.py · coverage.antenna_angles 와 같은 식 ─────────────

type V3 = [number, number, number];

/** 기체(FRD: 앞 · 오른쪽 · 아래) 벡터 → ENU(동 · 북 · 위). 자세는 ZYX 오일러(yaw → pitch → roll), 도. */
export function frdToEnu(v: V3, yawDeg: number, pitchDeg: number, rollDeg: number): V3 {
  const [cy, sy, cp, sp, cr, sr] = [Math.cos(rad(yawDeg)), Math.sin(rad(yawDeg)), Math.cos(rad(pitchDeg)), Math.sin(rad(pitchDeg)),
    Math.cos(rad(rollDeg)), Math.sin(rad(rollDeg))];
  const n = cy * cp * v[0] + (cy * sp * sr - sy * cr) * v[1] + (cy * sp * cr + sy * sr) * v[2];
  const e = sy * cp * v[0] + (sy * sp * sr + cy * cr) * v[1] + (sy * sp * cr - cy * sr) * v[2];
  const d = -sp * v[0] + cp * sr * v[1] + cp * cr * v[2];
  return [e, n, -d];
}

/** 안테나 축 (FRD) — 빔 중심 b, 방위 축 f(앞쪽), 고도 축 u(위쪽). */
function antennaAxes(a: AntennaDraft): { b: V3; f: V3; u: V3 } {
  const s = a.side === 'right' ? 1 : -1;
  const dep = rad(a.depressionDeg);
  const h: V3 = [0, s, 0];
  const down: V3 = [0, 0, 1];
  const b: V3 = [Math.cos(dep) * h[0], Math.cos(dep) * h[1], Math.sin(dep)];
  const u: V3 = [Math.sin(dep) * h[0] - Math.cos(dep) * down[0], Math.sin(dep) * h[1], -Math.cos(dep)];
  return { b, f: [1, 0, 0], u };
}

export type Attitude = { yawDeg: number; pitchDeg: number; rollDeg: number };

/** 땅 위 빔 자국(3 dB 빔폭 · 최대 거리로 자른 것) — 위경도 다각형. 땅은 기체 아래 h m 의 평면. */
export function beamFootprint(a: AntennaDraft, at: LatLon, hM: number, att: Attitude, steps = 10): LatLon[] | null {
  if (!(hM > 0.5)) return null;
  const { b, f, u } = antennaAxes(a);
  const A = rad(a.azBeamwidthDeg / 2);
  const E = rad(a.elBeamwidthDeg / 2);
  const ray = (az: number, el: number): V3 => {
    const c: V3 = [Math.cos(az) * b[0] + Math.sin(az) * f[0], Math.cos(az) * b[1] + Math.sin(az) * f[1], Math.cos(az) * b[2] + Math.sin(az) * f[2]];
    return [Math.cos(el) * c[0] + Math.sin(el) * u[0], Math.cos(el) * c[1] + Math.sin(el) * u[1], Math.cos(el) * c[2] + Math.sin(el) * u[2]];
  };
  const boundary: [number, number][] = [];
  for (let i = 0; i <= steps; i++) boundary.push([-A + (2 * A * i) / steps, -E]);        // 아래(가까운) 가장자리
  for (let i = 1; i <= steps; i++) boundary.push([A, -E + (2 * E * i) / steps]);
  for (let i = 1; i <= steps; i++) boundary.push([A - (2 * A * i) / steps, E]);           // 위(먼) 가장자리
  for (let i = 1; i < steps; i++) boundary.push([-A, E - (2 * E * i) / steps]);
  const horizMax = a.rangeMaxM > hM ? Math.sqrt(a.rangeMaxM ** 2 - hM ** 2) : 0;
  const pts: LatLon[] = [];
  for (const [az, el] of boundary) {
    const d = frdToEnu(ray(az, el), att.yawDeg, att.pitchDeg, att.rollDeg);   // el − = 빔 중심보다 아래(가까운 쪽)
    const hz = Math.hypot(d[0], d[1]) || 1e-9;
    let gx: number; let gy: number;
    if (d[2] < -1e-6) {
      const t = hM / -d[2];
      gx = d[0] * t; gy = d[1] * t;
      if (Math.hypot(gx, gy) > horizMax) { gx = (d[0] / hz) * horizMax; gy = (d[1] / hz) * horizMax; }
    } else { gx = (d[0] / hz) * horizMax; gy = (d[1] / hz) * horizMax; }                // 수평 위로 향한 줄기 — 최대 거리에서 자른다
    pts.push({ lat: at.lat + deg(gy / 6_378_137), lon: at.lon + deg(gx / (6_378_137 * Math.cos(rad(at.lat)))) });
  }
  return pts;
}

/** 이 순간 리플렉터가 빔(3 dB) · 거리 범위 안에 있나. 각은 안테나 면에서 잰다(드론 쪽과 같다). */
export function reflectorInBeam(a: AntennaDraft, at: LatLon, hM: number, att: Attitude, cr: LatLon): { lit: boolean; azDeg: number; elDeg: number; slantM: number } {
  const d0 = toLocal(at, cr);
  const d: V3 = [d0.e, d0.n, -hM];
  const { b, f, u } = antennaAxes(a);
  const B = frdToEnu(b, att.yawDeg, att.pitchDeg, att.rollDeg);
  const F = frdToEnu(f, att.yawDeg, att.pitchDeg, att.rollDeg);
  const U = frdToEnu(u, att.yawDeg, att.pitchDeg, att.rollDeg);
  const dot = (x: V3, y: V3) => x[0] * y[0] + x[1] * y[1] + x[2] * y[2];
  const db = dot(d, B);
  const azDeg = deg(Math.atan2(dot(d, F), db));
  const elDeg = -deg(Math.atan2(dot(d, U), db));
  const slantM = Math.hypot(d[0], d[1], d[2]);
  const lit = db > 0 && Math.abs(azDeg) <= a.azBeamwidthDeg / 2 && Math.abs(elDeg) <= a.elBeamwidthDeg / 2
    && slantM >= a.rangeMinM && slantM <= a.rangeMaxM;
  return { lit, azDeg, elDeg, slantM };
}

/**
 * 재처리용 기록을 `sar_start` 파라미터로 — 규약이 숫자 사전이라 목록을 숫자 키로 펼친다.
 * 드론 `sar_pass.mission.reflectors_from_params` · `radar_from_params` 가 다시 모은다(키 이름은 verify:sar 가 맞춰 본다).
 */
export function provenanceParams(reflectors: readonly LatLon[], a: AntennaDraft): Record<string, number> {
  const out: Record<string, number> = { cr_n: Math.min(reflectors.length, 32) };
  reflectors.slice(0, 32).forEach((p, i) => { out[`cr${i}_lat`] = p.lat; out[`cr${i}_lon`] = p.lon; });
  out.ant_side = a.side === 'right' ? 1 : -1;
  out.ant_depression_deg = a.depressionDeg;
  out.ant_el_bw_deg = a.elBeamwidthDeg;
  out.ant_az_bw_deg = a.azBeamwidthDeg;
  out.ant_range_min_m = a.rangeMinM;
  out.ant_range_max_m = a.rangeMaxM;
  if (a.wavelengthM != null) out.ant_wavelength_m = a.wavelengthM;
  if (a.bandwidthHz != null) out.ant_bandwidth_hz = a.bandwidthHz;
  if (a.prfHz != null) out.ant_prf_hz = a.prfHz;
  out.ant_off_f = a.antFwdM ?? 0; out.ant_off_r = a.antRightM ?? 0; out.ant_off_d = a.antDownM ?? 0;
  if (a.gnssFwdM != null && a.gnssRightM != null && a.gnssDownM != null) {
    out.gnss_off_f = a.gnssFwdM; out.gnss_off_r = a.gnssRightM; out.gnss_off_d = a.gnssDownM;
  }
  return out;
}
