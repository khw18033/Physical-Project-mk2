// measure:trace-scale (260920 신설 — 명령 기록 합류 §8 · 260921 라이브 열까지 넓힘)
//
// **층별 사건 수. 논문 §5-2 축 가의 분모가 되는 숫자다.**
//
// 지금 분모가 노드 24개라 「축소했다」는 말이 안 선다. 600줄을 40줄로 줄였다고 말하려면
// 600이 실재해야 하고, 그 600을 만드는 것이 액션 층이다 — 명령 하나에 응답이 여럿 붙고,
// 태스크 하나가 명령을 여럿 낸다.
//
// **재는 것이지 판정하는 것이 아니다.** 여기서 아무것도 실패시키지 않는다. 기준선과 견주는
// 것은 보고서가 하고, 규칙을 지키는 것은 `verify:*` 가 한다.
//
// 기준선 (260920 실측, 이 작업 착수 전):
//   대본 6편 합계 — 마일스톤 30 · 태스크 83 · 액션 아이템 4 · 사건 280
//
// ## 260921 — 라이브 열도 같은 자리에서 센다
//
// **대본용과 라이브용을 두 벌 만들지 않는다.** 세는 규칙이 갈리면 두 숫자를 견줄 수 없다.
// 층을 세는 자리는 `tally()` 하나이고, 대본과 라이브는 거기에 **재료만** 다르게 넣는다.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const scenarioDir = join(root, 'scenarios');
const historyDir = join(root, '..', 'mission-history');

const { actionItemEvents, ACTION_KINDS, ACTION_KIND_LIST } = await load('src', 'data', 'actionTrace.ts');
/** 액션 층 어휘. `actionTrace.ts` 의 목록을 그대로 쓴다 — 여기서 새로 적으면 갈린다. */
const ACTION_KIND_SET = new Set(ACTION_KIND_LIST);
const { ACTION_SEQ_BASE, LIVE_ACTION_SEQ_BASE } = await load('src', 'data', 'trace.ts');
const { NO_NODE } = await load('src', 'physical', 'missionLink.ts');

/** 착수 전 실측. 이 작업이 분모를 얼마나 키웠는지를 말하려면 출발점이 있어야 한다. */
const BASELINE = { milestones: 30, tasks: 83, actionItems: 4, events: 280 };

// ── 세는 규칙 하나 ──────────────────────────────────────────────────────────
//
// 대본이든 라이브든 **이 함수만 층을 센다.** 재료(`taskLayer` · `action`)를 만드는 방법이
// 다를 뿐이다.

/**
 * 한 판(또는 한 편)의 층별 합계.
 *
 * @param taskLayer  태스크·마일스톤 층 사건 — 대본은 `script.events`, 라이브는 `progress.trace`
 * @param action     액션 층 사건 — `{ commanded, answered, expired, adjusted }`
 */
function tally(taskLayer, action) {
  const derived = action.commanded + action.answered + action.expired + action.adjusted;
  return { taskLayer, ...action, derived, total: taskLayer + derived };
}

const COLUMNS = ['마일스톤', '태스크', '태스크층', '명령', '응답', '기한', '조정', '액션층', '합계'];

function printRows(rows, nameWidth, nameHeader, { header = true } = {}) {
  const head = nameHeader.padEnd(nameWidth) +
    '  마일스톤  태스크    태스크층   명령   응답  기한  조정   액션층    합계';
  if (header) {
    console.log(head);
    console.log('─'.repeat(head.length));
  }
  const line = (name, r) => console.log(
    name.padEnd(nameWidth) +
    String(r.milestones).padStart(10) +
    String(r.tasks).padStart(8) +
    String(r.taskLayer).padStart(12) +
    String(r.commanded).padStart(7) +
    String(r.answered).padStart(7) +
    String(r.expired).padStart(6) +
    String(r.adjusted).padStart(6) +
    String(r.derived).padStart(9) +
    String(r.total).padStart(8),
  );
  for (const r of rows) line(r.name, r);
  return line;
}

