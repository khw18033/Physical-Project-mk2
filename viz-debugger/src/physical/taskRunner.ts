/**
 * src/physical/taskRunner.ts (260929 신설 — 임무 실행기. `slotMove.ts` 를 넓혔다)
 *
 * **앞 태스크가 끝나면 다음 태스크를 실제 값으로 판정한다.**
 *
 * 260927 의 장치 두 대 편은 대본의 사건을 제 시각에 흘리고, Go1 의 「이동 시작 · 이동 완료 확인」 둘만 로봇
 * 응답이 칠했다(`slotMove.ts`). 260929 지시는 그 반대다 — **거의 모든 노드를 실제 값으로** 판정하고, 정해 준
 * 노드만 정해진 시간(지금은 5초)을 채워 넘긴다. 그래서 대본 재생 대신 이 실행기가 판을 몬다.
 *
 * ## 무엇으로 판정하나 — 대본의 `params.judges`
 *
 * 태스크마다 판정 방식을 대본이 적는다. 이 파일은 방식만 알고 어느 태스크가 무엇인지는 모른다 — 장치 두 대
 * 편과 @까지 이동 편이 같은 실행기를 쓴다.
 *
 *   online · link · battery · ready · camera   자리에 앉은 장비가 지금 보내는 값 (장비 상태 · ping · 영상 한 장)
 *   map-*                                      가상 맵 자료로 셈한다 (@ 자리 · 출발 자세 · 경로 · 간격 · 방위 · 시야)
 *   face · move                                걸을 수 있는 장비면 실제 명령, 아니면 정해진 시간을 채워 넘긴다
 *   hold                                       정해진 시간을 채워 넘긴다
 *   report                                     앞이 다 끝났으면 끝
 *
 * **걸을 수 있는가는 장비가 밝힌 명령 목록이 정한다**(`canWalk`) — 기종으로 가르지 않는다. 드론에 이동 명령이
 * 생기면 같은 대본에서 이동 노드가 저절로 실제 명령으로 바뀐다. 드론은 지금 `ping` 만 밝혀서 연결 확인만 실제다.
 *
 * ## 넘긴 노드
 *
 * 화면에서는 다른 완료 노드와 똑같이 칠한다(260929 지시 3-A). 넘겼다는 사실은 **판 기록**에 남는다 —
 * 「임무 시작」 줄의 `held_tasks`, 그리고 그 노드 근거값의 `hold_s`.
 *
 * ## 멈춤
 *
 * 정지·일시정지는 명령을 내고 있는 장비에 실제로 정지를 보낸다. 규약에 「이어 걷기」가 없어 멈춘 이동은 실패로
 * 남는다(다시 하려면 「처음부터」). 확인 노드는 다르다 — 재시작하면 실패한 확인을 다시 한다. 배터리를 갈거나
 * 링크를 다시 꽂고 이어 가는 것이 무대에서 실제로 하는 일이다.
 */

import { t } from '../i18n/dict.ts';
import {
  appendLiveEvent, currentMission, getMissionState, haltLocalRunOnFailure, localRunPhase, recordHuman, registerLiveMoveHooks,
  subscribeMission, traceEvents, type MissionView,
} from '../data/scenario.ts';
import { slotBindings } from '../data/slots.ts';
import { localDriven } from '../scenarios/library.ts';
import { noteIssue } from '../shared/notifications.ts';
import { connectedDevice } from '../shared/connectedDevices.ts';
import { telemetryValue } from '../shared/deviceTelemetry.ts';
import { deviceState, isStale } from './deviceState.ts';
import { deviceIdentityFor } from './deviceIdentity.ts';
import { clientForDevice } from './robotClient.ts';
import { directCameraUrl, type DirectCameraSource } from './cameraView.ts';
import { emergencyStop, issuePing, issueStepsToEnd, pauseMission } from './robotCommands.ts';
import { markApproved, releasePaused, robotSession } from './robotSession.ts';
import { pathStepCommands, STEP_VX, turnStepCommands } from './stepScript.ts';
import { mapSpecOf, pathGap, pathLengthM, r2, viewOf, type MapDevice, type MapSpec } from './mapPlan.ts';
import type { TaskCommand } from './missionLink.ts';

/** 걸을 수 있다고 볼 action 들. 둘 다 밝혀야 한다. */
const WALK_ACTIONS = ['turn', 'move_forward'] as const;
/** 정해진 시간을 채워 넘기는 노드의 기본 유지 시간(초). 대본의 `params.hold_sec` 이 이긴다. */
export const DEFAULT_HOLD_SEC = 5;
/** 장비 값을 기다리는 한도(판의 초). 상태는 5~10초 주기라 한 번은 온다. */
export const CHECK_TIMEOUT_SEC = 12;
/** 카메라 주소에서 첫 응답을 기다리는 한도(ms). */
const CAMERA_PROBE_MS = 8000;
/** 카메라 화각의 기본값(°) — Go1 앞 카메라 · pi3 카메라 모듈 둘 다 이 근처다. 대본의 `params.camera_fov_deg` 가 이긴다. */
const DEFAULT_FOV_DEG = 59;

type MovePhase = 'prepare' | 'start' | 'follow' | 'stop' | 'arrive' | 'end';

type MapJudge =
  | { kind: 'map-target' }
  | { kind: 'map-pose'; slots: string[] }
  | { kind: 'map-path' | 'map-bearing' | 'map-view'; slot: string }
  | { kind: 'map-gap' };

