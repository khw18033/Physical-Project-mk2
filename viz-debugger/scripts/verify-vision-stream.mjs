// verify:vision-stream (261001 신설 — 객체 탐지 추론 스트림)
//
// **스트림 서버(포트 = 소스)를 서버 수정 없이 읽는 길이 맞게 서 있는가.**
//
// 보는 것 다섯.
//  1. 중계 창구가 열어 둔 경로는 health · frame 둘뿐이고, base 는 경로 없는 주소만 받는다
//  2. 중계가 값을 고치지 않는다 — /health 는 그대로, frame 은 스트림의 첫 JPEG 한 장, 서버 사유는 그대로 옮긴다
//  3. 서버 `/health`(261001 실측 모양)를 뜯는다 — 상태 문장에서 파이 주소를 뽑고, 모델 요약을 그대로 옮긴다
//  4. 장비와 포트 묶기 — 사람이 고른 것이 이기고, 주소가 같은 포트가 하나면 묶고, 둘 이상이면 **안 고른다**
//  5. 처리 속도는 서버 누계의 차이로 잰다 · `src/vision/` 은 장애물 탐지 · 문 찾기 경계를 import 하지 않는다
//
// 대조군 — 모양이 다른 JSON 은 null 이어야 하고, 주소가 같은 포트가 둘이면 묶음이 비어야 한다.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const failures = [];
const controls = [];

const relay = await load('scripts', 'vision-stream-relay.mjs');
const client = await load('src', 'vision', 'visionClient.ts');
const binding = await load('src', 'vision', 'binding.ts');
const store = await load('src', 'vision', 'store.ts');

/** 261001 실측 — sysai-server2 :10003 `/health` (파이가 꺼져 있던 때). */
const HEALTH_ROBOT1_IDLE = {
  source: 'robot1', port: 10003, host: 'sysai-server2',
  folder: '/home/dg/capstone-db/data_stream/stream_data/robot1/20261001_103459',
  frames: 0, states: 0, save_fail: 0, redis_fail: 0, redis_error: null,
  status: { video: '끊김 (TimeoutError: timed out) — 다시 붙는 중', state: '붙는 중 mqtt://100.72.109.9:1883' },
  vision: {}, vision_error: null,
};
/** 같은 모양에 비전 결과가 붙은 것 — 서버 docstring 의 `"vision": {모델: {results, n, run, lag_ms, infer_ms, detections, age_s}}`. */
const HEALTH_ROBOT1_LIVE = {
  ...HEALTH_ROBOT1_IDLE,
  frames: 1520,
  status: { video: '받는 중 http://100.72.109.9:8090/stream/1', state: '받는 중 mqtt://100.72.109.9:1883' },
  vision: {
    yoloe: { results: 812, n: 1519, run: '20261001_103459', lag_ms: 71, infer_ms: 58.2, detections: 4, age_s: 0.2 },
    unidepth: { results: 120, n: 1498, run: '20261001_103459', lag_ms: 640, infer_ms: 590, detections: 4, age_s: 41.0 },
  },
};

// ── 1. 경로 ─────────────────────────────────────────────────────────────────
{
  const base = encodeURIComponent('http://100.102.8.102:10003');
  const health = relay.visionRelayTarget(`/vision-stream/health?base=${base}`);
  if (health?.upstream !== 'http://100.102.8.102:10003/health') failures.push(`health 가 그 포트의 /health 로 안 간다 — ${JSON.stringify(health)}`);
  const overlay = relay.visionRelayTarget(`/vision-stream/frame?base=${base}&model=yoloe&n=3`);
  if (overlay?.upstream !== 'http://100.102.8.102:10003/vision?model=yoloe') failures.push(`frame(model) 이 /vision?model= 로 안 간다 — ${JSON.stringify(overlay)}`);
  const raw = relay.visionRelayTarget(`/vision-stream/frame?base=${base}`);
  if (raw?.upstream !== 'http://100.102.8.102:10003/stream') failures.push(`model 이 없으면 원본 /stream 이어야 한다 — ${JSON.stringify(raw)}`);
  if (relay.visionRelayTarget('/autodrive-ai/control/go1_front') !== null) failures.push('다른 창구의 경로를 가로챈다');
  for (const [url, why] of [
    [`/vision-stream/push?base=${base}`, '열지 않은 경로'],
    [`/vision-stream/health?base=${encodeURIComponent('http://100.102.8.102:10003/admin')}`, '경로가 붙은 base'],
    [`/vision-stream/health?base=${encodeURIComponent('file:///etc/passwd')}`, 'http 가 아닌 base'],
    [`/vision-stream/frame?base=${base}&model=${encodeURIComponent('../x')}`, '모델 이름이 아닌 것'],
  ]) {
    const got = relay.visionRelayTarget(url);
    if (got === null || !('error' in got)) failures.push(`${why} 를 받아 준다 — ${url}`);
  }
}

