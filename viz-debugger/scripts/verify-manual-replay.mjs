// verify:manual-replay (261023 신설 — 사람 명령 액션 층 §3 · §4)
//
// **사람이 직접 몬 명령이 되감기를 따라가는가.**
//
// 액션 층에 들어왔으므로 접기(`foldActions`)를 지난다. 재생 머리를 과거로 옮기면 **그때까지 보낸 것만** 보여야
// 한다 — 사람 층의 점으로만 있을 때는 내용이 없어 되감아도 볼 것이 없었다.
//
// 보는 것.
//  ① 재생 머리 5 · 10 · 20 초에 한 건씩 낸 수동 명령이, 7 · 12 · 25 초로 되감으면 1 · 2 · 3 건 보인다
//     — 노드에 안 붙은 행을 장비로 고르는 자리(`nodelessActions`)와 화면이 읽는 자리(`actionsAt`) 둘 다
//  ② 답도 머리를 따른다 — 답이 온 시각보다 앞으로 되감으면 그 줄이 없다
//  ③ 타임라인의 사람 줄 — 같은 장비를 연달아 몬 명령은 구간 하나로, 누름은 점으로 남는다(`humanTimeline`)
//
// 대조군 — **재생 머리를 무시하는 사본**(접기에서 「시각을 넘으면 끊는다」를 지운 `actionTrace.ts`)이 잡혀야 한다.
// LF 로 정규화한 원본에서 만든다(`readSource`).
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeScratch } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const scenario = await load('src', 'data', 'scenario.ts');
const session = await load('src', 'physical', 'robotSession.ts');
const actionTrace = await load('src', 'data', 'actionTrace.ts');
const { recordHumanCommand } = await load('src', 'physical', 'humanCommands.ts');
const { humanTimeline, humanCount } = await load('src', 'data', 'humanTimeline.ts');

const failures = [];
const controls = [];
const MISSION = 'MSN-260909-01';
const DEVICE = 'go1-001';

// ── 판 하나 — 머리를 옮겨 가며 세 번 몬다 ───────────────────────────────────
session.resetRobotSession();
scenario.previewMission(MISSION);
const listeners = new Set();
const device = { onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); } };
const answer = (commandId) => { for (const cb of [...listeners]) cb({ kind: 'acceptance', commandId, accepted: true, code: null, message: null }); };

const at = [5, 10, 20];
for (const [index, sec] of at.entries()) {
  scenario.advanceRobotHead(MISSION, sec);
  recordHumanCommand(device, { commandId: `rp-${index}`, deviceId: DEVICE, action: 'teleop', parameters: { vx: 0.3, vy: 0, vyaw: 0, hold_ms: 500 } });
  // 답은 명령보다 1초 뒤에 온다.
  scenario.advanceRobotHead(MISSION, sec + 1);
  answer(`rp-${index}`);
}
// 다른 장비 하나 — 장비로 고르는 자리가 섞지 않는지 본다.
recordHumanCommand(device, { commandId: 'rp-other', deviceId: 'x500-001', action: 'sar_start', parameters: { passes: 1 } });
// 누름 하나 — 구간에 안 묶이고 점으로 남아야 한다.
scenario.recordHuman('approach_started', MISSION, { from: 'button' });
const trace = scenario.traceFor(scenario.currentMission());

const stamped = trace.filter((e) => e.kind === actionTrace.ACTION_KINDS.commanded && String(e.nodeId).startsWith('rp-') && e.nodeId !== 'rp-other').map((e) => e.atSec);
if (JSON.stringify(stamped) !== JSON.stringify(at)) failures.push(`수동 명령이 ${JSON.stringify(stamped)} 초에 적혔다 — 낸 그 시각(${JSON.stringify(at)})이어야 되감기가 자리를 찾는다 (검사가 헛돈다)`);

/** 판정 본체 — 원본과 사본의 접기가 같은 이 함수를 돈다. */
function judgeReplay(fold, nodeless) {
  const f = [];
  for (const [second, want] of [[7, 1], [12, 2], [25, 3], [2, 0]]) {
    const shown = nodeless(fold(second, trace), DEVICE);
    if (shown.length !== want) f.push(`${second}초로 되감았는데 수동 명령이 ${shown.length}건 보인다 — 그때까지 보낸 것은 ${want}건이다`);
  }
  // 답도 머리를 따른다 — 5초 명령의 답은 6초에 왔다.
  const before = nodeless(fold(5.5, trace), DEVICE)[0];
  const after = nodeless(fold(6.5, trace), DEVICE)[0];
  if (before === undefined || before.lines.length !== 0) f.push('답이 오기 전 시각(5.5초)에 답 줄이 보인다 — 미래가 과거에 그려진다');
  if (after === undefined || after.lines.length !== 1) f.push('답이 온 뒤 시각(6.5초)에 답 줄이 안 보인다');
  return f;
}

