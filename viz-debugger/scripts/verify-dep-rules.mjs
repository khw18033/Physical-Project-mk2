// verify:dep-rules (260904 신설 — 마일스톤 분리 지시서 §5)
//
// **이 작업에서 가장 중요한 검사다.** 규칙이 사람이 손으로 만든 정답 DAG 를 복원하지
// 못하면 규칙이 틀린 것이고, 그때는 모델을 고칠 것이 아니라 규칙을 고쳐야 한다.
//
// 보는 것 넷.
//  1. **순환이 없다** — 대본 4편에서도, 무작위 노드 목록에서도. `solveDeps()` 의 모든
//     엣지는 목록에서 앞선 노드만 가리키므로 순환은 구조적으로 불가능하다. 그래도 잰다 —
//     "불가능하다"는 주장은 검사로만 유지된다.
//  2. **대본의 원래 `deps` 를 복원한다** — 아래 기준선(`BASELINE`)과 정확히 같아야 한다.
//  3. **못 복원한 자리는 목록으로 못박는다**(`KNOWN_GAPS`). 새로 생기면 회귀이고,
//     **없어져도 실패다** — 규칙을 고쳐 좋아졌으면 그 사실을 보고서에 적으라는 뜻이다.
//     억지로 맞추지 말고 못 맞춘 채로 보고하는 쪽이 낫다(지시서).
//  4. **계약** — `task.schema.json` 의 `node_kind` 가 **선택** 필드인가. 필수가 되면
//     노드 분화 이전 편과 기존 예시가 통째로 무효가 된다.
//
// 대조군 포함 — 규칙을 무력화한 사본이 반드시 실패로 잡히는지까지 본다.
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(vizRoot, '..');
const solverPath = join(vizRoot, 'src', 'generate', 'solveDeps.ts');
const goldDir = join(repoRoot, 'gen-lab', 'goldset', 'missions');

const failures = [];
const controls = [];

const { solveDeps, hasCycle } = await import(pathToFileURL(solverPath).href);

const gold = readdirSync(goldDir)
  .filter((name) => name.endsWith('.json'))
  .map((name) => JSON.parse(readFileSync(join(goldDir, name), 'utf8')))
  .sort((a, b) => a.mission_id.localeCompare(b.mission_id));

/**
 * 복원 기준선. **지금 규칙이 실제로 내는 값**이고, 바뀌면(좋아져도) 이 검사가 실패한다.
 * 규칙을 손대면 이 표와 아래 KNOWN_GAPS 를 같이 고치고 보고서에 적는다.
 */
const BASELINE = {
  'MSN-260831-01': { tasks: 17, restored: 17 },
  'MSN-260831-02': { tasks: 18, restored: 13 },
  'MSN-260831-03': { tasks: 16, restored: 16 },
};

/**
 * 복원하지 못한 자리와 **왜 못하는지.**
 *
 * 다섯 다 대본 2편(재탐색 루프)이고 뿌리는 둘이다.
 *
 *  ① `sense` 를 매달지 않는 규칙의 대가 (T-23c · T-25c, 그리고 그 여파인 T-24a · T-26a)
 *     — 2편 MS-C 의 「칸 스캔」(sense)은 앞의 「대상 칸으로 이동」(act) 결과를 보는 것이라
 *       매달려야 하는데, 1편 MS-D 의 「위치 발행」(sense)은 앞의 「복도 경로 추종」(act)과
 *       **병렬**이어야 한다. 둘은 (종류·대상·순서)가 완전히 같다 — robot-01 의 act 뒤에
 *       오는 robot-01 의 sense. 구조만 보고는 가를 수 없다.
 *     — `sense` 도 직전에 매달게 해 보면 2편은 17/18 로 올라가지만 **1편의 합류가 사라지고**
 *       (17/17 → 14/17) 네 편 전체에서 합류가 0이 된다. 지시서가 예로 든 바로 그 합류이고,
 *       「병렬은 제약이 없어서 남는 것」이라는 규칙의 요지가 함께 무너진다. 그래서 안 바꿨다.
 *  ② 마일스톤을 멀리 건너뛰는 참조 (T-27a)
 *     — 2편 MS-F 의 「칸별 마지막 탐지 시각 감시」가 MS-B 의 「맵 칸 표시 발행」(T-22c)에
 *       매달린다. 직전 블록이 아니라 다섯 블록 앞이다. 「감시는 표시가 생긴 뒤부터」라는
 *       **의미**에서 나온 엣지라 구조 규칙으로는 낼 수 없다.
 */
