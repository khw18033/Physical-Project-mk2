// verify:history-server (261119 신설 — 임무 이력을 서버 DB 와 잇는다)
//
// **어느 장치에서든 모든 판을 본다.** 서버 담당의 임무 이력 서버(규약 documents/협의/임무이력서버_요청_VZ_261119.md)가
// 오기 전에, 가시화 쪽이 할 일이 다 됐는지를 가짜 서버(`history-server-mock.mjs`)로 본다. 막으려는 실패:
//
//  1. 가짜 서버가 규약과 다른 것 — 적합성 검사(`check-history-server.mjs`)가 가짜 서버에서 다 통과해야 한다.
//     서버 담당은 같은 검사를 자기 서버에 돌린다. 둘이 같은 잣대다.
//  2. 아무 서버나 「연결됨」 — health 의 service 를 안 보면 탐지 서버 주소를 넣어도 붙은 것으로 뜬다.
//  3. 서버가 붙었는데 기록이 서버로 안 가는 것 · 끊긴 동안의 기록이 사라지는 것.
//  4. 다른 장치가 쓴 판이 목록에 안 뜨는 것 · 그 판을 다시보기로 못 여는 것.
//  5. 이 PC 창구가 없는 화면(단독 빌드 · 다른 장치)에서 서버가 있어도 기록기가 「창구 없음」으로 멈추는 것.
//  6. 서버를 안 쓰면 지금과 달라지는 것 — 이 PC 창구 404 는 여전히 404 로 던져야 기록기가 멈춘다.
//  7. 이 PC 파일을 서버로 올리는 길이 없는 것.
// 대조군 포함.

import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const failures = [];
const controls = [];
const passed = [];
const expect = (name, ok, detail = '') => { if (ok) passed.push(name); else failures.push(`${name}${detail === '' ? '' : ` — ${detail}`}`); };

// localStorage — 브라우저처럼. 모듈을 읽기 전에 깐다(주소를 읽는 것이 모듈 첫 줄이다).
const memory = new Map();
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: { getItem: (k) => memory.get(k) ?? null, setItem: (k, v) => memory.set(k, String(v)), removeItem: (k) => memory.delete(k) },
});

const listen = (handler) => new Promise((done) => {
  const server = createServer(handler);
  server.listen(0, '127.0.0.1', () => done({ server, origin: `http://127.0.0.1:${server.address().port}` }));
});
const close = (server) => new Promise((done) => { server.closeAllConnections?.(); server.close(() => done()); });

// ── 가짜 서버 · 이 PC 창구 ─────────────────────────────────────────────────────
const { historyServerHandler } = await import(pathToFileURL(join(root, 'scripts', 'history-server-mock.mjs')).href);
const { missionRecordsMiddleware } = await import(pathToFileURL(join(root, 'scripts', 'mission-records.mjs')).href);
const serverDir = mkdtempSync(join(tmpdir(), 'history-server-'));
const localDir = mkdtempSync(join(tmpdir(), 'history-local-'));
let serverDown = false;
const mockHandler = historyServerHandler(serverDir);
const mock = await listen((req, res) => { if (serverDown) { res.socket?.destroy(); return; } mockHandler(req, res); });
let localGone = false;
const localMiddleware = missionRecordsMiddleware(localDir);
const local = await listen((req, res) => {
  if (localGone) { res.statusCode = 404; res.end('no endpoint'); return; }
  localMiddleware(req, res, () => { res.statusCode = 404; res.end('next'); });
});
// 답은 주지만 임무 이력 서버가 아닌 것 (지표 서버 따위).
const other = await listen((req, res) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ ok: true, service: 'metrics' })); });
const closedPort = await listen(() => {});
await close(closedPort.server);

// 브라우저의 상대 주소 → 이 PC 창구.
const realFetch = globalThis.fetch;
// 자식 프로세스는 비동기로 — 가짜 서버가 이 프로세스 안에 있어 동기로 기다리면 서로 막힌다.
const run = promisify(execFile);
const runNode = async (...args) => {
  try { return { ok: true, out: (await run(process.execPath, args, { encoding: 'utf8' })).stdout }; }
  catch (error) { return { ok: false, out: String(error.stdout ?? error) }; }
};
globalThis.fetch = (url, init) => realFetch(String(url).startsWith('/') ? `${local.origin}${url}` : url, init);

