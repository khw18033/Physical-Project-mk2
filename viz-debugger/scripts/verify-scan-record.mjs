// verify:scan-record (261124 신설 — 「임무 이력에서 스캔 탐지 그림이 안 보인다」)
//
// **스캔 탐지(data_stream) 한 판이 임무 이력에 남고, 이력에서 열면 같은 그림이 뜨는가.**
//
// 전에는 기록기가 옛 탐지기 그림만 떴다. 새 흐름의 각도 그림은 화면이 data_stream 창구(`/scan/frame`)에서 그때그때 받아
// 그렸을 뿐이라 기록 폴더에 한 장도 없었고, 판 상태(각도 칸 · 결과 · 경로)도 `progress.json` 에 없었다. 이력에서 열면
// 「판 없음」이었다. 막으려는 실패 넷.
//
//  1. 받은 각도의 원본 · 찾은 각도의 상자 그림 · 대상 잘라낸 그림이 판 폴더에 안 남는 것
//  2. 판 상태와 이동 계획이 `progress.json` 에 안 남는 것
//  3. 이력에서 연 판의 그림 주소가 아직 창구를 가리키는 것 — 창구는 끝난 판을 몇 개만 들고, 다른 PC 에선 안 닿는다
//  4. 이력을 닫은 뒤 그 판이 지금 화면에 남는 것
//
// 대조군: 못 받은 각도(프레임 없음)의 그림을 지어 남기지 않는다 · 찾지 못한 각도의 상자 그림을 남기지 않는다.

import { createServer } from 'node:http';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

const dir = mkdtempSync(join(tmpdir(), 'scan-records-'));
const { missionRecordsMiddleware } = await load('scripts', 'mission-records.mjs');
const middleware = missionRecordsMiddleware(dir);
const server = createServer((req, res) => middleware(req, res, () => { res.statusCode = 404; res.end('next'); }));
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;

// 브라우저의 상대 주소(기록 창구)를 임시 서버로 보낸다. data_stream 창구는 가짜를 그대로 부른다.
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  const text = String(url);
  if (text.startsWith('/')) return realFetch(`${origin}${text}`, init);
  return realFetch(url, init);
};

const { startScanMock } = await load('scripts', 'scan-detect-mock.mjs');
const mockLog = [];
// 135° 는 프레임 없음 — 그 각도의 그림이 지어져 남으면 안 된다. 90° 에서 찾는다.
const mock = await startScanMock({ port: 0, host: '127.0.0.1', log: mockLog, mode: 'frame-gaps', gapDegs: [135], foundDeg: 90, loadMs: 0, markMs: 0, resultMs: 0 });
const base = `http://127.0.0.1:${mock.address().port}`;

