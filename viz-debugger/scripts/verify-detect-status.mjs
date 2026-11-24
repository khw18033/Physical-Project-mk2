// verify:detect-status (261124 신설 — 객체 탐지 상태판, 「기능」 판 자리)
//
// **data_stream 을 고치지 않고 읽기만 해서 판이 맞게 서는가.**
//
// 보는 것 일곱.
//  1. `/health` 뜯기 — 스캔 창구가 끼워 넣은 빈 `targeted`(`{scan:{…}}`)를 모델로 세지 않고, 판 번호는 따로 든다
//  2. 카드 줄 — 상태 점 다섯 · 순서 · 머리 숫자 · 장비가 0대여도 카드가 선다 · 장비 묶음을 거꾸로 읽는다
//  3. Redis 창구 경로 — redis://host:port 만, 소스 · 모델은 이름표 모양만, 명령은 XREVRANGE 하나
//  4. RESP 뜯기 · 한 건 요약 — 그림(JPEG)은 버리고 대상 · 프로필 · 라벨 수만, 가짜 소켓으로 읽기 한 번
//  5. 지정 탐지 출처 넷 — 이 화면의 스캔 판 > 다른 화면의 판 > 런처 설정 > 못 읽음
//  6. 변경 기록 비교 — 모델 + · − · 다시 시작 · 대상 · 프로필 · 스캔 시작/끝 · 끊김/다시 연결, 끊긴 동안은 모델을 안 지운다
//  7. 기록은 임무 판이 돌 때만 — 판 폴더가 없으면 안 적고, 새 폴더면 「기록 시작」부터
//
// 대조군 — redis 가 아닌 주소 · 이름표가 아닌 키는 막혀야 하고, 대상을 못 읽은 순간은 「대상 바뀜」이 아니어야 한다.

import { EventEmitter } from 'node:events';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const failures = [];
const controls = [];
const expect = (what, ok, got = '') => { if (!ok) failures.push(`${what}${got === '' ? '' : ` — ${got}`}`); };

const client = await load('src', 'vision', 'visionClient.ts');
const summary = await load('src', 'detect', 'status', 'summary.ts');
const targets = await load('src', 'detect', 'status', 'targets.ts');
const history = await load('src', 'detect', 'status', 'history.ts');
const relay = await load('scripts', 'vision-stream-relay.mjs');
const redis = await load('scripts', 'vision-redis-latest.mjs');

/** data_stream a1e43f8 `/health` 모양 — targeted 가 안 돌 때도 스캔 창구가 `vision.targeted.scan` 을 끼워 넣는다. */
const health = (over = {}) => ({
  source: 'robot1', port: 10003, host: 'khw67', frames: 1520, states: 300,
  status: { video: '받는 중 http://100.72.109.9:8090/stream/1', state: '받는 중 mqtt://100.72.109.9:1883' },
  vision: { targeted: { scan: { busy_scan_id: null, devices: { 'go1-001': 'robot1' } } } },
  vision_error: null,
  ...over,
});

// ── 1. /health 뜯기 ─────────────────────────────────────────────────────────
{
  const idle = client.parseStreamHealth(health());
  expect('스캔 창구만 있는 targeted 를 모델로 센다', idle?.models.length === 0, JSON.stringify(idle?.models));
  expect('스캔 창구가 있으면 scan 이 선다', idle?.scan !== null && idle?.scan.busyScanId === null, JSON.stringify(idle?.scan));
  const live = client.parseStreamHealth(health({ vision: { targeted: { results: 40, n: 1519, run: 'r1', lag_ms: 210, infer_ms: 238, detections: 2, age_s: 0.3, scan: { busy_scan_id: 'abc' } }, yoloe: { results: 9, age_s: 1 } } }));
  expect('targeted 가 돌면 모델로 선다', live?.models.map((m) => m.model).join(',') === 'targeted,yoloe', JSON.stringify(live?.models.map((m) => m.model)));
  expect('판 번호를 든다', live?.scan?.busyScanId === 'abc');
  const old = client.parseStreamHealth(health({ vision: { yoloe: { results: 3, age_s: 1 } } }));
  if (old?.scan === null) controls.push('스캔 창구가 없는 옛 서버는 scan null');
  else failures.push('대조군 실패: 창구 없는 서버에 scan 을 지어낸다');
}