type Judge =
  /**
   * `soft` 가 있으면 (260929 — 이상 탐지 편의 첫 번째 장치) 실제 판정이 통과하면 그 값으로, 아니면(값이 없거나 실패)
   * `soft` 초 뒤 완료로 칠한다. pi3 는 붙이되 드론(FC)은 안 붙이는 시연 구성이다 — 판 기록의 `held_tasks` 에 적힌다.
   */
  | { kind: 'online' | 'link' | 'battery' | 'ready' | 'camera'; slot: string; soft?: number }
  | MapJudge
  | { kind: 'face'; slot: string }
  /**
   * `confirm` 이 있으면 (260929 — 이상 탐지 편) 이 이동은 **사람이 승인해야 끝난다.** 기다리는 동안 머리줄에
   * `confirm` 자리 장치의 산출 경로와 승인 버튼이 뜬다(`MoveGateButton`) — 드론 이동이 끝난 것을 눈으로 보고
   * Go1 을 출발시키는 자리다.
   */
  | { kind: 'move'; slot: string; phase: MovePhase; confirm?: string }
  /** `sec` 이 있으면 그 노드만 그만큼 유지한다 (260929 — 이상 탐지 편의 「모니터링 진행」 12초). 없으면 `hold_sec`. */
  | { kind: 'hold'; show?: 'target' | 'pose' | 'path' | 'rationale'; slot?: string; sec?: number }
  | { kind: 'report' };

type Producer = 'robot' | 'backend';
type Outcome = { ok: true; payload: Record<string, unknown> } | { ok: false; reason: string };

type TaskRun = {
  id: string;
  deps: readonly string[];
  criterion: string | null;
  judge: Judge;
  phase: 'waiting' | 'running' | 'done' | 'failed';
  startedAt: number;
  /** 비동기 판정(ping · 영상 · 회전)을 이미 냈는가. */
  asked: boolean;
  outcome: Outcome | null;
  /** 재시작하면 다시 하는가 — 확인은 다시 하고, 로봇을 움직인 것은 안 한다. */
  retry: boolean;
  /** 정해진 시간을 채워 넘기는가. 판을 열 때 정한다. */
  held: boolean;
  lastProgressAt: number;
  /** 사람이 멈춰서 끝난 것인가. */
  haltedBy: 'pause' | 'stop' | null;
};

type Walk = {
  slot: string;
  deviceId: string | null;
  device: MapDevice;
  /** 실제로 걷는가, 정해진 시간을 채워 넘기는가. 판을 열 때 정한다. */
  mode: 'walking' | 'held';
  state: 'idle' | 'going' | 'ended';
  marks: Set<MovePhase>;
  failure: string | null;
  haltedBy: 'pause' | 'stop' | null;
  steps: TaskCommand[];
  reads: string[];
  lengthM: number;
  commandId: string | null;
};

type Run = {
  missionId: string;
  view: MissionView;
  spec: MapSpec | null;
  tasks: TaskRun[];
  walks: Map<string, Walk>;
  yaw: Record<string, number>;
  holdSec: number;
  fovDeg: number;
  minBatteryPct: number;
  stopMaxM: number;
  minGapM: number;
  /** 지금 명령을 내고 있는 장비 — 멈춤이 여기로 정지를 보낸다. */
  busy: Set<string>;
};

let run: Run | null = null;

// ── 사람 승인 (260929) ────────────────────────────────────────────────────────

/** 머리줄이 그리는 승인 대기. 없으면 null. */
export type MoveGate = {
  missionId: string;
  taskId: string;
  /** 승인하면 출발할 장치의 자리 · 장비 · 산출 경로. */
  slot: string;
  deviceId: string | null;
  route: string;
  lengthM: number;
};

let gate: MoveGate | null = null;
/** 승인된 태스크 — 판마다 비운다. */
let approvedGates = new Set<string>();
const gateListeners = new Set<() => void>();

function setGate(next: MoveGate | null): void {
  if (gate === next || (gate !== null && next !== null && gate.taskId === next.taskId && gate.route === next.route)) return;
  gate = next;
  for (const listener of gateListeners) listener();
}

export function moveGate(): MoveGate | null {
  return gate;
}

/**
 * **지금 임무가 모는 장비** (261005 — 수동 제어가 키를 막는 기준).
 *
 * 판에 걸을 장비로 묶였고(`walking`) 아직 끝나지 않았으면 그 판의 것이다 — 출발 전에 기다리는 동안도 포함한다.
 * 기다리는 사이 사람이 몰아 두면 판이 잰 출발 자리 · 방위가 틀어진 채로 경로가 나간다.
 * 명령을 내는 중인 장비(`busy`)도 더한다.
 */
export function autoDrivenDevices(): ReadonlySet<string> {
  const out = new Set<string>();
  if (run === null) return out;
  for (const walk of run.walks.values()) {
    if (walk.deviceId !== null && walk.mode === 'walking' && walk.state !== 'ended') out.add(walk.deviceId);
  }
  for (const deviceId of run.busy) out.add(deviceId);
  return out;
}

export function subscribeMoveGate(listener: () => void): () => void {
  gateListeners.add(listener);
  return () => { gateListeners.delete(listener); };
}

/**
 * **승인** — 기다리던 이동을 끝내고 다음으로 넘긴다. 사람 조작이라 판 기록에 남긴다(`VZ-D-08`). 판이 멈춰
 * 있으면(일시정지 · 정지) 받지 않는다 — 멈춘 판에서 Go1 이 출발하면 안 된다.
 */
export function approveMoveGate(): boolean {
  if (gate === null || localRunPhase() !== 'running') return false;
  approvedGates.add(gate.taskId);
  recordHuman('move_gate_approved', gate.taskId, { slot: gate.slot, device: gate.deviceId, route: gate.route });
  setGate(null);
  tick();
  return true;
}

// ── 걸을 수 있는가 ────────────────────────────────────────────────────────────

/** 이 장비가 걸을 수 있는가. 붙은 소켓이 없으면 못 걷는다(명령이 닿을 곳이 없다). */
export function canWalk(deviceId: string): boolean {
  const client = clientForDevice(deviceId);
  if (client === null) return false;
  const identity = deviceIdentityFor(client.address());
  if (identity === null) return false;
  if (identity.actions !== null) return WALK_ACTIONS.every((action) => identity.actions!.includes(action));
  return identity.kind === 'robot';
}

// ── 영상 한 장 ────────────────────────────────────────────────────────────────

type CameraProbe = (source: DirectCameraSource) => Promise<{ ok: boolean; reason?: string }>;