try {
  const scenario = await load('src', 'data', 'scenario.ts');
  const session = await load('src', 'physical', 'robotSession.ts');
  const recorder = await load('src', 'record', 'recorder.ts');
  const { openRecordedRun } = await load('src', 'record', 'loadRecord.ts');
  const { isReplayingRecord } = await load('src', 'record', 'replayMode.ts');
  const { recordFileUrl, scanImagePath } = await load('src', 'record', 'recordClient.ts');
  const store = await load('src', 'detect', 'scan', 'scanStore.ts');
  const { scanClient } = await load('src', 'detect', 'scan', 'ScanClient.ts');
  const approachRun = await load('src', 'physical', 'scanApproachRun.ts');
  const { planScanApproach } = await load('src', 'physical', 'scanApproach.ts');

  const MISSION = 'MSN-261123-02';
  const SCAN = `${MISSION}-REC`;
  const runDirs = () => (existsSync(dir) ? readdirSync(dir).flatMap((date) => readdirSync(join(dir, date)).map((run) => `${date}/${run}`)) : []);

  recorder.resetRecorderForTest();
  const stopRecorder = recorder.startMissionRecorder();
  scenario.activateMission(MISSION, 'remote');
  session.markApproved();
  session.markStarted();

  // ── 한 판 — 실행기가 내는 것과 같은 사건을 가짜 창구의 실제 응답으로 ─────────────────
  const client = scanClient(base);
  store.applyScanEvent({ kind: 'begin', scanId: SCAN, missionId: MISSION, device: 'go1-001', base, target: 'box', query: null, queryKo: null, steps: 8, stepDeg: 45 });
  const prepared = await client.prepare({ scan_id: SCAN, device: 'go1-001', target: 'box', query: null, query_ko: null, steps: 8, step_deg: 45 });
  check(prepared.ok, `가짜 창구 prepare 실패 ${JSON.stringify(prepared)}`);
  if (prepared.ok) store.applyScanEvent({ kind: 'prepare', scanId: SCAN, answer: prepared.value });
  for (let i = 0; i < 8; i += 1) {
    const mark = await client.mark(SCAN, i * 45);
    store.applyScanEvent({ kind: 'mark', scanId: SCAN, index: i, answer: mark.ok ? mark.value : null });
  }
  await client.finish(SCAN);
  let result = null;
  for (let i = 0; i < 20 && (result === null || result.state !== 'done'); i += 1) {
    const answer = await client.result(SCAN);
    result = answer.ok ? answer.value : null;
    if (result?.state !== 'done') await new Promise((done) => setTimeout(done, 50));
  }
  check(result?.state === 'done' && result.best?.rotation_deg === 90, `가짜 창구 결과가 틀리다 ${JSON.stringify(result?.best ?? null)}`);
  if (result !== null) store.applyScanEvent({ kind: 'result', scanId: SCAN, result });
  const input = { best: result?.best ?? null, stopDistanceM: 0.2, headingStartDeg: 0, headingEndDeg: -8, testMode: false };
  approachRun.setScanApproach({ scanId: SCAN, missionId: MISSION, plan: planScanApproach(input), input, issued: true, waitingApproval: false });

  recorder.recordTick();
  await recorder.settleRecorder();
  recorder.recordTick();   // 결과 뒤 그림까지 — 주기 두 번
  await recorder.settleRecorder();

  const folders = runDirs();
  check(folders.length === 1, `판 폴더가 ${folders.length}개 — 하나여야 한다`);
  const folder = folders[0];
  if (folder !== undefined) {
    const has = (path) => existsSync(join(dir, folder, path));
    // 1. 그림
    for (const deg of [0, 45, 90, 180, 225, 270, 315]) check(has(scanImagePath(deg, 'original')), `받은 ${deg}° 원본이 안 남았다`);
    check(has(scanImagePath(90, 'overlay')), '찾은 90° 의 상자 그림이 안 남았다');
    check(has(scanImagePath(90, 'crop')), '대상 잘라낸 그림(90°)이 안 남았다');
    check(!has(scanImagePath(135, 'original')), '대조군: 프레임 없음(135°)의 그림을 지어 남겼다');
    check(!has(scanImagePath(45, 'overlay')), '대조군: 찾지 못한 45° 의 상자 그림을 남겼다');
    check(scanImagePath(90, 'overlay').startsWith('images/detect/'), '그림이 기록 창구가 받는 폴더(detect · robot) 밖에 있다');
    // 2. 판 상태 · 이동 계획
    const progress = JSON.parse(readFileSync(join(dir, folder, 'progress.json'), 'utf8'));
    check(progress.scan?.scanId === SCAN && progress.scan.angles.length === 8 && progress.scan.result?.best?.rotation_deg === 90,
      `progress.json 에 스캔 판이 안 남았다 (${JSON.stringify(progress.scan?.scanId ?? null)})`);
    check(progress.scan?.recorded === null, 'progress.json 의 판에 기록 폴더 표시가 섞였다');
    check(progress.scanApproach?.plan?.ok === true && progress.scanApproach.input.stopDistanceM === 0.2, 'progress.json 에 이동 계획 · 정지 거리가 안 남았다');

    // 3. 이력에서 연다
    stopRecorder();
    const [date, run] = folder.split('/');
    mock.close();   // 창구가 없어도 그림이 떠야 한다
    const opened = await openRecordedRun(date, run);
    check(opened.ok, `이력이 안 열린다 ${opened.ok ? '' : opened.reason}`);
    const restored = store.scanRunState();
    check(isReplayingRecord() && restored?.scanId === SCAN && restored.recorded?.date === date && restored.recorded.run === run,
      `이력의 스캔 판이 안 되살아났다 (${JSON.stringify(restored?.recorded ?? null)})`);
    check(approachRun.scanApproachState()?.plan.ok === true && approachRun.scanApproachState().waitingApproval === false,
      '이력의 이동 계획이 안 되살아났거나 누를 수 있게 열렸다');
    for (const [deg, kind] of [[90, 'overlay'], [90, 'crop'], [0, 'original']]) {
      const url = recordFileUrl(date, run, scanImagePath(deg, kind));
      const response = await globalThis.fetch(url);
      check(response.ok, `이력에서 ${deg}° ${kind} 를 못 읽는다 (${response.status} ${url})`);
    }

    // 4. 이력을 닫으면 그 판이 지금 화면에 남지 않는다
    scenario.closeRecordReplay();
    check(store.scanRunState() === null, '이력을 닫았는데 그 스캔 판이 남았다');
  }
} finally {
  globalThis.fetch = realFetch;
  server.close();
  mock.close();
  rmSync(dir, { recursive: true, force: true });
}

if (failures.length > 0) {
  console.error(`❌ verify:scan-record 실패 ${failures.length}건`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log('✅ 통과 — 각도 원본 · 찾은 각도 상자 그림 · 잘라낸 그림이 판 폴더에 · progress 에 판 · 이동 계획 · 이력에서 창구 없이 그림이 뜬다 · 닫으면 비운다 / 대조군: 프레임 없음 · 못 찾은 각도');
