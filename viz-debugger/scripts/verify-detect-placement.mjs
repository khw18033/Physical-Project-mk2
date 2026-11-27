// verify:detect-placement (261125 신설 — 객체 탐지 상태판 · 모델 실행 장치)
//
// **모델 칩이 어느 장치에서 도는지를 data_stream 스트림 두 개로 맞게 가르는가.**
//
// 보는 것 일곱.
//  1. 창구 경로 — `/vision-stream/placement` 는 redis://host:port 만 받고, 키는 쿼리로 안 받는다
//  2. 스트림 요약 — 가장 최근 `planned` 하나 · 그 요청의 마지막 기록, 노드마다 마지막 상태 + 가장 최근 baseline
//  3. 가짜 소켓 — 보낸 명령은 XREVRANGE 둘뿐(두 스트림), 허용 목록 밖의 키는 보내지도 않는다
//  4. 저장 · 갈아 끼우기 (사용자 결정 1 + data_stream 답 뒤 검토) — 배치표가 밀려나도 저장본 유지, 더 새 `planned` 면 통째로 교체,
//     옛것은 무시(기록 시각 ts 순), 실행 끝(stopped)은 밀려난 뒤에도 따라가 그 배치표를 칩 판단에서 뺀다
//  5. (소스, 모델) → 장치 (사용자 결정 2) — 배치표에 있으면 그 노드, 없으면 data_stream 기기로 확정, 칩 꼬리표 · 장치 수
//  6. 조회 한 번 — 창구 답을 받아 합치고, 실패하면 저장본 그대로 사유만 적는다. 저장 키는 Redis 주소마다
//  7. CPU 작업 → 만드는 소스 카드 (261125 안 2) — 단위 기록(applied · running · replanned · stopped)을 따라 지금 노드 · 이동,
//     끝나거나 기록이 없으면 서버 고정(data_stream 기기). 실제 M8 시험 probe 순서를 옮긴 고정 자료
//
// 대조군 — 깨진 plan JSON 은 배치표로 안 서고, 옛 planned 가 새 배치표를 덮지 않는다.

import { EventEmitter } from 'node:events';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const failures = [];
const controls = [];
const expect = (what, ok, got = '') => { if (!ok) failures.push(`${what}${got === '' ? '' : ` — ${got}`}`); };

const relay = await load('scripts', 'vision-stream-relay.mjs');
const redis = await load('scripts', 'vision-redis-latest.mjs');
const reader = await load('scripts', 'vision-redis-placement.mjs');
const place = await load('src', 'detect', 'status', 'placement.ts');

// ── 1. 창구 경로 ────────────────────────────────────────────────────────────
{
  const r = encodeURIComponent('redis://100.125.104.23:6380');
  const got = relay.visionRelayTarget(`/vision-stream/placement?redis=${r}`);
  expect('placement 경로', got?.kind === 'placement' && got.host === '100.125.104.23' && got.port === 6380 && got.key === undefined, JSON.stringify(got));
  let blocked = 0;
  for (const url of [
    `/vision-stream/placement?redis=${encodeURIComponent('http://h:6380')}`,
    `/vision-stream/placement?redis=${encodeURIComponent('redis://h:6380/0')}`,
    `/vision-stream/placement?redis=${encodeURIComponent('redis://u:p@h:6380')}`,
    '/vision-stream/keys?redis=redis%3A%2F%2Fh%3A6380',
  ]) {
    const res = relay.visionRelayTarget(url);
    if (res !== null && 'error' in res) blocked += 1; else failures.push(`대조군 실패: ${url} 를 받아 준다`);
  }
  if (blocked === 4) controls.push('redis 가 아닌 주소 · 경로 · 계정 · 없는 경로');
  const latest = relay.visionRelayTarget(`/vision-stream/latest?redis=${r}&source=robot1&model=targeted`);
  expect('latest 경로는 그대로', latest?.kind === 'latest' && latest.key === 'vision_stream:robot1:targeted', JSON.stringify(latest));
}

