// verify:goldset-en (260919 신설 — 영문화 5단계 L3 (나))
//
// **영어 정답셋은 한국어 판과 구조가 같고 글자만 다르다.**
//
// 영어로 생성을 재려면 정답셋이 영어여야 한다. 그런데 그 영어를 **채점하려고 새로 지으면**
// 내가 쓴 영어와 모델이 쓴 영어가 가까워져 점수가 부푼다. 그래서 3단계가 **화면에 그리려고**
// 만들어 둔 사이드카(`scenarios/MSN-*.en.json`)에서 뽑는다 — 채점을 염두에 두지 않고 쓴 글이다.
//
// 보는 것 다섯.
//  1. **편이 1:1** — 한국어 판에 있는 편이 영어 판에도 있다
//  2. **구조가 같다** — 마일스톤 수·차례·id·담당 장비·태스크 수가 같다. 다른 것은 글자뿐이다
//  3. **채점 대상 문장에 한글이 0** — 발화·마일스톤 제목·태스크 제목
//  4. **조회 규칙은 안 실렸다** — 그것은 대본이 발화를 고르는 키워드이지 정답이 아니다
//  5. **발화 변형도 1:1** — 편마다 변형 수가 같아야 두 판의 표본 수가 같다
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const gold = join(root, 'gen-lab', 'goldset');

const failures = [];
const controls = [];
const read = (...p) => JSON.parse(readFileSync(join(...p), 'utf8'));
const han = /[가-힣]/;

// ── 1·2·3·4 — 편마다 대조 ───────────────────────────────────────────────────
{
  if (!existsSync(join(gold, 'missions-en'))) {
    failures.push('영어 정답셋이 없다 — `npm run goldset:extract` 를 돌려라');
  } else {
    const koFiles = readdirSync(join(gold, 'missions')).filter((f) => f.endsWith('.json'));
    const enFiles = readdirSync(join(gold, 'missions-en')).filter((f) => f.endsWith('.json'));
    for (const file of koFiles) {
      if (!enFiles.includes(file)) { failures.push(`${file}: 영어 판이 없다`); continue; }
      const ko = read(gold, 'missions', file);
      const en = read(gold, 'missions-en', file);

      // 2 — 구조가 같다.
      if (ko.milestones.length !== en.milestones.length) {
        failures.push(`${file}: 마일스톤 수가 다르다 — ko ${ko.milestones.length} · en ${en.milestones.length}`);
      }
      for (let at = 0; at < Math.min(ko.milestones.length, en.milestones.length); at += 1) {
        const a = ko.milestones[at];
        const b = en.milestones[at];
        if (a.milestone_id !== b.milestone_id) failures.push(`${file}[${at}]: 마일스톤 id 가 다르다 (${a.milestone_id} ≠ ${b.milestone_id})`);
        if (a.order !== b.order) failures.push(`${file}[${at}]: 차례가 다르다`);
        if (JSON.stringify(a.assigned_targets) !== JSON.stringify(b.assigned_targets)) {
          failures.push(`${file}[${at}]: 담당 장비가 다르다 — 글자만 달라야 한다`);
        }
        if (a.title === b.title) failures.push(`${file}[${at}]: 제목이 한국어 그대로다 — 「${a.title}」`);
      }
      if ((ko.tasks ?? []).length !== (en.tasks ?? []).length) {
        failures.push(`${file}: 태스크 수가 다르다 — ko ${(ko.tasks ?? []).length} · en ${(en.tasks ?? []).length}`);
      }

      // 3 — 채점 대상 문장에 한글이 없다.
      const scored = [en.utterance.text, ...en.milestones.map((m) => m.title), ...(en.tasks ?? []).map((t) => t.title)];
      const left = scored.filter((s) => han.test(String(s)));
      for (const one of left.slice(0, 4)) failures.push(`${file}: 채점 문장에 한글 — 「${String(one).slice(0, 60)}」`);
      if (left.length > 4) failures.push(`${file}: 그 밖 ${left.length - 4}건`);

      // 4 — 조회 규칙은 안 실렸다.
      if (en.match !== undefined) failures.push(`${file}: 조회 규칙(match)이 실렸다 — 정답이 아니라 대본의 키워드다`);
    }
    const koCount = koFiles.length;
    console.log(`✅ 편 ${koCount}개가 1:1 — 마일스톤 id·차례·담당 장비가 같고 **제목만 영어다**`);
  }
}

