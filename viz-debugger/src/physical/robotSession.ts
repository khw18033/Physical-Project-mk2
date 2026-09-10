/**
 * src/physical/robotSession.ts (260910 신설 — 화면 연결 §1 · §3 · §4)
 *
 * **로봇 한 판의 상태를 들고 있는 열 하나.** 화면은 이걸 읽고, 응답은 이리로 들어온다.
 * `src/data/trace.ts` 와 같은 자리·같은 이유다 — 입구가 둘이면 갈라진다.
 *
 * ## 정지가 하는 넷은 서로 묶여 있지 않다 (§5 「명령이 안 나가도 화면은 멈춘다」)
 *
 *   1. `abort` 발행        ← 실패할 수 있다. 네트워크를 타고 나가므로
 *   2. 추적 중단           ← 여기서 일어난다
 *   3. 타이머·폴링 정지    ← 여기서 일어난다
 *   4. 화면 잠금           ← 여기서 일어난다
 *
 * **2·3·4 는 1의 결과를 보지 않는다.** 이게 이 기능의 뼈대다. 발행이 실패했다고 화면이
 * 계속 돌면, 누른 사람은 멈춘 줄 알고 로봇에 다가간다.
 *
 * ## 이건 안전장치가 아니다
 *
 * 화면의 정지는 소프트웨어 정지다. 브로커가 죽었거나 Wi-Fi 가 끊기면 명령이 아예 안 나간다.
 * **물리적 비상 정지는 로봇 본체와 조종기 쪽에 있다.** 시험할 때도 발표할 때도 조종기를
 * 든 사람이 옆에 있어야 한다.
 */

import { useSyncExternalStore } from 'react';
import type { ViewpointFrame } from '../viewpoint/fill.ts';
import type { LinkEffect } from './missionLink.ts';
import type { PhysicalStatus } from './PhysicalClient.ts';

/** 화면이 잠긴 이유. `null` 이면 안 잠겼다. */
export type StopState = {
  /** 누른 시각. 「정지됨」 띠에 적는다. */
  atIso: string;
  /** `abort` 가 실제로 나갔는가. **화면 잠금과 별개다.** */
  published: boolean;
  /** 못 나갔으면 왜. 크게 빨갛게 띄울 문구다. */
  failure: string | null;
};

/** 태스크 하나가 로봇에 낸 명령. 응답이 어느 노드의 것인지 이걸로 안다. */
export type TaskCommandRecord = {
  taskId: string;
  commandId: string;
  /** 추적기가 발급한 요청 식별자 — 감사·추적이 이 키로 걸린다. */
  requestId: string | null;
  state: 'issued' | 'running' | 'done' | 'failed';
  code: string | null;
  message: string | null;
  result: Record<string, number>;
};

export type RobotSession = {
  connection: PhysicalStatus;
  /** command_id → 그 명령을 낸 태스크. `effectsOf` 의 `taskOf` 가 이걸 본다. */
  commands: Readonly<Record<string, TaskCommandRecord>>;
  /** 뷰포인트 칸별 경고 (`note != ok`). 인덱스로 찾는다. */
  warnings: Readonly<Record<number, string>>;
  /** 진행률 — `ack/of`. 아직 모르면 null. */
  progress: { ack: number; of: number } | null;
  /** `door_turn` 이 왔는가 — `MS-B` 로 넘어가는 선이 열린다. 새 노드가 아니다. */
  doorTurn: { yawDeg: number | null; mismatch: { robot: number; chosen: number; diff: number } | null } | null;
  /** 접근을 이미 쐈는가. **자동으로 넘어가지 않는다** — 사람이 누른다(§1). */
  approachIssued: boolean;
  /** 승인 뒤인가. 이 값이 false 인 동안 로봇으로 나가는 바이트가 없어야 한다(§2). */
  approved: boolean;
  /** 잠김. `null` 이면 안 잠겼다. */
  stopped: StopState | null;
  /** 마지막 `ping` 왕복. 발표 직전에 이걸 보고 무대에 오른다. */
  ping: { ok: boolean; roundTripMs: number | null; message: string } | null;
};

const EMPTY: RobotSession = {
  connection: { state: 'idle' },
  commands: {},
  warnings: {},
  progress: null,
  doorTurn: null,
  approachIssued: false,
  approved: false,
  stopped: null,
  ping: null,
};

let session: RobotSession = EMPTY;
const listeners = new Set<() => void>();
/** 정지가 끊어야 할 타이머들. 목 재생기·폴링이 여기 등록한다 (§4 의 3번). */
const timers = new Set<() => void>();

function commit(next: RobotSession): void {
  session = next;
  for (const listener of listeners) listener();
}

export function robotSession(): RobotSession {
  return session;
}

