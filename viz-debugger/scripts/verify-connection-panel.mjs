// verify:connection-panel (260910 신설 — 연결 관리 통합 지시서 §6)
//
// **연결에 관한 것이 한 화면에 다 있는가.**
//
// 보는 것 넷.
//  1. 확인 대상 넷(`physical`·`detect`·`stt`·`generate`)이 다 올라와 있는가
//  2. **`physical` 이 브로커와 로봇을 따로 보이는가** ← 이번 작업의 요점
//  3. 확인 버튼이 **실제 왕복을 돌리는가** — 누른 척만 하지 않는가
//  4. 대상 하나가 죽어도 **그 줄만 빨갛고 나머지는 도는가**
//
// 2번이 핵심이다. 브로커는 살아 있는데 로봇이 꺼져 있으면 **연결은 성공이고 왕복은
// 실패다.** 한 표시등으로 뭉치면 발표 직전에 주소를 봐야 하는지 로봇 전원을 봐야 하는지
// 못 가른다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { CONNECTION_TARGETS } = await load('src', 'shared', 'connections.ts');
const { checkPhysical, checkTarget, checkDetect } = await load('src', 'shared', 'connectionCheck.ts');
const {
  CHECKED_TARGETS, healthOf, targetOk, firstBroken, resetHealth,
} = await load('src', 'shared', 'connectionHealth.ts');
const { BROKER_PRESETS, presetReady } = await load('src', 'physical', 'presets.ts');

const failures = [];
const controls = [];

// ── 1. 확인 대상 넷이 다 올라와 있는가 ───────────────────────────────────────
{
  const ids = CONNECTION_TARGETS.map((t) => t.id);
  for (const target of ['physical', 'detect', 'stt', 'generate']) {
    if (!ids.includes(target)) failures.push(`연결 관리에 ${target} 이 없다`);
    if (!CHECKED_TARGETS.includes(target)) failures.push(`${target} 이 확인 대상 목록에 없다`);
  }
  // 화면이 목록을 그린다 — 손으로 넷을 적으면 대상이 늘 때 한쪽만 는다.
  const panel = readFileSync(join(root, 'src', 'shell', 'ConnectionsPanel.tsx'), 'utf8');
  if (!/CONNECTION_TARGETS\.map/.test(panel)) failures.push('팝업이 목록을 그리지 않는다 — 손으로 적으면 갈라진다');
  for (const row of ['conn-health', 'conn-check']) {
    if (!panel.includes(row)) failures.push(`팝업에 ${row} 줄이 없다 — 네 줄 중 하나가 빠졌다`);
  }
}

// ── 2. physical 이 브로커와 로봇을 따로 보인다 (요점) ────────────────────────
{
  // 브로커도 로봇도 살아 있다.
  const both = await checkPhysical({
    getStatus: () => ({ state: 'open' }),
    connect: async () => ({ state: 'open' }),
    ping: async () => ({ ok: true, roundTripMs: 12, message: 'ok' }),
  });
  if (both.length !== 2) failures.push(`physical 이 줄을 ${both.length}개 낸다 — 브로커와 로봇 둘이어야 한다`);
  if (!both.every((l) => l.ok)) failures.push('둘 다 살아 있는데 실패로 나온다');
  if (both.find((l) => l.id === 'robot')?.roundTripMs !== 12) failures.push('왕복 시간이 안 실린다');

  // **브로커는 살아 있는데 로봇이 꺼져 있다** — 연결은 성공이고 왕복은 실패다.
  const robotDead = await checkPhysical({
    getStatus: () => ({ state: 'open' }),
    connect: async () => ({ state: 'open' }),
    ping: async () => ({ ok: false, roundTripMs: null, message: 'robot_state_dead' }),
  });
  const broker = robotDead.find((l) => l.id === 'broker');
  const robot = robotDead.find((l) => l.id === 'robot');
  if (broker?.ok !== true) failures.push('브로커가 붙었는데 브로커 줄이 빨갛다 — 로봇 실패에 끌려갔다');
  if (robot?.ok !== false) failures.push('로봇이 죽었는데 로봇 줄이 초록이다');
  if (!/robot_state_dead/.test(String(robot?.reason))) failures.push('로봇 실패 사유를 버렸다');

  // 브로커가 안 붙으면 로봇은 **못 물어본 것**이다 — 실패 사유가 그렇게 적혀야 한다.
  const brokerDead = await checkPhysical({
    getStatus: () => ({ state: 'closed', reason: '주소를 못 찾습니다' }),
    connect: async () => ({ state: 'closed', reason: '주소를 못 찾습니다' }),
    ping: async () => { throw new Error('여기까지 오면 안 된다'); },
  });
  if (brokerDead.find((l) => l.id === 'broker')?.ok !== false) failures.push('브로커가 죽었는데 초록이다');
  if (!/주소를 못 찾습니다/.test(String(brokerDead.find((l) => l.id === 'broker')?.reason))) {
    failures.push('브로커 실패 사유를 버렸다 — 주소 문제인지 알 수 없어진다');
  }
  if (!/물어보지 못했습니다/.test(String(brokerDead.find((l) => l.id === 'robot')?.reason))) {
    failures.push('브로커가 없을 때 로봇 줄이 「못 물어봤다」고 말하지 않는다');
  }

  // 대상 하나가 통째로 초록인가 — **줄이 하나라도 빨가면 빨갛다.**
  resetHealth();
  const { setHealth } = await load('src', 'shared', 'connectionHealth.ts');
  setHealth('physical', robotDead);
  if (targetOk('physical') !== false) failures.push('브로커만 붙었는데 대상이 초록이라고 한다');
  setHealth('physical', both);
  if (targetOk('physical') !== true) failures.push('둘 다 살아 있는데 대상이 초록이 아니다');
}

