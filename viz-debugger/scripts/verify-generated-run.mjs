// verify:generated-run (261123 신설 — AI 생성 임무 실행기)
//
// 계획서: documents/작업프롬프트/작업프롬프트_AI생성임무실행기_구현계획_261123.md §6.
//
// 모델을 부르지 않는다. 정답셋 임무 셋(gen-lab/goldset/missions/MSN-260831-0{1,2,3}.json — 액션 아이템이 들어 있다)을
// **생성 결과 모양으로 바꿔** 화면과 같은 함수(`tasksFromGenerated` · `viewFromGenerated`)에 넣는다.
//
//   1. 실행 계획 — 정답셋 셋의 명령 과업 · 사람 확인 과업 · 채울 값 · 거부
//   2. 거부 규칙 — 막는 동작 · 어휘 밖 · 장비 둘 · act 아닌 과업 · 이름 없음 · 순환
//   3. 값 — 빈칸 · 범위 밖 · 정상 · 걸음 자르기
//   4. 실행 순서 — 앞 과업이 끝나야 다음 · 사람 확인을 기다림 · 실패 · 정지 뒤에는 아무것도 안 나감
//   5. 승인 문 — 값이 덜 채워지면 승인 안 됨 · 채우면 걸음이 임무에 실리고 관문이 열림 · 사람이 채운 값이 승인보다 먼저 기록됨
//                · 실행 불가 계획은 지금처럼 캔버스에만 (관문 안 열림)
//   6. 대조군 — 규칙을 일부러 깬 사본이 반드시 잡히는가
import { readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const srcDir = join(vizRoot, 'src');
const goldDir = join(vizRoot, '..', 'gen-lab', 'goldset', 'missions');
const load = (...parts) => import(pathToFileURL(join(srcDir, ...parts)).href);

const commandsPath = join(srcDir, 'generate', 'actionCommands.ts');
const actions = await import(pathToFileURL(commandsPath).href);
const { tasksFromGenerated, viewFromGenerated, provenanceOf } = await load('generate', 'proposal.ts');
const store = await load('data', 'scenario.ts');
const { setFillValue, actionVocabulary } = await load('generate', 'runFill.ts');
const { robotSession } = await load('physical', 'robotSession.ts');

const failures = [];
const controls = [];
const vocabulary = actionVocabulary();

/** 정답셋 한 편 → 생성 결과 모양(`milestones[].tasks[]`). 액션 아이템은 그대로 옮긴다. */
function goldAsGenerated(id, missionId = `MSN-GEN-${id}`) {
  const gold = JSON.parse(readFileSync(join(goldDir, `${id}.json`), 'utf8'));
  const byId = new Map(gold.tasks.map((task) => [task.task_id, task]));
  return {
    mission_id: missionId,
    utterance: { audio_ref: null, text: gold.utterance.text, engine: 'manual_text', confidence: 1 },
    milestones: gold.milestones.map((milestone) => ({
      milestone_id: milestone.milestone_id,
      title: milestone.title,
      order: milestone.order,
      status: 'pending',
      assigned_targets: milestone.assigned_targets,
      tasks: milestone.task_ids.map((taskId) => {
        const task = byId.get(taskId);
        return {
          task_id: task.task_id, title: task.title, deps: task.deps ?? [], status: 'pending', attempt: 1,
          derived_from: null, action_items: task.action_items ?? [], evaluation: null,
          node_kind: task.node_kind, target: task.target ?? null,
        };
      }),
    })),
  };
}

function planOf(id) {
  return actions.planGeneratedRun(tasksFromGenerated(goldAsGenerated(id)).tasks, vocabulary);
}

// ── 1. 정답셋 셋의 실행 계획 ─────────────────────────────────────────────────
{
  const one = planOf('MSN-260831-01');
  const commandIds = one.order.filter((entry) => entry.kind === 'command').map((entry) => entry.taskId);
  if (commandIds.join(',') !== 'T-11b,T-13b,T-14a,T-15b') failures.push(`01 명령 과업이 ${commandIds.join(',')} 다 — T-11b,T-13b,T-14a,T-15b 여야 한다`);
  if (one.humanTasks !== 13) failures.push(`01 사람 확인 과업이 ${one.humanTasks}개다 — 13개여야 한다`);
  if (one.fills.length !== 3) failures.push(`01 채울 값이 ${one.fills.length}칸이다 — move_forward 셋이다`);
  if (!one.runnable) failures.push(`01 이 실행 불가다: ${JSON.stringify(one.rejected)}`);
  if (one.target !== 'robot-01') failures.push(`01 장비가 ${one.target} 다`);
  // 순서: 의존성을 지킨다 — 앞선 과업이 뒤에 오면 안 된다
  const tasks = tasksFromGenerated(goldAsGenerated('MSN-260831-01')).tasks;
  const position = new Map(one.order.map((entry, index) => [entry.taskId, index]));
  for (const task of tasks) for (const dep of task.deps) {
    if ((position.get(dep) ?? -1) > (position.get(task.id) ?? -1)) failures.push(`01 순서가 의존성을 어긴다: ${dep} 가 ${task.id} 뒤에 온다`);
  }

  const two = planOf('MSN-260831-02');
  if (!two.runnable || two.fills.length !== 2) failures.push(`02 는 실행 가능 · 채울 값 2칸이어야 한다 (runnable=${two.runnable}, fills=${two.fills.length})`);

  const three = planOf('MSN-260831-03');
  if (three.runnable) failures.push('03 (수문) 이 실행 가능으로 나왔다 — 수문은 2단계다');
  if (!three.rejected.some((rejection) => rejection.reason === 'later' && rejection.action === 'close_gate')) {
    failures.push(`03 의 close_gate 가 「2단계」로 거부되지 않았다: ${JSON.stringify(three.rejected)}`);
  }
}

// ── 2. 거부 규칙 ─────────────────────────────────────────────────────────────
function task(id, { kind = 'act', target = 'robot-01', items = [], deps = [] } = {}) {
  return {
    id, title: id, deps, target, milestone: 'MS-A', nodeKind: kind,
    actionItems: items.map((action, index) => ({ id: `${id}-${index + 1}`, label: action, params: action === '' ? {} : { action }, status: 'pending', target })),
  };
}
const reasonOf = (tasks) => actions.planGeneratedRun(tasks, vocabulary).rejected.map((rejection) => rejection.reason);
const expectReject = (name, tasks, reason) => {
  const reasons = reasonOf(tasks);
  if (!reasons.includes(reason)) failures.push(`${name}: '${reason}' 로 거부돼야 하는데 ${JSON.stringify(reasons)}`);
};
expectReject('scan_mission', [task('T-1', { items: ['scan_mission'] })], 'blocked');
expectReject('어휘 밖', [task('T-1', { items: ['open_gate'] })], 'vocabulary');
expectReject('장비 둘', [task('T-1', { items: ['move_forward'] }), task('T-2', { target: 'robot-02', items: ['turn'] })], 'targets');
expectReject('act 아닌 과업', [task('T-1', { kind: 'sense', items: ['move_forward'] })], 'not_act');
expectReject('동작 이름 없음', [task('T-1', { items: [''] })], 'shape');
expectReject('순환', [task('T-1', { deps: ['T-2'], items: ['abort'] }), task('T-2', { deps: ['T-1'], items: ['abort'] })], 'cycle');
{
  const plan = actions.planGeneratedRun([task('T-1', { kind: 'sense' })], vocabulary);
  if (plan.runnable) failures.push('명령 과업이 없는데 실행 가능으로 나왔다 — 로봇에 낼 것이 없다');
}

// ── 3. 값 ────────────────────────────────────────────────────────────────────
{
  const plan = actions.planGeneratedRun([task('T-1', { items: ['turn', 'move_forward'] }), task('T-2', { items: ['abort'], deps: ['T-1'] })], vocabulary);
  const [turnKey, forwardKey] = plan.fills.map((slot) => slot.key);
  const problemsOf = (values) => actions.fillProblems(plan, values).map((problem) => problem.reason).join(',');
  if (problemsOf({}) !== 'missing,missing') failures.push(`빈칸이 'missing' 둘로 안 잡혔다: ${problemsOf({})}`);
  for (const [values, name] of [[{ [turnKey]: 3, [forwardKey]: 1 }, '회전 3°'], [{ [turnKey]: 400, [forwardKey]: 1 }, '회전 400°'],
    [{ [turnKey]: 90, [forwardKey]: 0.01 }, '직진 0.01 m'], [{ [turnKey]: 90, [forwardKey]: 12 }, '직진 12 m']]) {
    if (!problemsOf(values).includes('range')) failures.push(`${name} 가 범위 밖으로 안 잡혔다`);
  }
  if (problemsOf({ [turnKey]: -90, [forwardKey]: 1.5 }) !== '') failures.push('왼쪽 90° · 1.5 m 가 문제로 잡혔다');
  if (actions.runItemsOf(plan, {}) !== null) failures.push('값이 빈 채로 실행 목록이 나왔다');
  const items = actions.runItemsOf(plan, { [turnKey]: -90, [forwardKey]: 1.5 });
  const first = items?.[0];
  if (first?.kind !== 'command' || first.steps.length !== 2 || first.steps[0].action !== 'turn' || first.steps[0].parameters.deg !== -90
    || first.steps[1].action !== 'move_forward' || first.steps[1].parameters.distance_m !== 1.5 || first.steps.some((step) => step.taskId !== 'T-1')) {
    failures.push(`T-1 걸음이 [turn -90, move_forward 1.5] 가 아니다: ${JSON.stringify(first)}`);
  }
  const stop = items?.[1];
  if (stop?.kind !== 'command' || stop.steps[0]?.action !== 'abort' || stop.steps[0]?.parameters?.reason !== 2) {
    failures.push(`정지가 화면 정지(abort · reason 2)로 안 나간다: ${JSON.stringify(stop)}`);
  }
}

// ── 4. 실행 순서 ─────────────────────────────────────────────────────────────
async function runWith(items, { failAt = null, humanVerdict = 'done', stopAfter = null } = {}) {
  const log = [];
  let stopped = false;
  const outcome = await actions.runGenerated(items, {
    issue: async (steps) => {
      log.push(`issue:${steps[0].taskId}`);
      if (stopAfter === steps[0].taskId) stopped = true;
      return { sent: steps[0].taskId !== failAt, reason: 'robot said no' };
    },
    waitHuman: async (taskId) => { log.push(`human:${taskId}`); return humanVerdict; },
    stopped: () => stopped,
  });
  return { log, outcome };
}
{
  const items = [
    { kind: 'command', taskId: 'A', steps: [{ taskId: 'A', action: 'turn', parameters: { deg: 90 } }] },
    { kind: 'human', taskId: 'B' },
    { kind: 'command', taskId: 'C', steps: [{ taskId: 'C', action: 'move_forward', parameters: { distance_m: 1 } }] },
  ];
  const ok = await runWith(items);
  if (ok.log.join(' ') !== 'issue:A human:B issue:C' || ok.outcome.ended !== 'done') failures.push(`정상 순서가 아니다: ${ok.log.join(' ')} → ${ok.outcome.ended}`);
  const failed = await runWith(items, { failAt: 'A' });
  if (failed.log.join(' ') !== 'issue:A' || failed.outcome.ended !== 'failed') failures.push(`A 가 실패했는데 뒤가 나갔다: ${failed.log.join(' ')}`);
  const humanNo = await runWith(items, { humanVerdict: 'failed' });
  if (humanNo.log.includes('issue:C') || humanNo.outcome.ended !== 'failed') failures.push(`사람이 실패로 닫았는데 C 가 나갔다: ${humanNo.log.join(' ')}`);
  const humanStop = await runWith(items, { humanVerdict: 'stopped' });
  if (humanStop.log.includes('issue:C') || humanStop.outcome.ended !== 'stopped') failures.push(`사람 확인 중 정지했는데 C 가 나갔다: ${humanStop.log.join(' ')}`);
  const stop = await runWith(items, { stopAfter: 'A' });
  if (stop.log.join(' ') !== 'issue:A' || stop.outcome.ended !== 'stopped') failures.push(`A 뒤에 정지했는데 더 나갔다: ${stop.log.join(' ')}`);
}

// ── 5. 승인 문 ───────────────────────────────────────────────────────────────
function sampleProvenance() {
  return provenanceOf({
    mission: goldAsGenerated('MSN-260831-01'), engine: 'llama.cpp', model: 'Qwen3-8B-Q4_K_M',
    grammar: { source: 'contracts/mission.schema.json', digest: 'abc123', bytes: 2048 },
    schema_checked: true, schema_errors: [], elapsed_sec: 7.4,
    extra: { stub: false, prompt_digest: 'deadbeef', prompt_chars: 9000, rules_applied: ['출력은 JSON 객체 하나다.'], overwritten: [],
      places_given: true, equipment_given: 10, examples_given: 2, node_kinds_given: false, actions_given: true },
  });
}
{
  const mission = goldAsGenerated('MSN-260831-01', 'MSN-GEN-RUN-0001');
  const view = viewFromGenerated(mission, '검사용 생성 임무');
  const plan = actions.planGeneratedRun(view.tasks, vocabulary);
  const before = store.getMissionState().current.missionId;
  store.proposeGenerated(view, sampleProvenance());
  if (store.acceptProposal('local') !== false) failures.push('값을 안 채웠는데 승인이 됐다');
  if (store.getMissionState().current.missionId !== before) failures.push('값을 안 채운 승인이 현재 임무를 바꿨다');
  if (robotSession().approved) failures.push('값을 안 채운 승인이 로봇 관문을 열었다');
  if (store.getMissionState().proposal === null) failures.push('막힌 승인이 제안을 지웠다 — 사람이 값을 채울 자리가 사라진다');

  plan.fills.forEach((slot, index) => setFillValue(view.missionId, slot.key, 1 + index * 0.5));
  if (store.acceptProposal('local') !== true) failures.push('값을 다 채웠는데 승인이 안 됐다');
  const current = store.getMissionState().current;
  const run = actions.generatedRunOf(current.params);
  if (run.length !== plan.order.length) failures.push(`임무에 실린 실행 목록이 ${run.length}칸이다 — ${plan.order.length}칸이어야 한다`);
  const forwards = run.flatMap((item) => (item.kind === 'command' ? item.steps : [])).filter((step) => step.action === 'move_forward').map((step) => step.parameters.distance_m);
  if (forwards.join(',') !== '1,1.5,2') failures.push(`실린 직진 거리가 ${forwards.join(',')} 다 — 사람이 채운 1,1.5,2 여야 한다`);
  if (!robotSession().approved) failures.push('실행 가능한 생성 임무를 승인했는데 로봇 관문이 안 열렸다');
  const trace = store.traceFor(current);
  const filled = trace.filter((event) => event.producedBy === 'human' && event.kind === 'action_params_filled');
  const accepted = trace.find((event) => event.producedBy === 'human' && event.kind === 'proposal_accepted');
  if (filled.length !== 3) failures.push(`사람이 채운 값 기록이 ${filled.length}건이다 — 3건이어야 한다`);
  if (accepted === undefined || filled.some((event) => event.seq > accepted.seq)) failures.push('사람이 채운 값이 승인보다 뒤에 기록됐다');

  // 사람 확인 사건이 그 노드를 닫는다
  const humanTask = plan.order.find((entry) => entry.kind === 'human').taskId;
  store.recordRunnerWait(humanTask);
  store.recordHumanVerdict(humanTask, 'done');
  const folded = store.statusesAt(store.getMissionState().headSec + 1, current);
  if (folded.tasks[humanTask]?.status !== 'done') failures.push(`사람이 확인한 ${humanTask} 가 '${folded.tasks[humanTask]?.status}' 다 — done 이어야 한다`);
  const verdict = store.traceFor(current).find((event) => event.kind === 'human_confirmed');
  if (verdict?.producedBy !== 'human') failures.push('사람 확인 사건의 주체가 human 이 아니다');
  const wait = store.traceFor(current).find((event) => event.kind === 'awaiting_human');
  if (wait?.producedBy !== 'backend') failures.push('사람 확인 대기 사건의 주체가 backend 가 아니다');
}
{
  // 실행 불가(액션 아이템 없음) — 지금까지처럼 캔버스에만, 관문은 안 연다
  const mission = goldAsGenerated('MSN-260831-03', 'MSN-GEN-RUN-0002');
  const view = viewFromGenerated(mission, '검사용 실행 불가 임무');
  store.proposeGenerated(view, sampleProvenance());
  if (store.acceptProposal('local') !== true) failures.push('실행 불가 계획의 승인(캔버스에만)이 안 됐다');
  if (robotSession().approved) failures.push('실행 불가 계획을 승인했는데 로봇 관문이 열렸다');
  if (actions.generatedRunOf(store.getMissionState().current.params).length !== 0) failures.push('실행 불가 계획에 걸음이 실렸다');
}

// ── 6. 대조군 ────────────────────────────────────────────────────────────────
{
  const source = readFileSync(commandsPath, 'utf8').replaceAll('\r\n', '\n');
  const mutants = [
    {
      name: 'scan_mission 을 막지 않는 사본',
      from: "const BLOCKED_ACTIONS: readonly string[] = ['scan_mission'];",
      to: 'const BLOCKED_ACTIONS: readonly string[] = [];',
      check: (module) => !module.planGeneratedRun([task('T-1', { items: ['scan_mission'] })], vocabulary).rejected.some((r) => r.reason === 'blocked'),
    },
    {
      name: '실패한 과업 뒤에도 계속 내는 사본',
      from: "    if (outcome.sent !== true) return { ended: 'failed', taskId: item.taskId, reason: outcome.reason ?? '' };",
      to: '',
      check: async (module) => {
        const log = [];
        await module.runGenerated([
          { kind: 'command', taskId: 'A', steps: [{ taskId: 'A', action: 'turn' }] },
          { kind: 'command', taskId: 'B', steps: [{ taskId: 'B', action: 'turn' }] },
        ], { issue: async (steps) => { log.push(steps[0].taskId); return { sent: false }; }, waitHuman: async () => 'done', stopped: () => false });
        return log.includes('B');
      },
    },
  ];
  for (const [index, mutant] of mutants.entries()) {
    if (!source.includes(mutant.from)) { failures.push(`대조군 ${index + 1}을 만들 자리가 사라졌다 (${mutant.name}) — 이 검사는 무의미하다`); continue; }
    const path = join(srcDir, 'generate', `.verify-generated-run-${index}.ts`);
    try {
      writeFileSync(path, source.replace(mutant.from, mutant.to), 'utf8');
      const module = await import(pathToFileURL(path).href);
      if (await mutant.check(module)) controls.push(mutant.name);
      else failures.push(`대조군을 검출하지 못했다: ${mutant.name} — 이 검사는 무의미하다`);
    } finally {
      try { rmSync(path, { force: true }); } catch { console.warn('임시 파일 정리 실패 — ' + path); }
    }
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:generated-run — ${failures.length}건`);
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log(`✅ verify:generated-run — 정답셋 셋 · 거부 6종 · 값 · 실행 순서 · 승인 문 · 대조군 ${controls.length}건 검출 (${controls.join(' · ')})`);
