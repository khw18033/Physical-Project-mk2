// verify:seq-mission (261113 신설 — 드론 복합 이동 미션)
//
// **화면이 pi3 의 `mission_seq.py` · `seq_plan.py` 와 같은 말을 하는가** (`MISSION_SEQ_요청_VZ.md`).
//
//  1. 시험 벡터 (§6) — 요청 문서 표의 세 미션에서 미션 키 · sha256 앞 16자 · 단계 끝 (fwd, right, yaw) 가 같은가.
//     더해 **드론 `seq_plan.py` 를 직접 돌려 뽑은 계획** 하나(270° 회전 조각 · 캡처 사이 쉼 · home 복귀 · 고도 7.5 · 속도 1.5)와
//     키 · 해시 · 단계 끝 · 끝 기수 · 최대 거리 · 총 이동 · 착륙점이 같은가 (pi3 drone-all eeea4b5, h0 123.4°)
//  2. 파라미터 (§3) — 규약 키 · 번호로 바뀌는가. 단계 속도는 정했을 때만, 캡처는 늘. dry-run 은 confirmed 가 없다
//  3. 검사 — 범위 · 개수 · 회전에 준 속도 · 최대 거리 · 총 이동 300 m 를 거르는가. 정상 미션은 통과하는가
//  4. 상태 토픽 (§4) — `mission_run` 을 읽고, 계획이 없으면 `[계획]` 줄로 물러서고, 모양이 틀리면 버리는가
//  5. 출력 읽기 (§5-2) — `[미션] 진행 #n` → 역할 → 단계, `STEP k/N END` 의 오차, `CAP k`, `[경고]`
//  6. 가짜 드론 — dry-run 이 키 · 해시 · 계획을 돌려주고(항목 역할이 드론 `seq_plan.build` 와 같은 구성), 짧은 비행이
//     단계마다 END 를 찍고 착륙하며, 왕복 시험과 서로 배제되는가
//
// 대조군 — 다른 미션의 키는 달라야 하고, 실행기 모양 검사는 모르는 키를 거절해야 한다.

import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const seq = await load('src', 'physical', 'seqPlan.ts');
const feed = await load('src', 'physical', 'missionRunFeed.ts');

const failures = [];
const controls = [];
const S = (kind, value, speedMps = null, capture = false) => ({ kind, value, speedMps, capture });
const M = (steps, land = 'here', extra = {}) => ({ altitudeM: 5, speedMps: 1, land, abort: 'rtl', maxRadiusM: 30, steps, ...extra });
const sha16 = (text) => createHash('sha256').update(text).digest('hex').slice(0, 16);
const near = (a, b) => Math.abs(a - b) < 1e-3;

