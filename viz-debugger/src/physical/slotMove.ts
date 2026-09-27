/**
 * src/physical/slotMove.ts (260927 신설 — 장치 두 대 편 · Go1 실동작)
 *
 * **자리에 앉은 장비가 실제로 걸을 수 있으면, 그 장비는 가상 맵의 경로를 실제로 걷는다.**
 *
 * 판(`driver: 'local'`)은 화면이 몬다. 그런데 카드로 앉힌 장비가 Go1 이면 「장치 이동」이 대본이어서는
 * 안 된다(260927 지시 — 「Go1 은 연결했을 때 실제 이동」). 그래서 판이 열릴 때 장비마다 묻는다:
 *
 *   걸을 수 있다    그 장비의 「이동 시작」「이동 완료 확인」을 맡는다 — 대본이 아니라 로봇의 응답이 칠한다
 *   못 걷는다       맡지 않는다 — 대본이 칠한다 (드론: 이동 action 이 아직 없다)
 *
 * 장비를 아는 면은 이 폴더 하나라(`verify:physical-port`), 판을 모는 저장소는 이 파일을 모르고
 * 훅(`registerLiveMoveHooks`)만 안다.
 *
 * ## 「걸을 수 있다」의 근거
 *
 * **장비가 밝힌 action 목록**이다 — `turn` 과 `move_forward` 둘 다 있어야 한다. 기종으로 판정하지 않는다
 * (`stopSupport()` 와 같은 원칙). 목록을 아직 못 받았으면(Capability 는 retained 가 아니다) 장비가 밝힌
 * 종류(`kind`)로 한 번 더 본다 — `robot` 이면 걷는다. 드론이 목록을 못 준 채로 걷는 쪽에 들어가도 드론은
 * 규약대로 `UNIMPLEMENTED` 로 거절하고, 그 거절이 노드에 실패로 뜬다 — 조용히 대본으로 넘어가지 않는다.
 *
 * ## 명령을 언제 내나
 *
 * 그 장비의 「이동 시작」 앞 태스크(「이동 경로 확인」)가 **완료로 칠해진 뒤**다. 승인만으로도, 「임무 시작」
 * 만으로도 안 나간다 — 연결 확인·위치 추정·경로 탐지가 화면에서 다 지나간 다음이다.
 *
 * ## 멈춤
 *
 * 정지·일시정지는 걷고 있는 장비에 실제로 정지를 보낸다(`emergencyStop` · `pauseMission`). 규약에 「이어 걷기」가
 * 없으므로 멈춘 이동은 **실패로 남는다** — 이어서 다시 걷게 하면 이미 걸은 만큼을 모르고 경로를 처음부터 다시 걷는다.
 * 다시 하려면 「처음부터」다.
 */

import { t } from '../i18n/dict.ts';
import {
  appendLiveEvent, currentMission, haltLocalRunOnFailure, localRunPhase, registerLiveMoveHooks,
  subscribeMission, traceEvents, type MissionView,
} from '../data/scenario.ts';
import { slotBindings } from '../data/slots.ts';
import { localDriven } from '../scenarios/library.ts';
import { noteIssue } from '../shared/notifications.ts';
import { deviceIdentityFor } from './deviceIdentity.ts';
import { clientForDevice } from './robotClient.ts';
import { emergencyStop, issueStepsToEnd, pauseMission } from './robotCommands.ts';
import { markApproved, releasePaused, robotSession } from './robotSession.ts';
import { pathStepCommands, STEP_VX } from './stepScript.ts';
import type { TaskCommand } from './missionLink.ts';

/** 걸을 수 있다고 볼 action 들. 둘 다 밝혀야 한다. */
const WALK_ACTIONS = ['turn', 'move_forward'] as const;

type MapDevice = {
  slot: string;
  start: { x: number; z: number };
  start_yaw_deg?: number;
  path: Array<[number, number]>;
  path_task: string;
  move_start_task: string;
  arrive_task: string;
};

