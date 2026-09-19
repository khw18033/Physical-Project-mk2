// verify:no-raw-korean (260919 신설 — 영문화 4단계 §3)
//
// **`src/` 전체에 표시용 한글이 없다.**
//
// 2단계의 `verify:i18n-demo-path` 는 시연 경로 22개 파일만 봤다. 4단계가 나머지를 다 옮겼으니
// 이제 저장소 전체로 넓힌다 — 이것이 4단계의 완료 표시다. 건수 0이 아니라 **이 검사가
// 서 있는 상태**가 끝난 것이다.
//
// ## 예외는 목록으로 못박는다
//
// 「어쩌다 남은 것」과 「남겨야 하는 것」은 다르다. 아래 목록은 뒤엣것이고, 각 줄에 **왜**가
// 붙어 있다. 사유 없이 목록만 늘리면 이 검사는 곧 아무것도 안 지킨다.
//
// 예외에 드는 갈래는 넷뿐이다.
//
//   ① 개발자에게만 보인다        `throw new Error(…)` — 화면에 안 뜬다
//   ② 한국어를 **읽는** 코드      발화 표지 · 정규식 — 영어로 바꾸면 인식이 깨진다
//   ③ 화면에 닿지 않는 경로       소비하는 화면이 제거된 코드
//   ④ 일부러 한국어              각 언어를 그 언어로 · 계약에 실려 나가는 값
//
// 대조군 — 예외 밖 파일에 한글을 한 줄 심은 사본이 반드시 잡혀야 한다.
import { readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { blankComments } from './lib/i18nMove.mjs';
import { isScratchPath } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const srcDir = join(root, 'src');

const failures = [];
const controls = [];

/**
 * **남겨야 하는 한글.** 파일마다 「몇 건인지」와 「왜인지」를 적는다.
 *
 * 건수를 같이 적는 이유: 사유가 맞더라도 **늘어나면 알아야 한다.** 예외 파일이라고
 * 새 한글을 자유롭게 넣을 수 있는 것이 아니다.
 */
const KEPT = [
  // ① 개발자에게만 보인다
  ['canvas/registry.ts', 1, '`throw new Error` — 뷰 노드 kind 중복 등록. 화면에 안 뜬다'],
  ['shared/pendingSources.ts', 1, '`throw new Error` — pendingSources 에 없는 id. 화면에 안 뜬다'],
  ['scenarios/axes.ts', 1, '`throw new Error` — SCENARIO_PANELS 에 없는 id'],
  ['scenarios/library.ts', 2, '`throw new Error` — 대본 목록과 실물이 어긋남 (기동 시 즉시 죽는다)'],
  ['generate/gbnf.ts', 6, '`throw new Error` 넷은 계약→문법 변환 실패, 둘은 **생성된 문법 파일의 주석**이다 — 화면이 아니라 파일로 나간다'],

  // ② 한국어를 **읽는** 코드
  // `physical/approachPlan.ts` · `physical/missionLink.ts` 의 정규식(`/왼쪽|반시계/`)은
  // **예외가 필요 없다** — 정규식 리터럴은 문자열도 JSX 텍스트도 아니라 아래 잣대에 안 걸린다.
  // 처음에 예외로 적었다가 §2(목록이 낡지 않았다)에 잡혀서 뺐다. 그 파일들의 주석이
  // 「이 한글은 옮기지 않는다」를 이미 말하고 있다.
  ['generate/planShape.ts', 16,
   'LOOP_MARKERS · BRANCH_MARKERS — **발화를 `includes()` 로 읽는 키워드**다. 영어로 바꾸면 「…할 때까지 반복해」를 못 잡는다'],

  // ③ 화면에 닿지 않는 경로
  ['shared/pipeline-contract.ts', 20,
   '`gateway/` 셋이 쓰지만 **소비하는 화면이 없다** — 탭⑥이 2026-08-31 에 제거됐다(`gateway/server.ts` 주석). 그 파일 머리에 경위가 있다'],
  ['views/TopBar.tsx', 3,
   '어느 화면도 이 부품을 그리지 않는다. 그래도 **검사 넷이 본다**(긴급정지·이동 버튼) — 지우면 그 규칙이 절반으로 준다. 그 파일 머리에 경위가 있다'],

  // ④ 일부러 한국어
  ['shell/LangSwitch.tsx', 1, '언어 세그먼트의 `한국어` — **각 언어를 그 언어로 적는다.** 영문 화면에서 `Korean` 이면 한국어 쓰는 사람이 못 찾는다'],
  ['stt/confidence.ts', 1, '`PROVISIONAL_NOTE` — 명령 payload 의 `threshold_status` 로 나가는 **계약 값**이다. 화면용 키는 `stt.provisionalNote` 로 따로 있다'],
];

const KEPT_BY_FILE = new Map(KEPT.map(([rel, n, why]) => [rel, { n, why }]));

/** 표시용 한글을 센다 — `verify-i18n-demo-path` 와 같은 잣대다. */
const CODE_MARKS = [';', '=>', 'const ', 'let ', 'return ', 'function ', 'import ', '&&', '||', '??'];

function displayKorean(src) {
  const code = blankComments(src);
  const hits = [];
  // ① 문자열 리터럴
  for (const m of code.matchAll(/(['"`])((?:[^\\\n]|\\.)*?)\1/g)) {
    if (/[가-힣]/.test(m[2])) hits.push(m[2]);
  }
  // ② JSX 텍스트 — 보간식을 접고 본다
  let s = code;
  let prev;
  do { prev = s; s = s.replace(/\{[^{}<>]*\}/g, '{}'); } while (s !== prev);
  for (const m of s.matchAll(/>([^<>]*[가-힣][^<>]*)<(?=[/A-Za-z])/g)) {
    const v = m[1].replace(/\s+/g, ' ').trim();
    if (v !== '' && !CODE_MARKS.some((k) => v.includes(k))) hits.push(v);
  }
  return hits;
}

/** ko 에 있고 en 에 없는 키 중 **못박히지 않은 것**. §3 이 쓰고 §4 가 시험한다. */
function unpinnedKoOnly(ko, en, pinned) {
  return [...ko].filter((k) => !en.has(k) && !pinned.has(k));
}

const files = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name.startsWith('.')) continue;
    const full = join(dir, name);
    if (isScratchPath(full)) continue;
    if (statSync(full).isDirectory()) walk(full);
    else if (/\.tsx?$/.test(name)) files.push(full);
  }
})(srcDir);

