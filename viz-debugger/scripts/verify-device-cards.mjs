// verify:device-cards (260921 신설 — 드론 연결 · 하드웨어 카드)
//
// **연결이 유지되는 장비는 임무와 상관없이 카드로 뜨는가.**
//
// 카드는 지금까지 **대본 배역**이었다. 그래서 대본에 안 적힌 장비는 붙어 있어도 안 보였고,
// 드론이 정확히 그 경우였다. 의도는 원래 「붙어 있으면 다 뜨고, 그중 쓸 것만 끌어다 쓴다」다.
//
// 보는 것 다섯.
//  1. 대본에 없는 장비도 **값이 오면** 카드 목록에 든다
//  2. **대본 배역은 값이 안 와도 남는다** — 하던 시연이 그대로 돈다
//  3. 조용해지면 **빠진다** — 꺼진 장비를 붙은 것처럼 두지 않는다
//  4. 두 길(`/state` · MQTT)로 같은 id 가 오면 **한 장으로** 센다
//  5. **단독 빌드가 `tabs/` 를 안 끌어온다** — 카드 때문에 대시보드 계층이 딸려 오면 안 된다
//
// 5번이 이 구조의 이유다. 그리는 쪽이 `/state` 저장소를 직접 읽으면 측정축 D 가 오염된다
// (`verify:standalone`). 그래서 **받는 쪽이 밀어 넣고** 그리는 쪽은 `shared/` 만 읽는다.

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, normalize, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DRONE } from './lib/droneFixtures.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const {
  CONNECTED_WINDOW_MS, connectedDevice, connectedDevices, noteConnectedEntity, resetConnectedDevices,
} = await load('src', 'shared', 'connectedDevices.ts');
const { listDeviceCardIds, deviceCardOrigin } = await load('src', 'shared', 'registry.ts');
const { listCastIds } = await load('src', 'shared', 'registry.ts');

const failures = [];
const controls = [];

const cast = listCastIds();

// ── 1·2. 붙은 장비는 들고, 대본 배역은 남는다 ───────────────────────────────
{
  resetConnectedDevices();
  // 아무것도 안 붙은 상태 — 카드는 대본 배역 그대로여야 한다 (하던 시연이 안 깨진다).
  const before = listDeviceCardIds();
  if (before.join(',') !== cast.join(',')) {
    failures.push(`아무것도 안 붙었는데 카드가 대본과 다르다 — ${before.join(',')}`);
  }

  // 드론이 `/state` 로 들어온다. **대본에는 없다.**
  noteConnectedEntity(DRONE.entityId, 'state');
  const after = listDeviceCardIds();
  if (!after.includes(DRONE.entityId)) failures.push('붙은 드론이 카드에 없다 — 대본에 없으면 안 보인다');
  for (const id of cast) {
    if (!after.includes(id)) failures.push(`대본 배역 ${id} 가 사라졌다 — 하던 시연이 깨진다`);
  }
  // 차례 — 배역이 먼저다.
  if (after.slice(0, cast.length).join(',') !== cast.join(',')) failures.push('배역이 앞에 안 온다');
  // 무엇으로 떴는지 화면이 가릴 수 있어야 한다.
  if (deviceCardOrigin(DRONE.entityId) !== 'connected') failures.push('붙어서 뜬 카드를 배역으로 적었다');
  if (cast.length > 0 && deviceCardOrigin(cast[0]) !== 'cast') failures.push('배역을 연결됨으로 적었다');
}

// ── 3. 조용해지면 빠진다 ─────────────────────────────────────────────────────
{
  resetConnectedDevices();
  const longAgo = Date.now() - CONNECTED_WINDOW_MS - 1_000;
  noteConnectedEntity(DRONE.entityId, 'state', longAgo);
  if (connectedDevice(DRONE.entityId) !== null) failures.push('창 밖인데 붙어 있다고 한다');
  if (listDeviceCardIds().includes(DRONE.entityId)) {
    failures.push('꺼진 장비가 카드에 남아 있다 — 끌어다 배정해도 아무 일이 안 일어난다');
  }
  // 다시 오면 돌아온다.
  noteConnectedEntity(DRONE.entityId, 'state');
  if (!listDeviceCardIds().includes(DRONE.entityId)) failures.push('다시 왔는데 안 돌아온다');
}

