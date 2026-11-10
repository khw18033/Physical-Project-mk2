/**
 * src/record/controlRecorder.ts (261110 신설 — 「가시화에서 한 조작도 기록에 남긴다」)
 *
 * **이 화면이 낸 조작을 판으로 남긴다.** 임무 기록(`recorder.ts`)은 승인된 임무가 있을 때만 판을 연다. 그래서 임무 없이
 * Go1 을 키보드로 몰거나 드론 비행 제어 탭에서 날린 것은 기록 열(`NO_MISSION`)에만 쌓였다가 새로고침 · 새 임무 한 번에
 * 사라졌다. 여기는 **임무와 상관없이** 장비마다 조작 판을 열고, 임무 기록과 **같은 창구 · 같은 폴더 · 같은 두 파일**로 쓴다.
 *
 *   mission-history/<날짜>/<시각>_CTL-<장비>/   수동 제어 · 사람 명령
 *   mission-history/<날짜>/<시각>_FLT-<장비>/   비행 실행 하나
 *     mission.json    판 요약 (`recordKind: 'control'`) — 이력 목록이 읽는다
 *     progress.json   일어난 일 전부 — 명령 · 답 · 막힘 · 유지 신호 구간 · 설정 · 비행 실행기 출력 · 텔레메트리 표본
 *
 * ## 남기는 것은 **이 화면이 한 조작**뿐이다
 *
 * 브로커를 엿듣지 않는다. 다른 화면 · 스크립트 · SSH · 조종기가 한 일은 여기 안 들어온다(261110 결정 — 안 A).
 * 대신 화면만 아는 것 — 어떤 키가 막혔나 · 어떤 모드였나 · 어떤 dry-run 의 짝인가 — 을 남긴다.
 *
 * ## 판의 경계
 *
 *   수동 제어   그 장비의 수동 제어를 켠 때부터 끈 때까지
 *   비행        `rtk_test_start` 한 건(dry-run 포함)부터 실행기가 그 실행의 종료를 알릴 때까지. 그 사이의 중단 · 비상도 이 판이다
 *   사람 명령   열린 판이 없는 장비에 사람이 명령을 냈다(SAR 등) — 60초 동안 아무 일 없으면 닫는다
 *
 * 장비마다 열린 판은 하나다. 비행 시작은 그 장비의 다른 판을 닫고 새 판을 연다.
 * **폴더는 무언가 일어난 뒤에야 만든다** — 켜기만 하고 끈 판까지 폴더가 생기면 목록이 빈 판으로 찬다(`recorder.ts` 와 같은 규칙).
 *
 * ## 임무 기록과 겹치는 것
 *
 * 임무 중에 낸 사람 명령은 지금처럼 임무 판의 기록 열에도 남는다(`humanCommands.ts`). 여기는 그와 **별개로** 같은 명령을
 * 조작 판에 적고, 그때 돌던 임무 id 와 그 임무 판의 폴더를 같이 적어 둘을 잇는다.
 *
 * ## 다시보기 중에도 적는다
 *
 * 다시보기는 화면이 지난 판을 그리는 것이고, 그 사이에도 키보드 조작은 실제 장비로 나간다. 실제로 나간 것은 적는다.
 *
 * **로봇에 나가는 바이트는 한 줄도 안 바뀐다.** 이미 나간 뒤에 적기만 한다.
 *
 * ## 텔레메트리 표본 (261111 — 2차)
 *
 * 판이 열려 있는 동안 주기(`TICK_MS`)마다 그 장비의 **지금 값**을 한 줄 적는다 — 배터리 · 전압 · 속도 · 고도 · 위치 ·
 * 방위 · 모드 · 무장 · GPS · 링크 · 수신 간격. 값은 실시간 그래프와 같은 이력(`shared/metricHistory.ts`)에서 읽는다.
 * **`TELEMETRY_FRESH_MS` 넘게 안 온 값은 빈칸(null)이다** — 마지막 값을 끌어다 「그때 값」으로 적지 않는다.
 * 표본만으로는 폴더를 만들지 않는다(조작이 있어야 판이 선다). 표본만 늘어난 쓰기는 `TELEMETRY_WRITE_MS` 에 한 번이다.
 */

import { useSyncExternalStore } from 'react';
import { getMissionState, NO_MISSION } from '../data/scenario.ts';
import { enabledManualDevices, manualConfig, manualModeOf, subscribeManual } from '../physical/manualControl.ts';
import { deviceCandidates } from '../physical/deviceIdentity.ts';
import { flightRuns, subscribeFlightRuns, readProgress, runOutcome, type FlightProcess } from '../physical/flightRunFeed.ts';
import type { UplinkMessage } from '../physical/uplink.ts';
import { recorderStatus } from './recorder.ts';
import { putRecordJson, runFolderOf } from './recordClient.ts';
import { hardwareTarget } from '../physical/encode.ts';
import { AGE_KEY, lastSeenAt, latestMetric, latestState } from '../shared/metricHistory.ts';

