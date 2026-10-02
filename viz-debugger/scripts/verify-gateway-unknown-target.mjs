// verify:gateway-unknown-target (260929 신설 — 게이트웨이가 죽은 날)
//
// 노드 상세의 「단독 재실행」 같은 버튼은 태스크 id(`T-E3`)를 명령 대상으로 보낸다. 게이트웨이는 그것을
// 거부해야 맞지만, 260929 에는 거부를 허브에 싣다가 「레지스트리에 없는 entity」로 던져 **게이트웨이가
// 통째로 내려갔다** — 개발 스택(dev-all)이 그것을 보고 화면 · STT · 생성까지 같이 내렸다.
//
// 보는 것: 모르는 대상으로 명령을 보내면 거부 ACK 가 오고, 게이트웨이는 **살아 있다**(다음 명령에도 답한다).
// 대조군: 레지스트리에 있는 대상의 없는 동작도 거부되고 살아 있다(전부터 되던 길).

import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import WebSocket from 'ws';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const PORT = Number(process.env.VERIFY_GATEWAY_PORT_UNKNOWN ?? 8797);
const failures = [];

const gateway = spawn(process.execPath, ['gateway/server.ts'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, MOCK_PORT: String(PORT) } });
let died = null;
gateway.once('exit', (code) => { died = code; });
await new Promise((resolve) => gateway.stdout.once('data', resolve));

const ws = new WebSocket(`ws://127.0.0.1:${PORT}`);
await new Promise((resolve, reject) => { ws.once('open', resolve); ws.once('error', reject); });
const acks = new Map();
ws.on('message', (raw) => {
  const msg = JSON.parse(String(raw));
  if (msg.type === 'command_ack') acks.set(msg.client_request_id, msg);
});
const send = (id, entity, action) => ws.send(JSON.stringify({ type: 'command', command: { client_request_id: id, entity, action, params: {} } }));
const waitAck = async (id) => {
  for (let i = 0; i < 40; i += 1) {
    if (acks.has(id) || died !== null) return acks.get(id) ?? null;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return null;
};

send('req-task', 'T-E3', 'single_action_run');
const taskAck = await waitAck('req-task');
await new Promise((resolve) => setTimeout(resolve, 300));
if (died !== null) failures.push(`태스크 id 를 대상으로 한 명령에 게이트웨이가 죽었다 (종료 코드 ${died})`);
else if (taskAck === null) failures.push('태스크 id 대상 명령에 ACK 가 안 왔다');
else if (taskAck.accepted !== false) failures.push('태스크 id 대상 명령이 받아들여졌다 — 거부여야 한다');

send('req-after', 'robot-01', 'no_such_action');
const afterAck = await waitAck('req-after');
if (died !== null || afterAck === null) failures.push('그 뒤의 명령에 게이트웨이가 답하지 않는다 — 죽었다');

ws.close();
gateway.kill();

if (failures.length) {
  console.error(`❌ verify:gateway-unknown-target\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 레지스트리에 없는 대상(T-E3)은 거부 ACK 로 끝나고 게이트웨이는 살아 있다 · 다음 명령에도 답한다');
process.exit(0);
