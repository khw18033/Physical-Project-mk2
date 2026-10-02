// verify:multi-robot (260922 신설 — 로봇 N대 동시 연결 1단계)
//
// **브로커 여럿에 동시에 붙고, 한쪽이 끊겨도 다른 쪽 로봇이 남는가.**
//
// 전에는 소켓이 하나였다. 주소를 바꾸면 앞엣것이 끊겼고, 그래서 Go1(pi7)과 드론(pi3)을
// 같이 볼 수 없었다. 목표는 「연결된 모든 로봇의 상태를 확인하고 임무에 배정해서 움직인다」
// 이고, 이 검사는 그 **1단계**(동시 연결 + 상태)를 못박는다.
//
// 보는 것 여섯.
//  1. 주소 칸이 **목록**이다 — 빈 줄·공백을 버리고 왕복한다
//  2. 브로커마다 장비가 따로 선다 — `deviceIdentityFor`
//  3. **한 브로커를 비워도 다른 브로커의 로봇은 남는다** ← 이번 작업의 요점
//  4. 전역 판정은 로봇이 둘이면 `null` 이다 — **그것이 맞다**(대상을 안 받는 명령은 막힌다)
//  5. 확인이 **주소마다** 줄을 낸다 — 하나면 주소를 안 적는다
//  6. 임무 배선이 **클라이언트 하나에만** 붙는다 — 전부에 달면 드론에도 스캔이 나간다
//
// 3번이 이 구조의 이유다. 전역으로 비우면 pi3 를 다시 붙일 때마다 pi7 의 Go1 이 화면에서
// 사라지고, 그 사라짐은 「로봇이 꺼졌다」로 읽힌다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { splitAddressList, joinAddressList } = await load('src', 'shared', 'connections.ts');
const {
  deviceIdentity, deviceIdentityFor, noteCapability, noteDeviceReport, resetDeviceIdentity,
} = await load('src', 'physical', 'deviceIdentity.ts');
const { checkPhysicalAll } = await load('src', 'shared', 'connectionCheck.ts');

const failures = [];
const controls = [];

const GO1 = 'ws://pi7.example:9001/mqtt';
const DRONE = 'ws://pi3.example:9001';

// ── 1. 주소 칸이 목록이다 ────────────────────────────────────────────────────
{
  const joined = joinAddressList([GO1, '  ', DRONE, '']);
  if (splitAddressList(joined).join('|') !== `${GO1}|${DRONE}`) {
    failures.push(`목록이 왕복하지 않는다 — ${splitAddressList(joined).join('|')}`);
  }
  // 옛 값(한 줄)이 그대로 목록 한 줄이다 — 옮길 것이 없어야 한다.
  if (splitAddressList(GO1).join('|') !== GO1) failures.push('옛 단일 주소가 목록 한 줄로 안 읽힌다');
  if (splitAddressList('').length !== 0) failures.push('빈 칸이 주소 하나로 읽힌다 — 빈 주소로 소켓을 연다');
  if (splitAddressList('\n  \n').length !== 0) failures.push('빈 줄이 주소로 읽힌다');
}

// ── 2·3. 브로커마다 장비가 서고, 한쪽을 비워도 다른 쪽은 남는다 ─────────────
{
  resetDeviceIdentity();
  noteCapability('go1-001', ['abort', 'scan_mission'], GO1);
  noteCapability('x500-001', ['ping'], DRONE);

  if (deviceIdentityFor(GO1)?.deviceId !== 'go1-001') failures.push('pi7 쪽 장비가 Go1 이 아니다');
  if (deviceIdentityFor(DRONE)?.deviceId !== 'x500-001') failures.push('pi3 쪽 장비가 드론이 아니다');
  // 남의 브로커 것을 끌어오면 안 된다.
  if (deviceIdentityFor('ws://nobody:9001') !== null) failures.push('아무도 없는 주소에서 장비가 나온다');

  /**
   * **요점.** 드론 쪽을 비운다(다시 붙는 중). Go1 은 그대로 있어야 한다 —
   * 전역으로 비우던 옛 동작이면 여기서 Go1 이 사라진다.
   */
  resetDeviceIdentity(DRONE);
  if (deviceIdentityFor(GO1)?.deviceId !== 'go1-001') {
    failures.push('드론 쪽을 비웠더니 Go1 까지 사라졌다 — 260922 의 그 실패다');
  }
  if (deviceIdentityFor(DRONE) !== null) failures.push('비웠는데 드론이 남아 있다');
}