const sumOf = (rows, key) => rows.reduce((total, row) => total + row[key], 0);

function totalRow(rows) {
  const keys = ['milestones', 'tasks', 'taskLayer', 'commanded', 'answered', 'expired', 'adjusted', 'derived', 'total'];
  return Object.fromEntries(keys.map((k) => [k, sumOf(rows, k)]));
}

// ── 1. 대본 ─────────────────────────────────────────────────────────────────

/** 대본 원본만. 사이드카(`.en.json` · `.match.json`)는 대본이 아니다. */
const scripts = readdirSync(scenarioDir)
  .filter((name) => /^MSN-[\d-]+\.json$/.test(name))
  .map((name) => JSON.parse(readFileSync(join(scenarioDir, name), 'utf8')))
  .sort((a, b) => a.missionId.localeCompare(b.missionId));

const scriptRows = scripts.map((script) => {
  const derived = actionItemEvents(script.tasks, ACTION_SEQ_BASE);
  const of = (kind) => derived.filter((e) => e.kind === kind).length;
  return {
    name: script.missionId,
    missionId: script.missionId,
    milestones: script.milestones.length,
    tasks: script.tasks.length,
    /** 대본이 **정의**한 액션 아이템 수. 그중 명령 정의가 있는 것만 흐른다. */
    actionItems: script.tasks.reduce((sum, task) => sum + (task.actionItems?.length ?? 0), 0),
    ...tally(script.events.length, {
      commanded: of(ACTION_KINDS.commanded),
      answered: of(ACTION_KINDS.answered),
      expired: of(ACTION_KINDS.expired),
      adjusted: of(ACTION_KINDS.adjusted),
    }),
  };
});

console.log('기록 열 규모 실측 — 층별 사건 수 (논문 §5-2 축 가의 분모)\n');
console.log('■ 대본 (재생)\n');
printRows(scriptRows, 16, '대본');
const scriptTotal = totalRow(scriptRows);
console.log('─'.repeat(78));
printRows([{ name: '합계', ...scriptTotal }], 16, '', { header: false });

const total = scriptTotal.total;
console.log('');
console.log(`기준선(260920 착수 전) — 마일스톤 ${BASELINE.milestones} · 태스크 ${BASELINE.tasks} · 액션 아이템 ${BASELINE.actionItems} · 사건 ${BASELINE.events}`);
console.log(`지금                   — 마일스톤 ${scriptTotal.milestones} · 태스크 ${scriptTotal.tasks} · 액션 아이템 ${sumOf(scriptRows, 'actionItems')} · 사건 ${total}`);
console.log(`사건 ${BASELINE.events} → ${total} (×${(total / BASELINE.events).toFixed(2)}) · 액션 층이 ${scriptTotal.derived}건을 더했다`);

// **한 편만 채웠다** (§5). 나머지 다섯은 다음 작업이고, 그 사실을 숫자 옆에 적어 둔다 —
// 「배수가 왜 이것밖에 안 되나」의 답이 여기 있다.
const filled = scriptRows.filter((row) => row.derived > 0);
const empty = scriptRows.filter((row) => row.derived === 0);
console.log('');
console.log(`액션 아이템을 채운 편 — ${filled.map((r) => r.missionId).join(', ') || '없음'} (${filled.length}/${scriptRows.length}편)`);
console.log(`아직 안 채운 편       — ${empty.map((r) => r.missionId).join(', ')}`);