// ── 2. 중계가 값을 고치지 않는다 ────────────────────────────────────────────
{
  const respond = () => {
    const res = { statusCode: 0, headers: {}, body: null, setHeader(k, v) { this.headers[k.toLowerCase()] = v; }, end(b) { this.body = b; } };
    return res;
  };
  const jsonBody = Buffer.from(JSON.stringify(HEALTH_ROBOT1_LIVE));
  const res1 = respond();
  await relay.handleVisionStream({ url: `/vision-stream/health?base=${encodeURIComponent('http://h:10003')}`, method: 'GET' }, res1, () => failures.push('health 를 다음 미들웨어로 넘긴다'),
    async (url) => {
      if (url !== 'http://h:10003/health') failures.push(`health 가 엉뚱한 곳을 두드린다 — ${url}`);
      return { status: 200, headers: { get: () => 'application/json' }, arrayBuffer: async () => jsonBody };
    });
  if (res1.statusCode !== 200 || !Buffer.from(res1.body).equals(jsonBody)) failures.push('health 본문이 그대로 안 옮겨진다');
  if (res1.headers['x-vision-relay'] !== '1') failures.push('X-Vision-Relay 표시가 없다 — 화면이 중계 유무를 못 가른다');

  const jpeg = Buffer.from([0xff, 0xd8, 1, 2, 3, 0xff, 0xd9]);
  const part = Buffer.concat([Buffer.from('--frame\r\nContent-Type: image/jpeg\r\n\r\n'), jpeg, Buffer.from('\r\n--frame\r\n')]);
  const res2 = respond();
  await relay.handleVisionStream({ url: `/vision-stream/frame?base=${encodeURIComponent('http://h:10003')}&model=yoloe`, method: 'GET' }, res2, () => undefined,
    async () => ({
      ok: true, status: 200,
      headers: { get: () => 'multipart/x-mixed-replace; boundary=frame' },
      body: { getReader: () => { let sent = false; return { read: async () => (sent ? { done: true } : (sent = true, { done: false, value: part })) }; } },
    }));
  if (res2.statusCode !== 200 || !Buffer.from(res2.body).equals(jpeg)) failures.push('frame 이 스트림의 첫 JPEG 한 장을 그대로 안 준다');

  const res3 = respond();
  await relay.handleVisionStream({ url: `/vision-stream/frame?base=${encodeURIComponent('http://h:10003')}&model=moge2_aerial`, method: 'GET' }, res3, () => undefined,
    async () => ({ ok: false, status: 404, headers: { get: () => 'application/json' }, body: null, text: async () => '{"detail": "비전 결과 없음"}' }));
  if (res3.statusCode !== 502 || !String(res3.body).includes('비전 결과 없음')) failures.push(`서버 사유(404)가 안 옮겨진다 — ${res3.statusCode} ${res3.body}`);
}

