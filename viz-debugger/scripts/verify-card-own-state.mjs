// verify:card-own-state (261126 신설 — 카메라 카드에 Go1 배터리)
//
// **로봇이 아닌 카드는 자기 상태만 그리는가.**
//
// Go1 과 360 카메라를 같이 붙이자 카메라 카드에 배터리가 둘 떴다 — 하나는 카메라(`/frame` 의 `X-State`), 하나는
// **Go1 의 MQTT 배터리**였다. 배터리를 안 싣는 다른 카메라로 바꿔도 Go1 배터리가 떴고, Go1 을 끊자 사라졌다(실물 확인).
// 카드 한 줄(`HardwareLink`)이 `hardwareTarget(entityId)` 로 찾는데, 그 함수는 붙은 로봇이 있으면 **넘겨받은 id 를
// 안 보고** 그 로봇 id 를 돌려주기 때문이다.
//
// 보는 것 — Go1(`go1-001`)이 자기를 밝힌 상태에서
//   ① 고정 카메라 · 3D 가상환경 카드는 **자기 id** 로 찾는다(`cardStateId(id, true)`)
//   ② 로봇 카드는 지금까지처럼 **붙은 로봇**을 본다(`cardStateId('robot-01', false)` → `go1-001`)
//   ③ 카드 한 줄이 실제로 그렇게 부른다 — `main.tsx` 가 두 카드에 `ownStateOnly` 를 켜고, `HardwareLink` 가 그것을 쓴다
//
// 대조군 넷 — `src/` 통째 복사 · LF 정규화 원본에서 한 줄(`lib/actionTimeRun.mjs` 의 `mutantTree`).

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { mutantTree } from './lib/actionTimeRun.mjs';
import { readSource } from './lib/source.mjs';

const vizRoot = join(fileURLToPath(new URL('.', import.meta.url)), '..');

async function judge(root) {
  const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
  const { cardStateId } = await load('src', 'physical', 'encode.ts');
  const { noteCapability, resetDeviceIdentity, commandTarget } = await load('src', 'physical', 'deviceIdentity.ts');
  const { FIXED_CAMERA_ID_PREFIX } = await load('src', 'fixedcam', 'fixedCamera.ts');
  const bad = [];

  resetDeviceIdentity();
  noteCapability('go1-001', ['move', 'stop'], 'ws://pi7:9001');
  if (commandTarget() !== 'go1-001') return [`판을 못 세웠다 — 붙은 로봇이 ${commandTarget()}`];

  // ①
  const camera = `${FIXED_CAMERA_ID_PREFIX}1`;
  if (cardStateId(camera, true) !== camera) bad.push(`① 카메라 카드가 ${cardStateId(camera, true)} 의 상태를 찾는다 — 로봇 배터리가 카메라 카드에 뜬다`);
  if (cardStateId('twin-lab', true) !== 'twin-lab') bad.push(`① 3D 카드가 ${cardStateId('twin-lab', true)} 의 상태를 찾는다`);
  // ②
  if (cardStateId('robot-01', false) !== 'go1-001') bad.push(`② 로봇 카드가 붙은 로봇을 안 본다 — ${cardStateId('robot-01', false)}`);

  // ③
  const main = readSource(root, 'src', 'main.tsx');
  const line = main.slice(main.indexOf('function CardStatusLine'));
  const body = line.slice(0, line.indexOf('\n}') + 2);
  if (!/isFixedCamera\(entityId\)\) return <><HardwareLink entityId=\{entityId\} ownStateOnly \/>/.test(body)) bad.push('③ 고정 카메라 카드가 ownStateOnly 를 안 켠다');
  if (!/isTwinDevice\(entityId\)\) return <HardwareLink entityId=\{entityId\} ownStateOnly \/>/.test(body)) bad.push('③ 3D 카드가 ownStateOnly 를 안 켠다');
  const link = readSource(root, 'src', 'physical', 'HardwareLink.tsx');
  if (!link.includes('devices[cardStateId(entityId, ownStateOnly)]')) bad.push('③ HardwareLink 가 ownStateOnly 대로 찾지 않는다');
  if (/hardwareTarget\(/.test(link)) bad.push('③ HardwareLink 가 아직 hardwareTarget 으로 찾는다');

  resetDeviceIdentity();
  return bad;
}

const failures = [];
const real = await judge(vizRoot);
failures.push(...real);
if (real.length === 0) console.log('✅ 원본 — Go1 이 붙어 있어도 카메라 · 3D 카드는 자기 상태만 · 로봇 카드는 붙은 로봇을 본다');

const controls = [
  { name: 'ownOnly 를 무시하는 사본(고치기 전 모양)', file: 'src/physical/encode.ts', from: '  return ownOnly ? vizEntityId : hardwareTarget(vizEntityId);', to: '  return hardwareTarget(vizEntityId);' },
  { name: '카메라 카드가 옵션을 안 켜는 사본', file: 'src/main.tsx', from: '<><HardwareLink entityId={entityId} ownStateOnly /><CameraStateDots', to: '<><HardwareLink entityId={entityId} /><CameraStateDots' },
  { name: '3D 카드가 옵션을 안 켜는 사본', file: 'src/main.tsx', from: 'if (isTwinDevice(entityId)) return <HardwareLink entityId={entityId} ownStateOnly />;', to: 'if (isTwinDevice(entityId)) return <HardwareLink entityId={entityId} />;' },
  { name: 'HardwareLink 가 옵션을 버리는 사본', file: 'src/physical/HardwareLink.tsx', from: 'devices[cardStateId(entityId, ownStateOnly)]', to: 'devices[cardStateId(entityId, false)]' },
];
const caught = [];
for (const c of controls) {
  const tree = mutantTree('.verify-cardstate-', c.file, c.from, c.to);
  if (tree === null) { failures.push(`대조군을 만들지 못했다: ${c.name} — 치환이 아무것도 안 바꿨다`); continue; }
  try {
    const hit = await judge(tree.root);
    if (hit.length > 0) caught.push(`${c.name} (${hit[0].slice(0, 55)})`);
    else failures.push(`대조군 실패: ${c.name} — 변조 사본이 잡히지 않았다`);
  } finally {
    tree.cleanup();
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:card-own-state — ${failures.length}건\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${caught.length}/${controls.length} 잡힘\n- ${caught.join('\n- ')}`);
console.log('✅ verify:card-own-state 통과');
