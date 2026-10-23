// verify:human-command-layer (261023 신설 — 사람 명령 액션 층 §1 · §4)
//
// **층은 「명령이냐」가 정하고, 주체는 「누가 냈느냐」가 정한다.**
//
// 앞 작업(261022)이 자동 명령을 액션 층으로 보냈지만 사람이 직접 낸 명령 셋(수동 제어 · SAR · 비행 제어)은
// 사람 층에 남았다. 그래서 사람이 몬 구간은 타임라인의 점뿐이었고, 무엇을 얼마나 보냈는지는 명령 표가 못 읽었다.
//
// 보는 것.
//  ① 세 명령이 **액션 층**에 `commanded` 로, 주체 `human` 으로, 받은 장비와 함께 들어간다 · 답이 같은 행에 붙는다
//  ② **노드에 안 붙는다** — `NO_NODE` · `attachedToNode` false · 어느 태스크를 열어도 안 보인다 (분모 밖)
//  ③ 사람 층에는 **안 들어간다** — 같은 명령이 두 층에 없다
//  ④ **누름은 사람 층 그대로** — 시작 · 재시작 · 접근 시작은 명령이 아니다. 버튼이 `recordHuman` 으로 적고,
//     액션 층으로 가는 길(`recordCommanded` · `recordHumanCommand`)을 부르지 않는다
//
// 대조군 넷 — 사람 층에 되돌린 사본 · 주체를 backend 로 적은 사본 · 노드에 붙인 사본 · 누름까지 액션 층으로 보낸 사본.
// 사본은 원본 옆 임시 폴더에 두고 상대 import 를 한 칸 늘려 같은 모듈 인스턴스를 쓴다.
// LF 로 정규화한 원본에서 만든다(`readSource`).
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeScratch } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';
import { humanCommandKit } from './lib/humanCommandRig.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const kit = await humanCommandKit(root);
const { load } = kit;
const { ACTION_KINDS, NO_NODE, actionsOfTask, attachedToNode, foldActions } = await load('src', 'data', 'actionTrace.ts');
const original = {
  md: await load('src', 'physical', 'manualDispatch.ts'),
  sar: await load('src', 'physical', 'sarCommands.ts'),
  flight: await load('src', 'physical', 'flightRunCommands.ts'),
};

const failures = [];
const controls = [];

/** 판정 본체 — 원본과 사본이 같은 이 함수를 돈다. */
function judgeRun({ added, issued, view }) {
  const f = [];
  if (issued.length < 4) f.push(`사람이 낸 명령이 ${issued.length}건 — 수동 둘 · SAR · 비행이 다 나가야 한다 (검사가 헛돈다)`);
  const folded = foldActions(Number.MAX_SAFE_INTEGER, added);
  for (const s of issued) {
    const rows = added.filter((e) => e.nodeId === s.commandId);
    const commanded = rows.filter((e) => e.kind === ACTION_KINDS.commanded);
    const who = `${s.action}(${s.deviceId})`;
    // ③ 사람 층에 같은 명령이 없다 — 옛 줄은 `kind` 가 명령 이름이고 `nodeId` 가 장비였다.
    if (added.some((e) => kit.isHumanLayer(e) && e.kind === s.action && e.nodeId === s.deviceId)) f.push(`${who} 가 사람 층에도 있다 — 명령은 액션 층이다`);
    if (commanded.length !== 1) { f.push(`${who} 가 액션 층에 ${commanded.length}줄 — 명령이라 한 줄로 들어가야 한다`); continue; }
    const c = commanded[0];
    if (c.producedBy !== 'human') f.push(`${who} 의 주체가 ${c.producedBy} 다 — 사람이 낸 명령이다`);
    if (c.payload?.taskId !== NO_NODE || attachedToNode({ taskId: String(c.payload?.taskId ?? '') })) f.push(`${who} 가 ${c.payload?.taskId} 노드에 붙었다 — 분모에 들어간다`);
    if (c.payload?.device !== s.deviceId) f.push(`${who} 의 장비가 ${c.payload?.device} 로 적혔다 — 노드가 없는 행을 가를 것이 장비뿐이다`);
    if (JSON.stringify(c.payload?.parameters) !== JSON.stringify(s.parameters)) f.push(`${who} 의 실린 값이 갈린다 — 기록 ${JSON.stringify(c.payload?.parameters)} · 나간 것 ${JSON.stringify(s.parameters)}`);
    if (!rows.some((e) => e.kind === ACTION_KINDS.answered && e.producedBy === 'robot')) f.push(`${who} 에 장비가 답했는데 행에 안 붙었다`);
    for (const task of view.tasks) {
      if (actionsOfTask(folded, task.id).some((a) => a.commandId === s.commandId)) f.push(`${task.id} 를 열면 ${who} 가 보인다 — 노드에 붙었다`);
    }
  }
  return f;
}

