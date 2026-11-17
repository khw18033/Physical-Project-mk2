// verify:arm-keys (261117 신설 — 로봇팔 MT4 키보드 제어)
//
// **키가 팔 명령이 되는 규칙** (`src/physical/armKeys.ts`).
//
//  1. 키 표 — W/S x± · A/D y± · R/F z± 가 상대 직교 이동(relative=1) 한 걸음, Q/E 가 4번 관절 조그 ∓/± 가 되는가.
//     걸음 크기 · 속도가 실리는가. (직교 `a` 는 펌웨어가 답하지 않는다 — 261117 실측)
//  2. 누르고 있으면 — 보내는 중에는 키 반복이 걸음을 겹쳐 내지 않고, 앞 걸음이 끝나면 다음 걸음이 나가는가. 떼면 멈추는가
//  3. 거절 — 거절되면 누른 키를 놓은 것으로 쳐서 더 안 보내는가
//  4. 도구 · 정지 — Z/X 그리퍼 1/2, 1·2·3 펌프, H 원점 복귀, Space 는 stop. 도구는 키 반복에 다시 안 나간다
//  5. 안 가로채는 때 — 꺼짐 · 글 칸 · 조합 키
//  6. MT4 상태 본문으로 팔 판정 · 버튼 열림
//  7. 연속 방식 — 누른 키의 합이 속도가 되고, 바뀔 때만 추적기로 내고, 같은 값은 유지 신호(200ms)로 잇고,
//     떼면 0 을 내고 유지 신호가 멎는가. 거절되면 유지 신호를 끊는가. 방식을 바꾸면 흐르던 이동을 세우는가
//  8. 상단 비상 정지 — 붙은 팔마다 `stop` 을 내는가(Go1 의 `abort` 가 아니다). Go1 에는 안 낸다
//  9. 연결 관리 로봇 줄 — MT4 의 `serial_ok` 가 내부 링크가 되어 ✓ 인가. 브로커마다 그 브로커의 장비를 보는가
//
// 대조군 — 수문(actuator, arm_state 없음)은 팔이 아니다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const keys = await load('src', 'physical', 'armKeys.ts');
const arm = await load('src', 'physical', 'armControl.ts');
const tel = await load('src', 'shared', 'deviceTelemetry.ts');
const rows = await load('src', 'shared', 'stateRows.ts');
const ident = await load('src', 'physical', 'deviceIdentity.ts');
const devState = await load('src', 'physical', 'deviceState.ts');
const check8 = await load('src', 'shared', 'connectionCheck.ts');
const facts = await load('src', 'physical', 'robotFacts.ts');

const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const ID = 'mt4-01';

// 흉내 — 보낸 명령을 적고, 답(수락/거절)은 검사가 정할 때 준다.
const sent = [];
let answer = 'accept';
const waiting = [];
keys.setArmKeysIssuer((deviceId, action, parameters) => new Promise((resolve) => {
  sent.push({ deviceId, action, parameters });
  waiting.push(() => resolve({ sent: true, commandId: `c${sent.length}`, accepted: answer === 'accept', message: '' }));
}));
const answerAll = async () => { while (waiting.length > 0) waiting.shift()(); await tick(); await tick(); };
const down = (code, repeat = false, modified = false, typing = false) => keys.armKeyDown({ code, repeat, modified }, typing);

// ── 1. 키 표 ────────────────────────────────────────────────────────────
{
  const config = { stepMm: 10, stepDeg: 15, speed: null };
  const expect = {
    // `a: 0` — 손목을 그대로 둔다(빼면 노드가 손목을 0° 로 되돌린다 · 261117 실측)
    forward: ['move_cart', { x: 10, a: 0, relative: 1 }], back: ['move_cart', { x: -10, a: 0, relative: 1 }],
    left: ['move_cart', { y: 10, a: 0, relative: 1 }], right: ['move_cart', { y: -10, a: 0, relative: 1 }],
    up: ['move_cart', { z: 10, a: 0, relative: 1 }], down: ['move_cart', { z: -10, a: 0, relative: 1 }],
    rotLeft: ['jog_joint', { joint: 4, delta_deg: -15 }], rotRight: ['jog_joint', { joint: 4, delta_deg: 15 }],
  };
  for (const [motion, [action, params]] of Object.entries(expect)) {
    const got = keys.stepCommand(motion, config);
    check(got.action === action && JSON.stringify(got.parameters) === JSON.stringify(params),
      `${motion}: ${got.action} ${JSON.stringify(got.parameters)} ≠ ${action} ${JSON.stringify(params)}`);
  }
  check(keys.stepCommand('up', { ...config, speed: 800 }).parameters.speed === 800, '속도를 정했으면 실려야 한다');
  const seen = new Set([...Object.values(keys.ARM_MOTION_KEYS), ...Object.values(keys.ARM_TOOL_KEYS), keys.ARM_STOP_KEY]);
  check(seen.size === keys.ARM_MOTIONS.length + keys.ARM_TOOLS.length + 1, '키 표에 겹치는 키가 있다');
}