// ── 2. 라이브 한 판 ─────────────────────────────────────────────────────────
//
// ## 라이브 열은 어디서 오나
//
// `mission-history/<날짜>/<시각>_<임무>/progress.json` 이다 (`scripts/mission-records.mjs`).
// `trace` 가 태스크·마일스톤 층이고, 액션 층은 `robot.commands` 에 있다.
//
// ## 260920 앞의 판을 어떻게 **같은 규칙으로** 세나
//
// 보관된 판은 액션 층 합류(260920)보다 앞서서 `commanded`·`answered` 가 열에 없다.
// 그래도 규칙은 확정적으로 복원된다 — `robotBridge.ts` 가 uplink 한 줄마다
// `noteCommandLog` 와 `recordAnswered` 를 **나란히** 부르고, `taskId` 가 `null`·`NO_NODE`
// 일 때만 뒤엣것을 건너뛴다 (같은 파일 §「기록 열에도 같은 줄을 넣는다」).
//
//   · `commanded` = `taskId` 가 있는(`NO_NODE` 아닌) 명령 수
//   · `answered`  = 그 명령들의 `log` 줄 수 — 1:1 이다
//
// ## 명령을 두 번 세지 않는다
//
// **보관된 판의 `trace` 에 이미 명령이 들어 있다.** 260920 앞에는 명령이 사람 층에 적혔다 —
// `nodeId: 'robot-01'` · `seq` 사람 대역 · `producedBy: 'human'` · `payload.task_id`.
// 260920 이 그것을 액션 층 `commanded` 로 옮겼고 `NO_NODE` 는 아예 열에서 뺐다.
//
// 그래서 `trace.length` 를 그대로 태스크 층으로 치면 **명령을 두 번 센다.** 옛 명령 줄을
// 태스크 층에서 걷어 내고 액션 층으로 옮겨 세야 260920 규칙과 같은 숫자가 나온다.
// 걷어 내는 기준은 `payload.task_id` 의 유무다 — 명령 줄만 그것을 달고 있다.
//
// **`expired` 는 복원할 수 없다.** `CommandLogLine.kind` 가 `acceptance|status|result` 뿐이라
// 「기다림이 끝났다」는 줄로 안 남는다. 일시정지·중단이 4초 안에 답을 못 받은 판에서만 나므로
// (`robotCommands.ts` 의 `reportPauseAnswer`), 답이 온 판은 0 이고 그 한계를 같이 적는다.

/** 보관된 한 판. 없으면 `null`. */
function readRun(dir) {
  const missionPath = join(dir, 'mission.json');
  const progressPath = join(dir, 'progress.json');
  if (!existsSync(missionPath) || !existsSync(progressPath)) return null;
  const mission = JSON.parse(readFileSync(missionPath, 'utf8'));
  const progress = JSON.parse(readFileSync(progressPath, 'utf8'));
  return { mission, progress, bytes: statSync(progressPath).size };
}

/** 이 명령이 기록 열에 들어가는가. `NO_NODE` 는 순서도에 자리가 없어 안 들어간다. */
const inColumn = (command) => command.taskId != null && command.taskId !== NO_NODE;

/** 옛 명령 줄인가 — 사람 층에 적히는 명령. `payload.task_id`(밑줄)는 이 줄만 단다. */
const isLegacyCommandEvent = (event) => event?.payload?.task_id !== undefined;

/** 260920 정식 액션 사건인가. */
const isActionEvent = (event) => ACTION_KIND_SET.has(event?.kind);

/**
 * **실제로 오간 것인가, 대본이 편 것인가.** `seq` 대역이 가른다 —
 * 대본 1.5M · 라이브 1.75M (`trace.ts`). 두 재생기가 같이 흐를 수 있어 일부러 갈라 둔
 * 대역이고, 여기서 그대로 쓴다. **로봇 없이 대본만 돌린 판을 실물로 세지 않기 위해서다.**
 */
const isLiveEvent = (event) => Number(event?.seq) >= LIVE_ACTION_SEQ_BASE;

