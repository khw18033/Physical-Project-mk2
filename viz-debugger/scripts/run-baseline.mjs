// scripts/run-baseline.mjs (260906 신설 — 마일스톤 분리 지시서 §4)
//
// `VZ-G-01` 베이스라인을 **CLI 로** 돌린다. 화면에 붙이기 전에 숫자가 나와야 한다 —
// 붙인 뒤에 실패하면 모델 탓인지 붙이는 코드 탓인지 가를 수 없다.
//
// ## 무엇을 도는가
//
//   모델 × 임무 4편 × 발화 5개(원본 1 + 변형 4) = 모델당 20건
//
// 발화 변형이 축의 하나다. **마일스톤 정답은 원본과 같으므로**(goldset/utterances.json)
// 같은 임무를 다른 말로 했을 때 같은 마일스톤이 나오는지가 표현 강건성이다.
//
// ## few-shot 은 leave-one-out 이다 — 여기가 누출이 나는 자리
//
// 채점 대상인 편을 예시에 넣으면 정답을 보여주고 정답을 맞히라고 하는 것이 된다.
// **논문에서 가장 먼저 찔리는 자리**이므로 규칙을 코드 한 곳(`examplesFor`)에 두고
// `verify:no-leak` 이 그 함수를 실제로 불러 검사한다.
//
// ## 부르는 길은 LlmClient 하나다
//
// 이 스크립트도 `src/generate/LlmClient.ts` 를 통해 부른다. 여기서 주소를 직접 알면
// 생성 주소를 아는 면이 둘이 되고, 그것이 `verify:gen-port` 가 막는 것이다.
//
// ## 실행
//
//   node scripts/run-baseline.mjs --model Qwen3-8B-Q4_K_M
//   node scripts/run-baseline.mjs --model X --no-grammar      문법 없는 대조군
//   node scripts/run-baseline.mjs --model X --no-equipment    장비 목록 없는 대조판 (7단계 A)
//   node scripts/run-baseline.mjs --model X --no-examples     예시 0편 (7단계 C)
//   node scripts/run-baseline.mjs --model X --limit 2         빠른 확인용
//   node scripts/run-baseline.mjs --rescore                   이미 낸 결과를 다시 채점만
//
// ## 끄는 스위치가 셋인 이유 — 하나씩 꺼야 원인이 갈린다
//
// `--no-grammar` 는 「강제 디코딩이 실제로 듣는가」를, `--no-equipment` 는 「장비 목록이
// 위반을 줄이는가」를, `--no-examples` 는 「개수 일치가 실력인가 예시를 베낀 것인가」를
// 답한다. **한 번에 하나만 끈다.** 둘을 같이 끄면 그 판의 숫자는 두 원인 중 어느 쪽에도
// 돌릴 수 없고, 돌릴 수 없는 숫자는 표에 올릴 수 없다.
//
// `--rescore` 가 있는 이유: 채점기에 축이 붙으면 옛 실행의 숫자에 그 축이 없다. 그때
// **모델을 다시 돌리면 안 된다** — 같은 출력을 다시 뽑는 데 시간을 쓰는 것도 문제지만,
// 재생성하면 「이 표의 출력이 그때 그 출력인가」가 흐려진다. 출력은 그대로 두고 채점만
// 다시 한다.
//
// 결과는 `gen-lab/runs/<이름>/` 에 쌓이고 채점은 `score-generation.mjs` 가 한다 —
// **축의 정의를 두 벌로 두지 않는다.**
import { execFileSync } from 'node:child_process';
// **누출을 막는 규칙은 여기 있지 않다** — scripts/lib/fewshot.mjs 한 곳이고,
// `verify:no-leak` 이 그 파일을 직접 불러 검사한다.
import { examplesFor } from './lib/fewshot.mjs';
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(vizRoot, '..');
const goldDir = join(repoRoot, 'gen-lab', 'goldset', 'missions');
const runsDir = join(repoRoot, 'gen-lab', 'runs');

