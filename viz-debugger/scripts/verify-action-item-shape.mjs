// verify:action-item-shape (261023 신설 — 생성기 3단계 H · 지시서 §6)
//
// **액션 아이템이 제자리에 붙었고, 목록에 있는 동작인가.**
//
// 액션 아이템은 장비에 주는 자세한 행동강령이다. 그래서 `act` 태스크에만 붙는다 — 탐지 같은
// 서비스는 켜 두면 입력이 오는 대로 돌아 지정할 행동이 없다. 그리고 `params.action` 은 그
// 태스크 target 의 생성 어휘(`equipment.json` 의 `actions`)에 있어야 한다.
//
// 문법은 계약에서 뽑으므로 **모양은 문법이 이미 막는다.** 이 검사가 보는 것은 문법이 못 보는
// 둘이다 — **어느 태스크에 붙었나**와 **목록에 있는 동작인가.** (`params` 는 계약에서
// `{"type":"object"}` 라 문법이 동작 이름을 모른다.)
//
// 보는 것.
//  ① 정답셋 세 편 — 계약을 통과하고, 원칙 위반이 0건이다. 정답이 어기면 채점이 원칙을 거꾸로 가르친다
//  ② 3단계 판의 few-shot 예시(`lib/fewshot.mjs`) — **모델이 실제로 보는 것**이다. 같은 기준으로 0건
//     이어야 하고, 예시에 액션 아이템이 실제로 실려 있어야 한다(규칙만 바꾸면 예시가 이긴다)
//  ③ 3단계 판을 끈 예시에는 액션 아이템이 **없다** — 2단계까지의 프롬프트가 안 바뀐다
//  ④ 생성 결과 — `gen-lab/runs/` 에서 3단계로 돈 실행이 있으면 위반 수를 **적기만 한다.**
//     모델이 어긴 것은 측정값이지 검사 실패가 아니다(`score:generation` 과 같은 성질)
//
// 대조군 셋 — 정답셋 원본(LF 정규화 · `readSource`)에서 만든다. 셋 다 잡혀야 한다.
//   목록 밖 동작을 넣은 사본 · `sense` 에 액션 아이템을 단 사본 · `action` 을 뺀 사본
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadContracts, validate } from './lib/json-schema.mjs';
import { mutate, readSource } from './lib/source.mjs';
import { actionVocabulary, inspectActionItems } from './lib/actionItems.mjs';
import { examplesFor } from './lib/fewshot.mjs';

const vizRoot = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const repoRoot = join(vizRoot, '..');
const goldDir = join(repoRoot, 'gen-lab', 'goldset', 'missions');
const contracts = loadContracts(join(repoRoot, 'contracts'));
const itemSchema = contracts.get('action-item.schema.json');
const vocabulary = actionVocabulary(JSON.parse(readFileSync(join(repoRoot, 'equipment', 'equipment.json'), 'utf8')));

/**
 * 정답셋(태스크가 평평하다) → 마일스톤 안에 태스크가 든 모양. 원칙 검사에 필요한 칸만 옮긴다.
 * (채점기의 `toContract` 를 import 하지 않는다 — 그 파일은 불리는 순간 채점을 돌린다.)
 */
const nested = (mission) => ({
  milestones: mission.milestones.map((milestone) => ({
    tasks: mission.tasks.filter((task) => task.milestone_id === milestone.milestone_id),
  })),
});

const failures = [];
const passed = [];

/** 원칙 위반의 합. `extra_params` 는 위반이 아니다(발화가 요구한 값일 수 있다). */
function violations(mission) {
  const seen = inspectActionItems(mission, vocabulary);
  return {
    seen,
    count: seen.misplaced.length + seen.off_list.length + seen.no_action.length + seen.target_mismatch.length + seen.adapter_set.length,
  };
}

// ── ① 정답셋 ─────────────────────────────────────────────────────────────────
const names = readdirSync(goldDir).filter((name) => name.endsWith('.json')).sort();
const gold = names.map((name) => JSON.parse(readSource(goldDir, name)));
let goldItems = 0;
for (const mission of gold) {
  for (const task of mission.tasks) {
    for (const item of task.action_items ?? []) {
      const checked = validate(item, itemSchema, contracts);
      if (!checked.ok) failures.push(`${mission.mission_id} ${task.task_id}: 정답 액션 아이템이 계약을 통과하지 못한다 — ${checked.errors.slice(0, 3).join(' / ')}`);
    }
  }
  const { seen, count } = violations(nested(mission));
  goldItems += seen.items;
  if (count > 0) failures.push(`${mission.mission_id}: 정답셋이 원칙을 어긴다 — ${JSON.stringify({ ...seen, extra_params: undefined, empty_act: undefined })}`);
}
if (goldItems === 0) failures.push('정답셋에 액션 아이템이 하나도 없다 — 검사할 재료가 없다 (`npm run goldset:extract`)');
else passed.push(`정답셋 ${gold.length}편 — 계약 통과 · 액션 아이템 ${goldItems}개 · 원칙 위반 0`);