// ── 2. 스트림 요약 ──────────────────────────────────────────────────────────
const bulk = (s) => Buffer.from(String(s));
/** XREVRANGE 한 항목 — parseResp 가 내는 모양(Buffer). */
const entry = (id, fields) => [bulk(id), Object.entries(fields).flatMap(([k, v]) => [bulk(k), bulk(typeof v === 'string' ? v : JSON.stringify(v))])];
const orchRec = (id, event, rid, extra = {}) => entry(id, { schema: 'orch/1', event_id: `ev-${id}`, event, request_id: rid, execution_id: '', mode: 'local', basis: 'live', reason: '', ts: `t-${id}`, seq: '1', ...extra });
const planJson = (node, sources, models) => ({
  algorithm: 'placement/1', request_id: 'x',
  gpu_units: [{ unit: `gpu:${models.join('+')}`, node, models, sources, fps_cap: Object.fromEntries(sources.map((s) => [s, 4.0])), need_mb: 1880, need_basis: 'measured', gpu_util: 0.3 }],
  cpu_units: [{ task: 'cam360_slice', node, reason: '비교 측정 전 — data_stream 기기에 둔다' }],
  refused: [{ item: 'gpu:river', reason: 'GPU 메모리 부족' }], degraded: [],
});
const nodeRec = (id, node, extra = {}) => entry(id, { schema: 'node/1', node, change: 'usage', role: 'gpu', source: 'local', ready: '1', cpu_pct: '12.5', mem_pct: '40.0', mem_mb: '6000', temp_c: '58.0', gpu: [{ name: 'NVIDIA GeForce RTX 4050 Laptop GPU', mem_total_mb: 6141, mem_used_mb: 3100, util_pct: 64, temp_c: 58 }], service_mode: '', ts: `t-${id}`, ...extra });
const baselineJson = { arch: 'x86_64', cpu_count: 20, cpu_model: '13th Gen Intel(R) Core(TM) i7-13700H', mem_total_mb: 15700, disk_total_gb: 1000, gpus: [{ name: 'NVIDIA GeForce RTX 4050 Laptop GPU', mem_total_mb: 6141 }] };

