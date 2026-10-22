// verify:stop-recorded (261022 신설 — 사람 층·액션 층 경계 §1 · §6)
//
// **긴급정지가 명령으로 기록 열에 들어가는가. 그리고 동작 순서는 그대로인가.**
//
// 전에는 일시정지만 `recordCommanded` 로 적혔다. 사람이 누른 정지는 `robot.stopped` 에만
// 남고 되감아도 명령 표에 안 떴다 — 정지는 사람 행동의 대표인데 §4-5 의 「사람이 만든 값을
// 적는다」가 바로 그 자리에서 거짓이었다.
//
// 그런데 정지는 **한 줄도 바뀌면 안 되는** 경로다(260910 · 9/20 지시서). 그래서 넣은 것이
// 「기록」뿐이고 **순서가 그대로**인지를 같이 본다.
//
//   1. 발행 (`client.send(abort)`)  — 그때 화면은 아직 안 잠겼고 기록도 없다
//   2. 잠금 (`lockStopped`)          — 그때도 기록은 아직 없다 ← 기록이 잠금을 앞지르면 실패
//   3. 기록 (`recordCommanded`)      — 이미 나갔고 이미 잠근 뒤에 적는다
//
// 보는 것.
//  ① 정지가 `commanded` 로 들어간다 — 같은 `command_id` · `abort` · 주체 `human` · 돌던 태스크
//  ② 로봇의 답도 그 행에 붙는다 — 일시정지와 같은 모양
//  ③ 돌던 태스크가 없으면 `NO_NODE` — 기록에는 남고 노드에는 안 붙는다
//  ④ 못 보낸 정지는 명령이 아니다 — 안 적는다. 그래도 잠근다
//  ⑤ 위 1→2→3 순서를 **실행 중에** 본다(발행 순간 · 잠금 순간의 기록 열을 들여다본다)
//  ⑥ 소스의 뼈대 순서 — 발행 → 알림 → 잠금 → 기록 → 반환. 잠금은 조건 안에 없다
//
// 대조군 — **기록을 지운 사본**과 **기록을 잠금 앞으로 옮긴 사본**이 둘 다 잡혀야 한다.
// 사본은 `src/physical/` 밑 임시 폴더에 둬 상대 import 가 같은 모듈 인스턴스를 끌어온다
// (`verify:action-trace` 와 같은 방법). LF 로 정규화한 원본에서 만든다(`readSource`).
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { makeScratch } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const session = await load('src', 'physical', 'robotSession.ts');
const scenario = await load('src', 'data', 'scenario.ts');
const { ACTION_KINDS, NO_NODE, attachedToNode } = await load('src', 'data', 'actionTrace.ts');
const { STOP_ACTION, STOP_REASON } = await load('src', 'physical', 'presets.ts');
const original = await load('src', 'physical', 'robotCommands.ts');

const failures = [];
const controls = [];

const MISSION = 'MSN-260909-01';
const column = () => scenario.traceFor(scenario.currentMission());
const stopRows = (commandId) => column().filter((e) => e.nodeId === commandId);

/**
 * 정지 명령을 받는 가짜 로봇. **보낸 그 순간**의 화면 잠금과 기록 열을 적어 둔다 — 순서를
 * 실행 중에 보는 첫 눈이다.
 */
function probeRobot(prefix) {
  const listeners = new Set();
  const sent = [];
  return {
    sent,
    getStatus: () => ({ state: 'open' }),
    send(action, parameters) {
      const commandId = `${prefix}-${String(sent.length + 1).padStart(4, '0')}`;
      sent.push({
        action, parameters: { ...(parameters ?? {}) }, commandId,
        lockedAtSend: session.robotSession().stopped !== null,
        recordedAtSend: stopRows(commandId).length > 0,
      });
      return { sent: true, commandId };
    },
    onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
    emit(message) { for (const cb of [...listeners]) cb(message); },
  };
}

function armed() {
  session.resetRobotSession();
  session.setConnection({ state: 'open' });
  scenario.previewMission(MISSION);
  session.markApproved();
}

/**
 * **판정 본체** — 정지 한 번을 실제로 누르고 본다. 원본과 사본이 **같은 이 함수**를 돈다.
 *
 * @param mod  `emergencyStop` 을 내는 모듈 (원본 또는 사본)
 */
