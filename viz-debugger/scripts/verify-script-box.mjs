// verify:script-box (261027 신설 — 「박스 앞까지 이동해」)
//
// 10편째 `MSN-261027-01` 은 문 찾기 편(`MSN-260909-01`)의 **대상만 박스로 바꾼 복사본**이다. 다른 점은 셋뿐이다.
//
//   1. 문 → 박스        마일스톤·태스크·평가 문장의 「문」이 「박스」다. 탐지 서비스에 `target=box` 로 묻는다
//   2. T-A1 이 없다     2D 맵을 안 쓴다. 준비 단계는 도면을 안 받고 방위(T-A2) 하나로 한 바퀴를 연다
//   3. T-B1 이 다르다   「이동 경로 산출」 — 객체 탐지 결과만으로 낸 경로만 받는다. 도면 경로(`path_mode: 'map'`)는 실패로 친다
//
// 막으려는 실패 넷.
//
//  1. **틀이 문 편과 갈라지는 것.** T-A1 을 빼고 나머지 노드·의존·액션 아이템이 문 편과 같아야 한다 — 「실제 연결은 문 탐지와 동일」
//  2. **도면을 기다리다 안 도는 것.** T-A1 이 없는데 준비 단계가 도면을 기다리면 방위가 와도 한 바퀴가 영영 안 나간다
//  3. **문을 묻는 것.** 대상이 박스인데 탐지에 `target=door` 로 물으면 문을 찾아 문 앞으로 간다
//  4. **도면 경로로 움직이는 것.** 탐지가 도면 위 자리에서 낸 경로를 받으면 「도면 없이 갔다」는 기록이 거짓이 된다
//
// 대조군 포함.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readFileSync(join(root, ...p), 'utf8');
const sample = (...p) => JSON.parse(readFileSync(join(root, '..', 'door_example', 'test', ...p), 'utf8'));

const BOX_ID = 'MSN-261027-01';
const DOOR_ID = 'MSN-260909-01';
const box = JSON.parse(read('scenarios', `${BOX_ID}.json`));
const door = JSON.parse(read('scenarios', `${DOOR_ID}.json`));

const failures = [];
const controls = [];
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}

