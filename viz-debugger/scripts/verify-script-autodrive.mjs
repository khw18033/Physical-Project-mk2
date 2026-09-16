// verify:script-autodrive (260915 신설 — 새 시나리오 「문 앞까지 자율주행 진행해」)
//
// 6편째 `MSN-260915-01` 이 틀대로 서 있고, **시연 편(`MSN-260909-01`)을 건드리지 않는지.**
//
// 막으려는 실패 넷.
//  1. **두 편이 서로의 문장을 먹는 것.** 「문 앞까지 자율주행 진행해」는 시연 편의 must 「문앞」에도
//     걸린다. 매처는 모호하면 고르지 않으므로 둘 다 못 쓰게 된다. 시연 편이 제외어(`not`)로
//     「자율주행」을 내어 주고, 시연 편의 문장은 여전히 시연 편에만 가야 한다.
//  2. **틀이 흐트러지는 것.** 마일스톤 셋(로봇 상태 확인 · 자율주행 시작 · 임무 종료), 태스크의
//     순서, 「장애물 탐지부터 반복」 되돌아감이 deps 가 아닌 참조 엣지로 서 있는가.
//  3. **새 편이 실물 로봇을 움직이는 것.** 로봇 경로(준비 · 스캔 · 접근)는 문 찾기 편의 태스크에
//     묶여 있다. 새 편을 승인하고 「임무 시작」을 눌러 `scan_mission` 이 나가면 안 된다 —
//     `driver: 'relay'` 편은 승인이 로봇 관문을 안 연다. 시연 편은 여전히 연다(대조).
//  4. **합성 진행이 중계와 섞이는 것** (260915 — `script` → `relay`). 새 편은 유니티가 몰고 pi1 이
//     전해 주는 것만 칠한다. 대본 재생기가 돌면 안 되고, 승인하면 중계 판이 열려야 한다.
//
// 대조군 포함 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 본다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readFileSync(join(root, ...p), 'utf8');
/** 주석을 걷어 낸 소스 — 「왜 이렇게 뒀는지」 적어 둔 글이 규칙에 걸리면 안 된다. */
const code = (source) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

const { matchLibrary } = await load('src', 'scenarios', 'matcher.ts');
const { SCRIPT_IDS, LEGACY_ID } = await load('src', 'scenarios', 'manifest.ts');

const AUTO_ID = 'MSN-260915-01';
const DOOR_ID = 'MSN-260909-01';
const readScript = (id) => JSON.parse(read('scenarios', `${id}.json`));

const failures = [];
const controls = [];

if (!SCRIPT_IDS.includes(AUTO_ID)) {
  console.error(`❌ verify:script-autodrive\n- ${AUTO_ID} 가 manifest 목록에 없다 — 라이브러리에 실리지 않는다`);
  process.exit(1);
}

const auto = readScript(AUTO_ID);
const door = readScript(DOOR_ID);
const legacySidecar = JSON.parse(read('scenarios', `${LEGACY_ID}.match.json`));
const library = [
  ...SCRIPT_IDS.map((id) => ({ missionId: id, match: readScript(id).match })),
  { missionId: LEGACY_ID, match: legacySidecar.match },
];
const matchOf = (sentence, lib = library) => {
  const outcome = matchLibrary(sentence, lib);
  return outcome.kind === 'matched' ? outcome.entry.missionId : outcome.kind;
};

// ── 1. 발화 — 새 편은 새 편에만, 시연 편은 시연 편에만 ──────────────────────────
const AUTO_VARIANTS = [
  '문 앞까지 자율주행 진행해',
  '문앞까지 자율주행 진행해',
  '문 앞까지 자율 주행 해줘',
  '자율주행으로 문 앞까지 가',
  '자율주행 시작해',
];
for (const sentence of AUTO_VARIANTS) {
  const got = matchOf(sentence);
  if (got !== AUTO_ID) failures.push(`「${sentence}」 → ${got} — ${AUTO_ID} 하나에만 맞아야 한다`);
}
if (auto.utterance.text !== '문 앞까지 자율주행 진행해') failures.push(`기준 문장이 「${auto.utterance.text}」 — 「문 앞까지 자율주행 진행해」여야 한다`);

