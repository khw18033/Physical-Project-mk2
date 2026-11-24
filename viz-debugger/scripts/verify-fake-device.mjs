// verify:fake-device (261014 신설 — 연결 관리 「가짜 Go1 · 가짜 드론」)
//
// **가짜 장비가 실물과 같은 길을 지나는가.** 가짜는 mqtt.js 자리만 바꾸고, 그 뒤는 실물 코드 그대로다. 그러니 여기서
// 보는 것은 「`PhysicalClient` 를 `fake:` 주소로 붙였을 때 실물에 붙은 것과 같은 저장소가 차는가」다.
//
//  1. 가짜 Go1 — 붙으면 자기소개(Capability)와 상태가 와서 카드 · 정체성이 선다. 「목」 표시가 붙는다.
//     `move_forward` 를 보내면 받아들이고, 끝나면 결과가 오고, 위치가 실제로 바뀐다.
//  2. 가짜 드론 — fcx 가 온다. dry-run 은 「대조 일치 → dry-run 끝」으로 코드 0. 확인 없는 비행은 거절.
//     짧은 비행은 이륙 → 패스 → 착륙 단계를 지나 코드 0. 비행 중 중단은 코드 1 과 「사용자 중단」.
//  2-1. 가짜 EP(261124) — 규약 부록 A 어휘 · turn + 는 오른쪽 · 범위 밖 거절 · 이동 중 거절 · abort.
//  3. 모르는 가짜 이름은 붙지 않고 사유를 말한다(대조군).

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
const { deviceIdentityFor } = await load('src', 'physical', 'deviceIdentity.ts');
const { deviceStates, receiveDeviceMessage } = await load('src', 'physical', 'deviceState.ts');
const { fcxReports } = await load('src', 'shared', 'fcxStatus.ts');
const { flightRuns, readProgress } = await load('src', 'physical', 'flightRunFeed.ts');

const failures = [];
const controls = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(what, cond, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const value = cond();
    if (value) return value;
    await sleep(50);
  }
  failures.push(`${what} — ${ms / 1000}초 안에 안 됐다`);
  return null;
}

/** 실물 앱처럼 상태 귀를 붙인다(`robotClient.makeClient` 가 하는 일). */
function client(url) {
  const c = new PhysicalClient(url);
  c.onDevice((topic, body, origin) => receiveDeviceMessage(topic, body, origin));
  return c;
}

/** 명령 하나를 보내고 그 명령의 응답을 모은다. */
async function command(c, action, params, waitResult = true, ms = 4000) {
  const seen = [];
  const off = c.onMessage((m) => seen.push(m));
  const out = c.send(action, params);
  if (!out.sent) { off(); failures.push(`${action} 를 못 보냈다: ${out.reason}`); return { seen, out }; }
  await until(`${action} 응답`, () => seen.find((m) => m.commandId === out.commandId && (waitResult ? m.kind === 'result' : m.kind === 'acceptance')), ms);
  off();
  return { seen: seen.filter((m) => m.commandId === out.commandId), out };
}

// ── 1. 가짜 Go1 ─────────────────────────────────────────────────────────
{
  const go1 = client('fake:go1');
  const status = await go1.connect(2000);
  if (status.state !== 'open') failures.push(`가짜 Go1 에 못 붙었다: ${JSON.stringify(status)}`);
  const who = await until('가짜 Go1 자기소개', () => deviceIdentityFor('fake:go1'), 2000);
  if (who !== null && (who.deviceId !== 'go1-fake' || !who.actions?.includes('teleop'))) failures.push(`가짜 Go1 정체성: ${JSON.stringify(who)}`);
  const state = await until('가짜 Go1 상태', () => deviceStates()['go1-fake']?.position, 3000);
  if (state !== null && deviceStates()['go1-fake'].simulated !== true) failures.push('가짜 Go1 에 「목」 표시(simulated)가 없다');
  const before = deviceStates()['go1-fake']?.position?.x ?? 0;
  const { seen } = await command(go1, 'move_forward', { distance_m: 0.6, vx: 0.6 });
  if (!seen.some((m) => m.kind === 'acceptance' && m.accepted)) failures.push('move_forward 를 안 받아들였다');
  await sleep(1200);
  const after = deviceStates()['go1-fake']?.position?.x ?? 0;
  if (Math.abs(after - before - 0.6) > 0.05) failures.push(`move_forward 0.6m 뒤 x 가 ${before} → ${after}`);
  const nope = await command(go1, 'rtk_test_start', { dry_run: 1 }, false);
  if (!nope.seen.some((m) => m.kind === 'acceptance' && !m.accepted && m.code === 'UNIMPLEMENTED')) failures.push('가짜 Go1 이 미선언 action 을 거절하지 않았다');
  go1.disconnect();
}

