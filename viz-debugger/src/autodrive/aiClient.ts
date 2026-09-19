/**
 * src/autodrive/aiClient.ts (260915 신설 — 자율주행 편 · 로봇 영상 · 장애물 탐지)
 *
 * **자율주행 AI 서버를 아는 유일한 면.** 주소·카메라 이름·경로가 이 파일 밖에 적히지 않는다.
 *
 * ## 문 찾기 시연(탐지 · pi7)과 무관하다
 *
 * 그쪽은 `src/detect/`(탐지 서버 · 문 판정)와 `src/physical/PhysicalClient.ts`(pi7)다. 이 폴더는
 * 그 둘을 import 하지 않고 그 둘도 이 폴더를 모른다(`verify:autodrive-ai`). 같은 「탐지」라는 말을
 * 써도 서버도 값도 다르다 — 섞으면 시연 편 노드에 장애물 값이 칠해진다.
 *
 * ## 받는 것 (260915 실측)
 *
 *   <base>/stream/ai/go1_front   MJPEG (`multipart/x-mixed-replace; boundary=frame`) — 약 3.5장/초, 가끔 멎는다
 *   <base>/control/go1_front     JSON 한 건 — 0.5초마다 갱신. **CORS 가 없다** → 개발 서버 창구로 받는다
 *
 * 영상은 `<img>` 로 **그대로** 띄운다(표시는 CORS 가 필요 없다). 접힌 카드의 한 장과 장애물 JSON 은
 * 개발 서버 창구(`scripts/autodrive-ai-relay.mjs`)를 지난다. 창구가 없는 서버(정적 빌드)에서는
 * 직접 두드리고, 막히면 그 사유를 그대로 말한다.
 */

import { t } from '../i18n/dict.ts';
import { connectionAddress, registerConnectionDefault } from '../shared/connections.ts';

const meta = import.meta as unknown as { env?: { VITE_AUTODRIVE_AI_BASE?: string } };

/** 사용자가 준 주소 그대로(260915). 연결 관리에서 덮어쓸 수 있다. */
registerConnectionDefault('autodrive-ai', 'base', meta.env?.VITE_AUTODRIVE_AI_BASE ?? 'http://210.110.250.33:7864');

/** 로봇 앞 카메라. 사용자가 준 두 주소가 같은 이름을 쓴다. */
export const AI_CAMERA = 'go1_front';

/** 개발 서버 창구 — `scripts/autodrive-ai-relay.mjs` 의 `AI_RELAY_URL` 과 같아야 한다. */
const RELAY = '/autodrive-ai';

/** 지금 쓰는 서버 주소. 끝의 `/` 는 뗀다. 읽을 때마다 지금 값이다. */
export function aiBase(): string {
  return connectionAddress('autodrive-ai', 'base').trim().replace(/\/+$/, '');
}

/** 실시간 영상 — 사용자가 준 주소 그대로. 확대에서 `<img>` 로 연다. */
export function aiStreamUrl(): string {
  return `${aiBase()}/stream/ai/${AI_CAMERA}`;
}

/** 장애물 JSON — 사용자가 준 주소 그대로. 화면에 적는 용도이고 요청은 `fetchObstacleJson` 이 한다. */
export function aiControlUrl(): string {
  return `${aiBase()}/control/${AI_CAMERA}`;
}

/** 접힌 카드의 **한 장** — 창구가 스트림의 첫 JPEG 만 잘라 준다. `nonce` 로 새로 받는다. */
export function aiFrameUrl(nonce: number): string {
  return `${RELAY}/frame/${AI_CAMERA}?base=${encodeURIComponent(aiBase())}&n=${nonce}`;
}

/**
 * 영상이 한 장이라도 오는가 — 연결 관리의 「확인」. 창구가 자른 한 장을 `Image` 로 받아 본다.
 * 브라우저가 아니면(검사) 확인할 수 없다고 돌려준다 — 성공으로 치지 않는다.
 */
