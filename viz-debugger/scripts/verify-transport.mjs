import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import WebSocket from 'ws';

globalThis.WebSocket = WebSocket;
const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const { WsTransport } = await import('../src/transport/WsTransport.ts');
let gateway;
const startGateway = () => new Promise((resolve, reject) => {
  gateway = spawn(process.execPath, ['gateway/server.mjs'], { cwd: root, stdio: ['ignore', 'pipe', 'inherit'] });
  gateway.stdout.once('data', resolve); gateway.once('error', reject);
});
const waitFor = (label, predicate, timeout = 20_000) => new Promise((resolve, reject) => {
  const started = Date.now(); const timer = setInterval(() => {
    if (predicate()) { clearInterval(timer); resolve(); }
    else if (Date.now() - started > timeout) { clearInterval(timer); reject(new Error(`${label} 시간 초과`)); }
  }, 50);
});

let openCount = 0; let received = 0; let lastState = 'closed';
const transport = new WsTransport({ url: 'ws://127.0.0.1:8790', httpBase: 'http://127.0.0.1:8790' });
transport.onStatus((status) => {
  console.log(`[transport] ${status.state} (attempt=${status.attempt})`);
  if (status.state === 'open' && lastState !== 'open') openCount += 1;
  lastState = status.state;
});
transport.subscribe({ entity: '*', node: '*', channel: '*' }, () => { received += 1; console.log(`[transport] data ${received}`); });
try {
  await startGateway(); transport.connect(); await waitFor('최초 연결·구독', () => openCount >= 1 && received >= 1);
  gateway.kill(); await new Promise((resolve) => gateway.once('exit', resolve));
  await waitFor('재연결 상태 진입', () => transport.getStatus().state === 'reconnecting');
  await startGateway(); await waitFor('재접속·구독 복원', () => openCount >= 2 && received >= 2);
  console.log('✅ connected → 재연결 → 기존 구독 자동 복원 확인');
} finally { transport.close(); gateway?.kill(); }
