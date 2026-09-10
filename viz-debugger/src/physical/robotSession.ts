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

/**
 * **일시정지.** 정지와 다른 점은 하나다 — **진행상황을 안 버린다.**
 *
 *   정지    로봇을 멈추고 화면을 잠근다. 여덟 칸도 진행률도 종결된다. 다시 승인해야 한다
 *   일시정지 로봇을 멈추지만 여덟 칸·진행률·문 방향은 그대로 둔다. 재시작하면 이어 간다
 *
 * ## 로봇에는 「이어 하기」가 없다
 *
 * 규약에 일시정지도 재개도 없다(연동 가이드 §4-2). 우리가 할 수 있는 것은 `abort_mission`
 * 으로 **돌던 임무를 접는 것**뿐이다. 그래서 재시작은 멈춘 지점부터가 아니라 **그 단계를
 * 처음부터** 다시 낸다. 화면이 그렇게 말한다 — 「이어서 간다」고 적어 두면 발표자가
 * 로봇이 세 걸음째부터 돌 줄 알고 기다린다.
 */
export type PauseState = {
  atIso: string;
  /** 멈출 때 돌던 태스크. 재시작이 다시 낼 명령이 이것이다. 없었으면 null. */
  taskId: string | null;
  /** `abort_mission` 이 실제로 나갔는가. **화면 멈춤과 별개다.** */
  published: boolean;
  failure: string | null;
};

/** 태스크 하나가 로봇에 낸 명령. 응답이 어느 노드의 것인지 이걸로 안다. */
export type TaskCommandRecord = {
  taskId: string;
  commandId: string;
  /** 무슨 명령이었나. 로봇이 「그런 명령 없다」고 하면 어느 이름인지 알아야 한다. */
  action: string;
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
  /**
   * `door_turn` 이 왔는가 — `MS-B` 로 넘어가는 선이 열린다. 새 노드가 아니다.
   * `chosenIndex` 는 **로봇이 고른 칸**이다. 그 칸이 초록이 된다 (260910).
   */
  doorTurn: { yawDeg: number | null; chosenIndex: number | null } | null;
  /** 이 판에서 각 걸음이 보고한 방위. `door_turn` 을 견주는 데 쓴다. */
  seenYaw: Readonly<Record<number, number>>;
  /** 스캔을 이미 쐈는가. 승인 한 번에 한 번만 나간다. */
  scanIssued: boolean;
  /** 접근을 이미 쐈는가. **자동으로 넘어가지 않는다** — 사람이 누른다(§1). */
  approachIssued: boolean;
  /** 승인 뒤인가. 이 값이 false 인 동안 로봇으로 나가는 바이트가 없어야 한다(§2). */
  approved: boolean;
  /** 잠김. `null` 이면 안 잠겼다. */
  stopped: StopState | null;
  /** 일시정지됨. `null` 이면 안 멈췄다. **진행상황은 그대로 남아 있다.** */
  paused: PauseState | null;
  /** 마지막 `ping` 왕복. 발표 직전에 이걸 보고 무대에 오른다. */
  ping: { ok: boolean; roundTripMs: number | null; message: string } | null;
  /** 승인한 시각(ms). 로봇이 몰 때 「몇 초째인가」의 기준이다. 승인 전에는 null. */
  approvedAtMs: number | null;
  /**
   * 지금 어느 **단계**인가 (연동 가이드 §4-3). `sdk_starting` 이면 로봇이 일어서는 중이다.
   * 임무 ACK 와 다른 축이라 따로 둔다 — 진행률은 아직 0인데 로봇은 이미 뭔가 하고 있다.
   */
  stage: string | null;
  /**
   * 로봇이 **「그런 명령 없다」고 한 이름들** (`UNIMPLEMENTED`).
   *
   * 가이드에 적힌 어휘와 노드에 올라가 있는 어휘가 다를 수 있다 — 260910 실측으로
   * `sdk_stop` · `sdk_auto` 가 `UNIMPLEMENTED: action not supported` 로 돌아왔다.
   * 그러면 그 버튼은 **눌러도 영영 안 되는 버튼**이다. 비활성으로 감추지 않고(정지
   * 버튼과 같은 규칙) 한 번 듣고 나면 화면이 그 사실을 말한다.
   *
   * 하드웨어가 올리는 날 거절이 멈추고 저절로 풀린다 — 우리가 고칠 자리가 없다.
   */
  unsupported: Readonly<Record<string, true>>;
  /**
   * **스캔 중에 로봇이 스스로 걸었다** (260910 실측). `forward_m: 0` 을 보냈는데도 온다.
   *
   * 「접근 시작」을 누르면 **한 번 더** 걷는다는 뜻이라, 누르기 전에 알아야 한다.
   * 담은 것은 로봇이 적어 준 문구 그대로다 — `"ok odo=1.00m cmd=1.00m"`.
   */
  walked: string | null;
};

