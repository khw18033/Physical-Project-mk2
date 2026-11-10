// verify:metric-history (261110 신설 — 실시간 상태 그래프)
//
// **그래프가 받은 것만 그린다.** 하드웨어 카드 · 전체 장치 확인의 흐름 그래프는 `shared/metricHistory.ts` 만 읽는다.
// 여기서 거짓이 생기면 화면 전체가 거짓이 된다 — 끊긴 동안을 선으로 잇거나, 안 온 값을 마지막 값으로 채우는 것.
//
// 보는 것 — 실제 받는 길(`noteDeviceTelemetry` · `noteFcx`)로 넣는다.
//  ① Go1 모양 본문 1 Hz → 배터리 · 속도 이력, 속도로 가른 동작(이동 · 정지). heartbeat(줄 없는 몸)도 「받았다」로 센다
//  ② 6초 끊김 → 덩어리 둘 · 끊김 하나. 끊긴 동안 점이 없다. 소식이 멎으면 마지막 값은 「지금」이 아니다(fresh=false, 끝 끊김)
//  ③ 5 Hz 에서 한 점 놓친 것은 끊김이 아니다(간격 중앙값의 세 배 기준)
//  ④ 수신 간격 — 끊긴 동안에도 0.5초마다 올라간다(브라우저가 잰다)
//  ⑤ 드론 — FC 확장 텔레메트리가 살아 있으면 `/state` 의 같은 지표는 안 섞는다. 모드는 구간으로, 바뀐 순간은 사건으로
//  ⑥ 60초 변화 — 지금 값이 낡았으면 모른다(null)
//  ⑦ 3분 창 밖은 버린다
//
// 대조군 둘 — 점을 전부 이어 그린 덩어리 · 끊긴 동안을 마지막 값으로 채운 이력. 판정이 각각 잡아야 한다.
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const mh = await load('src', 'shared', 'metricHistory.ts');
const dt = await load('src', 'shared', 'deviceTelemetry.ts');
const fx = await load('src', 'shared', 'fcxStatus.ts');

const failures = [];
const controls = [];

/** 판정 ① — 끊김을 넘어 이어진 덩어리가 없다. */
function bridged(runs, holeFrom, holeTo) {
  return runs.some((run) => run.some((p, i) => i > 0 && run[i - 1].atMs < holeFrom && p.atMs > holeTo));
}
/** 판정 ② — 끊긴 동안 점이 없다. */
function fabricated(points, holeFrom, holeTo) {
  return points.some((p) => p.atMs > holeFrom && p.atMs < holeTo);
}

const T0 = 1_800_000_000_000;
const row = [{ labelKey: 'dt.battery', value: '80 %', ageS: null, onCard: true }];

