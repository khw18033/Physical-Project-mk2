/**
 * src/physical/navLink.ts (260915 신설 — 자율주행 편 · pi1 중계)
 *
 * **pi1 이 전해 준 것 → 태스크 노드.** `missionLink.ts` 가 문 찾기 편에 하는 일을 자율주행
 * 편에 한다. 다른 점은 하나 — 화면이 낸 명령의 응답이 아니라 **유니티가 낸 명령을 pi1 이
 * 본 것**이다. 그래서 명령 표(`robotSession.commands`)를 안 쓰고 사건을 직접 옮긴다.
 *
 * ## pi1 이 관여하는 노드 넷 (260915 지시)
 *
 *   T-NA1 로봇 배터리 확인   nav_state.battery_pct — 판을 연 뒤의 지금 값이 기준 이상이면 완료
 *   T-NA2 로봇 위치 확인     nav_state.yaw_deg — **yaw 만** 쓴다
 *   T-NB4 목적지까지 이동    path_received 로 시작 · path_done(브리지 mode 99)으로 완료
 *   T-NB3 경로 재탐색        path_cancel 로 시작 · 다음 path_received 로 완료
 *
 * 나머지(이동경로 탐색 · 장애물 탐지 · 목적지 도착 · 임무 종료)는 **pi1 이 모르는 일**이다.
 * 여기서 칠하지 않는다 — 다른 연동이 붙을 때까지 대기로 남는 것이 사실이다.
 *
 * ## 되돌아감은 회차로 적는다
 *
 * 유니티가 경로를 바꾸면 pi1 에 `PATH_CANCEL` 이 먼저 오고 새 `go1_path` 가 뒤따른다. 그 한 번이
 * 「이동(n회차) 끝 → 재탐색 → 이동(n+1회차)」이다. 대본의 2회차와 같은 모양(`derived`)이다.
 */

import { currentMission, receiveRobotProgress } from '../data/scenario.ts';
import type { ScenarioEvent, TaskStatus } from '../model/types.ts';
import { isReplayingRecord } from '../record/replayMode.ts';
import { noteIssue } from '../shared/notifications.ts';
import { eventTimeMs, isCancelStop, NAV_FRESH_MS, navFeedState, subscribeNav, type NavEvent } from './navFeed.ts';
import { navRun, subscribeNavRun, type NavRun } from './navRun.ts';
import { robotSession } from './robotSession.ts';

export const NAV_TASKS = {
  battery: 'T-NA1',
  yaw: 'T-NA2',
  replan: 'T-NB3',
  move: 'T-NB4',
} as const;

/**
 * **pi1 이 직접 주지 않는 넷 — 받은 것으로 끝내는 규칙** (260915 지시 「네 제안대로」).
 *
 *   T-NB1 이동경로 탐색  위치 확인 뒤 진행 중(유니티 경로를 기다린다) · pi1 이 **처음 경로를 받으면** 완료
 *   T-NB2 장애물 탐지    AI 서버의 장애물 JSON 이 판 안에서 **처음 오면** 진행 중 · 가까운 장애물이 바뀔 때마다
 *                        진행 줄 · 목적지 도착과 함께 완료. JSON 이 한 번도 안 왔으면 대기로 남는다(탐지를 안 한 것이다)
 *   T-NB5 목적지 도착    **경로 끝(mode 99)** — 평가 대기 → 완료. 거리 기준은 목적지 좌표가 없어 판정하지 않는다
 *   T-NC1 임무 종료      목적지 도착 뒤 곧바로 완료
 *
 * 목적지에 닿았는데 재탐색이 한 번도 없었으면 「경로 재탐색」을 **0회로 완료**한다 — 그대로 두면 그 노드가
 * 영원히 대기라 마일스톤도 임무도 안 끝난다. 0회라는 사실은 payload(`replans: 0`)에 남긴다.
 *
 * 임무가 끝나면(T-NC1 완료) 뒤에 오는 경로 사건은 **칠하지 않는다** — 끝난 임무의 노드가 다시 진행 중이 되면
 * 이력의 「완료」와 화면이 어긋난다. 받은 사건은 액션 아이템의 줄에는 그대로 남는다.
 */
export const DERIVED_TASKS = {
  plan: 'T-NB1',
  obstacle: 'T-NB2',
  arrive: 'T-NB5',
  end: 'T-NC1',
} as const;

const NAV_TASK_IDS: ReadonlySet<string> = new Set([...Object.values(NAV_TASKS), DERIVED_TASKS.plan, DERIVED_TASKS.arrive]);

