// verify:sar (261002 신설 — 드론 파트 · RTK · SAR 직선 패스)
//
// **SAR 패스 기능이 이 저장소의 규칙 안에서 도는가.**
//
//  1. 드론 보고(`sar` 채널) 뜯기 — 모양이 틀리면 null, 숫자가 없으면 모름(null)
//  2. MQTT 소켓이 `sar` 토픽을 구독하고, 장비 상태 표가 아니라 제 저장소로 보낸다
//  3. 장비 고르기 — 기종이 아니라 `Capability` 의 `sar_start` 선언으로
//  4. 시작은 선언이 있어야 · 화면 정지 뒤에는 안 나간다 · 나갈 때는 추적기를 지난다
//  5. 중단은 선언했거나 모르면 나간다 · 선언 안 했으면 안 나가고 조종기를 가리킨다
//  6. 화면의 계획 검사 숫자 = 드론 실행기(`drone/sar_pass/mission.py`)의 숫자
//  7. RTK 등급 — fix_type 숫자가 먼저, 문자열은 그다음
//
// 음성 대조군 포함 — 판정이 무력화된 입력을 실제로 잡는지 본다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const read = (...p) => readFileSync(join(root, ...p), 'utf8').replace(/\r\n/g, '\n');

const { parseSarStatus, sarChannel, SAR_TOPIC } = await load('src', 'physical', 'sarFeed.ts');
const { noteSarStatus, resetSarStatus, sarReports } = await load('src', 'shared', 'sarStatus.ts');
const { sarLink, issueSarStart, issueSarAbort } = await load('src', 'physical', 'sarCommands.ts');
const { noteCapability, resetDeviceIdentity } = await load('src', 'physical', 'deviceIdentity.ts');
const { resetRobotSession, lockStopped } = await load('src', 'physical', 'robotSession.ts');
const { commandTracker } = await load('src', 'shared', 'commandCenter.ts');
const plan = await load('src', 'sar', 'plan.ts');
const { rtkLevel } = await load('src', 'sar', 'rtk.ts');

const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

const DRONE_URL = 'ws://drone-broker.test:9001';
const GO1_URL = 'ws://go1-broker.test:9001';

const sample = (over = {}) => ({
  schema_version: 'sar-0.1', channel: 'sar', source_id: 'x500-001', state: 'capture', pass: 1, passes_total: 2,
  capturing: true,
  plan: { start_lat: 37.5665, start_lon: 126.978, end_lat: 37.5670, end_lon: 126.9786, alt_m: 20, speed_mps: 4,
    passes: 2, gap_s: 10, lead_in_m: 16, length_m: 80, heading_deg: 45, require_rtk: true },
  live: { ground_speed_mps: 4.01, alt_rel_m: 20.1, yaw_deg: 45, heading_err_deg: 0.2, along_m: 33.1,
    cross_track_m: 0.05, gps_fix: 'RTK_FIXED', flight_mode: 'OFFBOARD' },
  passes: [{ pass_no: 1, start_unix: 1790930824.6, end_unix: null, captured: true, mean_speed_mps: null,
    max_speed_err_mps: 0.1, max_cross_track_m: 0.1, max_alt_err_m: 0.1, max_heading_err_deg: 0.5, note: '' }],
  message: null, error: null, time: 1790930830.1, timestamp: '2026-10-02T09:00:00.000+09:00',
  ...over,
});

