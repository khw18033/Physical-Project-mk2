/**
 * src/detect/scan/detectSourceSync.ts (261123 신설 — 스캔 탐지를 data_stream 으로 · S9)
 *
 * **탐지 방식 설정을 게이트웨이와 맞춘다.** 원천은 게이트웨이 프로세스의 `scenarios/detectSource.ts` 값이다
 * (`GET/POST /scan-detect-source`). 브라우저는 그 값을 받아 자기 쪽 같은 모듈에 넣는다 — 그래야 화면의 매칭(발화 패널)과
 * 게이트웨이의 매칭이 같은 편을 고른다.
 *
 * 게이트웨이가 없으면(단독 빌드) 브라우저 값 하나로 간다. **임무가 도는 중에는 바꾸지 못한다** — 판 도중 흐름이 바뀌면
 * 승인한 편과 도는 편이 다르다.
 */

import { useSyncExternalStore } from 'react';
import { GATEWAY } from '../../transport/index.ts';
import { robotSession } from '../../physical/robotSession.ts';
import {
  detectSource, isDetectSourceMode, setDetectSource, subscribeDetectSource, type DetectSourceMode,
} from '../../scenarios/detectSource.ts';

const PATH = '/scan-detect-source';

export type DetectSourceSyncState = {
  /** 게이트웨이와 맞췄는가. 아직 · 못 닿음이면 false — 브라우저 값만 쓰는 중이다. */
  synced: boolean;
  /** 마지막으로 바꾸려다 막힌 사유(사전 키). */
  blockedKey: string | null;
};

let syncState: DetectSourceSyncState = { synced: false, blockedKey: null };
const listeners = new Set<() => void>();
const notify = () => { for (const listener of listeners) listener(); };
const subscribeSync = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };

/** 게이트웨이 값을 받아 온다. 기동 때 한 번, 연결 판을 열 때 한 번. */
export async function pullDetectSource(): Promise<void> {
  try {
    const response = await fetch(GATEWAY.http + PATH, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(String(response.status));
    const body = await response.json() as { mode?: unknown };
    if (isDetectSourceMode(body.mode)) setDetectSource(body.mode);
    syncState = { ...syncState, synced: true };
  } catch {
    syncState = { ...syncState, synced: false };
  }
  notify();
}

/** 바꾼다. 임무가 도는 중이면 막는다. 게이트웨이가 받으면 그 값, 못 닿으면 브라우저 값만 바꾼다. */
export async function changeDetectSource(next: DetectSourceMode): Promise<boolean> {
  if (robotSession().started) {
    syncState = { ...syncState, blockedKey: 'sd.source.blockedRunning' };
    notify();
    return false;
  }
  try {
    const response = await fetch(GATEWAY.http + PATH, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ mode: next }),
    });
    if (!response.ok) throw new Error(String(response.status));
    const body = await response.json() as { mode?: unknown };
    setDetectSource(isDetectSourceMode(body.mode) ? body.mode : next);
    syncState = { synced: true, blockedKey: null };
  } catch {
    setDetectSource(next);
    syncState = { synced: false, blockedKey: null };
  }
  notify();
  return true;
}

export function useDetectSource(): DetectSourceMode {
  return useSyncExternalStore(subscribeDetectSource, detectSource, detectSource);
}

export function useDetectSourceSync(): DetectSourceSyncState {
  return useSyncExternalStore(subscribeSync, () => syncState, () => syncState);
}
