/**
 * src/record/recordClient.ts (260914 신설)
 *
 * **임무 기록 창구를 아는 면 하나.** 주소와 파일 이름이 여기 밖으로 안 나간다 — 탐지 주소를
 * `DetectClient.ts` 에 가두는 것과 같은 규칙이다. 창구 본체는 `scripts/mission-records.mjs`.
 *
 * 창구는 개발·미리보기 서버에만 있다. 단독 빌드를 파일로 열었거나 서버가 없으면 404 이고,
 * 그때 기록기는 조용히 멈추고 이력 목록은 「이 세션에서 본 것만」으로 돌아간다.
 *
 * ## 임무 이력 서버 (261119)
 *
 * 임무 이력 탭에서 서버 주소를 넣으면(`historyServer.ts`) **창구가 둘**이 된다. 규약은 서버가 이 PC 창구와
 * 같은 모양을 내는 것이다(`/api/v1/runs/…` · `/api/v1/files/…`) — 그래서 바꿀 것은 뿌리 주소뿐이다.
 *
 *   쓰기   이 PC 창구에 먼저 쓰고 서버에도 같이 보낸다. 서버가 끊겼으면 줄에 남겼다가 다시 붙으면 보낸다.
 *          이 PC 창구가 없는 화면(단독 빌드 · 다른 장치)이면 서버가 유일한 저장처다.
 *   목록   서버가 붙어 있으면 두 목록을 합친다 — 판마다 어디에 있는지(`where`)를 같이 든다.
 *   파일   그 판이 이 PC 에 있으면 이 PC 에서, 서버에만 있으면 서버에서 읽는다.
 */

import { t } from '../i18n/dict.ts';
import type { ControlRecordSummary } from './controlRecorder.ts';
import {
  CONFORMANCE_DATE, historyApiBase, historyServerConnected, sendToHistoryServer,
} from './historyServer.ts';

const BASE = '/mission-records';

