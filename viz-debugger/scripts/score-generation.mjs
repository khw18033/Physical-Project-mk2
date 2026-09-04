// scripts/score-generation.mjs (260904 신설 — 마일스톤 분리 지시서 §2)
//
// 생성 결과를 **네 축으로 따로** 잰다. 합산 점수 하나로 뭉치지 않는다.
//
// | 축 | 무엇을 | G-01 | G-02 |
// |---|---|---|---|
// | 스키마   | mission.schema.json 을 통과하는가        | ○ | ○ |
// | 마일스톤 | 개수 · 순서 · 장소 어휘가 정답과 맞는가    | ○ | — |
// | 노드 문법 | node_kind 라벨이 정답과 맞는가           | — | ○ |
// | 그래프   | deps 가 만드는 DAG 가 동형인가 · 순환 없나 | — | ○ |
//
// **축을 섞으면 실패 원인을 못 가른다.** 「형식 오류인가 내용 오류인가」가 학습 판단의
// 근거이므로(지시서 §학습 판단 관문) 여기서 갈라 두지 않으면 4단계에서 가를 수 없다.
//
// ## 재는 것이 아니라 못 재는 것도 적는다
//
// 「장소 어휘」는 `places.json` 이 원본인데 그 파일은 아직 비어 있다(Unity 미연결).
// 그래서 이 축은 **0이 아니라 `null` 이고 사유가 붙는다** — 자체 관측 패널과 같은 규칙이다.
//
// ## 실행
//
//   node scripts/score-generation.mjs                 정답셋을 자기 자신으로 채점 + 대조군
//   node scripts/score-generation.mjs --candidate x   생성 결과 파일(또는 폴더)을 채점
//   node scripts/score-generation.mjs --json          기계가 읽는 형태로
//
// 이것은 **측정 도구**다(`measure:representation` 과 같은 성질). 점수가 낮다고 실패로
// 끝내지 않는다 — 낮은 것 자체가 결과다. 다만 **대조군**은 다르다: 망가뜨린 사본이
// 축에 안 걸리면 그 축은 무의미하므로 그때만 1로 끝낸다.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadContracts, validate } from './lib/json-schema.mjs';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(vizRoot, '..');
const goldDir = join(repoRoot, 'gen-lab', 'goldset', 'missions');
const contracts = loadContracts(join(repoRoot, 'contracts'));
const missionSchema = contracts.get('mission.schema.json');

const args = process.argv.slice(2);
const candidateArg = args.includes('--candidate') ? args[args.indexOf('--candidate') + 1] : null;
const asJson = args.includes('--json');

// ── 정답셋 ───────────────────────────────────────────────────────────────────

const gold = readdirSync(goldDir)
  .filter((name) => name.endsWith('.json'))
  .map((name) => JSON.parse(readFileSync(join(goldDir, name), 'utf8')))
  .sort((a, b) => a.mission_id.localeCompare(b.mission_id));

if (gold.length === 0) {
  console.error('❌ 정답셋이 비어 있다 — 먼저 `npm run goldset:extract` 를 돌려라');
  process.exit(1);
}

/**
 * 장소 어휘의 원본. **비어 있으면 그 축은 못 잰다** — 지어내지 않는다.
 * Unity 맵 추출(지시서 §1)이 채운다.
 */
function placeVocabulary() {
  try {
    const raw = JSON.parse(readFileSync(join(repoRoot, 'places', 'places.json'), 'utf8'));
    const names = [];
    for (const place of raw.places ?? []) {
      names.push(place.label, ...(place.aliases ?? []));
    }
    return names.filter((name) => typeof name === 'string' && name.length > 0);
  } catch {
    return [];
  }
}

// ── 정답셋 → 계약 모양 ────────────────────────────────────────────────────────

/**
 * 정답셋을 `mission.schema.json` 이 요구하는 모양으로 편다.
 *
 * 정답셋은 **모델이 내야 하는 것**만 담고 있어서 계약의 필수 항목(status·attempt·
 * action_items·evaluation)이 없다. 그것들은 실행이 채우는 값이라 정답이 아니고, 그래서
 * 여기서 **계약이 요구하는 최소값으로 채운다** — 생성기도 같은 자리를 같은 값으로 낸다.
 */
