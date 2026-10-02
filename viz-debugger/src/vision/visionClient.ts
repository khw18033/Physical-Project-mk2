/**
 * src/vision/visionClient.ts (261001 신설 — 객체 탐지 추론 스트림)
 *
 * **스트림 서버를 아는 유일한 면.** 경로(`/health` · `/vision` · `/stream`)와 중계 주소가 이 파일 밖에 적히지 않는다.
 *
 * ## 받는 것 (261001 실측 · 서버 코드는 고치지 않는다)
 *
 *   <base>/health           JSON — 소스 이름 · 받은 장 수 · 연결 상태 문장 · 비전 모델별 요약
 *                           {results, n, run, lag_ms, infer_ms, detections, age_s}. **CORS 가 없다** → 중계로 받는다
 *   <base>/vision?model=<m> 오버레이 MJPEG. 서버가 **그 원본 프레임 위에 그린 것**이라 한 장 안에서는 원본과 결과가 맞다
 *   <base>/stream           원본 MJPEG. 결과보다 `lag_ms` 만큼 앞선다 — 결과 옆에 두면 같은 순간이 아니다
 *
 * 검출 하나하나의 JSON 과 원본 프레임 ID(`source_id`)는 서버 안 Redis 에만 있다. 그래서 이 면이 주는 것은
 * **영상과 요약**이고, 화면은 그 사실을 숨기지 않는다.
 *
 * 영상은 `<img>` 로 **그대로** 띄운다(표시는 CORS 가 필요 없다). 접힌 카드의 한 장과 `/health` 는 개발 서버 창구
 * (`scripts/vision-stream-relay.mjs`)를 지난다. 창구가 없는 서버(정적 빌드)에서는 직접 두드리고, 막히면 그 사유를 말한다.
 */

import { t } from '../i18n/dict.ts';
import { connectionAddress, registerConnectionDefault, splitAddressList } from '../shared/connections.ts';
import { VISION_DEFAULT_PORTS, VISION_STREAM_HOST } from './presets.ts';

const meta = import.meta as unknown as { env?: { VITE_VISION_STREAM_HOST?: string; VITE_VISION_STREAM_PORTS?: string } };

/**
 * **IP 한 칸 + 포트 목록** (261001 지시). IP 만 바뀌고 포트는 그대로인 일이 있어서, IP 칸 하나를 고치면 포트 줄이
 * 전부 따라간다. 환경변수가 있으면 그것이 이긴다(포트는 줄바꿈으로 여럿).
 */
registerConnectionDefault('vision', 'host', meta.env?.VITE_VISION_STREAM_HOST ?? VISION_STREAM_HOST);
registerConnectionDefault('vision', 'ports', meta.env?.VITE_VISION_STREAM_PORTS ?? VISION_DEFAULT_PORTS.join('\n'));

/** 개발 서버 창구 — `scripts/vision-stream-relay.mjs` 의 `VISION_RELAY_URL` 과 같아야 한다. */
const RELAY = '/vision-stream';

export const trimBase = (value: string) => value.trim().replace(/\/+$/, '');

/**
 * IP 칸의 값을 `http://호스트` 로 맞춘다. 스킴이 없으면 http 를 붙이고, 경로 · 포트가 붙어 있으면 뗀다 —
 * 포트는 아래 줄들이 붙인다. 주소가 아니면 null.
 */
export function visionHostOrigin(raw: string): string | null {
  const text = raw.trim();
  if (text === '') return null;
  try {
    const url = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `http://${text}`);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    if (url.hostname === '') return null;
    return `${url.protocol}//${url.hostname}`;
  } catch {
    return null;
  }
}

/**
 * 포트 줄 하나 → 그 포트의 주소. 번호(1~65535)면 IP 칸에 붙인다. 줄에 `http://` 로 시작하는 주소를 통째로 적었으면
 * 그 주소를 그대로 쓴다 — 한 포트만 다른 기계에 있을 때의 길이다. 둘 다 아니면 null.
 */
