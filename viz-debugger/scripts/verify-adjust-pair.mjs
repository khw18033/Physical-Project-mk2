// verify:adjust-pair (260920 신설 — 명령 기록 합류 §7)
//
// **사람이 바꾼 값이 전후 짝으로 남는가.**
//
// 후만 남기면 기록은 「속도가 0.40 이다」라고 말한다. 그것은 지금 값이지 **일어난 일**이
// 아니다. 일어난 일은 「0.35 였던 것을 사람이 0.40 으로 바꿨다」이고, 디버깅에서 알고 싶은
// 것도 그쪽이다 — 무엇이 달라졌길래 결과가 달라졌는가.
//
// 이 검사는 논문 §4-3 의 실증이기도 하다. 「AI·백엔드·사람 셋 중 누가 만든 값인지 적는다」고
// 주장하는데 **대본 6편의 실패 사건 4건이 전부 `producedBy: backend` 이고 사람이 만든 값이
// 기록에 0건**이었다. `adjusted` 가 그 0을 깬다.
//
// 보는 것 넷.
//
//  1. **사건에 before 와 after 가 둘 다 있다** — 한쪽만 있으면 짝이 아니다
//  2. **사람이 만든 것으로 적힌다** — `producedBy: 'human'`
//  3. **접기가 둘 다 내놓는다** — 명령에 붙은 조정과, 아직 명령이 없는 계획값 조정 둘 다
//  4. **화면이 둘 다 그린다** — 기록에 남아도 화면이 후만 그리면 사람은 못 본다
//
// 대조군 — **후만 남긴 사본이 반드시 잡혀야 한다.**
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeScratch } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const failures = [];
const controls = [];

const actionPath = join(root, 'src', 'data', 'actionTrace.ts');
const mod = await load('src', 'data', 'actionTrace.ts');
const { ACTION_SEQ_BASE } = await load('src', 'data', 'trace.ts');

/**
 * **판정 본체.** 대조군이 이 함수를 그대로 다시 쓴다 — 판정이 두 벌이면 사본은 통과하고
 * 원본만 엄해지는 일이 생긴다.
 */
export function judgeAdjust(m) {
  const f = [];
  let seq = ACTION_SEQ_BASE;
  const next = () => (seq += 1);

  // 시료 둘 — ① 명령에 붙은 조정 ② 아직 명령이 없는 계획값 조정
  const onCommand = m.adjustedEvent({
    seq: next(), atSec: 12, commandId: 'C-1', taskId: 'T-B2',
    field: 'distance_m', before: 4.2, after: 1,
  });
  const onPlan = m.adjustedEvent({
    seq: next(), atSec: 14, commandId: 'T-B2', taskId: 'T-B2',
    field: 'speed', before: '0.35', after: '0.40',
  });

  // ① 전후가 둘 다 있다
  for (const [label, event] of [['명령에 붙은 조정', onCommand], ['계획값 조정', onPlan]]) {
    const payload = event.payload ?? {};
    if (!('before' in payload)) f.push(`${label} 에 before 가 없다 — 무엇이 바뀌었는지 기록이 답할 수 없다`);
    if (!('after' in payload)) f.push(`${label} 에 after 가 없다`);
    if (payload.before === payload.after) f.push(`${label} 의 전후가 같다 — 바뀐 것이 아니다`);
    if (typeof payload.field !== 'string' || payload.field === '') f.push(`${label} 에 어느 칸인지가 없다`);
    // ② 사람이 만든 값
    if (event.producedBy !== 'human') f.push(`${label} 의 produced_by 가 ${event.producedBy} 다 — 사람이 바꾼 값이다`);
  }

  // ③-가. 명령에 붙은 조정은 그 명령 행에 붙는다
  const trace = [
    m.commandedEvent({ seq: next(), atSec: 10, commandId: 'C-1', taskId: 'T-B2', action: 'move_forward', parameters: { distance_m: 1 }, issuedBy: 'mission' }),
    onCommand, onPlan,
  ].sort((a, b) => (a.atSec === b.atSec ? a.seq - b.seq : a.atSec - b.atSec));

  const row = m.foldActions(20, trace).find((a) => a.commandId === 'C-1');
  if (row === undefined) f.push('명령 행이 접힌 결과에 없다');
  else if (row.adjustments.length !== 1) f.push(`명령에 붙은 조정이 ${row.adjustments.length}건이다 — 1건이어야 한다`);
  else {
    const pair = row.adjustments[0];
    if (pair.before === undefined || pair.after === undefined) f.push('접은 결과에 전후 짝이 다 안 남았다');
    if (pair.before === pair.after) f.push('접은 결과의 전후가 같다');
  }

  // ③-나. 아직 명령이 없는 계획값 조정은 태스크 쪽으로 나온다
  const plan = m.planAdjustments(20, trace, 'T-B2');
  if (plan.length !== 1) f.push(`계획값 조정이 ${plan.length}건이다 — 1건이어야 한다`);
  else if (plan[0].before === undefined || plan[0].after === undefined) f.push('계획값 조정에 전후 짝이 다 안 남았다');

  // ③-다. **되감기가 여기에도 닿는다** — 바꾸기 전 시각에는 안 보인다
  if (m.planAdjustments(13, trace, 'T-B2').length !== 0) f.push('T+13 에 T+14 의 조정이 보인다 — 미래를 읽었다');
  const early = m.foldActions(11, trace).find((a) => a.commandId === 'C-1');
  if ((early?.adjustments.length ?? 0) !== 0) f.push('T+11 에 T+12 의 조정이 보인다 — 되감기가 조정에 안 닿는다');

  return f;
}

