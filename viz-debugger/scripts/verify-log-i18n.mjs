// verify:log-i18n (260919 신설 — 영문화 5단계 §3)
//
// **로그 줄은 글자가 아니라 키를 들고 있다.**
//
// 전에는 `t()` 로 그린 글자를 그대로 담았다. 그러면 그 줄은 **쌓인 순간의 언어로 굳고**
// 나중에 언어를 바꿔도 안 따라온다 — 260919 에 사람이 「탐지 화면 로그는 '가까운 장애물
// 있음/없음' 부분만 한국어」로 본 것이 이것이다. 기록에도 그 글자가 그대로 남아서,
// 한국어로 기록한 판은 영문 화면에서도 한국어였다.
//
// 보는 것 넷.
//  1. 쌓는 자리가 **`say`(키)로 담는다** — `text: t(...)` 가 남아 있으면 그 줄이 굳는다
//  2. 그리는 자리가 **푸는 함수를 거친다** — `line.text` 를 바로 읽으면 새 줄이 빈칸이다
//  3. **옛 기록이 그대로 열린다** — `mission-record/1` 은 `text` 만 들고 있다
//  4. 언어를 바꾸면 **같은 줄이 다른 글자로** 그려진다
import { readdirSync, existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isScratchPath } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const failures = [];
const controls = [];

const { lineText, lineDetail, appendDetectLog, detectLog, resetDetectLog } =
  await load('src', 'detect', 'detectLog.ts');
// 말을 담는 모양은 표시층의 것이라 `src/i18n/phrase.ts` 에 산다 (탐지·자율주행 경계 밖).
const { sayText } = await load('src', 'i18n', 'phrase.ts');
const { setLang, getLang } = await load('src', 'shared', 'language.ts');

// ── 1. 쌓는 자리가 키로 담는다 ──────────────────────────────────────────────
{
  const files = [];
  (function walk(dir) {
    for (const name of readdirSync(dir)) {
      if (name.startsWith('.')) continue;
      const full = join(dir, name);
      // 남의 대조군 잔여물을 내 판정에 넣지 않는다 (260917 — 검사 위생 §3①).
      if (isScratchPath(full)) continue;
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.tsx?$/.test(name)) files.push(full);
    }
  })(join(root, 'src'));

  let producers = 0;
  for (const abs of files) {
    const rel = relative(join(root, 'src'), abs).split(sep).join('/');
    const src = readSource(abs);
    if (!/appendDetectLog\(|ObstacleLogLine\[\]|log: withLog\(/.test(src)) continue;
    producers += 1;
    // `text: t(...)` · `detail: t(...)` — 그리는 순간이 아니라 **쌓는 순간**에 굳는 모양이다.
    for (const m of src.matchAll(/(^|[^A-Za-z0-9_$])(text|detail):\s*t\(/g)) {
      const line = src.slice(0, m.index).split('\n').length;
      failures.push(`${rel}:${line} — 로그 줄에 \`${m[2]}: t(…)\` 로 **그린 글자**를 담는다. \`say\` 에 키를 담아라 (쌓인 순간의 언어로 굳는다)`);
    }
  }
  console.log(`✅ 로그를 쌓는 ${producers}개 파일이 글자 대신 키를 담는다`);
}

// ── 2. 그리는 자리가 푸는 함수를 거친다 ─────────────────────────────────────
{
  const views = [
    ['detect/views/DetectActionLog.tsx', /lineText\s*\(/, 'lineText()'],
    ['autodrive/views/AutodriveViews.tsx', /obstacleLineText\s*\(/, 'obstacleLineText()'],
  ];
  for (const [rel, want, what] of views) {
    const src = readSource(join(root, 'src', rel));
    if (!want.test(src)) failures.push(`${rel}: ${what} 를 안 거친다 — 새 줄이 빈칸으로 뜬다`);
    if (/\{line\.text\}|\{line\.detail\}/.test(src)) {
      failures.push(`${rel}: \`line.text\` 를 바로 그린다 — 새 줄은 그 자리가 비어 있다`);
    }
  }
  console.log(`✅ 그리는 자리 ${views.length}곳이 푸는 함수를 거친다`);
}

// ── 3. 옛 기록이 그대로 열린다 ──────────────────────────────────────────────
//
// **이것이 제일 중요하다.** 옛 판은 `text` 만 들고 있고 다시 그릴 재료가 없다.
// 그 자리를 안 봐 주면 260914~260916 의 판이 통째로 빈 줄이 된다.
{
  const old = { atIso: '2026-09-16T01:28:54.068Z', lane: 'screen', level: 'info', text: '준비 시작', detail: '둘 다 끝나야', tasks: ['T-A1'] };
  if (lineText(old) !== '준비 시작' || lineDetail(old) !== '둘 다 끝나야') {
    failures.push('옛 기록(mission-record/1)의 줄이 안 그려진다 — 45판이 빈 줄이 된다');
  } else controls.push('옛 기록의 글자를 그대로 그린다');

  // 실제 기록으로도 본다.
  const histRoot = join(root, '..', 'mission-history');
  let runs = 0;
  let blank = 0;
  if (existsSync(histRoot)) {
    for (const day of readdirSync(histRoot)) {
      for (const run of readdirSync(join(histRoot, day))) {
        const file = join(histRoot, day, run, 'progress.json');
        if (!existsSync(file)) continue;
        runs += 1;
        for (const line of JSON.parse(readFileSync(file, 'utf8')).detectLog ?? []) {
          if (lineText(line) === '') blank += 1;
        }
      }
    }
  }
  if (blank > 0) failures.push(`실제 기록 ${runs}판에서 빈 줄이 ${blank}건 나온다 — 옛 판을 못 읽는다`);
  console.log(`✅ 실제 기록 ${runs}판의 로그 줄이 전부 글자로 그려진다`);
}

// ── 4. 언어를 바꾸면 같은 줄이 다른 글자로 그려진다 ─────────────────────────
{
  const before = getLang();
  resetDetectLog();
  appendDetectLog({ lane: 'detect', level: 'info', say: { key: 'dpl.1' }, tasks: ['T-A3'] });
  const line = detectLog()[0];

  setLang('ko');
  const ko = lineText(line);
  setLang('en');
  const en = lineText(line);
  setLang(before);

  if (ko === '' || en === '') failures.push('키를 못 푼다 — 사전에 없는 키인가');
  else if (ko === en) failures.push(`언어를 바꿔도 같은 글자다 — 「${ko}」. 줄이 굳어 있다`);
  else controls.push(`같은 줄이 언어를 따라간다 (ko「${ko.slice(0, 14)}…」 ↔ en「${en.slice(0, 14)}…」)`);

  // 값 자리에 든 문구도 같이 풀린다.
  setLang('en');
  const nested = sayText({ key: 'dpl.frameResult', vars: { deg: 45, verdict: { key: 'dpl.doorYes' }, n: 1, count: 8 } });
  setLang(before);
  if (/[가-힣]/.test(nested)) failures.push(`값 자리의 문구가 안 풀린다 — 「${nested}」`);
  else controls.push('값 자리에 든 문구도 같은 언어로 풀린다');

  resetDetectLog();
}

if (failures.length > 0) {
  console.error(`❌ verify:log-i18n\n- ${failures.join('\n- ')}`);
  console.error('\n   로그 줄은 `say: { key, vars }` 로 담고, 그릴 때 `lineText()` 로 푼다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
