// verify:device-cards (260921 신설 — 드론 연결 · 하드웨어 카드)
//
// **카드는 「지금 붙어 있다」 하나만 뜻하는가.**
//
// 두 번 고친 자리다. 카드는 원래 **대본 배역**이었고, 그래서 대본에 안 적힌 드론은 붙어
// 있어도 안 보였다(260921). 그래서 「배역 ∪ 붙어 있는 것」으로 합쳤더니, 이번에는
// **아무것도 안 붙어도 옛 편의 자리표시 일곱 장이 떠 있었다** — 사람이 그것을 보고
// 「이건 더미 카드인가」라고 물었다(260922). 물어야 알 수 있으면 화면이 말한 것이 아니다.
//
// 그래서 뜻을 하나로 줄였다: **카드가 있다 = 지금 값이 흐른다.**
//
// 보는 것 다섯.
//  1. 값이 오는 장비는 **임무와 상관없이** 카드가 된다
//  2. **대본 배역은 카드가 아니다** — 아무것도 안 붙으면 한 장도 안 뜬다
//  3. 조용해지면 **빠진다** — 꺼진 장비를 붙은 것처럼 두지 않는다
//  4. 두 길(`/state` · MQTT)로 같은 id 가 오면 **한 장으로** 센다
//  5. **단독 빌드가 `tabs/` 를 안 끌어온다** — 카드 때문에 대시보드 계층이 딸려 오면 안 된다
//
// 5번이 이 구조의 이유다. 그리는 쪽이 `/state` 저장소를 직접 읽으면 측정축 D 가 오염된다
// (`verify:standalone`). 그래서 **받는 쪽이 밀어 넣고** 그리는 쪽은 `shared/` 만 읽는다.

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, normalize, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
// 자리표에 줄바꿈이 들어간다 — **LF 로 정규화한 원본**에서 만든다 (`verify:crlf-safe`).
import { readSource } from './lib/source.mjs';
import { DRONE } from './lib/droneFixtures.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
// 사전을 읽어 **키의 값까지** 본다 — 키만 맞고 사전이 비면 화면에 키가 그대로 뜬다.
const { ko: koDict } = await import(pathToFileURL(join(root, 'src', 'i18n', 'ko.ts')).href);

const {
  CONNECTED_WINDOW_MS, connectedDevice, connectedDevices, noteConnectedEntity, resetConnectedDevices,
} = await load('src', 'shared', 'connectedDevices.ts');
const { listDeviceCardIds, deviceCardOrigin } = await load('src', 'shared', 'registry.ts');
const { listCastIds } = await load('src', 'shared', 'registry.ts');

const failures = [];
const controls = [];

const cast = listCastIds();

