/**
 * src/record/recordClient.ts (260914 신설)
 *
 * **임무 기록 창구를 아는 면 하나.** 주소와 파일 이름이 여기 밖으로 안 나간다 — 탐지 주소를
 * `DetectClient.ts` 에 가두는 것과 같은 규칙이다. 창구 본체는 `scripts/mission-records.mjs`.
 *
 * 창구는 개발·미리보기 서버에만 있다. 단독 빌드를 파일로 열었거나 서버가 없으면 404 이고,
 * 그때 기록기는 조용히 멈추고 이력 목록은 「이 세션에서 본 것만」으로 돌아간다.
 *
 * ## 임무 이력 서버 (261119 · 2차)
 *
 * 임무 이력 탭에서 서버 주소를 넣으면(`historyServer.ts`) **서버가 기본 저장처**가 된다. 서버 규약은 이 PC 창구와
 * 같은 모양이다(`/api/v1/runs/…` · `/api/v1/files/…`).
 *
 *   쓰기   **판마다 한 곳.** 판을 열 때 서버가 `연결됨` 이면 서버, 아니면 이 PC(`chooseSink`). 서버로 쓰던 판이
 *          실패하면 그 판은 끝까지 이 PC 로 옮긴다(`nextSink`) — 판 하나가 두 곳에 나뉘면 어디서 열어도 깨진다.
 *          서버 주소를 둔 채 이 PC 에 쓴 판은 대피 판으로 적히고(`evacuations.ts`), 나중에 통째로 올라간다.
 *   목록   **한 출처.** 서버가 답하면(연결됨 · 불안정) 서버 목록만, 아니면 이 PC 목록만. 합치지 않는다.
 *   파일   그 판을 어느 목록에서 봤느냐를 따른다.
 *
 * 서버 주소가 없으면 1차 이전과 똑같다 — 이 PC 창구 404 는 404 로 던지고 기록기는 「창구 없음」으로 멈춘다.
 */

import { t } from '../i18n/dict.ts';
import type { ControlRecordSummary } from './controlRecorder.ts';
import { noteLocalRecordWrite } from './evacuations.ts';
import {
  CONFORMANCE_DATE, historyApiBase, historyServerConnected, historyServerReadable, noteServerListCount, writeToHistoryServer,
} from './historyServer.ts';

const BASE = '/mission-records';

/** 목록 한 줄 — `mission.json` 에서 본문(`view`)을 뺀 것. */
export type RecordedRun = {
  date: string;
  run: string;
  /** 임무 판이거나 조작 판(`recordKind: 'control'`, 261110)이다. 갈라 읽는 것은 `isControlSummary`. */
  mission: RecordMissionSummary | ControlRecordSummary | null;
};

/** 조작 판인가 (261110 — `controlRecorder.ts`). 임무 판에는 `recordKind` 칸이 없다. */
export function isControlSummary(mission: RecordedRun['mission']): mission is ControlRecordSummary {
  return mission !== null && (mission as { recordKind?: unknown }).recordKind === 'control';
}

export type RecordMissionSummary = {
  schema: string;
  missionId: string;
  label: string;
  startedAtIso: string;
  updatedAtIso: string;
  endedAtIso: string | null;
  outcome: 'done' | 'failed' | 'stopped' | null;
  done: number;
  of: number;
  failedTaskId: string | null;
  reason: string;
  headSec: number;
  robotDriven: boolean;
  testMode: boolean;
  imageCount: number;
  path: { mode: string | null; turnInstruction: string; forwardM: number } | null;
  pathFailure: string | null;
};

/** 판 폴더 이름. 날짜는 실행한 날(이 기기의 시계), 판은 시작 시각과 임무 id. */
export function runFolderOf(startedAt: Date, missionId: string): { date: string; run: string } {
  const two = (n: number) => String(n).padStart(2, '0');
  const date = `${String(startedAt.getFullYear()).slice(2)}${two(startedAt.getMonth() + 1)}${two(startedAt.getDate())}`;
  const safeId = missionId.replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 80) || 'mission';
  const run = `${two(startedAt.getHours())}${two(startedAt.getMinutes())}${two(startedAt.getSeconds())}_${safeId}`;
  return { date, run };
}