const relOf = (abs) => relative(srcDir, abs).split(sep).join('/');

// ── 1. 예외 밖에는 표시용 한글이 0건 ────────────────────────────────────────
{
  let scanned = 0;
  let kept = 0;
  for (const abs of files) {
    const rel = relOf(abs);
    if (rel.startsWith('i18n/')) continue;      // 사전 자체는 한국어로 가득하다
    scanned += 1;
    const hits = displayKorean(readSource(abs));
    const allow = KEPT_BY_FILE.get(rel);
    if (allow === undefined) {
      for (const hit of hits.slice(0, 3)) {
        failures.push(`${rel}: 표시용 한글 「${hit.length > 50 ? `${hit.slice(0, 50)}…` : hit}」`);
      }
      if (hits.length > 3) failures.push(`${rel}: 그 밖 ${hits.length - 3}건`);
      continue;
    }
    kept += hits.length;
    // **늘어나면 알아야 한다.** 사유가 맞아도 새 한글을 자유롭게 넣을 수는 없다.
    if (hits.length > allow.n) {
      failures.push(`${rel}: 남겨 둔 한글이 ${allow.n} → ${hits.length} 로 늘었다. 목록의 사유가 새 줄에도 맞는지 보고, 맞으면 수를 고쳐라 — 「${allow.why}」`);
    }
  }
  console.log(`✅ ${scanned}개 파일 — 예외 ${KEPT.length}개(${kept}건) 밖에 표시용 한글 0건`);
}

// ── 2. 예외 목록이 낡지 않았다 ──────────────────────────────────────────────
//
// 한글이 사라진 파일이 목록에 남아 있으면, 그 파일에 누가 한글을 새로 넣어도 눈감는다.
{
  const known = new Set(files.map(relOf));
  for (const [rel, n, why] of KEPT) {
    if (!known.has(rel)) { failures.push(`예외 목록의 ${rel} 가 없다 — 목록에서 지워라`); continue; }
    const hits = displayKorean(readSource(join(srcDir, rel)));
    if (hits.length === 0) {
      failures.push(`${rel} 에 한글이 더 없다 — 예외에서 지워라 (남겨 두면 이 파일을 눈감는다). 적어 둔 사유: 「${why}」`);
    }
    if (n <= 0) failures.push(`${rel} 의 예외 건수가 ${n} 이다 — 0 이면 예외가 아니다`);
    if (!why || why.length < 10) failures.push(`${rel} 에 사유가 없다 — 사유 없는 예외는 곧 아무것도 안 지킨다`);
  }
  console.log(`✅ 예외 목록 ${KEPT.length}개가 전부 실재하고, 아직 한글이 남아 있고, 사유가 적혀 있다`);
}

