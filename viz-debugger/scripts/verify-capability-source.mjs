// verify:capability-source (260920 신설 — 기능 상태 패널 이식)
//
// **테스트 자료가 실제 클러스터 화면에 남으면 안 된다.**
//
// 이 판은 「지금 무엇이 가능한가」를 말한다. 실제 k3s 에 붙은 화면에 테스트 자료의 노드가
// 한 줄이라도 남아 있으면 그것은 **없는 인프라를 있다고 말하는 것**이고, 이 저장소에서
// 가장 하면 안 되는 종류의 거짓말이다. 탐지에서 같은 자리를 한 함수(`sourceOf`)로 막았고
// 여기도 같다 — 다만 여기는 **켤 때도 끌 때도** 버린다.
//
// 보는 것 아홉.
//  1. 경계 — 기능 상태 주소·경로를 아는 면이 `src/capability/` 하나인가
//  2. 자료 격리 — `sample.ts` 를 여는 파일이 클라이언트 하나인가
//  3. 갈림이 하나 — `sourceOf(testMode)` 말고 자료를 고르는 자리가 없는가
//  4. 분리 — 테스트를 켜고 끌 때 **양쪽 다** 값이 비는가 (실제로 흘려서 본다)
//  5. 주소가 바뀌면 버리는가 · 늦게 온 답이 안 실리는가
//  6. 창구 — 메서드까지 보고 여는가. `placement` 는 GET 으로도 POST 로도 막히는가
//  7. 배지 — 「설정 기반」과 「가상 조건」이 가릴 수 없게 그려지는가
//  8. 가상 조건 — 조건이 값과 **함께** 버려지는가, 테스트 자료로는 안 걸리는가
//  9. 한글·영어 두 벌 — 화면이 쓰는 키가 양쪽 사전에 다 있는가
//
// ## 260921 — 여섯째가 뒤집혔다
//
// 이식 때 이 검사는 「`whatif` 가 **막히는가**」를 물었다. 그 전제가 틀렸다 —
// `serve.py` 의 `whatif_functions()` 는 `functions()` 를 두 번 부르는 계산이고 배치를
// 바꾸지 않는다. 그래서 묻는 것을 바꿨다: **메서드까지 보고 여는가.** 가르는 기준은
// 「POST 인가」가 아니라 「무엇을 바꾸는가」이고, `placement` 는 그대로 닫힌다.
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