// ── 2. 가짜 드론 ────────────────────────────────────────────────────────
{
  const drone = client('fake:drone');
  await drone.connect(2000);
  const who = await until('가짜 드론 자기소개', () => deviceIdentityFor('fake:drone'), 2000);
  if (who !== null && (who.deviceId !== 'x500-fake' || !who.actions?.includes('rtk_test_start'))) failures.push(`가짜 드론 정체성: ${JSON.stringify(who)}`);
  await until('가짜 드론 fcx', () => fcxReports()['x500-fake'], 2000);
  await until('가짜 드론 상태(카드)', () => deviceStates()['x500-fake'], 3000);
  const run = () => flightRuns()['x500-fake']?.run ?? null;

  // dry-run
  const dry = await command(drone, 'rtk_test_start', { pattern: 0, side: 0, altitude_m: 3, length_m: 3, speed_mps: 2, passes: 1, dry_run: 1 });
  await until('dry-run 종료', () => run()?.commandId === dry.out.commandId && run()?.state === 'exited', 6000);
  if (run()?.exitCode !== 0 || readProgress(run()?.lines ?? []).phase !== 'dryDone') failures.push(`dry-run: 코드 ${run()?.exitCode} 단계 ${readProgress(run()?.lines ?? []).phase}`);
  if (fcxReports()['x500-fake']?.armed !== false) failures.push('dry-run 인데 arm 됐다');

  // 확인 없는 비행 — 거절
  const unconfirmed = await command(drone, 'rtk_test_start', { pattern: 0, altitude_m: 3, passes: 1, dry_run: 0 }, false);
  if (!unconfirmed.seen.some((m) => m.kind === 'acceptance' && !m.accepted && m.message === 'not_confirmed')) failures.push('확인 없는 비행을 거절하지 않았다');

  // 짧은 비행 — 고도 2m · 2m · 2m/s · 1회 · 대기 0
  const fly = await command(drone, 'rtk_test_start', { pattern: 0, side: 0, altitude_m: 2, length_m: 2, speed_mps: 2, passes: 1, gap_s: 10,
    settle_s: 0, align_hold_s: 0, rtk_min_s: 0, dry_run: 0, confirmed: 1 });
  const flying = await until('이륙', () => (fcxReports()['x500-fake']?.position?.altRelM ?? 0) > 1, 6000);
  if (flying !== null && fcxReports()['x500-fake'].mode !== 'MISSION') failures.push(`비행 중 모드 ${fcxReports()['x500-fake'].mode}`);
  await until('비행 종료', () => run()?.commandId === fly.out.commandId && run()?.state === 'exited', 25000);
  const progress = readProgress(run()?.lines ?? []);
  if (run()?.exitCode !== 0 || progress.phase !== 'landed' || progress.passesDone !== 1 || !progress.ended) {
    failures.push(`비행: 코드 ${run()?.exitCode} 단계 ${progress.phase} 패스 ${progress.passesDone}`);
  }
  if (fcxReports()['x500-fake']?.armed !== false) failures.push('착륙 뒤에도 arm 상태다');

  // 비행 중 중단 — abort=land 로 빨리 내린다
  const again = await command(drone, 'rtk_test_start', { pattern: 1, side: 2, altitude_m: 2, length_m: 2, speed_mps: 2, passes: 2, gap_s: 10,
    settle_s: 0, align_hold_s: 0, rtk_min_s: 0, abort: 2, dry_run: 0, confirmed: 1 });
  await until('두 번째 이륙', () => run()?.commandId === again.out.commandId && (fcxReports()['x500-fake']?.position?.altRelM ?? 0) > 1, 8000);
  const twice = await command(drone, 'rtk_test_start', { pattern: 0, altitude_m: 3, passes: 1, dry_run: 1 }, false);
  if (!twice.seen.some((m) => m.kind === 'acceptance' && !m.accepted && m.message === 'already_running')) failures.push('실행 중 두 번째 시작을 거절하지 않았다');
  await command(drone, 'rtk_test_stop', undefined);
  await until('중단 종료', () => run()?.state === 'exited', 4000);
  if (run()?.exitCode !== 1 || !run()?.lines.some((l) => l.text.includes('사용자 중단'))) failures.push(`중단: 코드 ${run()?.exitCode}`);
  await until('중단 뒤 착륙(LAND)', () => fcxReports()['x500-fake']?.armed === false, 8000);
  drone.disconnect();
}

