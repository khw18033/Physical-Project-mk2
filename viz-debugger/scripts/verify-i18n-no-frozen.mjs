// verify:i18n-no-frozen (260919 신설 — 영문화 4단계 뒤풀이)
//
// **모듈 최상위에서 `t()` 를 부르지 않는다.**
//
// 최상위 상수는 파일이 import 될 때 **한 번** 평가된다. 거기서 `t()` 를 부르면 그 순간의
// 언어로 글자가 굳고, 그 뒤로는 안 바뀐다. 새로고침으로 `?lang=en` 을 열면 맞게 나오므로
// **언어 버튼으로 바꿀 때만 틀린다** — 사람이 실제로 쓰는 길이 그쪽이다.
//
// 이 규칙은 영문화 1단계부터 지시서 §1 에 있었다. 그런데 4단계에서 표시 한글을 `t()` 로
// 바꾸는 순간 **한글이 사라져 `verify:no-raw-korean` 이 초록이 되고, 굳은 것은 아무 검사에도
// 안 걸렸다.** 260919 에 사람이 화면을 보고 「아직 임무가 없습니다」를 찾아 알았고, 훑어
// 보니 29자리였다. 그래서 규칙을 검사로 굳힌다.
//
// ## 무엇이 「최상위」인가
//
//   const X = t('k')                  ← 굳는다. 로드 때 바로 부른다
//   const X = { a: t('k') }           ← 굳는다
//   const X = f()  ·  function f(){ t() }  ← 굳는다. 부른 함수가 안에서 부른다
//   const f = () => t('k')            ← **안 굳는다.** 몸통은 나중에 불린다
//   function f() { t('k') }           ← 안 굳는다
//
// 고치는 법은 **키를 담는 것**이다 — `X_KEY` · `labelKey` · `whyKey`. 푸는 것은 읽는 쪽 몫이다.
import { readdirSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isScratchPath } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const srcDir = join(root, 'src');

const failures = [];
const controls = [];

/** 문자열·주석을 공백으로 — 줄과 열을 보존한다. */
function blank(src) {
  let out = '';
  let i = 0;
  const keep = (c) => (c === '\n' ? '\n' : ' ');
  while (i < src.length) {
    const c = src[i];
    if (c === '/' && src[i + 1] === '/') {
      while (i < src.length && src[i] !== '\n') out += keep(src[i++]);
      continue;
    }
    if (c === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2);
      const stop = end === -1 ? src.length : end + 2;
      while (i < stop) out += keep(src[i++]);
      continue;
    }
    if (c === "'" || c === '"' || c === '`') {
      const q = c;
      out += ' ';
      i += 1;
      while (i < src.length) {
        if (src[i] === '\\') { out += '  '; i += 2; continue; }
        if (src[i] === q) { out += ' '; i += 1; break; }
        out += keep(src[i++]);
      }
      continue;
    }
    out += c;
    i += 1;
  }
  return out;
}

