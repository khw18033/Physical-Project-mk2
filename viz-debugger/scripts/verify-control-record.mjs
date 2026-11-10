// verify:control-record (261110 신설 — 조작 기록)
//
// **가시화에서 한 조작이 임무와 상관없이 판으로 남는다.** 임무 기록은 승인된 임무가 있을 때만 판을 열어서, 임무 밖에서
// Go1 을 키보드로 몬 것 · 드론 비행 제어 탭에서 날린 것은 새로고침 한 번에 사라졌다.
//
// 보는 것 — 실제 길(`manualDispatch` · `issueFlightStart` · `issueSarStart` → `humanCommands` → `controlRecorder`)로 낸다.
//  ① 임무 밖 수동 제어 — 켬 → 명령 · 답 · 유지 신호 · 막힘 → 끔 이 `CTL-<장비>` 판 하나로 쓰인다 (`recordKind: 'control'`)
//  ② 유지 신호는 **구간 한 줄**로 묶인다 — 건별로 적지 않는다. 막힘도 이어진 것은 한 줄로 센다
//  ③ 켜고 끄기만 한 판은 **폴더를 안 만든다**
//  ④ 비행 dry-run — `FLT-<장비>` 판 · 시작 명령의 dry_run · 실행기 출력 원문이 붙고, 실행이 끝나면 닫힌다
//  ⑤ 비행 시작 거절 — 판이 「시작 거절」로 닫힌다
//  ⑥ 사람 명령(SAR) — 열린 판이 없으면 사람 명령 판이 서고, 60초 쉬면 닫힌다
//  ⑦ 저장 창구 규칙 — 폴더 이름이 `mission-records.mjs` 의 형식을 지난다
//
// 대조군 둘 — 유지 신호를 건별로 적은 기록 · 켜고 끄기만 한 판에 폴더를 만든 기록. 판정이 각각 잡아야 한다.
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (globalThis.localStorage === undefined) {
  const memory = new Map();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: (k) => (memory.has(k) ? memory.get(k) : null), setItem: (k, v) => memory.set(k, String(v)), removeItem: (k) => memory.delete(k) },
  });
}

const cr = await load('src', 'record', 'controlRecorder.ts');
const md = await load('src', 'physical', 'manualDispatch.ts');
const mc = await load('src', 'physical', 'manualControl.ts');
const feed = await load('src', 'physical', 'flightRunFeed.ts');
const flight = await load('src', 'physical', 'flightRunCommands.ts');
const flightPlan = await load('src', 'physical', 'flightPlan.ts');
const sar = await load('src', 'physical', 'sarCommands.ts');
const sarPlan = await load('src', 'sar', 'plan.ts');
const { noteCapability, resetDeviceIdentity } = await load('src', 'physical', 'deviceIdentity.ts');
const { TELEOP_ACTION, STOP_ACTION } = await load('src', 'physical', 'presets.ts');
const { getMissionState, NO_MISSION } = await load('src', 'data', 'scenario.ts');

const failures = [];
const controls = [];

let now = Date.parse('2026-11-10T03:00:00Z');
const files = new Map();
cr.setControlProbes({
  clock: () => now,
  store: async (date, run, file, body) => { files.set(`${date}/${run}/${file}`, JSON.parse(body)); },
});

/** 명령마다 답하는 가짜 장비. `accept` 가 거짓이면 거절한다. */
function device(prefix, accept = true, code = null) {
  const listeners = new Set();
  const sent = [];
  return {
    sent,
    address: () => `ws://${prefix}.test:9001`,
    getStatus: () => ({ state: 'open' }),
    onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
    send(action, parameters) {
      const commandId = `${prefix}-${String(sent.length + 1).padStart(4, '0')}`;
      sent.push({ action, parameters: { ...(parameters ?? {}) }, commandId });
      setTimeout(() => { for (const cb of [...listeners]) cb({ kind: 'acceptance', commandId, accepted: accept, code: accept ? null : code, message: null }); }, 2);
      return { sent: true, commandId };
    },
  };
}

const RUN_NAME = /^\d{6}_[A-Za-z0-9_.-]{1,80}$/;   // scripts/mission-records.mjs 의 RUN
const filesOf = (pattern) => [...files.keys()].filter((k) => pattern.test(k));
const read = (folder, file) => files.get(`${folder}/${file}`);

if (getMissionState().current.missionId !== NO_MISSION) failures.push('검사 전제: 임무가 없는 상태여야 한다');