// 시연 편의 발화 변형 — verify:script-door 와 같은 목록이다. 제외어가 이 문장들을 내어 주면 안 된다.
for (const sentence of ['저기 문 쪽으로 가', '문 쪽으로 가', '문으로 가줘', '문 앞으로 이동해줘', '문앞으로 이동해줘']) {
  const got = matchOf(sentence);
  if (got !== DOOR_ID) failures.push(`시연 문장 「${sentence}」 → ${got} — 새 편이 시연 편을 빼앗았다`);
}
for (const id of SCRIPT_IDS) {
  const got = matchOf(readScript(id).utterance.text);
  if (got !== id) failures.push(`기존 편 문장 「${readScript(id).utterance.text}」 → ${got} — ${id} 이어야 한다`);
}
if (matchOf('안녕하세요') !== 'none') failures.push('「안녕하세요」가 거부되지 않았다');
// 제외어는 시연 편 **한 곳에만** 있다 — 다른 편에 퍼지면 그 편의 문장을 조용히 버리게 된다.
if (JSON.stringify(door.match.not) !== JSON.stringify(['자율주행'])) {
  failures.push(`시연 편의 제외어가 [${(door.match.not ?? []).join(', ')}] — 「자율주행」 하나여야 한다`);
}
for (const id of SCRIPT_IDS) {
  if (id !== DOOR_ID && readScript(id).match.not !== undefined) failures.push(`${id} 에 제외어가 생겼다 — 시연 편만 둔다`);
}

// ── 2. 틀 — 마일스톤 셋 · 태스크 순서 · 되돌아감 ────────────────────────────────
const MILESTONES = [['MS-A', '로봇 상태 확인'], ['MS-B', '자율주행 시작'], ['MS-C', '임무 종료']];
const gotMilestones = auto.milestones.map((m) => [m.id, m.title]);
if (JSON.stringify(gotMilestones) !== JSON.stringify(MILESTONES)) {
  failures.push(`마일스톤이 ${JSON.stringify(gotMilestones)} — ${JSON.stringify(MILESTONES)} 여야 한다`);
}
/** 마일스톤별 태스크 — 발화자가 준 순서 그대로. 사슬이라 앞 태스크 하나에만 매달린다. */
const CHAIN = [
  ['MS-A', 'T-NA1', '로봇 배터리 확인'],
  ['MS-A', 'T-NA2', '로봇 위치 확인'],
  ['MS-B', 'T-NB1', '이동경로 탐색'],
  ['MS-B', 'T-NB2', '장애물 탐지'],
  ['MS-B', 'T-NB3', '경로 재탐색'],
  ['MS-B', 'T-NB4', '목적지까지 이동'],
  ['MS-B', 'T-NB5', '목적지 도착'],
  ['MS-C', 'T-NC1', '임무 종료'],
];
function checkChain(script) {
  const f = [];
  const byId = new Map(script.tasks.map((t) => [t.id, t]));
  if (script.tasks.length !== CHAIN.length) f.push(`태스크가 ${script.tasks.length}개 — ${CHAIN.length}개여야 한다`);
  CHAIN.forEach(([milestone, id, title], index) => {
    const t = byId.get(id);
    if (!t) { f.push(`${id}(${title}) 이 없다`); return; }
    if (t.milestone !== milestone) f.push(`${id} 가 ${t.milestone} 에 있다 — ${milestone} 이어야 한다`);
    if (t.title !== title) f.push(`${id} 제목이 「${t.title}」 — 「${title}」여야 한다`);
    const want = index === 0 ? [] : [CHAIN[index - 1][1]];
    if (JSON.stringify(t.deps) !== JSON.stringify(want)) f.push(`${id}.deps 가 [${t.deps.join(', ')}] — 순서도는 [${want.join(', ')}] 다`);
  });
  const loop = (script.refEdges ?? []).filter((e) => e.from === 'T-NB4' && e.to === 'T-NB2');
  if (loop.length !== 1) f.push('「목적지까지 이동 → 장애물 탐지」 되돌아감 참조 엣지가 하나가 아니다');
  if ((script.refEdges ?? []).length !== 1) f.push(`참조 엣지가 ${(script.refEdges ?? []).length}개 — 되돌아감 하나다`);
  return f;
}
failures.push(...checkChain(auto));
if (auto.tasks.find((t) => t.id === 'T-NC1')?.target !== null) failures.push('임무 종료 태스크에 대상 장비가 있다 — 장비가 하지 않는 일이다');

