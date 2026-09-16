// verify:autodrive-ai (260915 신설 — 자율주행 편 · 로봇 영상 · 장애물 탐지)
//
// **AI 서버의 영상·장애물 JSON 이 자율주행 편에만 붙고, 문 찾기 시연과는 한 줄도 안 섞이는가.**
//
// 막으려는 실패 넷.
//  1. **창구가 아무 데나 두드리는 통로가 되는 것** — 경로는 control · frame 둘, base 는 경로 없는 http(s) 만.
//  2. **받은 값을 고치는 것** — JSON 은 받은 그대로(`raw`) 들고 있고, 판정(has_near_obstacle)을 다시 계산하지 않는다.
//  3. **폴링이 새거나 먼저 끝난 쪽이 남은 쪽을 끄는 것** — 붙잡은 수를 센다. 판이 안 열린 시연 편에서는 안 돈다.
//  4. **시연 쪽과 섞이는 것** — `src/autodrive/` 와 `src/detect/`·pi7 경계가 서로 import 하지 않고, 시연 편 팔레트는
//     전과 같으며, 표시등 목록도 그대로다.
//
// 대조군 포함 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 본다.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readFileSync(join(root, ...p), 'utf8');
const code = (source) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

const relay = await load('scripts', 'autodrive-ai-relay.mjs');
const client = await load('src', 'autodrive', 'aiClient.ts');
const obstacle = await load('src', 'autodrive', 'obstacle.ts');

const failures = [];
const controls = [];

/** 사용자가 준 실측 한 건 (260915). */
const SAMPLE = {
  timestamp: '1789438645.4756753', camera_id: 'go1_front',
  detections: [
    { id: 1, name: 'umbrella', group: 'HARD_OBSTACLE', rel_depth: 1.3098, distance_cm: 43.5888, distance_cm_raw: 43.1798, risk_level: 'near', bbox_xyxy: [91, 221, 230, 379] },
    { id: 2, name: 'person', group: 'AGENT', rel_depth: 2.4433, distance_cm: 101.4141, distance_cm_raw: 100.9085, risk_level: 'far', bbox_xyxy: [74, 116, 126, 232] },
  ],
  has_near_obstacle: true, state_change: false,
};

