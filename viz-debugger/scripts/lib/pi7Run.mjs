// scripts/lib/pi7Run.mjs (261022 신설 — 사람 층·액션 층 경계 §6)
//
// **문 찾기 편(pi7) 한 판을 실제 명령 길로 몬다.** `verify:human-layer-pure` 와
// `verify:no-command-dup` 가 같은 판을 본다 — 판을 두 벌 몰면 두 검사가 다른 것을 재게 된다.
//
// 길은 앱과 같다: 스캔(`T-A3`) → 스캔 이어 가기(`NO_NODE`) → 접근(회전·직진·도착 정지) →
// 일시정지 → 긴급정지. 가짜 로봇은 명령마다 수락과 종료를 **스스로** 답한다 — 앱이 듣는 두 길
// (`client.onMessage` · `receiveUplink`)으로 다 흘린다.
//
// `mod` 를 받는 이유는 대조군이다. 원본 대신 사본 `robotCommands.ts` 를 넣어 같은 판을 몬다.
//
// ## 시작을 누른다 · 시각은 앱과 같은 시계다 (261025 — 액션 층 시각)
//
// 전에는 승인(`markApproved`)만 하고 「임무 시작」(`markStarted`)을 안 눌렀고, 가짜 로봇의 응답을 **3초로 박아**
// 넣었다. 그래서 이 판의 명령은 전부 0초(시작 안 한 시계), 응답과 태스크 사건은 3초였다 — 액션 층 시각 결함이
// **이 도구 안에서 매번 재현되고 있었는데** 같은 명령의 층별 시각을 묻는 검사가 없어 통과했다.
//
// 지금은 앱과 같다. 응답은 `useRobotUplink` 처럼 `elapsedSec()` 를 달고 들어온다. 시작은 기본으로 누른다 —
// `started: false` 를 주면 **안 누른 판**(장치 두 대 편처럼 시계가 끝내 안 서는 판)을 몬다.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function pi7Kit(root) {
  const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
  const session = await load('src', 'physical', 'robotSession.ts');
  const scenario = await load('src', 'data', 'scenario.ts');
  const store = await load('src', 'detect', 'store.ts');
  const { receiveUplink } = await load('src', 'physical', 'robotBridge.ts');
  const trace = await load('src', 'data', 'trace.ts');
  const PATH = JSON.parse(readFileSync(join(root, '..', 'door_example', 'test', 'door', 'evidence.json'), 'utf8'));
  const MISSION = 'MSN-260909-01';
  const column = () => scenario.traceFor(scenario.currentMission());

  /** 명령마다 수락 → 종료를 스스로 답하는 가짜 로봇. */
  function selfAnsweringRobot(prefix) {
    const listeners = new Set();
    const sent = [];
    const emit = (message) => {
      for (const cb of [...listeners]) cb(message);
      // 앱의 귀(`useRobotUplink`)와 같은 시계다. 시작을 안 눌렀으면 0이다 — 그것도 앱과 같다.
      receiveUplink(message, scenario.currentMission().missionId, session.elapsedSec());
    };
    return {
      sent,
      getStatus: () => ({ state: 'open' }),
      send(action, parameters) {
        const commandId = `${prefix}-${String(sent.length + 1).padStart(4, '0')}`;
        sent.push({ action, parameters: { ...(parameters ?? {}) }, commandId });
        setTimeout(() => {
          emit({ kind: 'acceptance', commandId, accepted: true, code: null, message: null });
          setTimeout(() => emit({ kind: 'result', commandId, status: 'SUCCEEDED', result: {}, code: null, message: null }), 5);
        }, 5);
        return { sent: true, commandId };
      },
      onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
    };
  }

  /**
   * 한 판을 몬다. 돌려주는 것은 **이 판이 열에 더한 사건**과 로봇에 실제로 나간 명령이다.
   *
   * @param mod  `robotCommands.ts` 모듈 — 원본 또는 사본
   * @param opts `started` — 「임무 시작」을 누르는가(기본 참)
   */
  async function drive(mod, prefix, { started = true } = {}) {
    session.resetRobotSession();
    session.setConnection({ state: 'open' });
    scenario.previewMission(MISSION);
    session.markApproved();
    if (started) session.markStarted();
    store.resetDetect();
    store.setTestMode(false);
    store.receivePath(PATH);
    const before = new Set(column().map((e) => e.seq));
    const robot = selfAnsweringRobot(prefix);

    await mod.issueScan(robot, { viewpoint_count: 8 });
    await sleep(40);
    await mod.issueScanContinue(robot, 0, 500);
    await sleep(20);
    await mod.issueApproach(robot, null);
    await sleep(60);
    await mod.pauseMission(robot);
    await sleep(40);
    await mod.emergencyStop(robot);
    await sleep(40);

    const added = column().filter((e) => !before.has(e.seq));
    return { added, sent: robot.sent };
  }

  /** 사람 층 — `appendHuman` 이 매기는 대역. 대본의 액션(1.5M)부터는 남의 대역이다. */
  const isHumanLayer = (event) => Number(event.seq) >= trace.HUMAN_SEQ_BASE && Number(event.seq) < trace.ACTION_SEQ_BASE;

  return { drive, isHumanLayer, column, session, scenario, MISSION };
}