failures.push(...judgeReplay(actionTrace.foldActions, actionTrace.nodelessActions));
// 장비로 고르기 — 다른 장비는 안 섞인다.
if (actionTrace.nodelessActions(actionTrace.foldActions(1e9, trace), 'x500-001').length !== 1) failures.push('장비로 고르는 자리가 다른 장비의 명령을 섞거나 빠뜨린다');
// 화면이 읽는 자리도 같은 머리를 본다.
{
  const shown = actionTrace.nodelessActions(scenario.actionsAt(12), DEVICE);
  if (shown.length !== 2) failures.push(`화면이 읽는 actionsAt(12) 에 수동 명령이 ${shown.length}건 — 2건이어야 한다`);
}

// ── ③ 타임라인의 사람 줄 ────────────────────────────────────────────────────
{
  // 간격 2초 안의 몰기는 하나로 — 5·10·20 은 서로 멀어 셋이 따로다. 1초 간격으로 셋을 더 낸다.
  for (const [index, sec] of [30, 31, 32].entries()) {
    scenario.advanceRobotHead(MISSION, sec);
    recordHumanCommand(device, { commandId: `burst-${index}`, deviceId: DEVICE, action: 'teleop', parameters: { vx: 0.1, vy: 0, vyaw: 0, hold_ms: 500 } });
  }
  const line = humanTimeline(scenario.traceFor(scenario.currentMission()));
  const burst = line.spans.find((span) => span.device === DEVICE && span.count === 3);
  if (burst === undefined) failures.push('1초 간격으로 연달아 몬 수동 명령 셋이 구간 하나로 안 묶였다');
  else if (burst.start !== 30 || burst.end !== 32) failures.push(`몰기 구간이 ${burst.start}~${burst.end}초 — 30~32초여야 한다`);
  if (!line.points.some((e) => e.kind === 'approach_started')) failures.push('누름(approach_started)이 점으로 안 남았다 — 누름은 구간이 아니다');
  if (line.spans.some((span) => span.count < 2)) failures.push('한 건짜리를 구간으로 그렸다 — 구간이 아니다');
  const humanEvents = scenario.traceFor(scenario.currentMission()).filter((e) => e.producedBy === 'human').length;
  if (humanCount(line) !== humanEvents) failures.push(`묶은 뒤 건수가 ${humanCount(line)} — 사람이 만든 사건 ${humanEvents}건과 같아야 한다 (묶어도 세는 수는 그대로)`);
}

// ── 대조군 — 재생 머리를 무시하는 사본 ──────────────────────────────────────
{
  const scratch = makeScratch(join(root, 'src', 'data'), '.verify-mreplay-');
  try {
    const source = readSource(root, 'src', 'data', 'actionTrace.ts');
    // 접기의 「시각을 넘으면 끊는다」 한 줄을 지운다 — 머리가 어디 있든 열 전체를 접는다.
    const muted = source.replace('    if (event.atSec > second) break;\n    if (!ACTION_KIND_SET.has(event.kind)) continue;', '    if (!ACTION_KIND_SET.has(event.kind)) continue;');
    if (muted === source) failures.push('대조군을 만들지 못했다 — foldActions 의 시각 끊기 줄 (원본이 바뀌었나?)');
    else {
      const path = scratch.file('actionTrace.ts');
      writeFileSync(path, muted.replaceAll("from '../model/types.ts'", "from '../../model/types.ts'"), 'utf8');
      const mutant = await import(pathToFileURL(path).href);
      const hit = judgeReplay(mutant.foldActions, mutant.nodelessActions);
      if (hit.length === 0) failures.push('대조군 실패: 재생 머리를 무시하는 사본이 통과했다 — 이 검사는 무의미하다');
      else controls.push(`재생 머리를 무시하는 사본 (${hit.length}건)`);
    }
  } finally {
    scratch.cleanup();
  }
}

session.resetRobotSession();

if (failures.length) {
  console.error(`❌ verify:manual-replay\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 수동 명령이 되감기를 따라간다 — 7 · 12 · 25 초로 되감으면 1 · 2 · 3 건, 2초면 0건 · 답 줄도 온 시각부터');
console.log('✅ 장비로 고르면 그 장비 것만 · 화면이 읽는 actionsAt 도 같은 머리를 본다');
console.log('✅ 사람 줄 — 연달아 몬 명령은 구간 하나(30~32초 · 3건), 누름은 점 · 묶어도 건수는 그대로');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
