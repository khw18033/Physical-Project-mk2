/**
 * src/sar/plan.ts (261002 신설 — 드론 파트 · SAR 직선 패스)
 *
 * **패스 계획의 계산과 검사.** 드론 쪽(`drone/sar_pass/mission.py` · `geometry.py`)과 **같은 숫자**를 쓴다 —
 * 화면이 통과시킨 계획을 드론이 거절하거나, 그 반대가 되면 안 된다. `verify:sar` 가 두 쪽의 경계값을 대조한다.
 *
 * 문구는 키다(`sar.rule.*`). 이 파일은 화면을 모른다.
 */

/** 요구 조건 — `mission.py` 의 MIN_LINE_M · MIN_SPEED · MAX_SPEED · MIN_PASSES · MIN_GAP_S 와 같다. */
export const SAR_RULES = {
  minLineM: 60,
  minSpeed: 3,
  maxSpeed: 5,
  minPasses: 2,
  minGapS: 10,
  minAltM: 5,
  maxAltM: 120,
  defaultAltM: 20,
  defaultSpeed: 4,
  /** 가속 한계와 등속 안정 시간 — lead-in 자동 계산(`lead_in_m`)의 입력이다. 드론의 SETTLE_S 와 같다. */
  accelMps2: 1,
  settleS: 5,
  /** 품질 판정 기본값 — 드론 `SarPlan.q_*` 와 같다. 넘으면 그 패스는 무효이고 드론이 다시 난다. */
  qCrossM: 1.0,
  qSpeedMps: 0.3,
  qAltM: 0.5,
  qHeadingDeg: 3.0,
  qEdgeM: 2.0,
  extraPasses: 2,
  minBatteryPct: 30,
} as const;

