/**
 * src/sar/rtk.ts (261002 신설 — 드론 파트 · RTK)
 *
 * **GPS fix 를 RTK 관점에서 가른다.** 드론 상태(`state`)의 `gps` 묶음을 그대로 읽는다 — 새 칸을 지어내지 않는다.
 *
 * 숫자(`gps.fix_type`, MAVLink `GPS_FIX_TYPE`)가 있으면 그것이 먼저다. 문자열(`gps.fix`)은 에이전트마다 쓰는 법이
 * 달라(`3D` · `FIX_3D` · `RTK_FIXED` · `RTK_FIX`) 숫자가 없을 때만 본다.
 *
 *   0 NO_GPS · 1 NO_FIX · 2 2D · 3 3D · 4 DGPS · 5 RTK_FLOAT · 6 RTK_FIXED · 7 STATIC · 8 PPP
 */

export type RtkLevel = 'none' | 'gps' | 'dgps' | 'float' | 'fixed' | 'unknown';

const BY_TYPE: Record<number, RtkLevel> = {
  0: 'none', 1: 'none', 2: 'gps', 3: 'gps', 4: 'dgps', 5: 'float', 6: 'fixed', 7: 'gps', 8: 'gps',
};

export function rtkLevel(fixType: unknown, fix: unknown): RtkLevel {
  if (typeof fixType === 'number' && Number.isInteger(fixType) && fixType in BY_TYPE) return BY_TYPE[fixType]!;
  if (typeof fix !== 'string' || fix === '') return 'unknown';
  const s = fix.toUpperCase();
  if (s.includes('RTK') && (s.includes('FIX') && !s.includes('FLOAT'))) return 'fixed';
  if (s.includes('FLOAT')) return 'float';
  if (s.includes('DGPS')) return 'dgps';
  if (s.includes('NO_GPS') || s.includes('NO_FIX') || s === 'NONE') return 'none';
  if (/(^|_)(2D|3D)/.test(s) || s.includes('FIX')) return 'gps';
  return 'unknown';
}

/** 화면 이름의 사전 키. */
export const RTK_LABEL_KEY: Record<RtkLevel, string> = {
  none: 'rtk.level.none',
  gps: 'rtk.level.gps',
  dgps: 'rtk.level.dgps',
  float: 'rtk.level.float',
  fixed: 'rtk.level.fixed',
  unknown: 'rtk.level.unknown',
};

