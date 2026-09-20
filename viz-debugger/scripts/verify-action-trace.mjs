// verify:action-trace (260920 신설 — 명령 기록 합류 §7)
//
// **명령이 기록 열에 들어가는가.**
//
// 260920 전까지 명령과 로봇 응답은 작업대(`physical/robotSession.ts`)에만 살았다. 작업대는
// **지금 값**이라 되감기가 안 닿는다 — 재생 머리를 10초로 옮겨도 명령 표에는 40초에 온 줄
// 까지 떠 있었다. 「모든 노드가 같은 재생 머리를 쓴다」(논문 §4-4)가 그 자리에서 깨져 있었다.
//
// 보는 것 넷.
//
//  1. **작업대와 기록 열에 같은 `commandId` 가 있다** — 새 식별자를 만들지 않았는가
//  2. **실려 나간 값이 같다** — 화면 계획값이 아니라 바이트에 들어간 것이 양쪽에 같이 있는가
//  3. **응답도 열에 들어간다** — `answered` 가 그 `commandId` 에 붙는가
//  4. **태스크 없는 명령은 안 들어간다** (`NO_NODE`) — 어느 노드도 못 보여 주는 외톨이 행
//
// 대조군 — **기록 열에 안 넣은 사본이 반드시 잡혀야 한다.** 그것이 곧 260920 이전 상태이므로,
// 이 대조군이 안 잡히면 이 검사는 아무것도 증명하지 않는다.
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeScratch } from './lib/scratch.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const failures = [];
const controls = [];

const session = await load('src', 'physical', 'robotSession.ts');
const scenario = await load('src', 'data', 'scenario.ts');
const store = await load('src', 'detect', 'store.ts');
const { ACTION_KINDS } = await load('src', 'data', 'actionTrace.ts');
const { NO_NODE } = await load('src', 'physical', 'missionLink.ts');
const { SDK_ACTIONS } = await load('src', 'physical', 'presets.ts');

const PATH = JSON.parse(readFileSync(join(root, '..', 'door_example', 'test', 'door', 'evidence.json'), 'utf8'));

/** 명령을 세고, 시험자가 원할 때만 응답을 흘리는 가짜 로봇 (`verify:command-log` 와 같은 모양). */
function stubRobot(prefix = 'cmd') {
  const listeners = new Set();
  const sent = [];
  return {
    sent,
    getStatus: () => ({ state: 'open' }),
    send(action, parameters) {
      // **판마다 다른 id.** 열은 지우지 않으므로(덧붙이기 전용) 앞 판의 명령이 그대로
      // 남아 있다 — 같은 id 를 다시 쓰면 대조군이 앞 판의 기록을 보고 통과한다.
      const commandId = `${prefix}-${String(sent.length + 1).padStart(8, '0')}`;
      sent.push({ action, parameters: { ...(parameters ?? {}) }, commandId });
      return { sent: true, commandId };
    },
    onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
    emit(message) { for (const cb of [...listeners]) cb(message); },
  };
}

const { receiveUplink } = await load('src', 'physical', 'robotBridge.ts');

/**
 * **로봇의 답 한 줄을 실제 길로 흘린다.**
 *
 * `client.onMessage` 는 명령을 낸 쪽이 「끝났는가」를 듣는 길이고, 화면 상태로 들어가는
 * 길은 `receiveUplink` 다. 둘 다 쳐야 실제와 같은 판이 된다 — 하나만 치면 다음 명령이
 * 안 나가거나(앞엣것), 기록이 안 남는다(뒤엣것).
 */
async function answer(robot, message, waitMs) {
  robot.emit(message);
  receiveUplink(message, scenario.currentMission().missionId, 3);
  await sleep(waitMs);
}

function armed() {
  session.resetRobotSession();
  session.setConnection({ state: 'open' });
  session.markApproved();
  store.resetDetect();
  store.setTestMode(false);
  store.receivePath(PATH);
}

const column = () => scenario.traceFor(scenario.currentMission());
const commandedIn = (trace) => trace.filter((e) => e.kind === ACTION_KINDS.commanded);

/**
 * **판정 본체 — 작업대와 기록 열을 맞대 본다.**
 *
 * 이것을 함수로 떼어 둔 이유가 대조군이다. 아래에서 **기록 열을 비운 사본**을 같은 함수에
 * 넣어 보고, 그때 잡히지 않으면 이 검사가 무의미하다고 말한다.
 */