// ── ①② 임무 밖 수동 제어 ────────────────────────────────────────────────────
cr.resetControlRecorder();
const go1 = device('go1');
let typing = false;
md.setManualProbes({ client: (id) => (id === 'go1-001' ? go1 : null), typing: () => typing, auto: () => false });
resetDeviceIdentity();
noteCapability('go1-001', ['ping', TELEOP_ACTION, STOP_ACTION], go1.address());
mc.resetManualControl();
md.resetManualDispatch();

mc.setManualEnabled('go1-001', true);
cr.syncManualSessions();
cr.controlTick();
if (files.size !== 0) failures.push(`켜기만 했는데 ${files.size}개 파일을 썼다 — 폴더는 무언가 일어난 뒤에야`);

md.manualKeyDown({ code: 'KeyW', repeat: false, modified: false });
await sleep(10);
for (let i = 0; i < 5; i += 1) { now += 200; md.keepaliveTick(); }
await sleep(10);
now += 300;
md.manualKeyUp('KeyW');
await sleep(10);
typing = true;
now += 100; md.manualKeyDown({ code: 'KeyW', repeat: false, modified: false });
now += 100; md.manualKeyDown({ code: 'KeyW', repeat: false, modified: false });
typing = false;
// 입력 중 막힘은 키를 아예 안 가로챈다(`manualKeyDown` 이 typing 이면 건너뜀) — 막힘으로 남는 것은 자동 제어 · 연결 없음이다.
md.setManualProbes({ auto: () => true });
now += 100; md.manualKeyDown({ code: 'KeyW', repeat: false, modified: false });
now += 100; md.manualKeyDown({ code: 'KeyW', repeat: false, modified: false });
md.setManualProbes({ auto: () => false });
now += 1000;
mc.setManualEnabled('go1-001', false);
cr.syncManualSessions();
cr.controlTick();
await cr.settleControlRecorder();

/** 판정 — 수동 판 하나. 대조군도 같은 함수를 돈다. */
function judgeManual(summary, progress) {
  const f = [];
  if (summary === undefined || progress === undefined) return ['수동 판의 mission.json · progress.json 이 없다'];
  if (summary.recordKind !== 'control' || summary.sessionKind !== 'manual') f.push(`판 종류가 ${summary.recordKind}/${summary.sessionKind} 다`);
  if (summary.closeReason !== 'manualOff') f.push(`닫힌 사유가 ${summary.closeReason} — 수동 제어를 끄면 manualOff`);
  if (summary.missions.length !== 0) f.push('임무 밖 조작인데 임무가 이어졌다');
  const commanded = progress.events.filter((e) => e.kind === 'commanded');
  if (commanded.length !== 2) f.push(`명령이 ${commanded.length}건 — 누름(전진) · 뗌(0) 두 건이어야 한다`);
  if (commanded[0]?.action !== TELEOP_ACTION || !(commanded[0]?.parameters.vx > 0)) f.push('첫 명령이 전진 teleop 이 아니다');
  if (commanded[1]?.parameters.vx !== 0) f.push('뗀 명령이 0 이 아니다');
  if (commanded.some((e) => e.missionId !== null)) f.push('임무 밖 명령에 임무 id 가 붙었다');
  const answered = progress.events.filter((e) => e.kind === 'answered');
  for (const c of commanded) if (!answered.some((a) => a.commandId === c.commandId && a.accepted === true)) f.push(`${c.commandId} 의 수락이 안 붙었다`);
  if (answered.some((a) => a.keepalive)) f.push('유지 신호의 수락까지 적었다 — 거절만 적는다');
  const keep = progress.events.filter((e) => e.kind === 'keepalive');
  if (keep.length !== 1) f.push(`유지 신호가 ${keep.length}줄 — 구간 한 줄이어야 한다`);
  else if (keep[0].count !== 5 || keep[0].untilMs - keep[0].atMs !== 800) f.push(`유지 신호 구간이 ${keep[0].count}회 · ${keep[0].untilMs - keep[0].atMs}ms — 5회 · 800ms 여야 한다`);
  const blocked = progress.events.filter((e) => e.kind === 'blocked');
  if (blocked.length !== 1 || blocked[0].block !== 'auto' || blocked[0].count !== 2) f.push(`막힘이 ${JSON.stringify(blocked.map((b) => [b.block, b.count]))} — auto ×2 한 줄이어야 한다`);
  if (summary.counts.keepalive !== 5 || summary.counts.commands !== 2 || summary.counts.blocked !== 2) f.push(`요약 셈이 갈린다 — ${JSON.stringify(summary.counts)}`);
  if (!progress.events.some((e) => e.kind === 'config' && e.mode === 'velocity')) f.push('켤 때의 설정 · 모드가 없다');
  if (progress.events[0]?.kind !== 'opened' || progress.events.at(-1)?.kind !== 'closed') f.push('판이 열림으로 시작해 닫힘으로 끝나지 않는다');
  return f;
}

