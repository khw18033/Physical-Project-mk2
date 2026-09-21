/**
 * src/capability/CapabilityClient.ts (260920 신설 — 기능 상태 패널 이식)
 *
 * **기능 상태 서비스를 아는 유일한 면.** 주소·경로·테스트 자료가 이 파일 밖으로 나가지
 * 않는다 — `src/detect/DetectClient.ts` 와 같은 규칙이고 같은 이유다
 * (`verify:capability-source`).
 *
 * ## 두 원천을 한 함수로 가른다
 *
 *   테스트   `sample.ts` 의 값 — 연결 관리의 「테스트」가 켜졌을 때만
 *   실제     `<base>/api/…` — 연결 관리에 넣은 주소
 *
 * `sourceOf(testMode)` 가 그 갈림의 **유일한 자리**다. 다른 파일이 `testMode` 를 보고 자기
 * 나름대로 갈라지면 「테스트를 껐는데 한 칸만 시료가 남는」 모양이 생긴다 — 탐지에서
 * 그것을 한 함수로 막아 둔 이유가 그것이고, 여기도 같다.
 *
 * **테스트 자료도 같은 파서를 탄다.** `sample.ts` 가 서버 응답 모양(snake_case)을 그대로
 * 들고 있어서, 파서가 깨지면 테스트 경로에서도 깨진다.
 *
 * ## 실제 배치는 k3s 안이고 CORS 가 없다
 *
 * `serve.py` 는 `Access-Control-Allow-Origin` 을 안 붙인다. 그래서 개발 서버 창구
 * (`scripts/capability-relay.mjs`)를 지난다. 창구가 없는 서버(정적 빌드)에서는 직접
 * 두드리고, 막히면 그 사유를 그대로 말한다 — 자율주행 AI 창구와 같은 모양이다.
 *
 * ## 여는 길은 넷이고, 그중 하나만 POST 다 (260921)
 *
 *   GET   config · labels · functions   읽기
 *   POST  functions/whatif              가상 조건 계산 — **아무것도 바꾸지 않는다**
 *
 * `placement` 는 **여기에도 창구에도 없다**. 그 POST 는 `--control k3s` 에서 실제 클러스터
 * Deployment 를 바꾼다. 가르는 기준은 메서드가 아니라 「무엇을 바꾸는가」다.
 */

import { t } from '../i18n/dict.ts';
import { connectionAddress, registerConnectionDefault } from '../shared/connections.ts';
import { CAPABILITY_PRESETS } from './presets.ts';
import { encodeOverrides, parseControl, parseLabels, parseSnapshot, parseWhatif } from './parse.ts';
import { SAMPLE_CONFIG, SAMPLE_FUNCTIONS, SAMPLE_LABELS } from './sample.ts';
import {
  EMPTY_LABELS,
  type CapControl, type CapLabels, type CapOverrides, type CapSnapshot, type CapWhatif,
} from './types.ts';

const meta = import.meta as unknown as { env?: { VITE_CAPABILITY_URL?: string } };

/**
 * 기본값은 **검토용 로컬 주소**다(전달본의 실행 방법). 실제 배치의 k3s 주소는 우리가 모르므로
 * 연결 관리에서 넣는다 — 프리셋의 `k3s` 칸이 비어 있는 것과 같은 이유다.
 */
const LOCAL = CAPABILITY_PRESETS.find((preset) => preset.id === 'local')?.url ?? '';
registerConnectionDefault('capability', 'base', meta.env?.VITE_CAPABILITY_URL ?? LOCAL);

/** 개발 서버 창구 — `scripts/capability-relay.mjs` 의 `CAPABILITY_RELAY_URL` 과 같아야 한다. */
const RELAY = '/capability';

/** 지금 쓰는 서비스 주소. 끝의 `/` 는 뗀다. **이 함수 밖에서 주소 문자열을 만들지 않는다.** */
export function capabilityBaseUrl(): string {
  return connectionAddress('capability', 'base').trim().replace(/\/+$/, '');
}

/** 읽는 경로 셋. 창구가 여는 것과 같아야 한다. */
export type CapabilityEndpoint = 'config' | 'labels' | 'functions';

