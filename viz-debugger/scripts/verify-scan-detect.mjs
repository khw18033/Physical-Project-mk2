// verify:scan-detect (261123 신설 — 스캔 탐지를 data_stream 으로 · S11)
//
// **새 흐름(`scan-detect`)이 계획서 §2-3 의 순서로 돌고, 실패하면 움직이지 않는가.**
// 가짜 창구(`scan-detect-mock.mjs`)를 임의 포트로 띄우고, 회전은 가짜(기록만 하고 완료를 돌려준다)로 돌린다.
//
// 막으려는 실패:
//  1. turn 완료 **전에** mark 가 나가는 것 — 돌고 있는 장면을 그 각도의 대표로 잡는다.
//  2. turn 완료가 안 왔는데 다음 mark · turn 이 나가는 것.
//  3. 준비 실패 · 시간 초과 · 산출 실패 · 찾지 못함 · 거리 못 믿음 · 409 · 정지 · 프로필 바뀜에서 이동 계획이 서는 것.
//  4. 다른 scan_id 의 사건이 이번 판 상태를 바꾸는 것.
//  5. 경로 계산 — 방위 −170 · 5° 미만 · 0.05 m 미만 · 상한 초과 · 회전 오차 보정 있음 / 없음.
// 대조군 포함.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const { startScanMock } = await load('scripts', 'scan-detect-mock.mjs');
const { scanClient, newScanId } = await load('src', 'detect', 'scan', 'ScanClient.ts');
const { reduceScan } = await load('src', 'detect', 'scan', 'scanStore.ts');
const { parseResult } = await load('src', 'detect', 'scan', 'parse.ts');
const { runScanDetect, profileChanged } = await load('src', 'physical', 'scanDetectRun.ts');
const { planScanApproach, scanDrift } = await load('src', 'physical', 'scanApproach.ts');

const failures = [];
const controls = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

const FAST = { loadMs: 120, markMs: 30, resultMs: 120 };

async function withMock(options, body) {
  const log = [];
  const server = await startScanMock({ port: 0, host: '127.0.0.1', log, ...FAST, ...options });
  try {
    return await body(`http://127.0.0.1:${server.address().port}`, log);
  } finally {
    server.close();
  }
}

/** 실행기 한 판. 회전 · 노드 · 사건 · 기록을 전부 모아 돌려준다. */
async function runOnce(base, { turnFails = null, stopAfterTurns = null, heading = [0, -3.5], target = 'door', query = null, queryKo, limits = {}, scanId } = {}) {
  const timeline = [];
  const emits = [];
  const events = [];
  const records = [];
  let turns = 0;
  let stopped = false;
  const deps = {
    client: scanClient(base),
    async turn(deg, index) {
      timeline.push({ kind: 'turn-sent', index, deg, at: Date.now() });
      await new Promise((done) => setTimeout(done, 40));
      turns += 1;
      if (stopAfterTurns !== null && turns >= stopAfterTurns) stopped = true;
      if (turnFails === index) { timeline.push({ kind: 'turn-failed', index }); return { ok: false, reason: 'timeout' }; }
      timeline.push({ kind: 'turn-done', index, at: Date.now() });
      return { ok: true };
    },
    startHeading: async () => heading[0],
    heading: () => heading[1],
    emit: (taskId, status, payload) => emits.push({ taskId, status, payload }),
    event: (event) => events.push(event),
    record: (entry) => { records.push(entry); if (entry.call === 'mark') timeline.push({ kind: 'mark', index: entry.angleIndex }); },
    stopped: () => stopped,
    sleep: (ms) => new Promise((done) => setTimeout(done, ms)),
    now: () => Date.now(),
  };
  const outcome = await runScanDetect({
    scanId: scanId ?? newScanId('MSN-261123-01'), missionId: 'MSN-261123-01', device: 'go1-001', target, query,
    queryKo: queryKo !== undefined ? queryKo : query === null ? null : '소화기',
    steps: 8, stepDeg: 45, pollMs: 40, ...limits,
  }, deps);
  return { outcome, timeline, emits, events, records, turns };
}

