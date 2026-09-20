// verify:capability-source (260920 신설 — 기능 상태 패널 이식)
//
// **테스트 자료가 실제 클러스터 화면에 남으면 안 된다.**
//
// 이 판은 「지금 무엇이 가능한가」를 말한다. 실제 k3s 에 붙은 화면에 테스트 자료의 노드가
// 한 줄이라도 남아 있으면 그것은 **없는 인프라를 있다고 말하는 것**이고, 이 저장소에서
// 가장 하면 안 되는 종류의 거짓말이다. 탐지에서 같은 자리를 한 함수(`sourceOf`)로 막았고
// 여기도 같다 — 다만 여기는 **켤 때도 끌 때도** 버린다.
//
// 보는 것 여덟.
//  1. 경계 — 기능 상태 주소·경로를 아는 면이 `src/capability/` 하나인가
//  2. 자료 격리 — `sample.ts` 를 여는 파일이 클라이언트 하나인가
//  3. 갈림이 하나 — `sourceOf(testMode)` 말고 자료를 고르는 자리가 없는가
//  4. 분리 — 테스트를 켜고 끌 때 **양쪽 다** 값이 비는가 (실제로 흘려서 본다)
//  5. 주소가 바뀌면 버리는가 · 늦게 온 답이 안 실리는가
//  6. 창구 — 읽기 셋만 열리고 placement·whatif 는 막히는가, base 검증이 도는가
//  7. 배지 — 「설정 기반」이 조건 없이 그려지는가 (끌 수 없다)
//  8. 한글·영어 두 벌 — 화면이 쓰는 키가 양쪽 사전에 다 있는가
//
// 대조군 포함 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 본다.

import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readdirSync, statSync } from 'node:fs';
import { readSource } from './lib/source.mjs';
// 남의 대조군 잔여물을 내 판정에 넣지 않는다 (검사 위생 §3①).
import { isScratchPath } from './lib/scratch.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
/** 주석을 걷어 낸 소스 — 「왜 이렇게 뒀는지」 적어 둔 글이 규칙에 걸리면 안 된다. */
const code = (source) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

const failures = [];
const controls = [];

