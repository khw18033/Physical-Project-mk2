// verify:script-two-devices (260927 신설 — 「장치 두 가지를 @까지 이동시켜」)
//
// 7편째 `MSN-260927-01` 이 지시대로 서 있는지.
//
// 막으려는 실패는 넷이다.
//  1. **같은 일을 하는 두 장치가 차례로 도는 것.** 경로 탐지와 장치 이동에서 첫 번째 · 두 번째 장치가
//     같은 행동을 하는 태스크는 **같은 부모에 매달려 나란히** 서야 한다(지시 첨부 그림). deps 로 사슬을
//     만들면 그래프도 재생도 한 줄로 늘어선다.
//  2. **@ 를 지어 넣는 것.** 발화에서 못 잘랐으면 빈칸 그대로여야 한다.
//  3. **장치를 대본이 정하는 것.** 두 장치는 자리이고, 앉히는 것은 사람이다 — 한 장비가 두 자리에 앉으면
//     「동시에 움직인다」가 한 장비의 일이 된다.
//  4. **이 편의 노드가 남의 팔레트에 서는 것, 남의 노드가 이 편에 서는 것.**

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
const read = (...parts) => readFileSync(join(root, ...parts), 'utf8');
const readScript = (id) => JSON.parse(read('scenarios', `${id}.json`));

const ID = 'MSN-260927-01';
const DOOR_ID = 'MSN-260909-01';
const failures = [];
const controls = [];

const { SCRIPT_IDS, LEGACY_ID } = await load('src', 'scenarios', 'manifest.ts');
const { matchLibrary } = await load('src', 'scenarios', 'matcher.ts');
const { extractTarget, fillText, fillPayload } = await load('src', 'scenarios', 'target.ts');

if (!SCRIPT_IDS.includes(ID)) failures.push(`${ID} 가 대본 목록(manifest)에 없다`);
const script = readScript(ID);

// ── 1. 문장 — 이 편에만 맞고, 시연 편을 빼앗지 않는다 ───────────────────────────
const library = [
  ...SCRIPT_IDS.map((id) => ({ missionId: id, match: readScript(id).match })),
  { missionId: LEGACY_ID, match: JSON.parse(read('scenarios', `${LEGACY_ID}.match.json`)).match },
];
const matchOf = (sentence) => {
  const outcome = matchLibrary(sentence, library, 'ko');
  return outcome.kind === 'matched' ? outcome.entry.missionId : outcome.kind;
};
for (const sentence of ['장치 두 가지를 @까지 이동시켜', '장치 두 가지를 문까지 이동시켜', '장치 두 가지를 문 앞까지 이동시켜', '장치 2개를 빨간 의자까지 옮겨', '두 장치를 소화기까지 보내']) {
  const got = matchOf(sentence);
  if (got !== ID) failures.push(`「${sentence}」 → ${got} — ${ID} 이어야 한다`);
}
for (const sentence of ['저기 문 쪽으로 가', '문 앞으로 이동해줘']) {
  if (matchOf(sentence) !== DOOR_ID) failures.push(`시연 문장 「${sentence}」 가 시연 편에 안 간다 — 새 편이 빼앗았다`);
}

