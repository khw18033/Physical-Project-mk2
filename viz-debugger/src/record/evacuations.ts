/**
 * src/record/evacuations.ts (261119 신설 — 임무 이력 서버 2차)
 *
 * **서버 대신 이 PC 에 쓴 판(대피 판)의 목록.** 서버 주소를 넣어 둔 채로 이 PC 파일에 쓴 판은 전부 여기 적힌다
 * — 서버가 끊겼거나 불안정해서 대피한 판이다. `historyUpload.ts` 가 서버가 안정되면 통째로 올리고 지운다.
 *
 * - `localStorage` 에 둔다. 새로고침해도 남아야 올리기가 이어진다.
 * - 판마다 **마지막으로 이 PC 에 쓴 시각**을 든다. 올리는 사이에 또 쓰였으면(끝난 판에 그림이 늦게 오는 등)
 *   지우지 않고 다음에 다시 올린다.
 * - 서버 주소가 없을 때 쓴 판은 적지 않는다. 그것은 대피가 아니라 원래 이 PC 기록이다(올리려면 `history:push`).
 */

import { useSyncExternalStore } from 'react';
import { historyApiBase, historyServerStatus } from './historyServer.ts';

const STORAGE_KEY = 'viz.historyServer.evacuated.v1';

export type EvacuatedRun = {
  date: string;
  run: string;
  /** 처음 대피한 까닭 (서버 상태 · 실패 사유). */
  reason: string;
  firstAtIso: string;
  /** 마지막으로 이 PC 에 쓴 때. */
  dirtyAtMs: number;
  /** 서버가 거절했다 — 다시 쓰이기 전까지는 다시 안 올린다. */
  rejected: string | null;
};

let list: readonly EvacuatedRun[] = read();
const listeners = new Set<() => void>();

function read(): EvacuatedRun[] {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) as unknown : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is EvacuatedRun => typeof x?.date === 'string' && typeof x?.run === 'string') : [];
  } catch {
    return [];
  }
}

function save(next: readonly EvacuatedRun[]): void {
  list = next;
  try { globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(next)); } catch { /* 이 탭에서만 */ }
  for (const listener of listeners) listener();
}

export function evacuatedRuns(): readonly EvacuatedRun[] {
  return list;
}

export function subscribeEvacuated(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useEvacuatedRuns(): readonly EvacuatedRun[] {
  return useSyncExternalStore(subscribeEvacuated, evacuatedRuns, evacuatedRuns);
}

/** 이 PC 에 썼다 (`recordClient` 가 이 PC 쓰기가 될 때마다 부른다). 서버 주소가 있을 때만 대피로 적는다. */
export function noteLocalRecordWrite(date: string, run: string): void {
  if (historyApiBase() === null) return;
  const now = Date.now();
  const at = list.findIndex((item) => item.date === date && item.run === run);
  if (at >= 0) {
    const next = [...list];
    next[at] = { ...next[at], dirtyAtMs: now, rejected: null };
    save(next);
    return;
  }
  const server = historyServerStatus();
  save([...list, {
    date, run, firstAtIso: new Date(now).toISOString(), dirtyAtMs: now, rejected: null,
    reason: server.detail ?? server.state,
  }]);
}

/** 다 올렸다. 올리기를 시작한 뒤로 또 쓰였으면 남긴다. */
export function clearEvacuated(date: string, run: string, uploadStartedAtMs: number): void {
  const item = list.find((x) => x.date === date && x.run === run);
  if (item === undefined || item.dirtyAtMs > uploadStartedAtMs) return;
  save(list.filter((x) => x !== item));
}

export function markEvacuatedRejected(date: string, run: string, reason: string): void {
  save(list.map((x) => (x.date === date && x.run === run ? { ...x, rejected: reason } : x)));
}

// ── 아직 쓰고 있는 판 — 올리지 않는다 ─────────────────────────────────────────

const activeSources = new Set<() => readonly string[]>();

/** 기록기가 「지금 쓰고 있는 판」을 알려 줄 함수를 건다. `날짜/판` 꼴. */
export function registerActiveRecordFolders(source: () => readonly string[]): () => void {
  activeSources.add(source);
  return () => activeSources.delete(source);
}

export function activeRecordFolders(): ReadonlySet<string> {
  const all = new Set<string>();
  for (const source of activeSources) for (const key of source()) all.add(key);
  return all;
}

/** 검사용. */
export function resetEvacuatedForTest(): void {
  list = read();
  for (const listener of listeners) listener();
}
