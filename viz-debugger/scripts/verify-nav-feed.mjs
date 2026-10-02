// verify:nav-feed (260915 신설 — 자율주행 편 · pi1 중계)
//
// **pi1 이 전해 준 것이 네 노드를 옳게 칠하고, 시연 편은 건드리지 않는가.**
//
// 로봇이 없는 자리에서 한 판을 통째로 흘린다 — pi1 이 계약(`viz-nav/1`)대로 낸다고 치고 받은 봉투를
// 그대로 넣은 뒤, 화면이 접는 그대로(`foldStatuses`) 노드를 읽는다.
//
// 막으려는 실패 다섯.
//  1. **모양이 다른 것을 옛 규칙으로 읽는 것** — schema 가 다르면 버리고, 없는 값은 null 로 둔다.
//     배터리 null 을 0% 로, 출처 없는 yaw 를 부호 모르는 채로 쓰지 않는다.
//  2. **낡은 값·지난 사건으로 이 판을 칠하는 것** — 판을 열기 전에 받은 사건과 오래된 상태는 안 친다.
//  3. **되돌아감이 회차로 안 남는 것** — 취소 → 재탐색 → 새 경로가 이동 n+1 회차(derived)여야 한다.
//  4. **pi1 몫이 아닌 노드를 칠하는 것** — 이동경로 탐색 · 장애물 탐지 · 목적지 도착 · 임무 종료는 대기다.
//  5. **시연 편에 새는 것** — 시연 편에서는 중계 판이 안 열리고, 표시등 목록·pi7 주소가 그대로다.
//
// 대조군 포함 — 검사를 무력화한 사본이 반드시 실패로 잡히는지까지 본다.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isScratchPath } from './lib/scratch.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readFileSync(join(root, ...p), 'utf8');

const feed = await load('src', 'physical', 'navFeed.ts');
const { startNavLink, drainNavEvents, NAV_TASKS, NAV_REORDER_MS } = await load('src', 'physical', 'navLink.ts');
const { navRun, navRunState, beginNavRun, endNavRun, startArmedNavRun } = await load('src', 'physical', 'navRun.ts');
const { receiveObstacleSnapshot, DERIVED_TASKS } = await load('src', 'physical', 'navLink.ts');
const { stopRelayRun, pauseRelayRun, resumeRelayRun, RELAY_STOP_WORDS_KEY } = await load('src', 'physical', 'navControl.ts');
// 260918 — 문구가 사전 키가 되었으므로 사전도 읽는다 (키만 맞고 사전이 비면 화면에 키가 뜬다).
const { ko: koDict } = await load('src', 'i18n', 'ko.ts');
const obstacleSnap = (atMs, near, names = []) => ({
  receivedAtMs: atMs, cameraId: 'go1_front', hasNearObstacle: near,
  detections: names.map((name) => ({ name, distanceCm: 40, riskLevel: 'near' })),
});
const scenario = await load('src', 'data', 'scenario.ts');
const session = await load('src', 'physical', 'robotSession.ts');
const { foldStatuses } = await load('src', 'data', 'fold.ts');
const { checkAutodrive } = await load('src', 'shared', 'connectionCheck.ts');

const AUTO_ID = 'MSN-260915-01';
const DOOR_ID = 'MSN-260909-01';
const TOPIC_STATE = 'zoneA/robot/go1-001/nav_state';
const TOPIC_EVENT = 'zoneA/robot/go1-001/nav_event';

const failures = [];
const controls = [];

const state = (over = {}) => ({
  schema: 'viz-nav/1', node_id: 'pi1', entity_id: 'go1-001', ts_ms: 1_789_000_000_000,
  battery_pct: 82, yaw_deg: -12.5, yaw_source: 'bridge_state', moving: false, path_active: false, path_id: null, ...over,
});
let evSeq = 0;
const ev = (event, over = {}) => ({
  schema: 'viz-nav/1', node_id: 'pi1', entity_id: 'go1-001', seq: ++evSeq, ts_ms: 1_789_000_000_000 + evSeq,
  event, path_id: null, point_count: null, source: 'udp15110', note: '', ...over,
});
/** pi1 시계는 이 PC 보다 앞선다 — 260915 실측 2263 ms. 봉투의 ts_ms 를 받은 시각과 그만큼 어긋나게 만든다. */
const PI_AHEAD_MS = 2263;
const sendState = (over, atMs) => feed.receiveNavMessage(TOPIC_STATE, state({ ts_ms: atMs + PI_AHEAD_MS, ...over }), atMs);
/** `happenedMs` 를 주면 그 시각에 일어나 `atMs` 에 늦게 온 사건이다(pi1 브로커 큐 · 보고 §6-10). */
/** 받고 곧바로 적용까지 — 들고 있는 창(NAV_REORDER_MS)을 기다리지 않는다. 순서 검사는 아래 `queueEvent` 로 한다. */
const sendEvent = (kind, over, atMs, happenedMs = atMs) => {
  const accepted = feed.receiveNavMessage(TOPIC_EVENT, ev(kind, { ts_ms: happenedMs + PI_AHEAD_MS, ...over }), atMs);
  drainNavEvents();
  return accepted;
};
/** 받기만 한다 — 실측처럼 받은 순서와 pi1 시각이 어긋난 흐름을 흘릴 때. `tsMs` 는 pi1 시계 그대로. */
const queueEvent = (kind, over, atMs, tsMs) => feed.receiveNavMessage(TOPIC_EVENT, ev(kind, { ts_ms: tsMs, ...over }), atMs);