// ── 2. @ — 발화가 정하고, 못 정하면 빈칸 그대로 ─────────────────────────────────
const cases = [
  ['장치 두 가지를 문까지 이동시켜', 'ko', '문'],
  ['장치 두 가지를 문 앞까지 이동시켜', 'ko', '문 앞'],
  ['장치 2개를 빨간 의자까지 옮겨', 'ko', '빨간 의자'],
  ['장치 두 가지를 @까지 이동시켜', 'ko', null],
  // 관사를 떼지 않는다 — 떼면 「Move both devices to door」가 된다. 잘라 온 그대로 채운다.
  ['Move both devices to the door', 'en', 'the door'],
  ['Move the two devices to @', 'en', null],
];
for (const [sentence, lang, want] of cases) {
  const got = extractTarget(sentence, script.target, lang);
  if (got !== want) failures.push(`「${sentence}」 에서 잘라 온 대상이 ${JSON.stringify(got)} — ${JSON.stringify(want)} 여야 한다`);
}
if (fillText('@ 위치 추정', '@', '문') !== '문 위치 추정') failures.push('fillText 가 빈칸을 안 채운다');
if (fillText('@ 위치 추정', '@', null) !== '@ 위치 추정') failures.push('대상이 없는데 빈칸을 바꿨다 — 지어 넣으면 안 된다');
{
  const payload = { criterion: '정지 시 @까지 거리가 1m 이하다', distance_to_target_m: 0.8 };
  const out = fillPayload(payload, '@', '문');
  if (out.criterion !== '정지 시 문까지 거리가 1m 이하다' || out.distance_to_target_m !== 0.8) failures.push('fillPayload 가 글자 칸만 채우지 않는다');
  if (fillPayload(payload, '@', null) !== payload) failures.push('대상이 없는데 payload 를 새로 만들었다');
}
// 빈칸이 실제로 쓰이는 자리 — 「@ 위치 추정」 마일스톤과 그 태스크들.
const msC = script.milestones.find((m) => m.title.includes('위치 추정'));
if (msC === undefined || !msC.title.startsWith(script.target.token)) failures.push('「@ 위치 추정」 마일스톤이 없다');
const locate = script.tasks.find((t) => t.id === script.params.virtual_map.locate_task);
if (locate === undefined || !locate.title.includes('가상 맵') || locate.title.includes('2D')) {
  failures.push(`위치 확인 태스크가 「가상 맵」으로 이름 지어지지 않았다 — ${locate?.title}`);
}

// ── 3. 틀 — 마일스톤 다섯 · 연결 확인 셋 이상 · 나란히 서는 태스크 ──────────────────
const byId = new Map(script.tasks.map((t) => [t.id, t]));
const tasksOf = (ms) => script.tasks.filter((t) => t.milestone === ms);
const TITLES = ['첫 번째 장치 연결 확인', '두 번째 장치 연결 확인', '@ 위치 추정', '경로 탐지', '장치 이동'];
if (JSON.stringify(script.milestones.map((m) => m.title)) !== JSON.stringify(TITLES)) {
  failures.push(`마일스톤이 [${script.milestones.map((m) => m.title).join(' · ')}] — [${TITLES.join(' · ')}] 여야 한다`);
}
for (const [index, slot] of [[0, 'device-1'], [1, 'device-2']]) {
  const ms = script.milestones[index];
  const own = tasksOf(ms.id);
  if (own.length < 3) failures.push(`${ms.title} 의 태스크가 ${own.length}개 — 셋 이상이어야 한다`);
  if (own.some((t) => t.target !== slot)) failures.push(`${ms.title} 의 태스크가 전부 ${slot} 를 보지 않는다`);
  if (JSON.stringify(ms.slots) !== JSON.stringify([slot])) failures.push(`${ms.title} 의 자리가 [${ms.slots}] — [${slot}] 여야 한다`);
}

