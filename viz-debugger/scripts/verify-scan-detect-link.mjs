// verify:scan-detect-link (261123 신설 — 스캔 탐지를 data_stream 으로 · S11 화면 연결)
//
// **새 편(`MSN-261123-0x`)을 승인하고 「임무 시작」을 누르면, 화면 연결(`scanDetectLink.ts`)이 끝까지 도는가.**
// `verify:scan-detect` 는 실행기 순서만 본다. 여기는 실제 자리 — 승인 관문 · 준비 단계(T-A2 방위) · 추론 스트림 포트 묶음 ·
// `issueStepsToEnd` · 노드 칠하기 · 이동 명령 · 정지 → cancel — 를 지난다.
//
// 장치: `PhysicalClient.prototype.send` 를 가로채 수락 → 완료로 답한다(`scripts/lib/runnerRig.mjs` 와 같은 방식).
// 회전이 끝날 때마다 장치 방위를 보고하되 **한 번에 1° 씩 더 돈 것으로** 적는다 — 여덟 번이면 8° 어긋나고,
// 경로가 그만큼을 빼야 한다(회전 오차 보정).
// 창구: `scan-detect-mock.mjs` 를 임의 포트로. 연결 관리 「추론 스트림」에 그 포트를 적고 Go1 을 그 포트에 묶는다.
//
// 대조군: 찾지 못함 판(이동 명령이 안 나간다) · 판 도중 정지(cancel 이 나가고 더 돌지 않는다) · 옛 편(이 연결이 안 돈다).

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

// **robotClient 를 먼저 부른다** — PhysicalClient 가 기본 주소를 import 순간에 적어 둔다(runnerRig 와 같다).
const { robotClient } = await load('src', 'physical', 'robotClient.ts');
const { registerConnectionDefault } = await load('src', 'shared', 'connections.ts');
const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
const { receiveDeviceMessage, resetDevices } = await load('src', 'physical', 'deviceState.ts');
const { setVisionBinding } = await load('src', 'vision', 'binding.ts');
const scenario = await load('src', 'data', 'scenario.ts');
const session = await load('src', 'physical', 'robotSession.ts');
const link = await load('src', 'physical', 'scanDetectLink.ts');
const approachRun = await load('src', 'physical', 'scanApproachRun.ts');
const { resetScanRun, scanRunState } = await load('src', 'detect', 'scan', 'scanStore.ts');
const { startScanMock } = await load('scripts', 'scan-detect-mock.mjs');

const BROKER = 'ws://pi7.test:9001';
const GO1 = 'go1-001';
const DRIFT_PER_TURN = 1;

registerConnectionDefault('physical', 'ws', BROKER);
const client = robotClient();
const stopLink = link.startScanDetectLink();

const wrap = (deg) => ((((deg + 180) % 360) + 360) % 360) - 180;

async function runCase({ missionId, mode = 'ok', stopAfterTurns = null, waitMs = 15000 }) {
  const log = [];
  const server = await startScanMock({ port: 0, host: '127.0.0.1', log, mode, loadMs: 100, markMs: 20, resultMs: 100 });
  const port = server.address().port;
  registerConnectionDefault('vision', 'host', 'http://127.0.0.1');
  registerConnectionDefault('vision', 'ports', String(port));
  setVisionBinding(GO1, `http://127.0.0.1:${port}`);

  const sent = [];
  let heading = 0;
  let turns = 0;
  // 등록 · 생사는 status, 자리 · 방위는 state 로 온다(`deviceState.ts`) — 실물과 같은 두 갈래로 넣는다.
  const report = () => {
    receiveDeviceMessage(`zoneA/robot/${GO1}/status`, {
      channel: 'status', status: 'online', link: 'ok',
      registration: { entity_id: GO1, entity_type: 'robot', device_type: 'go1_robot' }, battery_pct: 80,
    }, client.address());
    receiveDeviceMessage(`zoneA/robot/${GO1}/state`, {
      channel: 'state', link: 'ok', battery_pct: 80, position: { x: 0, y: 0, heading_deg: wrap(heading) },
    }, client.address());
  };
  const original = PhysicalClient.prototype.send;
  let n = 0;
  PhysicalClient.prototype.send = function send(action, parameters) {
    n += 1;
    const commandId = `cmd-${n}`;
    sent.push({ action, parameters, at: Date.now() });
    const emit = (message) => { for (const listener of this.listeners) listener(message); };
    setTimeout(() => {
      if (action === 'abort') return;
      emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null });
      setTimeout(() => {
        if (action === 'turn') {
          turns += 1;
          // 실물 GO1 처럼 방위는 **반시계 +** — 오른쪽 + 인 turn 만큼 줄어든다(261123 실측). 한 번에 1° 더 오른쪽으로 돈다.
          heading -= Number(parameters?.deg ?? 0) + (turns <= 8 ? DRIFT_PER_TURN : 0);
          report();
          if (stopAfterTurns !== null && turns === stopAfterTurns) session.lockStopped(true, null);
        }
        sent[sent.findIndex((s) => s.at && s.action === action && !s.doneAt)].doneAt = Date.now();
        emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: {}, code: null, message: null });
      }, 30);
    }, 5);
    return { sent: true, commandId };
  };

  resetDevices();
  resetScanRun();
  scenario.resetMission();
  session.setConnection({ state: 'open' });
  report();
  scenario.proposeMission({ origin: 'script', missionId, title: missionId, keywords: [], planId: null, world: 'registry' });
  scenario.acceptProposal('remote');
  session.markStarted();
  report();

  const until = Date.now() + waitMs;
  const done = () => sent.some((s) => s.action === 'abort') || scanRunState()?.failure != null
    || (scanRunState()?.result != null && approachRun.scanApproachState() !== null && !approachRun.scanApproachState().plan.ok);
  while (Date.now() < until && !done()) {
    await sleep(50);
    report();
  }
  await sleep(200);
  const trace = [...scenario.traceEvents()];
  const run = scanRunState();
  PhysicalClient.prototype.send = original;
  server.close();
  if (session.robotSession().stopped !== null) session.releaseStopped();
  scenario.resetMission();
  return { sent, log, trace, run };
}

