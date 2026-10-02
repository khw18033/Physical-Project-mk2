/**
 * scripts/vision-stream-relay.mjs (261001 신설 — 객체 탐지 추론 스트림)
 *
 * **스트림 서버(`server_stream_multi_source.py`)를 브라우저가 읽을 수 있게 옮겨 주는 창구.** 개발 서버와 미리보기
 * 서버에 미들웨어로 붙는다(`vite.config.ts`) — 자율주행 AI 중계(`autodrive-ai-relay.mjs`)와 같은 자리다.
 *
 * ## 왜 필요한가 (261001 실측 · sysai-server2)
 *
 *   GET /health            application/json — **`Access-Control-Allow-Origin` 이 없다.** 브라우저 fetch 가 막힌다
 *   GET /vision?model=<m>  비전 오버레이 MJPEG. `<img>` 로는 그대로 뜬다 — **끝나지 않는 응답**이라 접힌 카드에
 *                          걸어 두면 카드 수만큼 연결이 열려 있다
 *   GET /stream            원본 MJPEG. 위와 같다
 *
 * 서버 코드는 고치지 않기로 했다(261001 지시). 그래서 둘을 옮긴다. **값은 손대지 않는다** — 받은 바이트 그대로다.
 *
 *   GET /vision-stream/health?base=<http://host:port>               → <base>/health 한 번
 *   GET /vision-stream/frame?base=<http://host:port>&model=<모델>   → <base>/vision?model=<모델> 의 **첫 JPEG 한 장**
 *   GET /vision-stream/frame?base=<http://host:port>                → <base>/stream 의 첫 JPEG 한 장 (원본)
 *
 * 포트가 곧 소스다(10001 cam360 · 10002 drone · 10003 robot1 · 10004 robot2). 어느 포트인지는 화면(연결 관리)이
 * 정하므로 `base` 로 받는다. 이 창구가 **아무 데나 두드리는 통로**가 되지 않게 경로는 위 둘만 열고, `base` 는 경로 없는
 * http 주소만 받는다. 응답에 `X-Vision-Relay: 1` 을 붙인다 — 화면이 「중계가 없는 서버(정적 빌드)」와 「중계가 옮긴
 * 실패」를 가른다.
 *
 * Redis(6380)는 서버 안(127.0.0.1)에서만 듣는다(261001 실측 — 테일넷 주소로 거절). 그래서 검출 하나하나의 JSON 과
 * 원본 프레임 ID(`source_id`)는 여기서 못 받는다 — 화면이 「요약만」이라고 적는다.
 */

import { firstJpeg } from './autodrive-ai-relay.mjs';

export const VISION_RELAY_URL = '/vision-stream';

const MODEL = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_FRAME_READ = 8 * 1024 * 1024;
const HEALTH_TIMEOUT_MS = 3000;
const FRAME_TIMEOUT_MS = 5000;

/**
 * 요청 주소 → 옮길 곳. 형식이 안 맞으면 `{ error }`, 이 창구의 경로가 아니면 null. **순수 함수**라 검사가 그대로 부른다.
 * @param {string} url  `req.url` (쿼리 포함)
 */
export function visionRelayTarget(url) {
  const [path, query = ''] = String(url).split('?');
  if (!path.startsWith(`${VISION_RELAY_URL}/`)) return null;
  const kind = path.slice(VISION_RELAY_URL.length + 1);
  if (kind !== 'health' && kind !== 'frame') return { error: '열린 경로는 health · frame 둘뿐입니다' };
  const params = new URLSearchParams(query);
  let base;
  try { base = new URL(params.get('base') ?? ''); } catch { return { error: 'base 가 주소가 아닙니다' }; }
  if (base.protocol !== 'http:' && base.protocol !== 'https:') return { error: 'base 는 http(s) 만 받습니다' };
  if (base.username !== '' || base.password !== '' || (base.pathname !== '/' && base.pathname !== '') || base.search !== '' || base.hash !== '') {
    return { error: 'base 는 경로·쿼리 없는 주소(http://host:port)여야 합니다' };
  }
  const origin = base.origin;
  if (kind === 'health') return { kind, upstream: `${origin}/health` };
  const model = params.get('model');
  if (model === null || model === '') return { kind, model: null, upstream: `${origin}/stream` };
  if (!MODEL.test(model)) return { error: '모델 이름 형식이 아닙니다' };
  return { kind, model, upstream: `${origin}/vision?model=${encodeURIComponent(model)}` };
}