const manualFolders = filesOf(/_CTL-go1-001\/mission\.json$/).map((k) => k.replace(/\/mission\.json$/, ''));
if (manualFolders.length !== 1) failures.push(`수동 판 폴더가 ${manualFolders.length}개 — 하나여야 한다`);
const manualFolder = manualFolders[0] ?? '';
failures.push(...judgeManual(read(manualFolder, 'mission.json'), read(manualFolder, 'progress.json')));
if (!RUN_NAME.test(manualFolder.split('/')[1] ?? '')) failures.push(`폴더 이름 ${manualFolder} 이 저장 창구 형식을 못 지난다`);
// 나간 바이트는 그대로다 — 기록이 명령을 더하거나 빼지 않는다.
if (go1.sent.filter((s) => s.action === TELEOP_ACTION).length !== 7) failures.push(`장비에 나간 teleop 이 ${go1.sent.length}건 — 누름 1 · 유지 5 · 뗌 1 이어야 한다`);

// 대조군 1 — 유지 신호를 건별로 적은 기록.
{
  const progress = structuredClone(read(manualFolder, 'progress.json'));
  const keep = progress.events.find((e) => e.kind === 'keepalive');
  const at = progress.events.indexOf(keep);
  progress.events.splice(at, 1, ...Array.from({ length: 5 }, (_, i) => ({ ...keep, atMs: keep.atMs + i * 200, untilMs: keep.atMs + i * 200, count: 1 })));
  if (judgeManual(read(manualFolder, 'mission.json'), progress).some((m) => m.includes('구간 한 줄'))) controls.push('유지 신호를 건별로 적은 기록');
  else failures.push('대조군 실패: 유지 신호를 건별로 적어도 판정이 못 잡는다');
}

// ── ③ 켜고 끄기만 ───────────────────────────────────────────────────────────
{
  const before = files.size;
  mc.setManualEnabled('go1-001', true); cr.syncManualSessions(); now += 5000;
  mc.setManualEnabled('go1-001', false); cr.syncManualSessions();
  cr.controlTick(); await cr.settleControlRecorder();
  const judge = (count) => (count !== 0 ? [`켜고 끄기만 했는데 파일 ${count}개를 썼다`] : []);
  failures.push(...judge(files.size - before));
  if (judge(2).length === 1) controls.push('켜고 끄기만 한 판에 폴더를 만든 기록');
  else failures.push('대조군 실패: 빈 판의 폴더를 못 잡는다');
}

// ── ④ 비행 dry-run ──────────────────────────────────────────────────────────
md.resetManualDispatch();
const pi3 = device('fly');
const link = { client: pi3, deviceId: 'x500-002', start: 'yes', stop: 'yes', emergency: 'yes', reason: '' };
now += 10_000;
await flight.issueFlightStart(link, flightPlan.FLIGHT_DEFAULTS, { dryRun: true, confirmed: false });
await sleep(10);
const startId = pi3.sent[0]?.commandId;
const runReport = (state, lines, exitCode = null) => ({
  run_id: 'run-0001', command_id: startId, state, dry_run: true, argv: ['python3', 'test_sar_rtk.py', '--dry-run'],
  started_at: now / 1000, ended_at: state === 'exited' ? now / 1000 + 20 : null, exit_code: exitCode, out_path: null,
  script: 'test_sar_rtk.py', rtk: true, lines,
});
const L = (seq, text) => ({ seq, text });
feed.noteFlightRun(feed.parseFlightRun({ source_id: 'x500-002', run: runReport('running', [L(1, '[연결] udp:14550'), L(2, '[경로] 3 패스')]), emergency: null }));
cr.syncFlightRuns();
now += 5000; cr.controlTick();
feed.noteFlightRun(feed.parseFlightRun({ source_id: 'x500-002', run: runReport('exited', [L(3, '[미션] 업로드 9개'), L(4, '[미션] 대조 일치'), L(5, '[dry-run] 여기서 멈춤'), L(6, '[종료]')], 0), emergency: null }));
cr.syncFlightRuns();
now += 1000; cr.controlTick();
if (!cr.openControlSessions().some((s) => s.deviceId === 'x500-002')) failures.push('실행이 끝나자마자 닫았다 — 마지막 줄을 기다려야 한다');
now += 7000; cr.controlTick(); await cr.settleControlRecorder();
{
  const folder = (filesOf(/_FLT-x500-002\/mission\.json$/)[0] ?? '').replace(/\/mission\.json$/, '');
  const summary = read(folder, 'mission.json');
  const progress = read(folder, 'progress.json');
  if (summary === undefined) failures.push('비행 판이 안 쓰였다');
  else {
    if (summary.sessionKind !== 'flight' || summary.closeReason !== 'flightExited') failures.push(`비행 판이 ${summary.sessionKind}/${summary.closeReason}`);
    if (summary.flight?.dryRun !== true || summary.flight?.outcome !== 'ok' || summary.flight?.phase !== 'dryDone' || summary.flight?.script !== 'test_sar_rtk.py') {
      failures.push(`비행 요약이 갈린다 — ${JSON.stringify(summary.flight)}`);
    }
    if (progress.flight?.startCommandId !== startId) failures.push('시작 명령 id 가 안 이어졌다');
    if (progress.flight?.runs[0]?.lines.length !== 6) failures.push(`실행기 출력이 ${progress.flight?.runs[0]?.lines.length}줄 — 6줄 이어 붙여야 한다`);
    if (!progress.events.some((e) => e.kind === 'commanded' && e.action === 'rtk_test_start' && e.parameters.dry_run === 1)) failures.push('시작 명령의 dry_run 이 기록에 없다');
  }
}