const args = process.argv.slice(2);
const flag = (name, fallback = null) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback);
const model = flag('--model');
const enforceGrammar = !args.includes('--no-grammar');
// 7단계의 두 축. **한 번에 하나만 끈다** — 둘을 같이 끄면 어느 쪽 덕인지 못 가른다.
const giveEquipment = !args.includes('--no-equipment');
const shots = args.includes('--no-examples') ? 'none' : 'leave-one-out';
const limit = Number(flag('--limit', '0')) || 0;
const rescoreOnly = args.includes('--rescore');
// 이름이 **설정을 말한다.** 6단계에 유령 llama-server 로 표가 한 번 무효가 됐고, 그때
// 배운 것이 「기록이 스스로를 설명해야 한다」였다. 끈 것이 있으면 이름에 남는다.
const suffix = `${enforceGrammar ? '' : '__nogrammar'}${giveEquipment ? '' : '__noequip'}${shots === 'none' ? '__noshot' : ''}`;
const label = flag('--label', model ? `${model}${suffix}` : null);

if (model === null && !rescoreOnly) {
  console.error('❌ --model 이 필요하다. 무엇을 쟀는지 모르는 숫자는 쓸 수 없다.');
  console.error('   쓸 수 있는 이름은 http://127.0.0.1:8802/generate/health 의 models 에 있다.');
  process.exit(1);
}

// ── 재료 ─────────────────────────────────────────────────────────────────────

const gold = readdirSync(goldDir)
  .filter((name) => name.endsWith('.json'))
  .map((name) => JSON.parse(readFileSync(join(goldDir, name), 'utf8')))
  .sort((a, b) => a.mission_id.localeCompare(b.mission_id));

const variants = JSON.parse(readFileSync(join(repoRoot, 'gen-lab', 'goldset', 'utterances.json'), 'utf8'));

/**
 * 장소 위상. **기하 파일을 읽지 않는다** — 좌표를 보면 모델이 503호 전용이 된다
 * (지시서 §1 · `verify:places` 4번 검사가 이 경로를 훑는다).
 */
const places = JSON.parse(readFileSync(join(repoRoot, 'places', 'places.json'), 'utf8'));

/**
 * 장비 어휘. **장소와 같은 자리의 재료**다 — 260906 에 목록을 준 축은 위반 0건이고
 * 안 준 축은 22~48% 였다(6단계 §4 축 3).
 *
 * `--no-equipment` 로 끄면 프롬프트에 규칙도 목록도 안 붙어 6단계와 같은 프롬프트가 된다.
 * 그 판이 있어야 차이를 장비 목록에 돌릴 수 있다.
 */
const equipment = giveEquipment
  ? JSON.parse(readFileSync(join(repoRoot, 'equipment', 'equipment.json'), 'utf8'))
  : null;

/** 원본 발화 + 손으로 적은 변형. 마일스톤 정답은 전부 원본과 같다. */
function utterancesFor(missionId, mission) {
  const entry = (variants.missions ?? []).find((item) => item.mission_id === missionId);
  return [mission.utterance.text, ...(entry?.variants ?? [])];
}

// ── 실행 ─────────────────────────────────────────────────────────────────────

/**
 * 채점 — **축의 정의는 `score-generation.mjs` 하나다.** 여기서 다시 계산하지 않는다.
 * 축을 두 곳에 적으면 표와 채점기가 조용히 갈라진다.
 */
function writeSummary(root, { model: modelName, label: runLabel, grammar_enforced, equipment_given, shots: runShots, records: rows }) {
  const scored = [];
  for (const dir of readdirSync(root).filter((name) => /^v\d+$/.test(name)).sort()) {
    const out = execFileSync(process.execPath, [join(vizRoot, 'scripts', 'score-generation.mjs'), '--candidate', join(root, dir), '--json'], {
      encoding: 'utf8', cwd: vizRoot, maxBuffer: 64 * 1024 * 1024,
    });
    scored.push({ variant: dir, results: JSON.parse(out).results });
  }
  const previous = (() => {
    try { return JSON.parse(readFileSync(join(root, 'summary.json'), 'utf8')); } catch { return null; }
  })();
  writeFileSync(join(root, 'summary.json'), JSON.stringify({
    model: modelName,
    label: runLabel,
    grammar_enforced,
    // **판을 파일이 스스로 말한다.** 이름만으로 설명하면 이름을 바꾼 순간 설명이 사라진다.
    equipment_given,
    shots: runShots,
    // **생성한 시각은 그대로 두고 채점한 시각만 갱신한다** — 다시 채점했다고 해서
    // 출력이 새로 난 것이 아니다. 그 둘을 한 칸에 적으면 기록이 거짓말한다.
    ran_at: previous?.ran_at ?? new Date().toISOString(),
    scored_at: new Date().toISOString(),
    calls: rows.length,
    records: rows,
    scored,
  }, null, 2), 'utf8');
}

