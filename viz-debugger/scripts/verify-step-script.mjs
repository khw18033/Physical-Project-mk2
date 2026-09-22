// verify:step-script (260922 신설 — 정량 명령 직접 입력)
//
// **사람이 적은 숫자가 그대로 걸음이 되는가. 못 읽으면 아무것도 안 내는가.**
//
// 이 기능의 실패는 화면에서 안 보인다 — **로봇이 틀리게 걷는다.** 그래서 재는 것이 둘이다:
// 읽은 값이 맞는가, 그리고 **못 읽었을 때 절반만 내지 않는가.**
//
// 보는 것 여섯.
//  1. 읽는다 — 거리·각도·방향·이어붙임
//  2. **거부한다** — 방향 없는 회전, 수치 없는 문장, 모르는 말 ← 이번 작업의 요점
//  3. 규약 범위로 자른다 — 10m 상한, 시한(45초 예산), 5도·0.05m 최솟값
//  4. **자른 것을 숨기지 않는다** — 알림이 따라 나온다
//  5. 뒤로 가기는 안 만든다 — 음수를 안 쏜다
//  6. 문구가 전부 사전에 있다 — 화면에 키가 그대로 뜨면 안 된다
//
// 2번이 핵심이다. 「1m 전진 후 어쩌고」에서 앞부분만 내면 **사람이 적은 것과 다른 것이
// 로봇에게 나간다.** 절반만 읽고 나머지를 지어내지 않는다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const { ko: koDict } = await import(pathToFileURL(join(root, 'src', 'i18n', 'ko.ts')).href);

const {
  parseStepScript, forwardChunkM, STEP_VX, STEP_BUDGET_S,
  TURN_MIN_DEG, TURN_MAX_DEG, FORWARD_MIN_M, FORWARD_MAX_M,
} = await load('src', 'physical', 'stepScript.ts');

const failures = [];
const controls = [];

const read = (sentence, vx) => parseStepScript(sentence, vx);
const shape = (script) => script.steps.map((step) => [step.action, step.parameters]);

// ── 1. 읽는다 ────────────────────────────────────────────────────────────────
{
  const one = read('1m 전진 후 오른쪽 90도 회전');
  if (one.reject !== null) failures.push(`기본 문장을 거부했다 — ${one.reject.key}`);
  const got = shape(one);
  if (got.length !== 2) failures.push(`걸음이 ${got.length}개 — 둘이어야 한다`);
  if (got[0]?.[0] !== 'move_forward' || got[0]?.[1]?.distance_m !== 1) failures.push('1m 전진을 못 읽었다');
  if (got[1]?.[0] !== 'turn' || got[1]?.[1]?.deg !== 90) failures.push('오른쪽 90도를 못 읽었다');
  // **차례가 적힌 대로다.** 돌기 전에 가야 하는데 뒤바뀌면 엉뚱한 데로 간다.
  if (got[0][0] !== 'move_forward') failures.push('차례가 문장과 다르다');

  // 왼쪽은 **부호가 뒤집힌다** — 규약이 「오른쪽 +」다.
  const left = read('왼쪽 90도 회전');
  if (shape(left)[0]?.[1]?.deg !== -90) failures.push(`왼쪽 90도가 ${shape(left)[0]?.[1]?.deg} — -90 이어야 한다`);

  // 단위 표기들.
  if (shape(read('50cm 전진'))[0]?.[1]?.distance_m !== 0.5) failures.push('cm 를 못 읽었다');
  if (shape(read('1미터 전진'))[0]?.[1]?.distance_m !== 1) failures.push('한글 단위를 못 읽었다');
  if (shape(read('0.5m 전진'))[0]?.[1]?.distance_m !== 0.5) failures.push('소수를 못 읽었다');

  // 이어붙임 — 세 걸음.
  const three = read('오른쪽 90도 회전 후 1m 전진 후 왼쪽 90도 회전');
  if (shape(three).length !== 3) failures.push(`이어붙임이 ${shape(three).length}걸음 — 셋이어야 한다`);

  // **속도는 늘 실린다** (260922 결정 — 문장에서 안 읽는다).
  if (shape(read('1m 전진'))[0]?.[1]?.vx !== STEP_VX) failures.push('속도가 안 실렸다');
}

