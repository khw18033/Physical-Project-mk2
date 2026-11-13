// verify:flight-run (261014 신설 — 드론 비행 제어 탭)
//
// **화면이 pi3 의 `test_sar_rtk.py` 와 같은 말을 하는가.** 화면은 비행 코드를 새로 짜지 않고 그 스크립트를 옵션으로
// 띄운다 — 그러니 화면 쪽에서 어긋날 수 있는 곳은 넷뿐이다.
//
//  1. 예상 시간 — 스크립트 `estimate_s` 를 옮긴 공식이 같은 수를 내는가(손으로 푼 값과 대조)
//  2. 파라미터 — 규약(요청 문서 §2-1)의 키 · 번호로 바뀌는가. 회전이면 쪽 · 거리 · 속도를 안 싣는가
//  3. 출력 읽기 — 스크립트가 실제로 찍는 줄 모양에서 단계 · 미션 항목 · 패스 · 착륙을 읽는가
//  4. dry-run 짝 — 같은 설정 · 내 command_id · 종료 코드 0 일 때만 비행이 열리는가
//  5. 스크립트 고르기 (261022) — RTK 보정이 없으면 실행기가 `test_sar.py` 를 띄운다. 화면이 보정 상태로 그것을
//     짐작하고, 돌아온 `run.script` 를 읽고, `test_sar.py` 명령줄에서 RTK 옵션을 빼는가
//  6. 착륙 상태 (261111) — 11/9 실기처럼 스크립트가 착륙 완료를 못 찍어도, 진행 번호가 항목 수에 닿으면 「FC 미션 완료」,
//     `[착륙감시]` 줄(또는 FC 텔레메트리)이 땅 위 · 무장 해제를 말하면 그것으로 가르는가. 이륙 전 지상은 착륙이 아니다
//
// 대조군 — 모양이 틀린 보고는 버려야 하고, 남이 보낸 dry-run 은 내 것으로 치면 안 된다.

import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const plan = await load('src', 'physical', 'flightPlan.ts');
const feed = await load('src', 'physical', 'flightRunFeed.ts');
const commands = await load('src', 'physical', 'flightRunCommands.ts');

const failures = [];
const controls = [];
const near = (a, b) => Math.abs(a - b) < 1e-6;

// ── 1. 예상 시간 ────────────────────────────────────────────────────────
{
  // estimate_s: t = alt + 6 + align + settle + alt/0.7 + 10, rest = max(settle, gap),
  //             직선 per = 2*(len/speed + 4) + settle + rest, 회전 per = 12 + rest, 합 = t + per*passes
  const cases = [
    [{ ...plan.FLIGHT_DEFAULTS }, 26 + 5 / 0.7 + 30 * 2],
    [{ ...plan.FLIGHT_DEFAULTS, pattern: 'rotate' }, 26 + 5 / 0.7 + 22 * 2],
    [{ ...plan.FLIGHT_DEFAULTS, altitudeM: 20, lengthM: 80, speedMps: 4, passes: 3, gapS: 15 }, 20 + 6 + 3 + 2 + 20 / 0.7 + 10 + 65 * 3],
  ];
  for (const [p, want] of cases) {
    const got = plan.estimateSec(p);
    if (!near(got, want)) failures.push(`예상 시간 ${p.pattern}/${p.lengthM}m: ${got} ≠ ${want}`);
  }
  if (!near(plan.timeoutSec(plan.FLIGHT_DEFAULTS), plan.estimateSec(plan.FLIGHT_DEFAULTS) * 2 + 60)) failures.push('시간 초과 판정이 estimate*2+60 이 아니다');
}