async function judgeStop(mod, prefix) {
  const f = [];

  // ── ① · ② · ⑤ — 돌던 태스크가 있을 때 ──
  armed();
  // 스캔이 돌고 있다 — `runningTaskId()` 가 T-A3 을 돌려준다.
  session.recordCommand({
    taskId: 'T-A3', commandId: `${prefix}-scan`, action: 'scan_mission', requestId: null, state: 'running',
    code: null, message: null, result: {}, issuedAtIso: new Date().toISOString(), parameters: {}, log: [],
  });
  const robot = probeRobot(prefix);
  let recordedAtLock = null;
  const off = session.subscribeRobot(() => {
    if (recordedAtLock !== null || session.robotSession().stopped === null) return;
    const id = robot.sent.at(-1)?.commandId ?? '';
    recordedAtLock = stopRows(id).length > 0;
  });
  await mod.emergencyStop(robot);
  off();

  const sent = robot.sent.at(-1);
  if (sent === undefined || sent.action !== STOP_ACTION) { f.push('정지가 안 나갔다 — 검사가 헛돈다'); return f; }
  if (session.robotSession().stopped === null) f.push('정지를 눌렀는데 화면이 안 잠겼다');

  const rows = stopRows(sent.commandId);
  const commanded = rows.filter((e) => e.kind === ACTION_KINDS.commanded);
  if (commanded.length !== 1) f.push(`정지가 기록 열에 ${commanded.length}줄 — 명령 한 줄로 들어가야 한다 (되감으면 명령 표에 떠야 한다)`);
  const c = commanded[0];
  if (c !== undefined) {
    if (c.payload?.action !== STOP_ACTION) f.push(`기록된 정지의 action 이 ${c.payload?.action} 다`);
    if (c.producedBy !== 'human') f.push(`정지의 주체가 ${c.producedBy} 다 — 사람이 누른 것이다`);
    if (c.payload?.taskId !== 'T-A3') f.push(`정지가 ${c.payload?.taskId} 에 붙었다 — 돌던 태스크(T-A3)여야 한다 (일시정지와 같은 모양)`);
    if (JSON.stringify(c.payload?.parameters) !== JSON.stringify({ reason: STOP_REASON.human })) {
      f.push(`기록된 정지의 값이 ${JSON.stringify(c.payload?.parameters)} — 실려 나간 값(reason 하나)이어야 한다`);
    }
  }

  // ⑤ 순서 — 발행 순간에는 안 잠겼고 기록도 없다. 잠그는 순간에도 기록은 아직 없다.
  if (sent.lockedAtSend) f.push('발행하는 순간 이미 잠겨 있었다 — 발행 → 잠금 순서가 바뀌었다');
  if (sent.recordedAtSend) f.push('발행하기 전에 기록이 있었다 — 안 나간 명령을 적었다');
  if (recordedAtLock === null) f.push('잠그는 순간을 못 봤다 — 검사가 헛돈다');
  else if (recordedAtLock) f.push('잠그기 전에 기록이 먼저 들어갔다 — 기록이 잠금을 앞질렀다 (기록은 잠근 뒤에 적는다)');

  // ② 답이 그 행에 붙는다.
  robot.emit({ kind: 'acceptance', commandId: sent.commandId, accepted: true, code: null, message: null });
  await sleep(20);
  if (!stopRows(sent.commandId).some((e) => e.kind === ACTION_KINDS.answered && e.producedBy === 'robot')) {
    f.push('로봇이 정지에 답했는데 기록 열에 안 붙었다 — 일시정지는 붙는다');
  }

  // ── ③ 돌던 태스크가 없을 때 ──
  armed();
  const idle = probeRobot(prefix + 'i');
  await mod.emergencyStop(idle);
  const idleRow = stopRows(idle.sent.at(-1)?.commandId ?? '').find((e) => e.kind === ACTION_KINDS.commanded);
  if (idleRow === undefined) f.push('돌던 태스크가 없을 때 누른 정지가 안 적혔다 — 사람이 누른 사실은 태스크와 무관하다');
  else if (idleRow.payload?.taskId !== NO_NODE || attachedToNode({ taskId: idleRow.payload.taskId })) {
    f.push(`돌던 태스크 없이 누른 정지가 ${idleRow.payload?.taskId} 에 붙었다 — NO_NODE 여야 한다`);
  }

  // ── ④ 못 보낸 정지 ──
  armed();
  const before = column().filter((e) => e.kind === ACTION_KINDS.commanded).length;
  await mod.emergencyStop({ getStatus: () => ({ state: 'closed' }), send: () => ({ sent: false, commandId: '', reason: '끊김' }), onMessage: () => () => {} });
  if (session.robotSession().stopped === null) f.push('못 보냈다고 안 잠갔다 — 뼈대가 깨졌다');
  if (column().filter((e) => e.kind === ACTION_KINDS.commanded).length !== before) f.push('못 보낸 정지를 명령으로 적었다 — 나가지 않은 명령이다');
  armed();
  await mod.emergencyStop({ getStatus: () => ({ state: 'open' }), send() { throw new Error('소켓이 죽었다'); } });
  if (session.robotSession().stopped === null) f.push('발행이 던졌는데 안 잠갔다 — 뼈대가 깨졌다');
  armed();
  await mod.emergencyStop(null);
  if (session.robotSession().stopped === null) f.push('클라이언트가 없는데 안 잠갔다 — 뼈대가 깨졌다');
  return f;
}

// ── ⑥ 소스의 뼈대 순서 ───────────────────────────────────────────────────────
//
// 실행으로 본 것을 소스로 한 번 더 본다. 실행은 이 판의 경로만 보고, 소스는 모든 분기를 본다.
function bodyOf(source) {
  const start = source.indexOf('export async function emergencyStop(');
  const end = source.indexOf('\nfunction recordStop(', start);
  return start < 0 || end < 0 ? null : source.slice(start, end);
}