// ── 4. 전역 판정은 로봇이 둘이면 null ───────────────────────────────────────
//
// **이것이 맞다.** 대상을 안 받는 명령(`commandTarget()`)은 로봇이 둘일 때 갈 곳이 정해지지
// 않는다. 고르는 것은 배정의 일이고(3단계), 그때 명령은 대상을 인자로 받는다(2단계).
// 조용히 한 대를 골라 쏘는 것보다 막히는 편이 낫다.
{
  resetDeviceIdentity();
  noteCapability('go1-001', ['abort'], GO1);
  if (deviceIdentity()?.deviceId !== 'go1-001') failures.push('한 대뿐인데 전역 판정이 안 선다');

  noteCapability('x500-001', ['ping'], DRONE);
  if (deviceIdentity() !== null) {
    failures.push('로봇이 둘인데 전역 판정이 한 대를 골랐다 — 엉뚱한 장비로 명령이 나간다');
  }
  // 그래도 **브로커별로는 선다** — 2단계가 이것을 쓴다.
  if (deviceIdentityFor(GO1) === null || deviceIdentityFor(DRONE) === null) {
    failures.push('전역이 막혔다고 브로커별 판정까지 막혔다 — 2단계가 설 자리가 없다');
  }
}

// ── 5. 확인이 주소마다 줄을 낸다 ────────────────────────────────────────────
{
  const probe = (state) => ({
    getStatus: () => ({ state }),
    connect: async () => ({ state }),
    ping: async () => ({ ok: state === 'open', roundTripMs: 7, message: 'ok' }),
  });

  // 하나면 **주소를 안 적는다** — 반복하면 읽을 것만 는다.
  const one = await checkPhysicalAll([{ probe: probe('open'), address: GO1 }]);
  if (one.some((row) => row.scope !== undefined)) failures.push('상대가 하나인데 주소를 적었다');
  if (one.length !== 3) failures.push(`상대가 하나인데 줄이 ${one.length}개 — 셋이어야 한다`);

  // 둘이면 주소마다 셋. **한쪽이 죽어도 나머지 줄은 그대로 나온다.**
  const two = await checkPhysicalAll([
    { probe: probe('open'), address: GO1 },
    { probe: probe('closed'), address: DRONE },
  ]);
  if (two.length !== 6) failures.push(`상대가 둘인데 줄이 ${two.length}개 — 여섯이어야 한다`);
  if (two.some((row) => row.scope === undefined)) failures.push('상대가 둘인데 어느 주소인지 안 적었다');
  if (new Set(two.map((row) => row.id)).size !== 6) failures.push('줄 id 가 겹친다 — 화면이 하나만 그린다');
  const go1Broker = two.find((row) => row.scope === GO1 && row.id.startsWith('broker'));
  const droneBroker = two.find((row) => row.scope === DRONE && row.id.startsWith('broker'));
  if (go1Broker?.ok !== true) failures.push('붙은 주소가 초록이 아니다');
  if (droneBroker?.ok !== false) failures.push('안 붙은 주소가 빨갛지 않다');
}

