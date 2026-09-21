// verify:no-hardcoded-target (260921 신설 — 드론 연결 2단계)
//
// **발행 대상이 상수가 아니라 받은 device_id 인가. 모르면 안 나가는가.**
//
// 막으려는 사고는 하나다. 드론에 붙은 채로 명령이 `terminal/go1-001/downlink` 로 나가는 것.
// pi3 브로커에는 그 토픽을 듣는 사람이 없어 **조용히 사라지고**, 화면은 「보냈다」고 적는다.
// 같은 랜에 pi7 이 살아 있으면 더 나쁘다 — 엉뚱한 로봇이 움직인다.
//
// 보는 것 넷.
//  1. 붙은 장비가 자기를 밝히면 **그 이름으로** 나간다
//  2. 아직 아무 말도 못 들었으면 **안 나간다** — 옛 상수로 물러서지 않는다
//  3. 장비가 바뀌면 대상도 따라 바뀐다 (생성자에 굳어 있지 않다)
//  4. 브로커에 장비가 둘로 보이면 **고르지 않는다** — 애매한 채로 쏘지 않는다
//
// **화면 조회는 물러서도 된다** — 빗나가면 「아직 아무것도 안 왔습니다」가 뜰 뿐이다.
// 위험한 것은 발행이고, 이 검사는 그쪽만 본다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DRONE, statusBody } from './lib/droneFixtures.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const {
  commandTarget, noteCapability, noteDeviceReport, resetDeviceIdentity,
} = await load('src', 'physical', 'deviceIdentity.ts');
const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
const { encodeCommand, hardwareTarget, HARDWARE_TARGET } = await load('src', 'physical', 'encode.ts');
const { physical } = await load('src', 'physical', 'protocol.js');

const failures = [];
const controls = [];

/** 붙은 척하고 **실제로 발행된 토픽과 바이트**를 받아 적는 클라이언트. */
function wired() {
  const client = new PhysicalClient();
  const sent = [];
  // 소켓 대신 받아 적는 것을 꽂는다 — 진짜 `send()` 경로를 그대로 지난다.
  client.client = { publish: (topic, payload) => sent.push({ topic, payload }) };
  client.status = { state: 'open' };
  return { client, sent };
}

/** 발행된 바이트에서 `target` 을 도로 뜯는다 — 적힌 대로 나갔는지 본다. */
function targetOf(payload) {
  return physical.PhysicalCommandEnvelope.decode(payload).command?.target ?? null;
}

// ── 1. 밝힌 이름으로 나간다 ──────────────────────────────────────────────────
{
  resetDeviceIdentity();
  noteCapability(DRONE.entityId, ['ping']);
  const { client, sent } = wired();
  const outcome = client.send('ping');
  if (!outcome.sent) failures.push(`장비를 아는데 안 보냈다 — ${outcome.reason}`);
  if (sent.length !== 1) failures.push(`발행이 ${sent.length}건`);
  else {
    if (sent[0].topic !== `terminal/${DRONE.entityId}/downlink`) {
      failures.push(`토픽이 ${sent[0].topic} — 받은 이름으로 안 갔다`);
    }
    if (targetOf(sent[0].payload) !== DRONE.entityId) {
      failures.push(`봉투의 target 이 ${targetOf(sent[0].payload)}`);
    }
  }
}

// ── 2. 모르면 안 나간다 (요점) ───────────────────────────────────────────────
{
  resetDeviceIdentity();
  const { client, sent } = wired();
  const outcome = client.send('ping');
  if (outcome.sent) failures.push('장비를 모르는데 보냈다 — 어디로 갔는지 아무도 모른다');
  if (sent.length !== 0) failures.push(`아무 말도 못 들었는데 ${sent.length}건이 나갔다`);
  if (!outcome.reason) failures.push('안 보낸 사유를 안 적었다 — 조용히 삼키면 안 된다');
  // **옛 상수로 물러서지 않았는지**까지 본다. 물러섰다면 토픽에 그 이름이 찍혔을 것이다.
  if (sent.some((s) => s.topic.includes(HARDWARE_TARGET))) failures.push('옛 상수로 물러서서 발행했다');
}

// ── 3. 장비가 바뀌면 대상도 바뀐다 ───────────────────────────────────────────
//
// 전에는 대상이 **생성자에서 굳었다.** 싱글턴이라 앱이 사는 내내 고정됐고, 주소를 바꿔
// 드론에 붙어도 `go1-001` 에 남았다. 같은 클라이언트로 두 장비를 겪게 해 본다.
{
  resetDeviceIdentity();
  const { client, sent } = wired();
  noteCapability('go1-001', ['ping', 'abort']);
  client.send('ping');
  resetDeviceIdentity();
  noteDeviceReport(DRONE.entityId, DRONE.entityType, statusBody());
  client.send('ping');
  const topics = sent.map((s) => s.topic);
  if (topics[0] !== 'terminal/go1-001/downlink') failures.push(`첫 장비에 ${topics[0]}`);
  if (topics[1] !== `terminal/${DRONE.entityId}/downlink`) failures.push(`장비가 바뀌었는데 ${topics[1]} — 대상이 굳어 있다`);
}

// ── 4. 둘로 보이면 고르지 않는다 ─────────────────────────────────────────────
{
  resetDeviceIdentity();
  noteDeviceReport('go1-001', 'robot', statusBody({
    source_id: 'go1-001',
    registration: { entity_id: 'go1-001', entity_type: 'robot' },
  }));
  noteDeviceReport(DRONE.entityId, DRONE.entityType, statusBody());
  if (commandTarget() !== null) failures.push(`장비가 둘인데 ${commandTarget()} 를 골랐다`);
  const { client, sent } = wired();
  if (client.send('ping').sent) failures.push('애매한데 보냈다 — 둘 중 하나는 남의 장비다');
  if (sent.length !== 0) failures.push('애매한데 바이트가 나갔다');
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name}`);
  controls.push(name);
}
{
  // 봉투 인코더는 **부르는 쪽이 지정한 대상을 안 덮어쓴다** — 덮어쓰면 지정한 것과 나간 것이 달라진다.
  resetDeviceIdentity();
  noteCapability(DRONE.entityId, ['ping']);
  const explicit = encodeCommand({ commandId: 'cmd-00000001', action: 'ping', target: 'go1-001' });
  control('인코더가 지정한 대상을 안 덮어쓴다', targetOf(explicit) === 'go1-001');
  // 화면 **조회**는 붙은 장비를 먼저 본다 — 발행과 달리 여기는 따라가야 한다.
  control('조회는 붙은 장비를 먼저 본다', hardwareTarget('robot-01') === DRONE.entityId);
  resetDeviceIdentity();
  control('아무 말도 못 들으면 조회만 옛 표로 물러선다', hardwareTarget('robot-01') === HARDWARE_TARGET);
}

resetDeviceIdentity();

if (failures.length) {
  console.error(`❌ verify:no-hardcoded-target\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 발행 대상·토픽이 받은 device_id 다 — 장비가 바뀌면 따라 바뀐다');
console.log('✅ 장비가 자기를 밝히기 전에는 한 바이트도 안 나간다 (옛 상수로 안 물러선다)');
console.log('✅ 브로커에 장비가 둘로 보이면 고르지 않는다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
