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
//  5. **박스 근거를 문의 말로 적는 것** (261102). 「특징 최고값」·「문 없음」·「도면 기준 방위」, 관문 키 이름 — 6절
//  6. **못 찾은 각도의 상자 그림이 404 인데 그림 없이 넘어가는 것** (261102) — 7절
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

// ── 6. 근거 카드 — 박스의 말로, 받은 문장 그대로 (261102) ─────────────────────────
//
// 카드를 실제로 그린다(`lib/detectViewsProbe.mjs`). 막으려는 실패 넷.
//   - 박스 편 카드에 「문」·「특징 최고값」·「도면」이 뜨는 것 — 문 전용 문구가 박스에 틀린 말을 한다
//   - 관문 키 이름(`score_gate`)이 뜨는 것 — 탐지가 준 `words` 를 안 읽는다
//   - 거리 조건 ✕를 숨기는 것 — 「통과」만 말하면 거리를 못 쓰는 판정이 멀쩡해 보인다
//   - 문 편이 바뀌는 것 — **고치기 전 커밋(`BASELINE`)과 같은 입력으로 그려 글자를 견준다**
//
// `BASELINE` 은 박스 근거 작업 바로 앞 커밋이다. 문 편 카드를 일부러 바꾸면 이 대조가 그 차이를 보여 준다 —
// 바꾼 것이 맞으면 그때 이 값을 그 커밋으로 옮긴다.
const BASELINE = '79c54e2';
const recordRun = (...p) => JSON.parse(readFileSync(join(root, '..', 'mission-history', ...p), 'utf8'));
{
  const { makeScratch } = await load('scripts', 'lib', 'scratch.mjs');
  const { bundleDetectViews, baselineTree } = await load('scripts', 'lib', 'detectViewsProbe.mjs');
  const scratch = makeScratch(root, '.verify-box-');
  try {
    const cur = await bundleDetectViews(root, scratch.file('current.mjs'));
    const base = await bundleDetectViews(baselineTree(BASELINE, scratch.dir), scratch.file('baseline.mjs'));
    const textOf = (html) => html.replace(/<[^>]*>/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
    /** 한 묶음에 판 하나를 넣고 카드를 그린다. */
    const card = (mod, missionId, { frames, evidence, features }, zoom) => {
      mod.scenario.previewMission(missionId);
      mod.store.resetDetect();
      mod.store.setTestMode(false);
      mod.store.receiveFrames(frames);
      for (const [frame, item] of Object.entries(evidence)) mod.store.receiveEvidence(frame, item);
      mod.store.receiveFeatures(features);
      // 그림 주소의 판 번호(`round=`)는 두 묶음이 그린 횟수에 따라 다르다 — 화면 글자가 아니라서 지운다.
      return mod.renderToString(mod.createElement(mod.DetectReason, { zoom, count: 8 })).replace(/round=\d+/g, 'round=N');
    };

    // 실물 — 261102/001748 판(270°에서 박스 0.568 · 119cm). 관문은 그 판에 없었다(`{}`) — 그대로가 「지난 판」이다.
    const real = recordRun('261102', '001748_MSN-261027-01', 'progress.json').detect;
    const realFrame = real.frames.find((f) => f.found);
    const oldRun = { frames: real.frames, evidence: real.evidence, features: real.features };
    // 계약대로 온 새 판 — 실물 위에 탐지 쪽이 더할 필드를 얹는다.
    const GATES = {
      score_gate: { required: true, passed: true, score: 0.568, threshold_min: 0.25, words: 'YOLO 점수 0.57/0.25' },
      height_gate: { required: false, passed: true, y1: 125.0, y2: 167.6, crop_h: 241, edge_px: 2.0, words: '높이 42.6px 측정 가능(위·아래 끝에 안 닿음)' },
      calibration_range: { required: false, passed: true, distance_cm: 119.0, validated_cm: [50, 150], words: '실측 검증 범위 50~150cm 안' },
    };
    const newFrames = real.frames.map((f) => f.found ? f
      : f.rotation_deg === 0 ? { ...f, best_rejected_score: 0.18 }
        : f.rotation_deg === 45 ? { ...f, best_rejected_score: null } : f);
    const withGates = (gates) => ({
      frames: newFrames,
      evidence: { [realFrame.frame]: { ...real.evidence[realFrame.frame], mandatory_gates: gates,
        rejected_candidates: [{ box_xyxy: [1, 2, 3, 4], score: 0.18, threshold_min: 0.25, words: '후보 0.18 < 0.25 → 버림' }] } },
      features: real.features,
    });
    const newRun = withGates(GATES);
    const outOfRange = withGates({ ...GATES, calibration_range: { ...GATES.calibration_range, passed: false, words: '실측 검증 범위 50~150cm 밖' } });

    const boxBanned = (what, text) => {
      for (const [word, why] of [[/(?<!관)문/, '「문」'], [/특징 최고값/, '「특징 최고값」'], [/도면/, '「도면」'], [/score_gate|height_gate|calibration_range/, '관문 키 이름']]) {
        if (word.test(text)) failures.push(`${what}에 ${why}이 뜬다 — ${text}`);
      }
    };
    for (const zoom of [false, true]) {
      const at = zoom ? '확대 카드' : '카드';
      const fresh = textOf(card(cur, BOX_ID, newRun, zoom));
      boxBanned(`박스 편 새 판 ${at}`, fresh);
      for (const words of Object.values(GATES).map((g) => g.words)) {
        if (!fresh.includes(words)) failures.push(`박스 편 ${at}에 탐지가 준 관문 문장 「${words}」이 안 뜬다 — ${fresh}`);
      }
      for (const must of ['판정', '거리 조건', 'YOLO 점수 0.568']) if (!fresh.includes(must)) failures.push(`박스 편 ${at}에 「${must}」가 없다 — ${fresh}`);
      if (fresh.includes('관문 근거 미수신')) failures.push(`관문이 왔는데 박스 편 ${at}가 「관문 근거 미수신」이다`);
      const old = textOf(card(cur, BOX_ID, oldRun, zoom));
      boxBanned(`박스 편 지난 판 ${at}`, old);
      if (!old.includes('관문 근거 미수신')) failures.push(`관문이 없는 지난 판(mandatory_gates: {})에서 박스 편 ${at}가 「관문 근거 미수신」이 아니다 — ${old}`);
      if (old.includes('물어본 특징')) failures.push(`박스 편 ${at}가 「물어본 특징 0개」를 적는다 — ${old}`);
    }
    const zoomed = card(cur, BOX_ID, newRun, true);
    if (/detect-features/.test(zoomed)) failures.push('박스 편이 빈 특징 표를 그린다 — 박스는 특징을 비교하지 않는다');
    if (!textOf(zoomed).includes('방위 300.1도 — 스캔 시작 기준, 박스 중심으로 보정한 참고값')) failures.push(`박스 편 방위 메모가 박스 문장이 아니다 — ${textOf(zoomed)}`);
    // 거리 조건 ✕ — 카드의 「거리 조건」 묶음에 ✕로, 판정 묶음은 그대로.
    const failedCard = card(cur, BOX_ID, outOfRange, false);
    if (!/is-fail">✕ 실측 검증 범위 50~150cm 밖/.test(failedCard.replace(/<!-- -->/g, ''))) failures.push(`거리 조건 ✕가 카드에 ✕로 안 뜬다 — ${textOf(failedCard)}`);
    // 거리를 못 쓴 칸 — 탐지가 준 이유 그대로. 「도면 좌표」는 안 나온다.
    const reason = '박스가 화면 위/아래 끝에 닿아 높이를 못 잰다';
    const noDistance = { ...oldRun, frames: real.frames.map((f) => f.found ? { ...f, distance_cm: null, in_valid_calibration_range: false, distance_reason: reason } : f) };
    const noDistanceText = textOf(card(cur, BOX_ID, noDistance, true));
    if (!noDistanceText.includes(reason)) failures.push(`거리를 못 쓴 박스 칸에 탐지가 준 이유가 안 뜬다 — ${noDistanceText}`);
    boxBanned('거리를 못 쓴 박스 확대 카드', noDistanceText);
    const noneFound = textOf(card(cur, BOX_ID, { frames: real.frames.map((f) => ({ frame: f.frame, rotation_deg: f.rotation_deg, found: false })), evidence: {}, features: null }, false));
    if (noneFound !== '여덟 각도에서 박스를 못 찾았습니다 임의로 한 방향을 고르지 않습니다') failures.push(`박스를 못 찾은 판의 카드가 「${noneFound}」`);

    // 한 줄 문장 — 여덟 칸에 붙는 말. 못 찾은 칸 셋 · 찾은 칸 · 거리 조건 ✕.
    const ev = (run) => run.evidence[realFrame.frame];
    const opts = (frame, run) => ({ target: 'box', frame, thresholdMin: cur.parse.boxThresholdOf(run.evidence) });
    const sentences = {
      rejected: cur.parse.reasonOf(null, false, true, opts(newFrames[0], newRun)),
      noCandidate: cur.parse.reasonOf(null, false, true, opts(newFrames[1], newRun)),
      unknown: cur.parse.reasonOf(null, false, true, opts(newFrames[2], newRun)),
      chosen: cur.parse.reasonOf(ev(newRun), true, true, opts(realFrame, newRun)),
      notChosen: cur.parse.reasonOf(ev(newRun), true, false, opts(realFrame, newRun)),
      failed: cur.parse.reasonOf(ev(outOfRange), true, true, opts(realFrame, outOfRange)),
      old: cur.parse.reasonOf(ev(oldRun), true, true, opts(realFrame, oldRun)),
    };
    const want = {
      rejected: '박스 없음 (최고 후보 0.18 < 0.25)',
      noCandidate: '박스 없음 (후보 없음)',
      unknown: '박스 없음',
      chosen: 'YOLO 점수 0.57/0.25 통과 · YOLO 점수 0.57',
      notChosen: '박스 후보 (점수가 더 높은 각도가 있어 안 고름) · YOLO 점수 0.57',
      failed: 'YOLO 점수 0.57/0.25 통과 · ✕ 실측 검증 범위 50~150cm 밖 · YOLO 점수 0.57',
      old: '박스 있음 · YOLO 점수 0.57',
    };
    for (const [key, sentence] of Object.entries(sentences)) {
      if (sentence !== want[key]) failures.push(`박스 편 칸 문장(${key})이 「${sentence}」 — 「${want[key]}」여야 한다`);
      boxBanned(`박스 편 칸 문장(${key})`, sentence);
    }
    // 기준을 받은 값이 없으면 문장에 기준을 지어 적지 않는다.
    const noThreshold = cur.parse.reasonOf(null, false, true, { target: 'box', frame: newFrames[0], thresholdMin: null });
    if (noThreshold !== '박스 없음 (최고 후보 0.18)') failures.push(`받은 기준이 없는데 「${noThreshold}」 — 0.25 를 지어 적는다`);
    if (cur.parse.boxThresholdOf(oldRun.evidence) !== 0.25) failures.push('지난 판의 기준을 검출기 conf(0.25)에서 못 읽는다');
    // 고르는 점수 — 근거를 못 받은 각도도 박스 편은 각도 결과 점수로 센다(탐지 경로의 best_overall 과 같은 기준).
    const two = [{ frame: 'a.jpg', rotation_deg: 90, found: true, final_score: 0.4 }, { frame: 'b.jpg', rotation_deg: 270, found: true, final_score: 0.6 }];
    const onlyA = { 'a.jpg': { final_score: 0.4 } };
    const pickBox = cur.parse.chosenFrame(two, (f) => cur.parse.judgeScore(f, onlyA[f.frame], 'box'));
    if (pickBox?.frame !== 'b.jpg') failures.push(`근거를 못 받은 각도(0.6)를 0 으로 쳐서 박스 편이 ${pickBox?.frame} 을 고른다 — 탐지 경로와 다른 각도다`);

    // ── 대조군 — 문 편은 고치기 전과 같다 ──
    const doorFeatures = cur.parse.normalizeFeatures(sample('door', 'features_sent.json'), 'door');
    const doorFrames = sample('door', 'target_summary.json').frames;
    const doorEvidence = Object.fromEntries(doorFrames.filter((f) => f.found).map((f) => [f.frame, sample('door', f.frame.replace(/\.jpg$/, ''), 'evidence.json')]));
    const doorRun = { frames: doorFrames, evidence: doorEvidence, features: doorFeatures };
    const doorNone = { frames: doorFrames.map((f) => ({ ...f, found: false })), evidence: {}, features: doorFeatures };
    // 박스 관문 모양(`words`)은 문 편에 안 온다 — `gateWords` 가 `words` 를 먼저 읽는 것이 설계다(문 관문에는 없다).
    for (const [what, run] of [['문 시료', doorRun], ['문 못 찾은 판', doorNone], ['문 편에 박스 지난 판 모양', oldRun]]) {
      for (const zoom of [false, true]) {
        // **확대 카드의 배치는 261103 에 일부러 바꿨다** (판단 근거 UI — 큰 그림 → 썸네일 + 값 표 · 원본 데이터 펼침).
        // 그 두 덩어리와 옛 큰 그림만 빼고 견준다 — 관문 · 특징 · 메모 글자는 여전히 고치기 전과 같아야 한다.
        const unzoomLayout = (html) => html
          .replace(/<div class="detect-reason__summary">[\s\S]*?<\/dl><\/div>/g, '')
          .replace(/<div class="detect-raw">[\s\S]*?<\/div>/g, '')
          .replace(/<img class="detect-crop"[^>]*\/>/g, '')
          .replace(' detect-reason--zoom', '');
        const now = zoom ? unzoomLayout(card(cur, DOOR_ID, run, zoom)) : card(cur, DOOR_ID, run, zoom);
        const before = zoom ? unzoomLayout(card(base, DOOR_ID, run, zoom)) : card(base, DOOR_ID, run, zoom);
        if (now !== before) failures.push(`문 편 ${what} ${zoom ? '확대 ' : ''}카드가 고치기 전(${BASELINE})과 다르다\n  전: ${textOf(before)}\n  후: ${textOf(now)}`);
      }
    }
    for (const frame of doorFrames) {
      const evidence = doorEvidence[frame.frame] ?? null;
      for (const chosen of [true, false]) {
        const now = cur.parse.reasonOf(evidence, frame.found, chosen);
        const before = base.parse.reasonOf(evidence, frame.found, chosen);
        if (now !== before) failures.push(`문 편 칸 문장이 바뀌었다 (${frame.rotation_deg}° chosen=${chosen}) — 전 「${before}」 · 후 「${now}」`);
      }
    }
    if (!textOf(card(cur, DOOR_ID, doorRun, true)).includes('특징 최고값')) failures.push('문 편 카드에 「특징 최고값」이 없다 — 대조가 헛돈다');
    // 대조가 헛돌지 않는지 — 박스 편 카드는 고치기 전과 **달라야** 한다(같으면 두 묶음이 같은 소스다).
    control('고치기 전 묶음의 박스 편 카드 (특징 최고값 · 관문 키 이름)', card(cur, BOX_ID, newRun, true) !== card(base, BOX_ID, newRun, true)
      && /score_gate|특징 최고값/.test(textOf(card(base, BOX_ID, newRun, true))));
  } finally {
    scratch.cleanup();
  }
}

// ── 7. 그림 — 못 찾은 각도도 상자 그림을 먼저, 404 면 원본이 뜬 뒤에 넘어간다 (261102) ─────
//
// 화면과 문지기가 같은 주소를 봐야 한다(`detect/frameImage.ts` 한 곳). 첫 주소의 실패를 「준비됨」으로 치면
// 그림이 안 뜬 채 다음 회전이 허락된다.
{
  const store = await load('src', 'detect', 'store.ts');
  const gate = await load('src', 'physical', 'scanGate.ts');
  const { frameImageSrc } = await load('src', 'detect', 'frameImage.ts');
  const { frameImageUrl, roundedImageUrl, viewSourceOf } = await load('src', 'detect', 'DetectClient.ts');
  const { receiveScanCapture } = await load('src', 'physical', 'robotBridge.ts');
  const { arrivedFrames } = await load('src', 'viewpoint', 'store.ts');
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const lit = () => [...new Set(arrivedFrames().filter((e) => e.frame.channel === 'robot_state').map((e) => e.frame.payload.rotation_index))].sort((a, b) => a - b).join(',');
  const name = (index) => `frame_${String(index + 1).padStart(6, '0')}.jpg`;
  const kindUrl = (index, kind, target) => roundedImageUrl(frameImageUrl(viewSourceOf(store.detectState()), name(index), kind, target), store.detectState().imageRound);
  const shown = (index, target) => frameImageSrc(viewSourceOf(store.detectState()), { frame: name(index), found: false }, target, store.detectState().imageRound);
  const result = (indices) => store.receiveFrames(indices.map((index) => ({ frame: name(index), rotation_deg: index * 45, found: false })));
  const freshRun = async (missionId) => {
    gate.resetScanGate();
    store.resetDetect();
    scenario.activateMission(missionId, 'remote');
    session.markApproved();
    await sleep(3);
    session.markStarted();
    session.markScanIssued();
    session.recordCommand({
      taskId: 'T-A3', commandId: 'cmd-box-gate', action: 'scan_mission', parameters: { steps: 8, step_deg: 45, forward_m: 0 },
      issuedAtIso: new Date().toISOString(), requestId: null, state: 'running', code: null, message: null, result: {}, log: [],
    });
    store.setTestMode(false);
  };
  const image = (missionId, index) => receiveScanCapture(missionId, index * 4 + 1, index, index === 0 ? 0 : null);
  try {
    // 뷰가 떠 있는 판 — img 의 onError → 원본으로 바꿔 그림 → 그 onLoad 뒤에야 다음 칸.
    await freshRun(BOX_ID);
    const releaseView = gate.registerScanImageView();
    image(BOX_ID, 0); image(BOX_ID, 1);
    result([0]);
    const overlay = kindUrl(0, 'target_overlay', 'box');
    const original = kindUrl(0, 'original', 'box');
    if (shown(0, 'box') !== overlay) failures.push(`박스 편 못 찾은 각도가 상자 그림을 먼저 안 묻는다 — ${shown(0, 'box')}`);
    gate.noteScanImageFailed(overlay);
    if (lit() !== '0') failures.push(`상자 그림이 404 인데 원본이 뜨기도 전에 다음 칸이 열렸다 (${lit()}) — 그림 없이 회전을 허락한다`);
    if (shown(0, 'box') !== original) failures.push(`상자 그림이 404 인데 원본으로 안 바꾼다 — ${shown(0, 'box')}`);
    gate.noteScanImageShown(original);
    if (lit() !== '0,1') failures.push(`원본이 떴는데 다음 칸이 안 열린다 (${lit()})`);
    // 원본까지 안 뜨면 지금처럼 넘어간다 — 멈추지 않는다.
    image(BOX_ID, 2);
    result([0, 1]);
    gate.noteScanImageFailed(kindUrl(1, 'target_overlay', 'box'));
    gate.noteScanImageFailed(kindUrl(1, 'original', 'box'));
    if (lit() !== '0,1,2') failures.push(`상자 그림 · 원본이 둘 다 안 떴는데 멈춘다 (${lit()})`);
    releaseView();

    // 뷰가 없는 판 — 문지기가 미리 받아 볼 때도 같은 차례다.
    await freshRun(BOX_ID);
    const asked = [];
    const realImage = globalThis.Image;
    globalThis.Image = class {
      set src(url) {
        asked.push(url);
        setTimeout(() => (url.includes('kind=target_overlay') ? this.onerror?.() : this.onload?.()), 0);
      }
    };
    gate.setScanImageLoader(null);
    try {
      image(BOX_ID, 0); image(BOX_ID, 1);
      result([0]);
      for (let i = 0; i < 40 && lit() !== '0,1'; i += 1) await sleep(5);
      if (asked[0] !== overlay.replace(/round=\d+/, `round=${store.detectState().imageRound}`)) failures.push(`뷰가 없을 때 상자 그림을 먼저 안 받는다 — ${asked[0]}`);
      if (!asked.some((u) => u.includes('kind=original'))) failures.push(`뷰가 없을 때 상자 그림이 404 인데 원본을 안 받는다 — ${asked.join(' · ')}`);
      if (lit() !== '0,1') failures.push(`뷰가 없을 때 원본을 받았는데 다음 칸이 안 열린다 (${lit()})`);
    } finally {
      globalThis.Image = realImage;
      gate.setScanImageLoader(null);
    }

    // 문 편은 그대로 — 못 찾은 각도는 원본 하나.
    await freshRun(DOOR_ID);
    result([0]);
    if (shown(0, 'door') !== kindUrl(0, 'original', 'door')) failures.push(`문 편 못 찾은 각도가 원본이 아닌 그림을 묻는다 — ${shown(0, 'door')}`);
  } finally {
    gate.resetScanGate(); store.resetDetect(); session.resetRobotSession();
  }
}

if (failures.length) {
  console.error(`❌ verify:script-box\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 박스 편은 문 편에서 T-A1 만 빠진 같은 틀이다 — 마일스톤은 문 → 박스, T-B1 은 「이동 경로 산출」');
console.log('✅ 준비 단계가 도면을 안 받고 방위 하나로 한 바퀴를 연다 — 문 편은 여전히 도면을 기다린다');
console.log('✅ 탐지에 target=box 로 묻고, 탐지 결과만으로 낸 경로만 받는다 — 도면 경로는 실패로 남기고 로봇은 안 움직인다');
console.log('✅ 2D 맵 노드는 도면을 쓰는 편에만 선다');
console.log('✅ 박스 편 근거 카드 — 탐지가 준 관문 문장 그대로 · 판정/거리 조건 두 묶음 · 「문」「특징 최고값」「도면」 없음 · 지난 판은 「관문 근거 미수신」');
console.log('✅ 박스 편 칸 문장 — 최고 후보 · 후보 없음 · 거리 조건 ✕를 숨기지 않는다 · 받은 기준만 적는다');
console.log(`✅ 문 편 카드·칸 문장이 고치기 전(${BASELINE})과 같다`);
console.log('✅ 박스 편 못 찾은 각도는 상자 그림을 먼저 묻고, 404 면 원본이 뜬 뒤에야 다음 칸 — 뷰가 있을 때도 없을 때도');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