const KNOWN_GAPS = [
  { mission: 'MSN-260831-02', task: 'T-23c', rule: ['T-22c'], gold: ['T-23b'], why: '① sense 는 매달지 않는다 — 1편 MS-D 의 병렬과 구조가 같아 가를 수 없다' },
  { mission: 'MSN-260831-02', task: 'T-24a', rule: ['T-23b', 'T-23c'], gold: ['T-23c'], why: '① 의 여파 — T-23c 가 블록 안에서 떠 있어 끝 노드가 둘이 됐다' },
  { mission: 'MSN-260831-02', task: 'T-25c', rule: ['T-24b'], gold: ['T-25b'], why: '① 과 같다' },
  { mission: 'MSN-260831-02', task: 'T-26a', rule: ['T-25b', 'T-25c'], gold: ['T-25c'], why: '① 의 여파 — 위와 같다' },
  { mission: 'MSN-260831-02', task: 'T-27a', rule: ['T-26b'], gold: ['T-22c'], why: '② 다섯 블록을 건너뛰는 의미 엣지 — 구조 규칙으로는 낼 수 없다' },
];

const nodesOf = (mission) => mission.tasks.map((task) => ({
  id: task.task_id,
  title: task.title,
  nodeKind: task.node_kind,
  target: task.target,
  milestoneId: task.milestone_id,
}));

/** 검사 본문. 대조군도 **같은 함수**를 돌린다 — 다른 잣대를 대면 대조가 아니다. */
function reconstruct(solve) {
  const rows = [];
  for (const mission of gold) {
    if (!mission.shape.labeled) continue; // 라벨이 없는 편은 규칙을 적용할 수 없다 (아래에서 따로 본다)
    const result = solve(nodesOf(mission));
    const gaps = [];
    let restored = 0;
    for (const task of mission.tasks) {
      const got = result.deps[task.task_id] ?? [];
      if (got.join(',') === [...task.deps].join(',')) restored += 1;
      else gaps.push({ mission: mission.mission_id, task: task.task_id, rule: got, gold: [...task.deps] });
    }
    rows.push({
      mission: mission.mission_id,
      tasks: mission.tasks.length,
      restored,
      gaps,
      cycle: hasCycle(result.deps),
      byRule: result.byRule,
      reduced: result.reduced,
      joins: Object.values(result.deps).filter((deps) => deps.length > 1).length,
      goldJoins: mission.tasks.filter((task) => task.deps.length > 1).length,
    });
  }
  return rows;
}

const rows = reconstruct(solveDeps);

// ── 1. 순환 ──────────────────────────────────────────────────────────────────
for (const row of rows) {
  if (row.cycle) failures.push(`${row.mission}: solveDeps 결과에 순환이 있다 — 모든 엣지는 앞선 노드만 가리켜야 한다`);
}

