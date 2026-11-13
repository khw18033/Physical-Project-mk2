/**
 * src/physical/flightRunFeed.ts (261014 신설 — 드론 비행 제어 탭)
 *
 * **pi3 실행기가 내는 비행 실행 상태** — 토픽 `{zone}/{type}/{id}/flight_run` (JSON, QoS 1, retained).
 * 규약은 `261014_드론비행실행기_요청_VZ.md` §4 다.
 *
 * 실행기는 프로세스 사실(돌고 있나 · 종료 코드)과 **스크립트 출력 원문**만 보낸다. 진행 단계(연결 → RTK →
 * 업로드 · 대조 → arm → 미션 #n → PASS → 착륙)는 여기서 원문을 읽어 판정한다(`readProgress`) — 스크립트가 터미널에
 * 찍던 것을 그대로 읽으므로, 화면이 말하는 단계와 SSH 로 보던 단계가 어긋나지 않는다.
 *
 * 숫자가 아니면 `null`(모름), 모양이 틀리면 묶음째 버린다 — `fcxFeed.ts` 와 같은 규칙이다.
 */

import { useSyncExternalStore } from 'react';

export const FLIGHT_RUN_TOPIC = 'zoneA/+/+/flight_run';

export function flightRunChannel(topic: string): boolean {
  return topic.split('/').at(-1) === 'flight_run';
}

export type RunLine = { seq: number; text: string };

/** 실행 하나 — 비행 스크립트 또는 비상 명령. */
export type FlightProcess = {
  runId: string;
  commandId: string | null;
  state: 'running' | 'exited';
  dryRun: boolean | null;
  argv: readonly string[];
  startedAt: number | null;
  endedAt: number | null;
  exitCode: number | null;
  outPath: string | null;
  /** 비상 명령만 — `land` · `rtl` · `hold`. */
  mode: string | null;
  /**
   * 실행기가 실제로 띄운 스크립트 (261022). RTK 보정이 FC 로 들어오면 `test_sar_rtk.py`, 아니면 `test_sar.py`.
   * 이 칸이 없던 실행기(261017 판)는 `null` — 그때는 늘 `test_sar_rtk.py` 였다.
   */
  script: string | null;
  /**
   * 시작 명령을 받은 순간 실행기가 판정한 RTK 여부 (`run.rtk`, **bool**) — 보정이 3초 안에 들어왔거나 FC 가 이미
   * RTK_FLOAT/FIXED 이면 `true`(REPORT_pi3_261022 §6). 비행 중에는 안 바뀐다. 옛 실행 · 비상 명령은 `null`.
   */
  rtk: boolean | null;
  lines: readonly RunLine[];
};

export type FlightRunReport = {
  deviceId: string;
  run: FlightProcess | null;
  emergency: FlightProcess | null;
};

export type FlightRunEntry = FlightRunReport & { receivedAtMs: number };

type Obj = Record<string, unknown>;
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const obj = (v: unknown): Obj | null => (v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Obj : null);

function parseProcess(value: unknown): FlightProcess | null | undefined {
  if (value === null) return null;
  const body = obj(value);
  if (body === null) return undefined;
  const runId = str(body.run_id);
  const state = body.state === 'running' || body.state === 'exited' ? body.state : null;
  if (runId === null || state === null) return undefined;
  const lines: RunLine[] = Array.isArray(body.lines)
    ? body.lines.map(obj).filter((line): line is Obj => line !== null && num(line.seq) !== null && typeof line.text === 'string')
      .map((line) => ({ seq: line.seq as number, text: line.text as string }))
    : [];
  return {
    runId,
    commandId: str(body.command_id),
    state,
    dryRun: typeof body.dry_run === 'boolean' ? body.dry_run : null,
    argv: Array.isArray(body.argv) ? body.argv.filter((item): item is string => typeof item === 'string') : [],
    startedAt: num(body.started_at),
    endedAt: num(body.ended_at),
    exitCode: num(body.exit_code),
    outPath: str(body.out_path),
    mode: str(body.mode),
    script: str(body.script),
    rtk: typeof body.rtk === 'boolean' ? body.rtk : null,
    lines,
  };
}

/** 보고 한 건. `run` · `emergency` 가 모양이 틀리면 묶음째 `null` — 반쪽만 믿지 않는다. */
export function parseFlightRun(body: Obj, topic = ''): FlightRunReport | null {
  const deviceId = str(body.source_id) ?? topic.split('/').at(-2) ?? '';
  if (deviceId === '') return null;
  const run = parseProcess(body.run ?? null);
  const emergency = parseProcess(body.emergency ?? null);
  if (run === undefined || emergency === undefined) return null;
  return { deviceId, run, emergency };
}