// ── 3. 사전 자체가 낸 구멍 — **ko 에만 있는 키** ────────────────────────────
//
// 위 §1 은 `i18n/` 을 건너뛴다 (사전은 한국어로 가득하다). 그런데 **사전 안에도 영문
// 화면에 한국어를 띄우는 자리가 있다** — ko 에 있고 en 에 없는 키다. 그 자리는 설계상
// 한국어로 떨어지고(`dict.ts` fallback) 콘솔에 한 줄 남는다.
//
// `verify:dict-shape` 의 §1 은 「en ⊆ ko」만 본다. 반대는 **일부러** 허용한다 — 그것이
// fallback 설계이고, 부분 번역 상태에서도 화면이 정상이어야 하기 때문이다. 그래서
// **ko 에만 있는 키는 지금까지 아무도 세지 않았다.** 새 ko 키를 넣고 en 을 잊으면 그
// 자리가 영문 화면에서 한국어로 뜨는데 검사는 전부 초록이다. 4단계가 막으려던 모양이다.
//
// 그러므로 「없어도 되는 것」이 아니라 **목록으로 못박는다.**
{
  const keysOf = (rel) =>
    new Set([...readSource(join(srcDir, rel)).matchAll(/^\s*'([^']+)':/gm)].map((m) => m[1]));
  const ko = keysOf('i18n/ko.ts');
  const en = keysOf('i18n/en.ts');

  /** 영어를 **일부러** 안 둔 키. 화면에 한국어로 뜬다 — 그래서 사유가 붙어 있다. */
  const KO_ONLY = [
    ['mode.mock',
     '1단계의 **시범 키 다섯째** — 이 빈자리가 fallback 이 실제로 도는지 보는 자리다. 영문 화면에서 이 버튼만 「목·개발」로 남고 콘솔에 한 줄이 찍힌다 (`i18n/en.ts` ⑤)'],
  ];
  const pinned = new Map(KO_ONLY);

  const missing = [...ko].filter((k) => !en.has(k));
  const loose = unpinnedKoOnly(ko, en, pinned);
  for (const k of loose) {
    failures.push(`사전 키 '${k}' 가 ko 에만 있다 — 영문 화면에서 이 자리가 한국어로 뜬다. en 에 넣거나, 일부러라면 이 파일의 KO_ONLY 에 **사유와 함께** 적어라`);
  }
  for (const [k, why] of KO_ONLY) {
    if (!ko.has(k)) failures.push(`KO_ONLY 의 '${k}' 가 ko 사전에 없다 — 목록에서 지워라`);
    else if (en.has(k)) failures.push(`KO_ONLY 의 '${k}' 에 영어가 생겼다 — 목록에서 지워라 (남겨 두면 다음에 빠진 것을 눈감는다). 적어 둔 사유: 「${why}」`);
  }
  // **센 값을 적는다.** 「전부 못박혔다」를 글자로 박아 두면 실패할 때도 그렇게 말한다 —
  // 3단계의 `verify:stt-language` 가 「겹치는 낱말 0건」으로 같은 거짓말을 하고 있었다.
  console.log(`✅ 사전 ko ${ko.size} · en ${en.size} — ko 에만 있는 키 ${missing.length}건 (못박은 것 ${missing.length - loose.length} · 못박히지 않은 것 ${loose.length})`);
}

// ── 4. 대조군 ───────────────────────────────────────────────────────────────
{
  // ① 예외 밖 파일에 한글을 심은 사본은 잡혀야 한다.
  const injected = 'export const x = <p>새로 박은 한글</p>;';
  if (displayKorean(injected).length !== 1) {
    failures.push('대조군 실패: JSX 텍스트에 심은 한글을 못 잡는다 — 이 검사는 무의미하다');
  } else controls.push('JSX 텍스트에 심은 한글을 잡는다');

  if (displayKorean("const a = '새 문자열';").length !== 1) {
    failures.push('대조군 실패: 문자열 리터럴에 심은 한글을 못 잡는다');
  } else controls.push('문자열 리터럴에 심은 한글을 잡는다');

  // ② 주석은 잡으면 안 된다 — 이 저장소의 주석은 한글로 길다.
  if (displayKorean('// 이것은 주석이다\n/* 이것도 주석이다 */\nconst a = 1;').length !== 0) {
    failures.push('대조군 실패: 주석을 표시 한글로 셌다 — 이 저장소의 주석은 전부 한국어다');
  } else controls.push('주석은 세지 않는다');

  // ③ 예외 파일의 건수를 넘기면 잡혀야 한다.
  const allow = KEPT_BY_FILE.get('shell/LangSwitch.tsx');
  if (allow === undefined || allow.n !== 1) {
    failures.push('대조군 실패: 예외 건수 표를 못 읽었다');
  } else controls.push(`예외 건수를 세어 둔다 (LangSwitch ${allow.n}건)`);

  // ④ 영어를 잊은 키는 잡고, 못박은 키는 통과시킨다.
  const ko = new Set(['a.kept', 'a.forgotten']);
  const en = new Set(['a.kept']);
  const got = unpinnedKoOnly(ko, en, new Map());
  if (got.length !== 1 || got[0] !== 'a.forgotten') {
    failures.push('대조군 실패: 영어를 잊은 키를 못 잡는다 — 그 자리는 영문 화면에서 한국어로 뜬다');
  } else if (unpinnedKoOnly(ko, en, new Map([['a.forgotten', '…']])).length !== 0) {
    failures.push('대조군 실패: 못박은 키까지 잡는다 — 그러면 fallback 시범 자리를 둘 수 없다');
  } else controls.push('영어를 잊은 키는 잡고 못박은 키는 통과시킨다');
}

if (failures.length > 0) {
  console.error(`❌ verify:no-raw-korean\n- ${failures.join('\n- ')}`);
  console.error('\n   화면에 뜨는 글자는 사전(`i18n/ko.ts`·`en.ts`)에 있어야 한다.');
  console.error('   남겨야 하는 것이라면 이 파일의 `KEPT` 에 **사유와 함께** 적어라.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
