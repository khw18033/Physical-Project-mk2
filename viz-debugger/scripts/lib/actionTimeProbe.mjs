// scripts/lib/actionTimeProbe.mjs (261025 신설 — 액션 층 시각)
//
// **세 가지 판을 몰아 열에 적힌 시각을 그대로 돌려준다.** 판정은 하지 않는다 — 판정은 검사 셋이 한다
// (`verify:action-time` · `verify:layer-time-agree` · `verify:action-replay-generated`).
//
// 보관 113판에서 갈린 세 모양을 하나씩 몬다. 셋 다 실제 기록 길(`robotCommands.ts` · `robotBridge.ts` ·
// `scenario.ts`)을 지난다 — 시각을 손으로 넣은 열을 접는 검사는 **읽기**만 시험해서 이 결함을 못 봤다.
//
//   door  문 찾기 편 · 「임무 시작」을 누름 · 로봇이 축을 민다 (`pi7Run` — 이제 시작을 누르고 앱과 같은 시계로 답한다)
//   local 장치 두 대 편 · 시작 없이 진행기가 축을 민다 · 로봇은 붙어 있다 — 보관 13판이 전부 0초였던 모양
//   gen   정량 명령(생성 임무) · `durationSec` 0 — 보관 11판이 전부 0초였던 모양
//
// **한 프로세스에 한 번만 부른다.** 판 상태가 모듈 전역이라 두 번 부르면 앞 판이 남는다. 그래서 검사는
// 이 파일을 자식 프로세스로 띄우고(`actionTimeRun.mjs`), 대조군은 `src/` 를 통째로 복사한 트리를 `root`
// 로 준다 — `scenario.ts` 는 모두가 상대 경로로 부르므로 그 파일 하나만 바꾼 사본은 아무도 안 쓴다.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { pi7Kit } from './pi7Run.mjs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ACTION = new Set(['commanded', 'answered', 'expired', 'adjusted']);

/** 기록 열의 사건을 검사가 읽을 모양으로. 대역(seq)으로 층을 가른다 — `trace.ts` 의 규칙 그대로. */
function layered(trace, events) {
  return events.map((e) => ({
    seq: Number(e.seq),
    layer: ACTION.has(e.kind) ? 'action'
      : Number(e.seq) >= trace.HUMAN_SEQ_BASE && Number(e.seq) < trace.ACTION_SEQ_BASE ? 'human' : 'task',
    kind: e.kind, nodeId: e.nodeId, status: e.status ?? null, atSec: Number(e.atSec),
    // 액션 층 사건은 `nodeId` 가 명령 id 이고 태스크는 payload 에 있다(`actionTrace.ts`).
    commandId: ACTION.has(e.kind) ? e.nodeId : null,
    action: e.payload?.action ?? null,
    taskId: ACTION.has(e.kind) ? e.payload?.taskId ?? null : e.nodeId,
  }));
}

/** 명령마다 늦게 답하는 가짜 로봇 — 수락 `acceptMs` 뒤, 종료 `doneMs` 뒤. 앱의 귀처럼 `elapsedSec()` 를 단다. */
function slowRobot(prefix, onAnswer, { acceptMs = 30, doneMs = 70 } = {}) {
  const listeners = new Set();
  const sent = [];
  const emit = (message) => { for (const cb of [...listeners]) cb(message); onAnswer(message); };
  return {
    sent,
    address: () => `ws://${prefix}.probe:9001`,
    getStatus: () => ({ state: 'open' }),
    send(action, parameters) {
      const commandId = `${prefix}-${String(sent.length + 1).padStart(4, '0')}`;
      sent.push({ action, parameters: { ...(parameters ?? {}) }, commandId });
      setTimeout(() => emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null }), acceptMs);
      setTimeout(() => emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: {}, code: null, message: null }), doneMs);
      return { sent: true, commandId };
    },
    onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
  };
}

