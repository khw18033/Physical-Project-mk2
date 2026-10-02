// verify:server-link (261001 신설 — 「서버와 통신은 되는데 하드웨어 카드에 안 뜬다」)
//
// 원인은 카드 목록이 MQTT 로 붙은 장비만 그리던 가름이었다(`registry.ts` — 목 게이트웨이의 가짜 함대를 걷어내려던 것).
// 백엔드 `/state` 로 온 실물 장비까지 같이 걸렀다.
//
// 보는 것 넷.
//  1. **서버 봉투와 목 봉투를 가른다** — 서버는 원래 메시지를 통째로 싣고 그 안에 공통 헤더가 있다. 주소로 가르지 않는다.
//  2. **서버 장비는 카드가 되고 목 함대는 안 된다.**
//  3. **연결 확인** — 소켓 · 값 수신 · 구역 세 줄. 값이 안 오면 구역 · 발행기를 사유로 적는다.
//  4. **서버 카드** — 게이트웨이가 우리 컴퓨터의 목이면 안 그린다 · 끌어서 놓을 수 없다.

import { createRequire } from 'node:module';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
const read = (...parts) => readSource(join(root, ...parts));
const failures = [];
const controls = [];

const feed = await load('src', 'shared', 'gatewayFeed.ts');
const connected = await load('src', 'shared', 'connectedDevices.ts');
const registry = await load('src', 'shared', 'registry.ts');

// 백엔드 어댑터가 실제로 싣는 모양(`vz_wire.to_vz_envelope` — payload 는 원래 메시지 통째).
const serverPayload = { schema_version: '1.1', source_id: 'go1-001', node_id: 'pi7', zone_id: 'zoneA', timestamp: '2026-10-01T10:00:00+09:00', channel: 'state', battery_pct: 80 };
// 목 게이트웨이 함대(`gateway/devices.ts`)의 모양 — 공통 헤더가 없다.
const mockPayload = { position: { x: 1, y: 0, z: 2, frame: 'site-global' }, battery_pct: 70, velocity: { linear_mps: 0, angular_rps: 0 }, is_moving: false, mission: null };

// ── 1. 가르기 ──────────────────────────────────────────────────────────────────
if (!feed.selfIntroduced(serverPayload)) failures.push('서버 봉투(공통 헤더 있음)를 서버 것으로 못 읽는다');
if (feed.selfIntroduced(mockPayload)) failures.push('목 함대 봉투를 서버 것으로 읽었다 — 가짜 함대가 카드로 돌아온다');
if (feed.selfIntroduced({ ...serverPayload, schema_version: undefined })) failures.push('대조군 실패: 헤더가 빠진 봉투를 서버 것으로 읽는다');
controls.push('공통 헤더가 빠진 봉투');

// ── 2. 카드 ───────────────────────────────────────────────────────────────────
{
  connected.resetConnectedDevices();
  connected.noteConnectedEntity('go1-001', feed.selfIntroduced(serverPayload) ? 'server' : 'state');
  connected.noteConnectedEntity('robot-01', feed.selfIntroduced(mockPayload) ? 'server' : 'state');
  connected.noteConnectedEntity('x500-001', 'mqtt');
  const cards = registry.listDeviceCardIds();
  if (!cards.includes('go1-001')) failures.push(`서버로 온 go1-001 이 카드에 없다 — ${cards}`);
  if (cards.includes('robot-01')) failures.push('목 함대(robot-01)가 카드에 떴다');
  if (!cards.includes('x500-001')) failures.push('MQTT 로 붙은 장비가 카드에서 빠졌다');
  connected.resetConnectedDevices();
  const index = read('src', 'tabs', 'data', 'index.ts');
  if (!/noteConnectedEntity\(envelope\.entity, selfIntroduced\(envelope\.payload\) \? 'server' : 'state'\)/.test(index)) failures.push('받는 쪽이 서버 봉투를 server 로 적지 않는다');
  if (!/noteGatewayEnvelope\(envelope\.entity, envelope\.payload\)/.test(index)) failures.push('받는 쪽이 게이트웨이 수신을 적지 않는다 — 연결 확인이 셀 것이 없다');
}

// ── 2-b. 화면이 다시 그려지는가 (261002 — 「드론이 붙었는데 카드에 안 뜬다 · 임무를 걸면 뜬다」) ──────────
//
// 저장소에는 들어왔는데 구독 스냅샷이 500ms 캐시의 옛 목록을 돌려줘서 React 가 「안 바뀌었다」로 보고 넘어갔다.
// 연결 확인 직후 세션이 열려 다시 그린 **바로 뒤**에 retained `status` 가 오는 순서다. 그 뒤로는 1초 안에 계속
// 와서 다시 알리지도 않으므로, 한 번 놓치면 다른 이유로 판이 다시 그려질 때까지 카드가 안 떴다.
{
  const require = createRequire(join(root, 'package.json'));
  const { createElement } = require('react');
  const { renderToString } = require('react-dom/server');
  let seen = null;
  const Probe = () => { seen = connected.useConnectedDevices(); return null; };
  const snap = () => { renderToString(createElement(Probe)); return seen; };

  connected.resetConnectedDevices();
  const before = snap();
  connected.noteConnectedEntity('x500-001', 'mqtt');
  const after = snap();
  if (after === before || !after.some((d) => d.entityId === 'x500-001')) failures.push('그린 직후 들어온 장비가 구독 스냅샷에 안 잡힌다 — 카드가 다시 안 그려진다');

  // 같은 장비가 다른 길로 오면(목 `state` → 서버 `server`) 카드 대상이 바뀐다 — id 가 같아도 새 참조여야 한다.
  connected.resetConnectedDevices();
  connected.noteConnectedEntity('go1-001', 'state');
  const asState = snap();
  connected.noteConnectedEntity('go1-001', 'server');
  if (snap() === asState) failures.push('들어온 길이 바뀌었는데 스냅샷이 그대로다 — 서버 장비가 카드로 안 바뀐다');

  // 대조군: 아무것도 안 바뀌면 같은 참조여야 한다(매번 새 배열이면 무한히 다시 그린다).
  const still = snap();
  if (snap() !== still) failures.push('대조군 실패: 바뀐 것이 없는데 스냅샷 참조가 바뀐다');
  controls.push('바뀐 것 없는 스냅샷');
  connected.resetConnectedDevices();
}