// 대본 안에서 루프가 실제로 한 바퀴 돈다 — 목적지 전에 장애물 탐지로 되돌아간 2회차가 있어야 한다.
const loopBack = auto.events.find((e) => e.kind === 'derived' && e.nodeId === 'T-NB2' && e.derivedFrom === 'T-NB4');
if (!loopBack) failures.push('대본에 장애물 탐지 2회차(derivedFrom T-NB4)가 없다 — 되돌아감이 그림에만 있다');
const arrive = auto.events.find((e) => e.nodeId === 'T-NB5' && e.status === 'done');
// 260915 — 도착 판정은 거리가 아니라 경로 끝 통지(mode 99)다. 목적지 좌표가 없어 거리를 판정할 수 없다.
if (!arrive || arrive.payload?.ended_by !== 'path_done') {
  failures.push('목적지 도착이 경로 끝(mode 99) 근거 없이 끝난다');
}
if ('arrival_distance_max_m' in (auto.params ?? {})) failures.push('판정하지 않는 거리 기준(arrival_distance_max_m)이 대본에 남아 있다');
if (loopBack && arrive && loopBack.atSec >= arrive.atSec) failures.push('도착 뒤에 되돌아간다 — 반복은 도착 전이다');

// 문 찾기 편의 태스크 id 와 겹치면 안 된다 — 로봇·탐지 경로가 태스크 id 로 노드를 칠한다.
const doorIds = new Set(door.tasks.map((t) => t.id));
const clash = auto.tasks.filter((t) => doorIds.has(t.id)).map((t) => t.id);
if (clash.length > 0) failures.push(`시연 편과 태스크 id 가 겹친다 — ${clash.join(', ')} (로봇 경로가 그 id 로 노드를 칠한다)`);

// ── 3. 로봇 관문 — 새 편은 안 열고, 시연 편은 연다 ─────────────────────────────
const { scriptDriven, relayDriven, opensRobotGate } = await load('src', 'scenarios', 'library.ts');
if (auto.driver !== 'relay') failures.push(`driver 가 ${auto.driver} — 유니티가 몰고 pi1 이 중계하는 편은 'relay' 여야 한다`);
if (!relayDriven(AUTO_ID)) failures.push('relayDriven() 이 새 편을 중계 편으로 안 본다');
if (scriptDriven(AUTO_ID)) failures.push('scriptDriven() 이 새 편을 대본 편으로 본다 — 합성 진행이 돈다');
if (opensRobotGate(AUTO_ID)) failures.push('opensRobotGate() 가 새 편에서 참이다');
for (const id of [...SCRIPT_IDS.filter((id) => id !== AUTO_ID), LEGACY_ID]) {
  if (scriptDriven(id) || relayDriven(id)) failures.push(`${id} 가 대본·중계 편으로 읽힌다 — 선언 없는 편은 그대로여야 한다`);
  if (!opensRobotGate(id)) failures.push(`opensRobotGate() 가 ${id} 에서 거짓이다 — 선언 없는 편은 그대로 관문을 연다`);
}

const scenario = await load('src', 'data', 'scenario.ts');
const session = await load('src', 'physical', 'robotSession.ts');
const commands = await load('src', 'physical', 'robotCommands.ts');

/** 붙은 척하면서 발행을 세는 가짜 클라이언트 (verify:no-publish-before-approval 과 같은 모양). */
function countingClient() {
  const sent = [];
  return {
    sent,
    getStatus: () => ({ state: 'open' }),
    onMessage: () => () => undefined,
    send(action, parameters) { sent.push({ action, parameters }); return { sent: true, commandId: `cmd-${sent.length}` }; },
  };
}

