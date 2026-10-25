// verify:command-target (261026 신설 — 대본 사건과 무응답 2부)
//
// **명령은 명령 받을 장비에만 나가고, 그 장비의 답만 받으며, 기록은 받은 장비를 적는가.**
//
// pi7 브로커에는 Go1 과 수위 센서(`wl-001`)가 같이 산다. 무응답 실물 판에서 `robot-node` 를 끄자 Go1 이 종료 알림으로
// 꺼짐이 됐고, 발행 대상 규칙이 **센서로 물러서** 일시정지(`abort`)가 `terminal/wl-001/downlink` 로 나갔다. 센서가
// 거절했고, 앱은 `terminal/+/uplink` 의 답을 `command_id` 로만 짝지어 그것을 「로봇이 거절했다」로 기록했다
// (10/26 00:03:12 · 00:08:47 — pi7 `sensor-node` 저널). 기록에는 받은 장비가 없어 그 사실을 기록만으로 못 봤다.
//
// 보는 것 — 가짜 Go1 에 붙은 실제 `PhysicalClient` + 같은 주소의 센서(`lib/commandTargetProbe.mjs`).
//   ① Go1 이 꺼지고 센서만 남으면 `abort` 는 **안 나간다**(어디로도 발행 0)
//   ② `ping` 은 센서로 나갈 수 있다 — 연결 점검이고 센서 노드도 답한다
//   ③ 둘 다 살아 있을 때 `abort` 는 Go1 의 downlink 로 나가고, **센서가 같은 id 로 낸 거절은 안 받고** Go1 의 답은 받는다
//   ④ 명령 기록(`commanded`)에 **받은 장비**가 적힌다
//
// 대조군 넷 — `src/` 통째 복사 · LF 정규화 원본에서 한 줄(`lib/actionTimeRun.mjs` 의 `mutantTree`).
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mutantTree } from './lib/actionTimeRun.mjs';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const probeFile = join(vizRoot, 'scripts', 'lib', 'commandTargetProbe.mjs');
const drive = (root) => JSON.parse(execFileSync(process.execPath, [probeFile, root], { encoding: 'utf8', cwd: vizRoot, maxBuffer: 1 << 24 })
  .trim().split('\n').filter((l) => l.startsWith('{')).at(-1));

function judge(r) {
  const bad = [];
  if (r.go1 === null) return ['가짜 Go1 이 자기를 밝히지 않았다 — 판을 못 세웠다'];
  // ①
  if (r.offline.sent || r.offline.topics.length > 0) bad.push(`① Go1 이 꺼졌는데 abort 가 나갔다 — ${r.offline.topics.join(',') || '(sent=true)'}. 센서로 물러섰다`);
  // ②
  if (!r.ping.sent || r.ping.topics[0] !== 'terminal/wl-001/downlink') bad.push(`② 센서만 남았을 때 ping 이 센서로 안 나간다 — ${JSON.stringify(r.ping)}`);
  // ③
  if (r.alive.topics.length !== 1 || r.alive.topics[0] !== `terminal/${r.go1}/downlink`) bad.push(`③ 둘 다 살아 있을 때 abort 가 Go1 로 안 나갔다 — ${r.alive.topics.join(',')}`);
  if (r.alive.heard.some((h) => h.endsWith(':acceptance:false'))) bad.push('③ 센서가 같은 command_id 로 낸 거절을 Go1 의 답으로 받았다');
  if (!r.alive.heard.some((h) => h.endsWith(':acceptance:true'))) bad.push('③ Go1 의 수락을 못 받았다 — 답을 다 버린다');
  // ④
  if (r.record.length !== 1 || r.record[0].device !== r.go1) bad.push(`④ 명령 기록에 받은 장비가 없다 — ${JSON.stringify(r.record)}`);
  return bad;
}

const failures = [];
const real = judge(drive(vizRoot));
failures.push(...real);
if (real.length === 0) console.log('✅ 원본 — 꺼진 로봇 대신 센서로 안 보낸다 · ping 은 센서로 · 남의 답은 안 받는다 · 기록에 받은 장비');

const controls = [
  { name: '센서로 물러서는 사본(첫 판의 모양)', file: 'src/physical/deviceIdentity.ts', from: "  return pick(here.filter((c) => c.online !== false && c.kind !== 'sensor'));", to: '  return resolve(here);' },
  { name: 'ping 까지 막는 사본', file: 'src/physical/deviceIdentity.ts', from: '  if (action === PING_ACTION) return resolve(here);\n', to: '' },
  { name: '남의 답도 받는 사본', file: 'src/physical/PhysicalClient.ts', from: '        if (to !== undefined && to !== uplinkDevice(topic)) return;\n', to: '' },
  { name: '받은 장비를 안 적는 사본', file: 'src/physical/robotCommands.ts', from: 'device: client.targetOf?.(commandId) ?? null,', to: 'device: null,' },
];
const caught = [];
for (const c of controls) {
  const tree = mutantTree('.verify-cmdtarget-', c.file, c.from, c.to);
  if (tree === null) { failures.push(`대조군을 만들지 못했다: ${c.name} — 치환이 아무것도 안 바꿨다`); continue; }
  try {
    const hit = judge(drive(tree.root));
    if (hit.length > 0) caught.push(`${c.name} (${hit[0].slice(0, 55)})`);
    else failures.push(`대조군 실패: ${c.name} — 변조 사본이 잡히지 않았다`);
  } finally {
    tree.cleanup();
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:command-target — ${failures.length}건\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${caught.length}건 전부 검출 — ${caught.join(' · ')}`);
console.log('✅ verify:command-target — 명령은 명령 받을 장비에만 · 그 장비의 답만 · 기록에 받은 장비');
