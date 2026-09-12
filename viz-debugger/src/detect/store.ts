/**
 * src/detect/store.ts (260912 신설)
 *
 * **탐지 한 판의 상태.** `physical/robotSession.ts` 와 같은 자리·같은 모양이다 —
 * 화면은 이걸 읽고 결과는 이리로 들어온다.
 *
 * 로봇과 탐지는 **다른 경로로 들어온다.** 로봇은 MQTT 로 밀어 주고 탐지는 우리가 HTTP 로
 * 받아 간다. 둘이 같은 여덟 칸을 채우므로 누가 무엇을 채우는지 갈라 둔다.
 *
 *   로봇   「회전이 지나갔다」   — `scan_turn`
 *   탐지   「거기 문이 있나」    — `found`
 */

import { useSyncExternalStore } from 'react';
import type { DetectFeatures, DetectFrame, DetectFrameEvidence, DetectPath } from './types.ts';

export type DetectState = {
  /** 연결 관리의 「테스트」가 켜져 있는가. 켜면 받아 둔 실제 산출물을 읽는다. */
  testMode: boolean;
  /** 각도별 결과. **한 각도 스캔이 끝날 때마다 늘어난다** (260912 확인). */
  frames: readonly DetectFrame[];
  /** 각도별 근거. 키는 `frame_000113.jpg`. 못 찾은 각도에는 없다. */
  evidence: Readonly<Record<string, DetectFrameEvidence>>;
  /** 경로 산출. 스캔이 끝나야 나온다 — 그 전에는 null 이고, 그것이 정상이다. */
  path: DetectPath | null;
  /** 무엇을 문이라고 물었나. */
  features: DetectFeatures | null;
  /** 마지막으로 읽어 온 시각(ms). 0 이면 아직 한 번도 안 읽었다. */
  fetchedAtMs: number;
  /** 못 읽었으면 왜. 조용히 비워 두지 않는다. */
  error: string | null;
};

const EMPTY: DetectState = {
  testMode: false,
  frames: [],
  evidence: {},
  path: null,
  features: null,
  fetchedAtMs: 0,
  error: null,
};

let state: DetectState = EMPTY;
const listeners = new Set<() => void>();

function commit(next: DetectState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function detectState(): DetectState {
  return state;
}

export function subscribeDetect(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useDetect(): DetectState {
  return useSyncExternalStore(subscribeDetect, detectState, detectState);
}

/** 「테스트」를 켜고 끈다. **끄면 읽어 둔 것도 같이 버린다** — 시료가 실제 결과로 보이면 안 된다. */
export function setTestMode(on: boolean): void {
  commit(on ? { ...state, testMode: true } : { ...EMPTY, testMode: false });
}

export function receiveFrames(frames: readonly DetectFrame[]): void {
  commit({ ...state, frames, fetchedAtMs: Date.now(), error: null });
}

export function receiveEvidence(frame: string, evidence: DetectFrameEvidence): void {
  commit({ ...state, evidence: { ...state.evidence, [frame]: evidence } });
}

export function receivePath(path: DetectPath | null): void {
  commit({ ...state, path });
}

export function receiveFeatures(features: DetectFeatures | null): void {
  commit({ ...state, features });
}

export function noteDetectError(reason: string): void {
  commit({ ...state, error: reason });
}

/**
 * 임무가 바뀌면 판을 비운다. **테스트 켬/끔은 남긴다** — 그것은 임무의 성질이 아니라
 * 사람이 설정한 것이고, 임무를 다시 올릴 때마다 꺼지면 매번 다시 켜야 한다.
 */
export function resetDetect(): void {
  commit({ ...EMPTY, testMode: state.testMode });
}
