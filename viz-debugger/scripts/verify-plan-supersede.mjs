// verify:plan-supersede (261123 신설 — AI 생성 임무 실행기 실측)
//
// **AI 결과를 고르면 같은 발화의 대본 계획이 닫히는가.**
//
// 실측(261123): 정답셋 문장(대본 MSN-260831-01 에 맞는다)으로 AI 결과를 골라 승인했더니, 게이트웨이에 남은 대본 계획이
// 「임무 승인」 창에 떴고 거기서 승인하면 대본이 AI 임무를 덮어썼다. 고친 자리는 `src/shell/missionBridge.ts` 다.
//
// 게이트웨이를 실제로 띄우고, 화면의 다리(`startMissionBridge`)를 Node 에서 그대로 붙인다(`verify:gateway-wire` 와 같은 방식).
//   1. 대본에 맞는 발화 → 대본 제안이 선다 → AI 결과를 고른다 → 게이트웨이의 그 계획이 rejected · 화면 제안은 AI 그대로
//   2. AI 를 고른 뒤 같은 발화의 대본 계획이 늦게 온다 → 받지 않고 rejected · 화면 제안은 AI 그대로
//   3. 대조군 — 새 발화를 내면(`noteNewUtterance`) 대본 제안이 다시 선다
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const load = (...parts) => import(pathToFileURL(join(root, ...parts)).href);
const { WebSocket } = createRequire(pathToFileURL(join(root, 'package.json')).href)('ws');
const PORT = Number(process.env.VERIFY_SUPERSEDE_PORT ?? 8896);
const UTTERANCE = '503호에서 복도에 있는 엘리베이터 앞까지 이동해줘';
const failures = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const server = spawn(process.execPath, ['gateway/server.ts'], {
  cwd: root, stdio: ['ignore', 'ignore', 'inherit'],
  env: { ...process.env, MOCK_PORT: String(PORT), VIZ_SCENARIO_SPEED: '40' },
});
const stop = () => { if (!server.killed) server.kill(); };
process.on('exit', stop);

/** 봉투 안 어디에 있든 plan 채널의 계획을 꺼낸다. */
function planOf(message) {
  const envelope = message?.envelope ?? message;
  if (envelope?.channel !== 'plan') return null;
  const plan = envelope.payload;
  return plan?.plan_id ? plan : null;
}