// ── 1. 뜯기 — 모양과 null ────────────────────────────────────────────────────
{
  feed.resetNavFeed();
  if (feed.navChannel('zoneA/robot/go1-001/state') !== null) failures.push('장비 상태 토픽을 중계로 읽는다');
  if (feed.navChannel('a/b/nav_state') !== null) failures.push('세 칸 토픽을 중계로 읽는다');
  const ok = feed.parseNavState(TOPIC_STATE, state(), 1000);
  if (ok?.batteryPct !== 82 || ok?.yawDeg !== -12.5 || ok?.yawSource !== 'bridge_state') failures.push('계약대로 온 nav_state 를 못 읽는다');
  if (feed.parseNavState(TOPIC_STATE, state({ schema: 'viz-nav/2' })) !== null) failures.push('schema 가 다른데 읽었다');
  if (feed.parseNavState(TOPIC_STATE, state({ battery_pct: null }))?.batteryPct !== null) failures.push('배터리 null 을 null 로 안 둔다');
  if (feed.parseNavState(TOPIC_STATE, state({ battery_pct: 140 }))?.batteryPct !== null) failures.push('배터리 140% 를 받은 값으로 쓴다');
  if (feed.parseNavState(TOPIC_STATE, state({ yaw_source: undefined }))?.yawDeg !== null) failures.push('출처 없는 yaw 를 쓴다 — 부호를 모른다');
  if (feed.parseNavState(TOPIC_STATE, state({ entity_id: undefined }))?.entityId !== 'go1-001') failures.push('본문에 장비 id 가 없을 때 토픽에서 못 읽는다');
  // 260915 pi1 답신 — IMU 방위는 선택 키다. 있으면 읽고, 없어도(옛 중계) 나머지를 버리지 않는다.
  if (feed.parseNavState(TOPIC_STATE, state({ yaw_odometry_deg: 2.5 }))?.yawOdometryDeg !== 2.5) failures.push('선택 키 yaw_odometry_deg 를 못 읽는다');
  if (feed.parseNavState(TOPIC_STATE, state())?.yawOdometryDeg !== null) failures.push('yaw_odometry_deg 가 없는데 값을 지어낸다');
  if (feed.parseNavEvent(TOPIC_EVENT, ev('teleport')) !== null) failures.push('계약에 없는 사건을 읽었다');
  if (feed.parseNavEvent(TOPIC_EVENT, ev('path_received', { seq: 'x' })) !== null) failures.push('seq 없는 사건을 읽었다');

  if (feed.receiveNavMessage(TOPIC_STATE, state({ schema: 'nope' })) !== false || feed.navFeedState().rejected !== 1) {
    failures.push('못 읽은 건을 세지 않는다 — 연결 관리가 「오긴 오는데 못 읽는다」를 말할 재료다');
  }
  const once = ev('path_received', { path_id: 9 });
  feed.receiveNavMessage(TOPIC_EVENT, once);
  if (feed.receiveNavMessage(TOPIC_EVENT, once) !== false) failures.push('QoS 1 로 다시 온 같은 사건을 또 받는다');
  // 중계가 다시 떠 seq 가 1 로 돌아가도 시각이 다르면 새 사건이다.
  if (feed.receiveNavMessage(TOPIC_EVENT, { ...once, ts_ms: once.ts_ms + 5000 }) !== true) failures.push('중계 재기동 뒤 같은 seq 의 새 사건을 버린다');
  // 대조군 — 열을 비우면 같은 사건이 다시 들어온다. 막은 것이 중복 표라는 뜻이다.
  feed.resetNavFeed();
  controls.push('중복 표를 비우면 같은 사건이 다시 들어온다');
  if (feed.receiveNavMessage(TOPIC_EVENT, once) !== true) failures.push('대조군 실패: 중복 표를 비워도 같은 사건이 막힌다 — 무엇이 막는지 모른다');
  feed.resetNavFeed();
}

// ── 한 판 흘리기 ─────────────────────────────────────────────────────────────
startNavLink();

/** 승인만 한다 — 260915 부터 판은 걸리기만 하고 안 열린다. */
function approveOnly(missionId) {
  scenario.resetMission();
  feed.resetNavFeed();
  session.setConnection({ state: 'idle' });
  scenario.proposeMission({ origin: 'script', missionId, title: missionId, keywords: [], planId: null, world: 'registry' });
  scenario.acceptProposal('remote');
}
/** 승인하고 「▶ 임무 시작」까지. 열린 판을 돌려준다(시연 편이면 걸린 것이 없어 null). */
function approve(missionId) {
  approveOnly(missionId);
  startArmedNavRun();
  return navRun();
}
const traceOf = (nodeId) => scenario.traceEvents().filter((e) => e.nodeId === nodeId);
const folded = () => foldStatuses(1e9, scenario.currentMission(), scenario.traceEvents());

// ── 1-1. 승인과 시작은 다르다 (260915 지시) ───────────────────────────────────
{
  approveOnly(AUTO_ID);
  if (navRunState().armed !== AUTO_ID) failures.push('승인했는데 판이 안 걸렸다 — 「임무 시작」이 열 것이 없다');
  if (navRun() !== null) failures.push('승인만 했는데 판이 열렸다 — 승인하자마자 노드에 불이 켜진다');
  sendState({}, Date.now());
  sendEvent('path_received', { path_id: 1 }, Date.now());
  receiveObstacleSnapshot(obstacleSnap(Date.now(), false));
  const early = scenario.traceEvents().filter((e) => e.seq >= 6_000_000);
  if (early.length > 0) failures.push(`시작 전에 중계로 노드 ${early.length}건을 칠했다`);
  if (!startArmedNavRun() || navRun()?.missionId !== AUTO_ID) failures.push('「임무 시작」이 걸어 둔 판을 안 연다');
  // 시작 직전 한 주기 안에 받은 상태는 지금 값이라 곧바로 끝날 수 있다 — 진행 중을 지났는지만 본다.
  if (!traceOf(NAV_TASKS.battery).some((e) => e.status === 'running' && e.atSec === 0)) failures.push('시작했는데 배터리 확인이 0초에 진행 중으로 안 선다');
  if (startArmedNavRun()) failures.push('이미 연 판을 또 연다 — 두 번 누르면 판이 새로 선다');
  // 승인 없이 시작은 없다.
  scenario.resetMission();
  if (startArmedNavRun() || navRun() !== null) failures.push('승인 없이 「임무 시작」이 판을 열었다');
  // 대조군 — 시작을 누르면 같은 상태가 칠해진다. 막은 것이 「시작 전」이라는 뜻이다.
  approve(AUTO_ID);
  sendState({}, Date.now());
  controls.push('시작한 뒤에는 같은 상태로 배터리가 끝난다');
  if (!traceOf(NAV_TASKS.battery).some((e) => e.status === 'done')) failures.push('대조군 실패: 시작해도 안 칠한다 — 1-1 검사가 헛돈다');
}

