/**
 * src/physical/generatedRun.ts (261123 신설 — AI 생성 임무 실행기)
 *
 * **승인된 생성 임무의 걸음을 낸다.** 차례 규칙은 `generate/actionCommands.ts` 의 `runGenerated` 하나에 있고, 여기는
 * 그 규칙에 소켓 · 기록 · 화면을 잇기만 한다.
 *
 * - 명령 과업: 정량 명령과 **같은 발행 함수**(`issueStepsToEnd`) — 앞 걸음의 종료 응답을 받은 뒤 다음, 마지막 걸음의
 *   종료까지 기다린다. 노드는 명령이 들고 간 과업 id 로 칠해진다(`robotBridge.ts` — 정량 명령과 같은 길).
 * - 사람 확인 과업: 그 노드를 「사람 확인 대기」로 세우고, 사람이 「확인」 · 「실패로 닫기」를 누를 때까지 기다린다.
 *
 * 관문은 정량 명령과 같다 — 승인 **그리고** 「임무 시작」(`wantsStepMission`), 한 판에 한 번(`markScanIssued`).
 */

import { useSyncExternalStore } from 'react';
import type { PhysicalClient } from './PhysicalClient.ts';
import { issueStepsToEnd } from './robotCommands.ts';
import { markScanIssued, robotSession, subscribeRobot } from './robotSession.ts';
import { deviceIdentityFor } from './deviceIdentity.ts';
import { currentMission, recordHumanVerdict, recordRunnerWait, subscribeMission } from '../data/scenario.ts';
import { runGenerated, type RunItem, type RunOutcome } from '../generate/actionCommands.ts';

export type GeneratedRunState = {
  missionId: string | null;
  phase: 'idle' | 'running' | 'waiting_human' | 'done' | 'failed' | 'stopped';
  /** 지금 차례인 과업. */
  taskId: string | null;
  /** 몇 번째 칸인가(0부터) / 모두 몇 칸인가. */
  index: number;
  total: number;
  /** 실패 사유 — 로봇이 준 사유거나 `human`(사람이 실패로 닫았다). */
  reason: string | null;
};

const IDLE: GeneratedRunState = { missionId: null, phase: 'idle', taskId: null, index: 0, total: 0, reason: null };
let state: GeneratedRunState = IDLE;
const listeners = new Set<() => void>();
/** 기다리는 사람 확인. 한 번에 하나다 — 실행이 한 줄이다. */
let pendingHuman: { missionId: string; taskId: string; resolve(verdict: 'done' | 'failed' | 'stopped'): void } | null = null;

function commit(next: GeneratedRunState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function generatedRunState(): GeneratedRunState {
  return state;
}

export function useGeneratedRun(): GeneratedRunState {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => listeners.delete(listener); },
    generatedRunState,
    generatedRunState,
  );
}

/** 정지됐거나 판이 바뀌었다 — 기다리던 사람 확인을 「멈춤」으로 끝낸다. */
function settlePendingIfGone(): void {
  if (pendingHuman === null) return;
  const gone = robotSession().stopped !== null || currentMission().missionId !== pendingHuman.missionId;
  if (!gone) return;
  const waiting = pendingHuman;
  pendingHuman = null;
  waiting.resolve('stopped');
}

let wired = false;
function wireOnce(): void {
  if (wired) return;
  wired = true;
  subscribeRobot(settlePendingIfGone);
  subscribeMission(settlePendingIfGone);
}

/**
 * **사람이 과업을 닫는다.** 지금 기다리는 그 과업일 때만 받는다 — 화면이 늦게 그려져 옛 버튼이 눌려도 엉뚱한 과업이
 * 닫히지 않는다. 받았으면 true.
 */
export function answerHuman(taskId: string, verdict: 'done' | 'failed'): boolean {
  if (pendingHuman === null || pendingHuman.taskId !== taskId) return false;
  if (currentMission().missionId !== pendingHuman.missionId) return false;
  const waiting = pendingHuman;
  pendingHuman = null;
  recordHumanVerdict(taskId, verdict);
  waiting.resolve(verdict);
  return true;
}

/**
 * **장비가 밝힌 동작에 없는 걸음** (발행 직전 확인). 목록을 아직 못 받았으면 빈 배열이다 — 보내고 장비의 거절을 받는다.
 * 목록에 없다고 **말한** 장비에게만 안 보낸다(`issueStepMission` 의 `move_relative` 확인과 같은 규칙).
 */
export function undeclaredActions(client: PhysicalClient, items: readonly RunItem[]): string[] {
  const actions = deviceIdentityFor(client.address())?.actions ?? null;
  if (actions === null) return [];
  const used = new Set(items.flatMap((item) => (item.kind === 'command' ? item.steps.map((step) => step.action) : [])));
  return [...used].filter((action) => !actions.includes(action));
}

/**
 * **한 판을 돈다.** 부르는 쪽(`robotClient.ts`)이 관문(`wantsStepMission`)과 한 번만(`lastScanAttempt`)을 본 뒤에 부른다.
 */
export async function startGeneratedRun(client: PhysicalClient, items: readonly RunItem[]): Promise<RunOutcome> {
  wireOnce();
  const missionId = currentMission().missionId;
  markScanIssued();
  commit({ missionId, phase: 'running', taskId: null, index: 0, total: items.length, reason: null });
  const outcome = await runGenerated(items, {
    issue: (steps) => issueStepsToEnd(client, steps),
    waitHuman: (taskId) => new Promise((resolve) => {
      pendingHuman = { missionId, taskId, resolve };
      recordRunnerWait(taskId);
      commit({ ...state, phase: 'waiting_human', taskId });
      // 기다리기 전에 이미 정지됐을 수 있다.
      settlePendingIfGone();
    }),
    stopped: () => robotSession().stopped !== null || currentMission().missionId !== missionId,
    onTask: (index, item) => commit({ ...state, phase: 'running', taskId: item.taskId, index }),
  });
  // 판이 바뀌었으면 새 판의 화면 상태를 덮어쓰지 않는다.
  if (state.missionId === missionId) {
    commit({
      ...state,
      phase: outcome.ended,
      taskId: outcome.ended === 'done' ? null : outcome.taskId,
      reason: outcome.ended === 'failed' ? outcome.reason : null,
    });
  }
  return outcome;
}
