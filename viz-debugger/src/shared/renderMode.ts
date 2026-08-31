/**
 * src/shared/renderMode.ts
 *
 * 남이 줄 데이터를 **그릴지 말지**를 정하는 한 곳.
 *
 * 목 게이트웨이는 끄지 않는다 — 개발과 검증에 필요하고, `verify:one-gateway` 가
 * "데이터가 실제로 온다"를 검사한다. 게이트웨이는 여전히 발행하고 데이터 계층도 여전히 받는다.
 * **바뀌는 것은 그리는 층뿐이다.**
 *
 * ## 기본값은 자리표시다
 *
 * 앱을 그냥 띄우면 남의 데이터가 있어야 할 자리에 **무엇을 · 누구에게서 기다리는지**가 뜬다.
 * 진짜처럼 보이는 목이 시연에서 거짓말이 되는 것을 막고, 무엇이 아직 안 왔는지가
 * 화면에 드러나야 다음 회의에서 "이건 누가 언제 주느냐"를 물을 수 있기 때문이다.
 *
 * `verify:placeholder-default` 가 이 기본값을 검사한다. **여기를 `'mock'` 으로 바꾸면
 * 그 검사가 실패한다** — 바꾸려면 그 검사부터 봐야 한다.
 */

import { useSyncExternalStore } from 'react';

export type RenderMode = 'placeholder' | 'mock';

/** **기본값.** 이 한 줄이 "앱을 그냥 띄우면 자리표시"를 정한다. */
const DEFAULT_MODE: RenderMode = 'placeholder';

let mode: RenderMode = DEFAULT_MODE;
const listeners = new Set<() => void>();

export function getRenderMode(): RenderMode {
  return mode;
}

export function setRenderMode(next: RenderMode): void {
  if (mode === next) return;
  mode = next;
  for (const listener of listeners) listener();
}

export function toggleRenderMode(): void {
  setRenderMode(mode === 'placeholder' ? 'mock' : 'placeholder');
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useRenderMode(): RenderMode {
  return useSyncExternalStore(subscribe, getRenderMode, () => DEFAULT_MODE);
}

/**
 * 목 렌더 중인가.
 *
 * 참이면 화면 어딘가에 **지워지지 않는 목 배지**가 떠 있어야 한다. 토글을 켠 것을 잊고
 * 시연하면 원래 문제로 되돌아간다 — 배지를 끄는 경로는 만들지 않는다.
 */
export function useMockRender(): boolean {
  return useRenderMode() === 'mock';
}
