// verify:action-modal-rewind (261025 신설 — 액션 층 시각 2부)
//
// **화면의 명령 표가 슬라이더를 따라가는가.**
//
// 1부가 시각을 고쳐도 화면에서는 안 보였다. 슬라이더의 되감기 값은 `main.tsx` 의 `GraphScreen` 안(`override`)에만
// 있었고, 명령 표(`ActionModal`)는 그 화면 밖에서 떠서 `actionsAt()` 을 **인자 없이** 불렀다 — 라이브 머리로
// 접혀 지금까지 온 줄 전부를 그렸다. §5-1 이 「프로그램으로 같은 함수를 돌린 것 · 화면을 눈으로 본 것은 아직
// 아니다」라고 밝혀 둔 바로 그 틈이다.
//
// 보는 것 — 배선이다. 접기 자체(머리를 옮기면 그때까지 온 것만)는 `verify:action-replay-generated` 가 실제
// 기록 길로 본다. 이 검사는 그 접기에 **슬라이더 값이 닿는지**만 본다.
//   ① `GraphScreen` 이 되감기 값(`override`)을 `onSecond` 로 올리고, 따라가는 중이면 `null` 을 올린다
//   ② `MissionDebugger` 가 그 값을 받아 `ActionModal` 에 `second` 로 넘긴다
//   ③ `ActionModal` 안의 접기가 **전부** `second` 를 받는다 — 인자 없는 `actionsAt()` 이 하나도 없다
//      (명령 표를 그리는 `RobotCommands` 포함)
//
// 대조군 — LF 정규화한 원본(`readSource`)에서 만든다. 셋 다 잡혀야 한다.
//   명령 표 한 곳을 `actionsAt()` 로 되돌린 사본 · 모달에 `second` 를 안 넘기는 사본 · 되감기 값을 안 올리는 사본
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mutate, readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const failures = [];

function judge(main, modal) {
  const bad = [];
  // ① 올리기
  const graph = main.slice(main.indexOf('function GraphScreen('), main.indexOf('export function MissionDebugger('));
  if (!/onSecond\?\.\(replay && override !== null \? override : null\)/.test(graph)) bad.push('① GraphScreen 이 되감기 값을 올리지 않는다');
  if (!/return \(\) => onSecond\?\.\(null\)/.test(graph)) bad.push('① GraphScreen 이 내려갈 때 null 을 안 올린다 — 지난 되감기 값이 명령 표에 남는다');
  // ② 받기 · 넘기기
  const app = main.slice(main.indexOf('export function MissionDebugger('));
  if (!/<GraphScreen[\s\S]*?onSecond=\{setViewSecond\}/.test(app)) bad.push('② MissionDebugger 가 GraphScreen 의 되감기 값을 안 받는다');
  // 그 요소 하나의 글자만 본다 — 속성 안에 화살표 함수(`=>`)가 있어 `>` 로는 끝을 못 찾는다.
  const at = app.indexOf('<ActionModal');
  const element = at < 0 ? '' : app.slice(at, app.indexOf(' />}', at));
  if (!element.includes('second={viewSecond ?? undefined}')) bad.push('② ActionModal 에 second 를 안 넘긴다 — 명령 표가 라이브 머리로 접힌다');
  // ③ 접기마다
  const calls = [...modal.matchAll(/actionsAt\(([^)]*)\)/g)].filter((m) => !modal.slice(Math.max(0, m.index - 3), m.index).includes('`'));
  const bare = calls.filter((m) => m[1].trim() !== 'second');
  if (calls.length < 3) bad.push(`③ ActionModal 의 접기가 ${calls.length}곳뿐이다 — 셋 이상이어야 한다(명령 표 · 조정 목록 · 각도 줄 수)`);
  for (const m of bare) bad.push(`③ ActionModal 에 second 를 안 받는 접기가 있다 — actionsAt(${m[1]})`);
  if (!/<RobotCommands taskId=\{task\.id\} second=\{second\} \/>/.test(modal)) bad.push('③ 명령 표(RobotCommands)에 second 를 안 넘긴다');
  return bad;
}

const main = readSource(root, 'src', 'main.tsx');
const modal = readSource(root, 'src', 'views', 'ActionModal.tsx');
const real = judge(main, modal);
failures.push(...real);
if (real.length === 0) console.log('✅ 원본 — 슬라이더 값이 명령 표의 접기 전부에 닿는다');

const controls = [
  ['명령 표 한 곳을 actionsAt() 로 되돌린 사본', main, mutate(modal, 'const folded = actionsAt(second).filter(attachedToNode);', 'const folded = actionsAt().filter(attachedToNode);')],
  ['모달에 second 를 안 넘기는 사본', mutate(main, " second={viewSecond ?? undefined}", ''), modal],
  ['되감기 값을 안 올리는 사본', mutate(main, 'onSecond?.(replay && override !== null ? override : null);', 'onSecond?.(null);'), modal],
];
const caught = [];
for (const [name, m, v] of controls) {
  if (m === null || v === null) { failures.push(`대조군을 만들지 못했다: ${name}`); continue; }
  const hit = judge(m, v);
  if (hit.length > 0) caught.push(`${name} (${hit[0].slice(0, 50)})`);
  else failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
}

if (failures.length > 0) {
  console.error(`❌ verify:action-modal-rewind — ${failures.length}건\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${caught.length}건 전부 검출 — ${caught.join(' · ')}`);
console.log('✅ verify:action-modal-rewind — 화면의 명령 표가 슬라이더를 따라간다');
