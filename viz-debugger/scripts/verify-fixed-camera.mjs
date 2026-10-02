// verify:fixed-camera (261002 신설 — 고정 카메라 · 360 카메라 연결 준비)
//
// **이미지가 받아지면 연결된 것이고, 연결되면 하드웨어 카드에 뜨는가.**
//
// 보는 것 다섯.
//  1. 연결 관리에서 「고정 카메라」가 로봇 바로 아래이고, 줄마다 카메라 한 대(목록 칸)이며 확인 버튼이 있다
//  2. 줄 순서로 장비 id 가 선다(`fixed-cam-1` …) — 빈 줄은 버린다
//  3. 확인 — 받아지면 초록 줄 + 연결 장비(`camera` 길)로 적히고, 안 받아지면 빨간 줄 + **안 적힌다**
//  4. `camera` 길로 온 장비는 하드웨어 카드다 · 상세가 고정 카메라 칸을 그린다
//  5. 추론 포트 묶기 — 카메라 주소가 곧 그 포트면 그 포트(`same`), 사람이 고른 것이 그보다 이긴다
//
// 대조군 — 받아지지 않은 카메라는 카드가 아니어야 하고, 목록에 없는 포트는 `same` 으로 묶이면 안 된다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readSource(join(root, ...p));

const failures = [];
const controls = [];

const connections = await load('src', 'shared', 'connections.ts');
const connected = await load('src', 'shared', 'connectedDevices.ts');
const registry = await load('src', 'shared', 'registry.ts');
const camera = await load('src', 'fixedcam', 'fixedCamera.ts');
const binding = await load('src', 'vision', 'binding.ts');

// ── 1. 연결 관리 ────────────────────────────────────────────────────────────────
{
  const ids = connections.CONNECTION_TARGETS.map((t) => t.id);
  const at = ids.indexOf('fixed-camera');
  if (at === -1) failures.push('연결 관리에 고정 카메라가 없다');
  else if (ids[at - 1] !== 'physical') failures.push(`고정 카메라가 로봇 바로 아래가 아니다 — 위가 ${ids[at - 1]}`);
  const target = connections.CONNECTION_TARGETS[at];
  if (target?.fields.length !== 1 || target.fields[0].list !== true) failures.push('고정 카메라 칸이 목록이 아니다 — 카메라가 늘면 줄이 늘어야 한다');
  const panel = read('src', 'shell', 'ConnectionsPanel.tsx');
  if (!/target === 'fixed-camera'/.test(panel)) failures.push('고정 카메라에 확인 버튼이 없다');
  const check = read('src', 'shared', 'connectionCheck.ts');
  if (!/target === 'fixed-camera'\) setHealth\(target, await checkFixedCameras\(\)\)/.test(check)) failures.push('확인이 고정 카메라 확인으로 안 간다');
}

// ── 2. 장비 id ────────────────────────────────────────────────────────────────
connections.saveConnections({ 'fixed-camera.url': 'http://cam-a/snap.jpg\n\n  http://10.0.0.9:10001/stream  ' });
{
  const cams = camera.fixedCameras();
  if (cams.length !== 2 || cams[0].entityId !== 'fixed-cam-1' || cams[1].entityId !== 'fixed-cam-2') failures.push(`장비 id 가 줄 순서대로 안 선다 — ${JSON.stringify(cams)}`);
  if (cams[1]?.url !== 'http://10.0.0.9:10001/stream') failures.push('주소 앞뒤 공백을 안 버린다');
  if (camera.fixedCameraUrl('fixed-cam-3') !== null) failures.push('없는 카메라의 주소를 지어낸다');
  if (camera.feedKindOf('http://10.0.0.9:10001/stream') !== 'stream') failures.push('스트림 주소를 한 장짜리로 본다');
  if (camera.feedKindOf('http://cam-a/snap.jpg') !== 'frames') failures.push('한 장짜리 주소를 스트림으로 본다 — 첫 장에서 멈춘다');
  if (camera.withNonce('http://a/x?y=1', 3) !== 'http://a/x?y=1&n=3') failures.push('차례 번호를 잘못 붙인다');
}