export function probeStill(timeoutMs = 6000): Promise<{ ok: boolean | null; reason: string | null; ms: number | null }> {
  const ImageCtor = (globalThis as { Image?: new () => HTMLImageElement }).Image;
  if (ImageCtor === undefined) return Promise.resolve({ ok: null, reason: t('ac.1'), ms: null });
  if (aiBase() === '') return Promise.resolve({ ok: false, reason: t('ac.2'), ms: null });
  return new Promise((resolve) => {
    const image = new ImageCtor();
    const startedAt = Date.now();
    const done = (result: { ok: boolean | null; reason: string | null; ms: number | null }) => {
      clearTimeout(timer);
      image.onload = null;
      image.onerror = null;
      image.src = '';
      resolve(result);
    };
    const timer = setTimeout(() => done({ ok: false, reason: t('ac.noFrameIn', { ms: timeoutMs }), ms: null }), timeoutMs);
    image.onload = () => done({ ok: true, reason: null, ms: Date.now() - startedAt });
    image.onerror = () => done({ ok: false, reason: t('ac.3'), ms: null });
    image.src = aiFrameUrl(Date.now());
  });
}

export type FetchLike =(url: string, init?: { signal?: AbortSignal }) => Promise<{
  ok: boolean;
  status: number;
  headers: { get(name: string): string | null };
  json(): Promise<unknown>;
}>;

export type ObstacleFetch = { ok: true; body: unknown; via: 'relay' | 'direct' } | { ok: false; reason: string };

/**
 * 장애물 JSON 한 건. **값을 고치지 않는다** — 받은 객체 그대로 돌려준다.
 *
 * 창구 먼저. 창구가 없는 서버면(응답에 `X-Autodrive-Relay` 가 없다) 직접 두드린다 — 그 서버가 CORS 를
 * 안 열어 두었으면 브라우저가 막고, 그 사실을 사유로 돌려준다.
 */
export async function fetchObstacleJson(fetcher: FetchLike = globalThis.fetch as unknown as FetchLike, timeoutMs = 3000): Promise<ObstacleFetch> {
  const base = aiBase();
  if (base === '') return { ok: false, reason: t('ac.4') };
  const once = async (url: string): Promise<{ status: number; relayed: boolean; body: unknown } | { error: string }> => {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), timeoutMs);
    try {
      const response = await fetcher(url, { signal: abort.signal });
      const relayed = response.headers.get('X-Autodrive-Relay') === '1';
      let body: unknown = null;
      try { body = await response.json(); } catch { body = null; }
      return { status: response.status, relayed, body };
    } catch (error) {
      return { error: error instanceof Error ? (error.name === 'AbortError' ? t('ac.noAnswerIn', { ms: timeoutMs }) : error.message) : String(error) };
    } finally {
      clearTimeout(timer);
    }
  };

  const viaRelay = await once(`${RELAY}/control/${AI_CAMERA}?base=${encodeURIComponent(base)}`);
  if ('status' in viaRelay && viaRelay.relayed) {
    if (viaRelay.status === 200 && viaRelay.body !== null) return { ok: true, body: viaRelay.body, via: 'relay' };
    const said = (viaRelay.body as { error?: unknown } | null)?.error;
    return { ok: false, reason: t('ac.relayFailed', { status: viaRelay.status, said: typeof said === 'string' ? said : t('ac.relaySaid') }) };
  }
  // 창구가 없다(정적 빌드 · 다른 서버). 직접.
  const direct = await once(aiControlUrl());
  if ('error' in direct) {
    return { ok: false, reason: t('ac.directFailed', { why: direct.error }) };
  }
  if (direct.status !== 200 || direct.body === null) return { ok: false, reason: t('ac.serverStatus', { status: direct.status }) };
  return { ok: true, body: direct.body, via: 'direct' };
}