// ── 저장소 ──────────────────────────────────────────────────────────────

/** 한 실행에서 화면이 들고 있는 줄 수. 실행기는 최근 200줄씩 보내고 화면은 `seq` 로 이어 붙인다. */
export const KEEP_LINES = 2000;
/** 실행기는 줄이 없어도 5초마다 보낸다. 15초 동안 없으면 실행기 · 브로커 길이 멎은 것이다. */
export const FLIGHT_RUN_STALE_MS = 15_000;

let entries: Readonly<Record<string, FlightRunEntry>> = {};
const listeners = new Set<() => void>();

function mergeProcess(previous: FlightProcess | null, next: FlightProcess | null): FlightProcess | null {
  if (next === null || previous === null || previous.runId !== next.runId) return next;
  const last = previous.lines.at(-1)?.seq ?? 0;
  const fresh = next.lines.filter((line) => line.seq > last);
  // 실행기가 다시 떠서 seq 가 처음부터라면(이어 읽기 실패) 받은 것으로 바꾼다 — 섞지 않는다.
  const restarted = next.lines.length > 0 && next.lines[0].seq < (previous.lines[0]?.seq ?? 0);
  const lines = restarted ? next.lines : [...previous.lines, ...fresh];
  return { ...next, lines: lines.length > KEEP_LINES ? lines.slice(lines.length - KEEP_LINES) : lines };
}

export function noteFlightRun(report: FlightRunReport, atMs = Date.now()): void {
  const previous = entries[report.deviceId];
  entries = {
    ...entries,
    [report.deviceId]: {
      deviceId: report.deviceId,
      run: mergeProcess(previous?.run ?? null, report.run),
      emergency: mergeProcess(previous?.emergency ?? null, report.emergency),
      receivedAtMs: atMs,
    },
  };
  for (const listener of listeners) listener();
}

export function flightRuns(): Readonly<Record<string, FlightRunEntry>> {
  return entries;
}

