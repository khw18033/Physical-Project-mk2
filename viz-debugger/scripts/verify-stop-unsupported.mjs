// verify:stop-unsupported (260921 신설 — 드론 연결 2단계)
//
// **정지를 선언하지 않은 장비에 정지를 쏘지 않는가. 대신 무엇을 하라고 말하는가.**
//
// 드론은 `Capability` 에 `ping` 하나만 선언한다(계약 §4). 정지는 **조종기의 일**이다.
// 그런데 머리줄의 ■ 정지는 늘 떠 있고, 무대에서 누군가 그것을 누른다. 그때 화면이
// 「거절당했습니다 UNIMPLEMENTED」를 적으면 누른 사람은 그것을 「실패했지만 시도는 했다」로
// 읽고 기다린다. 필요한 말은 **「조종기로 멈추세요」**이고, 그 말이 늦으면 안 된다.
//
// 보는 것 다섯.
//  1. 선언 안 한 장비면 **한 바이트도 안 나간다**
//  2. 그때 **화면은 그대로 잠긴다** — 사람이 눌렀으면 멈춘 것으로 다룬다
//  3. 안내 문구가 조종기를 가리킨다
//  4. 선언한 장비(Go1)는 **그대로 나간다** — 회귀가 없다
//  5. **목록을 못 받았으면 보낸다** — 「모른다」를 「없다」로 읽지 않는다
//
// 5번이 요점이다. `Capability` 는 retained 가 아니라 늦게 붙으면 못 받는다(계약 §11-4).
// 못 받은 것을 「지원 안 함」으로 읽으면 **멈출 수 있는 로봇 앞에서 못 멈춘다고 말한다.**

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DRONE, REJECT_ARM_HEX, bytes } from './lib/droneFixtures.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { emergencyStop, stopSupport, stopFailureMessage } = await load('src', 'physical', 'robotCommands.ts');
const { noteCapability, resetDeviceIdentity } = await load('src', 'physical', 'deviceIdentity.ts');
const { resetRobotSession, robotSession, setConnection } = await load('src', 'physical', 'robotSession.ts');
const { STOP_ACTION } = await load('src', 'physical', 'presets.ts');
const { decodeUplink } = await load('src', 'physical', 'uplink.ts');
const { ko } = await load('src', 'i18n', 'ko.ts');

const failures = [];
const controls = [];

function client() {
  const sent = [];
  return {
    sent,
    getStatus: () => ({ state: 'open' }),
    send(action, parameters) {
      sent.push({ action, parameters });
      return { sent: true, commandId: 'cmd-00000001' };
    },
  };
}

function fresh() {
  resetRobotSession();
  resetDeviceIdentity();
  setConnection({ state: 'open' });
}

// ── 1·2·3. 선언 안 한 장비 — 안 쏘고, 잠그고, 조종기를 가리킨다 ─────────────
{
  fresh();
  // 드론이 실제로 보내는 그대로 — `ping` 하나다 (계약 §4).
  noteCapability(DRONE.entityId, ['ping']);
  if (stopSupport() !== 'no') failures.push(`선언 안 한 정지를 ${stopSupport()} 로 읽었다`);

  const c = client();
  const stopped = await emergencyStop(c);
  if (c.sent.length !== 0) failures.push(`정지를 선언 안 했는데 ${c.sent.length}건이 나갔다`);
  if (stopped === null) failures.push('화면이 안 잠겼다');
  if (robotSession().stopped === null) failures.push('세션이 「정지됨」이 아니다 — 누른 사람은 멈춘 줄 안다');
  if (stopped?.published !== false) failures.push('안 보냈는데 보냈다고 적었다');
  const words = stopFailureMessage(stopped);
  if (!words) failures.push('크게 띄울 문구가 없다');
  // 문구가 **무엇을 하라고** 말하는가. 실패만 알리면 사람은 다시 누른다.
  if (!ko['robot.stopUnsupported'].includes('조종기')) failures.push('안내가 조종기를 가리키지 않는다');
}