// ── 4. 두 길로 와도 한 장 ────────────────────────────────────────────────────
//
// Go1 이 `/state` 로 옮겨 가는 동안 두 길이 겹치는 기간이 있다(지시 — 「Go1 도 나중엔
// 서버 연결로」). 그때 카드가 둘로 갈라지면 안 된다.
{
  resetConnectedDevices();
  noteConnectedEntity('go1-001', 'mqtt');
  noteConnectedEntity('go1-001', 'state');
  const rows = connectedDevices().filter((d) => d.entityId === 'go1-001');
  if (rows.length !== 1) failures.push(`같은 장비가 ${rows.length}장으로 갈라졌다`);
  if (rows[0]?.source !== 'state') failures.push('나중에 온 길이 안 이겼다');
  if (listDeviceCardIds().filter((id) => id === 'go1-001').length !== 1) failures.push('카드 목록에 중복이 있다');
}

// ── 5. 단독 빌드가 tabs/ 를 안 끌어온다 ──────────────────────────────────────
//
// `verify:standalone` 과 같은 규칙을 **빌드 없이** 여기서도 본다. 카드를 고치다가
// `shared/registry.ts` 가 `tabs/` 를 부르면 그 순간 잡혀야 한다.
{
  const sourceRoot = normalize(join(root, 'src') + '/');
  const entry = join(sourceRoot, 'standalone.tsx');
  const visited = new Set();
  const forbidden = [];
  (function visit(path) {
    if (visited.has(path) || !existsSync(path)) return;
    visited.add(path);
    const source = readFileSync(path, 'utf8');
    for (const match of source.matchAll(/from\s+['"](\.[^'"]+)['"]/g)) {
      const next = normalize(join(dirname(path), match[1]));
      if (!/\.(ts|tsx)$/.test(next)) continue;
      const rel = relative(sourceRoot, next).replaceAll('\\', '/');
      if (rel.startsWith('tabs/')) forbidden.push(`${relative(sourceRoot, path)} → ${rel}`);
      visit(next);
    }
  })(entry);
  for (const hit of forbidden) failures.push(`단독 빌드가 대시보드 계층을 끌어온다: ${hit}`);

  // 검사가 헛돌지 않게 — 카드가 보는 저장소가 실제로 그 그래프 안에 있어야 한다.
  const storePath = normalize(join(sourceRoot, 'shared', 'connectedDevices.ts'));
  if (!visited.has(storePath)) {
    failures.push('단독 빌드가 connectedDevices 를 안 거친다 — 카드가 이 저장소를 안 본다는 뜻이다');
  }
}

