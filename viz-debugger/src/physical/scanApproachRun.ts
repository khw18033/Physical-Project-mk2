/**
 * src/physical/scanApproachRun.ts (261123 신설 — 스캔 탐지를 data_stream 으로)
 *
 * **새 흐름의 노드 칠하기와 이동 계획 상태 · 「이동」.** `scanDetectLink.ts` 에서 떼어 냈다 — 노드 상세(`ScanDetectViews.tsx`)가
 * 이동 계획을 읽고 버튼을 누르는데, 연결 모듈을 통째로 끌어오면 @ 영어 옮기기(`generate/nameEn.ts` → `LlmClient.ts` → `contracts/`)까지
 * 딸려 와 화면 묶음(검사의 `src/` 사본 빌드 등)이 `src/` 밖을 찾는다. 여기는 그 고리를 모른다.
 */

import { useSyncExternalStore } from 'react';
import { receiveRobotProgress } from '../data/scenario.ts';
import type { ScenarioEvent, TaskStatus } from '../model/types.ts';
import { issueStepsToEnd } from './robotCommands.ts';
import { robotClient } from './robotClient.ts';
import { elapsedSec, markApproachIssued, robotSession } from './robotSession.ts';
import type { ScanApproachPlan } from './scanApproach.ts';

let seq = 6_000_000;

/** 노드 칠하기 — seq 6,000,000 대역(사람 1M · 생성 2M · 로봇 3M · 탐지 4M · 준비 5M 과 안 겹친다). 정지 뒤에는 실패만 칠한다. */
export function emitScanNode(missionId: string, nodeId: string, status: TaskStatus, payload?: Record<string, unknown>): void {
  const session = robotSession();
  if (session.stopped !== null && status !== 'failed') return;
  seq += 1;
  receiveRobotProgress(missionId, {
    seq, atSec: elapsedSec(), nodeId, status,
    kind: status === 'done' || status === 'failed' ? 'evaluated' : 'started',
    producedBy: 'backend',
    ...(payload === undefined ? {} : { payload }),
  } as ScenarioEvent);
}

// ── 이동 계획 (승인 대기 포함) ───────────────────────────────────────────

export type ScanApproachState = { scanId: string; missionId: string; plan: ScanApproachPlan; issued: boolean; waitingApproval: boolean } | null;
let approach: ScanApproachState = null;
const approachListeners = new Set<() => void>();
export function setScanApproach(next: ScanApproachState): void {
  approach = next;
  for (const listener of approachListeners) listener();
}
export function scanApproachState(): ScanApproachState { return approach; }
export function useScanApproach(): ScanApproachState {
  return useSyncExternalStore((l) => { approachListeners.add(l); return () => { approachListeners.delete(l); }; }, () => approach, () => approach);
}

/** 계획대로 이동 명령을 낸다. 승인 대기 중이면 사람이 이것을 누른다. */
export async function issueScanApproach(): Promise<boolean> {
  const current = approach;
  if (current === null || current.issued || !current.plan.ok) return false;
  if (robotSession().stopped !== null) return false;
  setScanApproach({ ...current, issued: true, waitingApproval: false });
  markApproachIssued();
  const outcome = await issueStepsToEnd(robotClient(), current.plan.steps);
  if (!outcome.sent) emitScanNode(current.missionId, 'T-B2', 'failed', { reason: outcome.reason ?? '' });
  return outcome.sent;
}

