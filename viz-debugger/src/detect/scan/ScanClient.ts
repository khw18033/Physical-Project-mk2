/**
 * src/detect/scan/ScanClient.ts (261123 신설 — 스캔 탐지를 data_stream 으로 · S1)
 *
 * **data_stream 스캔 창구를 아는 면 하나.** 경로(`/scan/*`)가 이 파일 밖에 적히지 않는다.
 * 창구는 data_stream 소스 서버(`server_stream_multi_source.py`)에 붙는다(결정 12) — 그래서 `base` 는
 * **장치의 추론 스트림 포트**(`http://<서버>:10003` 등)다. 장치 → 포트는 `scanAddress.ts` 가 정한다.
 *
 * 이 파일은 **순수하다** — `fetch` 를 받아 쓰고 화면 · 상태를 모른다. 실패는 사유 **코드**로 돌려주고, 글로 푸는 것은
 * 화면이 한다(사전 키). 검사(`verify:scan-detect`)가 가짜 창구에 그대로 붙인다.
 */

import { parseMark, parsePrepare, parseResult, parseStatus } from './parse.ts';
import type {
  ScanImageKind, ScanMarkAnswer, ScanPrepareAnswer, ScanPrepareRequest, ScanResult, ScanStatusAnswer,
} from './types.ts';

export type ScanFetch = (url: string, init?: { method?: string; headers?: Record<string, string>; body?: string; signal?: AbortSignal }) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

export type ScanFailure = {
  ok: false;
  /**
   * network 못 닿음 · timeout 시간 넘김 · http 오류 응답 · shape 응답 모양이 다름 · busy 다른 판이 도는 중(409) ·
   * bad_query 찾을 이름을 data_stream 이 못 받았다(400, 261124) — `detail` 을 사람에게 보이고 이름을 다시 받는다
   */
  code: 'network' | 'timeout' | 'http' | 'shape' | 'busy' | 'bad_query';
  status: number | null;
  detail: string;
  /** busy 일 때 진행 중인 판. */
  busyScanId: string | null;
};
export type ScanCall<T> = { ok: true; value: T } | ScanFailure;

/** 창구마다 기다리는 한도(ms). `mark` 는 data_stream 이 2초 안에 답하기로 했다 — 망 지연 몫을 얹는다(요청 문서 §6). */
export const SCAN_CALL_MS = { prepare: 8000, status: 4000, mark: 3500, finish: 4000, result: 4000, cancel: 4000 } as const;

const trim = (base: string) => base.trim().replace(/\/+$/, '');

function fail(code: ScanFailure['code'], detail: string, status: number | null = null, busyScanId: string | null = null): ScanFailure {
  return { ok: false, code, status, detail, busyScanId };
}

async function call<T>(
  fetcher: ScanFetch, url: string, method: 'GET' | 'POST', body: unknown, timeoutMs: number,
  parse: (raw: unknown) => T | null,
): Promise<ScanCall<T>> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), timeoutMs);
  try {
    const response = await fetcher(url, {
      method,
      headers: method === 'POST' ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: method === 'POST' ? JSON.stringify(body) : undefined,
      signal: abort.signal,
    });
    let raw: unknown = null;
    try { raw = await response.json(); } catch { raw = null; }
    // data_stream 오류 응답은 `{error, detail, …}` 다(구현 보고 `스캔탐지_창구_구현보고_261124.md` §3-10).
    // error: busy · bad_state · unknown_scan · unknown_device · wrong_port(+ stream: 맞는 소스) · bad_request
    const said = raw !== null && typeof raw === 'object' ? raw as { error?: unknown; detail?: unknown; stream?: unknown; busy_scan_id?: unknown; scan_id?: unknown } : {};
    // 409 라도 「다른 판이 도는 중」만 busy 다 — `mark` 를 엉뚱한 상태에서 보낸 409(bad_state)는 그냥 오류다.
    // 진행 중인 판은 `busy_scan_id`(회신 §5)로 오고, 요청 문서에 적었던 `scan_id` 도 받는다.
    if (response.status === 409 && (said.error === undefined || said.error === 'busy' || typeof said.busy_scan_id === 'string')) {
      const busy = typeof said.busy_scan_id === 'string' ? said.busy_scan_id : typeof said.scan_id === 'string' ? said.scan_id : null;
      return fail('busy', 'HTTP 409', 409, busy);
    }
    // 400 bad_query — 찾을 이름을 못 받았다(261124 · 요청 C). 사유는 data_stream 이 준 `detail` 그대로 사람에게 간다.
    if (response.status === 400 && said.error === 'bad_query') {
      return fail('bad_query', typeof said.detail === 'string' && said.detail !== '' ? said.detail : 'bad_query', 400);
    }
    if (!response.ok) {
      const words = [said.error, said.detail, typeof said.stream === 'string' ? `stream ${said.stream}` : undefined]
        .filter((word): word is string => typeof word === 'string' && word !== '');
      return fail('http', `HTTP ${response.status}${words.length > 0 ? ` ${words.join(' · ')}` : ''}`, response.status);
    }
    const value = parse(raw);
    return value === null ? fail('shape', url.replace(/^https?:\/\/[^/]+/, ''), response.status) : { ok: true, value };
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') return fail('timeout', `${timeoutMs}ms`);
    return fail('network', error instanceof Error ? error.message : String(error));
  } finally {
    clearTimeout(timer);
  }
}

