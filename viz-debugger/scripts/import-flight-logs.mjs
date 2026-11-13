// import-flight-logs (261111 신설 — 조작 기록에 Pi 비행 로그를 들인다)
//
// **라즈베리파이(pi3)에 남은 비행 로그를 조작 판으로 바꿔 `mission-history/` 에 넣는다.** 조작 기록(`controlRecorder.ts`)이
// 생기기 전에 가시화에서 날린 비행은 웹 쪽 기록이 없다. Pi 에는 실행기 출력 · 스크립트 로그 · FC 텔레메트리가 남아 있으니
// 그것으로 같은 모양의 판을 만든다 — 이력 목록과 「기록 보기」가 그대로 연다.
//
//   node scripts/import-flight-logs.mjs <로그 폴더> [--device x500-001] [--out <mission-history>] [--dry]
//
// 로그 폴더의 모양(`flight_20261109/README.md`):
//   script_logs/<날짜_시각>.out      실행기 출력 — 실행 하나. `-e.out` 은 비상 명령
//   cansar/<세션>/mav.csv            FC 위치 · 자세 · GPS (pi_epoch 기준) — 텔레메트리 표본의 재료
//
// ## 있는 것만 옮긴다
//
// - **웹이 낸 명령과 장비의 답은 없다** — Pi 로그에 없다. 사건은 판의 열림 · 닫힘뿐이고, 요약에 `imported` 를 달아
//   화면이 「가져온 판」이라고 말하게 한다.
// - **종료 코드는 없다**(`.out` 에 안 찍힌다) — `exitCode: null`. 대신 스크립트가 찍은 `[중단]` · `[오류]` 줄을 결과로 적는다.
// - 텔레메트리는 판 시작 ~ 끝을 1.5초(`controlRecorder` 의 주기)마다, 그 시각 이전 5초 안에 온 값만 — 웹 기록기와 같은 규칙.
//   mav.csv 에 없는 배터리 · 모드 · 무장은 칸을 만들지 않는다. 수신 간격도 브라우저가 잰 값이 아니므로 안 만든다.
// - NULL 바이트로 깨진 줄은 건너뛴다(README).
//
// ## 판 나누기 — 웹 기록기와 같은 규칙
//
// dry-run 과 그 뒤 `DRY_LINK_MS` 안에 이어 날린 비행은 한 판이다(dry-run 을 여러 번 했어도). 비상 명령은 그 시각에 돌던
// 판에 붙는다. 이어 날린 비행이 없는 dry-run 은 dry-run 만의 판이다.
//
// 같은 폴더를 다시 들이면 그 폴더에서 들였던 판을 지우고 새로 쓴다(판 나누기가 바뀌어도 옛 판이 남지 않는다).

import { createReadStream, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { basename, join, relative, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath, pathToFileURL } from 'node:url';

const vizRoot = resolve(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(vizRoot, ...p)).href);
const { landingOf, readProgress, runOutcome, stripTime } = await load('src', 'physical', 'flightRunFeed.ts');
const { runFolderOf } = await load('src', 'record', 'recordClient.ts');
const { CONTROL_SCHEMA, DRY_LINK_MS, TELEMETRY_FRESH_MS } = await load('src', 'record', 'controlRecorder.ts');

const args = process.argv.slice(2);
const flag = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : fallback; };
const source = args.find((a, i) => !a.startsWith('--') && !args[i - 1]?.startsWith('--'));
if (source === undefined) {
  console.error('사용법: node scripts/import-flight-logs.mjs <로그 폴더> [--device x500-001] [--out <mission-history>] [--dry]');
  process.exit(2);
}
const root = resolve(source);
const deviceId = flag('--device', 'x500-001');
const outDir = resolve(flag('--out', process.env.MISSION_RECORDS_DIR ?? join(vizRoot, '..', 'mission-history')));
const dry = args.includes('--dry');
const SAMPLE_MS = 1_500;
const repoRoot = resolve(vizRoot, '..');
const shown = (path) => relative(repoRoot, path).replaceAll('\\', '/');

// ── 실행기 출력 ─────────────────────────────────────────────────────────────

const EPOCH = /^\[(\d+(?:\.\d+)?)\]/;