/** 두 태스크가 **나란히** 서는가 — 같은 부모, 서로를 기다리지 않음, 같은 시각에 시작. */
function parallel(a, b) {
  const ta = byId.get(a);
  const tb = byId.get(b);
  if (ta === undefined || tb === undefined) return `${a} · ${b} 가 없다`;
  if (JSON.stringify([...ta.deps].sort()) !== JSON.stringify([...tb.deps].sort())) return `${a}(${ta.deps}) 와 ${b}(${tb.deps}) 의 부모가 다르다`;
  if (ta.deps.includes(b) || tb.deps.includes(a)) return `${a} 와 ${b} 가 서로를 기다린다`;
  const start = (id) => script.events.find((e) => e.nodeId === id && e.status === 'running')?.atSec;
  if (start(a) !== start(b)) return `${a}(${start(a)}s) 와 ${b}(${start(b)}s) 가 같은 시각에 시작하지 않는다`;
  if (ta.target === tb.target) return `${a} 와 ${b} 가 같은 대상(${ta.target})이다 — 첫 번째 · 두 번째 장치여야 한다`;
  return null;
}
function joins(id, parents) {
  const task = byId.get(id);
  if (task === undefined) return `${id} 가 없다`;
  return JSON.stringify([...task.deps].sort()) === JSON.stringify([...parents].sort()) ? null : `${id} 의 deps 가 [${task.deps}] — [${parents}] 여야 한다`;
}
const shape = [
  parallel('T-D1', 'T-D2'),
  joins('T-D3', ['T-D1', 'T-D2']),
  parallel('T-E1', 'T-E2'),
  joins('T-E3', ['T-E1']),
  joins('T-E4', ['T-E2']),
  joins('T-E5', ['T-E3', 'T-E4']),
].filter((line) => line !== null);
failures.push(...shape);
{
  // 대조군 — 두 번째 장치 경로 탐지를 첫 번째 뒤에 사슬로 걸면 잡혀야 한다.
  const chained = structuredClone(script);
  chained.tasks.find((t) => t.id === 'T-D2').deps = ['T-D1'];
  const saved = new Map(byId);
  byId.clear();
  for (const t of chained.tasks) byId.set(t.id, t);
  const caught = parallel('T-D1', 'T-D2') !== null;
  byId.clear();
  for (const [k, v] of saved) byId.set(k, v);
  if (!caught) failures.push('대조군 실패: 경로 탐지를 사슬로 건 사본이 안 잡혔다');
  controls.push('경로 탐지를 사슬로 건 사본');
}

// ── 4. 진행 · 관문 — 일반 모드로 돌고, 화면이 몰고, 로봇 관문은 안 연다 ──────────────
// 260927 둘째 지시 — 「문 탐지 때처럼 대본인 티를 내지 말고 일반에서 작동」. 시나리오 모드(합성 데이터 띠)로
// 들어가면 안 되고, 승인은 판을 걸어만 두며 「▶ 임무 시작」이 진행을 연다.
const { scriptDriven, relayDriven, localDriven, opensRobotGate, slotDriven } = await load('src', 'scenarios', 'library.ts');
if (script.driver !== 'local') failures.push(`driver 가 ${script.driver} — 일반 모드에서 화면이 모는 'local' 이어야 한다`);
if (scriptDriven(ID)) failures.push('scriptDriven() 이 참이다 — 승인하면 시나리오 모드(합성 데이터 띠)로 들어간다');
if (relayDriven(ID) || !localDriven(ID)) failures.push('localDriven() 이 이 편을 화면이 모는 편으로 안 본다');
if (opensRobotGate(ID)) failures.push('opensRobotGate() 가 이 편에서 참이다 — 승인하면 문 찾기 스캔이 로봇으로 나간다');
if (!slotDriven(ID)) failures.push('slotDriven() 이 이 편을 자리 편으로 안 본다');
for (const id of SCRIPT_IDS.filter((id) => id !== ID)) {
  if (slotDriven(id) || localDriven(id)) failures.push(`${id} 가 자리 편·화면이 모는 편으로 읽힌다 — 선언 없는 편은 그대로여야 한다`);
}
if (script.cast.length !== 0) failures.push(`cast 가 [${script.cast}] — 장비를 대본이 정하지 않는다`);
const bridge = read('src', 'shell', 'missionBridge.ts');
if (!/plan\.script\.world !== 'registry' \|\| scriptDriven\(plan\.script\.mission_id\)\) \{/.test(bridge)) failures.push('게이트웨이 승인이 시나리오 모드로 들어가는 조건이 바뀌었다 — 이 편이 띠를 띄울 수 있다');
if (!/libraryEntry\(missionId\)\?\.world === 'registry' && !scriptDriven\(missionId\)/.test(bridge)) failures.push('게이트웨이 합성 진행을 버리는 조건이 바뀌었다 — 이 편에 두 진행이 겹친다');
const buttons = read('src', 'physical', 'StopButton.tsx');
for (const fn of ['startLocalRun', 'pauseLocalRun', 'resumeLocalRun', 'stopLocalRun']) {
  if (!buttons.includes(`${fn}()`)) failures.push(`머리줄 버튼이 ${fn}() 을 안 부른다`);
}

