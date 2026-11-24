/**
 * scripts/scan-detect-mock.mjs (261123 신설 — 스캔 탐지를 data_stream 으로 · S0)
 *
 * **data_stream 스캔 창구의 가짜.** `documents/협의/스캔탐지창구_요청_VZ_261123.md` §3 의 창구를 그대로 낸다.
 * 진짜 창구는 data_stream 소스 서버(`server_stream_multi_source.py`, `robot1` `:10003` 등)에 붙는다 —
 * 그래서 이 가짜도 **포트 하나가 소스 하나**인 모양으로 뜬다. 가시화는 장치의 추론 스트림 포트(연결 관리
 * 「추론 스트림」 + 하드웨어 카드의 포트 묶음)로 부르므로, 시험할 때는 그 포트 줄에 이 가짜의 주소를 적는다.
 *
 *   npm run scan:mock                                  → http://0.0.0.0:10093 · 정상 판(90° 에 대상)
 *   npm run scan:mock -- --port 10093 --mode best-null  → 찾지 못함
 *
 * 고를 수 있는 판(`--mode`, 검사 스크립트는 `scanMockHandler({ mode })`):
 *   ok               정상 — `--found-deg`(기본 90) 각도에서 찾는다
 *   no-stream        prepare 가 failed + no_stream
 *   no-vision        prepare 가 failed + no_vision
 *   reject           prepare 가 failed + 반영 거절(profile_rejected)
 *   prepare-timeout  ready 가 영영 안 온다(loading 에 머문다)
 *   failed           finish 뒤 result 가 failed
 *   best-null        done + best null (찾지 못함)
 *   distance-invalid best 의 distance_valid false
 *   no-focal         best 에 bearing_note (초점 거리 모름 — 방위가 각도 정면, data_stream 회신 §4.2)
 *   frame-gaps       `--gap-degs`(기본 135,180) 각도의 mark 가 frame_captured false
 *   profile-changed  result 의 profile_version 이 prepare 때와 다르다
 *   result-timeout   finish 뒤 running 에 머문다
 *   extinguisher     261124 요청서 예시 — 13:35 소화기 판을 지금 규칙으로 다시 판정한 것(180° · 바닥선 1.686 m · valid ·
 *                    135/180/225 에서 같이 보임)
 *   door-measured    261124 요청서 예시 — 13:30 문 판(45° · UniDepth 5.819 m · valid false · 한 각도에서만)
 *   isolated         정상 판인데 best 가 한 각도에서만 보였다(`isolated: true`, reason 끝 「- seen at one angle only」)
 *
 * @ 판(`target: object`)의 이름 (261124 · 요청 C): `query_ko` 가 아는 낱말(`KNOWN_KO`)이면 그것을 먼저 쓴다(`query_source: query_ko`).
 * 모르면 `query` 를 쓰는데, 비었거나 소문자 영어 · 공백 · 하이픈 · 40자 · 「or」 없음에 어긋나면 400 `bad_query`.
 *
 * 그 밖의 손잡이: `--load-ms`(prepare → ready, 기본 1500) · `--mark-ms`(mark 응답 지연, 기본 600) ·
 * `--result-ms`(finish → done, 기본 1500) · `--bearing`(best 방위, 기본 96.4) · `--distance`(기본 2.35).
 *
 * 다른 `scan_id` 가 진행 중일 때 prepare 가 오면 409 + 진행 중인 `scan_id`(요청 문서 §7).
 * 그림(`/scan/frame`)은 JPEG 대신 **각도를 적은 SVG** 를 낸다 — 가짜라는 것이 그림에 보이게.
 */

import { createServer } from 'node:http';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const SCAN_MOCK_SERVICE = 'scan-detect-mock';

const TARGETS = { door: ['demo_door'], box: ['demo_box'] };

/** data_stream 이 아는 한국어 낱말 일부 (실제는 약 30개). */
const KNOWN_KO = { 사람: 'person', 문: 'door', 의자: 'chair', 책상: 'desk', 소화기: 'fire extinguisher' };
const SENDABLE = /^[a-z]+(?:[ -][a-z]+)*$/;