function readRun(file) {
  const name = basename(file, '.out');
  const emergency = name.endsWith('-e');
  const text = readFileSync(file, 'utf8').replace(/\r/g, '');
  const raw = text.split('\n');
  while (raw.length > 0 && raw.at(-1).trim() === '') raw.pop();
  const lines = raw.map((t, seq) => ({ seq, text: t.trimEnd() }));
  const epochs = lines.map((l) => l.text.match(EPOCH)?.[1]).filter(Boolean).map(Number);
  if (epochs.length === 0) return null;
  const setting = lines.find((l) => /\[설정\]/.test(l.text))?.text ?? '';
  const dryMatch = setting.match(/'dry_run':\s*(True|False)/);
  const logPath = lines.find((l) => /\[로그\]/.test(l.text))?.text.match(/\[로그\]\s*(\S+)/)?.[1] ?? null;
  const script = logPath === null ? null : `${basename(logPath).replace(/_\d{8}_\d{6}\.log$/, '')}.py`;
  const mode = emergency ? (lines.find((l) => /\[명령\]\s*(LAND|RTL|HOLD)/i.test(l.text))?.text.match(/\[명령\]\s*(LAND|RTL|HOLD)/i)?.[1].toLowerCase() ?? null) : null;
  const problems = readProgress(lines).problems;
  return {
    runId: name,
    commandId: null,
    state: 'exited',
    dryRun: emergency ? null : dryMatch === null ? null : dryMatch[1] === 'True',
    argv: [],
    startedAt: epochs[0],
    endedAt: epochs.at(-1),
    exitCode: null,
    outPath: `/home/physical/cansar_logs/runner/${name}.out`,
    mode,
    script,
    // 실행기는 RTK 보정이 들어오면 test_sar_rtk.py 를 띄운다(flightRunFeed.ts `script`) — 띄운 스크립트가 곧 그 판정이다.
    rtk: emergency || script === null ? null : script === 'test_sar_rtk.py',
    lines,
    emergency,
    file,
    result: problems.length > 0 ? stripTime(problems[0]).trim() : null,
  };
}

const logDir = join(root, 'script_logs');
const runs = readdirSync(logDir).filter((f) => f.endsWith('.out')).sort()
  .map((f) => readRun(join(logDir, f))).filter((r) => r !== null);

// dry-run → 이어 날린 비행은 한 판(`controlRecorder.ts` 의 `dryLinkable` 과 같은 규칙). 비상 명령은 그 시각에 돌던 판에 붙는다.
const sessions = [];
for (const run of runs) {
  const last = sessions.at(-1);
  if (run.emergency) {
    const host = [...sessions].reverse().find((s) => s.runs[0].startedAt <= run.startedAt);
    if (host) host.emergencies.push(run);
    else sessions.push({ runs: [run], emergencies: [] });
    continue;
  }
  const lastEnd = last === undefined ? null : Math.max(...last.runs.map((r) => r.endedAt));
  const linkable = last !== undefined && last.runs.every((r) => r.dryRun === true) && (run.startedAt - lastEnd) * 1000 <= DRY_LINK_MS;
  if (linkable) last.runs.push(run);
  else sessions.push({ runs: [run], emergencies: [] });
}

// ── FC 텔레메트리 (mav.csv) ───────────────────────────────────────────────────

const FIX = { 0: 'NO_GPS', 1: 'NO_FIX', 2: 'FIX_2D', 3: 'FIX_3D', 4: 'FIX_DGPS', 5: 'RTK_FLOAT', 6: 'RTK_FIXED' };