// 무작위 목록에서도. 종류·대상·마일스톤을 뒤섞어 던진다 — 모델이 낼 수 있는 아무 목록이나.
{
  const kinds = ['sense', 'decide', 'act', 'verify', 'report'];
  const targets = ['robot-01', 'camera-02', 'sensor-01', null];
  let seed = 20260904;
  const next = (limit) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % limit; };
  for (let round = 0; round < 300; round += 1) {
    const count = 1 + next(24);
    const milestoneCount = 1 + next(5);
    const nodes = [];
    for (let index = 0; index < count; index += 1) {
      nodes.push({
        id: `N-${index}`,
        title: `n${index}`,
        nodeKind: kinds[next(kinds.length)],
        target: targets[next(targets.length)],
        // 마일스톤이 **떨어져 다시 나오는** 경우까지 포함한다 (2편의 재탐색 루프 모양).
        milestoneId: `MS-${next(milestoneCount)}`,
      });
    }
    const result = solveDeps(nodes);
    if (hasCycle(result.deps)) { failures.push(`무작위 목록(round ${round})에서 순환이 나왔다 — 노드 ${count}개`); break; }
    // 엣지는 언제나 **앞**을 가리켜야 한다. 이것이 순환 불가능의 근거다.
    const order = new Map(nodes.map((node, index) => [node.id, index]));
    for (const [id, deps] of Object.entries(result.deps)) {
      for (const dep of deps) {
        if ((order.get(dep) ?? -1) >= (order.get(id) ?? -1)) {
          failures.push(`무작위 목록(round ${round}): ${id} 가 뒤(또는 자기)를 가리킨다 — ${dep}`);
        }
      }
    }
    if (failures.length > 0) break;
  }
}

// ── 2·3. 복원과 못 복원한 자리 ───────────────────────────────────────────────
for (const row of rows) {
  const expected = BASELINE[row.mission];
  if (expected === undefined) { failures.push(`${row.mission}: 기준선이 없다 — BASELINE 에 추가하고 보고서에 적어라`); continue; }
  if (row.tasks !== expected.tasks) failures.push(`${row.mission}: 태스크 ${row.tasks}개 — 기준선은 ${expected.tasks}개다`);
  if (row.restored !== expected.restored) {
    failures.push(
      `${row.mission}: ${row.restored}/${row.tasks} 복원 — 기준선은 ${expected.restored}/${expected.tasks} 다. ` +
      (row.restored > expected.restored
        ? '좋아졌다면 BASELINE·KNOWN_GAPS 를 고치고 보고서에 무엇을 바꿨는지 적어라'
        : '규칙이 나빠졌다'),
    );
  }
}

{
  const actual = rows.flatMap((row) => row.gaps);
  const key = (gap) => `${gap.mission}/${gap.task}:${gap.rule.join('+')}→${gap.gold.join('+')}`;
  const actualKeys = new Set(actual.map(key));
  const knownKeys = new Set(KNOWN_GAPS.map(key));
  for (const gap of actual) {
    if (!knownKeys.has(key(gap))) failures.push(`새로 복원 못 한 자리: ${key(gap)} — 규칙이 나빠졌거나 대본이 바뀌었다`);
  }
  for (const gap of KNOWN_GAPS) {
    if (!actualKeys.has(key(gap))) failures.push(`KNOWN_GAPS 에 적힌 ${key(gap)} 가 이제 복원된다 — 목록을 줄이고 보고서에 적어라`);
  }
}

// 합류가 살아 있는가. 이것이 「병렬은 제약이 없어서 남는 것」이라는 규칙의 요지다.
{
  const one = rows.find((row) => row.mission === 'MSN-260831-01');
  if (one !== undefined && one.joins < one.goldJoins) {
    failures.push(`MSN-260831-01: 합류가 ${one.joins}개 — 정답은 ${one.goldJoins}개다. 규칙이 일렬로 무너졌다`);
  }
}

// ── 라벨이 없는 편 — 적용할 수 없다는 것을 확인한다 (실패가 아니다) ──────────
const unlabeled = gold.filter((mission) => !mission.shape.labeled).map((mission) => mission.mission_id);

// ── 4. 계약 — node_kind 는 선택 필드다 ───────────────────────────────────────
{
  const schema = JSON.parse(readFileSync(join(repoRoot, 'contracts', 'task.schema.json'), 'utf8'));
  const field = schema.properties?.node_kind;
  if (field === undefined) failures.push('task.schema.json 에 node_kind 가 없다 — 생성 결과를 계약으로 검증할 수 없다');
  else {
    const want = ['sense', 'decide', 'act', 'verify', 'report'];
    if (JSON.stringify(field.enum) !== JSON.stringify(want)) failures.push(`node_kind 의 허용 목록이 노드 문법 5종이 아니다 — ${JSON.stringify(field.enum)}`);
    if ((schema.required ?? []).includes('node_kind')) {
      failures.push('node_kind 가 필수 필드다 — 노드 분화 이전 편(MSN-260826-01)과 기존 예시가 통째로 무효가 된다');
    }
  }
}

