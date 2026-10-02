/**
 * scripts/autodrive-ai-relay.mjs (260915 신설 — 자율주행 편 · 로봇 영상 · 장애물 탐지)
 *
 * **자율주행 AI 서버를 브라우저가 읽을 수 있게 옮겨 주는 창구.** 개발 서버(`npm run dev`)와 미리보기
 * 서버에 미들웨어로 붙는다(`vite.config.ts`) — `mission-records.mjs` 와 같은 자리다.
 *
 * ## 왜 필요한가 (260915 실측)
 *
 *   GET /control/go1_front      application/json — **`Access-Control-Allow-Origin` 이 없다.**
 *                               브라우저 fetch 가 막힌다. OPTIONS 는 405.
 *   GET /stream/ai/go1_front    multipart/x-mixed-replace; boundary=frame (MJPEG)
 *                               `<img>` 로는 그대로 뜬다(표시는 CORS 가 필요 없다). 다만 **끝나지 않는
 *                               응답**이라 접힌 카드에 걸어 두면 카드 수만큼 연결이 열려 있다.
 *
 * 그래서 둘을 옮긴다. **값은 손대지 않는다** — 받은 바이트를 그대로 넘긴다.
 *
 *   GET /autodrive-ai/control/<camera>?base=<http://host:port>   → <base>/control/<camera> 한 번
 *   GET /autodrive-ai/frame/<camera>?base=<http://host:port>     → <base>/stream/ai/<camera> 의 **첫 JPEG 한 장**
 *
 * 주소는 화면(연결 관리)이 정하므로 `base` 로 받는다. 이 창구가 **아무 데나 두드리는 통로**가 되지
 * 않게 경로는 위 둘만 열고, `base` 는 경로 없는 http(s) 주소만 받는다. 응답에 `X-Autodrive-Relay: 1` 을
 * 붙인다 — 화면이 「중계가 없는 서버(정적 빌드)」와 「중계가 404 를 옮긴 것」을 가른다.
 *
 * **문 찾기 시연(탐지 · pi7)과 무관하다.** 그쪽 창구(`/detect-sample`)와 경로도 코드도 섞지 않는다.
 */

export const AI_RELAY_URL = '/autodrive-ai';

const CAMERA = /^[A-Za-z0-9_-]{1,64}$/;
/** 한 장을 찾을 때까지 읽는 상한. 한 프레임이 수십 KB 다. */
const MAX_FRAME_READ = 8 * 1024 * 1024;
const CONTROL_TIMEOUT_MS = 3000;
const FRAME_TIMEOUT_MS = 5000;

/**
 * 요청 주소 → 옮길 곳. 형식이 안 맞으면 `{ error }`. **순수 함수**라 검사가 그대로 부른다.
 * @param {string} url  `req.url` (쿼리 포함)
 */
export function relayTarget(url) {
  const [path, query = ''] = String(url).split('?');
  if (!path.startsWith(`${AI_RELAY_URL}/`)) return null;
  const parts = path.slice(AI_RELAY_URL.length + 1).split('/');
  if (parts.length !== 2 || (parts[0] !== 'control' && parts[0] !== 'frame')) return { error: '열린 경로는 control · frame 둘뿐입니다' };
  const camera = decodeURIComponent(parts[1]);
  if (!CAMERA.test(camera)) return { error: '카메라 이름 형식이 아닙니다' };
  const raw = new URLSearchParams(query).get('base') ?? '';
  let base;
  try { base = new URL(raw); } catch { return { error: 'base 가 주소가 아닙니다' }; }
  if (base.protocol !== 'http:' && base.protocol !== 'https:') return { error: 'base 는 http(s) 만 받습니다' };
  if (base.username !== '' || base.password !== '' || (base.pathname !== '/' && base.pathname !== '') || base.search !== '' || base.hash !== '') {
    return { error: 'base 는 경로·쿼리 없는 주소(http://host:port)여야 합니다' };
  }
  const origin = base.origin;
  return parts[0] === 'control'
    ? { kind: 'control', camera, upstream: `${origin}/control/${encodeURIComponent(camera)}` }
    : { kind: 'frame', camera, upstream: `${origin}/stream/ai/${encodeURIComponent(camera)}` };
}

/**
 * MJPEG 바이트에서 **첫 JPEG 한 장**. 경계(`--frame`)로 자르고, 경계를 모르면 SOI(FFD8)~EOI(FFD9)로 자른다.
 * 아직 한 장이 다 안 왔으면 null.
 * @param {Buffer} bytes
 * @param {string | null} boundary
 */
export function firstJpeg(bytes, boundary) {
  const soi = bytes.indexOf(Buffer.from([0xff, 0xd8]));
  if (soi < 0) return null;
  if (boundary) {
    const next = bytes.indexOf(Buffer.from(`--${boundary}`), soi);
    if (next < 0) return null;
    // 경계 앞의 줄바꿈은 JPEG 가 아니다.
    let end = next;
    while (end > soi && (bytes[end - 1] === 0x0a || bytes[end - 1] === 0x0d)) end -= 1;
    return bytes.subarray(soi, end);
  }
  const eoi = bytes.indexOf(Buffer.from([0xff, 0xd9]), soi + 2);
  return eoi < 0 ? null : bytes.subarray(soi, eoi + 2);
}

function send(res, status, body, type) {
  res.statusCode = status;
  res.setHeader('Content-Type', type);
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Autodrive-Relay', '1');
  res.end(body);
}

function fail(res, status, message) {
  send(res, status, JSON.stringify({ error: message }), 'application/json; charset=utf-8');
}

async function relayControl(res, upstream, fetcher) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), CONTROL_TIMEOUT_MS);
  try {
    const response = await fetcher(upstream, { signal: abort.signal });
    const body = Buffer.from(await response.arrayBuffer());
    send(res, response.status, body, response.headers.get('content-type') ?? 'application/json');
  } catch (error) {
    fail(res, 502, `AI 서버에 닿지 못했습니다 — ${error instanceof Error ? error.message : String(error)}`);
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
      fail(res, 502, `AI 서버가 ${response.status} 로 답했습니다`);
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
    fail(res, 502, `영상을 못 받았습니다 — ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timer);
    // **끝나지 않는 응답이다** — 한 장을 받았으면 반드시 끊는다.
    abort.abort();
  }
}

/** 미들웨어 본체. `fetcher` 는 검사가 갈아 끼운다. */
export function handleAutodriveAi(req, res, next, fetcher = globalThis.fetch) {
  const target = relayTarget(req.url ?? '');
  if (target === null) return next();
  if ((req.method ?? 'GET') !== 'GET') { fail(res, 405, 'GET 만 받습니다'); return undefined; }
  if ('error' in target) { fail(res, 400, target.error); return undefined; }
  return target.kind === 'control'
    ? relayControl(res, target.upstream, fetcher)
    : relayFrame(res, target.upstream, fetcher);
}

export function autodriveAiRelay() {
  // **아무것도 돌려주지 않는다.** `configureServer` 가 함수를 돌려주면 vite 는 그것을 「내부 미들웨어 뒤에
  // 붙일 훅」으로 인자 없이 부른다 — `middlewares.use()` 의 반환값(connect 앱)을 그대로 돌려줬다가
  // 개발 서버가 기동 중에 죽었다(260915 실측). 중괄호로 감싸 undefined 를 돌려준다.
  const use = (server) => { server.middlewares.use((req, res, next) => { void handleAutodriveAi(req, res, next); }); };
  return {
    name: 'autodrive-ai-relay',
    configureServer: use,
    configurePreviewServer: use,
  };
}