export type ScanClient = {
  base: string;
  prepare(request: ScanPrepareRequest): Promise<ScanCall<ScanPrepareAnswer>>;
  status(scanId: string): Promise<ScanCall<ScanStatusAnswer>>;
  mark(scanId: string, rotationDeg: number): Promise<ScanCall<ScanMarkAnswer>>;
  finish(scanId: string): Promise<ScanCall<{ scan_id: string; state: string }>>;
  result(scanId: string): Promise<ScanCall<ScanResult>>;
  cancel(scanId: string): Promise<ScanCall<{ scan_id: string; state: string }>>;
  /** 그 각도 그림의 주소 — `<img>` 로 연다(표시는 CORS 가 필요 없다). */
  frameUrl(scanId: string, rotationDeg: number, kind: ScanImageKind): string;
};

const echo = (raw: unknown): { scan_id: string; state: string } | null => {
  if (raw === null || typeof raw !== 'object') return null;
  const { scan_id: id, state } = raw as { scan_id?: unknown; state?: unknown };
  return typeof id === 'string' && typeof state === 'string' ? { scan_id: id, state } : null;
};

export function scanClient(base: string, fetcher: ScanFetch = globalThis.fetch as unknown as ScanFetch): ScanClient {
  const root = trim(base);
  const q = (scanId: string) => `scan_id=${encodeURIComponent(scanId)}`;
  return {
    base: root,
    prepare: (request) => call(fetcher, `${root}/scan/prepare`, 'POST', request, SCAN_CALL_MS.prepare, parsePrepare),
    status: (scanId) => call(fetcher, `${root}/scan/status?${q(scanId)}`, 'GET', null, SCAN_CALL_MS.status, parseStatus),
    mark: (scanId, rotationDeg) => call(fetcher, `${root}/scan/mark`, 'POST', { scan_id: scanId, rotation_deg: rotationDeg }, SCAN_CALL_MS.mark, parseMark),
    finish: (scanId) => call(fetcher, `${root}/scan/finish`, 'POST', { scan_id: scanId }, SCAN_CALL_MS.finish, echo),
    result: (scanId) => call(fetcher, `${root}/scan/result?${q(scanId)}`, 'GET', null, SCAN_CALL_MS.result, parseResult),
    cancel: (scanId) => call(fetcher, `${root}/scan/cancel`, 'POST', { scan_id: scanId }, SCAN_CALL_MS.cancel, echo),
    frameUrl: (scanId, rotationDeg, kind) => `${root}/scan/frame?${q(scanId)}&rotation_deg=${rotationDeg}&kind=${kind}`,
  };
}

/** 판 번호 — `<임무>-<UTC 초>`. 요청 문서 §3-1 의 예와 같은 모양이다. */
export function newScanId(missionId: string, now: Date = new Date()): string {
  const stamp = now.toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  return `${missionId}-${stamp}`;
}