// ── 1. 정상 판: 순서 · 노드 · 결과 · 경로 ───────────────────────────────
await withMock({ mode: 'ok' }, async (base, log) => {
  const run = await runOnce(base);
  check(run.outcome.ok, `정상 판이 실패했다: ${JSON.stringify(run.outcome)}`);
  const marks = run.timeline.filter((e) => e.kind === 'mark');
  const turnsSent = run.timeline.filter((e) => e.kind === 'turn-sent');
  check(marks.length === 8, `mark 가 8번이어야 한다 (${marks.length})`);
  check(turnsSent.length === 8, `turn 이 8번이어야 한다 (${turnsSent.length})`);
  // mark(k) (k ≥ 1) 는 turn(k−1) 완료 뒤, turn(k) 는 mark(k) 뒤.
  const pos = (pred) => run.timeline.findIndex(pred);
  for (let k = 0; k < 8; k += 1) {
    const markAt = pos((e) => e.kind === 'mark' && e.index === k);
    const turnAt = pos((e) => e.kind === 'turn-sent' && e.index === k);
    check(markAt >= 0 && turnAt > markAt, `turn(${k}) 이 mark(${k}) 뒤가 아니다`);
    if (k > 0) {
      const prevDone = pos((e) => e.kind === 'turn-done' && e.index === k - 1);
      check(prevDone >= 0 && prevDone < markAt, `mark(${k}) 가 turn(${k - 1}) 완료 전에 나갔다`);
    }
  }
  // 창구가 **받은 시각**으로도 본다 — 응답 시각으로만 보면 turn 을 안 기다리고 보낸 mark 를 못 잡는다.
  const markArrivals = log.filter((r) => r.path === '/scan/mark').map((r) => ({ deg: r.body.rotation_deg, at: r.at }));
  for (let k = 1; k < 8; k += 1) {
    const arrived = markArrivals.find((m) => m.deg === k * 45);
    const prevDone = run.timeline.find((e) => e.kind === 'turn-done' && e.index === k - 1);
    check(arrived !== undefined && prevDone !== undefined && arrived.at >= prevDone.at, `mark(${k * 45}°) 가 창구에 turn(${k - 1}) 완료 전에 닿았다`);
  }
  const lastMark = pos((e) => e.kind === 'mark' && e.index === 7);
  const lastTurnDone = pos((e) => e.kind === 'turn-done' && e.index === 7);
  check(lastTurnDone > lastMark && run.timeline.slice(lastTurnDone).every((e) => e.kind !== 'mark'), '마지막 회전 뒤에 mark 가 나갔다');
  const finishAt = log.findIndex((r) => r.path === '/scan/finish');
  const marksInLog = log.filter((r) => r.path === '/scan/mark').length;
  check(finishAt > 0 && log.slice(finishAt).every((r) => r.path !== '/scan/mark') && marksInLog === 8, 'finish 가 mark 8번 뒤에 한 번 나가야 한다');
  const firstMark = log.findIndex((r) => r.path === '/scan/mark');
  const readyBefore = log.slice(0, firstMark).some((r) => r.path === '/scan/status');
  check(readyBefore, '준비(ready) 확인 전에 mark 가 나갔다');
  const done = (id) => run.emits.some((e) => e.taskId === id && e.status === 'done');
  for (const id of ['T-A0', 'T-A3', 'T-A4-0', 'T-A4-7']) check(done(id), `${id} 가 done 으로 칠해지지 않았다`);
  check(run.records.filter((r) => r.call === 'mark').every((r) => r.taskId === `T-A4-${r.angleIndex}`), 'mark 기록이 각도 노드에 붙지 않았다');
  check(run.records.some((r) => r.call === 'prepare' && r.taskId === 'T-A0') && run.records.some((r) => r.call === 'finish' && r.taskId === 'T-A5'), 'prepare · finish 기록 노드가 틀리다');
  if (run.outcome.ok) {
    const { result, headingStartDeg, headingEndDeg } = run.outcome;
    check(result.best?.rotation_deg === 90 && result.best.distance_valid === true, '정상 판의 best 가 90° 가 아니다');
    const plan = planScanApproach({ best: result.best, stopDistanceM: 0.9, headingStartDeg, headingEndDeg, testMode: false });
    check(plan.ok, `정상 판에서 이동 계획이 안 섰다: ${JSON.stringify(plan)}`);
    if (plan.ok) {
      check(plan.steps.map((s) => s.action).join(',') === 'turn,move_forward,abort', `이동 명령 차례가 틀리다: ${plan.steps.map((s) => s.action)}`);
      // 끝 방위 −3.5 는 반시계 + 기준으로 오른쪽 3.5° 더 돈 것(실물 GO1 · 261123) — 그만큼 뺀다.
      check(Math.abs(plan.turnDeg - (96.4 - 3.5)) < 1e-9, `회전 오차 보정이 틀리다 (${plan.turnDeg})`);
      // 261124 — 거리의 85% 만 믿는다(SCAN_DISTANCE_TRUST): 2.35 × 0.85 − 0.9
      check(Math.abs(plan.issuedForwardM - (2.35 * 0.85 - 0.9)) < 1e-9, `직진 거리가 틀리다 (${plan.issuedForwardM})`);
    }
    // 상태 저장소 — 사건을 접으면 각도 8칸이 전부 수집됨이고 결과가 들어 있다.
    const folded = run.events.reduce((state, event) => reduceScan(state, event), null);
    check(folded?.angles.every((a) => a.captured === true) && folded.result?.state === 'done', '저장소가 각도 · 결과를 접지 못했다');
    check(folded?.headingStartDeg === 0 && folded.headingEndDeg === -3.5, '저장소에 시작 · 끝 방위가 없다');
  }
});