async function readMav(file) {
  const pos = [];
  const att = [];
  const gps = [];
  let broken = 0;
  const rl = createInterface({ input: createReadStream(file, 'utf8'), crlfDelay: Infinity });
  for await (const line of rl) {
    if (line.includes('\u0000')) { broken += 1; continue; }
    const f = line.split(',');
    const t = Number(f[0]) * 1000;
    if (!Number.isFinite(t)) continue;
    const n = (i) => (f[i] === undefined || f[i] === '' ? null : Number(f[i]));
    if (f[2] === 'GLOBAL_POSITION_INT') {
      const [lat, lon, rel, vx, vy] = [n(4), n(5), n(7), n(8), n(9)];
      if (lat === null || lon === null) continue;
      pos.push({ t, lat: lat / 1e7, lon: lon / 1e7, altM: rel === null ? null : rel / 1000,
        speed: vx === null || vy === null ? null : Math.hypot(vx, vy) / 100 });
    } else if (f[2] === 'ATTITUDE') {
      const yaw = n(6);
      if (yaw !== null) att.push({ t, heading: ((yaw * 180) / Math.PI + 360) % 360 });
    } else if (f[2] === 'GPS_RAW_INT') {
      const fix = n(7);   // GPS_RAW_INT: f1 lat · f2 lon · f3 alt · f4 fix_type · f5 위성 수
      if (fix !== null) gps.push({ t, fix: FIX[fix] ?? `FIX_${fix}` });
    }
  }
  const byTime = (a, b) => a.t - b.t;
  pos.sort(byTime); att.sort(byTime); gps.sort(byTime);
  return { pos, att, gps, broken, from: pos[0]?.t ?? null, to: pos.at(-1)?.t ?? null };
}