// ── 1. 시험 벡터 ────────────────────────────────────────────────────────
{
  const vectors = [
    [M([S('right', 3), S('forward', 1)]), 'v1|alt=5|spd=1|land=here|right:3;forward:1', '2dd3a3eb1614f461',
      [[0, 3, 0], [1, 3, 0]]],
    [M([S('cw', 90), S('forward', 2), S('ccw', 45), S('back', 1.5)], 'home'), 'v1|alt=5|spd=1|land=home|cw:90;forward:2;ccw:45;back:1.5', '80739eedc8f1640d',
      [[0, 0, 90], [0, 2, 90], [0, 2, 45], [-1.061, 0.939, 45]]],
    [M([S('forward', 2, null, true), S('hover', 5), S('right', 2, 0.5, true)]), 'v1|alt=5|spd=1|land=here|forward:2+cap;hover:5;right:2@0.5+cap', 'f64a7ad0a0b01e83',
      [[2, 0, 0], [2, 0, 0], [2, 2, 0]]],
  ];
  for (const [mission, key, hash, ends] of vectors) {
    const got = seq.missionKey(mission);
    if (got !== key) failures.push(`미션 키: ${got} ≠ ${key}`);
    if (sha16(got) !== hash) failures.push(`해시: ${sha16(got)} ≠ ${hash} (${key})`);
    const preview = seq.previewOf(mission);
    ends.forEach(([fwd, right, yaw], index) => {
      const end = preview.ends[index];
      if (end === undefined || !near(end.fwd, fwd) || !near(end.right, right) || !near(end.yaw, yaw)) {
        failures.push(`${key} 단계 ${index + 1} 끝: ${JSON.stringify(end)} ≠ (${fwd}, ${right}, ${yaw})`);
      }
    });
  }
  // 드론 seq_plan.py 가 낸 계획 (pi3 drone-all eeea4b5 — `seq_plan.build(..., h0=123.4)` 의 to_json 에서 옮김)
  const DRONE = {
    mission: M([S('right', 2), S('cw', 270), S('forward', 1, 2, true), S('left', 4.25), S('ccw', 100), S('back', 3, null, true)], 'home', { altitudeM: 7.5, speedMps: 1.5 }),
    key: 'v1|alt=7.5|spd=1.5|land=home|right:2;cw:270;forward:1@2+cap;left:4.25;ccw:100;back:3+cap', hash: '83a3e9916ed4619c',
    ends: [[0, 2, 123.4], [0, 2, 33.4], [0, 1, 33.4], [-4.25, 1, 33.4], [-4.25, 1, 293.4], [-1.296, 0.479, 293.4]],
    maxR: 4.37, pathM: 11.63,
  };
  {
    const got = seq.missionKey(DRONE.mission);
    if (got !== DRONE.key || sha16(got) !== DRONE.hash) failures.push(`드론 계획 키 · 해시: ${got} ${sha16(got)}`);
    const preview = seq.previewOf(DRONE.mission);
    DRONE.ends.forEach(([fwd, right, yaw], index) => {
      const end = preview.ends[index];
      const abs = (((123.4 + end.yaw) % 360) + 360) % 360;
      if (Math.abs(end.fwd - fwd) > 2e-3 || Math.abs(end.right - right) > 2e-3 || Math.abs(abs - yaw) > 0.01) failures.push(`드론 계획 단계 ${index + 1}: ${JSON.stringify(end)} ≠ ${fwd},${right},${yaw}`);
    });
    if (Math.abs(preview.maxR - DRONE.maxR) > 0.01 || Math.abs(preview.pathM - DRONE.pathM) > 0.01) failures.push(`드론 계획 거리: ${preview.maxR} ${preview.pathM}`);
    if (preview.land.fwd !== 0 || preview.land.right !== 0) failures.push('드론 계획 착륙점(home)');
    if (seq.seqProblems(DRONE.mission).length !== 0) failures.push('드론이 받는 미션을 화면이 거른다');
  }
  // home 착륙은 L, here 는 마지막 자리
  const home = seq.previewOf(vectors[1][0]);
  if (home.land.fwd !== 0 || home.land.right !== 0) failures.push('home 착륙점이 L 이 아니다');
  const here = seq.previewOf(vectors[0][0]);
  if (here.land.fwd !== 1 || here.land.right !== 3) failures.push(`here 착륙점: ${JSON.stringify(here.land)}`);
  // 총 이동 — home 은 마지막 → L 포함
  if (!near(seq.previewOf(vectors[0][0]).pathM, 4)) failures.push(`총 이동(here): ${seq.previewOf(vectors[0][0]).pathM}`);
  if (!near(home.pathM, 3.5 + Math.hypot(-1.061, 0.939))) failures.push(`총 이동(home): ${home.pathM}`);
  // 북 · 동 — 요청 문서 §5-1 예: h0 123.4° 의 오른쪽 3m = (n -2.504, e -1.651)
  const ne = seq.bodyToNe(123.4, { fwd: 0, right: 3 });
  if (!near(Math.round(ne.n * 1000) / 1000, -2.504) || !near(Math.round(ne.e * 1000) / 1000, -1.651)) failures.push(`북 · 동 변환: ${JSON.stringify(ne)}`);
  // f(x) — 1.23456 → 1.235, 0.5 → 0.5
  if (seq.fmt3(1.23456) !== '1.235' || seq.fmt3(0.5) !== '0.5' || seq.fmt3(3) !== '3') failures.push('f(x) 자리수');
  // 대조군 — 다른 미션은 다른 키
  if (seq.missionKey(M([S('right', 3), S('forward', 1)])) === seq.missionKey(M([S('forward', 1), S('right', 3)]))) failures.push('대조군: 순서가 다른 미션의 키가 같다');
  else controls.push('순서가 다르면 키가 다르다');
}