/** 판 경로 — 이 PC 창구는 `/mission-records/api` 뒤, 서버는 `/api/v1` 뒤에 붙는다. */
const runPath = (date: string, run: string) => `/runs/${encodeURIComponent(date)}/${encodeURIComponent(run)}`;
const runUrl = (date: string, run: string) => `${BASE}/api${runPath(date, run)}`;
const filePath = (date: string, run: string, path: string) =>
  `/files/${encodeURIComponent(date)}/${encodeURIComponent(run)}/${path.split('/').map(encodeURIComponent).join('/')}`;

// ── 저장처 ────────────────────────────────────────────────────────────────────

/** 판 하나의 저장처. */
export type RecordSink = 'server' | 'local';

export type RecordWriteFailure = 'server-failed' | 'server-rejected' | 'local-missing' | 'local-failed';

/** 쓰기 실패 — 어느 쪽이 왜 못 받았나를 든다. 메시지는 예전 그대로다(이 PC 404 는 ` 404` 로 끝난다). */
export class RecordWriteError extends Error {
  readonly failure: RecordWriteFailure;
  constructor(message: string, failure: RecordWriteFailure) {
    super(message);
    this.failure = failure;
  }
}

/** 이 PC 창구가 있나 — 마지막으로 읽거나 쓴 결과. 처음엔 있다고 본다. */
let localAvailable = true;

export function localRecordsAvailable(): boolean {
  return localAvailable;
}

/**
 * **판을 열 때 저장처를 고른다.** 서버가 `연결됨` 이면 서버, 아니면 이 PC.
 * 서버 주소가 있는데 이 PC 창구도 없으면(단독 빌드 · 다른 장치) null — 지금은 쓸 곳이 없다. 기록기는 다음 주기에 다시 고른다.
 */
export function chooseSink(): RecordSink | null {
  if (historyServerConnected()) return 'server';
  if (localAvailable || historyApiBase() === null) return 'local';
  return null;
}

/**
 * **쓰기가 실패한 뒤 그 판을 어디로.** 두 기록기가 같은 규칙을 쓴다.
 *
 *   서버가 못 받음 · 거절   → 이 PC 로 (대피). 이 PC 창구도 없으면 null (다음 주기에 다시 고른다)
 *   이 PC 창구 없음(404)    → 서버 주소가 없으면 `stop` (예전 규칙: 기록기가 멈춘다). 있으면 null
 *   그 밖                   → 그대로 (다음 주기에 다시 쓴다)
 */
export function nextSink(current: RecordSink | null, error: unknown): { sink: RecordSink | null; evacuated: boolean; stop: boolean } {
  const failure = error instanceof RecordWriteError ? error.failure : null;
  if (failure === 'server-failed' || failure === 'server-rejected') {
    return localAvailable ? { sink: 'local', evacuated: true, stop: false } : { sink: null, evacuated: false, stop: false };
  }
  if (failure === 'local-missing') {
    return historyApiBase() === null ? { sink: current, evacuated: false, stop: true } : { sink: null, evacuated: false, stop: false };
  }
  return { sink: current, evacuated: false, stop: false };
}

async function writeServer(path: string, method: 'PUT' | 'POST', contentType: string, body: string | Blob | Uint8Array): Promise<void> {
  // 판을 연 뒤 서버가 불안정해졌으면 보내 보지도 않고 대피한다 — 「연결됨일 때만 서버」.
  if (!historyServerConnected()) throw new RecordWriteError(t('rcc.serverNotConnected'), 'server-failed');
  const answer = await writeToHistoryServer(path, method, contentType, body);
  if (answer.result === 'ok') return;
  throw new RecordWriteError(t('rcc.serverWriteFailed', { reason: answer.reason }), answer.result === 'rejected' ? 'server-rejected' : 'server-failed');
}