/**
 * 그 주소에서 영상이 오는가. Go1 뷰어는 끝나지 않는 MJPEG 이라 **첫 응답**이 오면 끊는다(CORS 가 없어 몸은 못
 * 읽는다 — 응답이 왔다는 것까지가 증거다). 드론은 개발 서버 중계가 한 장을 JPEG 로 주므로 그 한 장을 받아 본다.
 */
const defaultCameraProbe: CameraProbe = async (source) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CAMERA_PROBE_MS);
  try {
    if (source.kind === 'stream') {
      await fetch(source.url, { mode: 'no-cors', signal: controller.signal, cache: 'no-store' });
      return { ok: true };
    }
    const response = await fetch(source.url, { signal: controller.signal, cache: 'no-store' });
    if (!response.ok) return { ok: false, reason: `HTTP ${response.status}` };
    const type = response.headers.get('content-type') ?? '';
    const size = (await response.arrayBuffer()).byteLength;
    return type.startsWith('image/') && size > 0 ? { ok: true } : { ok: false, reason: type === '' ? 'empty' : type };
  } catch (error) {
    return { ok: false, reason: controller.signal.aborted ? t('runner.cameraTimeout', { sec: CAMERA_PROBE_MS / 1000 }) : String((error as Error)?.message ?? error) };
  } finally {
    clearTimeout(timer);
    // 끝나지 않는 영상을 계속 받지 않게 끊는다.
    controller.abort();
  }
};

let cameraProbe: CameraProbe = defaultCameraProbe;

/** 검사가 영상 확인을 바꿔 끼운다. `null` 이면 원래대로. */
export function setCameraProbe(probe: CameraProbe | null): void {
  cameraProbe = probe ?? defaultCameraProbe;
}

// ── 판을 연다 ─────────────────────────────────────────────────────────────────

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);

function judgesOf(view: MissionView): Record<string, Judge> | null {
  const judges = view.params.judges as Record<string, Judge> | undefined;
  return judges !== undefined && judges !== null && typeof judges === 'object' ? judges : null;
}

/** 이 편의 판을 이 실행기가 모는가 — 대본이 판정 방식을 적었을 때만이다. */
export function runnerDrives(view: MissionView): boolean {
  return localDriven(view.missionId) && judgesOf(view) !== null;
}

function claim(view: MissionView): readonly string[] {
  run = null;
  approvedGates = new Set();
  setGate(null);
  if (!runnerDrives(view)) return [];
  const judges = judgesOf(view)!;
  const spec = mapSpecOf(view.params);
  const bindings = slotBindings();
  const walks = new Map<string, Walk>();
  const yaw: Record<string, number> = {};
  for (const device of spec?.devices ?? []) {
    const deviceId = bindings[device.slot] ?? null;
    yaw[device.slot] = device.start_yaw_deg ?? 0;
    walks.set(device.slot, {
      slot: device.slot, deviceId, device,
      mode: deviceId !== null && canWalk(deviceId) ? 'walking' : 'held',
      state: 'idle', marks: new Set(), failure: null, haltedBy: null,
      steps: [], reads: [], lengthM: 0, commandId: null,
    });
  }
  const tasks: TaskRun[] = [];
  for (const task of view.tasks) {
    const judge = judges[task.id];
    if (judge === undefined) continue;
    const slot = 'slot' in judge ? judge.slot : undefined;
    const walk = slot === undefined ? undefined : walks.get(slot);
    const moves = judge.kind === 'move' || judge.kind === 'face';
    tasks.push({
      id: task.id,
      deps: task.deps,
      criterion: task.evaluation?.criteria[0] ?? null,
      judge,
      phase: 'waiting',
      startedAt: 0,
      asked: false,
      outcome: null,
      retry: !moves,
      held: judge.kind === 'hold' || (moves && walk?.mode !== 'walking') || ('soft' in judge && typeof judge.soft === 'number'),
      lastProgressAt: -Infinity,
      haltedBy: null,
    });
  }
  const params = view.params;
  run = {
    missionId: view.missionId,
    view,
    spec,
    tasks,
    walks,
    yaw,
    holdSec: num(params.hold_sec) ?? DEFAULT_HOLD_SEC,
    fovDeg: num(params.camera_fov_deg) ?? DEFAULT_FOV_DEG,
    minBatteryPct: num(params.min_battery_pct) ?? 30,
    stopMaxM: num(params.stop_distance_max_m) ?? 1,
    minGapM: num(params.min_path_gap_m) ?? 1,
    busy: new Set(),
  };
  /**
   * **로봇 명령의 관문을 연다** — 걸을 장비가 있을 때만. 발행기는 승인된 판에서만 낸다(`canIssueRobotCommand`).
   * 이 편은 문 찾기 흐름을 선언하지 않았으므로 스캔은 여전히 안 나간다(`doorScanFlow`).
   */
  if ([...walks.values()].some((walk) => walk.mode === 'walking')) markApproved();
  return tasks.map((task) => task.id);
}

function heldTasks(): readonly string[] {
  return run?.tasks.filter((task) => task.held).map((task) => task.id) ?? [];
}

// ── 한 걸음 ───────────────────────────────────────────────────────────────────

let ticking = false;
let again = false;

/** 판이 바뀔 때마다. 기록을 더하면 저장소가 다시 부르므로 겹쳐 돌지 않게 한 번 더 돌 표시만 한다. */
function tick(): void {
  if (ticking) { again = true; return; }
  ticking = true;
  try {
    let guard = 0;
    do {
      again = false;
      step();
      guard += 1;
    } while (again && guard < 50);
  } finally {
    ticking = false;
  }
}

function step(): void {
  if (gate !== null && (run === null || currentMission().missionId !== gate.missionId || localRunPhase() === null || localRunPhase() === 'done')) setGate(null);
  if (run === null || localRunPhase() !== 'running') return;
  if (currentMission().missionId !== run.missionId) return;
  const head = getMissionState().headSec;
  const done = new Set(traceEvents().filter((event) => event.status === 'done').map((event) => event.nodeId));
  for (const task of run.tasks) {
    if (localRunPhase() !== 'running') return;
    if (task.phase === 'waiting' && task.deps.every((dep) => done.has(dep))) begin(run, task, head);
    if (task.phase === 'running') poll(run, task, head);
  }
}