// ── 2. 실패 갈래: 어느 것도 이동 계획이 서면 안 된다 ──────────────────────
const branches = [
  { name: 'no-stream', mock: { mode: 'no-stream' }, stage: 'prepare' },
  { name: 'no-vision', mock: { mode: 'no-vision' }, stage: 'prepare' },
  { name: 'reject', mock: { mode: 'reject' }, stage: 'prepare' },
  { name: 'prepare-timeout', mock: { mode: 'prepare-timeout' }, run: { limits: { prepareLimitMs: 300 } }, stage: 'prepare', code: 'timeout' },
  { name: 'failed', mock: { mode: 'failed' }, stage: 'result' },
  { name: 'result-timeout', mock: { mode: 'result-timeout' }, run: { limits: { resultLimitMs: 300 } }, stage: 'result', code: 'timeout' },
  { name: 'turn-timeout', mock: { mode: 'ok' }, run: { turnFails: 2 }, stage: 'turn' },
  { name: 'stop', mock: { mode: 'ok' }, run: { stopAfterTurns: 3 }, stage: 'turn', code: 'stopped' },
];
for (const branch of branches) {
  await withMock(branch.mock, async (base, log) => {
    const run = await runOnce(base, branch.run ?? {});
    check(!run.outcome.ok, `${branch.name}: 실패해야 하는데 결과가 섰다`);
    if (!run.outcome.ok) {
      check(run.outcome.stage === branch.stage, `${branch.name}: 멈춘 단계가 ${run.outcome.stage} (기대 ${branch.stage})`);
      if (branch.code) check(run.outcome.code === branch.code, `${branch.name}: 사유 ${run.outcome.code} (기대 ${branch.code})`);
    }
    if (branch.name.startsWith('no-') || branch.name === 'reject' || branch.name === 'prepare-timeout') {
      check(!log.some((r) => r.path === '/scan/mark') && run.turns === 0, `${branch.name}: 준비가 안 됐는데 mark · turn 이 나갔다`);
    }
    if (branch.name === 'turn-timeout') {
      check(run.timeline.filter((e) => e.kind === 'mark').length === 3 && run.turns === 3, `turn-timeout: 완료 없는 turn 뒤에 mark · turn 이 더 나갔다 (mark ${run.timeline.filter((e) => e.kind === 'mark').length}, turn ${run.turns})`);
      check(!log.some((r) => r.path === '/scan/finish'), 'turn-timeout: finish 가 나갔다');
    }
    if (branch.name === 'stop') {
      check(log.some((r) => r.path === '/scan/cancel'), 'stop: cancel 이 안 나갔다');
      check(!log.some((r) => r.path === '/scan/finish'), 'stop: 정지 뒤 finish 가 나갔다');
    }
  });
}