// ── 2. 파라미터 ─────────────────────────────────────────────────────────
{
  const mission = M([S('right', 3), S('cw', 90), S('forward', 2, 0.5, true), S('hover', 5)], 'home', { abort: 'land', maxRadiusM: 20 });
  const fly = seq.seqStartParams(mission, { dryRun: false, confirmed: true });
  const want = {
    altitude_m: 5, step_count: 4, speed_mps: 1, land: 1, abort: 2, max_radius_m: 20, dry_run: 0, confirmed: 1,
    s1_kind: 2, s1_value: 3, s1_capture: 0,
    s2_kind: 4, s2_value: 90, s2_capture: 0,
    s3_kind: 0, s3_value: 2, s3_speed_mps: 0.5, s3_capture: 1,
    s4_kind: 6, s4_value: 5, s4_capture: 0,
  };
  if (JSON.stringify(Object.entries(fly).sort()) !== JSON.stringify(Object.entries(want).sort())) failures.push(`비행 파라미터: ${JSON.stringify(fly)}`);
  const dry = seq.seqStartParams(mission, { dryRun: true, confirmed: true });
  if (dry.dry_run !== 1 || 'confirmed' in dry) failures.push(`dry-run 파라미터: ${JSON.stringify(dry)}`);
  if (Object.values(fly).some((v) => typeof v !== 'number' || !Number.isFinite(v))) failures.push('숫자가 아닌 값이 실렸다(map<string,double>)');
  if (seq.seqSignature(mission) === seq.seqSignature({ ...mission, maxRadiusM: 25 })) failures.push('최대 거리가 달라도 서명이 같다');
  // 종류를 회전으로 바꾸면 단계 속도가 지워진다
  if (seq.withKind(S('forward', 2, 0.5), 'cw').speedMps !== null) failures.push('회전으로 바꿨는데 단계 속도가 남았다');
  if (seq.withKind(S('forward', 40), 'cw').value !== 40 && seq.withKind(S('forward', 40), 'hover').value !== 5) failures.push('종류를 바꿀 때 값 범위 맞추기');
}

// ── 3. 검사 ─────────────────────────────────────────────────────────────
{
  const kinds = (m) => seq.seqProblems(m).map((p) => `${p.field}:${p.kind}`);
  if (seq.seqProblems(seq.SEQ_DEFAULTS).length !== 0) failures.push(`기본 미션에 문제가 있다고 한다: ${JSON.stringify(seq.seqProblems(seq.SEQ_DEFAULTS))}`);
  if (!kinds(M([S('forward', 60)])).includes('step:value')) failures.push('이동 60 m 를 못 거른다(상한 50)');
  if (!kinds(M([S('cw', 400)])).includes('step:value')) failures.push('회전 400° 를 못 거른다');
  if (!kinds(M([S('hover', 0.5)])).includes('step:value')) failures.push('대기 0.5 초를 못 거른다(하한 1)');
  if (!kinds(M([S('cw', 90, 1)])).includes('step:speedNotMove')) failures.push('회전 단계 속도를 못 거른다(스크립트 종료 코드 2)');
  if (!kinds(M([S('forward', 2, 7)])).includes('step:speed')) failures.push('단계 속도 7 m/s 를 못 거른다');
  if (!kinds(M([])).includes('steps:count')) failures.push('단계 0개를 못 거른다');
  if (!kinds(M(Array.from({ length: 21 }, () => S('hover', 1)))).includes('steps:count')) failures.push('단계 21개를 못 거른다');
  if (!kinds(M([S('forward', 40)])).includes('radius:radius')) failures.push('40 m 가 최대 거리 30 m 를 넘는 것을 못 거른다');
  if (kinds(M([S('forward', 40)], 'here', { maxRadiusM: 50 })).length !== 0) failures.push('최대 거리 50 이면 40 m 는 통과해야 한다');
  const zigzag = M(Array.from({ length: 8 }, (_, i) => S(i % 2 === 0 ? 'forward' : 'back', 40)), 'here', { maxRadiusM: 50 });
  if (!kinds(zigzag).includes('path:path')) failures.push('총 이동 320 m 를 못 거른다(상한 300)');
  if (!kinds(M([S('forward', 2)], 'here', { altitudeM: 40 })).includes('altitudeM:range')) failures.push('고도 40 m 를 못 거른다');
}

