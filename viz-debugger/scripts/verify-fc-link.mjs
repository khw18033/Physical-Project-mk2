// verify:fc-link (260921 신설 — 드론 연결 2단계)
//
// **「라즈베리파이는 켜졌는데 FC 와 안 붙었다」를 화면이 가르는가.**
//
// 오늘 실제로 이 상황 때문에 반나절을 썼다. 브로커는 붙고 단말도 답하는데 기체가 안 움직인다 —
// 그 사이에 층이 하나 더 있다는 것을 화면이 말해 주지 않으면 무대 위에서 알 수 없다.
//
// 보는 것 다섯.
//  1. `ping` 의 `result` 에서 `fc_link` 를 읽는다 — **실측 hex 로** (계약 §5)
//  2. FC 링크가 없으면 **그 줄만** 빨갛다 — 브로커·단말은 초록으로 남는다
//  3. 줄은 여전히 **셋**이다 — 넷으로 늘리지 않는다
//  4. `fc_link` 를 안 싣는 장비(Go1)는 **옛 로봇 줄 그대로** — 회귀가 없다
//  5. 없는 키를 0 으로 읽지 않는다 — `fc_link_age_s` 가 없으면 「n초 전」을 안 적는다
//
// 대조군 — `fc_link` 를 0 으로 채워 읽는 사본이 잡혀야 한다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { PING_REPLY_HEX, bytes } from './lib/droneFixtures.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { checkPhysical } = await load('src', 'shared', 'connectionCheck.ts');
const { decodeUplink } = await load('src', 'physical', 'uplink.ts');
const { LINK_WATCH_MS } = await load('src', 'physical', 'linkWatch.ts');

const failures = [];
const controls = [];

const open = { getStatus: () => ({ state: 'open' }), connect: async () => ({ state: 'open' }) };
const who = async () => ({ deviceId: 'x500-001', kind: 'drone', deviceType: 'x500_drone' });
const find = (lines, id) => lines.find((l) => l.id === id);

// ── 1. 실측 응답에서 fc_link 를 읽는다 ───────────────────────────────────────
{
  // 계약 §5 의 네 번째 메시지 — `result{SUCCEEDED, uptime_s:3.8, fc_link:0}`.
  const result = decodeUplink(bytes(PING_REPLY_HEX[3]));
  if (result?.kind !== 'result') failures.push('실측 result 를 못 뜯었다');
  else {
    if (result.result.fc_link !== 0) failures.push(`fc_link 가 ${result.result.fc_link} — 실측은 0 이다`);
    if (!('uptime_s' in result.result)) failures.push('uptime_s 를 못 읽었다');
    // **한 번도 heartbeat 를 못 받으면 키가 통째로 없다** (계약 §5). 0 이 아니다.
    if ('fc_link_age_s' in result.result) failures.push('실측에 없는 fc_link_age_s 가 있다');
  }
}

// ── 2. FC 링크가 없으면 그 줄만 빨갛다 ───────────────────────────────────────
{
  const lines = await checkPhysical({
    ...open, identity: who,
    ping: async () => ({ ok: true, roundTripMs: 9, message: '답했습니다', fcLink: false, fcLinkAgeSec: null }),
  });
  if (find(lines, 'broker')?.ok !== true) failures.push('FC 가 끊겼다고 브로커까지 빨개졌다');
  if (find(lines, 'agent')?.ok !== true) failures.push('FC 가 끊겼다고 단말까지 빨개졌다');
  const third = find(lines, 'robot');
  if (third?.ok !== false) failures.push('FC 링크가 없는데 빨갛지 않다');
  if (third?.labelKey !== 'check.line.fcLink') failures.push(`셋째 줄 이름이 ${third?.labelKey} — FC 링크로 안 바뀌었다`);
  // 무엇을 봐야 하는지 적는다 — 「빨강」만으로는 결선을 볼지 전원을 볼지 모른다.
  if (!third?.reason) failures.push('FC 링크가 없는 사유를 안 적었다');
  // 장비 줄에 **무엇과 말했는지**가 적힌다 — pi7 인지 pi3 인지 화면에서 보여야 한다.
  if (!String(find(lines, 'agent')?.reason ?? '').includes('x500-001')) {
    failures.push('장비 줄에 장비 이름이 없다 — 어디에 붙었는지 화면에서 못 본다');
  }
}

