/**
 * src/physical/missionRunFeed.ts (261113 신설 — 드론 복합 이동 미션)
 *
 * **pi3 실행기가 내는 복합 미션 실행 상태** — 토픽 `{zone}/{type}/{id}/mission_run` (JSON, retained).
 * 규약은 `MISSION_SEQ_요청_VZ.md` §4 · §5 다. 본문은 `flight_run` 의 `run` 과 같은 모양에 셋이 더 붙는다 —
 * `steps`(띄운 단계 정규형) · `plan`(스크립트가 찍은 `[계획]` JSON) · `mission_key`/`mission_hash`. 비상(`emergency`)은
 * 여기 없고 `flight_run` 쪽에 남는다.
 *
 * 진행 판정은 `flightRunFeed.readProgress` 를 그대로 쓰고(연결 → 업로드 → 대조 → arm → 미션 → 착륙 문구가 같다),
 * 복합 미션만의 줄 — `STEP k/N START/END` · `CAP k` · `#n 단계 k/N … 진행` · `[결과]` — 을 여기서 더 읽는다.
 */

import { useSyncExternalStore } from 'react';
import { mergeProcess, parseProcess, readProgress, stripTime, type FlightProcess, type FlightProgress, type RunLine } from './flightRunFeed.ts';

export const MISSION_RUN_TOPIC = 'zoneA/+/+/mission_run';

export function missionRunChannel(topic: string): boolean {
  return topic.split('/').at(-1) === 'mission_run';
}

// ── [계획] (§5-1) ───────────────────────────────────────────────────────

export type PlanPoint = { n: number; e: number; fwd: number; right: number; lat: number | null; lon: number | null };

export type PlanStep = {
  k: number;
  kind: string;
  value: number;
  speed: number | null;
  cap: boolean;
  label: string;
  text: string;
  /** 이 단계에 속한 미션 항목 seq 범위. */
  seq: [number, number] | null;
  /** 이 단계 끝의 기수(도, 북 0). */
  yaw: number | null;
  from: PlanPoint | null;
  to: PlanPoint | null;
};

export type SeqPlanReport = {
  key: string;
  hash: string | null;
  /** 이륙 지점 = 원점. */
  L: [number, number] | null;
  /** 이륙 직전 기수(도, 0 = 북, 시계). */
  h0: number | null;
  alt: number | null;
  speed: number | null;
  land: string | null;
  estS: number | null;
  timeoutS: number | null;
  maxR: number | null;
  pathM: number | null;
  nItems: number | null;
  /** 미션 항목 seq 별 역할 — `[역할, 단계 k]`. */
  roles: readonly (readonly [string, number])[];
  steps: readonly PlanStep[];
  landPt: PlanPoint | null;
};

type Obj = Record<string, unknown>;
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const obj = (v: unknown): Obj | null => (v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Obj : null);

function parsePoint(value: unknown): PlanPoint | null {
  const body = obj(value);
  if (body === null) return null;
  const n = num(body.n);
  const e = num(body.e);
  const fwd = num(body.fwd);
  const right = num(body.right);
  if (n === null || e === null || fwd === null || right === null) return null;
  return { n, e, fwd, right, lat: num(body.lat), lon: num(body.lon) };
}

/** `[계획]` JSON. 키가 없으면 버린다 — 짝 맞추기의 근거가 키다. */
export function parseSeqPlan(value: unknown): SeqPlanReport | null {
  const body = obj(value);
  if (body === null) return null;
  const key = str(body.key);
  if (key === null) return null;
  const pair = (v: unknown): [number, number] | null =>
    Array.isArray(v) && v.length === 2 && num(v[0]) !== null && num(v[1]) !== null ? [v[0] as number, v[1] as number] : null;
  const roles = Array.isArray(body.roles)
    ? body.roles.map((role) => (Array.isArray(role) && typeof role[0] === 'string' ? [role[0], num(role[1]) ?? 0] as const : ['?', 0] as const))
    : [];
  const steps: PlanStep[] = Array.isArray(body.steps)
    ? body.steps.map(obj).filter((step): step is Obj => step !== null && num(step.k) !== null).map((step) => ({
      k: step.k as number,
      kind: str(step.kind) ?? '?',
      value: num(step.value) ?? 0,
      speed: num(step.speed),
      cap: step.cap === true,
      label: str(step.label) ?? str(step.text) ?? '',
      text: str(step.text) ?? '',
      seq: pair(step.seq),
      yaw: num(step.yaw),
      from: parsePoint(step.from),
      to: parsePoint(step.to),
    }))
    : [];
  return {
    key,
    hash: str(body.hash),
    L: pair(body.L),
    h0: num(body.h0),
    alt: num(body.alt),
    speed: num(body.speed),
    land: str(body.land),
    estS: num(body.est_s),
    timeoutS: num(body.timeout_s),
    maxR: num(body.max_r),
    pathM: num(body.path_m),
    nItems: num(body.n_items),
    roles,
    steps,
    landPt: parsePoint(body.land_pt),
  };
}

