// verify:manual-control (261005 신설 — 하드웨어 카드 · 로봇 수동 제어)
//
// **로봇 수동 제어가 지시대로 막히고 · 나가는가.**
//
//  1. 탭을 띄울 장비 — 로봇만. 드론 · 고정 카메라 · 아무 말도 안 한 장비는 아니다
//  2. 키 배치 — 기본 둘(WASD+QE / 방향키+ZX) · 다른 데 쓰는 키와 같은 장비 안의 겹침은 거절 · 다른 장비와 겹침은 경고
//  3. 켜짐은 저장하지 않는다 — 키 배치만 브라우저에 남는다
//  4. 키가 명령이 안 되는 때 — 꺼짐 · 입력 중 · 자동 제어 · 연결 없음 · 조합 키 · 누르고 있기(repeat) · 키 받아 적는 중
//  5. 스텝 모드 — W 한 걸음 · Q/E 돌기(오른쪽 +) · 뒤로/옆으로는 안 나감 · Space 정지
//  6. 여러 대 — 장비마다 제 소켓으로 · 같은 키면 둘 다 움직이고 경고
//  7. 속도 모드 — `teleop` 선언 시. 바뀐 순간만 추적기 · 유지 신호는 추적기 밖 · 막히면 세움(자동 제어면 0 을 안 보냄)
//  8. 추가 동작 — 선언된 것만 칸이 뜨고, 선언된 것만 나간다
//  9. 배선 — 앱에 한 번 걸리고 · 카드가 로봇 판정을 쓰고 · 출구는 추적기
//
// 음성 대조군 포함 — 막는 조건을 풀면 실제로 나가는지 본다(검사가 늘 0 건이라 초록인 것이 아님을).

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readFileSync(join(root, ...p), 'utf8').replace(/\r\n/g, '\n');

// 브라우저 저장소 흉내 — 모듈이 부를 때마다 이 값을 본다.
const memory = new Map();
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (key) => (memory.has(key) ? memory.get(key) : null),
    setItem: (key, value) => memory.set(key, String(value)),
    removeItem: (key) => memory.delete(key),
  },
});

const mc = await load('src', 'physical', 'manualControl.ts');
const md = await load('src', 'physical', 'manualDispatch.ts');
const { noteCapability, resetDeviceIdentity } = await load('src', 'physical', 'deviceIdentity.ts');
const { commandTracker } = await load('src', 'shared', 'commandCenter.ts');
const { TELEOP_ACTION, STOP_ACTION, STOP_REASON, APPROACH_VX } = await load('src', 'physical', 'presets.ts');

const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

function fakeClient() {
  const sent = [];
  let open = true;
  return {
    sent,
    close: () => { open = false; },
    getStatus: () => ({ state: open ? 'open' : 'closed' }),
    send(action, parameters) {
      if (!open) return { sent: false, commandId: '', reason: 'closed' };
      sent.push({ action, parameters });
      return { sent: true, commandId: 'cmd-' + String(sent.length).padStart(8, '0') };
    },
  };
}

let clients = {};
let typing = false;
let auto = new Set();
function fresh() {
  mc.resetManualControl();
  md.resetManualDispatch();
  resetDeviceIdentity();
  memory.clear();
  clients = {};
  typing = false;
  auto = new Set();
  md.setManualProbes({
    client: (id) => clients[id] ?? null,
    typing: () => typing,
    auto: (id) => auto.has(id),
  });
}
const key = (code, over = {}) => md.manualKeyDown({ code, repeat: false, modified: false, ...over });

// ── 1. 탭을 띄울 장비 ─────────────────────────────────────────────────────────
{
  const no = { drone: false, fixedCamera: false };
  check(mc.isManualRobot({ kind: 'robot', actions: null }, no), 'kind=robot 인 장비를 로봇으로 안 봤다');
  check(mc.isManualRobot({ kind: null, actions: ['ping', 'move_forward'] }, no), 'move_forward 를 선언한 장비를 로봇으로 안 봤다');
  check(mc.isManualRobot({ kind: null, actions: [TELEOP_ACTION] }, no), 'teleop 을 선언한 장비를 로봇으로 안 봤다');
  check(!mc.isManualRobot({ kind: 'robot', actions: null }, { drone: true, fixedCamera: false }), '드론에 수동 제어 탭이 뜬다');
  check(!mc.isManualRobot({ kind: 'robot', actions: null }, { drone: false, fixedCamera: true }), '고정 카메라에 수동 제어 탭이 뜬다');
  check(!mc.isManualRobot(null, no), '아무 말도 안 한 장비(대본 배역)에 수동 제어 탭이 뜬다');
  check(!mc.isManualRobot({ kind: 'sensor', actions: ['ping'] }, no), '걷지 못하는 장비에 수동 제어 탭이 뜬다');
  console.log('✅ 탭 판정 — 로봇만 · 드론/고정 카메라/배역은 아니다');
}