// ── 3. 줄은 셋이다 ───────────────────────────────────────────────────────────
{
  const lines = await checkPhysical({
    ...open, identity: who,
    ping: async () => ({ ok: true, roundTripMs: 9, message: '답했습니다', fcLink: true, fcLinkAgeSec: 0.2 }),
  });
  if (lines.length !== 3) failures.push(`줄이 ${lines.length}개 — 셋이어야 한다 (넷으로 늘리면 기존 검사가 깨진다)`);
  if (find(lines, 'robot')?.ok !== true) failures.push('FC 링크가 있는데 초록이 아니다');
  if (!String(find(lines, 'robot')?.reason ?? '').includes('0.2')) failures.push('받은 나이를 안 적었다');
}

// ── 4. fc_link 를 안 싣는 장비는 옛 로봇 줄 그대로 (Go1 회귀) ────────────────
{
  const robot = { online: true, link: 'ok', health: 'ok', batteryPct: 77, stale: false, staleSec: 0 };
  const lines = await checkPhysical({
    ...open,
    // Go1 의 목은 `fcLink` 라는 칸 자체가 없다 — 옛 목 그대로다.
    ping: async () => ({ ok: true, roundTripMs: 12, message: '로봇이 답했습니다' }),
  }, robot);
  if (lines.length !== 3) failures.push(`Go1 줄이 ${lines.length}개`);
  const third = find(lines, 'robot');
  if (third?.labelKey !== 'check.line.robot') failures.push(`Go1 셋째 줄이 ${third?.labelKey} 로 바뀌었다 — 회귀다`);
  if (third?.ok !== true) failures.push('Go1 의 link 가 ok 인데 초록이 아니다');
}

// ── 5. 없는 키를 0 으로 읽지 않는다 ──────────────────────────────────────────
{
  const lines = await checkPhysical({
    ...open, identity: who,
    // `fc_link` 는 실렸고 `fc_link_age_s` 는 없다 — 계약 §5 의 실제 모양이다.
    ping: async () => ({ ok: true, roundTripMs: 9, message: '답했습니다', fcLink: true }),
  });
  const reason = String(find(lines, 'robot')?.reason ?? '');
  if (/0(\.0)?초/.test(reason)) failures.push(`나이가 없는데 「${reason}」— 0 은 「방금 받았다」가 된다`);
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name}`);
  controls.push(name);
}
{
  // `fcLink` 를 아예 안 주면(모름) 셋째 줄은 **FC 링크가 아니어야** 한다.
  const lines = await checkPhysical({
    ...open, identity: who,
    ping: async () => ({ ok: true, roundTripMs: 9, message: '답했습니다' }),
  }, null);
  control('모름을 FC 링크 줄로 그리지 않는다', find(lines, 'robot')?.labelKey === 'check.line.robot');
}
{
  // 단말이 안 답하면 FC 링크는 **못 물어본 것**이지 끊긴 것이 아니다.
  const lines = await checkPhysical({
    ...open, identity: who,
    ping: async () => ({ ok: false, roundTripMs: null, message: '답이 없습니다', fcLink: false }),
  });
  control('단말이 침묵하면 FC 링크는 모른다', find(lines, 'robot')?.ok === null);
}
{
  // 되풀이 간격이 드론 주기(1Hz)보다 촘촘하지 않다 — 쓸데없이 명령을 쏟지 않는다.
  control('다시 재는 간격이 1초 이상', LINK_WATCH_MS >= 1000);
}

if (failures.length) {
  console.error(`❌ verify:fc-link\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ ping 의 실측 result 에서 fc_link 를 읽는다 — 없는 키는 모름으로 둔다');
console.log('✅ FC 링크가 끊기면 그 줄만 빨갛다 · 줄은 여전히 셋 · 장비 이름이 줄에 적힌다');
console.log(`✅ fc_link 를 안 싣는 장비(Go1)는 옛 로봇 줄 그대로 · 감시 간격 ${LINK_WATCH_MS}ms`);
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
