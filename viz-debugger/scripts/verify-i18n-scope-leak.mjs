// verify:i18n-scope-leak (260918 신설)
//
// **범위를 파일 목록으로 그으면 샌다.**
//
// ## 무엇이 있었나
//
// 영문화 2단계가 「시연 경로 22개 파일 · 608개 문구」를 사전으로 옮겼고, `verify:i18n-demo-path`
// 가 그 22개 파일에 표시용 한글이 0건임을 지켰다. 초록이었다. 그런데 **화면은 한국어였다.**
//
// ```
//   ConnectionsPanel.tsx   ← 범위 안. 한글 0건.
//     └ shared/connections.ts  ← 범위 밖. 「로봇 (MQTT 브로커)」 「객체 탐지」 …
//   MissionHistory.tsx     ← 범위 안. 한글 0건.
//     └ data/missionHistory.ts ← 범위 밖. 「완료」 「실패」 「정지」
// ```
//
// 화면을 그리는 파일은 옮겼는데 **그 파일이 읽어서 그리는 값**은 안 옮겼다. 검사는 파일
// 안만 보므로 이 모양을 볼 수 없었다. 260917 에 사람이 화면을 보고 둘을 찾아냈고, 그래서
// 훑었더니 같은 모양이 **33곳 130건**이었다.
//
// ## 무엇을 보는가
//
// 시연 경로 파일이 `import` 하는 이름을 따라가, **그 이름의 선언 몸통 안에 표시용 한글이
// 있는지** 본다. 있으면 그 글자는 화면에 뜨는데 사전을 안 탄다.
//
// ### 아는 예외 — 아직 안 옮긴 컴포넌트
//
// `DetectActionLog`·`AutodriveViews` 는 범위 밖의 **컴포넌트**이고 자기 화면을 스스로 그린다.
// 이것들은 4단계에서 통째로 옮기기로 선언된 것이라 여기서 붙잡지 않는다. 다만 **목록으로
// 못박는다** — 늘면 여기가 먼저 걸리고, 4단계가 끝나면 이 목록이 비어야 한다.
//
// ## 대조군
//
// 범위 파일이 읽는 모듈에 한글 상수를 하나 심은 사본이 반드시 잡혀야 한다.
import { existsSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
// **줄끝을 먼저 고른다** (검사 위생 §1). 이 저장소의 파일은 CRLF 이고, 여러 줄 문자열로
// 맞추는 자리가 이 검사에 있다 — 날것으로 읽으면 대조군이 조용히 아무것도 안 바꾼다.
import { mutate, readSource } from './lib/source.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const srcDir = join(root, 'src');

/**
 * 2단계 범위 (`verify-i18n-demo-path.mjs` 의 `DEMO_PATH` 와 같은 목록).
 *
 * **여기가 갈라지면 두 검사가 다른 것을 지킨다.** 한쪽을 고치면 다른 쪽도 고쳐야 한다 —
 * 아래 §0 이 그것을 본다.
 */
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
 * **4단계에서 통째로 옮길 컴포넌트.** 이것들은 자기 화면을 스스로 그리므로 「값이 새는」
 * 모양이 아니다 — 아직 안 옮긴 화면일 뿐이다. 늘면 안 된다: 새로 생기면 여기가 걸린다.
 */
const PENDING_STAGE4 = [
  'detect/views/DetectActionLog.tsx',
  'autodrive/views/AutodriveViews.tsx',
  // 260918 — 검사가 JSX 텍스트를 읽게 되면서 드러났다. 자율주행 편의 사실 줄이라
  // 바로 위 `AutodriveViews` 와 한 식구다. 문 찾기 시연 경로에는 안 뜬다.
  'physical/NavFacts.tsx',
];

/**
 * **계약에 실려 나가는 값.** 화면에도 뜨지만 명령 payload 로도 나가므로 옮기면 같은 판정이
 * 두 값으로 기록된다. 화면용 사전 키는 따로 있다 (`stt.provisionalNote`).
 */
const CONTRACT_VALUES = ['PROVISIONAL_NOTE'];

const failures = [];
const controls = [];

/** 주석을 지운다 — **문자열 안의 `/*` 에 안 속는다** (`verify-i18n-demo-path.mjs` 와 같은 구현). */
function code(src) {
  let out = '';
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (c === '"' || c === "'" || c === '`') {
      out += c;
      i += 1;
      while (i < src.length && src[i] !== c) {
        if (src[i] === '\\') { out += src[i] + (src[i + 1] ?? ''); i += 2; continue; }
        out += src[i];
        i += 1;
      }
      out += src[i] ?? '';
      i += 1;
      continue;
    }
    if (c === '/' && src[i + 1] === '*') { const e = src.indexOf('*/', i + 2); i = e < 0 ? src.length : e + 2; out += '\n'; continue; }
    if (c === '/' && src[i + 1] === '/') { const e = src.indexOf('\n', i); i = e < 0 ? src.length : e; continue; }
    out += c;
    i += 1;
  }
  return out;
}