export function toContract(mission) {
  return {
    mission_id: mission.mission_id,
    utterance: {
      audio_ref: mission.utterance.audio_ref,
      text: mission.utterance.text,
      engine: mission.utterance.engine,
      confidence: mission.utterance.confidence,
    },
    milestones: mission.milestones.map((milestone) => ({
      milestone_id: milestone.milestone_id,
      title: milestone.title,
      order: milestone.order,
      status: 'pending',
      assigned_targets: milestone.assigned_targets,
      tasks: mission.tasks
        .filter((task) => task.milestone_id === milestone.milestone_id)
        .map((task) => ({
          task_id: task.task_id,
          title: task.title,
          deps: task.deps,
          status: 'pending',
          attempt: 1,
          derived_from: milestone.milestone_id,
          action_items: [],
          evaluation: null,
          // 노드 문법 라벨. **계약의 선택 필드다** (§5 에서 올렸다) — 없는 편도 있다.
          ...(task.node_kind === null ? {} : { node_kind: task.node_kind }),
        })),
    })),
  };
}

// ── 문자열 비교 — 한국어라 어절이 아니라 글자 2-gram 이다 ────────────────────

function bigrams(text) {
  const clean = String(text).replace(/[\s·,.()→\-]/g, '');
  if (clean.length <= 1) return new Set([clean]);
  const out = new Set();
  for (let i = 0; i < clean.length - 1; i += 1) out.add(clean.slice(i, i + 2));
  return out;
}

/** 0~1. 어절 나눔이 들쭉날쭉한 한국어 제목에는 어절 집합보다 2-gram 이 안정적이다. */
function similarity(a, b) {
  const left = bigrams(a);
  const right = bigrams(b);
  if (left.size === 0 || right.size === 0) return a === b ? 1 : 0;
  let hit = 0;
  for (const gram of left) if (right.has(gram)) hit += 1;
  return (2 * hit) / (left.size + right.size);
}

/**
 * 정답 목록과 후보 목록을 **순서를 지키며** 짝짓는다 (단조 정렬).
 * 순서를 무시하고 최적 매칭을 하면 「순서가 틀렸다」를 영영 못 잰다.
 */
function alignInOrder(goldItems, gotItems, key, threshold = 0.4) {
  const pairs = [];
  let cursor = 0;
  for (let g = 0; g < goldItems.length; g += 1) {
    let best = -1;
    let bestScore = threshold;
    for (let c = cursor; c < gotItems.length; c += 1) {
      const score = similarity(key(goldItems[g]), key(gotItems[c]));
      if (score > bestScore) { bestScore = score; best = c; }
    }
    if (best >= 0) {
      pairs.push({ gold: goldItems[g], got: gotItems[best], score: bestScore });
      cursor = best + 1;
    } else {
      pairs.push({ gold: goldItems[g], got: null, score: 0 });
    }
  }
  return pairs;
}

const mean = (values) => (values.length === 0 ? null : values.reduce((a, b) => a + b, 0) / values.length);
const round = (value, digits = 3) => (value === null ? null : Math.round(value * 10 ** digits) / 10 ** digits);

// ── 축 넷 ────────────────────────────────────────────────────────────────────

/** 축 1 — 스키마. 강제 디코딩이 실제로 듣는가. */
function axisSchema(candidate) {
  const result = validate(candidate, missionSchema, contracts);
  return {
    pass: result.ok,
    errors: result.errors.slice(0, 6),
    error_count: result.errors.length,
    unsupported: result.unsupported.slice(0, 3),
  };
}