// ── ① · ② Go1 1 Hz, 20~26초 끊김, 40초 이후 침묵 ─────────────────────────────
mh.resetMetricHistory();
dt.resetDeviceTelemetry();
for (let s = 0; s < 40; s++) {
  if (s >= 20 && s < 26) continue;
  const at = T0 + s * 1000;
  dt.noteDeviceTelemetry('go1-001', row, { atMs: at, body: { battery_pct: 80 - Math.floor(s / 10), speed_mps: s % 10 < 5 ? 0.4 : 0 } });
}
// heartbeat — 줄 없는 몸. 이력에는 「받았다」만 남는다
dt.noteDeviceTelemetry('go1-001', [], { atMs: T0 + 41_000, body: {} });
{
  const battery = mh.metricSeries('go1-001', 'battery_pct');
  if (battery.length !== 34) failures.push(`Go1 배터리 점 ${battery.length}개 — 34개(40 − 끊김 6)여야 한다`);
  if (mh.metricSeries('go1-001', 'speed_mps').length !== 34) failures.push('Go1 속도 점 수가 다르다');
  if (mh.lastSeenAt('go1-001') !== T0 + 41_000) failures.push('heartbeat 가 「받았다」로 안 셌다');
  const motion = mh.stateSpans(mh.stateSeries('go1-001', mh.MOTION_KEY), T0 + 39_500, 120_000);
  const codes = new Set(motion.map((s) => s.code));
  if (!codes.has('moving') || !codes.has('idle')) failures.push('동작 띠에 이동 · 정지가 다 안 나온다');
  if (!motion.some((s) => s.code === null && s.from >= T0 + 19_000 && s.to <= T0 + 26_000)) failures.push('동작 띠가 끊긴 동안을 「수신 없음」으로 안 그렸다');

  const live = mh.trendRuns(battery, T0 + 39_500, 120_000);
  if (live.runs.length !== 2) failures.push(`끊김 하나에 덩어리 ${live.runs.length}개 — 둘이어야 한다`);
  if (live.gaps.length !== 1 || live.gaps[0][0] !== T0 + 19_000 || live.gaps[0][1] !== T0 + 26_000) failures.push(`끊김 구간이 다르다: ${JSON.stringify(live.gaps)}`);
  if (!live.fresh) failures.push('막 받은 값을 낡았다고 했다');
  if (bridged(live.runs, T0 + 19_500, T0 + 25_500)) failures.push('끊김을 넘어 선을 이었다');
  if (fabricated(battery, T0 + 19_500, T0 + 25_500)) failures.push('끊긴 동안 점이 있다');

  const later = mh.trendRuns(battery, T0 + 60_000, 120_000);
  if (later.fresh) failures.push('20초 넘게 소식 없는 값을 「지금」이라고 했다');
  const tail = later.gaps.at(-1);
  if (!tail || tail[0] !== T0 + 39_000 || tail[1] !== T0 + 60_000) failures.push('마지막 점 뒤 침묵을 끊김으로 안 그렸다');

  // 대조군 ① — 점을 전부 이어 그린 덩어리
  if (bridged([battery.slice()], T0 + 19_500, T0 + 25_500)) controls.push('끊김을 이은 선');
  else failures.push('대조군 ①(전부 이은 선)을 판정이 못 잡았다');
  // 대조군 ② — 끊긴 동안을 마지막 값으로 채운 이력
  const filled = [];
  for (let s = 0; s < 40; s++) filled.push({ atMs: T0 + s * 1000, v: battery.find((p) => p.atMs <= T0 + s * 1000)?.v ?? 80 });
  if (fabricated(filled, T0 + 19_500, T0 + 25_500)) controls.push('마지막 값으로 채운 이력');
  else failures.push('대조군 ②(채운 이력)를 판정이 못 잡았다');

  // ⑥ 60초 변화 — 낡으면 모른다
  if (mh.deltaOver(battery, T0 + 90_000, 60_000) !== null) failures.push('낡은 값으로 60초 변화를 말했다');
  const short = mh.deltaOver(battery, T0 + 39_200, 30_000);
  if (short !== -3) failures.push(`30초 변화가 ${short} — −3(80 → 77)이어야 한다`);
}

// ── ③ 5 Hz 에서 한 점 놓친 것 ────────────────────────────────────────────────
mh.resetMetricHistory();
for (let i = 0; i < 100; i++) {
  if (i === 50) continue;
  mh.noteMetric('x', 'k', i, T0 + i * 200);
}
{
  const r = mh.trendRuns(mh.metricSeries('x', 'k'), T0 + 99 * 200, 120_000);
  if (r.runs.length !== 1 || r.gaps.length !== 0) failures.push('5 Hz 에서 한 점 놓친 것을 끊김으로 그렸다');
}

// ── ④ 수신 간격 ──────────────────────────────────────────────────────────────
mh.resetMetricHistory();
mh.noteSeen('go1-001', T0);
for (let k = 1; k <= 10; k++) mh.sampleAges(T0 + k * 500);
{
  const ages = mh.metricSeries('go1-001', mh.AGE_KEY);
  if (ages.length !== 10 || ages[9].v !== 5 || ages.some((p, i) => i > 0 && p.v <= ages[i - 1].v)) failures.push('침묵 동안 수신 간격이 0.5초마다 오르지 않는다');
  mh.noteSeen('go1-001', T0 + 5_200);
  mh.sampleAges(T0 + 5_500);
  if (Math.abs(mh.metricSeries('go1-001', mh.AGE_KEY).at(-1).v - 0.3) > 1e-9) failures.push('받은 뒤 수신 간격이 0 근처로 안 돌아왔다');
  mh.sampleAges(T0 + 5_200 + mh.HISTORY_WINDOW_MS + 1);
  if (mh.metricSeries('go1-001', mh.AGE_KEY).at(-1).atMs > T0 + 5_500) failures.push('3분 넘게 조용한 장비를 계속 잰다');
}

