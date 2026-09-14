// verify:approach-plan (260914 신설 — 시연 리허설 지적 두 가지)
//
// **「2D 맵 기반 경로 산출」이 낸 경로로만 움직이는가, 그리고 0도 칸에서 돌았다고 적지 않는가.**
//
// 리허설에서 본 실패 둘.
//
//  1. **경로 없이 이동했다.** `door_turn` 만 오면 「경로대로 이동」이 열리고, 대본의 4.2m 로
//     방향도 모른 채 직진했다. 이제 경로가 없거나 경로 산출이 실패하면 계획이 없다.
//  2. **첫 노드에서 회전했다.** 0도는 스캔을 시작한 방향에서 찍기만 한다. 회전 k 가 k번 칸이고,
//     회전 8 은 출발 방향으로의 복귀다. 0도 칸이 회전 보고 없이 켜질 때 옆 걸음의 방위를
//     빌려 적으면 `door_turn` 견주기와 이동 보정이 둘 다 틀어진다.
//
// 그리고 **로봇은 스캔 뒤 제자리에 서 있지 않다** — `door_turn` 이 한 칸 되돌아 선다. 탐지의
// 회전각은 출발 방향 기준이라 로봇이 보고한 방위로 보정해야 한다. 수치는 실측 판의 것이다.
//
// 대조군 포함.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const strip = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const src = (...p) => strip(readFileSync(join(root, 'src', ...p), 'utf8'));

const failures = [];
const controls = [];
const near = (a, b, tol = 0.05) => typeof a === 'number' && Math.abs(a - b) <= tol;

const plan = await load('src', 'physical', 'approachPlan.ts');
const session = await load('src', 'physical', 'robotSession.ts');
const store = await load('src', 'detect', 'store.ts');
const { effectsOf } = await load('src', 'physical', 'missionLink.ts');
const { STOP_ACTION } = await load('src', 'physical', 'presets.ts');

// 실측 판 (verify-robot-run 과 같은 값). 회전 k 뒤의 방위다 — 회전 8(-54.76)이 곧 출발 방위.
const SEEN = [-9.98, 35.09, 80.06, 125.32, 170, -144.71, -99.67, -54.76];
const DOOR_YAW = -94.16;
// 문 단독 위치 추정(B) 리허설 산출물의 회전·직진.
const DETECTION_TURN = -78.7;
const FORWARD_M = 6.456;

const PATH = {
  target_class: 'door', ok: true, path_mode: 'map', localization_method: 'door_only',
  robot_position_cm: [226.4, 124.0], current_heading_map_deg: 0, goal_cm: [0, 0],
  turn_instruction: '왼쪽(반시계)으로 78.7도 회전', forward_distance_cm: FORWARD_M * 100,
  robot_command: { turn: { deg: DETECTION_TURN }, move_forward: { distance_m: FORWARD_M }, distance_m_in_range: true },
};

// ── 1. 순수 계산 ─────────────────────────────────────────────────────────────
{
  // 리허설 판: 출발 -2.8 · 스캔 뒤 -41.99 (한 칸 되돌아 섬) · 탐지 -78.7 → 약 -39.5 만 더 돈다.
  const r = plan.compensateTurn(-78.7, -2.8, -41.99, 1);
  if (!near(r.turnedSinceStartCwDeg, -39.19)) failures.push(`출발 뒤 돈 각도가 ${r.turnedSinceStartCwDeg} — -39.19 여야 한다`);
  if (!near(r.turnDeg, -39.51)) failures.push(`보낼 회전이 ${r.turnDeg} — -39.51 이어야 한다`);
  // 감김: 170 을 가야 하는데 이미 왼쪽으로 45 돌아 있으면 215 = 왼쪽 145.
  if (!near(plan.compensateTurn(170, 0, -45, 1).turnDeg, -145)) failures.push('±180 을 넘는 회전을 안 감는다');
  // yaw 가 시계에 줄어드는 로봇이면 부호가 뒤집힌다.
  if (!near(plan.compensateTurn(-78.7, 2.8, 41.99, -1).turnDeg, -39.51)) failures.push('yaw 가 반시계로 느는 로봇을 보정 못 한다');

  const seen = Object.fromEntries(SEEN.slice(0, 7).map((yaw, i) => [i + 1, yaw]));
  if (plan.yawCwSignOf(seen) !== 1) failures.push('실측 판에서 yaw 가 시계로 는다는 것을 못 잰다');
  if (plan.yawCwSignOf(Object.fromEntries(SEEN.slice(0, 7).map((yaw, i) => [i + 1, -yaw]))) !== -1) failures.push('yaw 가 주는 로봇을 못 잰다');
  if (plan.yawCwSignOf({ 3: 10 }) !== null) failures.push('걸음 하나로 방향을 지어낸다');

  if (plan.turnFromInstruction('왼쪽(반시계)으로 90.0도 회전') !== -90) failures.push('「왼쪽 90도」를 -90 으로 못 읽는다');
  if (plan.turnFromInstruction('오른쪽(시계)으로 30도 회전') !== 30) failures.push('「오른쪽 30도」를 30 으로 못 읽는다');
  if (plan.turnFromInstruction('직진') !== null) failures.push('각이 없는 문장에서 각을 지어낸다');
}

