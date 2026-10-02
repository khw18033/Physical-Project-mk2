/**
 * src/shared/imageStore.ts (260929 신설 — 연결 관리의 이미지 첨부 · SAR / 3D 복원 노드)
 *
 * **연결 관리에서 붙인 이미지를 이 브라우저 안(IndexedDB)에 둔다.**
 *
 * 연결 값은 `localStorage` 의 문자열 묶음(`viz.connections.v1`)이라 이미지를 담을 수 없다 — 한도가 약 5MB 이고,
 * 넘치면 주소까지 통째로 저장이 실패한다. 그래서 이미지는 따로 둔다(260929 결정 11-A — 서버를 고치지 않는다).
 * 대가는 **붙인 그 브라우저에서만 보인다**는 것이다. 다른 PC 에서는 다시 붙여야 한다.
 *
 * 키는 연결 칸 키와 같다(`sar.image` · `recon-3d.image`) — 연결 관리의 칸과 노드가 같은 이름으로 만난다.
 *
 * IndexedDB 가 없는 곳(검사 · 사생활 모드 일부)에서는 **메모리에만** 둔다. 던지지 않는다 — 여기서 던지면
 * 연결 관리 판 전체가 멈춘다.
 */

import { useSyncExternalStore } from 'react';

export type StoredImage = {
  /** 화면이 `<img src>` 로 쓰는 주소(`blob:`). */
  url: string;
  /** 사람이 붙인 파일 이름. 연결 관리가 그대로 적는다. */
  name: string;
  /** 붙인 시각(ms). */
  savedAtMs: number;
};

type Record_ = { blob: Blob; name: string; savedAtMs: number };

const DB_NAME = 'viz.images';
const STORE = 'images';

let cache: Readonly<Record<string, StoredImage>> = {};
const loaded = new Set<string>();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function setEntry(key: string, record: Record_ | null): void {
  const previous = cache[key];
  if (previous !== undefined && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(previous.url);
  const next = { ...cache };
  if (record === null) delete next[key];
  else next[key] = { url: URL.createObjectURL(record.blob), name: record.name, savedAtMs: record.savedAtMs };
  cache = next;
  notify();
}

function openDb(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === 'undefined') return Promise.resolve(null);
  return new Promise((resolve) => {
    try {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => { request.result.createObjectStore(STORE); };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

async function withStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T | null> {
  const db = await openDb();
  if (db === null) return null;
  return new Promise((resolve) => {
    try {
      const request = run(db.transaction(STORE, mode).objectStore(STORE));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

/** 이미지를 붙인다. 브라우저에 못 두면 이 창에서만 보인다 — `false` 를 돌려 화면이 그 사실을 적게 한다. */
export async function saveImage(key: string, file: Blob, name: string): Promise<boolean> {
  const record: Record_ = { blob: file, name, savedAtMs: Date.now() };
  setEntry(key, record);
  loaded.add(key);
  const stored = await withStore('readwrite', (store) => store.put(record, key));
  return stored !== null;
}

/** 붙인 이미지를 뗀다. */
export async function removeImage(key: string): Promise<void> {
  setEntry(key, null);
  loaded.add(key);
  await withStore('readwrite', (store) => store.delete(key));
}

/** 처음 묻는 키면 브라우저에서 읽어 온다. */
function load(key: string): void {
  if (loaded.has(key)) return;
  loaded.add(key);
  void withStore<Record_ | undefined>('readonly', (store) => store.get(key) as IDBRequest<Record_ | undefined>).then((record) => {
    if (record !== null && record !== undefined && cache[key] === undefined) setEntry(key, record);
  });
}

export function storedImage(key: string): StoredImage | null {
  load(key);
  return cache[key] ?? null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/**
 * 여러 칸을 한 번에 구독한다 (260929 — 3D 가상환경 영상 둘). 칸 수가 임무마다 달라도 훅 수는 하나다.
 */
export function useStoredImages(keys: readonly string[]): Readonly<Record<string, StoredImage | null>> {
  const snapshot = useSyncExternalStore(subscribe, () => cache, () => cache);
  const out: Record<string, StoredImage | null> = {};
  for (const key of keys) out[key] = snapshot[key] ?? storedImage(key);
  return out;
}

/** 그리는 쪽이 구독한다 — 연결 관리에서 붙이면 노드가 곧바로 바뀐다. */
export function useStoredImage(key: string): StoredImage | null {
  return useSyncExternalStore(subscribe, () => storedImage(key), () => storedImage(key));
}