const EARTH_RADIUS_M = 6_378_137;
const rad = (deg: number) => (deg * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

export type LatLon = { lat: number; lon: number };

/** 시작점 기준 북·동(m). 수백 m 안쪽이라 평면 근사로 충분하다. */
export function toLocal(origin: LatLon, p: LatLon): { n: number; e: number } {
  return {
    n: rad(p.lat - origin.lat) * EARTH_RADIUS_M,
    e: rad(p.lon - origin.lon) * EARTH_RADIUS_M * Math.cos(rad(origin.lat)),
  };
}

export function toGlobal(origin: LatLon, n: number, e: number): LatLon {
  return {
    lat: origin.lat + deg(n / EARTH_RADIUS_M),
    lon: origin.lon + deg(e / (EARTH_RADIUS_M * Math.cos(rad(origin.lat)))),
  };
}

/** 시작점에서 방위(북=0°)·거리로 끝점. */
export function endFrom(start: LatLon, headingDeg: number, lengthM: number): LatLon {
  return toGlobal(start, lengthM * Math.cos(rad(headingDeg)), lengthM * Math.sin(rad(headingDeg)));
}

export function lineOf(start: LatLon, end: LatLon): { lengthM: number; headingDeg: number } {
  const { n, e } = toLocal(start, end);
  return { lengthM: Math.hypot(n, e), headingDeg: ((deg(Math.atan2(e, n)) % 360) + 360) % 360 };
}

/** 가속 거리 + 등속 안정 구간. 캡처 시작점 앞에 이만큼 비워 둔다(`geometry.lead_in_m`). */
export function autoLeadInM(speedMps: number): number {
  return speedMps ** 2 / (2 * SAR_RULES.accelMps2) + speedMps * SAR_RULES.settleS;
}

/** (진행 방향 거리, 오른쪽 + 횡오차). */
export function alongCross(start: LatLon, end: LatLon, p: LatLon): { along: number; cross: number } {
  const { n: ln, e: le } = toLocal(start, end);
  const length = Math.hypot(ln, le) || 1;
  const un = ln / length;
  const ue = le / length;
  const { n, e } = toLocal(start, p);
  return { along: n * un + e * ue, cross: -n * ue + e * un };
}

export type SarPlanDraft = {
  start: LatLon | null;
  end: LatLon | null;
  altM: number;
  speedMps: number;
  passes: number;
  gapS: number;
  /** 0 이면 자동. */
  leadInM: number;
  requireRtk: boolean;
  rtlOnAbort: boolean;
  rtlOnDone: boolean;
  qCrossM: number;
  qSpeedMps: number;
  qAltM: number;
  qHeadingDeg: number;
  qEdgeM: number;
  extraPasses: number;
  minBatteryPct: number;
};

export function defaultDraft(): SarPlanDraft {
  return {
    start: null, end: null,
    altM: SAR_RULES.defaultAltM, speedMps: SAR_RULES.defaultSpeed, passes: SAR_RULES.minPasses,
    gapS: SAR_RULES.minGapS, leadInM: 0, requireRtk: true, rtlOnAbort: false, rtlOnDone: false,
    qCrossM: SAR_RULES.qCrossM, qSpeedMps: SAR_RULES.qSpeedMps, qAltM: SAR_RULES.qAltM,
    qHeadingDeg: SAR_RULES.qHeadingDeg, qEdgeM: SAR_RULES.qEdgeM, extraPasses: SAR_RULES.extraPasses,
    minBatteryPct: SAR_RULES.minBatteryPct,
  };
}

/** 위반 하나 — 사전 키와 치환값. */
export type PlanProblem = { key: string; vars?: Record<string, string | number> };

export function planProblems(d: SarPlanDraft): PlanProblem[] {
  const out: PlanProblem[] = [];
  if (d.start === null || d.end === null) {
    out.push({ key: 'sar.rule.noLine' });
  } else {
    const { lengthM } = lineOf(d.start, d.end);
    if (!(lengthM >= SAR_RULES.minLineM)) out.push({ key: 'sar.rule.line', vars: { m: lengthM.toFixed(1), min: SAR_RULES.minLineM } });
  }
  if (!(d.speedMps >= SAR_RULES.minSpeed && d.speedMps <= SAR_RULES.maxSpeed)) {
    out.push({ key: 'sar.rule.speed', vars: { v: d.speedMps, min: SAR_RULES.minSpeed, max: SAR_RULES.maxSpeed } });
  }
  if (!(Number.isInteger(d.passes) && d.passes >= SAR_RULES.minPasses)) {
    out.push({ key: 'sar.rule.passes', vars: { n: d.passes, min: SAR_RULES.minPasses } });
  }
  if (!(d.gapS >= SAR_RULES.minGapS)) out.push({ key: 'sar.rule.gap', vars: { s: d.gapS, min: SAR_RULES.minGapS } });
  if (!(d.altM >= SAR_RULES.minAltM && d.altM <= SAR_RULES.maxAltM)) {
    out.push({ key: 'sar.rule.alt', vars: { m: d.altM, min: SAR_RULES.minAltM, max: SAR_RULES.maxAltM } });
  }
  if (!(d.leadInM >= 0)) out.push({ key: 'sar.rule.leadIn' });
  if (!(d.qCrossM > 0 && d.qSpeedMps > 0 && d.qAltM > 0 && d.qHeadingDeg > 0 && d.qEdgeM >= 0)) out.push({ key: 'sar.rule.quality' });
  if (!(Number.isInteger(d.extraPasses) && d.extraPasses >= 0 && d.extraPasses <= 10)) out.push({ key: 'sar.rule.extra' });
  if (!(d.minBatteryPct >= 10 && d.minBatteryPct <= 80)) out.push({ key: 'sar.rule.battery' });
  return out;
}

/** 예상 — 화면이 「얼마나 걸리나」를 미리 적는다. */
export function planEstimate(d: SarPlanDraft): {
  lengthM: number; headingDeg: number; leadInM: number; captureS: number; totalMinS: number;
} | null {
  if (d.start === null || d.end === null) return null;
  const { lengthM, headingDeg } = lineOf(d.start, d.end);
  const leadInM = Math.max(d.leadInM, autoLeadInM(d.speedMps));
  const captureS = lengthM / d.speedMps;
  // 패스마다 가속 + 캡처 + 감속, 사이마다 되돌아오기(대략 같은 속도) 또는 간격 중 긴 쪽
  const accelS = d.speedMps / SAR_RULES.accelMps2;
  const perPass = accelS + SAR_RULES.settleS + captureS + accelS;
  const back = Math.max(d.gapS, (lengthM + 2 * leadInM) / Math.max(d.speedMps, 3));
  return { lengthM, headingDeg, leadInM, captureS, totalMinS: d.passes * perPass + (d.passes - 1) * back };
}

/** 규약 파라미터로 — `map<string, double>` 라 참·거짓은 1·0 이다. 검사를 통과한 계획만 받는다. */
export function toStartParams(d: SarPlanDraft) {
  if (d.start === null || d.end === null) throw new Error('plan without line');
  return {
    start_lat: d.start.lat, start_lon: d.start.lon, end_lat: d.end.lat, end_lon: d.end.lon,
    alt_m: d.altM, speed_mps: d.speedMps, passes: d.passes, gap_s: d.gapS, lead_in_m: d.leadInM,
    require_rtk: d.requireRtk ? 1 : 0, rtl_on_abort: d.rtlOnAbort ? 1 : 0, rtl_on_done: d.rtlOnDone ? 1 : 0,
    q_cross_m: d.qCrossM, q_speed_mps: d.qSpeedMps, q_alt_m: d.qAltM, q_heading_deg: d.qHeadingDeg,
    q_edge_m: d.qEdgeM, extra_passes: d.extraPasses, min_battery_pct: d.minBatteryPct,
  };
}