// ── 2-1. 가짜 EP (261124) — 규약 부록 A 의 어휘 · 범위 · 부호 ─────────────────
{
  const ep = client('fake:ep');
  const status = await ep.connect(2000);
  if (status.state !== 'open') failures.push(`가짜 EP 에 못 붙었다: ${JSON.stringify(status)}`);
  const who = await until('가짜 EP 자기소개', () => {
    const id = deviceIdentityFor('fake:ep');
    return id?.deviceType ? id : null;
  }, 3000);
  if (who !== null) {
    if (who.deviceId !== 'ep-fake' || who.kind !== 'robot' || who.deviceType !== 'robomaster_ep') failures.push(`가짜 EP 정체성: ${JSON.stringify(who)}`);
    const want = ['ping', 'diag', 'turn', 'move_forward', 'abort'];
    if (JSON.stringify([...(who.actions ?? [])].sort()) !== JSON.stringify([...want].sort())) failures.push(`가짜 EP 어휘: ${JSON.stringify(who.actions)}`);
  }
  await until('가짜 EP 상태', () => deviceStates()['ep-fake']?.position, 3000);
  if (deviceStates()['ep-fake']?.simulated !== true) failures.push('가짜 EP 에 「목」 표시(simulated)가 없다');

  // turn +90 = 오른쪽 → 방위(반시계 +)는 −90
  const turn = await command(ep, 'turn', { deg: 90 }, true, 4000);
  const turned = turn.seen.find((m) => m.kind === 'result');
  if (turned?.status !== 'SUCCEEDED' || turned.result?.deg !== 90) failures.push(`turn 90 결과: ${JSON.stringify(turned)}`);
  await sleep(300);
  const heading = deviceStates()['ep-fake']?.position?.headingDeg;
  if (heading === undefined || Math.abs(heading + 90) > 1) failures.push(`turn +90(오른쪽) 뒤 방위가 ${heading} — −90 이어야 한다`);

  // 오른쪽을 본 채 0.3 m 직진 → y 가 −0.3
  const y0 = deviceStates()['ep-fake']?.position?.y ?? 0;
  const go = await command(ep, 'move_forward', { distance_m: 0.3, vx: 0.3 }, true, 4000);
  const went = go.seen.find((m) => m.kind === 'result');
  if (went?.status !== 'SUCCEEDED' || Math.abs((went.result?.odo_m ?? 0) - 0.3) > 0.01) failures.push(`move_forward 결과: ${JSON.stringify(went)}`);
  await sleep(300);
  const y1 = deviceStates()['ep-fake']?.position?.y ?? 0;
  if (Math.abs(y1 - y0 + 0.3) > 0.03) failures.push(`오른쪽을 보고 0.3m 직진 뒤 y 가 ${y0} → ${y1}`);

  // 범위 밖은 거절(조용히 고치지 않는다)
  for (const [action, params] of [['move_forward', { distance_m: -1 }], ['move_forward', { distance_m: 1, vx: 0.6 }], ['turn', { deg: 2 }]]) {
    const r = await command(ep, action, params, false);
    if (!r.seen.some((m) => m.kind === 'acceptance' && !m.accepted && m.code === 'INVALID_ARGUMENT')) failures.push(`${action} ${JSON.stringify(params)} 를 INVALID_ARGUMENT 로 거절하지 않았다`);
  }
  // Go1 전용은 선언하지 않는다
  const nope = await command(ep, 'teleop', { vx: 0.2 }, false);
  if (!nope.seen.some((m) => m.kind === 'acceptance' && !m.accepted && m.code === 'UNIMPLEMENTED')) failures.push('가짜 EP 가 teleop 을 거절하지 않았다');

  // 이동 중 둘째 이동 → mission_in_progress, abort → 돌던 것은 ABORTED
  const long = { seen: [] };
  const offLong = ep.onMessage((m) => long.seen.push(m));
  const first = ep.send('move_forward', { distance_m: 5, vx: 0.15 });
  await sleep(200);
  const second = await command(ep, 'turn', { deg: 45 }, false);
  if (!second.seen.some((m) => m.kind === 'acceptance' && !m.accepted && m.message === 'mission_in_progress')) failures.push('이동 중 둘째 이동을 거절하지 않았다');
  await command(ep, 'abort', { reason: 1 });
  await until('abort 뒤 돌던 명령 종료', () => long.seen.find((m) => m.commandId === first.commandId && m.kind === 'result'), 2000);
  offLong();
  const cut = long.seen.find((m) => m.commandId === first.commandId && m.kind === 'result');
  if (cut !== undefined && cut.status !== 'ABORTED') failures.push(`abort 뒤 돌던 명령이 ${cut.status}`);
  ep.disconnect();
}

// ── 3. 대조군 — 모르는 가짜 이름 ─────────────────────────────────────────
{
  const bad = client('fake:submarine');
  const status = await bad.connect(1000);
  if (status.state === 'open') failures.push('대조군: fake:submarine 에 붙었다');
  else controls.push('모르는 가짜 이름은 안 붙는다');
}

if (failures.length > 0) {
  console.error('❌ verify:fake-device');
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log(`✅ 통과 — 가짜 Go1(정체성 · 목 표시 · 이동 · 거절) · 가짜 드론(fcx · dry-run · 거절 · 비행 · 중단) · 가짜 EP(정체성 · 부호 · 범위 거절 · 이동 중 거절 · 정지) (대조군 ${controls.length}개: ${controls.join(' / ')})`);
process.exit(0);