async function main() {
  for (let i = 0; i < 60; i += 1) {
    try { if ((await fetch(`http://127.0.0.1:${PORT}/registry`)).ok) break; } catch { /* 아직 */ }
    await sleep(250);
  }

  // 화면 쪽 — 연결 주소를 이 게이트웨이로 두고 다리를 붙인다.
  const { saveConnections, connectionKey } = await load('src', 'shared', 'connections.ts');
  saveConnections({
    [connectionKey('gateway', 'ws')]: `ws://127.0.0.1:${PORT}`,
    [connectionKey('gateway', 'http')]: `http://127.0.0.1:${PORT}`,
  });
  const bridge = await load('src', 'shell', 'missionBridge.ts');
  const { noteHumanAction } = await load('src', 'shared', 'humanAction.ts');
  const store = await load('src', 'data', 'scenario.ts');
  const { viewFromGenerated, provenanceOf } = await load('src', 'generate', 'proposal.ts');
  const stopBridge = bridge.startMissionBridge();

  // 관찰자 — 게이트웨이가 낸 계획의 결정을 본다.
  const decisions = new Map();
  const ws = new WebSocket(`ws://127.0.0.1:${PORT}?lang=ko`);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('게이트웨이에 못 붙었다')), 10000);
    ws.on('open', () => { clearTimeout(timer); resolve(); });
    ws.on('error', (error) => { clearTimeout(timer); reject(error); });
  });
  ws.on('message', (raw) => {
    let message; try { message = JSON.parse(String(raw)); } catch { return; }
    const plan = planOf(message);
    if (plan !== null) decisions.set(plan.plan_id, plan.decision);
  });
  ws.send(JSON.stringify({ type: 'subscribe', id: 'all', selector: { entity: '*', node: '*', channel: '*' }, scope: 'all' }));
  await sleep(1500);

  let n = 0;
  const utter = () => {
    n += 1;
    ws.send(JSON.stringify({
      type: 'command',
      command: { client_request_id: `supersede-${n}`, action: 'mission_from_utterance', entity: 'MSN-260831-01', node: 'zone-503', params: { text: UTTERANCE, source: 'manual_text' } },
    }));
  };
  const newestPlan = () => [...decisions.keys()].at(-1) ?? null;
  const aiView = (id) => viewFromGenerated({
    mission_id: id, utterance: { audio_ref: null, text: UTTERANCE, engine: 'manual_text', confidence: 1 },
    milestones: [{ milestone_id: 'MS-A', title: '이동', order: 0, status: 'pending', assigned_targets: ['robot-01'], tasks: [] }],
  }, '검사용 AI 임무');
  const provenance = provenanceOf({
    mission: null, engine: 'llama.cpp', model: 'test', grammar: null, schema_checked: true, schema_errors: [], elapsed_sec: 1,
    extra: { stub: false, prompt_digest: 'x', rules_applied: ['x'] },
  });

  // 1. 대본 제안 → AI 를 고른다 → 대본 계획이 닫힌다
  noteHumanAction();
  bridge.noteNewUtterance();
  utter();
  await sleep(2500);
  const first = newestPlan();
  if (first === null) failures.push('게이트웨이가 대본 계획을 안 냈다 — 이 검사의 전제가 깨졌다');
  if (store.getMissionState().proposal?.origin !== 'script') failures.push(`대본 계획이 왔는데 화면 제안이 대본이 아니다 (${store.getMissionState().proposal?.origin})`);
  store.proposeGenerated(aiView('MSN-GEN-SUPERSEDE-1'), provenance);
  bridge.chooseGeneratedOverScript();
  await sleep(2000);
  if (first !== null && decisions.get(first) !== 'rejected') failures.push(`AI 를 골랐는데 대본 계획(${first})이 '${decisions.get(first)}' 다 — rejected 여야 한다`);
  if (store.getMissionState().proposal?.origin !== 'ai') failures.push(`대본 계획을 닫은 거부가 돌아와 AI 제안을 지웠다 (${store.getMissionState().proposal?.origin ?? '없음'})`);

  // 2. 같은 발화의 대본 계획이 늦게 온다 → 받지 않는다
  utter();
  await sleep(2500);
  const late = newestPlan();
  if (late === first) failures.push('늦게 오는 대본 계획을 만들지 못했다 — 이 검사의 전제가 깨졌다');
  else if (decisions.get(late) !== 'rejected') failures.push(`AI 를 고른 뒤 온 대본 계획(${late})이 '${decisions.get(late)}' 다 — 받지 말고 닫아야 한다`);
  if (store.getMissionState().proposal?.origin !== 'ai') failures.push(`늦게 온 대본 계획이 AI 제안을 바꿨다 (${store.getMissionState().proposal?.origin ?? '없음'})`);

  // 3. 대조군 — 새 발화면 대본 제안이 다시 선다
  bridge.noteNewUtterance();
  utter();
  await sleep(2500);
  const fresh = newestPlan();
  if (decisions.get(fresh) !== 'pending') failures.push(`새 발화의 대본 계획(${fresh})이 '${decisions.get(fresh)}' 다 — 대조군: pending 이어야 한다`);
  if (store.getMissionState().proposal?.origin !== 'script') failures.push(`대조군: 새 발화인데 대본 제안이 안 섰다 (${store.getMissionState().proposal?.origin ?? '없음'})`);

  ws.close();
  stopBridge();
  stop();
}

await main().catch((error) => { failures.push(String(error?.stack ?? error)); stop(); });

if (failures.length > 0) {
  console.error(`❌ verify:plan-supersede — ${failures.length}건`);
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log('✅ verify:plan-supersede — AI 를 고르면 대본 계획이 rejected · 늦게 온 대본 계획도 닫힘 · AI 제안은 그대로 · 대조군(새 발화면 대본 제안) 검출');
process.exit(0);
