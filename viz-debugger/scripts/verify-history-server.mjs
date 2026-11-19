// verify:history-server (261119 신설 · 같은 날 2차로 다시 씀 — 임무 이력을 서버 DB 와 잇는다)
//
// **서버가 기본 저장처, 이 PC 는 대피처, 목록은 한 출처.** 계획서
// documents/작업프롬프트/작업프롬프트_임무이력서버연동_개발계획_261119.md §8 의 항목을 실제 기록기로 본다.
// 서버는 가짜(`history-server-mock.mjs`), 이 PC 창구는 임시 폴더에 띄운다. 막으려는 실패:
//
//  1. 가짜 서버가 규약과 다른 것 — 적합성 검사가 가짜 서버에서 다 통과해야 한다(서버 담당과 같은 잣대).
//  2. 아무 서버나 「연결됨」 · 흔들리는 서버에 바로 다시 쓰는 것 — 쓰기 실패면 곧바로 불안정, health 2연속이어야 복귀.
//  3. 서버가 붙었는데 이 PC 에도 쓰는 것 · 끊겼는데 기록이 안 남는 것.
//  4. 판 하나가 서버와 이 PC 에 나뉘는 것 — 실패한 판은 끝까지 이 PC 이고, 서버로 보냈던 그림도 이 PC 에 다시 쓴다.
//  5. 대피 판이 서버로 안 올라가는 것 · 도는 중에 올라가 반쪽이 되는 것 · 새로고침에 대피 목록이 사라지는 것.
//  6. 서버가 답하는데 이 PC 판이 목록에 섞이는 것.
//  7. 서버를 안 쓰면 예전과 달라지는 것 — 이 PC 창구 404 는 여전히 기록기를 멈춘다.
// 대조군 포함.