// ── 1. 창구 ──────────────────────────────────────────────────────────────────
{
  const base = encodeURIComponent('http://210.110.250.33:7864');
  const ok = relay.relayTarget(`/autodrive-ai/control/go1_front?base=${base}`);
  if (ok?.upstream !== 'http://210.110.250.33:7864/control/go1_front') failures.push(`control 이 사용자가 준 주소로 안 간다 — ${ok?.upstream}`);
  const frame = relay.relayTarget(`/autodrive-ai/frame/go1_front?base=${base}`);
  if (frame?.upstream !== 'http://210.110.250.33:7864/stream/ai/go1_front') failures.push(`frame 이 사용자가 준 스트림으로 안 간다 — ${frame?.upstream}`);
  if (relay.relayTarget('/detect-sample/x.json') !== null) failures.push('다른 창구의 경로를 가로챈다');
  const refused = [
    ['/autodrive-ai/upload/go1_front', '열린 경로 밖'],
    ['/autodrive-ai/command/go1_front', '명령 경로'],
    [`/autodrive-ai/control/../x?base=${base}`, '상위 경로'],
    [`/autodrive-ai/control/go1_front?base=${encodeURIComponent('http://h:1/evil')}`, 'base 에 경로'],
    [`/autodrive-ai/control/go1_front?base=${encodeURIComponent('file:///etc/passwd')}`, 'file 주소'],
    [`/autodrive-ai/control/go1_front?base=${encodeURIComponent('http://u:p@h:1')}`, 'base 에 계정'],
  ];
  for (const [url, why] of refused) {
    if (!('error' in (relay.relayTarget(url) ?? {}))) failures.push(`창구가 ${why}(${url})을 받는다`);
  }
  // 대조군 — 거르는 규칙이 실제로 무언가를 막는다: 같은 요청이 base 만 고치면 통과한다.
  controls.push('경로 없는 base 로 고치면 통과');
  if ('error' in (relay.relayTarget(`/autodrive-ai/control/go1_front?base=${encodeURIComponent('http://h:1')}`) ?? { error: 1 })) failures.push('대조군 실패: 올바른 base 도 막힌다 — 규칙이 전부를 막는다');

  // 첫 JPEG — 경계로 자르고, 줄바꿈은 뺀다.
  const jpeg = Buffer.from([0xff, 0xd8, 1, 2, 3, 0xff, 0xd9]);
  const part = (b) => Buffer.concat([Buffer.from('--frame\r\nContent-Type: image/jpeg\r\n\r\n'), b, Buffer.from('\r\n')]);
  const two = Buffer.concat([part(jpeg), part(Buffer.from([0xff, 0xd8, 9, 0xff, 0xd9]))]);
  if (relay.firstJpeg(two, 'frame')?.equals(jpeg) !== true) failures.push('MJPEG 에서 첫 한 장을 정확히 못 자른다');
  if (relay.firstJpeg(part(jpeg), 'frame') !== null) failures.push('다음 경계가 오기 전에 한 장이 끝났다고 본다 — 반쪽 JPEG 가 나간다');
  if (relay.firstJpeg(jpeg, null)?.equals(jpeg) !== true) failures.push('경계를 모를 때 SOI~EOI 로 못 자른다');

  // 미들웨어를 통째로 — 받은 바이트를 그대로 옮기고 표지를 붙인다. 가짜 서버.
  const res = () => ({ headers: {}, statusCode: 0, body: null, setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = Buffer.isBuffer(b) ? b : Buffer.from(String(b)); } });
  const upstreamBody = JSON.stringify(SAMPLE);
  const fakeFetch = async (url) => ({
    status: 200, ok: true,
    headers: { get: (k) => (k.toLowerCase() === 'content-type' ? (url.includes('/stream/') ? 'multipart/x-mixed-replace; boundary=frame' : 'application/json') : null) },
    arrayBuffer: async () => new TextEncoder().encode(upstreamBody).buffer,
    body: { getReader: () => { let sent = false; return { read: async () => (sent ? { done: true } : (sent = true, { done: false, value: new Uint8Array(two) })) }; } },
  });
  const r1 = res();
  await relay.handleAutodriveAi({ url: `/autodrive-ai/control/go1_front?base=${base}`, method: 'GET' }, r1, () => {}, fakeFetch);
  if (r1.statusCode !== 200 || r1.body?.toString() !== upstreamBody) failures.push('창구가 JSON 을 그대로 옮기지 않는다');
  if (r1.headers['X-Autodrive-Relay'] !== '1') failures.push('창구 표지(X-Autodrive-Relay)가 없다 — 화면이 정적 서버와 못 가른다');
  const r2 = res();
  await relay.handleAutodriveAi({ url: `/autodrive-ai/frame/go1_front?base=${base}`, method: 'GET' }, r2, () => {}, fakeFetch);
  if (r2.statusCode !== 200 || r2.headers['Content-Type'] !== 'image/jpeg' || r2.body?.equals(jpeg) !== true) failures.push('창구가 한 장을 JPEG 로 안 준다');
  const r3 = res();
  await relay.handleAutodriveAi({ url: `/autodrive-ai/control/go1_front?base=${base}`, method: 'POST' }, r3, () => {}, fakeFetch);
  if (r3.statusCode !== 405) failures.push('창구가 GET 아닌 요청을 옮긴다');

  const vite = read('vite.config.ts');
  if (!/autodriveAiRelay\(\)/.test(vite)) failures.push('개발 서버에 창구가 안 붙었다');
  // **개발 서버를 죽이지 않는다** (260915 실측) — configureServer 가 함수를 돌려주면 vite 가 인자 없이 불러
  // `npm run dev` 가 기동 중에 죽는다. connect 의 use() 는 앱(함수)을 돌려주므로 그대로 돌려주면 그렇게 된다.
  const plugin = relay.autodriveAiRelay();
  const connectLike = { middlewares: { use: () => () => { throw new Error('훅으로 불렸다'); } } };
  if (plugin.configureServer(connectLike) !== undefined) failures.push('configureServer 가 무언가를 돌려준다 — 개발 서버가 기동 중에 죽는다');
  if (plugin.configurePreviewServer(connectLike) !== undefined) failures.push('configurePreviewServer 가 무언가를 돌려준다 — 미리보기 서버가 죽는다');
}

