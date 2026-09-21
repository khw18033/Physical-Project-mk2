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
 *   GET  /capability/<endpoint>?base=<http://host:port>       → <base>/api/<endpoint>
 *   POST /capability/functions/whatif?base=<http://host:port> → <base>/api/functions/whatif
 *
 * **값은 손대지 않는다** — 받은 바이트를 그대로 넘긴다. 응답이 언어 중립 ID 중심이라
 * 여기서 뜯을 것도 없다.
 *
 * ## 아무 데나 두드리는 통로가 되지 않게 — 메서드까지 같이 본다
 *
 * 여는 경로는 **읽기 셋과 계산 하나**다. 목록이 둘로 갈린 것이 규칙의 전부다:
 *
 *   GET   config · labels · functions      읽기
 *   POST  functions/whatif                 계산
 *
 * `placement` 는 **열지 않는다** — 그 POST 는 `--control k3s` 에서 실제 클러스터 Deployment 를
 * 바꾼다(핸드오프 「배치 모드와 한계」). `reset` · `events` 도 화면이 안 쓰므로 닫는다.
 *
 * ## `functions/whatif` 는 왜 열었나 (260921)
 *
 * 이식 때는 「POST 니까 placement 와 한 묶음」으로 보고 닫아 뒀다. **그 판단이 틀렸다.**
 * `serve.py` 의 `whatif_functions()` 는 `self.functions()` 를 두 번 부르는 것이 전부이고
 * (`before` 와 `after`), 그 밑의 `_resolve_raw()` 는 매번 새 `ZoneApplication` 을 세워 계산만
 * 한다 — control 도 reconciler 도 건드리지 않는다. `--control k3s` 에서도 클러스터는 안 바뀐다.
 *
 * 그래서 **가르는 기준은 메서드가 아니라 「무엇을 바꾸는가」**다. 이 목록을 늘릴 사람은
 * 그 경로가 정말 계산만 하는지를 `serve.py` 에서 먼저 확인해야 하고, 그때
 * `verify:capability-source` §6 이 묻는다.
 *
 * `base` 는 경로·쿼리 없는 http(s) 주소만 받는다. 본문은 `MAX_BODY_BYTES` 까지만 옮긴다 —
 * 창구가 임의 크기의 바이트를 나르는 통로가 되면 안 된다. 응답에 `X-Capability-Relay: 1` 을
 * 붙인다 — 화면이 「창구가 없는 서버(정적 빌드)」와 「창구가 404 를 옮긴 것」을 가른다.
 *
 * **문 찾기 탐지(`/detect-sample`)·자율주행 AI(`/autodrive-ai`)와 경로도 코드도 섞지 않는다.**
 */

export const CAPABILITY_RELAY_URL = '/capability';

/** 여는 경로 — 읽기 셋. 늘리려면 여기 한 줄이고, 그때 `verify:capability-source` 가 묻는다. */
export const CAPABILITY_ENDPOINTS = ['config', 'labels', 'functions'];

/**
 * **계산만 하는 POST.** 여기 올릴 경로는 `serve.py` 에서 아무것도 바꾸지 않는다는 것을
 * 확인한 것뿐이다 — `placement` 는 영원히 여기 오면 안 된다.
 */
export const CAPABILITY_POST_ENDPOINTS = ['functions/whatif'];

const TIMEOUT_MS = 6000;

/** 옮기는 본문의 상한. What-if 오버라이드는 노드 수만큼이라 이보다 훨씬 작다. */
export const MAX_BODY_BYTES = 64 * 1024;

/**
 * 요청 주소 → 옮길 곳. 형식이 안 맞으면 `{ error }`. **순수 함수**라 검사가 그대로 부른다.
 *
 * 메서드를 같이 받는 이유는 **같은 경로라도 메서드로 갈리기** 때문이다 — `functions` 는
 * GET 만, `functions/whatif` 는 POST 만 연다. 한쪽 목록만 보면 `GET /functions/whatif` 나
 * `POST /functions` 가 새어 나간다.
 *
 * @param {string} url `req.url` (쿼리 포함)
 * @param {string} [method] `req.method`. 없으면 GET 으로 본다.
 */
export function relayTarget(url, method = 'GET') {
  const [path, query = ''] = String(url).split('?');
  if (!path.startsWith(`${CAPABILITY_RELAY_URL}/`)) return null;
  // **마디로 쪼개지 않고 통째로 대조한다.** `functions/whatif` 는 두 마디이고, `..` 같은
  // 것은 목록에 없으므로 그대로 떨어진다.
  const rest = path.slice(CAPABILITY_RELAY_URL.length + 1);
  const verb = String(method).toUpperCase();
  const allowed = verb === 'POST' ? CAPABILITY_POST_ENDPOINTS : CAPABILITY_ENDPOINTS;
  if (!allowed.includes(rest)) {
    return { error: `${verb} 으로 열린 경로는 ${allowed.join(' · ')} 뿐입니다` };
  }
  const raw = new URLSearchParams(query).get('base') ?? '';
  let base;
  try { base = new URL(raw); } catch { return { error: 'base 가 주소가 아닙니다' }; }
  if (base.protocol !== 'http:' && base.protocol !== 'https:') return { error: 'base 는 http(s) 만 받습니다' };
  if (base.username !== '' || base.password !== '' || (base.pathname !== '/' && base.pathname !== '') || base.search !== '' || base.hash !== '') {
    return { error: 'base 는 경로·쿼리 없는 주소(http://host:port)여야 합니다' };
  }
  return { endpoint: rest, method: verb, upstream: `${base.origin}/api/${rest}` };
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

/**
 * 한 번 옮긴다. `body` 가 있으면 POST 다. **값은 안 뜯는다** — 받은 바이트 그대로 넘긴다.
 */
async function relayOnce(res, upstream, fetcher, body = null) {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);
  try {
    const init = body === null
      ? { signal: abort.signal, headers: { Accept: 'application/json' } }
      : { signal: abort.signal, method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body };
    const response = await fetcher(upstream, init);
    const out = Buffer.from(await response.arrayBuffer());
    send(res, response.status, out, response.headers.get('content-type') ?? 'application/json');
  } catch (error) {
    fail(res, 502, `기능 상태 서비스에 닿지 못했습니다 — ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 본문을 모은다. **상한을 넘으면 거기서 끊는다** — 창구가 임의 크기를 나르면 안 된다.
 * @param {import('node:http').IncomingMessage} req
 */
export function readRequestBody(req, limit = MAX_BODY_BYTES) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error(`본문이 ${limit} 바이트를 넘습니다`));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

/** 미들웨어 본체. `fetcher` 는 검사가 갈아 끼운다. */
export async function handleCapability(req, res, next, fetcher = globalThis.fetch) {
  const verb = (req.method ?? 'GET').toUpperCase();
  const target = relayTarget(req.url ?? '', verb);
  if (target === null) return next();
  if (verb !== 'GET' && verb !== 'POST') { fail(res, 405, 'GET · POST 만 받습니다'); return undefined; }
  if ('error' in target) { fail(res, 400, target.error); return undefined; }
  if (verb === 'GET') return relayOnce(res, target.upstream, fetcher);
  let body;
  try {
    body = await readRequestBody(req);
  } catch (error) {
    fail(res, 413, error instanceof Error ? error.message : String(error));
    return undefined;
  }
  return relayOnce(res, target.upstream, fetcher, body);
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