// ── 2. 거부한다 — 절반만 읽고 나머지를 지어내지 않는다 (요점) ───────────────
{
  const cases = [
    ['90도 회전', 'step.reject.noSide', '방향이 없다'],
    ['조금만 앞으로', 'step.reject.noDistance', '수치가 없다'],
    ['회전', 'step.reject.noAngle', '각도가 없다'],
    ['어쩌고', 'step.reject.unknown', '무엇을 하라는지 모른다'],
    ['', 'step.reject.empty', '빈 문장'],
    ['왼쪽 오른쪽 90도 회전', 'step.reject.bothSides', '방향이 둘이다'],
  ];
  for (const [sentence, key, why] of cases) {
    const script = read(sentence);
    if (script.reject?.key !== key) {
      failures.push(`「${sentence}」(${why}) 를 ${script.reject?.key ?? '안 거부했다'} — ${key} 여야 한다`);
    }
    // **한 걸음도 안 낸다.** 이것이 이 검사의 이유다.
    if (script.steps.length !== 0) {
      failures.push(`「${sentence}」를 거부하고도 ${script.steps.length}걸음을 냈다`);
    }
  }

  /**
   * **일부만 읽히는 문장이 제일 위험하다.** 앞은 읽히고 뒤는 안 읽힌다 — 앞부분만 내면
   * 로봇이 1m 를 가고 거기서 멈춘다. 사람은 회전까지 될 줄 알고 서 있다.
   */
  const half = read('1m 전진 후 어쩌고');
  if (half.steps.length !== 0) failures.push(`절반만 읽고 ${half.steps.length}걸음을 냈다 — 0이어야 한다`);
  if (half.reject === null) failures.push('절반만 읽었는데 거부하지 않았다');
}

// ── 3·4. 규약 범위로 자르고, 자른 것을 숨기지 않는다 ────────────────────────
{
  // 구간 상한은 **규약과 시한 중 먼저 걸리는 쪽**이다.
  if (forwardChunkM(0.3) !== FORWARD_MAX_M) failures.push('0.30 m/s 에서 규약 상한이 안 걸린다');
  if (Math.abs(forwardChunkM(0.15) - 0.15 * STEP_BUDGET_S) > 1e-9) {
    failures.push('0.15 m/s 에서 시한이 안 걸린다 — 10m 를 한 번에 보내 시한을 넘긴다');
  }

  // 15m — 나뉘고, 각 구간이 상한 이하이고, 합이 보존된다.
  const long = read('15m 전진');
  const pieces = shape(long);
  if (pieces.length < 2) failures.push('15m 가 안 나뉘었다');
  const total = pieces.reduce((sum, [, params]) => sum + params.distance_m, 0);
  if (Math.abs(total - 15) > 0.05) failures.push(`나눈 합이 ${total}m — 15m 여야 한다`);
  for (const [, params] of pieces) {
    if (params.distance_m > FORWARD_MAX_M) failures.push(`구간이 ${params.distance_m}m — 규약 상한을 넘는다`);
    if (params.distance_m < FORWARD_MIN_M) failures.push(`구간이 ${params.distance_m}m — 규약 최소보다 작다`);
  }
  // **숨기지 않는다.**
  if (!long.notes.some((note) => note.key === 'step.note.forwardSplit')) {
    failures.push('나눠 보내면서 그 사실을 안 적었다');
  }

  // 시한이 걸리는 속도에서는 구간이 더 잘게 나뉜다.
  const slow = read('10m 전진', 0.15);
  for (const [, params] of shape(slow)) {
    if (params.distance_m > forwardChunkM(0.15) + 1e-9) {
      failures.push(`0.15 m/s 인데 구간이 ${params.distance_m}m — 시한을 넘는다`);
    }
  }

  // 최솟값 아래는 **안 낸다.** 조용히 버리지 않고 적는다.
  const tiny = read('3도 회전');
  if (tiny.steps.length !== 0) failures.push('3도 회전을 냈다 — 규약이 안 받는다');
  const tinyFwd = read('2cm 전진');
  if (tinyFwd.steps.length !== 0) failures.push('0.02m 직진을 냈다');
  if (!tinyFwd.notes.some((note) => note.key === 'step.note.forwardTooSmall')) {
    failures.push('너무 작아 안 낸 사실을 안 적었다');
  }

  // 360 초과 회전은 나뉜다.
  const spin = read('오른쪽 540도 회전');
  const turns = shape(spin);
  if (turns.length < 2) failures.push('540도가 안 나뉘었다');
  for (const [, params] of turns) {
    if (Math.abs(params.deg) > TURN_MAX_DEG) failures.push(`회전 구간이 ${params.deg}도 — 상한을 넘는다`);
    if (Math.abs(params.deg) < TURN_MIN_DEG) failures.push(`회전 구간이 ${params.deg}도 — 최소보다 작다`);
  }
  if (Math.abs(turns.reduce((sum, [, p]) => sum + p.deg, 0) - 540) > 0.1) failures.push('나눈 회전의 합이 다르다');
}

// ── 5. 뒤로 가기는 안 만든다 ────────────────────────────────────────────────
//
// Go1 은 뒤로 걷는다. 막는 것은 **어휘**다 — 음수를 넣으면 어떻게 읽히는지 문서에 없고
// 쏴 본 적도 없다. 절댓값으로 읽혀 **앞으로 갈 수도** 있다. 실험으로 알아보지 않는다.
{
  const back = read('-1m 전진');
  if (back.steps.length !== 0) failures.push('음수 거리를 걸음으로 냈다 — 쏴 본 적 없는 값이다');
  if (back.reject?.key !== 'step.reject.backward') failures.push('뒤로 가기를 뒤로 가기라고 말하지 않는다');
  // 어느 걸음에도 음수 거리가 없어야 한다.
  for (const sentence of ['1m 전진', '15m 전진', '50cm 전진']) {
    for (const [action, params] of shape(read(sentence))) {
      if (action === 'move_forward' && params.distance_m <= 0) failures.push('음수·0 거리가 나갔다');
      if (params.vx !== undefined && (params.vx < 0.05 || params.vx > 0.3)) failures.push(`속도 ${params.vx} 가 규약 밖이다`);
    }
  }
}

