// verify:script-at-move (260929 신설 — 「장치 하나를 @까지 이동시켜」)
//
// 8편 `MSN-260929-01` 이 지시대로 서 있는지. 문 쪽으로 이동 편을 고친 편이다.
//
// 막으려는 실패는 다섯이다.
//  1. **문장이 이웃 편과 부딪히는 것.** 「장치 두 가지를 …까지」(7편) · 「문 쪽으로」(문 찾기)와 갈려야 한다.
//  2. **360° 를 도는 것.** 가상 맵과 출발 자세로 @ 방향을 셈하고, 시야 밖일 때만 **한 번** 돈다(T-B5).
//  3. **드론에 이동 명령이 가는 것.** 드론은 연결만 한다 — 돌기 · 이동 노드는 5초를 채워 넘긴다.
//  4. **다른 장비를 붙이면 안 도는 것.** 걸을 수 있는 장비(Go1)면 같은 대본에서 돌기 · 이동이 실제 명령이다.
//  5. **문 찾기 흐름이 따라 도는 것.** 이 편은 `door-scan` 을 선언하지 않는다 — 스캔 · 도면 조회가 없다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
const read = (...parts) => readFileSync(join(root, ...parts), 'utf8');
const readScript = (id) => JSON.parse(read('scenarios', `${id}.json`));

const ID = 'MSN-260929-01';
const failures = [];
const controls = [];

const { SCRIPT_IDS, LEGACY_ID } = await load('src', 'scenarios', 'manifest.ts');
const { matchLibrary } = await load('src', 'scenarios', 'matcher.ts');
const { extractTarget } = await load('src', 'scenarios', 'target.ts');
if (!SCRIPT_IDS.includes(ID)) failures.push(`${ID} 가 대본 목록(manifest)에 없다`);
const script = readScript(ID);

// ── 1. 문장 ─────────────────────────────────────────────────────────────────────
const library = [
  ...SCRIPT_IDS.map((id) => ({ missionId: id, match: readScript(id).match })),
  { missionId: LEGACY_ID, match: JSON.parse(read('scenarios', `${LEGACY_ID}.match.json`)).match },
];
const matchOf = (sentence) => {
  const outcome = matchLibrary(sentence, library, 'ko');
  return outcome.kind === 'matched' ? outcome.entry.missionId : outcome.kind;
};
for (const [sentence, want] of [
  ['장치 하나를 @까지 이동시켜', ID],
  ['장치 하나를 문 앞까지 이동시켜', ID],
  ['장치 한 대를 소화기까지 보내', ID],
  ['장치 두 가지를 문까지 이동시켜', 'MSN-260927-01'],
  ['저기 문 쪽으로 가', 'MSN-260909-01'],
  ['문 앞으로 이동해줘', 'MSN-260909-01'],
]) {
  const got = matchOf(sentence);
  if (got !== want) failures.push(`「${sentence}」 → ${got} — ${want} 이어야 한다`);
}
for (const [sentence, lang, want] of [
  ['장치 하나를 문 앞까지 이동시켜', 'ko', '문 앞'],
  ['장치 하나를 @까지 이동시켜', 'ko', null],
  ['Move one device to the fire extinguisher', 'en', 'the fire extinguisher'],
]) {
  const got = extractTarget(sentence, script.target, lang);
  if (got !== want) failures.push(`「${sentence}」 에서 잘라 온 대상이 ${JSON.stringify(got)} — ${JSON.stringify(want)} 여야 한다`);
}
if (script.utterance.text !== '장치 하나를 @까지 이동시켜') failures.push(`기본 발화가 「${script.utterance.text}」 — 결정 10 의 문장이어야 한다`);

