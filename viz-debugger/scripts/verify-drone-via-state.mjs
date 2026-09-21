// verify:drone-via-state (260921 신설 — 드론 연결 2단계)
//
// **드론 상태가 백엔드 `/state` 로 들어오고, MQTT 직통으로는 안 들어오는가.**
//
// 경로가 둘이면 「어느 쪽이 진짜냐」가 생긴다. 한쪽만 고쳐지는 날 화면은 **연결됨인데 값만
// 옛것**이 되고, 그 실패는 어느 쪽을 봐야 하는지조차 알기 어렵다. 그래서 상태는 한 길이다.
//
//   연결 관리 (브로커·장비·FC 링크)   pi3 브로커에 MQTT 직통 — `ping` 과 `Capability`
//   드론 상태 (배터리·arm·비행 모드)   백엔드 `/state` — 계약 봉투
//
// 보는 것 넷.
//  1. `/state` 봉투 한 건이면 **「레지스트리에 없는 개체」 구획에 x500-001 이 뜬다** ← 첫 목표
//  2. 그 구획은 **상태를 판정하지 않는다** — 받은 것을 그대로 적는다
//  3. MQTT 장비 상태 경로가 드론 본문을 **안 뜯는다** — 두 번째 경로를 안 만든다
//  4. 상태 구독이 두 번째 칸을 `+` 로 받는다 — `zoneA/robot/…` 을 박으면 드론이 안 보인다
//
// 4번은 계약 §3-1 과 §11-1 이 둘 다 못박은 것이다. 드론의 etype 은 `robot` 이 아니라 `drone` 이다.

import { readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isScratchPath } from './lib/scratch.mjs';
// 자리표에 줄바꿈이 들어간다 — **LF 로 정규화한 원본**에서 만든다 (`verify:crlf-safe`).
import { readSource } from './lib/source.mjs';
import { DRONE, droneStateEnvelope, liveStateBody, stateBody } from './lib/droneFixtures.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { DataStore } = await load('src', 'tabs', 'data', 'store.ts');
const { RENDER_MERGE_WINDOW_MS } = await load('src', 'tabs', 'data', 'constants.ts');
const { applyDeviceMessage } = await load('src', 'physical', 'deviceState.ts');

const failures = [];
const controls = [];

// ── 1·2. /state 봉투가 「레지스트리에 없는 개체」로 뜬다 ─────────────────────
{
  const store = new DataStore();
  // 목 레지스트리에는 `robot-01` 뿐이다 — 드론은 아직 안 올라가 있다. 그것이 지금의 사실이다.
  store.setRegistry({ zones: [{ id: DRONE.zoneId, display_name: 'A' }], entities: [{ id: 'robot-01', zone: DRONE.zoneId }] }, null);
  store.apply(droneStateEnvelope());
  store.apply(droneStateEnvelope({ channel: 'heartbeat', seq: 174, payload: { channel: 'heartbeat' } }));

  // 병합 창이 닫힌 뒤의 스냅샷을 읽는다 — 앱이 실제로 그러므로 여기서도 기다린다.
  await new Promise((resolve) => setTimeout(resolve, RENDER_MERGE_WINDOW_MS + 60));

  const record = store.get(DRONE.entityId);
  if (record === null) {
    failures.push('/state 로 드론이 왔는데 저장소가 버렸다 — 카드가 영영 안 뜬다');
  } else {
    // 레지스트리에 없다 = 「레지스트리에 없는 개체」 구획의 조건이다.
    if (record.registry !== null) failures.push('레지스트리에 없는데 registry 가 채워졌다 — 없는 목록을 지어냈다');
    if (record.envelopeCount !== 2) failures.push(`봉투를 ${record.envelopeCount}건으로 셌다`);
    if (record.state === null) failures.push('state 칸이 비었다 — 받은 봉투가 안 들어갔다');
    // **받은 것을 그대로** 적는다. 여기서 배터리를 해석하거나 상태를 판정하지 않는다.
    const payload = record.state?.payload ?? null;
    if (payload?.fc_link !== false) failures.push('원문의 fc_link 가 그대로 안 남았다');
    if (payload?.battery !== null) failures.push('FC 가 없을 때의 battery: null 이 그대로 안 남았다');
  }
}

