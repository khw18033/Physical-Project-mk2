// verify:i18n-demo-path (260917 신설 — 영문화 2단계 지시서 §7)
//
// **시연 경로가 영어로 도는 상태를 못 잃게 한다.**
//
// 2단계가 22개 파일 608개 문구를 사전으로 옮겼다. 그 뒤로 누가 그 파일에 한글을 한 줄
// 직접 박으면, 화면은 한국어에서 멀쩡해 보이고 **영문 화면에서만 그 한 줄이 한국어로 남는다.**
// 눈으로 보기 전에는 모른다 — 그래서 검사로 잡는다.
//
// 보는 것 넷.
//  1. **시연 경로 22개 파일에 표시용 한글이 0건** — 주석·타입은 제외한다
//  2. **`t()` 를 쓰는 컴포넌트는 `useLang()` 을 갖는다** — 1단계 보고서 §3 ①이 지목한 함정
//  3. **ko 키가 en 에도 있다** — 시범 키 `mode.mock` 하나만 예외(그 빈자리가 fallback 의 증거다)
//  4. 대조군 — 위 셋을 어긴 사본이 반드시 잡혀야 한다
//
// 5단계의 `verify:no-raw-korean` 이 1번을 저장소 전체로 넓힌 것이 된다.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const { ko } = await import(pathToFileURL(join(root, 'src', 'i18n', 'ko.ts')).href);
const { en } = await import(pathToFileURL(join(root, 'src', 'i18n', 'en.ts')).href);

const failures = [];
const controls = [];

/** 2단계 범위 (지시서 §1). 늘리는 것은 3·4단계의 몫이다 — 줄이면 시연이 영어로 안 돈다. */
const DEMO_PATH = [
  'shared/pendingSources.ts', 'shared/PendingSource.tsx',
  'views/UtterancePanel.tsx', 'views/ActionModal.tsx', 'views/MissionHistory.tsx', 'views/ResetButton.tsx',
  'shell/HelpOverlay.tsx', 'shell/AppShell.tsx', 'shell/ConnectionsPanel.tsx', 'shell/ModeSwitch.tsx', 'shell/ConnectionLamp.tsx',
  'tabs/views/PlanApproval.tsx', 'physical/StopButton.tsx',
  'graph/TaskGraph.tsx', 'graph/shape.ts', 'graph/stateStyle.ts',
  'canvas/ViewNodeCard.tsx', 'canvas/Palette.tsx', 'canvas/ZoomOverlay.tsx',
  'canvas/persist.ts', 'canvas/useCanvas.ts', 'canvas/registry.ts',
];

/**
 * **개발자에게만 보이는 한글은 대상이 아니다.**
 *
 * `throw new Error('…')` 는 프로그래밍 실수를 알리는 자리이고 화면에 안 뜬다. 옮기면
 * 사전이 화면 문구와 개발 메시지를 섞어 담게 되고, 번역 품질 검수에서 무엇을 봐야 하는지가
 * 흐려진다. 두 곳뿐이라 목록으로 못박는다 — 늘면 여기가 먼저 걸린다.
 */
const DEV_ONLY = [
  'pendingSources 에 없는 id',
  '뷰 노드 kind 가 중복 등록됐다',
];

const read = (rel) => readFileSync(join(root, 'src', rel), 'utf8');
/** 주석을 지운다 — 이 저장소의 주석은 한글로 길고, 그건 옮길 대상이 아니다. */
const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