/** pi1 중계가 칠하는 노드인가. 액션 아이템이 중계 값을 붙일 자리를 고른다. */
export function isNavTask(taskId: string): boolean {
  return NAV_TASK_IDS.has(taskId);
}

/** 배터리·방위를 이만큼 기다렸는데 안 오면 알림에 한 줄. 노드는 그대로 진행 중이다. */
export const NAV_WAIT_WARN_MS = 15_000;

type Progress = {
  serial: number;
  battery: 'waiting' | 'done' | 'failed';
  yaw: 'idle' | 'waiting' | 'done';
  plan: 'idle' | 'waiting' | 'done';
  obstacle: 'idle' | 'running' | 'done';
  /** 마지막으로 칠한 「가까운 장애물 있음」. 바뀔 때만 진행 줄을 더한다. */
  lastNear: boolean | null;
  moveAttempt: number;
  moveActive: boolean;
  movePathId: number | null;
  replanAttempt: number;
  replanActive: boolean;
  /** 임무 종료까지 칠했다 — 뒤에 오는 사건은 칠하지 않는다. */
  ended: boolean;
};

/** 장애물 JSON 한 건 중 노드가 쓰는 만큼. `src/autodrive/` 의 모양을 이 파일이 알 필요는 없다. */
export type ObstacleSnapshotLike = {
  receivedAtMs: number;
  cameraId: string | null;
  hasNearObstacle: boolean | null;
  detections: ReadonlyArray<{ name: string; distanceCm: number | null; riskLevel: string | null }>;
};

let progress: Progress | null = null;
/** `seq` 대역 — 사람(1M)·생성(2M)·로봇(3M)·탐지(4M)·준비(5M)와 겹치지 않게 6,000,000 부터. */
let seq = 6_000_000;
let warnTimer: ReturnType<typeof setTimeout> | null = null;

function freshProgress(run: NavRun): Progress {
  return {
    serial: run.serial, battery: 'waiting', yaw: 'idle', plan: 'idle', obstacle: 'idle', lastNear: null,
    moveAttempt: 0, moveActive: false, movePathId: null,
    replanAttempt: 0, replanActive: false, ended: false,
  };
}

/** 칠할 수 있는 판인가 — 판이 열려 있고, 그 임무가 지금 화면의 임무이고, 멈추지 않았다. */
function liveRun(): NavRun | null {
  const run = navRun();
  if (run === null || isReplayingRecord()) return null;
  if (currentMission().missionId !== run.missionId) return null;
  // **정지·일시정지 뒤에는 칠하지 않는다** — 다른 로봇 경로와 같은 규칙이다(`applyEffects`).
  // ⚠ 머리줄 정지는 pi7 로 `abort` 를 보낼 뿐 **pi1 의 로봇을 세우지 않는다.** 화면만 멈춘다.
  const session = robotSession();
  if (session.stopped !== null || session.paused !== null) return null;
  return run;
}

function emit(
  run: NavRun,
  nodeId: string,
  status: TaskStatus,
  kind: string,
  payload: Record<string, unknown> = {},
  extra: { attempt?: number; derivedFrom?: string } = {},
  atMs = Date.now(),
): void {
  seq += 1;
  receiveRobotProgress(run.missionId, {
    seq,
    atSec: Math.max(0, (atMs - run.startedAtMs) / 1000),
    nodeId,
    status,
    kind,
    // **pi1 이 본 것이다.** 화면이 판정한 것(배터리 기준)도 값은 pi1 이 보냈다.
    producedBy: 'backend',
    ...(extra.attempt === undefined ? {} : { attempt: extra.attempt }),
    ...(extra.derivedFrom === undefined ? {} : { derivedFrom: extra.derivedFrom }),
    payload,
  } as ScenarioEvent);
}

/** 판이 열렸다 — 배터리 확인부터 진행 중으로. */
function openRun(run: NavRun): void {
  progress = freshProgress(run);
  emit(run, NAV_TASKS.battery, 'running', 'started', {}, {}, run.startedAtMs);
  if (warnTimer !== null) clearTimeout(warnTimer);
  warnTimer = setTimeout(() => {
    warnTimer = null;
    const now = navRun();
    if (now === null || progress === null || now.serial !== progress.serial) return;
    if (progress.battery === 'waiting') noteIssue('nav-battery', 'robot', `${NAV_TASKS.battery} pi1 배터리 값이 ${NAV_WAIT_WARN_MS / 1000}초째 안 옵니다 — 중계(nav_state)를 보세요`);
    else if (progress.yaw === 'waiting') noteIssue('nav-yaw', 'robot', `${NAV_TASKS.yaw} pi1 방위(yaw)가 ${NAV_WAIT_WARN_MS / 1000}초째 안 옵니다 — 중계(nav_state)를 보세요`);
  }, NAV_WAIT_WARN_MS);
  (warnTimer as { unref?: () => void }).unref?.();
  checkTelemetry();
}

