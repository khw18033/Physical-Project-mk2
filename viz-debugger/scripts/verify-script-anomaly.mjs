// verify:script-anomaly (260929 신설 — 「장치 두 가지로 이상 탐지를 진행해」)
//
// 9편 `MSN-260929-02` 은 장치 두 대 편(7편)의 복사본이다. 지시대로 바뀌었는지 본다.
//
//  1. 문장이 이 편에만 맞는다 — 「장치 두 가지를 …까지」(7편)와 갈린다.
//  2. 틀 — 연결 확인 둘은 유지(첫 번째 = 드론, 두 번째 = Go1) · @ 위치 추정이 없다 · 가상 맵 모니터링
//     (모니터링 진행 → 이상 현상 감지) · 경로 탐지는 첫 번째 장치만 · 장치 이동은 한 줄로
//     (첫 번째 장치 이동 → 두 번째 장치 경로 추정 → 두 번째 장치 이동 → 임무 완료).
//  3. 모니터링 진행은 12초를 채운 뒤 이상 현상 감지로 넘어간다.
//  4. 드론은 명령 없이 「왼쪽 45° 회전 → 2 m 전진」 경로 결과만 · Go1 은 드론 도착점까지 실제로 걷는다 —
//     드론 이동이 끝난 **뒤에** 걷는다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
const read = (...parts) => readFileSync(join(root, ...parts), 'utf8');
const readScript = (id) => JSON.parse(read('scenarios', `${id}.json`));

const ID = 'MSN-260929-02';
const failures = [];
const controls = [];

const { SCRIPT_IDS, LEGACY_ID } = await load('src', 'scenarios', 'manifest.ts');
const { matchLibrary } = await load('src', 'scenarios', 'matcher.ts');
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
  ['장치 두 가지로 이상 탐지를 진행해', ID],
  ['장치 두 대로 이상 감지 시작해', ID],
  ['장치 두 가지를 문까지 이동시켜', 'MSN-260927-01'],
  ['장치 하나를 문까지 이동시켜', 'MSN-260929-01'],
  ['저기 문 쪽으로 가', 'MSN-260909-01'],
]) {
  const got = matchOf(sentence);
  if (got !== want) failures.push(`「${sentence}」 → ${got} — ${want} 이어야 한다`);
}

// ── 2. 틀 ───────────────────────────────────────────────────────────────────────
const TITLES = ['첫 번째 장치 연결 확인', '두 번째 장치 연결 확인', '가상 맵 모니터링', '경로 탐지', '장치 이동'];
if (JSON.stringify(script.milestones.map((m) => m.title)) !== JSON.stringify(TITLES)) failures.push(`마일스톤이 [${script.milestones.map((m) => m.title).join(' · ')}]`);
if (script.tasks.some((t) => t.title.includes('@'))) failures.push('@ 위치 추정이 남아 있다');
const titlesOf = (ms) => script.tasks.filter((t) => t.milestone === ms).map((t) => t.title);
if (JSON.stringify(titlesOf('MS-C')) !== '["모니터링 진행","이상 현상 감지"]') failures.push(`가상 맵 모니터링의 태스크가 [${titlesOf('MS-C')}]`);
if (JSON.stringify(titlesOf('MS-D')) !== '["첫 번째 장치 경로 탐지"]') failures.push(`경로 탐지가 첫 번째 장치만이 아니다 — [${titlesOf('MS-D')}]`);
if (JSON.stringify(titlesOf('MS-E')) !== '["첫 번째 장치 이동","두 번째 장치 경로 추정","두 번째 장치 이동","임무 완료"]') failures.push(`장치 이동의 차례가 [${titlesOf('MS-E')}]`);
for (let i = 1; i < script.tasks.length; i += 1) {
  if (JSON.stringify(script.tasks[i].deps) !== JSON.stringify([script.tasks[i - 1].id])) failures.push(`${script.tasks[i].id} 가 앞 태스크 하나만 기다리지 않는다 — 차례대로 가야 한다`);
}
if (script.params.judges['T-C1']?.sec !== 12) failures.push('모니터링 진행이 12초 유지가 아니다');
// 260929 — 가상 맵 모니터링은 장치를 받지 않고 3D 가상환경 주소를 본다(「미배정」이 뜨면 안 된다).
const msC = script.milestones.find((m) => m.id === 'MS-C');
if (msC?.feed !== 'virtual-3d' || (msC.slots ?? []).length !== 0) failures.push('가상 맵 모니터링이 3D 가상환경을 보는 마일스톤이 아니다');
const mainSource = read('src', 'main.tsx');
if (!/item\.feed === 'virtual-3d'[\s\S]{0,120}connectionAddress\('virtual-3d', 'base'\)/.test(mainSource)) failures.push('마일스톤 배정 줄이 3D 가상환경 주소를 안 적는다 — 「미배정」이 뜬다');
if (!/if \(item\.feed === undefined\) onAssign/.test(mainSource)) failures.push('3D 가상환경 마일스톤에 카드를 놓으면 장치가 앉는다');
const { opensRobotGate, localDriven, slotDriven } = await load('src', 'scenarios', 'library.ts');
if (opensRobotGate(ID) || !localDriven(ID) || !slotDriven(ID)) failures.push('화면이 모는 자리 편이 아니거나 문 찾기 관문을 연다');