// 새것이 앞(XREVRANGE 순서)
const orchNewestFirst = [
  orchRec('1764050535000-0', 'running', 'req-B'),
  orchRec('1764050531000-0', 'applied', 'req-B'),
  orchRec('1764050530000-0', 'planned', 'req-B', { plan: planJson('book-4vg1edpvi5-wsl', ['robot1'], ['targeted']) }),
  orchRec('1764050529000-0', 'requested', 'req-B'),
  orchRec('1764040000000-0', 'planned', 'req-A', { plan: planJson('book-4vg1edpvi5-wsl', ['drone'], ['yoloe']) }),
];
const nodesNewestFirst = [
  nodeRec('1764050540000-0', 'book-4vg1edpvi5-wsl'),
  nodeRec('1764050500000-0', 'pi6', { role: 'sensor', source: 'k3s', gpu: [], temp_c: '' }),
  nodeRec('1764040000000-0', 'book-4vg1edpvi5-wsl', { change: 'added', baseline: baselineJson }),
];
{
  const s = reader.summarizePlacement(orchNewestFirst, nodesNewestFirst);
  expect('가장 최근 planned', s.plan?.requestId === 'req-B' && s.plan.eventId === 'ev-1764050530000-0' && s.plan.atMs === 1764050530000, JSON.stringify(s.plan));
  expect('배치표 단위', s.plan?.gpuUnits.length === 1 && s.plan.gpuUnits[0].node === 'book-4vg1edpvi5-wsl' && s.plan.gpuUnits[0].sources.join() === 'robot1' && s.plan.gpuUnits[0].fpsCap.robot1 === 4 && s.plan.gpuUnits[0].needMb === 1880, JSON.stringify(s.plan?.gpuUnits));
  expect('그 요청의 마지막 기록', s.plan?.last?.event === 'running' && s.plan.last.atMs === 1764050535000, JSON.stringify(s.plan?.last));
  expect('거절 · CPU 단위', s.plan?.refused[0]?.item === 'gpu:river' && s.plan.cpuUnits[0]?.task === 'cam360_slice');
  expect('요청별 마지막 기록', s.requests['req-B']?.event === 'running' && s.requests['req-A']?.event === 'planned', JSON.stringify(s.requests));
  // outbox — Redis 가 꺼져 있던 동안의 옛 planned 가 나중에 몰아 쓰여 스트림 ID 가 더 늦다. 기록 시각(ts)으로 가려야 한다.
  const outbox = reader.summarizePlacement([
    orchRec('1764062000000-0', 'planned', 'req-OLD', { ts: '2026-11-25T09:00:00.000+09:00', plan: planJson('book-4vg1edpvi5', ['drone'], ['yoloe']) }),
    orchRec('1764061000000-0', 'planned', 'req-NEW', { ts: '2026-11-25T10:00:00.000+09:00', plan: planJson('book-4vg1edpvi5', ['robot1'], ['targeted']) }),
  ], []);
  if (outbox.plan?.requestId === 'req-NEW') controls.push('outbox 로 늦게 쓰인 옛 planned 는 스트림 ID 가 늦어도 안 고른다');
  else failures.push(`대조군 실패: 스트림 ID 로 골라 옛 배치표(${outbox.plan?.requestId})를 냈다`);
  const wsl = s.nodes['book-4vg1edpvi5-wsl'];
  expect('노드 마지막 상태', wsl?.cpuPct === 12.5 && wsl.gpu[0]?.memUsedMb === 3100 && wsl.source === 'local' && wsl.atMs === 1764050540000, JSON.stringify(wsl));
  expect('baseline 은 옛 added 에서', wsl?.baseline?.cpuCount === 20 && wsl.baseline.gpus[0]?.name?.includes('4050') && wsl.baselineAtMs === 1764040000000, JSON.stringify(wsl?.baseline));
  expect('파이 노드 · 빈 온도', s.nodes.pi6?.role === 'sensor' && s.nodes.pi6.tempC === null && s.nodes.pi6.baseline === null, JSON.stringify(s.nodes.pi6));
  const broken = reader.summarizePlacement([orchRec('9-0', 'planned', 'req-X', { plan: '{not json' })], []);
  if (broken.plan === null) controls.push('깨진 plan JSON 은 배치표로 안 선다');
  else failures.push('대조군 실패: 깨진 plan 으로 배치표를 냈다');
  const none = reader.summarizePlacement([], []);
  expect('기록이 없으면 plan null', none.plan === null && Object.keys(none.nodes).length === 0);

  // 실제 실행 위치(261127) — 같은 요청의 GPU applied 의 detail.where. 기록의 mode(k3s)는 배치 계산 방식이라 따로 둔다
  const where = 'book-4vg1edpvi5 GPU (NVIDIA GeForce RTX 4050 Laptop GPU) — 이 기기 · WSL';
  const ran = reader.summarizePlacement([
    orchRec('1764050532000-0', 'applied', 'req-B', { mode: 'k3s', detail: JSON.stringify({ node: 'book-4vg1edpvi5', unit_id: 'gpu-1', where }) }),
    orchRec('1764050531500-0', 'applied', 'req-B', { mode: 'k3s', detail: JSON.stringify({ node: 'book-4vg1edpvi5', unit_id: 'cpu-x' }) }),
    orchRec('1764050530000-0', 'planned', 'req-B', { mode: 'k3s', plan: planJson('book-4vg1edpvi5', ['robot1'], ['targeted']) }),
    orchRec('1764040001000-0', 'applied', 'req-A', { detail: JSON.stringify({ node: 'pi6', unit_id: 'gpu-0', where: 'pi6 GPU' }) }),
  ], []);
  expect('실행 위치 — 같은 요청 GPU applied 의 where', ran.plan?.where?.['book-4vg1edpvi5'] === where && ran.plan.mode === 'k3s', JSON.stringify(ran.plan?.where));
  // 대조군 — 다른 요청의 applied 는 안 섞고, where 가 없는 applied(CPU 작업)는 덮지 않는다
  if (ran.plan?.where?.pi6 === undefined && Object.keys(ran.plan?.where ?? {}).length === 1) controls.push('다른 요청 · where 없는 applied 는 실행 위치에 안 섞인다');
  else failures.push(`대조군 실패: 실행 위치 ${JSON.stringify(ran.plan?.where)}`);
  expect('applied 전이면 실행 위치 없음', Object.keys(s.plan?.where ?? {}).length === 0, JSON.stringify(s.plan?.where));
}