function producerOf(task: TaskRun): Producer {
  switch (task.judge.kind) {
    case 'online': case 'link': case 'battery': case 'ready': case 'camera':
      return 'robot';
    case 'face': case 'move':
      return task.held ? 'backend' : 'robot';
    default:
      return 'backend';
  }
}

function deviceOfSlot(r: Run, slot: string): string | null {
  return r.walks.get(slot)?.deviceId ?? slotBindings()[slot] ?? null;
}

function begin(r: Run, task: TaskRun, head: number): void {
  task.phase = 'running';
  task.startedAt = head;
  task.asked = false;
  task.outcome = null;
  task.haltedBy = null;
  const slot = 'slot' in task.judge ? task.judge.slot : undefined;
  const device = slot === undefined ? null : deviceOfSlot(r, slot);
  appendLiveEvent(r.missionId, task.id, 'running', 'started', device === null ? {} : { device }, producerOf(task));
}

function finish(r: Run, task: TaskRun, payload: Record<string, unknown>): void {
  task.phase = 'done';
  const producer = producerOf(task);
  // 평가 노드다 — 판정 기준을 먼저 적고 근거와 함께 끝낸다(대본의 평가 태스크와 같은 두 줄).
  if (task.criterion !== null) appendLiveEvent(r.missionId, task.id, 'awaiting_evaluation', 'evaluated', { criterion: task.criterion }, producer);
  appendLiveEvent(r.missionId, task.id, 'done', 'evaluated', payload, producer);
}

function fail(r: Run, task: TaskRun, reason: string): void {
  task.phase = 'failed';
  appendLiveEvent(r.missionId, task.id, 'failed', 'failed', { message: reason }, producerOf(task));
  const title = r.view.tasks.find((item) => item.id === task.id)?.title ?? task.id;
  noteIssue(`task:${task.id}`, 'robot', t('runner.failed', { task: `${task.id} ${title}`, reason }));
  // 사람이 멈춘 것이 아니면 판을 세운다 — 못 한 채로 다음 노드가 칠해지면 안 된다.
  if (task.haltedBy === null) haltLocalRunOnFailure();
}

/** 정해진 시간을 채웠는가. 판의 머리로 잰다 — 일시정지하면 시간도 선다. */
function held(r: Run, task: TaskRun, head: number): boolean {
  return head - task.startedAt >= holdSecOf(r, task);
}

/** 이 노드의 유지 시간. 노드가 따로 적었으면 그것, 아니면 판의 `hold_sec`. */
function holdSecOf(r: Run, task: TaskRun): number {
  const own = task.judge.kind === 'hold' ? task.judge.sec : undefined;
  return typeof own === 'number' && Number.isFinite(own) && own > 0 ? own : r.holdSec;
}

/** 값을 기다리다 한도를 넘었는가. */
function timedOut(task: TaskRun, head: number): boolean {
  return head - task.startedAt >= CHECK_TIMEOUT_SEC;
}

/** 이 확인 노드의 유예(초). 없으면 null — 실제 판정 그대로다. */
function softSecOf(task: TaskRun): number | null {
  const judge = task.judge;
  if (judge.kind !== 'online' && judge.kind !== 'link' && judge.kind !== 'battery' && judge.kind !== 'ready' && judge.kind !== 'camera') return null;
  return typeof judge.soft === 'number' && Number.isFinite(judge.soft) && judge.soft >= 0 ? judge.soft : null;
}

/**
 * **유예가 있는 확인** (260929). 실제 판정이 먼저다 — 통과하면 그 값으로 끝낸다. 실패하거나 값이 안 오면 실패로 세우지
 * 않고, 유예 시간이 지나면 완료로 칠한다. 근거값에는 받은 만큼만 적는다(지어 넣지 않는다).
 */
function pollSoft(r: Run, task: TaskRun, head: number, soft: number): void {
  const judge = task.judge as Extract<Judge, { kind: 'online' | 'link' | 'battery' | 'ready' | 'camera' }>;
  const deviceId = deviceOfSlot(r, judge.slot);
  if (task.outcome !== null && task.outcome.ok) { const payload = task.outcome.payload; task.outcome = null; finish(r, task, payload); return; }
  if (deviceId !== null) {
    if (judge.kind === 'online' || judge.kind === 'battery' || judge.kind === 'ready') {
      const outcome = deviceJudge(r, judge.kind, deviceId);
      if (outcome !== null && outcome.ok) { finish(r, task, outcome.payload); return; }
    } else if (!task.asked) {
      task.asked = true;
      void (judge.kind === 'link' ? linkJudge(deviceId) : cameraJudge(deviceId)).then((outcome) => {
        if (task.phase !== 'running') return;
        task.outcome = outcome;
        tick();
      });
    }
  }
  if (head - task.startedAt < soft) return;
  finish(r, task, {
    ...(deviceId === null ? {} : { device: deviceId }),
    ...(judge.kind === 'battery' ? { min_battery_pct: r.minBatteryPct } : {}),
    hold_s: soft,
  });
}

