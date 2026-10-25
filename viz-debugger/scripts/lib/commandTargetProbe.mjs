// scripts/lib/commandTargetProbe.mjs (261026 신설 — 대본 사건과 무응답 2부 · 명령 대상)
//
// **한 브로커에 Go1 과 수위 센서가 같이 산다** — pi7 그대로다. 그 브로커에서 명령이 어디로 나가고 누구의 답을 받는지를
// 몰아 보고 그대로 돌려준다. 판정은 `verify:command-target` 이 한다. 한 프로세스에 한 번.
//
// 가짜 Go1(`fake:go1`)에 붙은 실제 `PhysicalClient` 를 쓴다 — 발행 · 응답 디코딩 · 짝짓기는 실물과 같은 코드다.
// 센서는 장비 보고(`noteDeviceReport`)로 같은 주소에 세운다. 다른 장비의 답은 가짜 브로커에 바이트로 흘린다.
//
//   node scripts/lib/commandTargetProbe.mjs <root>   → stdout 에 JSON 한 줄
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function probe(root) {
  const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
  const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
  const identity = await load('src', 'physical', 'deviceIdentity.ts');
  const { physical } = await load('src', 'physical', 'protocol.js');
  const scenario = await load('src', 'data', 'scenario.ts');
  const session = await load('src', 'physical', 'robotSession.ts');
  const commands = await load('src', 'physical', 'robotCommands.ts');
  const encode = (body) => physical.PhysicalCommandEnvelope.encode(physical.PhysicalCommandEnvelope.create(body)).finish();
  const URL = 'fake:go1';

  const pc = new PhysicalClient(URL);
  await pc.connect(2000);
  for (let i = 0; i < 40 && identity.deviceIdentityFor(URL) === null; i += 1) await sleep(50);
  const broker = pc.client;
  const published = [];
  const publish = broker.publish.bind(broker);
  broker.publish = (topic, payload, opts) => { published.push(topic); publish(topic, payload, opts); };
  const heard = [];
  pc.onMessage((m) => heard.push(`${m.commandId}:${m.kind}:${m.accepted ?? ''}`));
  // pi7 처럼 수위 센서가 같은 브로커에 산다.
  identity.noteDeviceReport('wl-001', 'sensor', { status: 'online', registration: { entity_id: 'wl-001', entity_type: 'sensor' } }, URL);
  const go1 = identity.deviceIdentityFor(URL)?.deviceId ?? null;

  // ③ 기록에 받은 장비가 적히는가 — 태스크 명령 하나를 실제 길로 낸다.
  scenario.previewMission('MSN-260909-01');
  session.setConnection({ state: 'open' });
  session.markApproved();
  const before = new Set(scenario.traceFor(scenario.currentMission()).map((e) => e.seq));
  await commands.issueSteps(pc, [{ taskId: 'T-B2', action: 'turn', parameters: { deg: 30 } }]);
  const commanded = scenario.traceFor(scenario.currentMission()).filter((e) => !before.has(e.seq) && e.kind === 'commanded');

  // ② 둘 다 살아 있을 때 abort — 센서가 같은 id 로 거절해도 그 답은 받지 않는다.
  published.length = 0;
  const alive = pc.send('abort', { reason: 1 });
  broker.deliver('terminal/wl-001/uplink', encode({ acceptance: { commandId: alive.commandId, accepted: false, rejection: { code: 'UNIMPLEMENTED', message: 'action not supported' } } }));
  await sleep(400);   // 가짜 Go1 이 제 답을 내는 시간
  const aliveTopics = [...published];
  const heardAlive = heard.filter((h) => h.startsWith(alive.commandId + ':'));

  // ① Go1 이 종료 알림으로 꺼짐 — 센서만 산다. abort 는 안 나가야 하고, ping 만 센서로 나갈 수 있다.
  identity.noteDeviceReport(go1, 'robot', { status: 'offline' }, URL);
  published.length = 0;
  const off = pc.send('abort', { reason: 1 });
  const offTopics = [...published];
  published.length = 0;
  const ping = pc.send('ping', {});
  const pingTopics = [...published];

  pc.disconnect?.();
  return {
    go1,
    record: commanded.map((e) => ({ action: e.payload?.action, device: e.payload?.device ?? null })),
    alive: { sent: alive.sent, topics: aliveTopics, heard: heardAlive },
    offline: { sent: off.sent, reason: off.reason ?? null, topics: offTopics },
    ping: { sent: ping.sent, topics: pingTopics },
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const [root] = process.argv.slice(2);
  process.stdout.write(`${JSON.stringify(await probe(root))}\n`);
  process.exit(0);
}