/** 배터리 → 방위. **판을 연 무렵 이후에 받은 지금 값**만 친다. */
function checkTelemetry(nowMs = Date.now()): void {
  const run = liveRun();
  if (run === null || progress === null || progress.serial !== run.serial || progress.ended) return;
  const telemetry = navFeedState().telemetry;
  if (telemetry === null) return;
  // 판을 열기 직전 한 주기 안에 온 값까지는 지금 값이다. 그보다 오래됐거나 끊겨서 멈춘 값이면 안 친다.
  const fresh = telemetry.receivedAtMs >= run.startedAtMs - NAV_FRESH_MS && nowMs - telemetry.receivedAtMs <= NAV_FRESH_MS;
  if (!fresh) return;
  const who = { node_id: telemetry.nodeId, entity_id: telemetry.entityId, ...(telemetry.tsMs === null ? {} : { pi_ts_ms: telemetry.tsMs }) };

  if (progress.battery === 'waiting' && telemetry.batteryPct !== null) {
    const params = currentMission().params;
    const min = typeof params.min_battery_pct === 'number' ? params.min_battery_pct : null;
    if (min === null) {
      // 기준이 대본에 없으면 판정하지 않고 받은 값만 남긴다 — 기준을 지어내지 않는다.
      emit(run, NAV_TASKS.battery, 'done', 'evaluated', { battery_pct: telemetry.batteryPct, ...who }, {}, nowMs);
      progress.battery = 'done';
    } else {
      emit(run, NAV_TASKS.battery, 'awaiting_evaluation', 'evaluated', { criterion: `battery_pct >= ${min}` }, {}, nowMs);
      if (telemetry.batteryPct >= min) {
        emit(run, NAV_TASKS.battery, 'done', 'evaluated', { battery_pct: telemetry.batteryPct, min_battery_pct: min, ...who }, {}, nowMs);
        progress.battery = 'done';
      } else {
        emit(run, NAV_TASKS.battery, 'failed', 'failed', {
          code: 'battery_too_low', message: `배터리 ${telemetry.batteryPct}% — 기준 ${min}% 미만`,
          battery_pct: telemetry.batteryPct, min_battery_pct: min, ...who,
        }, {}, nowMs);
        progress.battery = 'failed';
        noteIssue('nav-battery', 'robot', `${NAV_TASKS.battery} 배터리 ${telemetry.batteryPct}% — 기준 ${min}% 미만입니다`);
      }
    }
    // 배터리가 기준 미만이어도 방위는 본다 — 사실을 적는 것이지 임무를 막는 자리가 아니다.
    progress.yaw = 'waiting';
    emit(run, NAV_TASKS.yaw, 'running', 'started', {}, {}, nowMs);
  }
  if (progress.yaw === 'waiting' && telemetry.yawDeg !== null) {
    emit(run, NAV_TASKS.yaw, 'done', 'evaluated', {
      yaw_deg: telemetry.yawDeg, yaw_source: telemetry.yawSource,
      // IMU 방위를 나란히 — 브리지 yaw 의 기준이 경로마다 바뀌어서다(260915 pi1 답신). 안 오면 안 싣는다.
      ...(telemetry.yawOdometryDeg === null ? {} : { yaw_odometry_deg: telemetry.yawOdometryDeg }),
      ...who,
    }, {}, nowMs);
    progress.yaw = 'done';
  }
  // 위치 확인이 끝나면 경로를 기다린다 — 경로를 계산하는 것은 유니티이고, pi1 이 받는 순간 끝난다.
  if (progress.yaw === 'done' && progress.plan === 'idle' && !progress.ended) {
    progress.plan = 'waiting';
    emit(run, DERIVED_TASKS.plan, 'running', 'started', { reason: '유니티가 보낼 경로를 기다립니다' }, {}, nowMs);
  }
}