// ── 1·2. 붙은 것만 카드가 된다 ──────────────────────────────────────────────
{
  resetConnectedDevices();
  /**
   * **아무것도 안 붙었으면 한 장도 없다** (260922 지시 — 「더미 카드는 제거」).
   *
   * 여기가 이번에 뒤집힌 자리다. 전에는 대본 배역이 그대로 카드가 됐고, 옛 편
   * (`MSN-260826-01`)이 `go1-02`·`arm-03`·`cam-4f` … 일곱을 들고 있어서 연결이 0건인데도
   * 카드가 일곱 장이었다. 그 카드의 배터리·RSSI 는 자리표시이고 끌어다 배정해도 아무 일도
   * 안 일어난다 — 없는 장비를 그려 둔 자리다.
   */
  const before = listDeviceCardIds();
  if (before.length !== 0) {
    failures.push(`아무것도 안 붙었는데 카드가 ${before.length}장 — ${before.join(',')}`);
  }
  /**
   * **배역을 아예 안 읽는가** — 원본으로 잰다.
   *
   * 돌려서 재고 싶었지만 검사 기본 상태는 임무가 없어 `cast` 가 비어 있다. 그대로 재면
   * 「배역을 합친 사본」과 「안 합친 지금」이 **같은 답을 낸다** — 그러면 이 검사는 아무것도
   * 안 잰다. 실제로 260922 에 그 상태로 한 번 통과했고, 대조군이 그것을 잡아 줬다.
   * (대본을 열어 재려 했으나 `enterScriptPreview` 가 Node 에서 안 끝난다 — 브라우저 몫이다.)
   *
   * 그래서 **함수가 배역을 읽는지**를 원본에서 본다. 배역은 여전히 읽을 수 있고
   * (`listCastIds` · 마일스톤의 `assignedTargets`) 카드가 되지 않을 뿐이라, 파일 전체가
   * 아니라 **이 함수 몸통**만 본다.
   */
  const registry = readSource(join(root, 'src', 'shared', 'registry.ts'));
  const after1 = registry.slice(registry.indexOf('export function listDeviceCardIds'));
  // 함수 몸통만 잘라 본다 — 파일 전체를 보면 `listCastIds` 가 걸려 헛돈다.
  const fnBody = after1.slice(0, after1.indexOf(String.fromCharCode(10) + '}') + 2);
  if (fnBody.includes('.cast')) {
    failures.push('카드 목록이 대본 배역을 읽는다 — 붙지 않은 장비가 카드로 뜬다');
  }
  if (!fnBody.includes('connectedDevices()')) failures.push('카드 목록이 붙은 장비를 안 읽는다');
  // 배역을 읽는 길 자체는 남아 있어야 한다 — 없애는 것이 아니라 카드에서 뺀 것이다.
  if (typeof listCastIds !== 'function') failures.push('배역을 읽는 길이 사라졌다');

  // 드론이 들어온다. **대본에는 없다.**
  noteConnectedEntity(DRONE.entityId, 'state');
  const after = listDeviceCardIds();
  if (!after.includes(DRONE.entityId)) failures.push('붙은 드론이 카드에 없다 — 대본에 없으면 안 보인다');
  /**
   * **드론 하나만** (260922 지시 — 「드론 연결했으면 드론 하나만 띄우는 게 맞아」).
   * 대본이 열린 채로 잰다 — 배역 둘이 딸려 오면 여기서 3장이 된다.
   */
  if (after.length !== 1) failures.push(`드론 하나만 붙었는데 카드가 ${after.length}장 — ${after.join(',')}`);
  // 무엇으로 떴는지 화면이 가릴 수 있어야 한다.
  if (deviceCardOrigin(DRONE.entityId) !== 'connected') failures.push('붙어서 뜬 카드를 배역으로 적었다');
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

  /**
   * ⑤ **한 장도 없을 때 그 사실을 적는가** (260922).
   * 빈 자리는 「고장인가」로 읽힌다 — 아무것도 안 붙었다는 것과 화면이 못 그렸다는 것은
   * 다른 말이고, 그 차이를 화면이 말해야 한다.
   */
  if (!/cards\.length === 0/.test(main)) failures.push('카드가 0장일 때 아무 말도 안 한다');
  if (koDict['ms.noConnectedDevice'] === undefined) {
    failures.push('빈 자리 문구가 사전에 없다 — 화면에 키가 그대로 뜬다');
  }
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name}`);
  controls.push(name);
}
{
  resetConnectedDevices();
  /**
   * **옛 규칙(배역도 카드가 된다)을 흉내 내면 연결 0건에 카드가 생겨야 한다** — 260922 의
   * 그 불만이다. 고친 것이 진짜 고쳐졌는지 보려면 안 고친 것이 어떻게 틀렸는지도 재야 한다.
   */
  const oldUnion = (castIds) => [...castIds, ...connectedDevices().map((d) => d.entityId)];
  control('옛 규칙은 아무것도 안 붙어도 배역을 카드로 그린다',
    oldUnion(['robot-01', 'camera-02']).length === 2);
  // 원본 판정도 반대쪽을 잰다 — 배역을 읽는 사본은 반드시 잡혀야 한다.
  control('배역을 읽는 사본은 잡힌다',
    'return [...displayMission().view.cast, ...connectedDevices()];'.includes('.cast'));
  control('붙은 것만 읽는 지금은 안 잡힌다',
    !'return connectedDevices().map((device) => device.entityId);'.includes('.cast'));
  control('지금 규칙은 연결 0건이면 0장', listDeviceCardIds().length === 0);
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
console.log('✅ 카드는 「지금 붙어 있다」 하나만 뜻한다 — 연결 0건이면 0장, 드론만 붙으면 1장');
console.log(`✅ ${CONNECTED_WINDOW_MS / 1000}초 조용하면 빠지고, 다시 오면 돌아온다 · 두 길로 와도 한 장`);
console.log('✅ 화면이 그 목록을 그리고, 0장일 때 그 사실을 적는다 (더블클릭으로 상태를 연다)');
console.log('✅ 단독 빌드가 tabs/ 를 안 끌어온다 — 받는 쪽이 밀어 넣고 그리는 쪽은 shared/ 만 읽는다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
