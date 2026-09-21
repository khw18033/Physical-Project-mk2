// verify:no-answer (260920 신설 — 명령 기록 합류 §7)
//
// **「아직 기다리는 중」과 「영영 안 왔다」가 갈리는가.** 이 작업의 핵심이다.
//
// 일지는 일어난 일만 덧붙인다. 그런데 **안 온 응답은 일어나지 않은 일**이라 적을 수가
// 없다. 그래서 적는 것은 **기다림이 끝났다는 사실**(`expired`)이고, 기다린 것은 일어난
// 일이다.
//
// | 시각 t 에서 | 응답 | 기한 사건 | 뜻 |
// |---|---|---|---|
// | 명령 났음 | 0건 | 없음 | **아직 기다리는 중** |
// | 명령 났음 | 0건 | 있음 | **영영 안 왔다** |
//
// 기한 사건이 없으면 이 둘은 영원히 같아 보인다. 느린 것과 죽은 것은 원인이 완전히
// 다르므로, 디버깅에서 제일 값이 큰 구분이 이것이다. 로봇 침묵이 원인인 실패가 지금은
// 계측 범위 밖인데, 이 한 줄이 그것을 기록 안으로 들인다 (논문 §6-2).
//
// 보는 것 다섯.
//
//  1. **둘은 서로 배타다** — 같은 명령이 「아직」이면서 「영영」일 수 없다
//  2. **응답이 온 명령은 둘 다 아니다** ← 지시서가 못박은 대조군. **무응답으로 잡히면 실패**
//  3. **시각에 따라 뜻이 바뀐다** — 기한 전에는 「아직」, 기한 뒤에는 「영영」
//  4. **기한이 `status` 를 안 덮는다** — 덮으면 위 구분이 도로 사라진다
//  5. **화면이 둘을 다른 글자로 적는다** — 기록에서 갈려도 화면에서 같으면 사람은 못 본다
//
// 대조군 — 기한을 무시한 사본 · 응답을 무시한 사본이 반드시 잡혀야 한다.
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

// ── 시료 — 네 가지 모양을 손으로 짠다 ───────────────────────────────────────
//
// 대본에서만 뽑으면 「응답도 있고 기한도 있는」 모양이 없다. 그것이 없으면 ②의 대조군을
// 만들 수 없다 — 응답이 온 명령을 무응답으로 잡는 사본은 그 모양에서만 드러난다.
let seq = ACTION_SEQ_BASE;
const next = () => (seq += 1);
const cmd = (id, taskId, atSec) => mod.commandedEvent({
  seq: next(), atSec, commandId: id, taskId, action: 'turn', parameters: { deg: 90 }, issuedBy: 'mission',
});
const ans = (id, taskId, atSec, kind = 'status') => mod.answeredEvent({
  seq: next(), atSec, commandId: id, taskId, line: 'RUNNING', answerKind: kind,
});
const exp = (id, taskId, atSec) => mod.expiredEvent({
  seq: next(), atSec, commandId: id, taskId, waitedMs: 4000, reason: '4초 안에 안 왔다',
});

const sample = [
  // ① 아직 기다리는 중 — 명령만 났다
  cmd('C-WAIT', 'T-1', 10),
  // ② 영영 안 왔다 — 기한만 끝났다
  cmd('C-DEAD', 'T-2', 10), exp('C-DEAD', 'T-2', 14),
  // ③ 답이 왔다 — 둘 다 아니다
  cmd('C-OK', 'T-3', 10), ans('C-OK', 'T-3', 11), ans('C-OK', 'T-3', 12, 'result'),
  // ④ 답이 오고 **나서** 기한도 찍힌 모양 — 늦은 답이 온 판. 무응답이 아니다
  cmd('C-LATE', 'T-4', 10), ans('C-LATE', 'T-4', 11), exp('C-LATE', 'T-4', 14),
].sort((a, b) => (a.atSec === b.atSec ? a.seq - b.seq : a.atSec - b.atSec));

/**
 * **판정 본체.** 대조군이 이 함수를 그대로 다시 쓴다.
 *
 * `fold` · `waiting` · `never` 를 인자로 받는 이유가 대조군이다 — 셋 중 하나만 갈아 끼운
 * 사본을 같은 판정에 넣어 보고, 그때 안 잡히면 이 검사가 무의미하다고 말한다.
 */
