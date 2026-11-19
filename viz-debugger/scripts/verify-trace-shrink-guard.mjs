// verify:trace-shrink-guard (261026 신설 — 기록 열 덮어쓰기)
//
// **같은 판 안에서 기록 열이 줄어들면 판 폴더에 쓰지 않는가 — 그리고 그것을 알리는가.**
//
// 261026 03:29 `src` 를 고치자 vite 핫 리로드가 저장소를 비웠고, 기록기는 같은 판(`Run`)을 쥔 채 다음 틱에 빈 열을
// `024124_MSN-260909-01` 에 덮어썼다(101 → 0 · `adjusted` 의 유일한 실물 판). `write()` 의 판정은 「저번 글자와
// 다른가」 하나뿐이었다. §4-2 「기록은 덧붙이기만 한다」를 코드로 옮긴다 — 같은 판의 열은 줄어들 수 없다.
//
// 보는 것 — 실제 기록기 · 실제 창구(임시 폴더) · `lib/traceShrinkProbe.mjs`.
//   ① 열이 줄어든 채로 틱이 돌면 안 쓴다 — 23 → 3 · 23 → 0 둘 다
//   ② 그때 경고가 남는다 — `recorderStatus().lastError`(이력 패널의 「저장 오류」) · 콘솔
//   ③ 늘어나면 쓴다 · 같은 길이면 지금처럼 글자로 판정해 쓴다 · 줄기 전에는 경고가 없다
//   ④ 새 판(봉인 → 새 `Run`)이면 높이가 리셋되어 새 폴더에 쓴다 · 경고가 걷힌다
//
// 대조군 셋 — 지시서 4절. `src/` 통째 복사 · LF 정규화 원본에서(`lib/actionTimeRun.mjs` 의 `mutantTree`).
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mutantTree } from './lib/actionTimeRun.mjs';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const probeFile = join(vizRoot, 'scripts', 'lib', 'traceShrinkProbe.mjs');
const drive = (root) => JSON.parse(execFileSync(process.execPath, [probeFile, root], { encoding: 'utf8', cwd: vizRoot, maxBuffer: 1 << 24 })
  .trim().split('\n').filter((l) => l.startsWith('{')).at(-1));

function judge(r) {
  if (r.folder === null) return ['판 폴더가 안 섰다 — 판을 못 세웠다'];
  const bad = [];
  // ③
  if (r.grown !== r.first + 1) bad.push(`③ 열이 늘었는데 안 썼다 — ${r.first} → ${r.grown}`);
  if (r.sameLength !== r.grown || !r.sameLengthWritten) bad.push('③ 열 길이가 같고 다른 칸이 바뀌었는데 안 썼다');
  if (r.errorBeforeShrink !== null) bad.push(`③ 줄기 전부터 경고가 있다 — ${r.errorBeforeShrink}`);
  // ①
  if (r.afterPartial !== r.grown) bad.push(`① 열이 ${r.grown} → 3 으로 줄었는데 썼다 — 폴더에 ${r.afterPartial}건`);
  if (r.afterEmpty !== r.grown) bad.push(`① 빈 열을 덮어썼다(어제의 모양) — 폴더에 ${r.afterEmpty}건`);
  // ②
  for (const [what, error] of [['3건', r.errorPartial], ['0건', r.errorEmpty]]) {
    if (error === null || !error.includes(String(r.grown))) bad.push(`② 열이 ${what}으로 줄어 막았는데 경고가 없다 — 조용히 저장이 멈춘다`);
  }
  if (r.warned < 1) bad.push('② 막았는데 콘솔 경고가 없다');
  // ④
  if (r.folders !== 2 || r.next === null) bad.push(`④ 새 판인데 새 폴더가 안 섰다 — 폴더 ${r.folders}개`);
  else if (!(r.nextOnDisk > 0)) bad.push(`④ 새 판의 열을 안 썼다 — 지난 판의 높이로 막았다(${r.nextOnDisk})`);
  if (r.errorAfterNext !== null) bad.push(`④ 새 판을 썼는데 지난 판의 경고가 남았다 — ${r.errorAfterNext}`);
  return bad;
}

const failures = [];
const real = judge(drive(vizRoot));
failures.push(...real);
if (real.length === 0) console.log('✅ 원본 — 늘면 씀 · 같으면 글자로 · 23→3 · 23→0 막고 경고 · 새 판은 새 폴더에 씀');

const FILE = 'src/record/recorder.ts';
const GUARD = '  if (traceLength < target.traceHigh) {';
const controls = [
  { name: '막음을 걷은 사본 (어제 사고의 모양)', from: GUARD, to: '  if (false) {' },
  { name: '빈 열만 막는 사본 (101→3 을 놓친다)', from: GUARD, to: '  if (traceLength === 0 && target.traceHigh > 0) {' },
  {
    name: '판이 바뀌어도 높이를 이어 드는 사본 (Run 리셋까지 막는다)',
    from: `  const traceLength = traceEvents().length;\n${GUARD}`,
    to: `  const traceLength = traceEvents().length;\n  target.traceHigh = Math.max(target.traceHigh, globalThis.traceHighAll ?? 0);\n  globalThis.traceHighAll = Math.max(target.traceHigh, traceLength);\n${GUARD}`,
  },
];
const caught = [];
for (const c of controls) {
  const tree = mutantTree('.verify-shrink-', FILE, c.from, c.to);
  if (tree === null) { failures.push(`대조군을 만들지 못했다: ${c.name} — 치환이 아무것도 안 바꿨다`); continue; }
  try {
    const hit = judge(drive(tree.root));
    if (hit.length > 0) caught.push(`${c.name} (${hit[0].slice(0, 50)})`);
    else failures.push(`대조군 실패: ${c.name} — 변조 사본이 잡히지 않았다`);
  } finally {
    tree.cleanup();
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:trace-shrink-guard — ${failures.length}건\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${caught.length}건 전부 검출 — ${caught.join(' · ')}`);
console.log('✅ verify:trace-shrink-guard — 같은 판의 기록 열이 줄면 안 쓰고 알린다 · 새 판은 막지 않는다');