// 찾지 못함 · 거리 못 믿음 — 결과는 서지만 계획은 안 선다.
for (const mode of ['best-null', 'distance-invalid']) {
  await withMock({ mode }, async (base) => {
    const run = await runOnce(base);
    check(run.outcome.ok, `${mode}: 결과(done)는 받아야 한다`);
    if (run.outcome.ok) {
      const plan = planScanApproach({ best: run.outcome.result.best, stopDistanceM: 0.9, headingStartDeg: 0, headingEndDeg: 0, testMode: false });
      check(!plan.ok, `${mode}: 이동 계획이 섰다`);
    }
  });
}

// 프레임 없음 둘 — 그 각도만 비고 결과는 받는다.
await withMock({ mode: 'frame-gaps', gapDegs: [135, 180] }, async (base) => {
  const run = await runOnce(base);
  check(run.outcome.ok, 'frame-gaps: 결과를 받아야 한다');
  const failedAngles = run.emits.filter((e) => e.status === 'failed' && e.taskId.startsWith('T-A4-')).map((e) => e.taskId).sort();
  check(failedAngles.join(',') === 'T-A4-3,T-A4-4', `frame-gaps: 빈 각도가 틀리다 (${failedAngles})`);
  check(run.turns === 8, 'frame-gaps: 프레임 없음에 회전이 멈췄다');
});

// 프로필 바뀜 — 결과의 번호가 ready 때와 다르면 움직이지 않는다.
await withMock({ mode: 'profile-changed' }, async (base) => {
  const run = await runOnce(base);
  const folded = run.events.reduce((state, event) => reduceScan(state, event), null);
  check(run.outcome.ok && profileChanged(folded.profileVersion, run.outcome.result), 'profile-changed: 프로필 바뀜을 못 알아챘다');
});
await withMock({ mode: 'ok' }, async (base) => {
  const run = await runOnce(base);
  const folded = run.events.reduce((state, event) => reduceScan(state, event), null);
  check(run.outcome.ok && !profileChanged(folded.profileVersion, run.outcome.result), 'ok 판을 프로필 바뀜으로 읽었다 (대조군)');
});

// 409 — 다른 판이 도는 중이면 prepare 가 busy 로 끝난다.
await withMock({ mode: 'prepare-timeout' }, async (base) => {
  await scanClient(base).prepare({ scan_id: 'OTHER-1', device: 'go1-001', target: 'box', query: null, query_ko: null, steps: 8, step_deg: 45 });
  const run = await runOnce(base, { limits: { prepareLimitMs: 300 } });
  check(!run.outcome.ok && run.outcome.code === 'busy' && run.outcome.detail === 'OTHER-1', `409: busy 로 끝나지 않았다 (${JSON.stringify(run.outcome)})`);
});

// @ 편 — query 가 영어로 나간다.
await withMock({ mode: 'ok' }, async (base, log) => {
  const run = await runOnce(base, { target: 'object', query: 'fire extinguisher' });
  const prep = log.find((r) => r.path === '/scan/prepare');
  check(run.outcome.ok && prep?.body.query === 'fire extinguisher' && prep.body.query_ko === '소화기', '@ 편 prepare 에 query · query_ko 가 없다');
});

