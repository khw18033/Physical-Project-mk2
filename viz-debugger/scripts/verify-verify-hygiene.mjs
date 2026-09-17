// verify:verify-hygiene (260917 신설 — 검사 위생 지시서 §5)
//
// **검사 스크립트 자신을 검사한다.** 다시 켜지지 않게 하는 것이 이 작업의 진짜 산출물이다 —
// 없으면 석 달 뒤 같은 보고서를 쓴다.
//
// ## 왜 이것이 필요한가
//
// 늘 빨간 검사는 진짜 회귀를 가린다. 가정이 아니라 이미 일어난 일이다 — 260916 보고서가
// 「56 통과 / 2 실패(둘 다 기존)」이라 적었는데, **그 둘이 어느 둘인지가 기계마다 달랐고**
// 영어 로캘에서 새로 깨진 `verify:connection-panel` 이 그 개수 안에 숨었다.
// 개수만 보고 넘긴 것이 아니라 **개수가 맞아서 넘어간** 것이다.
//
// 그 빨강을 만든 세 가지를 여기서 못 돌아오게 막는다.
//
//  1. **`.pathname` 을 파일 경로로 쓰지 않는다** — 퍼센트 인코딩이라 한글 경로에서 ENOENT
//  2. **`src/` 안의 대조군 폴더는 공용 헬퍼로 만든다** — 조용한 정리 실패가 다른 검사를 오염시켰다
//  3. **`src/` 를 훑는 검사는 `.verify-*` 를 제외한다** — 남의 쓰레기가 내 판정을 바꾸면 안 된다
//
// 넷째로 대조군 — 위 셋을 어긴 사본이 반드시 잡혀야 한다.
import { readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readSource } from './lib/source.mjs';

const scriptsDir = dirname(fileURLToPath(import.meta.url));

const failures = [];
const controls = [];

/** 검사 대상 — `scripts/*.mjs` 와 `scripts/lib/*.mjs`. */
const FILES = [
  ...readdirSync(scriptsDir).filter((n) => n.endsWith('.mjs')).map((n) => ({ name: n, path: join(scriptsDir, n) })),
  ...readdirSync(join(scriptsDir, 'lib')).filter((n) => n.endsWith('.mjs')).map((n) => ({ name: `lib/${n}`, path: join(scriptsDir, 'lib', n) })),
];

/** 주석을 지운 소스. 규칙을 설명하는 주석이 규칙 위반으로 잡히면 안 된다. */
function code(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

/**
 * **이 파일 자신은 대상에서 뺀다.** 아래 ④ 의 대조군이 「위반하는 코드」를 문자열로 들고 있어서
 * 자기 규칙에 자기가 걸린다. 문자열 안이라 실제로 실행되지 않는 코드다.
 *
 * 문자열 리터럴을 지우고 훑는 방법도 있지만 그러면 **진짜 위반도 같이 안 보인다** — 규칙 ①·②가
 * 찾는 것이 바로 코드 조각이기 때문이다. 대조군을 잃느니 이 파일 하나를 빼는 편이 낫다.
 */
const SELF = 'verify-verify-hygiene.mjs';

const sources = new Map(FILES.filter((f) => f.name !== SELF).map((f) => [f.name, code(readSource(f.path))]));

// ── ① `.pathname` 을 파일 경로로 쓰지 않는다 ─────────────────────────────────
//
// `URL.pathname` 은 퍼센트 인코딩된 문자열이다. 저장소 경로에 한글이 있으면 `대학` 이
// `%EB%8C%80%ED%95%99` 로 남은 채 `readFileSync` 에 들어간다. `fileURLToPath` 가 디코딩과
// 윈도우 드라이브 문자를 둘 다 처리한다.
//
// **HTTP 경로로 쓰는 `.pathname` 은 해당 없다** — `autodrive-ai-relay.mjs` 가 요청 URL 을
// 검사하는 자리이고 파일을 열지 않는다. `import.meta.url`·`new URL(...)` 에서 나온 것만 본다.
const PATHNAME_ON_FILE_URL = /(?:import\.meta\.url[^\n]*|new URL\([^\n]*\))\.pathname/;
{
  for (const [name, source] of sources) {
    if (PATHNAME_ON_FILE_URL.test(source)) {
      failures.push(`${name}: 파일 경로를 .pathname 으로 만든다 — 한글 경로에서 ENOENT 다. fileURLToPath() 를 써라`);
    }
  }
  console.log(`✅ 파일 경로 — ${sources.size}개 스크립트가 .pathname 대신 fileURLToPath() 를 쓴다 (한글 경로에서도 돈다)`);
}

// ── ② `src/` 안의 대조군 폴더는 공용 헬퍼로 만든다 ───────────────────────────
//
// `os.tmpdir()` 에 만드는 것은 **해당 없다** — 거기 남아도 `src/` 를 훑는 검사를 오염시킬 수
// 없고 OS 가 치운다. 막으려는 것은 `src/` 안에 손으로 만드는 자리다.
{
  const SRC_SCRATCH = /mkdtempSync\(\s*join\((?![^)]*tmpdir)[^)]*\)\s*\)/;
  for (const [name, source] of sources) {
    if (name === 'lib/scratch.mjs') continue; // 헬퍼 자신이 유일하게 부르는 곳이다
    if (SRC_SCRATCH.test(source)) {
      failures.push(`${name}: src/ 안에 임시 폴더를 직접 만든다 — makeScratch() 를 써라 (lib/scratch.mjs). 정리 실패가 조용히 묻힌다`);
    }
  }
  const users = [...sources].filter(([n, s]) => n !== 'lib/scratch.mjs' && /makeScratch\(/.test(s)).length;
  if (users === 0) failures.push('makeScratch() 를 쓰는 스크립트가 하나도 없다 — 헬퍼가 죽었거나 검사가 잘못 보고 있다');
  console.log(`✅ 임시 폴더 — src/ 안에 만드는 ${users}개 스크립트가 전부 makeScratch() 를 지난다 (정리 실패가 끝에 목록으로 뜬다)`);
}

