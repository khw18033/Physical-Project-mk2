// verify:no-fake-plan (260918 신설)
//
// **지어낸 계획이 사람에게 진짜로 보이면 안 된다.**
//
// ## 무엇이 있었나
//
// 목 게이트웨이가 기동할 때마다 데모 계획 하나를 승인 대기에 깔았다 — 「화면을 열자마자
// 승인 절차를 볼 수 있게」가 이유였다. 그 계획의 제목은 **「503 구역 수위 상승 대응」**인데
// **503호와 수위는 아무 관계가 없다.** 문 찾기 시연 중 승인 탭에 그 계획이 떠 있었고,
// 260917 에 사람이 화면을 보고 찾았다.
//
// 이 저장소는 `renderMode` 기본값을 `placeholder` 로 둔다 — **진짜처럼 보이는 목이 시연에서
// 거짓말이 되는 것을 막으려는 것**이다. 그런데 계획은 그 관문을 안 지난다. `PlanApproval` 은
// 저장소에 있는 계획을 그냥 그리고, 그 계획이 목인지 진짜인지 구별할 표시가 없다.
// 자리표시 체계가 지키던 선이 이 채널 하나에서 비어 있었다.
//
// ## 보는 것 셋
//
//  1. **기동 경로가 계획을 안 만든다** — `server.ts` 최상위에서 `propose()` 를 안 부른다
//  2. **부르는 곳은 목·개발 시나리오뿐** — 사람이 붉은 배지를 켜고 명시적으로 눌러야 나온다
//  3. **devpanel 은 목·개발 모드에서만 보인다** — 그 버튼이 평시 화면에 뜨면 1·2가 무의미하다
//
// 대조군 — 기동 경로에 `propose()` 를 도로 넣은 사본이 반드시 잡혀야 한다.
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (...parts) => readFileSync(join(root, ...parts), 'utf8');
/** 주석을 지운다 — 사유를 적은 주석이 규칙 위반으로 잡히면 안 된다. */
const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

const failures = [];
const controls = [];

/** 기동 경로에서 계획을 만드는가 — 들여쓰기 없는 최상위 호출만 본다. */
const seedsAtBoot = (src) => /^\s*[\w.]*\bpropose\(\)/m.test(code(src));

// ── 1. 기동이 계획을 안 만든다 ───────────────────────────────────────────────
{
  const server = read('gateway', 'server.ts');
  if (seedsAtBoot(server)) {
    failures.push('gateway/server.ts 가 기동하면서 계획을 만든다 — 목 배지 없이 진짜 계획 채널로 나가 화면에서 진짜와 구별되지 않는다');
  }
  console.log('✅ 기동 — 게이트웨이가 켜질 때 계획을 만들지 않는다 (승인 탭은 발화가 있어야 찬다)');
}

// ── 2. `propose()` 를 부르는 곳은 목·개발 시나리오뿐 ─────────────────────────
{
  const callers = [];
  for (const rel of [['gateway', 'server.ts'], ['gateway', 'scenarios.ts'], ['gateway', 'script-engine.ts'], ['gateway', 'plans.ts']]) {
    const src = code(read(...rel));
    const count = [...src.matchAll(/\bplans\.propose\(\)/g)].length;
    if (count > 0) callers.push({ file: rel.join('/'), count });
  }
  const outside = callers.filter((c) => c.file !== 'gateway/scenarios.ts');
  for (const c of outside) {
    failures.push(`${c.file} 가 propose() 를 ${c.count}번 부른다 — 지어낸 계획은 목·개발 시나리오에서만 나와야 한다`);
  }
  const demo = callers.find((c) => c.file === 'gateway/scenarios.ts');
  if (demo === undefined) {
    failures.push('목·개발 시나리오가 propose() 를 안 부른다 — 이 검사가 지키는 것이 없다 (자리가 사라졌나?)');
  }
  console.log(`✅ 지어낸 계획 — 목·개발 시나리오 ${demo?.count ?? 0}곳에서만 나온다`);
}

// ── 3. devpanel 이 평시 화면에 안 보인다 ─────────────────────────────────────
//
// 1·2가 서 있어도 그 버튼이 평시에 보이면 누구든 한 번 눌러 지어낸 계획을 띄울 수 있다.
{
  const css = read('src', 'style.css');
  if (!/\.app-shell:not\(\.app-shell--dev\)\s*\.devpanel\s*\{\s*display:\s*none/.test(css)) {
    failures.push('devpanel 이 목·개발 모드 밖에서도 보인다 — 평시 화면에서 지어낸 계획을 부를 수 있다');
  }
  const panel = code(read('src', 'tabs', 'views', 'PlanApproval.tsx'));
  if (!/className="devpanel"/.test(panel)) {
    failures.push('계획 내려받기 버튼이 devpanel 밖으로 나갔다 — CSS 가 가리지 못한다');
  }
  console.log('✅ devpanel — 목·개발 모드에서만 보인다 (붉은 배지가 유지되는 모드다)');
}

// ── 4. 대조군 ────────────────────────────────────────────────────────────────
{
  const cases = [
    ['기동에 propose() 를 도로 넣은 사본', seedsAtBoot('const plans = new PlanEngine();\nplans.propose();\n'), true],
    ['주석 안의 propose() (잡으면 안 된다)', seedsAtBoot('// 전에는 plans.propose() 를 여기서 불렀다\nconst a = 1;\n'), false],
    ['시나리오 안의 propose() (잡으면 안 된다)', seedsAtBoot('  run() {\n      const plan = plans.propose();\n  }\n'), false],
  ];
  for (const [label, caught, want] of cases) {
    if (caught !== want) failures.push(`대조군 실패: ${label} — ${want ? '잡아야 하는데 놓쳤다' : '잡으면 안 되는데 잡았다'}. 이 검사는 무의미하다`);
    else controls.push(label);
  }
}

if (failures.length) {
  console.error(`❌ verify:no-fake-plan\n- ${failures.join('\n- ')}`);
  console.error('\n   지어낸 계획이 평시 화면에 뜨면 사람은 그것을 진짜로 읽는다.');
  console.error('   renderMode 기본값을 placeholder 로 둔 것과 같은 이유다.');
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — 기동 호출은 잡고, 주석과 시나리오 안의 호출은 통과시킨다`);