// ── 2. 정상 한 판 — 배터리 → 방위 → 경로 탐색 → 이동 · 취소 · 재탐색 · 새 경로 · 도착 · 종료 ─
{
  const run = approve(AUTO_ID);
  if (run?.missionId !== AUTO_ID) failures.push('새 편을 승인했는데 중계 판이 안 열렸다');
  if (session.robotSession().approved) failures.push('중계 편 승인이 로봇 관문(pi7 명령)을 열었다');
  const t0 = run?.startedAtMs ?? Date.now();
  if (traceOf(NAV_TASKS.battery).at(-1)?.status !== 'running') failures.push('판을 열었는데 배터리 확인이 진행 중이 아니다');

  sendState({ yaw_odometry_deg: 2 }, Date.now());
  const battery = traceOf(NAV_TASKS.battery);
  if (!battery.some((e) => e.status === 'awaiting_evaluation')) failures.push('배터리 확인이 평가 대기를 안 지난다 — 평가 태스크다');
  const batteryDone = battery.find((e) => e.status === 'done');
  if (batteryDone?.payload?.battery_pct !== 82 || batteryDone?.payload?.min_battery_pct !== 30) failures.push('배터리 완료에 받은 값·기준이 안 실린다');
  const yawDone = traceOf(NAV_TASKS.yaw).find((e) => e.status === 'done');
  if (yawDone?.payload?.yaw_deg !== -12.5 || yawDone?.payload?.yaw_source !== 'bridge_state') failures.push('위치 확인에 yaw 와 출처가 안 실린다');
  if (yawDone?.payload?.yaw_odometry_deg !== 2) failures.push('위치 확인에 IMU yaw 가 나란히 안 실린다');
  if (Object.keys(yawDone?.payload ?? {}).some((k) => /^(x|y|z|x_m|y_m|z_m|position)$/.test(k))) failures.push('위치 확인에 yaw 말고 좌표가 실린다 — yaw 만 쓴다');

  const at = (sec) => t0 + sec * 1000;
  // 위치 확인이 끝나면 경로를 기다린다.
  if (traceOf(DERIVED_TASKS.plan).at(-1)?.status !== 'running') failures.push('위치 확인 뒤 이동경로 탐색이 진행 중(경로 대기)이 아니다');
  // 장애물 JSON — 처음 온 것이 진행 중으로, 가까운 장애물이 바뀌면 진행 줄.
  receiveObstacleSnapshot(obstacleSnap(at(5), false));
  receiveObstacleSnapshot(obstacleSnap(at(5.5), false));
  receiveObstacleSnapshot(obstacleSnap(at(19), true, ['umbrella']));
  sendEvent('path_received', { path_id: 1, point_count: 5 }, at(10));
  sendEvent('path_cancel', { path_id: 1 }, at(20));
  sendEvent('cancel_ack', { source: 'udp15101_mode98' }, at(20.2));
  sendEvent('path_received', { path_id: 2, point_count: 7 }, at(23));
  sendEvent('path_cancel', { path_id: 2 }, at(30));
  sendEvent('path_received', { path_id: 3, point_count: 4 }, at(33));
  sendEvent('path_done', { path_id: 3, source: 'udp15101_mode99' }, at(45));

  const move = traceOf(NAV_TASKS.move);
  const replan = traceOf(NAV_TASKS.replan);
  const first = move[0];
  if (first?.status !== 'running' || first?.attempt !== 1 || first?.payload?.path_id !== 1) failures.push('첫 경로가 이동 1회차 시작이 아니다');
  if (Math.abs((first?.atSec ?? -1) - 10) > 0.01) failures.push(`사건 시각이 판을 연 뒤 초가 아니다 — ${first?.atSec}`);
  if (move[1]?.status !== 'done' || move[1]?.payload?.ended_by !== 'path_cancel') failures.push('취소가 이동 1회차를 끝내지 않는다');
  if (replan[0]?.status !== 'running' || replan[0]?.attempt !== 1) failures.push('첫 취소가 재탐색 1회차 시작이 아니다');
  if (!replan.some((e) => e.kind === 'progress' && e.payload?.cancel_ack === true)) failures.push('취소 ACK 가 재탐색 진행으로 안 남는다');
  const second = move.find((e) => e.attempt === 2 && e.kind === 'derived');
  if (second?.status !== 'rerunning' || second?.derivedFrom !== NAV_TASKS.replan || second?.payload?.path_id !== 2) {
    failures.push('새 경로가 이동 2회차(derived · 재탐색에서 파생)가 아니다');
  }
  const replan2 = replan.find((e) => e.attempt === 2 && e.kind === 'derived');
  if (replan2?.derivedFrom !== NAV_TASKS.move) failures.push('두 번째 취소가 재탐색 2회차(이동에서 파생)가 아니다');
  const last = move.at(-1);
  if (last?.status !== 'done' || last?.attempt !== 3 || last?.payload?.ended_by !== 'path_done') failures.push('경로 끝(mode 99)이 이동 3회차 완료가 아니다');

  const f = folded();
  if (f.tasks[NAV_TASKS.battery]?.status !== 'done' || f.tasks[NAV_TASKS.yaw]?.status !== 'done') failures.push('접으면 상태 확인 둘이 완료가 아니다');
  if (f.milestones['MS-A'] !== 'done') failures.push(`MS-A 가 ${f.milestones['MS-A']} — 완료여야 한다`);
  if (f.tasks[NAV_TASKS.move]?.attempt !== 3 || f.tasks[NAV_TASKS.replan]?.attempt !== 2) failures.push('접은 회차가 이동 3 · 재탐색 2 가 아니다');
  // 260915 — 받은 것으로 끝내는 넷.
  const plan = traceOf(DERIVED_TASKS.plan).find((e) => e.status === 'done');
  if (plan?.payload?.path_id !== 1 || Math.abs(plan.atSec - 10) > 0.01) failures.push('첫 경로 수신이 이동경로 탐색을 끝내지 않는다');
  if (traceOf(DERIVED_TASKS.plan).filter((e) => e.status === 'done').length !== 1) failures.push('이동경로 탐색이 경로마다 다시 끝난다 — 첫 경로 한 번이다');
  const obstacle = traceOf(DERIVED_TASKS.obstacle);
  if (obstacle[0]?.status !== 'running' || obstacle[0]?.payload?.has_near_obstacle !== false) failures.push('첫 장애물 JSON 이 장애물 탐지를 진행 중으로 안 만든다');
  if (obstacle.filter((e) => e.kind === 'progress').length !== 1 || !obstacle.some((e) => e.payload?.near?.includes('umbrella 40cm'))) {
    failures.push('가까운 장애물이 바뀐 순간이 한 줄로 안 남는다(같은 값이 반복되면 줄을 더하지 않는다)');
  }
  const arriveDone = traceOf(DERIVED_TASKS.arrive).find((e) => e.status === 'done');
  if (!traceOf(DERIVED_TASKS.arrive).some((e) => e.status === 'awaiting_evaluation')) failures.push('목적지 도착이 평가 대기를 안 지난다 — 평가 태스크다');
  if (arriveDone?.payload?.ended_by !== 'path_done' || arriveDone?.payload?.replans !== 2 || arriveDone?.payload?.move_attempts !== 3) failures.push('목적지 도착에 경로 끝 · 회차 근거가 안 실린다');
  if (f.tasks[DERIVED_TASKS.obstacle]?.status !== 'done') failures.push('도착했는데 장애물 탐지가 안 끝났다');
  if (f.tasks[DERIVED_TASKS.end]?.status !== 'done') failures.push('도착했는데 임무 종료가 안 끝났다');
  for (const ms of ['MS-A', 'MS-B', 'MS-C']) if (f.milestones[ms] !== 'done') failures.push(`${ms} 가 ${f.milestones[ms]} — 도착하면 셋 다 완료다`);
  if (Object.values(f.tasks).some((t) => t.status !== 'done')) failures.push('도착했는데 여덟 노드가 다 끝나지 않았다 — 임무 이력에 「완료」가 안 적힌다');
  // 끝난 임무 뒤의 경로 사건은 칠하지 않는다.
  const count = scenario.traceEvents().length;
  sendEvent('path_received', { path_id: 9 }, at(50));
  receiveObstacleSnapshot(obstacleSnap(at(51), false));
  if (scenario.traceEvents().length !== count) failures.push('임무 종료 뒤에 온 사건으로 노드를 다시 칠했다');
}

