/**
 * src/record/historyServer.ts (261119 신설 — 임무 이력을 서버 DB 와 잇는다)
 *
 * **임무 이력 서버의 주소와 연결 상태.** 서버 규약은 `documents/협의/임무이력서버_요청_VZ_261119.md`,
 * 가시화 쪽 계획은 `documents/작업프롬프트/작업프롬프트_임무이력서버연동_개발계획_261119.md`.
 *
 * ## 주소는 임무 이력 탭에서 넣는다 (지시)
 *
 * 연결 관리(`shared/connections.ts`)가 아니라 임무 이력 탭 맨 위다. 그래서 저장도 연결 관리 묶음과 따로
 * 이 모듈의 `localStorage` 키 하나에 둔다. 키는 앱 전역이다 — 주소는 이 설치본의 성질이다.
 *
 * ## 서버가 기본 저장처다 (2차 · 261119)
 *
 * 기록은 **`연결됨` 일 때만 서버에, 그 밖에는 이 PC 파일에** 쓴다(판마다 정한다 — `recordClient.ts`).
 * 그래서 「연결됨」을 엄하게 본다.
 *
 *   - health 가 규약대로(`service: "mission-history"`) 답해야 붙은 것이다. 아무 200 은 아니다.
 *   - 서버 쓰기가 **한 번이라도 실패하면 곧바로 `불안정`** — health 를 기다리지 않는다.
 *   - 끊겼거나 불안정했으면 health 가 **두 번 연속** 성공해야 `연결됨` 으로 돌아간다. 와이파이가 흔들릴 때
 *     판이 서버와 파일을 오가며 쪼개지는 것을 줄인다.
 *
 * 1차의 「못 보낸 기록 줄(outbox)」은 뺐다. 서버를 못 쓰면 이 PC 파일이 대피처이고, 대피한 판은
 * `historyUpload.ts` 가 서버가 안정되면 통째로 올린다.
 */

import { useSyncExternalStore } from 'react';

export const HISTORY_API_PATH = '/api/v1';
export const HISTORY_SERVICE = 'mission-history';
/** 서버 적합성 검사(`scripts/check-history-server.mjs`)가 쓰는 날짜. 목록에서 숨긴다. */
export const CONFORMANCE_DATE = '000101';

const STORAGE_KEY = 'viz.historyServer.v1';
/**
 * **기본 주소** (261119 지시) — 서버 담당이 연 임무 이력 서버(회신 `documents/협의/임무이력서버_회신_서버_261119.md`).
 * Tailscale 안에서만 닿는다. 저장된 값이 **아예 없을 때만** 쓴다 — 사람이 「연결 해제」를 누르면 빈 값을 저장해 두므로
 * 새로고침해도 기본 주소로 되살아나지 않는다.
 *
 * **`let status = initialStatus()` 보다 위에 둔다** — 아래에 두면 모듈을 읽는 순간 아직 안 만들어진 상수를 읽어(TDZ)
 * `readStored` 의 catch 가 삼키고 주소가 비었다(261119 실측 — 새 브라우저에서 「서버 미설정」).
 */
export const DEFAULT_HISTORY_SERVER = 'http://100.102.8.102:8850';
const POLL_MS = 10_000;
const HEALTH_TIMEOUT_MS = 4_000;
/** 서버 쓰기 한 건의 시간 한도. 넘으면 실패로 보고 대피한다. */
export const WRITE_TIMEOUT_MS = 5_000;
/** 끊긴 뒤 몇 번 연속 health 가 돼야 다시 `연결됨` 인가. */
const RECOVER_STREAK = 2;

export type HistoryServerState =
  | 'unset'          // 주소를 안 넣었다 — 이 PC 기록만
  | 'checking'       // 처음 확인 중
  | 'connected'      // 서버에 쓴다
  | 'unstable'       // health 는 되지만 쓰기가 실패했거나 막 돌아왔다 — 이 PC 에 쓴다
  | 'unreachable'    // 닿지 않는다 (꺼짐 · 주소 · 방화벽 · CORS)
  | 'wrong-service'  // 답은 왔는데 임무 이력 서버가 아니다
  | 'http-error';    // health 가 2xx 가 아니다

export type HistoryServerStatus = {
  /** 고른 주소(끝 `/` 없음). 비었으면 ''. */
  address: string;
  state: HistoryServerState;
  checkedAtIso: string | null;
  lastOkAtIso: string | null;
  latencyMs: number | null;
  /**
   * 서버가 health 에 적은 판 수. 없으면 null. **화면에 그대로 쓰지 않는다** — 적합성 검사 판(`000101`)까지 센다
   * (서버 회신 261119 §5). 이 값이 바뀌면 목록을 다시 읽는 신호로만 쓴다.
   */
  runCount: number | null;
  /** 화면이 읽은 서버 목록의 판 수 — 검사 판을 뺀 것(`recordClient.listRecordedRuns`). 아직 안 읽었으면 null. 「서버 판 N개」 는 이것이다. */
  listedRunCount: number | null;
  /** 끊김 · 오류 · 불안정의 사유. */
  detail: string | null;
  /** 불안정에서 돌아오는 중 — 연속 성공 횟수. */
  okStreak: number;
  /** 서버가 받기를 거절한 마지막 사유 (4xx). */
  lastRejected: string | null;
};