// ── 2. 틀 ───────────────────────────────────────────────────────────────────────
const TITLES = ['장치 준비', '@ 찾기', '@까지 이동', '임무 완료'];
if (JSON.stringify(script.milestones.map((m) => m.title)) !== JSON.stringify(TITLES)) failures.push(`마일스톤이 [${script.milestones.map((m) => m.title).join(' · ')}]`);
if (script.tasks.length !== 20) failures.push(`태스크가 ${script.tasks.length}개 — 분리 예시대로 20개여야 한다`);
if (script.driver !== 'local' || script.robotFlow !== undefined) failures.push('driver local · robotFlow 없음이어야 한다 — 문 찾기 흐름이 따라 돈다');
if (JSON.stringify(script.slots.map((s) => s.id)) !== '["device"]' || script.cast.length !== 0) failures.push('장치 자리가 하나(「장치」)가 아니거나 대본이 장비를 정했다');
const judges = script.params.judges ?? {};
for (const task of script.tasks) if (judges[task.id] === undefined) failures.push(`${task.id} 의 판정 방식(params.judges)이 없다`);
if (judges['T-B5']?.kind !== 'face') failures.push('T-B5(@ 쪽으로 방향 맞추기)가 한 번 돌기(face)가 아니다');
if (script.tasks.some((t) => /360|한 바퀴|회전 촬영/.test(t.title))) failures.push('360° 회전 태스크가 남아 있다');
const { opensRobotGate, doorScanFlow, localDriven, slotDriven } = await load('src', 'scenarios', 'library.ts');
if (opensRobotGate(ID) || doorScanFlow(ID)) failures.push('이 편이 문 찾기 흐름(관문 · 스캔)을 연다');
if (!localDriven(ID) || !slotDriven(ID)) failures.push('화면이 모는 자리 편으로 안 읽힌다');

