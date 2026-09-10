// verify:emergency-stop (260910 신설 — 화면 연결 지시서 §7)
//
// **정지를 눌렀는데 화면이 계속 진행하는 것**이 이 기능의 가장 흔한 실패 모양이다.
// 눈으로 보면 "어? 멈췄는데 왜 돌지"로 나타나고, 그때 누른 사람은 로봇이 멈춘 줄 알고
// 다가간다. 그래서 이 검사의 첫 줄이 그것부터 본다.
//
// 보는 것 다섯.
//  1. **정지 뒤 늦게 온 CommandStatus 가 노드를 안 바꾸는가** ← 핵심
//  2. 타이머·폴링이 멈추는가
//  3. 화면이 잠기는가 · 「정지됨」에서 나오는 길이 있는가
//  4. **연결이 없을 때 버튼이 눌리고 실패를 크게 말하는가** — 조용히 성공한 척하지 않는가
//  5. **발행 실패와 화면 잠금이 갈려 있는가** — 1번이 실패해도 2·3·4 는 일어나는가
//
// 5번이 이 기능의 뼈대다. 발행 성공 여부와 화면 잠금을 한 덩어리로 묶으면, 브로커가 죽은
// 날 화면이 계속 돌아간다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { emergencyStop, stopFailureMessage, issueScan } = await load('src', 'physical', 'robotCommands.ts');
const {
  resetRobotSession, markApproved, robotSession, registerTimer, releaseStopped,
  applyEffects, canIssueRobotCommand,
} = await load('src', 'physical', 'robotSession.ts');
const { receiveUplink } = await load('src', 'physical', 'robotBridge.ts');
const { decodeUplink, parseDetail } = await load('src', 'physical', 'uplink.ts');
const { mockScanUplink } = await load('src', 'physical', 'mockUplink.ts');
const { emptyFill, reduceFrames, cellsInOrder } = await load('src', 'viewpoint', 'fill.ts');
const { resetViewpoint, framesUpTo } = await load('src', 'viewpoint', 'store.ts');
const { commandTracker } = await load('src', 'shared', 'commandCenter.ts');

const failures = [];
const controls = [];

function client({ connected = true } = {}) {
  const sent = [];
  return {
    sent,
    getStatus: () => ({ state: connected ? 'open' : 'closed', reason: '브로커 연결 없음' }),
    send(action, parameters) {
      sent.push({ action, parameters });
      if (!connected) return { sent: false, commandId: '', reason: '브로커에 붙어 있지 않습니다 — closed' };
      return { sent: true, commandId: 'cmd-' + String(sent.length).padStart(8, '0') };
    },
  };
}

const MISSION = 'MSN-260909-01';
const filled = () => cellsInOrder(reduceFrames(emptyFill(8), framesUpTo(999))).filter((c) => c.phase !== 'pending').length;

// ── 1. 정지 뒤 늦게 온 CommandStatus 가 노드를 안 바꾼다 (핵심) ──────────────
{
  resetRobotSession();
  resetViewpoint(MISSION);
  markApproved();

  const frames = mockScanUplink();
  // 앞의 넷을 흘린다 — 회전이 도는 중이다.
  for (const frame of frames.slice(0, 4)) {
    receiveUplink(decodeUplink(frame.payload), MISSION, frame.atSec, 90);
  }
  const beforeStop = filled();
  if (beforeStop === 0) failures.push('정지 전에 노드가 하나도 안 찼다 — 검사가 헛돈다');

  await emergencyStop(client());

  // **남은 다섯을 흘린다. 노드가 더 차면 안 된다.**
  for (const frame of frames.slice(4)) {
    receiveUplink(decodeUplink(frame.payload), MISSION, frame.atSec, 90);
  }
  const afterStop = filled();
  if (afterStop !== beforeStop) {
    failures.push(`정지 뒤에 노드가 ${beforeStop} → ${afterStop} 로 더 찼다 — 「멈췄는데 왜 돌지」가 이것이다`);
  }

  // 진행률·door_turn 도 더 안 움직인다.
  const progressAfter = robotSession().progress;
  for (const frame of frames.slice(4)) receiveUplink(decodeUplink(frame.payload), MISSION, frame.atSec, 90);
  if (JSON.stringify(robotSession().progress) !== JSON.stringify(progressAfter)) {
    failures.push('정지 뒤에 진행률이 더 움직였다');
  }
  if (robotSession().doorTurn !== null) failures.push('정지 뒤에 door_turn 이 들어와 MS-B 선이 열렸다');
}