// ── ② ③ few-shot 예시 ─────────────────────────────────────────────────────────
let shownItems = 0;
let shownWithout = 0;
for (const mission of gold) {
  for (const example of examplesFor(mission.mission_id, gold, 'leave-one-out', { tasks: true, actions: true })) {
    const { seen, count } = violations(example);
    shownItems += seen.items;
    if (count > 0) failures.push(`${mission.mission_id} 의 예시 ${example.mission_id}: 모델이 보는 예시가 원칙을 어긴다 — ${JSON.stringify(seen.misplaced.concat(seen.off_list))}`);
  }
  for (const example of examplesFor(mission.mission_id, gold, 'leave-one-out', { tasks: true })) {
    shownWithout += inspectActionItems(example, vocabulary).items;
  }
}
if (shownItems === 0) failures.push('3단계 판의 예시에 액션 아이템이 없다 — 규칙만 바꾸면 예시가 이긴다 (10단계 E 판 15건 중 10건)');
else passed.push(`3단계 판 예시 — 액션 아이템 ${shownItems}개 실림 · 원칙 위반 0`);
if (shownWithout > 0) failures.push(`3단계를 끈 예시에 액션 아이템이 ${shownWithout}개 실렸다 — 2단계까지의 프롬프트가 바뀐다`);
else passed.push('3단계를 끈 예시 — 액션 아이템 0 (2단계 프롬프트 그대로)');

// ── ④ 생성 결과 — 적기만 한다 ───────────────────────────────────────────────
const runsDir = join(repoRoot, 'gen-lab', 'runs');
for (const run of existsSync(runsDir) ? readdirSync(runsDir).sort() : []) {
  let summary;
  try { summary = JSON.parse(readFileSync(join(runsDir, run, 'summary.json'), 'utf8')); } catch { continue; }
  if (summary.actions !== true) continue;
  const total = { missions: 0, items: 0, misplaced: 0, off_list: 0, no_action: 0, target_mismatch: 0, adapter_set: 0 };
  for (const dir of readdirSync(join(runsDir, run)).filter((name) => /^v\d+$/.test(name))) {
    for (const file of readdirSync(join(runsDir, run, dir)).filter((name) => name.endsWith('.json'))) {
      const { seen } = violations(JSON.parse(readSource(runsDir, run, dir, file)));
      total.missions += 1;
      total.items += seen.items;
      for (const key of ['misplaced', 'off_list', 'no_action', 'target_mismatch', 'adapter_set']) total[key] += seen[key].length;
    }
  }
  console.log(`  (측정값) ${run} — 임무 ${total.missions} · 액션 아이템 ${total.items} · 잘못 든 자리 ${total.misplaced} · 목록 밖 ${total.off_list} · action 없음 ${total.no_action} · target 불일치 ${total.target_mismatch} · adapter 적음 ${total.adapter_set}`);
}

// ── 대조군 — 정답셋 원본 글자에서 만든다 ─────────────────────────────────────
const source = readSource(goldDir, 'MSN-260831-01.json');
const control = (name, mutated, caught) => {
  if (mutated === null) { failures.push(`대조군을 만들지 못했다: ${name} — 치환이 아무것도 안 바꿨다`); return; }
  const { seen } = violations(nested(JSON.parse(mutated)));
  if (caught(seen)) passed.push(`대조군 검출: ${name}`);
  else failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
};
// 목록 밖 — robot-01 은 open_gate 를 밝히지 않았다. 문법은 이것을 통과시킨다.
control('목록 밖 동작(robot-01 에 open_gate)을 넣은 사본',
  mutate(source, '"action": "move_forward"', '"action": "open_gate"'),
  (seen) => seen.off_list.some((item) => item.action === 'open_gate'));
// sense 에 단 사본 — T-12a(문 주변 관측, sense)의 빈 배열을 명령으로 채운다.
control('sense 태스크(T-12a)에 액션 아이템을 단 사본',
  mutate(source, /("task_id": "T-12a",[\s\S]*?"action_items": )\[\]/,
    '$1[{"item_id":"T-12a-1","target":"camera-02","adapter":"","params":{"action":"scan_mission"},"status":"pending","telemetry_ref":null}]'),
  (seen) => seen.misplaced.some((item) => item.task_id === 'T-12a'));
// action 을 뺀 사본 — params 가 비면 명령이 아니다. 계약(`{"type":"object"}`)은 이것도 통과시킨다.
control('params.action 을 뺀 사본',
  mutate(source, /"params": \{\s*"action": "abort"\s*\}/, '"params": {}'),
  (seen) => seen.no_action.length > 0);

for (const line of passed) console.log(`✅ ${line}`);
if (failures.length > 0) {
  console.error(`❌ verify:action-item-shape — ${failures.length}건\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ verify:action-item-shape — 액션 아이템은 act 에만 · 목록의 동작만 · 대조군 셋 검출');
