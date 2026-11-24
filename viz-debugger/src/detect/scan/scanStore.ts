/**
 * src/detect/scan/scanStore.ts (261123 신설 — 스캔 탐지를 data_stream 으로 · S4)
 *
 * **스캔 한 판의 상태.** `scan_id` 하나에 준비 상태 · 각도별 수집 · 결과 · 실패를 든다. 실행기
 * (`physical/scanDetectRun.ts`)가 낸 사건을 받아 접고, 화면(각도 칸 · 근거 카드)이 구독한다.
 *
 * **다른 `scan_id` 의 사건은 버린다** — 옛 `detect/poll.ts` 의 지난 판 거르기와 같은 일이다. 정지 뒤 늦게 온 mark 응답이
 * 새 판의 각도 칸에 그림을 띄우면, 이번 판에 보지 않은 방향을 본 것처럼 보인다.
 */

import { useSyncExternalStore } from 'react';
import type { ScanMarkAnswer, ScanPrepareAnswer, ScanResult, ScanState, ScanStatusAnswer, ScanTarget } from './types.ts';

/** 각도 칸 하나. `captured` null = 아직 mark 전. */
export type ScanAngle = {
  index: number;
  deg: number;
  captured: boolean | null;
  frameN: number | null;
  capturedAt: string | null;
};

export type ScanStage = 'prepare' | 'heading' | 'turn' | 'mark' | 'finish' | 'result' | 'path';

export type ScanFailureInfo = { stage: ScanStage; code: string; detail: string };

export type ScanRunState = {
  scanId: string;
  missionId: string;
  device: string;
  base: string;
  target: ScanTarget;
  query: string | null;
  queryKo: string | null;
  /** data_stream 이 고른 `targeted` 대상(`demo_door` 등). */
  targets: string[];
  stream: string | null;
  serverState: ScanState | null;
  /** prepare 응답의 profile_version — 결과의 것과 다르면 판 도중 프로필이 바뀐 것이다. 모르면 null. */
  profileVersion: number | null;
  angles: ScanAngle[];
  /** 시작 · 끝 방위(장치가 주면). 회전 오차 보정에 쓴다. */
  headingStartDeg: number | null;
  headingEndDeg: number | null;
  result: ScanResult | null;
  failure: ScanFailureInfo | null;
  cancelled: boolean;
  /**
   * **임무 이력에서 연 판이면 그 기록 폴더** (261124). 그림을 data_stream 창구가 아니라 기록 폴더에서 읽는다 —
   * 창구는 끝난 판을 최근 몇 개만 들고, 다른 PC 에서는 닿지도 않는다. 지금 도는 판이면 null.
   */
  recorded: { date: string; run: string } | null;
};

export type ScanEvent =
  | { kind: 'begin'; scanId: string; missionId: string; device: string; base: string; target: ScanTarget; query: string | null; queryKo: string | null; steps: number; stepDeg: number }
  | { kind: 'prepare'; scanId: string; answer: ScanPrepareAnswer }
  | { kind: 'status'; scanId: string; answer: ScanStatusAnswer }
  | { kind: 'heading'; scanId: string; which: 'start' | 'end'; deg: number | null }
  | { kind: 'mark'; scanId: string; index: number; answer: ScanMarkAnswer | null }
  | { kind: 'result'; scanId: string; result: ScanResult }
  | { kind: 'fail'; scanId: string; failure: ScanFailureInfo }
  | { kind: 'cancel'; scanId: string };

let current: ScanRunState | null = null;
const listeners = new Set<() => void>();

function publish(next: ScanRunState | null): void {
  current = next;
  for (const listener of listeners) listener();
}

/** 사건 하나를 접는다 — **순수 함수**라 검사가 그대로 부른다. 다른 판의 사건이면 그대로 돌려준다. */
export function reduceScan(state: ScanRunState | null, event: ScanEvent): ScanRunState | null {
  if (event.kind === 'begin') {
    return {
      scanId: event.scanId, missionId: event.missionId, device: event.device, base: event.base, target: event.target,
      query: event.query, queryKo: event.queryKo, targets: [], stream: null, serverState: null, profileVersion: null,
      angles: Array.from({ length: event.steps }, (_, index) => ({ index, deg: index * event.stepDeg, captured: null, frameN: null, capturedAt: null })),
      headingStartDeg: null, headingEndDeg: null, result: null, failure: null, cancelled: false, recorded: null,
    };
  }
  if (state === null || state.scanId !== event.scanId) return state;
  switch (event.kind) {
    case 'prepare':
      return { ...state, serverState: event.answer.state, targets: event.answer.targets, stream: event.answer.stream, profileVersion: event.answer.profile_version ?? state.profileVersion };
    case 'status':
      return { ...state, serverState: event.answer.state, profileVersion: event.answer.profile_version ?? state.profileVersion };
    case 'heading':
      return event.which === 'start' ? { ...state, headingStartDeg: event.deg } : { ...state, headingEndDeg: event.deg };
    case 'mark': {
      const angles = state.angles.map((angle) => (angle.index !== event.index ? angle : {
        ...angle,
        captured: event.answer?.frame_captured ?? false,
        frameN: event.answer?.frame_n ?? null,
        capturedAt: event.answer?.captured_at ?? null,
      }));
      return { ...state, angles, serverState: state.serverState === 'ready' ? 'collecting' : state.serverState };
    }
    case 'result':
      return { ...state, result: event.result, serverState: event.result.state };
    case 'fail':
      return state.failure !== null ? state : { ...state, failure: event.failure };
    case 'cancel':
      return { ...state, cancelled: true, serverState: 'cancelled' };
  }
}

export function applyScanEvent(event: ScanEvent): void {
  const next = reduceScan(current, event);
  if (next !== current) publish(next);
}

export function scanRunState(): ScanRunState | null {
  return current;
}

/** 임무 이력에 싣는 모양 — 지금 상태 그대로(기록 폴더 표시는 뺀다). */
export function recordableScanRun(): ScanRunState | null {
  return current === null ? null : { ...current, recorded: null };
}

/**
 * 임무 이력에서 판을 열 때 되살린다. 모양이 틀리거나 없으면(옛 편 · 스캔 전 기록) 비운다 — 지금 판의 상태가
 * 지난 판 자리에 남으면 안 된다.
 */
export function restoreScanRun(saved: unknown, recorded: { date: string; run: string }): void {
  const ok = saved !== null && typeof saved === 'object'
    && typeof (saved as ScanRunState).scanId === 'string' && typeof (saved as ScanRunState).missionId === 'string'
    && Array.isArray((saved as ScanRunState).angles);
  publish(ok ? { ...(saved as ScanRunState), recorded } : null);
}

export function resetScanRun(): void {
  publish(null);
}

export function subscribeScanRun(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useScanRun(): ScanRunState | null {
  return useSyncExternalStore(subscribeScanRun, scanRunState, scanRunState);
}

/** 그 각도의 결과 줄 — 결과가 오기 전이면 null. */
export function frameResultAt(state: ScanRunState, deg: number) {
  return state.result?.frames.find((frame) => frame.rotation_deg === deg) ?? null;
}