const nearList = (snap: ObstacleSnapshotLike) => snap.detections
  .filter((d) => d.riskLevel === 'near')
  .map((d) => `${d.name}${d.distanceCm === null ? '' : ` ${d.distanceCm.toFixed(0)}cm`}`);

/**
 * **장애물 JSON 한 건** (`src/autodrive/watch.ts` 가 넘긴다). 판 안에서 처음 온 것이 「장애물 탐지」를 진행 중으로,
 * 가까운 장애물이 바뀔 때마다 진행 줄 하나. 판정은 AI 서버의 `has_near_obstacle` 그대로다.
 */
export function receiveObstacleSnapshot(snap: ObstacleSnapshotLike): void {
  const run = liveRun();
  if (run === null || progress === null || progress.serial !== run.serial || progress.ended) return;
  if (snap.receivedAtMs < run.startedAtMs) return;
  const payload = {
    has_near_obstacle: snap.hasNearObstacle,
    detections: snap.detections.length,
    near: nearList(snap),
    ...(snap.cameraId === null ? {} : { camera_id: snap.cameraId }),
  };
  if (progress.obstacle === 'idle') {
    progress.obstacle = 'running';
    progress.lastNear = snap.hasNearObstacle;
    emit(run, DERIVED_TASKS.obstacle, 'running', 'started', payload, {}, snap.receivedAtMs);
    return;
  }
  if (progress.obstacle === 'running' && snap.hasNearObstacle !== null && snap.hasNearObstacle !== progress.lastNear) {
    progress.lastNear = snap.hasNearObstacle;
    emit(run, DERIVED_TASKS.obstacle, 'running', 'progress', payload, {}, snap.receivedAtMs);
  }
}

/** 사건 하나 → 이동·재탐색 노드. 판을 열기 전에 받은 사건은 이 판의 것이 아니다. */
function applyEvent(event: NavEvent): void {
  const run = liveRun();
  if (run === null || progress === null || progress.serial !== run.serial || progress.ended) return;
  // **일어난 시각으로 판단한다** (260915 pi1 보고 §6-10) — 브로커가 끊긴 동안 쌓였다 늦게 온 사건은
  // 받은 시각이 아니라 일어난 시각이 판을 열기 전인지를 본다. 제때 온 사건은 받은 시각 그대로다.
  const at = eventTimeMs(event);
  if (at < run.startedAtMs) return;
  const late = event.receivedAtMs - at;
  const facts = {
    ...(event.pathId === null ? {} : { path_id: event.pathId }),
    ...(event.source === null ? {} : { source: event.source }),
    ...(event.tsMs === null ? {} : { pi_ts_ms: event.tsMs }),
    ...(late > 0 ? { delivered_late_ms: Math.round(late) } : {}),
    nav_seq: event.seq,
  };
  const p = progress;

  const startReplan = (reason: string) => {
    p.replanAttempt += 1;
    p.replanActive = true;
    if (p.replanAttempt === 1) emit(run, NAV_TASKS.replan, 'running', 'started', { reason, ...facts }, { attempt: 1 }, at);
    else emit(run, NAV_TASKS.replan, 'rerunning', 'derived', { reason, ...facts }, { attempt: p.replanAttempt, derivedFrom: NAV_TASKS.move }, at);
  };
  const endMove = (status: TaskStatus, kind: string, payload: Record<string, unknown>) => {
    if (!p.moveActive) return;
    emit(run, NAV_TASKS.move, status, kind, { ...payload, ...facts }, { attempt: p.moveAttempt }, at);
    p.moveActive = false;
  };

  switch (event.event) {
    case 'path_received': {
      // 첫 경로 — 「이동경로 탐색」이 끝났다. 유니티가 계산한 경로를 pi1 이 받은 것이 그 근거다.
      if (p.plan !== 'done') {
        if (p.plan === 'idle') emit(run, DERIVED_TASKS.plan, 'running', 'started', {}, {}, at);
        emit(run, DERIVED_TASKS.plan, 'done', 'evaluated', {
          ...(event.pointCount === null ? {} : { point_count: event.pointCount }), ...facts,
        }, {}, at);
        p.plan = 'done';
      }
      // 취소 없이 새 경로가 오면 브리지는 그대로 갈아탄다 — 그것도 재탐색 한 번이다.
      if (p.moveActive) {
        endMove('done', 'evaluated', { ended_by: 'new_path' });
        startReplan('취소 없이 새 경로 수신');
      }
      if (p.replanActive) {
        emit(run, NAV_TASKS.replan, 'done', 'evaluated', {
          ...(event.pointCount === null ? {} : { point_count: event.pointCount }), ...facts,
        }, { attempt: p.replanAttempt }, at);
        p.replanActive = false;
      }
      p.moveAttempt += 1;
      p.moveActive = true;
      p.movePathId = event.pathId;
      const payload = { ...(event.pointCount === null ? {} : { point_count: event.pointCount }), ...facts };
      if (p.moveAttempt === 1) emit(run, NAV_TASKS.move, 'running', 'started', payload, { attempt: 1 }, at);
      else emit(run, NAV_TASKS.move, 'rerunning', 'derived', payload, { attempt: p.moveAttempt, derivedFrom: NAV_TASKS.replan }, at);
      return;
    }
    case 'path_cancel':
      endMove('done', 'evaluated', { ended_by: 'path_cancel' });
      if (!p.replanActive) startReplan('PATH_CANCEL — 유니티가 경로를 바꿨습니다');
      return;
    case 'cancel_ack':
      if (!p.replanActive) return;
      emit(run, NAV_TASKS.replan, p.replanAttempt === 1 ? 'running' : 'rerunning', 'progress', { cancel_ack: true, ...facts }, { attempt: p.replanAttempt }, at);
      return;
    case 'path_done': {
      // 브리지가 경로 끝에 닿았다(mode 99).
      if (!p.moveActive) return;          // 따라가던 경로가 없는데 온 끝 통지는 이 판의 도착이 아니다
      endMove('done', 'evaluated', { ended_by: 'path_done' });
      if (p.replanActive) return;         // 재탐색이 걸려 있으면 아직 목적지가 아니다
      arrive(run, p, facts, at);
      return;
    }
    case 'estop':
      // **PATH_CANCEL 과 짝인 정지는 비상 정지가 아니다** (260915 §4.4 실측). 유니티가 경로를 바꿀 때마다
      // 같은 ms 에 텔레옵 estop=1 을 한 번 보낸다. 이것을 실패로 칠하면 재탐색마다 이동이 빨개지고 알림에
      // 「비상 정지」가 뜬다. 이동을 끝내는 것은 짝인 `path_cancel` 이 한다.
      if (isCancelStop(event)) return;
      if (p.moveActive) noteIssue('nav-estop', 'robot', `${NAV_TASKS.move} 비상 정지 — 경로가 폐기됐습니다`);
      endMove('failed', 'failed', { code: 'estop', message: event.note ?? '비상 정지 — 경로 폐기' });
      return;
    case 'feed_started':
      return;
  }
}