// ── ⑤ 비행 시작 거절 ────────────────────────────────────────────────────────
{
  feed.resetFlightRuns();
  const busy = device('busy', false, 'already_running');
  now += 60_000;
  await flight.issueFlightStart({ ...link, client: busy, deviceId: 'x500-003' }, flightPlan.FLIGHT_DEFAULTS, { dryRun: true, confirmed: false });
  await sleep(10);
  cr.controlTick(); await cr.settleControlRecorder();
  const folder = (filesOf(/_FLT-x500-003\/mission\.json$/)[0] ?? '').replace(/\/mission\.json$/, '');
  const summary = read(folder, 'mission.json');
  if (summary?.closeReason !== 'flightRejected') failures.push(`거절된 시작의 판이 ${summary?.closeReason} 로 닫혔다 — flightRejected`);
  if (summary?.counts.rejected !== 1) failures.push('거절 셈이 1 이 아니다');
}

// ── ⑥ 사람 명령 판 ──────────────────────────────────────────────────────────
{
  const drone = device('sar');
  const params = sarPlan.toStartParams({ ...sarPlan.defaultDraft(), start: { lat: 37.5665, lon: 126.978 }, end: sarPlan.endFrom({ lat: 37.5665, lon: 126.978 }, 45, 80) });
  now += 60_000;
  await sar.issueSarStart(params, { client: drone, deviceId: 'x500-001', start: 'yes', abort: 'yes', reason: '' });
  await sleep(10);
  cr.controlTick();
  if (cr.openControlSessions().find((s) => s.deviceId === 'x500-001')?.kind !== 'command') failures.push('SAR 시작이 사람 명령 판을 안 열었다');
  now += cr.COMMAND_IDLE_MS + 1;
  cr.controlTick(); await cr.settleControlRecorder();
  const folder = (filesOf(/_CTL-x500-001\/mission\.json$/)[0] ?? '').replace(/\/mission\.json$/, '');
  if (read(folder, 'mission.json')?.closeReason !== 'idle') failures.push('사람 명령 판이 쉼으로 안 닫혔다');
  if (read(folder, 'mission.json')?.actions?.sar_start !== 1) failures.push('사람 명령 판에 sar_start 가 없다');
}

cr.setControlProbes({ clock: null, store: null });
md.setManualProbes({ client: null, typing: null, auto: null });

if (failures.length > 0) {
  console.error('❌ verify:control-record');
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log('✅ 임무 밖 수동 제어 — 켬 → 명령 · 수락 · 유지 신호 구간 · 막힘 → 끔 이 CTL 판 하나로 · 나간 바이트 그대로');
console.log('✅ 켜고 끄기만 한 판은 폴더를 안 만든다');
console.log('✅ 비행 dry-run — FLT 판 · dry_run · 실행기 출력 6줄 · 끝난 뒤 기다렸다 닫음 · 시작 거절은 flightRejected');
console.log('✅ 사람 명령(SAR) — 사람 명령 판 · 60초 쉬면 닫힘');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