export function subscribeRobot(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 화면이 읽는 자리. `useSyncExternalStore` 는 같은 참조를 돌려받아야 다시 그리지 않는다. */
export function useRobotSession(): RobotSession {
  return useSyncExternalStore(subscribeRobot, robotSession, robotSession);
}

/** 임무가 바뀌면 판을 비운다. 남은 상태가 다음 임무의 노드를 칠하면 안 된다. */
export function resetRobotSession(): void {
  stopAllTimers();
  commit(EMPTY);
}

/**
 * 정지가 끊을 타이머를 맡긴다. 되돌려주는 함수를 부르면 등록이 풀린다.
 * 목 재생기와 폴링이 이걸 쓴다 — 정지 한 번에 전부 선다.
 */
export function registerTimer(cancel: () => void): () => void {
  timers.add(cancel);
  return () => timers.delete(cancel);
}

function stopAllTimers(): void {
  for (const cancel of timers) cancel();
  timers.clear();
}

export function setConnection(connection: PhysicalStatus): void {
  commit({ ...session, connection });
}

export function setPing(ping: RobotSession['ping']): void {
  commit({ ...session, ping });
}

/** 승인 — 이 뒤부터 로봇으로 바이트가 나갈 수 있다 (`VZ-U-07`). */
export function markApproved(): void {
  commit({ ...session, approved: true });
}

/** 태스크가 명령을 냈다. `requestId` 는 추적기가 준다. */
export function recordCommand(record: TaskCommandRecord): void {
  commit({ ...session, commands: { ...session.commands, [record.commandId]: record } });
}

export function markApproachIssued(): void {
  commit({ ...session, approachIssued: true });
}

/** `effectsOf` 가 낸 것을 판에 반영한다. **여기서 새로 계산하지 않는다** (§3). */
export function applyEffects(effects: readonly LinkEffect[]): ViewpointFrame[] {
  // **정지 뒤에는 아무것도 반영하지 않는다** (§4 의 2번). 뒤늦게 오는 CommandStatus 로
  // 노드가 더 차면, 「정지를 눌렀는데 화면이 계속 진행한다」가 된다 — 이 기능의 가장 흔한
  // 실패 모양이고 눈으로는 "어? 멈췄는데 왜 돌지"로 나타난다.
  if (session.stopped !== null) return [];

  let next = session;
  const frames: ViewpointFrame[] = [];
  for (const effect of effects) {
    if (effect.kind === 'viewpoint') {
      frames.push(effect.frame);
      // 경고는 회전 프레임에만 붙는다 — 로봇이 내는 것은 「어느 각도를 보는가」뿐이다(§6).
      if (effect.warning !== null && effect.frame.channel === 'robot_state') {
        const index = effect.frame.payload.rotation_index;
        next = { ...next, warnings: { ...next.warnings, [index]: effect.warning } };
      }
    } else if (effect.kind === 'progress') {
      next = { ...next, progress: { ack: effect.ack, of: effect.of } };
    } else if (effect.kind === 'door-turn') {
      next = { ...next, doorTurn: { yawDeg: effect.yawDeg, mismatch: effect.mismatch } };
    } else if (effect.kind === 'task-running' || effect.kind === 'task-failed' || effect.kind === 'task-done') {
      next = { ...next, commands: applyTaskEffect(next.commands, effect) };
    } else if (effect.kind === 'aborted') {
      // 로봇이 스스로 끊었다 — 우리가 누른 정지와 다르다. 화면은 잠그지 않고 사실만 남긴다.
      next = { ...next, progress: next.progress };
    }
  }
  if (next !== session) commit(next);
  return frames;
}

function applyTaskEffect(
  commands: RobotSession['commands'],
  effect: LinkEffect,
): RobotSession['commands'] {
  const entry = Object.values(commands).find((c) => 'taskId' in effect && c.taskId === effect.taskId);
  if (entry === undefined) return commands;
  const next = { ...entry };
  if (effect.kind === 'task-running') next.state = 'running';
  if (effect.kind === 'task-done') { next.state = 'done'; next.result = effect.result; }
  if (effect.kind === 'task-failed') {
    next.state = 'failed';
    // **거절 사유를 버리지 않는다** (§3). robot_state_dead 가 실제로 나온 응답이다.
    next.code = effect.code;
    next.message = effect.message;
  }
  return { ...commands, [entry.commandId]: next };
}

/**
 * **긴급 정지의 2·3·4.** 발행(1번)은 부르는 쪽이 따로 하고, **그 결과를 여기 넘긴다.**
 * 넘어온 결과가 실패여도 잠금은 그대로 일어난다 — 함수를 갈라 둔 것이 그 보장이다.
 */
export function lockStopped(published: boolean, failure: string | null): StopState {
  stopAllTimers();                                   // 3. 타이머·폴링 정지
  const stopped: StopState = { atIso: new Date().toISOString(), published, failure };
  commit({ ...session, stopped });                   // 2. 추적 중단(applyEffects 가 즉시 막힌다) · 4. 잠금
  return stopped;
}

/**
 * 「정지됨」에서 나오는 길. **자동으로 돌아가지 않는다** (§4) — 사람이 다시 승인해야 한다.
 * 그래서 푸는 것과 동시에 승인도 내린다.
 */
export function releaseStopped(): void {
  commit({ ...session, stopped: null, approved: false, approachIssued: false });
}

/** 지금 로봇 명령을 내도 되는가. 승인 전과 정지 뒤에는 안 된다. */
export function canIssueRobotCommand(): boolean {
  return session.approved && session.stopped === null;
}