function poll(r: Run, task: TaskRun, head: number): void {
  const judge = task.judge;
  const soft = softSecOf(task);
  if (soft !== null) { pollSoft(r, task, head, soft); return; }
  // 비동기 판정의 답이 와 있으면 그것으로 끝낸다.
  if (task.outcome !== null) {
    const outcome = task.outcome;
    task.outcome = null;
    if (outcome.ok) finish(r, task, outcome.payload);
    else fail(r, task, outcome.reason);
    return;
  }
  switch (judge.kind) {
    case 'hold':
      if (held(r, task, head)) finish(r, task, { ...holdPayload(r, judge), hold_s: holdSecOf(r, task) });
      return;
    case 'report':
      finish(r, task, {
        tasks_done: r.tasks.filter((item) => item.phase === 'done').length,
        devices_moved: [...r.walks.values()].filter((walk) => walk.marks.has('arrive') || walk.state === 'ended').length,
      });
      return;
    case 'map-target': case 'map-pose': case 'map-path': case 'map-gap': case 'map-bearing': case 'map-view': {
      const outcome = mapJudge(r, judge);
      if (outcome.ok) finish(r, task, outcome.payload);
      else fail(r, task, outcome.reason);
      return;
    }
    case 'online': case 'battery': case 'ready': {
      const deviceId = deviceOfSlot(r, judge.slot);
      if (deviceId === null) { fail(r, task, t('runner.noDevice', { slot: slotLabel(r, judge.slot) })); return; }
      const outcome = deviceJudge(r, judge.kind, deviceId);
      if (outcome === null) {
        if (timedOut(task, head)) fail(r, task, t('runner.timeout', { sec: CHECK_TIMEOUT_SEC, reason: waitingReason(judge.kind, deviceId) }));
        return;
      }
      if (outcome.ok) finish(r, task, outcome.payload);
      else fail(r, task, outcome.reason);
      return;
    }
    case 'link': case 'camera': {
      const deviceId = deviceOfSlot(r, judge.slot);
      if (deviceId === null) { fail(r, task, t('runner.noDevice', { slot: slotLabel(r, judge.slot) })); return; }
      if (!task.asked) {
        task.asked = true;
        void (judge.kind === 'link' ? linkJudge(deviceId) : cameraJudge(deviceId)).then((outcome) => {
          if (task.phase !== 'running') return;
          task.outcome = outcome;
          tick();
        });
      }
      return;
    }
    case 'face':
      faceJudge(r, task, judge.slot, head);
      return;
    case 'move':
      moveJudge(r, task, judge.slot, judge.phase, head);
      return;
  }
}

function slotLabel(r: Run, slot: string): string {
  return r.view.slots?.find((item) => item.id === slot)?.label ?? slot;
}

// ── 장비 값 ───────────────────────────────────────────────────────────────────

/** 판정할 값이 아직 없으면 `null` — 기다린다. */
function deviceJudge(r: Run, kind: 'online' | 'battery' | 'ready', deviceId: string): Outcome | null {
  const state = deviceState(deviceId);
  if (kind === 'online') {
    const seen = connectedDevice(deviceId);
    const alive = seen !== null || (state !== null && state.online === true && !isStale(state));
    if (!alive) return null;
    const lastMs = Math.max(seen?.lastSeenMs ?? 0, state?.lastSeenMs ?? 0);
    return { ok: true, payload: { device: deviceId, online: true, heartbeat_age_s: Math.max(0, Math.round((Date.now() - lastMs) / 1000)) } };
  }
  if (kind === 'battery') {
    const pct = num(telemetryValue(deviceId, 'battery_pct')) ?? num(telemetryValue(deviceId, 'battery.remaining_pct')) ?? state?.batteryPct ?? null;
    if (pct === null) return null;
    const rounded = Math.round(pct);
    if (pct < r.minBatteryPct) return { ok: false, reason: t('runner.batteryLow', { pct: rounded, min: r.minBatteryPct }) };
    return { ok: true, payload: { device: deviceId, battery_pct: rounded, min_battery_pct: r.minBatteryPct } };
  }
  // ready — 곧바로 판정한다. 기다릴 값이 아니라 「지금 막힌 것이 있는가」다.
  const status = telemetryValue(deviceId, 'device_status') ?? state?.health ?? null;
  const armed = telemetryValue(deviceId, 'flight.armed');
  const landed = telemetryValue(deviceId, 'flight.landed_state');
  if (armed === true) return { ok: false, reason: t('runner.armed') };
  if (status === 'fault') return { ok: false, reason: t('runner.fault') };
  return {
    ok: true,
    payload: {
      device: deviceId,
      device_status: typeof status === 'string' ? status : null,
      ...(typeof armed === 'boolean' ? { armed } : {}),
      ...(typeof landed === 'string' ? { landed_state: landed } : {}),
    },
  };
}

function waitingReason(kind: 'online' | 'battery' | 'ready', deviceId: string): string {
  if (kind === 'online') return t('runner.notConnected', { device: deviceId });
  if (kind === 'battery') return t('runner.noBattery', { device: deviceId });
  return t('runner.noState', { device: deviceId });
}

/** 통신 링크 — `ping` 왕복 한 번. FC 링크를 말하는 장비는 그것까지 본다. */
async function linkJudge(deviceId: string): Promise<Outcome> {
  const client = clientForDevice(deviceId);
  if (client === null) return { ok: false, reason: t('runner.noClient', { device: deviceId }) };
  const ping = await issuePing(client);
  if (!ping.ok) return { ok: false, reason: ping.message };
  if (ping.fcLink === false) return { ok: false, reason: t('runner.fcLinkDown') };
  const link = telemetryValue(deviceId, 'link') ?? deviceState(deviceId)?.link ?? null;
  if (typeof link === 'string' && link !== 'ok') return { ok: false, reason: t('runner.linkBad', { link }) };
  return {
    ok: true,
    payload: {
      device: deviceId,
      link: typeof link === 'string' ? link : 'ok',
      rtt_ms: ping.roundTripMs,
      ...(ping.fcLink === null ? {} : { fc_link: ping.fcLink }),
    },
  };
}

/** 카메라 — 그 장비의 영상 주소에서 한 장(또는 첫 응답)이 오는가. */
async function cameraJudge(deviceId: string): Promise<Outcome> {
  const source = directCameraUrl(deviceId, 'front');
  if (source === null) return { ok: false, reason: t('runner.noCamera', { device: deviceId }) };
  const probe = await cameraProbe(source);
  if (!probe.ok) return { ok: false, reason: t('runner.cameraFailed', { reason: probe.reason ?? t('robot.noReason') }) };
  return { ok: true, payload: { device: deviceId, camera_frames: true, via: source.kind === 'stream' ? 'stream' : 'frames' } };
}

// ── 가상 맵 ───────────────────────────────────────────────────────────────────

function mapDevice(r: Run, slot: string): MapDevice | null {
  return r.spec?.devices.find((device) => device.slot === slot) ?? null;
}