if (rescoreOnly) {
  // 출력은 손대지 않는다. 채점만 다시 한다.
  //
  // **정답셋이 바뀐 실행은 건너뛴다.** 다시 채점하면 그 실행이 그때 예시로 받았던 장비가
  // 갑자기 위반이 되고(어휘가 정답셋에서 온다), 모델이 나빠진 것처럼 보이는 표가 나온다.
  // 눈금이 바뀐 자로 옛 길이를 다시 재는 것이다 — **다시 채점이 아니라 다시 돌려야 한다.**
  const goldIds = new Set(gold.map((m) => m.mission_id));
  let skipped = 0;
  for (const name of readdirSync(runsDir)) {
    const root = join(runsDir, name);
    let previous;
    try { previous = JSON.parse(readFileSync(join(root, 'summary.json'), 'utf8')); } catch { continue; }
    const runIds = new Set((previous.records ?? []).map((r) => r.mission_id).filter(Boolean));
    const same = runIds.size === goldIds.size && [...runIds].every((id) => goldIds.has(id));
    if (!same) {
      console.log(`  건너뜀 — ${name}: ${runIds.size}편으로 돌았는데 지금 정답셋은 ${goldIds.size}편이다. 다시 채점하지 않는다 (다시 돌려라)`);
      skipped += 1;
      continue;
    }
    writeSummary(root, {
      model: previous.model, label: previous.label,
      grammar_enforced: previous.grammar_enforced,
      // 다시 채점하는 것이지 다시 도는 것이 아니다 — 그때의 판을 그대로 옮긴다.
      equipment_given: previous.equipment_given ?? false,
      shots: previous.shots ?? 'leave-one-out',
      records: previous.records,
    });
    console.log(`  다시 채점 — ${name} (${previous.records.length}건, 출력은 그대로)`);
  }
  if (skipped > 0) console.log(`  ${skipped}개 실행을 건너뛰었다 — 정답셋이 그때와 다르다.`);
  process.exit(0);
}

const { generateMission } = await import('../src/generate/LlmClient.ts');

const outRoot = join(runsDir, label);

/**
 * **설정이 다른 실행을 조용히 덮어쓰지 않는다.**
 *
 * 이 자리는 `rmSync` 다 — 같은 이름이면 지우고 다시 쓴다. 그래서 `--label` 을 빼먹은
 * 한 줄이 6단계의 8B 기록을 통째로 지울 수 있고, 지워진 뒤에는 표가 무엇과 무엇을
 * 비교했는지 아무도 모른다. 유령 `llama-server` 가 표를 한 번 무효로 만든 것과 같은
 * 종류의 사고이고, 그때 배운 것은 「기록을 못 믿게 되면 그 뒤가 전부 무의미하다」였다.
 *
 * 그래서 **덮어쓰기 자체를 막지는 않되**(같은 설정을 다시 돌리는 것은 정상이다)
 * 설정이 다르면 멈춘다. 다시 돌릴 사람은 이름을 주면 된다.
 */
const config = { model, grammar_enforced: enforceGrammar, equipment_given: giveEquipment, shots };
try {
  const previous = JSON.parse(readFileSync(join(outRoot, 'summary.json'), 'utf8'));
  const before = {
    model: previous.model,
    grammar_enforced: previous.grammar_enforced,
    // 옛 실행에는 이 두 칸이 없다 — 그때는 장비 목록도 예시 0편도 없었다(6단계).
    equipment_given: previous.equipment_given ?? false,
    shots: previous.shots ?? 'leave-one-out',
  };
  const differs = Object.keys(config).filter((key) => config[key] !== before[key]);
  if (differs.length) {
    console.error(`❌ ${label} 에 설정이 다른 실행이 이미 있다 — 지우고 덮어쓰지 않는다.`);
    for (const key of differs) console.error(`   ${key}: 기존 ${JSON.stringify(before[key])} → 지금 ${JSON.stringify(config[key])}`);
    console.error('   --label 로 다른 이름을 주거나, 그 기록이 정말 필요 없으면 폴더를 손으로 지워라.');
    process.exit(1);
  }
} catch { /* 없으면 새 실행이다 */ }

rmSync(outRoot, { recursive: true, force: true });
mkdirSync(join(outRoot, 'raw'), { recursive: true });

const records = [];
const targets = limit > 0 ? gold.slice(0, limit) : gold;

