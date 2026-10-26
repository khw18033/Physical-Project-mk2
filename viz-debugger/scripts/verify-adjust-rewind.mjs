// verify:adjust-rewind (261026 신설 — 조정 되감기)
//
// **사람이 바꾼 값을 되감아 볼 수 있는가 — 그리고 되감기에서는 바꿀 수 없는가.**
//
// `adjusted` 는 기록에는 제대로 적혔는데(`261026/024124_MSN-260909-01` 두 건) 되감기 화면에서 안 보였다. 원인 둘:
//   가) 「사람이 바꾼 값」 목록(`planAdjustments`)이 슬라이더(`second`)가 아니라 라이브 머리를 읽었다 — 액션 층 시각
//       2부에서 명령 표를 `actionsAt(second)` 로 옮길 때 이 줄이 빠졌다
//   나) 목록이 입력칸 폼 안에 있었고, 폼은 실패 화면에서만 뜬다. 되감기에서는 노드를 열어도 실패 화면이 안 된다
//       (`167bf7e` — 되감기가 풀리지 않게 일부러 막았다. 그 막음은 `verify:action-modal-rewind` ②-b 가 지킨다)
// 고침은 **입력칸과 목록을 가른다** — 입력칸은 라이브 실패 칸에만, 목록은 되감기에서도(슬라이더를 따라).
//
// 보는 것 — `ActionModal` 을 실제로 그린다(`lib/adjustRewindProbe.mjs` · esbuild 묶음 · `renderToString`).
//   ① 목록이 `second` 를 받는다 — 100초 0줄 · 120초 speed 한 줄 · 141초 두 줄
//   ② 되감기에서 목록이 그려진다 — 아직 없는 지점(100초)에도 「없음」으로 자리가 선다
//   ③ 되감기에서 입력칸은 안 그려진다 — 실패 칸이 어떻게든 열려도
//   ④ 라이브 실패 칸에는 입력칸 둘이 그대로 · 목록도 그대로
//   + 배선 — `MissionDebugger` 가 되감기 여부를 `rewind` 로 넘긴다(`second` 는 따라가는 중이면 비어 있어 대신 못 쓴다)
//
// 대조군 — 지시서 4절의 넷 + 배선 하나. `src/` 통째 복사 · LF 정규화 원본에서 한 줄(`lib/actionTimeRun.mjs` 의 `mutantTree`).
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mutantTree } from './lib/actionTimeRun.mjs';
import { readSource } from './lib/source.mjs';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const probeFile = join(vizRoot, 'scripts', 'lib', 'adjustRewindProbe.mjs');
const drive = (root) => JSON.parse(execFileSync(process.execPath, [probeFile, root], { encoding: 'utf8', cwd: vizRoot, maxBuffer: 1 << 24 })
  .trim().split('\n').filter((l) => l.startsWith('{')).at(-1));

function judge(r, main) {
  const bad = [];
  if (r.recorded !== 2) return [`판을 못 세웠다 — adjusted ${r.recorded}건`];
  // ①
  if (r.rewind100.lines !== 0) bad.push(`① 100초에 ${r.rewind100.lines}줄 — 슬라이더가 아니라 라이브 머리로 접는다`);
  if (r.rewind120.lines !== 1 || !r.rewind120.speed || r.rewind120.clearance) bad.push(`① 120초가 speed 한 줄이 아니다 — ${JSON.stringify(r.rewind120)}`);
  if (r.rewind141.lines !== 2 || !r.rewind141.speed || !r.rewind141.clearance) bad.push(`① 141초가 두 줄이 아니다 — ${JSON.stringify(r.rewind141)}`);
  // ②
  for (const [at, look] of [['100', r.rewind100], ['120', r.rewind120], ['141', r.rewind141], ['따라가는 중', r.rewindFollow]]) {
    if (!look.list) bad.push(`② 되감기(${at})에서 「사람이 바꾼 값」이 안 그려진다`);
  }
  // ③
  for (const [at, look] of [['100', r.rewind100], ['120', r.rewind120], ['141', r.rewind141], ['실패 칸', r.rewindFailure]]) {
    if (look.inputs > 0) bad.push(`③ 되감기(${at})에 입력칸이 ${look.inputs}개 — 지난 판의 값을 바꿀 수 있는 것처럼 읽힌다`);
  }
  // ④
  if (r.live.inputs !== 2) bad.push(`④ 라이브 실패 칸의 입력칸이 ${r.live.inputs}개 — adjusted 를 만들 길이 사라졌다`);
  if (r.live.lines !== 2) bad.push(`④ 라이브 실패 칸의 목록이 ${r.live.lines}줄 — 두 줄이어야 한다`);
  // 배선
  const app = main.slice(main.indexOf('export function MissionDebugger('));
  const at = app.indexOf('<ActionModal');
  const element = at < 0 ? '' : app.slice(at, app.indexOf(' />}', at));
  if (!element.includes("rewind={screen === 'replay'}")) bad.push('배선: ActionModal 에 되감기 여부(rewind)를 안 넘긴다 — 되감기에서 목록이 안 뜬다');
  return bad;
}

const failures = [];
const main = readSource(vizRoot, 'src', 'main.tsx');
const real = judge(drive(vizRoot), main);
failures.push(...real);
if (real.length === 0) console.log('✅ 원본 — 되감기 100초 0줄 · 120초 한 줄 · 141초 두 줄 · 되감기 입력칸 0 · 라이브 입력칸 2');

const MODAL = 'src/views/ActionModal.tsx';
const controls = [
  { name: 'displayMission().headSec 로 되돌린 사본', file: MODAL, from: 'planAdjustments(second ?? displayMission().headSec,', to: 'planAdjustments(displayMission().headSec,' },
  { name: '되감기에서 목록을 안 그리는 사본', file: MODAL, from: '{!editable && rewind && everAdjusted && ', to: '{false && ' },
  { name: '되감기에 입력칸을 띄우는 사본', file: MODAL, from: 'failure === true && rewind !== true &&', to: 'failure === true &&' },
  { name: '라이브 입력칸까지 감춘 사본 (되감기를 second 로 판정)', file: MODAL, from: 'failure === true && rewind !== true &&', to: 'failure === true && rewind !== true && second !== undefined &&' },
  { name: '되감기 여부를 안 넘기는 사본', file: 'src/main.tsx', from: " rewind={screen === 'replay'}", to: '' },
];
const caught = [];
for (const c of controls) {
  const tree = mutantTree('.verify-adjrewind-', c.file, c.from, c.to);
  if (tree === null) { failures.push(`대조군을 만들지 못했다: ${c.name} — 치환이 아무것도 안 바꿨다`); continue; }
  try {
    const hit = judge(drive(tree.root), readSource(tree.root, 'src', 'main.tsx'));
    if (hit.length > 0) caught.push(`${c.name} (${hit[0].slice(0, 50)})`);
    else failures.push(`대조군 실패: ${c.name} — 변조 사본이 잡히지 않았다`);
  } finally {
    tree.cleanup();
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:adjust-rewind — ${failures.length}건\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${caught.length}건 전부 검출 — ${caught.join(' · ')}`);
console.log('✅ verify:adjust-rewind — 사람이 바꾼 값이 슬라이더를 따라 되감기고, 되감기에서는 바꿀 수 없다');
