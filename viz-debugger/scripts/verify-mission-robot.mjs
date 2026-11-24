// verify:mission-robot (261124 신설 — 로봇 둘을 붙인 채 박스 탐지를 돌리면 명령과 영상이 갈라지던 것)
//
// **Go1 과 EP 를 같이 붙이고 박스 편(`MSN-261123-02`)을 돌리면, 회전 · 추론 포트 · 방위 · 접근 이동이 같은 로봇을 보는가.**
//
// 실측(261124): 회전은 연결 관리 첫 줄(EP)로 나가고, 스캔은 옛 표 `go1-001` 의 추론 포트로 해서 가만히 있는 Go1 의 그림을 썼다.
// 카드를 끌어 놓아도 그림만 바뀌었다(배정이 `main.tsx` 컴포넌트 상태였다).
//
// 장치: 브로커 둘(첫 줄 pi1 = EP, 둘째 줄 pi7 = Go1). `PhysicalClient.prototype.send` 를 가로채 **어느 소켓으로 나갔는지**를 적는다.
// 창구: `scan-detect-mock.mjs` 둘 — Go1 포트 · EP 포트. 어느 쪽에 `/scan/prepare` 가 닿았는지 본다.
//
//   1. 끌어 놓은 것 없음 → 고르지 않는다: 회전 0 · 창구 0 · T-A0 실패(`robot_choice`) · 알림
//   2. Go1 을 끌어 놓음 → 회전 · 직진이 전부 pi7 · prepare 가 Go1 포트에 device=go1-001 · 방위는 Go1 의 것
//   3. EP 를 끌어 놓음 → 전부 pi1 · EP 포트
//   4. 끌어 놓은 Go1 이 꺼짐 → EP 로 물러서지 않는다(`assignedAway`)
//   대조: 로봇이 하나(EP 만)면 끌어 놓지 않아도 그것으로 돈다

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

const { robotClient, syncRobotClients } = await load('src', 'physical', 'robotClient.ts');
const { registerConnectionDefault } = await load('src', 'shared', 'connections.ts');
const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
const { receiveDeviceMessage, resetDevices } = await load('src', 'physical', 'deviceState.ts');
const { resetDeviceIdentity } = await load('src', 'physical', 'deviceIdentity.ts');
const { setVisionBinding } = await load('src', 'vision', 'binding.ts');
const { assignToMilestone, resetAssignments } = await load('src', 'data', 'assignments.ts');
const scenario = await load('src', 'data', 'scenario.ts');
const session = await load('src', 'physical', 'robotSession.ts');
const link = await load('src', 'physical', 'scanDetectLink.ts');
const approachRun = await load('src', 'physical', 'scanApproachRun.ts');
const { resetScanRun, scanRunState } = await load('src', 'detect', 'scan', 'scanStore.ts');
const { notificationsNow, resetNotifications } = await load('src', 'shared', 'notifications.ts');
const { startScanMock } = await load('scripts', 'scan-detect-mock.mjs');

const PI1 = 'ws://pi1.test:9001';
const PI7 = 'ws://pi7.test:9001';
const GO1 = 'go1-001';
const EP = 'ep-001';
const MISSION = 'MSN-261123-02';

registerConnectionDefault('physical', 'ws', `${PI1}\n${PI7}`);
robotClient();
const [epClient, go1Client] = syncRobotClients();
check(epClient?.address() === PI1 && go1Client?.address() === PI7, `소켓 순서가 틀리다 (${epClient?.address()} · ${go1Client?.address()})`);
const stopLink = link.startScanDetectLink();

const wrap = (deg) => ((((deg + 180) % 360) + 360) % 360) - 180;