// ── 1. 뜯기 ───────────────────────────────────────────────────────────────────
{
  const s = parseSarStatus(sample(), 'zoneA/drone/x500-001/sar');
  check(s !== null && s.deviceId === 'x500-001' && s.state === 'capture' && s.capturing === true, '정상 보고를 못 뜯었다');
  check(s?.passes.length === 1 && s.passes[0].endUnix === null, '열린 패스의 끝 시각은 null(모름)이어야 한다');
  check(s?.live?.groundSpeedMps === 4.01 && s.plan?.lengthM === 80, '숫자 칸을 못 옮겼다');
  check(s?.clockOffsetS === null && Array.isArray(s?.warnings), '시계 오차가 없을 때 모름(null)이 아니다');
  const timed = parseSarStatus(sample({ clock_offset_s: 0.12, warnings: ['w', 3],
    passes: [{ pass_no: 1, captured: true, fc_start_unix: 100.5, worst_fix: 'RTK_FLOAT' }] }));
  check(timed?.clockOffsetS === 0.12 && timed.warnings.join() === 'w', '시계 오차·경고를 못 옮겼다(글자 아닌 경고는 버린다)');
  check(timed?.passes[0].fcStartUnix === 100.5 && timed.passes[0].worstFix === 'RTK_FLOAT' && timed.passes[0].fcEndUnix === null,
    '패스의 FC 시각·RTK 최저를 못 옮겼다');
  check(parseSarStatus(sample({ state: 'flying' })) === null, '모르는 상태를 받아들였다');
  check(parseSarStatus(sample({ state: undefined })) === null, '상태 없는 보고를 받아들였다');
  check(parseSarStatus(sample({ source_id: undefined }), 'zoneA/drone/x500-002/sar')?.deviceId === 'x500-002',
    'source_id 가 없을 때 토픽에서 id 를 못 찾았다');
  check(parseSarStatus(sample({ live: { ground_speed_mps: 'fast' } }))?.live?.groundSpeedMps === null,
    '숫자가 아닌 값을 0 이나 글자로 옮겼다 — 모름(null)이어야 한다');
  check(sarChannel('zoneA/drone/x500-001/sar') && !sarChannel('zoneA/drone/x500-001/state'), '채널 판정이 틀렸다');
  check(SAR_TOPIC.split('/')[2] === '+', 'SAR 토픽에 장비 id 를 박았다 — `+` 로 받아야 한다');
  console.log('✅ 뜯기 — 정상 보고 · 모르는 상태 거절 · 숫자 아니면 모름 · 토픽은 + 로');
}