// ── 3. /health 뜯기 ─────────────────────────────────────────────────────────
{
  const idle = client.parseStreamHealth(HEALTH_ROBOT1_IDLE);
  if (idle?.source !== 'robot1' || idle.port !== 10003) failures.push(`실측 /health 를 못 뜯는다 — ${JSON.stringify(idle)}`);
  if (idle?.upstreamHosts.join(',') !== '100.72.109.9') failures.push(`상태 문장에서 파이 주소를 못 뽑는다 — ${idle?.upstreamHosts}`);
  if (idle?.models.length !== 0) failures.push('결과가 없는데 모델이 생겼다');

  const live = client.parseStreamHealth(HEALTH_ROBOT1_LIVE);
  const yoloe = live?.models.find((m) => m.model === 'yoloe');
  const depth = live?.models.find((m) => m.model === 'unidepth');
  if (yoloe?.n !== 1519 || yoloe.lagMs !== 71 || yoloe.detections !== 4 || yoloe.ageS !== 0.2) failures.push(`모델 요약이 그대로 안 옮겨진다 — ${JSON.stringify(yoloe)}`);
  if (yoloe === undefined || !client.modelLive(yoloe)) failures.push('0.2초 전 결과를 끊긴 모델로 본다');
  if (depth === undefined || client.modelLive(depth)) failures.push('41초 전 결과를 지금 오는 모델로 본다 — 서버 10초 보고(30초 선)와 다르다');
  // 프레임 번호로 잰 차이 — 원본 최신 1520, yoloe 가 본 원본 1519 → 1장 뒤.
  if (client.frameGap(live?.frames ?? null, yoloe ?? null) !== 1) failures.push(`프레임 번호 차이가 1장이 아니다 — ${client.frameGap(live?.frames ?? null, yoloe ?? null)}`);
  if (client.frameGap(3, yoloe ?? null) !== null) failures.push('실행이 바뀌어 번호가 거꾸로인데 차이를 지어낸다');

  // 대조군 — 모양이 다르면 null.
  const wrong = client.parseStreamHealth({ status: 'ok', detail: 'not the stream server' });
  if (wrong === null) controls.push('모양이 다른 /health 는 null');
  else failures.push('대조군 실패: 다른 서버의 JSON 을 스트림 서버로 읽는다');
}

// ── 3-b. IP 한 칸 + 포트 줄 (261001 지시 — IP 만 바꾸면 포트 넷이 다 따라간다) ──
{
  const { saveConnections, connectionKey } = await load('src', 'shared', 'connections.ts');
  const defaults = client.visionBases();
  if (defaults.join(',') !== ['10001', '10002', '10003', '10004'].map((p) => `http://100.102.8.102:${p}`).join(',')) {
    failures.push(`기본 주소가 테일넷 IP + 포트 넷이 아니다 — ${defaults.join(', ')}`);
  }
  saveConnections({ [connectionKey('vision', 'host')]: '10.0.0.5' });
  const moved = client.visionBases();
  if (moved.join(',') !== ['10001', '10002', '10003', '10004'].map((p) => `http://10.0.0.5:${p}`).join(',')) {
    failures.push(`IP 칸만 바꿨는데 포트 줄이 안 따라간다 — ${moved.join(', ')}`);
  }
  saveConnections({
    [connectionKey('vision', 'host')]: 'http://10.0.0.5:9999/x',
    [connectionKey('vision', 'ports')]: '10003\nabc\n70000\nhttp://10.9.9.9:10004/\n10003',
  });
  const mixed = client.visionBases();
  if (mixed.join(',') !== 'http://10.0.0.5:10003,http://10.9.9.9:10004') {
    failures.push(`IP 칸의 포트 · 경로를 안 떼거나, 번호 아닌 줄 · 범위 밖 · 겹친 줄을 안 버리거나, 통째 주소 줄을 못 쓴다 — ${mixed.join(', ')}`);
  }
  if (client.visionHostOrigin('ftp://10.0.0.5') !== null) failures.push('http 가 아닌 IP 칸을 받아 준다');
  saveConnections({});
}