// ── 2-1. 재탐색 없이 도착 · 장애물 JSON 없이 도착 ────────────────────────────
{
  const run = approve(AUTO_ID);
  const at = (sec) => run.startedAtMs + sec * 1000;
  sendState({}, Date.now());
  sendEvent('path_received', { path_id: 1, point_count: 3 }, at(3));
  sendEvent('path_done', { path_id: 1 }, at(20));
  const f = folded();
  const replan = traceOf(NAV_TASKS.replan);
  if (replan.length !== 1 || replan[0].status !== 'done' || replan[0].payload?.replans !== 0) failures.push('재탐색 없이 도착했는데 경로 재탐색이 0회 완료가 아니다');
  // 장애물 JSON 이 한 번도 안 왔다 — 탐지를 안 한 것을 했다고 적지 않는다.
  if (f.tasks[DERIVED_TASKS.obstacle]?.status !== 'pending') failures.push(`장애물 JSON 없이 도착했는데 장애물 탐지가 ${f.tasks[DERIVED_TASKS.obstacle]?.status}`);
  if (f.milestones['MS-B'] === 'done') failures.push('장애물 탐지를 안 했는데 MS-B 가 완료다');
  // 이동 중이 아닌데 온 경로 끝은 도착이 아니다.
  approve(AUTO_ID);
  sendEvent('path_done', { path_id: 1 }, navRun().startedAtMs + 1000);
  if (traceOf(DERIVED_TASKS.arrive).length > 0) failures.push('따라가던 경로 없이 온 경로 끝으로 도착을 칠했다');
}

