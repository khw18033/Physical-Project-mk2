// verify:gateway-types (260919 신설)
//
// **목 게이트웨이도 타입 검사를 통과한다.**
//
// `package.json` 의 `typecheck` 는 `tsconfig.json`(화면)만 본다. 게이트웨이는 자기
// `gateway/tsconfig.json` 을 갖고 있는데 **아무도 안 돌리고 있었다.**
//
// 그래서 이런 일이 있었다 — 3단계(260918)에서 매처가 화면 언어를 보게 되면서
// `gateway/script-engine.ts` → `scenarios/matcher.ts` → `i18n/dict.ts` → `shared/language.ts`
// 가 딸려 들어왔고, 그 파일이 `location`·`document` 를 직접 적고 있었다. 게이트웨이의
// `lib` 에는 DOM 이 없으므로 **그날부터 게이트웨이 타입 검사가 통째로 실패했다.**
// 260919 에 게이트웨이 문구를 옮기려다 알았다. 하루가 아니라 **그물이 없었던 것**이 문제다.
//
// 게이트웨이는 목이지만 시연이 그 위에서 돈다. 화면만 재는 그물은 절반짜리다.
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

const failures = [];
const controls = [];

// ── 1. 게이트웨이 프로젝트가 타입 검사를 통과한다 ───────────────────────────
{
  // **`npx` 를 부르지 않는다.** 윈도우에서 `npx.cmd` 는 `shell:false` 로 못 띄운다
  // (`EINVAL`). 처음에 그렇게 썼더니 **아무것도 못 재고 초록**이었다 — 이 검사가
  // 막으려던 것과 똑같은 모양을, 이 검사 자신이 하고 있었다. 컴파일러를 node 로 직접 부른다.
  const tsc = join(root, 'node_modules', 'typescript', 'bin', 'tsc');
  const run = spawnSync(process.execPath, [tsc, '--noEmit', '-p', 'gateway/tsconfig.json'], {
    cwd: root, encoding: 'utf8', shell: false,
  });
  const out = `${run.stdout ?? ''}${run.stderr ?? ''}`.trim();

  // 못 돌린 것과 통과한 것은 **다르다.** 안 가르면 없는 그물이 있는 척한다.
  if (run.error !== undefined || run.status === null) {
    failures.push(`타입 검사를 **돌리지도 못했다** — ${run.error?.message ?? '종료 코드가 없다'}. 통과가 아니다`);
  } else if (run.status !== 0) {
    const lines = out.split('\n').filter((l) => l.trim() !== '');
    if (lines.length === 0) failures.push(`타입 검사가 ${run.status} 로 끝났는데 내용이 없다`);
    for (const line of lines.slice(0, 8)) failures.push(line);
    if (lines.length > 8) failures.push(`그 밖 ${lines.length - 8}줄`);
  } else {
    console.log('✅ gateway/tsconfig.json — 타입 검사 통과 (화면과 따로 돈다)');
  }
}

// ── 2. 게이트웨이가 **브라우저 전역을 직접 적지 않는다** ────────────────────
//
// 1번이 실패하는 가장 흔한 길이다. 게이트웨이는 `src/` 몇 파일을 그대로 끌어 쓰는데,
// 그 파일이 `document` 한 줄만 적어도 여기가 무너진다. 그래서 **원인을 이름으로** 잡는다.
{
  const { readFileSync } = await import('node:fs');
  const files = ['src/shared/language.ts', 'src/i18n/dict.ts', 'src/scenarios/matcher.ts'];
  for (const rel of files) {
    const src = readFileSync(join(root, rel), 'utf8');
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*/g, '$1');
    for (const name of ['document', 'location', 'window', 'navigator']) {
      // `browser.document` 처럼 **무엇에 달려서** 읽는 것은 괜찮다 — 타입이 우리 것이다.
      const bare = new RegExp(`(^|[^A-Za-z0-9_$.])${name}\\s*[.[]`, 'm');
      if (bare.test(code)) {
        failures.push(`${rel}: 브라우저 전역 \`${name}\` 을 그대로 적는다 — 이 파일은 게이트웨이 타입 검사에도 들어간다 (DOM lib 이 없다)`);
      }
    }
  }
  controls.push(`게이트웨이가 끌어 쓰는 ${files.length}개 파일이 브라우저 전역을 직접 안 적는다`);
}

// ── 3. 대조군 ───────────────────────────────────────────────────────────────
{
  const probe = (code) => /(^|[^A-Za-z0-9_$.])document\s*[.[]/m.test(code);
  if (!probe('if (x) document.documentElement.lang = next;')) {
    failures.push('대조군 실패: 맨 `document.` 를 못 잡는다 — 이 검사는 무의미하다');
  } else controls.push('맨 `document.` 를 잡는다');
  if (probe('browser.document.documentElement.lang = next;')) {
    failures.push('대조군 실패: `browser.document` 까지 잡는다 — 그건 우리가 타입을 붙인 것이라 괜찮다');
  } else controls.push('무엇에 달려 읽는 것은 통과시킨다');
}

if (failures.length > 0) {
  console.error(`❌ verify:gateway-types\n- ${failures.join('\n- ')}`);
  console.error('\n   게이트웨이는 목이지만 시연이 그 위에서 돈다 — 화면만 재는 그물은 절반짜리다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