// ── 3~4. 실행 ─────────────────────────────────────────────────────────────────
{
  const { makeRig, eventOf, startedLine } = await import(pathToFileURL(join(root, 'scripts', 'lib', 'runnerRig.mjs')).href);
  const rig = await makeRig(root);
  const DRONE = { id: 'x500-001', type: 'drone', deviceType: 'x500', broker: 'pi3', body: { fc_link: true, battery: { remaining_pct: 64 } } };
  const GO1 = { id: 'go1-001', type: 'robot', deviceType: 'go1_robot', broker: 'pi7', body: { battery_pct: 78 } };
  // 260929 — 첫 번째 장치 이동은 사람이 승인해야 끝난다. 시험대가 승인 대기를 보면 먼저 「승인 전」을 적고 승인한다.
  const runner = await load('src', 'physical', 'taskRunner.ts');
  let beforeApproval = null;
  const offGate = runner.subscribeMoveGate(() => {
    const gate = runner.moveGate();
    if (gate === null || beforeApproval !== null) return;
    setTimeout(() => {
      beforeApproval = { gate, e1: rig.scenario.traceEvents().filter((e) => e.nodeId === 'T-E1').map((e) => e.status), e2: rig.scenario.traceEvents().some((e) => e.nodeId === 'T-E2' && e.status !== 'pending') };
      runner.approveMoveGate();
    }, 300);
  });
  const ok = await rig.run({ missionId: ID, bindings: { 'device-1': 'x500-001', 'device-2': 'go1-001' }, devices: [DRONE, GO1] });
  offGate();
  if (beforeApproval === null) failures.push('첫 번째 장치 이동이 승인을 기다리지 않았다');
  else {
    if (beforeApproval.gate.taskId !== 'T-E1' || beforeApproval.gate.route !== '2.00 m 전진' || beforeApproval.gate.deviceId !== 'go1-001') failures.push(`승인 대기가 Go1 경로를 안 보인다 — ${JSON.stringify(beforeApproval.gate)}`);
    if (beforeApproval.e1.includes('done') || !beforeApproval.e1.includes('running')) failures.push('승인 전에 첫 번째 장치 이동이 끝났다 — 진행 중에 멈춰 있어야 한다');
    if (beforeApproval.e2) failures.push('승인 전에 두 번째 장치 경로 추정이 시작됐다');
  }
  if (!ok.trace.some((e) => e.kind === 'move_gate_approved' && e.producedBy === 'human')) failures.push('승인이 판 기록에 사람 조작으로 안 남았다');
  if (eventOf(ok.trace, 'T-E1', 'done')?.payload?.approved_by !== 'human') failures.push('첫 번째 장치 이동 완료에 승인 근거(approved_by)가 없다');
  if (ok.phase !== 'done') failures.push(`판이 끝까지 안 갔다 — ${ok.phase}`);
  const c1 = [eventOf(ok.trace, 'T-C1', 'running'), eventOf(ok.trace, 'T-C1', 'done')];
  if (c1.includes(null) || c1[1].atSec - c1[0].atSec < 12 - 0.01) failures.push(`모니터링 진행이 12초를 안 채웠다 (${c1[0]?.atSec} → ${c1[1]?.atSec})`);
  if (c1[1]?.payload?.hold_s !== 12) failures.push('모니터링 진행 근거값에 hold_s: 12 가 없다');
  // 260929 — 첫 번째 장치 연결 확인은 드론(FC)이 안 붙어도 0.5초 뒤 통과한다(이 편에서만). 두 번째 장치는 그대로 실제 판정.
  const noFc = await rig.run({
    missionId: ID, bindings: { 'device-1': 'x500-001', 'device-2': 'go1-001' },
    devices: [{ ...DRONE, body: { fc_link: false, link: 'degraded', battery: null } }, GO1], maxTicks: 40,
    // 1배속으로 본다 — 시험대의 20배속이면 한 걸음이 4초라 0.5초를 볼 수 없다.
    tweak: (view) => { view.params.play_speed = 1; },
  });
  for (const id of ['T-A1', 'T-A2', 'T-A3', 'T-A4']) {
    const run = eventOf(noFc.trace, id, 'running');
    const done = eventOf(noFc.trace, id, 'done');
    if (run === null || done === null || done.atSec - run.atSec > 0.8) failures.push(`드론 FC 가 없는데 ${id} 가 0.5초 뒤 통과하지 않았다 (${run?.atSec} → ${done?.atSec})`);
  }
  if (noFc.trace.some((e) => e.status === 'failed' && e.nodeId.startsWith('T-A'))) failures.push('첫 번째 장치 연결 확인이 실패로 칠해졌다');
  rig.scenario.stopLocalRun();
  const lowGo1 = await rig.run({
    missionId: ID, bindings: { 'device-1': 'x500-001', 'device-2': 'go1-001' },
    devices: [DRONE, { ...GO1, body: { battery_pct: 10 } }], maxTicks: 60,
  });
  if (lowGo1.trace.find((e) => e.status === 'failed')?.nodeId !== 'T-B3') failures.push('두 번째 장치(Go1) 배터리가 부족한데 T-B3 이 실패로 안 섰다 — 유예는 첫 번째 장치에만');
  controls.push('Go1 배터리 부족(두 번째 장치는 실제 판정)');
  // 다른 편에는 유예가 없다.
  for (const other of ['MSN-260927-01', 'MSN-260929-01']) {
    if (Object.values(readScript(other).params.judges ?? {}).some((j) => j.soft !== undefined)) failures.push(`${other} 에 유예(soft)가 있다 — 이상 탐지 편에서만`);
  }
  if (startedLine(ok.trace)?.payload?.held_tasks !== 'T-A1,T-A2,T-A3,T-A4,T-C1,T-C2,T-E1') failures.push(`넘긴 태스크가 「${startedLine(ok.trace)?.payload?.held_tasks}」 — 모니터링 · 감지 · 드론 이동이어야 한다`);
  if (eventOf(ok.trace, 'T-D1', 'done')?.payload?.route !== '왼쪽 45° 회전 → 2.00 m 전진') failures.push(`드론 경로 결과가 「${eventOf(ok.trace, 'T-D1', 'done')?.payload?.route}」`);
  // 260929 — Go1 은 회전 없이 「2 m 전진」만으로 드론 자리까지 간다(실제 명령).
  if (eventOf(ok.trace, 'T-E2', 'done')?.payload?.route !== '2.00 m 전진') failures.push(`Go1 경로 결과가 「${eventOf(ok.trace, 'T-E2', 'done')?.payload?.route}」`);
  const go1Steps = ok.sent.filter((s) => s.action !== 'ping');
  if (go1Steps.length !== 1 || go1Steps[0].action !== 'move_forward' || Math.abs(go1Steps[0].parameters.distance_m - 2) > 0.01) failures.push(`Go1 명령이 회전 없는 2 m 전진이 아니다 — ${JSON.stringify(go1Steps)}`);
  const moves = ok.sent.filter((s) => s.action !== 'ping');
  if (moves.some((s) => !s.to.includes('pi7'))) failures.push('드론(pi3)에 이동 명령이 나갔다');
  const walked = moves.filter((s) => s.action === 'move_forward').reduce((sum, s) => sum + s.parameters.distance_m, 0);
  const go1Path = script.params.virtual_map.devices[1].path;
  const drone = script.params.virtual_map.devices[0].path;
  if (JSON.stringify(go1Path.at(-1)) !== JSON.stringify(drone.at(-1))) failures.push('Go1 경로 끝이 드론 도착점이 아니다');
  if (Math.abs(walked - Math.hypot(go1Path[1][0] - go1Path[0][0], go1Path[1][1] - go1Path[0][1])) > 0.02) failures.push(`Go1 직진 합 ${walked.toFixed(2)}m 가 드론 자리까지 거리와 다르다`);
  const e1 = eventOf(ok.trace, 'T-E1', 'done');
  const e3 = eventOf(ok.trace, 'T-E3', 'running');
  if (e1 === null || e3 === null || ok.trace.indexOf(e3) < ok.trace.indexOf(e1)) failures.push('Go1 이 드론 이동이 끝나기 전에 걷기 시작했다');
  if (eventOf(ok.trace, 'T-E3', 'done')?.producedBy !== 'robot') failures.push('두 번째 장치 이동을 Go1 응답이 안 칠했다');
  // 대조군 — 장치를 바꿔 앉히면(Go1 이 첫 번째) Go1 이 먼저 걷는다: 걸을지 말지는 기종이 아니라 앉은 장비가 정한다.
  const offSwap = runner.subscribeMoveGate(() => { if (runner.moveGate() !== null) setTimeout(() => runner.approveMoveGate(), 50); });
  const swapped = await rig.run({ missionId: ID, bindings: { 'device-1': 'go1-001', 'device-2': 'x500-001' }, devices: [DRONE, GO1] });
  offSwap();
  const swappedHeld = startedLine(swapped.trace)?.payload?.held_tasks;
  if (swappedHeld !== 'T-A1,T-A2,T-A3,T-A4,T-C1,T-C2,T-E3') failures.push(`장치를 바꿔 앉혔는데 넘긴 태스크가 「${swappedHeld}」`);
  // 승인 없이 두면 판이 거기서 기다린다 — 끝나지 않는다.
  const waiting = await rig.run({ missionId: ID, bindings: { 'device-1': 'x500-001', 'device-2': 'go1-001' }, devices: [DRONE, GO1], maxTicks: 120 });
  if (waiting.phase === 'done' || waiting.sent.some((s) => s.action !== 'ping')) failures.push('승인하지 않았는데 판이 끝났거나 Go1 이 움직였다');
  controls.push('승인하지 않은 판(기다린다)');
  // 기다리는 판을 세운다 — 안 세우면 판의 타이머가 살아 있어 검사가 끝나지 않는다.
  rig.scenario.stopLocalRun();
  controls.push('장치를 바꿔 앉힌 판');
}

if (failures.length) {
  console.error(`❌ verify:script-anomaly\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 문장 — 「장치 두 가지로 이상 탐지」는 이 편 · 「…까지 이동」 편들과 갈림');
console.log('✅ 틀 — 연결 확인 둘 · @ 위치 추정 없음 · 가상 맵 모니터링(진행 → 감지) · 첫 번째 장치만 경로 탐지 · 이동은 한 줄로');
console.log('✅ 실행 — 모니터링 12초 · 드론은 명령 없이 「왼쪽 45° → 2 m」 · 드론 이동은 승인 전까지 진행 중(Go1 경로를 보임) · 승인 뒤 Go1 이 드론 자리까지 실제로 걸음');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
process.exit(0);