// ── 3. 지난 판 거르기 ─────────────────────────────────────────────────
{
  const begin = { kind: 'begin', scanId: 'A', missionId: 'M', device: 'go1-001', base: 'x', target: 'door', query: null, queryKo: null, steps: 8, stepDeg: 45 };
  const s0 = reduceScan(null, begin);
  const stale = reduceScan(s0, { kind: 'mark', scanId: 'B', index: 0, answer: { scan_id: 'B', rotation_deg: 0, frame_captured: true, frame_n: 1, captured_at: null } });
  check(stale === s0, '다른 scan_id 의 mark 가 상태를 바꿨다');
  const fresh = reduceScan(s0, { kind: 'mark', scanId: 'A', index: 0, answer: { scan_id: 'A', rotation_deg: 0, frame_captured: true, frame_n: 1, captured_at: null } });
  if (fresh === s0) controls.push('대조군: 같은 scan_id 의 mark 도 버렸다');
}

// ── 4. 경로 계산 ──────────────────────────────────────────────────────
{
  const best = (bearing, distance, extra = {}) => ({ rotation_deg: 0, bearing_deg: bearing, distance_m: distance, distance_valid: true, distance_source: 'unidepth', distance_note: null, bearing_note: null, provisional: false, ...extra });
  const plan = (b, extra = {}) => planScanApproach({ best: b, stopDistanceM: 0.9, headingStartDeg: null, headingEndDeg: null, testMode: false, ...extra });
  const p1 = plan(best(-170, 3));
  check(p1.ok && p1.turnDeg === -170 && p1.notes.some((n) => n.key === 'sd.plan.noDrift'), '방위 −170 · 보정 없음 메모가 틀리다');
  const p2 = plan(best(3, 3));
  check(p2.ok && p2.steps[0].action === 'move_forward' && p2.notes.some((n) => n.key === 'sd.plan.turnTooSmall'), '5° 미만 회전을 냈다');
  check(!plan(best(30, 0.93)).ok, '0.05 m 미만 직진에 계획이 섰다');
  check(!plan(best(30, 14)).ok, '이동 상한을 넘었는데 계획이 섰다'); // 14 × 0.85 − 0.9 = 11 > 10
  // 방위는 실물 GO1 처럼 **반시계 +** 다(261123 실측 · `HEADING_TURN_SIGN = −1`). 시작 −175 → 끝 178 은 반시계로 −7°(= 오른쪽 +7° 더 돎)…가 아니라
  // 178 − (−175) = 353 → 감으면 −7 → 반시계 −7 = 시계 +7 — 오른쪽으로 7° 더 돌았다. 그만큼 뺀다.
  const p3 = plan(best(170, 3), { headingStartDeg: -175, headingEndDeg: 178 });
  check(p3.ok && Math.abs(p3.driftDeg - 7) < 1e-9 && Math.abs(p3.turnDeg - 163) < 1e-9, `회전 오차 감기가 틀리다 (${p3.ok ? `${p3.driftDeg} ${p3.turnDeg}` : p3.reason.key})`);
  // 끝이 반시계로 +5 → 왼쪽으로 5° 덜 돈 것(오른쪽 −5) → 178 − (−5) = 183 → −177 로 감긴다.
  const p4 = plan(best(178, 3), { headingStartDeg: 0, headingEndDeg: 5 });
  check(p4.ok && Math.abs(p4.turnDeg - (-177)) < 1e-9, `−180~180 감기가 틀리다 (${p4.ok ? p4.turnDeg : ''})`);
  check(scanDrift(null, 3) === null, '시작 방위가 없는데 보정했다');
  const p5 = plan(best(30, 3), { testMode: true });
  check(p5.ok && p5.issuedForwardM === 1, '테스트 상한이 안 걸렸다');
  if (plan(best(30, 3, { distance_valid: false })).ok) failures.push('distance_valid false 에 계획이 섰다');
  // 방위가 각도 정면으로 대신한 값이면 계획은 서되 메모가 붙는다(data_stream 회신 §4.2).
  const p6 = plan(best(45, 3, { bearing_note: 'no focal length — heading of the scan step' }));
  check(p6.ok && p6.notes.some((n) => n.key === 'sd.plan.bearingNote' && n.vars?.note.startsWith('no focal')), 'bearing_note 메모가 안 붙었다');
  check(p1.ok && !p1.notes.some((n) => n.key === 'sd.plan.bearingNote'), '대조군: bearing_note 가 없는데 메모가 붙었다');
}

