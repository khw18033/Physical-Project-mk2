// verify:crlf-safe (260921 신설 — 검사 줄바꿈 지시서 §1)
//
// **대조군을 만드는 검사가 줄끝에 걸려 조용히 죽지 않는가.**
//
// ## 무엇이 일어났나
//
// `.gitattributes` 가 `* text=auto` 다 — **저장소는 LF, 윈도우 작업 트리는 CRLF.** 일부러
// 그렇게 못박은 규칙이고 그 파일에 이유까지 적혀 있다. 그런데 대조군을 만드는 치환이
// 여러 줄을 찾으면 자리표에 `\n` 이 들어간다.
//
// ```js
// source.replace('    if (event.atSec > second) break;\n    if (!ACTION_KIND_SET…', …)
// ```
//
// 작업본은 `\r\n` 이라 **`replace` 가 아무것도 못 찾고 원본을 그대로 돌려준다.** 검사는
// 그것을 「대조군을 만들지 못했다」로 잡아낸다 — 검사가 제 일을 한 것이다. 다만
// **WSL 에서는 초록, 윈도우에서는 빨강**이라 260920 보고서의 80/80 이 WSL 기준이 됐다.
//
// ## 왜 `\r?\n` 정규식이 아니라 입구 정규화인가
//
// 찾는 쪽을 `\r?\n` 으로 바꾸면 **대조군이 늘어날 때마다 사람이 기억해야 하는 규칙**이 되고,
// 한 번 잊으면 조용히 통과한다. 입구에서 한 번 정규화하면 잊을 자리가 없다.
//
// > **대조군은 LF 로 정규화한 원본에서 만든다.** — `readSource()` (lib/source.mjs)
//
// ## 이 검사가 보는 것
//
// 소스만 본다. 돌릴 필요가 없어 빠르다.
//
//  1. **`replace(` 안에 `\n` 이 있는데 원본을 정규화하지 않으면 실패** — 그 파일은
//     `readSource()` 로 읽어야 한다. 맨 `readFileSync` 는 위반이다
//  2. 대조군 — **정규화를 되돌린 사본이 반드시 잡혀야 한다**
//  3. 반대 대조군 — 정당한 것(`readSource` · JSON 읽기 · 한 줄 치환)은 **잡으면 안 된다**
//
// 이것이 없으면 다음에 검사를 하나 더 쓸 때 다시 밟는다. 260920 에 넷을 새로 썼고
// **그중 둘이 밟았다.**
import { readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readSource } from './lib/source.mjs';

const scriptsDir = dirname(fileURLToPath(import.meta.url));

const failures = [];
const controls = [];

/**
 * **이 파일 자신은 대상에서 뺀다.** 아래 대조군이 「위반하는 코드」를 문자열로 들고 있어서
 * 자기 규칙에 자기가 걸린다 — `verify:verify-hygiene` 이 같은 이유로 자신을 뺀다.
 */
const SELF = 'verify-crlf-safe.mjs';

/**
 * **정규화하는 자리 그 자신.** `readSource()` 안에 `\r\n` → `\n` 치환이 있고 `readFileSync`
 * 를 부르는 것이 당연하다. 여기까지 규칙을 물리면 정규화 자체를 금지하게 된다.
 */
const NORMALIZER = 'lib/source.mjs';

const FILES = [
  ...readdirSync(scriptsDir).filter((n) => n.endsWith('.mjs')).map((n) => ({ name: n, path: join(scriptsDir, n) })),
  ...readdirSync(join(scriptsDir, 'lib')).filter((n) => n.endsWith('.mjs')).map((n) => ({ name: `lib/${n}`, path: join(scriptsDir, 'lib', n) })),
].filter((f) => f.name !== SELF && f.name !== NORMALIZER);