const PLAN_LINE = /^\[계획\]\s*(\{.*\})\s*$/;

/** 출력 원문의 `[계획]` 줄 — 상태 토픽의 `plan` 이 없을 때(옛 실행기) 물러설 자리. 마지막 것. */
export function planFromLines(lines: readonly RunLine[]): SeqPlanReport | null {
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const match = stripTime(lines[i]!.text).trim().match(PLAN_LINE);
    if (match === null) continue;
    try { return parseSeqPlan(JSON.parse(match[1]!)); } catch { return null; }
  }
  return null;
}

// ── 상태 보고 ───────────────────────────────────────────────────────────

export type MissionProcess = FlightProcess & {
  /** 띄운 단계 정규형(`right:3`). */
  steps: readonly string[];
  plan: SeqPlanReport | null;
  missionKey: string | null;
  missionHash: string | null;
};

export type MissionRunReport = { deviceId: string; run: MissionProcess | null };
export type MissionRunEntry = MissionRunReport & { receivedAtMs: number };

function parseMissionProcess(value: unknown): MissionProcess | null | undefined {
  const base = parseProcess(value);
  if (base === null || base === undefined) return base;
  const body = value as Obj;
  const plan = parseSeqPlan(body.plan) ?? planFromLines(base.lines);
  return {
    ...base,
    steps: Array.isArray(body.steps) ? body.steps.filter((item): item is string => typeof item === 'string') : [],
    plan,
    missionKey: str(body.mission_key) ?? plan?.key ?? null,
    missionHash: str(body.mission_hash) ?? plan?.hash ?? null,
  };
}

/** 보고 한 건. `run` 이 모양이 틀리면 버린다. */
export function parseMissionRun(body: Obj, topic = ''): MissionRunReport | null {
  const deviceId = str(body.source_id) ?? topic.split('/').at(-2) ?? '';
  if (deviceId === '') return null;
  const run = parseMissionProcess(body.run ?? null);
  if (run === undefined) return null;
  return { deviceId, run };
}

let entries: Readonly<Record<string, MissionRunEntry>> = {};
const listeners = new Set<() => void>();

export function noteMissionRun(report: MissionRunReport, atMs = Date.now()): void {
  const previous = entries[report.deviceId]?.run ?? null;
  let run = mergeProcess(previous, report.run);
  // 같은 실행인데 이번 보고에 계획이 빠졌으면(줄이 밀려 `[계획]` 이 안 보이는 옛 실행기) 앞서 본 계획을 지킨다.
  if (run !== null && previous !== null && run.runId === previous.runId && run.plan === null && previous.plan !== null) {
    run = { ...run, plan: previous.plan, missionKey: run.missionKey ?? previous.missionKey, missionHash: run.missionHash ?? previous.missionHash };
  }
  entries = { ...entries, [report.deviceId]: { deviceId: report.deviceId, run, receivedAtMs: atMs } };
  for (const listener of listeners) listener();
}

