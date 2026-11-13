/**
 * src/record/controlView.ts (261113 신설)
 *
 * **지금 열어 본 조작 판.** 값 하나와 그 구독이다.
 *
 * 조작 판은 처음에 이력 목록 위에 뜨는 창(모달)이었다. 그러면 화면의 대부분인 그래프 자리가 놀고, 창은 그 위에서 좁다.
 * 이제 이력 목록(셸 판 · 리플레이 왼쪽 기둥)이 이 값을 세우고, 리플레이 화면이 **그래프 자리에** 조작 판을 그린다.
 * 닫으면 그래프가 그대로 돌아온다 — 다시보기 중이던 임무 판은 건드리지 않는다.
 */

import { useSyncExternalStore } from 'react';

export type ControlViewTarget = { date: string; run: string };

let current: ControlViewTarget | null = null;
const listeners = new Set<() => void>();

const read = () => current;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function openControlView(date: string, run: string): void {
  current = { date, run };
  for (const listener of listeners) listener();
}

export function closeControlView(): void {
  if (current === null) return;
  current = null;
  for (const listener of listeners) listener();
}

export function useControlView(): ControlViewTarget | null {
  return useSyncExternalStore(subscribe, read, read);
}