/** 주석을 지운 소스. 규칙을 설명하는 주석이 규칙 위반으로 잡히면 안 된다. */
function code(text) {
  return text.replace(/[/][*][^]*?[*][/]/g, '').replace(/^[ \t]*[/][/].*$/gm, '');
}

/** 소스에 적힌 역슬래시-n **두 글자**. 실제 줄바꿈이 아니다. */
const NEWLINE_ESCAPE = /\\n/;

/**
 * 정규화 치환 그 자신 — `.replaceAll('\r\n', '\n')` · `.replace(/\r\n/g, '\n')`.
 *
 * **이것을 빼지 않으면 정규화하는 파일이 정규화를 안 한다고 잡힌다.** 실제로
 * `verify:plan-shape` 와 `verify:proposal-gate` 가 그렇게 걸렸다 — 둘은 제대로 하고 있었다.
 */
const NORMALIZE_CALL = /\\r\\n/;

/**
 * `.replace(` · `.replaceAll(` 의 **인자 전체**를 괄호 짝을 세어 떠낸다.
 *
 * 정규식 한 방으로 `replace\([^)]*\\n` 을 찾으면 인자 안의 `(event.kind)` 같은 괄호에서
 * 끊긴다 — 실제로 고친 다섯 중 셋이 그런 모양이다.
 */