// ── 5. 응답 모양 검사 ──────────────────────────────────────────────────
{
  check(parseResult({ scan_id: 'A', state: 'done', frames: [], best: { rotation_deg: 0 } }) === null, '반쯤 있는 best 를 받아들였다');
  check(parseResult({ scan_id: 'A', state: 'running' })?.state === 'running', 'running 결과를 못 읽었다');
  // 오류 응답 `{error, detail, …}` (data_stream 구현 보고 §3-10) — 409 라도 busy 만 busy 다.
  const stub = (status, body) => scanClient('http://stub', async () => ({ ok: status < 400, status, json: async () => body }));
  const badState = await stub(409, { error: 'bad_state', detail: 'not collecting (done)' }).mark('A', 45);
  check(!badState.ok && badState.code === 'http' && badState.detail.includes('not collecting'), `409 bad_state 를 busy 로 읽었다 (${JSON.stringify(badState)})`);
  const busy = await stub(409, { error: 'busy', busy_scan_id: 'B' }).prepare({ scan_id: 'A' });
  check(!busy.ok && busy.code === 'busy' && busy.busyScanId === 'B', `409 busy 를 못 읽었다 (${JSON.stringify(busy)})`);
  const wrongPort = await stub(400, { error: 'wrong_port', detail: 'go1-001 is not robot2', stream: 'robot1' }).prepare({ scan_id: 'A' });
  check(!wrongPort.ok && wrongPort.detail.includes('wrong_port') && wrongPort.detail.includes('stream robot1'), `wrong_port 의 맞는 소스가 빠졌다 (${JSON.stringify(wrongPort)})`);
  const noted = parseResult({ scan_id: 'A', state: 'done', frames: [], best: { rotation_deg: 90, bearing_deg: 90, distance_m: 2, distance_valid: true, bearing_note: 'no focal length' } });
  check(noted?.best?.bearing_note === 'no focal length', 'best 의 bearing_note 를 못 읽었다');
  if (parseResult({ scan_id: 'A', state: 'done', frames: [], best: null }) === null) controls.push('대조군: 찾지 못함(best null)을 거부했다');
}