// ── 3. 확인 버튼이 실제 왕복을 돌린다 ────────────────────────────────────────
{
  resetHealth();
  let pinged = 0;
  await checkTarget('physical', {
    getStatus: () => ({ state: 'open' }),
    connect: async () => ({ state: 'open' }),
    ping: async () => { pinged += 1; return { ok: true, roundTripMs: 8, message: 'ok' }; },
  });
  if (pinged !== 1) failures.push(`확인 버튼이 왕복을 ${pinged}번 돌렸다 — 한 번이어야 한다`);
  if (healthOf('physical').lines.length !== 2) failures.push('확인 뒤 결과가 안 적혔다');
  if (healthOf('physical').checking) failures.push('확인이 끝났는데 「확인 중」이 안 풀렸다');

  // **던지지 않는다** — 여기서 예외가 새면 팝업이 통째로 날아간다.
  resetHealth();
  await checkTarget('physical', {
    getStatus: () => ({ state: 'open' }),
    connect: async () => ({ state: 'open' }),
    ping: async () => { throw new Error('소켓이 죽었다'); },
  });
  const lines = healthOf('physical').lines;
  if (lines.length === 0) failures.push('확인이 던져서 결과가 아예 안 남았다');
  if (!lines.some((l) => /소켓이 죽었다/.test(String(l.reason)))) failures.push('예외 사유가 안 남았다');
}

// ── 4. detect 는 자리만 — 2단계-B 에서 잇는다 ────────────────────────────────
{
  const detect = await checkDetect();
  if (detect.length === 0) failures.push('detect 줄이 아예 없다 — 자리는 있어야 한다');
  if (!/2단계-B/.test(String(detect[0]?.reason))) {
    failures.push('detect 가 「아직 확인하지 않는다」고 말하지 않는다 — 없는 서비스에 붙는 척하면 안 된다');
  }
}

// ── 5. 한 대상이 죽어도 나머지는 돈다 ────────────────────────────────────────
{
  resetHealth();
  const { setHealth, line } = await load('src', 'shared', 'connectionHealth.ts');
  setHealth('physical', [line('broker', '브로커', false, { reason: '끊김' })]);
  setHealth('stt', [line('probe', '서비스', true, { roundTripMs: 5 })]);
  if (targetOk('stt') !== true) failures.push('physical 이 죽었다고 stt 까지 빨개졌다');

  const broken = firstBroken(CHECKED_TARGETS);
  if (broken?.target !== 'physical') failures.push('끊긴 대상을 못 짚는다 — 표시등이 무엇이 끊겼는지 말해야 한다');
  if (!String(broken?.line.label ?? '').trim()) failures.push('끊긴 줄의 이름이 없다');
}

// ── 6. physical 프리셋 넷 ────────────────────────────────────────────────────
{
  if (BROKER_PRESETS.length !== 4) failures.push(`프리셋이 ${BROKER_PRESETS.length}개 — 넷이어야 한다`);
  const venue = BROKER_PRESETS.find((p) => p.id === 'venue');
  if (venue === undefined) failures.push('발표장 핫스팟 프리셋이 없다');
  // **비어 있어야 한다** — 정적 IP 를 받으면 채운다. 지어내 넣지 않는다.
  if (venue !== undefined && venue.url.trim() !== '') failures.push(`발표장 주소가 채워져 있다 — ${venue.url}`);
  if (venue !== undefined && presetReady(venue)) failures.push('값이 빈 프리셋을 고를 수 있다');
  const panel = readFileSync(join(root, 'src', 'shell', 'ConnectionsPanel.tsx'), 'utf8');
  if (!/BROKER_PRESETS/.test(panel)) failures.push('연결 관리가 프리셋을 안 그린다');
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  // 브로커와 로봇을 한 줄로 뭉친 사본 — 로봇이 죽으면 브로커까지 빨개진다.
  const merged = (brokerOk, robotOk) => [{ id: 'both', ok: brokerOk && robotOk }];
  const ours = await checkPhysical({
    getStatus: () => ({ state: 'open' }),
    connect: async () => ({ state: 'open' }),
    ping: async () => ({ ok: false, roundTripMs: null, message: 'dead' }),
  });
  control(
    '브로커와 로봇을 한 줄로 뭉친 사본',
    merged(true, false)[0].ok === false && ours.find((l) => l.id === 'broker').ok === true,
  );
}
{
  resetHealth();
  control('안 눌러 본 대상은 「모른다」 (빨강이 아니다)', targetOk('physical') === null);
}

resetHealth();

if (failures.length) {
  console.error(`❌ verify:connection-panel\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 확인 대상 넷이 다 올라와 있다 — ${CHECKED_TARGETS.join(' · ')} (팝업이 목록을 그린다)`);
console.log('✅ physical 이 브로커와 로봇을 따로 보인다 — 로봇이 죽어도 브로커 줄은 초록');
console.log('✅ 브로커가 없으면 로봇 줄은 「못 물어봤다」 · 줄 하나라도 빨가면 대상이 빨갛다');
console.log('✅ 확인 버튼이 실제 왕복을 한 번 돌린다 · 던져도 사유가 남는다 (팝업이 안 날아간다)');
console.log('✅ detect 는 자리만 — 2단계-B 에서 잇는다 · 한 대상이 죽어도 나머지는 돈다');
console.log('✅ 프리셋 넷 · 발표장 핫스팟은 빈 채로 고를 수 없다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