// ── 2. 파라미터 · 검사 ──────────────────────────────────────────────────
{
  const d = plan.FLIGHT_DEFAULTS;
  if (plan.planProblems(d).length !== 0) failures.push(`기본값에 문제가 있다고 한다: ${JSON.stringify(plan.planProblems(d))}`);
  const fly = plan.startParams(d, { dryRun: false, confirmed: true });
  const want = { pattern: 0, side: 0, altitude_m: 5, length_m: 5, speed_mps: 1, passes: 2, gap_s: 10, accept_radius_m: 0.5,
    align_hold_s: 3, settle_s: 2, abort: 0, rtk_min_s: 30, rtk_timeout_s: 120, dry_run: 0, confirmed: 1 };
  if (JSON.stringify(Object.entries(fly).sort()) !== JSON.stringify(Object.entries(want).sort())) {
    failures.push(`비행 파라미터가 규약과 다르다: ${JSON.stringify(fly)}`);
  }
  const dry = plan.startParams(d, { dryRun: true, confirmed: false });
  if (dry.dry_run !== 1 || 'confirmed' in dry) failures.push(`dry-run 파라미터: ${JSON.stringify(dry)}`);
  const rot = plan.startParams(plan.withPattern(d, 'rotate'), { dryRun: true, confirmed: false });
  if ('side' in rot || 'length_m' in rot || 'speed_mps' in rot || rot.pattern !== 2) failures.push(`회전 파라미터에 쪽 · 거리 · 속도가 실렸다: ${JSON.stringify(rot)}`);
  const lr = plan.withPattern(d, 'lr');
  if (lr.side !== 'right' || plan.startParams(lr, { dryRun: true, confirmed: false }).side !== 2) failures.push('좌우로 바꾸면 먼저 갈 쪽이 오른쪽(2)이어야 한다');
  if (!plan.argvPreview(lr, true).join(' ').startsWith('--yes --pattern lr --side right --altitude 5 --length 5 --speed 1 --passes 2')) {
    failures.push(`명령줄 미리보기: ${plan.argvPreview(lr, true).join(' ')}`);
  }
  if (!plan.argvPreview(d, true).includes('--dry-run') || plan.argvPreview(d, false).includes('--dry-run')) failures.push('--dry-run 이 엉뚱하게 붙는다');
  const kinds = (p) => plan.planProblems(p).map((x) => `${x.field}:${x.kind}`);
  if (!kinds({ ...d, altitudeM: 50 }).includes('altitudeM:range')) failures.push('고도 50m 를 못 거른다(스크립트 상한 30)');
  if (!kinds({ ...d, passes: 2.5 }).includes('passes:integer')) failures.push('왕복 2.5회를 못 거른다');
  if (!kinds({ ...d, lengthM: 2, acceptRadiusM: 2 }).includes('acceptRadiusM:radius')) failures.push('도달 반경 ≥ 이동거리를 못 거른다');
  if (!kinds({ ...d, gapS: 5 }).includes('gapS:range')) failures.push('간격 5초를 못 거른다(스크립트 하한 10)');
  if (kinds({ ...plan.withPattern(d, 'rotate'), lengthM: 999 }).length !== 0) failures.push('회전인데 쓰지 않는 이동거리를 검사했다');
  if (plan.planSignature(d) !== plan.planSignature({ ...d })) failures.push('같은 설정의 서명이 다르다');
  if (plan.planSignature(d) === plan.planSignature({ ...d, altitudeM: 6 })) failures.push('다른 설정의 서명이 같다');
}

