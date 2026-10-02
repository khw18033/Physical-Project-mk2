/**
 * scripts/server-metrics-relay.mjs (261002 신설 — 서버 칸 · 서버 자원 상태)
 *
 * **서버 기계의 지표(`/metrics`, Prometheus 글자 형식)를 브라우저가 읽을 수 있게 옮겨 주는 창구.** 개발 서버와 미리보기
 * 서버에 미들웨어로 붙는다(`vite.config.ts`) — 추론 스트림 중계(`vision-stream-relay.mjs`)와 같은 자리다.
 *
 * node_exporter 같은 지표 서버는 `Access-Control-Allow-Origin` 을 안 붙인다 — 브라우저 fetch 가 막힌다.
 *
 *   GET /server-metrics?url=<http://host:port/metrics>   → 그 주소를 한 번 그대로
 *
 * **아무 데나 두드리는 통로가 되지 않게** 경로가 `/metrics` 로 끝나는 http(s) 주소만 받는다. 값은 손대지 않는다.
 * 응답에 `X-Metrics-Relay: 1` 을 붙인다 — 화면이 「중계가 없는 서버(정적 빌드)」와 「중계가 옮긴 실패」를 가른다.
 */

export const METRICS_RELAY_URL = '/server-metrics';

const TIMEOUT_MS = 4000;
/** 지표 한 번이 이보다 크면 자른다 — node_exporter 기본이 수백 KB 다. */
const MAX_BYTES = 4 * 1024 * 1024;

/**
 * 요청 주소 → 옮길 곳. 이 창구의 경로가 아니면 null, 형식이 안 맞으면 `{ error }`. **순수 함수**라 검사가 그대로 부른다.
 * @param {string} url  `req.url` (쿼리 포함)
 */
export function metricsRelayTarget(url) {
  const [path, query = ''] = String(url).split('?');
  if (path !== METRICS_RELAY_URL) return null;
  let target;
  try { target = new URL(new URLSearchParams(query).get('url') ?? ''); } catch { return { error: 'url 이 주소가 아닙니다' }; }
  if (target.protocol !== 'http:' && target.protocol !== 'https:') return { error: 'url 은 http(s) 만 받습니다' };
  if (target.username !== '' || target.password !== '' || target.hash !== '') return { error: 'url 에 계정 · 조각을 넣을 수 없습니다' };
  if (!target.pathname.endsWith('/metrics')) return { error: '경로가 /metrics 로 끝나는 지표 주소만 받습니다' };
  return { upstream: target.href };
}

function send(res, status, body, type) {
  res.statusCode = status;
  res.setHeader('Content-Type', type);
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Metrics-Relay', '1');
  res.end(body);
}

/** 미들웨어 본체. `fetcher` 는 검사가 갈아 끼운다. */
export async function handleServerMetrics(req, res, next, fetcher = globalThis.fetch) {
  const target = metricsRelayTarget(req.url ?? '');
  if (target === null) return next();
  const fail = (status, message) => send(res, status, JSON.stringify({ error: message }), 'application/json; charset=utf-8');
  if ((req.method ?? 'GET') !== 'GET') return fail(405, 'GET 만 받습니다');
  if ('error' in target) return fail(400, target.error);
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), TIMEOUT_MS);
  try {
    const response = await fetcher(target.upstream, { signal: abort.signal });
    const body = Buffer.from(await response.arrayBuffer()).subarray(0, MAX_BYTES);
    send(res, response.status, body, response.headers.get('content-type') ?? 'text/plain; charset=utf-8');
  } catch (error) {
    fail(502, abort.signal.aborted
      ? `${TIMEOUT_MS / 1000}초 안에 지표 서버가 답하지 않았습니다`
      : `지표 서버에 닿지 못했습니다 — ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timer);
  }
  return undefined;
}

export function serverMetricsRelay() {
  // 아무것도 돌려주지 않는다 — 이유는 `autodrive-ai-relay.mjs` 의 같은 자리에 적어 두었다.
  const use = (server) => { server.middlewares.use((req, res, next) => { void handleServerMetrics(req, res, next); }); };
  return {
    name: 'server-metrics-relay',
    configureServer: use,
    configurePreviewServer: use,
  };
}
