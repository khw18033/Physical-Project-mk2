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
  // 260928 — **머리줄 입력칸(`StepCommandBar`)은 없어졌다** (사용자 지시). 정량 명령의 입구는 발화·문장 입력
  // 하나이고, 승인은 제안 카드의 승인 버튼, 발행은 「임무 시작」이다(아래 7 · 8). 입력칸이 돌아오면 안 된다.
  const shell = readSource(join(root, 'src', 'shell', 'AppShell.tsx'));
  if (/StepCommandBar/.test(shell)) failures.push('머리줄에 정량 명령 입력칸이 다시 생겼다 — 없애기로 했다');
  // **모델을 안 부른다.** 숫자를 지어내면 로봇이 그만큼 움직인다.
  const parser = readSource(join(root, 'src', 'physical', 'stepScript.ts'));
  if (/fetch\(|\/generate\/|LlmClient/.test(parser)) failures.push('문장 해석이 바깥을 부른다 — 규칙으로만 읽어야 한다');
}

// ── 7. **발화·문장으로 들어와도 작동한다** (260922 지시) ────────────────────
//
// 머리줄 입력칸은 도구이지 유일한 입구가 아니다. 사람이 말하거나 적은 문장이 정량 명령이면
// 그것으로 **임무가 서야** 한다 — 「Go1이 1m 앞으로 전진해」는 대본에 없고 모델에게 물을
// 것도 없다(사람이 이미 숫자로 다 적었다).
//
// **섞인 문장은 손대지 않고 지나보낸다.** 「90도 회전시킨 후 거울 위치를 탐지한 후…」는
// 정량과 임무 어휘가 섞여 있어 우리가 통째로 읽을 수 없다. 앞부분만 내면 사람이 적은 것과
// 다른 것이 로봇에게 가므로, 그때는 대본 매칭과 생성이 하던 대로 받는다.
{
  const { stepMissionView, stepCommandsOf } = await load('src', 'physical', 'stepScript.ts');

  // ① 정량 명령만 — 임무가 선다.
  const only = read('Go1이 1m 앞으로 전진해');
  if (only.reject !== null) failures.push(`정량 명령만인 문장을 거부했다 — ${only.reject.key}`);
  const view = stepMissionView('Go1이 1m 앞으로 전진해', only, 'MSN-Q-test');
  if (view.tasks.length !== 1) failures.push(`태스크가 ${view.tasks.length}개 — 걸음 수와 같아야 한다`);
  if (view.milestones.length !== 1) failures.push('마일스톤이 없다 — 승인 판단 재료가 없어진다');
  // **걸음이 임무에 실려 있다.** 화면이 그린 태스크와 로봇에 나갈 걸음이 같은 출처여야 한다.
  if (stepCommandsOf(view.params).length !== only.steps.length) {
    failures.push('임무에 실린 걸음 수가 읽은 것과 다르다');
  }
  // 차례가 매달려 있다 — 돌기 전에 가면 엉뚱한 데로 간다.
  const three = read('오른쪽 90도 회전 후 1m 전진 후 왼쪽 90도 회전');
  const chained = stepMissionView('x', three, 'MSN-Q-x');
  if (chained.tasks[0].deps.length !== 0) failures.push('첫 걸음에 선행이 붙었다');
  for (let i = 1; i < chained.tasks.length; i += 1) {
    if (chained.tasks[i].deps[0] !== chained.tasks[i - 1].id) failures.push('걸음이 차례대로 안 매달렸다');
  }

  // ② 섞인 문장 — **지나보낸다.** 여기서 임무를 세우면 절반만 실행된다.
  const mixed = read('Go1을 90도 왼쪽으로 회전시킨 후 거울 위치를 탐지한 후 거기까지 이동해');
  if (mixed.reject === null) failures.push('섞인 문장을 통째로 읽었다고 했다 — 절반만 나간다');
  if (mixed.steps.length !== 0) failures.push(`섞인 문장에서 ${mixed.steps.length}걸음을 냈다`);

  // ③ 화면이 그 갈래를 실제로 쓰는가. 안 쓰면 위가 다 맞아도 발화는 그대로 떨어진다.
  const panel = readSource(join(root, 'src', 'views', 'UtterancePanel.tsx'));
  if (!/proposeQuantitative\(/.test(panel)) failures.push('발화 경로가 정량 명령을 안 본다');
  // 260928 — 조건이 두 줄로 갈렸다(거부면 사유를 돌려주고, 걸음이 0이면 false). 둘 다 `proposeSteps` 앞에 있어야 한다.
  const quant = panel.slice(panel.indexOf('function proposeQuantitative'), panel.indexOf('return proposeSteps('));
  if (!/if \(script\.reject !== null\)/.test(quant) || !/if \(script\.steps\.length === 0\) return false;/.test(quant)) {
    failures.push('통째로 읽혔을 때만 세우는 조건이 없다 — 섞인 문장이 반만 실행된다');
  }
  // ④ **모델 제안으로 뭉치지 않는다.** 근거가 다르다(논문 §4-3).
  const store = readSource(join(root, 'src', 'data', 'scenario.ts'));
  if (!/origin: 'steps'/.test(store)) failures.push('정량 명령 제안이 따로 서지 않는다');
  if (/proposeSteps[\s\S]{0,400}origin: 'ai'/.test(store)) failures.push('정량 명령을 모델이 낸 것으로 적었다');
  // ⑤ **승인 전에는 안 나간다.** 시작을 눌러야 걸음이 나간다.
  const commands = readSource(join(root, 'src', 'physical', 'robotCommands.ts'));
  if (!/session\.started && session\.approved/.test(commands)) {
    failures.push('승인·시작 없이 걸음이 나간다');
  }
}

// ── 9. **반 바퀴·한 바퀴는 방향이 없어도 받는다** (260928 — 「로봇 180도 회전 후 1미터 전진」) ───────────
{
  const half = read('로봇 180도 회전 후 1미터 전진');
  if (half.reject !== null) failures.push(`방향 없는 180도 회전을 거부했다 — ${half.reject.key}`);
  else {
    if (JSON.stringify(shape(half)) !== JSON.stringify([['turn', { deg: 180 }], ['move_forward', { distance_m: 1, vx: half.steps[1]?.parameters?.vx }]])) failures.push(`180도 + 1m 가 ${JSON.stringify(shape(half))} 로 읽혔다`);
    if (!half.notes.some((note) => note.key === 'step.note.sideAssumed')) failures.push('방향을 정해 돌면서 그 사실을 안 적는다');
  }
  // 그 밖의 각도는 여전히 되묻는다 — 거기서는 방향이 곧 결과다.
  if (read('로봇 90도 회전 후 1미터 전진').reject?.key !== 'step.reject.noSide') failures.push('방향 없는 90도 회전을 받았다');
  // 발화 경로가 멈춘 사유를 띄운다 — 입력칸이 없어진 뒤 사유가 사라졌었다.
  const panel = readSource(join(root, 'src', 'views', 'UtterancePanel.tsx'));
  if (!/utter\.quantStopped/.test(panel)) failures.push('정량 명령으로 읽다 멈춘 사유를 화면에 안 띄운다');
}

// ── 8. **승인하면 「임무 시작」이 된다** (260928 — 「정량 명령 임무가 시작이 안 된다」) ──────────────
//
// 두 겹으로 막혀 있었다. ① 통합 앱의 승인 칸은 게이트웨이 계획만 그려서 정량 명령에는 승인 버튼이 없었고,
// ② 승인해도 이 길(`activateGenerated`)은 로봇 관문을 안 열어 `markStarted()` 가 「승인 없이는 시작도 없다」에서 돌아갔다.
{
  const scenario = await load('src', 'data', 'scenario.ts');
  const session = await load('src', 'physical', 'robotSession.ts');
  const { stepMissionView } = await load('src', 'physical', 'stepScript.ts');
  const script = read('Go1이 1m 앞으로 전진해');
  scenario.proposeSteps(stepMissionView('Go1이 1m 앞으로 전진해', script, 'MSN-Q-verify'), 'Go1이 1m 앞으로 전진해');
  if (session.robotSession().approved) failures.push('제안만으로 로봇 관문이 열렸다 — 승인 전에 열리면 안 된다');
  scenario.acceptProposal('local');
  if (!session.robotSession().approved) failures.push('정량 명령을 승인했는데 로봇 관문이 안 열렸다 — 「임무 시작」이 아무 일도 안 한다');
  session.markStarted();
  if (!session.robotSession().started) failures.push('승인 뒤 「임무 시작」을 눌렀는데 시작되지 않았다');
  session.resetRobotSession();
  // 모델이 낸 임무는 열지 않는다 — 보낼 걸음이 없고, 열면 「임무 시작」에 스캔 조건이 돈다.
  scenario.proposeGenerated({ ...stepMissionView('모델 계획', script, 'MSN-AI-verify'), params: {} }, { producedBy: 'ai', engine: 'verify', model: 'verify', stub: true, promptDigest: null, promptChars: null, grammar: null, rules: [], overwritten: [], schemaErrors: [], elapsedSec: 0, shapeWarnings: [], examplesGiven: 0, placesGiven: false, equipmentGiven: false, nodeKindsGiven: false });
  scenario.acceptProposal('local');
  if (session.robotSession().approved) failures.push('모델이 낸 임무의 승인이 로봇 관문을 열었다');
  scenario.resetMission();
  session.resetRobotSession();
  // ① 통합 앱에서도 게이트웨이를 안 거친 제안은 화면이 승인한다.
  const main = readSource(join(root, 'src', 'main.tsx'));
  if (!/origin !== 'script'/.test(main) || !/localOnly \? undefined : planApproval/.test(main)) {
    failures.push('통합 앱에서 정량 명령 제안에 승인 버튼이 없다 — 게이트웨이 칸만 그린다');
  }
}

// ── 10. **걸음은 걸을 수 있는 장비로 · 정지 뒤 재시작이 된다** (260928 — 「Go1 을 붙이고 시작해도 안 움직인다」) ──
//
// 걸음이 연결 관리 **첫 줄** 브로커로만 나갔다. 첫 줄에 드론(pi3)이 있으면 Go1 이 붙어 있어도 조용히 안 나갔다.
// 정지 뒤 「재시작」은 일시정지만 풀어 반응이 없었고, 「처음부터」는 정량 명령 임무를 다시 못 세웠다.
{
  const scenario = await load('src', 'data', 'scenario.ts');
  const session = await load('src', 'physical', 'robotSession.ts');
  const { robotClients } = await load('src', 'physical', 'robotClient.ts');
  const { registerConnectionDefault } = await load('src', 'shared', 'connections.ts');
  const di = await load('src', 'physical', 'deviceIdentity.ts');
  const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
  const { emergencyStop } = await load('src', 'physical', 'robotCommands.ts');
  const notes = await load('src', 'shared', 'notifications.ts');
  const { stepMissionView } = await load('src', 'physical', 'stepScript.ts');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const sent = [];
  let n = 0;
  const origSend = PhysicalClient.prototype.send;
  const origStatus = PhysicalClient.prototype.getStatus;
  PhysicalClient.prototype.getStatus = function getStatus() { return { state: 'open' }; };
  PhysicalClient.prototype.send = function send(action) {
    n += 1;
    const commandId = `v-${n}`;
    sent.push(`${this.address().includes('pi7') ? 'pi7' : 'pi3'}:${action}`);
    const emit = (m) => { for (const l of this.listeners) l(m); };
    setTimeout(() => {
      if (action === 'abort') return;
      emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null });
      setTimeout(() => emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: {}, code: null, message: null }), 50);
    }, 5);
    return { sent: true, commandId };
  };
  registerConnectionDefault('physical', 'ws', ['ws://pi3.test:9001', 'ws://pi7.test:9001/mqtt'].join(String.fromCharCode(10)));
  const [pi3, pi7] = robotClients();
  di.noteDeviceReport('x500-001', 'drone', { channel: 'status', status: 'online', registration: { entity_id: 'x500-001', entity_type: 'drone' } }, pi3.address());
  di.noteDeviceReport('go1-001', 'robot', { channel: 'status', status: 'online', registration: { entity_id: 'go1-001', entity_type: 'robot' } }, pi7.address());
  // 화면이 하는 것과 같게 응답 수신기를 붙인다(`useRobotUplink` — 붙은 브로커 전부).
  const { receiveUplink } = await load('src', 'physical', 'robotBridge.ts');
  const offs = [pi3, pi7].map((client) => client.onMessage((message) => receiveUplink(message, 'MSN-Q-route', session.elapsedSec())));
  const sentence = '로봇 180도 회전 후 1미터 전진';
  scenario.proposeSteps(stepMissionView(sentence, read(sentence), 'MSN-Q-route'), sentence);
  scenario.acceptProposal('local');
  session.markStarted();
  await sleep(600);
  if (sent.join(',') !== 'pi7:turn,pi7:move_forward') failures.push(`첫 줄이 드론일 때 걸음이 ${sent.join(',') || '안 나갔다'} — pi7 로 turn · move_forward 여야 한다`);
  /**
   * **노드에 불이 들어온다** (260928 — 「임무는 진행되는데 노드에 불이 안 들어온다」). 걸음이 `T-STEP` 을 들고 나가서
   * 응답이 아무 노드도 못 칠했다. 이제 걸음마다 그 노드의 id(`T-Q1` · `T-Q2`)를 든다.
   */
  const painted = (id) => scenario.traceEvents().filter((e) => e.nodeId === id).map((e) => e.status);
  for (const id of ['T-Q1', 'T-Q2']) {
    if (!painted(id).includes('done')) failures.push(`${id} 가 로봇 응답으로 안 칠해졌다 — [${painted(id).join(',')}]`);
  }
  if (scenario.traceEvents().some((e) => e.nodeId === 'T-STEP')) failures.push('없는 노드(T-STEP)에 사건이 붙었다');
  for (const off of offs) off();
  sent.length = 0;
  await emergencyStop(pi7);
  if (scenario.restartMission()) session.markStarted();
  await sleep(600);
  if (!sent.includes('pi7:turn')) failures.push(`정지 뒤 재시작이 걸음을 다시 안 냈다 — ${sent.join(',') || '없음'}`);
  sent.length = 0;
  di.resetDeviceIdentity(pi7.address());
  if (scenario.restartMission()) session.markStarted();
  await sleep(200);
  if (sent.length !== 0) failures.push(`걸을 장비가 없는데 ${sent.join(',')} 가 나갔다`);
  if (!notes.notificationsNow().some((x) => String(x.message).includes('걸을 수 있는 로봇이 붙어 있지 않습니다'))) failures.push('걸을 장비가 없을 때 사유를 알림에 안 적었다 — 아무 반응이 없는 것처럼 보인다');
  PhysicalClient.prototype.send = origSend;
  PhysicalClient.prototype.getStatus = origStatus;
  scenario.resetMission();
  session.resetRobotSession();
  di.resetDeviceIdentity();
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
console.log('✅ 문구가 전부 사전에 있다 · 머리줄 입력칸은 없다(입구는 발화·문장 하나)');
console.log('✅ 발화·문장으로 들어온 정량 명령이 임무가 된다 — 섞인 문장은 지나보낸다 (승인·시작 뒤에 나간다)');
console.log('✅ 걸음마다 그 노드의 id 를 들고 가서 로봇 응답이 T-Q1 · T-Q2 를 칠한다');
console.log('✅ 걸음은 걸을 수 있는 장비의 브로커로(첫 줄 무관) · 정지 뒤 재시작은 처음부터 다시 · 걸을 장비가 없으면 알림에 사유');
console.log('✅ 승인하면 로봇 관문이 열리고 「임무 시작」이 된다 · 통합 앱에도 승인 버튼이 있다 · 모델이 낸 임무는 관문을 안 연다');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
