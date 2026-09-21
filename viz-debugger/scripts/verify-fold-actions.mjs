// verify:fold-actions (260920 신설 — 명령 기록 합류 §7)
//
// **접기가 세 층을 돌려주는가. 그리고 접기가 여전히 순수 함수인가.**
//
// `verify:scenario-mode` 와 **같은 방식**으로 본다 — 접기를 Node 에서 직접 부른다. 소스
// 문자열 검사로 내려앉으면 「층이 있다고 적혀 있다」만 보고 「층이 실제로 채워진다」는
// 못 본다.
//
// 보는 것 넷.
//
//  1. **순수하다** — `fold.ts` · `actionTrace.ts` 가 저장소·React·작업대를 안 끌어온다.
//     `robotSession` 을 import 하는 순간 이 검사도 `verify:scenario-mode` 도 죽는다
//  2. **세 층을 돌려준다** — `tasks` · `milestones` · `actions`
//  3. **되감기가 액션 층에 닿는다** — 시각이 다르면 접힌 명령도 응답 수도 달라진다
//  4. **액션 사건이 태스크 층을 안 흔든다** — 값 하나 고친 것이 태스크를 rerunning 으로
//     만들면 안 된다
//
// 대조군 — **액션 층이 빈 사본이 반드시 잡혀야 한다.**
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeScratch } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const failures = [];
const controls = [];

const foldPath = join(root, 'src', 'data', 'fold.ts');
const actionPath = join(root, 'src', 'data', 'actionTrace.ts');
const { foldStatuses } = await load('src', 'data', 'fold.ts');
const { ACTION_SEQ_BASE } = await load('src', 'data', 'trace.ts');
const { actionItemEvents } = await load('src', 'data', 'actionTrace.ts');

// ── 1. 접기는 순수하다 ──────────────────────────────────────────────────────
//
// 이 검사가 여기까지 왔다는 것 자체가 절반의 증명이다 — 두 파일이 React 나 저장소를
// 끌어왔으면 위 `load()` 에서 죽었다. 나머지 절반은 소스로 못박는다: 지금은 안 끌어와도
// 내일 누가 한 줄 적으면 끌어온다.
{
  const banned = ['robotSession', 'react', 'scenarios/library', "with { type: 'json' }"];
  for (const [label, path] of [['fold.ts', foldPath], ['actionTrace.ts', actionPath]]) {
    const source = readSource(path);
    // `import type { ... }` 은 실행 시 아무것도 안 끌어온다 — 그것만 통과시킨다.
    const runtimeImports = source
      .split('\n')
      .filter((line) => /^import\s/.test(line) && !/^import type\s/.test(line))
      .join('\n');
    for (const word of banned) {
      if (runtimeImports.includes(word)) {
        failures.push(`${label} 이 실행 시 ${word} 을(를) 끌어온다 — Node 가 접기를 직접 못 돌린다`);
      }
    }
  }
  console.log('✅ 접기 두 파일은 실행 시 저장소·React·대본 파일을 안 끌어온다 — Node 가 그대로 연다');
}

// ── 시료 — 시연 편의 액션 아이템을 편 것 ────────────────────────────────────
const script = JSON.parse(readFileSync(join(root, 'scenarios', 'MSN-260909-01.json'), 'utf8'));
const view = {
  missionId: script.missionId, label: script.title, world: 'registry',
  utteranceText: script.utterance.text, durationSec: script.durationSec,
  milestones: script.milestones, tasks: script.tasks, events: script.events,
  cast: script.cast, hardware: null, params: script.params ?? {}, map: null, refEdges: [],
};
/** 대본 사건 + 액션 사건을 `(atSec, seq)` 오름차순으로 — `TraceStore` 가 보장하는 순서다. */
const column = [...script.events, ...actionItemEvents(script.tasks, ACTION_SEQ_BASE)]
  .sort((a, b) => (a.atSec === b.atSec ? a.seq - b.seq : a.atSec - b.atSec));

/**
 * **판정 본체.** 대조군이 이 함수를 그대로 다시 쓴다 — 판정이 두 벌이면 사본은 통과하고
 * 원본만 엄해지는 일이 생긴다.
 */