function send(res, status, body, type) {
  res.statusCode = status;
  res.setHeader('Content-Type', type);
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Vision-Relay', '1');
  res.end(body);
}

function fail(res, status, message) {
  send(res, status, JSON.stringify({ error: message }), 'application/json; charset=utf-8');
}

async function relayHealth(res, upstream, fetcher) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), HEALTH_TIMEOUT_MS);
  try {
    const response = await fetcher(upstream, { signal: abort.signal });
    const body = Buffer.from(await response.arrayBuffer());
    send(res, response.status, body, response.headers.get('content-type') ?? 'application/json');
  } catch (error) {
    fail(res, 502, `스트림 서버에 닿지 못했습니다 — ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timer);
  }
}

async function relayFrame(res, upstream, fetcher) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), FRAME_TIMEOUT_MS);
  try {
    const response = await fetcher(upstream, { signal: abort.signal });
    if (!response.ok || response.body === null) {
      // 서버는 결과가 없는 모델에 404 와 JSON 사유를 준다 — 그 사유를 그대로 옮긴다.
      let said = '';
      try { said = (await response.text()).slice(0, 300); } catch { said = ''; }
      fail(res, 502, `스트림 서버가 ${response.status} 로 답했습니다${said === '' ? '' : ` — ${said}`}`);
      return;
    }
    const boundary = /boundary=([^;]+)/i.exec(response.headers.get('content-type') ?? '')?.[1]?.trim().replace(/^"|"$/g, '') ?? null;
    const reader = response.body.getReader();
    let bytes = Buffer.alloc(0);
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes = Buffer.concat([bytes, Buffer.from(value)]);
      const jpeg = firstJpeg(bytes, boundary);
      if (jpeg !== null) {
        send(res, 200, Buffer.from(jpeg), 'image/jpeg');
        return;
      }
      if (bytes.length > MAX_FRAME_READ) break;
    }
    fail(res, 502, '스트림에서 JPEG 한 장을 못 찾았습니다');
  } catch (error) {
    // 서버는 모델 이름을 주면 결과가 없어도 200 으로 열어 두고 기다린다(261001 실측) — 그래서 시간 초과가 「결과 없음」이다.
    fail(res, 504, abort.signal.aborted
      ? `${FRAME_TIMEOUT_MS / 1000}초 안에 한 장이 안 왔습니다 — 그 모델(또는 원본)에 아직 결과가 없을 수 있습니다`
      : `영상을 못 받았습니다 — ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timer);
    // **끝나지 않는 응답이다** — 한 장을 받았으면 반드시 끊는다.
    abort.abort();
  }
}

/** 미들웨어 본체. `fetcher` 는 검사가 갈아 끼운다. */
export function handleVisionStream(req, res, next, fetcher = globalThis.fetch) {
  const target = visionRelayTarget(req.url ?? '');
  if (target === null) return next();
  if ((req.method ?? 'GET') !== 'GET') { fail(res, 405, 'GET 만 받습니다'); return undefined; }
  if ('error' in target) { fail(res, 400, target.error); return undefined; }
  return target.kind === 'health'
    ? relayHealth(res, target.upstream, fetcher)
    : relayFrame(res, target.upstream, fetcher);
}

export function visionStreamRelay() {
  // 아무것도 돌려주지 않는다 — 이유는 `autodrive-ai-relay.mjs` 의 같은 자리에 적어 두었다.
  const use = (server) => { server.middlewares.use((req, res, next) => { void handleVisionStream(req, res, next); }); };
  return {
    name: 'vision-stream-relay',
    configureServer: use,
    configurePreviewServer: use,
  };
}