export const CONTROL_SCHEMA = 'control-record/1';
const TICK_MS = 1500;
/** 사람 명령 판 — 이만큼 아무 일 없으면 닫는다. */
export const COMMAND_IDLE_MS = 60_000;
/** 비행 판 — 시작을 냈는데 실행기가 이만큼 아무 실행도 안 알리면 닫는다. */
export const FLIGHT_IDLE_MS = 120_000;
/** 비행 판 — 실행이 끝난 뒤 마지막 줄을 기다리는 시간. 실행기는 5초마다 보낸다. */
export const FLIGHT_GRACE_MS = 6_000;
/** 유지 신호 · 막힘이 이 간격 안에 이어지면 한 구간으로 묶는다. */
const MERGE_GAP_MS = 1_000;

/** 이보다 오래된 값은 표본에 안 적는다(빈칸). 1 Hz 장비가 몇 번 놓쳐도 남고, 멎은 장비는 곧 빈칸이 된다. */
export const TELEMETRY_FRESH_MS = 5_000;
/** 표본만 늘어난 판을 다시 쓰는 간격. 조작 · 닫힘은 이와 상관없이 바로 쓴다. */
export const TELEMETRY_WRITE_MS = 10_000;
/** 판 하나의 표본 상한 — 1.5초마다면 2시간. 넘으면 더 안 적고 그 사실을 남긴다. */
const MAX_TELEMETRY = 4_800;

/**
 * 표본의 칸. 숫자는 이력 키 중 먼저 있는 것(Go1 모양 · 드론 모양), 낱말은 범주 키. 이 차례가 저장 차례다.
 * `rxAgeS` 는 이 브라우저가 잰 「마지막으로 무엇이든 받은 지 몇 초」.
 */
const TELEMETRY_NUMBERS: ReadonlyArray<readonly [string, readonly string[]]> = [
  ['batteryPct', ['battery_pct', 'battery.remaining_pct']],
  ['voltageV', ['battery.voltage_v']],
  ['speedMps', ['speed_mps', 'hud.groundspeed']],
  ['altM', ['altitude.relative_m']],
  ['lat', ['gps.lat']],
  ['lon', ['gps.lon']],
  ['x', ['position.x']],
  ['y', ['position.y']],
  ['headingDeg', ['position.heading_deg']],
];
const TELEMETRY_WORDS: ReadonlyArray<readonly [string, readonly string[]]> = [
  ['mode', ['robot_mode', 'flight.mode']],
  ['armed', ['flight.armed']],
  ['gpsFix', ['gps.fix']],
  ['link', ['link']],
];
export const TELEMETRY_COLUMNS = ['atMs', ...TELEMETRY_NUMBERS.map(([k]) => k), 'rxAgeS', ...TELEMETRY_WORDS.map(([k]) => k)] as const;
type TelemetryCell = number | string | null;

const FLIGHT_START = 'rtk_test_start';
const FLIGHT_EMERGENCY = 'rtk_test_emergency';

export type ControlSessionKind = 'manual' | 'flight' | 'command';
export type ControlCloseReason = 'manualOff' | 'flightExited' | 'flightRejected' | 'idle' | 'replaced';
export type ControlBlock = 'typing' | 'auto' | 'offline' | 'unsupported' | 'undeclared';

/** 판에 적는 한 줄. **글자가 아니라 값**이다 — 다시 볼 때 그 화면의 언어로 그린다(`mission-record/2` 와 같은 규칙). */
export type ControlEvent = { atMs: number } & (
  | { kind: 'opened'; reason: 'manualOn' | 'flightStart' | 'command' }
  | { kind: 'closed'; reason: ControlCloseReason }
  | { kind: 'config'; mode: string; config: unknown }
  | { kind: 'commanded'; commandId: string; action: string; parameters: Record<string, number>; requestId: string | null; missionId: string | null }
  | { kind: 'answered'; commandId: string; answerKind: UplinkMessage['kind']; accepted: boolean | null; code: string | null; message: string | null; state: string | null; status: string | null; keepalive: boolean }
  | { kind: 'notSent'; action: string; reason: string }
  | { kind: 'blocked'; block: ControlBlock; count: number; untilMs: number }
  | { kind: 'keepalive'; parameters: Record<string, number>; count: number; untilMs: number }
);

export type ControlMissionLink = { missionId: string; recordFolder: string | null };