export function judgeFold(fold) {
  const f = [];
  const end = fold(view.durationSec, view, column);

  // ── 2. 세 층 ──
  for (const layer of ['tasks', 'milestones', 'actions']) {
    if (end[layer] === undefined || end[layer] === null) f.push(`접기가 ${layer} 층을 안 돌려준다`);
  }
  const rows = Object.values(end.actions ?? {});
  if (rows.length === 0) f.push('액션 층이 비어 있다 — 대본의 액션 아이템이 기록으로 안 흘렀다');
  for (const [commandId, row] of Object.entries(end.actions ?? {})) {
    if (typeof row.taskId !== 'string' || row.taskId === '') f.push(`${commandId} 에 태스크가 없다 — 어느 노드에도 못 붙는다`);
    if (typeof row.answered !== 'number') f.push(`${commandId} 의 응답 줄 수가 숫자가 아니다`);
    if (typeof row.expired !== 'boolean') f.push(`${commandId} 의 기한 칸이 참·거짓이 아니다`);
    if (!['issued', 'running', 'done', 'failed'].includes(row.status)) f.push(`${commandId} 의 상태가 액션 어휘 밖이다 — ${row.status}`);
  }

  // **`expired` 가 `status` 에 안 섞였다.** 섞이면 「아직」과 「영영」이 같아진다 (§2).
  const expiredRows = Object.entries(end.actions ?? {}).filter(([, row]) => row.expired);
  if (expiredRows.length === 0) {
    f.push('기한이 끝난 명령이 한 건도 없다 — 시연 편에 일부러 심어 둔 한 건이 안 흐른다');
  }
  for (const [commandId, row] of expiredRows) {
    if (row.status === 'failed') f.push(`${commandId} 의 기한이 status 에 섞였다(failed) — 기다림이 끝난 것이지 실패한 것이 아니다`);
  }

  // ── 3. 되감기 ──
  const early = fold(31, view, column);
  if (Object.keys(early.actions ?? {}).length >= Object.keys(end.actions ?? {}).length) {
    f.push('T+31 과 끝에서 접힌 명령 수가 같다 — 되감기가 액션 층에 안 닿는다');
  }
  const scan = 'AI-0909-A3-1';
  const mid = fold(12, view, column).actions?.[scan];
  const late = end.actions?.[scan];
  if (mid === undefined || late === undefined) {
    f.push(`${scan} 이 접힌 결과에 없다 — 시연 편의 스캔 명령이 안 흐른다`);
  } else if (mid.answered >= late.answered) {
    f.push(`${scan} 의 응답 줄 수가 T+12(${mid.answered})와 끝(${late.answered})에서 안 는다 — 응답이 재생 머리를 안 따라간다`);
  }

  // ── 4. 액션 사건이 태스크 층을 안 흔든다 ──
  //
  // 값 하나 고친 것(`adjusted`)이 태스크를 `rerunning` 으로 만들면 안 된다 — 아무것도
  // 다시 돌지 않았다. `nodeId` 가 태스크인 `adjusted` 를 일부러 넣어 본다.
  const withAdjust = [...column, {
    seq: ACTION_SEQ_BASE + 9000, atSec: 20, nodeId: 'T-B2', status: 'rerunning',
    kind: 'adjusted', producedBy: 'human',
    payload: { taskId: 'T-B2', field: 'speed', before: '0.35', after: '0.40' },
  }].sort((a, b) => (a.atSec === b.atSec ? a.seq - b.seq : a.atSec - b.atSec));
  // **T-B2 가 아직 안 시작한 시각에 본다** (started 는 T+30). 시작한 뒤에 보면 그 사건이
  // 조정을 덮어써서, 태스크를 흔드는 사본도 같은 값을 내놓는다 — 대조군이 무의미해진다.
  const before = fold(25, view, column).tasks['T-B2']?.status;
  const after = fold(25, view, withAdjust).tasks['T-B2']?.status;
  if (before !== after) f.push(`값을 바꾸자 태스크 상태가 ${before} → ${after} 로 흔들렸다 — 아무것도 다시 돌지 않았다`);

  return f;
}

failures.push(...judgeFold(foldStatuses));
{
  const end = foldStatuses(view.durationSec, view, column);
  console.log(`✅ 세 층 — 태스크 ${Object.keys(end.tasks).length}개 · 마일스톤 ${Object.keys(end.milestones).length}개 · 액션 ${Object.keys(end.actions).length}건`);
  const expired = Object.entries(end.actions).filter(([, r]) => r.expired);
  console.log(`✅ 기한이 끝난 명령 ${expired.length}건 — 상태는 [${expired.map(([, r]) => r.status).join(', ')}] 로 남는다 (failed 로 안 덮는다)`);
  console.log(`✅ 되감기 — T+12 에 ${Object.keys(foldStatuses(12, view, column).actions).length}건 · T+31 에 ${Object.keys(foldStatuses(31, view, column).actions).length}건 · 끝에 ${Object.keys(end.actions).length}건`);
}

// ── 대조군 ──────────────────────────────────────────────────────────────────
{
  const scratch = makeScratch(join(root, 'src', 'data'), '.verify-foldactions-');
  try {
    // 사본은 한 칸 깊은 곳에 산다 — 이웃 모듈 경로를 그만큼 올려 준다.
    // **LF 로 정규화한 원본에서 만든다** (lib/source.mjs) — 자리표에 `\n` 이 든
    // 사본은 CRLF 작업본에서 아무것도 못 찾고 원본 그대로 돌아온다.
    const source = readSource(foldPath)
      .replaceAll("from './actionTrace.ts'", "from '../actionTrace.ts'")
      .replaceAll("from './scenario.ts'", "from '../scenario.ts'");
    const mutants = [
      ['액션 층이 빈 사본', source.replace('for (const action of foldActions(second, trace)) {', 'for (const action of []) {')],
      ['기한을 status 에 섞은 사본', source.replace("expired: action.expired !== null,", "expired: action.expired !== null,\n      ...(action.expired !== null ? { status: 'failed' } : {}),")],
      ['되감기를 무시하는 사본(늘 마지막 상태)', source.replace('const actions: FoldedStatuses[\'actions\'] = {};', 'const actions: FoldedStatuses[\'actions\'] = {};\n  second = Number.POSITIVE_INFINITY;')],
      ['액션 사건을 태스크로도 접는 사본', source.replace('    if (isActionEvent(event)) continue;', '')],
    ];
    for (const [label, code] of mutants) {
      if (code === source) { failures.push(`대조군을 만들지 못했다 — ${label} (원본이 바뀌었나?)`); continue; }
      const path = scratch.file(`fold-${controls.length}.ts`);
      writeFileSync(path, code, 'utf8');
      let detected;
      try {
        const mutant = await import(pathToFileURL(path).href);
        detected = judgeFold(mutant.foldStatuses).length > 0;
      } catch {
        detected = true;                 // 아예 안 열리는 것도 잡힌 것이다
      }
      if (!detected) failures.push(`대조군 실패: ${label}이 통과했다 — 이 검사는 무의미하다`);
      else controls.push(label);
    }
  } finally {
    // 일부 개발 환경은 파일 삭제가 막혀 EPERM 이 난다 — 검사는 이미 끝났으므로 죽지 않는다.
    scratch.cleanup();
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:fold-actions\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
