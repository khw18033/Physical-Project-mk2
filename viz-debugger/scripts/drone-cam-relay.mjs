/**
 * scripts/drone-cam-relay.mjs (260928 신설 — 드론 노드 카메라)
 *
 * **pi3 영상 말단(`drone_rpi`, 8890)의 프레임 한 장을 JPEG 로 옮겨 준다.** 개발 서버(vite)에 붙는 중계다.
 *
 * 말단은 엣지가 당겨 가는(pull) 구조라 `GET /api/frame?cam=N` 한 번에 **메타 JSON + JPEG** 를
 * `multipart/form-data` 로 준다. 브라우저에는 두 가지가 막힌다:
 *
 *   - `<img>` 는 그 형식을 못 그린다(`multipart/x-mixed-replace` 만 받는다)
 *   - 응답에 CORS 헤더가 없어 `fetch` 로 읽지도 못한다
 *
 * 그래서 자율주행 AI 중계(`autodrive-ai-relay.mjs`)와 같은 자리에서 JPEG 만 꺼내 돌려준다. 꺼내는 함수도 그쪽 것을 쓴다.
 *
 * 경로는 `/drone-cam/frame?base=http://<host>:<port>&cam=<번호>` 하나다. `base` 는 경로·쿼리 없는 주소만 받는다 —
 * 아무 주소나 대신 요청해 주는 창구가 되지 않게.
 *
 * ⚠ 말단은 「엣지가 5초 넘게 안 오면 단절」로 보고 디스크에 쌓기 시작한다. 이 중계로 보는 동안은 당겨 가는 쪽이
 * 있으므로 그 스풀이 멈춘다 — 보는 동안의 일이고, 창을 닫으면 원래대로 돌아간다.
 */

import { firstJpeg } from './autodrive-ai-relay.mjs';

export const DRONE_CAM_RELAY_URL = '/drone-cam';

const FRAME_TIMEOUT_MS = 5000;
const MAX_FRAME_READ = 8 * 1024 * 1024;

export function droneCamTarget(url) {
  const [path, query = ''] = String(url).split('?');
  if (path !== `${DRONE_CAM_RELAY_URL}/frame`) return path.startsWith(`${DRONE_CAM_RELAY_URL}/`) ? { error: '열린 경로는 frame 하나뿐입니다' } : null;
  const params = new URLSearchParams(query);
  const cam = params.get('cam') ?? '0';
  if (!/^\d{1,2}$/.test(cam)) return { error: '카메라 번호 형식이 아닙니다' };
  let base;
  try { base = new URL(params.get('base') ?? ''); } catch { return { error: 'base 가 주소가 아닙니다' }; }
  if (base.protocol !== 'http:') return { error: 'base 는 http 만 받습니다' };
  if (base.username !== '' || base.password !== '' || (base.pathname !== '/' && base.pathname !== '') || base.search !== '' || base.hash !== '') {
    return { error: 'base 는 경로·쿼리 없는 주소(http://host:port)여야 합니다' };
  }
  // `since` 를 안 싣는다 — 늘 최신 한 장이다. 새 것이 없을 때의 204 롱폴링은 화면이 한 장씩 당기는 데 필요 없다.
  return { upstream: `${base.origin}/api/frame?cam=${cam}` };
}

function send(res, status, body, type) {
  res.statusCode = status;
  res.setHeader('Content-Type', type);
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Drone-Cam-Relay', '1');
  res.end(body);
}

function fail(res, status, message) {
  send(res, status, JSON.stringify({ error: message }), 'application/json; charset=utf-8');
}

/** 미들웨어 본체. `fetcher` 는 검사가 갈아 끼운다. */
export async function handleDroneCam(req, res, next, fetcher = globalThis.fetch) {
  const target = droneCamTarget(req.url ?? '');
  if (target === null) return next();
  if ((req.method ?? 'GET') !== 'GET') { fail(res, 405, 'GET 만 받습니다'); return undefined; }
  if ('error' in target) { fail(res, 400, target.error); return undefined; }
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), FRAME_TIMEOUT_MS);
  try {
    const response = await fetcher(target.upstream, { signal: abort.signal });
    if (response.status === 404) { fail(res, 404, '그 번호의 카메라가 말단에 없습니다'); return undefined; }
    if (!response.ok) { fail(res, 502, `드론 영상 말단이 ${response.status} 로 답했습니다`); return undefined; }
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length > MAX_FRAME_READ) { fail(res, 502, '프레임이 너무 큽니다'); return undefined; }
    const boundary = /boundary=([^;]+)/i.exec(response.headers.get('content-type') ?? '')?.[1]?.trim().replace(/^"|"$/g, '') ?? null;
    // 메타 칸이 먼저 오고 그림 칸이 뒤에 온다. SOI(FFD8)부터 다음 경계 앞까지가 그림이다.
    const jpeg = firstJpeg(bytes, boundary) ?? firstJpeg(bytes, null);
    if (jpeg === null) { fail(res, 502, '응답에서 JPEG 를 못 찾았습니다'); return undefined; }
    send(res, 200, Buffer.from(jpeg), 'image/jpeg');
  } catch (error) {
    fail(res, 502, `드론 영상 말단에 닿지 못했습니다 — ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    clearTimeout(timer);
  }
  return undefined;
}

export function droneCamRelay() {
  // 자율주행 중계와 같은 이유로 아무것도 돌려주지 않는다(`configureServer` 반환값 함정).
  const use = (server) => { server.middlewares.use((req, res, next) => { void handleDroneCam(req, res, next); }); };
  return { name: 'drone-cam-relay', configureServer: use, configurePreviewServer: use };
}