// ── 2. 소켓이 구독하고 제 저장소로 보낸다 ───────────────────────────────────
{
  const src = read('src', 'physical', 'PhysicalClient.ts');
  check(/client\.subscribe\(SAR_TOPIC/.test(src), 'PhysicalClient 가 SAR 토픽을 구독하지 않는다');
  const sarAt = src.indexOf('if (sarChannel(topic))');
  const deviceAt = src.indexOf('for (const listener of this.deviceListeners)');
  check(sarAt > 0 && sarAt < deviceAt, 'SAR 보고가 장비 상태 표보다 먼저 갈라지지 않는다 — stateRows 에 섞인다');
  check(/noteSarStatus\(sar, this\.address\(\)\)/.test(src), 'SAR 보고에 어느 브로커에서 왔는지가 안 실린다');
  for (const file of ['sar/SarPassView.tsx', 'sar/RtkView.tsx', 'sar/plan.ts', 'shared/sarStatus.ts']) {
    const body = read('src', ...file.split('/'));
    check(!/zoneA\/|terminal\//.test(body), `${file} 에 토픽 문자열이 있다 — physical/ 밖이다`);
    check(!/from 'mqtt'|protobufjs/.test(body), `${file} 가 mqtt/protobuf 를 직접 가져온다`);
  }
  console.log('✅ 소켓 — sar 토픽 구독 · 상태 표보다 먼저 갈라 제 저장소로 · 토픽은 physical/ 안에만');
}

// ── 3~5. 장비 고르기와 명령 ─────────────────────────────────────────────────
function fakeClient(url, { reply = 'accept' } = {}) {
  const sent = [];
  const listeners = new Set();
  return {
    sent,
    address: () => url,
    getStatus: () => ({ state: 'open' }),
    onMessage(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    send(action, parameters) {
      const commandId = `cmd-${String(sent.length + 1).padStart(8, '0')}`;
      sent.push({ action, parameters });
      if (reply === 'accept' || reply === 'reject') {
        const message = { kind: 'acceptance', commandId, accepted: reply === 'accept',
          code: reply === 'reject' ? 'INVALID_ARGUMENT' : null, message: reply === 'reject' ? 'speed out of range' : null };
        queueMicrotask(() => { for (const l of listeners) l(message); });
      }
      return { sent: true, commandId };
    },
  };
}

const params = plan.toStartParams({
  ...plan.defaultDraft(),
  start: { lat: 37.5665, lon: 126.978 },
  end: plan.endFrom({ lat: 37.5665, lon: 126.978 }, 45, 80),
});

{
  // 선언 없음 → 시작 안 나간다
  resetRobotSession(); resetDeviceIdentity(); resetSarStatus();
  const drone = fakeClient(DRONE_URL);
  const go1 = fakeClient(GO1_URL);
  noteCapability('x500-001', ['ping'], DRONE_URL);
  noteCapability('go1-001', ['ping', 'move_forward', 'turn', 'abort'], GO1_URL);
  let link = sarLink([drone, go1]);
  check(link.client === null && link.start === 'no', '아무도 sar_start 를 선언 안 했는데 장비를 골랐다');
  const notSent = await issueSarStart(params, link);
  check(!notSent.sent && drone.sent.length === 0 && go1.sent.length === 0, '선언 없이 시작이 나갔다');

  // 보고만 있음 → 그 브로커를 고르되 시작은 닫힌다, 중단은 선언 목록대로
  noteSarStatus(parseSarStatus(sample()), DRONE_URL);
  link = sarLink([drone, go1]);
  check(link.client === drone && link.start === 'no' && link.abort === 'no', 'SAR 보고 브로커를 못 골랐거나 선언 판정이 틀렸다');
  const abortNo = await issueSarAbort(link);
  check(!abortNo.sent && drone.sent.length === 0, 'sar_abort 를 선언 안 한 장비에 중단을 쐈다');
  check(/조종기|RC/.test(abortNo.message), '중단 불가 안내가 조종기를 가리키지 않는다');

  // 선언 → 시작이 나가고 추적기를 지난다
  noteCapability('x500-001', ['ping', 'sar_start', 'sar_abort'], DRONE_URL);
  link = sarLink([drone, go1]);
  check(link.client === drone && link.deviceId === 'x500-001' && link.start === 'yes', '선언한 드론을 못 골랐다');
  const before = commandTracker.getSnapshot().length;
  const started = await issueSarStart(params, link);
  check(started.sent && started.accepted === true, `시작이 안 나갔거나 수락을 못 읽었다: ${started.message}`);
  check(drone.sent.length === 1 && drone.sent[0].action === 'sar_start', `드론 소켓으로 나간 것이 sar_start 하나가 아니다: ${drone.sent.map((x) => x.action)}`);
  check(go1.sent.length === 0, 'Go1 소켓으로 SAR 명령이 샜다');
  const startParams = drone.sent.find((x) => x.action === 'sar_start')?.parameters ?? {};
  check(Object.keys(startParams).length > 0 && Object.values(startParams).every((v) => typeof v === 'number'), '파라미터가 없거나 숫자가 아닌 값이 있다 — 규약은 map<string,double>');
  check(startParams.require_rtk === 1 && startParams.passes === 2, '참거짓·정수 파라미터가 1/0·숫자로 안 실렸다');
  const tracked = commandTracker.getSnapshot();
  check(tracked.length === before + 1 && tracked[0].action === 'sar_start' && tracked[0].entity === 'x500-001',
    'SAR 시작이 추적기를 안 지났거나 대상이 장비 id 가 아니다');

  // 거절은 거절로 적는다
  const rejecting = fakeClient(DRONE_URL, { reply: 'reject' });
  const rejected = await issueSarStart(params, sarLink([rejecting]));
  check(rejected.sent && rejected.accepted === false && rejected.message.includes('INVALID_ARGUMENT'), '드론의 거절 사유를 버렸다');

  // 화면 정지 뒤에는 시작 안 한다 — 중단은 나간다
  lockStopped(true, null);
  const afterStop = await issueSarStart(params, sarLink([drone]));
  check(!afterStop.sent && drone.sent.filter((x) => x.action === 'sar_start').length === 1, '화면 정지 뒤에 시작이 나갔다');
  const abortYes = await issueSarAbort(sarLink([drone]));
  check(abortYes.sent && drone.sent.at(-1).action === 'sar_abort', '정지 뒤 중단이 안 나갔다 — 중단은 늘 나가야 한다');

  // 모름 → 중단은 보낸다 (Capability 를 못 받은 늦은 화면)
  resetRobotSession(); resetDeviceIdentity();
  const late = fakeClient(DRONE_URL, { reply: 'none' });
  const lateLink = sarLink([late]);
  check(lateLink.client === late && lateLink.abort === 'unknown', '목록을 못 받은 브로커를 「모름」으로 못 읽었다');
  check(lateLink.deviceId === 'x500-001', 'SAR 보고의 source_id 로 장비 id 를 못 찾았다');

  // 두 대가 선언 → 고르지 않는다
  resetDeviceIdentity();
  noteCapability('x500-001', ['sar_start'], DRONE_URL);
  noteCapability('x500-002', ['sar_start'], GO1_URL);
  const many = sarLink([fakeClient(DRONE_URL), fakeClient(GO1_URL)]);
  check(many.client === null && many.start === 'no', 'sar_start 를 선언한 드론이 둘인데 하나를 짐작해 골랐다');

  resetDeviceIdentity(); resetSarStatus(); resetRobotSession();
  check(Object.keys(sarReports()).length === 0, '저장소를 못 비웠다');
  console.log('✅ 명령 — 선언으로 고름 · 시작은 선언+정지 해제 필요 · 중단은 선언/모름이면 · 추적기 경유 · 숫자 파라미터 · 거절 사유 보존');
}

// ── 6. 화면과 드론의 숫자가 같다 ────────────────────────────────────────────
{
  const py = read('drone', 'sar_pass', 'mission.py');
  const pyNum = (name) => Number(py.match(new RegExp(`^${name}\\s*=\\s*([0-9.]+)`, 'm'))?.[1]);
  const pairs = [['MIN_LINE_M', 'minLineM'], ['MIN_SPEED', 'minSpeed'], ['MAX_SPEED', 'maxSpeed'], ['MIN_PASSES', 'minPasses'], ['MIN_GAP_S', 'minGapS']];
  for (const [p, j] of pairs) {
    check(pyNum(p) === plan.SAR_RULES[j], `${p}(드론 ${pyNum(p)}) 와 SAR_RULES.${j}(화면 ${plan.SAR_RULES[j]}) 가 다르다`);
  }
  // 대조군 — 없는 이름은 NaN 이라 같다고 나오면 안 된다
  check(Number.isNaN(pyNum('NO_SUCH_RULE')), '대조군 실패: 없는 상수를 찾았다고 한다');
  // lead-in 자동 계산: v²/(2a) + v·settle — 드론과 같은 식 · 같은 상수
  const settle = pyNum('SETTLE_S');
  check(settle === plan.SAR_RULES.settleS, `등속 안정 시간이 드론(${settle} s)과 화면(${plan.SAR_RULES.settleS} s)에서 다르다`);
  check(Math.abs(plan.autoLeadInM(4) - (8 + 4 * settle)) < 1e-9, `자동 가속 구간이 드론과 다르다: ${plan.autoLeadInM(4)}`);
  check(/accel_mps2: float = 1\.0/.test(py) && plan.SAR_RULES.accelMps2 === 1, '드론 쪽 가속 기본값이 화면(1 m/s²)과 다르다');
  // 품질 판정 기본값 — 화면이 보내는 값과 드론이 받지 않았을 때의 값이 같아야 한다
  const pyField = (name) => Number(py.match(new RegExp(`^\\s+${name}: (?:float|int) = ([0-9.]+)`, 'm'))?.[1]);
  for (const [f, j] of [['q_cross_m', 'qCrossM'], ['q_speed_mps', 'qSpeedMps'], ['q_alt_m', 'qAltM'], ['q_heading_deg', 'qHeadingDeg'], ['q_course_deg', 'qCourseDeg'], ['q_edge_m', 'qEdgeM'], ['extra_passes', 'extraPasses'], ['min_battery_pct', 'minBatteryPct']]) {
    check(pyField(f) === plan.SAR_RULES[j], `품질 기본값 ${f}(드론 ${pyField(f)}) 와 SAR_RULES.${j}(화면 ${plan.SAR_RULES[j]}) 가 다르다`);
  }
  const sent = plan.toStartParams({ ...plan.defaultDraft(), start: { lat: 1, lon: 1 }, end: { lat: 1.001, lon: 1 } });
  check(['q_cross_m', 'q_speed_mps', 'q_alt_m', 'q_heading_deg', 'q_course_deg', 'q_edge_m', 'extra_passes', 'min_battery_pct'].every((k) => typeof sent[k] === 'number'),
    '품질 기준이 sar_start 파라미터에 안 실린다');

  const good = { ...plan.defaultDraft(), start: { lat: 37.5665, lon: 126.978 } };
  good.end = plan.endFrom(good.start, 45, 80);
  check(plan.planProblems(good).length === 0, `조건을 만족하는 계획을 거절했다: ${JSON.stringify(plan.planProblems(good))}`);
  const { lengthM, headingDeg } = plan.lineOf(good.start, good.end);
  check(Math.abs(lengthM - 80) < 0.01 && Math.abs(headingDeg - 45) < 0.01, '방위·길이 → 끝점 → 방위·길이 왕복이 어긋난다');
  const bad = (over) => plan.planProblems({ ...good, ...over }).map((p) => p.key);
  check(bad({ end: plan.endFrom(good.start, 45, 59) }).includes('sar.rule.line'), '59 m 선을 통과시켰다');
  check(bad({ speedMps: 5.5 }).includes('sar.rule.speed') && bad({ speedMps: 2.9 }).includes('sar.rule.speed'), '속도 범위 밖을 통과시켰다');
  check(bad({ passes: 1 }).includes('sar.rule.passes') && bad({ passes: 2.5 }).includes('sar.rule.passes'), '패스 1회·소수 패스를 통과시켰다');
  check(bad({ gapS: 9 }).includes('sar.rule.gap'), '간격 9초를 통과시켰다');
  check(bad({ speedMps: Number.NaN }).includes('sar.rule.speed'), '빈 칸(NaN) 속도를 통과시켰다');
  console.log('✅ 계획 — 경계값 다섯이 드론과 같다 · 자동 가속 구간 같은 식 · 위반 다섯을 잡는다');
}

// ── 8. RTK 보정 전달기 보고 ─────────────────────────────────────────────────
{
  const { parseRtcmStatus, rtcmChannel, RTCM_TOPIC } = await load('src', 'physical', 'rtcmFeed.ts');
  const body = { source_id: 'x500-001', receiving: true, age_s: 0.4, frames_per_s: 4.1, rate_bps: 812.5, frames: 120,
    types: { '1005': 3, '1077': 40, junk: 1 }, base: { station_id: 7, lat: 36.35, lon: 127.29, alt_m: 85.1 },
    sender: '192.168.43.20:51234', injected_messages: 200, bad_crc: 0 };
  const r = parseRtcmStatus(body, 'zoneA/drone/x500-001/rtcm');
  check(r !== null && r.receiving && r.ageS === 0.4 && r.base?.stationId === 7, '보정 전달기 보고를 못 뜯었다');
  check(r?.types.join() === '1005,1077', '메시지 번호가 아닌 키를 걸러 내지 않았다');
  check(parseRtcmStatus({ ...body, receiving: 'yes' }) === null, 'receiving 이 참거짓이 아닌 보고를 받아들였다');
  check(parseRtcmStatus({ ...body, base: null, age_s: null })?.base === null, '베이스 위치가 없을 때 모름(null)이 아니다');
  check(rtcmChannel('zoneA/drone/x500-001/rtcm') && RTCM_TOPIC.split('/')[2] === '+', 'RTCM 토픽 규칙이 틀렸다');
  const src = read('src', 'physical', 'PhysicalClient.ts');
  check(/client\.subscribe\(RTCM_TOPIC/.test(src), 'PhysicalClient 가 RTCM 토픽을 구독하지 않는다');
  check(src.indexOf('if (rtcmChannel(topic))') < src.indexOf('for (const listener of this.deviceListeners)'),
    'RTCM 보고가 장비 상태 표보다 먼저 갈라지지 않는다');
  console.log('✅ 보정 전달기 — 보고 뜯기 · 숫자 아닌 메시지 키 거름 · 베이스 모름 · 구독과 분기');
}

// ── 9. 드론 상태판 텔레메트리(fcx) ───────────────────────────────────────────
{
  const { parseFcx, fcxChannel, FCX_TOPIC } = await load('src', 'physical', 'fcxFeed.ts');
  const { noteFcx, fcxReports, resetFcx } = await load('src', 'shared', 'fcxStatus.ts');
  const body = {
    source_id: 'x500-001', link: { heartbeat_age_s: 0.2, msgs_per_s: 31, fc_sysid: 1 }, armed: true, mode: 'OFFBOARD',
    attitude: { roll_deg: 1.2, pitch_deg: -6.5, yaw_deg: 45 }, hud: { groundspeed: 4.0, climb: 0.1 },
    position: { lat: 37.5665, lon: 126.978, alt_rel_m: 20.1 }, gps: { fix_type: 6, fix: 'RTK_FIXED', satellites: 27, hdop: 0.62 },
    battery: { voltage_v: 15.9, cells_v: [3.97, 3.98, 'x', 3.96] }, sensors: [{ name: 'GPS', enabled: true, healthy: false }, { bad: 1 }],
    ekf: { pos: 0.08, vel: 'nan', mag: 1.2 }, console: [{ t: 1, severity: 'WARNING', level: 4, text: 'Yaw' }, { t: 2 }],
  };
  const f = parseFcx(body, 'zoneA/drone/x500-001/fcx');
  check(f !== null && f.mode === 'OFFBOARD' && f.attitude?.pitchDeg === -6.5 && f.gps?.fix === 'RTK_FIXED', 'fcx 보고를 못 뜯었다');
  check(f?.battery?.cellsV.length === 3, '숫자가 아닌 셀 전압을 걸러 내지 않았다');
  check(f?.sensors?.length === 1 && f.sensors[0].healthy === false, '센서 목록을 잘못 옮겼다');
  check(f?.ekf?.vel === null && f.ekf.mag === 1.2, 'EKF 비율의 모름을 지키지 않았다');
  check(f?.console.length === 1, '글자 없는 콘솔 줄을 받아들였다');
  check(f?.hud?.airspeed === null && f.home === null && f.vibration === null, '안 온 값을 지어 채웠다');
  check(parseFcx({ source_id: 'x' }) === null, 'link 없는 보고를 받아들였다');
  check(fcxChannel('zoneA/drone/x500-001/fcx') && FCX_TOPIC.split('/')[2] === '+', 'fcx 토픽 규칙이 틀렸다');
  resetFcx();
  for (let i = 0; i < 905; i++) noteFcx(f, 1000 + i * 200);
  const r = fcxReports()['x500-001'];
  check(r.history.length === 900 && r.history.at(-1).atMs === 1000 + 904 * 200, '이력이 900 점으로 잘리지 않는다');
  resetFcx();
  const src = read('src', 'physical', 'PhysicalClient.ts');
  check(/client\.subscribe\(FCX_TOPIC/.test(src), 'PhysicalClient 가 fcx 토픽을 구독하지 않는다');
  console.log('✅ 드론 상태판 — fcx 뜯기 · 숫자 아닌 값 거름 · 안 온 값은 모름 · 이력 900점 · 구독');
}

// ── 10. 코너리플렉터 판정 — drone/sar_image/coverage.py 와 같은 식 ─────────────
{
  const cov = await load('src', 'sar', 'coverage.ts');
  const a = cov.defaultAntenna();
  const { near, far } = cov.swathGroundRanges(a, 20);
  check(Math.abs(near - 20 / Math.tan(65 * Math.PI / 180)) < 1e-9 && Math.abs(far - 20 / Math.tan(25 * Math.PI / 180)) < 1e-9,
    `관측 띠가 드론 쪽 식과 다르다: ${near}, ${far}`);
  const start = { lat: 37.5665, lon: 126.978 };
  const end = plan.endFrom(start, 45, 80);
  // 진행 방향 f = (n cos h, e sin h), 오른쪽 r = (n −sin h, e cos h) — h = 45°
  const h45 = Math.PI / 4;
  const at = (al, cr) => plan.toGlobal(start, al * Math.cos(h45) - cr * Math.sin(h45), al * Math.sin(h45) + cr * Math.cos(h45));
  const good = cov.checkReflector(a, start, end, 20, at(40, 20));
  check(good.ok && Math.abs(good.alongM - 40) < 0.05 && Math.abs(good.groundRangeM - 20) < 0.05, `가운데 · 오른쪽 20 m 리플렉터를 못 본다고 한다: ${JSON.stringify(good)}`);
  check(Math.abs(good.apertureM - 2 * Math.hypot(20, 20) * Math.tan(15 * Math.PI / 180)) < 0.05, '개구 길이가 2R·tan(β/2) 가 아니다');
  check(!cov.checkReflector(a, start, end, 20, at(40, -20)).ok, '안테나 반대쪽 리플렉터를 보인다고 한다');
  check(!cov.checkReflector(a, start, end, 20, at(3, 20)).ok, '선 끝에 붙은 리플렉터(개구 부족)를 보인다고 한다');
  check(!cov.checkReflector(a, start, end, 20, at(40, 70)).ok, '관측 띠 밖 리플렉터를 보인다고 한다');
  const py = read('drone', 'sar_image', 'example_radar.json');
  const ex = JSON.parse(py);
  check(ex.depression_deg === a.depressionDeg && ex.el_beamwidth_deg === a.elBeamwidthDeg && ex.az_beamwidth_deg === a.azBeamwidthDeg
    && ex.range_max_m === a.rangeMaxM && ex.side === a.side, '화면 기본 안테나 값이 drone/sar_image/example_radar.json 과 다르다');
  console.log('✅ 코너리플렉터 — 관측 띠 · 개구 · 반대쪽 · 끝 · 띠 밖 판정이 드론 쪽 식과 같다');

  // 실시간 빔 — 드론 쪽 antenna_angles · frd_to_enu 로 낸 값(아래 숫자)과 같아야 한다. 식을 바꾸면 둘 다 바꾼다.
  const ref = [
    { yaw: 45, pitch: -4, roll: 2, e: 14.1, n: -14.1, az: 2.833192, el: -1.984388, lever: [0.181940192, -0.080988084, -0.412721089] },
    { yaw: 45, pitch: -22, roll: -3, e: 20.0, n: -5.0, az: 37.127762, el: -2.503806, lever: [0.11855527, -0.193505504, -0.398120921] },
    { yaw: 120, pitch: 3, roll: 5, e: 5.0, n: -18.0, az: 26.831784, el: 7.657882, lever: [0.023146305, -0.203169323, -0.410105443] },
  ];
  for (const c of ref) {
    const att = { yawDeg: c.yaw, pitchDeg: c.pitch, rollDeg: c.roll };
    const cr = plan.toGlobal(start, c.n, c.e);
    const r = cov.reflectorInBeam(a, start, 20, att, cr);
    check(Math.abs(r.azDeg - c.az) < 1e-3 && Math.abs(r.elDeg - c.el) < 1e-3, `빔 각이 드론 쪽과 다르다: ${r.azDeg},${r.elDeg} vs ${c.az},${c.el}`);
    const v = cov.frdToEnu([0.1, 0.2, 0.4], c.yaw, c.pitch, c.roll);
    check(v.every((x, i) => Math.abs(x - c.lever[i]) < 1e-6), `자세 회전이 드론 쪽 attitude.frd_to_enu 와 다르다: ${v}`);
  }
  const fp = cov.beamFootprint(a, start, 20, { yawDeg: 45, pitchDeg: 0, rollDeg: 0 });
  const g = fp.map((p) => { const d = plan.toLocal(start, p); return { al: d.n * Math.cos(h45) + d.e * Math.sin(h45), cr: d.e * Math.cos(h45) - d.n * Math.sin(h45) }; });
  check(Math.abs(Math.min(...g.map((x) => x.cr)) - near) < 0.5 && g.every((x) => x.cr > 0), `수평 비행 빔 자국의 가까운 끝이 관측 띠와 다르다: ${Math.min(...g.map((x) => x.cr))} vs ${near}`);
  check(cov.reflectorInBeam(a, start, 20, { yawDeg: 45, pitchDeg: 0, rollDeg: 0 }, at(0, 20)).lit && !cov.reflectorInBeam(a, start, 20, { yawDeg: 45, pitchDeg: 0, rollDeg: 0 }, at(0, -20)).lit,
    '바로 옆 리플렉터가 빔 안 · 반대쪽은 밖이어야 한다');
  console.log('✅ 실시간 빔 — 빔 각 · 자세 회전 · 빔 자국이 드론 쪽 식과 같다');

  // 재처리용 기록 — 화면이 펼친 키를 드론이 같은 이름으로 다시 모아야 한다
  const prov = cov.provenanceParams([{ lat: 1, lon: 2 }, { lat: 3, lon: 4 }], { ...a, gnssFwdM: 0, gnssRightM: 0, gnssDownM: -0.1 });
  const mission = read('drone', 'sar_pass', 'mission.py');
  check(prov.cr_n === 2 && prov.cr1_lon === 4 && /f"cr\{i\}_lat"/.test(mission) && mission.includes('"cr_n"'), '리플렉터 기록 키가 드론과 다르다');
  for (const k of Object.keys(prov).filter((k) => k.startsWith('ant_') && !k.startsWith('ant_off_') && k !== 'ant_side')) {
    check(mission.includes(`"${k}"`), `안테나 기록 키 ${k} 를 드론(RADAR_PARAM_KEYS)이 모른다`);
  }
  check(mission.includes('f"ant_off_{a}"') && mission.includes('f"gnss_off_{a}"') && mission.includes('"ant_side"'), '레버암 · 보는 쪽 기록 키가 드론과 다르다');
  console.log('✅ 재처리용 기록 — 리플렉터 · 안테나 키가 드론과 같다');

  // 리플렉터 측량 — 3 초 창 안의 점만 평균, 흩어짐(m)
  const base = { lat: 37.5665, lon: 126.978 };
  const pts = [0.02, -0.02, 0.0, 0.01, -0.01].map((d, i) => ({ ...plan.toGlobal(base, d, 0), atMs: 10_000 + i * 200 }));
  const sv = cov.surveyPoint([{ ...plan.toGlobal(base, 5, 0), atMs: 1000 }, ...pts], 11_000);
  const off = plan.toLocal(base, sv.point);
  check(sv.n === 5 && Math.abs(off.n) < 0.001 && sv.spreadM > 0.005 && sv.spreadM < 0.03, `리플렉터 측량 평균이 이상하다: ${JSON.stringify(sv)}`);
  check(cov.surveyPoint(pts.slice(0, 2), 11_000) === null, '점이 3개보다 적으면 측량하지 않아야 한다');
  console.log('✅ 리플렉터 측량 — 최근 3 초 평균 · 오래된 점 제외 · 흩어짐');

  // 바람 영향 — 북쪽으로 4 m/s 날며 북풍 3 m/s(맞바람) → 공기 속도 7 m/s · 앞 숙임 · 빔은 뒤로. 서풍은 동쪽(오른쪽)으로 밀어 왼쪽으로 기울여 버틴다
  const head = plan.windEffect(0, 4, { speedMps: 3, fromDeg: 0 }, 45, 40, 30);
  check(Math.abs(head.headMps - 3) < 1e-9 && Math.abs(head.airspeedMps - 7) < 1e-9 && head.pitchDeg < 0 && head.squintDeg > 0 && Math.abs(head.rollDeg) < 1e-9,
    `맞바람 계산이 틀렸다: ${JSON.stringify(head)}`);
  const west = plan.windEffect(0, 4, { speedMps: 3, fromDeg: 270 }, 45, 40, 30);
  check(Math.abs(west.crossMps - 3) < 1e-9 && west.rollDeg < 0 && Math.abs(west.headMps) < 1e-9, `옆바람 계산이 틀렸다: ${JSON.stringify(west)}`);
  const bud = plan.batteryBudget({ ...plan.defaultDraft(), start, end }, 18);
  check(bud !== null && bud.worstMin > bud.passMin && bud.usableMin > 0, '배터리 예산이 이상하다');
  console.log('✅ 바람 · 배터리 — 맞바람은 앞 숙임 · 빔 뒤로, 서풍은 왼쪽 기울임, 재시도까지 포함');
}

// ── 7. RTK 등급 ─────────────────────────────────────────────────────────────
{
  const cases = [
    [6, null, 'fixed'], [5, null, 'float'], [3, 'RTK_FIXED', 'gps'],   // 숫자가 이긴다
    [null, 'RTK_FIXED', 'fixed'], [null, 'RTK_FIX', 'fixed'], [null, 'RTK_FLOAT', 'float'],
    [null, '3D', 'gps'], [null, 'FIX_3D', 'gps'], [null, 'NO_GPS', 'none'], [null, 'DGPS', 'dgps'],
    [null, null, 'unknown'], [null, 'WHATEVER', 'unknown'],
  ];
  for (const [type, fix, want] of cases) {
    const got = rtkLevel(type, fix);
    check(got === want, `rtkLevel(${type}, ${fix}) = ${got}, 기대 ${want}`);
  }
  console.log(`✅ RTK — ${cases.length}가지 fix 표기를 등급으로 가른다(숫자 우선)`);
}

if (failures.length > 0) {
  console.error(`\n❌ verify:sar 실패 ${failures.length}건`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log('\n✅ verify:sar 통과');
process.exit(0);