// ── 6. 창구 — 메서드까지 보고 연다 ───────────────────────────────────────────
{
  const { relayTarget, CAPABILITY_ENDPOINTS, CAPABILITY_POST_ENDPOINTS } = await load('scripts', 'capability-relay.mjs');
  const base = 'http://127.0.0.1:8765';
  const q = `?base=${encodeURIComponent(base)}`;

  // 읽기 셋은 GET 으로 열린다.
  for (const endpoint of ['config', 'labels', 'functions']) {
    const ok = relayTarget(`/capability/${endpoint}${q}`, 'GET');
    if (ok?.upstream !== `${base}/api/${endpoint}`) failures.push(`창구가 ${endpoint} 를 안 옮긴다 — ${JSON.stringify(ok)}`);
  }
  // 계산 하나는 POST 로 열린다.
  const whatif = relayTarget(`/capability/functions/whatif${q}`, 'POST');
  if (whatif?.upstream !== `${base}/api/functions/whatif`) {
    failures.push(`창구가 functions/whatif 를 POST 로 안 옮긴다 — ${JSON.stringify(whatif)}`);
  }

  // **메서드가 어긋나면 막힌다.** 한쪽 목록만 보면 GET whatif 나 POST functions 가 샌다.
  const crossed = [
    ['functions/whatif', 'GET'],
    ['functions', 'POST'],
    ['config', 'POST'],
    ['labels', 'POST'],
  ];
  for (const [endpoint, verb] of crossed) {
    const outcome = relayTarget(`/capability/${endpoint}${q}`, verb);
    if (outcome === null || !('error' in outcome)) failures.push(`창구가 ${verb} ${endpoint} 를 연다 — 경로마다 메서드가 하나여야 한다`);
  }

  // **바꾸는 길은 어느 메서드로도 안 열린다.** placement 는 클러스터 Deployment 를 바꾼다.
  for (const closed of ['placement', 'whatif', 'reset', 'events', '../api/config', 'functions/placement']) {
    for (const verb of ['GET', 'POST']) {
      const outcome = relayTarget(`/capability/${closed}${q}`, verb);
      if (outcome === null || !('error' in outcome)) failures.push(`창구가 ${verb} ${closed} 를 연다 — placement 는 클러스터를 바꾼다`);
    }
  }
  for (const [name, list] of [['읽기', CAPABILITY_ENDPOINTS], ['POST', CAPABILITY_POST_ENDPOINTS]]) {
    if (list.some((entry) => entry.includes('placement'))) failures.push(`창구의 ${name} 목록에 placement 가 들어 있다`);
  }

  for (const bad of ['', 'file:///etc', 'http://h:1/a/b', 'http://u:p@h:1', 'http://h:1/?x=1']) {
    const outcome = relayTarget(`/capability/functions?base=${encodeURIComponent(bad)}`, 'GET');
    if (outcome === null || !('error' in outcome)) failures.push(`창구가 base 「${bad}」 를 받는다`);
    const posted = relayTarget(`/capability/functions/whatif?base=${encodeURIComponent(bad)}`, 'POST');
    if (posted === null || !('error' in posted)) failures.push(`창구가 POST 에서 base 「${bad}」 를 받는다`);
  }
  if (relayTarget('/autodrive-ai/control/go1_front?base=http://x', 'GET') !== null) failures.push('창구가 남의 경로를 가로챈다');

  // **두 설정이 갈라지지 않는가** (260920). 단독본은 마일스톤 화면으로 열리므로 기능 판이
  // 전달본에서 제일 먼저 보인다 — 한쪽에만 창구가 있으면 그 판만 거기서 영영 실패한다.
  for (const config of ['vite.config.ts', 'vite.standalone.config.ts']) {
    const src = code(readSource(config));
    if (!/capabilityRelay\(\)/.test(src)) failures.push(`${config} 가 기능 상태 창구를 안 붙인다 — 그 빌드에서만 판이 실패한다`);
  }
  // 창구는 **미들웨어**다. 번들에 들어가면 측정축 D 가 오염되므로 진입점이 끌어가면 안 된다.
  for (const rel of SOURCES) {
    if (/capability-relay\.mjs/.test(code(readSource(rel)))) failures.push(`${rel} 이 창구 스크립트를 import 한다 — 창구는 서버 미들웨어이지 번들 코드가 아니다`);
  }
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

  // **「가상 조건」도 가릴 수 없다** (260921). 이 판의 값은 이미 한 단계 약한 주장(계산)인데
  // 거기에 「그것도 가정」이 겹친다. 문은 하나여야 한다 — 조건이 `cap.whatif !== null` 뿐인가.
  const whatifBadge = /\{cap\.whatif !== null && <em className="cap-chip cap-chip--whatif" title=\{t\('cap\.badge\.whatifTitle'\)\}>\{t\('cap\.badge\.whatif'\)\}<\/em>\}/;
  if (!whatifBadge.test(panel)) {
    failures.push('「가상 조건」 배지가 없거나 그 조건이 `cap.whatif !== null` 하나가 아니다 — 가상값이 현재값으로 읽힌다');
  }
  const drill = code(readSource('src/capability/views/CapabilityDrill.tsx'));
  if (!drill.includes('cap.badge.whatif')) failures.push('드릴다운 머리에 「가상 조건」 표시가 없다 — 거기서도 값이 가상이다');
}