export type ControlRecordSummary = {
  schema: string;
  recordKind: 'control';
  folder: string;
  sessionKind: ControlSessionKind;
  deviceId: string;
  /** 목록이 굵게 쓰는 자리 — 임무 판의 `missionId` 자리와 같다. */
  missionId: string;
  startedAtIso: string;
  updatedAtIso: string;
  endedAtIso: string | null;
  closeReason: ControlCloseReason | null;
  counts: { commands: number; rejected: number; blocked: number; notSent: number; keepalive: number };
  /** 동작별 건수 — `teleop` 몇 건 · `abort` 몇 건. */
  actions: Record<string, number>;
  missions: ControlMissionLink[];
  flight: {
    dryRun: boolean | null;
    runId: string | null;
    script: string | null;
    rtk: boolean | null;
    exitCode: number | null;
    outcome: string | null;
    phase: string | null;
    emergencies: number;
  } | null;
  /** 텔레메트리 표본 요약(261111). 값이 하나도 없었으면 null. 옛 판(1차)에는 칸 자체가 없다. */
  telemetry?: {
    samples: number;
    batteryStart: number | null;
    batteryEnd: number | null;
    batteryMin: number | null;
    /** 가장 길었던 수신 간격(초) — 판 사이 끊김의 크기. */
    maxRxAgeS: number | null;
    /** 지나간 모드 차례(이어진 같은 값은 하나로). */
    modes: string[];
    truncated: boolean;
  } | null;
};

export type ControlProgress = {
  schema: string;
  deviceId: string;
  sessionKind: ControlSessionKind;
  updatedAtIso: string;
  events: ControlEvent[];
  flight: { startCommandId: string | null; dryRun: boolean | null; runs: FlightProcess[]; emergencies: FlightProcess[] } | null;
  /**
   * 텔레메트리 표본(261111) — 칸 이름 한 줄 + 줄마다 값. 첫 칸은 시각(ms). 판 내내 한 번도 안 온 칸은 뺀다.
   * 옛 판(1차)에는 없다.
   */
  telemetry?: { columns: string[]; rows: TelemetryCell[][]; truncated: boolean };
};

type Session = {
  serial: number;
  deviceId: string;
  kind: ControlSessionKind;
  openedAtMs: number;
  closedAtMs: number | null;
  closeReason: ControlCloseReason | null;
  lastEventMs: number;
  /** 폴더를 만들 만큼 일어났나 — 명령 · 막힘 · 못 보냄. 켜고 끄기 · 설정만으로는 안 선다. */
  happened: boolean;
  folder: { date: string; run: string } | null;
  events: ControlEvent[];
  missions: Map<string, string | null>;
  /** 이 판이 낸 명령 id → 유지 신호인가. 답을 어느 판에 붙일지 찾는다. */
  commandIds: Map<string, boolean>;
  flight: {
    startCommandId: string | null;
    dryRun: boolean | null;
    emergencyIds: Set<string>;
    runs: Map<string, FlightProcess>;
    emergencies: Map<string, FlightProcess>;
    /** 이 판의 실행이 끝난 것을 처음 본 시각. */
    exitedSeenMs: number | null;
  } | null;
  written: { mission: string; progress: string };
  lastConfig: string;
  telemetry: TelemetryCell[][];
  telemetryTruncated: boolean;
  /** 마지막으로 쓴 때의 사건 수와 시각 — 표본만 늘었으면 `TELEMETRY_WRITE_MS` 에 한 번만 쓴다. */
  writtenEvents: number;
  writtenAtMs: number;
};

export type ControlRecorderStatus = {
  state: 'idle' | 'recording' | 'unavailable';
  /** 지금 쓰고 있는 판 폴더들. */
  folders: readonly string[];
  lastSavedAtIso: string | null;
  lastError: string | null;
};

// ── 바꿔 끼울 수 있는 것 — 검사가 시계와 창구를 흉내 낸다 ──────────────────────────

let clock: () => number = () => Date.now();
let store: (date: string, run: string, file: 'mission.json' | 'progress.json', body: string) => Promise<void> = putRecordJson;

/** 검사용. 화면에서는 부르지 않는다. `null` 을 주면 원래 것으로 돌아간다. */
export function setControlProbes(probes: {
  clock?: (() => number) | null;
  store?: ((date: string, run: string, file: 'mission.json' | 'progress.json', body: string) => Promise<void>) | null;
}): void {
  if (probes.clock !== undefined) clock = probes.clock ?? (() => Date.now());
  if (probes.store !== undefined) store = probes.store ?? putRecordJson;
}

// ── 상태 ─────────────────────────────────────────────────────────────────────