function replaceArguments(source) {
  const args = [];
  const opener = /[.]replace(?:All)?[(]/g;
  let match;
  while ((match = opener.exec(source)) !== null) {
    let depth = 0;
    let i = match.index + match[0].length - 1;
    for (; i < source.length; i += 1) {
      const c = source[i];
      if (c === '(') depth += 1;
      else if (c === ')') { depth -= 1; if (depth === 0) break; }
    }
    args.push(source.slice(match.index + match[0].length, i));
  }
  return args;
}

/**
 * **정규화를 안 지난 읽기.** 둘은 해당 없다.
 *
 *   · `JSON.parse(readFileSync(…))` — JSON 은 줄끝을 안 가리고, 그렇게 읽은 것을
 *     문자열 치환으로 무력화하는 자리도 없다
 *   · `readFileSync(…).replaceAll('\r\n', '\n')` — 손으로 적었을 뿐 정규화는 했다.
 *     `readSource()` 쪽을 권하지만 **틀린 것은 아니므로 실패시키지 않는다**
 */
function bareReads(source) {
  const re = /readFileSync[(]/g;
  const hits = [];
  let match;
  while ((match = re.exec(source)) !== null) {
    if (/JSON[.]parse[(]\s*$/.test(source.slice(0, match.index))) continue;
    // 읽기 호출의 닫는 괄호를 찾아, 바로 뒤에 정규화가 붙어 있는지 본다.
    let depth = 0;
    let i = match.index + match[0].length - 1;
    for (; i < source.length; i += 1) {
      const c = source[i];
      if (c === '(') depth += 1;
      else if (c === ')') { depth -= 1; if (depth === 0) break; }
    }
    if (NORMALIZE_CALL.test(source.slice(i, i + 40))) continue;
    hits.push(match.index);
  }
  return hits;
}

/** 여러 줄 자리표 — 정규화 치환 그 자신은 빼고 센다. */
function multilineNeedles(source) {
  return replaceArguments(source).filter((a) => NEWLINE_ESCAPE.test(a) && !NORMALIZE_CALL.test(a)).length;
}

/** 이 소스가 규칙을 어기는가. 대조군도 **같은 잣대**를 문다. */
function offends(text) {
  const source = code(text);
  const risky = multilineNeedles(source);
  if (risky === 0) return null;
  const bare = bareReads(source).length;
  if (bare === 0) return null;
  return { risky, bare };
}

// ── 1. 본검사 ───────────────────────────────────────────────────────────────
{
  let normalized = 0;
  for (const f of FILES) {
    const text = readSource(f.path);
    const verdict = offends(text);
    if (verdict) {
      failures.push(
        `${f.name}: 대조군 자리표에 \\n 이 ${verdict.risky}곳 있는데 원본을 정규화하지 않는다 ` +
        `(맨 readFileSync ${verdict.bare}곳) — readSource() 를 써라 (lib/source.mjs). ` +
        'CRLF 작업본에서 치환이 아무것도 못 찾고 「대조군을 만들지 못했다」로 떨어진다',
      );
      continue;
    }
    if (multilineNeedles(code(text)) > 0) normalized += 1;
  }
  console.log(`✅ 여러 줄 대조군을 쓰는 ${normalized}개 검사가 전부 LF 로 정규화한 원본에서 만든다 (윈도우·WSL 이 같은 답을 낸다)`);
}

// ── 2. 대조군 — 정규화를 되돌린 사본이 잡혀야 한다 ──────────────────────────
//
// **실제 파일을 건드리지 않는다.** 메모리 안에서 `readSource(` 를 맨 `readFileSync(` 로
// 되돌리고 잣대가 무는지만 본다 — 260920 직전의 코드가 정확히 그 모양이었다.
{
  const REVERTED = [
    ['verify-no-answer.mjs', 'readSource(actionPath)', "readFileSync(actionPath, 'utf8')"],
    ['verify-adjust-pair.mjs', 'readSource(actionPath)', "readFileSync(actionPath, 'utf8')"],
    ['verify-fold-actions.mjs', 'readSource(foldPath)', "readFileSync(foldPath, 'utf8')"],
    ['verify-action-trace.mjs', "readSource(root, 'src', 'physical', 'robotCommands.ts')",
      "readFileSync(join(root, 'src', 'physical', 'robotCommands.ts'), 'utf8')"],
    ['verify-human-trace.mjs', 'readSource(tracePath)', "readFileSync(tracePath, 'utf8')"],
  ];
  for (const [name, from, to] of REVERTED) {
    const text = readSource(join(scriptsDir, name));
    if (!text.includes(from)) {
      failures.push(`대조군을 만들지 못했다 — ${name} 에서 「${from}」를 못 찾았다 (원본이 바뀌었나?)`);
      continue;
    }
    if (offends(text.replace(from, to)) === null) {
      failures.push(`대조군 실패: ${name} 의 정규화를 되돌린 사본이 통과했다 — 이 검사는 무의미하다`);
    } else {
      controls.push(`${name} 의 정규화를 되돌린 사본`);
    }
  }
}

// ── 3. 반대 대조군 — 정당한 것을 잡으면 안 된다 ─────────────────────────────
//
// 「전부 실패」하는 잣대는 아무것도 안 재는 것과 같다. 물면 안 되는 것 셋을 같이 먹인다.
{
  const INNOCENT = [
    ['readSource 로 읽고 여러 줄을 치환하는 사본',
      "const source = readSource(p);\nconst m = source.replace('a;\\nb;', 'b;');"],
    ['JSON 을 읽는 사본 (줄끝을 안 가린다)',
      "const s = JSON.parse(readFileSync(p, 'utf8'));\nconst m = t.replace('a;\\nb;', 'b;');"],
    ['한 줄짜리만 치환하는 사본 (맨 읽기여도 안 걸린다)',
      "const source = readFileSync(p, 'utf8');\nconst m = source.replace('a;', 'b;');"],
  ];
  for (const [label, sample] of INNOCENT) {
    if (offends(sample) !== null) {
      failures.push(`반대 대조군 실패: ${label} 을 잡았다 — 잣대가 너무 넓다`);
    } else {
      controls.push(`${label} (안 잡음)`);
    }
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:crlf-safe\n- ${failures.join('\n- ')}`);
  console.error('\n   대조군은 LF 로 정규화한 원본에서 만든다. 입구에서 한 번 하면 잊을 자리가 없다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — 정규화를 되돌린 사본은 잡고, 정당한 것(readSource · JSON · 한 줄 치환)은 통과시킨다`);
