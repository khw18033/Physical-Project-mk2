/**
 * src/record/historyServer.ts (261119 신설 — 임무 이력을 서버 DB 와 잇는다)
 *
 * **임무 이력 서버의 주소 · 연결 상태 · 못 보낸 기록.** 지금까지 판은 이 PC 의 저장소 루트
 * `mission-history/` 에만 남아서, 다른 장치에서는 볼 길이 없었다. 서버 담당이 만드는 임무 이력 서버
 * (규약 `documents/협의/임무이력서버_요청_VZ_261119.md`)에 같이 써 두고, 어느 장치에서든 거기서 읽는다.
 *
 * ## 주소는 임무 이력 탭에서 넣는다 (지시)
 *
 * 연결 관리(`shared/connections.ts`)가 아니라 임무 이력 탭 맨 위다. 그래서 저장도 연결 관리 묶음과 따로
 * 이 모듈의 `localStorage` 키 하나에 둔다. 키는 앱 전역이다 — 주소는 이 설치본의 성질이다.
 *
 * ## 이 PC 파일은 그대로 쓴다
 *
 * 서버가 붙어도 기록기는 개발 서버 창구(`mission-records.mjs`)에 **먼저** 쓰고 서버에는 같이 보낸다
 * (`recordClient.ts`). 서버가 잠깐 끊겨도 판이 안 사라지고, 못 보낸 것은 여기 줄에 남았다가 다시 붙으면 간다.
 * 줄은 이 탭이 살아 있는 동안만이다 — 새로고침하면 빈다. 그때 빠진 판은 `npm run history:push` 가 파일에서 올린다.
 *
 * ## 「붙었다」는 health 가 규약대로 답했을 때만
 *
 * 아무 서버나 200 을 주면 붙은 것으로 치지 않는다 — `service: "mission-history"` 를 본다. 주소를 다른 서버
 * (탐지 · 지표)로 잘못 넣으면 「임무 이력 서버가 아니다」로 따로 적는다. 끊김과 주소 잘못을 가른다.
 */

import { useSyncExternalStore } from 'react';

export const HISTORY_API_PATH = '/api/v1';
export const HISTORY_SERVICE = 'mission-history';
/** 서버 적합성 검사(`scripts/check-history-server.mjs`)가 쓰는 날짜. 목록에서 숨긴다. */
export const CONFORMANCE_DATE = '000101';

const STORAGE_KEY = 'viz.historyServer.v1';
const POLL_MS = 10_000;
const TIMEOUT_MS = 4_000;
/** 못 보낸 기록을 들고 있는 상한. 그림이 쌓여 탭이 무거워지지 않게 — 넘치면 오래된 그림부터 버린다. */
const OUTBOX_MAX_BYTES = 64 * 1024 * 1024;

export type HistoryServerState =
  | 'unset'          // 주소를 안 넣었다 — 이 PC 기록만
  | 'checking'       // 확인 중
  | 'connected'      // health 가 규약대로 답했다
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
  /** 서버가 health 에 적은 판 수. 없으면 null. */
  runCount: number | null;
  /** 끊김 · 오류의 사유. */
  detail: string | null;
  /** 서버로 아직 못 보낸 기록 수. */
  pending: number;
  /** 서버가 받기를 거절한 마지막 사유 (4xx). */
  lastRejected: string | null;
};

const empty: HistoryServerStatus = {
  address: '', state: 'unset', checkedAtIso: null, lastOkAtIso: null, latencyMs: null,
  runCount: null, detail: null, pending: 0, lastRejected: null,
};

let status: HistoryServerStatus = { ...empty, address: readStored() };
if (status.address !== '') status = { ...status, state: 'checking' };
const listeners = new Set<() => void>();

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
    return globalThis.localStorage?.getItem(STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
}

function store(address: string): void {
  try {
    if (address === '') globalThis.localStorage?.removeItem(STORAGE_KEY);
    else globalThis.localStorage?.setItem(STORAGE_KEY, address);
  } catch {
    // 저장소가 막혔다 — 이 탭에서만 쓴다.
  }
}