// ── 1. 틀 — T-A1 만 빠지고 나머지는 문 편 그대로 ─────────────────────────────
function shapeFailures(script) {
  const f = [];
  if (script.utterance?.text !== '박스 앞까지 이동해') f.push(`기준 문장이 「${script.utterance?.text}」 — 「박스 앞까지 이동해」여야 한다`);
  if (script.robotFlow !== 'door-scan') f.push('문 찾기 흐름(robotFlow: door-scan)을 선언하지 않았다 — 실제 연결이 문 편과 달라진다');
  if (script.detectTarget !== 'box') f.push(`탐지 대상이 ${script.detectTarget} — box 여야 한다`);
  const ms = script.milestones.map((m) => `${m.id}:${m.title}`).join(' · ');
  if (ms !== 'MS-A:박스를 찾는다 · MS-B:박스에 접근한다 · MS-C:임무 완료') f.push(`마일스톤이 [${ms}] — 문 편에서 문 → 박스만 바뀌어야 한다`);
  const ids = script.tasks.map((t) => t.id);
  if (ids.includes('T-A1')) f.push('T-A1(2D 맵에서 위치 확인)이 남아 있다');
  if (ids[0] !== 'T-A2' || script.tasks[0].deps.length !== 0) f.push(`첫 태스크가 ${ids[0]}(deps ${JSON.stringify(script.tasks[0].deps)}) — 의존 없는 T-A2 여야 한다`);
  const want = door.tasks.filter((t) => t.id !== 'T-A1').map((t) => t.id);
  if (ids.join(',') !== want.join(',')) f.push(`태스크가 [${ids.join(', ')}] — 문 편에서 T-A1 만 뺀 [${want.join(', ')}] 여야 한다`);
  for (const t of script.tasks) {
    const d = door.tasks.find((x) => x.id === t.id);
    if (d === undefined) continue;
    const deps = t.id === 'T-A2' ? [] : d.deps;
    if (JSON.stringify(t.deps) !== JSON.stringify(deps)) f.push(`${t.id} 의존이 ${JSON.stringify(t.deps)} — 문 편은 ${JSON.stringify(deps)}`);
    if (t.nodeKind !== d.nodeKind || t.target !== d.target || t.milestone !== d.milestone) f.push(`${t.id} 의 종류·장비·마일스톤이 문 편과 다르다`);
    const cmds = (items) => JSON.stringify(items.map((a) => [a.label, a.command?.action, a.command?.parameters]));
    if (cmds(t.actionItems) !== cmds(d.actionItems)) f.push(`${t.id} 의 액션 아이템(명령)이 문 편과 다르다 — 실제 연결이 갈라진다`);
  }
  const b1 = script.tasks.find((t) => t.id === 'T-B1');
  if (b1?.title !== '이동 경로 산출') f.push(`T-B1 이 「${b1?.title}」 — 「이동 경로 산출」이어야 한다`);
  if (!(b1?.evaluation?.criteria ?? []).some((c) => /객체 탐지 결과만/.test(c))) f.push('T-B1 평가 기준에 「객체 탐지 결과만」이 없다');
  // 대본 글자에 문이 남으면 화면이 박스 편에서 문을 말한다. 페이로드 키(`door`)는 수신 형식이라 글자가 아니다.
  const words = JSON.stringify({ t: script.title, m: script.milestones, k: script.tasks, e: script.events.map((e) => e.payload ?? {}), v: script.viewpointTimeline.map((v) => v.payload.reason ?? '') });
  for (const stale of ['2D 맵', '문 위치', '문이 있는', '문과', '문까지', '문틀']) if (words.includes(stale)) f.push(`대본에 「${stale}」이 남아 있다`);
  if (script.events.some((e) => e.nodeId === 'T-A1')) f.push('T-A1 사건이 남아 있다 — 없는 노드를 칠한다');
  const seqs = script.events.map((e) => e.seq);
  if (seqs.some((s, i) => s !== i + 1)) f.push('사건 seq 가 1부터 빈틈없이 이어지지 않는다');
  return f;
}
failures.push(...shapeFailures(box));
{
  const withMap = structuredClone(box);
  withMap.tasks.unshift(structuredClone(door.tasks[0]));
  control('T-A1 을 남긴 사본', shapeFailures(withMap).length > 0);
  const oldB1 = structuredClone(box);
  oldB1.tasks.find((t) => t.id === 'T-B1').title = '2D 맵 기반 경로 산출';
  control('T-B1 을 2D 맵 기반으로 둔 사본', shapeFailures(oldB1).length > 0);
}

// ── 2. 라이브러리 — 도면을 쓰는가 · 무엇을 찾는가 ──────────────────────────────
const library = await load('src', 'scenarios', 'library.ts');
if (library.usesFloorPlan(BOX_ID)) failures.push('박스 편이 2D 맵을 쓴다고 한다');
if (!library.usesFloorPlan(DOOR_ID)) failures.push('문 편이 2D 맵을 안 쓴다고 한다 — 문 편 준비 단계가 도면을 건너뛴다');
if (!library.usesFloorPlan('MSN-260831-01')) failures.push('문 찾기 흐름이 아닌 편에서 usesFloorPlan 이 거짓이다 — 2D 맵 노드가 사라진다');
if (library.detectTargetOf(BOX_ID) !== 'box' || library.detectTargetOf(DOOR_ID) !== 'door') failures.push('탐지 대상이 편마다 갈리지 않는다');
if (!library.doorScanFlow(BOX_ID)) failures.push('박스 편이 문 찾기 흐름을 안 탄다 — 관문·스캔·탐지 조회가 안 돈다');