/** 제안 → 승인(사람이 누른 것과 같은 문) → 「임무 시작」 → 준비 창 닫힘 → 스캔 시도. */
async function approveAndStart(missionId) {
  scenario.resetMission();
  session.setConnection({ state: 'open' });
  scenario.proposeMission({ origin: 'script', missionId, title: missionId, keywords: [], planId: null, world: 'registry' });
  const accepted = scenario.acceptProposal('remote');
  const approved = session.robotSession().approved;
  session.markStarted();
  session.markPrepTasksDone();
  session.finishPrep();
  const client = countingClient();
  const scan = await commands.issueScan(client, scenario.currentMission().params);
  const result = {
    accepted, approved,
    started: session.robotSession().started,
    shouldScan: commands.shouldIssueScan(),
    sent: client.sent.map((s) => s.action),
    scanSent: scan.sent,
  };
  scenario.resetMission();
  return result;
}

const autoRun = await approveAndStart(AUTO_ID);
if (!autoRun.accepted) failures.push('새 편 승인이 캔버스에 안 올라갔다');
if (autoRun.approved) failures.push('새 편 승인이 로봇 관문을 열었다 — 「임무 시작」 한 번에 문 찾기 스캔이 나갈 수 있다');
if (autoRun.started) failures.push('새 편에서 「임무 시작」이 로봇 판을 시작했다');
if (autoRun.shouldScan) failures.push('새 편에서 스캔을 쏠 조건이 선다');
if (autoRun.sent.length > 0 || autoRun.scanSent) failures.push(`새 편에서 로봇으로 ${autoRun.sent.join(', ')} 이 나갔다`);

// 대조 — 시연 편은 지금까지처럼 승인이 관문을 열고, 시작 뒤 스캔이 나간다.
const doorRun = await approveAndStart(DOOR_ID);
if (!doorRun.approved) failures.push('시연 편 승인이 로봇 관문을 안 연다 — 시연이 멈춘다');
if (!doorRun.started) failures.push('시연 편에서 「임무 시작」이 안 먹는다');
if (JSON.stringify(doorRun.sent) !== JSON.stringify(['scan_mission'])) {
  failures.push(`시연 편 시작 뒤 나간 명령이 [${doorRun.sent.join(', ')}] — scan_mission 하나여야 한다`);
}

// 처음부터 — 새 편은 관문을 안 열고, 시연 편은 연다.
for (const [id, wantOpen] of [[AUTO_ID, false], [DOOR_ID, true]]) {
  scenario.resetMission();
  scenario.proposeMission({ origin: 'script', missionId: id, title: id, keywords: [], planId: null, world: 'registry' });
  scenario.acceptProposal('remote');
  scenario.restartMission();
  if (session.robotSession().approved !== wantOpen) {
    failures.push(`${id} 「처음부터」 뒤 관문이 ${session.robotSession().approved ? '열렸다' : '닫혔다'} — ${wantOpen ? '열려야' : '닫혀야'} 한다`);
  }
  scenario.resetMission();
}

// 브리지 — 중계 편은 로봇 편처럼 합성 진행을 버리고(일반 모드), 대본 편만 시나리오 모드로 간다.
// 관문은 선언 없는 편만 연다. 로봇 편 규칙은 그대로.
const bridge = code(read('src', 'shell', 'missionBridge.ts'));
if (!/world === 'registry' && !scriptDriven\(missionId\)/.test(bridge)) failures.push('missionBridge 가 합성 진행을 버리는 규칙이 바뀌었다');
if (!/world !== 'registry' \|\| scriptDriven\(/.test(bridge)) failures.push('missionBridge 의 시나리오 모드 관문이 바뀌었다');
if (!/opensRobotGate\(plan\.script\.mission_id\)\) markApproved\(\)/.test(bridge)) failures.push('missionBridge 승인이 중계 편에도 로봇 관문을 연다');