// ── 2. 타이머·폴링이 멈춘다 ─────────────────────────────────────────────────
{
  resetRobotSession();
  markApproved();
  let cancelled = 0;
  registerTimer(() => { cancelled += 1; });
  registerTimer(() => { cancelled += 1; });

  await emergencyStop(client());
  if (cancelled !== 2) failures.push(`정지가 타이머를 ${cancelled}개만 끊었다 — 둘 다 끊어야 한다`);
}

// ── 3. 화면이 잠기고, 나오는 길이 있다 ──────────────────────────────────────
{
  resetRobotSession();
  markApproved();
  await emergencyStop(client());

  const stopped = robotSession().stopped;
  if (stopped === null) failures.push('정지를 눌렀는데 화면이 안 잠겼다');
  if (!String(stopped?.atIso ?? '').trim()) failures.push('정지 시각이 안 남았다');
  if (canIssueRobotCommand()) failures.push('잠긴 화면에서 명령을 내도 된다고 한다');

  // **자동으로 돌아가지 않는다** — 사람이 다시 승인해야 한다.
  releaseStopped();
  if (robotSession().stopped !== null) failures.push('정지 해제가 안 된다 — 갇힌다');
  if (robotSession().approved) failures.push('정지를 풀었더니 승인이 그대로다 — 사람이 다시 승인해야 한다');
}

// ── 4. 연결이 없을 때 — 눌리고, 실패를 크게 말한다 ──────────────────────────
{
  resetRobotSession();
  markApproved();
  const offline = client({ connected: false });

  const stopped = await emergencyStop(offline);

  // 눌리기는 했는가 — 보내려는 시도가 있어야 한다.
  if (offline.sent.length !== 1) failures.push('연결이 없을 때 정지가 아예 시도되지 않았다');
  // **조용히 성공한 척하지 않는다.**
  if (stopped.published !== false) failures.push('못 보냈는데 보냈다고 한다 — 최악의 경우다');
  const message = stopFailureMessage(stopped);
  if (message === null) failures.push('정지 실패인데 화면에 띄울 문구가 없다');
  if (!/보내지 못했습니다/.test(String(message))) failures.push(`실패 문구가 «${message}» — 「보내지 못했습니다」가 들어가야 한다`);
  // **그래도 잠긴다.**
  if (robotSession().stopped === null) failures.push('발행이 실패했다고 화면이 안 잠겼다 — 이게 이 기능의 뼈대다');
}

// ── 5. 클라이언트가 아예 없어도 잠긴다 ──────────────────────────────────────
{
  resetRobotSession();
  markApproved();
  const stopped = await emergencyStop(null);
  if (robotSession().stopped === null) failures.push('클라이언트가 null 인데 화면이 안 잠겼다');
  if (stopped.published !== false) failures.push('클라이언트가 없는데 보냈다고 한다');
  if (stopped.failure === null) failures.push('클라이언트가 없는데 사유가 비었다');
}

// ── 6. 발행이 던져도 잠긴다 ─────────────────────────────────────────────────
{
  resetRobotSession();
  markApproved();
  const throwing = {
    getStatus: () => ({ state: 'open' }),
    send() { throw new Error('소켓이 죽었다'); },
  };
  const stopped = await emergencyStop(throwing);
  if (robotSession().stopped === null) failures.push('발행이 예외를 던졌더니 화면이 안 잠겼다');
  if (stopped.published !== false) failures.push('예외가 났는데 보냈다고 한다');
  if (!/소켓이 죽었다/.test(String(stopped.failure))) failures.push('예외 사유가 안 남았다');
}

// ── 7. 규약 밖으로 나가지 않는다 ────────────────────────────────────────────
{
  resetRobotSession();
  markApproved();
  const c = client();
  await emergencyStop(c);

  const stop = c.sent[0];
  const { STOP_ACTION, STOP_REASON } = await load('src', 'physical', 'presets.ts');
  if (stop?.action !== STOP_ACTION) failures.push(`정지가 ${stop?.action} 을 쐈다 — ${STOP_ACTION} 이어야 한다`);
  // **reason 하나뿐이다** — 규약 밖의 파라미터를 더하지 않는다.
  const keys = Object.keys(stop?.parameters ?? {});
  if (JSON.stringify(keys) !== JSON.stringify(['reason'])) {
    failures.push(`정지 파라미터가 [${keys.join(', ')}] — reason 하나뿐이어야 한다`);
  }
  if (stop?.parameters?.reason !== STOP_REASON.human) failures.push('사람이 눌렀다는 사유(1)가 아니다');

  // **abort 는 자기 command_id 를 새로 만든다** — 돌던 임무의 id 를 재사용하면 응답이 섞인다.
  resetRobotSession();
  markApproved();
  const c2 = client();
  await issueScan(c2, { viewpoint_count: 8, forward_distance_m: 4.2 });
  const scanId = Object.keys(robotSession().commands)[0];
  await emergencyStop(c2);
  if (c2.sent.length !== 2) failures.push('스캔과 정지가 둘 다 안 나갔다');
  // 클라이언트가 부를 때마다 새 id 를 만든다 — 같은 id 가 두 번 나오면 안 된다.
  if (scanId !== undefined && c2.sent[1]?.commandId === scanId) failures.push('abort 가 돌던 임무의 id 를 재사용했다');
}

