/**
 * src/fixedcam/cameraState.ts (261111 신설 — 360 카메라 장비 상태)
 *
 * **고정 카메라가 이미지와 함께 보내는 장비 상태.** 스트림 서버의 `/frame` 은 JPEG 본문에 더해 헤더 둘을 싣는다
 * (261111 실측 · `cam360 :10001`).
 *
 *   X-Frame-N     그 장의 저장 번호
 *   X-Frame-Meta  그 장의 메타 JSON — camera_id · sequence_id · timestamp · width · height …
 *   X-State       장비 상태 JSON — gps{lat, lon, alt_m, fix_type, satellites, snr_max} · battery{level_pct, charging}
 *                 · temperature_c{battery, board, module} · camera_state · timestamp
 *
 * 서버가 `Access-Control-Expose-Headers` 로 셋을 열어 두었으므로 브라우저 `fetch` 가 읽는다. `<img>` 는 헤더를
 * 못 읽으므로 영상 칸과 따로 묻는다. 서버가 `HEAD` 를 안 받아(501) **GET 을 열고 헤더만 읽은 뒤 본문을 끊는다.**
 *
 * 값은 받은 그대로 적는다 — 없는 칸(`lat: null` 등)은 「—」이지 0 이 아니다.
 */

import { useSyncExternalStore } from 'react';
import { noteConnectedEntity } from '../shared/connectedDevices.ts';
import { fixedCameras, withNonce, type FixedCamera } from './fixedCamera.ts';

/** 상세 · 전체 장치 확인이 열려 있는 동안 묻는 주기. */
export const CAMERA_STATE_POLL_MS = 2000;
export const CAMERA_STATE_TIMEOUT_MS = 5000;
/** 이보다 오래 새 상태가 없으면 낡았다고 적는다. */
export const CAMERA_STATE_STALE_MS = 15_000;

export type CameraGps = {
  lat: number | null;
  lon: number | null;
  altM: number | null;
  fixType: number | null;
  satellites: number | null;
  snrMax: number | null;
};

export type CameraState = {
  /** 장비가 상태에 찍은 시각(문자열 그대로). */
  timestamp: string | null;
  sourceId: string | null;
  gps: CameraGps | null;
  batteryPct: number | null;
  charging: boolean | null;
  /** 부위 → °C. 서버가 준 이름 그대로(battery · board · module …). */
  temperatures: ReadonlyArray<readonly [string, number]>;
  cameraState: number | null;
  frameN: number | null;
  frameWidth: number | null;
  frameHeight: number | null;
  frameTimestamp: string | null;
  /** 이 브라우저 시계로 받은 시각. */
  receivedAtMs: number;
  raw: { state: unknown; frameMeta: unknown };
};

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const obj = (v: unknown): Record<string, unknown> | null =>
  (v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : null);

function parseJson(text: string | null): unknown {
  if (text === null || text === '') return null;
  try { return JSON.parse(text); } catch { return null; }
}

/** 헤더 셋 → 상태. `X-State` 가 없거나 JSON 이 아니면 null — 이 서버가 상태를 안 싣는 것이다. */
export function parseCameraHeaders(get: (name: string) => string | null, receivedAtMs: number): CameraState | null {
  const stateRaw = parseJson(get('X-State'));
  const state = obj(stateRaw);
  if (state === null) return null;
  const metaRaw = parseJson(get('X-Frame-Meta'));
  const meta = obj(metaRaw);
  const gpsRaw = obj(state.gps);
  const battery = obj(state.battery);
  const temps = obj(state.temperature_c);
  const frameN = Number.parseInt(get('X-Frame-N') ?? '', 10);
  return {
    timestamp: str(state.timestamp),
    sourceId: str(state.source_id),
    gps: gpsRaw === null ? null : {
      lat: num(gpsRaw.lat),
      lon: num(gpsRaw.lon),
      altM: num(gpsRaw.alt_m),
      fixType: num(gpsRaw.fix_type),
      satellites: num(gpsRaw.satellites),
      snrMax: num(gpsRaw.snr_max),
    },
    batteryPct: num(battery?.level_pct),
    charging: typeof battery?.charging === 'boolean' ? battery.charging : null,
    temperatures: temps === null ? [] : Object.entries(temps)
      .filter((entry): entry is [string, number] => num(entry[1]) !== null),
    cameraState: num(state.camera_state),
    frameN: Number.isFinite(frameN) ? frameN : null,
    frameWidth: num(meta?.width),
    frameHeight: num(meta?.height),
    frameTimestamp: str(meta?.timestamp),
    receivedAtMs,
    raw: { state: stateRaw, frameMeta: metaRaw },
  };
}