/**
 * JSX 텍스트 노드의 한글을 찾는다.
 *
 * ## 260917 — 여기에 사각이 있었다
 *
 * 전에는 이랬다.
 *
 * ```js
 * /&gt;([^&lt;&gt;{}]*[가-힣][^&lt;&gt;]*)&lt;/g
 * //   ^^^^^^^^ 여는 쪽이 중괄호를 배제한다
 * ```
 *
 * `<small>{items.length}판</small>` 은 `>` 와 한글 사이에 `{` 가 있어 **매칭 후보가 되지도
 * 못했다.** 그래서 2단계가 「표시 한글 0건」이라 적고도 **보간식에 붙은 단위·연결어 9건**이
 * 남아 있었다 — `12 노드` · `3판` · `그림 5장` 이 영문 화면에 그대로 뜬다.
 *
 * ## 그래서 표현식을 먼저 비운다
 *
 * `{…}` 를 안쪽부터 `{}` 로 접어 두면 보간식 옆 텍스트가 보인다. **그런데 그대로 쓰면
 * 코드의 비교 연산자를 태그 경계로 오인한다** — `x > 0; const a = b < c` 같은 줄이
 * 「텍스트 노드」로 잡힌다. 실제로 두 건이 그렇게 떴다.
 *
 * 줄바꿈을 막으면(`[^<>\n]`) 오탐은 사라지지만 **여러 줄 JSX 두 건을 놓친다** —
 * `추론 …s · 로드 …s` 와 `그림 …장 · T+…s` 가 정확히 그 모양이다. 둘 다 못 버린다.
 *
 * ## 가르는 잣대 — **둘을 섞는다.** 하나로는 안 됐다
 *
 * **① 닫는 `<` 가 태그 시작인가.** 진짜 텍스트 노드는 여는 `>` 가 태그의 끝이고 닫는 `<` 가
 * 태그의 시작이다 — `<` 다음이 `/` 이거나 글자다.
 *
 * ```
 * const f = (a) => a > 1 ? 이름 : 0 < 2;
 * //                 ^^^^^^^^^^^^^^^^ 「 1 ? 이름 : 0 」— `<` 다음이 공백이라 ①이 버린다
 * ```
 *
 * **② 잡힌 텍스트에 코드 문법이 없는가.** ①만으로는 아래 둘이 샜다 — 우연히 `<` 뒤에
 * 글자가 오는 코드다.
 *
 * ```
 * = 0; const x1 = from.x + from.w / 2; …     (TaskGraph)
 * { if (!manual.trim()) return; const …      (UtterancePanel)
 * ```
 *
 * **②를 잡힌 텍스트에만 건다** — 줄 전체에 걸면 `return <p>3판</p>;` 같은 진짜 텍스트가
 * 세미콜론 때문에 샌다. 텍스트 노드 안에는 `;` 도 `const ` 도 안 나온다.
 *
 * 처음에는 ②만 썼다가 대조군(`=>` 가 바깥에 있는 줄)에 뚫렸고, ①만 쓰자 위 둘이 샜다.
 * **대조군이 두 번 다 잡았다** — 그래서 둘을 섞는다.
 *
 * 5단계 `verify:no-raw-korean` 이 이 규칙을 저장소 전체로 넓힌다 — 거기서 오탐이 나면
 * 아무도 검사를 안 보게 되므로, 잣대를 여기서 정확히 세워 둔다.
 */
const CODE_MARKS = [';', '=>', 'const ', 'let ', 'return ', 'function ', 'import ', '&&', '||', '??'];

function jsxTexts(src) {
  // 표현식을 안쪽부터 접는다 — `{a.b({c})}` 처럼 겹친 것도 `{}` 하나가 된다.
  let s = src;
  let prev;
  do { prev = s; s = s.replace(/\{[^{}]*\}/g, '{}'); } while (s !== prev);
  return [...s.matchAll(/>([^<>]*[가-힣][^<>]*)<(?=[/A-Za-z])/g)]   // ① 모양
    .map((m) => m[1].replace(/\s+/g, ' ').trim())
    .filter((v) => v !== '' && !CODE_MARKS.some((mark) => v.includes(mark)));   // ② 내용
}