// ── 3. 가짜 소켓 ────────────────────────────────────────────────────────────
const array = (items) => Buffer.concat([Buffer.from(`*${items.length}\r\n`), ...items.map(encodeItem)]);
function encodeItem(item) {
  if (Array.isArray(item)) return array(item);
  const b = Buffer.isBuffer(item) ? item : Buffer.from(String(item));
  return Buffer.concat([Buffer.from(`$${b.length}\r\n`), b, Buffer.from('\r\n')]);
}
{
  const sent = [];
  const connect = () => {
    const sock = new EventEmitter();
    sock.write = (b) => {
      const cmd = b.toString();
      sent.push(cmd);
      const body = cmd.includes('orchestration_stream') ? array(orchNewestFirst) : array(nodesNewestFirst);
      setImmediate(() => { sock.emit('data', body.subarray(0, 17)); sock.emit('data', body.subarray(17)); });
    };
    sock.destroy = () => {};
    setImmediate(() => sock.emit('connect'));
    return sock;
  };
  const got = await reader.readPlacement({ host: 'h', port: 1, reader: (opts) => reader.readRecent({ ...opts, connect }) });
  expect('가짜 소켓으로 요약', got.plan?.requestId === 'req-B' && got.nodes['book-4vg1edpvi5-wsl']?.baseline !== null, JSON.stringify(got.plan));
  expect('보낸 명령은 XREVRANGE 둘', sent.length === 2 && sent.every((c) => c.startsWith('*6\r\n$9\r\nXREVRANGE')) && sent.some((c) => c.includes('COUNT\r\n$3\r\n200')) && !sent.some((c) => /XADD|DEL|SET\r/.test(c)), JSON.stringify(sent));
  let refused = false;
  await reader.readRecent({ host: 'h', port: 1, key: 'vision_stream:robot1:targeted', count: 1, connect: () => { throw new Error('붙으면 안 된다'); } })
    .catch((error) => { refused = /읽을 수 없는 키/.test(error.message); });
  if (refused) controls.push('허용 목록 밖의 키는 보내지도 않는다');
  else failures.push('대조군 실패: 허용 목록 밖의 키를 읽으러 간다');
  const empty = await reader.readRecent({ host: 'h', port: 1, key: 'orchestration_stream', count: 5, connect: () => {
    const sock = new EventEmitter();
    sock.write = () => setImmediate(() => sock.emit('data', Buffer.from('*0\r\n')));
    sock.destroy = () => {};
    setImmediate(() => sock.emit('connect'));
    return sock;
  } });
  expect('키가 없으면 빈 목록', Array.isArray(empty) && empty.length === 0);
  // 중계 본체 — 갈아 끼운 placementReader 의 답을 그대로 JSON 으로
  const res = { headers: {}, setHeader(k, v) { this.headers[k] = v; }, end(body) { this.body = body; } };
  await relay.handleVisionStream({ url: `/vision-stream/placement?redis=${encodeURIComponent('redis://h:6380')}`, method: 'GET' }, res, () => failures.push('placement 를 다음 미들웨어로 넘긴다'),
    undefined, undefined, async ({ host, port }) => ({ plan: null, nodes: {}, host, port }));
  const body = JSON.parse(String(res.body));
  expect('중계가 요약을 옮긴다', res.statusCode === 200 && body.host === 'h' && body.port === 6380 && res.headers['X-Vision-Relay'] === '1', JSON.stringify(body));
}