// ── 3. 연결 확인 ───────────────────────────────────────────────────────────────
{
  const { checkGateway } = await load('src', 'shared', 'connectionCheck.ts');
  const { registerConnectionDefault } = await load('src', 'shared', 'connections.ts');
  registerConnectionDefault('gateway', 'zone', 'zone-503');
  feed.resetGatewayFeed();
  feed.noteGatewaySocket('open');
  setTimeout(() => feed.noteGatewayEnvelope('go1-001', serverPayload, Date.now()), 150);
  const ok = await checkGateway(1500);
  const byId = Object.fromEntries(ok.map((row) => [row.id, row]));
  if (byId.socket?.ok !== true) failures.push(`소켓이 열렸는데 ${JSON.stringify(byId.socket)}`);
  if (byId.feed?.ok !== true || !String(byId.feed.reason).includes('go1-001')) failures.push(`값이 왔는데 ${JSON.stringify(byId.feed)}`);
  if (byId.zone?.ok !== null || byId.zone.reason !== 'zone-503') failures.push(`구역 줄이 ${JSON.stringify(byId.zone)}`);
  const empty = await checkGateway(400);
  const emptyFeed = empty.find((row) => row.id === 'feed');
  if (emptyFeed?.ok !== false || !String(emptyFeed.reason).includes('zone-503')) failures.push(`값이 안 오는데 사유에 구역이 없다 — ${JSON.stringify(emptyFeed)}`);
  controls.push('값이 안 오는 판(사유에 구역)');
  feed.noteGatewaySocket('closed');
  const closed = await checkGateway(100);
  if (closed.find((row) => row.id === 'socket')?.ok !== false) failures.push('소켓이 끊겼는데 성공으로 적었다');
  if (feed.maskToken('ws://h:8765/state?token=abc&x=1') !== 'ws://h:8765/state?token=***&x=1') failures.push('토큰을 가리지 않는다');
  const panel = read('src', 'shell', 'ConnectionsPanel.tsx');
  if (!/target === 'gateway';/.test(panel)) failures.push('연결 관리의 게이트웨이에 확인 버튼이 없다');
  feed.resetGatewayFeed();
}

// ── 4. 서버 카드 ───────────────────────────────────────────────────────────────
{
  const card = read('src', 'shell', 'ServerCard.tsx');
  if (/draggable/.test(card)) failures.push('서버 카드를 끌 수 있다 — 장치 자리에 서버가 앉는다');
  // 261002 — 서버 상태를 묻는 훅이 판정과 return 사이에 들어가 두 줄로 갈렸다(`local`). 규칙은 같다.
  if (!/isLocalGateway\(url\)\) return null/.test(card) && !(/const local = url === '' \|\| isLocalGateway\(url\);/.test(card) && /if \(local\) return null;/.test(card))) failures.push('목 게이트웨이일 때도 서버 카드가 뜬다');
  const main = read('src', 'main.tsx');
  if (!/<ServerCard \/>/.test(main)) failures.push('오른쪽 기둥에 서버 칸이 없다');
  // 261001 — 서버는 장비가 아니라서 하드웨어 패널 **밖**, 오른쪽 기둥의 제 칸이다.
  const hardwarePanel = main.slice(main.indexOf('<aside className="hardware-panel"'), main.indexOf('<CapabilityPanel />'));
  if (/<ServerCard \/>/.test(hardwarePanel)) failures.push('서버 카드가 아직 하드웨어 패널 안에 있다');
  if (!/onDoubleClick=\{\(\) => setOpen\(true\)\}/.test(card)) failures.push('서버 카드를 더블클릭해도 상세가 안 열린다');
  const overlay = read('src', 'shell', 'ServerStatusOverlay.tsx');
  if (!/'Escape'/.test(overlay) || !/event\.target === event\.currentTarget/.test(overlay)) failures.push('서버 상세를 닫는 길이 하나뿐이다 — Esc · 배경 누르기');
  if (!/maskToken\(url\)/.test(overlay)) failures.push('서버 상세가 토큰을 가리지 않는다');
}

if (failures.length) {
  console.error(`❌ verify:server-link\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 서버 봉투(공통 헤더)와 목 함대를 가른다 · 서버 장비와 MQTT 장비는 카드, 목 함대는 아니다');
console.log('✅ 그린 직후 들어온 장비도 스냅샷에 잡힌다 · 들어온 길이 바뀌어도 다시 그린다');
console.log('✅ 연결 확인 —소켓 · 값 수신(받은 서버 장비 이름) · 구역 · 값이 안 오면 구역을 사유로 · 토큰은 가린다');
console.log('✅ 서버 칸 — 하드웨어 패널 밖 · 목 게이트웨이면 안 뜨고 끌 수 없다 · 더블클릭하면 상세(Esc · 배경으로 닫힘 · 토큰 가림)');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
process.exit(0);