// ── 2. 받은 그대로 ────────────────────────────────────────────────────────────
{
  const snap = obstacle.parseObstacle(SAMPLE, 1000);
  if (snap === null) failures.push('실측 JSON 을 못 읽는다');
  else {
    if (snap.raw !== SAMPLE) failures.push('받은 객체를 그대로 들고 있지 않다 — 액션 아이템의 「받은 JSON 그대로」가 거짓이 된다');
    if (snap.timestampSec !== 1789438645.4756753) failures.push('문자열 timestamp 를 못 읽는다');
    if (snap.detections[0].distanceCm !== 43.5888 || snap.detections[0].riskLevel !== 'near' || snap.detections[0].bbox?.[2] !== 230) failures.push('탐지 한 줄의 칸을 잘못 옮긴다');
    if (snap.hasNearObstacle !== true) failures.push('서버 판정을 못 옮긴다');
  }
  if (obstacle.parseObstacle({ ...SAMPLE, detections: 'x' }) !== null) failures.push('detections 가 배열이 아닌데 읽었다');
  const noVerdict = obstacle.parseObstacle({ ...SAMPLE, has_near_obstacle: undefined });
  if (noVerdict?.hasNearObstacle !== null) failures.push('판정 값이 없는데 null 이 아니다 — 화면이 거리로 판정을 지어낸다');
  const views = code(read('src', 'autodrive', 'views', 'AutodriveViews.tsx'));
  if (/distanceCm\s*[<>]=?\s*\d/.test(views)) failures.push('화면이 거리로 판정을 다시 한다 — 판정은 AI 서버의 has_near_obstacle 이다');
}