function startPoseOf(r: Run, device: MapDevice): Record<string, number> {
  return { x: device.start.x, z: device.start.z, yaw_deg: r2(r.yaw[device.slot] ?? device.start_yaw_deg ?? 0) };
}

function mapJudge(r: Run, judge: MapJudge): Outcome {
  const spec = r.spec;
  if (spec === null) return { ok: false, reason: t('runner.noMap') };
  const frame = spec.frame ?? 'site-global';
  switch (judge.kind) {
    case 'map-target':
      return { ok: true, payload: { source: 'virtual-map', x: spec.target.x, z: spec.target.z, frame } };
    case 'map-pose': {
      const poses: Record<string, unknown> = {};
      for (const slot of judge.slots) {
        const device = mapDevice(r, slot);
        if (device === null) return { ok: false, reason: t('runner.noMapDevice', { slot: slotLabel(r, slot) }) };
        poses[slot] = startPoseOf(r, device);
      }
      return { ok: true, payload: { source: 'virtual-map', pose_frame: frame, ...poses } };
    }
    case 'map-path': {
      const device = mapDevice(r, judge.slot);
      if (device === null) return { ok: false, reason: t('runner.noMapDevice', { slot: slotLabel(r, judge.slot) }) };
      const plan = planOf(r, device);
      return {
        ok: true,
        payload: {
          source: 'virtual-map',
          ...(deviceOfSlot(r, judge.slot) === null ? {} : { device: deviceOfSlot(r, judge.slot) }),
          route: routeWords(plan.steps),
          waypoints: device.path.length,
          path_length_m: r2(plan.lengthM),
          steps: plan.reads.join(' · '),
        },
      };
    }
    case 'map-gap': {
      const devices = spec.devices;
      let minGapM = Infinity;
      let crossing = false;
      for (let a = 0; a < devices.length; a += 1) {
        for (let b = a + 1; b < devices.length; b += 1) {
          const gap = pathGap(devices[a].path, devices[b].path);
          minGapM = Math.min(minGapM, gap.minGapM);
          crossing = crossing || gap.crossing;
        }
      }
      if (!Number.isFinite(minGapM)) return { ok: true, payload: { paths: devices.length } };
      if (crossing) return { ok: false, reason: t('runner.pathsCross') };
      if (minGapM < r.minGapM) return { ok: false, reason: t('runner.pathsTooClose', { gap: r2(minGapM), min: r.minGapM }) };
      return { ok: true, payload: { min_gap_m: r2(minGapM), min_path_gap_m: r.minGapM, crossing: false } };
    }
    case 'map-bearing': case 'map-view': {
      const device = mapDevice(r, judge.slot);
      if (device === null) return { ok: false, reason: t('runner.noMapDevice', { slot: slotLabel(r, judge.slot) }) };
      const view = viewOf(device.start, r.yaw[judge.slot] ?? 0, spec.target, r.fovDeg);
      if (judge.kind === 'map-bearing') {
        return { ok: true, payload: { source: 'virtual-map', bearing_deg: r2(view.bearingDeg), relative_deg: r2(view.relativeDeg), distance_m: r2(view.distanceM) } };
      }
      return { ok: true, payload: { relative_deg: r2(view.relativeDeg), half_fov_deg: r2(view.halfFovDeg), in_view: view.inView } };
    }
  }
  return { ok: false, reason: t('runner.noMap') };
}

/**
 * **경로를 사람이 읽는 한 줄로** (260929). 「왼쪽 45° 회전 → 2.00 m 전진」. 가상 맵 경로에서 푼 걸음을 그대로
 * 말로 옮긴다 — 경로 탐지 노드의 근거값이 「이렇게 산출됐다」를 이 줄로 보인다.
 */
function routeWords(steps: readonly TaskCommand[]): string {
  const words: string[] = [];
  let forward = 0;
  const flush = () => {
    if (forward > 0) words.push(t('runner.route.forward', { m: forward.toFixed(2) }));
    forward = 0;
  };
  for (const step of steps) {
    if (step.action === 'move_forward') { forward += Number(step.parameters?.distance_m ?? 0); continue; }
    flush();
    if (step.action === 'turn') {
      const deg = Number(step.parameters?.deg ?? 0);
      words.push(t(deg < 0 ? 'runner.route.left' : 'runner.route.right', { deg: Number(Math.abs(deg).toFixed(1)) }));
    }
  }
  flush();
  return words.join(' → ');
}

/** 그 자리 장치의 경로를 지금 방위에서 푼다. */
function planOf(r: Run, device: MapDevice) {
  return pathStepCommands(device.path, r.yaw[device.slot] ?? device.start_yaw_deg ?? 0, device.arrive_task, STEP_VX);
}

function holdPayload(r: Run, judge: Extract<Judge, { kind: 'hold' }>): Record<string, unknown> {
  const spec = r.spec;
  if (spec === null || judge.show === undefined) return {};
  switch (judge.show) {
    case 'target':
      return { source: 'virtual-map', x: spec.target.x, z: spec.target.z, frame: spec.frame ?? 'site-global' };
    case 'pose': {
      const poses: Record<string, unknown> = {};
      for (const device of spec.devices) poses[device.slot] = startPoseOf(r, device);
      return { source: 'virtual-map', pose_frame: spec.frame ?? 'site-global', ...poses };
    }
    case 'path': {
      const device = judge.slot === undefined ? null : mapDevice(r, judge.slot);
      if (device === null) return {};
      // 걸을 수 없는 장치(드론)도 경로 산출 결과는 같은 꼴로 남긴다 — 명령을 안 낼 뿐 경로는 같은 계산이다.
      const plan = planOf(r, device);
      return {
        source: 'virtual-map',
        ...(deviceOfSlot(r, device.slot) === null ? {} : { device: deviceOfSlot(r, device.slot) }),
        route: routeWords(plan.steps),
        waypoints: device.path.length,
        path_length_m: r2(pathLengthM(device.path)),
        steps: plan.reads.join(' · '),
      };
    }
    case 'rationale':
      return { reason: t('runner.rationale', { x: spec.target.x, z: spec.target.z }), image_ref: null };
  }
  return {};
}

