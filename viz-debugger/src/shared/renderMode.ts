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

/**
 * 셋째 모드 `scenario` (260831 — 대본 재생).
 * **기본값은 여전히 `placeholder` 다.** scenario 는 토글이 아니라 대본이 **승인된 뒤에만**
 * 자동으로 들어가고, 「대본 닫기」로만 나온다. 목 렌더 토글이 켜져 있으면 `mock` 이 이긴다
 * (전부 그린다 — 붉은 띠가 대본 띠 위에 겹친다).
 */
export type RenderMode = 'placeholder' | 'mock' | 'scenario';

/** **기본값.** 이 한 줄이 "앱을 그냥 띄우면 자리표시"를 정한다. */
const DEFAULT_MODE: RenderMode = 'placeholder';

let mode: RenderMode = DEFAULT_MODE;
const listeners = new Set<() => void>();

/** 재생 중(또는 재생 끝·닫기 전)인 대본. cast 밖 장비는 이 모드에서도 자리표시다. */
export type ScenarioRender = {
  missionId: string;
  title: string;
  cast: readonly string[];
  castSet: ReadonlySet<string>;
};

let scenarioRender: ScenarioRender | null = null;

export function getRenderMode(): RenderMode {
  if (mode === 'mock') return 'mock'; // 목 렌더 토글이 이긴다 — 전부 그린다.
  if (scenarioRender !== null) return 'scenario';
  return mode;
}

export function setRenderMode(next: RenderMode): void {
  if (mode === next) return;
  mode = next;
  for (const listener of listeners) listener();
}

export function toggleRenderMode(): void {
  setRenderMode(mode === 'mock' ? 'placeholder' : 'mock');
}

/**
 * 대본 승인 → scenario 모드 진입 (자동). 통합 셸의 임무 브리지가 부른다.
 * 구판 세계(legacy) 대본은 들어오지 않는다 — 탭②~⑤에 따라 움직일 것이 없다.
 */
export function enterScenarioRender(info: { missionId: string; title: string; cast: readonly string[] }): void {
  scenarioRender = { missionId: info.missionId, title: info.title, cast: [...info.cast], castSet: new Set(info.cast) };
  for (const listener of listeners) listener();
}

/** 「대본 닫기」 — placeholder 복귀. 끄는 경로는 이것 하나다. */
export function exitScenarioRender(): void {
  if (scenarioRender === null) return;
  scenarioRender = null;
  for (const listener of listeners) listener();
}

export function getScenarioRender(): ScenarioRender | null {
  return scenarioRender;
}

/** 대본 띠(셸)와 자리표시 분기(PendingSource)가 읽는 훅. */
export function useScenarioRender(): ScenarioRender | null {
  return useSyncExternalStore(subscribe, getScenarioRender, () => null);
}

/**
 * 「이 장비를 지금 그려도 되는가」의 판단 훅 (지시서 §탭②~⑤ — 자리 ID뿐 아니라 장비 ID).
 * scenario 모드에서만 cast 집합을 돌려준다. 목 렌더가 켜져 있으면 null — 목이 이긴다
 * (그때는 PendingSource 가 전부 그린다). 대본에 안 나오는 장비는 대본 중에도 자리표시다.
 */
export function useScenarioCast(): ReadonlySet<string> | null {
  const scenario = useScenarioRender();
  const effective = useRenderMode();
  return effective === 'scenario' && scenario !== null ? scenario.castSet : null;
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