// ── 2-2. 정지 · 일시정지 — pi7 로 보내지 않고 화면·기록만 멈춘다 ─────────────
{
  const run = approve(AUTO_ID);
  sendState({}, Date.now());
  sendEvent('path_received', { path_id: 1 }, run.startedAtMs + 1000);
  // 일시정지 — 그동안 온 사건은 칠하지 않고, 풀면 다시 칠한다.
  const paused = pauseRelayRun();
  if (paused.published !== false) failures.push('자율주행 일시정지가 무언가를 보냈다고 한다');
  const n0 = scenario.traceEvents().length;
  sendEvent('path_cancel', { path_id: 1 }, run.startedAtMs + 2000);
  if (scenario.traceEvents().length !== n0) failures.push('일시정지 중에 온 사건을 칠했다');
  resumeRelayRun();
  sendEvent('path_received', { path_id: 1 }, run.startedAtMs + 3000);
  if (scenario.traceEvents().length === n0) failures.push('일시정지를 풀었는데 사건을 안 칠한다');
  // 정지 — 잠그고 칠하지 않는다. 못 멈췄다는 사실을 크게 말한다.
  const stopped = stopRelayRun();
  // 260918 — 문구가 사전 키로 바뀌었다. 규칙은 그대로다: 정지가 **로봇에는 안 갔다**는
  // 사실이 `failure` 에 남아야 한다. 이제는 사전이 푼 값과 대조하고, 그 값이 한국어 원문
  // 그대로인지도 본다 — 사전이 비면 화면에 키가 그대로 뜬다.
  if (stopped.published !== false || stopped.failure !== koDict[RELAY_STOP_WORDS_KEY]) failures.push('자율주행 정지가 「로봇에는 못 보냈다」를 안 남긴다');
  if (!String(koDict[RELAY_STOP_WORDS_KEY] ?? '').includes('유니티')) failures.push('사전의 relay.stopWords 가 「유니티나 조종기로 세우라」는 길을 안 알려 준다');
  const n1 = scenario.traceEvents().length;
  sendEvent('path_done', { path_id: 1 }, run.startedAtMs + 4000);
  if (scenario.traceEvents().length !== n1) failures.push('정지 뒤에 온 사건을 칠했다');
  // 정지 해제 — 판이 내려가고 다시 승인해야 한다.
  session.releaseStopped();
  if (navRunState().armed !== null || navRun() !== null) failures.push('정지를 풀었는데 판이 그대로다 — 다시 승인하지 않고 이어 칠한다');
  if (startArmedNavRun()) failures.push('정지 해제 뒤 승인 없이 「임무 시작」이 판을 열었다');
  // 머리줄 버튼이 이 편에서 pi7 로 abort 를 보내지 않는다(소스).
  const buttons = read('src', 'physical', 'StopButton.tsx');
  if (!/relayDriven\(currentMission\(\)\.missionId\) \? stopRelayRun\(\) : emergencyStop\(robotClient\(\)\)/.test(buttons)) failures.push('정지 버튼이 자율주행 편에서도 pi7 로 abort 를 보낸다');
  if (!/relayDriven\(currentMission\(\)\.missionId\) \? pauseRelayRun\(\) : pauseMission\(robotClient\(\)\)/.test(buttons)) failures.push('일시정지 버튼이 자율주행 편에서도 pi7 로 보낸다');
  if (!/if \(!started\) \{ startArmedNavRun\(\); return; \}/.test(buttons)) failures.push('임무 시작 버튼이 자율주행 판을 안 연다');
}

// ── 3. 낡은 값 · 지난 사건 · 멈춘 판 ─────────────────────────────────────────
{
  const run = approve(AUTO_ID);
  const t0 = run.startedAtMs;
  // 판을 열기 10초 전에 받은 상태 — 지금 값이 아니다.
  sendState({}, t0 - 10_000);
  if (traceOf(NAV_TASKS.battery).some((e) => e.status === 'done')) failures.push('판을 열기 10초 전 값으로 배터리를 완료했다');
  // 판을 열기 전에 받은 사건 — 이 판의 것이 아니다.
  sendEvent('path_received', { path_id: 7 }, t0 - 1);
  if (traceOf(NAV_TASKS.move).length > 0) failures.push('판을 열기 전에 받은 경로로 이동을 칠했다');
  // 대조군 — 같은 값을 지금 받으면 완료된다. 막은 것이 나이라는 뜻이다.
  sendState({}, Date.now());
  controls.push('같은 상태를 지금 받으면 배터리 완료');
  if (!traceOf(NAV_TASKS.battery).some((e) => e.status === 'done')) failures.push('대조군 실패: 지금 받은 값으로도 배터리가 안 끝난다 — 무엇이 막는지 모른다');

  // 정지 뒤에는 칠하지 않는다.
  await (await load('src', 'physical', 'robotCommands.ts')).emergencyStop(null);
  const before = scenario.traceEvents().length;
  sendEvent('path_received', { path_id: 8 }, Date.now());
  if (scenario.traceEvents().length !== before) failures.push('정지 뒤에 받은 경로로 노드를 칠했다');
  session.releaseStopped();
}

// ── 3-1. 늦게 온 사건 — pi1 브로커 큐에서 나온 것 (260915 보고 §6-10) ───────────
{
  const run = approve(AUTO_ID);
  const t0 = run.startedAtMs;
  // 시계 차를 잴 상태 몇 건 — 제때 온다.
  for (let i = 0; i < 5; i += 1) sendState({}, Date.now());
  const offset = feed.navFeedState().clockOffsetMs;
  if (offset !== -PI_AHEAD_MS) failures.push(`시계 차를 ${offset} 으로 쟀다 — ${-PI_AHEAD_MS} 여야 한다`);
  // 판을 열기 5초 전에 일어나 판을 연 뒤에 온 사건 — 이 판의 것이 아니다.
  sendEvent('path_received', { path_id: 21 }, t0 + 15_000, t0 - 5_000);
  if (traceOf(NAV_TASKS.move).length > 0) failures.push('판을 열기 전에 일어난 사건이 늦게 왔다고 이 판에 칠했다');
  // 판을 연 1초 뒤에 일어나 20초 뒤에 온 사건 — 1초 자리에 칠한다.
  sendEvent('path_received', { path_id: 22 }, t0 + 20_000, t0 + 1_000);
  const late = traceOf(NAV_TASKS.move)[0];
  if (Math.abs((late?.atSec ?? -1) - 1) > 0.05) failures.push(`늦게 온 사건을 ${late?.atSec}초에 칠했다 — 일어난 1초여야 한다`);
  if (!(late?.payload?.delivered_late_ms >= 18_000)) failures.push('늦게 왔다는 사실(delivered_late_ms)이 안 남는다');
  // 제때 온 사건은 받은 시각 그대로 — 시계 차 추정이 평소 시각을 흔들면 안 된다.
  sendEvent('path_done', { path_id: 22 }, t0 + 30_000);
  const onTime = traceOf(NAV_TASKS.move).find((e) => e.status === 'done');
  if (Math.abs((onTime?.atSec ?? -1) - 30) > 0.05 || 'delivered_late_ms' in (onTime?.payload ?? {})) failures.push('제때 온 사건의 시각을 건드렸다');

  // 대조군 — 시계 차를 모르면(상태가 안 왔으면) 같은 사건이 받은 시각에 칠해진다. 되돌린 것이 시계 차라는 뜻이다.
  approve(AUTO_ID);
  const t1 = navRun().startedAtMs;
  sendEvent('path_received', { path_id: 23 }, t1 + 20_000, t1 + 1_000);
  controls.push('시계 차를 모르면 늦게 온 사건이 받은 시각에 칠해진다');
  if (Math.abs((traceOf(NAV_TASKS.move)[0]?.atSec ?? -1) - 20) > 0.05) failures.push('대조군 실패: 시계 차 없이도 시각이 되돌려진다 — 무엇이 되돌리는지 모른다');
}

