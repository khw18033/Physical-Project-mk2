// verify:dict-shape (260918 신설 — 영문화 4단계)
//
// **두 사전의 같은 키가 같은 모양인가.**
//
// ## 무엇이 있었나
//
// 4단계는 사전을 기계로 부풀린다 — 원본에서 뽑은 한국어 목록과 내가 쓴 영어 목록을
// **차례로 짝지어** 넣는다. 그 짝이 한 칸 밀리면 `mv.20` 의 영어 자리에 `mv.21` 의 영어가
// 들어가고, **검사도 타입도 그것을 못 본다.** 사전은 그냥 문자열 표이기 때문이다.
//
// 묶음 4b 에서 실제로 영어 한 줄이 빠져 32:33 이 됐다. 그때는 개수가 달라 생성기가
// 죽었지만, **개수가 우연히 맞으면 조용히 어긋난다.**
//
// ## 치환자가 증거다
//
// 어긋나면 거의 반드시 **치환자가 안 맞는다.**
//
// ```
//   ko  'mv.colAge':  '경과 (대본 시각 T+{sec}s 기준)'
//   en  'mv.colAge':  'Age (as of script time T+{sec}s)'     ← 같아야 한다
// ```
//
// `{sec}` 가 한쪽에만 있으면 화면에 `{sec}` 가 글자로 뜨거나 값이 사라진다. 이건 짝이
// 밀렸을 때 가장 먼저 드러나는 자국이고, 짝이 맞아도 **그 자체로 버그**다.
//
// 보는 것 셋.
//   1. en 에 있는 키는 ko 에도 있다 (반대는 허용 — 없으면 한국어로 떨어진다)
//   2. 같은 키의 **치환자 집합**이 같다
//   3. `<Rich>` 미니 마크업(`**`·`` ` ``)의 **짝이 맞는다** — 홀수면 화면에 별표가 뜬다
//
// 대조군 — 치환자를 하나 지운 사본과 별표를 홀수로 만든 사본이 잡혀야 한다.
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const { ko } = await import(pathToFileURL(join(root, 'src', 'i18n', 'ko.ts')).href);
const { en } = await import(pathToFileURL(join(root, 'src', 'i18n', 'en.ts')).href);

const failures = [];
const controls = [];

/** `{name}` 꼴 치환자. 차례는 언어마다 달라도 되지만 **집합은 같아야 한다.** */
const vars = (text) => new Set([...String(text).matchAll(/\{(\w+)\}/g)].map((m) => m[1]));

const same = (a, b) => a.size === b.size && [...a].every((v) => b.has(v));

// ── 1. en 의 키는 ko 에도 있다 ───────────────────────────────────────────────
//
// 반대는 허용한다 — ko 에만 있으면 영문 화면이 한국어로 떨어지고, 그것은 설계다
// (`mode.mock` 이 그 시범 키다). 그러나 **en 에만 있는 키는 아무도 안 쓴다** — 오타이거나
// 짝이 밀린 자국이다.
{
  const orphans = Object.keys(en).filter((k) => ko[k] === undefined);
  for (const k of orphans) failures.push(`en 에만 있는 키 '${k}' — ko 에 없다. 오타이거나 짝이 밀렸다`);
  console.log(`✅ 키 — en ${Object.keys(en).length}개가 전부 ko 에 있다 (ko ${Object.keys(ko).length}개)`);
}

// ── 2. 치환자 집합이 같다 ────────────────────────────────────────────────────
{
  let checked = 0;
  for (const [key, value] of Object.entries(en)) {
    if (ko[key] === undefined) continue;
    const a = vars(ko[key]);
    const b = vars(value);
    checked += 1;
    if (!same(a, b)) {
      failures.push(`'${key}' 치환자가 다르다 — ko {${[...a].join(',')}} vs en {${[...b].join(',')}}`);
    }
  }
  console.log(`✅ 치환자 — ${checked}개 키에서 ko 와 en 이 같은 자리를 채운다`);
}

// ── 3. `<Rich>` 마크업의 짝이 맞는다 ─────────────────────────────────────────
//
// `**굵게**` 와 `` `코드` `` 는 여는 것과 닫는 것이 같은 글자다. 홀수면 마크업이 안 걸리고
// **별표나 백틱이 화면에 그대로 뜬다.**
{
  let checked = 0;
  for (const [dict, name] of [[ko, 'ko'], [en, 'en']]) {
    for (const [key, value] of Object.entries(dict)) {
      const bold = String(value).split('**').length - 1;
      const code = String(value).split('`').length - 1;
      checked += 1;
      if (bold % 2 !== 0) failures.push(`${name} '${key}' 의 ** 가 홀수다 — 별표가 화면에 그대로 뜬다`);
      if (code % 2 !== 0) failures.push(`${name} '${key}' 의 백틱이 홀수다 — 백틱이 화면에 그대로 뜬다`);
    }
  }
  console.log(`✅ 마크업 — 두 사전 ${checked}개 키에서 ** 와 백틱의 짝이 맞는다`);
}

// ── 4. 대조군 ────────────────────────────────────────────────────────────────
{
  const cases = [
    ['치환자를 하나 지운 사본', !same(vars('T+{sec}s 기준'), vars('as of script time')), true],
    ['차례만 다른 사본 (잡으면 안 된다)', !same(vars('{a} 뒤 {b}'), vars('{b} after {a}')), false],
    ['별표가 홀수인 사본', ('**굵게'.split('**').length - 1) % 2 !== 0, true],
    ['별표가 짝수인 사본 (잡으면 안 된다)', ('**굵게**'.split('**').length - 1) % 2 !== 0, false],
  ];
  for (const [label, caught, want] of cases) {
    if (caught !== want) failures.push(`대조군 실패: ${label} — ${want ? '잡아야 하는데 놓쳤다' : '잡으면 안 되는데 잡았다'}`);
    else controls.push(label);
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:dict-shape\n- ${failures.join('\n- ')}`);
  console.error('\n   사전은 문자열 표라 짝이 한 칸 밀려도 타입도 검사도 못 본다.');
  console.error('   치환자가 그 어긋남의 가장 이른 자국이다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
