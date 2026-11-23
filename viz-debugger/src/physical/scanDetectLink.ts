/**
 * src/physical/scanDetectLink.ts (261123 신설 — 스캔 탐지를 data_stream 으로 · S3 연결)
 *
 * **새 흐름(`robotFlow: 'scan-detect'`)을 실물에 붙인다.** 순서는 `scanDetectRun.ts` 가 들고, 여기는 그 의존성을 채운다:
 *
 *   창구     장치의 추론 스트림 포트(`detect/scan/scanAddress.ts`)
 *   회전     `issueStepsToEnd` — `turn 45` 하나를 내고 **종료 응답까지** 기다린다
 *   방위     T-A2 는 준비 단계(`prepStage.ts`)가 받는다 — 그 값을 기다린다(못 받으면 「모름」)
 *   노드     `receiveRobotProgress` · seq 6,000,000 대역(사람 1M · 생성 2M · 로봇 3M · 탐지 4M · 준비 5M 과 안 겹친다)
 *   기록     data_stream 요청도 명령 기록 열에 남긴다(노드 T-A0 · T-A4-n · T-A5)
 *
 * 승인(로봇 관문) + 「임무 시작」이 되면 **판마다 한 번** 돈다. 결과가 오면 T-A5 · T-A6 · T-B1 을 칠하고 이동 명령을 낸다.
 * T-B2 의 「이동 전 승인」이 켜진 편은 사람이 누를 때까지 기다린다(`issueScanApproach`).
 * 옛 흐름의 로봇 전용 부품(`scan_mission` · `:8000` 폴링 · scanGate)은 이 편에서 돌지 않는다 — `doorScanFlow()` 가 지킨다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../i18n/dict.ts';
import { currentMission, receiveRobotProgress, recordAnswered, recordCommanded } from '../data/scenario.ts';
import type { ScenarioEvent, TaskStatus } from '../model/types.ts';
import { scanDetectFlow, scanTargetOf } from '../scenarios/library.ts';
import { scanClient, newScanId } from '../detect/scan/ScanClient.ts';
import { scanBaseFor } from '../detect/scan/scanAddress.ts';
import { applyScanEvent, scanRunState } from '../detect/scan/scanStore.ts';
import { detectState } from '../detect/store.ts';
import { translateObjectName } from '../generate/nameEn.ts';
import { deviceState } from './deviceState.ts';
import { hardwareTarget } from './encode.ts';
import { approachNeedsApproval } from './approachAuto.ts';
import { prepState, subscribePrep } from './prepStage.ts';
import { issueStepsToEnd } from './robotCommands.ts';
import { robotClient } from './robotClient.ts';
import { elapsedSec, markApproachIssued, robotSession, subscribeRobot } from './robotSession.ts';
import { planScanApproach, type ScanApproachPlan } from './scanApproach.ts';
import { profileChanged, runScanDetect, type ScanCallRecord, type ScanRunOutcome } from './scanDetectRun.ts';

const ROBOT_ENTITY = 'robot-01';
/** T-A2 방위를 기다리는 한도. 못 주는 장치면 이 뒤 「모름」으로 돈다(계획서 §2-2). */
const HEADING_WAIT_MS = 10_000;

let seq = 6_000_000;
let callSeq = 0;