export function visionBaseOf(host: string | null, row: string): string | null {
  const text = row.trim();
  if (/^\d{1,5}$/.test(text)) {
    const port = Number(text);
    if (host === null || port < 1 || port > 65535) return null;
    return `${host}:${port}`;
  }
  if (/^https?:\/\//i.test(text)) return trimBase(text);
  return null;
}

/** 연결 관리에 적힌 스트림 포트 전부 — IP 칸 + 포트 줄로 만든 주소. 못 만드는 줄은 버린다. */
export function visionBases(): readonly string[] {
  const host = visionHostOrigin(connectionAddress('vision', 'host'));
  const out: string[] = [];
  for (const row of splitAddressList(connectionAddress('vision', 'ports'))) {
    const base = visionBaseOf(host, row);
    if (base !== null && !out.includes(base)) out.push(base);
  }
  return out;
}

/** 실시간 오버레이 — 확대에서 `<img>` 로 연다. */
export function overlayStreamUrl(base: string, model: string): string {
  return `${trimBase(base)}/vision?model=${encodeURIComponent(model)}`;
}

/** 실시간 원본 — 확대에서 `<img>` 로 연다. */
export function rawStreamUrl(base: string): string {
  return `${trimBase(base)}/stream`;
}

/** 접힌 카드의 **한 장** — 창구가 스트림의 첫 JPEG 만 잘라 준다. 모델이 null 이면 원본. `nonce` 로 새로 받는다. */
export function stillUrl(base: string, model: string | null, nonce: number): string {
  const modelPart = model === null ? '' : `&model=${encodeURIComponent(model)}`;
  return `${RELAY}/frame?base=${encodeURIComponent(trimBase(base))}${modelPart}&n=${nonce}`;
}

export function healthUrl(base: string): string {
  return `${trimBase(base)}/health`;
}

/** 모델 하나의 요약 — 서버 `/health` 의 `vision.<모델>` 그대로. 없는 칸은 null. */
export type VisionModelSummary = {
  model: string;
  /** 서버가 읽은 결과 누계. */
  results: number | null;
  /** 마지막 결과의 원본 저장 번호(frames/<번호>.jpg). */
  n: number | null;
  run: string | null;
  lagMs: number | null;
  inferMs: number | null;
  /** 마지막 결과의 검출 개수. */
  detections: number | null;
  /** 마지막 결과가 몇 초 전에 왔는가 — **서버 시계**로 잰 값이다. */
  ageS: number | null;
};

export type StreamHealth = {
  source: string | null;
  port: number | null;
  host: string | null;
  frames: number | null;
  states: number | null;
  /** 연결 상태 문장 그대로 (서버가 쓴 한국어). */
  video: string | null;
  state: string | null;
  /** 상태 문장에 나온 상대 주소(파이) — 장비 맞추기의 재료. */
  upstreamHosts: readonly string[];
  models: readonly VisionModelSummary[];
  visionError: string | null;
  raw: unknown;
};

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);

/** 상태 문장에서 상대 호스트를 뽑는다 — `받는 중 mqtt://100.72.109.9:1883` → `100.72.109.9`. */
export function upstreamHostsOf(texts: readonly (string | null)[]): string[] {
  const out = new Set<string>();
  for (const text of texts) {
    if (text === null) continue;
    for (const match of text.matchAll(/\b(?:mqtt|https?|wss?):\/\/\[?([^\s/:\]]+)/g)) out.add(match[1]);
  }
  return [...out];
}

/** 서버 `/health` 한 건. 모양이 아니면 null — **값을 고치지 않는다.** */
export function parseStreamHealth(body: unknown): StreamHealth | null {
  if (body === null || typeof body !== 'object' || Array.isArray(body)) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.source !== 'string') return null;
  const status = (record.status !== null && typeof record.status === 'object') ? record.status as Record<string, unknown> : {};
  const video = str(status.video);
  const state = str(status.state);
  const vision = (record.vision !== null && typeof record.vision === 'object' && !Array.isArray(record.vision))
    ? record.vision as Record<string, unknown>
    : {};
  const models: VisionModelSummary[] = Object.entries(vision)
    .filter(([, value]) => value !== null && typeof value === 'object')
    .map(([model, value]) => {
      const v = value as Record<string, unknown>;
      return {
        model,
        results: num(v.results),
        n: num(v.n),
        run: str(v.run),
        lagMs: num(v.lag_ms),
        inferMs: num(v.infer_ms),
        detections: num(v.detections),
        ageS: num(v.age_s),
      };
    })
    .sort((a, b) => a.model.localeCompare(b.model));
  return {
    source: record.source,
    port: num(record.port),
    host: str(record.host),
    frames: num(record.frames),
    states: num(record.states),
    video,
    state,
    upstreamHosts: upstreamHostsOf([video, state]),
    models,
    visionError: str(record.vision_error),
    raw: body,
  };
}