export function missionRuns(): Readonly<Record<string, MissionRunEntry>> {
  return entries;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export const subscribeMissionRuns = subscribe;

export function useMissionRuns(): Readonly<Record<string, MissionRunEntry>> {
  return useSyncExternalStore(subscribe, missionRuns, missionRuns);
}

export function resetMissionRuns(): void {
  entries = {};
  for (const listener of listeners) listener();
}

// ── 진행 읽기 (§5-2) ────────────────────────────────────────────────────

export type StepResult = {
  /** `STEP k/N END` 의 걸린 시간 · 목표 오차 · 기수 오차. 못 읽은 값은 `null`. */
  durS: number | null;
  posErrM: number | null;
  yawErrDeg: number | null;
  /** `[결과] 단계 k …` 원문(있으면). */
  text: string | null;
};

export type SeqProgress = FlightProgress & {
  /** 지금 FC 가 하는 항목의 역할(`plan.roles[n]`). 계획이 없거나 아직이면 `null`. */
  role: string | null;
  /** 지금 단계(1부터). `STEP k START` 또는 진행 번호 → 역할로 판정. */
  stepCur: number | null;
  stepTotal: number | null;
  /** `STEP k END` 를 본 단계. */
  stepsDone: ReadonlySet<number>;
  results: Readonly<Record<number, StepResult>>;
  /** 지금 캡처 중인 단계(`CAP k START` ~ `CAP k END`). */
  capturingStep: number | null;
  /** `[경고]` 줄 원문 — 결과에서 눈에 띄게. */
  warningLines: readonly string[];
};

const numOf = (text: string, re: RegExp): number | null => {
  const match = text.match(re);
  return match === null ? null : Number(match[1]);
};

export function readSeqProgress(lines: readonly RunLine[], plan: SeqPlanReport | null): SeqProgress {
  const base = readProgress(lines);
  let stepCur: number | null = null;
  let stepTotal: number | null = plan?.steps.length || null;
  let role: string | null = null;
  const stepsDone = new Set<number>();
  const results: Record<number, StepResult> = {};
  let capturingStep: number | null = null;
  const warningLines: string[] = [];
  let live = base.live;
  let liveItem = base.liveItem;
  const resultOf = (k: number) => (results[k] ??= { durS: null, posErrM: null, yawErrDeg: null, text: null });
  const fromItem = (n: number) => {
    const at = plan?.roles[n];
    if (at === undefined) return;
    role = at[0];
    if (at[1] >= 1 && (at[0] === 'speed' || at[0] === 'move' || at[0] === 'rot' || at[0] === 'hover')) stepCur = at[1];
  };
  for (const { text: raw } of lines) {
    const text = stripTime(raw).trim();
    let match: RegExpMatchArray | null;
    if ((match = text.match(/^\[미션\] 진행 #(\d+)/)) !== null) fromItem(Number(match[1]));
    else if ((match = text.match(/^STEP (\d+)\/(\d+) START\b/)) !== null) {
      stepCur = Number(match[1]);
      stepTotal = Number(match[2]);
    } else if ((match = text.match(/^STEP (\d+)\/(\d+) END\b/)) !== null) {
      const k = Number(match[1]);
      stepTotal = Number(match[2]);
      stepsDone.add(k);
      const result = resultOf(k);
      result.durS = numOf(text, /dur=(\d+(?:\.\d+)?)s/);
      result.posErrM = numOf(text, /목표 오차 (\d+(?:\.\d+)?)m/);
      result.yawErrDeg = numOf(text, /\(목표 [-\d.]+°, 오차 (\d+(?:\.\d+)?)°\)/);
    } else if ((match = text.match(/^CAP (\d+) START\b/)) !== null) capturingStep = Number(match[1]);
    else if ((match = text.match(/^CAP (\d+) END\b/)) !== null) {
      if (capturingStep === Number(match[1])) capturingStep = null;
    } else if ((match = text.match(/^#(\d+)\s+\S/)) !== null) {
      // 2초마다 찍는 진행 줄 (`mission_seq.py` monitor). 단계 안이면 `#n 단계 k/N 라벨 [진행 a/b m] …`, 단계 밖(이륙 · 정렬 ·
      // 복귀 · 착륙)이면 `#n land  속도 …` 처럼 역할 이름이 온다 — 둘 다 진행 번호를 읽어야 착륙 중 「FC 미션 완료」가 선다.
      live = text;
      liveItem = Number(match[1]);
      fromItem(liveItem);
    } else if ((match = text.match(/^\[결과\] 단계 (\d+)\s/)) !== null) resultOf(Number(match[1])).text = text;
    if (/^\[경고\]/.test(text)) warningLines.push(text);
  }
  // 「단계 k 진행」 줄은 `readProgress` 의 `#n 진행` 과 모양이 달라 여기서 다시 센다.
  const itemsTotal = base.itemsTotal ?? plan?.nItems ?? null;
  const missionDone = base.phase === 'mission' && itemsTotal !== null && liveItem !== null && liveItem >= itemsTotal;
  return {
    ...base, itemsTotal, live, liveItem, missionDone,
    role, stepCur, stepTotal, stepsDone, results, capturingStep, warningLines,
  };
}

export type StepState = 'waiting' | 'active' | 'done';

/** 단계 표의 한 줄 상태. 끝난 실행에서 END 를 못 본 단계는 `waiting` 으로 둔다(어디서 멈췄는지 보이게). */
export function stepState(progress: SeqProgress, k: number): StepState {
  if (progress.stepsDone.has(k)) return 'done';
  if (progress.stepCur === k) return 'active';
  return 'waiting';
}