// ── 2. 키 배치 ───────────────────────────────────────────────────────────────
{
  fresh();
  const wasd = mc.manualConfig('go1-001').motionKeys;
  check(wasd.forward === 'KeyW' && wasd.back === 'KeyS' && wasd.left === 'KeyA' && wasd.right === 'KeyD'
    && wasd.rotLeft === 'KeyQ' && wasd.rotRight === 'KeyE', '기본 배치가 WASD+QE 가 아니다');
  mc.setPreset('go1-001', 'arrows');
  const arrows = mc.manualConfig('go1-001').motionKeys;
  check(arrows.forward === 'ArrowUp' && arrows.back === 'ArrowDown' && arrows.left === 'ArrowLeft' && arrows.right === 'ArrowRight'
    && arrows.rotLeft === 'KeyZ' && arrows.rotRight === 'KeyX', '방향키+ZX 배치가 틀렸다');
  check(!mc.customized(mc.manualConfig('go1-001')), '배치를 고른 직후가 「직접 바꿈」으로 잡힌다');
  check(mc.bindKey('go1-001', { kind: 'motion', motion: 'forward' }, 'KeyI').ok, '빈 키를 못 달았다');
  check(mc.manualConfig('go1-001').motionKeys.forward === 'KeyI' && mc.customized(mc.manualConfig('go1-001')), '단 키가 반영되지 않았다');
  for (const reserved of ['Space', 'Escape', 'Tab', 'Enter', 'ShiftLeft']) {
    const result = mc.bindKey('go1-001', { kind: 'motion', motion: 'back' }, reserved);
    check(!result.ok && result.reason === 'reserved', `${reserved} 를 동작에 달 수 있다`);
  }
  const taken = mc.bindKey('go1-001', { kind: 'motion', motion: 'back' }, 'KeyZ');
  check(!taken.ok && taken.reason === 'taken' && taken.by.kind === 'motion' && taken.by.motion === 'rotLeft',
    '같은 장비의 다른 칸이 쓰는 키를 거절하지 않았다');
  check(mc.bindKey('go1-001', { kind: 'motion', motion: 'forward' }, 'KeyI').ok, '같은 칸에 같은 키를 다시 다는 것을 거절했다');
  mc.unbindKey('go1-001', { kind: 'motion', motion: 'forward' });
  check(mc.manualConfig('go1-001').motionKeys.forward === null, '떼기가 칸을 비우지 않았다');
  mc.bindKey('go1-001', { kind: 'extra', action: 'sdk_start' }, 'KeyW');
  mc.setPreset('go1-001', 'wasd');
  check(mc.manualConfig('go1-001').extraKeys.sdk_start === undefined, '새 배치와 겹치는 추가 동작 키를 떼지 않았다');
  console.log('✅ 키 배치 — 기본 둘 · 예약 키 · 같은 장비 겹침 거절 · 배치 바꾸면 겹친 추가 키 뗌');
}