// ── 4. 저장 · 갈아 끼우기 ──────────────────────────────────────────────────
const snapB = reader.summarizePlacement(orchNewestFirst, nodesNewestFirst);
const snapA = reader.summarizePlacement(orchNewestFirst.slice(4), []);
{
  const empty = { plan: null, nodes: {} };
  const first = place.mergePlacement(empty, snapB);
  expect('처음 받은 배치표를 쓴다', first.plan?.requestId === 'req-B' && first.planFrom === 'live');
  const trimmed = place.mergePlacement(first, { plan: null, nodes: { 'book-4vg1edpvi5-wsl': { ...snapB.nodes['book-4vg1edpvi5-wsl'], cpuPct: 80, baseline: null, baselineAtMs: null } } });
  expect('배치표가 밀려나도 저장본 유지', trimmed.plan?.requestId === 'req-B' && trimmed.planFrom === 'stored');
  expect('사용량은 새 값, baseline 은 저장본', trimmed.nodes['book-4vg1edpvi5-wsl'].cpuPct === 80 && trimmed.nodes['book-4vg1edpvi5-wsl'].baseline?.cpuCount === 20);
  expect('안 온 노드는 남긴다', trimmed.nodes.pi6?.role === 'sensor');
  const newer = reader.summarizePlacement([orchRec('1764060000000-0', 'planned', 'req-C', { plan: planJson('pi6', ['realsense'], ['yoloe']) })], []);
  const replaced = place.mergePlacement(trimmed, newer);
  expect('더 새 planned 면 통째로 교체', replaced.plan?.requestId === 'req-C' && replaced.plan.gpuUnits.every((u) => !u.sources.includes('robot1')), JSON.stringify(replaced.plan?.gpuUnits));
  const old = place.mergePlacement(replaced, snapA);
  if (old.plan?.requestId === 'req-C' && old.planFrom === 'stored') controls.push('옛 planned 가 새 배치표를 덮지 않는다');
  else failures.push(`대조군 실패: 옛 배치표(${old.plan?.requestId})가 새것을 덮었다`);
  const same = place.mergePlacement(first, { plan: { ...snapB.plan, last: { event: 'stopped', reason: '요청', ts: null, atMs: 1764050600000 } }, nodes: {} });
  expect('같은 배치표면 마지막 기록만 갱신', same.plan?.last?.event === 'stopped' && same.planFrom === 'live');

  // 검토 A — 배치표가 스트림에서 밀려난 뒤에 온 stopped 도 저장본에 이어 붙는다.
  const stoppedLater = place.mergePlacement(trimmed, { plan: null, nodes: {}, requests: { 'req-B': { event: 'stopped', reason: '오케스트레이터 끝남', ts: null, atMs: 1764050700000 } } });
  expect('밀려난 뒤의 stopped 를 따라간다', stoppedLater.plan?.requestId === 'req-B' && stoppedLater.plan.last?.event === 'stopped' && stoppedLater.planFrom === 'stored', JSON.stringify(stoppedLater.plan?.last));
  expect('끝난 배치표', place.planEnded(stoppedLater.plan) && !place.planEnded(first.plan));
  const ended = place.placementOf(stoppedLater, 'robot1', 'targeted');
  expect('끝난 배치표는 칩 판단에 안 쓴다 → data_stream 기기', ended.from === 'dataStream' && ended.kind === 'laptop' && ended.unit === null, JSON.stringify(ended));
  const olderLast = place.mergePlacement(stoppedLater, { plan: null, nodes: {}, requests: { 'req-B': { event: 'running', reason: null, ts: null, atMs: 1764050535000 } } });
  if (olderLast.plan?.last?.event === 'stopped') controls.push('옛 running 이 stopped 를 되돌리지 않는다');
  else failures.push('대조군 실패: 옛 기록이 끝남을 되돌렸다');
  const otherReq = place.mergePlacement(stoppedLater, { plan: null, nodes: {}, requests: { 'req-Z': { event: 'running', reason: null, ts: null, atMs: 1764050800000 } } });
  expect('다른 요청의 기록은 안 붙인다', otherReq.plan?.last?.event === 'stopped');
  // 새 실행 — 새 planned 가 오면 끝난 배치표 대신 다시 배치표를 쓴다.
  const rerun = place.mergePlacement(stoppedLater, reader.summarizePlacement([
    orchRec('1764050900000-0', 'running', 'req-D'),
    orchRec('1764050890000-0', 'planned', 'req-D', { plan: planJson('book-4vg1edpvi5-wsl', ['robot1'], ['targeted']) }),
  ], []));
  expect('새 실행이면 다시 배치표', rerun.plan?.requestId === 'req-D' && place.placementOf(rerun, 'robot1', 'targeted').from === 'plan');
  // outbox — 저장본이 새것이면, 스트림 ID 만 늦은 옛 planned 로 안 바뀐다.
  const prevNew = { plan: reader.summarizePlacement([orchRec('1764061000000-0', 'planned', 'req-NEW', { ts: '2026-11-25T10:00:00.000+09:00', plan: planJson('n', ['robot1'], ['targeted']) })], []).plan, nodes: {} };
  const gotOld = reader.summarizePlacement([orchRec('1764062000000-0', 'planned', 'req-OLD', { ts: '2026-11-25T09:00:00.000+09:00', plan: planJson('n', ['drone'], ['yoloe']) })], []);
  expect('저장본이 더 새것이면 그대로', place.mergePlacement(prevNew, gotOld).plan?.requestId === 'req-NEW');
}