// ── 2. 경로가 없으면 움직이지 않는다 ─────────────────────────────────────────
{
  session.resetRobotSession();
  store.setTestMode(false);
  store.resetDetect();
  const none = plan.planApproach(45);
  if (none.ok) failures.push('경로가 없는데 이동 계획이 나온다 — 대본 거리로 걷던 그 실패다');
  else if (!/경로/.test(none.reason)) failures.push(`경로가 없다는 사유가 아니다: ${none.reason}`);

  store.receivePathFailure({ target_class: 'door', ok: false, reason: '문을 한 각도에서도 못 찾았습니다', fallback_chain: [] });
  const failed = plan.planApproach(45);
  if (failed.ok) failures.push('경로 산출이 실패했는데 이동 계획이 나온다');
  else if (!/문을 한 각도에서도 못 찾았습니다/.test(failed.reason)) failures.push(`탐지가 준 실패 사유를 안 옮긴다: ${failed.reason}`);

  store.resetDetect();
  store.receivePath({ ...PATH, robot_command: { ...PATH.robot_command, distance_m_in_range: false, warning: '직진 12m 가 범위 밖' } });
  const out = plan.planApproach(45);
  if (out.ok) failures.push('범위 밖 직진을 그대로 낸다');

  // 소스에 대본 거리로 되돌아가는 길이 남아 있지 않다.
  const commands = src('physical', 'robotCommands.ts');
  if (/issueTask\(\s*['"]T-B2['"]/.test(commands)) failures.push('「경로대로 이동」이 아직 대본 명령(T-B2)으로 되돌아간다');
  if (/missionGeometry/.test(src('physical', 'approachPlan.ts'))) failures.push('이동 계획이 대본 기하값을 읽는다');
}

// ── 3. 실측 판 → 보낼 명령 ───────────────────────────────────────────────────
function playScan({ withReturn }) {
  session.resetRobotSession();
  store.resetDetect();
  const effects = [];
  SEEN.slice(0, 7).forEach((yaw, i) => {
    effects.push({
      kind: 'viewpoint', warning: null,
      frame: { channel: 'robot_state', payload: { rotation_index: i + 1, yaw, state: 'rotating', last_cmd: 'scan_mission', result: null } },
    });
  });
  if (withReturn) effects.push({ kind: 'scan-return', yawDeg: SEEN[7] });
  effects.push({ kind: 'door-turn', yawDeg: DOOR_YAW, chosenIndex: 7 });
  session.applyEffects(effects);
  store.receivePath(PATH);
  return plan.planApproach(45);
}
{
  const p = playScan({ withReturn: true });
  if (!p.ok) failures.push(`실측 판에서 계획이 안 나온다: ${p.reason}`);
  else {
    // 출발 -54.76 → 지금 -94.16: 왼쪽으로 39.4 돌아 있다. 탐지 -78.7 에서 그만큼 덜 돈다.
    if (p.startYawDeg !== SEEN[7]) failures.push(`출발 방위가 ${p.startYawDeg} — 복귀 회전의 ${SEEN[7]} 여야 한다`);
    if (p.nowYawDeg !== DOOR_YAW) failures.push(`지금 방위가 ${p.nowYawDeg} — door_turn 의 ${DOOR_YAW} 여야 한다`);
    if (!near(p.turnDeg, -39.3)) failures.push(`보낼 회전이 ${p.turnDeg} — -39.3 이어야 한다`);
    const actions = p.steps.map((s) => s.action).join(',');
    if (actions !== `turn,move_forward,${STOP_ACTION}`) failures.push(`걸음이 ${actions} — 회전·직진·도착 정지여야 한다`);
    if (p.steps[0]?.parameters.deg !== -39.3) failures.push(`회전 명령이 ${p.steps[0]?.parameters.deg} 로 나간다`);
    if (p.steps[1]?.parameters.distance_m !== FORWARD_M) failures.push(`직진이 ${p.steps[1]?.parameters.distance_m}m 로 나간다 — 경로의 ${FORWARD_M}m 여야 한다`);
    if (p.steps[2]?.taskId !== 'T-B3') failures.push('도착 정지가 T-B3 의 걸음이 아니다');
  }
  // 복귀 보고를 놓쳐도 첫 회전 방위에서 한 칸 되돌려 출발을 잡는다.
  const q = playScan({ withReturn: false });
  if (!q.ok || !near(q.startYawDeg, SEEN[0] - 45) || !near(q.turnDeg, -39.52)) {
    failures.push(`복귀 보고 없이 출발을 못 잡는다: ${JSON.stringify(q.ok ? { start: q.startYawDeg, turn: q.turnDeg } : q.reason)}`);
  }
}

// ── 4. 0도 칸은 돌지 않는다 ──────────────────────────────────────────────────
{
  session.resetRobotSession();
  const context = { taskOf: () => 'T-A3', seenYawByIndex: new Map(), litIndices: new Set(), viewpointCount: 8 };
  const detail = { ack: 1, of: 10, ackSeq: null, event: 'scan_turn', step: 1, steps: 8, yaw_deg: SEEN[0], note: 'ok' };
  const effects = effectsOf({ kind: 'status', commandId: 'c', state: 'RUNNING', detail, raw: '' }, context);
  const indices = effects.filter((e) => e.kind === 'viewpoint').map((e) => e.frame.payload.rotation_index);
  if (indices.join(',') !== '0,1') failures.push(`회전1 이 켠 칸이 ${indices} — 0(찍힌 칸)과 1 이어야 한다`);
  session.applyEffects(effects);
  const s = session.robotSession();
  if (s.seenYaw[0] !== undefined) failures.push(`0도 칸에 회전1 뒤의 방위 ${s.seenYaw[0]} 를 빌려 적었다`);
  if (s.litIndices[0] !== true) failures.push('0도 칸이 켜진 것으로 안 남는다 — 회전2 에서 또 켠다');
  if (s.seenYaw[1] !== SEEN[0]) failures.push('회전1 의 방위가 1번 칸에 안 남는다');

  const again = effectsOf(
    { kind: 'status', commandId: 'c', state: 'RUNNING', detail: { ...detail, ack: 2, step: 2, yaw_deg: SEEN[1] }, raw: '' },
    { ...context, seenYawByIndex: new Map([[1, SEEN[0]]]), litIndices: new Set([0, 1]) },
  );
  if (again.some((e) => e.kind === 'viewpoint' && e.frame.payload.rotation_index === 0)) failures.push('회전2 가 0도 칸을 또 켠다');

  const back = effectsOf(
    { kind: 'status', commandId: 'c', state: 'RUNNING', detail: { ...detail, ack: 8, step: 8, yaw_deg: SEEN[7] }, raw: '' }, context,
  );
  if (back.some((e) => e.kind === 'viewpoint')) failures.push('복귀 회전(8)이 칸을 켠다');
  if (!back.some((e) => e.kind === 'scan-return' && e.yawDeg === SEEN[7])) failures.push('복귀 회전의 방위가 출발 방위로 안 남는다');
  session.resetRobotSession();
}

// ── 대조군 ───────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  controls.push(name);
}
{
  // **보정 없이 탐지 회전각을 그대로 보낸 사본.** 문에서 39도 어긋난 쪽으로 걷는다.
  control('탐지 회전각을 보정 없이 보낸 사본', Math.abs(DETECTION_TURN - (-39.3)) > 30);
}
{
  // **0도 칸에 회전1 방위를 빌려 적은 사본.** 출발을 첫 회전 방위로 잡으면 한 칸 틀린다.
  const borrowed = plan.compensateTurn(DETECTION_TURN, SEEN[0], DOOR_YAW, 1).turnDeg;
  control('0도 칸에 회전1 방위를 빌려 적은 사본', Math.abs(borrowed - (-39.3)) > 30);
}
{
  // **회전 k 를 k-1 칸에 붙인 사본.** 7번 걸음(-99.67)이 6번 칸이 되어 초록이 한 칸 밀린다.
  const shifted = SEEN.slice(0, 7).map((_, i) => i);
  control('회전 k 를 k-1 칸에 붙인 사본', shifted[6] !== 7);
}

if (failures.length) {
  console.error(`❌ verify:approach-plan\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 경로가 없거나 산출이 실패하면 이동 계획이 없다 — 대본 거리로 걷지 않고 탐지가 준 사유를 옮긴다');
console.log('✅ 탐지 회전각은 출발 방향 기준 — 로봇이 보고한 방위로 스캔 뒤 틀어진 만큼 보정한다 (실측 -78.7 → -39.3)');
console.log('✅ 복귀 보고를 놓쳐도 첫 회전 방위에서 한 칸 되돌려 출발을 잡는다 · ±180 을 감는다 · yaw 방향을 잰다');
console.log('✅ 회전 → 직진(경로 거리 그대로) → 도착 정지(T-B3)');
console.log('✅ 0도 칸은 회전 보고 없이 켜지고 방위를 빌려 적지 않는다 · 회전 8 은 칸이 아니라 출발 방위다');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