// ── 6. data_stream 스캔 창구 변경 대응 (261124 — `a1e43f8` · 요청서 「확인 방법 1」) ─────────────────
{
  // 요청서의 두 예시 JSON 을 그대로 결과로 읽는다.
  const fireBody = { scan_id: 'F', state: 'done', frames: [], best: {
    rotation_deg: 180, bearing_deg: 157.2, bearing_note: 'reference - no fisheye correction',
    distance_m: 1.686, distance_valid: true, distance_source: 'ground_line', distance_note: null,
    score: 99.1, box_xyxy: [169.9, 212.0, 181.6, 239.8], provisional: true, isolated: false, seen_at: [135, 180, 225] } };
  const doorBody = { scan_id: 'D', state: 'done', frames: [], best: {
    rotation_deg: 45, bearing_deg: 11.2, distance_m: 5.819, distance_valid: false, distance_source: 'measured',
    distance_note: 'monocular depth on the Go1 fisheye camera is not calibrated - ground line: outside 50-300 cm',
    isolated: true, seen_at: [45] } };
  const fire = parseResult(fireBody);
  const door = parseResult(doorBody);
  check(fire?.best?.distance_source === 'ground_line' && fire.best.isolated === false && fire.best.seen_at.join(',') === '135,180,225', `소화기 예시를 못 읽었다 (${JSON.stringify(fire?.best)})`);
  check(door?.best?.isolated === true && door.best.distance_valid === false, `문 예시를 못 읽었다 (${JSON.stringify(door?.best)})`);
  const at = (b, stop = 0.2) => planScanApproach({ best: b, stopDistanceM: stop, headingStartDeg: 0, headingEndDeg: 0, testMode: false });

  // 소화기 예시 → 전진이 나간다. 거리의 85% − 정지 거리 0.2 = 1.686 × 0.85 − 0.2.
  const firePlan = at(fire.best);
  check(firePlan.ok && firePlan.confirm === null, `소화기 예시에 계획이 안 섰거나 확인을 요구했다 (${JSON.stringify(firePlan)})`);
  if (firePlan.ok) {
    const fwd = firePlan.steps.find((s) => s.action === 'move_forward')?.parameters.distance_m;
    check(Math.abs(fwd - Number((1.686 * 0.85 - 0.2).toFixed(3))) < 1e-9, `소화기 예시의 직진이 ${fwd} — 1.686 × 0.85 − 0.2 여야 한다`);
    check(firePlan.notes.some((n) => n.key === 'sd.plan.trust'), '거리 믿음 비율 메모가 안 붙었다');
  }
  // 문 예시 → 전진하지 않는다. 사유에 distance_note 가 실린다.
  const doorPlan = at(door.best);
  check(!doorPlan.ok && doorPlan.reason.key === 'sd.plan.distanceInvalid' && String(doorPlan.reason.vars?.note).includes('outside 50-300 cm'),
    `문 예시에 계획이 섰거나 distance_note 가 빠졌다 (${JSON.stringify(doorPlan)})`);
  // distance_source 로 갈래를 나누지 않는다 — measured 라도 valid 면 가고, ground_line 이라도 valid 가 아니면 안 간다.
  check(at({ ...fire.best, distance_source: 'measured' }).ok, 'valid 인 measured 거리를 막았다 — distance_valid 만 봐야 한다');
  check(!at({ ...fire.best, distance_valid: false }).ok, 'valid 가 아닌 ground_line 거리로 계획이 섰다');
  // isolated best → 계획은 서되 확인을 요구한다.
  const lone = at({ ...fire.best, isolated: true, seen_at: [180] });
  check(lone.ok && lone.confirm === 'isolated' && lone.notes.some((n) => n.key === 'sd.plan.isolated'), `isolated best 가 확인 없이 갈 계획이다 (${JSON.stringify(lone)})`);
  // 옛 창구(칸 없음)는 지금처럼 — isolated 거짓 · seen_at 빈 목록.
  const old = parseResult({ scan_id: 'O', state: 'done', frames: [{ rotation_deg: 0, found: true }], best: { rotation_deg: 0, bearing_deg: 0, distance_m: 2, distance_valid: true } });
  check(old?.best?.isolated === false && old.best.seen_at.length === 0 && old.frames[0].isolated === null && old.query_used === null, '옛 창구 결과의 새 칸 기본값이 틀리다');
}

// 깨진 번역 — 보내기 전 검사.
{
  const { sendableQuery } = await load('src', 'generate', 'nameEn.ts');
  for (const broken of ['celedar or person orhumanbeingorhumanh', 'ionalescrollingtext uebaa uebaa uebaa', 'Fire Extinguisher', '소화기', 'a'.repeat(41), '', 'chair!']) {
    check(!sendableQuery(broken).ok, `깨진 이름 ${JSON.stringify(broken)} 을 보내도 된다고 했다`);
  }
  for (const good of ['fire extinguisher', 'person', 'traffic-cone', '  chair  ']) {
    check(sendableQuery(good).ok, `멀쩡한 이름 ${JSON.stringify(good)} 을 막았다`);
  }
}