// ── 3. 켜짐은 저장하지 않는다 ─────────────────────────────────────────────────
{
  fresh();
  mc.setManualEnabled('go1-001', true);
  mc.setStep('go1-001', { stepM: 0.5 });
  const saved = memory.get('vz.manual.go1-001');
  check(typeof saved === 'string' && JSON.parse(saved).stepM === 0.5, '키 배치 · 걸음 크기가 저장되지 않았다');
  check(saved !== undefined && !('enabled' in JSON.parse(saved)), '켜짐이 브라우저에 저장된다 — 새로고침하면 바로 키를 받는다');
  mc.resetManualControl();   // 새로고침 흉내 — 모듈 상태만 비우고 저장소는 둔다
  check(!mc.manualEnabled('go1-001'), '새로고침 뒤 켜진 채로 시작한다');
  check(mc.manualConfig('go1-001').stepM === 0.5, '새로고침 뒤 저장한 걸음 크기를 못 읽었다');
  mc.setStep('go1-001', { stepM: 99, stepDeg: 1 });
  check(mc.manualConfig('go1-001').stepM === mc.STEP_M_RANGE.max && mc.manualConfig('go1-001').stepDeg === mc.STEP_DEG_RANGE.min,
    '걸음 크기가 범위로 붙지 않았다');
  console.log('✅ 저장 — 배치 · 걸음은 남고 켜짐은 안 남는다 · 걸음 범위');
}

// ── 4. 키가 명령이 안 되는 때 ──────────────────────────────────────────────────
{
  fresh();
  const go1 = fakeClient();
  clients['go1-001'] = go1;
  noteCapability('go1-001', ['ping', 'turn', 'move_forward'], 'ws://go1.test:9001');

  check(key('KeyW') === false && go1.sent.length === 0, '꺼진 장비의 키를 가로챘거나 보냈다');

  mc.setManualEnabled('go1-001', true);
  typing = true;
  check(key('KeyW') === false && go1.sent.length === 0, '입력 중인데 키를 가로챘거나 보냈다');
  typing = false;

  auto.add('go1-001');
  check(key('KeyW') === true && go1.sent.length === 0, '자동 제어 중에 키가 나갔다(가로채기는 해야 화면이 안 굴러간다)');
  check(md.manualEvents()['go1-001']?.kind === 'blocked' && md.manualEvents()['go1-001'].block === 'auto', '자동 제어 막힘이 알림에 안 적혔다');
  auto.clear();

  check(key('KeyW', { modified: true }) === false && go1.sent.length === 0, 'Ctrl/Alt 와 같이 누른 키가 명령이 됐다');
  check(key('KeyW', { repeat: true }) === true && go1.sent.length === 0, '누르고 있는 반복 키가 명령이 됐다');
  mc.setKeyCapture(true);
  check(key('KeyW') === false && go1.sent.length === 0, '키를 받아 적는 중인데 명령이 됐다');
  mc.setKeyCapture(false);

  go1.close();
  check(key('KeyW') === true && go1.sent.length === 0 && md.manualEvents()['go1-001'].block === 'offline', '연결이 없는데 막힘이 안 적혔다');

  // 음성 대조군 — 막는 것을 다 풀면 실제로 나간다.
  clients['go1-001'] = fakeClient();
  check(key('KeyW') === true && clients['go1-001'].sent.length === 1, '막는 조건을 다 풀었는데 안 나갔다 — 위 0 건들이 공짜 초록이다');

  check(md.isTypingTarget({ tagName: 'input' }) && md.isTypingTarget({ tagName: 'TEXTAREA' }) && md.isTypingTarget({ tagName: 'SELECT' })
    && md.isTypingTarget({ tagName: 'DIV', isContentEditable: true }), '글 칸 판정이 틀렸다');
  check(!md.isTypingTarget({ tagName: 'BUTTON' }) && !md.isTypingTarget(null), '버튼 · 포커스 없음을 글 칸으로 봤다');
  console.log('✅ 막힘 — 꺼짐 · 입력 중 · 자동 제어 · 조합 키 · 반복 · 받아 적는 중 · 연결 없음 (대조군: 풀면 나간다)');
}