const CALLS_T = /(^|[^A-Za-z0-9_$.])tr?\s*\(/;

/** 이름 있는 함수의 몸통을 떼어 낸다 — 안에서 `t()` 를 부르는지만 보면 된다. */
function bodyOf(code, name) {
  const re = new RegExp(`(?:function\\s+${name}\\s*\\(|(?:const|let|var)\\s+${name}\\s*(?::[^=]*)?=\\s*(?:async\\s*)?(?:function\\s*)?\\()`);
  const m = re.exec(code);
  if (m === null) return null;
  const i = code.indexOf('{', m.index + m[0].length - 1);
  if (i === -1) return null;
  let depth = 0;
  for (let j = i; j < code.length; j += 1) {
    if (code[j] === '{') depth += 1;
    else if (code[j] === '}') { depth -= 1; if (depth === 0) return code.slice(i, j + 1); }
  }
  return null;
}

/** 로드 때 굳는 자리. `{rel, ln, kind}` 목록을 돌려준다. */
export function frozenSites(src) {
  const code = blank(src);
  const lines = code.split('\n');
  const rawLines = src.split('\n');
  const hits = [];

  // 최상위 **문(statement)** 을 통째로 모은다 — 선언이 여러 줄에 걸친다.
  let depth = 0;
  let open = null;
  const stmts = [];
  for (let n = 0; n < lines.length; n += 1) {
    if (open === null && depth === 0 && /^(?:export\s+)?(?:const|let|var)\s+[A-Za-z0-9_$]+/.test(rawLines[n] ?? '')) {
      open = { start: n, lines: [] };
    }
    if (open !== null) open.lines.push(lines[n]);
    for (const c of lines[n]) {
      if (c === '{' || c === '(' || c === '[') depth += 1;
      else if (c === '}' || c === ')' || c === ']') depth = Math.max(0, depth - 1);
    }
    if (open !== null && depth === 0) {
      stmts.push({ n: open.start, body: open.lines.join('\n') });
      open = null;
    }
  }

  for (const stmt of stmts) {
    const body = stmt.body;
    // 화살표·함수 **선언**은 몸통이 나중에 불린다 — 굳지 않는다.
    if (/=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_$]+)\s*=>/.test(body)) continue;
    if (/=\s*(?:async\s*)?function\b/.test(body)) continue;

    if (CALLS_T.test(body)) { hits.push({ ln: stmt.n + 1, kind: '바로' }); continue; }
    for (const call of body.matchAll(/(^|[^A-Za-z0-9_$.])([a-z][A-Za-z0-9_$]*)\s*\(/g)) {
      const name = call[2];
      if (name === 'require' || name === 'import') continue;
      const fn = bodyOf(code, name);
      if (fn !== null && CALLS_T.test(fn)) hits.push({ ln: stmt.n + 1, kind: `${name}() 를 거쳐` });
    }
  }
  return hits;
}

// ── 1. 최상위에서 t() 를 부르는 자리가 없다 ─────────────────────────────────
{
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

  let scanned = 0;
  let frozen = 0;
  for (const abs of files) {
    const rel = relative(srcDir, abs).split(sep).join('/');
    if (rel.startsWith('i18n/')) continue;
    scanned += 1;
    for (const hit of frozenSites(readSource(abs))) {
      frozen += 1;
      failures.push(`${rel}:${hit.ln} — 최상위에서 ${hit.kind} t() 를 부른다. 로드 시점 언어로 굳어 **언어 버튼을 안 따라온다**`);
    }
  }
  // **센 값을 적는다.** 「0건」을 글자로 박으면 실패할 때도 0이라고 말한다 —
  // 3단계 `verify:stt-language` · 4단계 `verify:no-raw-korean` 에 이어 세 번째다.
  console.log(`✅ ${scanned}개 파일 — 최상위에서 t() 를 부르는 자리 ${frozen}건`);
}

// ── 2. 대조군 ───────────────────────────────────────────────────────────────
{
  const cases = [
    ["const X = t('k');", 1, '바로 부르는 최상위 상수를 잡는다'],
    ["const X = { a: t('k'), b: t('k2') };", 1, '표 안에서 부르는 것을 잡는다'],
    ["function make() { return t('k'); }\nlet state = { cur: make() };", 1, '부른 함수가 안에서 부르는 것을 잡는다'],
    ["const f = () => t('k');", 0, '화살표 함수는 통과시킨다 — 몸통은 나중에 불린다'],
    ["function f() { return t('k'); }", 0, '함수 선언은 통과시킨다'],
    ["// const X = t('k');\nconst Y = 1;", 0, '주석은 안 센다'],
    ["const X = 't(k)';", 0, '문자열 안은 안 센다'],
  ];
  for (const [src, want, why] of cases) {
    const got = frozenSites(src).length;
    if ((want === 0) !== (got === 0)) {
      failures.push(`대조군 실패: ${why} — ${want === 0 ? '잡으면 안 되는데 잡았다' : '잡아야 하는데 못 잡았다'} (${got}건)`);
    } else controls.push(why);
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:i18n-no-frozen\n- ${failures.join('\n- ')}`);
  console.error('\n   최상위에는 **글자가 아니라 키**를 담아라 — `X_KEY` · `labelKey` · `whyKey`.');
  console.error('   푸는 것은 읽는 쪽 몫이다 (`t(X_KEY[v])`).');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