/**
 * 계산만 하는 POST 하나. 창구의 `CAPABILITY_POST_ENDPOINTS` 와 같아야 한다.
 *
 * **배치(`placement`)는 여기 오지 않는다** — 그 POST 는 실제 Deployment 를 바꾼다.
 * 이 경로는 `serve.py` 의 `whatif_functions()` 이고, 그것은 `functions()` 를 두 번 부르는
 * 것이 전부다(계산만 한다).
 */
const WHATIF_ENDPOINT = 'functions/whatif';

export type CapabilitySource = { kind: 'sample' } | { kind: 'live'; base: string };

/**
 * **지금 어디서 읽는가.** 테스트가 켜져 있으면 자료, 아니면 실제 서비스.
 *
 * 갈림은 여기 하나다. 이 함수를 거치지 않고 `sample.ts` 를 여는 자리가 생기면
 * `verify:capability-source` 가 잡는다.
 */
export function sourceOf(testMode: boolean): CapabilitySource {
  return testMode ? { kind: 'sample' } : { kind: 'live', base: capabilityBaseUrl() };
}

export type FetchLike = (input: string, init?: {
  signal?: AbortSignal;
  headers?: Record<string, string>;
  /** What-if 만 `POST` 다. 없으면 GET. */
  method?: string;
  body?: string;
}) => Promise<{
  ok: boolean;
  status: number;
  headers: { get(name: string): string | null };
  json(): Promise<unknown>;
  text(): Promise<string>;
}>;

export type ReadOutcome =
  | { ok: true; body: unknown; via: 'relay' | 'direct' | 'sample' }
  | { ok: false; reason: string };

const SAMPLE_BODY: Record<CapabilityEndpoint, Record<string, unknown>> = {
  config: SAMPLE_CONFIG,
  labels: SAMPLE_LABELS,
  functions: SAMPLE_FUNCTIONS,
};

const TIMEOUT_MS = 8000;

/** 한 번 두드린다. `body` 가 있으면 POST 다. **던지지 않는다** — 사유도 결과다. */
async function attempt(
  doFetch: FetchLike, url: string, via: 'relay' | 'direct', body: string | null,
): Promise<ReadOutcome & { relayed?: boolean }> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== null) headers['Content-Type'] = 'application/json';
    const response = await doFetch(url, body === null
      ? { signal: abort.signal, headers }
      : { signal: abort.signal, headers, method: 'POST', body });
    const relayed = response.headers.get('X-Capability-Relay') === '1';
    if (!response.ok) {
      // 창구가 없으면 개발 서버가 index.html 을 200 으로 돌려주기도 한다 — 그건 아래에서 걸린다.
      return { ok: false, reason: t('cap.status', { status: response.status }), relayed };
    }
    const parsed: unknown = await response.json();
    return { ok: true, body: parsed, via, relayed };
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : String(error), relayed: false };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 창구를 먼저 쓴다. 창구가 없는 서버(정적 빌드)면 `X-Capability-Relay` 가 안 붙어 오므로
 * 그때만 직접 두드린다 — 자율주행 AI 와 같은 가름이다.
 *
 * **읽기와 계산이 같은 길을 탄다.** 갈림이 둘이 되면 한쪽만 창구를 안 타는 날이 온다.
 */
async function call(
  base: string, endpoint: string, body: string | null, fetcher?: FetchLike,
): Promise<ReadOutcome> {
  if (base === '') return { ok: false, reason: t('cap.noAddress') };
  const doFetch = (fetcher ?? globalThis.fetch) as FetchLike | undefined;
  if (doFetch === undefined) return { ok: false, reason: t('cap.noFetch') };
  const query = `?base=${encodeURIComponent(base)}`;
  const viaRelay = await attempt(doFetch, `${RELAY}/${endpoint}${query}`, 'relay', body);
  if (viaRelay.ok && viaRelay.relayed === true) return { ok: true, body: viaRelay.body, via: 'relay' };
  // 창구가 없다 — 정적 빌드다. 직접 두드린다. CORS 가 막으면 그 사유가 그대로 온다.
  const direct = await attempt(doFetch, `${base}/api/${endpoint}`, 'direct', body);
  if (direct.ok) return { ok: true, body: direct.body, via: 'direct' };
  return { ok: false, reason: viaRelay.ok ? direct.reason : viaRelay.reason };
}

/** 한 경로를 읽는다. 테스트가 켜져 있으면 붙잡아 둔 응답이다. */
export async function readCapability(
  source: CapabilitySource, endpoint: CapabilityEndpoint, fetcher?: FetchLike,
): Promise<ReadOutcome> {
  if (source.kind === 'sample') return { ok: true, body: SAMPLE_BODY[endpoint], via: 'sample' };
  return call(source.base, endpoint, null, fetcher);
}

