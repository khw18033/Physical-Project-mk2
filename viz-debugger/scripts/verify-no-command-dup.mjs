// verify:no-command-dup (261022 신설 — 사람 층·액션 층 경계 §2 · §6)
//
// **같은 명령이 두 층에 없는가.**
//
// 260920 이 액션 층을 더하면서 사람 층의 옛 명령 줄을 안 지웠다. 그래서 태스크가 있는 명령은
// **두 번** 들어갔다 — 액션 층의 `commanded`(주체 backend)와 사람 층의 옛 줄(주체 human).
// `measure:trace-scale` 이 「판마다 1~4건」으로 세던 중복이 이것이다. 같은 일이 두 주체로
// 적혀 있으면 「이 명령은 누가 냈나」에 기록이 두 답을 한다.
//
// 보는 것.
//  ① 문 찾기 편 한 판을 실제 길로 몰았을 때, 액션 층의 명령 하나하나에 대해 **같은 명령**
//     (이름 · 태스크 · 실린 값이 같은 것)이 사람 층에 0건이다
//  ② 로봇에 나간 명령은 **정확히 한 층**에 한 번 있다 — 빠져도 실패, 두 번이어도 실패
//
// 대조군 — **복사본을 되살린 사본**이 잡혀야 한다. 로봇 명령이 `actionLayer` 를 안 주는
// `robotCommands.ts` 사본으로 같은 판을 몬다(그것이 260920~261021 의 코드다). 판정 함수에
// 옛 줄을 손으로 끼운 열도 넣어 본다. LF 로 정규화한 원본에서 만든다(`readSource`).
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeScratch } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';
import { pi7Kit } from './lib/pi7Run.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const kit = await pi7Kit(root);
const original = await load('src', 'physical', 'robotCommands.ts');
const { ACTION_KINDS } = await load('src', 'data', 'actionTrace.ts');

const failures = [];
const controls = [];

/** 명령의 정체 — 이름 · 태스크 · 실린 값. 사람 층 옛 줄은 태스크를 `task_id` 로, 값을 payload 에 펴서 든다. */
const sorted = (o) => JSON.stringify(Object.fromEntries(Object.entries(o ?? {}).sort(([a], [b]) => a.localeCompare(b))));
const keyOfAction = (e) => `${e.payload?.action}|${e.payload?.taskId}|${sorted(e.payload?.parameters)}`;
function keyOfHuman(e) {
  const { task_id: taskId, ...rest } = e.payload ?? {};
  return taskId === undefined ? null : `${e.kind}|${taskId}|${sorted(rest)}`;
}

function judgeDup({ added, sent }) {
  const f = [];
  const commanded = added.filter((e) => e.kind === ACTION_KINDS.commanded);
  const humanKeys = new Map();
  for (const e of added.filter(kit.isHumanLayer)) {
    const key = keyOfHuman(e);
    if (key !== null) humanKeys.set(key, (humanKeys.get(key) ?? 0) + 1);
  }
  // ① 액션 층 명령마다 사람 층의 같은 명령.
  const dup = commanded.filter((e) => humanKeys.has(keyOfAction(e)));
  if (dup.length > 0) f.push(`같은 명령이 두 층에 있다 ${dup.length}건 — ${dup.map((e) => `${e.payload.action}(${e.payload.taskId})`).join(', ')}`);
  // ② 나간 명령은 정확히 한 층에 한 번.
  for (const s of sent) {
    const inAction = commanded.filter((e) => e.nodeId === s.commandId).length;
    const inHuman = [...added.filter(kit.isHumanLayer)].filter((e) => e.kind === s.action
      && sorted(Object.fromEntries(Object.entries(e.payload ?? {}).filter(([k]) => k !== 'task_id'))) === sorted(s.parameters)).length;
    if (inAction + Math.min(inHuman, 1) !== 1) {
      f.push(`${s.action}(${s.commandId}) 가 액션 층 ${inAction} · 사람 층 ${inHuman} — 한 층에 한 번이어야 한다`);
    }
  }
  return f;
}

// ── 한 판 ───────────────────────────────────────────────────────────────────
const run = await kit.drive(original, 'dup');
failures.push(...judgeDup(run));
if (run.sent.length < 6) failures.push(`로봇에 나간 명령이 ${run.sent.length}건 — 검사가 헛돈다`);

// ── 대조군 ──────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  else controls.push(name);
}
{
  // ⓐ 열에 옛 줄을 손으로 되살린다 — 판정 함수만 본다.
  const scan = run.added.find((e) => e.kind === ACTION_KINDS.commanded && e.payload?.action === 'scan_mission');
  if (scan === undefined) failures.push('판에 scan_mission 이 없다 — 대조군을 만들 재료가 없다');
  else {
    const legacy = { seq: 1_000_999, atSec: scan.atSec, nodeId: 'robot-01', status: 'rerunning', kind: 'scan_mission', producedBy: 'human',
      payload: { ...scan.payload.parameters, task_id: scan.payload.taskId } };
    control('열에 scan_mission 옛 줄을 되살린 사본', judgeDup({ ...run, added: [...run.added, legacy] }).length > 0);
  }
  // 빠진 것도 실패다 — 액션 층에서 지운 열.
  control('액션 층에서 명령을 지운 사본', judgeDup({ ...run, added: run.added.filter((e) => e.kind !== ACTION_KINDS.commanded) }).length > 0);
}
{
  // ⓑ 코드 사본 — 로봇 명령이 `actionLayer` 를 안 준다. 출구 본체가 옛 줄을 다시 쓴다.
  const scratch = makeScratch(join(root, 'src', 'physical'), '.verify-nodup-');
  try {
    const source = readSource(root, 'src', 'physical', 'robotCommands.ts')
      .replaceAll("from '../", "from '\u0000/")
      .replaceAll("from './", "from '../")
      .replaceAll("from '\u0000/", "from '../../");
    const muted = source.replace('      actionLayer: true,\n', '');
    if (muted === source) failures.push('대조군을 만들지 못했다 — robotCommands.ts 의 actionLayer 줄 (원본이 바뀌었나?)');
    else {
      const path = scratch.file('robotCommands.ts');
      writeFileSync(path, muted, 'utf8');
      const mutant = await import(pathToFileURL(path).href);
      const bad = await kit.drive(mutant, 'dupM');
      const hit = judgeDup(bad);
      control(`복사본을 되살린 robotCommands 사본 (${hit.length}건)`, hit.length > 0);
    }
  } finally {
    scratch.cleanup();
  }
}

kit.session.resetRobotSession();

if (failures.length) {
  console.error(`❌ verify:no-command-dup\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
const commandedCount = run.added.filter((e) => e.kind === ACTION_KINDS.commanded).length;
console.log(`✅ 한 판에 나간 명령 ${run.sent.length}건 — 액션 층 commanded ${commandedCount}건, 사람 층의 같은 명령 0건`);
console.log('✅ 나간 명령은 정확히 한 층에 한 번 — 빠진 것도 두 번 있는 것도 없다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