// ── 4. 상태 토픽 ────────────────────────────────────────────────────────
const PLAN = {
  v: 1, key: 'v1|alt=5|spd=1|land=here|right:3;forward:1', hash: '2dd3a3eb1614f461', L: [36.35, 127.3], h0: 123.4,
  alt: 5, speed: 1, land: 'here', est_s: 47, timeout_s: 154, max_r: 3.16, path_m: 4.0, n_items: 7,
  roles: [['takeoff', 0], ['align', 0], ['speed', 1], ['move', 1], ['speed', 2], ['move', 2], ['land', 0]],
  steps: [
    { k: 1, kind: 'right', value: 3, speed: null, cap: false, label: '오른쪽 3m', text: 'right:3', seq: [2, 3], yaw: 123.4,
      from: { n: 0, e: 0, fwd: 0, right: 0, lat: 36.35, lon: 127.3 }, to: { n: -2.504, e: -1.651, fwd: 0, right: 3, lat: 36.34998, lon: 127.29998 } },
    { k: 2, kind: 'forward', value: 1, speed: null, cap: true, label: '앞 1m', text: 'forward:1', seq: [4, 5], yaw: 123.4,
      from: { n: -2.504, e: -1.651, fwd: 0, right: 3, lat: 36.34998, lon: 127.29998 }, to: { n: -3.054, e: -0.816, fwd: 1, right: 3, lat: 36.34997, lon: 127.29999 } },
  ],
  land_pt: { n: -3.054, e: -0.816, fwd: 1, right: 3, lat: 36.34997, lon: 127.29999 },
};
const RUN = (extra = {}) => ({
  run_id: '20261113_101500', command_id: 'cmd-1', state: 'running', dry_run: false, exit_code: null,
  argv: ['--yes', '--step', 'right:3', '--step', 'forward:1'], started_at: 1794576300, ended_at: null, out_path: '/x.out',
  script: 'mission_seq.py', rtk: false, lines: [], steps: ['right:3', 'forward:1'], plan: PLAN,
  mission_key: PLAN.key, mission_hash: PLAN.hash, ...extra,
});
{
  const report = feed.parseMissionRun({ schema_version: '1', source_id: 'x500-001', runner: 'mission_seq', run: RUN() }, 'zoneA/drone/x500-001/mission_run');
  if (report === null || report.run === null) failures.push('정상 mission_run 을 못 읽었다');
  else {
    const run = report.run;
    if (run.missionKey !== PLAN.key || run.missionHash !== PLAN.hash || run.steps.length !== 2) failures.push(`키 · 단계: ${run.missionKey} ${run.steps}`);
    if (run.plan?.h0 !== 123.4 || run.plan.steps[1]?.to?.fwd !== 1 || run.plan.roles[3]?.[0] !== 'move' || run.plan.nItems !== 7) failures.push(`계획: ${JSON.stringify(run.plan)}`);
    if (run.rtk !== false || run.script !== 'mission_seq.py') failures.push('rtk · script');
  }
  if (!feed.missionRunChannel('zoneA/drone/x500-001/mission_run') || feed.missionRunChannel('zoneA/drone/x500-001/flight_run')) failures.push('토픽 가르기');
  // 계획이 null 이면 `[계획]` 줄로 물러선다
  const fromLine = feed.parseMissionRun({ source_id: 'x', run: RUN({ plan: null, mission_key: null, mission_hash: null,
    lines: [{ seq: 1, text: `[1794576300.100] [계획] ${JSON.stringify(PLAN)}` }] }) });
  if (fromLine?.run?.plan?.key !== PLAN.key || fromLine.run.missionKey !== PLAN.key) failures.push('`[계획]` 줄로 물러서지 못했다');
  // 범위 오류 — 계획 null, 키 없음
  const bad = feed.parseMissionRun({ source_id: 'x', run: RUN({ plan: null, mission_key: null, mission_hash: null, state: 'exited', exit_code: 2,
    lines: [{ seq: 1, text: 'mission_seq.py: error: --step forward:60: 1~50 m' }] }) });
  if (bad?.run?.plan !== null || bad.run.missionKey !== null || bad.run.exitCode !== 2) failures.push('범위 오류 실행에 계획 · 키가 생겼다');
  // 대조군 — 모양이 틀리면 버린다
  if (feed.parseMissionRun({ source_id: 'x', run: { state: 'running' } }) !== null) failures.push('대조군: run_id 없는 실행을 받았다');
  else controls.push('run_id 없는 실행은 버린다');
  if (feed.parseSeqPlan({ steps: [] }) !== null) failures.push('대조군: key 없는 계획을 받았다');
  else controls.push('key 없는 계획은 버린다');
  // 같은 실행의 다음 보고에 계획이 빠져도 앞 계획을 지킨다
  feed.resetMissionRuns();
  feed.noteMissionRun(report);
  feed.noteMissionRun(feed.parseMissionRun({ source_id: 'x500-001', run: RUN({ plan: null, mission_key: null, mission_hash: null }) }));
  if (feed.missionRuns()['x500-001']?.run?.plan?.key !== PLAN.key) failures.push('같은 실행인데 계획을 잃었다');
}