// ── 3-2. 실측 한 판 되돌려 보기 (260915 §4.4 · 12:24:00 구간) ─────────────────
//
// 받은 순서가 일어난 순서와 다르고(journal 이 최대 0.5초 늦다), 재탐색 한 번에 PATH_CANCEL 3건과 짝인 estop 3건이 온다.
// 보고서 §4 표의 ts_ms 와 받은 시각(pi1 시계)을 그대로 넣는다 — 받은 시각은 가시화 시계로 옮겨 넣는다.
async function replay4_4(options = {}) {
  const run = approve(AUTO_ID);
  // 판을 연 순간을 pi1 시각 …640000 에 맞추고, 받은 시각은 그 뒤 몇 ms 인가로 옮긴다. ts_ms 는 pi1 시계 그대로 둔다.
  const PI0 = 1789442640000;
  const recv = (piRecvMs) => run.startedAtMs + (piRecvMs - PI0);
  const ts = (piTsMs) => piTsMs;
  // 흐름 (보고서 §4 표 seq 18~25 — 받은 순서 그대로)
  const flow = [
    ['estop', {}, 640978, 640978],
    ['estop', {}, 641089, 641089],
    ['path_received', { path_id: 1, point_count: 8, source: 'journal' }, 641091, 640839],
    ['path_cancel', { path_id: 1, source: 'journal' }, 641093, 640979],
    ['path_cancel', { path_id: 1, source: 'journal' }, 641093, 641089],
    ['estop', {}, 641188, 641187],
    ['path_cancel', { path_id: 1, source: 'journal' }, 641431, 641189],
    ['path_received', { path_id: 1, point_count: 7, source: 'journal' }, 647664, 647663],
  ].filter(([kind]) => !(options.dropCancels && kind === 'path_cancel'));
  for (const [kind, over, piRecv, piTs] of flow) {
    queueEvent(kind, { source: 'udp15100_estop', ...over }, recv(1789442000000 + piRecv), ts(1789442000000 + piTs));
  }
  if (options.wait) await new Promise((resolve) => setTimeout(resolve, NAV_REORDER_MS + 400));
  else drainNavEvents();
  return { move: traceOf(NAV_TASKS.move), replan: traceOf(NAV_TASKS.replan) };
}
{
  // 실제 타이머로 창(NAV_REORDER_MS)이 지나기를 기다린다 — drain 으로 건너뛰지 않는다.
  const { move, replan } = await replay4_4({ wait: true });
  if (move.some((e) => e.status === 'failed')) failures.push('실측 재탐색에서 이동이 실패로 칠해졌다 — PATH_CANCEL 과 짝인 estop 을 비상 정지로 읽었다');
  if (move[0]?.status !== 'running' || move[0]?.attempt !== 1) failures.push('늦게 발행된 path_received 가 이동 1회차 시작으로 안 들어갔다 — 순서를 ts_ms 로 안 맞췄다');
  if (move[1]?.status !== 'done' || move[1]?.payload?.ended_by !== 'path_cancel') failures.push('취소가 이동 1회차를 끝내지 않는다(실측 흐름)');
  if (replan.filter((e) => e.kind === 'started' || e.kind === 'derived').length !== 1) failures.push(`재탐색 한 번이 ${replan.filter((e) => e.kind === 'started' || e.kind === 'derived').length}회로 셌다 — PATH_CANCEL 3건은 한 번이다`);
  if (!replan.some((e) => e.status === 'done')) failures.push('새 경로가 재탐색을 끝내지 않는다(실측 흐름)');
  const second = move.find((e) => e.attempt === 2);
  if (second?.status !== 'rerunning') failures.push('새 경로가 이동 2회차가 아니다(실측 흐름)');
  const estops = feed.navFeedState().events.filter((e) => e.event === 'estop');
  if (estops.length !== 3 || !estops.every((e) => feed.isCancelStop(e))) failures.push('짝인 estop 셋을 취소용 정지로 못 알아본다');

  // 짝 없는 estop 은 여전히 비상 정지다.
  {
    approve(AUTO_ID);
    const t = navRun().startedAtMs;
    sendEvent('path_received', { path_id: 1 }, t + 1000);
    sendEvent('estop', { source: 'udp15100_estop' }, t + 5000);
    const failed = traceOf(NAV_TASKS.move).find((e) => e.status === 'failed');
    if (failed?.payload?.code !== 'estop') failures.push('짝 없는 estop 이 비상 정지로 안 칠해진다');
  }
  // 12:22:15 구간 — **이동 중에** estop 셋이 먼저 오고 짝인 PATH_CANCEL 셋은 journal 로 0.3~0.5초 뒤에 온다.
  // 들고 있지 않으면 첫 estop 을 받는 순간 짝이 아직 없어 이동을 실패로 칠한다. 들고 있는 창이 막는 자리다.
  const replay2215 = async (immediate) => {
    const run = approve(AUTO_ID);
    const PI0 = 1789442535000;
    const at = (pi) => run.startedAtMs + (pi - PI0);
    const flow = [
      ['path_received', { path_id: 1, point_count: 7, source: 'journal' }, 1789442536182, 1789442535929],
      ['estop', { source: 'udp15100_estop' }, 1789442537698, 1789442537697],
      ['estop', { source: 'udp15100_estop' }, 1789442537793, 1789442537793],
      ['estop', { source: 'udp15100_estop' }, 1789442537905, 1789442537905],
      ['path_cancel', { path_id: 1, source: 'journal' }, 1789442538178, 1789442537697],
      ['path_cancel', { path_id: 1, source: 'journal' }, 1789442538179, 1789442537793],
      ['path_cancel', { path_id: 1, source: 'journal' }, 1789442538179, 1789442537905],
      ['path_received', { path_id: 1, point_count: 5, source: 'journal' }, 1789442543846, 1789442543843],
    ];
    for (const [kind, over, piRecv, piTs] of flow) {
      queueEvent(kind, over, at(piRecv), piTs);
      if (immediate) drainNavEvents();
    }
    if (!immediate) await new Promise((resolve) => setTimeout(resolve, NAV_REORDER_MS + 400));
    return traceOf(NAV_TASKS.move);
  };
  const held = await replay2215(false);
  if (held.some((e) => e.status === 'failed')) failures.push('12:22 실측 흐름에서 이동이 실패로 칠해졌다 — 짝이 오기 전의 estop 을 비상 정지로 읽었다');
  if (held.at(-1)?.attempt !== 2 || held.at(-1)?.status !== 'rerunning') failures.push('12:22 실측 흐름이 이동 2회차로 안 이어진다');
  // 대조군 — 들고 있지 않고 받는 즉시 적용하면 같은 흐름이 실패로 칠해진다. 막은 것이 창이라는 뜻이다.
  const immediate = await replay2215(true);
  controls.push('창 없이 받는 즉시 적용하면 12:22 흐름이 실패로 칠해진다');
  if (!immediate.some((e) => e.status === 'failed')) failures.push('대조군 실패: 창 없이도 실패로 안 칠해진다 — 창이 무엇을 막는지 검사가 모른다');

  // 대조군 — 짝인 PATH_CANCEL 을 빼면 같은 estop 이 비상 정지가 된다. 막은 것이 짝이라는 뜻이다.
  const noPair = await replay4_4({ dropCancels: true });
  controls.push('짝인 PATH_CANCEL 을 빼면 같은 estop 이 이동을 실패로 만든다');
  if (!noPair.move.some((e) => e.status === 'failed')) failures.push('대조군 실패: PATH_CANCEL 없이도 estop 이 무시된다 — 무엇이 거르는지 모른다');
}