const open = new Map<string, Session>();
/** 닫혔지만 마지막 모습을 아직 안 쓴 판. */
const closing: Session[] = [];
/** 명령 id → 그 명령을 적은 판. 답이 판이 닫힌 뒤에 와도 그 판에 붙인다(마지막 쓰기 전까지). */
const byCommand = new Map<string, Session>();
let serial = 0;
let manualOn = new Set<string>();
let writing: Promise<void> = Promise.resolve();
let status: ControlRecorderStatus = { state: 'idle', folders: [], lastSavedAtIso: null, lastError: null };
const statusListeners = new Set<() => void>();

function setStatus(next: Partial<ControlRecorderStatus>): void {
  const merged = { ...status, ...next };
  if (merged.state === status.state && merged.folders.join('|') === status.folders.join('|')
    && merged.lastSavedAtIso === status.lastSavedAtIso && merged.lastError === status.lastError) return;
  status = merged;
  for (const listener of statusListeners) listener();
}

export function controlRecorderStatus(): ControlRecorderStatus {
  return status;
}

export function useControlRecorderStatus(): ControlRecorderStatus {
  return useSyncExternalStore(
    (listener) => { statusListeners.add(listener); return () => statusListeners.delete(listener); },
    controlRecorderStatus, controlRecorderStatus,
  );
}

/** 지금 열린 판 — 검사와 배지가 읽는다. */
export function openControlSessions(): ReadonlyArray<{ deviceId: string; kind: ControlSessionKind; folder: string | null; events: readonly ControlEvent[] }> {
  return [...open.values()].map((s) => ({ deviceId: s.deviceId, kind: s.kind, folder: folderWords(s), events: s.events }));
}

function folderWords(s: Session): string | null {
  return s.folder === null ? null : `${s.folder.date}/${s.folder.run}`;
}

// ── 텔레메트리 표본 ─────────────────────────────────────────────────────────

/** 이 장비의 이력 id — 명령 id 그대로이거나 하드웨어 id(`hardwareTarget`). 이력이 있는 쪽. */
function historyIdOf(deviceId: string): string {
  const hardware = hardwareTarget(deviceId);
  return lastSeenAt(deviceId) === null && lastSeenAt(hardware) !== null ? hardware : deviceId;
}

/** 지금 값 한 줄. 아무 값도 없으면(장비가 아직 아무것도 안 보냈으면) 안 적는다. */
function sampleTelemetry(session: Session, now = clock()): void {
  if (session.closedAtMs !== null) return;
  if (session.telemetry.length >= MAX_TELEMETRY) { session.telemetryTruncated = true; return; }
  const id = historyIdOf(session.deviceId);
  const numbers = TELEMETRY_NUMBERS.map(([, keys]) => {
    for (const key of keys) {
      const value = latestMetric(id, key, now, TELEMETRY_FRESH_MS);
      if (value !== null) return value;
    }
    return null;
  });
  const seen = lastSeenAt(id);
  // 수신 간격은 표본기(0.5초)를 기다리지 않고 지금 잰다 — 이 줄의 시각과 맞는다.
  const rxAgeS = seen === null ? latestMetric(id, AGE_KEY, now, TELEMETRY_FRESH_MS) : Math.max(0, Math.round((now - seen) / 100) / 10);
  const words = TELEMETRY_WORDS.map(([, keys]) => {
    for (const key of keys) {
      const value = latestState(id, key, now, TELEMETRY_FRESH_MS);
      if (value !== null) return value;
    }
    return null;
  });
  if (seen === null && numbers.every((v) => v === null) && words.every((v) => v === null)) return;
  const row: TelemetryCell[] = [now, ...numbers.map((v) => (v === null ? null : Math.round(v * 1e7) / 1e7)), rxAgeS, ...words];
  if (session.telemetry.at(-1)?.[0] === now) session.telemetry[session.telemetry.length - 1] = row;
  else session.telemetry.push(row);
}

function telemetryBody(session: Session): ControlProgress['telemetry'] {
  if (session.telemetry.length === 0) return undefined;
  // 판 내내 빈 칸은 뺀다 — 드론 판에 Go1 지도 좌표 칸이 줄마다 null 로 서지 않게.
  const keep = TELEMETRY_COLUMNS.map((_, index) => index === 0 || session.telemetry.some((row) => row[index] !== null));
  return {
    columns: TELEMETRY_COLUMNS.filter((_, index) => keep[index]),
    rows: session.telemetry.map((row) => row.filter((_, index) => keep[index])),
    truncated: session.telemetryTruncated,
  };
}