function liveRow(folder, run) {
  const { mission, progress } = run;
  const commands = Object.values(progress.robot?.commands ?? {});
  const columned = commands.filter(inColumn);
  const answered = columned.reduce((sum, c) => sum + (c.log?.length ?? 0), 0);

  const trace = progress.trace ?? [];

  // ── 판이 어느 시대인가 ────────────────────────────────────────────────────
  //
  // 260920 뒤의 판은 `commanded`·`answered` 가 **열에 직접 들어 있다.** 그때는 복원하지
  // 말고 열을 그대로 세야 한다 — 복원해서 더하면 같은 명령을 두 번 센다.
  const actionInTrace = trace.filter(isActionEvent);
  const modern = actionInTrace.length > 0;

  // 태스크·마일스톤 층 — 옛 명령 줄과 액션 사건을 **둘 다** 걷어 낸 나머지.
  const taskLayer = trace.filter((e) => !isLegacyCommandEvent(e) && !isActionEvent(e)).length;

  // 일시정지·중단이 답을 못 받은 것만 기한이다. 260920 앞의 판에서는 줄로 안 남으므로
  // 이 모양으로만 셀 수 있다 (한계).
  const silentPause = columned.filter((c) => /abort|pause|stop/i.test(String(c.action)) && (c.log?.length ?? 0) === 0);

  const countKind = (kind) => actionInTrace.filter((e) => e.kind === kind).length;
  const action = modern
    ? {
      commanded: countKind(ACTION_KINDS.commanded),
      answered: countKind(ACTION_KINDS.answered),
      expired: countKind(ACTION_KINDS.expired),
      adjusted: countKind(ACTION_KINDS.adjusted),
    }
    : { commanded: columned.length, answered, expired: silentPause.length, adjusted: 0 };

  // 두 자리에서 센 명령 수가 어긋나면 규칙이 틀린 것이다 — 조용히 넘기지 않는다.
  const fromTrace = modern
    ? countKind(ACTION_KINDS.commanded)
    : trace.filter((e) => isLegacyCommandEvent(e) && e.payload.task_id !== NO_NODE).length;
  const mismatch = fromTrace !== columned.length ? ` ⚠ 열 ${fromTrace} ≠ 작업대 ${columned.length}` : '';

  /**
   * **옛 명령 줄이 아직 같이 적힌다.** 260920 이 액션 층을 더하면서 사람 층의 옛 명령
   * 줄을 안 지웠다. 그래서 260920 뒤의 판에는 같은 명령이 **두 벌** 있다. 정식 분모는
   * 액션 층 쪽이고, 중복분은 따로 내놓는다 — 지울지는 이 스크립트가 정할 일이 아니다.
   */
  const legacyDuplicates = modern
    ? trace.filter((e) => isLegacyCommandEvent(e) && e.payload.task_id !== NO_NODE).length
    : 0;

  /** 실제로 오간 액션 사건이 있나 — 대본만 돌린 판과 가른다. */
  const liveActions = actionInTrace.filter(isLiveEvent).length;

  const lines = columned.map((c) => c.log?.length ?? 0);
  const scan = columned.filter((c) => String(c.action) === 'scan_mission').map((c) => c.log?.length ?? 0);

  const startMs = Date.parse(mission.startedAtIso);
  const endMs = Date.parse(mission.endedAtIso ?? mission.updatedAtIso);

  return {
    name: folder + mismatch,
    missionId: mission.missionId,
    outcome: mission.outcome ?? 'null',
    done: `${mission.done}/${mission.of}`,
    /**
     * **실물 로봇이 몬 판인가.**
     *
     * `mission.robotDriven` 은 **믿을 수 없다** — `robotDrives()` 가 「지금 브로커에 붙어
     * 있나」이고 기록은 판이 끝난 뒤에도 계속 덮어써진다. 실제로 260921/114930 은 실물로
     * 완주했는데 250초 뒤 마지막 기록 때 로봇이 떨어져 있어 `false` 로 남았다.
     *
     * 그래서 **증거로 판정한다.** 260920 뒤의 판은 라이브 대역 액션 사건이 있으면 실물이고,
     * 그 앞의 판은 로봇이 준 응답 줄이 있으면 실물이다. 목(`mockScanUplink`)은
     * `verify:*` 만 쓰고 앱은 안 쓰므로 응답 줄이 있으면 실물에서 온 것이다.
     */
    robotDriven: mission.testMode !== true && (modern ? liveActions > 0 : answered > 0),
    /** 기록에 적힌 값 그대로. 위 판정과 어긋나는 것을 보이기 위해 같이 든다. */
    robotDrivenFlag: mission.robotDriven === true,
    modern,
    legacyDuplicates,
    broker: mission.connections?.robot ?? '',
    milestones: mission.view?.milestones?.length ?? 0,
    tasks: mission.view?.tasks?.length ?? 0,
    actionItems: 0,
    ...tally(taskLayer, action),
    /** 열 밖 — `NO_NODE` 명령과 그 응답. 계측 범위 밖이라는 사실을 숫자로 남긴다. */
    outsideCommands: commands.length - columned.length,
    outsideLines: commands.filter((c) => !inColumn(c)).reduce((s, c) => s + (c.log?.length ?? 0), 0),
    lines,
    scanLines: scan,
    seconds: Number.isFinite(startMs) && Number.isFinite(endMs) ? (endMs - startMs) / 1000 : null,
    /** 기록 열만의 바이트 — 그림·뷰포인트 프레임은 열이 아니다. */
    columnBytes: Buffer.byteLength(JSON.stringify(trace), 'utf8'),
    fileBytes: run.bytes,
  };
}

