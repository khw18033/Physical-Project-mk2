// verify:build-parity (260916 신설 — 단독 빌드 정합 지시서 §5)
//
// **두 빌드의 차이가 `tabs/` 뿐인가.**
//
// 이 검사가 이 작업의 진짜 산출물이다. 나머지는 한 번 고치면 끝이지만 이건 **다시 벌어지는
// 것을 막는다.** 없으면 석 달 뒤 같은 보고서를 또 쓴다.
//
// ## 무엇이 벌어졌었나
//
// `verify:standalone` 은 「단독 진입점이 금지 폴더를 가져오는가」만 봤다. 그래서 **단독에
// 빠진 것이 늘어나는 것은 한 번도 안 봤다.** 08-28 에 `shell/` 을 금지한 뒤 그 폴더가
// 상단 바의 서랍이 됐고, 모드 스위치(08-31) · 연결 관리(09-04) · 연결 램프(09-10) 가
// 차례로 들어오면서 전달본에서 조용히 빠졌다. 19일 뒤에 사람이 손으로 재서 알았다.
//
// 금지 목록을 지키는 검사와 **빠진 것이 없는지 보는 검사는 다른 물건**이다. 이것이 후자다.
//
// ## 보는 것
//
//   통합 도달집합 − 단독 도달집합  ⊆  { tabs/**, integrated.tsx }
//
// 이 밖의 파일이 나오면 실패하고 **어느 import 사슬로 빠졌는지**까지 찍는다. 이름만 찍으면
// 왜 빠졌는지 찾느라 또 반나절이 간다.
//
// 대조군 포함 — 통합에만 셸 파일을 하나 더 매단 사본이 반드시 실패로 잡혀야 한다.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, normalize, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const sourceRoot = normalize(join(vizRoot, 'src') + sep);
const rel = (path) => relative(sourceRoot, path).split(sep).join('/');

const failures = [];

/**
 * 세는 방식이 검사의 잣대다.
 *
 * `from` 이 붙는 꼴(`import … from` · `export … from`)만 보면 **부수효과 import
 * (`import './x.ts'`)를 통째로 놓친다.** 그것도 번들에 실리는 코드이므로 같이 센다.
 * 동적 `import()` 도 마찬가지다.
 */