// ── 4. 장비와 포트 묶기 ─────────────────────────────────────────────────────
{
  const B = (port) => `http://100.102.8.102:${port}`;
  const state = (body) => ({ health: client.parseStreamHealth(body), receivedAtMs: 0, error: null, via: 'relay', rate: {} });
  const robot2 = { ...HEALTH_ROBOT1_IDLE, source: 'robot2', port: 10004, status: { state: '붙는 중 mqtt://100.83.132.16:1883' } };
  const sources = { [B(10003)]: state(HEALTH_ROBOT1_IDLE), [B(10004)]: state(robot2) };
  const bases = [B(10001), B(10002), B(10003), B(10004)];

  const matched = binding.resolveVisionBinding(null, '100.72.109.9', sources, bases);
  if (matched.how !== 'matched' || matched.base !== B(10003)) failures.push(`주소가 같은 포트 하나를 못 묶는다 — ${JSON.stringify(matched)}`);
  const chosen = binding.resolveVisionBinding(B(10004), '100.72.109.9', sources, bases);
  if (chosen.how !== 'chosen' || chosen.base !== B(10004)) failures.push('사람이 고른 포트가 자동 맞춤에 진다');
  const unbound = binding.resolveVisionBinding(binding.VISION_UNBOUND, '100.72.109.9', sources, bases);
  if (unbound.base !== null || unbound.how !== 'unbound') failures.push('「연결 안 함」을 골랐는데 묶는다');
  const none = binding.resolveVisionBinding(null, 'pi7.local', sources, bases);
  if (none.base !== null) failures.push('주소가 다른데 아무 포트나 묶는다');
  const noHost = binding.resolveVisionBinding(null, null, sources, bases);
  if (noHost.base !== null) failures.push('브로커가 없는 장비(/state)를 아무 포트에나 묶는다');

  // 대조군 — 같은 파이를 두 포트가 보고 있으면(서버 실행 인자 실수) 고르지 않는다.
  const twin = { ...sources, [B(10004)]: state({ ...robot2, status: { state: '받는 중 mqtt://100.72.109.9:1883' } }) };
  const ambiguous = binding.resolveVisionBinding(null, '100.72.109.9', twin, bases);
  if (ambiguous.base === null && ambiguous.how === 'ambiguous' && ambiguous.candidates.length === 2) controls.push('주소가 같은 포트가 둘이면 안 묶는다');
  else failures.push(`대조군 실패: 후보가 둘인데 하나를 골랐다 — ${JSON.stringify(ambiguous)}`);
}

// ── 5. 속도 · 경계 ──────────────────────────────────────────────────────────
{
  let results = 100;
  let now = 10_000;
  store.resetVisionStore(async (url) => ({
    ok: true, status: 200,
    headers: { get: (name) => (name === 'X-Vision-Relay' ? '1' : null) },
    json: async () => ({ ...HEALTH_ROBOT1_LIVE, vision: { yoloe: { ...HEALTH_ROBOT1_LIVE.vision.yoloe, results } } }),
  }));
  const base = 'http://100.102.8.102:10003';
  await store.pollVisionSource(base, () => now);
  if (store.visionSourceOf(base).rate.yoloe !== undefined) failures.push('한 번 받고 속도를 지어낸다');
  results = 164; now = 20_000;
  await store.pollVisionSource(base, () => now);
  const rate = store.visionSourceOf(base).rate.yoloe;
  if (rate === undefined || Math.abs(rate - 6.4) > 1e-9) failures.push(`누계 차이로 잰 속도가 6.4장/초가 아니다 — ${rate}`);
  if (store.visionSourceOf(base).via !== 'relay') failures.push('중계로 받은 것을 중계로 안 적는다');
  store.resetVisionStore();

  const dir = join(root, 'src', 'vision');
  const walk = (d) => readdirSync(d).flatMap((name) => {
    const p = join(d, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
  for (const file of walk(dir)) {
    const rel = relative(root, file).split(sep).join('/');
    const text = readFileSync(file, 'utf8');
    if (/from '\.\.\/(\.\.\/)?(autodrive|detect)\//.test(text)) failures.push(`${rel}: 장애물 탐지 · 문 찾기 경계를 import 한다`);
    if (/210\.110\.250\.33/.test(text)) failures.push(`${rel}: 장애물 탐지 AI 서버 주소가 경계 밖에 있다`);
  }
}

if (failures.length > 0) {
  console.error('❌ verify:vision-stream');
  for (const f of failures) console.error('  - ' + f);
  process.exit(1);
}
console.log(`✅ 추론 스트림 — 중계 경로 둘 · 값 그대로 · 실측 /health 뜯기 · IP 한 칸 + 포트 줄 · 장비 묶음(고름 > 같은 주소 하나) · 누계로 잰 속도 · 경계 분리 (대조군 ${controls.length}: ${controls.join(' · ')})`);