/** 축 2 — 마일스톤 (G-01 본문). 개수 · 순서 · 장소 어휘. */
function axisMilestone(goldMission, candidate, vocabulary) {
  const goldList = goldMission.milestones;
  const gotList = candidate.milestones ?? [];
  const pairs = alignInOrder(goldList, gotList, (item) => item.title);
  const matched = pairs.filter((pair) => pair.got !== null);
  /**
   * 장소 어휘 — **정답 마일스톤이 말한 장소를 후보도 말했는가.**
   *
   * 「없는 장소를 지어냈는가」(위반 건수)는 여기서 못 잰다. 자유 문장에서 장소를 집어내려면
   * 장소 인식이 필요한데 그건 이 채점기의 일이 아니다 — 4단계에서 생성기가 장소를
   * **필드로** 내게 하고 그때 센다. 지금 재는 것은 재현율 하나이고, 그 사실을 적어 둔다.
   */
  const placePairs = vocabulary.length === 0 ? [] : matched.map((pair) => {
    const want = vocabulary.filter((name) => String(pair.gold.title).includes(name));
    if (want.length === 0) return null;
    const got = want.filter((name) => String(pair.got.title).includes(name));
    return got.length / want.length;
  }).filter((value) => value !== null);
  return {
    count: { gold: goldList.length, got: gotList.length, match: goldList.length === gotList.length },
    order_recall: round(matched.length / Math.max(1, goldList.length)),
    title_similarity: round(mean(matched.map((pair) => pair.score))),
    place_recall: vocabulary.length === 0 ? null : round(mean(placePairs)),
    place_vocab_note: vocabulary.length === 0
      ? '해당 없음 — places/places.json 이 비어 있다 (Unity 맵 추출 §1 대기). 빈칸에 0을 넣지 않는다'
      : '재현율만 잰다 — 「없는 장소를 지어냈는가」는 생성기가 장소를 필드로 낼 때(4단계) 센다',
    unmatched: pairs.filter((pair) => pair.got === null).map((pair) => pair.gold.milestone_id),
  };
}

/**
 * 마일스톤 정렬을 받아 태스크까지 짝짓는다. 축 3·4 가 같은 정렬을 써야
 * 「라벨이 틀린 것」과 「자리가 밀린 것」이 섞이지 않는다.
 */
function alignTasks(goldMission, candidate) {
  const pairs = alignInOrder(goldMission.milestones, candidate.milestones ?? [], (item) => item.title);
  const taskPairs = [];
  for (const pair of pairs) {
    const goldTasks = goldMission.tasks.filter((task) => task.milestone_id === pair.gold.milestone_id);
    const gotTasks = pair.got === null ? [] : pair.got.tasks ?? [];
    for (const [index, task] of goldTasks.entries()) {
      taskPairs.push({ gold: task, got: gotTasks[index] ?? null });
    }
  }
  return taskPairs;
}

/** 축 3 — 노드 문법. 라벨이 없는 편(옛 편)은 잴 수 없다. */
function axisNodeGrammar(goldMission, taskPairs) {
  if (!goldMission.shape.labeled) {
    return {
      accuracy: null,
      note: `해당 없음 — ${goldMission.mission_id} 의 대본에 node_kind 라벨이 없다 (노드 분화 이전 편)`,
    };
  }
  const scored = taskPairs.filter((pair) => pair.gold.node_kind !== null);
  const hit = scored.filter((pair) => pair.got !== null && pair.got.node_kind === pair.gold.node_kind);
  const confusion = {};
  for (const pair of scored) {
    const got = pair.got?.node_kind ?? '(없음)';
    if (got === pair.gold.node_kind) continue;
    const key = `${pair.gold.node_kind}→${got}`;
    confusion[key] = (confusion[key] ?? 0) + 1;
  }
  return { accuracy: round(hit.length / Math.max(1, scored.length)), scored: scored.length, confusion, note: null };
}