// ── 3. 확인 ───────────────────────────────────────────────────────────────────
connected.resetConnectedDevices();
{
  const probe = async (url) => (url.includes('cam-a')
    ? { ok: true, ms: 12, width: 3840, height: 1920 }
    : { ok: false, reason: '안 옴' });
  const lines = await camera.checkFixedCameras(probe);
  if (lines.length !== 2) failures.push(`카메라마다 한 줄이 아니다 — ${lines.length}줄`);
  if (lines[0]?.ok !== true || lines[0]?.scope !== 'fixed-cam-1') failures.push('받아진 카메라가 초록이 아니다 · 줄이 어느 카메라인지 안 적는다');
  if (lines[1]?.ok !== false || lines[1]?.reason !== '안 옴') failures.push('안 받아진 카메라의 사유가 줄에 안 남는다');
  const seen = connected.connectedDevices().map((d) => `${d.entityId}:${d.source}`);
  if (!seen.includes('fixed-cam-1:camera')) failures.push('받아진 카메라가 연결 장비로 안 적힌다');
  if (seen.some((s) => s.startsWith('fixed-cam-2'))) failures.push('대조군 실패: 안 받아진 카메라가 연결 장비로 적혔다');
  controls.push('안 받아진 카메라');

  // ── 4. 카드 ─────────────────────────────────────────────────────────────────
  const cards = registry.listDeviceCardIds();
  if (!cards.includes('fixed-cam-1')) failures.push('받아진 고정 카메라가 하드웨어 카드에 안 뜬다');
  if (cards.includes('fixed-cam-2')) failures.push('안 받아진 고정 카메라가 카드에 떴다');
  const overlay = read('src', 'views', 'DeviceStatusOverlay.tsx');
  if (!/fixedCamera \? <FixedCameraSection entityId=\{deviceId\} \/>/.test(overlay)) failures.push('상세가 고정 카메라 칸을 안 그린다');
  if (!/<VisionDeviceSection entityId=\{deviceId\} \/>/.test(overlay)) failures.push('상세에서 추론 스트림 칸이 빠졌다');

  const empty = await (connections.saveConnections({}), camera.checkFixedCameras(probe));
  if (empty.length !== 1 || empty[0].ok !== null) failures.push('주소가 없는데 「모른다」가 아니다 — 빨갛게 칠하면 카메라가 죽었다고 읽힌다');
}

// ── 5. 추론 포트 묶기 ─────────────────────────────────────────────────────────
connections.saveConnections({ 'fixed-camera.url': 'http://10.0.0.9:10001/stream' });
{
  const bases = ['http://10.0.0.9:10001', 'http://10.0.0.9:10002'];
  const direct = binding.deviceDirectBase('fixed-cam-1');
  if (direct !== 'http://10.0.0.9:10001') failures.push(`카메라 주소에서 포트 주소를 못 뽑는다 — ${direct}`);
  if (binding.deviceBrokerHost('fixed-cam-1') !== '10.0.0.9') failures.push('카메라의 호스트를 주소 맞대기에 못 쓴다');
  const same = binding.resolveVisionBinding(null, '10.0.0.9', {}, bases, direct);
  if (same.how !== 'same' || same.base !== 'http://10.0.0.9:10001') failures.push(`카메라 주소가 곧 포트인데 안 묶인다 — ${JSON.stringify(same)}`);
  const chosen = binding.resolveVisionBinding('http://10.0.0.9:10002', '10.0.0.9', {}, bases, direct);
  if (chosen.how !== 'chosen') failures.push('사람이 고른 포트가 안 이긴다');
  const outside = binding.resolveVisionBinding(null, '10.0.0.9', {}, ['http://10.0.0.9:10002'], direct);
  if (outside.how === 'same') failures.push('대조군 실패: 목록에 없는 포트로 묶었다');
  controls.push('목록에 없는 포트');
}

connections.resetConnections();
connected.resetConnectedDevices();

if (failures.length) {
  console.error('❌ verify:fixed-camera');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}
console.log('✅ 연결 관리 — 고정 카메라가 로봇 바로 아래 · 줄마다 카메라 한 대 · 확인 버튼');
console.log('✅ 이미지가 받아지면 연결 장비(camera) → 하드웨어 카드 · 안 받아지면 빨간 줄과 사유 · 주소가 없으면 모른다');
console.log('✅ 상세 — 고정 카메라 영상 칸 + 추론 스트림 칸 · 카메라 주소가 곧 포트면 자동으로 묶는다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
process.exit(0);