const EMPTY: RobotSession = {
  connection: { state: 'idle' },
  commands: {},
  warnings: {},
  progress: null,
  doorTurn: null,
  scanIssued: false,
  approachIssued: false,
  approved: false,
  stopped: null,
  paused: null,
  ping: null,
  approvedAtMs: null,
  stage: null,
  unsupported: {},
  walked: null,
  seenYaw: {},
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

/**
 * 임무가 바뀌면 판을 비운다. 남은 상태가 다음 임무의 노드를 칠하면 안 된다.
 *
 * **연결은 안 지운다** (260910 — 실제로 났던 버그). 브로커에 붙은 것은 임무의 성질이
 * 아니라 전송의 성질이다. 여기서 지웠더니 승인 순간에 「브로커 안 붙음」으로 보여
 * 대본 타이머가 돌았고, 로봇이 첫 걸음도 떼기 전에 화면이 끝나 있었다.
 *
 * `ping` 결과도 남긴다 — 연결 관리에서 확인한 사실이 임무를 바꿨다고 사라지면 안 된다.
 */
export function resetRobotSession(): void {
  stopAllTimers();
  commit({ ...EMPTY, connection: session.connection, ping: session.ping });
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

/**
 * **사람이 이번 세션에서 승인을 누른 계획.** 로봇 관문은 이 값이 맞을 때만 열린다.
 *
 * 260910 에 페이지를 새로 열자마자 `approved: true` 였다. 계획 채널이 **캐시되는 채널**이라
 * 지난 세션의 승인된 계획이 재접속 즉시 다시 내려오고, 그걸 새 승인으로 받아 관문을
 * 열었기 때문이다. 브로커가 붙는 순간 스캔이 나갔다 — **사람이 아무것도 안 눌렀는데
 * 로봇이 움직일 수 있는 상태**였다.
 *
 * 모듈 변수로 둔다(세션 밖으로 안 나간다). 새로고침하면 비고, 그것이 이 값의 요점이다.
 */
let humanApprovedPlanId: string | null = null;

/** 사람이 「승인」을 눌렀다. 누른 그 순간에만 부른다. */
export function armApproval(planId: string): void {
  humanApprovedPlanId = planId;
}

/** 이 계획을 이번 세션에서 사람이 승인했는가. */
export function approvedByHuman(planId: string): boolean {
  return humanApprovedPlanId === planId;
}

/** 승인 — 이 뒤부터 로봇으로 바이트가 나갈 수 있다 (`VZ-U-07`). */
export function markApproved(): void {
  commit({ ...session, approved: true, approvedAtMs: Date.now() });
}

/**
 * **로봇이 임무를 모는가.** 브로커에 붙어 있으면 그렇다.
 *
 * 붙어 있으면 대본의 자동 진행을 멈추고 uplink 가 오는 대로 진행한다 — 「라즈베리파이와
 * 통신되어서 받아오는 정보를 토대로 진행되어야 한다」(260910 지적). 안 붙어 있으면
 * 대본이 그대로 돈다 — 로봇 없이도 시연이 되어야 하기 때문이다.
 */
export function robotDrives(): boolean {
  return session.connection.state === 'open';
}

/** 승인 뒤 몇 초째인가. 로봇이 몰 때 사건의 시각이 된다. */
export function elapsedSec(): number {
  if (session.approvedAtMs === null) return 0;
  return (Date.now() - session.approvedAtMs) / 1000;
}

/** 태스크가 명령을 냈다. `requestId` 는 추적기가 준다. */
export function recordCommand(record: TaskCommandRecord): void {
  commit({ ...session, commands: { ...session.commands, [record.commandId]: record } });
}

export function markApproachIssued(): void {
  commit({ ...session, approachIssued: true });
}

export function markScanIssued(): void {
  commit({ ...session, scanIssued: true });
}

/** 발행이 실패했으면 표시를 도로 내린다 — 안 나간 것을 나갔다고 둘 수 없다. */
export function clearScanIssued(): void {
  commit({ ...session, scanIssued: false });
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
      if (effect.frame.channel === 'robot_state') {
        const index = effect.frame.payload.rotation_index;
        // 이 걸음이 보고한 방위를 적어 둔다 — `door_turn` 이 어느 걸음이었는지 견줄 재료다.
        next = { ...next, seenYaw: { ...next.seenYaw, [index]: effect.frame.payload.yaw } };
        // 경고는 회전 프레임에만 붙는다 — 로봇이 내는 것은 「어느 각도를 보는가」뿐이다(§6).
        if (effect.warning !== null) {
          next = { ...next, warnings: { ...next.warnings, [index]: effect.warning } };
        }
      }
    } else if (effect.kind === 'progress') {
      next = { ...next, progress: { ack: effect.ack, of: effect.of } };
    } else if (effect.kind === 'door-turn') {
      next = { ...next, doorTurn: { yawDeg: effect.yawDeg, chosenIndex: effect.chosenIndex } };
    } else if (effect.kind === 'task-running' || effect.kind === 'task-failed' || effect.kind === 'task-done') {
      next = { ...next, commands: applyTaskEffect(next.commands, effect) };
      // 명령이 끝났으면 단계는 지난 말이다 — 「실행 중」을 끝난 뒤에도 띄우면 거짓말이다.
      if (effect.kind !== 'task-running') next = { ...next, stage: null };
      // **「그런 명령 없다」를 기억한다.** 눌러도 영영 안 되는 버튼을 계속 권하지 않는다.
      if (effect.kind === 'task-failed' && effect.code === 'UNIMPLEMENTED') {
        const action = next.commands[effect.commandId]?.action;
        if (action !== undefined) next = { ...next, unsupported: { ...next.unsupported, [action]: true } };
      }
    } else if (effect.kind === 'walked') {
      // 스캔이 걸었을 때만 놀랄 일이다 — 「접근 시작」(T-B2)은 걸으라고 시킨 것이다.
      if (effect.taskId === 'T-A3') next = { ...next, walked: effect.note };
    } else if (effect.kind === 'stage') {
      // **일어서는 중이라는 말을 안 삼킨다.** 몇 초 동안 아무 일도 안 일어나는 것처럼
      // 보이는 구간이고, 그때 화면이 조용하면 발표장에서 「왜 안 가지」가 된다.
      next = { ...next, stage: effect.stage };
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
  // **command_id 로 찾는다.** 태스크 이름으로 찾으면 같은 이름의 둘째 명령이 첫째를 덮는다.
  const entry = 'commandId' in effect ? commands[effect.commandId] : undefined;
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
  // 정지를 풀면 승인도 내려간다 — 사람이 다시 눌러야 관문이 열린다.
  humanApprovedPlanId = null;
  commit({ ...session, stopped: null, approved: false, approachIssued: false, scanIssued: false });
}

/** 지금 로봇 명령을 내도 되는가. 승인 전과 정지 뒤에는 안 된다. */
export function canIssueRobotCommand(): boolean {
  return session.approved && session.stopped === null && session.paused === null;
}

/**
 * **일시정지를 건다.** 정지와 같은 뼈대다 — 발행이 실패해도 2·3 은 그대로 일어난다.
 * 다른 점은 **아무것도 안 버린다**는 것뿐이다. 여덟 칸도 진행률도 문 방향도 그대로다.
 */
export function lockPaused(taskId: string | null, published: boolean, failure: string | null): PauseState {
  stopAllTimers();
  const paused: PauseState = { atIso: new Date().toISOString(), taskId, published, failure };
  commit({ ...session, paused });
  return paused;
}

/**
 * **일시정지를 푼다.** 정지 해제와 달리 **승인을 안 내린다** — 사람이 이미 승인한 임무를
 * 잠깐 세웠다가 이어 가는 것이라 다시 승인을 받을 이유가 없다.
 *
 * `scanIssued` 는 내린다. 재시작이 그 단계를 다시 내야 하기 때문이다.
 */
export function releasePaused(): void {
  commit({ ...session, paused: null, scanIssued: false, approachIssued: false });
}

/** 지금 로봇이 돌리고 있는 태스크. 재시작이 무엇을 다시 낼지 정하는 재료다. */
export function runningTaskId(): string | null {
  const running = Object.values(session.commands).find((c) => c.state === 'running' || c.state === 'issued');
  return running?.taskId ?? null;
}
