// scripts/lib/traceShrinkProbe.mjs (261026 신설 — 기록 열 덮어쓰기)
//
// **실제 기록기를 실제 창구에 붙여 판 하나를 몰아 보고, 판 폴더에 무엇이 남았는지 돌려준다.** 판정은
// `verify:trace-shrink-guard` 가 한다. 창구(`scripts/mission-records.mjs`)는 임시 폴더에 띄운다 — 저장소의
// `mission-history/` 는 건드리지 않는다.
//
// 핫 리로드 사고의 모양은 **저장소만 비고 기록기는 같은 판을 쥔 채**다. 그래서 `scenario.ts` 를 거치지 않고
// 기록 열 저장소(`trace.ts`)를 직접 비운다 — `scenario` 를 거치면 `sealRun()` 이 판을 놓아 사고가 안 난다.
//
//   node scripts/lib/traceShrinkProbe.mjs <root>   → stdout 에 JSON 한 줄
import { createServer } from 'node:http';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const vizRoot = join(fileURLToPath(new URL('.', import.meta.url)), '..', '..');
const MISSION = 'MSN-260909-01';

export async function probe(rootArg) {
  const root = resolve(rootArg);
  const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
  const dir = mkdtempSync(join(tmpdir(), 'trace-shrink-'));
  const { missionRecordsMiddleware } = await import(pathToFileURL(join(vizRoot, 'scripts', 'mission-records.mjs')).href);
  const middleware = missionRecordsMiddleware(dir);
  const server = createServer((req, res) => middleware(req, res, () => { res.statusCode = 404; res.end('next'); }));
  await new Promise((done) => server.listen(0, '127.0.0.1', done));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    const text = String(url);
    if (text.startsWith('/')) return realFetch(`${origin}${text}`, init);
    return realFetch(url, init);
  };
  const warned = [];
  const realWarn = console.warn;
  console.warn = (...args) => warned.push(args.join(' '));

  try {
    const recorder = await load('src', 'record', 'recorder.ts');
    const scenario = await load('src', 'data', 'scenario.ts');
    const trace = await load('src', 'data', 'trace.ts');
    const session = await load('src', 'physical', 'robotSession.ts');
    const log = await load('src', 'detect', 'detectLog.ts');

    const runDirs = () => existsSync(dir) ? readdirSync(dir).flatMap((date) => readdirSync(join(dir, date)).map((run) => `${date}/${run}`)).sort() : [];
    const onDisk = (folder) => JSON.parse(readFileSync(join(dir, folder, 'progress.json'), 'utf8')).trace.length;
    const event = (seq, atSec) => ({ seq, atSec, nodeId: 'T-A3', status: 'running', kind: 'robot_progress', producedBy: 'backend' });
    const tick = async () => { recorder.recordTick(); await recorder.settleRecorder(); };
    const lastError = () => recorder.recorderStatus().lastError;

    recorder.resetRecorderForTest();
    const stop = recorder.startMissionRecorder();
    scenario.activateMission(MISSION, 'remote');
    session.markApproved();
    session.markStarted();
    for (let i = 1; i <= 5; i += 1) scenario.receiveRobotProgress(MISSION, event(3_000_000 + i, i));
    await tick();
    const folder = runDirs()[0] ?? null;
    if (folder === null) return { folder: null };
    const first = onDisk(folder);

    // ③ 늘어나면 쓴다
    scenario.receiveRobotProgress(MISSION, event(3_000_006, 6));
    await tick();
    const grown = onDisk(folder);
    // ③ 같은 길이면 지금처럼 글자로 — 열 밖(탐지 로그)이 바뀌면 쓴다
    scenario.receiveRobotProgress(MISSION, event(3_000_006, 6));   // 같은 seq — 열이 흡수한다(길이 그대로)
    log.appendDetectLog({ lane: 'detect', level: 'info', text: '같은 길이 검사', detail: '', tasks: ['T-B1'] });
    await tick();
    const sameLength = onDisk(folder);
    const sameLengthWritten = JSON.stringify(JSON.parse(readFileSync(join(dir, folder, 'progress.json'), 'utf8')).detectLog).includes('같은 길이 검사');
    const errorBeforeShrink = lastError();

    // ① 101 → 3 의 모양: 저장소만 비고 판은 그대로 — 몇 건을 다시 받는다
    trace.resetTrace(MISSION);
    for (let i = 1; i <= 3; i += 1) trace.appendTrace(MISSION, event(3_100_000 + i, 100 + i));
    await tick();
    const afterPartial = onDisk(folder);
    const errorPartial = lastError();
    // ① 어제의 모양: 빈 열
    trace.resetTrace(MISSION);
    await tick();
    const afterEmpty = onDisk(folder);
    const errorEmpty = lastError();

    // ④ 새 판 — 「처음부터」는 비우기 전에 봉인한다. 새 Run · 새 폴더 · 높이 0
    await new Promise((done) => setTimeout(done, 1100));   // 폴더 이름이 초 단위다
    scenario.activateMission(MISSION, 'remote');
    session.markApproved();
    session.markStarted();
    scenario.receiveRobotProgress(MISSION, event(3_200_001, 1));
    await tick();
    const folders = runDirs();
    const next = folders.find((f) => f !== folder) ?? null;

    stop();
    return {
      folder,
      first, grown, sameLength, sameLengthWritten, errorBeforeShrink,
      afterPartial, errorPartial, afterEmpty, errorEmpty,
      warned: warned.filter((w) => w.includes('[recorder]')).length,
      folders: folders.length,
      next, nextOnDisk: next === null ? null : onDisk(next),
      errorAfterNext: lastError(),
    };
  } finally {
    console.warn = realWarn;
    globalThis.fetch = realFetch;
    await new Promise((done) => server.close(done));
    rmSync(dir, { recursive: true, force: true });
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [root] = process.argv.slice(2);
  process.stdout.write(`${JSON.stringify(await probe(root))}\n`);
  process.exit(0);
}