/** `t` 이전 `TELEMETRY_FRESH_MS` 안의 마지막 값. 이분 탐색. */
function latest(list, t) {
  let lo = 0;
  let hi = list.length - 1;
  let best = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (list[mid].t <= t) { best = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return best >= 0 && t - list[best].t <= TELEMETRY_FRESH_MS ? list[best] : null;
}

const cansarDir = join(root, 'cansar');
const mavs = [];
for (const dir of existsSync(cansarDir) ? readdirSync(cansarDir).sort() : []) {
  const file = join(cansarDir, dir, 'mav.csv');
  if (!existsSync(file)) continue;
  const mav = await readMav(file);
  mavs.push({ dir, file, ...mav });
}

/** 컬럼 차례는 `controlRecorder.ts` 의 TELEMETRY_COLUMNS 에서 mav.csv 가 주는 것만. */
const COLUMNS = ['atMs', 'speedMps', 'altM', 'lat', 'lon', 'headingDeg', 'gpsFix'];

function telemetryFor(startMs, endMs) {
  const mav = mavs.find((m) => m.from !== null && m.from <= endMs && m.to >= startMs);
  if (!mav) return null;
  const rows = [];
  for (let t = startMs; t <= endMs + 1; t += SAMPLE_MS) {
    const p = latest(mav.pos, t);
    const a = latest(mav.att, t);
    const g = latest(mav.gps, t);
    if (p === null && a === null && g === null) continue;
    const r = (v, d) => (v === null ? null : Math.round(v * 10 ** d) / 10 ** d);
    rows.push([Math.round(t), r(p?.speed ?? null, 2), r(p?.altM ?? null, 2), r(p?.lat ?? null, 7), r(p?.lon ?? null, 7), r(a?.heading ?? null, 1), g?.fix ?? null]);
  }
  if (rows.length === 0) return null;
  const keep = COLUMNS.map((_, i) => i === 0 || rows.some((row) => row[i] !== null));
  return {
    mav,
    body: { columns: COLUMNS.filter((_, i) => keep[i]), rows: rows.map((row) => row.filter((_, i) => keep[i])), truncated: false },
  };
}

// ── 판 쓰기 ─────────────────────────────────────────────────────────────────

const iso = (ms) => new Date(ms).toISOString();
const report = [];

// 이 로그 폴더에서 들였던 판을 지운다 — 판 나누기가 바뀌었어도 옛 판이 남지 않게.
if (!dry && existsSync(outDir)) {
  const prefix = `${shown(root)}/`;
  for (const date of readdirSync(outDir)) {
    if (!/^\d{6}$/.test(date)) continue;
    for (const run of readdirSync(join(outDir, date))) {
      const file = join(outDir, date, run, 'mission.json');
      if (!existsSync(file)) continue;
      try {
        const imported = JSON.parse(readFileSync(file, 'utf8')).imported;
        if (imported?.source === 'pi-log' && String(imported.from).startsWith(prefix)) rmSync(join(outDir, date, run), { recursive: true, force: true });
      } catch { /* 깨진 판은 건드리지 않는다 */ }
    }
  }
}

for (const { runs: group, emergencies } of sessions) {
  // 요약은 마지막 실행(이어 날린 비행)의 것이다 — 웹 기록기의 `main = runs.at(-1)` 과 같다.
  const main = group.at(-1);
  const startMs = Math.round(group[0].startedAt * 1000);
  const endMs = Math.round(Math.max(...group.map((r) => r.endedAt), ...emergencies.map((e) => e.endedAt)) * 1000);
  const folder = runFolderOf(new Date(startMs), `FLT-${deviceId}`);
  const telemetry = telemetryFor(startMs, endMs);
  const strip = ({ emergency, file, result, ...process }) => process;
  const modes = [];
  const rows = telemetry?.body.rows ?? [];
  const summary = {
    schema: CONTROL_SCHEMA,
    recordKind: 'control',
    folder: `${folder.date}/${folder.run}`,
    sessionKind: 'flight',
    deviceId,
    missionId: folder.run.slice(7),
    startedAtIso: iso(startMs),
    updatedAtIso: iso(endMs),
    endedAtIso: iso(endMs),
    closeReason: 'flightExited',
    counts: { commands: 0, rejected: 0, blocked: 0, notSent: 0, keepalive: 0 },
    actions: {},
    missions: [],
    flight: {
      dryRun: main.dryRun,
      runId: main.runId,
      script: main.script,
      rtk: main.rtk,
      exitCode: null,
      outcome: runOutcome(strip(main)),
      phase: readProgress(main.lines).phase,
      emergencies: emergencies.length,
      dryRuns: group.filter((r) => r !== main && r.dryRun === true).length,
      landing: landingOf(readProgress(main.lines)),
    },
    telemetry: rows.length === 0 ? null : {
      samples: rows.length, batteryStart: null, batteryEnd: null, batteryMin: null, maxRxAgeS: null, modes, truncated: false,
    },
    imported: {
      source: 'pi-log',
      from: group.map((r) => shown(r.file)).join(' · '),
      emergencyFrom: emergencies.map((e) => shown(e.file)),
      telemetryFrom: telemetry === null ? null : shown(telemetry.mav.file),
      result: emergencies.length > 0 ? `${main.result ?? ''}${main.result ? ' · ' : ''}${emergencies.map((e) => e.mode ?? 'emergency').join(', ')}`.trim() : main.result,
      importedAtIso: new Date().toISOString(),
    },
  };
  const progress = {
    schema: CONTROL_SCHEMA,
    deviceId,
    sessionKind: 'flight',
    updatedAtIso: iso(endMs),
    events: [
      { atMs: startMs, kind: 'opened', reason: 'flightStart' },
      { atMs: endMs, kind: 'closed', reason: 'flightExited' },
    ],
    flight: { startCommandId: null, dryRun: main.dryRun, runs: group.map(strip), emergencies: emergencies.map(strip) },
    ...(telemetry === null ? {} : { telemetry: telemetry.body }),
  };
  report.push({ folder: `${folder.date}/${folder.run}`, run: group.map((r) => `${r.runId}${r.dryRun ? '(dry)' : ''}`).join(' + '), dry: main.dryRun, script: main.script, samples: rows.length, emergencies: emergencies.length, result: summary.imported.result });
  if (dry) continue;
  const dir = join(outDir, folder.date, folder.run);
  mkdirSync(dir, { recursive: true });
  for (const [file, body] of [['progress.json', JSON.stringify(progress)], ['mission.json', JSON.stringify(summary, null, 2)]]) {
    const tmp = join(dir, `.${file}.tmp`);
    writeFileSync(tmp, body);
    renameSync(tmp, join(dir, file));
  }
}

for (const mav of mavs) if (mav.broken > 0) console.log(`  · ${shown(mav.file)}: 깨진 줄 ${mav.broken}개 건너뜀`);
for (const r of report) {
  console.log(`${r.folder}  ${r.run}  ${r.dry === true ? 'dry-run' : r.dry === false ? '비행   ' : '—      '}  ${r.script ?? '—'}  표본 ${r.samples}${r.emergencies ? `  비상 ${r.emergencies}` : ''}${r.result ? `  — ${r.result}` : ''}`);
}
console.log(`${dry ? '(--dry: 쓰지 않음) ' : ''}판 ${report.length}개 → ${shown(outDir)}`);
