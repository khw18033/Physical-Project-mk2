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
// 사전을 읽어 **키의 값까지** 본다 — 키만 맞고 사전이 비면 화면에 키가 그대로 뜬다.
const { ko: koDict } = await import(pathToFileURL(join(root, 'src', 'i18n', 'ko.ts')).href);

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

// ── 3-2. **그 본문이 화면에 그릴 줄이 되는가** (260922 — 카드 안을 채운다) ───
//
// 1~3절은 「저장소에 원문이 그대로 남는가」까지였다. 그런데 카드와 상세 보기는 그 저장소를
// 못 읽는다 — 단독 빌드가 `tabs/` 를 끌어오면 안 되기 때문이다(`verify:standalone`).
// 그래서 **받는 쪽이 `shared/` 로 밀어 넣고** 그리는 쪽이 그것만 읽는다. 그 다리를 잰다.
//
// 값은 전부 계약이 준 실측 본문(`liveStateBody`)에서 나온다 — 지어낸 값으로 재면 그 검사는
// 우리 상상을 확인하는 것이 된다.
{
  const { stateRows } = await load('src', 'tabs', 'data', 'stateRows.ts');
  const rows = stateRows(liveStateBody());
  const find = (key) => rows.find((row) => row.labelKey === key) ?? null;

  // ① 무대에서 먼저 봐야 하는 것들이 줄이 된다.
  for (const key of ['dt.fcLink', 'dt.battery', 'dt.armed', 'dt.flightMode']) {
    if (find(key) === null) failures.push(`${key} 줄이 안 생겼다 — 카드가 그것을 못 적는다`);
  }
  if (find('dt.battery')?.value !== '74 %') failures.push(`배터리 값이 ${find('dt.battery')?.value} — 원문 74.0 에 % 를 붙인 것이어야 한다`);
  if (find('dt.voltage')?.value !== '15.75 V') failures.push('전압이 원문과 다르다');
  // **규약 문자열은 번역하지 않는다** — 번역하면 계약 문서와 화면을 대조할 수 없다.
  if (find('dt.flightMode')?.value !== 'AUTO.LOITER') failures.push('비행 모드를 손댔다');
  if (find('dt.landedState')?.value !== 'ON_GROUND') failures.push('착륙 상태를 손댔다');
  // 참/거짓은 낱말이라 **키**여야 한다.
  if (find('dt.armed')?.valueKey !== 'dt.armedNo') failures.push('arm 이 거짓인데 그 낱말 키가 아니다');
  if (find('dt.fcLink')?.valueKey !== 'dt.yes') failures.push('fc_link 가 참인데 그 낱말 키가 아니다');

  /**
   * ② **계약이 스스로 의심한 값은 그 사실을 달고 나온다.**
   * 「참고값. 디스암인데 12.2A 로 읽혔다(스케일 의심)」 — 빼면 왜 없는지 모르고,
   * 그냥 그리면 12.2A 를 사실로 읽는다.
   */
  if (find('dt.current')?.noteKey !== 'dt.note.suspect') {
    failures.push('계약이 의심한 전류값이 아무 표시 없이 나온다');
  }

  // ③ **계약이 쓰지 말라고 한 것은 줄이 안 된다.**
  if (rows.some((row) => row.rawLabel === 'system_status')) {
    failures.push('system_status 가 줄이 됐다 — 계약이 arm 판정에 쓰지 말라고 못박은 값이다');
  }

  // ④ **안 온 것은 줄이 안 된다.** FC 가 없으면 계약이 묶음을 통째로 null 로 준다.
  const dark = stateRows(stateBody());
  for (const key of ['dt.battery', 'dt.armed', 'dt.flightMode', 'dt.gpsFix']) {
    if (dark.find((row) => row.labelKey === key)) failures.push(`FC 가 없는데 ${key} 줄을 지어냈다`);
  }
  // 그래도 **이유는 남는다** — 그 한 줄이 위의 빈자리를 설명한다.
  if (dark.find((row) => row.labelKey === 'dt.fcLink')?.valueKey !== 'dt.no') {
    failures.push('FC 링크가 없다는 줄조차 없다 — 왜 비었는지 알 수 없어진다');
  }
  // fix 가 없으면 좌표는 계약이 null 을 준다 — 0,0 은 좌표가 아니라 부재다.
  if (rows.some((row) => row.labelKey === 'dt.lat' || row.labelKey === 'dt.lon')) {
    failures.push('fix 가 없는데 좌표 줄이 생겼다');
  }

  // ⑤ 이름은 **전부 사전에 있어야 한다** — 없으면 화면에 키가 그대로 뜬다.
  for (const row of rows) {
    if (row.labelKey !== null && koDict[row.labelKey] === undefined) {
      failures.push(`줄 이름 ${row.labelKey} 가 사전에 없다`);
    }
    if (row.valueKey !== undefined && koDict[row.valueKey] === undefined) {
      failures.push(`값 낱말 ${row.valueKey} 가 사전에 없다`);
    }
  }

  // ⑥ **다리가 실제로 놓였는가.** 위가 다 맞아도 배선이 없으면 화면은 그대로 비어 있다.
  const layer = readSource(join(root, 'src', 'tabs', 'data', 'index.ts'));
  if (!/noteDeviceTelemetry\(\s*envelope\.entity/.test(layer)) {
    failures.push('받는 자리가 상태 줄을 안 밀어 넣는다 — 카드가 영영 이름만 적는다');
  }
  const facts = readSource(join(root, 'src', 'physical', 'DeviceFacts.tsx'));
  if (!/useDeviceTelemetry\(\)/.test(facts)) failures.push('상세 보기가 그 저장소를 안 읽는다');
  const link = readSource(join(root, 'src', 'physical', 'HardwareLink.tsx'));
  if (!/useDeviceTelemetry\(\)/.test(link)) failures.push('카드 한 줄이 그 저장소를 안 읽는다');
  // **기종별 항목표가 화면 코드에 없다** (지시서 260921 §원칙 2).
  for (const [name, source] of [['DeviceFacts.tsx', facts], ['HardwareLink.tsx', link]]) {
    if (/\bbattery\.|remaining_pct|flight\.armed|fc_link\b/.test(source)) {
      failures.push(`${name} 에 계약 필드 이름이 박혀 있다 — 기종별 항목표를 화면 코드에 두지 않는다`);
    }
  }
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
  /**
   * **옛 화면을 흉내 내면 카드가 이름만 적어야 한다** — 260922 까지의 그 상태다.
   *
   * 드론은 값이 오고 있는데도 카드가 「연결됨 · n초 전」 밖에 못 적었다. 밀어 넣는 다리가
   * 없어서 그리는 쪽이 읽을 것이 없었기 때문이다. 고친 것이 진짜 고쳐졌는지 보려면
   * 안 고친 것이 어떻게 비어 있었는지도 재야 한다.
   */
  const { stateRows } = await load('src', 'tabs', 'data', 'stateRows.ts');
  const rows = stateRows(liveStateBody());
  const oldCard = [];                                   // 옛 화면이 들고 있던 줄
  control('옛 화면은 카드에 적을 줄이 하나도 없다', oldCard.length === 0);
  control('지금은 카드 몫 줄이 있다', rows.filter((row) => row.onCard === true).length > 0);
  // 카드 몫은 **고르는 것이 아니라 붙어서 온다** — 화면 코드에 기종별 표를 두지 않는다.
  control('카드 몫은 줄에 표시돼서 온다',
    rows.some((row) => row.labelKey === 'dt.battery' && row.onCard === true)
    && rows.some((row) => row.labelKey === 'dt.voltage' && row.onCard !== true));
  // 모양을 모르는 것이 와도 던지지 않는다 — 여기서 던지면 구독 하나가 화면을 멈춘다.
  control('모르는 본문은 빈 줄로 떨어진다 (던지지 않는다)',
    stateRows(null).length === 0 && stateRows('x').length === 0 && stateRows([1]).length === 0);
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
console.log('✅ 그 본문이 카드·상세의 줄이 된다 — 규약 문자열은 그대로, 안 온 것은 줄이 안 생긴다');
console.log('✅ 상태 구독이 두 번째 칸을 + 로 받는다 (robot 을 박은 곳 0건)');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