type Move = {
  missionId: string;
  deviceId: string;
  startTask: string;
  arriveTask: string;
  /** 「이동 시작」 앞에서 끝나 있어야 하는 태스크들. */
  after: readonly string[];
  steps: TaskCommand[];
  reads: string[];
  lengthM: number;
  plannedToTargetM: number | null;
  phase: 'waiting' | 'walking' | 'ended';
  /** 사람이 멈췄는가 — 끝난 사유를 가른다. */
  haltedBy: 'pause' | 'stop' | null;
};

let moves: Move[] = [];

/** 이 장비가 걸을 수 있는가 — 위 머리말의 규칙. 붙은 소켓이 없으면 못 걷는다(명령이 닿을 곳이 없다). */
export function canWalk(deviceId: string): boolean {
  const client = clientForDevice(deviceId);
  if (client === null) return false;
  const identity = deviceIdentityFor(client.address());
  if (identity === null) return false;
  if (identity.actions !== null) return WALK_ACTIONS.every((action) => identity.actions!.includes(action));
  return identity.kind === 'robot';
}

function mapDevices(view: MissionView): MapDevice[] {
  const spec = view.params.virtual_map as { devices?: MapDevice[]; target?: { x: number; z: number } } | undefined;
  return Array.isArray(spec?.devices) ? spec.devices : [];
}

/** 판이 열린다 — 걸을 수 있는 장비의 이동을 맡는다. */
function claim(view: MissionView): readonly string[] {
  moves = [];
  if (!localDriven(view.missionId)) return [];
  const bindings = slotBindings();
  const target = (view.params.virtual_map as { target?: { x: number; z: number } } | undefined)?.target ?? null;
  for (const device of mapDevices(view)) {
    const deviceId = bindings[device.slot];
    if (deviceId === undefined || !canWalk(deviceId)) continue;
    const plan = pathStepCommands(device.path, device.start_yaw_deg ?? 0, device.arrive_task, STEP_VX);
    if (plan.steps.length === 0) continue;
    const end = device.path[device.path.length - 1];
    moves.push({
      missionId: view.missionId,
      deviceId,
      startTask: device.move_start_task,
      arriveTask: device.arrive_task,
      after: view.tasks.find((task) => task.id === device.move_start_task)?.deps ?? [],
      steps: plan.steps,
      reads: plan.reads,
      lengthM: Number(plan.lengthM.toFixed(2)),
      plannedToTargetM: target === null || end === undefined ? null : Number(Math.hypot(end[0] - target.x, end[1] - target.z).toFixed(2)),
      phase: 'waiting',
      haltedBy: null,
    });
  }
  /**
   * **로봇 명령의 관문을 연다.** 발행기는 승인된 판에서만 낸다(`canIssueRobotCommand`). 이 편은 문 찾기 편의
   * 관문(`opensRobotGate`)을 안 여는데 — 그러면 승인하자마자 스캔이 나간다 — 걸을 장비가 있을 때만 여기서 연다.
   * 스캔은 여전히 안 나간다: 스캔은 로봇 세션의 「시작」(`markStarted`)을 기다리고, 이 편은 그것을 안 누른다.
   */
  if (moves.length > 0) markApproved();
  return moves.flatMap((move) => [move.startTask, move.arriveTask]);
}

/** 앞 태스크가 다 끝났으면 걷기 시작한다. 판이 도는 중일 때만이다. */
function check(): void {
  if (moves.length === 0 || localRunPhase() !== 'running') return;
  const mission = currentMission();
  const done = new Set(traceEvents().filter((event) => event.status === 'done').map((event) => event.nodeId));
  for (const move of moves) {
    if (move.phase !== 'waiting' || move.missionId !== mission.missionId) continue;
    if (!move.after.every((id) => done.has(id))) continue;
    move.phase = 'walking';
    void walk(move, mission);
  }
}