export function isFlightRunStale(entry: FlightRunEntry, nowMs = Date.now()): boolean {
  return nowMs - entry.receivedAtMs > FLIGHT_RUN_STALE_MS;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** 화면 밖에서 듣는 자리 — 조작 기록기(`record/controlRecorder.ts`)가 비행 판에 실행을 붙인다 (261110). */
export const subscribeFlightRuns = subscribe;

export function useFlightRuns(): Readonly<Record<string, FlightRunEntry>> {
  return useSyncExternalStore(subscribe, flightRuns, flightRuns);
}

export function resetFlightRuns(): void {
  entries = {};
  for (const listener of listeners) listener();
}

// ── 출력 원문 읽기 ───────────────────────────────────────────────────────

/**
 * 스크립트가 지나는 단계. 순서가 곧 진행이다(`PHASES` 의 앞이 먼저).
 * `dryDone` 은 dry-run 에서만, `landed` 는 비행에서만 온다.
 */
export const PHASES = ['starting', 'connecting', 'position', 'rtk', 'route', 'upload', 'verified', 'arming', 'mission', 'landed'] as const;
export type Phase = (typeof PHASES)[number] | 'dryDone';

export type FlightProgress = {
  phase: Phase;
  /** 미션 항목 수 — 업로드 전에 찍는 `[미션] #n …` 목록에서 센다. */
  itemsTotal: number | null;
  /** 지금 FC 가 하고 있는 항목 — `[미션] 진행 #n …`. */
  itemCur: number | null;
  itemText: string | null;
  /** 지금 캡처 중인 패스(`PASS n START` ~ `PASS n END`). */
  capturing: number | null;
  passesDone: number;
  /** 2초마다 찍는 `#n 진행 …m 속도 … 고도 …` 의 마지막 줄. */
  live: string | null;
  /** `[중단]` · `[오류]` 줄 — 그대로. */
  problems: readonly string[];
  warnings: number;
  /** `[종료]` 를 봤다 — 스크립트가 스스로 끝을 찍었다. */
  ended: boolean;
  /**
   * **FC 가 미션을 끝냈다** (261111). 진행 번호(`#n 진행` · `[미션] 진행 #n`)가 항목 수에 닿았다 — PX4 는 마지막 항목(LAND)을
   * 마치면 번호를 항목 수로 넘긴다. 11/9 실기에서 스크립트는 이 뒤로 착륙을 못 알아봤다(`REPORT_착륙판정_261111.md`).
   */
  missionDone: boolean;
  /** 마지막으로 본 진행 번호 — 2초마다 찍는 `#n 진행` 줄까지 포함(`itemCur` 는 `[미션] 진행` 줄만). */
  liveItem: number | null;
  /** pi3 스크립트의 `[착륙감시]` 줄(LAND 이후에만 찍힌다)에서 읽은 FC 값. 그 줄이 없으면 `seen: false`. */
  landWatch: LandWatch;
};

/** `[착륙감시]` 줄의 FC 값 — 줄마다 `in_air=… landed=… armed=… mode=…` 를 실어 온다. 뒤 줄이 앞 줄을 덮는다. */
export type LandWatch = {
  seen: boolean;
  inAir: boolean | null;
  landed: string | null;
  armed: boolean | null;
  mode: string | null;
  /** 요약 줄의 「판정창 겹침」 초 — 스크립트의 착륙 조건이 성립했던 시간. */
  overlapS: number | null;
};

const LAND_WATCH = /^\[착륙감시\]/;
const pyBool = (value: string | undefined): boolean | null | undefined =>
  value === undefined ? undefined : value === 'True' ? true : value === 'False' ? false : null;

/** `[착륙감시]` 한 줄을 지금 값에 얹는다. 같은 키가 한 줄에 여럿이면(요약 줄의 「판정창(…)」 · 「끝 …」) 마지막 것이 지금 값이다. */
function readLandWatch(text: string, into: LandWatch): void {
  into.seen = true;
  const last: Record<string, string> = {};
  for (const match of text.matchAll(/(?:^|[^A-Za-z_])(in_air|landed|armed|mode)=([A-Za-z_]+)/g)) last[match[1]!] = match[2]!;
  const inAir = pyBool(last.in_air);
  if (inAir !== undefined) into.inAir = inAir;
  const armed = pyBool(last.armed);
  if (armed !== undefined) into.armed = armed;
  if (last.landed !== undefined) into.landed = last.landed === 'None' ? null : last.landed;
  if (last.mode !== undefined) into.mode = last.mode === 'None' ? null : last.mode;
  const overlap = text.match(/겹침=(\d+(?:\.\d+)?)s/);
  if (overlap !== null) into.overlapS = Number(overlap[1]);
}

/**
 * **착륙 상태** (261111). 스크립트가 `[확인] 착륙 완료` 를 못 찍어도 FC 가 말하는 것으로 가른다. 제어는 하지 않는다 — 화면이
 * 사람에게 알리기만 한다.
 *
 *   confirmed    스크립트가 착륙 완료를 찍었다(정상)
 *   disarmed     FC 기준 땅 위 + 무장 해제
 *   onGround     FC 기준 땅 위(landed=ON_GROUND 또는 in_air=False), 무장은 아직이거나 모름
 *   missionDone  진행 번호가 항목 수에 닿았다 — FC 가 LAND 를 마쳤다. 땅 위인지는 FC 값이 없어 모른다
 *   none         그 전
 *
 * `fc` 는 실시간 FC 텔레메트리(fcx)가 있을 때 — `[착륙감시]` 줄이 없는 옛 스크립트에서도 같은 판정을 하게. LAND 전(이륙 전 지상)을
 * 착륙으로 읽지 않도록, FC 값은 미션이 끝났거나 `[착륙감시]` 가 시작된 뒤에만 본다.
 */
export type Landing = 'none' | 'missionDone' | 'onGround' | 'disarmed' | 'confirmed';

export function landingOf(progress: FlightProgress, fc: { landedState: string | null; armed: boolean | null } | null = null): Landing {
  if (progress.phase === 'landed') return 'confirmed';
  if (!progress.missionDone && !progress.landWatch.seen) return 'none';
  const watch = progress.landWatch;
  const landed = watch.landed ?? fc?.landedState ?? null;
  const inAir = watch.inAir;
  const armed = watch.armed ?? fc?.armed ?? null;
  const onGround = landed === 'ON_GROUND' || inAir === false;
  if (onGround && armed === false) return 'disarmed';
  if (onGround) return 'onGround';
  return progress.missionDone ? 'missionDone' : 'none';
}

const TIME_PREFIX = /^\[\d+(?:\.\d+)?\]\s?/;

/** `[1760455812.512] [연결] …` → `[연결] …`. 시각 머리가 없는 줄(print · 오류 출력)은 그대로. */
export function stripTime(text: string): string {
  return text.replace(TIME_PREFIX, '');
}

function advance(current: Phase, next: Phase): Phase {
  if (current === 'dryDone' || next === 'dryDone') return next === 'dryDone' ? next : current;
  return PHASES.indexOf(next) > PHASES.indexOf(current) ? next : current;
}

/** 출력 원문 → 진행. 같은 줄을 여러 번 넣어도 같은 답이다. */
export function readProgress(lines: readonly RunLine[]): FlightProgress {
  let phase: Phase = 'starting';
  let itemsTotal: number | null = null;
  let itemCur: number | null = null;
  let itemText: string | null = null;
  let capturing: number | null = null;
  let passesDone = 0;
  let live: string | null = null;
  const problems: string[] = [];
  let warnings = 0;
  let ended = false;
  let liveItem: number | null = null;
  const landWatch: LandWatch = { seen: false, inAir: null, landed: null, armed: null, mode: null, overlapS: null };
  for (const { text: raw } of lines) {
    const text = stripTime(raw).trim();
    let match: RegExpMatchArray | null;
    if (/^\[연결\]/.test(text)) phase = advance(phase, 'connecting');
    else if (/^\[확인\] 위치 추정/.test(text)) phase = advance(phase, 'position');
    else if (/^\[RTK\] 이륙 전/.test(text)) phase = advance(phase, 'rtk');
    else if (/^\[경로\]/.test(text)) phase = advance(phase, 'route');
    else if ((match = text.match(/^\[미션\] 진행 #(\d+)\s*(.*)$/)) !== null) {
      phase = advance(phase, 'mission');
      itemCur = Number(match[1]);
      liveItem = itemCur;
      itemText = match[2].trim() || null;
    } else if ((match = text.match(/^\[미션\] #(\d+)\s/)) !== null) {
      itemsTotal = Math.max(itemsTotal ?? 0, Number(match[1]) + 1);
    } else if (/^\[미션\] 업로드/.test(text)) phase = advance(phase, 'upload');
    else if (/^\[미션\] 대조 일치/.test(text)) phase = advance(phase, 'verified');
    else if (/^\[dry-run\]/.test(text)) phase = advance(phase, 'dryDone');
    else if (/^\[명령\] arm/.test(text)) phase = advance(phase, 'arming');
    else if (/^\[명령\] 미션 시작/.test(text)) phase = advance(phase, 'mission');
    else if (/^\[확인\] 착륙 완료/.test(text)) phase = advance(phase, 'landed');
    else if ((match = text.match(/^PASS (\d+) START\b/)) !== null) capturing = Number(match[1]);
    else if ((match = text.match(/^PASS (\d+) END\b/)) !== null) {
      passesDone = Math.max(passesDone, Number(match[1]));
      if (capturing === Number(match[1])) capturing = null;
    } else if ((match = text.match(/^#(\d+) 진행/)) !== null) { live = text; liveItem = Number(match[1]); }
    else if (/^\[종료\]$/.test(text)) ended = true;
    else if (LAND_WATCH.test(text)) readLandWatch(text, landWatch);
    if (/^\[중단\]/.test(text) || /^\[오류\]/.test(text)) problems.push(text);
    if (/^\[경고\]/.test(text)) warnings += 1;
  }
  const missionDone = phase === 'mission' && itemsTotal !== null && liveItem !== null && liveItem >= itemsTotal;
  return { phase, itemsTotal, itemCur, itemText, capturing, passesDone, live, problems, warnings, ended, missionDone, liveItem, landWatch };
}

export type LineTone = 'bad' | 'warn' | 'ok' | 'pass' | '';

/** 출력 칸이 줄마다 칠할 색. 뜻을 바꾸지 않고 눈에 띄게만 한다. */
export function lineTone(raw: string): LineTone {
  const text = stripTime(raw).trim();
  if (/^\[중단\]/.test(text) || /^\[오류\]/.test(text) || /^중단됨/.test(text) || /^usage:|error:/.test(text)) return 'bad';
  if (/^\[경고\]/.test(text)) return 'warn';
  if (/^PASS \d+ /.test(text)) return 'pass';
  if (text.includes('✔')) return 'ok';
  return '';
}

/**
 * 실행의 결론. 프로세스가 끝났으면 종료 코드가 말한다 — 스크립트 기준 0 정상 · 1 중단 · 실패 · 2 옵션 오류,
 * 음수는 신호로 죽은 것(실행기 규약).
 */
export type RunOutcome = 'running' | 'ok' | 'failed' | 'badArgs' | 'killed' | 'unknown';

export function runOutcome(process: FlightProcess): RunOutcome {
  if (process.state === 'running') return 'running';
  const code = process.exitCode;
  if (code === null) return 'unknown';
  if (code === 0) return 'ok';
  if (code === 2) return 'badArgs';
  if (code < 0) return 'killed';
  return 'failed';
}