// 400 bad_query — 사유를 따로 받는다.
{
  const stub = (status, body) => scanClient('http://stub', async () => ({ ok: status < 400, status, json: async () => body }));
  const bad = await stub(400, { error: 'bad_query', detail: 'query "uebaa uebaa" is not a known object' }).prepare({ scan_id: 'A' });
  check(!bad.ok && bad.code === 'bad_query' && bad.detail.includes('not a known object'), `bad_query 를 못 읽었다 (${JSON.stringify(bad)})`);
  const other = await stub(400, { error: 'bad_request', detail: 'x' }).prepare({ scan_id: 'A' });
  check(!other.ok && other.code === 'http', '대조군: bad_request 를 bad_query 로 읽었다');
}

// 가짜 창구 판 — 예시 판 · isolated · @ 이름(아는 낱말 · 모르는 낱말)
await withMock({ mode: 'extinguisher' }, async (base) => {
  const run = await runOnce(base);
  const best = run.outcome.ok ? run.outcome.result.best : null;
  check(best?.rotation_deg === 180 && best.distance_source === 'ground_line' && best.seen_at.join(',') === '135,180,225', `extinguisher 판의 best 가 틀리다 (${JSON.stringify(best)})`);
  const lone = run.outcome.ok ? run.outcome.result.frames.filter((f) => f.found && f.isolated === false).length : 0;
  check(lone === 3, `extinguisher 판의 찾은 각도 셋이 같이 보인 것으로 오지 않았다 (${lone})`);
});
await withMock({ mode: 'door-measured' }, async (base) => {
  const run = await runOnce(base);
  const best = run.outcome.ok ? run.outcome.result.best : null;
  check(best?.distance_valid === false && best.isolated === true && run.outcome.result.reason.endsWith('seen at one angle only'), `door-measured 판이 틀리다 (${JSON.stringify(best)})`);
  check(best !== null && !planScanApproach({ best, stopDistanceM: 0.2, headingStartDeg: 0, headingEndDeg: 0, testMode: false }).ok, 'door-measured 판에 계획이 섰다');
});
await withMock({ mode: 'box-ok' }, async (base) => {
  const run = await runOnce(base, { target: 'box' });
  const not = run.outcome.ok ? run.outcome.result.frames.find((f) => !f.found) : null;
  check(not?.reason === 'score 52 < 65 (scan floor)', `박스 점수 하한 사유가 그대로 오지 않았다 (${not?.reason})`);
});
await withMock({ mode: 'ok' }, async (base, log) => {
  // 번역을 버리고 query_ko 만 — 아는 낱말이면 돈다.
  const run = await runOnce(base, { target: 'object', query: null, queryKo: '소화기' });
  const prep = log.find((r) => r.path === '/scan/prepare');
  check(run.outcome.ok && prep?.body.query === null && prep.body.query_ko === '소화기', `query 없이 query_ko 만으로 준비가 안 됐다 (${JSON.stringify(run.outcome)})`);
  check(run.outcome.ok && run.outcome.result.query_used === 'fire extinguisher' && run.outcome.result.query_source === 'query_ko', 'query_used · query_source 를 못 읽었다');
});
await withMock({ mode: 'ok' }, async (base, log) => {
  // 모르는 낱말 + 이름 없음 → bad_query 로 준비에서 선다. 아무것도 돌지 않는다.
  const run = await runOnce(base, { target: 'object', query: null, queryKo: '거울' });
  check(!run.outcome.ok && run.outcome.stage === 'prepare' && run.outcome.code === 'bad_query', `모르는 낱말이 bad_query 로 서지 않았다 (${JSON.stringify(run.outcome)})`);
  check(!log.some((r) => r.path === '/scan/mark') && run.turns === 0, 'bad_query 뒤에 mark · turn 이 나갔다');
});

if (controls.length > 0) failures.push(...controls);
if (failures.length > 0) {
  console.error(`❌ verify:scan-detect 실패 ${failures.length}건`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}
console.log('✅ 통과 — 순서(turn 완료 → mark) · 실패 갈래 10 · 프레임 없음 · 프로필 바뀜 · 409 · @ 질의 · 지난 판 거르기 · 경로 계산 · 응답 모양');