async function walk(move: Move, mission: MissionView): Promise<void> {
  appendLiveEvent(move.missionId, move.startTask, 'running', 'started', {
    device: move.deviceId, steps: move.reads.join(' · '), planned_path_m: move.lengthM, source: 'robot',
  });
  const client = clientForDevice(move.deviceId);
  let started = false;
  const outcome = await issueStepsToEnd(client, move.steps, (order, issued) => {
    if (order !== 0) return;
    // **첫 걸음이 나간 순간이 「이동 시작」의 끝이다** — 로봇이 받았고 걷기 시작했다.
    started = true;
    appendLiveEvent(move.missionId, move.startTask, 'done', 'evaluated', { device: move.deviceId, command_id: issued.commandId });
    appendLiveEvent(move.missionId, move.arriveTask, 'running', 'started', { device: move.deviceId });
  });
  move.phase = 'ended';
  if (outcome.sent === true) {
    // 평가 노드다 — 판정 기준을 먼저 적고 근거와 함께 끝낸다(대본의 평가 태스크와 같은 두 줄).
    const criterion = mission.tasks.find((task) => task.id === move.arriveTask)?.evaluation?.criteria[0];
    if (criterion !== undefined) appendLiveEvent(move.missionId, move.arriveTask, 'awaiting_evaluation', 'evaluated', { criterion });
    appendLiveEvent(move.missionId, move.arriveTask, 'done', 'evaluated', {
      device: move.deviceId,
      ended_by: 'SUCCEEDED',
      commands: move.steps.length,
      planned_path_m: move.lengthM,
      // **실측 거리가 아니다.** 로봇은 「다 걸었다」만 말하고 어디에 섰는지는 말하지 않는다 — 계획한 경로 끝과
      // 대상 사이의 거리라서 이름에 planned 를 붙였다.
      ...(move.plannedToTargetM === null ? {} : { planned_distance_to_target_m: move.plannedToTargetM }),
      source: 'robot',
    });
    return;
  }
  const reason = move.haltedBy === null ? (outcome.reason ?? t('robot.noReason')) : t(move.haltedBy === 'stop' ? 'smove.stopped' : 'smove.paused');
  appendLiveEvent(move.missionId, started ? move.arriveTask : move.startTask, 'failed', 'failed', {
    device: move.deviceId, message: reason, source: 'robot',
  });
  noteIssue(`task:${started ? move.arriveTask : move.startTask}`, 'robot', t('smove.failed', { device: move.deviceId, reason }));
  // 사람이 멈춘 것이 아니면 판을 세운다 — 로봇이 못 간 채로 「임무 완료」를 기다리며 서 있게 두지 않는다.
  if (move.haltedBy === null) haltLocalRunOnFailure();
}

/** 사람이 멈췄다 — **걷고 있는 장비에만** 정지를 보낸다. 안 걷는 장비(드론)에는 아무것도 안 보낸다. */
function halt(kind: 'pause' | 'stop'): void {
  for (const move of moves) {
    if (move.phase !== 'walking') continue;
    move.haltedBy = kind;
    const client = clientForDevice(move.deviceId);
    void (kind === 'stop' ? emergencyStop(client) : pauseMission(client));
  }
}

/** 이어 가기 — 일시정지가 건 명령 잠금을 푼다. 멈춘 이동을 다시 걷게 하지는 않는다(머리말). */
function resume(): void {
  if (robotSession().paused !== null) releasePaused();
}

let started = false;

/** 앱이 살아 있는 동안 한 번 건다 — 노드를 눌러 화면을 옮겨도 끊기면 안 된다(`startNavLink` 와 같은 자리). */
export function startSlotMove(): () => void {
  if (started) return () => undefined;
  started = true;
  registerLiveMoveHooks({ claim, halt, resume });
  const off = subscribeMission(check);
  return () => {
    off();
    registerLiveMoveHooks(null);
    moves = [];
    started = false;
  };
}