/**
 * **목적지 도착 → 임무 종료.** 경로 끝(mode 99)이 재탐색 없이 왔다.
 *
 * 평가 태스크라 평가 대기를 지나고, 근거는 받은 사실(경로 끝 통지 · 이동 회차 · 재탐색 횟수)이다. 거리 기준은
 * 목적지 좌표가 없어 판정하지 않는다 — 대본의 평가 기준도 그렇게 적었다.
 */
function arrive(run: NavRun, p: Progress, facts: Record<string, unknown>, at: number): void {
  const criterion = '재탐색이 걸리지 않은 채 브리지가 경로 끝(mode 99)을 알린다';
  emit(run, DERIVED_TASKS.arrive, 'running', 'started', {}, {}, at);
  emit(run, DERIVED_TASKS.arrive, 'awaiting_evaluation', 'evaluated', { criterion }, {}, at);
  emit(run, DERIVED_TASKS.arrive, 'done', 'evaluated', {
    ended_by: 'path_done', move_attempts: p.moveAttempt, replans: p.replanAttempt, ...facts,
  }, {}, at);
  // 재탐색이 한 번도 없었다 — 0회로 끝낸다. 안 끝내면 마일스톤이 영원히 진행 중이다.
  if (p.replanAttempt === 0) {
    emit(run, NAV_TASKS.replan, 'done', 'evaluated', { replans: 0, reason: '경로를 바꾸지 않고 도착했습니다' }, {}, at);
  }
  // 장애물 탐지는 도착과 함께 끝난다. **한 번도 안 돌았으면 끝내지 않는다** — 탐지를 안 한 것을 했다고 적지 않는다.
  if (p.obstacle === 'running') {
    emit(run, DERIVED_TASKS.obstacle, 'done', 'evaluated', { has_near_obstacle: p.lastNear, reason: '목적지 도착' }, {}, at);
    p.obstacle = 'done';
  }
  emit(run, DERIVED_TASKS.end, 'running', 'started', {}, {}, at);
  emit(run, DERIVED_TASKS.end, 'done', 'evaluated', {
    arrived: true, move_attempts: p.moveAttempt, replans: p.replanAttempt, obstacle_watched: p.obstacle === 'done',
  }, {}, at);
  p.ended = true;
}

