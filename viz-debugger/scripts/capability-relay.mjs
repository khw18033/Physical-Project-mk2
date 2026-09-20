/**
 * scripts/capability-relay.mjs (260920 신설 — 기능 상태 패널 이식)
 *
 * **기능 상태 서비스를 브라우저가 읽을 수 있게 옮겨 주는 창구.** 개발 서버(`npm run dev`)와
 * 미리보기 서버에 미들웨어로 붙는다(`vite.config.ts`) — `autodrive-ai-relay.mjs` 와 같은 자리다.
 *
 * ## 왜 필요한가
 *
 * `perception-framework/tools/status_ui/serve.py` 는 파이썬 표준 라이브러리 HTTP 서버이고
 * **`Access-Control-Allow-Origin` 을 안 붙인다.** 브라우저 `fetch` 가 막힌다. 실제 배치에서는
 * 그 서버가 k3s 안에 서므로 주소도 우리가 모른다 — 화면(연결 관리)이 정한다.
 *
 *   GET /capability/<endpoint>?base=<http://host:port>  → <base>/api/<endpoint>
 *
 * **값은 손대지 않는다** — 받은 바이트를 그대로 넘긴다. 응답이 언어 중립 ID 중심이라
 * 여기서 뜯을 것도 없다.
 *
 * ## 아무 데나 두드리는 통로가 되지 않게
 *
 * 여는 경로는 **읽기 셋뿐**이다(`config` · `labels` · `functions`). `placement` 는 열지 않는다 —
 * 그 POST 는 `--control k3s` 에서 **실제 클러스터 Deployment 를 바꾼다**(핸드오프 「배치 모드와
 * 한계」). 화면이 안 쓰는 길은 창구도 열지 않는다. `whatif` 도 마찬가지로 지금은 닫는다.
 *
 * `base` 는 경로·쿼리 없는 http(s) 주소만 받는다. 응답에 `X-Capability-Relay: 1` 을 붙인다 —
 * 화면이 「창구가 없는 서버(정적 빌드)」와 「창구가 404 를 옮긴 것」을 가른다.
 *
 * **문 찾기 탐지(`/detect-sample`)·자율주행 AI(`/autodrive-ai`)와 경로도 코드도 섞지 않는다.**
 */

export const CAPABILITY_RELAY_URL = '/capability';

/** 여는 경로 — 읽기 셋. 늘리려면 여기 한 줄이고, 그때 `verify:capability-source` 가 묻는다. */
export const CAPABILITY_ENDPOINTS = ['config', 'labels', 'functions'];

const TIMEOUT_MS = 6000;

/**
 * 요청 주소 → 옮길 곳. 형식이 안 맞으면 `{ error }`. **순수 함수**라 검사가 그대로 부른다.
 * @param {string} url `req.url` (쿼리 포함)
 */
export function relayTarget(url) {
  const [path, query = ''] = String(url).split('?');
  if (!path.startsWith(`${CAPABILITY_RELAY_URL}/`)) return null;
  const parts = path.slice(CAPABILITY_RELAY_URL.length + 1).split('/');
  if (parts.length !== 1 || !CAPABILITY_ENDPOINTS.includes(parts[0])) {
    return { error: `열린 경로는 ${CAPABILITY_ENDPOINTS.join(' · ')} 뿐입니다` };
  }
  const raw = new URLSearchParams(query).get('base') ?? '';
  let base;
  try { base = new URL(raw); } catch { return { error: 'base 가 주소가 아닙니다' }; }
  if (base.protocol !== 'http:' && base.protocol !== 'https:') return { error: 'base 는 http(s) 만 받습니다' };
  if (base.username !== '' || base.password !== '' || (base.pathname !== '/' && base.pathname !== '') || base.search !== '' || base.hash !== '') {
    return { error: 'base 는 경로·쿼리 없는 주소(http://host:port)여야 합니다' };
  }
  return { endpoint: parts[0], upstream: `${base.origin}/api/${parts[0]}` };
}

function send(res, status, body, type) {
  res.statusCode = status;
  res.setHeader('Content-Type', type);
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Capability-Relay', '1');
  res.end(body);
}

function fail(res, status, message) {
  send(res, status, JSON.stringify({ error: message }), 'application/json; charset=utf-8');
}

async function relayRead(res, upstream, fetcher) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);
  try {
    const response = await fetcher(upstream, { signal: abort.signal, headers: { Accept: 'application/json' } });
    const body = Buffer.from(await response.arrayBuffer());
    send(res, response.status, body, response.headers.get('content-type') ?? 'application/json');
  } catch (error) {
    fail(res, 502, `기능 상태 서비스에 닿지 못했습니다 — ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timer);
  }
}

/** 미들웨어 본체. `fetcher` 는 검사가 갈아 끼운다. */
export function handleCapability(req, res, next, fetcher = globalThis.fetch) {
  const target = relayTarget(req.url ?? '');
  if (target === null) return next();
  if ((req.method ?? 'GET') !== 'GET') { fail(res, 405, 'GET 만 받습니다'); return undefined; }
  if ('error' in target) { fail(res, 400, target.error); return undefined; }
  return relayRead(res, target.upstream, fetcher);
}

export function capabilityRelay() {
  // **아무것도 돌려주지 않는다.** `configureServer` 가 함수를 돌려주면 vite 는 그것을 훅으로
  // 알고 인자 없이 부른다 — 자율주행 창구에서 그것 때문에 개발 서버가 죽은 적이 있다(260915).
  const use = (server) => { server.middlewares.use((req, res, next) => { void handleCapability(req, res, next); }); };
  return {
    name: 'capability-relay',
    configureServer: use,
    configurePreviewServer: use,
  };
}