// ── 1. 시연 경로에 표시용 한글이 0건 ─────────────────────────────────────────
{
  let checked = 0;
  for (const rel of DEMO_PATH) {
    const src = code(read(rel));
    const literals = [...src.matchAll(/(['"`])((?:[^\\\n]|\\.)*?)\1/g)].map((m) => m[2]);
    const left = [...literals.filter((v) => /[가-힣]/.test(v)), ...jsxTexts(src)]
      .filter((v) => !DEV_ONLY.some((allow) => v.includes(allow)));
    checked += 1;
    for (const v of left) {
      failures.push(`${rel}: 한글이 직접 박혀 있다 — 「${v.slice(0, 60)}」. 사전으로 보내라 (t())`);
    }
  }
  if (checked !== DEMO_PATH.length) failures.push('시연 경로 파일을 다 못 읽었다');
  console.log(`✅ 시연 경로 ${DEMO_PATH.length}개 파일에 표시용 한글 0건 — 보간식 옆 텍스트까지 본다 · 개발자 메시지 ${DEV_ONLY.length}건만 예외`);
}

/**
 * `.tsx` 를 **컴포넌트 단위로** 자른다 — `function [A-Z]…` 부터 다음 컴포넌트 전까지.
 *
 * ## 260917 — 파일 단위로는 못 잡던 것
 *
 * 2단계에서 `useLang()` 을 **네 번** 빠뜨렸고 **넷 다 「한 파일에 컴포넌트가 여럿」**인
 * 모양이었다(2단계 보고서 §4 ①) — `ConnectionsPanel` 의 `HealthRow`, `StopButton` 의 네
 * 컴포넌트, `UtterancePanel` 의 `Numbers`·`LevelMeter`. 파일에 `useLang()` 이 **한 번이라도**
 * 있으면 통과하는 검사는 그 넷 중 하나도 구조적으로 못 잡는다. `AppShell` 을 잡은 것은
 * 그 파일에 컴포넌트가 하나였기 때문이지 검사가 좋아서가 아니었다.
 *
 * 4단계가 1,300여 개를 옮기는 동안 같은 함정을 훨씬 더 많이 밟는다. 그때 잡히게 지금 조인다.
 *
 * **순수 함수는 대상이 아니다.** 소문자로 시작하는 함수(`producerWord` · `mockSteps`)에서
 * `t()` 를 부르는 것은 정상이고, 그리는 컴포넌트가 훅을 가지면 된다. 그래서 대문자 함수만 본다.
 */
function components(src) {
  const marks = [...src.matchAll(/^(?:export )?function ([A-Z][A-Za-z0-9_]*)\s*\(/gm)];
  return marks.map((m, i) => ({
    name: m[1],
    body: src.slice(m.index, i + 1 < marks.length ? marks[i + 1].index : src.length),
  }));
}

/** 컴포넌트 본문이 `t()` 를 부르면서 `useLang()` 이 없는가. */
function missingHook(src) {
  return components(src)
    .filter((c) => /\bt\(/.test(c.body) && !/useLang\(\)/.test(c.body))
    .map((c) => c.name);
}

// ── 2. `t()` 를 쓰는 **컴포넌트마다** `useLang()` 이 있다 ────────────────────
//
// **1단계에서 실제로 밟은 함정이다** (보고서 §3 ①). `t()` 는 부르는 순간의 값을 줄 뿐
// 구독이 아니라, 이 훅이 없으면 그 부품만 옛 언어로 남는다. 증상이 「일부만 안 바뀐다」라
// 원인을 찾기 어렵다 — 2단계에서 네 번 빠뜨렸다.
{
  let checkedComponents = 0;
  for (const rel of DEMO_PATH) {
    // **`.tsx` 만 컴포넌트다.** `.ts` 는 순수 함수라 부르는 쪽이 훅을 갖고 있으면 된다
    // (`graph/shape.ts` 의 `shapeLabel()` 을 `main.tsx` 가 그리는 식).
    if (!rel.endsWith('.tsx')) continue;
    const src = code(read(rel));
    checkedComponents += components(src).filter((c) => /\bt\(/.test(c.body)).length;
    for (const name of missingHook(src)) {
      failures.push(`${rel}: ${name}() 가 t() 를 쓰는데 useLang() 이 없다 — 언어를 바꿔도 이 부품만 옛 언어로 남는다`);
    }
  }
  console.log(`✅ useLang() — t() 를 쓰는 컴포넌트 ${checkedComponents}개가 **하나씩** 전부 갖고 있다 (파일 단위가 아니다)`);
}

// ── 3. ko 키가 en 에도 있다 ──────────────────────────────────────────────────
//
// **시범 키 `mode.mock` 하나만 비어 있어야 한다.** 그 빈자리가 fallback 이 실제로 도는
// 증거이고(1단계 §4 다섯째), 채우면 2단계 이후로 그 증거가 사라진다.
{
  const EXPECTED_GAP = ['mode.mock'];
  const missing = Object.keys(ko).filter((key) => en[key] === undefined);
  const unexpected = missing.filter((key) => !EXPECTED_GAP.includes(key));
  const filled = EXPECTED_GAP.filter((key) => en[key] !== undefined);
  for (const key of unexpected) failures.push(`en 에 없는 키: ${key} — 시연 경로 키는 전부 있어야 한다`);
  for (const key of filled) failures.push(`${key} 가 en 에 채워졌다 — 이 빈자리가 fallback 이 도는 증거다 (1단계 §4 다섯째)`);
  const orphan = Object.keys(en).filter((key) => ko[key] === undefined);
  for (const key of orphan) failures.push(`ko 에 없는데 en 에만 있는 키: ${key} — 한국어가 없으면 fallback 이 키 이름을 그린다`);
  console.log(`✅ 사전 — ko ${Object.keys(ko).length}키 · en ${Object.keys(en).length}키 · 비어 있는 것은 ${EXPECTED_GAP.join(', ')} 하나뿐`);
}

// ── 4. 자리표시 데이터의 키가 값과 1:1인가 ───────────────────────────────────
//
// **2단계에서 실제로 글자를 하나 잃었다.** `pendingSources.ts` 의 요구사항 제목을
// `req.<ID>` 로 키를 만들어 사전에 옮겼는데, 같은 ID 가 **제목이 다른 채로 두 번** 나오는
// 자리가 있었다(`BE-T-04` — 「…관리(Birth/Death)」와 「…관리」). Map 에 담으면서 뒤엣것이
// 이겨 괄호가 조용히 사라졌고, 한국어 화면이 그만큼 바뀌었다 — §4 를 어긴 유일한 자리다.
//
// 키가 값과 1:1이 아니면 같은 일이 또 난다. 그래서 **id 가 겹치면 여기서 잡는다.**
{
  const { PENDING_SOURCES } = await import(pathToFileURL(join(root, 'src', 'shared', 'pendingSources.ts')).href);
  const ids = new Set();
  for (const spec of PENDING_SOURCES) {
    if (ids.has(spec.id)) failures.push(`자리표시 id 가 겹친다 — ${spec.id}. 키가 값과 1:1이 아니면 한쪽이 조용히 사라진다`);
    ids.add(spec.id);
    for (const key of ['title', 'what']) {
      if (ko[`pending.${spec.id}.${key}`] === undefined) failures.push(`사전에 pending.${spec.id}.${key} 가 없다`);
    }
    for (const sender of spec.from) {
      if (ko[`req.${sender.id}`] === undefined) failures.push(`사전에 req.${sender.id} 가 없다`);
    }
  }
  console.log(`✅ 자리표시 ${PENDING_SOURCES.length}건 · 요구사항 제목이 전부 사전에 있고 id 가 안 겹친다`);
}

// ── 5. 대조군 — 위 넷을 어긴 사본이 잡혀야 한다 ──────────────────────────────
//
// 실제 파일을 안 건드린다. 판정식에 손으로 만든 입력을 먹여 **잣대가 무는지**만 본다 —
// 진짜 위반이 하나라도 있으면 대조군이 그것 때문에 통과/실패해서 무엇을 확인한 것인지
// 알 수 없어진다 (검사 위생 260917 에서 세운 규약).
{
  const hangul = (src) => {
    const s = code(src);
    return [...[...s.matchAll(/(['"`])((?:[^\\\n]|\\.)*?)\1/g)].map((m) => m[2]).filter((v) => /[가-힣]/.test(v)),
      ...[...s.matchAll(/>([^<>{}]*[가-힣][^<>]*)</g)].map((m) => m[1])].length;
  };
  const cases = [
    ['JSX 에 한글을 도로 박은 사본', hangul('const a = <p>연결 예정</p>;') > 0, true],
    ['문자열에 한글을 도로 박은 사본', hangul("const a = '연결 예정';") > 0, true],
    ['주석의 한글 (잡으면 안 된다)', hangul('// 연결 예정을 그린다\nconst a = 1;') > 0, false],
    ['키만 든 코드 (잡으면 안 된다)', hangul("const a = <p>{t('conn.pendingBadge')}</p>;") > 0, false],

    // **이번에 뚫린 모양이다** (260917). 보간식 옆에 붙은 단위·연결어 — `12 노드` · `3판`.
    // 옛 규칙은 `>` 와 한글 사이의 `{` 때문에 이것을 **후보로도 안 봤다.**
    ['보간식 옆 단위 (이번에 뚫린 모양)', jsxTexts('<small>{items.length}판</small>').length > 0, true],
    ['보간식 사이 연결어', jsxTexts('<span>{a}/{b} 노드</span>').length > 0, true],
    ['여러 줄 JSX 의 보간식 옆 단위', jsxTexts('<p>\n  {a} · 그림 {b}장\n</p>').length > 0, true],
    // 오탐 — 코드의 비교 연산자를 텍스트 경계로 오인하면 안 된다. **닫는 `<` 의 모양**이 가른다.
    ['비교 연산자가 든 코드 줄 (잡으면 안 된다)', jsxTexts('if (x > 0) { const 이름 = 1; } y < z;').length > 0, false],
    ['화살표 함수가 든 줄 (잡으면 안 된다)', jsxTexts('const f = (a) => a > 1 ? 이름 : 0 < 2;').length > 0, false],
    // **줄에 `;` 가 있어도 진짜 텍스트면 잡아야 한다** — 코드 문법 목록으로 거르면 이것이 샌다.
    ['세미콜론이 붙은 진짜 JSX (잡아야 한다)', jsxTexts('return <p>3판</p>;').length > 0, true],

    // §3 — **둘째 컴포넌트에서 훅을 뺀 사본이 잡혀야 조인 것이다.**
    // 파일 단위 검사는 첫 컴포넌트의 `useLang()` 을 보고 통과시킨다.
    ['둘째 컴포넌트에서 useLang() 을 뺀 사본',
      missingHook("function First() {\n  useLang();\n  return <p>{t('a')}</p>;\n}\nfunction Second() {\n  return <p>{t('b')}</p>;\n}").join() === 'Second', true],
    ['둘 다 훅을 가진 사본 (잡으면 안 된다)',
      missingHook("function First() {\n  useLang();\n  return <p>{t('a')}</p>;\n}\nfunction Second() {\n  useLang();\n  return <p>{t('b')}</p>;\n}").length > 0, false],
    ['소문자 순수 함수의 t() (잡으면 안 된다)',
      missingHook("function helper() {\n  return t('a');\n}\nfunction View() {\n  useLang();\n  return <p>{helper()}</p>;\n}").length > 0, false],
  ];
  for (const [label, caught, shouldCatch] of cases) {
    if (caught !== shouldCatch) {
      failures.push(`대조군 실패: ${label} — ${shouldCatch ? '잡아야 하는데 놓쳤다' : '잡으면 안 되는데 잡았다'}. 이 검사는 무의미하다`);
    } else controls.push(label);
  }
}

if (failures.length) {
  console.error(`❌ verify:i18n-demo-path\n- ${failures.join('\n- ')}`);
  console.error('\n   시연 경로에 한글이 직접 박히면 한국어 화면은 멀쩡하고 영문 화면에서만 그 줄이 남는다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — 박힌 한글은 잡고, 주석과 키는 통과시킨다`);