// ── ⑤ 드론 — FC 확장 텔레메트리가 이긴다 · 모드 구간 ────────────────────────────
mh.resetMetricHistory();
fx.resetFcx();
const fcx = (mode, alt, pct) => ({
  deviceId: 'x500-001', link: { heartbeatAgeS: 0.1, msgsPerS: 40, fcSysid: 1 }, armed: true, mode, landedState: null,
  attitude: null, hud: { groundspeed: 3, airspeed: null, climb: 0.2, heading: 90, throttle: null },
  position: { lat: 36.35, lon: 127.3, altRelM: alt, altMslM: null, vn: null, ve: null, vd: null }, home: null,
  gps: { fixType: 6, fix: 'RTK_FIXED', satellites: 22, hdop: 0.6, vdop: null, hAccM: null, vAccM: null }, rtk: null,
  battery: { voltageV: 16.1, currentA: null, remainingPct: pct, cellsV: [], temperatureC: null, consumedMah: null },
  sensors: null, loadPct: null, dropRatePct: null, ekf: null, vibration: null, rc: null, wind: null, clockOffsetS: null, console: [], deviceTime: null,
});
for (let i = 0; i < 50; i++) {
  fx.noteFcx(fcx(i < 25 ? 'GUIDED' : 'LOITER', 10 + i * 0.1, 70), T0 + i * 200);
  if (i % 5 === 0) dt.noteDeviceTelemetry('x500-001', row, { atMs: T0 + i * 200 + 50, body: { battery: { remaining_pct: 12 }, flight: { mode: 'STALE' } } });
}
{
  const pct = mh.metricSeries('x500-001', 'battery.remaining_pct');
  if (pct.length !== 50 || pct.some((p) => p.v !== 70)) failures.push('FC 확장 텔레메트리가 살아 있는데 /state 의 배터리가 섞였다');
  if (mh.stateSeries('x500-001', 'flight.mode').some((p) => p.code === 'STALE')) failures.push('FC 확장 텔레메트리가 살아 있는데 /state 의 모드가 섞였다');
  const spans = mh.stateSpans(mh.stateSeries('x500-001', 'flight.mode'), T0 + 49 * 200, 120_000);
  if (spans.map((s) => s.code).join(',') !== 'GUIDED,LOITER') failures.push(`모드 구간이 ${spans.map((s) => s.code).join(',')}`);
  if (mh.changeMoments(spans).join() !== String(T0 + 25 * 200)) failures.push('모드가 바뀐 순간이 다르다');
  // FC 가 멎은 뒤 /state 는 다시 적힌다
  dt.noteDeviceTelemetry('x500-001', row, { atMs: T0 + 20_000, body: { battery: { remaining_pct: 66 } } });
  if (mh.metricSeries('x500-001', 'battery.remaining_pct').at(-1).v !== 66) failures.push('FC 가 멎었는데 /state 값을 안 적는다');
}

// ── ⑦ 3분 창 ────────────────────────────────────────────────────────────────
mh.resetMetricHistory();
for (let s = 0; s < 400; s++) mh.noteMetric('y', 'k', s, T0 + s * 1000);
{
  const points = mh.metricSeries('y', 'k');
  if (points[0].atMs < T0 + 399_000 - mh.HISTORY_WINDOW_MS) failures.push('3분 창 밖 점이 남았다');
  mh.noteMetric('y', 'k', 1, T0);
  if (mh.metricSeries('y', 'k').at(-1).atMs !== T0 + 399_000) failures.push('거꾸로 온 점을 받았다');
}

mh.resetMetricHistory();
dt.resetDeviceTelemetry();
fx.resetFcx();

if (failures.length > 0) {
  console.error('❌ verify:metric-history');
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log('✅ Go1 1 Hz — 배터리 · 속도 이력 · 이동/정지 띠 · heartbeat 도 수신으로 셈');
console.log('✅ 끊김 — 덩어리를 가르고 잇지 않음 · 끊긴 동안 점 없음 · 침묵 뒤 값은 「지금」이 아님');
console.log('✅ 5 Hz 한 점 놓침은 끊김 아님 · 수신 간격은 침묵 동안 0.5초마다 오름 · 3분 창');
console.log('✅ 드론 — FC 확장 텔레메트리가 살아 있으면 /state 를 안 섞음 · 모드 구간과 바뀐 순간');
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