async function runCase({ assign = null, robots = [GO1, EP], offline = [], waitMs = 12000 }) {
  const logGo1 = [];
  const logEp = [];
  const serverGo1 = await startScanMock({ port: 0, host: '127.0.0.1', log: logGo1, distance: 2.35, loadMs: 50, markMs: 10, resultMs: 50 });
  const serverEp = await startScanMock({ port: 0, host: '127.0.0.1', log: logEp, distance: 2.35, loadMs: 50, markMs: 10, resultMs: 50 });
  const baseGo1 = `http://127.0.0.1:${serverGo1.address().port}`;
  const baseEp = `http://127.0.0.1:${serverEp.address().port}`;
  setVisionBinding(GO1, baseGo1);
  setVisionBinding(EP, baseEp);

  const heading = { [GO1]: 30, [EP]: -60 };
  const clientOf = { [GO1]: go1Client, [EP]: epClient };
  const deviceOf = (address) => (address === PI7 ? GO1 : EP);
  const report = () => {
    for (const id of robots) {
      const origin = clientOf[id].address();
      const type = id === GO1 ? 'go1_robot' : 'robomaster_ep';
      receiveDeviceMessage(`zoneA/robot/${id}/status`, {
        channel: 'status', status: offline.includes(id) ? 'offline' : 'online', link: 'ok',
        registration: { entity_id: id, entity_type: 'robot', device_type: type }, battery_pct: 80,
      }, origin);
      if (offline.includes(id)) continue;
      receiveDeviceMessage(`zoneA/robot/${id}/state`, {
        channel: 'state', link: 'ok', battery_pct: 80, position: { x: 0, y: 0, heading_deg: wrap(heading[id]) },
      }, origin);
    }
  };
  const sent = [];
  const original = PhysicalClient.prototype.send;
  let n = 0;
  PhysicalClient.prototype.send = function send(action, parameters) {
    n += 1;
    const commandId = `cmd-${n}`;
    const via = this.address();
    sent.push({ action, parameters, via });
    const emit = (message) => { for (const listener of this.listeners) listener(message); };
    setTimeout(() => {
      if (action === 'abort') return;
      emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null });
      setTimeout(() => {
        if (action === 'turn') { heading[deviceOf(via)] -= Number(parameters?.deg ?? 0); report(); }
        emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: {}, code: null, message: null });
      }, 20);
    }, 5);
    return { sent: true, commandId };
  };

  resetDevices();
  resetDeviceIdentity();
  resetScanRun();
  resetNotifications();
  scenario.resetMission();
  resetAssignments();
  session.setConnection({ state: 'open' });
  report();
  scenario.proposeMission({ origin: 'script', missionId: MISSION, title: MISSION, keywords: [], planId: null, world: 'registry' });
  scenario.acceptProposal('remote');
  if (assign !== null) assignToMilestone('MS-1', assign);
  session.markStarted();
  report();

  const until = Date.now() + waitMs;
  const done = () => scanRunState()?.failure != null
    || (scanRunState()?.result != null && approachRun.scanApproachState() !== null
      && (!approachRun.scanApproachState().plan.ok || approachRun.scanApproachState().waitingApproval || approachRun.scanApproachState().issued));
  while (Date.now() < until && !done()) { await sleep(50); report(); }
  // 직진이 이미 나갔거나 누르기를 기다리면 눌러서 어느 소켓으로 가는지 본다.
  if (approachRun.scanApproachState()?.waitingApproval === true) await approachRun.issueScanApproach();
  await sleep(300);
  const trace = [...scenario.traceEvents()];
  const run = scanRunState();
  const notes = notificationsNow().map((item) => item.message);
  PhysicalClient.prototype.send = original;
  serverGo1.close();
  serverEp.close();
  if (session.robotSession().stopped !== null) session.releaseStopped();
  scenario.resetMission();
  resetAssignments();
  return { sent, logGo1, logEp, trace, run, notes };
}

const lastOf = (trace, id) => [...trace].reverse().find((e) => e.nodeId === id) ?? null;
const moving = (sent) => sent.filter((s) => s.action === 'turn' || s.action === 'move_forward');

// ── 1. 로봇 둘 · 끌어 놓은 것 없음 — 고르지 않는다 ─────────────────────────
{
  const { sent, logGo1, logEp, trace, notes } = await runCase({ waitMs: 2500 });
  check(moving(sent).length === 0, `로봇 둘인데 고르지 않고 움직였다 (${moving(sent).map((s) => `${s.action}@${s.via}`).join(',')})`);
  check(logGo1.length === 0 && logEp.length === 0, `로봇 둘인데 창구를 두드렸다 (go1 ${logGo1.length} · ep ${logEp.length})`);
  const a0 = lastOf(trace, 'T-A0');
  check(a0?.status === 'failed' && a0.payload?.code === 'robot_choice', `T-A0 가 robot_choice 실패가 아니다 (${JSON.stringify(a0?.payload)})`);
  check(notes.some((m) => m.includes(GO1) && m.includes(EP)), `알림에 두 로봇 이름이 없다 (${notes.join(' | ')})`);
}

