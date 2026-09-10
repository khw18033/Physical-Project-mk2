// verify:no-detect (260910 신설 — 연결 관리 통합 지시서 §6)
//
// **탐지가 없어도 그 줄만 빨갛고 나머지는 도는가.**
//
// `verify:no-stt` · `verify:no-llm` · `verify:no-physical` 과 같은 검사다. 탐지는 2단계-B
// 에서 붙으므로 **지금은 늘 없는 상태**이고, 그 상태가 나머지를 끌어내리면 안 된다.
//
// 특히 §5 의 발표 직전 점검이 성립해야 한다 — 넷 중 detect 만 「아직 확인하지 않음」이고
// 나머지 셋은 초록일 수 있어야 한다. detect 를 지금 빨갛게 칠하면 「넷 다 초록」이
// 애초에 불가능해진다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { checkDetect, checkTarget } = await load('src', 'shared', 'connectionCheck.ts');
const {
  resetHealth, setHealth, line, healthOf, targetOk, firstBroken, CHECKED_TARGETS,
} = await load('src', 'shared', 'connectionHealth.ts');
const { CONNECTION_TARGETS } = await load('src', 'shared', 'connections.ts');

const failures = [];
const controls = [];

// ── 1. 자리는 있다 ──────────────────────────────────────────────────────────
{
  const target = CONNECTION_TARGETS.find((t) => t.id === 'detect');
  if (target === undefined) failures.push('연결 관리에 detect 자리가 없다');
  // 없는 서비스를 있는 척하지 않는다 — 자리표시 문구가 있어야 한다.
  if (target !== undefined && !String(target.pending ?? '').trim()) {
    failures.push('detect 에 「아직 안 붙었다」는 문구가 없다 — 없는 것을 있는 척하면 안 된다');
  }
  if (target !== undefined && !/2단계-B/.test(String(target.pending))) {
    failures.push('detect 자리표시가 언제 붙는지 안 적었다');
  }
}

// ── 2. 확인이 던지지 않는다 ─────────────────────────────────────────────────
{
  let lines;
  try {
    lines = await checkDetect();
  } catch (error) {
    failures.push(`detect 확인이 던졌다 — ${error instanceof Error ? error.message : error}`);
    lines = [];
  }
  if (lines.length === 0) failures.push('detect 확인이 아무 줄도 안 낸다');
  // **실제 확인은 2단계-B 에서 잇는다** — 지금 GET /health 를 부르면 안 된다.
  if (!/2단계-B/.test(String(lines[0]?.reason))) {
    failures.push('detect 가 「아직 확인하지 않는다」고 말하지 않는다');
  }

  // 확인 버튼을 눌러도 팝업이 안 날아간다.
  resetHealth();
  await checkTarget('detect', null);
  if (healthOf('detect').lines.length === 0) failures.push('detect 확인 뒤 결과가 안 남았다');
  if (healthOf('detect').checking) failures.push('detect 확인이 끝났는데 「확인 중」이 안 풀렸다');
}

// ── 3. detect 가 나머지를 끌어내리지 않는다 ─────────────────────────────────
{
  resetHealth();
  await checkTarget('detect', null);
  setHealth('physical', [line('broker', '브로커', true), line('robot', '로봇', true, { roundTripMs: 9 })]);
  setHealth('stt', [line('probe', '서비스', true, { roundTripMs: 4 })]);
  setHealth('generate', [line('probe', '서비스', true, { roundTripMs: 6 })]);

  if (targetOk('physical') !== true) failures.push('detect 때문에 physical 이 빨개졌다');
  if (targetOk('stt') !== true) failures.push('detect 때문에 stt 가 빨개졌다');
  if (targetOk('generate') !== true) failures.push('detect 때문에 generate 가 빨개졌다');

  // 표시등이 짚는 것은 detect 하나여야 한다.
  const broken = firstBroken(CHECKED_TARGETS);
  if (broken?.target !== 'detect') {
    failures.push(`표시등이 ${broken?.target} 을 짚는다 — 지금 끊긴 것은 detect 하나다`);
  }
}

// ── 4. 화면은 탐지 없이도 돈다 ──────────────────────────────────────────────
//
// 문 유무는 아직 대본이 준다(2단계-A §6). 탐지가 없다고 뷰포인트가 안 차면 안 된다.
{
  const { readFileSync } = await import('node:fs');
  const { emptyFill, reduceFrames, cellsInOrder } = await load('src', 'viewpoint', 'fill.ts');
  const { scriptFrames } = await load('src', 'viewpoint', 'source.ts');
  const door = JSON.parse(readFileSync(join(root, 'scenarios', 'MSN-260909-01.json'), 'utf8'));
  const fill = reduceFrames(emptyFill(8), scriptFrames(door.viewpointTimeline, door.durationSec));
  const selected = cellsInOrder(fill).filter((c) => c.phase === 'selected').length;
  if (selected !== 1) failures.push(`탐지 없이 돌린 대본이 선정 ${selected}칸 — 문 유무는 대본이 준다`);
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  // detect 를 빨갛게 칠한 사본이라면 「넷 다 초록」이 불가능하다 — 지금이 그 상태다.
  resetHealth();
  await checkTarget('detect', null);
  control('detect 는 지금 초록이 될 수 없다', targetOk('detect') === false);
}
{
  resetHealth();
  control('안 눌러 본 detect 는 「모른다」', targetOk('detect') === null);
}

resetHealth();

if (failures.length) {
  console.error(`❌ verify:no-detect\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ detect 자리가 있고 「2단계-B 에서 잇는다」고 적혀 있다 — 없는 것을 있는 척하지 않는다');
console.log('✅ detect 확인이 던지지 않는다 — 눌러도 팝업이 안 날아간다');
console.log('✅ detect 가 나머지 셋을 안 끌어내린다 · 표시등이 짚는 것은 detect 하나');
console.log('✅ 탐지 없이도 뷰포인트가 찬다 — 문 유무는 아직 대본이 준다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