/**
 * 사람이 넣은 주소를 고른다. 틀 밖이면 null.
 *
 *   100.64.0.5:8790            → http://100.64.0.5:8790
 *   http://host:8790/          → http://host:8790
 *   http://host:8790/api/v1    → http://host:8790      (규약 경로까지 붙여 넣은 경우)
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

export function historyServerConnected(): boolean {
  return status.state === 'connected';
}

/** 주소를 바꾼다. 빈 글자면 연결을 푼다. 틀 밖이면 그대로 두고 false. */
export function setHistoryServerAddress(input: string): boolean {
  const address = normalizeServerAddress(input);
  if (address === null) return false;
  store(address);
  // 주소가 바뀌면 지난 서버의 셈은 버린다. 못 보낸 기록은 남긴다 — 새 서버로 간다.
  setStatus({ ...empty, address, state: address === '' ? 'unset' : 'checking', pending: outbox.size });
  if (address !== '') void checkHistoryServer();
  return true;
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
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    const checkedAtIso = new Date().toISOString();
    try {
      const response = await fetch(`${address}${HISTORY_API_PATH}/health`, { cache: 'no-store', signal: controller.signal });
      if (status.address !== address) return;   // 묻는 사이 주소가 바뀌었다
      if (!response.ok) {
        setStatus({ state: 'http-error', checkedAtIso, latencyMs: null, detail: `HTTP ${response.status}` });
        return;
      }
      const body = await response.json().catch(() => null) as { service?: unknown; runCount?: unknown } | null;
      if (body === null || body.service !== HISTORY_SERVICE) {
        setStatus({ state: 'wrong-service', checkedAtIso, latencyMs: null, detail: body === null ? 'not JSON' : `service=${String(body.service)}` });
        return;
      }
      setStatus({
        state: 'connected', checkedAtIso, lastOkAtIso: checkedAtIso, latencyMs: Date.now() - started,
        runCount: typeof body.runCount === 'number' ? body.runCount : null, detail: null,
      });
      void drainOutbox();
    } catch (error) {
      if (status.address !== address) return;
      const why = controller.signal.aborted ? `timeout ${TIMEOUT_MS}ms` : error instanceof Error ? error.message : String(error);
      setStatus({ state: 'unreachable', checkedAtIso, latencyMs: null, detail: why });
    } finally {
      clearTimeout(timer);
      checking = null;
    }
  })();
  return checking;
}

/**
 * 주기적으로 묻는다. 앱이 켤 때 한 번 건다(`main.tsx` — 기록기와 같은 자리).
 * 임무 이력 탭을 안 열어도 돈다 — 기록기가 도는 동안 서버로 보낼지 정해야 한다.
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

// ── 못 보낸 기록 ───────────────────────────────────────────────────────────────

type OutboxJob = {
  /** `/runs/<날짜>/<판>/…` — 창구 뿌리 뒤의 경로. 같은 경로는 새 것이 옛 것을 밀어낸다. */
  path: string;
  method: 'PUT' | 'POST';
  contentType: string;
  body: string | Blob | Uint8Array;
  bytes: number;
  waiters: Array<(ok: boolean) => void>;
};

/**
 * **서버로 가는 쓰기는 전부 이 줄 하나로 차례대로 간다.** 같은 파일을 두 요청이 겹쳐 쓰면 늦게 출발한
 * 옛 본문이 나중에 도착해 새 본문을 덮을 수 있다(기록기가 같은 이유로 차례로 쓴다).
 */
const outbox = new Map<string, OutboxJob>();
let draining = false;

function sizeOf(body: OutboxJob['body']): number {
  return typeof body === 'string' ? body.length : body instanceof Uint8Array ? body.byteLength : body.size;
}