// ── 3. 출력 읽기 — 스크립트 log() 의 실제 줄 모양 ─────────────────────────
const L = (seq, text) => ({ seq, text });
const FLY = [
  '[1760000000.001] [로그] /home/physical/cansar_logs/test_sar_rtk_20261014_153012.log',
  "[1760000000.002] [설정] {'altitude': 5.0}",
  '[1760000000.010] [연결] udpin://0.0.0.0:14540 ...',
  '[1760000001.000] [연결] 완료',
  '[1760000001.100] [확인] 위치 추정 대기 (최대 60.0초)...',
  '[1760000001.200] [확인] 위치 추정 정상 ✔',
  '[1760000001.300] [RTK] 이륙 전: Fixed 30초 연속 유지 대기 (최대 120초) — 현재 fix RTK_FIXED 위성 22, Fixed 12초',
  '[1760000019.000] [RTK] 이륙 전: Fixed 30초 유지 ✔',
  '[1760000019.100] [경로] 이동 방향 전후, 헤딩(고정) 120.0°, 앞 먼저, 이동선 120.0°, 2회',
  '[1760000019.110] [미션] #0  TAKEOFF  이륙             36.0000000, 127.0000000  고도 5m  헤딩 120.0°',
  '[1760000019.111] [미션] #1  WAYPOINT yaw 정렬         36.0000000, 127.0000000  고도 5m  헤딩 120.0°  대기 3s  반경 0.5m',
  '[1760000019.112] [미션] #2  SPEED    속도             1m/s',
  '[1760000019.113] [미션] #11 LAND     착륙             36.0000000, 127.0000000  고도 0m  헤딩 120.0°',
  '[1760000019.200] [미션] 예상 비행 시간 93초, 시간 초과 판정 246초',
  '[1760000019.300] [미션] 업로드 (12개 항목)...',
  '[1760000019.400] [미션] FC 수락 ✔ — 내려받아 대조...',
  '[1760000019.500] [미션] 대조 일치 ✔ (12개 항목 모두 같다)',
  '[1760000019.600] [정렬] 이륙 직전 yaw 120.1° 기억 (미션 헤딩 120.0°, 차이 0.1°, L 에서 0.02m)',
  '[1760000019.700] [명령] arm',
  '[1760000020.000] [명령] 미션 시작 — 이제부터 FC 가 이륙·왕복·착륙을 스스로 진행한다',
  '[1760000020.500] [미션] 진행 #0  TAKEOFF  이륙             36.0000000, 127.0000000  고도 5m  헤딩 120.0°',
  '[1760000040.000] [미션] 진행 #5  WAYPOINT 패스 1 L→X      36.0000400, 127.0000400  고도 5m  헤딩 120.0°  대기 2s  반경 0.5m',
  '[1760000040.010] PASS 1 START t=1760000040.010 속도 0.10m/s 고도 5.0m',
  '[1760000042.000]        #5 진행   2.0m  속도  1.0m/s  고도   5.0m  헤딩 120.0°  CAP',
].map((text, i) => L(i + 1, text));
{
  const mid = feed.readProgress(FLY);
  if (mid.phase !== 'mission') failures.push(`비행 중 단계: ${mid.phase}`);
  if (mid.itemsTotal !== 12) failures.push(`미션 항목 수 ${mid.itemsTotal} ≠ 12 (#11 이 마지막)`);
  if (mid.itemCur !== 5 || !mid.itemText?.startsWith('WAYPOINT 패스 1')) failures.push(`현재 항목: #${mid.itemCur} ${mid.itemText}`);
  if (mid.capturing !== 1) failures.push(`캡처 중 패스: ${mid.capturing}`);
  if (!mid.live?.startsWith('#5 진행')) failures.push(`2초 줄을 못 읽었다: ${mid.live}`);
  const end = feed.readProgress([...FLY,
    L(100, '[1760000044.000] PASS 1 END   t=1760000044.000 속도 0.90m/s 고도 5.0m'),
    L(101, '[1760000044.001] PASS 1 SUMMARY start=1 end=2 dur=4.00s alt min/max=5.0/5.0m rtk=OK'),
    L(102, '[1760000110.000] [확인] 착륙 완료 ✔'),
    L(103, '[1760000110.100] [미션] FC 의 미션을 지웠다'),
    L(104, '[1760000110.200] [종료]'),
  ]);
  if (end.phase !== 'landed' || end.capturing !== null || end.passesDone !== 1 || !end.ended) {
    failures.push(`착륙 뒤: ${JSON.stringify({ phase: end.phase, capturing: end.capturing, done: end.passesDone, ended: end.ended })}`);
  }
  const dry = feed.readProgress([...FLY.slice(0, 17), L(50, '[1760000019.600] [미션] FC 의 미션을 지웠다'), L(51, '[1760000019.700] [dry-run] 여기서 끝낸다. arm 하지 않았다.')]);
  if (dry.phase !== 'dryDone') failures.push(`dry-run 끝: ${dry.phase}`);
  const stopped = feed.readProgress([...FLY, L(200, '[1760000050.000] [중단] 사용자 중단 (Ctrl+C/SIGTERM) — 캡처 OFF')]);
  if (stopped.problems.length !== 1) failures.push('[중단] 줄을 못 모았다');
  if (feed.lineTone('[1.0] [중단] x') !== 'bad' || feed.lineTone('[1.0] [경고] x') !== 'warn' || feed.lineTone('[1.0] PASS 2 START t=1') !== 'pass') failures.push('줄 색 판정');
  if (feed.lineTone('test_sar_rtk.py: error: --altitude 는 2~30 m 여야 한다') !== 'bad') failures.push('ap.error 줄을 빨갛게 못 칠한다');
}