// ── 돌기 · 걷기 ───────────────────────────────────────────────────────────────

/**
 * **@ 쪽으로 방향 맞추기** — 시야 안이면 안 돈다. 밖이면 걸을 수 있는 장비는 실제로 한 번 돌고, 못 걷는 장비는
 * 정해진 시간을 채워 넘긴다. 어느 쪽이든 그 뒤의 경로는 @ 쪽을 본 방위에서 푼다.
 */
function faceJudge(r: Run, task: TaskRun, slot: string, head: number): void {
  const device = mapDevice(r, slot);
  if (r.spec === null || device === null) { fail(r, task, t('runner.noMapDevice', { slot: slotLabel(r, slot) })); return; }
  const view = viewOf(device.start, r.yaw[slot] ?? 0, r.spec.target, r.fovDeg);
  if (view.inView) {
    finish(r, task, { in_view: true, turned_deg: 0 });
    return;
  }
  const walk = r.walks.get(slot);
  if (task.held || walk === undefined || walk.deviceId === null) {
    if (!held(r, task, head)) return;
    r.yaw[slot] = view.bearingDeg;
    finish(r, task, { in_view: false, planned_turn_deg: r2(view.relativeDeg), hold_s: r.holdSec });
    return;
  }
  if (task.asked) return;
  task.asked = true;
  const deviceId = walk.deviceId;
  const plan = turnStepCommands(view.relativeDeg, task.id);
  const client = clientForDevice(deviceId);
  r.busy.add(deviceId);
  void issueStepsToEnd(client, plan.steps).then((outcome) => {
    r.busy.delete(deviceId);
    if (task.phase !== 'running') return;
    if (outcome.sent === true) {
      r.yaw[slot] = view.bearingDeg;
      task.outcome = { ok: true, payload: { device: deviceId, in_view: false, turned_deg: r2(view.relativeDeg), steps: plan.reads.join(' · '), command_id: outcome.commandId } };
    } else {
      task.outcome = { ok: false, reason: task.haltedBy === null ? (outcome.reason ?? t('robot.noReason')) : t(task.haltedBy === 'stop' ? 'smove.stopped' : 'smove.paused') };
    }
    tick();
  });
}

/** 이 자리에서 「움직이는 동안」에 해당하는 단계 — 지도가 이 단계 동안 장치를 경로 위로 옮긴다. */
function movingPhase(r: Run, slot: string): MovePhase {
  const phases = r.tasks.flatMap((task) => (task.judge.kind === 'move' && task.judge.slot === slot ? [task.judge.phase] : []));
  return phases.includes('follow') ? 'follow' : 'arrive';
}

/** 지도에 장치 위치를 옮기라고 남긴다. 1초에 한 번까지. */
function progress(r: Run, task: TaskRun, slot: string, fraction: number, head: number, force = false): void {
  if (!force && head - task.lastProgressAt < 1) return;
  task.lastProgressAt = head;
  appendLiveEvent(r.missionId, task.id, 'running', 'progress', { slot, fraction: r2(Math.max(0, Math.min(1, fraction))) }, producerOf(task));
}

/**
 * 승인을 기다려야 하면 참을 돌려준다(끝내지 않는다). 기다리는 동안 머리줄에 승인 대기를 건다.
 */
function awaitingApproval(r: Run, task: TaskRun): boolean {
  const confirm = task.judge.kind === 'move' ? task.judge.confirm : undefined;
  if (confirm === undefined || approvedGates.has(task.id)) return false;
  const device = mapDevice(r, confirm);
  const plan = device === null ? null : planOf(r, device);
  setGate({
    missionId: r.missionId,
    taskId: task.id,
    slot: confirm,
    deviceId: deviceOfSlot(r, confirm),
    route: plan === null ? '' : routeWords(plan.steps),
    lengthM: plan === null ? 0 : r2(plan.lengthM),
  });
  return true;
}

function moveJudge(r: Run, task: TaskRun, slot: string, phase: MovePhase, head: number): void {
  const walk = r.walks.get(slot);
  if (walk === undefined) { fail(r, task, t('runner.noMapDevice', { slot: slotLabel(r, slot) })); return; }
  const moving = movingPhase(r, slot) === phase;
  const plannedToTargetM = r.spec === null ? null : (() => {
    const end = walk.device.path[walk.device.path.length - 1];
    return end === undefined ? null : r2(Math.hypot(end[0] - r.spec.target.x, end[1] - r.spec.target.z));
  })();

  if (task.held) {
    if (moving && !held(r, task, head)) progress(r, task, slot, (head - task.startedAt) / holdSecOf(r, task), head);
    if (!held(r, task, head)) return;
    if (moving && task.lastProgressAt < task.startedAt + holdSecOf(r, task)) progress(r, task, slot, 1, head, true);
    if (awaitingApproval(r, task)) return;
    if (phase === 'arrive' && plannedToTargetM !== null && plannedToTargetM > r.stopMaxM) {
      fail(r, task, t('runner.tooFar', { dist: plannedToTargetM, max: r.stopMaxM }));
      return;
    }
    walk.marks.add(phase);
    if (phase === 'end' || (phase === 'arrive' && !hasPhase(r, slot, 'end'))) walk.state = 'ended';
    finish(r, task, {
      ...(walk.deviceId === null ? {} : { device: walk.deviceId }),
      planned_path_m: r2(pathLengthM(walk.device.path)),
      ...(phase === 'arrive' && plannedToTargetM !== null ? { planned_distance_to_target_m: plannedToTargetM } : {}),
      hold_s: r.holdSec,
      ...(approvedGates.has(task.id) ? { approved_by: 'human' } : {}),
    });
    return;
  }

  if (walk.state === 'idle') startWalk(r, walk);
  if (walk.failure !== null) { fail(r, task, walk.failure); return; }
  if (!walk.marks.has(phase)) return;
  if (awaitingApproval(r, task)) return;
  const base = { device: walk.deviceId, planned_path_m: r2(walk.lengthM) };
  switch (phase) {
    case 'prepare':
      finish(r, task, { ...base, steps: walk.reads.join(' · ') });
      return;
    case 'start':
      finish(r, task, { ...base, command_id: walk.commandId });
      return;
    case 'follow':
      finish(r, task, { ...base, commands: walk.steps.length });
      return;
    case 'stop':
      finish(r, task, { ...base, ended_by: 'SUCCEEDED' });
      return;
    case 'arrive':
      if (plannedToTargetM !== null && plannedToTargetM > r.stopMaxM) {
        fail(r, task, t('runner.tooFar', { dist: plannedToTargetM, max: r.stopMaxM }));
        return;
      }
      // **실측 거리가 아니다.** 로봇은 「다 걸었다」만 말하고 어디에 섰는지는 말하지 않는다 — 계획한 경로 끝과
      // 대상 사이의 거리라서 이름에 planned 를 붙였다.
      finish(r, task, {
        ...base,
        ended_by: 'SUCCEEDED',
        commands: walk.steps.length,
        ...(plannedToTargetM === null ? {} : { planned_distance_to_target_m: plannedToTargetM }),
        source: 'robot',
      });
      return;
    case 'end':
      finish(r, task, { device: walk.deviceId });
      return;
  }
}