/**
 * 판마다 미리 정한 결과 (261124 요청서의 두 예시 · isolated). `found` 는 찾은 각도들, `best` 는 best 에 덮을 칸.
 * best 는 `bestDeg` 각도의 프레임에서 만든다.
 */
const PRESETS = {
  extinguisher: {
    found: [135, 180, 225], bestDeg: 180,
    frame: { distance_m: 1.686, distance_valid: true, distance_source: 'ground_line', score: 99.1, box_xyxy: [169.9, 212.0, 181.6, 239.8] },
    best: { bearing_deg: 157.2, distance_m: 1.686, distance_valid: true, distance_source: 'ground_line', distance_note: null, isolated: false, seen_at: [135, 180, 225] },
  },
  'door-measured': {
    found: [45], bestDeg: 45,
    frame: { distance_m: 5.819, distance_valid: false, distance_source: 'measured' },
    best: {
      bearing_deg: 11.2, distance_m: 5.819, distance_valid: false, distance_source: 'measured',
      distance_note: 'monocular depth on the Go1 fisheye camera is not calibrated - ground line: outside 50-300 cm',
      isolated: true, seen_at: [45],
    },
  },
};
const TERMINAL = new Set(['done', 'failed', 'cancelled']);

function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Private-Network', 'true');
  res.setHeader('Access-Control-Max-Age', '600');
}

function sendJson(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.end(JSON.stringify(body));
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8');
  if (text.trim() === '') return {};
  try { return JSON.parse(text); } catch { return null; }
}

const wait = (ms) => new Promise((done) => setTimeout(done, ms));
const angleOf = (value) => ((Math.round(Number(value)) % 360) + 360) % 360;

function frameSvg(scanId, deg, kind, found) {
  const tint = kind === 'overlay' && found ? '#2e7d32' : kind === 'crop' ? '#1565c0' : '#455a64';
  const box = kind !== 'original' && found
    ? '<rect x="150" y="50" width="100" height="180" fill="none" stroke="#66bb6a" stroke-width="6"/>' : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">`
    + `<rect width="400" height="300" fill="${tint}"/>${box}`
    + `<text x="20" y="40" font-family="sans-serif" font-size="28" fill="#fff">${deg}° · ${kind}</text>`
    + `<text x="20" y="285" font-family="sans-serif" font-size="14" fill="#ddd">mock ${String(scanId).slice(-24)}</text></svg>`;
}

/**
 * 요청 처리기. 검사 스크립트가 임의 포트로 띄울 수 있게 서버와 갈라 둔다.
 * `options.log` 에 받은 요청이 차례대로 쌓인다 — 검사가 「mark 가 turn 완료 뒤에만 나갔나」를 본다.
 */
