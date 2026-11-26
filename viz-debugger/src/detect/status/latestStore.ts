/**
 * src/detect/status/latestStore.ts (261124 신설 — 객체 탐지 상태판 · 지정 탐지 대상)
 *
 * **`targeted` 가 살아 있는 포트마다 Redis 마지막 한 건의 요약.** 개발 서버 창구 `/vision-stream/latest` 가 Redis 를 읽고
 * (`scripts/vision-redis-latest.mjs`) 대상 목록 · 프로필 판 · 마지막 장 라벨만 돌려준다.
 *
 * 2초마다 묻는다. 한 건에 오버레이 JPEG 가 같이 실려 창구 쪽에서는 수십~수백 KB 를 받으므로, 판이 붙잡은 포트
 * (= targeted 가 살아 있는 포트)만 묻는다. 창구가 없는 빌드(정적)면 실패 사유를 적고 화면은 「대상 목록 못 읽음」으로 내려간다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../../i18n/dict.ts';
import { redisLatestUrl, visionRedisUrl } from '../../vision/visionClient.ts';

export const LATEST_POLL_MS = 2000;

/** 창구 요약 그대로 (`summarizeVisionEntry`). */
export type RedisLatest = {
  id: string;
  atMs: number | null;
  model: string | null;
  stream: string | null;
  run: string | null;
  n: number | null;
  emittedAt: string | null;
  /** 이 장비가 찾는 대상 — `targets_device` 가 있으면 그것(빈 목록 = 찾는 대상 없음), 없으면 `targets` (261126). */
  targets: readonly string[] | null;
  /** 비전 프로세스 전체의 대상(`targets` 그대로) — 여러 장비를 맡으면 합친 목록이다. */
  targetsAll: readonly string[] | null;
  /** `targets` 가 어디서 왔나 — `device` 는 장비별 칸, `all` 은 프로세스 전체 칸(옛 판). */
  targetScope: 'device' | 'all' | null;
  /** 하한 측정 전 대상 — 장비별 대상이 있으면 그 안의 것만. */
  provisional: readonly string[] | null;
  distance: boolean | null;
  profile: { label: string | null; version: number | null; scanId: string | null } | null;
  labels: Readonly<Record<string, number>> | null;
  resultError: string | null;
};

export type LatestState = {
  latest: RedisLatest | null;
  /** 키는 있는데 항목이 없다(Redis 를 막 켰다 · 그 모델이 아직 한 장도 안 냈다). */
  empty: boolean;
  error: string | null;
  receivedAtMs: number | null;
};

type Fetcher = (url: string) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;

const EMPTY: LatestState = { latest: null, empty: false, error: null, receivedAtMs: null };
let states: Readonly<Record<string, LatestState>> = {};
const listeners = new Set<() => void>();
/** 키(`base|source|model`) → 붙잡은 수. */
const holds = new Map<string, number>();
const inFlight = new Set<string>();
let timer: ReturnType<typeof setInterval> | null = null;
let fetcher: Fetcher = (url) => globalThis.fetch(url);

const keyOf = (base: string, source: string, model: string) => `${base}|${source}|${model}`;

function commit(key: string, next: LatestState): void {
  states = { ...states, [key]: next };
  for (const listener of listeners) listener();
}

export function latestOf(base: string, source: string | null, model: string): LatestState {
  return source === null ? EMPTY : (states[keyOf(base, source, model)] ?? EMPTY);
}

export function useLatestStates(): Readonly<Record<string, LatestState>> {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    () => states, () => states,
  );
}

/** 한 번 묻는다. 검사가 직접 부른다. */
export async function pollLatest(base: string, source: string, model: string, nowMs: () => number = Date.now): Promise<void> {
  const key = keyOf(base, source, model);
  if (inFlight.has(key)) return;
  const redis = visionRedisUrl();
  const before = states[key] ?? EMPTY;
  if (redis === null) { commit(key, { ...before, error: t('dms.redisNoAddress') }); return; }
  inFlight.add(key);
  try {
    const response = await fetcher(redisLatestUrl(redis, source, model));
    let body: unknown = null;
    try { body = await response.json(); } catch { body = null; }
    if (!response.ok) {
      const why = body !== null && typeof body === 'object' && typeof (body as { error?: unknown }).error === 'string'
        ? (body as { error: string }).error : `HTTP ${response.status}`;
      commit(key, { ...before, error: why });
      return;
    }
    if (body !== null && typeof body === 'object' && (body as { empty?: unknown }).empty === true) {
      commit(key, { latest: null, empty: true, error: null, receivedAtMs: nowMs() });
      return;
    }
    if (body === null || typeof body !== 'object' || typeof (body as { id?: unknown }).id !== 'string') {
      commit(key, { ...before, error: t('dms.relayShape') });
      return;
    }
    commit(key, { latest: body as RedisLatest, empty: false, error: null, receivedAtMs: nowMs() });
  } catch (error) {
    commit(key, { ...before, error: error instanceof Error ? error.message : String(error) });
  } finally {
    inFlight.delete(key);
  }
}

function tick(): void {
  for (const [key, count] of holds) {
    if (count <= 0) continue;
    const [base, source, model] = key.split('|');
    void pollLatest(base, source, model);
  }
}

function ensureTimer(): void {
  const busy = [...holds.values()].some((count) => count > 0);
  if (busy && timer === null) { tick(); timer = setInterval(tick, LATEST_POLL_MS); }
  else if (!busy && timer !== null) { clearInterval(timer); timer = null; }
}

/** 이 포트의 모델 결과를 보는 동안 붙잡는다 — `useEffect` 의 정리 함수로 놓는다. */
export function holdLatest(base: string, source: string | null, model: string): () => void {
  if (source === null) return () => undefined;
  const key = keyOf(base, source, model);
  holds.set(key, (holds.get(key) ?? 0) + 1);
  ensureTimer();
  return () => {
    holds.set(key, Math.max(0, (holds.get(key) ?? 1) - 1));
    ensureTimer();
  };
}

/** 검사가 부른다. */
export function resetLatestStore(next?: Fetcher): void {
  states = {};
  holds.clear();
  inFlight.clear();
  if (timer !== null) { clearInterval(timer); timer = null; }
  if (next !== undefined) fetcher = next;
}