function telemetrySummary(session: Session): ControlRecordSummary['telemetry'] {
  const rows = session.telemetry;
  if (rows.length === 0) return null;
  const col = (name: string) => TELEMETRY_COLUMNS.indexOf(name as (typeof TELEMETRY_COLUMNS)[number]);
  const numbers = (name: string) => rows.map((row) => row[col(name)]).filter((v): v is number => typeof v === 'number');
  const battery = numbers('batteryPct');
  const ages = numbers('rxAgeS');
  const modes: string[] = [];
  for (const row of rows) {
    const mode = row[col('mode')];
    if (typeof mode === 'string' && modes.at(-1) !== mode) modes.push(mode);
  }
  return {
    samples: rows.length,
    batteryStart: battery[0] ?? null,
    batteryEnd: battery.at(-1) ?? null,
    batteryMin: battery.length === 0 ? null : Math.min(...battery),
    maxRxAgeS: ages.length === 0 ? null : Math.max(...ages),
    modes,
    truncated: session.telemetryTruncated,
  };
}

// ── 판 열고 닫기 ─────────────────────────────────────────────────────────────

function openSession(deviceId: string, kind: ControlSessionKind, reason: 'manualOn' | 'flightStart' | 'command'): Session {
  const previous = open.get(deviceId);
  if (previous !== undefined) closeSession(previous, 'replaced');
  serial += 1;
  const now = clock();
  const session: Session = {
    serial, deviceId, kind,
    openedAtMs: now, closedAtMs: null, closeReason: null, lastEventMs: now,
    happened: false, folder: null,
    events: [{ atMs: now, kind: 'opened', reason }],
    missions: new Map(),
    commandIds: new Map(),
    flight: kind === 'flight'
      ? { startCommandId: null, dryRun: null, emergencyIds: new Set(), runs: new Map(), emergencies: new Map(), exitedSeenMs: null }
      : null,
    written: { mission: '', progress: '' },
    lastConfig: '',
    telemetry: [],
    telemetryTruncated: false,
    writtenEvents: 0,
    writtenAtMs: 0,
  };
  open.set(deviceId, session);
  sampleTelemetry(session, now);
  if (kind === 'manual') noteConfig(session);
  return session;
}

function closeSession(session: Session, reason: ControlCloseReason): void {
  if (session.closedAtMs !== null) return;
  const now = clock();
  sampleTelemetry(session, now);
  session.closedAtMs = now;
  session.closeReason = reason;
  session.events.push({ atMs: now, kind: 'closed', reason });
  if (open.get(session.deviceId) === session) open.delete(session.deviceId);
  closing.push(session);
}

/** 이 장비에 지금 열린 판. 없으면 사람 명령 판을 연다. */
function sessionFor(deviceId: string): Session {
  return open.get(deviceId) ?? openSession(deviceId, 'command', 'command');
}

function push(session: Session, event: ControlEvent, happened = true): void {
  session.events.push(event);
  session.lastEventMs = event.atMs;
  if (happened) session.happened = true;
  linkMission(session);
}

/** 지금 승인된 임무가 돌고 있으면 그 임무와 그 판의 폴더를 잇는다. */
function linkMission(session: Session): string | null {
  const mission = getMissionState();
  if (mission.current.missionId === NO_MISSION || mission.activatedBy !== 'approval') return null;
  const id = mission.current.missionId;
  const folder = recorderStatus().folder;
  if (!session.missions.has(id) || (session.missions.get(id) === null && folder !== null)) session.missions.set(id, folder);
  return id;
}

function noteConfig(session: Session): void {
  const config = manualConfig(session.deviceId);
  const actions = deviceCandidates().find((candidate) => candidate.deviceId === session.deviceId)?.actions ?? null;
  const mode = manualModeOf(actions);
  const key = JSON.stringify({ mode, config });
  if (key === session.lastConfig) return;
  session.lastConfig = key;
  push(session, { atMs: clock(), kind: 'config', mode, config: JSON.parse(JSON.stringify(config)) }, false);
}

// ── 들어오는 것 ──────────────────────────────────────────────────────────────

/** 사람이 낸 명령 한 건 — `humanCommands.recordHumanCommand` 가 부른다(발행이 성공한 뒤). */
export function controlCommanded(input: {
  commandId: string; deviceId: string; action: string;
  parameters: Record<string, number>; requestId?: string | null;
}): void {
  const session = input.action === FLIGHT_START
    ? openSession(input.deviceId, 'flight', 'flightStart')
    : sessionFor(input.deviceId);
  if (session.flight !== null) {
    if (input.action === FLIGHT_START && session.flight.startCommandId === null) {
      session.flight.startCommandId = input.commandId;
      // 실행기 규약: dry_run 은 1/0 숫자로 실린다(`flightPlan.startParams`).
      session.flight.dryRun = typeof input.parameters.dry_run === 'number' ? input.parameters.dry_run !== 0 : null;
    }
    if (input.action === FLIGHT_EMERGENCY) session.flight.emergencyIds.add(input.commandId);
  }
  session.commandIds.set(input.commandId, false);
  byCommand.set(input.commandId, session);
  push(session, {
    atMs: clock(), kind: 'commanded', commandId: input.commandId, action: input.action,
    parameters: { ...input.parameters }, requestId: input.requestId ?? null, missionId: linkMission(session),
  });
}