// ── 5. 출력 읽기 ────────────────────────────────────────────────────────
{
  const at = (t) => `[1794576334.685] ${t}`;
  const lines = [
    at('[연결] 완료'), at('[확인] 위치 추정 정상 ✔'), at(`[계획] ${JSON.stringify(PLAN)}`),
    at('[미션] #0  TAKEOFF'), at('[미션] #6  LAND'), at('[미션] 업로드 (7개 항목)...'), at('[미션] 대조 일치 ✔'), at('[명령] arm'),
    at('[명령] 미션 시작'),
    at('[미션] 진행 #3  WAYPOINT 단계 1 오른쪽 3m  36.35, 127.30  고도 5m  헤딩 123.4°  대기 2s  반경 0.5m'),
    at('STEP 1/2 START t=1794576334.685 오른쪽 3m 고도 5.0m 헤딩 123.4°'),
    '       #3 단계 1/2 오른쪽 3m 진행  1.8/3.0m  속도  1.0m/s  고도   5.0m  헤딩 123.4°',
    at('STEP 1/2 END   t=1794576338.088 dur=3.4s 목표 오차 0.31m 헤딩 123.1°(목표 123.4°, 오차 0.3°) 고도 5.0m'),
    at('[미션] 진행 #5  WAYPOINT 단계 2 앞 1m'),
    at('CAP 2 START t=1794576340.000'),
    at('[경고] 단계 2 기수 오차 16.2° — 15° 초과'),
  ].map((text, index) => ({ seq: index + 1, text }));
  const p = feed.readSeqProgress(lines, PLAN);
  if (p.phase !== 'mission') failures.push(`단계: ${p.phase}`);
  if (p.stepCur !== 2 || p.role !== 'move' || p.stepTotal !== 2) failures.push(`현재 단계: ${p.stepCur} ${p.role} / ${p.stepTotal}`);
  if (!p.stepsDone.has(1) || p.stepsDone.has(2)) failures.push(`끝난 단계: ${[...p.stepsDone]}`);
  const r = p.results[1];
  if (r?.durS !== 3.4 || r.posErrM !== 0.31 || r.yawErrDeg !== 0.3) failures.push(`단계 1 결과: ${JSON.stringify(r)}`);
  if (p.capturingStep !== 2) failures.push(`캡처 중 단계: ${p.capturingStep}`);
  if (p.warningLines.length !== 1 || p.warnings !== 1) failures.push('경고 줄');
  if (p.live === null || !p.live.includes('1.8/3.0m')) failures.push(`실시간 줄: ${p.live}`);
  if (feed.stepState(p, 1) !== 'done' || feed.stepState(p, 2) !== 'active') failures.push('단계 표 상태');
  const done = feed.readSeqProgress([...lines,
    { seq: 100, text: at('CAP 2 END t=1794576342.000') },
    { seq: 101, text: at('STEP 2/2 END   t=1794576342.1 dur=2.0s 목표 오차 0.2m 헤딩 123.0°(목표 123.4°, 오차 0.4°) 고도 5.0m') },
    { seq: 102, text: at('[미션] 진행 #6  LAND') },
    { seq: 103, text: at('[확인] 착륙 완료 ✔') },
    { seq: 104, text: at('[결과] 단계 1 오른쪽 3m: 목표 오차 0.31m · 기수 오차 0.3°') },
  ], PLAN);
  if (done.phase !== 'landed' || done.capturingStep !== null || !done.stepsDone.has(2) || done.role !== 'land') failures.push(`착륙 뒤: ${done.phase} ${done.capturingStep} ${done.role}`);
  if (done.results[1]?.text === null) failures.push('[결과] 줄을 못 읽었다');
  // 단계 밖 진행 줄 — 실물 monitor 는 `#n land  속도 …` 로 역할 이름을 찍는다. 진행 번호가 항목 수(7)에 닿으면 FC 미션 완료.
  const landing = feed.readSeqProgress([...lines.slice(0, 9),
    { seq: 200, text: at('[미션] 진행 #6  LAND') },
    { seq: 201, text: '       #6 land  속도  0.0m/s  고도   2.1m  헤딩 123.4°  ' },
    { seq: 202, text: '       #7 land  속도  0.0m/s  고도   0.0m  헤딩 123.4°  ' },
  ], PLAN);
  if (landing.liveItem !== 7 || !landing.missionDone || landing.live?.includes('#7 land') !== true) failures.push(`착륙 중 진행 줄: liveItem ${landing.liveItem} missionDone ${landing.missionDone}`);
}