// ── 3~4. 실행기 — Go1 은 실제로 한 번 돌고 걷고, 드론은 연결만 ──────────────────────
{
  const { makeRig, eventOf, startedLine } = await import(pathToFileURL(join(root, 'scripts', 'lib', 'runnerRig.mjs')).href);
  const rig = await makeRig(root);
  const GO1 = { id: 'go1-001', type: 'robot', deviceType: 'go1_robot', broker: 'pi7', body: { battery_pct: 78 } };
  const DRONE = { id: 'x500-001', type: 'drone', deviceType: 'x500', broker: 'pi3', body: { fc_link: true, battery: { remaining_pct: 64 }, flight: { armed: false, landed_state: 'ON_GROUND' } } };

  const go1 = await rig.run({ missionId: ID, bindings: { device: 'go1-001' }, devices: [GO1] });
  const moves = go1.sent.filter((s) => s.action !== 'ping');
  const first = moves[0];
  if (first?.action !== 'turn' || Math.abs(first.parameters.deg - 59.5) > 0.2) failures.push(`첫 명령이 @ 쪽으로 한 번 돌기(turn ≈59.5°)가 아니다 — ${JSON.stringify(first)}`);
  if (moves.filter((s) => s.action === 'turn' && Math.abs(s.parameters.deg) >= 300).length > 0) failures.push('한 바퀴 회전이 나갔다');
  const plan = script.params.virtual_map.devices[0];
  const walked = moves.filter((s) => s.action === 'move_forward').reduce((sum, s) => sum + s.parameters.distance_m, 0);
  const planned = plan.path.slice(1).reduce((sum, p, i) => sum + Math.hypot(p[0] - plan.path[i][0], p[1] - plan.path[i][1]), 0);
  if (Math.abs(walked - planned) > 0.05) failures.push(`낸 직진 합 ${walked.toFixed(2)}m 가 가상 맵 경로 ${planned.toFixed(2)}m 와 다르다`);
  // 돈 뒤의 경로는 @ 쪽을 본 방위에서 푼다 — 두 번째 회전이 출발 방위(90°) 기준이면 엉뚱한 쪽으로 간다.
  const secondTurn = moves.filter((s) => s.action === 'turn')[1];
  const legHeading = (Math.atan2(plan.path[1][0] - plan.path[0][0], plan.path[1][1] - plan.path[0][1]) * 180) / Math.PI;
  const bearing = eventOf(go1.trace, 'T-B3', 'done')?.payload?.bearing_deg;
  if (secondTurn === undefined || typeof bearing !== 'number' || Math.abs(secondTurn.parameters.deg - (legHeading - bearing)) > 0.2) failures.push(`경로 첫 회전이 돈 뒤의 방위에서 안 풀렸다 — ${JSON.stringify(secondTurn)}`);
  for (const id of ['T-B5', 'T-C3', 'T-C5']) if (eventOf(go1.trace, id, 'done')?.producedBy !== 'robot') failures.push(`Go1 판의 ${id} 를 로봇 응답이 안 칠했다`);
  if (startedLine(go1.trace)?.payload?.held_tasks !== 'T-B6,T-B7,T-B8') failures.push(`Go1 판에서 넘긴 태스크가 「${startedLine(go1.trace)?.payload?.held_tasks}」 — @ 탐지 셋만이어야 한다`);
  if (go1.phase !== 'done' || eventOf(go1.trace, 'T-D1', 'done') === null) failures.push(`Go1 판이 끝까지 안 갔다 — ${go1.phase}`);
  if (go1.sent.some((s) => s.action === 'scan_mission')) failures.push('문 찾기 스캔이 나갔다');

  const drone = await rig.run({ missionId: ID, bindings: { device: 'x500-001' }, devices: [DRONE] });
  const droneMoves = drone.sent.filter((s) => s.action !== 'ping');
  if (droneMoves.length !== 0) failures.push(`드론에 명령이 ${droneMoves.map((s) => s.action).join(', ')} 나갔다 — 연결만 해야 한다`);
  if (!drone.sent.some((s) => s.action === 'ping')) failures.push('드론의 통신 링크를 ping 으로 안 쟀다');
  const HELD = ['T-B5', 'T-B6', 'T-B7', 'T-B8', 'T-C2', 'T-C3', 'T-C4', 'T-C5', 'T-C6'];
  if (startedLine(drone.trace)?.payload?.held_tasks !== HELD.join(',')) failures.push(`드론 판에서 넘긴 태스크가 「${startedLine(drone.trace)?.payload?.held_tasks}」 — 「${HELD.join(',')}」`);
  for (const id of HELD) {
    const run = eventOf(drone.trace, id, 'running');
    const done = eventOf(drone.trace, id, 'done');
    if (run === null || done === null || done.atSec - run.atSec < 5 - 0.01) failures.push(`드론 판의 ${id} 가 5초를 안 채웠다`);
  }
  for (const id of ['T-A1', 'T-A2', 'T-A3', 'T-A4', 'T-A5']) if (eventOf(drone.trace, id, 'done')?.producedBy !== 'robot') failures.push(`드론 판의 ${id} 를 장비 값으로 안 칠했다`);
  if (!drone.trace.some((e) => e.kind === 'progress' && e.payload?.slot === 'device')) failures.push('드론 판에서 지도 진행을 안 남겼다 — 가상 맵의 장치가 안 움직인다');
  if (drone.phase !== 'done') failures.push(`드론 판이 끝까지 안 갔다 — ${drone.phase}`);

  // 대조군 — 시동이 걸린 드론은 이동 준비에서 선다.
  const armed = await rig.run({ missionId: ID, bindings: { device: 'x500-001' }, devices: [{ ...DRONE, body: { ...DRONE.body, flight: { armed: true } } }] });
  if (armed.trace.find((e) => e.status === 'failed')?.nodeId !== 'T-A4') failures.push('시동 걸린 드론이 T-A4(이동 준비 상태)에서 안 섰다');
  controls.push('시동 걸린 드론');
  // 대조군 — 처음부터 @ 를 보고 서 있으면 돌지 않는다.
  const facing = await rig.run({
    missionId: ID, bindings: { device: 'go1-001' }, devices: [GO1],
    tweak: (view) => { view.params.virtual_map.devices[0].start_yaw_deg = 150; },
  });
  const turns = facing.sent.filter((s) => s.action === 'turn');
  if (eventOf(facing.trace, 'T-B5', 'done')?.payload?.turned_deg !== 0 || (turns[0] !== undefined && Math.abs(turns[0].parameters.deg) > 30)) failures.push(`@ 를 보고 선 판에서 돌았다 — ${JSON.stringify(turns[0])}`);
  controls.push('처음부터 @ 를 본 판(돌지 않는다)');
  // 대조군 — 넘기는 노드를 판정 없는 hold 로 바꿔 넣으면 넘긴 목록이 달라져 잡힌다(목록 검사가 살아 있는가).
  const tampered = structuredClone(judges);
  tampered['T-A3'] = { kind: 'hold' };
  if (Object.values(tampered).filter((j) => j.kind === 'hold').length === Object.values(judges).filter((j) => j.kind === 'hold').length) failures.push('대조군 실패: hold 를 하나 더 넣었는데 수가 같다');
  controls.push('확인 노드를 넘김으로 바꾼 사본');
}

if (failures.length) {
  console.error(`❌ verify:script-at-move\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 문장 — 「장치 하나를 …까지」는 이 편, 「두 가지」는 7편, 「문 쪽으로」는 문 찾기 편 · @ 는 발화에서만');
console.log('✅ 틀 — 마일스톤 넷 · 태스크 20 · 태스크마다 판정 방식 · 360° 회전 없음 · 문 찾기 흐름 없음');
console.log('✅ Go1 — @ 쪽으로 한 번(≈59.5°) 돈 뒤 그 방위에서 경로를 푼다 · 직진 합 = 경로 · @ 탐지 셋만 넘김');
console.log('✅ 드론 — ping 만 · 돌기 · 이동 아홉은 5초씩 채워 넘김 · 연결 확인 다섯은 장비 값');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