// ── 2. Go1 을 끌어 놓음 — 전부 Go1 ───────────────────────────────────────
{
  const { sent, logGo1, logEp, run } = await runCase({ assign: GO1 });
  const moves = moving(sent);
  check(moves.filter((s) => s.action === 'turn').length >= 8, `Go1 판에서 회전이 ${moves.length}번뿐 (${sent.map((s) => s.action).join(',')})`);
  check(moves.length > 0 && moves.every((s) => s.via === PI7), `Go1 을 끌어 놓았는데 다른 소켓으로 나갔다 (${moves.map((s) => `${s.action}@${s.via}`).join(',')})`);
  check(moves.some((s) => s.action === 'move_forward'), '접근 직진이 나가지 않았다');
  const prep = logGo1.find((r) => r.path === '/scan/prepare');
  check(prep?.body.device === GO1, `Go1 포트의 prepare 가 틀리다 ${JSON.stringify(prep?.body)}`);
  check(logEp.length === 0, `EP 포트를 두드렸다 (${logEp.map((r) => r.path).join(',')})`);
  check(run?.headingStartDeg === 30, `시작 방위가 ${run?.headingStartDeg} — Go1 의 30 이어야 한다`);
}

// ── 3. EP 를 끌어 놓음 — 전부 EP ─────────────────────────────────────────
{
  const { sent, logGo1, logEp, run } = await runCase({ assign: EP });
  const moves = moving(sent);
  check(moves.length > 8 && moves.every((s) => s.via === PI1), `EP 를 끌어 놓았는데 다른 소켓으로 나갔다 (${moves.map((s) => `${s.action}@${s.via}`).join(',')})`);
  check(logEp.find((r) => r.path === '/scan/prepare')?.body.device === EP, 'EP 포트에 prepare 가 안 닿았다');
  check(logGo1.length === 0, `Go1 포트를 두드렸다 (${logGo1.map((r) => r.path).join(',')})`);
  check(run?.headingStartDeg === -60, `시작 방위가 ${run?.headingStartDeg} — EP 의 −60 이어야 한다`);
}

// ── 4. 끌어 놓은 Go1 이 꺼짐 — EP 로 물러서지 않는다 ─────────────────────────
{
  const { sent, logEp, trace } = await runCase({ assign: GO1, offline: [GO1], waitMs: 2500 });
  check(moving(sent).length === 0 && logEp.length === 0, `끌어 놓은 Go1 이 꺼졌는데 EP 가 돌았다 (${moving(sent).map((s) => s.via).join(',')})`);
  const a0 = lastOf(trace, 'T-A0');
  check(a0?.status === 'failed' && String(a0.payload?.detail ?? '').includes(GO1), `T-A0 사유에 ${GO1} 이 없다 (${JSON.stringify(a0?.payload)})`);
}

// ── 대조: 로봇이 하나(EP 만) — 끌어 놓지 않아도 그것 ─────────────────────────
{
  const { sent, logEp, logGo1 } = await runCase({ robots: [EP] });
  const moves = moving(sent);
  check(moves.length > 8 && moves.every((s) => s.via === PI1), `EP 하나인데 그것으로 안 돌았다 (${moves.map((s) => `${s.action}@${s.via}`).join(',')})`);
  check(logEp.some((r) => r.path === '/scan/prepare') && logGo1.length === 0, 'EP 하나인데 EP 포트로 스캔하지 않았다');
}