/**
 * JSX 텍스트 노드의 한글 — **문자열 리터럴이 아니다.**
 *
 * ## 260918 — 여기가 비어 있었다
 *
 * 처음 이 검사는 가져온 이름의 몸통에서 **문자열 리터럴만** 셌다. 그런데 컴포넌트를
 * 가져다 그리는 경우 그 안의 한글은 대개 JSX 텍스트다.
 *
 * ```jsx
 *   <span>배터리<strong>{device.battery}%</strong></span>
 * //       ^^^^ 문자열 리터럴이 아니다
 * ```
 *
 * `views/ActionModal.tsx`(범위 안)가 `views/DeviceStrip.tsx`(범위 밖)를 그리는데 그 안의
 * 한글 다섯이 전부 이 모양이라 **검사는 「새는 값 0건」이라고 말했다.** 사람이 화면에서
 * 한국어를 보고 알려 줘서 찾았다 — 2단계에서 한 번 겪은 것과 같은 모양이다.
 *
 * 잣대는 `verify-i18n-demo-path.mjs` 의 것과 같다.
 */
/** 문자열 리터럴의 속. 따옴표 셋을 다 보고, 이스케이프한 따옴표에 안 끊긴다. */
function stringLiterals(src) {
  return [...src.matchAll(/(['"`])((?:[^\\\n]|\\.)*?)\1/g)].map((m) => m[2]);
}

const CODE_MARKS = [';', '=>', 'const ', 'let ', 'return ', 'function ', 'import ', '&&', '||', '??'];
function jsxTexts(src) {
  let s = src;
  let prev;
  do { prev = s; s = s.replace(/\{[^{}<>]*\}/g, '{}'); } while (s !== prev);
  return [...s.matchAll(/>([^<>]*[가-힣][^<>]*)<(?=[/A-Za-z])/g)]
    .map((m) => m[1].replace(/\s+/g, ' ').trim())
    .filter((v) => v !== '' && !CODE_MARKS.some((k) => v.includes(k)));
}

const relOf = (abs) => relative(srcDir, abs).split(sep).join('/');

function resolveImport(fromAbs, spec) {
  if (!spec.startsWith('.')) return null;
  const base = resolve(dirname(fromAbs), spec);
  for (const cand of [base, `${base}.ts`, `${base}.tsx`, join(base, 'index.ts'), join(base, 'index.tsx')]) {
    if (existsSync(cand) && /\.(ts|tsx)$/.test(cand)) return cand;
  }
  return null;
}

/** `{ a, b as c, type D }` · `X` · `X, { a }` → 원래 이름 목록. `type` 은 뺀다 — 값이 안 온다. */
function importedNames(clause) {
  const out = [];
  const braced = clause.match(/\{([\s\S]*)\}/);
  const bare = clause.replace(/\{[\s\S]*\}/, '').replace(/,/g, ' ').trim();
  if (bare !== '' && !bare.startsWith('*')) out.push(bare);
  if (braced) {
    for (const part of braced[1].split(',')) {
      const p = part.trim();
      if (p === '' || p.startsWith('type ')) continue;
      out.push(p.split(/\s+as\s+/)[0].trim());
    }
  }
  return out;
}

/**
 * 이름의 선언 몸통.
 *
 * **타입 표기를 먼저 건너뛴다.** `export const X: readonly T[] = [` 에서 그냥 괄호를 세면
 * `T[]` 의 대괄호가 열자마자 닫혀 몸통을 한 글자도 못 읽는다 — 훑기를 처음 돌렸을 때
 * `CONNECTION_TARGETS` 24건이 통째로 안 잡힌 이유가 이것이었다.
 */
function declaration(text, name) {
  const re = new RegExp(`^\\s*export\\s+(?:async\\s+)?(const|let|function|class)\\s+${name}\\b`, 'm');
  const m = re.exec(text);
  if (m === null) return null;
  let i = m.index + m[0].length;
  if (m[1] === 'const' || m[1] === 'let') {
    const eq = text.indexOf('=', i);
    if (eq < 0) return null;
    i = eq + 1;
  } else {
    /**
     * **매개변수 목록을 먼저 지나친다** (260918 두 번째 수습).
     *
     * 그냥 다음 `{` 부터 세면 구조 분해가 몸통으로 읽힌다.
     *
     * ```ts
     *   export function DeviceStrip({ device }: { device: Device }) {
     * //                            ^^^^^^^^^^ 여기서 열고 닫혀 몸통을 한 줄도 안 읽는다
     * ```
     *
     * `views/DeviceStrip.tsx` 의 한글 다섯이 이것 때문에 안 잡혔다. 여는 `(` 를 찾아
     * 짝이 맞는 `)` 까지 건너뛴 뒤의 `{` 가 진짜 몸통이다.
     */
    const paren = text.indexOf('(', i);
    if (paren >= 0) {
      let d = 0;
      let k = paren;
      for (; k < text.length; k += 1) {
        if (text[k] === '(') d += 1;
        else if (text[k] === ')') { d -= 1; if (d === 0) { k += 1; break; } }
      }
      i = k;
    }
    const brace = text.indexOf('{', i);
    if (brace < 0) return null;
    i = brace;
  }
  const start = i;
  let depth = 0;
  let started = false;
  for (; i < text.length; i += 1) {
    const c = text[i];
    if (c === '{' || c === '[' || c === '(') { depth += 1; started = true; }
    else if (c === '}' || c === ']' || c === ')') { depth -= 1; if (started && depth === 0) { i += 1; break; } }
    else if (!started && (c === ';' || c === '\n')) break;
  }
  return text.slice(start, i);
}

/**
 * 한 파일이 읽어 오는, 한글이 든 자리들.
 *
 * 원본과 **읽어 오는 모듈**을 둘 다 함수로 받는다 — 대조군이 「원천 모듈에 한글을 심은
 * 사본」을 만들려면 그 모듈의 내용을 갈아 끼울 수 있어야 하기 때문이다. 파일에서 바로
 * 읽으면 대조군이 실제 경로를 안 타고, 그러면 무엇을 시험했는지 알 수 없다.
 */
function leaks(entry, sourceOf, depSourceOf = (_rel, abs) => readSource(abs)) {
  const abs = join(srcDir, entry);
  const text = sourceOf(entry);
  const found = [];
  for (const m of text.matchAll(/import\s+(type\s+)?([\s\S]*?)\s*from\s*['"]([^'"]+)['"]/g)) {
    if (m[1]) continue;
    const target = resolveImport(abs, m[3]);
    if (target === null) continue;
    const rel = relOf(target);
    if (DEMO_PATH.includes(rel) || rel.startsWith('i18n/')) continue;
    const dep = code(depSourceOf(rel, target));
    for (const name of importedNames(m[2])) {
      if (CONTRACT_VALUES.includes(name)) continue;
      const decl = declaration(dep, name);
      if (decl === null) continue;
      const hits = [
        ...stringLiterals(decl).filter((v) => /[가-힣]/.test(v)),
        // 컴포넌트를 가져다 그리면 한글은 대개 JSX 텍스트다 (위 `jsxTexts` 주석).
        ...jsxTexts(decl),
      ];
      if (hits.length > 0) found.push({ entry, rel, name, hits });
    }
  }
  return found;
}

const read = (rel) => readSource(join(srcDir, rel));

// ── 0. 두 검사가 같은 범위를 지킨다 ──────────────────────────────────────────
{
  const other = readSource(join(root, 'scripts', 'verify-i18n-demo-path.mjs'));
  const missing = DEMO_PATH.filter((rel) => !other.includes(`'${rel}'`));
  if (missing.length > 0) {
    failures.push(`범위 목록이 verify:i18n-demo-path 와 갈라졌다 — 거기 없는 것 ${missing.length}건: ${missing.join(', ')}`);
  }
  console.log(`✅ 범위 — 두 검사가 같은 ${DEMO_PATH.length}개 파일을 본다`);
}

// ── 1. 범위 파일이 읽어서 그리는 한글이 없다 ─────────────────────────────────
{
  const found = [];
  for (const entry of DEMO_PATH) found.push(...leaks(entry, read));
  const unexpected = found.filter((f) => !PENDING_STAGE4.includes(f.rel));
  for (const f of unexpected) {
    failures.push(`${f.entry} 가 ${f.rel} 의 \`${f.name}\` 를 가져다 그린다 — 그 안에 한글 ${f.hits.length}건: 「${f.hits[0]}」`);
  }
  const held = found.filter((f) => PENDING_STAGE4.includes(f.rel));
  console.log(`✅ 새는 값 0건 — 범위 밖 컴포넌트 ${new Set(held.map((f) => f.rel)).size}개(${held.reduce((s, f) => s + f.hits.length, 0)}건)만 4단계로 미뤄 둔다`);
}

// ── 2. 미뤄 둔 목록이 실재한다 ───────────────────────────────────────────────
//
// 4단계가 끝나 그 파일에서 한글이 사라지면 이 목록도 지워야 한다. 안 지우면 다음에
// 누가 그 파일에 한글을 넣어도 이 검사가 눈감는다.
{
  for (const rel of PENDING_STAGE4) {
    const path = join(srcDir, rel);
    if (!existsSync(path)) { failures.push(`미뤄 둔 목록의 ${rel} 가 없다 — 목록에서 지워라`); continue; }
    if (!/[가-힣]/.test(code(readSource(path)))) {
      failures.push(`${rel} 에 한글이 더 없다 — 4단계가 끝났으면 PENDING_STAGE4 에서 지워라 (남겨 두면 이 검사가 그 파일을 눈감는다)`);
    }
  }
  console.log(`✅ 미뤄 둔 목록 ${PENDING_STAGE4.length}개가 실재하고 아직 한글이 남아 있다`);
}

// ── 3. 대조군 ────────────────────────────────────────────────────────────────
{
  // ① 범위 파일이 읽는 모듈에 한글 상수를 심은 사본은 잡혀야 한다.
  //
  //    **양쪽을 다 갈아 끼운다** — 원천 모듈에 상수를 심고, 범위 파일이 그것을 실제로
  //    `import` 하게 한다. 한쪽만 바꾸면 이 대조군은 늘 통과하고 아무것도 시험하지 않는다.
  //
  //    `mutate()` 는 **아무것도 안 바뀌면 null 을 준다** (검사 위생 §1). 조용히 통과하던
  //    대조군을 그때 잡으려고 만든 것이고, 여기가 딱 그 자리다.
  const entrySource = mutate(
    read('shell/ConnectionsPanel.tsx'),
    'import {\n  CONNECTION_TARGETS,',
    'import {\n  SNEAKY_LABEL,\n  CONNECTION_TARGETS,',
  );
  const depSource = mutate(
    read('shared/connections.ts'),
    'export const CONNECTION_TARGETS',
    "export const SNEAKY_LABEL = '새는 이름';\nexport const CONNECTION_TARGETS",
  );
  const sneaked = entrySource === null || depSource === null ? [] : leaks(
    'shell/ConnectionsPanel.tsx',
    () => entrySource,
    (rel, abs) => (rel === 'shared/connections.ts' ? depSource : readSource(abs)),
  );
  if (entrySource === null || depSource === null) {
    failures.push('대조군을 만들지 못했다 — 심을 자리를 못 찾았다 (원본이 바뀌었나?)');
  } else if (!sneaked.some((f) => f.name === 'SNEAKY_LABEL')) {
    failures.push('대조군 실패: 범위 밖 모듈에 심은 한글 상수를 놓쳤다 — 이 검사는 무의미하다');
  } else controls.push('범위 파일이 가져가는 한글 상수를 심은 사본');

  // ② `import type` 은 잡으면 안 된다 — 값이 안 오므로 글자도 안 온다.
  const typeOnly = (rel) => rel === 'shell/ConnectionLamp.tsx'
    ? read(rel).replace("import { CONNECTION_TARGETS }", "import type { CONNECTION_TARGETS }")
    : read(rel);
  if (leaks('shell/ConnectionLamp.tsx', typeOnly).length > 0) {
    failures.push('대조군 실패: `import type` 을 잡았다 — 타입만 가져오면 글자는 안 온다');
  } else controls.push('`import type` 은 통과시킨다');

  // ③ 계약 값(`PROVISIONAL_NOTE`)은 잡으면 안 된다 — 옮기면 기록이 갈라진다.
  if (leaks('views/UtterancePanel.tsx', read).some((f) => f.name === 'PROVISIONAL_NOTE')) {
    failures.push('대조군 실패: 계약 값을 잡았다 — 그것은 payload 로 나가므로 옮기면 안 된다');
  } else controls.push('계약 값 PROVISIONAL_NOTE 는 통과시킨다');
}

if (failures.length > 0) {
  console.error(`❌ verify:i18n-scope-leak\n- ${failures.join('\n- ')}`);
  console.error('\n   화면을 그리는 파일만 옮기면, 그 파일이 읽는 값은 영문 화면에 한국어로 남는다.');
  console.error('   원천 모듈에 **글자 대신 사전 키**를 담고 읽는 자리에서 t() 로 풀어라.');
  console.error('   (모듈 최상위 상수에서 t() 를 부르면 로드 시점 언어로 굳는다.)');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