// ── 4. 중계 편은 대본 재생기가 안 돌고, 승인하면 중계 판이 열린다 ─────────────────
const { navRun, navRunState } = await load('src', 'physical', 'navRun.ts');
async function localPlays(missionId, connection) {
  scenario.resetMission();
  session.setConnection({ state: connection });
  scenario.activateMission(missionId, 'local');
  // 260915 — 승인은 판을 **걸어만** 둔다. 여는 것은 「▶ 임무 시작」이다.
  const opened = navRunState().armed === missionId && navRun() === null;
  await new Promise((resolve) => setTimeout(resolve, 450));
  const head = scenario.getMissionState().headSec;
  scenario.resetMission();
  return { plays: head > 0, opened, closedAfterReset: navRun() === null };
}
for (const connection of ['open', 'idle']) {
  const run = await localPlays(AUTO_ID, connection);
  if (run.plays) failures.push(`브로커 ${connection} 에서 새 편의 대본 재생기가 돈다 — 합성 진행이 중계와 섞인다`);
  if (!run.opened) failures.push(`브로커 ${connection} 에서 새 편을 올렸는데 중계 판이 걸리지 않았거나(승인) 벌써 열렸다(시작 전)`);
  if (!run.closedAfterReset || navRunState().armed !== null) failures.push('초기화했는데 중계 판이 안 내려갔다');
}
{
  const door = await localPlays(DOOR_ID, 'open');
  if (door.plays) failures.push('브로커가 붙은 상태에서 시연 편의 대본 타이머가 돈다 — 로봇보다 화면이 앞서 간다');
  if (door.opened) failures.push('시연 편을 올렸는데 중계 판이 열렸다');
}
session.setConnection({ state: 'idle' });

// ── 대조군 — 무력화한 사본이 잡히는가 ─────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  // 시연 편의 제외어를 지우면 기준 문장이 두 편에 걸려 모호 거부된다.
  const noNot = library.map((e) => (e.missionId === DOOR_ID ? { ...e, match: { ...e.match, not: undefined } } : e));
  control('시연 편 제외어 삭제(두 편에 모호)', matchOf(auto.utterance.text, noNot) === 'ambiguous');
}
{
  // 되돌아감을 deps 로 넣으면 사슬 검사가 잡는다.
  const m = structuredClone(auto);
  m.tasks.find((t) => t.id === 'T-NB2').deps = ['T-NB1', 'T-NB4'];
  control('되돌아감을 deps 로 넣음', checkChain(m).some((msg) => msg.includes('T-NB2.deps')));
}
{
  // 참조 엣지를 지우면 반복이 그림에서 사라진다.
  const m = structuredClone(auto);
  m.refEdges = [];
  control('되돌아감 참조 엣지 삭제', checkChain(m).some((msg) => msg.includes('되돌아감')));
}
{
  // 선언을 지우면 새 편이 로봇 편으로 돌아가 관문이 열린다 — 지금 규칙이 그 선언 하나에 달려 있다.
  const { SCRIPT_LIBRARY } = await load('src', 'scenarios', 'library.ts');
  const entry = SCRIPT_LIBRARY.find((e) => e.missionId === AUTO_ID);
  const saved = entry.script.driver;
  delete entry.script.driver;
  const run = await approveAndStart(AUTO_ID);
  entry.script.driver = saved;
  control('driver 선언 삭제(관문이 열린다)', run.approved && run.sent.includes('scan_mission'));
}

// ── 결과 ─────────────────────────────────────────────────────────────────────
if (failures.length) {
  console.error(`❌ verify:script-autodrive\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 발화 변형 ${AUTO_VARIANTS.length}개 전부 ${AUTO_ID} 하나에 · 시연 문장은 여전히 ${DOOR_ID} · 기존 편 무사`);
console.log(`✅ 마일스톤 셋 · 태스크 ${auto.tasks.length} 사슬 · 「장애물 탐지부터 반복」 참조 엣지 · 대본 안 2회차 · 시연 편과 태스크 id 안 겹침`);
console.log('✅ 새 편 승인·처음부터는 로봇 관문을 안 연다 — 「임무 시작」에도 로봇으로 0건 · 시연 편은 그대로 scan_mission');
console.log('✅ 새 편은 대본 재생기가 안 돌고 승인하면 중계 판이 열린다 · 시연 편은 중계 판이 안 열리고 타이머도 그대로');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
