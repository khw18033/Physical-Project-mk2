/**
 * src/shared/fcxStatus.ts (261002 신설 — 드론 파트 · 드론 상태판)
 *
 * **FC 확장 텔레메트리(fc_watch)의 마지막 보고와 짧은 이력.** 받는 쪽(`physical/fcxFeed.ts`)이 밀어 넣고
 * 그리는 쪽(`src/dronedash/`)은 여기만 읽는다. 이력은 그래프와 궤적용이고 장비마다 최근 3분(5 Hz × 900)만 둔다.
 */

import { useSyncExternalStore } from 'react';

export type FcxSensor = { name: string; enabled: boolean; healthy: boolean };
export type FcxConsoleLine = { t: number; severity: string; level: number; text: string };

export type Fcx = {
  deviceId: string;
  link: { heartbeatAgeS: number | null; msgsPerS: number | null; fcSysid: number | null };
  armed: boolean | null;
  mode: string | null;
  landedState: string | null;
  attitude: { rollDeg: number | null; pitchDeg: number | null; yawDeg: number | null } | null;
  hud: { groundspeed: number | null; airspeed: number | null; climb: number | null; heading: number | null; throttle: number | null } | null;
  position: { lat: number | null; lon: number | null; altRelM: number | null; altMslM: number | null; vn: number | null; ve: number | null; vd: number | null } | null;
  home: { lat: number | null; lon: number | null; altMslM: number | null } | null;
  gps: { fixType: number | null; fix: string | null; satellites: number | null; hdop: number | null; vdop: number | null; hAccM: number | null; vAccM: number | null } | null;
  rtk: { baselineM: number | null; accuracyMm: number | null; iarHypotheses: number | null; rtkRate: number | null; nsats: number | null } | null;
  battery: { voltageV: number | null; currentA: number | null; remainingPct: number | null; cellsV: readonly number[]; temperatureC: number | null; consumedMah: number | null } | null;
  sensors: readonly FcxSensor[] | null;
  loadPct: number | null;
  dropRatePct: number | null;
  ekf: { vel: number | null; pos: number | null; ver: number | null; mag: number | null; ter: number | null; gpsGlitch: boolean; accelError: boolean } | null;
  vibration: { x: number | null; y: number | null; z: number | null; clipping: readonly number[] } | null;
  rc: { rssi: number | null; channels: number | null } | null;
  clockOffsetS: number | null;
  console: readonly FcxConsoleLine[];
  deviceTime: number | null;
};

/** 이력 한 점 — 그래프 · 궤적이 쓴다. 받은 시각(ms)이 x 다. */
export type FcxSample = {
  atMs: number;
  altRelM: number | null;
  groundspeed: number | null;
  climb: number | null;
  voltageV: number | null;
  lat: number | null;
  lon: number | null;
};

export type FcxReport = Fcx & { receivedAtMs: number; history: readonly FcxSample[] };

const HISTORY = 900;

let reports: Readonly<Record<string, FcxReport>> = {};
const listeners = new Set<() => void>();

export function noteFcx(fcx: Fcx, atMs = Date.now()): void {
  const previous = reports[fcx.deviceId]?.history ?? [];
  const sample: FcxSample = {
    atMs,
    altRelM: fcx.position?.altRelM ?? null,
    groundspeed: fcx.hud?.groundspeed ?? null,
    climb: fcx.hud?.climb ?? null,
    voltageV: fcx.battery?.voltageV ?? null,
    lat: fcx.position?.lat ?? null,
    lon: fcx.position?.lon ?? null,
  };
  const history = previous.length >= HISTORY ? [...previous.slice(previous.length - HISTORY + 1), sample] : [...previous, sample];
  reports = { ...reports, [fcx.deviceId]: { ...fcx, receivedAtMs: atMs, history } };
  for (const listener of listeners) listener();
}

export function fcxReports(): Readonly<Record<string, FcxReport>> {
  return reports;
}

/** 수집기는 5 Hz 로 낸다. 3초면 수집기(또는 브로커 길)가 멎은 것이다. */
export const FCX_STALE_MS = 3_000;

export function isFcxStale(report: FcxReport, nowMs = Date.now()): boolean {
  return nowMs - report.receivedAtMs > FCX_STALE_MS;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useFcxReports(): Readonly<Record<string, FcxReport>> {
  return useSyncExternalStore(subscribe, fcxReports, fcxReports);
}

export function resetFcx(): void {
  reports = {};
  for (const listener of listeners) listener();
}