console.log(`베이스라인 — model=${model} · 문법=${enforceGrammar ? '강제' : '없음(대조군)'} · 임무 ${targets.length}편`);
console.log(`             장비 목록=${equipment ? `${equipment.equipment.length}건` : '없음'} · 예시=${shots === 'none' ? '0편' : `${targets.length - 1}편(leave-one-out)`} · 이름=${label}`);
console.log('');

for (const mission of targets) {
  const examples = examplesFor(mission.mission_id, gold, shots);
  const texts = utterancesFor(mission.mission_id, mission);
  for (const [index, text] of texts.entries()) {
    const started = Date.now();
    let result = null;
    let failure = null;
    try {
      result = await generateMission(text, {
        places,
        equipment,
        examples,
        model,
        missionId: mission.mission_id,
        // 대본 유래라 인식 수치가 없다 — `confidence_signals` 없이 간다 (§7.8 규칙 2).
        utteranceMeta: mission.utterance,
        enforceGrammar,
        maxTokens: 2048,
        temperature: 0,
        seed: 0,
      });
    } catch (error) {
      // **삼키지 않는다.** 서비스가 죽은 것과 모델이 못 낸 것은 다른 일이고,
      // 둘을 같은 빈칸으로 적으면 표가 거짓말을 한다.
      failure = String(error?.message ?? error);
    }
    const wall = (Date.now() - started) / 1000;
    const variantDir = join(outRoot, `v${index}`);
    mkdirSync(variantDir, { recursive: true });

    const record = {
      mission_id: mission.mission_id,
      variant: index,
      utterance: text,
      ok: failure === null,
      failure,
      wall_sec: Number(wall.toFixed(3)),
      // **서비스가 말한 모델과 실제로 답한 파일을 둘 다 적는다.** 260906 에 이 둘이
      // 어긋난 채로 표가 나온 적이 있다 (유령 llama-server). 기록이 거짓말하면
      // 그 뒤의 모든 판단이 무의미하다.
      model_requested: model,
      model_reported: result?.model ?? null,
      served_model_file: result?.extra?.served_model_file ?? null,
      elapsed_sec: result?.elapsed_sec ?? null,
      schema_errors: result?.schema_errors ?? null,
      schema_pass: result === null ? null : (result.schema_errors ?? []).length === 0,
      grammar: result?.grammar ?? null,
      grammar_enforced: result?.extra?.grammar_enforced ?? null,
      examples_used: examples.map((example) => example.mission_id),
      // 프롬프트에 실제로 실린 장비가 몇 건인가 (서비스가 센 값). **「줬다」만 남기면
      // 목록이 채점 어휘 크기로 좁아진 채 돈 실행을 나중에 못 가려낸다** — 그 순간
      // 이 축은 자기 자신을 채점하게 되고, `verify:no-leak` 5번이 이 숫자를 본다.
      equipment_given: result?.extra?.equipment_given ?? (giveEquipment ? null : 0),
      extra: result?.extra ?? null,
    };
    records.push(record);
    writeFileSync(join(outRoot, 'raw', `${mission.mission_id}__v${index}.json`), JSON.stringify({ record, mission: result?.mission ?? null }, null, 2), 'utf8');

    if (result?.mission != null) {
      // 채점기는 mission_id 로 짝을 찾는다. 모델이 식별자를 안 옮겨 적었어도 그 건을
      // 잃지 않도록 여기서 맞춘다 — **식별자는 애초에 부르는 쪽이 준 값이다.**
      // 지켰는지 여부는 `id_obeyed` 로 따로 남는다: 고쳐 놓고 안 고친 척하지 않는다.
      record.id_obeyed = result.mission.mission_id === mission.mission_id;
      writeFileSync(
        join(variantDir, `${mission.mission_id}.json`),
        JSON.stringify({ ...result.mission, mission_id: mission.mission_id }, null, 2),
        'utf8',
      );
    }
    const status = failure !== null ? `실패 — ${failure.slice(0, 60)}`
      : `${record.schema_pass ? '스키마통과' : `스키마실패 ${record.schema_errors.length}`} · ${wall.toFixed(1)}초 · 마일스톤 ${result.mission?.milestones?.length ?? '?'}`;
    console.log(`  ${mission.mission_id} v${index}  ${status}`);
  }
}

writeSummary(outRoot, { model, label, grammar_enforced: enforceGrammar, equipment_given: giveEquipment, shots, records });
console.log('');
console.log(`기록 ${records.length}건 → ${join(outRoot, 'summary.json')}`);
console.log('표는 `node scripts/report-baseline.mjs` 가 만든다 — 여러 모델을 한 표에 놓아야 낙폭이 보인다.');