// ── ③ `src/` 를 훑는 검사는 `.verify-*` 를 제외한다 ──────────────────────────
//
// 260917 에 `verify:human-trace` 가 흘린 `.verify-human-*/trace-3.ts` 6건을
// `verify:trace-append` 가 「기록 열을 따로 만드는 곳」으로 셌다. 잔여물이 0이어도 이 제외는
// 있어야 한다 — 정리는 실패할 수 있고, 판정은 아니다.
{
  let walkers = 0;
  for (const [name, source] of sources) {
    if (name.startsWith('lib/') || name === 'verify-clean.mjs') continue; // 청소기는 잔여물을 **찾는** 쪽이다
    // 재귀로 디렉터리를 내려가면서 .ts 를 모으는 꼴인가.
    const walks = /readdirSync\(/.test(source) && /isDirectory\(\)/.test(source) && /\\\.(?:tsx?|\(ts\|tsx\))/.test(source);
    if (!walks) continue;
    walkers += 1;
    if (!/isScratchPath\(/.test(source)) {
      failures.push(`${name}: src/ 를 훑는데 .verify-* 를 제외하지 않는다 — 남의 대조군 잔여물을 위반으로 센다. isScratchPath() 를 써라`);
    }
  }
  if (walkers === 0) failures.push('src/ 를 훑는 검사를 하나도 못 찾았다 — 이 검사가 아무것도 안 재고 있다');
  console.log(`✅ 훑기 — src/ 를 훑는 ${walkers}개 검사가 전부 .verify-* 를 제외한다 (판정이 잔여물에 안 흔들린다)`);
}

// ── ④ 대조군 — 위 셋을 어긴 사본이 반드시 잡혀야 한다 ────────────────────────
//
// 실제 파일을 건드리지 않는다. 판정식에 손으로 만든 문자열을 먹여 **잣대가 무는지**만 본다 —
// 진짜 위반이 하나라도 있으면 대조군이 그것 때문에 통과/실패해서 무엇을 확인한 것인지
// 알 수 없어진다.
{
  const cases = [
    ['.pathname 으로 경로를 만드는 사본', PATHNAME_ON_FILE_URL,
      "const ROOT = new URL('../../', import.meta.url).pathname;", true],
    ['HTTP 경로의 .pathname (잡으면 안 된다)', PATHNAME_ON_FILE_URL,
      "if (base.pathname !== '/') return;", false],
    ['src/ 안에 직접 mkdtemp 하는 사본', /mkdtempSync\(\s*join\((?![^)]*tmpdir)[^)]*\)\s*\)/,
      "const scratch = mkdtempSync(join(srcDir, '.verify-x-'));", true],
    ['tmpdir 에 만드는 사본 (잡으면 안 된다)', /mkdtempSync\(\s*join\((?![^)]*tmpdir)[^)]*\)\s*\)/,
      "const scratch = mkdtempSync(join(tmpdir(), 'verify-x-'));", false],
  ];
  for (const [label, pattern, sample, shouldCatch] of cases) {
    const caught = pattern.test(sample);
    if (caught !== shouldCatch) {
      failures.push(`대조군 실패: ${label} — ${shouldCatch ? '잡아야 하는데 놓쳤다' : '잡으면 안 되는데 잡았다'}. 이 검사는 무의미하다`);
    } else {
      controls.push(label);
    }
  }
}

if (failures.length) {
  console.error(`❌ verify:verify-hygiene\n- ${failures.join('\n- ')}`);
  console.error('\n   늘 빨간 검사는 진짜 회귀를 가린다. 260916 에 그렇게 verify:connection-panel 을 놓쳤다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — 위반은 잡고, 비슷하지만 정당한 것(HTTP 경로 · tmpdir)은 통과시킨다`);