// ── 5. 다른 임무 · 정지 버튼도 같은 규칙 (261124 — 정량 명령 · AI 생성 · 옛 문 찾기 · 정지 · 일시정지 · 재개 · 접근) ─────────
{
  const { walkingClient, missionClient } = await load('src', 'physical', 'robotClient.ts');
  const { pinMissionRobot } = await load('src', 'physical', 'missionRobot.ts');
  const { readFileSync } = await import('node:fs');
  // 걸음 고르기는 붙은 소켓만 본다 — 검사에서는 둘 다 붙은 것으로.
  for (const client of [epClient, go1Client]) client.getStatus = () => ({ state: 'open' });
  const both = () => {
    resetDevices(); resetDeviceIdentity(); resetAssignments();
    for (const [id, client, type] of [[GO1, go1Client, 'go1_robot'], [EP, epClient, 'robomaster_ep']]) {
      receiveDeviceMessage(`zoneA/robot/${id}/status`, {
        channel: 'status', status: 'online', link: 'ok', registration: { entity_id: id, entity_type: 'robot', device_type: type },
      }, client.address());
    }
  };
  both();
  const none = walkingClient();
  check(none.client === null && none.reason.includes(GO1) && none.reason.includes(EP), `로봇 둘 · 끌어 놓은 것 없음인데 걸음 대상을 골랐다 (${none.reason})`);
  assignToMilestone('MS-1', GO1);
  check(walkingClient().client === go1Client, 'Go1 을 끌어 놓았는데 정량 명령이 Go1 소켓으로 안 간다');
  both();
  assignToMilestone('MS-1', EP);
  check(walkingClient().client === epClient, 'EP 를 끌어 놓았는데 정량 명령이 EP 소켓으로 안 간다');
  // 정지 · 일시정지는 판에 박힌 로봇으로 — 첫 줄(EP)이 아니라.
  both();
  session.markStarted();
  pinMissionRobot(session.robotSession().startedAtMs, GO1);
  check(missionClient() === go1Client, `판에 박힌 Go1 이 아니라 ${missionClient().address()} 로 정지가 간다`);
  pinMissionRobot(0, null);
  check(missionClient() === epClient, '박힌 로봇도 고를 로봇도 없으면 첫 줄로 물러서야 한다');
  const stopSrc = readFileSync(join(root, 'src', 'physical', 'StopButton.tsx'), 'utf8');
  const autoSrc = readFileSync(join(root, 'src', 'physical', 'approachAuto.ts'), 'utf8');
  check(!/robotClient\(\)/.test(stopSrc) && (stopSrc.match(/missionClient\(\)/g) ?? []).length >= 4, '정지 · 일시정지 · 재개 · 접근 버튼이 아직 첫 줄(robotClient)로 낸다');
  check(!/robotClient\(\)/.test(autoSrc), '자동 접근이 아직 첫 줄(robotClient)로 낸다');
  resetAssignments();
}

// ── 6. AI 계획 장비와 움직일 장비가 다르면 경고만 (261124) ────────────────────────────
{
  const { planTargetsAway } = await load('src', 'physical', 'missionRobot.ts');
  const { readFileSync } = await import('node:fs');
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  check(same(planTargetsAway(['robot-01', 'robot-01'], GO1), []), 'robot-01 → go1-001 은 같은 장비인데 경고했다');
  check(same(planTargetsAway(['robot-01'], EP), ['robot-01']), 'robot-01 계획을 EP 가 도는데 경고하지 않았다');
  check(same(planTargetsAway(['robot-02', null, 'robot-02'], EP), ['robot-02']), '이어진 표가 없는 robot-02 를 한 번만 알려야 한다');
  check(same(planTargetsAway([EP], EP), []), '같은 이름인데 경고했다');
  const src = readFileSync(join(root, 'src', 'physical', 'robotClient.ts'), 'utf8');
  const branch = src.slice(src.indexOf('const generated = generatedRunOf('), src.indexOf('if (stepCommandsOf(stepParams)'));
  check(/planTargetsAway\(/.test(branch) && /noteIssue\('steps', 'robot', t\('grun\.targetAway'/.test(branch), 'AI 생성 갈래가 계획 장비 경고를 안 낸다');
  // 경고 뒤에 return 이 없어야 한다 — 막지 않는다.
  const after = branch.slice(branch.indexOf("t('grun.targetAway'"));
  check(/^t\('grun\.targetAway'[^\n]*\}\)\);\n\s*const missing = undeclaredActions/.test(after), '계획 장비 경고 뒤에 실행이 이어지지 않는다(막으면 안 된다)');
}

stopLink();
if (failures.length > 0) {
  console.error(`❌ verify:mission-robot 실패 ${failures.length}건`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log('✅ 통과 — 로봇 둘: 끌어 놓은 것 없으면 안 돈다(알림) · Go1 을 놓으면 회전 · 직진 · 포트 · 방위가 전부 Go1 · EP 를 놓으면 전부 EP · 놓은 로봇이 꺼지면 다른 로봇으로 안 물러선다 · AI 계획 장비가 다르면 경고만 · 정량 명령 · AI 생성 · 정지 · 일시정지 · 재개 · 접근도 끌어 놓은/판에 박힌 로봇으로 / 대조: 로봇 하나면 그대로');
process.exit(0);