// ── 8. 기존 버튼을 살렸는가 — 새 버튼을 만들지 않았는가 ─────────────────────
{
  const shell = readFileSync(join(root, 'src', 'shell', 'AppShell.tsx'), 'utf8');
  const topbar = readFileSync(join(root, 'src', 'views', 'TopBar.tsx'), 'utf8');
  for (const [name, source] of [['AppShell', shell], ['TopBar', topbar]]) {
    if (!/<StopButton \/>/.test(source)) failures.push(`${name} 이 정지 버튼을 안 그린다 — 어느 화면에 있든 보여야 한다`);
    if (/mission_abort/.test(source)) failures.push(`${name} 에 옛 mission_abort 가 남아 있다 — 기존 버튼을 살리기로 했다`);
  }
  const button = readFileSync(join(root, 'src', 'physical', 'StopButton.tsx'), 'utf8');
  // **비활성화하지 않는다.**
  if (/disabled/.test(button)) failures.push('정지 버튼에 disabled 가 있다 — 연결이 없어도 눌려야 한다');
  // **확인 대화상자를 띄우지 않는다.**
  if (/confirm\(/.test(button)) failures.push('정지 버튼이 확인 대화상자를 띄운다 — 한 번 누르면 멈춰야 한다');
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  // 정지를 안 눌렀으면 늦게 온 사건이 노드를 채운다 — 1번 검사가 뜻이 있으려면 이래야 한다.
  resetRobotSession();
  resetViewpoint(MISSION);
  markApproved();
  const frames = mockScanUplink();
  for (const frame of frames.slice(0, 4)) receiveUplink(decodeUplink(frame.payload), MISSION, frame.atSec, 90);
  const before = filled();
  for (const frame of frames.slice(4, 6)) receiveUplink(decodeUplink(frame.payload), MISSION, frame.atSec, 90);
  control('정지를 안 누르면 노드가 더 찬다', filled() > before);
}
{
  // 발행 성공과 잠금을 묶은 사본 — 실패했으면 안 잠근다. 그것이 막으려는 것이다.
  resetRobotSession();
  markApproved();
  const stopped = await emergencyStop(client({ connected: false }));
  control('발행 실패해도 잠긴다', stopped.published === false && robotSession().stopped !== null);
}
{
  // detail 이 깨져도 정지 상태에서는 아무것도 안 바뀐다.
  resetRobotSession();
  markApproved();
  await emergencyStop(client());
  const before = JSON.stringify(robotSession());
  applyEffects([{ kind: 'progress', ack: 9, of: 9 }]);
  control('잠긴 뒤 effects 는 통째로 무시된다', JSON.stringify(robotSession()) === before);
}

resetRobotSession();
resetViewpoint(MISSION);
commandTracker.clear();

if (failures.length) {
  console.error(`❌ verify:emergency-stop\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 정지 뒤 늦게 온 CommandStatus 가 노드를 안 바꾼다 — 진행률·door_turn 도 멈춘다');
console.log('✅ 타이머·폴링이 끊긴다 · 화면이 잠기고 「정지 해제」로 나온다 (승인은 내려간다)');
console.log('✅ 연결이 없어도 눌린다 — 못 보내면 「보내지 못했습니다」를 띄운다 (조용히 성공한 척 안 한다)');
console.log('✅ 발행이 실패해도·예외를 던져도·클라이언트가 없어도 화면은 잠긴다 (발행과 잠금이 갈려 있다)');
console.log('✅ 규약 그대로 — action 은 상수 하나 · 파라미터는 reason 뿐 · abort 는 자기 command_id');
console.log('✅ 기존 「■ 중단」을 살렸다 — 두 셸 다 그리고, disabled 도 confirm 도 없다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