export async function probe(root, which) {
  const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
  const scenario = await load('src', 'data', 'scenario.ts');
  const session = await load('src', 'physical', 'robotSession.ts');
  const trace = await load('src', 'data', 'trace.ts');
  const commands = await load('src', 'physical', 'robotCommands.ts');
  const { receiveUplink } = await load('src', 'physical', 'robotBridge.ts');
  const column = () => scenario.traceFor(scenario.currentMission());

  if (which === 'door') {
    const kit = await pi7Kit(root);
    const run = await kit.drive(commands, 'door', { started: true });
    // 도구가 정말 시작을 눌렀는가 — 안 눌렀으면 이 판은 결함을 재현하는 판이 된다(261025 전의 `pi7Run`).
    const started = session.robotSession().startedAtMs !== null;
    return { durationSec: scenario.currentMission().durationSec, started, events: layered(trace, run.added) };
  }

  if (which === 'local') {
    // 장치 두 대 편. 관문을 안 열어 「임무 시작」이 서지 않는다 — 명령 시계가 `null` 이다.
    const MISSION = 'MSN-260929-02';
    session.resetRobotSession();
    session.setConnection({ state: 'open' });
    scenario.previewMission(MISSION);
    // 보관 13판의 세션 그대로 — 승인은 됐고(`taskRunner` 가 건다) 시작은 끝내 안 섰다.
    session.markApproved();
    const before = new Set(column().map((e) => e.seq));
    // 진행기가 축을 민 자리. **축 끝(52초)보다 뒤**에 둔다 — 화면이 모는 판도 로봇이 늦으면 축을 넘는다.
    const HEAD = 60;
    scenario.advanceRobotHead(MISSION, HEAD);
    const robot = slowRobot('local', (m) => receiveUplink(m, MISSION, session.elapsedSec()));
    // 태스크가 달린 명령 하나 — 그 응답은 `robotBridge.ts` 가 적는다(보관 판의 `T-E3 turn` 과 같은 길).
    const walked = await commands.issueSteps(robot, [{ taskId: 'T-E3', action: 'turn', parameters: { deg: 30 } }]);
    await sleep(120);
    // 같은 순간의 두 기록 — 사람이 누른 일시정지(사람 층)와 장비에 나간 일시정지(액션 층).
    scenario.recordHuman('mission_paused', MISSION, { from: 'probe' });
    await commands.pauseMission(robot);
    await sleep(120);
    const added = column().filter((e) => !before.has(e.seq));
    return { durationSec: scenario.currentMission().durationSec, head: HEAD, started: session.robotSession().started, walked: walked.sent === true, events: layered(trace, added) };
  }

  if (which === 'gen') {
    // 정량 명령 — `activateGenerated` 로 열리고 `durationSec` 이 0이다. 시작을 누르고 걸음을 낸다.
    const { stepMissionView, parseStepScript } = await load('src', 'physical', 'stepScript.ts');
    const sentence = 'Go1이 1m 앞으로 전진해';
    session.resetRobotSession();
    session.setConnection({ state: 'open' });
    scenario.proposeSteps(stepMissionView(sentence, parseStepScript(sentence), 'MSN-Q-probe'), sentence);
    scenario.acceptProposal('local');
    session.markStarted();
    const before = new Set(column().map((e) => e.seq));
    await sleep(150);   // 시작 뒤 한참 있다 나간 명령 — 0초가 아니어야 한다
    const robot = slowRobot('gen', (m) => receiveUplink(m, 'MSN-Q-probe', session.elapsedSec()), { acceptMs: 60, doneMs: 160 });
    await commands.issueStepMission(robot, scenario.currentMission().params ?? null);
    await sleep(260);
    const added = column().filter((e) => !before.has(e.seq));
    // 접기 — 화면이 명령 표를 그릴 때 쓰는 그 함수를 머리를 옮겨 가며 부른다.
    const events = layered(trace, added);
    const marks = [0, ...new Set(events.filter((e) => e.layer === 'action').map((e) => e.atSec))].sort((a, b) => a - b);
    const folds = [];
    for (const at of [...marks, ...marks.map((m) => m + 0.0005)]) {
      const folded = scenario.actionsAt(at);
      folds.push({ at, commands: folded.length, lines: folded.reduce((n, a) => n + a.lines.length, 0), statuses: folded.map((a) => a.status) });
    }
    folds.sort((a, b) => a.at - b.at);
    return { durationSec: scenario.currentMission().durationSec, started: session.robotSession().started, events, folds };
  }
  if (which === 'door-long') {
    // **축 끝(48초)을 넘는 문 찾기 판** — 회귀 기준 ④를 보는 판이다. 시험이 몇 ms 에 끝나면 축 끝 자름이
    // 영영 안 걸린다(그것이 108종이 못 본 이유 둘째). 그래서 이 프로세스 안에서만 `Date.now` 를 가상 시계로
    // 바꾸고, 시각을 §5-1 의 완주 판(`260921/114930`)에 맞춘다 — 촬영 5초 시작 · 59초 끝 · 이동 65.7초.
    const { readFileSync } = await import('node:fs');
    const store = await load('src', 'detect', 'store.ts');
    const PATH = JSON.parse(readFileSync(join(root, '..', 'door_example', 'test', 'door', 'evidence.json'), 'utf8'));
    const MISSION = 'MSN-260909-01';
    const base = Date.now();
    let virtualSec = 0;
    Date.now = () => base + Math.round(virtualSec * 1000);
    // 명령마다 걸리는 가상 초 — 수락은 바로, 종료는 이만큼 뒤.
    const LASTS = { scan_mission: 54.2, scan_continue: 0.1, turn: 2.0, move_forward: 5.8, abort: 0.2 };
    const listeners = new Set();
    const robot = {
      sent: [],
      address: () => 'ws://long.probe:9001',
      getStatus: () => ({ state: 'open' }),
      onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
      send(action, parameters) {
        const commandId = `long-${String(robot.sent.length + 1).padStart(4, '0')}`;
        robot.sent.push({ action, parameters: { ...(parameters ?? {}) }, commandId });
        const emit = (message) => { for (const cb of [...listeners]) cb(message); receiveUplink(message, MISSION, session.elapsedSec()); };
        setTimeout(() => {
          emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null });
          setTimeout(() => {
            virtualSec += LASTS[action] ?? 0.5;
            emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: {}, code: null, message: null });
          }, 5);
        }, 5);
        return { sent: true, commandId };
      },
    };
    session.resetRobotSession();
    session.setConnection({ state: 'open' });
    scenario.previewMission(MISSION);
    session.markApproved();
    session.markStarted();
    store.resetDetect();
    store.setTestMode(false);
    store.receivePath(PATH);
    const before = new Set(column().map((e) => e.seq));
    virtualSec = 5.0;
    await commands.issueScan(robot, { viewpoint_count: 8 });
    await sleep(40);
    virtualSec = 65.7;
    await commands.issueApproach(robot, null);
    await sleep(80);
    const added = column().filter((e) => !before.has(e.seq));
    // §5-1 의 머리들 — 그 표를 이 모양의 판으로 다시 낸다(⑤ · 60초 줄).
    const table = [];
    for (const at of [5, 10, 20, 30, 45, 50, 60, 66, 70, 75]) {
      const folded = scenario.actionsAt(at);
      table.push({ at, commands: folded.length, lines: folded.reduce((n, x) => n + x.lines.length, 0), per: folded.map((x) => `${x.action} ${x.status} ${x.lines.length}`) });
    }
    return { durationSec: scenario.currentMission().durationSec, events: layered(trace, added), sent: robot.sent.map((s) => s.action), table };
  }
  if (which === 'gen-long') {
    // **§5-1 의 표를 생성 임무로** (지시서 3-2). 정량 명령 세 걸음을 가상 시계로 몰고, 화면이 명령 표를 그릴 때
    // 쓰는 `actionsAt()` 을 정해 둔 머리마다 부른다. 판정은 안 한다 — 표를 만드는 판이다.
    const { stepMissionView, parseStepScript } = await load('src', 'physical', 'stepScript.ts');
    const sentence = '오른쪽 90도 회전 후 1m 전진 후 왼쪽 90도 회전';
    const MISSION = 'MSN-Q-table';
    const base = Date.now();
    let virtualSec = 0;
    Date.now = () => base + Math.round(virtualSec * 1000);
    const LASTS = { turn: 4.0, move_forward: 6.0 };
    const listeners = new Set();
    const robot = {
      sent: [],
      address: () => 'ws://table.probe:9001',
      getStatus: () => ({ state: 'open' }),
      onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
      send(action, parameters) {
        const commandId = `table-${String(robot.sent.length + 1).padStart(4, '0')}`;
        robot.sent.push({ action, parameters: { ...(parameters ?? {}) }, commandId });
        const emit = (message) => { for (const cb of [...listeners]) cb(message); receiveUplink(message, MISSION, session.elapsedSec()); };
        setTimeout(() => {
          virtualSec += 0.5;   // 수락까지 반 초
          emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null });
          setTimeout(() => {
            virtualSec += LASTS[action] ?? 1;
            emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: {}, code: null, message: null });
          }, 5);
        }, 5);
        return { sent: true, commandId };
      },
    };
    session.resetRobotSession();
    session.setConnection({ state: 'open' });
    scenario.proposeSteps(stepMissionView(sentence, parseStepScript(sentence), MISSION), sentence);
    scenario.acceptProposal('local');
    session.markStarted();
    const before = new Set(column().map((e) => e.seq));
    virtualSec = 3.0;   // 시작을 누르고 3초 뒤에 걸음이 나간다
    await commands.issueStepMission(robot, scenario.currentMission().params ?? null);
    await sleep(120);
    const added = column().filter((e) => !before.has(e.seq));
    const table = [];
    for (const at of [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20]) {
      const folded = scenario.actionsAt(at);
      table.push({ at, commands: folded.length, lines: folded.reduce((n, a) => n + a.lines.length, 0), per: folded.map((a) => `${a.action} ${a.status} ${a.lines.length}`) });
    }
    return { durationSec: scenario.currentMission().durationSec, sent: robot.sent.map((s) => s.action), events: layered(trace, added), table };
  }
  throw new Error(`모르는 판: ${which}`);
}