function hasPhase(r: Run, slot: string, phase: MovePhase): boolean {
  return r.tasks.some((task) => task.judge.kind === 'move' && task.judge.slot === slot && task.judge.phase === phase);
}

/** 지금 이 자리에서 도는 이동 태스크 — 진행을 여기에 남긴다. */
function runningMoveTask(r: Run, slot: string): TaskRun | null {
  return r.tasks.find((task) => task.phase === 'running' && task.judge.kind === 'move' && task.judge.slot === slot) ?? null;
}

function startWalk(r: Run, walk: Walk): void {
  walk.state = 'going';
  const deviceId = walk.deviceId!;
  const stepsTask = r.tasks.find((task) => task.judge.kind === 'move' && task.judge.slot === walk.slot && task.judge.phase === movingPhase(r, walk.slot))?.id
    ?? walk.device.arrive_task;
  const plan = pathStepCommands(walk.device.path, r.yaw[walk.slot] ?? walk.device.start_yaw_deg ?? 0, stepsTask, STEP_VX);
  walk.steps = plan.steps;
  walk.reads = plan.reads;
  walk.lengthM = plan.lengthM;
  walk.marks.add('prepare');
  if (plan.steps.length === 0) {
    for (const phase of ['start', 'follow', 'stop', 'arrive', 'end'] as const) walk.marks.add(phase);
    walk.state = 'ended';
    return;
  }
  // 걸음마다 경로 위 어디쯤인지 — 직진 거리로 잰다(회전은 제자리다).
  const forward = plan.steps.map((command) => (command.action === 'move_forward' ? Number(command.parameters?.distance_m ?? 0) : 0));
  const total = forward.reduce((sum, value) => sum + value, 0) || 1;
  const before = forward.map((_, index) => forward.slice(0, index).reduce((sum, value) => sum + value, 0));
  const client = clientForDevice(deviceId);
  r.busy.add(deviceId);
  void issueStepsToEnd(client, plan.steps, (order, issued) => {
    if (order === 0) {
      walk.commandId = issued.commandId;
      walk.marks.add('start');
    }
    if (order === plan.steps.length - 1) walk.marks.add('follow');
    const task = runningMoveTask(r, walk.slot);
    if (task !== null) progress(r, task, walk.slot, before[order] / total, getMissionState().headSec, true);
    tick();
  }).then((outcome) => {
    r.busy.delete(deviceId);
    walk.state = 'ended';
    if (outcome.sent === true) {
      for (const phase of ['start', 'follow', 'stop', 'arrive', 'end'] as const) walk.marks.add(phase);
      const task = runningMoveTask(r, walk.slot);
      if (task !== null) progress(r, task, walk.slot, 1, getMissionState().headSec, true);
    } else {
      walk.failure = walk.haltedBy === null ? (outcome.reason ?? t('robot.noReason')) : t(walk.haltedBy === 'stop' ? 'smove.stopped' : 'smove.paused');
      const task = runningMoveTask(r, walk.slot);
      if (task !== null) task.haltedBy = walk.haltedBy;
    }
    tick();
  });
}

// ── 멈춤 · 이어 가기 ──────────────────────────────────────────────────────────

/** 사람이 멈췄다 — **명령을 내고 있는 장비에만** 정지를 보낸다. 넘기는 장비(드론)에는 아무것도 안 보낸다. */
function halt(kind: 'pause' | 'stop'): void {
  if (run === null) return;
  for (const walk of run.walks.values()) if (walk.state === 'going') walk.haltedBy = kind;
  for (const task of run.tasks) if (task.phase === 'running' && task.judge.kind === 'face' && task.asked) task.haltedBy = kind;
  for (const deviceId of run.busy) {
    const client = clientForDevice(deviceId);
    void (kind === 'stop' ? emergencyStop(client) : pauseMission(client));
  }
}

/** 이어 가기 — 명령 잠금을 풀고, 실패한 **확인**은 다시 한다. 멈춘 이동은 다시 걷지 않는다(머리말). */
function resume(): void {
  if (robotSession().paused !== null) releasePaused();
  if (run === null) return;
  for (const task of run.tasks) {
    if (task.phase === 'failed' && task.retry) {
      task.phase = 'waiting';
      task.asked = false;
      task.outcome = null;
      task.haltedBy = null;
    }
  }
}

let started = false;

/** 앱이 살아 있는 동안 한 번 건다 — 노드를 눌러 화면을 옮겨도 끊기면 안 된다(`startNavLink` 와 같은 자리). */
export function startTaskRunner(): () => void {
  if (started) return () => undefined;
  started = true;
  registerLiveMoveHooks({ claim, halt, resume, heldTasks });
  const off = subscribeMission(tick);
  return () => {
    off();
    registerLiveMoveHooks(null);
    run = null;
    started = false;
  };
}