/** `src/` 아래 모든 소스 (상대 경로). */
function walk(dir, out = []) {
  for (const name of readdirSync(join(root, dir))) {
    const rel = `${dir}/${name}`;
    if (isScratchPath(rel)) continue;
    if (statSync(join(root, rel)).isDirectory()) walk(rel, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(rel);
  }
  return out;
}
const SOURCES = walk('src');
/**
 * 경계 밖. **사전은 뺀다** — 거기 있는 `GET /api/functions` 나 `127.0.0.1:8765` 는 화면에
 * 적히는 **글자**이지 주소를 만드는 코드가 아니다. 이 규칙이 막으려는 것은 두 번째 면이
 * 생기는 것이고, 사전은 면이 아니다.
 */
const outside = SOURCES.filter((rel) => !rel.startsWith('src/capability/') && !rel.startsWith('src/i18n/'));

// ── 1. 경계 — 기능 상태를 아는 면은 하나다 ───────────────────────────────────
{
  // 주소·창구 경로·엔드포인트를 경계 밖에서 적으면 두 벌이 된다.
  const MARKS = [/'\/capability(\/|')/, /\/api\/(functions|labels|config)/, /VITE_CAPABILITY_URL/, /127\.0\.0\.1:8765/];
  for (const rel of outside) {
    const src = code(readSource(rel));
    for (const mark of MARKS) {
      if (mark.test(src)) failures.push(`${rel} 가 기능 상태의 주소·경로를 직접 적는다 (${mark}) — 그 면은 src/capability/ 하나여야 한다`);
    }
  }
  // 연결 관리는 `capability.base` 키를 **함수로** 만들어야 한다 — 문자열을 손으로 적으면 안 된다.
  for (const rel of outside) {
    if (/['"]capability\.base['"]/.test(code(readSource(rel)))) {
      failures.push(`${rel} 가 'capability.base' 를 손으로 적는다 — connectionKey() 로 만든다`);
    }
  }
}

// ── 2. 테스트 자료 격리 ──────────────────────────────────────────────────────
{
  const importers = SOURCES.filter((rel) => /from '[^']*sample\.ts'/.test(code(readSource(rel))) && rel.startsWith('src/capability/'));
  const others = SOURCES.filter((rel) => /capability\/sample\.ts/.test(code(readSource(rel))));
  const allowed = 'src/capability/CapabilityClient.ts';
  const bad = [...new Set([...importers, ...others])].filter((rel) => rel !== allowed);
  if (bad.length > 0) failures.push(`테스트 자료를 여는 파일이 클라이언트 말고 또 있다 — ${bad.join(' · ')}`);
  if (!importers.includes(allowed)) failures.push('클라이언트가 테스트 자료를 안 읽는다 — 「테스트」를 켜도 아무것도 안 뜬다');
}

// ── 2b. 붙잡아 둔 응답에 이 PC 의 흔적이 없는가 ───────────────────────────────
{
  // `GET /api/config` 에는 그 서버를 띄운 PC 의 절대경로가 실려 온다(260920 실측).
  // 그래서 config 는 control 만 손으로 옮겼다. 다시 붙잡을 사람이 통째로 넣지 않도록 못을 박는다.
  for (const rel of ['capability-sample/functions.json', 'capability-sample/labels.json']) {
    const raw = readSource(rel);
    const hit = /[A-Za-z]:\\\\|[A-Za-z]:\/Users\/|\/home\/[a-z]|\/Users\/[a-z]/i.exec(raw);
    if (hit !== null) failures.push(`${rel} 에 이 PC 의 경로가 들어 있다 — 「${hit[0]}」 (저장소에 남길 값이 아니다)`);
    try {
      JSON.parse(raw);
    } catch (error) {
      failures.push(`${rel} 이 JSON 이 아니다 — ${error.message}`);
    }
  }
  // 붙잡은 응답이 **우리 파서를 통과하는가.** 통과 못 하면 「테스트」를 켜도 빈 화면이다.
  const { parseSnapshot, parseLabels } = await load('src', 'capability', 'parse.ts');
  const { SAMPLE_FUNCTIONS, SAMPLE_LABELS, SAMPLE_CONFIG } = await load('src', 'capability', 'sample.ts');
  const snap = parseSnapshot(SAMPLE_FUNCTIONS);
  if (snap === null || snap.functions.length === 0 || snap.nodes.length === 0) {
    failures.push('붙잡아 둔 응답이 파서를 못 지난다 — 「테스트」를 켜도 빈 화면이다');
  } else {
    // 서버가 객체로 주는 칸 둘 — 문자열로 읽으면 조용히 비는 자리라 값으로 못을 박는다.
    const rows = snap.nodes.flatMap((n) => n.rows);
    if (!rows.some((r) => r.nodeSelector !== null)) failures.push('node_selector 를 하나도 못 읽었다 — 서버는 객체로 준다');
    if (!rows.some((r) => r.alternatives.some((a) => a.reasonData !== null))) {
      failures.push('reason_data 를 하나도 못 읽었다 — 「어느 태그가 없는지」가 사라진다');
    }
  }
  if (Object.keys(parseLabels(SAMPLE_LABELS).functions).length === 0) failures.push('붙잡아 둔 라벨을 파서가 못 읽는다');
  if (JSON.stringify(SAMPLE_CONFIG).includes('config_path')) failures.push('붙잡은 config 를 통째로 넣었다 — 그 안에 PC 의 절대경로가 있다');
}

// ── 3. 갈림이 하나 ───────────────────────────────────────────────────────────
{
  const client = code(readSource('src/capability/CapabilityClient.ts'));
  if (!/export function sourceOf\(testMode: boolean\)/.test(client)) {
    failures.push('sourceOf(testMode) 가 없다 — 테스트와 실제의 갈림이 한 자리여야 한다');
  }
  // 경계 안에서도 `sourceOf` 말고 testMode 를 보고 자료를 고르는 자리가 있으면 안 된다.
  for (const rel of SOURCES.filter((r) => r.startsWith('src/capability/') && !r.endsWith('CapabilityClient.ts') && !r.endsWith('store.ts'))) {
    if (/SAMPLE_/.test(code(readSource(rel))) && !rel.endsWith('sample.ts')) {
      failures.push(`${rel} 가 테스트 상수를 직접 쓴다 — 갈림은 sourceOf 하나다`);
    }
  }
}

// ── 4·5. 분리 — 실제로 흘려서 본다 ───────────────────────────────────────────
{
  const store = await load('src', 'capability', 'store.ts');
  const { SAMPLE_FUNCTIONS } = await load('src', 'capability', 'sample.ts');
  const { saveConnections, resetConnections, connectionKey } = await load('src', 'shared', 'connections.ts');

  /** 실제 서비스인 척하는 응답기. 노드 이름을 바꿔 두어 테스트 자료와 구별된다. */
  const liveBody = { ...SAMPLE_FUNCTIONS, nodes: [{ node_id: 'live-node-1', role: 'edge', tags: [], budget: null, exclude_providers: [], rows: [] }] };
  const fetcher = (url) => Promise.resolve({
    ok: true,
    status: 200,
    headers: { get: (k) => (k === 'X-Capability-Relay' && url.startsWith('/capability/') ? '1' : null) },
    json: () => Promise.resolve(url.includes('/labels') ? {} : url.includes('/config') ? {} : liveBody),
    text: () => Promise.resolve(''),
  });

  store.resetCapability();
  resetConnections();
  saveConnections({ [connectionKey('capability', 'base')]: 'http://cluster.invalid:8765' });

  // (a) 테스트를 켜면 자료가 뜬다
  store.setCapabilityTestMode(true);
  await store.loadCapability(fetcher);
  const onSample = store.capabilityState();
  if (onSample.via !== 'sample') failures.push(`테스트를 켰는데 자료를 안 읽었다 — via=${onSample.via}`);
  if (onSample.snapshot === null || onSample.snapshot.nodes.length === 0) failures.push('테스트 자료가 비어 있다');
  if (onSample.snapshot?.nodes.some((n) => n.nodeId === 'live-node-1')) failures.push('테스트를 켰는데 실제 서비스를 두드렸다');

  // (b) **끄면 값이 통째로 빈다** — 다시 읽기 전까지 아무것도 없어야 한다
  store.setCapabilityTestMode(false);
  const offed = store.capabilityState();
  if (offed.snapshot !== null || offed.via !== null || offed.fetchedAtMs !== 0) {
    failures.push('테스트를 껐는데 자료가 남아 있다 — 실제 클러스터 화면에 없는 인프라가 뜬다');
  }
  if (Object.keys(offed.labels.functions).length !== 0) failures.push('테스트를 껐는데 자료의 라벨이 남아 있다');

  // (c) **켤 때도 비운다** — 실제 값이 테스트 화면에 남으면 그것도 거짓이다
  await store.loadCapability(fetcher);
  if (store.capabilityState().via !== 'relay') failures.push('실제 경로가 창구를 안 탄다');
  if (!store.capabilityState().snapshot?.nodes.some((n) => n.nodeId === 'live-node-1')) failures.push('실제 응답을 안 읽었다');
  store.setCapabilityTestMode(true);
  if (store.capabilityState().snapshot !== null) failures.push('테스트를 켰는데 실제 클러스터의 값이 남아 있다');
  store.setCapabilityTestMode(false);

  // (d) 주소가 바뀌면 버린다
  await store.loadCapability(fetcher);
  if (store.capabilityState().snapshot === null) failures.push('다시 읽었는데 값이 없다');
  store.clearCapabilityForAddressChange();
  if (store.capabilityState().snapshot !== null) failures.push('주소가 바뀌었는데 옛 클러스터의 값이 남는다');

  // (e) **늦게 온 답은 안 실린다** — 읽는 도중에 테스트를 켜면 그 답은 지금 화면의 것이 아니다
  // 세 경로(functions·labels·config)를 한꺼번에 부르므로 **붙잡은 것을 다 모아 두었다가**
  // 한 번에 놓는다. 하나만 들고 있으면 나머지 둘이 영영 안 끝나 검사가 멎는다.
  const held = [];
  const slow = (url) => new Promise((resolve) => {
    held.push(() => resolve({
      ok: true, status: 200,
      headers: { get: (k) => (k === 'X-Capability-Relay' && url.startsWith('/capability/') ? '1' : null) },
      json: () => Promise.resolve(url.includes('/labels') || url.includes('/config') ? {} : liveBody),
      text: () => Promise.resolve(''),
    }));
  });
  const pending = store.loadCapability(slow);
  store.setCapabilityTestMode(true);
  for (const release of held) release();
  await pending;
  if (store.capabilityState().snapshot?.nodes.some((n) => n.nodeId === 'live-node-1')) {
    failures.push('테스트를 켠 뒤에 도착한 실제 응답이 화면에 실렸다');
  }
  store.resetCapability();
  resetConnections();
}

// ── 6. 창구 ──────────────────────────────────────────────────────────────────
{
  const { relayTarget, CAPABILITY_ENDPOINTS } = await load('scripts', 'capability-relay.mjs');
  const base = 'http://127.0.0.1:8765';
  const ok = relayTarget(`/capability/functions?base=${encodeURIComponent(base)}`);
  if (ok?.upstream !== `${base}/api/functions`) failures.push(`창구가 functions 를 안 옮긴다 — ${JSON.stringify(ok)}`);
  for (const closed of ['placement', 'whatif', 'reset', 'events', '../api/config']) {
    const outcome = relayTarget(`/capability/${closed}?base=${encodeURIComponent(base)}`);
    if (outcome === null || !('error' in outcome)) failures.push(`창구가 ${closed} 를 연다 — 읽기 셋만 열어야 한다 (placement 는 클러스터를 바꾼다)`);
  }
  if (CAPABILITY_ENDPOINTS.includes('placement')) failures.push('창구의 열린 경로에 placement 가 들어 있다');
  for (const bad of ['', 'file:///etc', 'http://h:1/a/b', 'http://u:p@h:1', 'http://h:1/?x=1']) {
    const outcome = relayTarget(`/capability/functions?base=${encodeURIComponent(bad)}`);
    if (outcome === null || !('error' in outcome)) failures.push(`창구가 base 「${bad}」 를 받는다`);
  }
  if (relayTarget('/autodrive-ai/control/go1_front?base=http://x') !== null) failures.push('창구가 남의 경로를 가로챈다');
}

// ── 7. 배지를 끌 수 없다 ─────────────────────────────────────────────────────
{
  const panel = code(readSource('src/capability/views/CapabilityPanel.tsx'));
  const badge = /<em className="cap-chip cap-chip--warn" title=\{t\('cap\.badge\.configTitle'\)\}>\{t\('cap\.badge\.config'\)\}<\/em>/;
  if (!badge.test(panel)) failures.push('「설정 기반 · 실측 아님」 배지를 못 찾겠다 — 모양이 바뀌었으면 이 검사도 같이 고친다');
  // 배지 줄에 `&&` 나 삼항이 붙으면 끌 수 있게 된 것이다.
  const badgeLine = panel.split('\n').find((l) => l.includes("cap.badge.config'")) ?? '';
  if (/&&|\?/.test(badgeLine)) failures.push('「설정 기반」 배지에 조건이 붙었다 — 이 배지는 끌 수 없어야 한다');
  if (!panel.includes("cap.badge.sample")) failures.push('테스트 자료 배지가 없다 — 켜져 있는 동안 화면이 그 사실을 적어야 한다');
}

// ── 8. 한글·영어 두 벌 ───────────────────────────────────────────────────────
{
  const { ko } = await load('src', 'i18n', 'ko.ts');
  const { en } = await load('src', 'i18n', 'en.ts');
  const used = new Set();
  for (const rel of [...SOURCES.filter((r) => r.startsWith('src/capability/')), 'src/shared/connections.ts', 'src/shared/connectionCheck.ts']) {
    // **앞에 글자가 붙은 `t(` 는 다른 함수다** — `registerConnectionDefault('capability'` 나
    // `.get('X-Capability-Relay'` 가 사전 키로 잡히던 자리다.
    for (const [, key] of code(readSource(rel)).matchAll(/(?<![A-Za-z0-9_$])t\('([^']+)'/g)) used.add(key);
    for (const [, key] of code(readSource(rel)).matchAll(/(?:label|hint|what|pending|why|title)Key: '([^']+)'/g)) used.add(key);
  }
  const missingKo = [...used].filter((key) => ko[key] === undefined);
  const missingEn = [...used].filter((key) => en[key] === undefined);
  if (missingKo.length > 0) failures.push(`한국어 사전에 없는 키 — ${missingKo.join(' · ')}`);
  if (missingEn.length > 0) failures.push(`영어 사전에 없는 키 — ${missingEn.join(' · ')}`);
  // 표시용 한글이 경계 안 코드에 직접 박히면 영어 화면이 한국어로 샌다 (verify:i18n-scope-leak 과 같은 규칙).
  for (const rel of SOURCES.filter((r) => r.startsWith('src/capability/') && !r.endsWith('sample.ts'))) {
    const hits = [...code(readSource(rel)).matchAll(/'([^']*[가-힣][^']*)'/g)].map((m) => m[1]);
    if (hits.length > 0) failures.push(`${rel} 에 표시용 한글이 박혀 있다 — 「${hits[0]}」 (사전 키로 옮긴다)`);
  }
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
{
  // (가) 끌 때 값을 안 버리는 사본이 잡히는가
  const storeSrc = readSource('src/capability/store.ts');
  const broken = storeSrc.replace(
    'if (state.testMode === on) return;\n  commit({ testMode: on, ...EMPTY });',
    'if (state.testMode === on) return;\n  commit({ ...state, testMode: on });',
  );
  if (broken === storeSrc) failures.push('대조군(가)을 만들지 못했다 — setCapabilityTestMode 의 모양이 바뀌었다');
  else controls.push('끌 때 값을 안 버리는 사본');

  // (나) 창구가 placement 를 여는 사본이 잡히는가
  const relaySrc = readSource('scripts/capability-relay.mjs');
  const opened = relaySrc.replace(
    "export const CAPABILITY_ENDPOINTS = ['config', 'labels', 'functions'];",
    "export const CAPABILITY_ENDPOINTS = ['config', 'labels', 'functions', 'placement'];",
  );
  if (opened === relaySrc) failures.push('대조군(나)을 만들지 못했다 — 창구의 열린 경로 목록 모양이 바뀌었다');
  else controls.push('창구가 placement 를 여는 사본');

  // (다) 배지에 조건이 붙은 사본이 잡히는가
  const panelSrc = readSource('src/capability/views/CapabilityPanel.tsx');
  const hidden = panelSrc.replace(
    '<em className="cap-chip cap-chip--warn" title={t(\'cap.badge.configTitle\')}>',
    '{!sample && <em className="cap-chip cap-chip--warn" title={t(\'cap.badge.configTitle\')}>',
  );
  if (hidden === panelSrc) failures.push('대조군(다)을 만들지 못했다 — 배지의 모양이 바뀌었다');
  else controls.push('배지를 조건부로 바꾼 사본');
}

if (failures.length) {
  console.error(`❌ verify:capability-source\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 경계 — 기능 상태의 주소·창구 경로·엔드포인트를 아는 면은 src/capability/ 하나');
console.log('✅ 자료 격리 — sample.ts 를 여는 곳은 CapabilityClient 하나, 갈림은 sourceOf(testMode) 하나');
console.log('✅ 붙잡아 둔 응답 — 우리 파서를 지나고(node_selector·reason_data 포함) 이 PC 의 경로가 안 섞여 있다');
console.log('✅ 분리 — 켤 때도 끌 때도 값이 통째로 빔 · 주소가 바뀌면 버림 · 늦게 온 답은 안 실림');
console.log('✅ 창구 — config·labels·functions 만 열림(placement·whatif 차단) · base 는 경로·계정·쿼리 없는 http(s)');
console.log('✅ 표시 — 「설정 기반 · 실측 아님」은 끌 수 없고, 테스트 중에는 「테스트 자료」가 함께 뜸');
console.log('✅ 두 벌 — 화면이 쓰는 키가 ko·en 양쪽에 다 있고 경계 안에 박힌 표시용 한글 0건');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