// ── 6. 문구가 전부 사전에 있다 ──────────────────────────────────────────────
{
  const keys = new Set();
  const sentences = ['', '어쩌고', '90도 회전', '회전', '조금만 앞으로', '왼쪽 오른쪽 90도 회전',
    '-1m 전진', '3도 회전', '2cm 전진', '15m 전진', '오른쪽 540도 회전', '1m 전진 후 오른쪽 90도 회전'];
  for (const sentence of sentences) {
    const script = read(sentence);
    if (script.reject !== null) keys.add(script.reject.key);
    for (const note of script.notes) keys.add(note.key);
  }
  for (const key of keys) {
    if (koDict[key] === undefined) failures.push(`${key} 가 사전에 없다 — 화면에 키가 그대로 뜬다`);
  }
  // 화면이 그 값을 실제로 푸는가 — 키만 맞고 안 그리면 아무것도 안 바뀐다.
  const bar = readSource(join(root, 'src', 'physical', 'StepCommandBar.tsx'));
  if (!/t\(read\.reject\.key, read\.reject\.vars\)/.test(bar)) failures.push('화면이 거부 사유를 안 그린다');
  if (!/t\(note\.key, note\.vars\)/.test(bar)) failures.push('화면이 알림을 안 그린다');
  /**
   * **승인 전에 바이트가 나가지 않는다**(`VZ-U-07`). 읽기와 보내기가 한 번에 일어나면
   * 잘못 읽은 문장이 그대로 로봇에게 간다.
   */
  if (!/disabled=\{!ready \|\| busy\}/.test(bar)) failures.push('읽기 전에 보내기가 열려 있다');
  if (!/setRead\(null\)/.test(bar)) failures.push('문장을 고쳐도 읽은 것이 남는다 — 고치기 전 문장을 승인한 채로 보낸다');
  // **모델을 안 부른다.** 숫자를 지어내면 로봇이 그만큼 움직인다.
  const parser = readSource(join(root, 'src', 'physical', 'stepScript.ts'));
  if (/fetch\(|\/generate\/|LlmClient/.test(parser)) failures.push('문장 해석이 바깥을 부른다 — 규칙으로만 읽어야 한다');
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name}`);
  controls.push(name);
}
{
  // 방향에 기본값을 주던 사본 — 반대로 도는 날이 온다.
  const withDefault = (script) => (script.reject?.key === 'step.reject.noSide'
    ? [['turn', { deg: 90 }]]                              // 오른쪽으로 짐작
    : shape(script));
  control('기본값을 주는 사본은 방향 없는 회전을 낸다', withDefault(read('90도 회전')).length === 1);
  control('지금은 안 낸다', read('90도 회전').steps.length === 0);

  // 규약 상한만 보고 자르던 사본 — 0.15 m/s 에서 시한을 넘긴다.
  const protocolOnly = (vx) => FORWARD_MAX_M;
  control('규약만 보면 0.15 m/s 에서 10m 한 건이 된다', protocolOnly(0.15) / 0.15 > 60);
  control('지금은 시한 안으로 자른다', forwardChunkM(0.15) / 0.15 <= STEP_BUDGET_S + 1e-9);

  // 합이 안 맞는 사본 — 15m 를 10m + 5m 가 아니라 10m 하나로 자르면 5m 가 사라진다.
  control('합이 보존된다',
    Math.abs(shape(read('15m 전진')).reduce((s, [, p]) => s + p.distance_m, 0) - 15) <= 0.05);
}

if (failures.length) {
  console.error(`❌ verify:step-script\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 숫자를 읽는다 — 거리(m·cm·미터)·각도·방향(왼쪽은 음수)·이어붙임, 속도는 늘 실린다');
console.log('✅ 못 읽으면 한 걸음도 안 낸다 — 방향 없는 회전·수치 없는 문장·절반만 읽히는 문장');
console.log(`✅ 규약으로 자른다 — 한 건 ${FORWARD_MAX_M}m·${TURN_MAX_DEG}도, 최소 ${FORWARD_MIN_M}m·${TURN_MIN_DEG}도, 시한 ${STEP_BUDGET_S}초 예산 (합이 보존된다)`);
console.log('✅ 자른 것을 숨기지 않는다 · 뒤로 가기는 안 쏜다 (쏴 본 적 없는 값이다)');
console.log('✅ 문구가 전부 사전에 있고 화면이 그것을 푼다 · 읽기 전에는 보내기가 안 열린다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