// ── 대조군 — 규칙을 무력화한 사본이 반드시 잡혀야 한다 ───────────────────────
{
  const scratch = mkdtempSync(join(vizRoot, 'src', 'generate', '.verify-dep-'));
  try {
    const source = readFileSync(solverPath, 'utf8').replace("from '../model/types.ts'", "from '../../model/types.ts'");
    const mutants = [
      ['마일스톤 경계를 없앤 사본', source.replace('    if (order === 0) continue;', '    if (order >= 0) continue;')],
      ['sense 도 직전에 매다는 사본', source.replace('  sense: [],', "  sense: ['act', 'sense', 'decide', 'verify', 'report'],")],
      ['전이 축약을 없앤 사본', source.replace('      const viaOther = own.some((other) => other !== dep && ancestorsOf(other).has(dep));', '      const viaOther = false;')],
      ['경계를 「첫 노드만」으로 좁힌 사본', source.replace('      if (inBlock) continue;', '      if (inBlock || index !== block.indices[0]) continue;')],
    ];
    for (const [label, code] of mutants) {
      if (code === source) { failures.push(`대조군을 만들지 못했다 — ${label} (원본이 바뀌었나?)`); continue; }
      const path = join(scratch, `solveDeps-${controls.length}.ts`);
      writeFileSync(path, code, 'utf8');
      const mutant = await import(pathToFileURL(path).href);
      let detected;
      try {
        const mutantRows = reconstruct(mutant.solveDeps);
        // 「복원 수가 기준선과 다르다」로 잡는다 — 순환만 보면 대부분의 무력화를 놓친다.
        detected = mutantRows.some((row) => row.restored !== BASELINE[row.mission]?.restored || row.cycle);
      } catch { detected = true; }
      if (!detected) failures.push(`대조군 실패: ${label}이 통과했다 — 이 검사는 무의미하다`);
      else controls.push(label);
    }
  } finally {
    // 일부 개발 환경은 파일 삭제가 막혀 EPERM 이 난다 — 검사는 이미 끝났으므로 죽지 않는다.
    try { rmSync(scratch, { recursive: true, force: true }); } catch { console.warn('임시 디렉터리 정리 실패 — ' + scratch); }
  }
}

// ── 출력 ─────────────────────────────────────────────────────────────────────

for (const row of rows) {
  console.log(
    `   ${row.mission} — ${row.restored}/${row.tasks} 복원 · 합류 ${row.joins}(정답 ${row.goldJoins}) · ` +
    `규칙별 선행 ${row.byRule.upstream} · 자원 ${row.byRule.resource} · 경계 ${row.byRule['milestone-boundary']} · 축약 ${row.reduced}`,
  );
  for (const gap of row.gaps) {
    const known = KNOWN_GAPS.find((item) => item.mission === gap.mission && item.task === gap.task);
    console.log(`       ${gap.task}: 규칙 [${gap.rule.join(', ')}] · 정답 [${gap.gold.join(', ')}]${known ? ` — ${known.why}` : ' — 목록에 없다'}`);
  }
}
if (unlabeled.length > 0) {
  console.log(`   적용 불가 — ${unlabeled.join(', ')} (노드 분화 이전 편이라 node_kind 라벨이 없다. 지어내지 않는다)`);
}

