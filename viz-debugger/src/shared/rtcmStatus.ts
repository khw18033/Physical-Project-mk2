/**
 * src/shared/rtcmStatus.ts (261002 신설 — 드론 파트 · RTK 보정 전달)
 *
 * **보정 전달기의 마지막 보고.** 받는 쪽(`physical/PhysicalClient.ts` → `rtcmFeed.ts`)이 밀어 넣고 그리는 쪽
 * (`src/sar/RtkView.tsx`)은 여기만 읽는다. `sarStatus.ts` 와 같은 모양이다.
 */

import { useSyncExternalStore } from 'react';

export type RtcmStatus = {
  deviceId: string;
  /** 전달기가 「최근 3초 안에 보정을 받았다」고 판단했는가. */
  receiving: boolean;
  /** 마지막 보정 이후 경과(초). null 은 한 번도 못 받았다. */
  ageS: number | null;
  framesPerS: number | null;
  rateBps: number | null;
  frames: number | null;
  /** 받은 RTCM 메시지 번호들 (1005 · 1077 · 1087 …). */
  types: readonly string[];
  /** 1005/1006 이 알려 준 베이스 위치. 아직 못 받았으면 null. */
  base: { stationId: number | null; lat: number | null; lon: number | null; altM: number | null } | null;
  /** 보정을 보내 온 노트북 주소. */
  sender: string | null;
  injectedMessages: number | null;
  badCrc: number | null;
  timestamp: string | null;
};

export type RtcmReport = RtcmStatus & { receivedAtMs: number };

let reports: Readonly<Record<string, RtcmReport>> = {};
const listeners = new Set<() => void>();

export function noteRtcmStatus(status: RtcmStatus, atMs = Date.now()): void {
  reports = { ...reports, [status.deviceId]: { ...status, receivedAtMs: atMs } };
  for (const listener of listeners) listener();
}

export function rtcmReports(): Readonly<Record<string, RtcmReport>> {
  return reports;
}

/** 전달기 자체의 보고가 끊긴 것 — 전달기가 1초마다 내므로 5초면 전달기(또는 브로커 길)가 멎은 것이다. */
export const RTCM_REPORT_STALE_MS = 5_000;

export function isRtcmReportStale(report: RtcmReport, nowMs = Date.now()): boolean {
  return nowMs - report.receivedAtMs > RTCM_REPORT_STALE_MS;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useRtcmReports(): Readonly<Record<string, RtcmReport>> {
  return useSyncExternalStore(subscribe, rtcmReports, rtcmReports);
}

export function resetRtcmStatus(): void {
  reports = {};
  for (const listener of listeners) listener();
}