// ── 3-1. 보고 뜯기 · 이어 붙이기 ─────────────────────────────────────────
const report = (lines, extra = {}) => ({
  schema_version: '1', source_id: 'x500-001',
  run: { run_id: 'r1', command_id: 'cmd-a', state: 'running', dry_run: true, argv: ['--yes'], started_at: 1, ended_at: null, exit_code: null, lines, ...extra },
  emergency: null,
});
{
  feed.resetFlightRuns();
  const a = feed.parseFlightRun(report(FLY.slice(0, 5)), 'zoneA/drone/x500-001/flight_run');
  const b = feed.parseFlightRun(report(FLY.slice(3, 8)), 'zoneA/drone/x500-001/flight_run');
  if (a === null || b === null) failures.push('정상 보고를 못 뜯었다');
  else {
    feed.noteFlightRun(a);
    feed.noteFlightRun(b);
    const lines = feed.flightRuns()['x500-001'].run.lines;
    if (lines.length !== 8 || new Set(lines.map((l) => l.seq)).size !== 8) failures.push(`겹친 줄을 이어 붙이기: ${lines.length}줄`);
  }
  if (!feed.flightRunChannel('zoneA/drone/x500-001/flight_run') || feed.flightRunChannel('zoneA/drone/x500-001/fcx')) failures.push('토픽 판정');
  // 대조군 — 모양이 틀리면 묶음째 버린다.
  const broken = feed.parseFlightRun({ source_id: 'x500-001', run: { run_id: 'r1', state: 'flying' }, emergency: null });
  if (broken === null) controls.push('모르는 state 를 버렸다');
  else failures.push('대조군: state=flying 을 받아들였다');
  if (feed.runOutcome({ state: 'exited', exitCode: 2 }) !== 'badArgs' || feed.runOutcome({ state: 'exited', exitCode: -15 }) !== 'killed') failures.push('종료 코드 판정');
}