const statusOf = (trace, id) => [...trace].reverse().find((e) => e.nodeId === id)?.status ?? null;

// ── 1. 정상 판 (박스 편) ───────────────────────────────────────────────
{
  const { sent, log, trace, run } = await runCase({ missionId: 'MSN-261123-02' });
  const actions = sent.map((s) => s.action);
  const turns = sent.filter((s) => s.action === 'turn');
  check(turns.length >= 9 && turns.slice(0, 8).every((s) => s.parameters.deg === 45), `회전 45° 여덟 번이 앞서야 한다 (${actions.join(',')})`);
  check(actions.slice(-2).join(',') === 'move_forward,abort', `끝이 move_forward · abort 가 아니다 (${actions.join(',')})`);
  check(!actions.includes('scan_mission'), '새 편에서 scan_mission 이 나갔다');
  // mark(k) 는 turn(k−1) 완료 뒤에 창구에 닿는다.
  const marks = log.filter((r) => r.path === '/scan/mark');
  check(marks.length === 8, `mark 가 ${marks.length}번 — 여덟 번이어야 한다`);
  for (let k = 1; k < marks.length; k += 1) {
    const prevDone = turns[k - 1]?.doneAt;
    check(prevDone !== undefined && marks[k].at >= prevDone, `mark(${k * 45}°) 가 turn(${k - 1}) 완료 전에 닿았다`);
  }
  const prep = log.find((r) => r.path === '/scan/prepare');
  check(prep?.body.device === GO1 && prep.body.target === 'box' && prep.body.query === null, `prepare 가 틀리다 ${JSON.stringify(prep?.body)}`);
  check(log.findIndex((r) => r.path === '/scan/finish') > log.findLastIndex((r) => r.path === '/scan/mark'), 'finish 가 마지막 mark 뒤가 아니다');
  // 경로: 방위 96.4 − 회전 오차 8 = 88.4, 직진 2.35 − 0.9 = 1.45 (테스트 상한이 꺼져 있을 때)
  const lastTurn = turns[turns.length - 1];
  check(turns.length === 9 && Math.abs(lastTurn.parameters.deg - 88.4) < 0.05, `경로 회전이 ${lastTurn?.parameters.deg} — 96.4 − 8 = 88.4 여야 한다`);
  const forward = sent.find((s) => s.action === 'move_forward');
  check(forward !== undefined && Math.abs(forward.parameters.distance_m - 1.45) < 1e-6, `직진이 ${forward?.parameters.distance_m} — 1.45 여야 한다`);
  for (const id of ['T-A0', 'T-A2', 'T-A3', 'T-A4-0', 'T-A4-7', 'T-A5', 'T-A6', 'T-B1']) {
    check(statusOf(trace, id) === 'done', `${id} 가 끝남으로 칠해지지 않았다 (${statusOf(trace, id)})`);
  }
  check(run?.headingStartDeg === 0 && run.headingEndDeg === -8, `시작 · 끝 방위가 ${run?.headingStartDeg} · ${run?.headingEndDeg} — 0 · −8(반시계 +) 이어야 한다`);
  check(run?.angles.every((a) => a.captured === true), '각도 여덟이 다 수집됨이 아니다');
}

// ── 2. 찾지 못함 — 이동 명령이 안 나간다 ─────────────────────────────────
{
  const { sent, trace } = await runCase({ missionId: 'MSN-261123-01', mode: 'best-null' });
  const actions = sent.map((s) => s.action);
  check(!actions.includes('move_forward') && actions.filter((a) => a === 'turn').length === 8, `찾지 못함 판에서 이동이 나갔다 (${actions.join(',')})`);
  check(statusOf(trace, 'T-A5') === 'failed', `찾지 못함 판의 T-A5 가 ${statusOf(trace, 'T-A5')}`);
}

// ── 3. 판 도중 정지 — cancel 이 나가고 더 돌지 않는다 ───────────────────────
{
  const { sent, log } = await runCase({ missionId: 'MSN-261123-02', stopAfterTurns: 3, waitMs: 4000 });
  const turns = sent.filter((s) => s.action === 'turn').length;
  check(turns === 3, `정지 뒤에도 회전이 나갔다 (${turns})`);
  check(log.some((r) => r.path === '/scan/cancel'), '정지 뒤 cancel 이 안 나갔다');
  check(!log.some((r) => r.path === '/scan/finish'), '정지 뒤 finish 가 나갔다');
}

// ── 4. 옛 편 — 이 연결이 안 돈다 ────────────────────────────────────────
{
  const { log } = await runCase({ missionId: 'MSN-261027-01', waitMs: 1500 });
  check(log.length === 0, `옛 편에서 data_stream 창구를 두드렸다 (${log.map((r) => r.path).join(',')})`);
}

stopLink();
if (failures.length > 0) {
  console.error(`❌ verify:scan-detect-link 실패 ${failures.length}건`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log('✅ 통과 — 승인 · 시작 → 준비(방위) · 추론 스트림 포트 · turn 45° ×8(완료 뒤 mark) · 산출 → 회전 오차 8° 를 뺀 경로 · 직진 · 정지 / 찾지 못함 · 판 도중 정지 · 옛 편 대조');
process.exit(0);
