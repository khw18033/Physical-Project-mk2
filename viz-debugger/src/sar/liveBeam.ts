// 비행 중 지도에 그릴 레이더 빔 — 상태판 지도와 SAR 패스 지도가 같이 쓴다.
//
// 안테나 값 · 리플렉터는 SAR 패스 화면에서 고른 것(브라우저 저장)을 그대로 읽는다 — 한 곳에서만 고친다.

import { beamFootprint, defaultAntenna, reflectorInBeam, type AntennaDraft, type Attitude } from './coverage.ts';
import type { LatLon } from './plan.ts';
import type { Area, Marker } from '../dronedash/SatMap.tsx';

export const ANT_KEY = 'viz.sar.antenna.v1';
export const CR_KEY = 'viz.sar.reflectors.v1';

export function readAntenna(): AntennaDraft {
  try { const raw = localStorage.getItem(ANT_KEY); if (raw !== null) return { ...defaultAntenna(), ...JSON.parse(raw) } as AntennaDraft; } catch { /* */ }
  return defaultAntenna();
}

export function readReflectors(): LatLon[] {
  try {
    const raw = localStorage.getItem(CR_KEY);
    const v: unknown = raw === null ? [] : JSON.parse(raw);
    return Array.isArray(v) ? v.filter((p): p is LatLon => typeof p?.lat === 'number' && typeof p?.lon === 'number') : [];
  } catch { return []; }
}

export type LiveDrone = { at: LatLon | null; altM: number | null; yawDeg: number | null; pitchDeg: number | null; rollDeg: number | null };

/**
 * 지금 빔 자국(다각형)과 빔 안에 든 리플렉터 번호. 땅에서 2 m 아래로 내려오면 그리지 않는다(이착륙 중엔 의미 없다).
 * 자세가 없으면 수평으로 본다 — 그 경우 `approx` 가 true.
 */
export function liveBeam(a: AntennaDraft, d: LiveDrone, reflectors: readonly LatLon[]): { area: Area | null; lit: Set<number>; approx: boolean } {
  const lit = new Set<number>();
  if (d.at === null || d.altM === null || d.yawDeg === null || d.altM < 2) return { area: null, lit, approx: false };
  const approx = d.pitchDeg === null || d.rollDeg === null;
  const att: Attitude = { yawDeg: d.yawDeg, pitchDeg: d.pitchDeg ?? 0, rollDeg: d.rollDeg ?? 0 };
  const poly = beamFootprint(a, d.at, d.altM, att);
  reflectors.forEach((cr, i) => { if (reflectorInBeam(a, d.at!, d.altM!, att, cr).lit) lit.add(i); });
  return { area: poly ? { points: poly, kind: 'beam' } : null, lit, approx };
}

/** 리플렉터 표식 — 빔 안이면 빛난다. 계획 판정(good/bad)이 있으면 그 색을 바탕으로 둔다. */
export function reflectorMarkers(reflectors: readonly LatLon[], lit: Set<number>, tone?: (i: number) => Marker['tone']): Marker[] {
  return reflectors.map((cr, i) => ({ ...cr, kind: 'reflector', label: `CR${i + 1}`, tone: tone?.(i), lit: lit.has(i) }));
}
