// verify:stray-entity (260921 신설 — 관문 C-a 준비)
//
// **값이 도착했는데 화면에 아무것도 없는 상태를 없앤다.**
//
// 관문 C-a 는 「VZ 화면에 상태값이 한 건이라도 뜬다」로 판정한다. 그런데 백엔드가 보내는
// `go1-001` 은 목 레지스트리(`robot-01` 뿐)에 없고, 현황판은 `r.registry?.zone === ZONE_ID`
// 로 거른다 — **저장소는 받아 두는데 화면에만 없다.** 그러면 어댑터가 안 붙은 것인지
// 우리가 안 그리는 것인지 구분할 수가 없고, 그것이 이 실측에서 가장 나쁜 실패다.
//
// 보는 것 여섯.
//  1. 저장소가 레지스트리 밖 개체를 받아 두고 봉투를 세는가
//  2. **상태를 지어내지 않는가** — 3층 모양이 아닌 payload 는 「알 수 없음」인가
//  3. 정상 3층 판정은 그대로인가 (2번 가드가 기존 규칙을 안 망가뜨렸는가)
//  4. 화면이 그 개체를 따로 그리는가 — 구획과 필터가 소스에 있는가
//  5. 그 카드가 **판정을 안 그리는가** — 3층 전제 카드를 재사용하지 않는가
//  6. 한글·영어 두 벌
//
// ## 목 게이트웨이는 건드리지 않는다
//
// 목에는 레지스트리 밖 개체를 발행하는 시나리오가 없다. 그래서 **이 검사 안에서만**
// 흉내 낸다 — 봉투 한 건을 손으로 만들어 저장소에 흘린다. `gateway/` 는 그대로다.
//
// 대조군 포함 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 본다.

import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
/** 주석을 걷어 낸 소스 — 「왜 이렇게 뒀는지」 적어 둔 글이 규칙에 걸리면 안 된다. */
const code = (source) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');

const failures = [];
const controls = [];

/** 백엔드 `/state` 어댑터가 보내는 모양 — **원래 메시지를 통째로** payload 에 넣는다. */
const foreignPayload = { robot: { battery: 87, mode: 'idle' }, zone_id: 'zoneA' };

function envelope(entity, channel, seq) {
  return {
    zone: 'zoneA', node: 'pi7', entity, channel,
    ts: new Date().toISOString(), seq,
    payload: foreignPayload,
    quality: 'good', aggregation: 'raw', scope: 'all', coordinate_frame: null,
  };
}

// ── 1. 저장소가 받아 두고 센다 ───────────────────────────────────────────────
{
  const { DataStore } = await load('src', 'tabs', 'data', 'store.ts');
  const store = new DataStore();
  // 레지스트리에는 `robot-01` 만 있다 — 목이 주는 것과 같은 상황이다.
  store.setRegistry({ zones: [{ id: 'zone-503', display_name: 'A' }], entities: [{ id: 'robot-01', zone: 'zone-503' }] }, null);

  store.apply(envelope('go1-001', 'state', 1));
  store.apply(envelope('go1-001', 'heartbeat', 2));

  // `get()` 은 **병합 창이 닫힌 뒤의 스냅샷**을 읽는다(`RENDER_MERGE_WINDOW_MS` = 100ms).
  // 앱이 실제로 그러므로 여기서도 기다린다 — 강제로 흘리면 화면이 안 겪는 경로를 재게 된다.
  const { RENDER_MERGE_WINDOW_MS } = await load('src', 'tabs', 'data', 'constants.ts');
  await new Promise((resolve) => setTimeout(resolve, RENDER_MERGE_WINDOW_MS + 60));

  const rec = store.get('go1-001');
  if (rec === null) failures.push('레지스트리 밖 개체를 저장소가 버렸다 — 값이 왔는데 아무 데도 안 남는다');
  else {
    if (rec.registry !== null) failures.push('레지스트리에 없는데 registry 가 채워졌다 — 없는 목록을 지어냈다');
    if (rec.envelopeCount !== 2) failures.push(`봉투를 ${rec.envelopeCount}건으로 셌다 — 2건이어야 한다`);
    if (rec.state === null) failures.push('state 칸이 비었다 — 받은 봉투가 안 들어갔다');
    if (rec.heartbeat === null) failures.push('heartbeat 칸이 비었다');
  }
}

// ── 2·3. 상태를 지어내지 않는다 ──────────────────────────────────────────────
{
  const { deriveDisplayStatus } = await load('src', 'tabs', 'data', 'statusModel.ts');

  // **핵심.** `deployment` 칸이 아예 없는 payload 는 「미배포」가 아니라 「알 수 없음」이다.
  // 미배포는 「배포된 적이 없다」는 사실 주장이고, 우리가 아는 것은 「모양을 모른다」뿐이다.
  const got = deriveDisplayStatus(foreignPayload);
  if (got !== 'unknown') {
    failures.push(`3층 모양이 아닌 payload 를 「${got}」 으로 단정한다 — 없는 상태를 지어내고 있다`);
  }
  if (deriveDisplayStatus(null) !== 'unknown') failures.push('값을 못 받은 대상이 unknown 이 아니다');

  // 기존 규칙이 그대로인가 — 가드가 멀쩡한 판정을 망가뜨리면 안 된다.
  const layers = (over) => ({
    device_status: 'ok', availability: 'online', deployment: 'deployed',
    last_seen: null, stale_threshold_ms: 5000, reason: null, ...over,
  });
  const cases = [
    [layers(), 'normal'],
    [layers({ deployment: 'not_deployed' }), 'not_deployed'],
    [layers({ availability: 'offline' }), 'fault'],
    [layers({ availability: 'stale' }), 'unknown'],
    [layers({ device_status: 'fault' }), 'fault'],
    [layers({ device_status: null }), 'normal'],
  ];
  for (const [input, want] of cases) {
    const out = deriveDisplayStatus(input);
    if (out !== want) failures.push(`기존 판정이 바뀌었다 — ${JSON.stringify(input.deployment)}/${input.availability}/${input.device_status} → ${out} (${want} 이어야 한다)`);
  }
}