export function scanMockHandler(options = {}) {
  const opt = {
    mode: 'ok', foundDeg: 90, gapDegs: [135, 180], loadMs: 1500, markMs: 600, resultMs: 1500,
    bearing: 96.4, distance: 2.35, stream: 'robot1', ...options,
  };
  const log = options.log ?? [];
  /** scan_id → 판 */
  const scans = new Map();
  let profileVersion = 11;

  const busy = () => [...scans.values()].find((scan) => !TERMINAL.has(scan.state)) ?? null;

  function stateOf(scan) {
    const now = Date.now();
    if (scan.state === 'loading' && opt.mode !== 'prepare-timeout' && now >= scan.readyAt) scan.state = 'ready';
    if (scan.state === 'running' && opt.mode !== 'result-timeout' && now >= scan.doneAt) {
      scan.state = opt.mode === 'failed' ? 'failed' : 'done';
      if (scan.state === 'failed') scan.error = 'model_error';
    }
    return scan.state;
  }

  function foundDegsOf() {
    if (opt.mode === 'best-null') return [];
    return PRESETS[opt.mode]?.found ?? [angleOf(opt.foundDeg)];
  }

  function resultOf(scan) {
    const preset = PRESETS[opt.mode] ?? null;
    const foundDegs = foundDegsOf();
    const found = (deg) => foundDegs.includes(deg);
    // 기본 판(ok)은 한 각도에서 찾지만 isolated 가 아닌 것으로 낸다 — 옛 창구와 같은 동작이다. 미리 정한 판은 그 값대로.
    const isolated = opt.mode === 'isolated' || preset?.best.isolated === true;
    const frames = [...scan.marks.entries()]
      .filter(([, mark]) => mark.frame_captured)
      .sort(([a], [b]) => a - b)
      .map(([deg, mark]) => (found(deg)
        ? {
          rotation_deg: deg, frame_n: mark.frame_n, found: true, score: 71.0, box_xyxy: [412, 96, 598, 470],
          bearing_deg: opt.bearing, distance_m: opt.distance, distance_valid: opt.mode !== 'distance-invalid',
          distance_source: scan.target === 'box' ? 'box_height' : 'unidepth',
          ...(preset?.frame ?? {}),
          // 261124 — 방위 ±20° 안에서 같이 보인 각도. 가짜는 「찾은 각도 전부」를 같이 보인 것으로 친다.
          seen_at: isolated ? [deg] : foundDegs, isolated,
        }
        : {
          rotation_deg: deg, frame_n: mark.frame_n, found: false, score: scan.target === 'box' ? 52.0 : 8.0, box_xyxy: null,
          reason: scan.target === 'box' ? 'score 52 < 65 (scan floor)' : 'no candidate',
        }));
    const hit = (preset === null ? frames.find((frame) => frame.found) : frames.find((frame) => frame.rotation_deg === preset.bestDeg)) ?? null;
    const best = hit === null ? null : {
      rotation_deg: hit.rotation_deg, bearing_deg: hit.bearing_deg, distance_m: hit.distance_m,
      distance_valid: hit.distance_valid, distance_source: hit.distance_source,
      distance_note: hit.distance_valid ? null : 'box touches the top/bottom edge',
      // 실제 창구는 Go1 에 늘 'reference - no fisheye correction' 을 붙인다(구현 보고 §3-6). 기본은 그 모양, no-focal 은 초점 거리 모름.
      bearing_note: opt.mode === 'no-focal' ? 'no focal length - heading of the scan step' : 'reference - no fisheye correction',
      provisional: true,
      isolated: hit.isolated, seen_at: hit.seen_at,
      ...(preset?.best ?? {}),
    };
    const reasonOf = () => {
      if (best === null) return `no ${scan.targets.join(', ')} found in ${frames.length} angles`;
      return `found ${scan.targets[0]} at ${best.rotation_deg}° — gates passed${best.isolated ? ' - seen at one angle only' : ''}`;
    };
    return {
      scan_id: scan.scan_id, state: scan.state, target: scan.target, query: scan.query,
      query_used: scan.query_used ?? null, query_source: scan.query_source ?? null, targets: scan.targets,
      frames, best,
      evidence: hit === null
        ? { cues: [], enough: false }
        : { cues: [['OVD pair IoU', 1, '0.61 >= 0.42'], ['CLIP colour', 1, 'light blue pass'], ['aspect', 0.8, 'h/w 2.1 >= 1.5']], enough: true },
      reason: reasonOf(),
      model: 'targeted', profile_version: opt.mode === 'profile-changed' ? scan.profile_version + 1 : scan.profile_version,
      score_basis: 'frame', computed_at: new Date().toISOString(), error: scan.error ?? null,
    };
  }

  return async (req, res) => {
    cors(res);
    if (req.method === 'OPTIONS') { res.statusCode = 204; res.end(); return; }
    const url = new URL(req.url ?? '/', 'http://mock');
    const path = url.pathname.replace(/\/+$/, '') || '/';
    const body = req.method === 'POST' ? await readJson(req) : null;
    log.push({ at: Date.now(), method: req.method, path, query: Object.fromEntries(url.searchParams), body });
    if (req.method === 'POST' && body === null) { sendJson(res, 400, { error: 'bad json' }); return; }

    if (path === '/health' && req.method === 'GET') {
      const current = busy();
      // 261124 — 실물(data_stream a1e43f8) 모양에 맞췄다: 스캔 창구는 `vision.targeted.scan` 에 끼어든다(`vision.scan` 이 아니다).
      // 요약 칸(age_s 등)이 있어야 객체 탐지 상태판이 targeted 를 살아 있는 모델로 센다.
      sendJson(res, 200, {
        source: opt.stream, port: Number(opt.port) || null, service: SCAN_MOCK_SERVICE, frames: 100 + log.length, states: 0,
        status: { video: '받는 중 (가짜 창구)', state: null },
        vision: { targeted: { results: 1 + log.length, n: 99 + log.length, run: 'mock', lag_ms: 120, infer_ms: 90, detections: 1, age_s: 0.4, scan: { busy_scan_id: current?.scan_id ?? null, devices: { 'go1-001': opt.stream } } } },
        vision_error: null,
      });
      return;
    }

    if (path === '/scan/prepare' && req.method === 'POST') {
      const id = String(body.scan_id ?? '');
      if (id === '') { sendJson(res, 400, { error: 'scan_id required' }); return; }
      const known = scans.get(id);
      if (known !== undefined) {
        stateOf(known);
        sendJson(res, 200, { scan_id: id, state: known.state, stream: opt.stream, model: 'targeted', targets: known.targets, profile_version: known.profile_version, error: known.error ?? null });
        return;
      }
      const current = busy();
      if (current !== null) { sendJson(res, 409, { error: 'busy', busy_scan_id: current.scan_id }); return; }
      const target = body.target;
      if (!['door', 'box', 'object'].includes(target)) { sendJson(res, 400, { error: 'unknown target' }); return; }
      // @ 판의 이름 (261124 · 요청 C) — 아는 한국어 낱말이 먼저, 없으면 query 를 검사해서 쓴다. 못 쓰면 400 bad_query.
      let queryUsed = null;
      let querySource = null;
      if (target === 'object') {
        const ko = typeof body.query_ko === 'string' ? body.query_ko.trim() : '';
        const en = typeof body.query === 'string' ? body.query.trim() : '';
        if (KNOWN_KO[ko] !== undefined) { queryUsed = KNOWN_KO[ko]; querySource = 'query_ko'; }
        else if (en !== '' && en.length <= 40 && SENDABLE.test(en) && !` ${en} `.includes(' or ')) { queryUsed = en; querySource = 'query'; }
        else {
          sendJson(res, 400, { error: 'bad_query', detail: en === '' ? `unknown query_ko ${JSON.stringify(ko)} and no query` : `query ${JSON.stringify(en)} is not lowercase English (40 chars, no " or ")` });
          return;
        }
      }
      const failure = { 'no-stream': 'no_stream', 'no-vision': 'no_vision', reject: 'profile_rejected: out of GPU memory' }[opt.mode];
      profileVersion += 1;
      const scan = {
        scan_id: id, device: body.device, target, query: target === 'object' ? body.query ?? null : null, query_ko: body.query_ko ?? null,
        query_used: queryUsed, query_source: querySource,
        targets: target === 'object' ? [queryUsed] : TARGETS[target],
        state: failure === undefined ? 'loading' : 'failed', error: failure ?? null,
        readyAt: Date.now() + opt.loadMs, doneAt: Infinity, marks: new Map(), lastFrame: 18300,
        profile_version: profileVersion,
      };
      scans.set(id, scan);
      stateOf(scan);
      sendJson(res, 200, { scan_id: id, state: scan.state, stream: opt.stream, model: 'targeted', targets: scan.targets, profile_version: scan.profile_version, error: scan.error });
      return;
    }

    const scanId = String(body?.scan_id ?? url.searchParams.get('scan_id') ?? '');
    const scan = scans.get(scanId);
    if (path.startsWith('/scan/') && scan === undefined) { sendJson(res, 404, { error: 'unknown_scan', detail: scanId }); return; }

    if (path === '/scan/status' && req.method === 'GET') {
      stateOf(scan);
      sendJson(res, 200, { scan_id: scanId, state: scan.state, angles_captured: [...scan.marks.entries()].filter(([, m]) => m.frame_captured).map(([deg]) => deg).sort((a, b) => a - b), profile_version: scan.profile_version, error: scan.error ?? null });
      return;
    }

    if (path === '/scan/mark' && req.method === 'POST') {
      const state = stateOf(scan);
      if (state !== 'ready' && state !== 'collecting') { sendJson(res, 409, { error: 'bad_state', detail: `not collecting (${state})` }); return; }
      scan.state = 'collecting';
      const deg = angleOf(body.rotation_deg);
      await wait(opt.markMs);
      const gap = opt.mode === 'frame-gaps' && opt.gapDegs.map(angleOf).includes(deg);
      scan.lastFrame += 9;
      const mark = gap
        ? { frame_captured: false, frame_n: null, captured_at: null }
        : { frame_captured: true, frame_n: scan.lastFrame, captured_at: new Date().toISOString() };
      scan.marks.set(deg, mark);
      sendJson(res, 200, { scan_id: scanId, rotation_deg: deg, ...mark });
      return;
    }

    if (path === '/scan/finish' && req.method === 'POST') {
      const state = stateOf(scan);
      if (state !== 'collecting' && state !== 'ready') { sendJson(res, 409, { error: 'bad_state', detail: `cannot finish (${state})` }); return; }
      scan.state = 'running';
      scan.doneAt = Date.now() + opt.resultMs;
      sendJson(res, 200, { scan_id: scanId, state: 'running' });
      return;
    }

    if (path === '/scan/result' && req.method === 'GET') {
      stateOf(scan);
      if (!TERMINAL.has(scan.state)) { sendJson(res, 200, { scan_id: scanId, state: scan.state, error: null }); return; }
      sendJson(res, 200, resultOf(scan));
      return;
    }

    if (path === '/scan/cancel' && req.method === 'POST') {
      if (!TERMINAL.has(stateOf(scan))) scan.state = 'cancelled';
      sendJson(res, 200, { scan_id: scanId, state: scan.state });
      return;
    }

    if (path === '/scan/frame' && req.method === 'GET') {
      const deg = angleOf(url.searchParams.get('rotation_deg'));
      const kind = url.searchParams.get('kind') ?? 'original';
      const mark = scan.marks.get(deg);
      if (mark === undefined || !mark.frame_captured) { sendJson(res, 404, { error: 'no frame at that angle' }); return; }
      const found = foundDegsOf().includes(deg);
      if (kind === 'crop' && !found) { sendJson(res, 404, { error: 'no crop (not found)' }); return; }
      res.statusCode = 200;
      res.setHeader('Content-Type', 'image/svg+xml');
      res.setHeader('Cache-Control', 'no-store');
      res.end(frameSvg(scanId, deg, kind, found));
      return;
    }

    sendJson(res, 404, { error: 'no such route' });
  };
}