// ── 5. 스텝 모드 ─────────────────────────────────────────────────────────────
{
  fresh();
  const go1 = fakeClient();
  clients['go1-001'] = go1;
  noteCapability('go1-001', ['ping', 'turn', 'move_forward', STOP_ACTION], 'ws://go1.test:9001');
  mc.setManualEnabled('go1-001', true);
  const before = commandTracker.getSnapshot().length;
  key('KeyW'); key('KeyQ'); key('KeyE');
  check(go1.sent[0]?.action === 'move_forward' && go1.sent[0].parameters.distance_m === mc.manualConfig('go1-001').stepM
    && go1.sent[0].parameters.vx === APPROACH_VX, 'W 가 한 걸음 move_forward 가 아니다');
  check(go1.sent[1]?.action === 'turn' && go1.sent[1].parameters.deg === -15, 'Q 가 왼쪽(−) 돌기가 아니다');
  check(go1.sent[2]?.action === 'turn' && go1.sent[2].parameters.deg === 15, 'E 가 오른쪽(+) 돌기가 아니다');
  for (const code of ['KeyS', 'KeyA', 'KeyD']) key(code);
  check(go1.sent.length === 3 && md.manualEvents()['go1-001'].block === 'unsupported', '스텝 모드에서 뒤로 · 옆으로가 나갔다');
  key('Space');
  check(go1.sent[3]?.action === STOP_ACTION && go1.sent[3].parameters.reason === STOP_REASON.human, 'Space 가 abort 를 안 보냈다');
  const tracked = commandTracker.getSnapshot().slice(0, commandTracker.getSnapshot().length - before);
  check(tracked.length === 4 && tracked.every((c) => c.entity === 'go1-001'), '스텝 명령이 장비 id 로 추적기를 안 지났다');
  console.log('✅ 스텝 모드 — W 한 걸음 · Q −/E + 돌기 · 뒤/옆 안 나감 · Space 정지 · 추적기 경유');
}

// ── 6. 여러 대 ───────────────────────────────────────────────────────────────
{
  fresh();
  const a = fakeClient();
  const b = fakeClient();
  clients['go1-001'] = a;
  clients['go1-002'] = b;
  noteCapability('go1-001', ['turn', 'move_forward'], 'ws://a.test:9001');
  noteCapability('go1-002', ['turn', 'move_forward'], 'ws://b.test:9001');
  mc.setManualEnabled('go1-001', true);
  mc.setManualEnabled('go1-002', true);
  mc.setPreset('go1-002', 'arrows');
  check(mc.sharedKeys().size === 0, '배치가 다른데 겹친다고 경고한다');
  key('KeyW');
  check(a.sent.length === 1 && b.sent.length === 0, 'W 가 방향키 장비에도 나갔다');
  key('ArrowUp');
  check(a.sent.length === 1 && b.sent.length === 1, '↑ 가 방향키 장비로만 나가지 않았다');
  mc.setPreset('go1-002', 'wasd');
  key('KeyE');
  check(a.sent.length === 2 && b.sent.length === 2, '같은 키를 쓰는 두 장비가 함께 움직이지 않았다');
  check(mc.sharedKeys().get('KeyE')?.join() === 'go1-001,go1-002', '같은 키를 쓰는데 경고가 없다');
  auto.add('go1-002');
  key('KeyW');
  check(a.sent.length === 3 && b.sent.length === 2, '한 대의 자동 제어가 다른 장비의 수동 제어까지 막았다');
  console.log('✅ 여러 대 — 장비마다 제 소켓 · 같은 키면 함께 + 경고 · 막힘은 장비별');
}