const runs = [];
if (existsSync(historyDir)) {
  for (const day of readdirSync(historyDir)) {
    const dayDir = join(historyDir, day);
    if (!statSync(dayDir).isDirectory()) continue;
    for (const name of readdirSync(dayDir)) {
      const run = readRun(join(dayDir, name));
      if (run !== null) runs.push(liveRow(`${day}/${name}`, run));
    }
  }
}

console.log('');
console.log('■ 라이브 (실물 로봇 한 판)\n');

if (runs.length === 0) {
  console.log('보관된 판이 없다 — mission-history/ 가 비어 있다.');
} else {
  const real = runs.filter((r) => r.robotDriven);
  /** **완주한 판만 「한 판」이다.** 중간에 멈춘 판은 분모를 과소평가한다. */
  const complete = real.filter((r) => r.outcome === 'done' && r.done.split('/')[0] === r.done.split('/')[1]);
  const modern = runs.filter((r) => r.modern);
  console.log(`보관 ${runs.length}판 · 실물 ${real.length}판 · 완주 ${complete.length}판`);
  console.log(`그중 260920 뒤(액션 층이 열에 직접 있는) 판 ${modern.length}판 — 있으면 복원하지 않고 열을 그대로 센다\n`);

  // **기록의 robotDriven 과 어긋나는 판을 드러낸다.** 그 값은 「지금 붙어 있나」라서
  // 판이 끝난 뒤 로봇이 떨어지면 실물 판도 false 로 남는다.
  const misflagged = real.filter((r) => !r.robotDrivenFlag);
  if (misflagged.length > 0) {
    console.log(`⚠ mission.json 의 robotDriven 이 false 인데 실물로 판정한 판 ${misflagged.length}건 —`);
    for (const r of misflagged) {
      console.log(`    ${r.name}  (${r.modern ? '라이브 대역 액션 사건이 있다' : '로봇이 준 응답 줄이 있다'})`);
    }
    console.log('    robotDrives() 는 「지금 브로커에 붙어 있나」이고 기록은 판이 끝난 뒤에도 덮어써진다.\n');
  }

  const shown = complete.length > 0 ? complete : real;
  printRows(shown, 30, '판');

  if (complete.length > 0) {
    console.log('');
    const median = (xs) => {
      const s = [...xs].sort((a, b) => a - b);
      return s.length === 0 ? 0 : s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
    };
    const avg = (xs) => (xs.length === 0 ? 0 : xs.reduce((a, b) => a + b, 0) / xs.length);

    const totals = complete.map((r) => r.total);
    console.log(`완주 한 판의 사건 수 — 최소 ${Math.min(...totals)} · 중앙 ${median(totals)} · 최대 ${Math.max(...totals)} (평균 ${avg(totals).toFixed(1)})`);

    const allLines = complete.flatMap((r) => r.lines);
    console.log(`명령당 응답 줄 수 — 최소 ${Math.min(...allLines)} · 중앙 ${median(allLines)} · 최대 ${Math.max(...allLines)} (명령 ${allLines.length}건)`);

    const allScan = complete.flatMap((r) => r.scanLines);
    if (allScan.length > 0) {
      console.log(`scan_mission 한 건 — 최소 ${Math.min(...allScan)} · 중앙 ${median(allScan)} · 최대 ${Math.max(...allScan)} 줄 (${allScan.length}건)`);
    }

    const secs = complete.map((r) => r.seconds).filter((s) => s !== null);
    if (secs.length > 0) console.log(`한 판 소요 — 최소 ${Math.min(...secs).toFixed(0)}초 · 중앙 ${median(secs).toFixed(0)}초 · 최대 ${Math.max(...secs).toFixed(0)}초`);
    console.log(`기록 열 바이트 — 중앙 ${Math.round(median(complete.map((r) => r.columnBytes))).toLocaleString()} B (progress.json 전체는 중앙 ${Math.round(median(complete.map((r) => r.fileBytes))).toLocaleString()} B)`);

    const expired = complete.reduce((s, r) => s + r.expired, 0);
    console.log(`expired — 완주 판에서 ${expired}건. 보관 판은 줄로 안 남아 「일시정지·중단이 답을 못 받음」으로만 센다 (한계)`);

    console.log('');
    console.log(`열 밖(NO_NODE) — 명령 중앙 ${median(complete.map((r) => r.outsideCommands))}건 · 응답 중앙 ${median(complete.map((r) => r.outsideLines))}줄`);
    console.log('  이만큼이 **계측 범위 밖**이다 (논문 §6-2). 기록 열이 분모이므로 위 합계에 안 들어간다.');

    // 260920 뒤의 판에만 있는 중복. 정식 분모에는 안 넣되 크기는 보인다.
    const dup = complete.filter((r) => r.modern);
    if (dup.length > 0) {
      const d = dup.map((r) => r.legacyDuplicates);
      console.log('');
      console.log(`⚠ 옛 명령 줄 중복 — 260920 뒤 완주 판에서 판마다 ${Math.min(...d)}~${Math.max(...d)}건`);
      console.log('    260920 이 액션 층을 더하면서 사람 층의 옛 명령 줄을 안 지웠다. 같은 명령이 두 벌 있다.');
      console.log('    정식 분모는 액션 층 쪽이라 위 합계에는 안 넣었다. 지울지는 따로 정할 일이다.');
    }

    // ── 완주하지 못한 판도 같이 낸다 ─────────────────────────────────────────
    //
    // **디버깅 도구가 보는 판은 실패한 판이다.** 완주 판만 재면 정작 쓰이는 자리의 분모를
    // 모르고 넘어간다. 세는 규칙은 위와 같고, 완주 여부로 가르기만 한다.
    const broken = real.filter((r) => !complete.includes(r));
    if (broken.length > 0) {
      const bt = broken.map((r) => r.total);
      console.log('');
      console.log(`미완주 ${broken.length}판 — 합계 최소 ${Math.min(...bt)} · 중앙 ${median(bt)} · 최대 ${Math.max(...bt)}`);
      console.log(`  가장 큰 판 — ${broken.reduce((a, b) => (a.total >= b.total ? a : b)).name} (${Math.max(...bt)}건)`);
      console.log(`  실물 전체(${real.length}판)에서 관측된 최대는 ${Math.max(...real.map((r) => r.total))}건이다.`);
    }
  }
}