// ── 8. 가상 조건 — 값과 함께 버려진다 ───────────────────────────────────────
{
  const store = await load('src', 'capability', 'store.ts');
  const { SAMPLE_FUNCTIONS } = await load('src', 'capability', 'sample.ts');
  const { saveConnections, resetConnections, connectionKey } = await load('src', 'shared', 'connections.ts');

  const liveBody = {
    ...SAMPLE_FUNCTIONS,
    nodes: [{ node_id: 'live-node-1', role: 'edge', tags: ['compute.gpu'], budget: { compute_units: 8 }, exclude_providers: [], rows: [] }],
  };
  /** 조건이 걸린 판 — 기능 하나가 뒤집힌다. 실제 서버의 답 모양 그대로다. */
  const whatifBody = {
    before: liveBody,
    after: { ...liveBody, overrides: { 'live-node-1': { exclude_providers: ['unidepth'] } } },
    diff: [{ function_id: 'go_to_door', before_state: 'ACTIVE', after_state: 'DISABLED', changed: true }],
  };
  const fetcher = (url) => Promise.resolve({
    ok: true,
    status: 200,
    headers: { get: (k) => (k === 'X-Capability-Relay' && url.startsWith('/capability/') ? '1' : null) },
    json: () => Promise.resolve(
      url.includes('/whatif') ? whatifBody
        : url.includes('/labels') || url.includes('/config') ? {} : liveBody,
    ),
    text: () => Promise.resolve(''),
  });

  store.resetCapability();
  resetConnections();
  saveConnections({ [connectionKey('capability', 'base')]: 'http://cluster.invalid:8765' });

  // (a) 조건을 걸면 화면이 **가상값**을 그린다
  await store.loadCapability(fetcher);
  await store.setCapabilityOverride('live-node-1', { excludeProviders: ['unidepth'] }, fetcher);
  const on = store.capabilityState();
  if (on.whatif === null) failures.push('조건을 걸었는데 가상값이 없다');
  if (store.shownSnapshot(on) === on.snapshot) failures.push('조건이 걸렸는데 화면이 기준선을 그린다');
  if (store.baselineSnapshot(on) !== on.snapshot) failures.push('기준선이 가상값으로 덮였다 — 비교 대상이 자기 자신이 된다');

  // (b) **테스트를 토글하면 조건까지 빈다** — 다른 클러스터의 node_id 를 들고 있으면 안 된다
  store.setCapabilityTestMode(true);
  const toggled = store.capabilityState();
  if (Object.keys(toggled.overrides).length !== 0 || toggled.whatif !== null) {
    failures.push('테스트를 켰는데 옛 클러스터의 조건이 남아 있다 — 그 node_id 는 여기 없다');
  }

  // (c) 주소가 바뀌어도 버린다
  store.setCapabilityTestMode(false);
  await store.loadCapability(fetcher);
  await store.setCapabilityOverride('live-node-1', { excludeProviders: ['unidepth'] }, fetcher);
  store.clearCapabilityForAddressChange();
  if (store.capabilityState().whatif !== null || Object.keys(store.capabilityState().overrides).length !== 0) {
    failures.push('주소가 바뀌었는데 옛 조건의 가상값이 남는다');
  }

  // (d) 다시 읽으면 조건이 지워진다 — 새 기준선에서는 다시 계산해야 한다
  await store.loadCapability(fetcher);
  await store.setCapabilityOverride('live-node-1', { excludeProviders: ['unidepth'] }, fetcher);
  await store.loadCapability(fetcher);
  if (store.capabilityState().whatif !== null) failures.push('새로 읽었는데 옛 조건의 가상값이 남는다');

  // (e) 조건을 걷으면 기준선으로 돌아온다
  await store.setCapabilityOverride('live-node-1', { excludeProviders: ['unidepth'] }, fetcher);
  await store.clearCapabilityOverrides();
  const cleared = store.capabilityState();
  if (cleared.whatif !== null) failures.push('조건을 걷었는데 가상값이 남는다');
  if (store.shownSnapshot(cleared) !== cleared.snapshot) failures.push('조건을 걷었는데 화면이 기준선으로 안 돌아온다');

  // (g) **연달아 만지면 한 번만 나간다.** 체크 하나가 왕복 하나면 서버가 fleet 전체를
  // 매번 두 번(before·after) 계산하고, 그중 마지막 하나 빼고는 도착하자마자 버려진다.
  store.setCapabilityTestMode(false);
  await store.loadCapability(fetcher);
  let posts = 0;
  const counting = (url, init) => { if (url.includes('/whatif')) posts += 1; return fetcher(url, init); };
  await Promise.all([
    store.setCapabilityOverride('live-node-1', { excludeProviders: ['a'] }, counting),
    store.setCapabilityOverride('live-node-1', { excludeProviders: ['a', 'b'] }, counting),
    store.setCapabilityOverride('live-node-1', { excludeProviders: ['a', 'b', 'c'] }, counting),
  ]);
  if (posts !== 1) failures.push(`조작 3회에 whatif 가 ${posts}회 나갔다 — 묶어서 한 번이어야 한다`);
  if (store.capabilityState().whatif === null) failures.push('묶어서 보낸 뒤에 가상값이 없다');
  // 묶는 동안 예약이 남아 있으면 안 된다 — 걷는 자리가 그것을 못 걷으면 뒤늦게 나간다.
  await store.clearCapabilityOverrides();
  const after = posts;
  await store.loadCapability(fetcher);
  if (posts !== after) failures.push('조건을 걷었는데 미뤄 둔 whatif 가 뒤늦게 나갔다');

  // (f) **테스트 자료로는 못 건다** — 붙잡아 둔 한 장면이라 다시 계산해 줄 서버가 없다
  store.setCapabilityTestMode(true);
  await store.loadCapability(fetcher);
  await store.setCapabilityOverride('go1-onboard', { excludeProviders: ['unidepth'] }, fetcher);
  const onSample = store.capabilityState();
  if (onSample.whatif !== null) failures.push('테스트 자료인데 가상값이 생겼다 — 다시 계산한 척한 것이다');
  if (onSample.whatifError === null) failures.push('테스트 자료로 조건을 걸었는데 사유가 없다 — 조용히 안 되면 먹힌 줄 안다');

  store.resetCapability();
  resetConnections();
}