/** 목록 한 줄 — `mission.json` 에서 본문(`view`)을 뺀 것. */
export type RecordedRun = {
  date: string;
  run: string;
  /** 임무 판이거나 조작 판(`recordKind: 'control'`, 261110)이다. 갈라 읽는 것은 `isControlSummary`. */
  mission: RecordMissionSummary | ControlRecordSummary | null;
  /** 어디에 있나 (261119). 목록을 읽은 쪽이 채운다 — 서버가 준 줄에는 없다. */
  where?: { local: boolean; server: boolean };
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

/**
 * 판이 어디에 있나 — 마지막으로 읽은 목록에서 (261119). 다시보기 · 그림 주소가 이것으로 읽을 곳을 고른다.
 * 목록에 없던 판(방금 시작한 판 등)은 이 PC 다.
 */
const whereByRun = new Map<string, { local: boolean; server: boolean }>();
let localAvailable = true;

/** 저장된 파일의 주소. 다시보기가 그림과 JSON 을 여기서 읽는다. */
export function recordFileUrl(date: string, run: string, path: string): string {
  const where = whereByRun.get(`${date}/${run}`);
  const server = historyApiBase();
  if (server !== null && where !== undefined && !where.local && where.server) return `${server}${filePath(date, run, path)}`;
  return `${BASE}${filePath(date, run, path)}`;
}

/** 탐지 그림의 저장 이름 — 기록기와 다시보기가 같은 함수를 쓴다. */
export function detectImagePath(name: 'path_overlay' | 'map' | { frame: string; kind: string }): string {
  if (typeof name === 'string') return `images/detect/${name}.jpg`;
  const stem = name.frame.replace(/\.(jpg|jpeg|png)$/i, '').replace(/[^A-Za-z0-9_.-]/g, '_');
  return `images/detect/${stem}_${name.kind}.jpg`;
}

/** 로봇 원본의 저장 이름 — 각도 세 자리. */
export function robotImagePath(rotationDeg: number): string {
  const deg = ((Math.round(rotationDeg) % 360) + 360) % 360;
  return `images/robot/rot_${String(deg).padStart(3, '0')}.jpg`;
}

/**
 * 두 곳에 쓴다 (261119). **이 PC 창구가 답의 기준이다** — 서버는 줄로 따로 간다(`historyServer.ts`).
 * 이 PC 창구가 없으면(404 · 닿지 않음) 서버가 받았는지가 답이 된다. 서버를 설정하지 않았으면 이 PC 의 실패를
 * 그대로 던진다 — 기록기가 404 를 보고 「창구 없음」으로 멈추는 규칙이 그대로 산다.
 */
async function writeBoth(local: () => Promise<Response>, localError: (status: number) => string,
  serverPath: string, method: 'PUT' | 'POST', contentType: string, body: string | Blob | Uint8Array): Promise<void> {
  const mirrored = sendToHistoryServer(serverPath, method, contentType, body);
  let failure: Error;
  try {
    const response = await local();
    if (response.ok) { localAvailable = true; return; }
    if (response.status === 404) localAvailable = false;
    failure = new Error(localError(response.status));
  } catch (error) {
    failure = error instanceof Error ? error : new Error(String(error));
  }
  if (historyApiBase() === null) throw failure;
  if (await mirrored) return;
  // 서버도 못 받았다(끊김 — 줄에는 남았다). 「창구 없음(404)」으로 던지지 않는다 — 기록기가 멈추지 않고 다음 주기에 다시 쓴다.
  throw new Error(t('rcc.serverPending'));
}

export async function putRecordJson(date: string, run: string, file: 'mission.json' | 'progress.json', body: string): Promise<void> {
  await writeBoth(
    () => fetch(`${runUrl(date, run)}/${file}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body }),
    (status) => t('rcc.saveFailed', { file, status }),
    `${runPath(date, run)}/${file}`, 'PUT', 'application/json', body,
  );
}

/** `images/detect/x.jpg` 꼴의 경로로 그림 바이트를 올린다. */
export async function postRecordImage(date: string, run: string, path: string, bytes: Blob | Uint8Array): Promise<void> {
  const [, dir, name] = path.split('/');
  const tail = `/images/${encodeURIComponent(dir)}/${encodeURIComponent(name)}`;
  await writeBoth(
    () => fetch(`${runUrl(date, run)}${tail}`, { method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body: bytes as BodyInit }),
    (status) => t('rcc.imageSaveFailed', { status }),
    `${runPath(date, run)}${tail}`, 'POST', 'image/jpeg', bytes,
  );
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

/** 판 목록과 그것이 어디서 왔나 (261119). */
export type RecordedRunList = {
  dir: string;
  runs: RecordedRun[];
  /** 이 PC 창구를 읽었나. */
  local: boolean;
  /** 서버: 안 씀(주소 없음 · 끊김) · 읽음 · 붙어 있는데 목록을 못 읽음. */
  server: 'off' | 'ok' | 'failed';
  /** 서버 목록의 판 수 (숨긴 검사 판 뺌). */
  serverCount: number;
  /** 이 PC 에만 있는 판 수 — 서버 목록을 읽었을 때만 센다. 아직 안 올라간 판이다. */
  localOnly: number;
};

/**
 * 판 목록. 이 PC 창구도 서버도 못 읽었으면 null — 「못 읽었다」와 「비었다」를 가른다.
 * 서버가 붙어 있으면 두 목록을 합친다. 같은 판이 양쪽에 있으면 이 PC 것을 쓴다(이 PC 에 먼저 쓰므로 더 새것이다).
 */
export async function listRecordedRuns(): Promise<RecordedRunList | null> {
  const api = historyApiBase();
  const useServer = api !== null && historyServerConnected();
  const [local, server] = await Promise.all([
    readList(`${BASE}/api/runs`),
    useServer ? readList(`${api}/runs`) : Promise.resolve(null),
  ]);
  localAvailable = local !== null;
  if (local === null && server === null) return null;
  const merged = new Map<string, RecordedRun>();
  for (const run of server?.runs ?? []) {
    if (run.date === CONFORMANCE_DATE) continue;
    merged.set(`${run.date}/${run.run}`, { ...run, where: { local: false, server: true } });
  }
  const serverCount = merged.size;
  let localOnly = 0;
  for (const run of local?.runs ?? []) {
    const key = `${run.date}/${run.run}`;
    const onServer = merged.has(key);
    if (!onServer) localOnly += 1;
    merged.set(key, { ...run, where: { local: true, server: onServer } });
  }
  whereByRun.clear();
  for (const [key, run] of merged) if (run.where !== undefined) whereByRun.set(key, run.where);
  const runs = [...merged.values()].sort((a, b) => `${b.date}/${b.run}`.localeCompare(`${a.date}/${a.run}`));
  return {
    dir: local?.dir ?? '',
    runs,
    local: local !== null,
    server: !useServer ? 'off' : server === null ? 'failed' : 'ok',
    serverCount,
    localOnly: server === null ? 0 : localOnly,
  };
}

export async function fetchRecordJson<T>(date: string, run: string, file: 'mission.json' | 'progress.json'): Promise<T> {
  const url = recordFileUrl(date, run, file);
  let response = await fetch(url, { cache: 'no-store' }).catch(() => null);
  // 이 PC 에서 못 읽었는데 서버가 있으면 서버에서 한 번 더 — 이 PC 창구가 없는 화면이거나 목록을 읽기 전이다.
  const api = historyApiBase();
  if ((response === null || !response.ok) && api !== null && url.startsWith(BASE)) {
    const fromServer = await fetch(`${api}${filePath(date, run, file)}`, { cache: 'no-store' }).catch(() => null);
    if (fromServer !== null && fromServer.ok) {
      // 그림도 서버에서 읽게 — 다시보기가 이 판의 그림 주소를 이것으로 만든다.
      whereByRun.set(`${date}/${run}`, { local: false, server: true });
      response = fromServer;
    }
  }
  if (response === null || !response.ok) {
    throw new Error(t('rcc.readFailed', { path: `${date}/${run}/${file}`, status: response?.status ?? 0 }));
  }
  return await response.json() as T;
}

/** 이 PC 창구가 있나 — 마지막으로 읽거나 쓴 결과. */
export function localRecordsAvailable(): boolean {
  return localAvailable;
}