// ── 5. 꺼져 있으면 안 가로챈다 ──────────────────────────────────────────
check(down('KeyW') === false, '꺼져 있는데 W 를 가로챘다');
check(sent.length === 0, '꺼져 있는데 보냈다');

keys.setArmKeysEnabled(ID, true);
keys.setArmKeyConfig(ID, { stepMm: 5 });

// ── 2. 누르고 있으면 ────────────────────────────────────────────────────
{
  check(down('KeyW') === true, '켜졌는데 W 를 안 가로챘다');
  for (let i = 0; i < 10; i++) down('KeyW', true);
  check(sent.length === 1, `보내는 중의 키 반복이 걸음을 겹쳐 냈다 (${sent.length}건)`);
  check(sent[0]?.action === 'move_cart' && sent[0]?.parameters.x === 5 && sent[0]?.parameters.relative === 1, `첫 걸음이 틀렸다: ${JSON.stringify(sent[0])}`);
  await answerAll();
  check(sent.length === 2, `앞 걸음이 끝났는데 다음 걸음이 안 나갔다 (${sent.length}건)`);
  keys.armKeyUp('KeyW');
  await answerAll();
  check(sent.length === 2, `키를 뗐는데 걸음이 또 나갔다 (${sent.length}건)`);
}

// ── 3. 거절 ─────────────────────────────────────────────────────────────
{
  sent.length = 0;
  answer = 'reject';
  down('KeyR');
  await answerAll();
  for (let i = 0; i < 5; i++) down('KeyR', true);
  await answerAll();
  check(sent.length === 1, `거절된 뒤에도 누른 키로 계속 보냈다 (${sent.length}건)`);
  keys.armKeyUp('KeyR');
  answer = 'accept';
}

// ── 4. 도구 · 정지 ──────────────────────────────────────────────────────
{
  sent.length = 0;
  down('KeyZ'); await answerAll();
  down('KeyZ', true); await answerAll();
  down('KeyX'); await answerAll();
  down('Digit1'); await answerAll();
  down('Digit3'); await answerAll();
  down('KeyH'); await answerAll();
  down('KeyH', true); await answerAll();
  down('Space'); await answerAll();
  const got = sent.map((item) => `${item.action}:${item.parameters?.mode ?? ''}`).join(' ');
  check(got === 'gripper:1 gripper:2 pump:1 pump:0 home: stop:', `도구 · 정지 명령이 틀렸다: ${got}`);
}

// ── 5. 글 칸 · 조합 키 ──────────────────────────────────────────────────
{
  sent.length = 0;
  check(down('KeyW', false, false, true) === false, '글 칸에서 W 를 가로챘다');
  check(down('KeyW', false, true) === false, 'Ctrl+W 를 가로챘다');
  check(sent.length === 0, '글 칸 · 조합 키에서 보냈다');
}