// ── 8b. 조건 목록은 기준선에서 뽑는다 ───────────────────────────────────────
{
  const { parseSnapshot } = await load('src', 'capability', 'parse.ts');
  const { SAMPLE_FUNCTIONS } = await load('src', 'capability', 'sample.ts');
  const options = await load('src', 'capability', 'options.ts');
  const snap = parseSnapshot(SAMPLE_FUNCTIONS);

  if (Object.keys(snap.served).length === 0) {
    failures.push('served 를 못 읽었다 — 계층마다 「이 계층이 제공하는 것」을 적을 수가 없다');
  }
  const roles = options.rolesOf(snap);
  if (roles.length < 2) failures.push(`계층이 ${roles.length}개다 — 노드의 role 을 못 읽고 있다`);
  for (const role of roles) {
    if (options.nodesOfRole(snap, role).length === 0) failures.push(`계층 ${role} 에 노드가 없다`);
  }
  // 제외할 수 있는 provider 에 **실제로 뽑힌 것**이 들어 있는가. 여기가 비면 조작면이 빈칸이다.
  const providers = options.providerUniverse(snap);
  if (!providers.includes('unidepth')) {
    failures.push(`provider 목록에 unidepth 가 없다 — 전달본의 확인 순서 3번을 할 수가 없다 (${providers.length}건)`);
  }
  const tags = options.tagUniverse(snap);
  if (!tags.includes('compute.gpu')) failures.push(`태그 목록이 비었거나 얕다 — ${tags.length}건`);

  // **설정값으로 돌아오면 조건이 지워지는가.** 안 지워지면 바뀐 것이 없는데 가상값이 뜬다.
  const node = snap.nodes[0];
  const patched = options.withOverride({}, node.nodeId, options.tagsPatch(node, [...node.tags]));
  if (options.hasOverrides(patched)) failures.push('설정과 같은 태그를 넣었는데 조건이 걸린 것으로 센다');
  const real = options.withOverride({}, node.nodeId, options.tagsPatch(node, [...node.tags, 'made.up.tag']));
  if (!options.hasOverrides(real)) failures.push('태그를 늘렸는데 조건으로 안 센다');
  if (options.isNodeBaseline(real, node)) failures.push('조건이 걸린 노드를 기준선이라고 한다');

  // **서버가 펼친 `'*'` 를 되접는가** (260921 실측 — 전체에 하나를 걸면 답신에 노드 수만큼 온다).
  // 안 되접으면 조건 한 건이 화면에서 여섯 건이 되고, 그것은 사용자가 한 일과 다르다.
  const ids = snap.nodes.map((entry) => entry.nodeId);
  const one = { tags: null, budget: null, excludeProviders: ['unidepth'] };
  const spread = Object.fromEntries(ids.map((id) => [id, one]));
  const folded = options.collapseOverrides(spread, ids);
  if (Object.keys(folded).length !== 1 || folded['*'] === undefined) {
    failures.push(`전체에 건 조건을 안 되접는다 — 한 건이 ${Object.keys(folded).length}건으로 보인다`);
  }
  // **다르면 되접지 않는다.** 되접으면 이번엔 다른 것을 같다고 말하게 된다.
  const mixed = { ...spread, [ids[0]]: { tags: null, budget: null, excludeProviders: ['unidepth', 'fastsam'] } };
  if (Object.keys(options.collapseOverrides(mixed, ids)).length !== ids.length) {
    failures.push('노드마다 다른 조건을 전체 하나로 되접었다');
  }
  // 한 노드에만 건 것도 그대로 둔다.
  const single = { [ids[0]]: one };
  if (Object.keys(options.collapseOverrides(single, ids)).length !== 1 || options.collapseOverrides(single, ids)['*'] !== undefined) {
    failures.push('노드 하나에 건 조건이 전체로 둔갑했다');
  }
}