// ── 4. 배터리 기준 미만 ──────────────────────────────────────────────────────
{
  approve(AUTO_ID);
  sendState({ battery_pct: 18 }, Date.now());
  const failed = traceOf(NAV_TASKS.battery).find((e) => e.status === 'failed');
  if (failed?.payload?.code !== 'battery_too_low' || failed?.payload?.battery_pct !== 18) failures.push('배터리 18% 가 기준 미만 실패로 안 남는다');
  // 배터리 null 이면 판정하지 않는다 — 0% 로 실패시키지 않는다.
  approve(AUTO_ID);
  sendState({ battery_pct: null, yaw_deg: 3 }, Date.now());
  const status = folded().tasks[NAV_TASKS.battery]?.status;
  if (status !== 'running') failures.push(`배터리 null 인데 배터리 확인이 ${status} — 모르면 진행 중으로 남아야 한다`);
}

// ── 5. 시연 편에 새지 않는다 ─────────────────────────────────────────────────
{
  approve(DOOR_ID);
  if (navRun() !== null) failures.push('시연 편을 승인했는데 중계 판이 열렸다');
  if (!session.robotSession().approved) failures.push('시연 편 승인이 로봇 관문을 안 연다 — 시연이 멈춘다');
  sendState({}, Date.now());
  sendEvent('path_received', { path_id: 11 }, Date.now());
  const leaked = scenario.traceEvents().filter((e) => Object.values(NAV_TASKS).includes(e.nodeId) || e.seq >= 6_000_000);
  if (leaked.length > 0) failures.push(`시연 편 기록 열에 중계 사건 ${leaked.length}건이 들어갔다`);
  // 대조군 — 시연 편인데 판을 억지로 열면 칠한다. 막은 것이 「판이 안 열림」이라는 뜻이다.
  beginNavRun(DOOR_ID);
  sendState({}, Date.now());
  controls.push('시연 편에 판을 억지로 열면 칠한다');
  if (!scenario.traceEvents().some((e) => e.seq >= 6_000_000)) failures.push('대조군 실패: 판을 열어도 안 칠한다 — 5절 검사가 헛돈다');
  endNavRun();
  scenario.resetMission();

  const { CHECKED_TARGETS } = await load('src', 'shared', 'connectionHealth.ts');
  if (CHECKED_TARGETS.includes('autodrive')) failures.push('pi1 이 머리줄 표시등 목록에 들어갔다 — 시연의 「n/4 확인됨」이 바뀐다');
  const { CONNECTION_TARGETS, connectionAddress } = await load('src', 'shared', 'connections.ts');
  if (!CONNECTION_TARGETS.some((t) => t.id === 'autodrive' && t.live)) failures.push('연결 관리에 pi1 대상이 없다');
  await load('src', 'physical', 'PhysicalClient.ts');
  await load('src', 'physical', 'NavClient.ts');
  if (!/pi7\./.test(connectionAddress('physical', 'ws'))) failures.push(`시연 로봇 주소가 ${connectionAddress('physical', 'ws')} — pi7 이어야 한다`);
  if (connectionAddress('autodrive', 'ws') === connectionAddress('physical', 'ws')) failures.push('pi1 과 pi7 이 같은 주소를 본다');
}