failures.push(...judgeAdjust(mod));
console.log('✅ 조정은 전후 짝으로 남고 produced_by 가 human 이다 — 명령에 붙은 것과 계획값 둘 다');
console.log('✅ 되감기 — 바꾸기 전 시각에는 그 조정이 안 보인다');

// ── 4. 화면이 전후를 둘 다 그린다 ──────────────────────────────────────────
{
  const modal = readSource(root, 'src', 'views', 'ActionModal.tsx');
  const ko = readSource(root, 'src', 'i18n', 'ko.ts');
  const en = readSource(root, 'src', 'i18n', 'en.ts');
  if (!/recordAdjusted\(/.test(modal)) failures.push('화면이 값 변경을 기록하지 않는다 — 사람이 만든 값이 기록에 0건으로 남는다');
  if (!/planAdjustments\(/.test(modal)) failures.push('화면이 계획값 조정을 안 읽는다');
  if (!/adjustments/.test(modal)) failures.push('화면이 명령에 붙은 조정을 안 읽는다');
  // **문구가 아니라 키를 보되, 두 사전이 전후를 **둘 다** 그리는지까지 본다.
  const value = (dict) => dict.match(/'act\.adjustPair':\s*'([^']*)'/)?.[1] ?? null;
  for (const [lang, dict] of [['ko', ko], ['en', en]]) {
    const line = value(dict);
    if (line === null) { failures.push(`${lang} 사전에 act.adjustPair 가 없다`); continue; }
    if (!line.includes('{before}')) failures.push(`${lang} 의 act.adjustPair 에 {before} 가 없다 — 후만 그리면 무엇이 바뀌었는지 모른다`);
    if (!line.includes('{after}')) failures.push(`${lang} 의 act.adjustPair 에 {after} 가 없다`);
  }
  console.log('✅ 화면 — 값 변경을 기록하고, 두 사전 모두 전후를 같이 그린다');
}

// ── 대조군 ──────────────────────────────────────────────────────────────────
{
  const scratch = makeScratch(join(root, 'src', 'data'), '.verify-adjust-');
  try {
    // **LF 로 정규화한 원본에서 만든다** (lib/source.mjs) — 자리표에 `\n` 이 든
    // 사본은 CRLF 작업본에서 아무것도 못 찾고 원본 그대로 돌아온다.
    const source = readSource(actionPath).replaceAll("from '../model/types.ts'", "from '../../model/types.ts'");
    const mutants = [
      ['후만 남긴 사본',
        source.replace('payload: { taskId: input.taskId, field: input.field, before: input.before, after: input.after },',
                       'payload: { taskId: input.taskId, field: input.field, after: input.after },')],
      ['조정을 백엔드가 한 것으로 적은 사본',
        source.replace("    kind: ACTION_KINDS.adjusted,\n    producedBy: 'human',", "    kind: ACTION_KINDS.adjusted,\n    producedBy: 'backend',")],
      ['조정을 접기에서 버리는 사본',
        source.replace('} else if (event.kind === ACTION_KINDS.adjusted) {', '} else if (false) {')],
      ['계획값 조정을 안 내놓는 사본',
        source.replace("if (event.kind !== ACTION_KINDS.adjusted || event.nodeId !== taskId) continue;", 'continue;')],
      ['미래의 조정까지 읽는 사본',
        source.replace('    if (event.atSec > second) break;\n    if (event.kind !== ACTION_KINDS.adjusted', '    if (event.kind !== ACTION_KINDS.adjusted')],
    ];
    for (const [label, code] of mutants) {
      if (code === source) { failures.push(`대조군을 만들지 못했다 — ${label} (원본이 바뀌었나?)`); continue; }
      const path = scratch.file(`actionTrace-${controls.length}.ts`);
      writeFileSync(path, code, 'utf8');
      let detected;
      try {
        detected = judgeAdjust(await import(pathToFileURL(path).href)).length > 0;
      } catch {
        detected = true;
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
  console.error(`❌ verify:adjust-pair\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