/**
 * 서버로 보낼 것을 줄에 넣는다. 돌려주는 약속은 **이 경로의 이 본문(또는 그 뒤에 온 더 새 본문)이 서버에
 * 들어갔는가**다. 주소가 없으면 곧바로 false.
 */
export function sendToHistoryServer(path: string, method: 'PUT' | 'POST', contentType: string, body: OutboxJob['body']): Promise<boolean> {
  if (status.address === '') return Promise.resolve(false);
  return new Promise((resolve) => {
    const previous = outbox.get(path);
    // 끊겨 있으면 줄에만 넣고 곧바로 false — 기다리게 하면 이 PC 창구가 없는 화면(단독 빌드)에서 기록기가 멈춘다.
    const connected = status.state === 'connected';
    const job: OutboxJob = { path, method, contentType, body, bytes: sizeOf(body), waiters: [...(previous?.waiters ?? []), ...(connected ? [resolve] : [])] };
    if (!connected) resolve(false);
    outbox.delete(path);
    outbox.set(path, job);
    trimOutbox();
    setStatus({ pending: outbox.size });
    void drainOutbox();
  });
}

function trimOutbox(): void {
  let total = 0;
  for (const job of outbox.values()) total += job.bytes;
  if (total <= OUTBOX_MAX_BYTES) return;
  // JSON 은 판의 뼈대라 남기고, 그림부터 오래된 순으로 버린다.
  for (const [path, job] of outbox) {
    if (total <= OUTBOX_MAX_BYTES) break;
    if (job.method !== 'POST') continue;
    outbox.delete(path);
    total -= job.bytes;
    for (const done of job.waiters) done(false);
  }
}

async function drainOutbox(): Promise<void> {
  if (draining) return;
  draining = true;
  try {
    while (outbox.size > 0) {
      const base = historyApiBase();
      // 붙어 있을 때만 보낸다. 끊겼으면 health 가 다시 붙을 때 이 함수를 부른다.
      if (base === null || status.state !== 'connected') {
        for (const job of outbox.values()) for (const done of job.waiters.splice(0)) done(false);
        return;
      }
      const [path, job] = outbox.entries().next().value as [string, OutboxJob];
      let response: Response;
      try {
        response = await fetch(`${base}${path}`, { method: job.method, headers: { 'Content-Type': job.contentType }, body: job.body as BodyInit });
      } catch (error) {
        // 닿지 않는다 — 줄은 그대로 두고 멈춘다. 다음 health 가 붙으면 다시 돈다.
        for (const done of job.waiters.splice(0)) done(false);
        if (status.state === 'connected') {
          setStatus({ state: 'unreachable', detail: error instanceof Error ? error.message : String(error) });
        }
        return;
      }
      const current = outbox.get(path);
      if (response.ok) {
        // 보내는 사이 더 새 본문이 들어왔으면 그것은 남겨 다음에 보낸다.
        if (current === job) outbox.delete(path);
        for (const done of job.waiters.splice(0)) done(true);
      } else if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) {
        // 서버가 거절했다 — 다시 보내도 같다. 버리고 사유를 남긴다.
        if (current === job) outbox.delete(path);
        for (const done of job.waiters.splice(0)) done(false);
        setStatus({ lastRejected: `${job.method} ${path} → HTTP ${response.status}` });
      } else {
        // 서버 쪽 사정(5xx · 408 · 429) — 남겨 두고 멈춘다.
        for (const done of job.waiters.splice(0)) done(false);
        setStatus({ pending: outbox.size, detail: `HTTP ${response.status}` });
        return;
      }
      setStatus({ pending: outbox.size });
    }
  } finally {
    draining = false;
  }
}

/** 검사용 — 모듈 상태를 처음으로. */
export function resetHistoryServerForTest(): void {
  for (const job of outbox.values()) for (const done of job.waiters) done(false);
  outbox.clear();
  checking = null;
  draining = false;
  status = { ...empty, address: readStored() };
  if (status.address !== '') status = { ...status, state: 'checking' };
  for (const listener of listeners) listener();
}