// ── 3. 준비 단계 — 도면 없이 방위 하나로 연다 ─────────────────────────────────
const session = await load('src', 'physical', 'robotSession.ts');
const { shouldIssueScan } = await load('src', 'physical', 'robotCommands.ts');
const scenario = await load('src', 'data', 'scenario.ts');
const prep = await load('src', 'physical', 'prepStage.ts');
const devices = await load('src', 'physical', 'deviceState.ts');
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const robotState = (heading) => devices.receiveDeviceMessage('zoneA/robot/go1-001/state', {
  timestamp: '2026-10-27T10:00:00+0900', position: { x: 0.1, y: 0.2, heading_deg: heading },
});
{
  const realFetch = globalThis.fetch;
  const asked = [];
  globalThis.fetch = async (url) => { asked.push(String(url)); return new Response('jpeg', { status: 200 }); };
  try {
    prep.initPrepStage();
    scenario.previewMission(BOX_ID);
    devices.resetDevices(); prep.resetPrepStage(); session.resetRobotSession();
    session.setConnection({ state: 'open' });
    session.markApproved();
    session.markStarted();
    await flush(); await flush();
    if (prep.prepState().runKey === null) failures.push('박스 편에서 「임무 시작」이 준비 단계를 안 켰다');
    if (prep.prepState().map.step !== 'idle') failures.push(`박스 편 준비 단계가 도면을 ${prep.prepState().map.step} 로 둔다 — 안 쓰는 도면을 받는다`);
    if (asked.some((u) => /map/.test(u))) failures.push(`박스 편이 도면을 받으러 갔다 — ${asked.join(' · ')}`);
    const ran = scenario.traceEvents().filter((e) => e.producedBy === 'backend').map((e) => e.nodeId);
    if (!ran.includes('T-A2')) failures.push('준비 단계가 T-A2 를 진행 중으로 안 칠했다 — 아래 T-A1 검사가 헛돈다');
    if (ran.includes('T-A1')) failures.push('박스 편에서 T-A1 사건이 났다 — 없는 노드를 칠한다');
    session.finishPrep();
    if (shouldIssueScan()) failures.push('방위를 아직 안 받았는데 스캔이 나간다');
    robotState(15);
    if (prep.prepState().pose.step !== 'done') failures.push('방위가 왔는데 T-A2 가 안 끝난다');
    if (!shouldIssueScan()) failures.push('방위가 왔는데 한 바퀴가 안 나간다 — 없는 도면(T-A1)을 기다린다');

    // 문 편은 그대로 도면을 기다린다 — 박스 편의 생략이 문 편으로 새지 않는다.
    scenario.previewMission(DOOR_ID);
    devices.resetDevices(); prep.resetPrepStage(); session.resetRobotSession();
    globalThis.fetch = async () => new Response('nope', { status: 404 });
    session.setConnection({ state: 'open' });
    session.markApproved();
    session.markStarted();
    await flush(); await flush();
    session.finishPrep();
    robotState(15);
    const doorOpened = shouldIssueScan();
    if (doorOpened) failures.push('문 편이 도면 없이 한 바퀴를 연다 — 박스 편의 생략이 문 편으로 샜다');
  } finally {
    globalThis.fetch = realFetch;
    prep.resetPrepStage(); session.resetRobotSession(); devices.resetDevices();
  }
}