// ── 2. 카드 줄 ──────────────────────────────────────────────────────────────
const B = (port) => `http://100.125.104.23:${port}`;
const st = (body, extra = {}) => ({ health: body === null ? null : client.parseStreamHealth(body), receivedAtMs: 1000, error: null, via: 'relay', rate: {}, ...extra });
const sources = {
  [B(10003)]: st(health({ vision: { targeted: { results: 40, n: 1519, run: 'r1', lag_ms: 210, age_s: 0.3, scan: { busy_scan_id: null } } } }), { rate: { targeted: 3.9 }, sourceRate: { frames: 14.8, states: 1 } }),
  [B(10004)]: { health: null, receivedAtMs: null, error: '응답 없음', via: null, rate: {} },
  [B(10006)]: st(health({ source: 'cam360_slice', port: 10006, vision: {} }), { sourceRate: { frames: 4.8, states: 0 } }),
  [B(10001)]: st(health({ source: 'cam360', port: 10001, vision: {}, status: { video: '끊김 (timeout) — 다시 붙는 중', state: null } }), { sourceRate: { frames: 0, states: 0 } }),
  [B(10002)]: st(health({ source: 'drone', port: 10002, vision: { yoloe: { results: 9, age_s: 40 } } }), { sourceRate: { frames: 9, states: 4 } }),
};
{
  const bases = [B(10001), B(10002), B(10003), B(10004), B(10006), B(10008)];
  const devices = summary.devicesByBase({ 'go1-001': B(10003), 'go1-002': null });
  const { rows, totals } = summary.summarizeDetectSources(bases, sources, devices);
  const order = rows.map((row) => `${row.source ?? 'x'}:${row.state}`).join(' ');
  expect('순서 · 상태 점', order === 'robot1:models drone:raw cam360_slice:raw cam360:noVideo x:waiting x:down', order);
  expect('머리 숫자', totals.models === 1 && totals.connected === 4 && totals.down === 1 && totals.targeted === 1 && totals.ports === 6, JSON.stringify(totals));
  expect('장비를 거꾸로 묶는다', rows[0].devices.join(',') === 'go1-001' && rows[1].devices.length === 0);
  expect('40초 지난 모델은 살아 있지 않다', rows[1].live.length === 0);
  const none = summary.summarizeDetectSources(bases, sources, {});
  expect('장비가 0대여도 카드가 선다', none.rows.length === 6 && none.rows.every((row) => row.devices.length === 0));
  const first = summary.rowState(st(health({ vision: {} })));
  expect('처음 한 번(속도 모름)은 받은 장으로 원본을 본다', first === 'raw', first);
}

// ── 3. Redis 창구 경로 ──────────────────────────────────────────────────────
{
  const r = encodeURIComponent('redis://100.125.104.23:6380');
  const got = relay.visionRelayTarget(`/vision-stream/latest?redis=${r}&source=robot1&model=targeted`);
  expect('latest 가 키 하나로 간다', got?.kind === 'latest' && got.host === '100.125.104.23' && got.port === 6380 && got.key === 'vision_stream:robot1:targeted', JSON.stringify(got));
  let blocked = 0;
  for (const [url, why] of [
    [`/vision-stream/latest?redis=${encodeURIComponent('http://100.125.104.23:6380')}&source=robot1&model=targeted`, 'redis 가 아닌 주소'],
    [`/vision-stream/latest?redis=${encodeURIComponent('redis://h:6380/0')}&source=robot1&model=targeted`, '경로가 붙은 redis'],
    [`/vision-stream/latest?redis=${encodeURIComponent('redis://u:p@h:6380')}&source=robot1&model=targeted`, '계정이 붙은 redis'],
    [`/vision-stream/latest?redis=${r}&source=${encodeURIComponent('robot1:*')}&model=targeted`, '이름표가 아닌 소스'],
    [`/vision-stream/latest?redis=${r}&source=robot1&model=${encodeURIComponent('x y')}`, '이름표가 아닌 모델'],
  ]) {
    const res = relay.visionRelayTarget(url);
    if (res !== null && 'error' in res) blocked += 1; else failures.push(`대조군 실패: ${why} 를 받아 준다`);
  }
  if (blocked === 5) controls.push('redis 가 아닌 주소 · 이름표가 아닌 키');
}