// ── 6. 가짜 드론 ────────────────────────────────────────────────────────
{
  const { PhysicalClient } = await load('src', 'physical', 'PhysicalClient.ts');
  const { deviceIdentityFor } = await load('src', 'physical', 'deviceIdentity.ts');
  const { receiveDeviceMessage } = await load('src', 'physical', 'deviceState.ts');
  const { fcxReports } = await load('src', 'shared', 'fcxStatus.ts');
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const until = async (what, cond, ms) => {
    const end = Date.now() + ms;
    while (Date.now() < end) { const v = cond(); if (v) return v; await sleep(50); }
    failures.push(`${what} — ${ms / 1000}초 안에 안 됐다`);
    return null;
  };
  const command = async (c, action, params, waitResult = true, ms = 4000) => {
    const seen = [];
    const off = c.onMessage((m) => seen.push(m));
    const out = c.send(action, params);
    if (!out.sent) { off(); failures.push(`${action} 를 못 보냈다`); return { seen, out }; }
    await until(`${action} 응답`, () => seen.find((m) => m.commandId === out.commandId && (waitResult ? m.kind === 'result' : m.kind === 'acceptance')), ms);
    off();
    return { seen: seen.filter((m) => m.commandId === out.commandId), out };
  };
  feed.resetMissionRuns();
  const drone = new PhysicalClient('fake:drone');
  drone.onDevice((topic, body, origin) => receiveDeviceMessage(topic, body, origin));
  await drone.connect(2000);
  const who = await until('가짜 드론 자기소개', () => deviceIdentityFor('fake:drone'), 2000);
  if (who !== null && !who.actions?.includes('seq_mission_start')) failures.push('가짜 드론이 seq_mission_start 를 선언하지 않았다');
  await until('fcx', () => fcxReports()['x500-fake'], 2000);
  const run = () => feed.missionRuns()['x500-fake']?.run ?? null;

  // 모양 검사 — 모르는 키는 수락 전에 거절(대조군)
  const odd = await command(drone, 'seq_mission_start', { ...seq.seqStartParams(M([S('right', 2)]), { dryRun: true, confirmed: false }), s1_banana: 1 }, false);
  if (!odd.seen.some((m) => m.kind === 'acceptance' && !m.accepted)) failures.push('대조군: 모르는 키를 받아들였다');
  else controls.push('모르는 키는 수락 전에 거절');

  // dry-run — 계획 · 키 · 해시
  const mission = M([S('right', 2), S('cw', 90), S('forward', 1, 2, true)], 'home', { altitudeM: 2, speedMps: 2 });
  const dry = await command(drone, 'seq_mission_start', seq.seqStartParams(mission, { dryRun: true, confirmed: false }));
  await until('dry-run 종료', () => run()?.commandId === dry.out.commandId && run()?.state === 'exited', 6000);
  const dr = run();
  if (dr?.exitCode !== 0 || dr.missionKey !== seq.missionKey(mission) || dr.missionHash !== sha16(seq.missionKey(mission))) {
    failures.push(`dry-run: 코드 ${dr?.exitCode} 키 ${dr?.missionKey} 해시 ${dr?.missionHash}`);
  }
  const preview = seq.previewOf(mission);
  dr?.plan?.steps.forEach((step, index) => {
    const end = preview.ends[index];
    if (!near(step.to.fwd, end.fwd) || !near(step.to.right, end.right)) failures.push(`계획 단계 ${step.k} 끝이 미리보기와 다르다`);
  });
  if (fcxReports()['x500-fake']?.armed !== false) failures.push('dry-run 인데 arm 됐다');
  // 항목 역할 — 드론 seq_plan.build 가 같은 미션에 내는 구성(home 복귀 앞 speed 0)
  const wantRoles = [['takeoff', 0], ['align', 0], ['speed', 1], ['move', 1], ['rot', 2], ['speed', 3], ['move', 3], ['speed', 0], ['return', 0], ['land', 0]];
  if (JSON.stringify(dr?.plan?.roles) !== JSON.stringify(wantRoles)) failures.push(`가짜 드론 항목 역할: ${JSON.stringify(dr?.plan?.roles)}`);
  // 큰 미션도 드론과 같은 역할 구성인가 — 위 DRONE 계획(270° 조각 · 쉼)과 비교
  const big = await command(drone, 'seq_mission_start', seq.seqStartParams(
    M([S('right', 2), S('cw', 270), S('forward', 1, 2, true), S('left', 4.25), S('ccw', 100), S('back', 3, null, true)], 'home', { altitudeM: 7.5, speedMps: 1.5 }),
    { dryRun: true, confirmed: false }));
  await until('큰 미션 dry-run 종료', () => run()?.commandId === big.out.commandId && run()?.state === 'exited', 6000);
  const droneRoles = [['takeoff', 0], ['align', 0], ['speed', 1], ['move', 1], ['rot', 2], ['rot', 2], ['rot', 2], ['speed', 3], ['move', 3], ['rest', 3],
    ['speed', 4], ['move', 4], ['rot', 5], ['rot', 5], ['speed', 6], ['move', 6], ['speed', 0], ['return', 0], ['land', 0]];
  if (JSON.stringify(run()?.plan?.roles) !== JSON.stringify(droneRoles)) failures.push(`가짜 드론 항목 역할(큰 미션)이 드론과 다르다: ${JSON.stringify(run()?.plan?.roles)}`);
  if (JSON.stringify(run()?.plan?.steps.map((step) => step.seq)) !== JSON.stringify([[2, 3], [4, 6], [7, 8], [10, 11], [12, 13], [14, 15]])) failures.push('가짜 드론 단계 seq 범위가 드론과 다르다');

  // 확인 없는 비행 — 거절
  const unconfirmed = await command(drone, 'seq_mission_start', seq.seqStartParams(mission, { dryRun: false, confirmed: false }), false);
  if (!unconfirmed.seen.some((m) => m.kind === 'acceptance' && !m.accepted && m.message === 'not_confirmed')) failures.push('확인 없는 비행을 거절하지 않았다');

  // 짧은 비행 — 단계마다 END, 착륙, 코드 0
  const fly = await command(drone, 'seq_mission_start', seq.seqStartParams(mission, { dryRun: false, confirmed: true }));
  await until('이륙', () => (fcxReports()['x500-fake']?.position?.altRelM ?? 0) > 1, 6000);
  // 서로 배제 — 복합 미션 중 왕복 시험 시작은 거절
  const other = await command(drone, 'rtk_test_start', { pattern: 0, altitude_m: 3, passes: 1, dry_run: 1 }, false);
  if (!other.seen.some((m) => m.kind === 'acceptance' && !m.accepted && m.message === 'other_flight_running')) failures.push('복합 미션 중 왕복 시험을 거절하지 않았다');
  await until('비행 종료', () => run()?.commandId === fly.out.commandId && run()?.state === 'exited', 30000);
  const fr = run();
  const progress = feed.readSeqProgress(fr?.lines ?? [], fr?.plan ?? null);
  if (fr?.exitCode !== 0 || progress.phase !== 'landed' || progress.stepsDone.size !== 3 || progress.results[3]?.posErrM == null) {
    failures.push(`비행: 코드 ${fr?.exitCode} 단계 ${progress.phase} 끝난 단계 ${[...progress.stepsDone]}`);
  }
  if (!(fr?.lines ?? []).some((line) => line.text.includes('CAP 3 START'))) failures.push('캡처 단계에서 CAP 을 안 찍었다');
  if (fcxReports()['x500-fake']?.armed !== false) failures.push('착륙 뒤에도 arm 상태다');
  drone.disconnect();
}

if (failures.length > 0) {
  console.error('❌ verify:seq-mission');
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log(`✅ 통과 — 시험 벡터 3개(키 · 해시 · 단계 끝) · 파라미터 · 검사 · mission_run 읽기 · 출력 읽기 · 가짜 드론(dry-run · 비행 · 서로 배제) (대조군 ${controls.length}개: ${controls.join(' / ')})`);
process.exit(0);