// ── 4. 선언한 장비는 그대로 나간다 (Go1 회귀) ───────────────────────────────
{
  fresh();
  noteCapability('go1-001', ['ping', 'diag', STOP_ACTION]);
  if (stopSupport() !== 'yes') failures.push(`선언한 정지를 ${stopSupport()} 로 읽었다`);
  const c = client();
  const stopped = await emergencyStop(c);
  if (c.sent.length !== 1) failures.push(`정지가 ${c.sent.length}건 나갔다 — 하나여야 한다`);
  if (c.sent[0]?.action !== STOP_ACTION) failures.push(`나간 action 이 ${c.sent[0]?.action}`);
  if (stopped?.published !== true) failures.push('보냈는데 안 보냈다고 적었다');
}

// ── 5. 목록을 못 받았으면 보낸다 ─────────────────────────────────────────────
//
// **Go1 의 평소 모습이 이것이다.** `Capability` 가 retained 가 아니라 웹이 대개 못 받는다.
// 여기서 안 보내면 오늘까지 되던 정지가 내일 안 된다.
{
  fresh();
  if (stopSupport() !== 'unknown') failures.push(`아무 말도 못 들었는데 ${stopSupport()} 로 단언했다`);
  const c = client();
  await emergencyStop(c);
  if (c.sent.length !== 1) failures.push('목록을 모른다고 정지를 안 보냈다 — 못 멈추는 것보다 낫다');
}

// ── 6. 쏴 봐서 거절당했으면 그것도 장비가 한 말이다 ─────────────────────────
//
// 260910 에 이미 있던 길이다 — `UNIMPLEMENTED` 를 기억해 두는 것. `Capability` 를 못 받는
// 장비에서도 **두 번째부터는** 안 쏘고 안내할 수 있다.
{
  fresh();
  // 계약 §6 의 실측 거절 — `acceptance{rejection{UNIMPLEMENTED}}`, `result` 는 안 온다.
  const reject = decodeUplink(bytes(REJECT_ARM_HEX));
  if (reject?.kind !== 'acceptance') failures.push('실측 거절을 못 뜯었다');
  if (reject?.code !== 'UNIMPLEMENTED') failures.push(`거절 코드가 ${reject?.code}`);

  const { applyEffects } = await load('src', 'physical', 'robotSession.ts');
  const { recordCommand } = await load('src', 'physical', 'robotSession.ts');
  recordCommand({
    taskId: 'T-A3', commandId: 'cmd-00000009', requestId: null, state: 'issued', code: null, message: null,
    result: {}, issuedAtIso: new Date().toISOString(), parameters: {}, log: [], action: STOP_ACTION,
  });
  applyEffects([{ kind: 'task-failed', taskId: 'T-A3', commandId: 'cmd-00000009', code: 'UNIMPLEMENTED', message: 'action not supported' }]);
  if (robotSession().unsupported[STOP_ACTION] !== true) failures.push('거절을 기억하지 않았다');
  if (stopSupport() !== 'no') failures.push('거절당한 적이 있는데 또 쏘려 한다');
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name}`);
  controls.push(name);
}
{
  fresh();
  noteCapability(DRONE.entityId, ['ping']);
  control('선언 안 한 장비는 no', stopSupport() === 'no');
  resetDeviceIdentity();
  control('아무 말도 못 들으면 unknown', stopSupport() === 'unknown');
  noteCapability(DRONE.entityId, ['ping', STOP_ACTION]);
  control('선언하면 yes', stopSupport() === 'yes');
}
{
  // 연결이 없어도 버튼은 눌린다 — 260910 부터의 규칙이고 안 바뀌었다.
  fresh();
  const stopped = await emergencyStop(null);
  control('연결이 없어도 화면은 잠긴다', stopped !== null && robotSession().stopped !== null);
}

resetDeviceIdentity();
resetRobotSession();

if (failures.length) {
  console.error(`❌ verify:stop-unsupported\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 정지를 선언 안 한 장비에는 한 바이트도 안 나간다 — 화면은 그대로 잠기고 조종기를 가리킨다');
console.log('✅ 선언한 장비(Go1)는 그대로 나간다 · 목록을 못 받았으면 보낸다 (모름 ≠ 없음)');
console.log('✅ 실측 UNIMPLEMENTED 거절을 기억해 두 번째부터는 안 쏜다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