// ── 9. 한글·영어 두 벌 ───────────────────────────────────────────────────────
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
    '  commit({ testMode: on, ...EMPTY });',
    '  commit({ ...state, testMode: on });',
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

  // (라) **창구가 placement 를 POST 로 여는 사본** (260921). 메서드 목록이 둘로 갈린 뒤로
  // 이쪽이 새 구멍이다 — 「계산만 한다」를 확인 안 하고 한 줄 더 적는 것.
  const openedPost = relaySrc.replace(
    "export const CAPABILITY_POST_ENDPOINTS = ['functions/whatif'];",
    "export const CAPABILITY_POST_ENDPOINTS = ['functions/whatif', 'placement'];",
  );
  if (openedPost === relaySrc) failures.push('대조군(라)을 만들지 못했다 — 창구의 POST 목록 모양이 바뀌었다');
  else controls.push('창구가 placement 를 POST 로 여는 사본');

  // (마) 「가상 조건」 배지에 조건이 하나 더 붙은 사본이 잡히는가
  const hiddenWhatif = panelSrc.replace(
    '{cap.whatif !== null && <em className="cap-chip cap-chip--whatif"',
    '{cap.whatif !== null && !sample && <em className="cap-chip cap-chip--whatif"',
  );
  if (hiddenWhatif === panelSrc) failures.push('대조군(마)을 만들지 못했다 — 「가상 조건」 배지의 모양이 바뀌었다');
  else controls.push('「가상 조건」 배지를 가릴 수 있게 바꾼 사본');

  // (바) **조건을 안 버리는 저장소 사본.** 이것이 남으면 옛 클러스터의 가정이 새 화면에 얹힌다.
  const storeSrc2 = readSource('src/capability/store.ts');
  const keepsOverrides = storeSrc2.replace(
    '  overrides: {},\n  whatif: null,\n  whatifLoading: false,\n  whatifError: null,\n};',
    '};',
  );
  if (keepsOverrides === storeSrc2) failures.push('대조군(바)을 만들지 못했다 — EMPTY 의 모양이 바뀌었다');
  else controls.push('조건을 안 버리는 저장소 사본');
}

if (failures.length) {
  console.error(`❌ verify:capability-source\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 경계 — 기능 상태의 주소·창구 경로·엔드포인트를 아는 면은 src/capability/ 하나');
console.log('✅ 자료 격리 — sample.ts 를 여는 곳은 CapabilityClient 하나, 갈림은 sourceOf(testMode) 하나');
console.log('✅ 붙잡아 둔 응답 — 우리 파서를 지나고(node_selector·reason_data 포함) 이 PC 의 경로가 안 섞여 있다');
console.log('✅ 분리 — 켤 때도 끌 때도 값이 통째로 빔 · 주소가 바뀌면 버림 · 늦게 온 답은 안 실림');
console.log('✅ 창구 — GET 읽기 셋 · POST functions/whatif 뿐 · placement 는 두 메서드 다 차단 · base 검증');
console.log('✅ 두 빌드가 같다 — 통합·단독 설정이 같은 창구를 붙이고, 창구는 번들에 안 들어간다(측정축 D 보존)');
console.log('✅ 표시 — 「설정 기반 · 실측 아님」과 「가상 조건」은 끌 수 없고, 테스트 중에는 「테스트 자료」가 함께 뜸');
console.log('✅ 가상 조건 — 값과 함께 버려짐(토글·주소·재조회) · 걷으면 기준선 · 연달아 만져도 왕복 한 번 · 테스트 자료로는 안 걸리고 사유가 뜸');
console.log('✅ 조건 목록 — served·role·provider·태그를 기준선 응답에서 뽑고, 설정값으로 돌아오면 조건이 지워짐');
console.log('✅ 두 벌 — 화면이 쓰는 키가 ko·en 양쪽에 다 있고 경계 안에 박힌 표시용 한글 0건');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