// ── 사건을 pi1 시각 순으로 적용한다 (260915 §4.4 실측) ─────────────────────────
//
// 원천마다 발행 지연이 다르다 — 패킷 캡처(`estop`)는 0~15 ms, journal(경로 사건)은 최대 약 0.5초(평균 0.19초).
// 그래서 **받은 순서가 일어난 순서와 다르다.** 실측에서 `path_received`(ts …839)가 그보다 늦게 일어난
// `estop`(ts …978) 뒤에 왔다. 받는 대로 적용하면 ① 짝인 `path_cancel` 이 아직 안 온 `estop` 을 비상 정지로 읽고
// ② 이동 시작보다 정지를 먼저 적용한다.
//
// 받은 사건을 `NAV_REORDER_MS` 동안 들고 있다가 `ts_ms` 순으로 적용한다. 노드가 그만큼 늦게 칠해지지만
// 칠해지는 시각(`atSec`)은 사건의 시각이다 — 되감기에는 차이가 없다.

/** 들고 있는 시간. journal 지연 실측 최대 481 ms 의 두 배 남짓. */
export const NAV_REORDER_MS = 1200;

let pending: Array<{ event: NavEvent; arrivedMs: number }> = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

const orderKey = (event: NavEvent) => event.tsMs ?? event.receivedAtMs;

function release(all: boolean): void {
  const cutoff = Date.now() - NAV_REORDER_MS;
  const ready = all ? pending : pending.filter((entry) => entry.arrivedMs <= cutoff);
  if (ready.length === 0) return;
  pending = all ? [] : pending.filter((entry) => entry.arrivedMs > cutoff);
  // 같은 시각이면 받은 순서(seq)를 지킨다 — 정렬이 안정적이어야 한다.
  ready.sort((a, b) => orderKey(a.event) - orderKey(b.event) || a.event.seq - b.event.seq);
  for (const entry of ready) applyEvent(entry.event);
}

function scheduleFlush(): void {
  if (flushTimer !== null) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    release(false);
    if (pending.length > 0) scheduleFlush();
  }, Math.max(50, NAV_REORDER_MS / 4));
  (flushTimer as { unref?: () => void }).unref?.();
}

function enqueue(event: NavEvent): void {
  pending.push({ event, arrivedMs: Date.now() });
  scheduleFlush();
}

function dropPending(): void {
  pending = [];
  if (flushTimer !== null) { clearTimeout(flushTimer); flushTimer = null; }
}

/** 들고 있는 사건을 지금 전부 적용한다 — 검사가 기다리지 않고 결과를 보려고 쓴다. */
export function drainNavEvents(): void {
  release(true);
}

let started = false;

/**
 * 앱 수명 내내 잇는다 — `startMissionRecorder` 와 같은 자리다. 판이 열리고 닫히는 것과 중계가
 * 오는 것을 둘 다 듣는다. 되돌려주는 함수를 부르면 끊긴다.
 */
export function startNavLink(): () => void {
  if (started) return () => undefined;
  started = true;
  let lastSerial: number | null = null;
  const offRun = subscribeNavRun(() => {
    const run = navRun();
    if (run === null) {
      lastSerial = null;
      progress = null;
      dropPending();
      if (warnTimer !== null) { clearTimeout(warnTimer); warnTimer = null; }
      return;
    }
    if (run.serial === lastSerial) return;
    lastSerial = run.serial;
    // 지난 판에 들고 있던 사건은 버린다 — 새 판의 시각 검사로도 걸러지지만 섞일 틈을 안 둔다.
    dropPending();
    openRun(run);
  });
  const offFeed = subscribeNav((event) => {
    if (event === null) checkTelemetry();
    else enqueue(event);
  });
  // 이미 열린 판이 있으면(잇기 전에 승인했다) 지금 연다.
  const run = navRun();
  if (run !== null) { lastSerial = run.serial; openRun(run); }
  return () => {
    offRun();
    offFeed();
    dropPending();
    started = false;
  };
}

/** 검사용 — 지금 판의 진행. */
export function navProgress(): Readonly<Progress> | null {
  return progress;
}
