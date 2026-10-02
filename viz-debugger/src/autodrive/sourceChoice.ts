/**
 * src/autodrive/sourceChoice.ts (260929 신설 — 장애물 탐지 주소 둘 이상)
 *
 * **탐지 영상 · 객체 탐지 로그 노드 한 장이 고른 주소.** 노드마다 따로다 — 같은 노드를 여러 장 놓고 확대에서
 * 각자 주소를 고른다(카메라 노드의 장치 고름과 같은 규칙 · `media/cameraChoice.ts`).
 *
 * 고르지 않았으면 `null` — 연결 관리 목록의 **첫 줄**을 본다. 고른 주소가 목록에서 빠지면 그 노드는
 * 「목록에 없는 주소」라고 적고 여전히 그 주소를 본다 — 말없이 첫 줄로 바꾸면 다른 로봇의 영상을 그 로봇
 * 것으로 읽는다.
 *
 * 캔버스 구성(`canvas/persist.ts`)에 넣지 않는 이유도 카메라 고름과 같다 — 칸 하나 때문에 판을 올리면
 * 사람이 짜 둔 배치가 전부 버려진다.
 */

import { useSyncExternalStore } from 'react';

const STORAGE_KEY = 'viz.obstacleSource.v1';

function read(): Record<string, string> {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, string> = {};
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'string' && value !== '') out[id] = value;
    }
    return out;
  } catch {
    // 저장소가 막혔거나 깨졌다 — 고르지 않은 것으로 진행한다. 여기서 던지면 캔버스가 멎는다.
    return {};
  }
}

let choices: Record<string, string> = read();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** 그 노드가 고른 주소. 고르지 않았으면 `null`(첫 줄). */
export function obstacleSource(nodeId: string): string | null {
  return choices[nodeId] ?? null;
}

export function useObstacleSource(nodeId: string): string | null {
  return useSyncExternalStore(subscribe, () => obstacleSource(nodeId), () => obstacleSource(nodeId));
}

/** `null` 이면 고름을 지운다(첫 줄로). */
export function setObstacleSource(nodeId: string, base: string | null): void {
  const next = { ...choices };
  if (base === null || base === '') delete next[nodeId];
  else next[nodeId] = base;
  choices = next;
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(choices));
  } catch {
    // 이번 세션에만 남는다. 카메라 고름과 같은 규칙이다.
  }
  for (const listener of listeners) listener();
}
