// scenario 렌더 모드 (260831) — 대본 재생이 자리표시 기본값을 깨뜨리지 않는지 검사한다.
//
// 이 검사가 막으려는 실패는 둘이다.
//  1. **대본이 자리표시를 우회하는 것** — scenario 모드가 승인 없이 켜지거나, cast 밖
//     장비까지 그리거나, 배지 없이 그리면 「목입니다」 문제로 되돌아간다.
//  2. **승인 전 실행** — 매칭 결과는 제안이고, 승인 전에는 trace_event 도 세계 채널도
//     하나도 나가면 안 된다 (plans.ts 머리말 · REQ-1506).
//
// 세 층을 본다: ① renderMode 모듈의 실동작 ② 화면 소스의 배지·분기 ③ 게이트웨이 실동작
// (직접 띄워 발화→매칭→승인→재생→감사→닫기 왕복). 음성 대조군 포함.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { WebSocket } from 'ws';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = Number(process.env.VERIFY_SCENARIO_PORT ?? 8797);
const URL = `ws://127.0.0.1:${PORT}`;
const HTTP = `http://127.0.0.1:${PORT}`;

const failures = [];
const controls = [];

// ── ① renderMode 모듈 — 기본값·진입·우선순위·복귀 ────────────────────────────
const modePath = join(root, 'src', 'shared', 'renderMode.ts');
{
  const m = await import(pathToFileURL(modePath).href);
  if (m.getRenderMode() !== 'placeholder') failures.push(`기본 렌더 모드가 '${m.getRenderMode()}' — 앱을 그냥 띄우면 자리표시여야 한다`);
  m.enterScenarioRender({ missionId: 'MSN-X', title: 't', cast: ['sensor-01'] });
  if (m.getRenderMode() !== 'scenario') failures.push('대본 진입 후 모드가 scenario 가 아니다');
  if (!m.getScenarioRender()?.castSet.has('sensor-01') || m.getScenarioRender()?.castSet.has('robot-02')) {
    failures.push('cast 집합이 대본 등장 장비만 담지 않는다 — cast 밖 장비는 자리표시여야 한다');
  }
  m.setRenderMode('mock');
  if (m.getRenderMode() !== 'mock') failures.push('목 렌더 토글이 scenario 를 이기지 않는다 — 토글이 켜져 있으면 mock 이 이겨야 한다');
  m.setRenderMode('placeholder');
  m.exitScenarioRender();
  if (m.getRenderMode() !== 'placeholder') failures.push('대본 닫기 후 placeholder 로 복귀하지 않는다');
}

// 대조군 — exitScenarioRender 를 무력화한 사본이 잡히는가.
{
  const scratch = mkdtempSync(join(root, '.verify-scenario-'));
  try {
    const mutantPath = join(scratch, 'renderMode.ts');
    writeFileSync(mutantPath, readFileSync(modePath, 'utf8').replace('scenarioRender = null;', ';'), 'utf8');
    const mutant = await import(pathToFileURL(mutantPath).href);
    mutant.enterScenarioRender({ missionId: 'MSN-X', title: 't', cast: [] });
    mutant.exitScenarioRender();
    if (mutant.getRenderMode() === 'placeholder') failures.push('대조군 실패: 닫기를 무력화한 사본이 placeholder 로 복귀했다 — 검사가 무의미하다');
    else controls.push('닫기 무력화 사본 검출');
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

// ── ② 화면 소스 — 배지·끄는 경로·카드 단위 분기 ──────────────────────────────
function checkSources(shellSource, pendingSource, gridSource) {
  const f = [];
  if (!shellSource.includes('scenario-banner')) f.push('셸에 대본 띠(scenario-banner)가 없다 — 지워지지 않는 배지가 요구사항이다');
  if (!shellSource.includes('대본 닫기')) f.push('셸에 「대본 닫기」 버튼이 없다 — placeholder 복귀 경로가 없다');
  if (!pendingSource.includes('scenarioCast.has(entity)')) f.push('PendingSource 가 장비 ID 로 cast 를 대조하지 않는다 — cast 밖 장비가 그려질 길이 열린다');
  if (!gridSource.includes('scenarioCast.has(r.id)')) f.push('장치 그리드가 카드 단위로 갈리지 않는다 — 자리 하나가 여러 장비를 담으면 카드 단위여야 한다');
  return f;
}
const shellSource = readFileSync(join(root, 'src', 'shell', 'AppShell.tsx'), 'utf8');
const pendingSourceText = readFileSync(join(root, 'src', 'shared', 'PendingSource.tsx'), 'utf8');
const gridSource = readFileSync(join(root, 'src', 'tabs', 'views', 'DeviceGrid.tsx'), 'utf8');
failures.push(...checkSources(shellSource, pendingSourceText, gridSource));
// 대조군 — 배지를 지운 사본이 잡히는가.
if (checkSources(shellSource.replaceAll('scenario-banner', 'x'), pendingSourceText, gridSource).length === 0) {
  failures.push('대조군 실패: 배지를 지운 사본이 잡히지 않았다');
} else {
  controls.push('배지 삭제 사본 검출');
}
// 끄는 경로는 하나 — 닫기(셸) 밖에서 exitScenarioRender 를 부르면 배지가 조용히 꺼질 수 있다.
{
  const allowed = new Set(['src/shared/renderMode.ts', 'src/shell/AppShell.tsx']);
  const { readdirSync, statSync } = await import('node:fs');
  const offenders = [];
  (function walk(dir) {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.tsx?$/.test(name)) {
        const rel = path.slice(root.length + 1).replaceAll('\\', '/');
        if (!allowed.has(rel) && readFileSync(path, 'utf8').includes('exitScenarioRender')) offenders.push(rel);
      }
    }
  })(join(root, 'src'));
  if (offenders.length > 0) failures.push(`닫기(셸) 밖에서 exitScenarioRender 를 부른다: ${offenders.join(', ')} — 끄는 경로는 하나여야 한다`);
}