// ── 4. dry-run 짝 ───────────────────────────────────────────────────────
{
  feed.resetFlightRuns();
  commands.resetDryRuns();
  const listeners = new Set();
  const sent = [];
  const client = {
    getStatus: () => ({ state: 'open' }),
    onMessage(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    send(action, parameters) {
      const commandId = `cmd-${String(sent.length + 1).padStart(8, '0')}`;
      sent.push({ action, parameters, commandId });
      setTimeout(() => { for (const l of listeners) l({ kind: 'acceptance', commandId, accepted: true, code: null, message: null }); }, 5);
      return { sent: true, commandId };
    },
  };
  const link = { client, deviceId: 'x500-001', start: 'yes', stop: 'yes', emergency: 'yes', reason: '' };
  const p = plan.FLIGHT_DEFAULTS;

  const unconfirmed = await commands.issueFlightStart(link, p, { dryRun: false, confirmed: false });
  if (unconfirmed.sent || sent.length !== 0) failures.push('「yes」 없이 비행이 나갔다');
  const undeclared = await commands.issueFlightStart({ ...link, start: 'unknown' }, p, { dryRun: true, confirmed: false });
  if (undeclared.sent) failures.push('선언을 못 받았는데 시작이 나갔다');

  const outcome = await commands.issueFlightStart(link, p, { dryRun: true, confirmed: false });
  if (!outcome.sent || outcome.accepted !== true || sent.at(-1)?.action !== 'rtk_test_start' || sent.at(-1)?.parameters.dry_run !== 1) {
    failures.push(`dry-run 발행: ${JSON.stringify(outcome)} ${JSON.stringify(sent.at(-1))}`);
  }
  const entry = () => feed.flightRuns()['x500-001'];
  if (commands.dryRunPassed('x500-001', p, entry())) failures.push('결과가 오기 전에 통과로 쳤다');
  if (!commands.dryRunPending('x500-001', p, entry())) failures.push('기다리는 중으로 안 본다');

  // 대조군 — 남이 보낸 dry-run(다른 command_id)이 0 으로 끝났다.
  feed.noteFlightRun(feed.parseFlightRun(report([], { command_id: 'cmd-other', state: 'exited', exit_code: 0 })));
  if (commands.dryRunPassed('x500-001', p, entry())) failures.push('대조군: 남의 dry-run 을 내 것으로 쳤다');
  else controls.push('남의 dry-run 은 통과로 안 친다');

  feed.noteFlightRun(feed.parseFlightRun(report([], { run_id: 'r2', command_id: outcome.commandId, state: 'exited', exit_code: 1 })));
  if (commands.dryRunPassed('x500-001', p, entry())) failures.push('종료 코드 1 인 dry-run 을 통과로 쳤다');
  feed.noteFlightRun(feed.parseFlightRun(report([], { run_id: 'r2', command_id: outcome.commandId, state: 'exited', exit_code: 0 })));
  if (!commands.dryRunPassed('x500-001', p, entry())) failures.push('내 dry-run 이 0 으로 끝났는데 통과로 안 친다');
  if (commands.dryRunPassed('x500-001', { ...p, altitudeM: 6 }, entry())) failures.push('설정을 바꿨는데 통과가 남았다');

  const fly = await commands.issueFlightStart(link, p, { dryRun: false, confirmed: true });
  if (!fly.sent || sent.at(-1)?.parameters.confirmed !== 1 || sent.at(-1)?.parameters.dry_run !== 0) failures.push(`비행 발행: ${JSON.stringify(sent.at(-1))}`);
  const em = await commands.issueFlightEmergency(link, 'rtl');
  if (!em.sent || sent.at(-1)?.action !== 'rtk_test_emergency' || sent.at(-1)?.parameters.mode !== 1) failures.push(`비상 발행: ${JSON.stringify(sent.at(-1))}`);
  const stop = await commands.issueFlightStop({ ...link, stop: 'unknown' });
  if (!stop.sent || sent.at(-1)?.action !== 'rtk_test_stop') failures.push('선언을 모를 때 중단이 안 나갔다(모르면 보낸다)');
  const noStop = await commands.issueFlightStop({ ...link, stop: 'no' });
  if (noStop.sent) failures.push('중단을 선언하지 않았다고 밝힌 장비에 보냈다');
}

// ── 5. 스크립트 고르기 ──────────────────────────────────────────────────
{
  const tele = await load('src', 'shared', 'deviceTelemetry.ts');
  const d = plan.FLIGHT_DEFAULTS;
  const plainArgv = plan.argvPreview(d, true, plan.SCRIPT_PLAIN).join(' ');
  if (plainArgv.includes('--rtk-')) failures.push(`test_sar.py 명령줄에 RTK 옵션이 남았다: ${plainArgv}`);
  if (!plan.argvPreview(d, true).join(' ').includes('--rtk-min 30 --rtk-timeout 120')) failures.push('RTK 판 명령줄에서 RTK 옵션이 빠졌다');
  if (plan.scriptFor(true) !== 'test_sar_rtk.py' || plan.scriptFor(false) !== 'test_sar.py' || plan.scriptFor(null) !== null) failures.push('scriptFor 가 틀렸다');

  // 실물 pi3 의 state 모양(261022 실측) — rtk.corrections 가 false 면 test_sar.py.
  const g0 = commands.scriptGuess('x500-sg');
  if (g0.script !== null) failures.push(`보고가 없는데 스크립트를 짐작했다: ${g0.script}`);
  else controls.push('보정 보고가 없으면 스크립트를 짐작하지 않는다');
  tele.noteDeviceTelemetry('x500-sg', [{ path: 'rtk.fix' }], { body: { rtk: { corrections: false, fix: 'NONE' } } });
  if (commands.scriptGuess('x500-sg').script !== 'test_sar.py') failures.push(`보정이 없는데 ${commands.scriptGuess('x500-sg').script}`);
  tele.noteDeviceTelemetry('x500-sg', [{ path: 'rtk.fix' }], { body: { rtk: { corrections: true, fix: 'NONE' } } });
  if (commands.scriptGuess('x500-sg').script !== 'test_sar_rtk.py') failures.push('보정이 들어오는데 RTK 판으로 안 본다');
  // 실행기 판정: 보정이 끊겼어도 FC 가 이미 RTK_FLOAT/FIXED 면 RTK 판(REPORT_pi3_261022 §6).
  tele.noteDeviceTelemetry('x500-sg', [{ path: 'rtk.fix' }], { body: { rtk: { corrections: false, fix: 'RTK_FLOAT' } } });
  if (commands.scriptGuess('x500-sg').script !== 'test_sar_rtk.py') failures.push('보정은 끊겼지만 FC 가 RTK_FLOAT 인데 RTK 판으로 안 본다');
  tele.noteDeviceTelemetry('x500-sg', [{ path: 'rtk.fix' }], { body: { rtk: { corrections: true } }, atMs: Date.now() - 60_000 });
  if (commands.scriptGuess('x500-sg').script !== null) failures.push('낡은 보고로 스크립트를 짐작했다');

  // 돌아온 run.script — 있으면 그대로, 없던 실행기(261017 판)는 test_sar_rtk.py.
  const body = (extra) => ({ source_id: 'x500-sg', run: { run_id: 'r9', command_id: 'c9', state: 'exited', exit_code: 0, dry_run: true, lines: [], ...extra }, emergency: null });
  // 실물 모양(REPORT_pi3_261022 §6) — run.rtk 는 bool 이다.
  const withScript = feed.parseFlightRun(body({ script: 'test_sar.py', rtk: false }));
  if (withScript?.run?.script !== 'test_sar.py' || withScript.run.rtk !== false) failures.push(`run.script · run.rtk 를 못 읽었다: ${JSON.stringify(withScript?.run)}`);
  if (feed.parseFlightRun(body({ script: 'test_sar_rtk.py', rtk: true }))?.run?.rtk !== true) failures.push('run.rtk=true 를 못 읽었다');
  if (feed.parseFlightRun(body({ rtk: { corrections: true } }))?.run?.rtk !== null) failures.push('bool 이 아닌 run.rtk 에서 값을 지어냈다');
  if (commands.scriptOf(feed.parseFlightRun(body({}))?.run ?? null) !== 'test_sar_rtk.py') failures.push('script 칸이 없는 옛 보고를 test_sar_rtk.py 로 안 본다');
  if (feed.parseFlightRun(body({ rtk: null }))?.run?.rtk !== null) failures.push('run.rtk 가 null 인데 값을 지어냈다');
}

// ── 6. 착륙 상태 (261111) ────────────────────────────────────────────────
{
  const L = (text, seq) => ({ seq, text });
  // 11/9 실기 모양 — 항목 13개, LAND(#12) 뒤 진행 번호가 13 으로 넘어가고 착륙 완료 줄은 없다
  const base = [
    ...Array.from({ length: 13 }, (_, i) => `[1794196110.842] [미션] #${i}  ${i === 12 ? 'LAND     착륙' : 'WAYPOINT x'}`),
    '[1794196111.034] [명령] arm', '[1794196111.077] [명령] 미션 시작 — 이제부터 FC 가 이륙·왕복·착륙을 스스로 진행한다',
    '[1794196151.574] [미션] 진행 #12 LAND     착륙             36.5609065, 128.5593643  고도 0m  헤딩 288.3°',
    '[1794196153.489]        #12 진행  -0.1m  속도  0.0m/s  고도   0.9m  헤딩 288.0°',
  ];
  const before = feed.readProgress(base.map(L));
  if (before.missionDone || feed.landingOf(before) !== 'none') failures.push('LAND 진행 중(#12)을 미션 완료로 봤다');
  // 이륙 전 지상: FC 가 ON_GROUND · 무장 해제여도 미션이 안 끝났으면 착륙이 아니다
  if (feed.landingOf(before, { landedState: 'ON_GROUND', armed: false }) !== 'none') failures.push('미션이 안 끝났는데 FC 지상 값으로 착륙이라 했다');
  else controls.push('이륙 전 지상을 착륙으로 안 본다');

  const done = feed.readProgress([...base, '[1794196157.525]        #13 진행  -0.0m  속도  0.0m/s  고도  -0.7m  헤딩 289.9°'].map(L));
  if (!done.missionDone || done.liveItem !== 13 || feed.landingOf(done) !== 'missionDone') failures.push(`진행 #13/13 을 FC 미션 완료로 못 봤다: ${feed.landingOf(done)}`);
  if (feed.landingOf(done, { landedState: 'ON_GROUND', armed: true }) !== 'onGround') failures.push('FC 텔레메트리 ON_GROUND 를 착지로 못 봤다');
  if (feed.landingOf(done, { landedState: 'ON_GROUND', armed: false }) !== 'disarmed') failures.push('FC 텔레메트리 무장 해제를 못 봤다');

  // `[착륙감시]` 줄 — 변화 줄과 요약 줄(판정창의 cur=12∧in_air=False 는 지금 값이 아니다 — 「끝 …」이 지금 값)
  const watch = feed.readProgress([...base,
    '[1794196155.100] [착륙감시] 변화 in_air True→False t=+2.556 | cur=12/13 in_air=False landed=ON_GROUND armed=True mode=MISSION',
    '[1794196205.600] [착륙감시] 요약 판정창(cur=12∧in_air=False) 겹침=0.000s/0회 | cur 12→13 t=+2.536 | 끝 cur=13/13 in_air=False landed=ON_GROUND armed=False mode=RETURN_TO_LAUNCH',
  ].map(L));
  const w = watch.landWatch;
  if (!w.seen || w.inAir !== false || w.landed !== 'ON_GROUND' || w.armed !== false || w.mode !== 'RETURN_TO_LAUNCH' || w.overlapS !== 0) failures.push(`[착륙감시] 줄을 잘못 읽었다: ${JSON.stringify(w)}`);
  if (feed.landingOf(watch) !== 'disarmed') failures.push(`[착륙감시] 가 무장 해제를 말하는데 ${feed.landingOf(watch)}`);
  // [착륙감시] 줄이 다른 판정 줄을 건드리지 않는다 — 진행 · 문제 · 경고 · 끝
  if (watch.live !== before.live || watch.problems.length !== 0 || watch.warnings !== 0 || watch.ended || watch.phase !== 'mission') failures.push('[착륙감시] 줄이 다른 판정을 바꿨다');
  if (feed.lineTone('[1794196205.600] [착륙감시] 요약 판정창 …') !== '') failures.push('[착륙감시] 줄에 색을 칠했다');

  // 정상 — 착륙 완료 줄이 있으면 그것이 이긴다
  const ok = feed.readProgress([...base, '[1794196157.000] [확인] 착륙 완료 ✔'].map(L));
  if (feed.landingOf(ok) !== 'confirmed') failures.push('착륙 완료 줄을 confirmed 로 안 봤다');
  // 대조군 — 진행 번호만 보던 옛 판정(LAND 항목 번호 == 착륙)은 #12 진행 중을 착륙으로 잘못 본다
  const naive = (p) => p.liveItem !== null && p.itemsTotal !== null && p.liveItem >= p.itemsTotal - 1;
  if (naive(before)) controls.push('「#12 = 착륙」 옛 판정은 LAND 진행 중을 착륙으로 본다'); else failures.push('대조군(#12 = 착륙)이 안 걸렸다');
}

if (failures.length > 0) {
  console.error('❌ verify:flight-run');
  for (const failure of failures) console.error('  - ' + failure);
  process.exit(1);
}
console.log(`✅ 통과 — 예상 시간 · 파라미터 · 출력 읽기 · dry-run 짝 · 스크립트 고르기 · 착륙 상태(FC 미션 완료 · [착륙감시]) (대조군 ${controls.length}개: ${controls.join(' / ')})`);