import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const failures = [];
const controls = [];
const passed = [];
const expect = (name, ok, detail = '') => { if (ok) passed.push(name); else failures.push(`${name}${detail === '' ? '' : ` — ${detail}`}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// localStorage — 브라우저처럼. 모듈을 읽기 전에 깐다(주소 · 대피 목록을 읽는 것이 모듈 첫 줄이다).
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
const other = await listen((req, res) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify({ ok: true, service: 'metrics' })); });
const closedPort = await listen(() => {});
await close(closedPort.server);

// 브라우저의 상대 주소 → 이 PC 창구.
const realFetch = globalThis.fetch;
globalThis.fetch = (url, init) => realFetch(String(url).startsWith('/') ? `${local.origin}${url}` : url, init);
const run = promisify(execFile);
const runNode = async (...args) => {
  try { return { ok: true, out: (await run(process.execPath, args, { encoding: 'utf8' })).stdout }; }
  catch (error) { return { ok: false, out: String(error.stdout ?? error) }; }
};

const hs = await load('src', 'record', 'historyServer.ts');
// 모듈을 처음 읽은 순간의 주소 — 저장소가 비어 있으니 기본 주소여야 한다(261119 TDZ 실측: 상수가 아래 있어 비었다).
const firstLoadAddress = hs.historyServerStatus().address;
const rc = await load('src', 'record', 'recordClient.ts');
const ev = await load('src', 'record', 'evacuations.ts');
const up = await load('src', 'record', 'historyUpload.ts');
const recorder = await load('src', 'record', 'recorder.ts');
const scenario = await load('src', 'data', 'scenario.ts');
const history = await load('src', 'data', 'missionHistory.ts');
const session = await load('src', 'physical', 'robotSession.ts');

const runsIn = (dir) => existsSync(dir) ? readdirSync(dir).filter((d) => /^\d{6}$/.test(d)).flatMap((d) => readdirSync(join(dir, d)).map((r) => `${d}/${r}`)) : [];
const readJson = (dir, key, file) => JSON.parse(readFileSync(join(dir, key, file), 'utf8'));
const has = (dir, key, file) => existsSync(join(dir, key, file));
const MISSION = 'MSN-260909-01';
const jpeg = readFileSync(join(root, '..', 'door_example', 'test', 'door', 'frame_000001', 'original.jpg'));
let seq = 4_000_000;
const progressEvent = (status = 'running') => ({ seq: ++seq, atSec: seq % 100, nodeId: 'T-A3', status, kind: 'robot_progress', producedBy: 'backend' });
/** 판 하나를 연다 — 승인 · 시작 · 진행 하나. 판 이름이 시작 초라 판마다 1초 띄운다. */
async function startRun() {
  await sleep(1100);
  scenario.activateMission(MISSION, 'remote');
  session.markApproved();
  session.markStarted();
  scenario.receiveRobotProgress(MISSION, progressEvent());
  recorder.recordTick();
  await recorder.settleRecorder();
  return recorder.recorderStatus().folder;
}
async function tick() { recorder.recordTick(); await recorder.settleRecorder(); }
function endRun(outcome = 'done') {
  history.noteMissionEnd({ missionId: MISSION, label: 'x', outcome, endedAtIso: new Date().toISOString(), done: 1, of: 1, failedTaskId: null, reason: '' });
}
const frame = (rotationDeg) => ({
  kind: 'frame', deviceId: 'go1-001', missionId: MISSION, seq: ++seq, rotationDeg, width: 640, height: 480,
  bytes: jpeg.length, sha1: `s${seq}`, duplicateOfPrev: false, timestamp: null, imageBase64: jpeg.toString('base64'),
});
async function connect() {
  serverDown = false;
  for (let i = 0; i < 3 && !hs.historyServerConnected(); i += 1) await hs.checkHistoryServer();
}

let stopRecorder = () => {};
try {
  // ── 1. 적합성 검사 ─────────────────────────────────────────────────────────
  {
    const { ok, out } = await runNode(join(root, 'scripts', 'check-history-server.mjs'), mock.origin);
    expect('적합성 검사가 가짜 서버에서 전부 통과', ok && /(\d+)\/\1 통과/.test(out), out.split('\n').filter((l) => l.startsWith('FAIL')).join(' | '));
  }

  // ── 2. 주소 · 상태 ──────────────────────────────────────────────────────────
  {
    // 기본 주소 (261119 지시) — 한 번도 정한 적 없으면 서버 담당의 서버. 해제하면 새로고침해도 해제 그대로.
    expect('모듈을 처음 읽을 때(새 브라우저) 기본 주소가 선다', firstLoadAddress === 'http://100.102.8.102:8850', `'${firstLoadAddress}'`);
    memory.clear();
    hs.resetHistoryServerForTest();
    expect('처음 켜면 기본 주소(100.102.8.102:8850)', hs.historyServerStatus().address === hs.DEFAULT_HISTORY_SERVER && hs.DEFAULT_HISTORY_SERVER === 'http://100.102.8.102:8850');
    hs.setHistoryServerAddress('');
    hs.resetHistoryServerForTest();
    expect('연결 해제는 새로고침해도 해제 (기본 주소로 안 돌아감)', hs.historyServerStatus().address === '' && hs.historyServerStatus().state === 'unset');
    const n = hs.normalizeServerAddress;
    expect('주소 고르기 (http:// · 끝 / · /api/v1 · 빈 글자 · 틀 밖)',
      n('100.64.0.5:8790') === 'http://100.64.0.5:8790' && n(' http://h:1/api/v1/ ') === 'http://h:1' && n(' ') === '' && n('ftp://x') === null && n('http://h:1/?q=1') === null);
    hs.setHistoryServerAddress(closedPort.origin); await hs.checkHistoryServer();
    expect('닫힌 포트 → 닿지 않음', hs.historyServerStatus().state === 'unreachable');
    hs.setHistoryServerAddress(other.origin); await hs.checkHistoryServer();
    expect('다른 서버(200 · service 다름) → 임무 이력 서버 아님', hs.historyServerStatus().state === 'wrong-service');
    hs.setHistoryServerAddress(local.origin); await hs.checkHistoryServer();
    expect('health 404 → 서버 오류', hs.historyServerStatus().state === 'http-error');
    hs.setHistoryServerAddress(mock.origin.replace('http://', '')); await hs.checkHistoryServer();
    expect('첫 연결은 health 한 번이면 연결됨', hs.historyServerStatus().state === 'connected' && hs.historyServerStatus().address === mock.origin);
    hs.resetHistoryServerForTest();
    expect('새로고침해도 주소가 돌아온다', hs.historyServerStatus().address === mock.origin);
    await hs.checkHistoryServer();
    hs.noteServerWriteFailed('test');
    expect('쓰기 실패 한 번 → 곧바로 불안정', hs.historyServerStatus().state === 'unstable' && !hs.historyServerConnected());
    await hs.checkHistoryServer();
    expect('불안정에서 health 한 번으로는 안 돌아온다', hs.historyServerStatus().state === 'unstable' && hs.historyServerStatus().okStreak === 1);
    await hs.checkHistoryServer();
    expect('health 두 번 연속이면 연결됨', hs.historyServerStatus().state === 'connected');
  }

  recorder.resetRecorderForTest();
  stopRecorder = recorder.startMissionRecorder();

  // ── 3. 연결됨에서 시작한 판 — 서버에만 ──────────────────────────────────────
  let runA;
  {
    runA = await startRun();
    recorder.noteRobotFrame(frame(45));
    await tick();
    expect('연결됨에서 시작한 판은 서버에 쓴다', runA !== null && has(serverDir, runA, 'mission.json') && has(serverDir, runA, 'progress.json') && has(serverDir, runA, 'images/robot/rot_045.jpg'), String(runA));
    expect('그 판은 이 PC 에 안 쓴다', !runsIn(localDir).includes(runA));
    expect('기록 상태가 저장처 「서버」', recorder.recorderStatus().sink === 'server');
    expect('대피 판 없음', ev.evacuatedRuns().length === 0);
    endRun('done');
    await tick();
    expect('끝 표시도 서버에', readJson(serverDir, runA, 'mission.json').outcome === 'done');
  }

  // ── 4. 끊긴 채 시작한 판 — 이 PC 에만, 대피 판으로 ─────────────────────────────
  let runB;
  {
    serverDown = true; await hs.checkHistoryServer();
    runB = await startRun();
    expect('끊긴 채 시작한 판은 이 PC 에 쓴다', has(localDir, runB, 'mission.json') && !runsIn(serverDir).includes(runB), String(runB));
    expect('기록 상태가 저장처 「이 PC」', recorder.recorderStatus().sink === 'local');
    expect('대피 판으로 적힌다', ev.evacuatedRuns().some((x) => `${x.date}/${x.run}` === runB));
    endRun('stopped');
    await tick();
  }

  // ── 5. 서버로 쓰던 판이 중간에 실패 — 끝까지 이 PC, 그림도 이 PC 에 ──────────────
  let runC;
  {
    await connect();
    runC = await startRun();
    recorder.noteRobotFrame(frame(90));
    await tick();
    expect('판 C 는 서버로 시작', recorder.recorderStatus().sink === 'server' && has(serverDir, runC, 'images/robot/rot_090.jpg'));
    serverDown = true;   // health 는 아직 안 물었다 — 쓰기가 먼저 실패를 안다
    scenario.receiveRobotProgress(MISSION, progressEvent());
    await tick();
    expect('쓰기 실패로 곧바로 불안정', hs.historyServerStatus().state === 'unstable', hs.historyServerStatus().state);
    await tick();   // 대피한 다음 주기 — 두 JSON 을 통째로 이 PC 에
    await tick();
    expect('그 판이 이 PC 로 옮겨 온전히 (두 JSON · 서버로 보냈던 그림)',
      has(localDir, runC, 'mission.json') && has(localDir, runC, 'progress.json') && has(localDir, runC, 'images/robot/rot_090.jpg'));
    expect('판 C 가 대피 판으로 적힌다', ev.evacuatedRuns().some((x) => `${x.date}/${x.run}` === runC));
    const serverSeqBefore = readJson(serverDir, runC, 'progress.json').trace.length;
    await connect();
    expect('서버가 돌아왔다 (2연속)', hs.historyServerConnected());
    scenario.receiveRobotProgress(MISSION, progressEvent());
    await tick();
    expect('서버가 돌아와도 도는 판은 이 PC 에 쓴다 (판이 안 나뉜다)',
      recorder.recorderStatus().sink === 'local' && readJson(serverDir, runC, 'progress.json').trace.length === serverSeqBefore
      && readJson(localDir, runC, 'progress.json').trace.length > serverSeqBefore);
  }

  // ── 6. 대피 판 올리기 ───────────────────────────────────────────────────────
  {
    ev.resetEvacuatedForTest();   // 새로고침 흉내 — localStorage 에서 다시 읽는다
    expect('새로고침해도 대피 목록이 남는다', ev.evacuatedRuns().length === 2);
    await up.uploadEvacuatedRuns();
    await up.settleUpload();
    expect('끝난 대피 판(B)은 서버로 올라간다', has(serverDir, runB, 'mission.json') && readJson(serverDir, runB, 'mission.json').outcome === 'stopped');
    expect('도는 판(C)은 아직 안 올린다', ev.evacuatedRuns().some((x) => `${x.date}/${x.run}` === runC)
      && readJson(serverDir, runC, 'progress.json').trace.length < readJson(localDir, runC, 'progress.json').trace.length);
    expect('올린 판은 대피 목록에서 빠진다', !ev.evacuatedRuns().some((x) => `${x.date}/${x.run}` === runB));
    expect('올려도 이 PC 파일은 남는다', has(localDir, runB, 'mission.json'));
    endRun('failed');
    await tick();
    await up.uploadEvacuatedRuns();
    await up.settleUpload();
    expect('끝난 뒤 판 C 가 통째로 올라간다 (끝 표시 · 그림)', readJson(serverDir, runC, 'mission.json').outcome === 'failed'
      && readJson(serverDir, runC, 'progress.json').trace.length === readJson(localDir, runC, 'progress.json').trace.length
      && has(serverDir, runC, 'images/robot/rot_090.jpg'));
    expect('대피 목록이 빈다', ev.evacuatedRuns().length === 0, JSON.stringify(ev.evacuatedRuns()));
  }

  // ── 7. 목록 — 한 출처 ───────────────────────────────────────────────────────
  {
    mkdirSync(join(localDir, '261101', '080000_MSN-LOCALONLY'), { recursive: true });
    writeFileSync(join(localDir, '261101', '080000_MSN-LOCALONLY', 'mission.json'), JSON.stringify({ missionId: 'MSN-LOCALONLY', view: {} }));
    mkdirSync(join(serverDir, '261102', '090000_MSN-OTHER'), { recursive: true });
    writeFileSync(join(serverDir, '261102', '090000_MSN-OTHER', 'mission.json'), JSON.stringify({ missionId: 'MSN-OTHER', view: {} }));
    writeFileSync(join(serverDir, '261102', '090000_MSN-OTHER', 'progress.json'), '{"trace":[{"seq":7}]}');
    const list = await rc.listRecordedRuns();
    const keys = list?.runs.map((r) => `${r.date}/${r.run}`) ?? [];
    expect('연결됨이면 서버 목록', list?.source === 'server' && keys.includes('261102/090000_MSN-OTHER'));
    expect('서버 목록에 이 PC 에만 있는 판이 안 섞인다', !keys.includes('261101/080000_MSN-LOCALONLY'));
    expect('적합성 검사 판(000101)은 숨긴다', !keys.some((k) => k.startsWith('000101/')));
    // 서버 회신 261119 §5 — health 의 runCount 는 검사 판까지 센다. 띠의 「서버 판 N개」 는 목록(검사 판 뺀 것)의 수다.
    await hs.checkHistoryServer();
    const health = hs.historyServerStatus();
    expect('「서버 판 N개」 는 검사 판을 뺀 목록 수 (health 의 수가 아니다)',
      health.listedRunCount === list?.runs.length && health.runCount !== null && health.runCount > health.listedRunCount,
      `health ${health.runCount} · listed ${health.listedRunCount} · list ${list?.runs.length}`);
    expect('서버 판의 파일 주소는 서버', rc.recordFileUrl('261102', '090000_MSN-OTHER', 'images/detect/a.jpg').startsWith(`${mock.origin}/api/v1/files/`));
    expect('다른 장치의 판을 다시보기로 읽는다', (await rc.fetchRecordJson('261102', '090000_MSN-OTHER', 'progress.json')).trace[0].seq === 7);
    serverDown = true; await hs.checkHistoryServer();
    const down = await rc.listRecordedRuns();
    const downKeys = down?.runs.map((r) => `${r.date}/${r.run}`) ?? [];
    expect('끊기면 이 PC 목록', down?.source === 'local' && downKeys.includes('261101/080000_MSN-LOCALONLY') && !downKeys.includes('261102/090000_MSN-OTHER'));
    await connect();
  }

  // ── 8. 서버 거절 (4xx) — 상태는 그대로, 그 판은 이 PC 로 ─────────────────────────
  {
    let error = null;
    try { await rc.putRecordJson('bad', 'x', 'mission.json', '{}', 'server'); } catch (e) { error = e; }
    const next = rc.nextSink('server', error);
    expect('4xx 는 서버 거절로 갈리고 상태는 연결됨 그대로', error?.failure === 'server-rejected' && hs.historyServerConnected() && /HTTP 400/.test(hs.historyServerStatus().lastRejected ?? ''));
    expect('거절당한 판은 이 PC 로 옮긴다', next.sink === 'local' && next.evacuated);
  }

  // ── 9. 서버 주소가 없으면 예전과 같다 ─────────────────────────────────────────
  {
    hs.setHistoryServerAddress('');
    expect('주소가 없으면 저장처는 이 PC', rc.chooseSink() === 'local');
    localGone = true;
    let error = null;
    try { await rc.putRecordJson('261119', '100000_MSN-X', 'mission.json', '{}', 'local'); } catch (e) { error = e; }
    expect('이 PC 창구 404 는 ` 404` 로 던지고 기록기를 멈추게 한다', / 404$/.test(error?.message ?? '') && rc.nextSink('local', error).stop === true, error?.message);
    expect('서버 주소 없이 쓴 판은 대피로 안 적는다', ev.evacuatedRuns().length === 0);
  }

  // ── 10. 이 PC 창구가 없는 화면 ────────────────────────────────────────────────
  {
    hs.setHistoryServerAddress(mock.origin); await hs.checkHistoryServer();
    expect('창구 없는 화면에서도 연결됨이면 서버', rc.chooseSink() === 'server');
    let error = null;
    try { await rc.putRecordJson('261119', '100001_MSN-X', 'mission.json', '{}', 'local'); } catch (e) { error = e; }
    expect('서버 주소가 있으면 이 PC 404 로 멈추지 않는다 (다음 주기에 다시 고른다)', rc.nextSink('local', error).stop === false && rc.nextSink('local', error).sink === null);
    serverDown = true; await hs.checkHistoryServer();
    expect('서버도 끊기면 저장처 없음 (null)', rc.chooseSink() === null);
    localGone = false;
    await connect();
  }

  // ── 11. 이 PC 파일 목록 창구 · history:push ──────────────────────────────────
  {
    const files = await rc.listLocalRunFiles(...runC.split('/'));
    expect('이 PC 판의 파일 목록 창구', Array.isArray(files) && files.includes('mission.json') && files.includes('images/robot/rot_090.jpg'));
    const { out } = await runNode(join(root, 'scripts', 'push-history-to-server.mjs'), mock.origin, '--dir', localDir);
    expect('history:push 가 서버에 없는 이 PC 판을 올린다', has(serverDir, '261101/080000_MSN-LOCALONLY', 'mission.json'), out.trim().split('\n').at(-1));
  }

  // ── 12. 화면 · 연결 ─────────────────────────────────────────────────────────
  {
    const view = readFileSync(join(root, 'src', 'views', 'MissionHistory.tsx'), 'utf8');
    const bar = readFileSync(join(root, 'src', 'views', 'HistoryServerBar.tsx'), 'utf8');
    const main = readFileSync(join(root, 'src', 'main.tsx'), 'utf8');
    const conns = readFileSync(join(root, 'src', 'shared', 'connections.ts'), 'utf8');
    const ko = (await load('src', 'i18n', 'ko.ts')).ko;
    const en = (await load('src', 'i18n', 'en.ts')).en;
    // 261119 화면 확인 지시 — 목록 기둥 안 작은 상자가 아니라 상단 바와 목록 · 그래프 칸 사이의 가로 띠.
    expect('서버 띠가 리플레이 화면에서 목록 · 그래프 칸보다 먼저(가로 띠)', /\{replay && <HistoryServerBar \/>\}\s*\{replay && <aside className="history">/.test(main) && !/<HistoryServerBar/.test(view));
    const css = readFileSync(join(root, 'src', 'style.css'), 'utf8');
    expect('서버 띠가 격자 한 줄을 통째로 쓴다', /\.history-server\{[^}]*grid-column:1\/-1/.test(css));
    expect('리플레이 둘째 칸이 내용에 밀려 넓어지지 않는다 (minmax(0,1fr))', /\.replay-layout\{grid-template-columns:300px minmax\(0,1fr\)\}/.test(css));
    expect('서버 주소는 연결 관리 목록에 없다', !/history-server|historyServer/.test(conns));
    expect('앱이 켜질 때 서버 확인과 대피 판 올리기를 건다', /startHistoryServerWatch\(\)/.test(main) && /startEvacuationUpload\(\)/.test(main));
    expect('목록에 「이 PC만」 딱지 · 합치기가 없다', !/is-local-only|localOnly|where\?\./.test(view));
    const keys = [...bar.matchAll(/t\('((?:hsrv|hist)\.[^']+)'/g), ...view.matchAll(/t\('((?:hsrv|hist)\.[^']+)'/g)].map((m) => m[1]);
    const missing = [...new Set(keys)].filter((k) => ko[k] === undefined || en[k] === undefined);
    expect('화면이 쓰는 hsrv · hist 키가 두 사전에 다 있다', keys.length > 15 && missing.length === 0, missing.join(', '));
  }

  // ── 대조군 ─────────────────────────────────────────────────────────────────
  {
    const naiveHealth = (await realFetch(`${other.origin}/api/v1/health`)).ok;
    hs.setHistoryServerAddress(other.origin); await hs.checkHistoryServer();
    control('200 만 보고 연결됨으로 치는 사본', naiveHealth && !hs.historyServerConnected());
    hs.setHistoryServerAddress(mock.origin); await hs.checkHistoryServer();
    // 두 목록을 합치는 사본 — 이 PC 에만 있는 판이 서버 목록에 섞인다.
    fsWrite(join(localDir, '261103', '070000_MSN-MERGE'), 'mission.json', JSON.stringify({ missionId: 'MSN-MERGE', view: {} }));
    const localList = await realFetch(`${local.origin}/mission-records/api/runs`).then((r) => r.json());
    const serverList = await realFetch(`${mock.origin}/api/v1/runs`).then((r) => r.json());
    const merged = [...serverList.runs, ...localList.runs].map((r) => `${r.date}/${r.run}`);
    const ours = (await rc.listRecordedRuns()).runs.map((r) => `${r.date}/${r.run}`);
    control('두 목록을 합치는 사본', merged.includes('261103/070000_MSN-MERGE') && !ours.includes('261103/070000_MSN-MERGE'));
    // 「쓰기마다 그때 상태로 저장처를 고르는 사본」은 따로 만들지 않았다 — §5 의 「서버가 돌아와도 도는 판은 이 PC 에 쓴다」가
    // 바로 그 사본이 깨뜨릴 항목이다(서버 쪽 진행 수가 늘면 실패).
  }
} finally {
  stopRecorder();
  await Promise.all([close(mock.server), close(local.server), close(other.server)]);
}

function fsWrite(dir, name, body) { mkdirSync(dir, { recursive: true }); writeFileSync(join(dir, name), body); }
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}

if (failures.length) {
  console.error(`❌ verify:history-server\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 가짜 서버가 적합성 검사를 전부 통과한다 — 서버 담당이 같은 검사를 돌린다');
console.log('✅ 연결 상태를 가르고, 쓰기 실패 한 번이면 불안정 · health 2연속이어야 다시 서버에 쓴다');
console.log('✅ 연결됨에서 연 판은 서버에만, 끊긴 채 연 판은 이 PC 에만 — 실패한 판은 끝까지 이 PC 로 온전히 옮긴다');
console.log('✅ 대피 판은 끝난 뒤 통째로 올라가고(도는 판은 기다림 · 새로고침에도 이어짐) 이 PC 파일은 남는다');
console.log('✅ 목록은 한 출처 — 서버가 답하면 서버 목록만, 아니면 이 PC 목록만 · 서버 주소가 없으면 예전 규칙 그대로');
console.log(`✅ 확인 ${passed.length}건 · 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