// ── 5. (소스, 모델) → 장치 ─────────────────────────────────────────────────
{
  const p = place.placementOf(snapB, 'robot1', 'targeted');
  expect('배치표에 있으면 그 노드', p.from === 'plan' && p.node === 'book-4vg1edpvi5-wsl' && p.kind === 'laptop' && p.unit?.needMb === 1880, JSON.stringify(p));
  const ds = place.placementOf(snapB, 'drone', 'yoloe');
  expect('배치표에 없으면 data_stream 기기로 확정', ds.from === 'dataStream' && ds.node === 'book-4vg1edpvi5-wsl' && ds.kind === 'laptop' && ds.unit === null, JSON.stringify(ds));
  const noRecorder = place.placementOf({ plan: null, nodes: {} }, 'robot1', 'targeted');
  expect('자원 기록이 없어도 data_stream 기기', noRecorder.from === 'dataStream' && noRecorder.node === null && noRecorder.kind === 'laptop');
  const piSnap = { plan: reader.summarizePlacement([orchRec('2-0', 'planned', 'r', { plan: planJson('pi6', ['realsense'], ['yoloe']) })], []).plan, nodes: snapB.nodes };
  const pi = place.placementOf(piSnap, 'realsense', 'yoloe');
  expect('파이 노드는 이름', pi.kind === 'pi' && place.shortTag(pi) === 'pi6', `${pi.kind} ${place.shortTag(pi)}`);
  expect('노트북 꼬리표', place.shortTag(p) === '노트북' || place.shortTag(p) === 'laptop', place.shortTag(p));
  const longName = place.shortTag({ from: 'plan', node: 'worker-node-long', unit: null, info: null, kind: 'other' });
  expect('긴 이름은 자른다', longName.length <= 8 && longName.endsWith('…'), longName);
  expect('장치 수', place.countDevices([p, ds, pi]) === 2 && place.countDevices([noRecorder, noRecorder]) === 1);
}

// ── 6. 조회 한 번 ───────────────────────────────────────────────────────────
{
  let asked = '';
  place.resetPlacementStore(async (url) => { asked = url; return { ok: true, status: 200, json: async () => snapB }; });
  await place.pollPlacement(() => 42);
  const s = place.placementState();
  expect('창구를 부른다', asked.startsWith('/vision-stream/placement?redis=redis%3A%2F%2F'), asked);
  expect('받아 합친다', s.plan?.requestId === 'req-B' && s.planFrom === 'live' && s.receivedAtMs === 42 && s.error === null, JSON.stringify({ planFrom: s.planFrom, error: s.error }));
  place.resetPlacementStore(async () => ({ ok: false, status: 502, json: async () => ({ error: 'Redis 를 못 읽었습니다 — ECONNREFUSED' }) }));
  // localStorage 가 없는 node 라 저장본은 비어 시작한다 — 받은 값을 넣고 실패시킨다.
  await place.pollPlacement();
  expect('실패는 사유만', /ECONNREFUSED/.test(place.placementState().error ?? '') && place.placementState().plan === null);
  place.resetPlacementStore(async () => ({ ok: true, status: 200, json: async () => ({ nope: 1 }) }));
  await place.pollPlacement();
  expect('모양이 아닌 답', place.placementState().error !== null);
  place.resetPlacementStore(async () => { throw new Error('unused'); });
  // 검토 C — 저장본은 Redis 주소마다 따로.
  const a = place.storageKeyOf('redis://100.125.104.23:6380');
  const b = place.storageKeyOf('redis://10.0.0.5:6380');
  expect('저장 키가 Redis 주소마다 다르다', a !== b && a.startsWith(place.PLACEMENT_STORAGE_KEY) && a.endsWith('100.125.104.23:6380'), `${a} ${b}`);
}