/**
 * 장비의 답 한 줄 — `humanCommands.recordHumanAnswer` 가 부른다. 이 판이 낸 명령의 답만 붙인다.
 * 유지 신호의 답은 **거절만** 적는다 — 초당 다섯 건의 수락을 적으면 판이 수락으로 찬다.
 */
export function controlAnswered(message: UplinkMessage): void {
  const session = byCommand.get(message.commandId);
  if (session === undefined) return;
  const keepalive = session.commandIds.get(message.commandId) === true;
  const refused = message.kind === 'acceptance' && !message.accepted;
  if (keepalive && !refused) return;
  push(session, {
    atMs: clock(), kind: 'answered', commandId: message.commandId, answerKind: message.kind,
    accepted: message.kind === 'acceptance' ? message.accepted : null,
    code: message.kind === 'status' ? null : message.code,
    message: message.kind === 'status' ? null : message.message,
    state: message.kind === 'status' ? message.state : null,
    status: message.kind === 'result' ? message.status : null,
    keepalive,
  });
  // 비행 시작을 실행기가 거절했다 — 실행은 안 선다. 판을 닫는다.
  if (refused && session.flight !== null && session.flight.startCommandId === message.commandId) closeSession(session, 'flightRejected');
}

/** 키가 명령이 되지 않았다 · 보내지 못했다 — `manualDispatch.note` 가 부른다. 이어진 같은 막힘은 한 줄로 센다. */
export function controlManualEvent(deviceId: string, event:
  | { kind: 'blocked'; block: ControlBlock; atMs?: number }
  | { kind: 'failed'; action: string; reason: string; atMs?: number }): void {
  const session = sessionFor(deviceId);
  const now = clock();
  if (event.kind === 'failed') {
    push(session, { atMs: now, kind: 'notSent', action: event.action, reason: event.reason });
    return;
  }
  const last = session.events.at(-1);
  if (last !== undefined && last.kind === 'blocked' && last.block === event.block && now - last.untilMs <= MERGE_GAP_MS) {
    last.count += 1;
    last.untilMs = now;
    session.lastEventMs = now;
    return;
  }
  push(session, { atMs: now, kind: 'blocked', block: event.block, count: 1, untilMs: now });
}

/**
 * 유지 신호 한 번 — `manualDispatch.keepaliveTick` 가 부른다. 건별로 안 적고 **구간**으로 묶는다: 같은 값이 이어지는 동안
 * 한 줄의 `count` · `untilMs` 만 는다. 명령 id 는 답(거절)을 이 판에 붙이려고만 든다.
 */
export function controlKeepalive(deviceId: string, parameters: Record<string, number>, commandId: string): void {
  const session = open.get(deviceId);
  if (session === undefined) return;
  const now = clock();
  session.commandIds.set(commandId, true);
  byCommand.set(commandId, session);
  const same = (a: Record<string, number>) => JSON.stringify(a) === JSON.stringify(parameters);
  // 앞 줄이 같은 값의 유지 신호 구간이면 늘린다. 그 사이 다른 줄(거절 등)이 끼었으면 새 구간이다.
  const last = session.events.at(-1);
  if (last !== undefined && last.kind === 'keepalive' && same(last.parameters) && now - last.untilMs <= MERGE_GAP_MS) {
    last.count += 1;
    last.untilMs = now;
    session.lastEventMs = now;
    return;
  }
  push(session, { atMs: now, kind: 'keepalive', parameters: { ...parameters }, count: 1, untilMs: now });
}

/** 수동 제어를 켜고 끈 것 · 설정을 바꾼 것. `subscribeManual` 이 부른다. 검사가 직접 부른다. */
export function syncManualSessions(): void {
  const now = new Set(enabledManualDevices());
  for (const deviceId of now) {
    const session = open.get(deviceId);
    // 켜져 있는데 수동 판이 아니면(새로 켰다 · 사람 명령 판이 먼저 열려 있었다) 수동 판을 연다. 이미 수동 판이면 설정만 본다.
    if (session !== undefined && session.kind === 'manual') noteConfig(session);
    else openSession(deviceId, 'manual', 'manualOn');
  }
  for (const deviceId of manualOn) {
    if (now.has(deviceId)) continue;
    const session = open.get(deviceId);
    if (session !== undefined && session.kind === 'manual') closeSession(session, 'manualOff');
  }
  manualOn = now;
}

