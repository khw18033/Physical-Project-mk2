import { WebSocketServer } from 'ws';

const port = Number(process.env.VIZ_GATEWAY_PORT ?? 8790);
const server = new WebSocketServer({ port, host: '127.0.0.1' });
server.on('connection', (socket) => {
  socket.send(JSON.stringify({ type: 'hello', server_time: new Date().toISOString(), stale_threshold_ms: 60_000, mock: true }));
  socket.on('message', (raw) => {
    let message;
    try { message = JSON.parse(String(raw)); } catch { return; }
    if (message.type !== 'subscribe') return;
    socket.send(JSON.stringify({ type: 'subscribed', id: message.id, snapshot_count: 0, mock: true }));
    socket.send(JSON.stringify({
      type: 'data', sub: message.id,
      envelope: { schema_version: '1.0', entity: 'mock-gateway', node: 'viz-debugger', channel: 'heartbeat', ts: new Date().toISOString(), seq: 1, scope: message.scope ?? 'all', payload: { mock: true } },
    }));
  });
});
console.log(`[viz-debugger mock] ws://127.0.0.1:${port} — 목 서버`);