// ── 4. RESP · 한 건 요약 · 가짜 소켓 ─────────────────────────────────────────
const resultJson = {
  model: 'targeted', stream: 'robot1', run: '20261124_140000', n: 41233, emitted_at: '2026-11-24T14:02:11.120+09:00',
  targets: ['door'], provisional: ['door'], distance: true,
  profile: { label: '스캔', version: 12, scan: '7f3c', mark: 3 },
  detections: [{ label: 'door', bbox: [1, 2, 3, 4] }, { label: 'chair', bbox: [1, 2, 3, 4] }, { label: 'door', bbox: [0, 0, 1, 1] }],
};
const jpeg = Buffer.from([0xff, 0xd8, 0x0d, 0x0a, 0x24, 0x2a, 0xff, 0xd9]); // \r\n · $ · * 가 섞인 그림 — 길이로 읽어야 한다
const bulk = (b) => Buffer.concat([Buffer.from(`$${b.length}\r\n`), b, Buffer.from('\r\n')]);
const reply = Buffer.concat([
  Buffer.from('*1\r\n*2\r\n'), bulk(Buffer.from('1764000131120-0')),
  Buffer.from('*6\r\n'), bulk(Buffer.from('result')), bulk(Buffer.from(JSON.stringify(resultJson))), bulk(Buffer.from('overlay')), bulk(jpeg),
  bulk(Buffer.from('header')), bulk(Buffer.from('{"lag_ms":210}')),
]);
{
  const cmd = redis.encodeCommand(['XREVRANGE', 'vision_stream:robot1:targeted', '+', '-', 'COUNT', '1']).toString();
  expect('명령은 RESP 배열', cmd.startsWith('*6\r\n$9\r\nXREVRANGE\r\n'), JSON.stringify(cmd.slice(0, 30)));
  expect('덜 온 답은 null', redis.parseResp(reply.subarray(0, reply.length - 3)) === null);
  const [value] = redis.parseResp(reply);
  const s = redis.summarizeVisionEntry(value[0]);
  expect('대상 · 프로필 · 라벨 수', s?.targets?.join() === 'door' && s.profile?.version === 12 && s.profile?.scanId === '7f3c' && s.labels?.door === 2 && s.labels?.chair === 1, JSON.stringify(s));
  expect('그림은 요약에 없다', !JSON.stringify(s).includes('overlay') && s.atMs === 1764000131120);
  const broken = redis.summarizeVisionEntry([Buffer.from('1-0'), [Buffer.from('result'), Buffer.from('{not json')]]);
  if (broken?.resultError !== null && broken?.targets === null) controls.push('JSON 이 아닌 result 는 대상을 지어내지 않는다');
  else failures.push('대조군 실패: 깨진 result 에서 대상을 냈다');

  // 가짜 소켓 — 보낸 명령이 XREVRANGE 하나인지, 답을 두 조각으로 받아도 읽는지
  const sent = [];
  const connect = () => {
    const sock = new EventEmitter();
    sock.write = (b) => { sent.push(b.toString()); setImmediate(() => { sock.emit('data', reply.subarray(0, 20)); sock.emit('data', reply.subarray(20)); }); };
    sock.destroy = () => {};
    setImmediate(() => sock.emit('connect'));
    return sock;
  };
  const read = await redis.readLatest({ host: 'h', port: 1, key: 'vision_stream:robot1:targeted', connect });
  expect('가짜 소켓으로 한 건', read?.targets?.join() === 'door', JSON.stringify(read));
  expect('보낸 명령은 XREVRANGE 하나', sent.length === 1 && sent[0].includes('XREVRANGE') && !/XADD|DEL|SET\r/.test(sent[0]));
  const emptyConnect = () => {
    const sock = new EventEmitter();
    sock.write = () => setImmediate(() => sock.emit('data', Buffer.from('*0\r\n')));
    sock.destroy = () => {};
    setImmediate(() => sock.emit('connect'));
    return sock;
  };
  const empty = await redis.readLatest({ host: 'h', port: 1, key: 'k', connect: emptyConnect });
  expect('빈 스트림은 empty', empty?.empty === true, JSON.stringify(empty));
}