export type StateFetch = (url: string, init: { signal: AbortSignal }) => Promise<{
  ok: boolean;
  headers: { get(name: string): string | null };
}>;

/** 한 번 묻는다. 헤더만 읽고 본문은 끊는다 — 스트림 주소여도 헤더는 첫 줄에 온다. */
export async function fetchCameraState(
  url: string,
  fetcher: StateFetch = globalThis.fetch as unknown as StateFetch,
  timeoutMs = CAMERA_STATE_TIMEOUT_MS,
  nowMs: () => number = Date.now,
): Promise<CameraState | null> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const response = await fetcher(withNonce(url, nowMs()), { signal: abort.signal });
    if (!response.ok) return null;
    return parseCameraHeaders((name) => response.headers.get(name), nowMs());
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
    abort.abort();
  }
}

// ── 저장소 ──────────────────────────────────────────────────────────────────

let states: Readonly<Record<string, CameraState>> = {};
const listeners = new Set<() => void>();
const inFlight = new Set<string>();
const holds = new Map<string, number>();
let timer: ReturnType<typeof setInterval> | null = null;

function emit(): void {
  for (const listener of listeners) listener();
}

export function cameraStates(): Readonly<Record<string, CameraState>> {
  return states;
}

export function useCameraStates(): Readonly<Record<string, CameraState>> {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    cameraStates,
    cameraStates,
  );
}

export function useCameraState(entityId: string): CameraState | null {
  return useCameraStates()[entityId] ?? null;
}

export function isCameraStateStale(state: CameraState, nowMs = Date.now()): boolean {
  return nowMs - state.receivedAtMs > CAMERA_STATE_STALE_MS;
}

/** 카메라 하나를 묻는다. 받으면 연결 장비로도 적는다 — 상태가 왔다는 것은 그 주소가 답했다는 것이다. */
export async function pollCameraState(camera: FixedCamera, fetcher?: StateFetch): Promise<void> {
  const key = `${camera.entityId}|${camera.url}`;
  if (inFlight.has(key)) return;
  inFlight.add(key);
  try {
    const got = await fetchCameraState(camera.url, fetcher);
    if (got === null) return;
    // 그 사이 주소가 바뀌었으면 버린다 — 옛 주소의 값을 새 줄에 붙이지 않는다.
    if (fixedCameras().find((c) => c.entityId === camera.entityId)?.url !== camera.url) return;
    noteConnectedEntity(camera.entityId, 'camera');
    states = { ...states, [camera.entityId]: got };
    emit();
  } finally {
    inFlight.delete(key);
  }
}

function tick(): void {
  for (const camera of fixedCameras()) {
    if ((holds.get(camera.entityId) ?? 0) > 0) void pollCameraState(camera);
  }
}

function ensureTimer(): void {
  const busy = [...holds.values()].some((count) => count > 0);
  if (busy && timer === null) {
    tick();
    timer = setInterval(tick, CAMERA_STATE_POLL_MS);
  } else if (!busy && timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

/** 이 카메라를 보는 동안 자주(2초) 묻는다. 돌려준 함수로 놓는다 — `useEffect` 의 정리 함수로 쓴다. */
export function holdCameraState(entityId: string): () => void {
  holds.set(entityId, (holds.get(entityId) ?? 0) + 1);
  ensureTimer();
  return () => {
    holds.set(entityId, Math.max(0, (holds.get(entityId) ?? 1) - 1));
    ensureTimer();
  };
}

/** 검사가 부른다. */
export function resetCameraStates(): void {
  states = {};
  inFlight.clear();
  holds.clear();
  if (timer !== null) { clearInterval(timer); timer = null; }
  emit();
}