// ── 6. 팔 판정 · 버튼 ───────────────────────────────────────────────────
{
  // pi6 실측 본문 (261117)
  const body = { channel: 'state', actuator_state: 'error', arm_state: 'Alarm', homed: false, joints_deg: null, tcp: null, pump_pwm: 0, serial_ok: true, control_locked: false, device_status: 'degraded' };
  tel.noteDeviceTelemetry(ID, rows.stateRows(body), { body });
  check(arm.isArmDevice(null, ID) === true, 'MT4 상태 본문인데 팔로 안 봤다');
  const view = arm.armView(ID);
  const open = ['home', 'jog_joint', 'move_cart', 'pump', 'stop', 'resume', 'reset'].filter((a) => arm.armReady(a, view)).join(' ');
  check(open === 'home stop reset', `Alarm 에서 열린 버튼이 틀렸다: ${open}`);
  check(arm.armReady('move_cart', { ...view, armState: 'Idle' }) === true, 'Idle 인데 이동이 닫혔다');
  check(arm.armReady('resume', { ...view, armState: 'Hold:0' }) === true, 'Hold:0 인데 재개가 닫혔다');
  // 대조군 — 수문
  const gate = { channel: 'state', device_status: 'ok', actuator_state: 'idle', opening_pct: 0 };
  tel.noteDeviceTelemetry('gate-01', rows.stateRows(gate), { body: gate });
  check(arm.isArmDevice(null, 'gate-01') === false, '대조군: 수문을 팔로 봤다');
}

// ── 7. 연속 방식 ────────────────────────────────────────────────────────
{
  keys.resetArmKeys();
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const issued = [];
  const kept = [];
  let keepReject = null;
  keys.setArmKeysIssuer(async (deviceId, action, parameters) => {
    issued.push({ action, parameters });
    return { sent: true, commandId: `j${issued.length}`, accepted: answer === 'accept', message: '' };
  }, (deviceId, parameters, onReject) => { kept.push(parameters); if (keepReject !== null) onReject(keepReject); });
  answer = 'accept';
  const cfg = { mode: 'jog', stepMm: 10, stepDeg: 10, speed: null, jogMmS: 20, jogDegS: 30 };
  const v = keys.jogVelocity(['forward', 'left', 'rotRight'], cfg);
  check(v.vx === 20 && v.vy === 20 && v.vz === 0 && v.vj4 === 30, `속도 합이 틀렸다: ${JSON.stringify(v)}`);
  const opposite = keys.jogVelocity(['forward', 'back'], cfg);
  check(opposite.vx === 0, '반대 키를 같이 누르면 그 축은 0 이어야 한다');

  keys.setArmKeysEnabled(ID, true);
  keys.setArmKeyConfig(ID, { mode: 'jog', jogMmS: 20 });
  down('KeyW');
  for (let i = 0; i < 5; i++) down('KeyW', true);
  await tick();
  check(issued.length === 1 && issued[0].action === 'jog' && issued[0].parameters.vx === 20 && issued[0].parameters.hold_ms > 0,
    `누른 순간 jog 한 건이어야 한다: ${JSON.stringify(issued)}`);
  await sleep(keys.JOG_KEEPALIVE_MS * 2 + 80);
  check(kept.length >= 2 && kept.every((p) => p.vx === 20), `유지 신호가 같은 값으로 이어지지 않았다: ${JSON.stringify(kept)}`);
  down('KeyA'); await tick();
  check(issued.length === 2 && issued[1].parameters.vy === 20 && issued[1].parameters.vx === 20, '키를 더 누르면 바뀐 속도를 내야 한다');
  keys.armKeyUp('KeyW'); keys.armKeyUp('KeyA'); await tick();
  const last = issued.at(-1);
  check(last.parameters.vx === 0 && last.parameters.vy === 0 && last.parameters.vz === 0 && last.parameters.vj4 === 0, `다 떼면 0 을 내야 한다: ${JSON.stringify(last)}`);
  const keptAfter = kept.length;
  await sleep(keys.JOG_KEEPALIVE_MS * 2 + 80);
  check(kept.length === keptAfter, '다 뗐는데 유지 신호가 이어졌다');

  // 거절 — 노드가 jog 를 모른다
  issued.length = 0; kept.length = 0;
  answer = 'reject';
  down('KeyR'); await tick(); await tick();
  for (let i = 0; i < 5; i++) down('KeyR', true);
  await sleep(keys.JOG_KEEPALIVE_MS * 2 + 80);
  check(issued.length === 1 && kept.length === 0, `거절 뒤에도 보냈다 (issue ${issued.length} · 유지 ${kept.length})`);
  keys.armKeyUp('KeyR');
  answer = 'accept';

  // 유지 신호가 거절되면 끊는다
  issued.length = 0; kept.length = 0;
  keepReject = 'out_of_range';
  down('KeyF'); await tick();
  await sleep(keys.JOG_KEEPALIVE_MS * 3 + 80);
  check(kept.length === 1, `유지 신호가 거절된 뒤에도 이어졌다 (${kept.length}건)`);
  keys.armKeyUp('KeyF');
  keepReject = null;

  // 방식을 바꾸면 흐르던 이동을 세운다
  issued.length = 0;
  down('KeyD'); await tick();
  keys.setArmKeyConfig(ID, { mode: 'step' }); await tick();
  const stopJog = issued.at(-1);
  check(issued.length === 2 && stopJog.action === 'jog' && stopJog.parameters.vy === 0, `방식을 바꿨는데 연속 이동을 안 세웠다: ${JSON.stringify(issued)}`);
  keys.armKeyUp('KeyD');
}