// ── 5. 지정 탐지 출처 ───────────────────────────────────────────────────────
{
  const { rows } = summary.summarizeDetectSources([B(10003)], sources, {});
  const row = rows[0];
  const latest = { latest: { id: '1-0', atMs: 1, model: 'targeted', stream: 'robot1', run: 'r', n: 1, emittedAt: null, targets: ['person', 'chair'], provisional: [], distance: true, profile: { label: 'L', version: 7, scanId: null }, labels: { person: 1 }, resultError: null }, empty: false, error: null, receivedAtMs: 1 };
  const scan = { scanId: 's1', missionId: 'MSN-261123-01', device: 'go1-001', base: B(10003), target: 'door', query: null, queryKo: null, targets: ['demo_door'], stream: 'robot1', serverState: 'collecting', profileVersion: 12, angles: [{ captured: true }, { captured: true }, { captured: null }], headingStartDeg: null, headingEndDeg: null, result: null, failure: null, cancelled: false, recorded: null };
  const a = targets.targetInfo(row, scan, latest);
  expect('이 화면의 판이 이긴다', a?.source === 'mission' && a.targets.join() === 'demo_door' && a.angles.captured === 2 && a.profileVersion === 12, JSON.stringify(a));
  const busyRow = { ...row, busyScanId: 'other' };
  const b = targets.targetInfo(busyRow, null, latest);
  expect('남의 판 — 대상은 그 판 결과일 때만', b?.source === 'otherScan' && b.targets === null, JSON.stringify(b));
  const c = targets.targetInfo(row, null, latest);
  expect('런처 설정', c?.source === 'profile' && c.targets.join() === 'person,chair' && c.profileVersion === 7 && c.seen.person === 1, JSON.stringify(c));
  const d = targets.targetInfo(row, null, { latest: null, empty: false, error: 'Redis 를 못 읽었습니다', receivedAtMs: null });
  expect('못 읽음은 사유와 함께', d?.source === 'unknown' && d.why.includes('Redis'), JSON.stringify(d));
  const finished = targets.targetInfo(row, { ...scan, serverState: 'done' }, latest);
  expect('끝난 판은 이 화면의 판이 아니다', finished?.source === 'profile', finished?.source);
  const noTargeted = targets.targetInfo({ ...row, live: [] }, scan, latest);
  expect('targeted 가 안 돌면 null', noTargeted === null);
}