// ── 7. 속도 모드 ─────────────────────────────────────────────────────────────
{
  fresh();
  const go1 = fakeClient();
  clients['go1-001'] = go1;
  noteCapability('go1-001', ['ping', TELEOP_ACTION, STOP_ACTION], 'ws://go1.test:9001');
  check(mc.manualModeOf([TELEOP_ACTION]) === 'velocity' && mc.manualModeOf(null) === 'step', '모드 판정이 틀렸다');
  mc.setManualEnabled('go1-001', true);
  const before = commandTracker.getSnapshot().length;
  key('KeyW');
  key('KeyD');
  key('KeyW', { repeat: true });
  check(go1.sent.length === 2, `누른 순간만 나가야 하는데 ${go1.sent.length} 건`);
  check(go1.sent[0].action === TELEOP_ACTION && go1.sent[0].parameters.vx === 0.3 && go1.sent[0].parameters.vy === 0, 'W 의 속도가 틀렸다');
  check(go1.sent[1].parameters.vx === 0.3 && go1.sent[1].parameters.vy === -0.2, 'W+D 의 속도가 틀렸다(오른쪽은 vy −)');
  check(typeof go1.sent[0].parameters.hold_ms === 'number', '유지 시한(hold_ms)이 안 실렸다');
  md.keepaliveTick();
  check(go1.sent.length === 3 && go1.sent[2].parameters.vy === -0.2, '유지 신호가 같은 값으로 안 나갔다');
  check(commandTracker.getSnapshot().length === before + 2, '유지 신호가 추적기를 지났다 — 실행 기록이 초당 다섯 줄씩 찬다');
  md.manualKeyUp('KeyW');
  check(go1.sent[3]?.parameters.vx === 0 && go1.sent[3].parameters.vy === -0.2, 'W 를 뗐는데 앞 속도가 안 빠졌다');
  md.manualKeyUp('KeyD');
  check(go1.sent[4]?.parameters.vx === 0 && go1.sent[4].parameters.vy === 0 && go1.sent[4].parameters.vyaw === 0, '다 뗐는데 0 을 안 보냈다');
  const after = go1.sent.length;
  md.keepaliveTick();
  check(go1.sent.length === after, '선 뒤에도 유지 신호가 나간다');
  check(mc.velocityOf(['forward', 'back']).vx === 0 && mc.velocityOf(['rotLeft']).vyaw > 0, '속도 합산이 틀렸다(반시계 +)');

  // 누른 채로 글 칸에 들어가면 0 을 보내고 선다.
  key('KeyQ');
  typing = true;
  md.keepaliveTick();
  const last = go1.sent[go1.sent.length - 1];
  check(last.parameters.vyaw === 0 && last.parameters.vx === 0, '누른 채 입력 칸에 들어갔는데 세우지 않았다');
  typing = false;

  // 누른 채로 자동 제어가 시작되면 0 을 안 보내고 유지 신호만 끊는다.
  key('KeyW');
  const count = go1.sent.length;
  auto.add('go1-001');
  md.keepaliveTick();
  check(go1.sent.length === count, '자동 제어가 넘겨받았는데 0 을 보냈다 — 임무 이동을 세울 수 있다');
  md.keepaliveTick();
  check(go1.sent.length === count, '자동 제어 뒤에도 유지 신호가 나간다');
  auto.clear();

  // 끄면 세운다.
  key('KeyW');
  mc.setManualEnabled('go1-001', false);
  md.keepaliveTick();
  check(go1.sent[go1.sent.length - 1].parameters.vx === 0, '수동 제어를 껐는데 세우지 않았다');

  // 창이 포커스를 잃으면 세운다.
  mc.setManualEnabled('go1-001', true);
  key('KeyA');
  md.haltAllManual();
  check(go1.sent[go1.sent.length - 1].parameters.vy === 0, '창이 포커스를 잃었는데 세우지 않았다');
  console.log('✅ 속도 모드 — 누른/뗀 순간만 추적기 · 유지 신호 · 입력/끄기/포커스 잃음은 0 · 자동 제어는 0 없이 끊음');
}

// ── 8. 추가 동작 ─────────────────────────────────────────────────────────────
{
  fresh();
  const extras = mc.extraActions(['ping', 'diag', 'turn', 'move_forward', TELEOP_ACTION, 'scan_mission', 'scan_continue',
    STOP_ACTION, 'abort_mission', 'sdk_auto', 'sdk_start', 'sdk_stop', 'sit_down']);
  check(extras.join() === 'sdk_start,sdk_stop,sit_down', `추가 동작 칸이 ${extras.join()}`);
  check(mc.extraActions(null).length === 0, '선언을 못 받았는데 추가 칸이 떴다');
  const go1 = fakeClient();
  clients['go1-001'] = go1;
  noteCapability('go1-001', ['move_forward', 'sit_down'], 'ws://go1.test:9001');
  mc.setManualEnabled('go1-001', true);
  check(mc.bindKey('go1-001', { kind: 'extra', action: 'sit_down' }, 'KeyR').ok, '추가 동작에 키를 못 달았다');
  key('KeyR');
  check(go1.sent[0]?.action === 'sit_down' && Object.keys(go1.sent[0].parameters).length === 0, '추가 동작이 안 나갔다');
  noteCapability('go1-001', ['move_forward'], 'ws://go1.test:9001');   // 장비가 선언을 거뒀다
  key('KeyR');
  check(go1.sent.length === 1 && md.manualEvents()['go1-001'].block === 'undeclared', '선언에서 빠진 추가 동작이 나갔다');
  console.log('✅ 추가 동작 — 이동 · 연결 확인 · 임무 · 정지 · 설정은 빼고 · 선언된 것만 나간다');
}