// 값이 찬 상태도 원문 그대로 지난다 — 우리가 단위를 바꾸거나 0 으로 채우지 않는다.
{
  const store = new DataStore();
  store.setRegistry({ zones: [{ id: DRONE.zoneId, display_name: 'A' }], entities: [] }, null);
  store.apply(droneStateEnvelope({ payload: liveStateBody() }));
  await new Promise((resolve) => setTimeout(resolve, RENDER_MERGE_WINDOW_MS + 60));
  const payload = store.get(DRONE.entityId)?.state?.payload ?? null;
  if (payload?.battery?.voltage_v !== 15.75) failures.push('전압이 원문과 다르다');
  if (payload?.flight?.armed !== false) failures.push('arm 이 원문과 다르다');
  if (payload?.gps?.lat !== null) failures.push('fix 없을 때의 lat: null 을 0 으로 바꿨다');
}

// ── 3. MQTT 경로가 드론 본문을 안 뜯는다 ────────────────────────────────────
//
// 여기서 뜯기 시작하면 **경로가 둘**이 된다. 연결 관리가 같은 소켓에 붙어 있어 `state` 가
// 지나가기는 하지만, 화면에 그리는 값은 `/state` 쪽 하나여야 한다.
{
  const parsed = { entityType: DRONE.entityType, entityId: DRONE.entityId, channel: 'state' };
  const device = applyDeviceMessage(undefined, parsed, liveStateBody());
  if (device.batteryPct !== null) {
    failures.push(`MQTT 경로가 드론 배터리를 ${device.batteryPct} 로 뜯었다 — 상태 경로가 둘이 됐다`);
  }
  if ('details' in device) failures.push('MQTT 경로에 드론 본문을 담는 칸이 생겼다');
  if ('fcLink' in device) failures.push('MQTT 경로가 fc_link 를 담는다 — FC 링크는 ping 이 본다');
  // 그래도 **식별은 한다** — 그건 상태가 아니라 「누가 붙어 있나」다.
  if (device.entityType !== DRONE.entityType) failures.push('토픽의 종류 칸을 안 담았다');
}

// ── 4. 상태 구독이 etype 을 `+` 로 받는다 ────────────────────────────────────
function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (isScratchPath(full)) continue;
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

/** 상태 토픽에 `robot` 을 박은 모양. 주석은 뺀다 — 설명은 분기가 아니다. */
const PINNED = /['"`]\w[\w-]*\/robot\/[^'"`]*\/(state|status|heartbeat)['"`]/;

{
  for (const file of walk(join(root, 'src'))) {
    const source = readSource(file)
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/[^\n]*/g, '');
    if (PINNED.test(source)) {
      failures.push(`${relative(root, file)}: 상태 토픽에 robot 이 박혀 있다 — 드론(drone)이 안 보인다`);
    }
  }
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name}`);
  controls.push(name);
}
{
  control('robot 을 박은 구독은 잡힌다', PINNED.test("const T = ['zoneA/robot/+/state'];"));
  control('+ 로 받는 구독은 안 잡힌다', !PINNED.test("const T = ['zoneA/+/+/state'];"));
}
{
  // Go1 회귀 — 같은 함수가 Go1 의 평평한 배터리는 **그대로** 뜯는다.
  const go1 = applyDeviceMessage(undefined, { entityType: 'robot', entityId: 'go1-001', channel: 'state' }, {
    battery_pct: 77, device_status: 'ok', robot_mode: 'idle', speed_mps: 0.2,
  });
  control('Go1 의 battery_pct 는 그대로 뜯는다', go1.batteryPct === 77);
  control('Go1 의 mode 도 그대로', go1.mode === 'idle');
}
{
  // 드론의 `state` 를 MQTT 로 받아도 **조용히 무시**된다 — 던지거나 값을 지어내지 않는다.
  const quiet = applyDeviceMessage(undefined, { entityType: DRONE.entityType, entityId: DRONE.entityId, channel: 'state' }, stateBody());
  control('드론 state 를 받아도 안 죽는다', quiet.entityId === DRONE.entityId && quiet.batteryPct === null);
}

if (failures.length) {
  console.error(`❌ verify:drone-via-state\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ /state 봉투 한 건이면 x500-001 이 「레지스트리에 없는 개체」로 뜬다 — 원문 그대로');
console.log('✅ MQTT 장비 상태 경로는 드론 본문을 안 뜯는다 — 상태 경로가 하나다');
console.log('✅ 상태 구독이 두 번째 칸을 + 로 받는다 (robot 을 박은 곳 0건)');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
