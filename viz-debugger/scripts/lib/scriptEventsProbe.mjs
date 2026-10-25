// scripts/lib/scriptEventsProbe.mjs (261025 신설 — 대본 사건과 무응답 1부)
//
// **판 하나를 앱이 여는 길(`propose…` → `acceptProposal`)로 열고 기록 열을 그대로 돌려준다.** 판정은 안 한다 —
// `verify:script-events-live` 가 한다. 판 상태가 모듈 전역이라 **한 프로세스에 판 하나**다.
//
//   robot  문 찾기 편 · 로봇이 붙어 있다 → 타이머를 안 세운다(로봇이 모는 판). 보관 66판이 `created` 0개였던 모양
//   timer  문 찾기 편 · 로봇이 없다 → 타이머가 대본을 흘린다(`feedLocalTrace`). 기준이 되는 판
//   steps  정량 명령(생성 임무) — 대본 사건이 없어 태스크마다 지어 넣는다. 주체 human
//   ai     모델 제안(생성 임무) — 같은 것. 주체 ai
//
//   node scripts/lib/scriptEventsProbe.mjs <root> <robot|timer|steps|ai>   → stdout 에 JSON 한 줄
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function probe(root, which) {
  const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
  const scenario = await load('src', 'data', 'scenario.ts');
  const session = await load('src', 'physical', 'robotSession.ts');
  session.resetRobotSession();
  if (which === 'robot' || which === 'timer') {
    if (which === 'robot') session.setConnection({ state: 'open' });
    scenario.proposeMission({ origin: 'script', missionId: 'MSN-260909-01', title: '문', keywords: [], planId: null, world: 'registry' });
    scenario.acceptProposal('local');
    // 타이머 판은 대본을 흘릴 틈을 준다. 로봇 판은 머리를 아무도 안 민다 — 기다려도 같다.
    await sleep(which === 'timer' ? 400 : 50);
  } else {
    const { stepMissionView, parseStepScript } = await load('src', 'physical', 'stepScript.ts');
    const sentence = '오른쪽 90도 회전 후 1m 전진 후 왼쪽 90도 회전';
    const view = stepMissionView(sentence, parseStepScript(sentence), which === 'steps' ? 'MSN-Q-seed' : 'MSN-AI-seed');
    if (which === 'steps') scenario.proposeSteps(view, sentence);
    else scenario.proposeGenerated({ ...view, params: {} }, { producedBy: 'ai', engine: 'probe', model: 'probe', stub: true, promptDigest: null, promptChars: null, grammar: null, rules: [], overwritten: [], schemaErrors: [], elapsedSec: 0, shapeWarnings: [], examplesGiven: 0, placesGiven: false, equipmentGiven: false, nodeKindsGiven: false });
    scenario.acceptProposal('local');
    await sleep(20);
  }
  const view = scenario.currentMission();
  return {
    missionId: view.missionId,
    tasks: view.tasks.map((t) => t.id),
    scriptCreated: view.events.filter((e) => e.kind === 'created').map((e) => ({ seq: e.seq, nodeId: e.nodeId })),
    column: scenario.traceFor(view).map((e) => ({ seq: Number(e.seq), atSec: e.atSec, nodeId: e.nodeId, status: e.status, kind: e.kind, producedBy: e.producedBy })),
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [root, which] = process.argv.slice(2);
  process.stdout.write(`${JSON.stringify(await probe(root, which))}\n`);
  process.exit(0);
}