async function writeLocal(date: string, run: string, url: string, init: RequestInit, error: (status: number) => string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    throw new RecordWriteError(cause instanceof Error ? cause.message : String(cause), 'local-failed');
  }
  if (response.status === 404) { localAvailable = false; throw new RecordWriteError(error(404), 'local-missing'); }
  if (!response.ok) throw new RecordWriteError(error(response.status), 'local-failed');
  localAvailable = true;
  noteLocalRecordWrite(date, run);
}

export async function putRecordJson(date: string, run: string, file: 'mission.json' | 'progress.json', body: string,
  sink: RecordSink = 'local'): Promise<void> {
  if (sink === 'server') return writeServer(`${runPath(date, run)}/${file}`, 'PUT', 'application/json', body);
  return writeLocal(date, run, `${runUrl(date, run)}/${file}`,
    { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body },
    (status) => t('rcc.saveFailed', { file, status }));
}

/** `images/detect/x.jpg` 꼴의 경로로 그림 바이트를 올린다. */
export async function postRecordImage(date: string, run: string, path: string, bytes: Blob | Uint8Array,
  sink: RecordSink = 'local'): Promise<void> {
  const [, dir, name] = path.split('/');
  const tail = `/images/${encodeURIComponent(dir)}/${encodeURIComponent(name)}`;
  if (sink === 'server') return writeServer(`${runPath(date, run)}${tail}`, 'POST', 'image/jpeg', bytes);
  return writeLocal(date, run, `${runUrl(date, run)}${tail}`,
    { method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body: bytes as BodyInit },
    (status) => t('rcc.imageSaveFailed', { status }));
}

// ── 읽기 ──────────────────────────────────────────────────────────────────────

/**
 * 판을 어느 목록에서 봤나 — 다시보기 · 그림 주소가 이것으로 읽을 곳을 고른다. 목록에 없던 판은 이 PC 다.
 * 목록을 다시 읽어도 지우지 않는다 — 서버 판을 열어 둔 채 목록이 이 PC 로 내려가도 그 판은 서버에서 읽는다.
 */
const whereByRun = new Map<string, RecordSink>();

/** 저장된 파일의 주소. 다시보기가 그림과 JSON 을 여기서 읽는다. */
export function recordFileUrl(date: string, run: string, path: string): string {
  const server = historyApiBase();
  if (server !== null && whereByRun.get(`${date}/${run}`) === 'server') return `${server}${filePath(date, run, path)}`;
  return `${BASE}${filePath(date, run, path)}`;
}

/** 탐지 그림의 저장 이름 — 기록기와 다시보기가 같은 함수를 쓴다. */
export function detectImagePath(name: 'path_overlay' | 'map' | { frame: string; kind: string }): string {
  if (typeof name === 'string') return `images/detect/${name}.jpg`;
  const stem = name.frame.replace(/\.(jpg|jpeg|png)$/i, '').replace(/[^A-Za-z0-9_.-]/g, '_');
  return `images/detect/${stem}_${name.kind}.jpg`;
}

/**
 * 스캔 탐지(data_stream) 각도 그림의 저장 이름 (261124) — 기록기와 다시보기가 같은 함수를 쓴다.
 * 기록 창구 · 이력 서버가 그림 폴더를 `detect` · `robot` 둘만 받으므로 `detect` 안에 `scan_` 이름으로 둔다.
 */
export function scanImagePath(rotationDeg: number, kind: 'original' | 'overlay' | 'crop'): string {
  const deg = ((Math.round(rotationDeg) % 360) + 360) % 360;
  return `images/detect/scan_rot_${String(deg).padStart(3, '0')}_${kind}.jpg`;
}

/** 로봇 원본의 저장 이름 — 각도 세 자리. */
export function robotImagePath(rotationDeg: number): string {
  const deg = ((Math.round(rotationDeg) % 360) + 360) % 360;
  return `images/robot/rot_${String(deg).padStart(3, '0')}.jpg`;
}

async function readList(url: string): Promise<{ dir: string; runs: RecordedRun[] } | null> {
  try {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) return null;
    const body = await response.json() as { dir?: string; runs?: RecordedRun[] };
    return Array.isArray(body.runs) ? { dir: body.dir ?? '', runs: body.runs } : null;
  } catch {
    return null;
  }
}