// ── 7. CPU 작업 → 만드는 소스 카드 (261125 안 2) ────────────────────────────
// 실제 orchestration_stream(11-24 21:00, M8 시험 probe)의 순서를 그대로 옮기고 작업 이름만 cam360_slice 로 바꿨다.
{
  const cpuPlan = { algorithm: 'placement/1', gpu_units: [], refused: [], degraded: [],
    cpu_units: [{ task: 'cam360_slice', node: 'pi6', requests: { cpu_m: 200, mem_mb: 64 }, limits: { cpu_m: 400, mem_mb: 128 }, priority_class: 'ds-vision-low' }] };
  const iso = (s) => `2026-11-24T21:${s}+09:00`;
  const rec = (id, event, rid, ts, extra = {}) => orchRec(id, event, rid, { ts: iso(ts), ...extra });
  const seq = [
    rec('1795521644000-0', 'planned', 'req-P', '00:44.704', { plan: cpuPlan }),
    rec('1795521645000-0', 'applied', 'req-P', '00:45.055', { reason: 'CPU 작업 cam360_slice → pi6', detail: { node: 'pi6', unit_id: 'cpu-cam360_slice-fe58bf', requests: { cpu_m: 200, mem_mb: 64 }, limits: { cpu_m: 400, mem_mb: 128 } } }),
    rec('1795521652000-0', 'running', 'req-P', '00:52.331', { detail: { node: 'pi6', unit_id: 'cpu-cam360_slice-fe58bf' } }),
    rec('1795521697000-0', 'applied', 'req-P', '01:37.723', { detail: { node: 'pi13', unit_id: 'cpu-cam360_slice-c3d882' } }),
    rec('1795521697001-0', 'replanned', 'req-P', '01:37.723', { reason: '노드 pi6 빠짐 → pi6 에서 pi13 로', detail: { from: 'cpu-cam360_slice-fe58bf', from_node: 'pi6', to: 'cpu-cam360_slice-c3d882', to_node: 'pi13' } }),
    rec('1795521706000-0', 'running', 'req-P', '01:46.174', { detail: { node: 'pi13', unit_id: 'cpu-cam360_slice-c3d882' } }),
  ];
  const newestFirst = (list) => [...list].reverse();
  const nodes = [
    nodeRec('1795521700000-0', 'book-4vg1edpvi5'),
    nodeRec('1795521699000-0', 'pi13', { role: 'small', source: 'k3s', gpu: [] }),
    nodeRec('1795521698000-0', 'pi6', { role: 'sensor', source: 'k3s', gpu: [] }),
  ];
  expect('단위 id → 작업', reader.taskOfUnit('cpu-cam360_slice-c3d882') === 'cam360_slice' && reader.taskOfUnit('gpu-49fcb030') === null && reader.taskOfUnit('cpu-x') === null);

  const running = reader.summarizePlacement(newestFirst(seq), nodes);
  const task = running.cpuTasks.cam360_slice;
  expect('이동 뒤 지금 단위 · 노드', task?.node === 'pi13' && task.unitId === 'cpu-cam360_slice-c3d882' && task.state === 'running' && task.lost === false, JSON.stringify(task));
  expect('이동 기록 한 줄', task?.moves.length === 1 && task.moves[0].fromNode === 'pi6' && task.moves[0].toNode === 'pi13');
  expect('요청 · 상한', task?.requests?.cpuM === 200 && task.limits?.memMb === 128);

  // 판단 — 스트림이 말하는 노드(파이)
  let snap = place.mergePlacement({ plan: null, nodes: {} }, running);
  let p = place.cpuPlacementOf(snap, 'cam360_slice');
  expect('스트림 위치 → pi13', p?.from === 'stream' && p.node === 'pi13' && p.kind === 'pi' && place.cpuShortTag(p) === 'pi13', JSON.stringify(p && { from: p.from, node: p.node, kind: p.kind }));
  const movedAt = task.moves[0].tsMs;
  expect('옮긴 뒤 1분 안 「↪」', place.recentMove(p, movedAt + 30_000)?.fromNode === 'pi6' && place.recentMove(p, movedAt + 61_000) === null);
  expect('모델 소스 카드는 CPU 작업이 아님', place.cpuPlacementOf(snap, 'robot1') === null && place.cpuPlacementOf(snap, null) === null);

  // k3s 응답 없음 — 위치 그대로, 확인 불가
  const lost = reader.summarizePlacement(newestFirst([...seq, rec('1795521711000-0', 'degraded', 'req-P', '01:51.127', { reason: 'k3s 응답 없음' })]), nodes);
  expect('k3s 응답 없음 — 위치 그대로', lost.cpuTasks.cam360_slice?.node === 'pi13' && lost.cpuTasks.cam360_slice.lost === true);

  // 옛 단위의 끝 기록은 지금 단위를 닫지 않는다(대조군)
  const oldStop = reader.summarizePlacement(newestFirst([...seq, rec('1795521712000-0', 'stopped', 'req-P', '01:52.000', { detail: { unit_id: 'cpu-cam360_slice-fe58bf' } })]), nodes);
  if (oldStop.cpuTasks.cam360_slice?.state === 'running') controls.push('옮기기 전 단위의 stopped 는 지금 단위를 안 닫는다');
  else failures.push('대조군 실패: 옛 단위의 stopped 로 지금 작업을 닫았다');

  // 끝 — 서버 고정(data_stream 기기)으로 돌아가고 지난 기록은 남는다
  const stopped = reader.summarizePlacement(newestFirst([...seq, rec('1795521713000-0', 'stopped', 'req-P', '01:53.119', { reason: '시험 끝', detail: { unit_id: 'cpu-cam360_slice-c3d882' } })]), nodes);
  snap = place.mergePlacement(snap, stopped);
  p = place.cpuPlacementOf(snap, 'cam360_slice');
  expect('끝나면 data_stream 기기', p?.from === 'dataStream' && p.node === 'book-4vg1edpvi5' && p.kind === 'laptop' && p.ended?.state === 'stopped', JSON.stringify(p && { from: p.from, node: p.node }));

  // 밀려난 뒤 — 저장본 유지, 그 요청의 stopped 만 오면 끝(data_stream 기기에 둔 단위는 끝 기록이 없다)
  snap = place.mergePlacement({ plan: null, nodes: {} }, running);
  const trimmed = { plan: null, nodes: {}, cpuTasks: {}, requests: { 'req-P': { event: 'stopped', reason: '오케스트레이터 끝남', ts: iso('02:00.000'), tsMs: Date.parse(iso('02:00.000')), atMs: 1795521720000 } } };
  const kept = place.mergePlacement(snap, { plan: null, nodes: {} });
  expect('밀려나도 저장본 유지', kept.cpuTasks?.cam360_slice?.node === 'pi13');
  const closed = place.mergePlacement(snap, trimmed);
  expect('요청 stopped → 작업 끝', closed.cpuTasks?.cam360_slice?.state === 'stopped');

  // 기록이 하나도 없을 때(런처가 직접 띄움 — 지금 방식) — 서버 고정
  const none = place.cpuPlacementOf({ plan: null, nodes: snap.nodes }, 'cam360_slice');
  expect('기록 없음 → 서버 고정 노트북', none?.from === 'dataStream' && none.record === null && none.ended === null && none.kind === 'laptop' && place.cpuShortTag(none) === '노트북');
  // 레지스트리 목록에 없고 기록도 없는 소스는 CPU 작업으로 안 본다(대조군)
  if (place.cpuPlacementOf({ plan: null, nodes: snap.nodes }, 'drone') === null) controls.push('기록 · 목록에 없는 소스엔 「만드는 곳」을 안 붙인다');
  else failures.push('대조군 실패: 모델 소스에 만드는 곳을 붙였다');
}

if (failures.length > 0) {
  console.error(`❌ 모델 실행 장치 — ${failures.length}건\n  - ${failures.join('\n  - ')}`);
  process.exit(1);
}
console.log(`✅ 모델 실행 장치 — 창구 경로 · 스트림 요약(최근 planned · 노드 baseline) · XREVRANGE 둘 · 배치표 저장 · 교체 · data_stream 기기 확정 · 꼬리표 · 조회 · CPU 작업 만드는 곳(이동 · 끝 · 서버 고정) (대조군 ${controls.length}: ${controls.join(' · ')})`);
