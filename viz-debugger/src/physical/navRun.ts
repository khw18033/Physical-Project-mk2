/**
 * src/physical/navRun.ts (260915 신설 — 자율주행 편 · pi1 중계)
 *
 * **지금 중계를 받아 칠할 판 하나.** 노드를 칠하는 쪽(`navLink.ts`)은 이것만 본다.
 *
 * 따로 떼어 둔 이유는 import 방향 하나다 — 저장소(`data/scenario.ts`)·로봇 세션(`robotSession.ts`)이
 * 열고 닫는데 칠하는 쪽은 저장소를 불러야 한다. 한 파일에 두면 서로를 부른다. 그래서 이 파일은
 * **react 말고는 아무것도 import 하지 않는다.**
 *
 * ## 승인과 시작은 다르다 (260915 지시 — 「승인을 누르자마자 노드에 불이 켜진다」)
 *
 *   승인        `armNavRun`   — 판을 **걸어만** 둔다. 노드는 아직 대기다
 *   ▶ 임무 시작 `startArmedNavRun` — 판이 열리고 이 순간이 0초다. 이때부터 받은 것을 칠한다
 *   정지 해제 · 초기화 · 새 임무   `endNavRun` — 걸어 둔 것까지 내린다. 다시 승인해야 한다
 *
 * 문 찾기 시연 편과 같은 순서다. 다른 점은 화면이 로봇에 아무것도 안 보낸다는 것뿐이다(로봇은 유니티가 몬다).
 */

import { useSyncExternalStore } from 'react';

export type NavRun = {
  missionId: string;
  /** 판을 연 시각(이 노트북 시계, ms). 사건 시각의 0초이자 신선도의 기준이다. */
  startedAtMs: number;
  /** 판마다 늘어난다 — 같은 임무를 다시 올려도 새 판으로 읽힌다. */
  serial: number;
};

export type NavRunState = {
  /** 승인됐고 시작을 기다리는 임무. 없으면 null. 판이 열려도 그대로 둔다(같은 임무다). */
  armed: string | null;
  run: NavRun | null;
};

let state: NavRunState = { armed: null, run: null };
let serial = 0;
const listeners = new Set<() => void>();

function commit(next: NavRunState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function navRun(): NavRun | null {
  return state.run;
}

export function navRunState(): NavRunState {
  return state;
}

/** 승인 — 판을 걸어 둔다. 지난 판이 열려 있었으면 닫는다(새 승인은 새 판이다). */
export function armNavRun(missionId: string): void {
  commit({ armed: missionId, run: null });
}

/** 판을 연다. 검사와 `startArmedNavRun` 이 부른다. */
export function beginNavRun(missionId: string, nowMs = Date.now()): void {
  serial += 1;
  commit({ armed: missionId, run: { missionId, startedAtMs: nowMs, serial } });
}

/**
 * **「▶ 임무 시작」.** 걸어 둔 임무가 있고 아직 안 열렸을 때만 연다. 열었으면 true.
 * 승인 없이 시작은 없다 — 걸어 둔 것이 없으면 아무 일도 안 한다.
 */
export function startArmedNavRun(nowMs = Date.now()): boolean {
  if (state.armed === null || state.run !== null) return false;
  beginNavRun(state.armed, nowMs);
  return true;
}

/** 걸어 둔 것까지 내린다. */
export function endNavRun(): void {
  if (state.armed === null && state.run === null) return;
  commit({ armed: null, run: null });
}

export function subscribeNavRun(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 머리줄 버튼이 읽는 자리. */
export function useNavRunState(): NavRunState {
  return useSyncExternalStore(subscribeNavRun, navRunState, navRunState);
}