// ── 4. 탐지 — box 로 묻고, 도면 경로는 안 받는다 ──────────────────────────────
{
  const { registerConnectionDefault } = await load('src', 'shared', 'connections.ts');
  await load('src', 'detect', 'DetectClient.ts');
  registerConnectionDefault('detect', 'base', 'http://detect.test');
  const { pollOnce, resetDetectGate } = await load('src', 'detect', 'poll.ts');
  const { detectState, resetDetect, setTestMode } = await load('src', 'detect', 'store.ts');
  const { planApproach } = await load('src', 'physical', 'approachPlan.ts');
  setTestMode(false);

  const frames = sample('door', 'target_summary.json').frames;
  const evidence = sample('door', 'frame_000113', 'evidence.json');
  const basePath = sample('door', 'evidence.json');
  const served = { frames: [], path: null };
  const asked = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const u = String(url);
    asked.push(u);
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
    if (u.includes('/detect/results')) return json({ target_class: 'box', frames: served.frames });
    if (u.includes('/detect/path')) return served.path ? json(served.path) : json({ error: 'not_available' }, 404);
    if (u.includes('/detect/evidence')) return json(evidence);
    if (u.includes('/detect/features')) return json({ box: { features_compared: [] } });
    return json({ error: 'not_found' }, 404);
  };
  // 한 판을 흘린다 — 빈 서비스 → 여덟 각도 → 경로.
  const run = async (path) => {
    resetDetect(); resetDetectGate(); asked.length = 0;
    Object.assign(served, { frames: [], path: null });
    await pollOnce(8);
    Object.assign(served, { frames, path });
    await pollOnce(8);
    await pollOnce(8);
    return detectState();
  };
  try {
    scenario.previewMission(BOX_ID);
    const relative = await run({ ...basePath, target_class: 'box', path_mode: 'door_relative' });
    const targets = new Set(asked.filter((u) => u.includes('target=')).map((u) => /target=(\w+)/.exec(u)[1]));
    if (targets.size !== 1 || !targets.has('box')) failures.push(`박스 편이 탐지에 target=[${[...targets].join(', ')}] 로 물었다 — box 하나여야 한다`);
    if (relative.path === null) failures.push(`탐지 결과만으로 낸 경로(door_relative)를 안 받았다 — ${relative.pathFailure}`);
    if (relative.path !== null && !planApproach().ok) failures.push(`탐지 결과 경로를 받았는데 이동 계획이 안 선다 — ${planApproach().reason}`);

    const mapped = await run({ ...basePath, target_class: 'box', path_mode: 'map' });
    if (mapped.path !== null) failures.push('박스 편이 도면 경로(path_mode: map)를 받았다 — 도면 없이 간다는 노드가 도면으로 간다');
    if (mapped.pathFailure === null) failures.push('도면 경로를 거르고도 실패로 안 남겼다 — T-B1 이 진행 중인 채 멈춘다');
    if (planApproach().ok) failures.push('도면 경로를 거부했는데 이동 계획이 선다 — 로봇이 움직인다');

    // 문 편은 같은 도면 경로를 그대로 받는다 — 거름이 문 편으로 새지 않는다.
    scenario.previewMission(DOOR_ID);
    const doorMapped = await run({ ...basePath, path_mode: 'map' });
    if (doorMapped.path === null) failures.push('문 편이 도면 경로를 못 받는다 — 박스 편의 거름이 문 편으로 샜다');
    if (!asked.some((u) => u.includes('target=door'))) failures.push('문 편이 target=door 로 안 묻는다');
  } finally {
    globalThis.fetch = realFetch;
    resetDetect(); resetDetectGate();
  }
}

// ── 5. 팔레트 — 2D 맵 노드는 도면을 쓰는 편에만 ───────────────────────────────
{
  const nodes = read('src', 'tabs', 'viewNodes.tsx');
  const entry = nodes.slice(nodes.indexOf("kind: 'detect-map'"), nodes.indexOf('zoom:', nodes.indexOf("kind: 'detect-map'")));
  if (!/showFor:\s*withFloorPlan\b/.test(entry)) failures.push('2D 맵 노드가 도면을 안 쓰는 편(박스 편) 팔레트에도 선다');
}

if (failures.length) {
  console.error(`❌ verify:script-box\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 박스 편은 문 편에서 T-A1 만 빠진 같은 틀이다 — 마일스톤은 문 → 박스, T-B1 은 「이동 경로 산출」');
console.log('✅ 준비 단계가 도면을 안 받고 방위 하나로 한 바퀴를 연다 — 문 편은 여전히 도면을 기다린다');
console.log('✅ 탐지에 target=box 로 묻고, 탐지 결과만으로 낸 경로만 받는다 — 도면 경로는 실패로 남기고 로봇은 안 움직인다');
console.log('✅ 2D 맵 노드는 도면을 쓰는 편에만 선다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
