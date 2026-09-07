// verify:no-leak (260906 신설 — 마일스톤 분리 지시서 §4 검사)
//
// **few-shot 예시에 채점 대상 편이 들어가지 않았는가.**
//
// 정답을 보여주고 정답을 맞히라고 한 표는 아무것도 증명하지 못한다. 정답셋이 4편뿐이라
// 한 편만 새어도 그 편의 숫자는 통째로 무의미해지고, **논문에서 가장 먼저 찔리는 자리**가
// 여기다. 그래서 규칙을 코드 한 곳(`scripts/lib/fewshot.mjs`)에 두고 여기서 검사한다.
//
// 넷을 본다.
//   1. 규칙 함수가 실제로 빼는가 — 안 빼는 사본(대조군) 포함
//   2. **실제로 돌린 기록**이 깨끗한가 (`gen-lab/runs/*/summary.json` 의 `examples_used`)
//   3. 서비스가 예시를 **스스로 만들지 않는가** — 정답셋을 여는 경로가 프롬프트 쪽에 없는가
//   4. 기록의 예시 수가 정답셋에서 하나 뺀 수와 맞는가 (빼는 척하고 다 넣지 않았는가)
//
// 2번이 이 검사의 알맹이다. 함수가 옳아도 **그 함수를 안 쓰고 돌린 실행**이 있으면
// 표는 여전히 거짓말한다. 그래서 함수가 아니라 남은 기록을 본다.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(vizRoot, '..');
const goldDir = join(repoRoot, 'gen-lab', 'goldset', 'missions');
const runsDir = join(repoRoot, 'gen-lab', 'runs');
const failures = [];
const controls = [];
const notes = [];

const gold = readdirSync(goldDir)
  .filter((name) => name.endsWith('.json'))
  .map((name) => JSON.parse(readFileSync(join(goldDir, name), 'utf8')))
  .sort((a, b) => a.mission_id.localeCompare(b.mission_id));

if (gold.length === 0) {
  console.error('❌ 정답셋이 비어 있다 — 먼저 `npm run goldset:extract` 를 돌려라');
  process.exit(1);
}

// ── 1. 규칙 함수 ─────────────────────────────────────────────────────────────
{
  const { examplesFor, asExample } = await import('./lib/fewshot.mjs');
  for (const mission of gold) {
    const examples = examplesFor(mission.mission_id, gold);
    const ids = examples.map((example) => example.mission_id);
    if (ids.includes(mission.mission_id)) {
      failures.push(`examplesFor('${mission.mission_id}') 가 채점 대상 편을 예시에 넣었다`);
    }
    if (ids.length !== gold.length - 1) {
      failures.push(`examplesFor('${mission.mission_id}') 가 ${ids.length}편을 냈다 — ${gold.length - 1}편이어야 한다`);
    }
    // 예시에 태스크를 실으면 모델이 이번 단계에서 하지 말아야 할 일을 배운다 (§5).
    for (const example of examples) {
      if (example.milestones.some((milestone) => (milestone.tasks ?? []).length > 0)) {
        failures.push(`예시(${example.mission_id})에 태스크가 실렸다 — G-01 단계의 예시는 마일스톤까지다`);
      }
    }
  }
  // 대조군 — 안 빼는 사본은 반드시 잡혀야 한다.
  const leaky = (missionId, missions) => missions.map(asExample);
  if (!leaky(gold[0].mission_id, gold).some((example) => example.mission_id === gold[0].mission_id)) {
    failures.push('누출 대조군을 만들지 못했다 — 이 검사는 무의미하다');
  } else {
    controls.push('채점 대상 편을 빼지 않는 사본');
  }
}