export function startScanMock({ port = 10093, host = '0.0.0.0', ...options } = {}) {
  const server = createServer(scanMockHandler(options));
  return new Promise((done, fail) => {
    server.once('error', fail);
    server.listen(port, host, () => done(server));
  });
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const arg = (name, fallback) => {
    const at = process.argv.indexOf(`--${name}`);
    return at >= 0 && process.argv[at + 1] !== undefined ? process.argv[at + 1] : fallback;
  };
  const port = Number(arg('port', '10093'));
  const options = {
    mode: arg('mode', 'ok'),
    foundDeg: Number(arg('found-deg', '90')),
    gapDegs: arg('gap-degs', '135,180').split(',').map(Number),
    loadMs: Number(arg('load-ms', '1500')),
    markMs: Number(arg('mark-ms', '600')),
    resultMs: Number(arg('result-ms', '1500')),
    bearing: Number(arg('bearing', '96.4')),
    distance: Number(arg('distance', '2.35')),
    stream: arg('stream', 'robot1'),
    port,
  };
  const server = await startScanMock({ port, host: arg('host', '0.0.0.0'), ...options }).catch((error) => {
    if (error?.code === 'EADDRINUSE') { console.error(`포트 ${port} 를 다른 프로그램이 쓰고 있습니다. --port 로 바꾸세요.`); process.exit(1); }
    throw error;
  });
  const at = server.address();
  console.log(`스캔 탐지 가짜 창구 (${options.mode}) — http://localhost:${at.port}`);
  console.log('연결 관리 「추론 스트림」의 포트 줄에 이 주소를 적고, 하드웨어 카드에서 로봇을 이 포트에 묶으면 붙습니다. 끄려면 Ctrl+C');
}