export function judgeJoin(workbench, trace) {
  const f = [];
  const commanded = new Map(commandedIn(trace).map((e) => [e.nodeId, e]));
  for (const record of Object.values(workbench)) {
    if (record.taskId === NO_NODE) continue;            // 순서도에 자리가 없는 명령은 대상이 아니다
    const event = commanded.get(record.commandId);
    if (event === undefined) {
      f.push(`작업대에는 있는데 기록 열에 없는 명령: ${record.commandId} (${record.action}) — 되감기가 이 명령에 안 닿는다`);
      continue;
    }
    if (event.payload?.taskId !== record.taskId) {
      f.push(`${record.commandId} 의 태스크가 갈린다 — 작업대 ${record.taskId} · 기록 열 ${event.payload?.taskId}`);
    }
    // **실려 나간 값 그대로인가.** 화면 계획값이 섞이면 둘이 달라진다.
    const a = JSON.stringify(record.parameters);
    const b = JSON.stringify(event.payload?.parameters ?? {});
    if (a !== b) f.push(`${record.commandId} 의 실린 값이 갈린다 — 작업대 ${a} · 기록 열 ${b}`);
  }
  return f;
}

// ── 1 · 2. 낸 명령이 양쪽에 같은 id 로 있다 ─────────────────────────────────
let runTrace = [];
let runWorkbench = {};
{
  armed();
  const robot = stubRobot();
  const running = issueAll(robot);
  await sleep(150);
  if (robot.sent.length === 0) failures.push('명령이 한 건도 안 나갔다 — 이 검사가 볼 것이 없다');

  // 회전 → 직진 → 도착 정지. 걸음마다 종료 응답을 흘려 준다.
  for (let guard = 0; guard < 6 && robot.sent.length > 0; guard += 1) {
    const last = robot.sent.at(-1);
    await answer(robot, { kind: 'acceptance', commandId: last.commandId, accepted: true, code: null, message: null }, 40);
    await answer(robot, { kind: 'result', commandId: last.commandId, status: 'SUCCEEDED', result: {}, code: null, message: null }, 120);
    if (robot.sent.at(-1) === last) break;
  }
  await running;

  runWorkbench = session.robotSession().commands;
  runTrace = column();
  failures.push(...judgeJoin(runWorkbench, runTrace));

  const ids = new Set(Object.keys(runWorkbench).filter((id) => runWorkbench[id].taskId !== NO_NODE));
  if (ids.size < 2) failures.push(`작업대에 남은 명령이 ${ids.size}건 — 회전·직진·정지 셋이 나가야 한다`);
  console.log(`✅ 작업대 ${ids.size}건 · 기록 열의 commanded ${commandedIn(runTrace).length}건 — 같은 commandId 로 맞물린다`);
}

async function issueAll(robot) {
  const { issueApproach } = await load('src', 'physical', 'robotCommands.ts');
  return issueApproach(robot, null);
}

// ── 3. 응답도 열에 붙는다 ───────────────────────────────────────────────────
{
  const answered = runTrace.filter((e) => e.kind === ACTION_KINDS.answered);
  if (answered.length === 0) {
    failures.push('응답이 열에 한 줄도 안 들어갔다 — 되감기가 로봇의 답에 안 닿는다');
  }
  const orphan = answered.filter((e) => !commandedIn(runTrace).some((c) => c.nodeId === e.nodeId));
  if (orphan.length > 0) {
    failures.push(`낸 적 없는 명령의 응답이 열에 있다: ${orphan.map((e) => e.nodeId).join(', ')}`);
  }
  // **로봇이 낸 것으로 적힌다** — 백엔드로 뭉개면 §4-3 이 로봇을 백엔드라고 답한다.
  const wrongly = answered.filter((e) => e.producedBy !== 'robot');
  if (wrongly.length > 0) failures.push(`응답의 produced_by 가 robot 이 아니다: ${[...new Set(wrongly.map((e) => e.producedBy))].join(', ')}`);
  console.log(`✅ 응답 ${answered.length}줄 — 전부 낸 명령에 붙고 produced_by 가 robot 이다`);
}