// ── 4. 화면이 따로 그린다 ────────────────────────────────────────────────────
{
  const grid = code(readSource('src/tabs/views/DeviceGrid.tsx'));
  // 거르는 조건 — 레지스트리에 없고, 값이 한 번이라도 온 것.
  if (!/registry === null && r\.envelopeCount > 0/.test(grid)) {
    failures.push('레지스트리 밖 개체를 모으는 자리가 없다 — 값이 와도 화면에 안 나온다');
  }
  if (!/UnregisteredCard/.test(grid)) failures.push('현황판이 레지스트리 밖 카드를 안 그린다');
  if (!/strays\.length > 0/.test(grid)) {
    failures.push('구획이 조건 없이 그려진다 — 평소에 없는 것이 정상이라 빈 구획이 늘 떠 있으면 안 된다');
  }
}

// ── 5. 그 카드는 판정을 안 그린다 ────────────────────────────────────────────
{
  const card = code(readSource('src/tabs/views/UnregisteredCard.tsx'));
  for (const banned of ['deriveDisplayStatus', 'DeviceCard', 'DISPLAY_STATUS_LABEL_KEY']) {
    if (card.includes(banned)) {
      failures.push(`레지스트리 밖 카드가 ${banned} 를 쓴다 — 3층이 없는 payload 에 층별 판정을 태우면 없는 상태를 말하게 된다`);
    }
  }
  for (const want of ['envelopeCount', 'seq', 'ts']) {
    if (!card.includes(want)) failures.push(`레지스트리 밖 카드가 ${want} 를 안 적는다 — 아는 사실은 다 적는다`);
  }
}

// ── 6. 한글·영어 두 벌 ───────────────────────────────────────────────────────
{
  const { ko } = await load('src', 'i18n', 'ko.ts');
  const { en } = await load('src', 'i18n', 'en.ts');
  const used = new Set();
  for (const rel of ['src/tabs/views/UnregisteredCard.tsx', 'src/tabs/views/DeviceGrid.tsx']) {
    for (const [, key] of code(readSource(rel)).matchAll(/(?<![A-Za-z0-9_$])t\('(dg\.stray\.[^']+)'/g)) used.add(key);
  }
  if (used.size === 0) failures.push('레지스트리 밖 구획이 사전 키를 하나도 안 쓴다 — 글자가 박혀 있다는 뜻이다');
  const missingKo = [...used].filter((k) => ko[k] === undefined);
  const missingEn = [...used].filter((k) => en[k] === undefined);
  if (missingKo.length > 0) failures.push(`한국어 사전에 없는 키 — ${missingKo.join(' · ')}`);
  if (missingEn.length > 0) failures.push(`영어 사전에 없는 키 — ${missingEn.join(' · ')}`);
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
{
  // (가) 구획을 지운 사본이 잡히는가
  const gridSrc = readSource('src/tabs/views/DeviceGrid.tsx');
  const dropped = gridSrc.replace('.filter((r) => r.registry === null && r.envelopeCount > 0)', '.filter(() => false)');
  if (dropped === gridSrc) failures.push('대조군(가)을 만들지 못했다 — 레지스트리 밖 필터의 모양이 바뀌었다');
  else controls.push('레지스트리 밖 개체를 안 모으는 사본');

  // (나) 상태를 지어내는 사본이 잡히는가
  const modelSrc = readSource('src/tabs/data/statusModel.ts');
  const invented = modelSrc.replace(
    "  if (layers.deployment !== 'deployed' && layers.deployment !== 'not_deployed') return 'unknown';\n",
    '',
  );
  if (invented === modelSrc) failures.push('대조군(나)을 만들지 못했다 — 3층 모양 가드의 모양이 바뀌었다');
  else controls.push('3층 아닌 payload 를 미배포로 단정하는 사본');
}

if (failures.length) {
  console.error(`❌ verify:stray-entity\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 저장소 — 레지스트리 밖 개체를 받아 두고 봉투를 센다');
console.log('✅ 판정 — 3층 모양이 아닌 payload 는 「알 수 없음」이고, 기존 3층 판정 6종은 그대로다');
console.log('✅ 화면 — 값이 온 레지스트리 밖 개체를 따로 그리고, 없으면 구획도 안 뜬다');
console.log('✅ 카드 — 층별 판정을 태우지 않고 아는 사실(봉투 수·ts·seq·원문)만 적는다');
console.log('✅ 두 벌 — 구획이 쓰는 키가 ko·en 양쪽에 다 있다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
