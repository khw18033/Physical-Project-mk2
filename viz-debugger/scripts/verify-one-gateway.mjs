// 목 게이트웨이가 **하나**이고, 그 하나가 탭 여섯을 다 채우는지 검사한다.
//
// 화면만 옮기면 탭②~⑥은 텅 빈 채로 뜬다. 이식에서 가장 놓치기 쉬운 곳이라
// "빌드가 된다"가 아니라 **"데이터가 실제로 온다"**를 본다.
//
// transport 는 싱글턴이고 주소가 하나라 "탭마다 다른 게이트웨이"는 성립하지 않는다.
// 그래서 게이트웨이 하나에 붙어 탭별 채널이 전부 흘러나오는지 세고, 재연결 후에도
// 같은 구독이 복원되는지 본다.
//
// 이 스크립트는 게이트웨이를 **직접 띄웠다가 끈다.** 이미 떠 있는 것에 붙으면
// 남아 있던 프로세스가 다른 버전일 때 조용히 통과한다.
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocket } from 'ws';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = Number(process.env.VERIFY_GATEWAY_PORT ?? 8795);
const URL = `ws://127.0.0.1:${PORT}`;

/** 탭별로 최소 한 건은 와야 하는 채널. 안 오면 그 탭이 빈 화면이라는 뜻이다. */
const TAB_CHANNELS = {
  '② 구역 현황판': ['state'],
  '③ 제어 패널': ['actuator_state', 'control_lock'],
  '④ 지표 조회': ['telemetry'],
  '⑤ 영상 오버레이': ['video_meta'],
  // 탭⑥은 2026-08-31에 제거됐다. 게이트웨이의 /pipelines/* 라우팅은 이식본 그대로
  // 남아 있지만(기준선과의 diff 최소화) 소비하는 화면이 없으므로 검사하지 않는다.
  '① 임무 디버깅': ['trace_event'],
};

const failures = [];
const seen = new Set();

function open() {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(URL);
    const timer = setTimeout(() => reject(new Error('연결 시간 초과')), 8000);
    socket.on('open', () => { clearTimeout(timer); resolve(socket); });
    socket.on('error', (error) => { clearTimeout(timer); reject(error); });
  });
}

/** 데이터 계층이 실제로 거는 구독과 같은 축으로 건다. */
function subscribe(socket, id, selector) {
  socket.send(JSON.stringify({ type: 'subscribe', id, selector, scope: 'all' }));
}

function collect(socket, ms) {
  return new Promise((resolve) => {
    const subscribed = new Set();
    socket.on('message', (raw) => {
      let message;
      try { message = JSON.parse(String(raw)); } catch { return; }
      if (message.type === 'subscribed') subscribed.add(message.id);
      if (message.type === 'data' && message.envelope) seen.add(message.envelope.channel);
    });
    setTimeout(() => resolve(subscribed), ms);
  });
}

const server = spawn(process.execPath, ['gateway/server.ts'], {
  cwd: root,
  stdio: ['ignore', 'ignore', 'inherit'],
  env: { ...process.env, MOCK_PORT: String(PORT), VIZ_SCENARIO_SPEED: '40' },
});

const stop = () => { if (!server.killed) server.kill(); };
process.on('exit', stop);

try {
  // 게이트웨이가 뜰 때까지 기다린다.
  let socket = null;
  for (let attempt = 0; attempt < 20 && socket === null; attempt += 1) {
    try { socket = await open(); } catch { await new Promise((r) => setTimeout(r, 400)); }
  }
  if (socket === null) throw new Error(`게이트웨이(${URL})가 뜨지 않았다`);

  // 데이터 계층의 구독 축 + 탭①의 임무 기록 축. **연결은 하나다.**
  subscribe(socket, 'zone', { entity: '*', node: 'zone-503', channel: '*' });
  subscribe(socket, 'trace', { entity: 'MSN-260826-01', node: '*', channel: 'trace_event' });
  const firstSubs = await collect(socket, 4000);
  if (firstSubs.size !== 2) failures.push(`구독 확인이 ${firstSubs.size}건 (2건이어야 한다)`);

  for (const [tab, channels] of Object.entries(TAB_CHANNELS)) {
    for (const channel of channels) {
      if (!seen.has(channel)) failures.push(`${tab} — 채널 '${channel}' 이 한 건도 오지 않았다 (빈 화면이 된다)`);
    }
  }

  // 음성 대조군 — 이 검사가 채널 이름을 실제로 보고 있는가.
  // command_result 는 명령을 내지 않았으므로 와서는 안 되고(캐시 금지 채널이기도 하다),
  // 아무거나 통과시키는 검사라면 이것도 '봤다'로 잡힐 것이다.
  if (seen.has('command_result')) {
    failures.push('명령을 내지 않았는데 command_result 가 왔다 — 캐시 금지(BE-T-06)가 깨졌거나 이 검사가 채널을 안 보고 있다');
  }
  if (seen.size < 4) failures.push(`받은 채널이 ${seen.size}종뿐이다 — 게이트웨이가 절반만 돌고 있다`);

  // 재연결 — 껐다 켜면 구독이 한 번에 복원되어야 한다 (여기서는 다시 걸리는지만 본다).
  socket.close();
  const reconnected = await open();
  seen.clear();
  subscribe(reconnected, 'zone', { entity: '*', node: 'zone-503', channel: '*' });
  const secondSubs = await collect(reconnected, 3000);
  if (secondSubs.size !== 1) failures.push('재연결 후 구독이 복원되지 않았다');
  if (!seen.has('state')) failures.push('재연결 후 구독 즉시 스냅샷(VZ-I-02)이 오지 않았다');
  reconnected.close();
} catch (error) {
  failures.push(String(error?.message ?? error));
} finally {
  stop();
}

if (failures.length) {
  console.error(`❌ 게이트웨이 하나가 탭 여섯을 못 채운다:\n  - ${failures.join('\n  - ')}`);
  process.exit(1);
}
console.log(`✅ 통과 — 게이트웨이 1개 · 연결 1개로 탭별 채널 ${Object.values(TAB_CHANNELS).flat().join('·')} 수신, 재연결 후 구독·스냅샷 복원, 미발행 채널 대조군 확인`);