// ── 4. 태스크 없는 명령은 안 들어간다 ───────────────────────────────────────
{
  const before = column().length;
  session.recordCommand({
    commandId: 'cmd-bridge', taskId: NO_NODE, action: SDK_ACTIONS.start, requestId: null,
    state: 'issued', code: null, message: null, result: {}, issuedAtIso: new Date().toISOString(),
    parameters: {}, log: [],
  });
  receiveUplink({ kind: 'acceptance', commandId: 'cmd-bridge', accepted: true, code: null, message: null }, scenario.currentMission().missionId, 3);
  if (column().length !== before) {
    failures.push('태스크 없는 명령(NO_NODE)의 응답이 열에 들어갔다 — 어느 노드도 못 보여 주는 외톨이 행이다');
  }
  console.log('✅ 태스크 없는 명령(NO_NODE)은 열에 안 들어간다 — verify:sdk-bridge 와 같은 선');
}

// ── 대조군 ──────────────────────────────────────────────────────────────────
//
// **기록 열에 안 넣은 사본이 반드시 잡혀야 한다.** 둘로 본다: ① 판정 함수에 빈 열을 넣어
// 보고 ② 소스에서 `recordCommanded(...)` 를 지운 사본을 실제로 돌려 본다. ①만 하면
// 「판정은 옳은데 아무도 안 부른다」를 못 잡는다.
{
  if (judgeJoin(runWorkbench, runTrace.filter((e) => e.kind !== ACTION_KINDS.commanded)).length === 0) {
    failures.push('대조군 실패: 기록 열에서 commanded 를 통째로 지웠는데 판정이 통과했다');
  } else {
    controls.push('기록 열에서 commanded 를 지운 사본 검출');
  }

  // 실린 값만 바꾼 사본 — 화면 계획값을 적어 넣는 실수가 이 모양이다.
  const swapped = runTrace.map((e) => (e.kind === ACTION_KINDS.commanded
    ? { ...e, payload: { ...e.payload, parameters: { distance_m: 6.35 } } }
    : e));
  if (judgeJoin(runWorkbench, swapped).length === 0) {
    failures.push('대조군 실패: 실린 값을 계획값으로 바꾼 사본이 안 잡혔다');
  } else {
    controls.push('실린 값을 계획값으로 바꾼 사본 검출');
  }
}

{
  /**
   * **소스 사본** — `recordCommanded(...)` 호출을 지운 `robotCommands.ts` 로 같은 판을
   * 돌린다. 260920 이전의 코드가 정확히 이 모양이다.
   *
   * 사본은 `src/physical/` 밑의 대조군 임시 폴더 안에 사므로 상대 경로가 한 칸 깊어진다.
   * `'./x'` → `'../x'`, `'../y'` → `'../../y'` 로 옮겨 **같은 모듈 인스턴스**를 끌어오게
   * 한다 — 그래야 사본이 원본과 같은 기록 열에 쓴다.
   */
  const scratch = makeScratch(join(root, 'src', 'physical'), '.verify-action-');
  try {
    const original = readFileSync(join(root, 'src', 'physical', 'robotCommands.ts'), 'utf8');
    const deepened = original
      .replaceAll("from '../", "from '\u0000/")
      .replaceAll("from './", "from '../")
      .replaceAll("from '\u0000/", "from '../../");
    // `recordCommanded({ ... });` 한 덩어리를 지운다.
    const muted = deepened.replace(/recordCommanded\(\{[\s\S]*?\n      \}\);/, ';');
    if (muted === deepened) {
      failures.push('대조군을 만들지 못했다 — robotCommands.ts 의 recordCommanded 호출 모양이 바뀌었나?');
    } else {
      const path = scratch.file('robotCommands.ts');
      writeFileSync(path, muted, 'utf8');
      const mutant = await import(pathToFileURL(path).href);
      armed();
      const robot = stubRobot('mut');
      void mutant.issueApproach(robot, null);
      await sleep(150);
      const f = judgeJoin(session.robotSession().commands, column());
      if (f.length === 0) {
        failures.push('대조군 실패: 기록 열에 안 넣는 사본이 통과했다 — 이 검사는 무의미하다');
      } else {
        controls.push('recordCommanded 를 지운 robotCommands.ts 사본 검출');
      }
    }
  } finally {
    // 일부 개발 환경은 파일 삭제가 막혀 EPERM 이 난다 — 검사는 이미 끝났으므로 죽지 않는다.
    scratch.cleanup();
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:action-trace\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