// ── 6. **화면이 그 목록을 그리는가** (260922 — 5절까지 초록인데 드론이 안 보였다) ──
//
// 1~5절은 `listDeviceCardIds()` 를 쟀고 전부 초록이었다. 그런데 화면에는 드론이 없었다 —
// **판이 그 함수를 안 쓰는 갈래를 갖고 있었기** 때문이다.
//
// ```jsx
// {view.hardware ? hardware.map(…) : cast.map(…)}
// //              ^^^^^^^^^^^^^^^^ 대본에 실측 목록이 있으면 합집합을 통째로 건너뛴다
// ```
//
// 임무를 안 연 상태(`hardware: []`)도 빈 배열이 참이라 그 갈래로 갔고, 그래서 **카드가 한
// 장도 안 떴다.** 붙어 있는 드론을 볼 자리가 화면 어디에도 없었다.
//
// 검사가 화면과 다른 것을 재고 있었던 것이다. 그 자리를 메운다.
{
  const main = readFileSync(join(root, 'src', 'main.tsx'), 'utf8');

  // ① 판이 합집합을 그린다.
  if (!/useDeviceCardIds\(\)/.test(main)) failures.push('판이 카드 목록을 안 불러온다');
  if (!/cards\.map\(/.test(main)) failures.push('판이 카드 목록을 안 그린다 — 검사가 화면과 다른 것을 재고 있다');

  // ② **목록을 가르던 갈래가 없다.** 이것이 그 버그다.
  if (/view\.hardware\s*$/m.test(main) || /\{view\.hardware\s*\?/.test(main)) {
    failures.push('대본 실측 목록이 있으면 합집합을 건너뛰는 갈래가 남아 있다 — 260922 의 그 버그다');
  }
  // 세는 것도 합집합이어야 한다 — 「장비 n」과 실제 카드 수가 다르면 무엇을 믿을지 모른다.
  if (/hardwareCount[^}]*view\.hardware/.test(main)) {
    failures.push('머리줄의 장비 수가 합집합이 아니다');
  }

  // ③ 대본이 실측 행을 든 장비는 그것을 그리고, 아닌 것은 살아 있는 줄을 그린다.
  //    갈래는 **카드마다**여야 한다 — 목록을 가르는 조건이 아니다.
  if (!/hardware\.find\(/.test(main)) failures.push('카드마다 대본 실측 행을 찾지 않는다');
  if (!/HardwareLink/.test(main)) failures.push('붙어서 뜬 카드가 살아 있는 줄을 안 그린다');

  // ④ 더블클릭으로 상태를 열 수 있다 — **드론을 확인할 방법**이 그것이다 (260922 지시 2).
  if (!/onDoubleClick=\{\(\) => setStatusDeviceId\(id\)\}/.test(main)) {
    failures.push('카드를 더블클릭해도 상태가 안 열린다 — 드론을 확인할 방법이 없어진다');
  }
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name}`);
  controls.push(name);
}
{
  resetConnectedDevices();
  control('빈 목록이면 카드는 대본 그대로', listDeviceCardIds().join(',') === cast.join(','));
  noteConnectedEntity('', 'state');
  control('빈 id 는 안 담는다', connectedDevices().length === 0);
  noteConnectedEntity('cam-4f', 'state');
  control('카메라도 붙으면 뜬다 (로봇만이 아니다)', listDeviceCardIds().includes('cam-4f'));
}
{
  /**
   * **옛 갈래를 흉내 내면 드론이 사라져야 한다** — 260922 의 그 버그다.
   *
   * 고친 것이 진짜 고쳐진 것인지 보려면 안 고친 것이 어떻게 틀렸는지도 재야 한다.
   * 옛 판은 `view.hardware` 가 있으면 그쪽만 그렸다. 빈 배열도 참이라 임무를 안 열었을
   * 때조차 그 갈래로 갔다 — 그래서 카드가 한 장도 안 떴다.
   */
  resetConnectedDevices();
  noteConnectedEntity(DRONE.entityId, 'state');
  const union = listDeviceCardIds();
  const oldBranch = (viewHardware) => (viewHardware ? viewHardware.map((h) => h.id) : union);
  control('옛 갈래는 대본 실측 목록이 있으면 드론을 버린다',
    !oldBranch([{ id: 'go1-001' }]).includes(DRONE.entityId));
  control('옛 갈래는 임무를 안 열면 카드가 한 장도 없다 (빈 배열도 참이다)',
    oldBranch([]).length === 0 && union.length > 0);
  control('지금 목록은 임무와 상관없이 드론을 든다',
    union.includes(DRONE.entityId));
}
{
  // 받는 쪽이 실제로 밀어 넣는가 — 배선이 빠지면 카드가 영영 안 뜬다.
  const layer = readFileSync(join(root, 'src', 'tabs', 'data', 'index.ts'), 'utf8');
  control('/state 받는 자리가 밀어 넣는다', /noteConnectedEntity\(\s*envelope\.entity/.test(layer));
  const mqtt = readFileSync(join(root, 'src', 'physical', 'deviceState.ts'), 'utf8');
  control('MQTT 받는 자리가 밀어 넣는다', /noteConnectedEntity\(/.test(mqtt));
}

resetConnectedDevices();

if (failures.length) {
  console.error(`❌ verify:device-cards\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 붙은 장비는 대본에 없어도 카드로 뜬다 — 배역은 값이 안 와도 남는다');
console.log(`✅ ${CONNECTED_WINDOW_MS / 1000}초 조용하면 빠지고, 다시 오면 돌아온다 · 두 길로 와도 한 장`);
console.log('✅ 화면이 그 목록을 그린다 — 대본 실측 목록이 있어도 합집합을 안 건너뛴다 (더블클릭으로 상태를 연다)');
console.log('✅ 단독 빌드가 tabs/ 를 안 끌어온다 — 받는 쪽이 밀어 넣고 그리는 쪽은 shared/ 만 읽는다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