/** 축 4 — 그래프. deps 가 만드는 DAG 가 동형인가 · 순환이 없는가. */
function axisGraph(goldMission, candidate, taskPairs) {
  const map = new Map();
  for (const pair of taskPairs) if (pair.got !== null) map.set(pair.got.task_id, pair.gold.task_id);

  const goldEdges = new Set();
  for (const task of goldMission.tasks) for (const dep of task.deps) goldEdges.add(`${dep}→${task.task_id}`);

  const gotEdges = new Set();
  const gotTasks = (candidate.milestones ?? []).flatMap((milestone) => milestone.tasks ?? []);
  for (const task of gotTasks) {
    for (const dep of task.deps ?? []) {
      // 정렬로 정답 id 를 알아낸 것만 비교할 수 있다. 못 찾으면 그대로 두어 **틀린 엣지로 남긴다.**
      gotEdges.add(`${map.get(dep) ?? dep}→${map.get(task.task_id) ?? task.task_id}`);
    }
  }

  let hit = 0;
  for (const edge of gotEdges) if (goldEdges.has(edge)) hit += 1;
  const precision = gotEdges.size === 0 ? (goldEdges.size === 0 ? 1 : 0) : hit / gotEdges.size;
  const recall = goldEdges.size === 0 ? 1 : hit / goldEdges.size;

  return {
    exact: hit === goldEdges.size && gotEdges.size === goldEdges.size,
    precision: round(precision),
    recall: round(recall),
    f1: round(precision + recall === 0 ? 0 : (2 * precision * recall) / (precision + recall)),
    has_cycle: hasCycle(gotTasks),
    missing: [...goldEdges].filter((edge) => !gotEdges.has(edge)).slice(0, 8),
    extra: [...gotEdges].filter((edge) => !goldEdges.has(edge)).slice(0, 8),
  };
}

function hasCycle(tasks) {
  const deps = new Map(tasks.map((task) => [task.task_id, task.deps ?? []]));
  const state = new Map();
  const visit = (id) => {
    if (state.get(id) === 'done') return false;
    if (state.get(id) === 'open') return true;
    state.set(id, 'open');
    for (const dep of deps.get(id) ?? []) if (deps.has(dep) && visit(dep)) return true;
    state.set(id, 'done');
    return false;
  };
  return [...deps.keys()].some((id) => visit(id));
}

// ── 채점 ─────────────────────────────────────────────────────────────────────

export function score(candidates, vocabulary = placeVocabulary()) {
  return gold.map((goldMission) => {
    const candidate = candidates.find((item) => item.mission_id === goldMission.mission_id) ?? null;
    if (candidate === null) {
      return { mission_id: goldMission.mission_id, missing: true };
    }
    const taskPairs = alignTasks(goldMission, candidate);
    return {
      mission_id: goldMission.mission_id,
      missing: false,
      schema: axisSchema(candidate),
      milestone: axisMilestone(goldMission, candidate, vocabulary),
      node_grammar: axisNodeGrammar(goldMission, taskPairs),
      graph: axisGraph(goldMission, candidate, taskPairs),
    };
  });
}

function loadCandidates(target) {
  const path = join(process.cwd(), target);
  const stat = statSync(path);
  const files = stat.isDirectory()
    ? readdirSync(path).filter((name) => name.endsWith('.json')).map((name) => join(path, name))
    : [path];
  return files.flatMap((file) => {
    const parsed = JSON.parse(readFileSync(file, 'utf8'));
    return Array.isArray(parsed) ? parsed : [parsed];
  });
}

const selfCandidates = gold.map(toContract);
const candidates = candidateArg === null ? selfCandidates : loadCandidates(candidateArg);
const results = score(candidates);

// ── 대조군 — 축이 실제로 잡는가 ──────────────────────────────────────────────
//
// 정답을 그대로 넣으면 네 축이 다 만점이라, 그것만으로는 **채점기가 아무것도 안 하는
// 경우**와 구별되지 않는다. 그래서 축마다 하나씩 망가뜨려 그 축만 떨어지는지 본다.