// ── 5. 자리 배정 — 한 장비는 한 자리 ────────────────────────────────────────────
const slots = await load('src', 'data', 'slots.ts');
slots.resetSlots();
slots.holdSlotsFor(ID);
slots.dropOnSlots(['device-1'], 'go1');
slots.dropOnSlots(['device-2'], 'drone');
let b = slots.slotBindings();
if (b['device-1'] !== 'go1' || b['device-2'] !== 'drone') failures.push(`한 자리 마일스톤에 놓은 배정이 ${JSON.stringify(b)}`);
slots.dropOnSlots(['device-1'], 'drone');
b = slots.slotBindings();
if (b['device-1'] !== 'drone' || b['device-2'] !== 'go1') failures.push(`이미 앉은 장비를 다른 자리에 놓았는데 맞바꾸지 않았다 — ${JSON.stringify(b)}`);
slots.resetSlots();
slots.holdSlotsFor(ID);
slots.dropOnSlots(['device-1', 'device-2'], 'go1');
slots.dropOnSlots(['device-1', 'device-2'], 'drone');
b = slots.slotBindings();
if (b['device-1'] !== 'go1' || b['device-2'] !== 'drone') failures.push(`두 자리 마일스톤에 차례로 놓은 배정이 ${JSON.stringify(b)} — 빈 자리부터 채워야 한다`);
slots.dropOnSlots(['device-1', 'device-2'], 'go1');
if (JSON.stringify(slots.slotBindings()) !== JSON.stringify(b)) failures.push('이미 앉은 장비를 같은 마일스톤에 또 놓았는데 배정이 바뀌었다');
if (slots.resolveSlot('device-2') !== 'drone' || slots.resolveSlot('robot-01') !== 'robot-01' || slots.resolveSlot(null) !== null) failures.push('resolveSlot 이 자리만 풀지 않는다');
slots.holdSlotsFor(ID);
if (slots.slotBindings()['device-1'] !== 'go1') failures.push('같은 임무를 다시 올렸는데 배정이 지워졌다 — 제안 중에 앉힌 것이 승인 뒤에 사라진다');
slots.holdSlotsFor(DOOR_ID);
if (Object.keys(slots.slotBindings()).length !== 0) failures.push('다른 임무로 바뀌었는데 배정이 남았다');
slots.resetSlots();

// 화면이 이 규칙을 실제로 쓰는가 — 마일스톤에 놓는 자리와 태스크 대상을 푸는 자리.
const main = read('src', 'main.tsx');
if (!/dropOnSlots\(slots, hardware\)/.test(main)) failures.push('마일스톤에 카드를 놓아도 자리 배정(dropOnSlots)을 안 부른다');
if (!/bindings\[slot\.id\] \?\? slot\.label/.test(main)) failures.push('태스크 그래프가 자리를 배정된 장비로 풀지 않는다');

// ── 6. 뷰 노드 — 이 편의 셋은 이 편에만, 시연 편의 넷은 이 편에서 빠진다 ──────────────
const renderers = read('src', 'tabs', 'viewNodes.tsx');
for (const kind of ['virtual-map', 'device-cam', 'obstacle-log']) {
  const block = renderers.match(new RegExp(`kind: '${kind}'[\\s\\S]*?showFor: (\\w+)`));
  if (block?.[1] !== 'onlySlots') failures.push(`${kind} 가 이 편 팔레트에만 서지 않는다 (showFor: ${block?.[1]})`);
}
if (!/const notRelay = \(missionId: string\) => !relayDriven\(missionId\) && !slotDriven\(missionId\)/.test(renderers)) {
  failures.push('문 찾기 시연의 노드(탐지 셋 · 로봇)가 이 편 팔레트에도 선다');
}
// 버튼을 장치마다 · 맵 종류마다 늘리지 않는다 — 카메라 하나, 가상 맵 하나.
if ((renderers.match(/kind: '[^']*cam[^']*'/g) ?? []).filter((k) => !/autodrive|detect/.test(k)).length !== 1) failures.push('카메라 노드 종류가 하나가 아니다 — 장치마다 버튼을 늘렸다');
const connections = read('src', 'shared', 'connections.ts');
if (!/id: 'digital-twin',[\s\S]{0,200}?live: true/.test(connections)) failures.push('연결 관리의 가상 맵(digital-twin) 대상이 아직 「상대 없음」이다 — 맵은 연결 관리에서 고른다');
const vmap = read('src', 'virtualmap', 'VirtualMap.tsx');
if (!/connectionAddress\('digital-twin', 'base'\)/.test(vmap)) failures.push('가상 맵 노드가 연결 관리의 주소로 Unity · 2D 를 가르지 않는다');