export function judgeNoAnswer({ foldActions, stillWaiting, neverAnswered }) {
  const f = [];
  const at = (second) => Object.fromEntries(foldActions(second, sample).map((a) => [a.commandId, a]));

  const end = at(20);
  for (const [id, action] of Object.entries(end)) {
    // ① 서로 배타
    if (stillWaiting(action) && neverAnswered(action)) {
      f.push(`${id} 이 「아직」이면서 「영영」이다 — 두 뜻이 겹치면 구분이 없는 것과 같다`);
    }
  }

  // ② **응답이 온 명령이 무응답으로 잡히면 실패** (지시서가 못박은 대조군)
  for (const id of ['C-OK', 'C-LATE']) {
    const action = end[id];
    if (action === undefined) { f.push(`${id} 이 접힌 결과에 없다`); continue; }
    if (action.lines.length === 0) { f.push(`${id} 에 응답이 안 붙었다 — 시료가 틀렸다`); continue; }
    if (neverAnswered(action)) f.push(`${id} 은 응답이 ${action.lines.length}줄 왔는데 「영영 안 왔다」로 잡힌다`);
    if (stillWaiting(action)) f.push(`${id} 은 응답이 왔는데 「아직 기다리는 중」으로 잡힌다`);
  }

  // ①의 두 모양이 제대로 갈리는가
  if (!stillWaiting(end['C-WAIT'] ?? {})) f.push('명령만 나고 기한이 없는데 「아직 기다리는 중」이 아니다');
  if (neverAnswered(end['C-WAIT'] ?? {})) f.push('기한 사건이 없는데 「영영 안 왔다」로 잡힌다 — 느린 것을 죽은 것이라고 말한다');
  if (!neverAnswered(end['C-DEAD'] ?? {})) f.push('기한이 끝났는데 「영영 안 왔다」가 아니다 — 죽은 것을 느린 것이라고 말한다');
  if (stillWaiting(end['C-DEAD'] ?? {})) f.push('기한이 끝났는데 아직 「기다리는 중」이다');

  // ③ 시각에 따라 뜻이 바뀐다 — 기한 **전**에는 같은 명령이 「아직」이다
  const before = at(12)['C-DEAD'];
  if (before === undefined) f.push('T+12 에 C-DEAD 가 없다 — 명령은 T+10 에 났다');
  else {
    if (!stillWaiting(before)) f.push('기한이 찍히기 전인데 「아직 기다리는 중」이 아니다 — 되감기가 이 구분에 안 닿는다');
    if (neverAnswered(before)) f.push('기한이 찍히기 전인데 「영영 안 왔다」다 — 미래를 읽었다');
  }

  // ④ 기한이 `status` 를 안 덮는다
  const dead = end['C-DEAD'];
  if (dead !== undefined && dead.status !== 'issued') {
    f.push(`기한이 끝난 명령의 상태가 ${dead.status} 다 — 기다림이 끝난 것이지 그 명령이 실패했다고 안 것이 아니다`);
  }
  return f;
}

failures.push(...judgeNoAnswer(mod));
{
  const end = Object.fromEntries(mod.foldActions(20, sample).map((a) => [a.commandId, a]));
  const say = (id) => `${id}=${mod.neverAnswered(end[id]) ? '영영' : mod.stillWaiting(end[id]) ? '아직' : '답옴'}`;
  console.log(`✅ 끝에서 — ${['C-WAIT', 'C-DEAD', 'C-OK', 'C-LATE'].map(say).join(' · ')}`);
  const mid = Object.fromEntries(mod.foldActions(12, sample).map((a) => [a.commandId, a]));
  console.log(`✅ 기한 전(T+12) — C-DEAD=${mod.stillWaiting(mid['C-DEAD']) ? '아직' : '???'} · 같은 명령이 시각에 따라 뜻이 바뀐다`);
}