// ── 5. 발화 변형도 1:1 ──────────────────────────────────────────────────────
{
  const koPath = join(gold, 'utterances.json');
  const enPath = join(gold, 'utterances.en.json');
  if (!existsSync(enPath)) {
    failures.push('영어 발화 변형(utterances.en.json)이 없다 — 표현 강건성 축을 영어로 못 잰다');
  } else {
    const ko = read(koPath);
    const en = read(enPath);
    const byId = new Map(en.missions.map((m) => [m.mission_id, m]));
    let total = 0;
    for (const one of ko.missions) {
      const other = byId.get(one.mission_id);
      if (other === undefined) { failures.push(`${one.mission_id}: 영어 변형이 없다`); continue; }
      if (one.variants.length !== other.variants.length) {
        failures.push(`${one.mission_id}: 변형 수가 다르다 — ko ${one.variants.length} · en ${other.variants.length}. 표본 수가 갈린다`);
      }
      for (const line of [other.original, ...other.variants]) {
        total += 1;
        if (han.test(line)) failures.push(`${one.mission_id}: 영어 변형에 한글 — 「${line.slice(0, 50)}」`);
      }
    }
    // **같은 표에 못 놓는다**를 파일이 스스로 적고 있어야 한다. 그 한 줄이 없으면
    // 나중에 두 숫자를 나란히 놓는 사람이 생긴다.
    if (typeof en.caveat !== 'string' || !en.caveat.includes('나란히 놓을 수 없다')) {
      failures.push('utterances.en.json 에 「같은 표에 나란히 놓을 수 없다」가 안 적혀 있다 — 그 한 줄이 이 실험의 한계다');
    } else controls.push('한계가 파일에 적혀 있다 (두 판의 점수를 나란히 놓지 않는다)');
    console.log(`✅ 발화 ${total}건이 영어 — 편마다 변형 수가 한국어 판과 같다`);
  }
}

// ── 6. 영어로 재는 길이 **끊긴 데 없이** 이어져 있다 ────────────────────────
//
// 셋이 한꺼번에 갈려야 한다 — 정답셋 · 발화 변형 · 프롬프트. 하나라도 빠지면
// 「영어로 물었는데 한국어 정답과 맞춘다」가 되어 그 숫자는 아무 뜻이 없다.
// 그런데 그 어긋남은 **실행이 끝나고 점수가 나온 뒤에야** 이상해 보인다.
{
  const links = [
    ['scripts/run-baseline.mjs', /--lang/, '실행기가 `--lang` 을 받는다'],
    ['scripts/run-baseline.mjs', /missions-en/, '실행기가 영어 정답셋을 읽는다'],
    ['scripts/run-baseline.mjs', /utterances\.en\.json/, '실행기가 영어 발화 변형을 읽는다'],
    ['scripts/run-baseline.mjs', /lang === 'en' \? '__en'/, '영어 실행이 폴더를 따로 쓴다 (한국어 판을 안 덮는다)'],
    ['src/generate/LlmClient.ts', /lang: options\.lang \?\? 'ko'/, '요청이 언어를 싣고 기본이 한국어다'],
  ];
  for (const [rel, want, what] of links) {
    const src = readFileSync(join(root, 'viz-debugger', rel), 'utf8');
    if (!want.test(src)) failures.push(`${rel}: ${what} — 끊겼다`);
  }
  // 서비스 쪽도 본다 (파이썬).
  const server = readFileSync(join(root, 'gen-lab', 'server', 'main.py'), 'utf8');
  if (!/lang: str = "ko"/.test(server)) failures.push('gen-lab/server/main.py: 요청이 `lang` 을 안 받는다');
  if (!/lang=request\.lang/.test(server)) failures.push('gen-lab/server/main.py: 받은 `lang` 을 프롬프트로 안 넘긴다');
  console.log(`✅ 영어로 재는 길 ${links.length + 2}자리가 이어져 있다 — 정답셋 · 발화 · 프롬프트가 한꺼번에 갈린다`);
}

// ── 대조군 ──────────────────────────────────────────────────────────────────
{
  // 한국어 판은 **그대로 한국어다.** 영어 판을 만들다 원본을 건드리면 베이스라인이 깨진다.
  const koFiles = existsSync(join(gold, 'missions')) ? readdirSync(join(gold, 'missions')).filter((f) => f.endsWith('.json')) : [];
  let koTitles = 0;
  for (const file of koFiles) {
    for (const ms of read(gold, 'missions', file).milestones) {
      koTitles += 1;
      if (!han.test(ms.title)) failures.push(`${file}: 한국어 정답의 제목이 한국어가 아니다 — 「${ms.title}」`);
    }
  }
  if (koTitles === 0) failures.push('한국어 정답셋을 못 읽었다 — 이 검사가 아무것도 안 재고 있다');
  else controls.push(`한국어 정답 ${koTitles}줄이 그대로 한국어다`);
}

if (failures.length > 0) {
  console.error(`❌ verify:goldset-en\n- ${failures.join('\n- ')}`);
  console.error('\n   영어 정답셋은 **손으로 적지 않는다** — `npm run goldset:extract` 가 사이드카에서 뽑는다.');
  console.error('   빠진 문장이 있으면 `scenarios/MSN-*.en.json` 에 더해라.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