/** 실행기 피드가 바뀌었다 — 열린 비행 판에 그 실행을 붙인다. 검사가 직접 부른다. */
export function syncFlightRuns(): void {
  const entries = flightRuns();
  for (const session of [...open.values()]) {
    const flight = session.flight;
    if (flight === null) continue;
    const entry = entries[session.deviceId];
    if (entry === undefined) continue;
    const run = entry.run;
    // 내 시작이 띄운 실행만 — 실행기가 되돌려 준 `command_id` 로 맞춘다. 옛 실행기(칸 없음)는 판을 연 뒤에 시작한 것.
    if (run !== null && (run.commandId !== null
      ? run.commandId === flight.startCommandId
      : run.startedAt !== null && run.startedAt * 1000 >= session.openedAtMs - 2000)) {
      const before = flight.runs.get(run.runId);
      if (before === undefined || before !== run) {
        flight.runs.set(run.runId, run);
        session.lastEventMs = clock();
        session.happened = true;
      }
    }
    const emergency = entry.emergency;
    if (emergency !== null && (emergency.commandId === null ? emergency.state === 'running' : flight.emergencyIds.has(emergency.commandId))) {
      if (flight.emergencies.get(emergency.runId) !== emergency) {
        flight.emergencies.set(emergency.runId, emergency);
        session.lastEventMs = clock();
        session.happened = true;
      }
    }
  }
}

/** 닫을 때가 된 판을 닫는다 — 사람 명령 판의 쉼 · 비행 판의 실행 끝. */
function closeDue(now: number): void {
  for (const session of [...open.values()]) {
    if (session.kind === 'command' && now - session.lastEventMs >= COMMAND_IDLE_MS) { closeSession(session, 'idle'); continue; }
    const flight = session.flight;
    if (flight === null) continue;
    const runs = [...flight.runs.values()];
    const emergencies = [...flight.emergencies.values()];
    const exited = runs.length > 0 && runs.every((run) => run.state === 'exited') && emergencies.every((e) => e.state === 'exited');
    if (exited) {
      flight.exitedSeenMs ??= now;
      if (now - flight.exitedSeenMs >= FLIGHT_GRACE_MS) closeSession(session, 'flightExited');
      continue;
    }
    flight.exitedSeenMs = null;
    if (runs.length === 0 && now - session.lastEventMs >= FLIGHT_IDLE_MS) closeSession(session, 'idle');
  }
}

// ── 본문 ─────────────────────────────────────────────────────────────────────

const iso = (ms: number) => new Date(ms).toISOString();

export function buildControlBodies(session: Session): { mission: string; progress: string } {
  const now = clock();
  const counts = { commands: 0, rejected: 0, blocked: 0, notSent: 0, keepalive: 0 };
  const actions: Record<string, number> = {};
  for (const event of session.events) {
    if (event.kind === 'commanded') { counts.commands += 1; actions[event.action] = (actions[event.action] ?? 0) + 1; }
    if (event.kind === 'answered' && event.accepted === false) counts.rejected += 1;
    if (event.kind === 'blocked') counts.blocked += event.count;
    if (event.kind === 'notSent') counts.notSent += 1;
    if (event.kind === 'keepalive') counts.keepalive += event.count;
  }
  const flight = session.flight;
  const runs = flight === null ? [] : [...flight.runs.values()];
  const main = runs.at(-1) ?? null;
  const summary: ControlRecordSummary = {
    schema: CONTROL_SCHEMA,
    recordKind: 'control',
    folder: folderWords(session) ?? '',
    sessionKind: session.kind,
    deviceId: session.deviceId,
    missionId: session.folder?.run.slice(7) ?? session.deviceId,
    startedAtIso: iso(session.openedAtMs),
    updatedAtIso: iso(now),
    endedAtIso: session.closedAtMs === null ? null : iso(session.closedAtMs),
    closeReason: session.closeReason,
    counts,
    actions,
    missions: [...session.missions].map(([missionId, recordFolder]) => ({ missionId, recordFolder })),
    flight: flight === null ? null : {
      dryRun: main?.dryRun ?? flight.dryRun,
      runId: main?.runId ?? null,
      script: main?.script ?? null,
      rtk: main?.rtk ?? null,
      exitCode: main?.exitCode ?? null,
      outcome: main === null ? null : runOutcome(main),
      phase: main === null ? null : readProgress(main.lines).phase,
      emergencies: flight.emergencies.size,
    },
    telemetry: telemetrySummary(session),
  };
  const progress: ControlProgress = {
    schema: CONTROL_SCHEMA,
    deviceId: session.deviceId,
    sessionKind: session.kind,
    updatedAtIso: iso(now),
    events: session.events,
    flight: flight === null ? null : {
      startCommandId: flight.startCommandId,
      dryRun: flight.dryRun,
      runs,
      emergencies: [...flight.emergencies.values()],
    },
    telemetry: telemetryBody(session),
  };
  return { mission: JSON.stringify(summary, null, 2), progress: JSON.stringify(progress) };
}