// ── 8. 상단 비상 정지 ───────────────────────────────────────────────────
{
  keys.resetArmKeys();
  ident.resetDeviceIdentity();
  const issued = [];
  keys.setArmKeysIssuer(async (deviceId, action) => { issued.push(`${deviceId}:${action}`); return { sent: true, commandId: 'x', accepted: true, message: '' }; });
  const PI6 = 'ws://pi6:9001/mqtt';
  const PI7 = 'ws://pi7:9001/mqtt';
  ident.noteDeviceReport(ID, 'actuator', { registration: { entity_id: ID, entity_type: 'actuator', device_type: 'wlkata_mt4' }, status: 'online' }, PI6);
  ident.noteDeviceReport('go1-001', 'robot', { registration: { entity_id: 'go1-001', entity_type: 'robot' }, status: 'online' }, PI7);
  const stopped = keys.stopAllArms();
  await tick();
  check(JSON.stringify(stopped) === JSON.stringify([ID]), `정지를 낸 팔이 틀렸다: ${JSON.stringify(stopped)}`);
  check(JSON.stringify(issued) === JSON.stringify([`${ID}:stop`]), `상단 정지가 팔에 stop 을 안 냈거나 Go1 에도 냈다: ${JSON.stringify(issued)}`);
  keys.setArmKeysIssuer(null);

  // ── 9. 연결 관리 로봇 줄 ─────────────────────────────────────────────
  devState.resetDevices();
  devState.receiveDeviceMessage(`zoneA/actuator/${ID}/status`, { status: 'online', device_status: 'ok', serial_ok: true }, PI6);
  devState.receiveDeviceMessage('zoneA/robot/go1-001/status', { status: 'online', device_status: 'ok', link: 'lost' }, PI7);
  check(devState.deviceState(ID)?.link === 'ok', `serial_ok 가 내부 링크가 안 됐다: ${devState.deviceState(ID)?.link}`);
  devState.receiveDeviceMessage(`zoneA/actuator/${ID}/state`, { serial_ok: false }, PI6);
  check(devState.deviceState(ID)?.link === 'serial_lost', '시리얼이 끊겼는데 내부 링크가 ok 로 남았다');
  devState.receiveDeviceMessage(`zoneA/actuator/${ID}/state`, { serial_ok: true }, PI6);
  const probe = { getStatus: () => ({ state: 'open' }), connect: async () => ({ state: 'open' }), ping: async () => ({ ok: true, roundTripMs: 5 }), identity: async () => null };
  const lines = await check8.checkPhysicalAll([{ probe, address: PI6 }, { probe, address: PI7 }], facts.robotFacts);
  const robot6 = lines.find((row) => row.id === `robot@${PI6}`);
  const robot7 = lines.find((row) => row.id === `robot@${PI7}`);
  check(robot6?.ok === true, `pi6 로봇 줄이 ✓ 가 아니다: ${JSON.stringify(robot6)}`);
  // 대조군 — pi7 은 Go1 의 link 가 lost 라 ✕. 줄마다 제 장비를 본다는 증거
  check(robot7?.ok === false, `대조군: pi7 로봇 줄이 Go1(link lost)로 칠해지지 않았다: ${JSON.stringify(robot7)}`);
  devState.resetDevices();
  ident.resetDeviceIdentity();
}

keys.resetArmKeys();
keys.setArmKeysIssuer(null);

if (failures.length > 0) {
  console.error('❌ verify:arm-keys');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}
console.log('✅ verify:arm-keys — 키 표 · 누르고 있기 · 거절 · 도구/정지 · 안 가로챔 · 팔 판정 · 연속 방식 · 상단 정지 · 로봇 줄');