// ── 3. 열 · 줄 · 폴링 ────────────────────────────────────────────────────────
{
  obstacle.resetObstacle();
  obstacle.receiveObstacle({ ...SAMPLE, has_near_obstacle: false }, 'relay', 1000);
  obstacle.receiveObstacle(SAMPLE, 'relay', 1500);
  obstacle.receiveObstacle(SAMPLE, 'relay', 2000);
  obstacle.receiveObstacle({ ...SAMPLE, timestamp: '1789438646.0', has_near_obstacle: false }, 'relay', 2500);
  const texts = obstacle.obstacleState().log.map((l) => l.text);
  if (texts.filter((t) => t.startsWith('가까운 장애물 있음')).length !== 1) failures.push(`가까운 장애물 생김이 한 번으로 안 남는다 — ${texts.join(' / ')}`);
  if (!texts.some((t) => t.includes('umbrella 44cm'))) failures.push('줄에 무엇이 가까워졌는지 안 적는다');
  if (texts.filter((t) => t === '가까운 장애물 없음').length !== 2) failures.push('사라짐이 바뀔 때마다 안 남는다');
  // 서버 시계가 멈추면 멈춤이다.
  obstacle.resetObstacle();
  obstacle.receiveObstacle(SAMPLE, 'relay', 10_000);
  obstacle.receiveObstacle(SAMPLE, 'relay', 16_000);
  if (!obstacle.obstacleFrozen(obstacle.obstacleState(), 16_000)) failures.push('서버 시각이 6초째 같은데 멈춤으로 안 본다');
  obstacle.receiveObstacle({ ...SAMPLE, timestamp: '1789438700' }, 'relay', 16_500);
  if (obstacle.obstacleFrozen(obstacle.obstacleState(), 16_500)) failures.push('서버 시각이 바뀌었는데 멈춤이 안 풀린다');
  obstacle.noteObstacleError('끊김', 17_000);
  obstacle.noteObstacleError('끊김', 17_500);
  if (obstacle.obstacleState().log.filter((l) => l.text.includes('끊김')).length !== 1) failures.push('같은 실패가 줄마다 쌓인다');

  // 폴링 — 붙잡은 수. 가짜 창구.
  obstacle.resetObstacle();
  let calls = 0;
  const fetcher = async (url) => { calls += 1; return { ok: true, status: 200, headers: { get: (k) => (k === 'X-Autodrive-Relay' && url.startsWith('/autodrive-ai/') ? '1' : null) }, json: async () => SAMPLE }; };
  const a = obstacle.holdObstaclePolling(fetcher);
  const b = obstacle.holdObstaclePolling();
  await new Promise((r) => setTimeout(r, 1200));
  const afterTwo = calls;
  a();
  if (!obstacle.obstacleState().polling) failures.push('붙잡은 둘 중 하나가 놓자 폴링이 멈췄다');
  await new Promise((r) => setTimeout(r, 700));
  if (calls <= afterTwo) failures.push('하나가 남아 있는데 요청이 멈췄다');
  b();
  const stopped = calls;
  await new Promise((r) => setTimeout(r, 900));
  if (calls > stopped + 1) failures.push('다 놓았는데 폴링이 계속 돈다');
  if (afterTwo < 2 || afterTwo > 4) failures.push(`1.2초에 요청 ${afterTwo}번 — 0.5초 주기(2~3번)가 아니다`);
  if (obstacle.obstacleState().latest?.hasNearObstacle !== true || obstacle.obstacleState().via !== 'relay') failures.push('폴링이 받은 값을 창구 경유로 안 적는다');

  // 창구가 없는 서버 → 직접. 직접이 막히면 사유를 말한다.
  const noRelay = async () => ({ ok: false, status: 404, headers: { get: () => null }, json: async () => { throw new Error('html'); } });
  const blocked = await client.fetchObstacleJson(async (url) => (url.startsWith('/autodrive-ai/') ? noRelay() : Promise.reject(new TypeError('Failed to fetch'))));
  if (blocked.ok || !/CORS/.test(blocked.reason)) failures.push('창구도 없고 직접도 막혔는데 CORS 사유를 안 말한다');

  // 판이 열려야 돈다 — 시연 편은 판이 안 열린다.
  obstacle.resetObstacle();
  const { startObstacleWatch } = await load('src', 'autodrive', 'watch.ts');
  const { beginNavRun, endNavRun } = await load('src', 'physical', 'navRun.ts');
  const stop = startObstacleWatch();
  if (obstacle.obstacleHolders() !== 0) failures.push('판이 없는데 장애물 폴링을 붙잡았다');
  const scenario = await load('src', 'data', 'scenario.ts');
  scenario.resetMission();
  scenario.proposeMission({ origin: 'script', missionId: 'MSN-260909-01', title: 'door', keywords: [], planId: null, world: 'registry' });
  scenario.acceptProposal('remote');
  if (obstacle.obstacleHolders() !== 0) failures.push('시연 편을 승인했는데 장애물 폴링이 돈다');
  scenario.resetMission();
  // 대조군 — 판을 열면 붙잡는다. 막은 것이 「판이 안 열림」이라는 뜻이다.
  beginNavRun('MSN-260915-01');
  controls.push('판을 열면 장애물 폴링을 붙잡는다');
  if (obstacle.obstacleHolders() !== 1) failures.push('대조군 실패: 판을 열어도 폴링을 안 붙잡는다 — 위 검사가 헛돈다');
  endNavRun();
  if (obstacle.obstacleHolders() !== 0) failures.push('판을 닫았는데 폴링을 안 놓는다');
  stop();
  obstacle.resetObstacle();
}