// ── 되돌아가는 것을 **마일스톤 단위로 적을 수 있는가** (260908 · 분기와 되풀이 1단계) ──
//
// 계약에 `repeat_of` 를 열기 전에 답해야 하는 물음이 하나 있었다: **마일스톤 단위 표현이
// 사람이 손으로 적은 태스크 단위 엣지를 왜곡 없이 담는가.** 담지 못하면 그 계약은 표현이
// 아니라 근사이고, 그 위에서 잰 숫자는 무엇을 잰 것인지 말할 수 없다.
//
// 여기서 확인하는 것은 규칙이 아니라 **표현의 적합성**이다 — `solveDeps` 를 안 부른다.
// 규칙이 이것을 실제로 만들어 내는지는 2단계의 몫이고, 그때 이 자리가 그 정답이 된다.
//
// **정답셋이 아니라 대본을 읽는다.** `extract-goldset.mjs` 는 `refEdges` 를 일부러 안
// 뽑고 그 사유를 파일에 적어 두었다 — 「사람이 대본에 적은 것이고 생성 대상이 아니다(§5)」.
// 그 사유가 바로 이 작업이 고쳐 쓰는 결정이므로, 뽑을지 말지는 **생성이 실제로 그것을
// 만들기 시작하는 3단계**에서 정한다. 여기서는 원본을 본다.
{
  const scriptDir = join(vizRoot, 'scenarios');
  const scripts = readdirSync(scriptDir)
    .filter((name) => /^MSN-260831-\d+\.json$/.test(name))
    .map((name) => JSON.parse(readFileSync(join(scriptDir, name), 'utf8')));
  const withLoops = scripts.filter((mission) => (mission.refEdges ?? []).length > 0);
  if (withLoops.length === 0) {
    failures.push('되돌아가는 엣지를 가진 대본이 하나도 없다 — 표현 적합성을 확인할 원본이 사라졌다');
  }
  for (const mission of withLoops) {
    const tasksOf = (milestoneId) => mission.tasks.filter((task) => task.milestone === milestoneId).map((task) => task.id);
    for (const edge of mission.refEdges) {
      const fromMilestone = mission.tasks.find((task) => task.id === edge.from)?.milestone;
      const toMilestone = mission.tasks.find((task) => task.id === edge.to)?.milestone;
      if (fromMilestone === undefined || toMilestone === undefined) {
        failures.push(`${mission.missionId}: refEdge ${edge.from}→${edge.to} 의 태스크가 어느 마일스톤 것인지 모른다`);
        continue;
      }
      // 마일스톤 단위로 적은 것을 태스크로 펴는 규칙: **끝 노드 → 첫 노드.**
      const expanded = { from: tasksOf(fromMilestone).slice(-1)[0], to: tasksOf(toMilestone)[0] };
      if (expanded.from !== edge.from || expanded.to !== edge.to) {
        failures.push(
          `${mission.missionId}: 마일스톤 단위(${fromMilestone}→${toMilestone})를 펴면 ${expanded.from}→${expanded.to} 인데 `
          + `대본은 ${edge.from}→${edge.to} 다 — 마일스톤 단위 표현이 이 되돌아감을 담지 못한다`,
        );
      } else {
        console.log(`   ${mission.missionId} 되돌아감 — 마일스톤 ${fromMilestone}→${toMilestone} 를 펴면 ${edge.from}→${edge.to} · 대본과 같다`);
      }
    }
  }
}

if (failures.length) {
  console.error(`❌ verify:dep-rules\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
const total = rows.reduce((sum, row) => sum + row.tasks, 0);
const restored = rows.reduce((sum, row) => sum + row.restored, 0);
console.log(`✅ 순환 없음 — 대본 ${rows.length}편 + 무작위 목록 300건, 모든 엣지가 앞을 가리킨다`);
console.log(`✅ 복원 ${restored}/${total} — 기준선과 일치 · 못 복원한 ${KNOWN_GAPS.length}자리는 사유와 함께 못박혀 있다`);
console.log('✅ 합류가 살아 있다 (MSN-260831-01) — 병렬은 만들어지는 것이 아니라 제약이 없어서 남는다');
console.log('✅ 계약 — task.schema.json 의 node_kind 는 노드 문법 5종의 **선택** 필드다');
console.log('✅ 되돌아감을 마일스톤 단위로 적을 수 있다 — 펴면(끝 노드→첫 노드) 대본이 손으로 적은 엣지와 글자까지 같다');
console.log(`✅ 대조군 ${controls.length}건 검출 — ${controls.join(' · ')}`);