/** ④ 누름은 사람 층 — 버튼 소스가 `recordHuman` 으로 적고 액션 층 길을 안 부른다. */
function judgePresses(buttonSource) {
  const f = [];
  for (const kind of ['mission_started', 'mission_resumed', 'approach_started']) {
    if (!buttonSource.includes(`recordHuman('${kind}'`)) f.push(`버튼이 ${kind} 를 사람 층에 안 적는다`);
  }
  if (/recordCommanded\s*\(|recordHumanCommand\s*\(/.test(buttonSource)) f.push('버튼이 누름을 액션 층에 적는다 — 누름은 명령이 아니다');
  return f;
}

// ── 본 판 ────────────────────────────────────────────────────────────────────
const run = await kit.drive(original, 'hc');
failures.push(...judgeRun(run));
const buttons = readSource(root, 'src', 'physical', 'StopButton.tsx');
failures.push(...judgePresses(buttons));
{
  // 누름이 실제로 사람 층에 들어가는가 — 버튼이 부르는 그 함수로.
  const before = kit.column().filter(kit.isHumanLayer).length;
  kit.scenario.recordHuman('mission_started', kit.MISSION, { from: 'button' });
  const pressed = kit.column().filter(kit.isHumanLayer);
  if (pressed.length !== before + 1 || pressed.at(-1)?.kind !== 'mission_started' || pressed.at(-1)?.producedBy !== 'human') {
    failures.push('누름(mission_started)이 사람 층에 주체 human 으로 안 들어갔다');
  }
}

// ── 대조군 ──────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  else controls.push(name);
}
const deepen = (code) => code
  .replaceAll("from '../", "from '\u0000/")
  .replaceAll("from './", "from '../")
  .replaceAll("from '\u0000/", "from '../../");

{
  const scratch = makeScratch(join(root, 'src', 'physical'), '.verify-hcmd-');
  try {
    const write = async (name, code) => {
      const path = scratch.file(name);
      writeFileSync(path, code, 'utf8');
      return import(pathToFileURL(path).href);
    };
    const humanSource = deepen(readSource(root, 'src', 'physical', 'humanCommands.ts'));
    const mutants = [
      // ⓐ 사람 층에 되돌린 사본 — 셋 다 `actionLayer` 와 기록 줄을 뺀다. 261022 의 모양이다.
      ['사람 층에 되돌린 사본', async () => {
        const back = (rel) => deepen(readSource(root, 'src', 'physical', rel))
          .replace(/ {6,8}actionLayer: true,\n/, '')
          .replace(/\n\s*if \(outcome\.sent\) recordHumanCommand\([^\n]*\n/, '\n');
        return {
          md: await write('manualDispatch.ts', back('manualDispatch.ts')),
          sar: await write('sarCommands.ts', back('sarCommands.ts')),
          flight: await write('flightRunCommands.ts', back('flightRunCommands.ts')),
        };
      }],
      // ⓑ 주체를 backend 로 적은 사본 · ⓒ 노드에 붙인 사본 — 기록 자리 하나(`humanCommands.ts`)를 바꾸고 셋이 그것을 부른다.
      ['주체를 backend 로 적은 사본', async () => humanVia(await write('humanCommands-b.ts', humanSource.replace("issuedBy: 'human'", "issuedBy: 'mission'")), 'b')],
      ['노드에 붙인 사본 (T-A3)', async () => humanVia(await write('humanCommands-c.ts', humanSource.replace('taskId: NO_NODE, action', "taskId: 'T-A3', action")), 'c')],
    ];
    /** 세 명령 파일이 사본 기록 자리를 부르게 한다. */
    async function humanVia(_mod, tag) {
      const via = (rel) => deepen(readSource(root, 'src', 'physical', rel)).replace("from '../humanCommands.ts'", `from './humanCommands-${tag}.ts'`);
      return {
        md: await write(`manualDispatch-${tag}.ts`, via('manualDispatch.ts')),
        sar: await write(`sarCommands-${tag}.ts`, via('sarCommands.ts')),
        flight: await write(`flightRunCommands-${tag}.ts`, via('flightRunCommands.ts')),
      };
    }
    for (const [label, make] of mutants) {
      let mods;
      try { mods = await make(); } catch (error) { failures.push(`대조군을 만들지 못했다 — ${label}: ${error.message}`); continue; }
      const bad = await kit.drive(mods, `m${controls.length}`);
      const hit = judgeRun(bad);
      control(`${label} (${hit.length}건)`, hit.length > 0);
    }
  } finally {
    scratch.cleanup();
  }
}
// ⓓ 누름까지 액션 층으로 보낸 사본 — 버튼이 시작을 명령처럼 적는다.
{
  const pushed = buttons.replace("recordHuman('mission_started', currentMission().missionId, { from: 'button' })",
    "recordCommanded({ commandId: 'press', taskId: 'no-node', action: 'mission_started', parameters: {}, issuedBy: 'human' })");
  if (pushed === buttons) failures.push('대조군을 만들지 못했다 — 누름을 액션 층으로 보낸 사본 (원본이 바뀌었나?)');
  else control('누름까지 액션 층으로 보낸 사본', judgePresses(pushed).length > 0);
}

kit.session.resetRobotSession();
original.md.resetManualDispatch();

if (failures.length) {
  console.error(`❌ verify:human-command-layer\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 사람이 낸 명령 ${run.issued.length}건(수동 제어 · SAR · 비행 제어) — 액션 층 · 주체 human · 받은 장비 · 실린 값 그대로 · 답이 붙는다`);
console.log('✅ 노드에 안 붙는다(NO_NODE · 어느 태스크를 열어도 안 보임) · 사람 층에는 없다');
console.log('✅ 누름(시작 · 재시작 · 접근 시작)은 사람 층 그대로 — 버튼은 액션 층 길을 안 부른다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