/** 판 목록과 그 출처 (261119). */
export type RecordedRunList = {
  /** 이 PC 목록이면 기록 폴더, 서버 목록이면 서버가 준 이름. */
  dir: string;
  runs: RecordedRun[];
  source: RecordSink;
  /** 서버가 답하는데 목록을 못 읽어 이 PC 로 내려왔다. */
  serverFailed: boolean;
};

/**
 * 판 목록 — **한 출처.** 서버가 답하면 서버 목록만, 아니면 이 PC 목록만. 둘 다 못 읽었으면 null
 * (「못 읽었다」와 「비었다」를 가른다).
 */
export async function listRecordedRuns(): Promise<RecordedRunList | null> {
  const api = historyApiBase();
  if (api !== null && historyServerReadable()) {
    const server = await readList(`${api}/runs`);
    if (server !== null) {
      const runs = server.runs.filter((run) => run.date !== CONFORMANCE_DATE);
      // 서버 띠의 「서버 판 N개」 — health 의 수는 검사 판까지 세므로 이 수를 쓴다 (261119 서버 회신 §5).
      noteServerListCount(runs.length);
      for (const run of runs) whereByRun.set(`${run.date}/${run.run}`, 'server');
      return { dir: server.dir, runs, source: 'server', serverFailed: false };
    }
    const local = await readList(`${BASE}/api/runs`);
    localAvailable = local !== null;
    if (local === null) return null;
    for (const run of local.runs) whereByRun.set(`${run.date}/${run.run}`, 'local');
    return { ...local, source: 'local', serverFailed: true };
  }
  const local = await readList(`${BASE}/api/runs`);
  localAvailable = local !== null;
  if (local === null) return null;
  for (const run of local.runs) whereByRun.set(`${run.date}/${run.run}`, 'local');
  return { ...local, source: 'local', serverFailed: false };
}

export async function fetchRecordJson<T>(date: string, run: string, file: 'mission.json' | 'progress.json'): Promise<T> {
  const response = await fetch(recordFileUrl(date, run, file), { cache: 'no-store' }).catch(() => null);
  if (response === null || !response.ok) {
    throw new Error(t('rcc.readFailed', { path: `${date}/${run}/${file}`, status: response?.status ?? 0 }));
  }
  return await response.json() as T;
}

// ── 대피 판 올리기가 쓰는 이 PC 읽기 (`historyUpload.ts`) ─────────────────────────

/** 이 PC 판의 파일 목록. 없거나 못 읽으면 null. */
export async function listLocalRunFiles(date: string, run: string): Promise<string[] | null> {
  try {
    const response = await fetch(`${runUrl(date, run)}/files`, { cache: 'no-store' });
    if (!response.ok) return null;
    const body = await response.json() as { files?: unknown };
    return Array.isArray(body.files) ? body.files.filter((f): f is string => typeof f === 'string') : null;
  } catch {
    return null;
  }
}

/** 이 PC 판의 파일 한 개. */
export async function readLocalRecordFile(date: string, run: string, path: string): Promise<Blob | null> {
  try {
    const response = await fetch(`${BASE}${filePath(date, run, path)}`, { cache: 'no-store' });
    return response.ok ? await response.blob() : null;
  } catch {
    return null;
  }
}

/** 서버에 판 파일 한 개를 쓴다 — 올리기용. 경로는 판 폴더 안의 것(`mission.json` · `images/detect/x.jpg`). */
export async function uploadRecordFile(date: string, run: string, path: string, body: Blob): Promise<'ok' | 'rejected' | 'failed'> {
  const isJson = path.endsWith('.json');
  const answer = await writeToHistoryServer(
    `${runPath(date, run)}/${path.split('/').map(encodeURIComponent).join('/')}`,
    isJson ? 'PUT' : 'POST',
    isJson ? 'application/json' : path.endsWith('.png') ? 'image/png' : 'image/jpeg',
    body,
  );
  return answer.result;
}