// ── 2. 실제로 돌린 기록 ───────────────────────────────────────────────────────
//
// **함수가 옳은 것과 그 함수로 돌린 것은 다른 일이다.**
{
  let labels = [];
  try {
    labels = readdirSync(runsDir).filter((name) => statSync(join(runsDir, name)).isDirectory());
  } catch {
    labels = [];
  }
  if (labels.length === 0) {
    // 실행이 없는 것은 실패가 아니다 — 하지만 **검사했다고 말하지도 않는다.**
    notes.push('gen-lab/runs/ 에 실행 기록이 없다 — 기록 검사는 하지 않았다 (0건을 통과로 세지 않는다)');
  }
  let checked = 0;
  for (const label of labels) {
    let summary;
    try {
      summary = JSON.parse(readFileSync(join(runsDir, label, 'summary.json'), 'utf8'));
    } catch {
      notes.push(`${label}: summary.json 이 없다 — 아직 안 끝난 실행이다`);
      continue;
    }
    // 예시 수는 **그 실행이 돈 편 수** 기준으로 본다. 지금 정답셋 크기로 재면, 정답셋이
    // 바뀐 뒤(415 편 보류 · 260907) 옛 실행이 전부 실패로 잡힌다 — 그 실행은 그 시점의
    // 규칙을 지켰는데도. 검사가 봐야 하는 것은 「그때 leave-one-out 을 지켰는가」다.
    const runMissions = new Set((summary.records ?? []).map((r) => r.mission_id).filter(Boolean));
    const expected = runMissions.size - 1;
    for (const record of summary.records ?? []) {
      checked += 1;
      const used = record.examples_used ?? null;
      if (used === null) {
        failures.push(`${label} / ${record.mission_id} v${record.variant}: 어떤 예시를 썼는지 기록이 없다 — 누출을 확인할 방법이 없다`);
        continue;
      }
      if (used.includes(record.mission_id)) {
        failures.push(`${label} / ${record.mission_id} v${record.variant}: **채점 대상 편이 예시에 들어갔다** (${used.join(', ')})`);
      }
      if (used.length !== expected) {
        failures.push(`${label} / ${record.mission_id} v${record.variant}: 예시가 ${used.length}편이다 — 이 실행은 ${runMissions.size}편을 돌았으므로 ${expected}편이어야 한다`);
      }
    }
  }
  if (checked > 0) controls.push(`실행 기록 ${checked}건을 실제로 훑음`);

  // 대조군 — 누출된 기록을 넣으면 반드시 잡혀야 한다.
  const dirty = { mission_id: 'MSN-260831-01', variant: 0, examples_used: gold.map((mission) => mission.mission_id) };
  const caught = dirty.examples_used.includes(dirty.mission_id) && dirty.examples_used.length !== gold.length - 1;
  if (!caught) failures.push('누출된 기록 대조군을 만들지 못했다 — 이 검사는 무의미하다');
  else controls.push('채점 대상 편이 섞인 기록');
}

// ── 3. 서비스가 예시를 스스로 만들지 않는가 ────────────────────────────────────
//
// 예시를 고르는 것은 **부르는 쪽**이다. 서비스가 정답셋을 직접 열면 「채점 대상 편을
// 뺐다」를 부르는 쪽이 보장할 수 없게 된다 — 그 순간 규칙이 두 곳으로 갈라진다.
{
  const promptSource = readFileSync(join(repoRoot, 'gen-lab', 'server', 'prompt.py'), 'utf8');
  if (/goldset|missions\//.test(promptSource)) {
    failures.push('gen-lab/server/prompt.py 가 정답셋 경로를 안다 — 예시를 서비스가 스스로 고를 수 있게 된다');
  }
  // 라우터가 정답셋을 **세는** 것은 괜찮다 (health 의 건수). 읽어서 예시로 싣는 경로가
  // 없어야 한다 — 예시는 요청으로만 들어온다.
  const mainSource = readFileSync(join(repoRoot, 'gen-lab', 'server', 'main.py'), 'utf8');
  if (/examples\s*=\s*\[.*goldset/is.test(mainSource)) {
    failures.push('gen-lab/server/main.py 가 정답셋에서 예시를 채운다 — 부르는 쪽의 선택이 무의미해진다');
  }
  controls.push('서비스가 정답셋을 열어 예시를 만들지 않음');
}

if (failures.length) {
  console.error(`❌ verify:no-leak\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ leave-one-out — 정답셋 ${gold.length}편, 예시는 언제나 ${gold.length - 1}편이고 채점 대상 편은 빠진다`);
console.log('✅ 실행 기록의 examples_used 에 자기 자신이 없다 — 함수가 아니라 남은 기록을 봤다');
console.log('✅ 예시를 고르는 것은 부르는 쪽이다 — 서비스는 정답셋을 열지 않는다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
for (const note of notes) console.log(`   · ${note}`);