const empty: HistoryServerStatus = {
  address: '', state: 'unset', checkedAtIso: null, lastOkAtIso: null, latencyMs: null,
  runCount: null, listedRunCount: null, detail: null, okStreak: 0, lastRejected: null,
};

let status: HistoryServerStatus = initialStatus();
/** 한 번이라도 끊기거나 실패했나 — 그러면 돌아올 때 연속 성공을 요구한다. 첫 연결은 한 번이면 된다. */
let needsRecovery = false;
const listeners = new Set<() => void>();

function initialStatus(): HistoryServerStatus {
  const address = readStored();
  return { ...empty, address, state: address === '' ? 'unset' : 'checking' };
}

function setStatus(patch: Partial<HistoryServerStatus>): void {
  status = { ...status, ...patch };
  for (const listener of listeners) listener();
}

export function historyServerStatus(): HistoryServerStatus {
  return status;
}

export function subscribeHistoryServer(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useHistoryServer(): HistoryServerStatus {
  return useSyncExternalStore(subscribeHistoryServer, historyServerStatus, historyServerStatus);
}


function readStored(): string {
  try {
    const storage = globalThis.localStorage;
    // 브라우저 밖(검사 · 노드)에는 저장소가 없다 — 그때는 주소 없음으로 둔다. 기본 주소는 화면에서만.
    if (storage === undefined) return '';
    const value = storage.getItem(STORAGE_KEY);
    return value === null ? DEFAULT_HISTORY_SERVER : value;
  } catch {
    return '';
  }
}

function store(address: string): void {
  try {
    // 빈 값도 적는다 — 「해제했다」를 「한 번도 안 정했다(→ 기본 주소)」와 가른다.
    globalThis.localStorage?.setItem(STORAGE_KEY, address);
  } catch {
    // 저장소가 막혔다 — 이 탭에서만 쓴다.
  }
}

/**
 * 사람이 넣은 주소를 고른다. 틀 밖이면 null.
 *
 *   100.64.0.5:8820            → http://100.64.0.5:8820
 *   http://host:8820/          → http://host:8820
 *   http://host:8820/api/v1    → http://host:8820      (규약 경로까지 붙여 넣은 경우)
 */
export function normalizeServerAddress(input: string): string | null {
  const trimmed = input.trim();
  if (trimmed === '') return '';
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`;
  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    return null;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  if (url.search !== '' || url.hash !== '') return null;
  const path = url.pathname.replace(/\/+$/, '').replace(new RegExp(`${HISTORY_API_PATH.replace(/\//g, '\\/')}$`), '');
  return `${url.protocol}//${url.host}${path}`;
}

/** 서버 창구의 뿌리(`…/api/v1`). 주소를 안 넣었으면 null. */
export function historyApiBase(): string | null {
  return status.address === '' ? null : `${status.address}${HISTORY_API_PATH}`;
}

/** **서버에 쓸 수 있나.** `연결됨` 일 때만이다. */
export function historyServerConnected(): boolean {
  return status.state === 'connected';
}

/** 서버 목록을 읽어도 되나 — health 가 답하는 동안(연결됨 · 불안정). */
export function historyServerReadable(): boolean {
  return status.state === 'connected' || status.state === 'unstable';
}

/** 주소를 바꾼다. 빈 글자면 연결을 푼다. 틀 밖이면 그대로 두고 false. */
export function setHistoryServerAddress(input: string): boolean {
  const address = normalizeServerAddress(input);
  if (address === null) return false;
  store(address);
  // 다른 서버다 — 지난 서버의 셈과 끊긴 이력은 버린다.
  needsRecovery = false;
  setStatus({ ...empty, address, state: address === '' ? 'unset' : 'checking' });
  if (address !== '') void checkHistoryServer();
  return true;
}

/**
 * **서버 쓰기가 실패했다** (`recordClient` · `historyUpload` 가 부른다). 곧바로 `불안정` —
 * 그 뒤로 새 판과 대피한 판은 이 PC 에 쓰고, health 가 두 번 연속 돼야 돌아온다.
 */
export function noteServerWriteFailed(reason: string): void {
  if (status.address === '') return;
  needsRecovery = true;
  const keep = status.state === 'connected' || status.state === 'unstable' || status.state === 'checking';
  setStatus({ state: keep ? 'unstable' : status.state, detail: reason, okStreak: 0 });
}

/** 서버 목록을 읽었다 — 검사 판을 뺀 판 수를 적는다 (`recordClient` 가 부른다). */
export function noteServerListCount(count: number): void {
  if (status.listedRunCount === count) return;
  setStatus({ listedRunCount: count });
}

/** 서버가 거절했다 (4xx) — 우리 쪽 잘못이라 상태는 그대로 두고 사유만 남긴다. */
export function noteServerRejected(what: string): void {
  setStatus({ lastRejected: what });
}

let checking: Promise<void> | null = null;

/** health 를 한 번 묻는다. 이미 묻는 중이면 그 답을 같이 기다린다. */
export function checkHistoryServer(): Promise<void> {
  if (checking !== null) return checking;
  const address = status.address;
  if (address === '') return Promise.resolve();
  checking = (async () => {
    const started = Date.now();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    const checkedAtIso = new Date().toISOString();
    const fail = (state: HistoryServerState, detail: string) => {
      needsRecovery = true;
      setStatus({ state, checkedAtIso, latencyMs: null, detail, okStreak: 0 });
    };
    try {
      const response = await fetch(`${address}${HISTORY_API_PATH}/health`, { cache: 'no-store', signal: controller.signal });
      if (status.address !== address) return;   // 묻는 사이 주소가 바뀌었다
      if (!response.ok) { fail('http-error', `HTTP ${response.status}`); return; }
      const body = await response.json().catch(() => null) as { service?: unknown; runCount?: unknown } | null;
      if (body === null || body.service !== HISTORY_SERVICE) {
        fail('wrong-service', body === null ? 'not JSON' : `service=${String(body.service)}`);
        return;
      }
      const okStreak = status.state === 'connected' ? 0 : status.okStreak + 1;
      const recovered = !needsRecovery || okStreak >= RECOVER_STREAK;
      if (recovered) needsRecovery = false;
      setStatus({
        state: recovered ? 'connected' : 'unstable',
        checkedAtIso, lastOkAtIso: checkedAtIso, latencyMs: Date.now() - started,
        runCount: typeof body.runCount === 'number' ? body.runCount : null,
        detail: recovered ? null : status.detail,
        okStreak: recovered ? 0 : okStreak,
      });
    } catch (error) {
      if (status.address !== address) return;
      fail('unreachable', controller.signal.aborted ? `timeout ${HEALTH_TIMEOUT_MS}ms` : error instanceof Error ? error.message : String(error));
    } finally {
      clearTimeout(timer);
      checking = null;
    }
  })();
  return checking;
}

/**
 * 서버에 한 건 쓴다 — 시간 한도를 걸고. 답의 뜻을 셋으로 가른다.
 *
 *   ok        받았다
 *   rejected  4xx (408 · 429 빼고) — 다시 보내도 같다. 우리 쪽 잘못
 *   failed    닿지 않음 · 시간 초과 · 5xx · 408 · 429 — 서버 사정. `불안정` 으로 바꾼다
 */
export async function writeToHistoryServer(path: string, method: 'PUT' | 'POST', contentType: string,
  body: string | Blob | Uint8Array): Promise<{ result: 'ok' | 'rejected' | 'failed'; reason: string }> {
  const base = historyApiBase();
  if (base === null) return { result: 'failed', reason: 'no server' };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), WRITE_TIMEOUT_MS);
  try {
    const response = await fetch(`${base}${path}`, {
      method, headers: { 'Content-Type': contentType }, body: body as BodyInit, signal: controller.signal,
    });
    if (response.ok) return { result: 'ok', reason: '' };
    const reason = `${method} ${path} → HTTP ${response.status}`;
    if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) {
      noteServerRejected(reason);
      return { result: 'rejected', reason };
    }
    noteServerWriteFailed(reason);
    return { result: 'failed', reason };
  } catch (error) {
    const reason = controller.signal.aborted ? `timeout ${WRITE_TIMEOUT_MS}ms` : error instanceof Error ? error.message : String(error);
    noteServerWriteFailed(reason);
    return { result: 'failed', reason };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 주기적으로 묻는다. 앱이 켤 때 한 번 건다(`main.tsx` — 기록기와 같은 자리).
 * 임무 이력 탭을 안 열어도 돈다 — 새 판을 서버에 쓸지가 이것으로 정해진다.
 */
export function startHistoryServerWatch(): () => void {
  void checkHistoryServer();
  const timer = setInterval(() => { void checkHistoryServer(); }, POLL_MS);
  const again = () => { void checkHistoryServer(); };
  globalThis.addEventListener?.('online', again);
  return () => {
    clearInterval(timer);
    globalThis.removeEventListener?.('online', again);
  };
}

/** 검사용 — 모듈 상태를 처음으로(새로고침 흉내). */
export function resetHistoryServerForTest(): void {
  checking = null;
  needsRecovery = false;
  status = initialStatus();
  for (const listener of listeners) listener();
}