/**
 * **결과가 지금도 오는 모델인가.** 서버의 10초 보고는 30초 넘게 결과가 없는 모델을 안 찍는다 — 같은 선을 쓴다.
 * 그 사이(5초 넘게)는 「멎은 듯」으로 적는다(`modelStale`).
 */
export const MODEL_GONE_S = 30;
export const MODEL_STALE_S = 5;

export function modelLive(model: VisionModelSummary): boolean {
  return model.ageS !== null && model.ageS < MODEL_GONE_S;
}

export function modelStale(model: VisionModelSummary): boolean {
  return model.ageS !== null && model.ageS >= MODEL_STALE_S;
}

/**
 * **결과가 원본 최신보다 몇 장 뒤인가** — 프레임 번호로 잰다(시계를 안 쓴다). 서버는 원본 한 장마다 번호 `n` 을 하나씩
 * 올리고(`frames/<n>.jpg`), `/health` 의 `frames`(받은 장 수)는 같은 실행 안에서 그 최신 번호와 같다. 결과의 `n` 은
 * 그 결과가 본 원본 번호다. 모르면(번호가 없거나 실행이 바뀌어 거꾸로면) null.
 */
export function frameGap(framesNow: number | null, summary: VisionModelSummary | null): number | null {
  if (framesNow === null || summary === null || summary.n === null || framesNow < summary.n) return null;
  return framesNow - summary.n;
}

export type FetchLike = (url: string, init?: { signal?: AbortSignal }) => Promise<{
  ok: boolean;
  status: number;
  headers: { get(name: string): string | null };
  json(): Promise<unknown>;
}>;

export type HealthFetch = { ok: true; health: StreamHealth; via: 'relay' | 'direct' } | { ok: false; reason: string };

/**
 * 스트림 서버 `/health` 한 건. 창구 먼저 — 창구가 없는 서버면(응답에 `X-Vision-Relay` 가 없다) 직접 두드린다.
 * 그 서버는 CORS 를 안 열어 두었으므로 직접은 대개 막히고, 그 사실을 사유로 돌려준다.
 */
export async function fetchStreamHealth(
  target: string,
  fetcher: FetchLike = globalThis.fetch as unknown as FetchLike,
  timeoutMs = 4000,
): Promise<HealthFetch> {
  const base = trimBase(target);
  if (base === '') return { ok: false, reason: t('vis.noAddress') };
  const once = async (url: string): Promise<{ status: number; relayed: boolean; body: unknown } | { error: string }> => {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), timeoutMs);
    try {
      const response = await fetcher(url, { signal: abort.signal });
      const relayed = response.headers.get('X-Vision-Relay') === '1';
      let body: unknown = null;
      try { body = await response.json(); } catch { body = null; }
      return { status: response.status, relayed, body };
    } catch (error) {
      return { error: error instanceof Error ? (error.name === 'AbortError' ? t('vis.noAnswerIn', { ms: timeoutMs }) : error.message) : String(error) };
    } finally {
      clearTimeout(timer);
    }
  };
  const settle = (status: number, body: unknown, via: 'relay' | 'direct'): HealthFetch => {
    if (status !== 200) {
      const said = (body as { error?: unknown; detail?: unknown } | null);
      const why = typeof said?.error === 'string' ? said.error : typeof said?.detail === 'string' ? said.detail : '';
      return { ok: false, reason: t('vis.serverStatus', { status, why }) };
    }
    const health = parseStreamHealth(body);
    return health === null ? { ok: false, reason: t('vis.healthShape') } : { ok: true, health, via };
  };

  const viaRelay = await once(`${RELAY}/health?base=${encodeURIComponent(base)}`);
  if ('status' in viaRelay && viaRelay.relayed) return settle(viaRelay.status, viaRelay.body, 'relay');
  const direct = await once(healthUrl(base));
  if ('error' in direct) return { ok: false, reason: t('vis.directFailed', { why: direct.error }) };
  return settle(direct.status, direct.body, 'direct');
}