const hs = await load('src', 'record', 'historyServer.ts');
const rc = await load('src', 'record', 'recordClient.ts');
const waitFor = async (what, until, ms = 3000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (until()) return true; await new Promise((r) => setTimeout(r, 20)); }
  return false;
};
const serverFile = (...p) => join(serverDir, ...p);
const localFile = (...p) => join(localDir, ...p);
const mission = (id, extra = {}) => JSON.stringify({
  schema: 'mission-record/2', missionId: id, label: id, startedAtIso: '2026-11-19T01:00:00Z', updatedAtIso: '2026-11-19T01:00:00Z',
  endedAtIso: null, outcome: null, done: 0, of: 3, failedTaskId: null, reason: '', headSec: 1, robotDriven: false, testMode: true,
  imageCount: 0, path: null, pathFailure: null, view: { missionId: id, label: id, tasks: [], milestones: [] }, ...extra,
});

try {
  // ── 1. 적합성 검사가 가짜 서버에서 다 통과한다 ─────────────────────────────
  {
    const { ok, out } = await runNode(join(root, 'scripts', 'check-history-server.mjs'), mock.origin);
    expect('적합성 검사가 가짜 서버에서 전부 통과', ok && /(\d+)\/\1 통과/.test(out), out.split('\n').filter((l) => l.startsWith('FAIL')).join(' | '));
  }

  // ── 2. 주소 고르기 ─────────────────────────────────────────────────────────
  {
    const n = hs.normalizeServerAddress;
    expect('주소: 앞에 http:// 를 붙인다', n('100.64.0.5:8790') === 'http://100.64.0.5:8790');
    expect('주소: 끝 / 와 /api/v1 를 뗀다', n(' http://host:8790/api/v1/ ') === 'http://host:8790');
    expect('주소: 빈 글자는 해제', n('   ') === '');
    expect('주소: 틀 밖은 null', n('ftp://x') === null && n('http://') === null && n('http://h:1/?q=1') === null);
  }

  // ── 3. 서버를 안 쓰면 지금과 같다 ───────────────────────────────────────────
  {
    hs.resetHistoryServerForTest();
    expect('처음엔 미설정', hs.historyServerStatus().state === 'unset');
    await rc.putRecordJson('261119', '100000_MSN-A', 'mission.json', mission('MSN-A'));
    expect('미설정이면 이 PC 에만 쓴다', existsSync(localFile('261119', '100000_MSN-A', 'mission.json')) && !existsSync(serverFile('261119')));
    const list = await rc.listRecordedRuns();
    expect('미설정이면 목록은 이 PC 것 · 서버는 off', list?.server === 'off' && list.runs.length === 1);
    localGone = true;
    let thrown = '';
    try { await rc.putRecordJson('261119', '100001_MSN-A', 'mission.json', mission('MSN-A')); } catch (error) { thrown = error.message; }
    expect('미설정 + 이 PC 창구 없음 → 여전히 404 로 던진다 (기록기가 멈추는 규칙)', / 404$/.test(thrown), thrown);
    localGone = false;
  }

  // ── 4. 연결 상태 넷을 가른다 ───────────────────────────────────────────────
  {
    hs.setHistoryServerAddress(closedPort.origin);
    await hs.checkHistoryServer();
    expect('닫힌 포트 → 닿지 않음', hs.historyServerStatus().state === 'unreachable', hs.historyServerStatus().state);
    hs.setHistoryServerAddress(other.origin);
    await hs.checkHistoryServer();
    expect('다른 서버(200 · service 다름) → 임무 이력 서버 아님', hs.historyServerStatus().state === 'wrong-service', hs.historyServerStatus().state);
    hs.setHistoryServerAddress(local.origin);
    await hs.checkHistoryServer();
    expect('health 가 404 → 서버 오류', hs.historyServerStatus().state === 'http-error', hs.historyServerStatus().state);
    hs.setHistoryServerAddress(mock.origin.replace('http://', ''));
    await hs.checkHistoryServer();
    const s = hs.historyServerStatus();
    expect('가짜 서버 → 연결됨 (주소에 http:// 붙여 저장)', s.state === 'connected' && s.address === mock.origin && s.latencyMs !== null, `${s.state} ${s.address}`);
    expect('주소가 localStorage 에 남는다', memory.get('viz.historyServer.v1') === mock.origin);
    hs.resetHistoryServerForTest();
    expect('새로고침해도 주소가 돌아온다', hs.historyServerStatus().address === mock.origin && hs.historyServerStatus().state === 'checking');
    await hs.checkHistoryServer();
  }

  // ── 5. 붙어 있으면 두 곳에 쓴다 ────────────────────────────────────────────
  {
    await rc.putRecordJson('261119', '110000_MSN-B', 'progress.json', '{"trace":[]}');
    await rc.putRecordJson('261119', '110000_MSN-B', 'mission.json', mission('MSN-B'));
    await rc.postRecordImage('261119', '110000_MSN-B', 'images/detect/frame_1_original.jpg', new Uint8Array([0xff, 0xd8, 1, 2, 0xff, 0xd9]));
    await waitFor('drain', () => hs.historyServerStatus().pending === 0);
    expect('mission · progress · 그림이 서버에도 있다',
      existsSync(serverFile('261119', '110000_MSN-B', 'mission.json')) && existsSync(serverFile('261119', '110000_MSN-B', 'progress.json'))
      && existsSync(serverFile('261119', '110000_MSN-B', 'images', 'detect', 'frame_1_original.jpg')));
    expect('이 PC 에도 있다', existsSync(localFile('261119', '110000_MSN-B', 'mission.json')));
  }

  // ── 6. 끊긴 동안의 기록은 줄에 남았다가 다시 붙으면 간다 ──────────────────────
  {
    serverDown = true;
    await hs.checkHistoryServer();
    expect('서버가 죽으면 닿지 않음', hs.historyServerStatus().state === 'unreachable');
    await rc.putRecordJson('261119', '120000_MSN-C', 'mission.json', mission('MSN-C', { done: 1 }));
    await rc.putRecordJson('261119', '120000_MSN-C', 'mission.json', mission('MSN-C', { done: 2 }));
    expect('끊겨도 이 PC 에는 쓴다', JSON.parse(readFileSync(localFile('261119', '120000_MSN-C', 'mission.json'), 'utf8')).done === 2);
    expect('못 보낸 것이 줄에 하나 (같은 파일은 새 것만)', hs.historyServerStatus().pending === 1, String(hs.historyServerStatus().pending));
    serverDown = false;
    await hs.checkHistoryServer();
    await waitFor('drain', () => hs.historyServerStatus().pending === 0);
    const sent = existsSync(serverFile('261119', '120000_MSN-C', 'mission.json'))
      ? JSON.parse(readFileSync(serverFile('261119', '120000_MSN-C', 'mission.json'), 'utf8')).done : null;
    expect('다시 붙으면 마지막 본문이 서버로 간다', sent === 2, `server done=${sent}`);
  }

  // ── 7. 목록 합치기 · 다른 장치의 판 · 검사 판 숨김 ─────────────────────────────
  {
    // 다른 장치가 쓴 판 — 서버에만.
    mkdirSync(serverFile('261118', '090000_MSN-OTHER', 'images', 'detect'), { recursive: true });
    writeFileSync(serverFile('261118', '090000_MSN-OTHER', 'mission.json'), mission('MSN-OTHER'));
    writeFileSync(serverFile('261118', '090000_MSN-OTHER', 'progress.json'), '{"trace":[{"seq":1}]}');
    // 서버 없을 때 이 PC 에만 쓰인 판.
    mkdirSync(localFile('261117', '080000_MSN-LOCAL'), { recursive: true });
    writeFileSync(localFile('261117', '080000_MSN-LOCAL', 'mission.json'), mission('MSN-LOCAL'));
    // 적합성 검사가 남긴 판 (1단계에서 이미 서버에 있다).
    const list = await rc.listRecordedRuns();
    const keyOf = (r) => `${r.date}/${r.run}`;
    const find = (key) => list?.runs.find((r) => keyOf(r) === key);
    expect('서버가 붙으면 목록에 서버 판이 합쳐진다', list?.server === 'ok' && find('261118/090000_MSN-OTHER')?.where?.server === true && find('261118/090000_MSN-OTHER')?.where?.local === false);
    expect('이 PC에만 있는 판을 가른다', find('261117/080000_MSN-LOCAL')?.where?.server === false && list?.localOnly === 2,
      `localOnly=${list?.localOnly}`); // MSN-A(서버 붙기 전) · MSN-LOCAL
    expect('양쪽에 있는 판은 한 줄', list?.runs.filter((r) => r.run === '110000_MSN-B').length === 1 && find('261119/110000_MSN-B')?.where?.local === true && find('261119/110000_MSN-B')?.where?.server === true);
    expect('적합성 검사 판(000101)은 숨긴다', list !== null && !list.runs.some((r) => r.date === '000101'));
    expect('최근 것이 먼저', list !== null && list.runs.map(keyOf).join() === [...list.runs.map(keyOf)].sort().reverse().join());
    expect('서버에만 있는 판의 그림 주소는 서버', rc.recordFileUrl('261118', '090000_MSN-OTHER', 'images/detect/a.jpg').startsWith(`${mock.origin}/api/v1/files/`));
    expect('이 PC 에 있는 판의 그림 주소는 이 PC', rc.recordFileUrl('261119', '110000_MSN-B', 'images/detect/a.jpg').startsWith('/mission-records/files/'));
    const progress = await rc.fetchRecordJson('261118', '090000_MSN-OTHER', 'progress.json');
    expect('다른 장치의 판을 다시보기로 읽는다', progress?.trace?.[0]?.seq === 1);
  }

  // ── 8. 이 PC 창구가 없는 화면 (단독 빌드 · 다른 장치) ─────────────────────────
  {
    localGone = true;
    let error = null;
    try { await rc.putRecordJson('261119', '130000_MSN-D', 'mission.json', mission('MSN-D')); } catch (e) { error = e; }
    expect('이 PC 창구가 없어도 서버가 받으면 성공', error === null && existsSync(serverFile('261119', '130000_MSN-D', 'mission.json')), String(error?.message));
    const list = await rc.listRecordedRuns();
    expect('이 PC 창구가 없어도 서버 목록을 보여 준다', list !== null && list.local === false && list.runs.some((r) => r.run === '130000_MSN-D'));
    const read = await rc.fetchRecordJson('261119', '110000_MSN-B', 'mission.json').catch(() => null);
    expect('이 PC 에서 못 읽으면 서버에서 읽는다', read?.missionId === 'MSN-B');
    serverDown = true;
    await hs.checkHistoryServer();
    let thrown = '';
    try { await rc.putRecordJson('261119', '130001_MSN-D', 'mission.json', mission('MSN-D')); } catch (e) { thrown = e.message; }
    expect('둘 다 없으면 던지되 404 꼴이 아니다 (기록기가 멈추지 않고 다시 쓴다)', thrown !== '' && !/ 404$/.test(thrown), thrown);
    serverDown = false;
    localGone = false;
    await hs.checkHistoryServer();
    await waitFor('drain', () => hs.historyServerStatus().pending === 0);
  }

  // ── 9. 서버가 거절하면 버리고 사유를 남긴다 ─────────────────────────────────
  {
    const ok = await hs.sendToHistoryServer('/runs/bad/x/mission.json', 'PUT', 'application/json', '{}');
    expect('4xx 는 다시 안 보낸다', ok === false && hs.historyServerStatus().pending === 0 && /HTTP 400/.test(hs.historyServerStatus().lastRejected ?? ''), hs.historyServerStatus().lastRejected ?? '');
  }

  // ── 10. 이 PC 파일을 서버로 올린다 ──────────────────────────────────────────
  {
    const { out } = await runNode(join(root, 'scripts', 'push-history-to-server.mjs'), mock.origin, '--dir', localDir);
    expect('history:push 가 서버에 없는 판을 올린다', existsSync(serverFile('261117', '080000_MSN-LOCAL', 'mission.json')) && /올림 2\/2판/.test(out), out.trim().split('\n').at(-1));
    const list = await rc.listRecordedRuns();
    expect('올린 뒤엔 이 PC만 판이 없다', list?.localOnly === 0, String(list?.localOnly));
  }

  // ── 11. 화면 · 연결 ─────────────────────────────────────────────────────────
  {
    const view = readFileSync(join(root, 'src', 'views', 'MissionHistory.tsx'), 'utf8');
    const bar = readFileSync(join(root, 'src', 'views', 'HistoryServerBar.tsx'), 'utf8');
    const main = readFileSync(join(root, 'src', 'main.tsx'), 'utf8');
    const conns = readFileSync(join(root, 'src', 'shared', 'connections.ts'), 'utf8');
    const ko = (await load('src', 'i18n', 'ko.ts')).ko;
    const en = (await load('src', 'i18n', 'en.ts')).en;
    expect('서버 칸이 임무 이력 목록 맨 위', /<div className="history-list">\s*<HistoryServerBar \/>/.test(view));
    expect('서버 주소는 연결 관리 목록에 없다', !/history-server|historyServer/.test(conns));
    expect('앱이 켜질 때 서버 확인을 건다', /startHistoryServerWatch\(\)/.test(main));
    const keys = [...bar.matchAll(/t\('(hsrv\.[^']+)'/g), ...view.matchAll(/t\('(hsrv\.[^']+)'/g)].map((m) => m[1]);
    const missing = keys.filter((k) => ko[k] === undefined || en[k] === undefined);
    expect('화면이 쓰는 hsrv 키가 두 사전에 다 있다', keys.length > 10 && missing.length === 0, missing.join(', '));
  }

  // ── 대조군 ─────────────────────────────────────────────────────────────────
  {
    // 200 이면 붙은 것으로 치는 사본 — 다른 서버를 「연결됨」으로 띄운다.
    const naive = (await realFetch(`${other.origin}/api/v1/health`)).ok;
    hs.setHistoryServerAddress(other.origin);
    await hs.checkHistoryServer();
    control('200 만 보고 연결됨으로 치는 사본', naive && hs.historyServerStatus().state !== 'connected');
    // 끊긴 동안 쓴 것을 줄 없이 버리는 사본 — 서버에 안 남는다.
    hs.setHistoryServerAddress(mock.origin);
    await hs.checkHistoryServer();
    serverDown = true;
    await hs.checkHistoryServer();
    await realFetch(`${local.origin}/mission-records/api/runs/261119/140000_MSN-E/mission.json`, { method: 'PUT', body: mission('MSN-E') }); // 줄 없는 사본: 이 PC 에만
    await rc.putRecordJson('261119', '140001_MSN-E', 'mission.json', mission('MSN-E'));                                                      // 우리: 줄에 남긴다
    serverDown = false;
    await hs.checkHistoryServer();
    await waitFor('drain', () => hs.historyServerStatus().pending === 0);
    control('끊긴 동안의 기록을 버리는 사본', !existsSync(serverFile('261119', '140000_MSN-E', 'mission.json')) && existsSync(serverFile('261119', '140001_MSN-E', 'mission.json')));
  }
} finally {
  await Promise.all([close(mock.server), close(local.server), close(other.server)]);
}

function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}

if (failures.length) {
  console.error(`❌ verify:history-server\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 가짜 서버가 적합성 검사를 전부 통과한다 — 서버 담당이 같은 검사를 돌린다`);
console.log(`✅ 연결 상태 넷(미설정 · 닿지 않음 · 다른 서버 · 오류)을 가르고, 주소는 새로고침에 남는다`);
console.log(`✅ 붙어 있으면 두 곳에 쓰고, 끊긴 동안 것은 줄에 남겼다가 다시 붙으면 마지막 본문을 보낸다`);
console.log(`✅ 목록은 서버 판과 이 PC 판을 합치고(이 PC만 딱지 · 검사 판 숨김), 다른 장치의 판을 다시보기로 연다`);
console.log(`✅ 이 PC 창구가 없는 화면에서도 서버로 쓰고 읽는다 · 서버를 안 쓰면 지금 규칙 그대로`);
console.log(`✅ history:push 가 이 PC 파일을 서버로 채운다 — 확인 ${passed.length}건`);
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