// ── 6. 임무 배선은 클라이언트 하나에만 ──────────────────────────────────────
//
// 전부에 달면 드론에도 `scan_mission` 이 나간다. 드론은 그 action 을 선언한 적이 없다
// (계약 §4 — `ping` 하나). 거절당하는 것이 그나마 다행인 실패다.
{
  const source = readSource(join(root, 'src', 'physical', 'robotClient.ts'));
  if (!/function attachDriver\(/.test(source)) failures.push('임무 배선을 따로 다는 자리가 없다');
  if (!/const pool = new Map<string, PhysicalClient>\(\)/.test(source)) {
    failures.push('클라이언트가 주소마다 하나가 아니다');
  }
  // 만드는 자리에 임무 배선이 있으면 전부에 달린다.
  const make = source.slice(source.indexOf('function makeClient('), source.indexOf('function attachDriver('));
  for (const wiring of ['onScanFeed', 'initPrepStage', 'initScanContinue', 'issueScan']) {
    if (make.includes(wiring)) failures.push(`makeClient 에 ${wiring} 가 있다 — 붙는 로봇마다 임무가 걸린다`);
  }
  // 세션도 모는 쪽만 민다 — 둘이 번갈아 덮어쓰면 「붙었다 끊겼다」가 반복된다.
  if (!/url !== drivingUrl/.test(make)) failures.push('모든 클라이언트가 임무 세션을 덮어쓴다');
  // 줄이 지워지면 소켓도 버린다 — 안 버리면 없는 설정의 로봇이 카드에 계속 뜬다.
  if (!/client\.disconnect\(\);/.test(source)) failures.push('지운 주소의 소켓을 안 끊는다');
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name}`);
  controls.push(name);
}
{
  /**
   * **옛 동작(전역으로 비우기)을 흉내 내면 다른 로봇이 사라져야 한다.**
   * 고친 것이 진짜 고쳐졌는지 보려면 안 고친 것이 어떻게 틀렸는지도 재야 한다.
   */
  resetDeviceIdentity();
  noteCapability('go1-001', ['abort'], GO1);
  noteCapability('x500-001', ['ping'], DRONE);
  const before = deviceIdentityFor(GO1)?.deviceId ?? null;
  resetDeviceIdentity();                                  // origin 없이 = 옛 동작
  control('옛 동작은 한쪽을 비우면 전부 사라진다', before === 'go1-001' && deviceIdentityFor(GO1) === null);

  resetDeviceIdentity();
  noteCapability('go1-001', ['abort'], GO1);
  noteCapability('x500-001', ['ping'], DRONE);
  resetDeviceIdentity(DRONE);                             // 지금 동작
  control('지금 동작은 그 브로커만 비운다', deviceIdentityFor(GO1)?.deviceId === 'go1-001');
}
{
  // 토픽으로만 안 장비도 브로커가 붙는다 — `registration` 이 없어도 origin 은 실려야 한다.
  resetDeviceIdentity();
  noteDeviceReport('go1-001', 'robot', {}, GO1);
  control('토픽으로 안 장비도 브로커가 붙는다', deviceIdentityFor(GO1)?.deviceId === 'go1-001');
  control('그 장비는 남의 브로커에서 안 보인다', deviceIdentityFor(DRONE) === null);
}
{
  // 목록 규약 — 한 곳에서만 푼다. 읽는 쪽이 손으로 쪼개면 공백 규칙이 갈린다.
  const users = readFileSync(join(root, 'src', 'physical', 'PhysicalClient.ts'), 'utf8');
  control('읽는 쪽이 목록 함수를 쓴다', /splitAddressList\(/.test(users));
  control('읽는 쪽이 손으로 쪼개지 않는다', !/\.split\('\\n'\)/.test(users));
}

resetDeviceIdentity();

if (failures.length) {
  console.error(`❌ verify:multi-robot\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 주소 칸이 목록이다 — 빈 줄·공백을 버리고 왕복한다 (옛 단일 주소가 그대로 한 줄)');
console.log('✅ 브로커마다 장비가 따로 서고, 한쪽을 비워도 다른 쪽 로봇은 남는다');
console.log('✅ 전역 판정은 로봇이 둘이면 null — 대상을 안 받는 명령은 막힌다 (브로커별 판정은 선다)');
console.log('✅ 확인이 주소마다 줄 셋 · 하나면 주소를 안 적는다 · 한쪽이 죽어도 나머지는 그대로');
console.log('✅ 임무 배선은 클라이언트 하나에만 — 붙는 로봇마다 스캔이 걸리지 않는다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