// ── 7. Go1 실동작 — 걷는 장비만 실제로 걷고, 드론은 대본이 칠한다 (260927 셋째 지시) ─────────────
// 가짜 브로커 둘(pi7 · pi3)에 Go1 과 드론이 자기를 밝힌 상태로 판을 끝까지 돌린다. 로봇 응답은 `send` 를 가로채 만든다.
{
  const scenario = await load('src', 'data', 'scenario.ts');
  const { startSlotMove, canWalk } = await load('src', 'physical', 'slotMove.ts');
  const { robotClients } = await load('src', 'physical', 'robotClient.ts');
  const { noteDeviceReport } = await load('src', 'physical', 'deviceIdentity.ts');
  const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
  const { registerConnectionDefault } = await load('src', 'shared', 'connections.ts');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const original = PhysicalClient.prototype.send;

  async function run(rejectAt) {
    const sent = [];
    let n = 0;
    PhysicalClient.prototype.send = function send(action, parameters) {
      n += 1;
      const commandId = `cmd-${n}`;
      const order = n;
      sent.push({ to: this.address(), action, parameters });
      const emit = (message) => { for (const listener of this.listeners) listener(message); };
      setTimeout(() => {
        if (action === 'abort') return;
        if (order === rejectAt) { emit({ kind: 'acceptance', commandId, accepted: false, code: 'UNIMPLEMENTED', message: 'no' }); return; }
        emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null });
        setTimeout(() => emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: {}, code: null, message: null }), 150);
      }, 10);
      return { sent: true, commandId };
    };
    registerConnectionDefault('physical', 'ws', ['ws://pi7.test:9001', 'ws://pi3.test:9001'].join('\n'));
    const [go1, drone] = robotClients();
    noteDeviceReport('go1-001', 'robot', {}, go1.address());
    noteDeviceReport('x500-001', 'drone', {}, drone.address());
    startSlotMove();
    scenario.proposeMission({ origin: 'script', missionId: ID, title: script.title, keywords: [], planId: null, world: 'registry', target: '문' });
    slots.holdSlotsFor(ID);
    slots.dropOnSlots(['device-1'], 'go1-001');
    slots.dropOnSlots(['device-2'], 'x500-001');
    scenario.acceptProposal('local');
    const beforeStart = sent.length;
    scenario.getMissionState().current.params.play_speed = 20;   // 1배속이면 56초 — 판의 규칙은 그대로다
    scenario.startLocalRun();
    for (let i = 0; i < 80 && scenario.localRunPhase() === 'running'; i += 1) await sleep(200);
    const trace = scenario.traceEvents();
    PhysicalClient.prototype.send = original;
    return { sent, beforeStart, trace, phase: scenario.localRunPhase(), canWalk: [canWalk('go1-001'), canWalk('x500-001')] };
  }

  const ok = await run(null);
  if (JSON.stringify(ok.canWalk) !== '[true,false]') failures.push(`걸을 수 있는 장비 판정이 ${ok.canWalk} — Go1 은 걷고 드론은 못 걸어야 한다`);
  if (ok.beforeStart !== 0) failures.push(`승인만으로 로봇에 명령이 ${ok.beforeStart}건 나갔다 — 「임무 시작」 전에는 0건이어야 한다`);
  if (ok.sent.some((s) => !s.to.includes('pi7'))) failures.push('Go1 브로커(pi7) 밖으로 명령이 나갔다 — 드론에는 이동 명령이 없다');
  const actions = ok.sent.map((s) => `${s.action}:${JSON.stringify(s.parameters)}`);
  const plan = script.params.virtual_map.devices[0];
  if (ok.sent.length === 0 || ok.sent.some((s) => !['turn', 'move_forward'].includes(s.action))) failures.push(`경로 걸음이 turn · move_forward 가 아니다 — ${actions.join(' | ')}`);
  const walked = ok.sent.filter((s) => s.action === 'move_forward').reduce((sum, s) => sum + s.parameters.distance_m, 0);
  const planned = plan.path.slice(1).reduce((sum, p, i) => sum + Math.hypot(p[0] - plan.path[i][0], p[1] - plan.path[i][1]), 0);
  if (Math.abs(walked - planned) > 0.05) failures.push(`낸 직진 합 ${walked.toFixed(2)}m 가 가상 맵 경로 ${planned.toFixed(2)}m 와 다르다`);
  const at = (id, status) => ok.trace.find((e) => e.nodeId === id && e.status === status) ?? null;
  const e3 = at('T-E3', 'done');
  const e5 = at('T-E5', 'running');
  if (e3?.producedBy !== 'robot') failures.push('「첫 번째 장치 이동 완료 확인」을 로봇 응답이 아니라 대본이 칠했다');
  if (at('T-E4', 'done')?.producedBy === 'robot') failures.push('드론의 이동 완료를 로봇이 칠했다 — 드론은 대본이어야 한다');
  if (e3 === null || e5 === null || e5.atSec < e3.atSec || ok.trace.indexOf(e5) < ok.trace.indexOf(e3)) failures.push('「임무 완료」가 Go1 도착보다 먼저 칠해졌다');
  if (ok.phase !== 'done') failures.push(`판이 끝까지 안 갔다 — ${ok.phase}`);

  const rejected = await run(2);
  const failed = rejected.trace.find((e) => e.status === 'failed');
  if (failed?.nodeId !== 'T-E3' || failed.producedBy !== 'robot') failures.push('로봇이 걸음을 거절했는데 이동 완료 확인이 실패로 안 칠해졌다');
  if (rejected.trace.some((e) => e.nodeId === 'T-E5' && e.status !== 'pending')) failures.push('로봇이 못 갔는데 「임무 완료」가 진행됐다');
  if (rejected.phase !== 'stopped') failures.push(`로봇이 못 갔는데 판이 안 섰다 — ${rejected.phase}`);
  if (rejected.sent.length !== 2) failures.push(`거절 뒤에도 걸음이 나갔다 — ${rejected.sent.length}건`);
  controls.push('로봇이 둘째 걸음을 거절한 판');
}

// ── 결과 ─────────────────────────────────────────────────────────────────────
if (failures.length) {
  console.error(`❌ verify:script-two-devices\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 문장 5개가 이 편 하나에만 · 시연 문장은 여전히 시연 편 · @ 는 발화에서만 채우고 못 자르면 빈칸 그대로');
console.log('✅ 마일스톤 다섯 · 연결 확인 넷씩 · 경로 탐지와 장치 이동의 같은 일은 같은 부모 · 같은 시각에 나란히 → 합류');
console.log('✅ 일반 모드(시나리오 띠 없음) · 화면이 모는 판 · 로봇 관문 안 엶 · cast 없이 자리 둘 · 한 장비 한 자리(맞바꿈)');
console.log('✅ 가상 맵 · 카메라 · 객체 탐지 로그는 이 편 팔레트에만 · 맵 종류는 연결 관리가 가른다');
console.log('✅ Go1 실동작 — 시작 전 0건 · pi7 에만 경로 걸음(직진 합 = 경로 길이) · 도착은 로봇이, 드론은 대본이 칠한다 · 임무 완료는 도착 뒤 · 거절이면 실패로 서고 멈춘다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
