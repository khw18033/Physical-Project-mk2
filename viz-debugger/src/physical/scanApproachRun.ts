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
import { missionClient } from './robotClient.ts';
import { elapsedSec, markApproachIssued, robotSession } from './robotSession.ts';
import { t } from '../i18n/dict.ts';
import { planScanApproach, type ScanApproachPlan, type ScanPlanInput } from './scanApproach.ts';

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

export type ScanApproachState = {
  scanId: string;
  missionId: string;
  plan: ScanApproachPlan;
  /** 계획을 다시 셀 재료 — 정지 거리를 바꾸면 이것으로 다시 센다. */
  input: ScanPlanInput;
  issued: boolean;
  waitingApproval: boolean;
} | null;
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

// ── 정지 거리 (261124 — 실물 Go1 시험) ─────────────────────────────────────
//
// 대상 앞 몇 m 에서 설지. 편의 `params.stop_distance_max_m` 이 기본이고(새 편 셋은 0.2 m), 「이동 경로 산출」(T-B1) 상세에서
// 사람이 바꿀 수 있다. 바꾼 값은 **그 편에 이 화면이 켜져 있는 동안** 남는다 — 다음 판도 그 값으로 센다.
// 0.9 m 였을 때 실물 시험에서 탐지를 해도 대상 가까이 가지 못했다(261124).

/** 편이 값을 안 줄 때의 정지 거리(m). */
export const SCAN_STOP_DEFAULT_M = 0.2;
/** 사람이 고를 수 있는 범위(m). */
export const SCAN_STOP_RANGE = { min: 0, max: 3 } as const;

const stopEdits = new Map<string, number>();
const stopListeners = new Set<() => void>();
let stopVersion = 0;

/** 그 편의 정지 거리 — 사람이 바꾼 값 > 편의 값 > 기본. */
export function scanStopDistance(missionId: string, fromParams: unknown): number {
  const edited = stopEdits.get(missionId);
  if (edited !== undefined) return edited;
  const param = Number(fromParams);
  return fromParams !== undefined && fromParams !== null && Number.isFinite(param) ? param : SCAN_STOP_DEFAULT_M;
}
export function scanStopEdited(missionId: string): boolean { return stopEdits.has(missionId); }
export function useScanStopVersion(): number {
  return useSyncExternalStore((l) => { stopListeners.add(l); return () => { stopListeners.delete(l); }; }, () => stopVersion, () => stopVersion);
}

/** T-B1 노드에 싣는 값 — 처음 셀 때와 다시 셀 때 같은 모양이다. */
export function scanPlanPayload(plan: ScanApproachPlan, stopDistanceM: number, edited: boolean): Record<string, unknown> {
  const stop = { stop_distance_m: stopDistanceM, ...(edited ? { stop_distance_edited: true } : {}) };
  if (!plan.ok) return { reason: t(plan.reason.key, plan.reason.vars), ...stop };
  return {
    turn_deg: plan.turnDeg, forward_m: plan.issuedForwardM, drift_deg: plan.driftDeg, bearing_deg: plan.bearingDeg,
    notes: plan.notes.map((note) => t(note.key, note.vars)), ...(plan.confirm === null ? {} : { confirm: plan.confirm }), ...stop,
  };
}

// ── 찾을 이름 다시 받기 (261124 — data_stream 요청 C · 400 bad_query) ─────────────────
//
// data_stream 이 찾을 이름을 못 받으면(번역이 깨졌거나 모르는 낱말) 판은 준비에서 선다. 사람이 영어 이름을 적어 다시 준비한다.
// 판을 다시 여는 것은 연결 모듈(`scanDetectLink.ts`)이 한다 — 화면은 그 모듈을 끌어오지 않고 여기 걸린 함수를 부른다(파일 머리 이유).

export type ScanQueryRetry = (query: string) => { ok: true } | { ok: false; reason: string };
let queryRetry: ScanQueryRetry | null = null;
export function setScanQueryRetry(next: ScanQueryRetry | null): void { queryRetry = next; }
export function retryScanQuery(query: string): { ok: true } | { ok: false; reason: string } {
  return queryRetry === null ? { ok: false, reason: t('sd.query.noRetry') } : queryRetry(query);
}

/**
 * 정지 거리를 바꾼다. 아직 이동이 안 나간 계획이 있으면 **그 자리에서 다시 세고**, 다시 센 계획은 사람이 「이 경로로 이동」을
 * 눌러야 출발한다(승인 설정과 상관없이) — 화면에서 손댄 경로가 저절로 나가지 않게. 이미 나갔으면 다음 판부터 쓴다.
 * 범위 밖이거나 숫자가 아니면 false.
 */
export function setScanStopDistance(missionId: string, meters: number): boolean {
  if (!Number.isFinite(meters) || meters < SCAN_STOP_RANGE.min || meters > SCAN_STOP_RANGE.max) return false;
  stopEdits.set(missionId, meters);
  stopVersion += 1;
  for (const listener of stopListeners) listener();
  const current = approach;
  if (current === null || current.issued || current.missionId !== missionId) return true;
  const input = { ...current.input, stopDistanceM: meters };
  const plan = planScanApproach(input);
  setScanApproach({ ...current, plan, input, waitingApproval: plan.ok });
  emitScanNode(missionId, 'T-B1', plan.ok ? 'done' : 'failed', scanPlanPayload(plan, meters, true));
  return true;
}

/** 임무 이력에 싣는 모양 (261124). */
export function recordableScanApproach(): Omit<NonNullable<ScanApproachState>, 'waitingApproval'> | null {
  if (approach === null) return null;
  const { waitingApproval: _waiting, ...rest } = approach;
  return rest;
}

/** 임무 이력에서 되살린다 — 다시보기에서는 누를 것이 없다(승인 대기 끔). 모양이 틀리면 비운다. */
export function restoreScanApproach(saved: unknown): void {
  const ok = saved !== null && typeof saved === 'object'
    && typeof (saved as { missionId?: unknown }).missionId === 'string'
    && typeof (saved as { plan?: { ok?: unknown } }).plan?.ok === 'boolean'
    && typeof (saved as { input?: unknown }).input === 'object';
  setScanApproach(ok ? { ...(saved as NonNullable<ScanApproachState>), waitingApproval: false } : null);
}

/** 계획대로 이동 명령을 낸다. 승인 대기 중이면 사람이 이것을 누른다. */
export async function issueScanApproach(): Promise<boolean> {
  const current = approach;
  if (current === null || current.issued || !current.plan.ok) return false;
  if (robotSession().stopped !== null) return false;
  setScanApproach({ ...current, issued: true, waitingApproval: false });
  markApproachIssued();
  // 스캔을 돈 그 로봇으로 간다(261124 · `missionRobot.ts`) — 첫 줄로 내면 다른 로봇이 걸어 나간다.
  const outcome = await issueStepsToEnd(missionClient(), current.plan.steps);
  if (!outcome.sent) emitScanNode(current.missionId, 'T-B2', 'failed', { reason: outcome.reason ?? '' });
  return outcome.sent;
}