function judgeSkeleton(source) {
  const body = bodyOf(source);
  if (body === null) return ['emergencyStop 본문을 못 찾았다 — 검사가 헛돈다'];
  const f = [];
  const anchors = [
    ['발행', 'client.send(STOP_ACTION, { reason: STOP_REASON.human })'],
    ['예외를 받아도 이어 간다', '} catch (error) {'],
    ['못 보낸 정지를 알린다', "if (!published) noteIssue('stop'"],
    ['잠금 — 발행 결과를 넘기기만 한다', '\n  const stopped = lockStopped(published, failure);'],
    ['기록 — 잠근 뒤', 'recordStop(client, commandId,'],
    ['반환', '\n  return stopped;'],
  ];
  let at = -1;
  for (const [what, mark] of anchors) {
    const next = body.indexOf(mark);
    if (next < 0) { f.push(`emergencyStop 에 「${what}」(${mark.trim()}) 이 없다`); continue; }
    if (next < at) f.push(`emergencyStop 의 「${what}」이 제자리보다 앞에 있다 — 순서가 바뀌었다`);
    at = Math.max(at, next);
  }
  // 기록은 이 자리 하나뿐이다 — 잠금 앞에 또 적으면 순서 검사가 한쪽만 본다.
  const recordAt = body.indexOf('recordStop(');
  if (recordAt >= 0 && recordAt < body.indexOf('lockStopped(')) f.push('emergencyStop 이 잠그기 전에 기록한다');
  if (/recordCommanded\(/.test(body)) f.push('emergencyStop 본문이 직접 기록한다 — 기록은 잠근 뒤 recordStop 하나로');
  return f;
}

const source = readSource(root, 'src', 'physical', 'robotCommands.ts');
failures.push(...judgeSkeleton(source));
failures.push(...await judgeStop(original, 'stop'));

// ── 대조군 ──────────────────────────────────────────────────────────────────
const RECORD_LINE = '  if (client !== null && published) recordStop(client, commandId, taskId ?? NO_NODE);\n';
const LOCK_LINE = '  const stopped = lockStopped(published, failure);\n';
{
  const scratch = makeScratch(join(root, 'src', 'physical'), '.verify-stoprec-');
  try {
    // 사본은 한 칸 깊은 폴더에 산다 — 상대 경로를 한 칸 늘려 **같은 모듈 인스턴스**를 끌어온다.
    const deepened = source
      .replaceAll("from '../", "from '\u0000/")
      .replaceAll("from './", "from '../")
      .replaceAll("from '\u0000/", "from '../../");
    const lockAt = deepened.indexOf(LOCK_LINE);
    const mutants = [
      ['기록을 지운 사본', deepened.replace(RECORD_LINE, '')],
      // 기록 줄을 잠금 줄 **앞**으로 옮긴다 — 발행 → 기록 → 잠금. 기록이 잠금을 앞지른다.
      ['기록을 잠금 앞으로 옮긴 사본 (순서를 바꾼 사본)', lockAt < 0 ? deepened
        : deepened.replace(RECORD_LINE, '').replace(LOCK_LINE, RECORD_LINE + LOCK_LINE)],
    ];
    for (const [label, code] of mutants) {
      if (code === deepened || !code.includes('export async function emergencyStop(')) {
        failures.push(`대조군을 만들지 못했다 — ${label} (원본이 바뀌었나?)`);
        continue;
      }
      const path = scratch.file(`robotCommands-${controls.length}.ts`);
      writeFileSync(path, code, 'utf8');
      const mutant = await import(pathToFileURL(path).href);
      // **둘 다 본다** — 실행 판정과 소스 판정. 어느 한쪽만 잡아도 대조군은 잡힌 것이다.
      const runtime = await judgeStop(mutant, `m${controls.length}`);
      const skeleton = judgeSkeleton(code);
      if (runtime.length === 0 && skeleton.length === 0) {
        failures.push(`대조군 실패: ${label}이 통과했다 — 이 검사는 무의미하다`);
      } else {
        controls.push(`${label} (실행 ${runtime.length} · 소스 ${skeleton.length})`);
      }
    }
  } finally {
    scratch.cleanup();
  }
}

session.resetRobotSession();

if (failures.length) {
  console.error(`❌ verify:stop-recorded\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log('✅ 긴급정지가 명령으로 기록 열에 들어간다 — 같은 command_id · abort · 주체 human · 돌던 태스크 · 로봇의 답도 붙는다');
console.log('✅ 돌던 태스크가 없으면 NO_NODE(노드에 안 붙음) · 못 보낸 정지는 안 적는다 — 그래도 잠근다 (실패·예외·연결 없음)');
console.log('✅ 순서 그대로 — 발행 순간 안 잠김·기록 없음 → 잠그는 순간 기록 없음 → 그 뒤에 기록 (실행 중에 봤다) · 소스 뼈대도 같은 순서');
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