function emit(missionId: string, nodeId: string, status: TaskStatus, payload?: Record<string, unknown>): void {
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

/** data_stream 요청 한 건을 명령 기록 열에 — MQTT 명령이 아니므로 id 를 따로 만든다. */
function record(entry: ScanCallRecord): void {
  callSeq += 1;
  const commandId = `ds-${Date.now().toString(36)}-${callSeq}`;
  const numeric: Record<string, number> = {};
  for (const [key, value] of Object.entries(entry.body)) if (typeof value === 'number') numeric[key] = value;
  recordCommanded({ commandId, taskId: entry.taskId, action: `data_stream.${entry.call}`, parameters: numeric });
  recordAnswered({
    commandId, taskId: entry.taskId, line: entry.answer, answerKind: 'result',
    index: entry.angleIndex ?? null, outcome: entry.ok ? 'done' : 'failed',
  });
}

/** 준비 단계가 받은 방위를 기다린다. */
function waitHeading(runKey: number): Promise<number | null> {
  return new Promise((resolve) => {
    const settle = (): boolean => {
      const prep = prepState();
      if (prep.runKey !== runKey) return false;
      if (prep.pose.step === 'done' && prep.pose.value !== null) { resolve(prep.pose.value.headingDeg); return true; }
      if (prep.pose.step === 'failed') { resolve(null); return true; }
      return false;
    };
    if (settle()) return;
    const off = subscribePrep(() => { if (settle()) { off(); clearTimeout(timer); } });
    const timer = setTimeout(() => { off(); resolve(null); }, HEADING_WAIT_MS);
  });
}

function headingNow(): number | null {
  return deviceState(hardwareTarget(ROBOT_ENTITY))?.position?.headingDeg ?? null;
}

// ── 이동 계획 (승인 대기 포함) ───────────────────────────────────────────

export type ScanApproachState = { scanId: string; missionId: string; plan: ScanApproachPlan; issued: boolean; waitingApproval: boolean } | null;
let approach: ScanApproachState = null;
const approachListeners = new Set<() => void>();
function setApproach(next: ScanApproachState): void {
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
  setApproach({ ...current, issued: true, waitingApproval: false });
  markApproachIssued();
  const outcome = await issueStepsToEnd(robotClient(), current.plan.steps);
  if (!outcome.sent) emit(current.missionId, 'T-B2', 'failed', { reason: outcome.reason ?? '' });
  return outcome.sent;
}

function onResult(missionId: string, outcome: ScanRunOutcome & { ok: true }, scanId: string): void {
  const { result } = outcome;
  const readyVersion = scanRunState()?.scanId === scanId ? scanRunState()?.profileVersion ?? null : null;
  if (profileChanged(readyVersion, result)) {
    applyScanEvent({ kind: 'fail', scanId, failure: { stage: 'result', code: 'profile_changed', detail: `${readyVersion} → ${result.profile_version}` } });
    emit(missionId, 'T-A5', 'failed', { code: 'profile_changed', ready: readyVersion, result: result.profile_version });
    return;
  }
  emit(missionId, 'T-A5', result.best === null ? 'failed' : 'done', {
    best: result.best, frames_found: result.frames.filter((f) => f.found).map((f) => f.rotation_deg), reason: result.reason,
  });
  if (result.best === null) return;
  emit(missionId, 'T-A6', 'done', { cues: result.cues.map((c) => [c.name, c.value, c.note]), enough: result.enough, reason: result.reason });

  const params = currentMission().params;
  const stop = Number((params as Record<string, unknown>).stop_distance_max_m ?? 0.9);
  const plan = planScanApproach({
    best: result.best, stopDistanceM: Number.isFinite(stop) ? stop : 0.9,
    headingStartDeg: outcome.headingStartDeg, headingEndDeg: outcome.headingEndDeg, testMode: detectState().testMode,
  });
  if (!plan.ok) {
    emit(missionId, 'T-B1', 'failed', { reason: t(plan.reason.key, plan.reason.vars) });
    setApproach({ scanId, missionId, plan, issued: false, waitingApproval: false });
    return;
  }
  emit(missionId, 'T-B1', 'done', {
    turn_deg: plan.turnDeg, forward_m: plan.issuedForwardM, drift_deg: plan.driftDeg, bearing_deg: plan.bearingDeg,
    notes: plan.notes.map((note) => t(note.key, note.vars)),
  });
  const waiting = approachNeedsApproval(missionId);
  setApproach({ scanId, missionId, plan, issued: false, waitingApproval: waiting });
  if (!waiting) void issueScanApproach();
}

// ── 판 하나 ──────────────────────────────────────────────────────────

let runningKey: number | null = null;

async function launch(missionId: string, runKey: number): Promise<void> {
  const target = scanTargetOf(missionId) ?? 'door';
  const device = hardwareTarget(ROBOT_ENTITY);
  const scanId = newScanId(missionId);
  const params = currentMission().params;
  const steps = Number(params.viewpoint_count ?? 8);
  const stepDeg = Number(params.viewpoint_step_deg ?? 45);
  setApproach(null);

  const failEarly = (code: string, detail: string) => {
    applyScanEvent({ kind: 'begin', scanId, missionId, device, base: '', target, query: null, queryKo: null, steps, stepDeg });
    applyScanEvent({ kind: 'fail', scanId, failure: { stage: 'prepare', code, detail } });
    emit(missionId, 'T-A0', 'failed', { code, detail });
  };

  const base = scanBaseFor(device);
  if (base === null) { failEarly('no_address', t('sd.noAddress', { device })); return; }

  let query: string | null = null;
  let queryKo: string | null = null;
  if (target === 'object') {
    queryKo = currentMission().targetWord ?? null;
    if (queryKo === null || queryKo.trim() === '' || queryKo.includes('@')) { failEarly('no_query', t('sd.noQuery')); return; }
    emit(missionId, 'T-A0', 'running', { query_ko: queryKo });
    const named = await translateObjectName(queryKo);
    if (!named.ok) { failEarly('translate_failed', named.reason); return; }
    query = named.nameEn;
  }

  const outcome = await runScanDetect({ scanId, missionId, device, target, query, queryKo, steps, stepDeg }, {
    client: scanClient(base),
    async turn(deg) {
      // 회전 명령은 T-A3 에 붙는다. 로봇 응답이 T-A3 을 끝냄으로 칠하므로 다시 진행 중으로 돌린다 — 끝은 실행기가 칠한다.
      const issued = await issueStepsToEnd(robotClient(), [{ taskId: 'T-A3', action: 'turn', parameters: { deg } }]);
      if (issued.sent) emit(missionId, 'T-A3', 'running', {});
      return issued.sent ? { ok: true } : { ok: false, reason: issued.reason ?? t('sd.turnFailed') };
    },
    startHeading: () => waitHeading(runKey),
    heading: headingNow,
    emit: (taskId, status, payload) => emit(missionId, taskId, status, payload),
    event: applyScanEvent,
    record,
    stopped: () => robotSession().stopped !== null || robotSession().startedAtMs !== runKey,
    sleep: (ms) => new Promise((done) => setTimeout(done, ms)),
    now: () => Date.now(),
  });
  if (outcome.ok) onResult(missionId, outcome, scanId);
}

function check(): void {
  const session = robotSession();
  const missionId = currentMission().missionId;
  if (!scanDetectFlow(missionId)) return;
  if (!session.approved || !session.started || session.startedAtMs === null || session.stopped !== null) return;
  if (runningKey === session.startedAtMs) return;
  runningKey = session.startedAtMs;
  void launch(missionId, session.startedAtMs);
}

/** 앱이 살아 있는 동안 한 번 건다(`main.tsx`). 돌려준 함수로 푼다. */
export function startScanDetectLink(): () => void {
  const off = subscribeRobot(check);
  check();
  return off;
}

/** 정지 버튼 — 진행 중인 판이 있으면 data_stream 에도 멈추라고 한다(실행기는 매 걸음 앞에서 정지를 보고 cancel 을 보낸다). */
export function cancelScanDetect(): void {
  const run = scanRunState();
  if (run === null || run.result !== null || run.failure !== null || run.cancelled || run.base === '') return;
  void scanClient(run.base).cancel(run.scanId).then((answer) => {
    record({ taskId: 'T-A0', call: 'cancel', body: { scan_id: run.scanId }, ok: answer.ok, answer: answer.ok ? answer.value.state : `${answer.code} ${answer.detail}` });
    applyScanEvent({ kind: 'cancel', scanId: run.scanId });
  });
}