const PATTERNS = [
  /from\s+['"](\.[^'"]+)['"]/g,
  /import\s+['"](\.[^'"]+)['"]/g,
  /import\s*\(\s*['"](\.[^'"]+)['"]/g,
];

/**
 * 도달 집합과 **누가 누구를 끌어왔는지**. 사슬을 찍으려면 부모가 필요하다.
 *
 * `skipTabs` 면 `tabs/` 안으로 **들어가지 않는다.** 이것이 이 검사의 핵심 장치다.
 *
 * 단순히 「통합 − 단독 중 `tabs/` 가 아닌 것」을 보면 틀린다. `detect/views/DetectViews.tsx`
 * 처럼 **`tabs/` 를 거쳐서만 닿는 파일**이 있기 때문이다 — 그건 `tabs/` 밖에 살지만 대시보드
 * 뷰 노드가 쓰는 것이라 단독에 없는 것이 **맞다.** 폴더 이름이 아니라 **도달 경로**로 갈라야
 * 「단독에 있어야 하는데 없는 것」이 정확히 나온다.
 *
 * 그래서 비교 대상은 「통합이 대시보드를 빼고 도달하는 집합」이고, 그것이 단독과 같아야 한다.
 */
function graph(entryName, { skipTabs = false } = {}) {
  const entry = join(sourceRoot, entryName);
  const visited = new Set();
  const parent = new Map();
  (function visit(path) {
    if (visited.has(path)) return;
    visited.add(path);
    if (skipTabs && rel(path).startsWith('tabs/')) return; // 문턱까지만 세고 안으로 안 들어간다
    let source;
    try { source = readFileSync(path, 'utf8'); } catch { return; }
    for (const pattern of PATTERNS) {
      for (const match of source.matchAll(pattern)) {
        const next = normalize(join(dirname(path), match[1]));
        if (!/\.(ts|tsx)$/.test(next) || !existsSync(next)) continue;
        if (!parent.has(next)) parent.set(next, path);
        visit(next);
      }
    }
  })(entry);
  return { entry, files: new Set([...visited].map(rel)), parent, paths: visited };
}

/** `integrated.tsx → shell/AppShell.tsx → …` — 왜 그 파일이 딸려 왔는지. */
function chain(g, target) {
  const full = [...g.paths].find((path) => rel(path) === target);
  if (full === undefined) return target;
  const steps = [];
  for (let at = full; at !== undefined; at = g.parent.get(at)) {
    steps.unshift(rel(at));
    if (at === g.entry) break;
  }
  return steps.join(' → ');
}

/** 진입점 파일 자신은 서로 다른 것이 당연하다. 그 둘만 뺀다. */
const ENTRIES = new Set(['integrated.tsx', 'standalone.tsx']);

/** 「통합이 대시보드 없이 도달하는 것」 중 단독에 없는 것. 나오면 전부 회귀다. */
function drift(standaloneFiles, coreFiles) {
  return [...coreFiles]
    .filter((file) => !standaloneFiles.has(file) && !ENTRIES.has(file) && !file.startsWith('tabs/'))
    .sort();
}

const standalone = graph('standalone.tsx');
/** 통합에서 `tabs/` 안으로 안 들어간 도달 집합 — **이것이 단독과 같아야 한다.** */
const core = graph('integrated.tsx', { skipTabs: true });
const integrated = graph('integrated.tsx');

for (const file of drift(standalone.files, core.files)) {
  failures.push(`단독 빌드에 없다: ${file}\n      딸려 온 사슬 — ${chain(core, file)}`);
}

// ── 역방향 — 단독에만 있는 것 ────────────────────────────────────────────────
//
// 있을 수 없는 일이지만(단독은 통합의 부분집합이어야 한다) 잰다. 나오면 두 진입점이
// 갈라진 것이고, 그때는 한쪽에서 고친 것이 다른 쪽에 안 간다.
for (const file of [...standalone.files].filter((f) => !integrated.files.has(f) && !ENTRIES.has(f)).sort()) {
  failures.push(`통합 빌드에 없다: ${file} — 단독이 통합의 부분집합이 아니다 (사슬: ${chain(standalone, file)})`);
}

// ── 대조군 — 판정이 실제로 무는가 ────────────────────────────────────────────
//
// **실제 측정값을 재료로 쓰지 않는다.** 진짜 회귀가 하나라도 있으면 대조군이 그것 때문에
// 통과/실패해서 무엇을 확인한 것인지 알 수 없어진다(첫 판에 실제로 그렇게 됐다).
// 손으로 만든 최소 집합으로 잣대만 본다.
{
  const base = new Set(['shared/a.ts', 'canvas/b.ts']);

  // ① 통합에만 있는 **셸 파일**은 반드시 잡힌다. 이 검사의 존재 이유다.
  const withShell = new Set([...base, 'shell/HelpOverlay.tsx']);
  if (drift(base, withShell).length === 0) {
    failures.push('대조군 실패: 통합에만 있는 셸 파일을 판정이 놓쳤다 — 이 검사는 무의미하다');
  }

  // ② 통합에만 있는 **`tabs/`** 는 통과해야 한다. 잡으면 검사가 과해서 경계 자체를 막는다.
  const withTabs = new Set([...base, 'tabs/views/DeviceGrid.tsx']);
  if (drift(base, withTabs).length !== 0) {
    failures.push('대조군 실패: tabs/ 가 통합에만 있는 것을 회귀로 잡았다 — 그것이 이 경계의 존재 이유인데 막고 있다');
  }

  // ③ `tabs/` **를 거쳐서만** 닿는 바깥 파일도 통과해야 한다 — `skipTabs` 가 그래서 있다.
  //    실물로 확인한다: DetectViews 는 tabs/viewNodes.tsx 가 끌어오는 것이라 단독에 없는 게 맞다.
  if (core.files.has('detect/views/DetectViews.tsx')) {
    failures.push('대조군 실패: tabs/ 를 거쳐서만 닿는 파일이 core 에 들어왔다 — skipTabs 가 안 듣는다');
  }
  if (!integrated.files.has('detect/views/DetectViews.tsx')) {
    failures.push('대조군을 만들지 못했다 — detect/views/DetectViews.tsx 가 통합 그래프에서 사라졌다 (저장소가 바뀌었나?)');
  }
}

// ── 출력 ─────────────────────────────────────────────────────────────────────

const tabsCount = [...integrated.files].filter((file) => file.startsWith('tabs/')).length;

if (failures.length) {
  console.error(`❌ verify:build-parity\n- ${failures.join('\n- ')}`);
  console.error('\n   단독 빌드가 또 뒤처지고 있다. 셸에 새 부품을 넣었다면 그것이 tabs/ 를 끌어오는지 보고,');
  console.error('   안 끌어온다면 단독 진입점도 같이 쓰게 해라. tabs/ 를 끌어온다면 주입으로 끊어라');
  console.error('   (shared/appServices.ts · shared/envelopeSink.ts 가 그 자리다).');
  process.exit(1);
}

console.log(`✅ 두 빌드의 차이가 tabs/ 뿐이다 — 단독 ${standalone.files.size}개 · 통합 ${integrated.files.size}개 · 그중 tabs/ ${tabsCount}개`);
console.log(`✅ 통합이 대시보드 없이 도달하는 ${core.files.size - 1}개가 단독에 그대로 있다 — 빠진 것 0`);
console.log('✅ 단독은 통합의 부분집합이다 — 한쪽에서만 도는 파일이 없다');
console.log('✅ 대조군 4건 — 셸 파일은 잡고 · tabs/ 는 통과시키고 · tabs/ 를 거쳐서만 닿는 바깥 파일도 통과시킨다');
