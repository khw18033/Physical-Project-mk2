/**
 * src/vision/store.ts (261001 신설 — 객체 탐지 추론 스트림)
 *
 * **포트마다 마지막 `/health` 한 건.** 보는 화면이 있을 때만 묻는다 — 화면이 「붙잡는다」(`holdVisionSource`).
 * 하드웨어 카드는 장비 맞추기 때문에 포트 전부를 붙잡는다(`holdAllVisionSources`).
 *
 * 1초마다 묻는다. 한 건이 작고(1KB 안쪽) 포트가 넷이라 부담이 없다. 대답이 늦으면 다음 차례를 거른다 —
 * 같은 포트에 요청이 겹쳐 쌓이지 않게.
 *
 * 처리 속도(장/초)는 **서버가 센 결과 누계의 차이**로 잰다. 서버의 10초 보고와 같은 값을 화면에서도 보려는 것이다.
 */

import { useSyncExternalStore } from 'react';
import { fetchStreamHealth, visionBases, type FetchLike, type StreamHealth } from './visionClient.ts';

export const VISION_POLL_MS = 1000;

export type VisionSourceState = {
  health: StreamHealth | null;
  /** 마지막으로 받은 시각 (이 브라우저 시계). */
  receivedAtMs: number | null;
  error: string | null;
  via: 'relay' | 'direct' | null;
  /** 모델별 처리 속도(장/초). 두 번 받아야 생긴다. */
  rate: Readonly<Record<string, number>>;
};

const EMPTY: VisionSourceState = { health: null, receivedAtMs: null, error: null, via: null, rate: {} };

let sources: Readonly<Record<string, VisionSourceState>> = {};
const listeners = new Set<() => void>();
const holds = new Map<string, number>();
let allHolds = 0;
const inFlight = new Set<string>();
/** 속도를 재는 앞 값 — 포트 · 모델마다 (누계, 받은 시각). */
const previous = new Map<string, { results: number; atMs: number }>();
let timer: ReturnType<typeof setInterval> | null = null;
let fetcher: FetchLike | undefined;

function commit(base: string, next: VisionSourceState): void {
  sources = { ...sources, [base]: next };
  for (const listener of listeners) listener();
}

export function visionSources(): Readonly<Record<string, VisionSourceState>> {
  return sources;
}

export function visionSourceOf(base: string): VisionSourceState {
  return sources[base] ?? EMPTY;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useVisionSources(): Readonly<Record<string, VisionSourceState>> {
  return useSyncExternalStore(subscribe, visionSources, visionSources);
}

/** 지금 묻는 포트들. 붙잡힌 것 ∪ (전부를 붙잡았으면) 연결 관리 목록. */
function heldBases(): string[] {
  const out = new Set<string>();
  for (const [base, count] of holds) if (count > 0) out.add(base);
  if (allHolds > 0) for (const base of visionBases()) out.add(base);
  return [...out];
}

/** 한 포트를 한 번 묻는다. 검사가 직접 부른다. */
export async function pollVisionSource(base: string, nowMs: () => number = Date.now): Promise<void> {
  if (inFlight.has(base)) return;
  inFlight.add(base);
  try {
    const got = await fetchStreamHealth(base, fetcher);
    const before = visionSourceOf(base);
    if (!got.ok) {
      // 옛 값은 남긴다 — 다만 언제 받은 것인지(`receivedAtMs`)가 그대로라 화면이 「n초 전」으로 낡음을 적는다.
      commit(base, { ...before, error: got.reason });
      return;
    }
    const at = nowMs();
    const rate: Record<string, number> = {};
    for (const model of got.health.models) {
      const key = `${base}|${model.model}`;
      const prev = previous.get(key);
      if (model.results !== null) {
        if (prev !== undefined && at > prev.atMs && model.results >= prev.results) {
          rate[model.model] = ((model.results - prev.results) * 1000) / (at - prev.atMs);
        }
        previous.set(key, { results: model.results, atMs: at });
      }
    }
    commit(base, { health: got.health, receivedAtMs: at, error: null, via: got.via, rate });
  } finally {
    inFlight.delete(base);
  }
}

function tick(): void {
  for (const base of heldBases()) void pollVisionSource(base);
}

function ensureTimer(): void {
  const busy = allHolds > 0 || [...holds.values()].some((count) => count > 0);
  if (busy && timer === null) {
    tick();
    timer = setInterval(tick, VISION_POLL_MS);
  } else if (!busy && timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

/** 이 포트를 보는 동안 붙잡는다. 돌려준 함수로 놓는다 — `useEffect` 의 정리 함수로 쓴다. */
export function holdVisionSource(base: string | null): () => void {
  if (base === null || base === '') return () => undefined;
  holds.set(base, (holds.get(base) ?? 0) + 1);
  ensureTimer();
  return () => {
    holds.set(base, Math.max(0, (holds.get(base) ?? 1) - 1));
    ensureTimer();
  };
}

/** 연결 관리에 적힌 포트 전부를 붙잡는다 — 장비 맞추기가 쓴다. */
export function holdAllVisionSources(): () => void {
  allHolds += 1;
  ensureTimer();
  return () => {
    allHolds = Math.max(0, allHolds - 1);
    ensureTimer();
  };
}

/** 검사가 부른다 — 받은 값을 비우고 요청 함수를 갈아 끼운다. */
export function resetVisionStore(nextFetcher?: FetchLike): void {
  sources = {};
  previous.clear();
  inFlight.clear();
  holds.clear();
  allHolds = 0;
  if (timer !== null) { clearInterval(timer); timer = null; }
  fetcher = nextFetcher;
}