export type SnapshotOutcome =
  | { ok: true; snapshot: CapSnapshot; via: 'relay' | 'direct' | 'sample' }
  | { ok: false; reason: string };

/** 기능·노드 한 벌. 모양이 아니면 실패다 — 엉뚱한 주소에 붙었을 때 빈 화면 대신 사유가 뜬다. */
export async function fetchSnapshot(source: CapabilitySource, fetcher?: FetchLike): Promise<SnapshotOutcome> {
  const outcome = await readCapability(source, 'functions', fetcher);
  if (!outcome.ok) return outcome;
  const snapshot = parseSnapshot(outcome.body);
  if (snapshot === null) return { ok: false, reason: t('cap.shape') };
  return { ok: true, snapshot, via: outcome.via };
}

/** 라벨. 못 받으면 빈 묶음이고, 그때 화면은 ID 를 그대로 적는다 — 그것이 전달본의 규칙이다. */
export async function fetchLabels(source: CapabilitySource, fetcher?: FetchLike): Promise<CapLabels> {
  const outcome = await readCapability(source, 'labels', fetcher);
  return outcome.ok ? parseLabels(outcome.body) : EMPTY_LABELS;
}

/** 배치 모드. 못 받으면 null — 「모른다」이지 local 이 아니다. */
export async function fetchControl(source: CapabilitySource, fetcher?: FetchLike): Promise<CapControl | null> {
  const outcome = await readCapability(source, 'config', fetcher);
  return outcome.ok ? parseControl(outcome.body) : null;
}

export type WhatifOutcome =
  | { ok: true; whatif: CapWhatif; via: 'relay' | 'direct' }
  | { ok: false; reason: string };

/**
 * **가상 조건을 걸어 본다.** `before`·`after`·`diff` 가 한 응답에 온다.
 *
 * ## 테스트 자료로는 못 한다
 *
 * 붙잡아 둔 것은 **한 장면**이고(2026-09-20 의 `GET /api/functions` 한 건), 조건을 바꿔
 * 다시 계산해 줄 서버가 없다. 여기서 `before` 를 그대로 `after` 로 돌려주면 화면은
 * 「조건을 걸었는데 아무것도 안 바뀐다」를 보여 주고, 그것은 **없는 계산을 했다고 말하는
 * 것**이다. 그래서 사유를 내고, 화면은 조작면을 끈다.
 *
 * ## 배치는 안 바뀐다
 *
 * `serve.py` 의 `whatif_functions()` 는 `functions()` 를 두 번 부르는 것이 전부다.
 * `--control k3s` 에서도 Deployment 에 손대지 않는다 — 그것이 창구가 이 경로만 POST 로
 * 여는 근거다(`scripts/capability-relay.mjs`).
 */
export async function fetchWhatif(
  source: CapabilitySource, overrides: CapOverrides, fetcher?: FetchLike,
): Promise<WhatifOutcome> {
  if (source.kind === 'sample') return { ok: false, reason: t('cap.whatif.noSample') };
  const body = JSON.stringify({ overrides: encodeOverrides(overrides) });
  const outcome = await call(source.base, WHATIF_ENDPOINT, body, fetcher);
  if (!outcome.ok) return outcome;
  const whatif = parseWhatif(outcome.body);
  if (whatif === null) return { ok: false, reason: t('cap.whatif.shape') };
  // `via` 가 `sample` 로 올 수 없다 — 위에서 걸렀다.
  return { ok: true, whatif, via: outcome.via === 'direct' ? 'direct' : 'relay' };
}

/** 연결 관리의 「확인」. 한 번 읽어 보고 몇 건이 왔는지 말한다. */
export async function probeCapability(
  source: CapabilitySource, fetcher?: FetchLike,
): Promise<{ alive: boolean; reason: string | null }> {
  const outcome = await fetchSnapshot(source, fetcher);
  if (!outcome.ok) return { alive: false, reason: outcome.reason };
  return {
    alive: true,
    reason: t('cap.probeOk', { functions: outcome.snapshot.functions.length, nodes: outcome.snapshot.nodes.length })
      + (outcome.via === 'direct' ? t('cap.viaDirect') : ''),
  };
}
