/**
 * src/shared/radarStatus.ts (261003 신설 — 드론 파트 · 레이더 상태)
 *
 * **레이더(cansar)의 마지막 보고.** 받는 쪽(`physical/PhysicalClient.ts` → `radarFeed.ts`)이 밀어 넣고, 상태판 · SAR 점검이 읽는다.
 * 규약: `viz-debugger/drone/RADAR_INTERFACE.md` 5 절. `rtcmStatus.ts` 와 같은 모양이다.
 */

import { useSyncExternalStore } from 'react';

export type RadarState = 'idle' | 'armed' | 'recording' | 'error';

export type RadarStatus = {
  deviceId: string;
  state: RadarState;
  recording: boolean;
  file: string | null;
  pulsesPerS: number | null;
  dropped: number | null;
  bufferPct: number | null;
  tempC: number | null;
  timeSource: 'pps' | 'ntp' | 'none' | null;
  ppsLocked: boolean | null;
  diskFreeGb: number | null;
  lastError: string | null;
  deviceTime: number | null;
};

export type RadarReport = RadarStatus & { receivedAtMs: number };

let reports: Readonly<Record<string, RadarReport>> = {};
const listeners = new Set<() => void>();

export function noteRadarStatus(status: RadarStatus, atMs = Date.now()): void {
  reports = { ...reports, [status.deviceId]: { ...status, receivedAtMs: atMs } };
  for (const listener of listeners) listener();
}

export function radarReports(): Readonly<Record<string, RadarReport>> {
  return reports;
}

/** 레이더가 1 초마다 내므로 5 초면 레이더 프로그램(또는 브로커 길)이 멎은 것이다. */
export const RADAR_REPORT_STALE_MS = 5_000;

export function isRadarReportStale(report: RadarReport, nowMs = Date.now()): boolean {
  return nowMs - report.receivedAtMs > RADAR_REPORT_STALE_MS;
}

/**
 * 한 줄 판정 — good · warn · bad. 놓친 펄스 · PRF 와 5 % 넘게 다른 펄스 수 · PPS 미동기 · 버퍼 80 % 이상은 주의, 오류 · 끊김은 나쁨.
 * `prfHz` 는 화면에서 고른 안테나 값(모르면 null — 그 검사만 빠진다).
 */
export function radarLevel(r: RadarReport, prfHz: number | null, nowMs = Date.now()): { level: 'good' | 'warn' | 'bad'; reasonKey: string | null } {
  if (isRadarReportStale(r, nowMs)) return { level: 'bad', reasonKey: 'radar.why.stale' };
  if (r.state === 'error') return { level: 'bad', reasonKey: 'radar.why.error' };
  if (r.dropped !== null && r.dropped > 0) return { level: 'warn', reasonKey: 'radar.why.dropped' };
  if (r.recording && prfHz !== null && r.pulsesPerS !== null && Math.abs(r.pulsesPerS - prfHz) > 0.05 * prfHz) return { level: 'warn', reasonKey: 'radar.why.prf' };
  if (r.bufferPct !== null && r.bufferPct >= 80) return { level: 'warn', reasonKey: 'radar.why.buffer' };
  if (r.timeSource !== null && r.timeSource !== 'pps') return { level: 'warn', reasonKey: 'radar.why.noPps' };
  if (r.ppsLocked === false) return { level: 'warn', reasonKey: 'radar.why.noPps' };
  return { level: 'good', reasonKey: null };
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useRadarReports(): Readonly<Record<string, RadarReport>> {
  return useSyncExternalStore(subscribe, radarReports, radarReports);
}

export function resetRadarStatus(): void {
  reports = {};
  for (const listener of listeners) listener();
}