function write(session: Session, force = false): void {
  if (!session.happened) return;
  if (session.folder === null) {
    session.folder = runFolderOf(new Date(session.openedAtMs), `${session.kind === 'flight' ? 'FLT' : 'CTL'}-${session.deviceId}`);
  }
  const folder = session.folder;
  const bodies = buildControlBodies(session);
  const strip = (body: string) => body.replace(/"updatedAtIso": ?"[^"]*"/g, '');
  const missionChanged = strip(bodies.mission) !== strip(session.written.mission);
  const progressChanged = strip(bodies.progress) !== strip(session.written.progress);
  if (!missionChanged && !progressChanged) return;
  // 표본만 늘었으면 몇 초에 한 번만 — 사건이 생겼거나 닫힌 판은 바로 쓴다.
  const now = clock();
  const onlySamples = session.closedAtMs === null && session.events.length === session.writtenEvents && session.writtenAtMs > 0;
  if (!force && onlySamples && now - session.writtenAtMs < TELEMETRY_WRITE_MS) return;
  session.writtenEvents = session.events.length;
  session.writtenAtMs = now;
  session.written = bodies;
  // 차례로 쓴다 — 같은 파일을 두 요청이 겹쳐 쓰면 늦게 출발한 것이 먼저 끝날 수 있다.
  writing = writing.then(async () => {
    try {
      if (progressChanged) await store(folder.date, folder.run, 'progress.json', bodies.progress);
      await store(folder.date, folder.run, 'mission.json', bodies.mission);
      setStatus({ state: 'recording', lastSavedAtIso: new Date().toISOString(), lastError: null });
    } catch (error) {
      const why = error instanceof Error ? error.message : String(error);
      // 창구가 아예 없으면(404) 멈춘다 — 매 주기 실패를 쌓지 않는다.
      if (/ 404$/.test(why)) { setStatus({ state: 'unavailable', lastError: why }); return; }
      session.written = { mission: '', progress: '' };   // 다음 주기에 다시 쓴다
      setStatus({ lastError: why });
    }
  });
}

/** 한 번 본다 — 닫을 판을 닫고, 바뀐 판을 쓴다. 검사가 직접 부른다. */
export function controlTick(): void {
  if (status.state === 'unavailable') return;
  syncFlightRuns();
  closeDue(clock());
  for (const session of open.values()) { sampleTelemetry(session); write(session); }
  // 닫힌 판은 마지막 모습을 한 번 쓰고 내려놓는다.
  for (const session of closing.splice(0)) {
    write(session);
    for (const id of session.commandIds.keys()) if (byCommand.get(id) === session) byCommand.delete(id);
  }
  const folders = [...open.values()].map(folderWords).filter((f): f is string => f !== null);
  setStatus({ folders, state: folders.length > 0 ? 'recording' : status.state === 'recording' ? 'idle' : status.state });
}

// ── 앱에 거는 것 ─────────────────────────────────────────────────────────────

let refs = 0;
let stopAll: (() => void) | null = null;

/** 켠다. 되돌려주는 함수를 부르면 끈다. 여러 번 켜도 하나만 돈다. */
export function startControlRecorder(): () => void {
  refs += 1;
  if (stopAll === null) {
    syncManualSessions();
    const timer = setInterval(controlTick, TICK_MS);
    const offManual = subscribeManual(syncManualSessions);
    const offFlight = subscribeFlightRuns(syncFlightRuns);
    // 창을 닫을 때 열린 판을 닫힌 것으로 한 번 더 쓴다 — 못 가도 1.5초 전까지는 남아 있다.
    const onHide = () => { for (const session of [...open.values()]) { sampleTelemetry(session); write(session, true); } };
    if (typeof window !== 'undefined') window.addEventListener('pagehide', onHide);
    stopAll = () => {
      clearInterval(timer); offManual(); offFlight();
      if (typeof window !== 'undefined') window.removeEventListener('pagehide', onHide);
    };
  }
  return () => {
    refs -= 1;
    if (refs === 0 && stopAll !== null) { stopAll(); stopAll = null; }
  };
}

/** 검사용 — 기록기를 처음 상태로. */
export function resetControlRecorder(): void {
  open.clear();
  closing.length = 0;
  byCommand.clear();
  manualOn = new Set();
  serial = 0;
  writing = Promise.resolve();
  status = { state: 'idle', folders: [], lastSavedAtIso: null, lastError: null };
}

/** 검사용 — 밀린 쓰기가 끝날 때까지 기다린다. */
export async function settleControlRecorder(): Promise<void> {
  await writing;
}