// ── 9. 배선 ──────────────────────────────────────────────────────────────────
{
  const main = read('src', 'main.tsx');
  check((main.match(/startManualDispatch\(\)/g) ?? []).length === 1, '키 처리기가 앱에 한 번 걸리지 않는다');
  check(/<ManualControlBadge \/>/.test(main), '우측 상단 알림이 앱에 안 붙었다');
  const overlay = read('src', 'views', 'DeviceStatusOverlay.tsx');
  check(/isManualRobot\(/.test(overlay) && /robot && tab === 'manual'/.test(overlay), '카드가 로봇 판정으로 탭을 가르지 않는다');
  const tab = read('src', 'views', 'ManualControlTab.tsx');
  check(!/addEventListener\('keydown', onKey\)(?!, true)/.test(tab) && /addEventListener\('keydown', onKey, true\)/.test(tab),
    '키 받아 적기가 capture 단계가 아니다 — Esc 가 카드 창까지 닫는다');
  const dispatch = read('src', 'physical', 'manualDispatch.ts');
  check((dispatch.match(/commandTracker\.issue\(/g) ?? []).length === 1, '수동 명령의 출구가 추적기 하나가 아니다');
  check(!/publishCommand/.test(dispatch), '수동 명령이 게이트웨이로 나간다');
  console.log('✅ 배선 — 앱에 한 번 · 알림 · 카드 로봇 판정 · capture 단계 받아 적기 · 출구는 추적기');
}

// ── 10. 장비의 거절 (261005 · pi7 답신) ──────────────────────────────────────
{
  fresh();
  const go1 = fakeClient();
  const listeners = [];
  go1.onMessage = (listener) => { listeners.push(listener); return () => undefined; };
  const reply = (message) => { for (const listener of listeners) listener(message); };
  clients['go1-001'] = go1;
  noteCapability('go1-001', [TELEOP_ACTION, STOP_ACTION], 'ws://go1.test:9001');
  mc.setManualEnabled('go1-001', true);
  key('KeyW');
  const first = go1.sent.length;
  check(listeners.length === 1, '거절을 들을 귀를 안 걸었다');
  reply({ kind: 'acceptance', commandId: 'cmd-' + String(first).padStart(8, '0'), accepted: false,
    code: 'FAILED_PRECONDITION', message: 'teleop_halted_by_abort' });
  const event = md.manualEvents()['go1-001'];
  check(event?.kind === 'rejected' && event.message === 'teleop_halted_by_abort', '장비의 거절이 알림에 안 올라왔다');
  md.keepaliveTick();
  check(go1.sent.length === first, 'teleop 이 거절됐는데 유지 신호를 계속 보낸다');
  key('KeyD');
  check(listeners.length === 1, '명령마다 귀를 새로 걸었다 — 소켓 하나에 하나여야 한다');
  reply({ kind: 'acceptance', commandId: 'cmd-99999999', accepted: false, code: 'X', message: null });
  check(md.manualEvents()['go1-001'].kind !== 'rejected' || md.manualEvents()['go1-001'].code !== 'X', '우리가 안 낸 명령의 거절을 우리 것으로 적었다');
  console.log('✅ 거절 — 장비의 Acceptance 거절을 알림에 · teleop 거절이면 유지 신호를 끊음 · 소켓에 귀 하나');
}

// ── 11. 임무의 상대 이동은 고른 장비가 선언했을 때만 (261005) ─────────────────────
{
  resetDeviceIdentity();
  const { issueStepMission } = await load('src', 'physical', 'robotCommands.ts');
  const { resetRobotSession } = await load('src', 'physical', 'robotSession.ts');
  resetRobotSession();
  const sent = [];
  const client = { address: () => 'ws://old-go1.test:9001', getStatus: () => ({ state: 'open' }),
    send: (action, parameters) => { sent.push(action); return { sent: true, commandId: 'cmd-00000001' }; }, onMessage: () => () => undefined };
  noteCapability('go1-001', ['turn', 'move_forward'], 'ws://old-go1.test:9001');
  const outcome = await issueStepMission(client, { step_commands: [{ taskId: 'T-Q1', action: 'move_relative', parameters: { dx_m: -1, dy_m: 0, v_mps: 0.3 } }] });
  check(outcome?.sent === false && sent.length === 0, '상대 이동을 선언하지 않은 장비에 move_relative 를 보냈다');
  const commands = read('src', 'physical', 'robotCommands.ts');
  check((commands.match(/noteUnreached\(/g) ?? []).length >= 3, 'reached=0 을 걸음 사이 · 마지막 걸음 둘 다에서 보지 않는다');
  console.log('✅ 상대 이동 관문 — 선언 안 한 장비에는 안 보냄 · reached=0 은 알림에');
}

// ── 12. 속도를 탭에서 정한다 (261005) ─────────────────────────────────────────
{
  fresh();
  const { TELEOP_LIMITS, TELEOP_SPEED } = await load('src', 'physical', 'presets.ts');
  const def = mc.manualConfig('go1-001').speed;
  check(def.vx === TELEOP_SPEED.vx && def.vy === TELEOP_SPEED.vy && def.vyaw === TELEOP_SPEED.vyaw, '속도 기본값이 TELEOP_SPEED 가 아니다');
  mc.setSpeed('go1-001', { vx: 9, vy: 0.01, vyaw: 0.5 });
  const speed = mc.manualConfig('go1-001').speed;
  check(speed.vx === TELEOP_LIMITS.vx.max && speed.vy === TELEOP_LIMITS.vy.min && speed.vyaw === 0.5, '속도가 pi7 상한 · 하한으로 안 묶였다');
  check(JSON.parse(memory.get('vz.manual.go1-001')).speed.vyaw === 0.5, '속도가 저장되지 않았다');
  mc.resetManualControl();
  check(mc.manualConfig('go1-001').speed.vyaw === 0.5, '새로고침 뒤 속도를 못 읽었다');

  // 속도 모드 — 정한 속도로 나가고, 누른 채로 바꾸면 다음 유지 신호에서 새 값(추적기 경유).
  const go1 = fakeClient();
  clients['go1-001'] = go1;
  noteCapability('go1-001', [TELEOP_ACTION], 'ws://go1.test:9001');
  mc.setManualEnabled('go1-001', true);
  mc.setSpeed('go1-001', { vx: 0.2 });
  key('KeyW');
  check(go1.sent[0]?.parameters.vx === 0.2, `정한 속도(0.2)가 아니라 ${go1.sent[0]?.parameters.vx} 로 나갔다`);
  const before = commandTracker.getSnapshot().length;
  mc.setSpeed('go1-001', { vx: 0.35 });
  md.keepaliveTick();
  check(go1.sent[1]?.parameters.vx === 0.35 && commandTracker.getSnapshot().length === before + 1, '누른 채 바꾼 속도가 기록과 함께 반영되지 않았다');
  md.keepaliveTick();
  check(go1.sent[2]?.parameters.vx === 0.35 && commandTracker.getSnapshot().length === before + 1, '바뀐 뒤의 유지 신호가 새 값이 아니거나 추적기를 지났다');
  md.manualKeyUp('KeyW');

  // 스텝 모드 — 한 걸음의 속도는 vx 이고, move_forward 규약(0.30)으로 한 번 더 묶인다.
  fresh();
  const step = fakeClient();
  clients['go1-001'] = step;
  noteCapability('go1-001', ['move_forward', 'turn'], 'ws://go1.test:9001');
  mc.setManualEnabled('go1-001', true);
  mc.setSpeed('go1-001', { vx: 0.4 });
  key('KeyW');
  check(step.sent[0]?.parameters.vx === mc.STEP_VX_RANGE.max, `스텝 모드 걸음 속도가 규약 0.30 을 넘었다: ${step.sent[0]?.parameters.vx}`);
  mc.setSpeed('go1-001', { vx: 0.1 });
  key('KeyW');
  check(step.sent[1]?.parameters.vx === 0.1, '스텝 모드가 정한 속도를 안 쓴다');
  console.log('✅ 속도 — 기본값 · pi7 상한으로 묶음 · 저장 · 누른 채 바꾸면 반영 · 스텝은 vx 를 규약 0.30 으로');
}

md.resetManualDispatch();
if (failures.length > 0) {
  console.error(`❌ verify:manual-control — ${failures.length}건`);
  for (const failure of failures) console.error('  · ' + failure);
  process.exit(1);
}
console.log('✅ verify:manual-control 통과');
process.exit(0);
