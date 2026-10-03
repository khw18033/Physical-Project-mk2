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