// ── 5. 화면이 둘을 다른 글자로 적는다 ──────────────────────────────────────
//
// 기록에서 갈려도 화면에서 같은 글자면 사람은 끝내 못 본다. 그 구분이 사람 눈에 닿는
// 자리가 명령 표 하나뿐이라 여기서 같이 본다.
{
  const modal = readSource(root, 'src', 'views', 'ActionModal.tsx');
  const ko = readSource(root, 'src', 'i18n', 'ko.ts');
  const en = readSource(root, 'src', 'i18n', 'en.ts');
  if (!/neverAnswered\(/.test(modal)) failures.push('명령 표가 「영영 안 왔다」를 안 묻는다');
  if (!/stillWaiting\(/.test(modal)) failures.push('명령 표가 「아직 기다리는 중」을 안 묻는다');
  for (const key of ['act.noAnswer', 'act.waiting', 'act.waitedFor']) {
    if (!modal.includes(`t('${key}')`) && !modal.includes(`t('${key}',`)) failures.push(`명령 표가 ${key} 를 안 그린다`);
    // **문구가 아니라 키를 보되, 사전에 그 키가 실제로 있는지도 본다** (영문화 2단계 §5).
    for (const [lang, dict] of [['ko', ko], ['en', en]]) {
      if (!dict.includes(`'${key}':`)) failures.push(`${lang} 사전에 ${key} 가 없다 — 화면이 키 이름을 그대로 그린다`);
    }
  }
  // 두 딱지가 **같은 글자**면 갈라 놓은 뜻이 없다.
  const valueOf = (dict, key) => dict.match(new RegExp(`'${key.replace('.', '\\.')}':\\s*'([^']*)'`))?.[1] ?? null;
  for (const [lang, dict] of [['ko', ko], ['en', en]]) {
    const a = valueOf(dict, 'act.noAnswer');
    const b = valueOf(dict, 'act.waiting');
    if (a === null || b === null) failures.push(`${lang} 사전에서 두 딱지 문구를 못 읽었다`);
    else if (a === b) failures.push(`${lang} 에서 「${a}」와 「${b}」가 같은 글자다 — 화면에서 둘이 구분되지 않는다`);
  }
  console.log('✅ 화면 — 「응답 없음」과 「대기 중」이 다른 글자로, 두 사전 모두에 있다');
}

// ── 대조군 ──────────────────────────────────────────────────────────────────
{
  const scratch = makeScratch(join(root, 'src', 'data'), '.verify-noanswer-');
  try {
    // **LF 로 정규화한 원본에서 만든다** (lib/source.mjs) — 자리표에 `\n` 이 든
    // 사본은 CRLF 작업본에서 아무것도 못 찾고 원본 그대로 돌아온다.
    const source = readSource(actionPath).replaceAll("from '../model/types.ts'", "from '../../model/types.ts'");
    const mutants = [
      ['기한을 안 보는 사본 (느린 것을 죽은 것이라 한다)',
        source.replace('return action.lines.length === 0 && action.expired !== null;', 'return action.lines.length === 0;')],
      ['응답을 안 보는 사본 (답이 왔는데 무응답이라 한다)',
        source.replace('return action.lines.length === 0 && action.expired !== null;', 'return action.expired !== null;')],
      ['기한을 status 에 섞은 사본',
        source.replace("      row.expired = {", "      row.status = 'failed';\n      row.expired = {")],
      ['기한 사건을 통째로 버리는 사본',
        source.replace('} else if (event.kind === ACTION_KINDS.expired) {', '} else if (false) {')],
      ['미래의 기한까지 읽는 사본 (되감기를 무시한다)',
        source.replace('    if (event.atSec > second) break;\n    if (!ACTION_KIND_SET.has(event.kind)) continue;', '    if (!ACTION_KIND_SET.has(event.kind)) continue;')],
    ];
    for (const [label, code] of mutants) {
      if (code === source) { failures.push(`대조군을 만들지 못했다 — ${label} (원본이 바뀌었나?)`); continue; }
      const path = scratch.file(`actionTrace-${controls.length}.ts`);
      writeFileSync(path, code, 'utf8');
      let detected;
      try {
        detected = judgeNoAnswer(await import(pathToFileURL(path).href)).length > 0;
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
  console.error(`❌ verify:no-answer\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${controls.length}건 — ${controls.join(' · ')}`);