// ── 6. 변경 기록 비교 ───────────────────────────────────────────────────────
{
  const snap = (over = {}) => ({ source: 'robot1', reachable: true, downSinceMs: null, models: { targeted: { run: 'r1', results: 10 } }, targets: ['person'], profileVersion: 7, scanId: null, ...over });
  const kinds = (prev, next) => history.diffDetectSnapshot({ b: prev }, { b: next }, 5000).map((e) => e.kind).join(',');
  expect('모델 +', kinds(snap(), snap({ models: { targeted: { run: 'r1', results: 11 }, yoloe: { run: 'r1', results: 1 } } })) === 'modelUp');
  expect('모델 −', kinds(snap(), snap({ models: {} })) === 'modelDown');
  expect('다시 시작(run)', kinds(snap(), snap({ models: { targeted: { run: 'r2', results: 1 } } })) === 'modelRestart');
  expect('다시 시작(누계 줄어듦)', kinds(snap(), snap({ models: { targeted: { run: 'r1', results: 3 } } })) === 'modelRestart');
  expect('대상 바뀜', kinds(snap(), snap({ targets: ['door'], profileVersion: 8 })) === 'targets');
  expect('프로필만', kinds(snap(), snap({ profileVersion: 8 })) === 'profile');
  expect('스캔 시작 · 끝', kinds(snap(), snap({ scanId: 'x' })) === 'scanStart' && kinds(snap({ scanId: 'x' }), snap()) === 'scanEnd');
  expect('끊김', kinds(snap(), snap({ reachable: false, downSinceMs: 5000 })) === 'down');
  const up = history.diffDetectSnapshot({ b: snap({ reachable: false, downSinceMs: 1000 }) }, { b: snap() }, 43000);
  expect('다시 연결 + 끊긴 길이', up.length === 1 && up[0].kind === 'up' && up[0].downMs === 42000, JSON.stringify(up));
  expect('같으면 사건 없음', kinds(snap(), snap({ models: { targeted: { run: 'r1', results: 99 } } })) === '');

  // 끊긴 동안 모델을 안 지운다 — snapshotOf 가 앞 값을 든다
  const { rows } = summary.summarizeDetectSources([B(10003)], sources, {});
  const s1 = history.snapshotOf(rows, { [B(10003)]: { targets: ['person'], profileVersion: 7 } }, {}, 1000);
  const downRows = summary.summarizeDetectSources([B(10003)], { [B(10003)]: { ...sources[B(10003)], error: 'x' } }, {}).rows;
  const s2 = history.snapshotOf(downRows, {}, s1, 2000);
  const s3 = history.snapshotOf(rows, { [B(10003)]: { targets: ['person'], profileVersion: 7 } }, s2, 9000);
  const seq = [...history.diffDetectSnapshot(s1, s2, 2000), ...history.diffDetectSnapshot(s2, s3, 9000)].map((e) => e.kind).join(',');
  expect('끊김 → 다시 연결 사이에 모델 −/+ 가 없다', seq === 'down,up', seq);
  // 대조군 — 대상을 못 읽은 순간(targets null)은 앞 값을 든다
  const s4 = history.snapshotOf(rows, { [B(10003)]: { targets: null, profileVersion: null } }, s3, 10000);
  if (history.diffDetectSnapshot(s3, s4, 10000).length === 0) controls.push('대상을 못 읽은 순간은 「대상 바뀜」이 아니다');
  else failures.push('대조군 실패: 읽기 실패를 대상 바뀜으로 적었다');
}

// ── 7. 임무 판이 돌 때만 ────────────────────────────────────────────────────
{
  history.resetDetectHistory();
  const { rows } = summary.summarizeDetectSources([B(10003)], sources, {});
  const tg = { [B(10003)]: { targets: ['person'], profileVersion: 7 } };
  history.noteDetectRows(rows, tg, null, 1000);
  expect('임무 없으면 안 적는다', history.detectHistory().events.length === 0 && !history.detectHistory().recording);
  history.noteDetectRows(rows, tg, '2026-11-24/140000_MSN', 2000);
  const started = history.detectHistory();
  expect('새 판 폴더면 기록 시작 줄', started.recording && started.events.length === 1 && started.events[0].kind === 'start' && started.events[0].after === 'targeted', JSON.stringify(started.events));
  history.noteDetectRows(rows, { [B(10003)]: { targets: ['door'], profileVersion: 8 } }, '2026-11-24/140000_MSN', 3000);
  expect('판 안의 변화는 쌓인다', history.detectHistory().events.map((e) => e.kind).join(',') === 'start,targets');
  expect('판 기록에 실린다', history.recordableDetectHistory()?.length === 2);
  history.noteDetectRows(rows, tg, '2026-11-24/141500_MSN', 4000);
  expect('다른 판 폴더면 새로 시작', history.detectHistory().events.length === 1);
  history.restoreDetectHistory([{ atMs: 1, base: 'b', source: 'robot1', kind: 'modelUp', model: 'yoloe' }, { bad: true }], { date: '2026-11-24', run: '140000' });
  expect('기록에서 열면 모양 맞는 것만', history.detectHistory().events.length === 1 && history.detectHistory().recorded !== null && history.recordableDetectHistory() === null);
  history.noteDetectRows(rows, tg, null, 5000);
  expect('다시보기에서 돌아오면 비운다', history.detectHistory().events.length === 0 && history.detectHistory().recorded === null);
}

if (failures.length > 0) {
  console.error(`❌ 객체 탐지 상태판 — ${failures.length}건\n  - ${failures.join('\n  - ')}`);
  process.exit(1);
}
console.log(`✅ 객체 탐지 상태판 — /health 뜯기(빈 targeted · 판 번호) · 카드 줄 · Redis 창구 경로 · RESP 요약 · 지정 탐지 출처 넷 · 변경 기록 비교 · 임무 판일 때만 (대조군 ${controls.length}: ${controls.join(' · ')})`);