function damaged(kind) {
  const copy = JSON.parse(JSON.stringify(selfCandidates));
  const target = copy.find((mission) => mission.mission_id === 'MSN-260831-01');
  if (kind === 'schema') target.milestones[0].order = '첫째';           // 타입 위반
  if (kind === 'milestone') target.milestones.splice(2, 1);              // 마일스톤 하나 삭제
  if (kind === 'node_grammar') target.milestones[0].tasks[0].node_kind = 'report'; // 라벨 오염
  if (kind === 'graph') {
    // 순환을 만든다 — 모델이 deps 를 직접 내면 실제로 나는 실패다.
    const tasks = target.milestones[0].tasks;
    tasks[0].deps = [tasks[tasks.length - 1].task_id];
  }
  return copy;
}

const controlFailures = [];
const controls = [];
for (const kind of ['schema', 'milestone', 'node_grammar', 'graph']) {
  const before = results.find((item) => item.mission_id === 'MSN-260831-01');
  const after = score(damaged(kind)).find((item) => item.mission_id === 'MSN-260831-01');
  const caught = {
    // **기준선이 이미 통과하지 않아도 잡아야 한다.** 「통과 → 실패」로만 재면 다른 이유로
    // 이미 실패 중일 때 이 대조군이 조용히 무의미해진다 (지금이 그 상황이다 — node_kind).
    schema: () => after.schema.error_count > before.schema.error_count,
    milestone: () => before.milestone.count.match && !after.milestone.count.match,
    node_grammar: () => (after.node_grammar.accuracy ?? 1) < (before.node_grammar.accuracy ?? 0),
    graph: () => !before.graph.has_cycle && after.graph.has_cycle,
  }[kind]();
  if (caught) controls.push(kind);
  else controlFailures.push(`${kind} 축이 망가뜨린 사본을 잡지 못했다 — 그 축은 무의미하다`);
}

// ── 출력 ─────────────────────────────────────────────────────────────────────

if (asJson) {
  console.log(JSON.stringify({ source: candidateArg ?? '(정답셋 자기 채점)', results, controls, controlFailures }, null, 2));
} else {
  console.log(`채점 대상 — ${candidateArg ?? '정답셋 자기 채점 (축이 연결돼 있는지 보는 기준선)'}`);
  console.log('');
  const cell = (value, width) => (value === null ? '해당없음' : value.toFixed(2)).padStart(width);
  const head = (text, width) => text.padStart(width);
  console.log('  ' + '임무'.padEnd(16) + head('스키마', 10) + head('마일 개수', 11) + head('마일 순서', 10) + head('문법', 9) + head('그래프 F1', 10) + head('순환', 7));
  for (const row of results) {
    if (row.missing) { console.log('  ' + row.mission_id.padEnd(16) + '(결과 없음)'); continue; }
    console.log('  ' + row.mission_id.padEnd(16) +
      (row.schema.pass ? '통과' : `실패 ${row.schema.error_count}`).padStart(10) +
      `${row.milestone.count.got}/${row.milestone.count.gold}${row.milestone.count.match ? '' : ' ✗'}`.padStart(11) +
      cell(row.milestone.order_recall, 10) +
      cell(row.node_grammar.accuracy, 9) +
      cell(row.graph.f1, 10) +
      (row.graph.has_cycle ? '있음' : '없음').padStart(7));
  }
  console.log('');
  console.log('축별로 못 잰 것 — 0이 아니라 「해당 없음」이다');
  const seen = new Set();
  for (const row of results) {
    if (row.missing) continue;
    for (const note of [row.milestone.place_vocab_note, row.node_grammar.note]) {
      if (note && !seen.has(note)) { seen.add(note); console.log('  - ' + note); }
    }
  }
  for (const row of results) {
    if (row.missing || row.schema.pass) continue;
    console.log('');
    console.log(`스키마 실패 — ${row.mission_id} (${row.schema.error_count}건, 앞 ${row.schema.errors.length}건)`);
    for (const error of row.schema.errors) console.log('    ' + error);
  }
  console.log('');
  console.log(`대조군 ${controls.length}/4 검출 — ${controls.join(' · ')}`);
}

if (controlFailures.length > 0) {
  console.error(`❌ 대조군 실패:\n- ${controlFailures.join('\n- ')}`);
  process.exit(1);
}