// ── 6. 연결 확인 — 브로커 · 중계 두 줄 ──────────────────────────────────────
{
  const probe = (over = {}) => ({ getStatus: () => ({ state: 'open' }), connect: async () => ({ state: 'open' }), latest: () => null, ...over });
  const alive = await checkAutodrive(probe({ latest: () => ({ receivedAtMs: Date.now() + 50, nodeId: 'pi1', entityId: 'go1-001', batteryPct: 82, yawDeg: -12.5, yawSource: 'bridge_state' }) }), 300);
  if (alive[0]?.ok !== true || alive[1]?.ok !== true) failures.push('중계가 오는데 두 줄이 초록이 아니다');
  if (!/배터리 82%/.test(String(alive[1]?.reason))) failures.push('중계 줄에 받은 값이 안 적힌다');
  const silent = await checkAutodrive(probe(), 300);
  if (silent[0]?.ok !== true || silent[1]?.ok !== false) failures.push('브로커는 붙었는데 중계가 안 올 때 중계 줄만 빨갛지 않다');
  // 붙기 전에 온 값은 살아 있다는 증거가 아니다.
  const old = await checkAutodrive(probe({ latest: () => ({ receivedAtMs: Date.now() - 60_000, nodeId: 'pi1', entityId: '', batteryPct: null, yawDeg: null, yawSource: null }) }), 300);
  if (old[1]?.ok !== false) failures.push('확인 전에 받은 옛 값으로 중계를 초록으로 칠했다');
  const dead = await checkAutodrive(probe({ getStatus: () => ({ state: 'closed' }), connect: async () => ({ state: 'closed', reason: '주소가 비어 있습니다' }) }), 300);
  if (dead[0]?.ok !== false || dead[1]?.ok !== null) failures.push('브로커가 없을 때 중계 줄이 「못 물어봤다」가 아니다');
  const { navClient } = await load('src', 'physical', 'NavClient.ts');
  const { connectionAddress: addressOf, registerConnectionDefault } = await load('src', 'shared', 'connections.ts');
  // 260915 — pi1 이 보고한 이름이 기본값이다. 검사는 실제 테일넷에 붙지 않게 잠깐 비운다.
  const seeded = addressOf('autodrive', 'ws');
  if (seeded !== 'ws://pi1.tailcb6bfb.ts.net:9001/mqtt') failures.push(`pi1 기본 주소가 ${seeded} — 보고된 Tailscale 이름이어야 한다`);
  registerConnectionDefault('autodrive', 'ws', '');
  const empty = await navClient().connect();
  registerConnectionDefault('autodrive', 'ws', seeded);
  if (empty.state !== 'closed' || !/주소가 비어/.test(String(empty.reason))) failures.push('주소가 빈 채로 붙으려 할 때 사유를 안 말한다');
}

// ── 7. 경계 — 보내지 않는다 · 토픽은 src/physical/ 안에만 ──────────────────────
{
  const client = read('src', 'physical', 'NavClient.ts');
  if (/\.publish\s*\(|\bsend\s*\(/.test(client.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, ''))) {
    failures.push('NavClient 가 무언가를 보낸다 — 자율주행 편은 받기만 한다');
  }
  const walk = (dir) => readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    // 남의 대조군 잔여물을 내 판정에 넣지 않는다 (260917 — 검사 위생 §3①).
    if (isScratchPath(full)) return [];
    return statSync(full).isDirectory() ? walk(full) : /\.(ts|tsx)$/.test(name) ? [full] : [];
  });
  for (const file of walk(join(root, 'src'))) {
    const rel = relative(root, file);
    if (rel.startsWith(join('src', 'physical'))) continue;
    if (/nav_state|nav_event|\/robot\/\+\//.test(readFileSync(file, 'utf8'))) failures.push(`${rel}: 중계 토픽이 경계 밖에 있다`);
  }
}

if (failures.length) {
  console.error(`❌ verify:nav-feed\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 뜯기 — schema 가 다르면 버리고 센다 · 배터리 null/범위 밖은 모름 · 출처 없는 yaw 는 버림 · QoS 1 중복 흡수');
console.log('✅ 한 판 — 배터리(평가) → yaw → 이동 1 → 취소·ACK → 재탐색 → 이동 2(derived) → 재탐색 2 → 이동 3 → 경로 끝');
console.log('✅ 승인은 판을 걸기만 · 「임무 시작」이 연다 · 시작 전 중계는 안 칠함 · 승인 없이 시작 없음');
console.log('✅ 받은 것으로 끝내는 넷 — 첫 경로=이동경로 탐색 · 장애물 JSON=장애물 탐지(바뀔 때만 줄) · 경로 끝=목적지 도착(평가) · 임무 종료 → 여덟 다 완료 · 종료 뒤 사건 무시');
console.log('✅ 재탐색 없으면 0회 완료 · 장애물 JSON 없으면 탐지는 대기(MS-B 미완) · 이동 없이 온 경로 끝은 도착 아님');
console.log('✅ 정지·일시정지 — pi7 로 안 보냄 · 못 보냈다고 남김 · 멈춘 동안 안 칠함 · 정지 해제면 다시 승인');
console.log('✅ 판 열기 전 사건·10초 묵은 상태·정지 뒤 사건은 안 칠함 · 배터리 기준 미만은 실패 · null 은 진행 중으로 남음');
console.log('✅ 실측 §4.4 흐름 — ts_ms 순으로 적용(늦게 발행된 path_received 가 앞) · PATH_CANCEL 3건 = 재탐색 1회 · 짝인 estop 은 실패로 안 칠함 · 짝 없는 estop 은 비상 정지');
console.log('✅ 늦게 온 사건(pi1 큐) — 시계 차(nav_state 중앙값)로 일어난 시각에 칠함 · 판 전에 일어난 것은 버림 · 제때 온 것은 받은 시각 그대로');
console.log('✅ 시연 편 — 중계 판 안 열림 · 기록 열 누수 0 · 로봇 관문 그대로 · 표시등 목록·pi7 주소 그대로');
console.log('✅ 연결 확인 — 브로커·중계 두 줄 · 확인 뒤에 온 값만 살아 있다고 봄 · 빈 주소는 사유를 말함 · NavClient 는 보내지 않음');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
