// verify:device-by-capability (260921 신설 — 드론 연결 2단계)
//
// **장비 종류와 이름을 주소가 아니라 장비가 정하는가.**
//
// 주소는 바뀐다. 같은 드론이 `pi3.local` 이었다가 연구실 IP 였다가 Tailscale IP 가 된다.
// 주소 문자열로 기종을 가르면 그때마다 깨지고, **깨진 줄도 모른다** — 화면은 여전히 초록이다.
//
// 보는 것 넷.
//  1. `Capability` 를 받으면 그 `device_id` 와 `actions` 가 선다
//  2. `Capability` 를 **못 받아도**(retained 가 아니다) retained `status` 의 `registration`
//     으로 이름과 종류가 선다 — 늦게 붙은 웹이 겪는 정상 경로다
//  3. 종류 문자열이 코드에 목록으로 박혀 있지 않다 — `drone` 이라고 보내면 `drone` 이다
//  4. **`src/` 어디에도 `pi3`·`pi7` 문자열로 갈라지는 코드가 없다**
//
// 대조군 — 주소로 판정하는 사본, 종류를 못 읽는 사본이 반드시 잡혀야 한다.

import { readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isScratchPath } from './lib/scratch.mjs';
// 자리표에 줄바꿈이 들어간다 — **LF 로 정규화한 원본**에서 만든다 (`verify:crlf-safe`).
import { readSource } from './lib/source.mjs';
import { CAPABILITY_HEX, DRONE, bytes, statusBody } from './lib/droneFixtures.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const {
  deviceIdentity, noteCapability, noteDeviceReport, resetDeviceIdentity, supportsAction, commandTarget,
} = await load('src', 'physical', 'deviceIdentity.ts');
const { decodeCapability } = await load('src', 'physical', 'uplink.ts');

const failures = [];
const controls = [];

// ── 1. Capability 한 건이면 이름과 어휘가 선다 ───────────────────────────────
{
  resetDeviceIdentity();
  // **장비가 실제로 보낸 바이트**로 시작한다 (계약 §4). 우리가 만든 것이 아니다.
  const capability = decodeCapability(bytes(CAPABILITY_HEX));
  if (capability === null) failures.push('계약 §4 의 실측 Capability 를 못 뜯었다');
  else {
    if (capability.deviceId !== DRONE.entityId) failures.push(`Capability 의 device_id 가 ${capability.deviceId}`);
    if (capability.actions.join(',') !== 'ping') failures.push(`actions 가 ${capability.actions.join(',')} — ping 하나여야 한다`);
    noteCapability(capability.deviceId, capability.actions);
  }
  if (commandTarget() !== DRONE.entityId) failures.push(`발행 대상이 ${commandTarget()} — 받은 이름이 아니다`);
  if (supportsAction('ping') !== true) failures.push('선언한 ping 을 못 한다고 읽었다');
  if (supportsAction('abort') !== false) failures.push('선언 안 한 abort 를 할 수 있다고 읽었다');
}

// ── 2. Capability 를 못 받아도 retained status 가 메운다 ─────────────────────
//
// **이것이 늦게 붙은 웹의 정상 경로다.** `Capability` 는 노드가 붙는 순간 한 번 오고
// retained 가 아니다(계약 §4). 그것만 원천으로 두면 화면은 영영 장비를 모르고, 그러면
// `ping` 조차 못 낸다 — 계약 §11-4 가 「`ping` 으로 확인하라」고 적은 그 `ping` 을.
{
  resetDeviceIdentity();
  noteDeviceReport(DRONE.entityId, DRONE.entityType, statusBody());
  const found = deviceIdentity();
  if (found === null) failures.push('retained status 를 받고도 장비를 모른다 — 늦게 붙으면 영영 모른다');
  else {
    if (found.deviceId !== DRONE.entityId) failures.push(`이름이 ${found.deviceId}`);
    if (found.kind !== 'drone') failures.push(`종류가 ${found.kind} — registration.entity_type 을 안 읽었다`);
    if (found.deviceType !== DRONE.deviceType) failures.push(`기종이 ${found.deviceType}`);
    if (found.source !== 'registration') failures.push(`원천이 ${found.source} — 자기소개로 안 읽었다`);
  }
  // **어휘는 모른다.** status 에는 actions 가 없다 — 「못 받았다」를 「없다」로 읽으면 안 된다.
  if (supportsAction('abort') !== null) failures.push('actions 를 못 받았는데 지원 여부를 단언했다');
}