// ── 4. 시연 쪽과 섞이지 않는다 ─────────────────────────────────────────────────
{
  const walk = (dir) => readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : /\.(ts|tsx)$/.test(name) ? [full] : [];
  });
  const autodriveDir = join('src', 'autodrive') + sep;
  for (const file of walk(join(root, 'src'))) {
    const rel = relative(root, file);
    const source = readFileSync(file, 'utf8');
    if (rel.startsWith(autodriveDir)) {
      if (/from\s+['"][^'"]*\/detect\//.test(source)) failures.push(`${rel}: 문 찾기 탐지(src/detect)를 import 한다`);
      if (/PhysicalClient|robotClient|robotSession|robotCommands/.test(code(source))) failures.push(`${rel}: pi7 로봇 경계를 쓴다`);
    } else {
      if (/210\.110\.250\.33|:7864|go1_front/.test(source) && !rel.startsWith(autodriveDir)) failures.push(`${rel}: AI 서버 주소·카메라 이름이 경계 밖에 있다`);
    }
    if (rel.startsWith(join('src', 'detect')) && /autodrive/.test(source)) failures.push(`${rel}: 문 찾기 탐지가 자율주행 폴더를 안다`);
  }

  // 팔레트 — 시연 편은 전과 같고, 자율주행 편에는 로봇 영상이 있고 시연 노드가 없다.
  const { VIEW_NODE_RENDERERS } = await load('src', 'tabs', 'viewNodes.tsx').catch(() => ({ VIEW_NODE_RENDERERS: null }));
  const shown = (missionId) => (VIEW_NODE_RENDERERS ?? []).filter((e) => e.inPalette !== false && (e.showFor?.(missionId) ?? true)).map((e) => e.kind).sort();
  if (VIEW_NODE_RENDERERS === null) {
    // tsx 는 Node 에서 안 열린다 — 소스로 본다.
    const nodes = read('src', 'tabs', 'viewNodes.tsx');
    const entryOf = (kind) => nodes.slice(nodes.indexOf(`kind: '${kind}'`), nodes.indexOf('zoom:', nodes.indexOf(`kind: '${kind}'`)));
    if (!/showFor:\s*onlyRelay/.test(entryOf('autodrive-cam'))) failures.push('로봇 영상 노드가 자율주행 편에만 뜨게 걸려 있지 않다 — 시연 편 팔레트에 버튼이 는다');
    for (const kind of ['detect-cam', 'detect-reason', 'detect-map', 'robot']) {
      if (!/showFor:\s*notRelay/.test(entryOf(kind))) failures.push(`${kind} 가 자율주행 편 팔레트에도 뜬다 — 시연 노드가 섞인다`);
    }
    for (const kind of ['device-risk', 'control', 'metrics']) {
      if (/showFor:/.test(entryOf(kind))) failures.push(`${kind} 의 팔레트 조건이 바뀌었다 — 시연 편 팔레트가 달라진다`);
    }
    if (!/const notRelay = \(missionId: string\) => !relayDriven\(missionId\)/.test(nodes)) failures.push('notRelay 가 중계 편만 가르는 규칙이 아니다');
    if (!/const onlyRelay = \(missionId: string\) => relayDriven\(missionId\)/.test(nodes)) failures.push('onlyRelay 가 중계 편만 고르는 규칙이 아니다');
  } else {
    if (shown('MSN-260909-01').includes('autodrive-cam')) failures.push('시연 편 팔레트에 로봇 영상이 뜬다');
  }
  const palette = read('src', 'canvas', 'Palette.tsx');
  if (!/entry\.showFor\?\.\(missionId\) \?\? true/.test(palette)) failures.push('팔레트가 showFor 를 안 본다 — 조건이 있어도 모든 임무에 뜬다');
  const { relayDriven } = await load('src', 'scenarios', 'library.ts');
  if (relayDriven('MSN-260909-01') || !relayDriven('MSN-260915-01')) failures.push('중계 편 판정이 어긋난다 — 팔레트가 반대로 갈린다');

  // 액션 아이템 — 장애물은 중계 편의 T-NB2 에서만.
  const modal = code(read('src', 'views', 'ActionModal.tsx'));
  if (!/relay\s*\?[\s\S]*task\.id === OBSTACLE_TASK && <><h3>장애물 탐지/.test(modal)) failures.push('장애물 액션 아이템이 중계 편 갈래 안에 있지 않다');
  if (!/relay && task\.id === OBSTACLE_TASK && <><h3>판단 근거<\/h3><ObstacleEvidence/.test(modal)) failures.push('장애물 판단 근거가 중계 편 T-NB2 에만 걸려 있지 않다');
  if (obstacle.OBSTACLE_TASK !== 'T-NB2') failures.push('장애물을 붙이는 노드가 「장애물 탐지」(T-NB2)가 아니다');
  const door = JSON.parse(read('scenarios', 'MSN-260909-01.json'));
  if (door.tasks.some((t) => t.id === obstacle.OBSTACLE_TASK)) failures.push('시연 편에 같은 태스크 id 가 있다 — 장애물 값이 시연 노드에 붙을 수 있다');

  // 연결 — 새 대상은 따로, 표시등 목록·탐지 주소는 그대로.
  const { CHECKED_TARGETS } = await load('src', 'shared', 'connectionHealth.ts');
  if (CHECKED_TARGETS.includes('autodrive-ai')) failures.push('AI 서버가 머리줄 표시등 목록에 들어갔다 — 시연의 「n/4 확인됨」이 바뀐다');
  const { CONNECTION_TARGETS, connectionAddress } = await load('src', 'shared', 'connections.ts');
  if (!CONNECTION_TARGETS.some((t) => t.id === 'autodrive-ai' && t.live)) failures.push('연결 관리에 AI 서버 대상이 없다');
  await load('src', 'detect', 'DetectClient.ts');
  if (connectionAddress('detect', 'base') === connectionAddress('autodrive-ai', 'base')) failures.push('문 찾기 탐지와 AI 서버가 같은 주소를 본다');
  if (client.aiStreamUrl() !== 'http://210.110.250.33:7864/stream/ai/go1_front') failures.push(`영상 주소가 사용자가 준 것과 다르다 — ${client.aiStreamUrl()}`);
  if (client.aiControlUrl() !== 'http://210.110.250.33:7864/control/go1_front') failures.push(`장애물 주소가 사용자가 준 것과 다르다 — ${client.aiControlUrl()}`);
  const { checkAutodriveAi } = await load('src', 'shared', 'connectionCheck.ts');
  const lines = await checkAutodriveAi(async (url) => ({ ok: true, status: 200, headers: { get: (k) => (k === 'X-Autodrive-Relay' && url.startsWith('/autodrive-ai/') ? '1' : null) }, json: async () => SAMPLE }));
  if (lines[0]?.ok !== true || !/탐지 2건/.test(String(lines[0]?.reason))) failures.push('연결 확인의 장애물 줄이 받은 값을 말하지 않는다');
  if (lines[1]?.ok !== null) failures.push('브라우저가 아닌데 영상 줄을 초록/빨강으로 칠했다 — 확인 못 한 것은 모른다');
}

if (failures.length) {
  console.error(`❌ verify:autodrive-ai\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 창구 — control · frame 둘만, base 는 경로·계정 없는 http(s) · JSON 은 바이트 그대로 · MJPEG 첫 장만 잘라 JPEG 로');
console.log('✅ 받은 그대로 — raw 보존 · 문자열 timestamp · 판정은 서버의 has_near_obstacle (화면이 거리로 다시 판정하지 않음)');
console.log('✅ 줄 — 가까운 장애물 생김/사라짐만 · 같은 실패는 한 번 · 서버 시각 멈춤 판정');
console.log('✅ 폴링 — 0.5초 · 붙잡은 수를 셈 · 자율주행 판에서만 붙잡고 시연 편에서는 안 돎 · 창구 없으면 직접, 막히면 CORS 사유');
console.log('✅ 시연과 분리 — src/autodrive ↔ src/detect·pi7 import 0 · 주소는 경계 안 · 시연 편 팔레트 그대로 · 표시등 목록 그대로');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