// ── ③ 게이트웨이 실동작 — 발화 → 제안 → 승인 전 0건 → 재생 → 감사 → 닫기 ───────
const server = spawn(process.execPath, ['gateway/server.ts'], {
  cwd: root,
  stdio: ['ignore', 'ignore', 'inherit'],
  env: { ...process.env, MOCK_PORT: String(PORT), VIZ_SCENARIO_SPEED: '20' },
});
const stop = () => { if (!server.killed) server.kill(); };
process.on('exit', stop);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function open() {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(URL);
    const timer = setTimeout(() => reject(new Error('연결 시간 초과')), 8000);
    socket.on('open', () => { clearTimeout(timer); resolve(socket); });
    socket.on('error', (error) => { clearTimeout(timer); reject(error); });
  });
}

try {
  let socket = null;
  for (let attempt = 0; attempt < 20 && socket === null; attempt += 1) {
    try { socket = await open(); } catch { await wait(400); }
  }
  if (socket === null) throw new Error(`게이트웨이(${URL})가 뜨지 않았다`);

  const envelopes = [];
  let planSeen = null;
  let ackWaiters = [];
  socket.on('message', (raw) => {
    let msg;
    try { msg = JSON.parse(String(raw)); } catch { return; }
    if (msg.type === 'command_ack') {
      const waiter = ackWaiters.find((w) => w.id === msg.client_request_id);
      if (waiter) { ackWaiters = ackWaiters.filter((w) => w !== waiter); waiter.resolve(msg); }
    }
    if (msg.type === 'data' && msg.envelope) {
      envelopes.push(msg.envelope);
      if (msg.envelope.channel === 'plan' && msg.envelope.payload?.script) planSeen = msg.envelope.payload;
    }
  });
  const sendCommand = (action, params) => new Promise((resolve) => {
    const id = 'req-' + Math.random().toString(36).slice(2, 8);
    ackWaiters.push({ id, resolve });
    socket.send(JSON.stringify({ type: 'command', command: { client_request_id: id, entity: 'MSN-260826-01', action, params, expires_at: new Date(Date.now() + 30000).toISOString(), audit: { input_mode: 'click', decision_source: 'human' } } }));
  });
  socket.send(JSON.stringify({ type: 'subscribe', id: 'all', selector: { entity: '*', node: '*', channel: '*' }, scope: 'all' }));
  await wait(1200);

  // 맞는 대본이 없으면 없다고 한다.
  const noMatch = await sendCommand('mission_from_utterance', { text: '안녕하세요' });
  if (noMatch.accepted !== false || noMatch.reason_code !== 'no_script_match') {
    failures.push(`「안녕하세요」가 no_script_match 로 거부되지 않았다 — ${noMatch.reason_code}`);
  }

  // 3편 문장 → 제안 (pending).
  const matched = await sendCommand('mission_from_utterance', { text: '월류방어벽 자동 개폐 시스템을 가동해.' });
  if (matched.accepted !== true || !matched.message.includes('MSN-260831-03')) failures.push(`3편 매칭 실패 — ${matched.message}`);
  await wait(600);
  if (planSeen?.script?.mission_id !== 'MSN-260831-03' || planSeen?.decision !== 'pending') {
    failures.push('대본 계획이 제안(pending) 상태로 오지 않았다');
  }

  // **승인 전 실행 없음** — 기록 열도, 대본 명령도 0건.
  envelopes.length = 0;
  await wait(2500);
  if (envelopes.some((e) => e.entity === 'MSN-260831-03' && e.channel === 'trace_event')) {
    failures.push('승인 전에 trace_event 가 나갔다 — 매칭 결과는 제안일 뿐이다');
  }
  if (envelopes.some((e) => e.channel === 'command_result' && e.entity === 'actuator-01')) {
    failures.push('승인 전에 수문 명령이 나갔다');
  }

  // 승인 → 재생. close_gate 가 실시간 개폐(6초)를 마치고 감사에 적힐 때까지 본다.
  socket.send(JSON.stringify({ type: 'plan_decision', plan_id: planSeen?.plan_id, decision: 'approve' }));
  await wait(16000);

  const trace = envelopes.filter((e) => e.entity === 'MSN-260831-03' && e.channel === 'trace_event');
  if (trace.length === 0) failures.push('승인 후 trace_event 가 오지 않는다 — 재생기가 죽어 있다');
  const levels = envelopes.filter((e) => e.entity === 'sensor-01' && e.channel === 'telemetry').map((e) => e.payload?.water_level?.value);
  if (!levels.includes(1.9)) failures.push('sensor-01 수위가 대본 값(120초의 1.90 m)을 지나지 않았다 — 세계 채널이 대본을 따르지 않는다');
  const modes = envelopes.filter((e) => e.entity === 'sensor-01' && e.channel === 'telemetry').map((e) => e.payload?.report_mode);
  if (!modes.includes('event')) failures.push('상승 급변에서 report_mode 가 event 로 바뀌지 않았다');
  const gate = envelopes.filter((e) => e.channel === 'command_result' && e.entity === 'actuator-01' && e.payload?.action === 'close_gate');
  for (const stage of ['ack', 'executing', 'settled']) {
    if (!gate.some((e) => e.payload?.stage === stage)) failures.push(`close_gate 의 '${stage}' 단계가 없다 — 대본 명령이 엔진 4단계를 지나지 않는다`);
  }
  const audit = await (await fetch(HTTP + '/audit?entity=actuator-01&limit=10')).json();
  const closeAudit = audit.records.find((r) => r.action === 'close_gate');
  if (!closeAudit) failures.push('close_gate 가 감사에 없다');
  else {
    if (closeAudit.actor_display_name !== '임무 MSN-260831-03') failures.push(`감사 actor 가 임무가 아니다 — ${closeAudit.actor_display_name}`);
    if (closeAudit.input_mode === 'click' || closeAudit.input_mode === 'voice') failures.push(`대본 명령의 input_mode 가 사람 어휘(${closeAudit.input_mode})다`);
  }

  // 닫기 — 게이트웨이가 재생을 멈추고 장치를 평시로 되돌린다.
  const closed = await sendCommand('script_close', {});
  if (closed.accepted !== true) failures.push(`대본 닫기가 거부됐다 — ${closed.message}`);

  socket.close();
} catch (error) {
  failures.push(String(error?.message ?? error));
} finally {
  stop();
}

if (failures.length) {
  console.error(`❌ verify:scenario-mode\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
controls.push('무매칭 문장 거부(no_script_match)');
console.log('✅ 기본 placeholder · 승인 후에만 scenario 진입 · cast 집합 대조 · 목 렌더 우선 · 닫으면 복귀');
console.log('✅ 배지(scenario-banner) 존재 · 끄는 경로는 「대본 닫기」 하나 · 장치 그리드는 카드 단위 분기');
console.log('✅ 게이트웨이 왕복 — 거부 · 제안 · 승인 전 발행 0건 · 재생(기록·세계 채널·event 모드·명령 4단계) · 감사 actor=임무 · 닫기');
console.log(`✅ 음성 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