// ── 3. 종류 문자열을 우리가 정하지 않는다 ────────────────────────────────────
//
// 장비가 처음 보는 종류를 말해도 그대로 받아야 한다. `'robot' | 'drone'` 같은 합집합을
// 코드에 적으면 세 번째 기종이 붙는 날 이 파일을 고쳐야 하고, 그게 「기종별 표를 코드에
// 두지 않는다」가 막으려던 바로 그것이다.
{
  resetDeviceIdentity();
  noteDeviceReport('rov-009', 'submersible', statusBody({
    source_id: 'rov-009',
    registration: { entity_id: 'rov-009', entity_type: 'submersible', device_type: 'bluerov2' },
  }));
  const found = deviceIdentity();
  if (found?.kind !== 'submersible') failures.push(`처음 보는 종류를 ${found?.kind} 로 바꿔 적었다`);
  if (found?.deviceId !== 'rov-009') failures.push('처음 보는 장비의 이름을 못 읽었다');
}

// ── 4. 주소 문자열로 갈라지는 코드가 없다 ────────────────────────────────────
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

/**
 * 주석과 사전은 뺀다. **주석에 `pi3` 라고 적는 것은 설명이지 분기가 아니고**, 사전의 `pi7`
 * 은 사람에게 보여 주는 말이다. 코드가 그 문자열을 **비교**하는 것만 잡는다.
 */
function codeOnly(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '');
}

/** 주소 조각으로 **갈라지는** 모양. 비교·포함·정규식 셋. */
const ADDRESS_BRANCH = [
  /[=!]==?\s*['"`][^'"`]*pi[137][^'"`]*['"`]/,
  /['"`][^'"`]*pi[137][^'"`]*['"`]\s*[=!]==?/,
  /\.(includes|startsWith|endsWith|indexOf|match|test)\(\s*['"`/][^'"`/]*pi[137]/,
  /\b(kind|type|isDrone|isRobot)\b[^\n;]{0,40}pi[137]/,
];

{
  const files = walk(join(root, 'src'));
  for (const file of files) {
    // 사전은 사람에게 보여 주는 말이라 예외다 — 코드가 아니다.
    const rel = relative(root, file);
    if (rel.includes(join('src', 'i18n'))) continue;
    const source = codeOnly(readSource(file));
    for (const pattern of ADDRESS_BRANCH) {
      if (pattern.test(source)) failures.push(`${rel}: 주소 문자열로 갈라진다 — 장비가 말하게 해야 한다`);
    }
  }
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  const injected = "const kind = url.includes('pi3') ? 'drone' : 'robot';";
  control('주소로 기종을 가르는 사본', ADDRESS_BRANCH.some((p) => p.test(injected)));
  control('주소를 등호로 견주는 사본', ADDRESS_BRANCH.some((p) => p.test("if (host === 'pi3.local') {")));
  // 반대 대조군 — 주석에 적힌 `pi3` 는 잡으면 안 된다.
  control('주석의 pi3 는 안 잡는다', !ADDRESS_BRANCH.some((p) => p.test(codeOnly('// pi3 는 드론이다\n'))));
}
{
  // 종류를 못 읽는 사본 — registration 이 없으면 토픽 칸으로 물러서야 한다.
  resetDeviceIdentity();
  noteDeviceReport(DRONE.entityId, DRONE.entityType, { channel: 'state' });
  control('registration 이 없으면 토픽 칸으로 판정', deviceIdentity()?.kind === 'drone');
}

resetDeviceIdentity();

if (failures.length) {
  console.error(`❌ verify:device-by-capability\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 장비 종류·이름이 Capability(실측 18B)와 retained status 의 registration 에서 온다');
console.log('✅ 처음 보는 종류도 그대로 받는다 — 코드에 기종 목록이 없다');
console.log('✅ src/ 에 pi3·pi7 문자열로 갈라지는 코드 0건 (사전·주석 제외)');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
