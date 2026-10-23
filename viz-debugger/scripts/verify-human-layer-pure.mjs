// verify:human-layer-pure (261022 신설 — 사람 층·액션 층 경계 §2 · §6)
//
// **사람 층에 자동 명령이 없는가.**
//
// 260921 실물 판(`114930_MSN-260909-01`)의 사람 층 12건 중 사람이 누른 것은
// `mission_restarted` 하나였다. 나머지 열하나는 `scan_mission` · `scan_continue` · `turn` …
// 화면이 낸 로봇 명령의 **복사본**이었고 주체가 `human` 이었다. 260920 이 액션 층을 더하면서
// 출구 본체(`CommandTracker.issue`)의 옛 기록 줄을 안 지운 탓이다.
//
// 층의 뜻을 하나로 정했다 — **사람 층은 사람이 한 일만 담는다. 명령은 액션 층이 담는다.**
//
// 261023 — **층은 「명령이냐」, 주체는 「누가 냈느냐」.** 사람이 직접 낸 명령(수동 제어 · SAR · 비행 제어)도
// 액션 층으로 갔다(주체 human). 그래서 사람 층에 **남아야 하는 것**을 다시 적는다.
//
//   남는다  누름 — `mission_started` · `mission_resumed` · `approach_started` · `mission_restarted` 류
//           게이트웨이 출구의 명령 — `shared/commandEgress.ts` · `tabs/views/ControlPanel.tsx` (이번 범위 밖,
//           장비가 아니라 게이트웨이로 나간다. 아래 ④가 그 둘만 남았는지 본다)
//   빠진다  장비로 나가는 명령 전부 — `physical/` 의 추적기 호출은 모두 `actionLayer` 를 단다
//
// 보는 것.
//  ① 문 찾기 편 한 판을 실제 길로 몰았을 때 사람 층에 **로봇에 나간 명령의 이름**이나
//     옛 명령 줄의 표식(`payload.task_id`)을 단 사건이 0건이다
//  ② 출구 본체 — `actionLayer` 를 준 명령은 사람 층에 안 적히고, 안 준 명령(사람이 누른
//     제어 패널·수동 제어)은 그대로 적힌다. 사람의 명령까지 지우면 반대쪽 거짓이 된다
//  ③ 사람이 누른 것은 남는다 — 복사본이 흔적 노릇을 하던 시작·접근·재시작을 버튼이 직접 적는다
//
// 대조군 — **`scan_mission` 을 사람 층에 도로 넣은 사본**이 잡혀야 한다. 둘로 만든다:
// 로봇 명령이 `actionLayer` 를 안 주는 `robotCommands.ts` 사본(판을 실제로 몬다)과, 출구 본체가
// `actionLayer` 를 무시하는 `commandCenter.ts` 사본. LF 로 정규화한 원본에서 만든다(`readSource`).
import { readdirSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isScratchPath, makeScratch } from './lib/scratch.mjs';
import { readSource } from './lib/source.mjs';
import { pi7Kit } from './lib/pi7Run.mjs';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);

const kit = await pi7Kit(root);
const original = await load('src', 'physical', 'robotCommands.ts');

const failures = [];
const controls = [];

/** 이 판의 사람 층에 섞인 자동 명령. 로봇에 실제로 나간 이름이 기준이다 — 목록을 손으로 안 적는다. */
function autoInHumanLayer(added, sent) {
  const names = new Set(sent.map((s) => s.action));
  return added.filter((e) => kit.isHumanLayer(e) && (names.has(e.kind) || e.payload?.task_id !== undefined));
}

function judgeRun({ added, sent }) {
  const f = [];
  if (sent.length < 6) f.push(`로봇에 나간 명령이 ${sent.length}건 — 스캔·이어 가기·회전·직진·도착 정지·일시정지·정지가 다 나가야 한다 (검사가 헛돈다)`);
  const mixed = autoInHumanLayer(added, sent);
  if (mixed.length > 0) {
    f.push(`사람 층에 자동 명령 ${mixed.length}건 — ${[...new Set(mixed.map((e) => e.kind))].join(', ')} (사람이 누른 적이 없다)`);
  }
  return f;
}

// ── ① 한 판 ──────────────────────────────────────────────────────────────────
const run = await kit.drive(original, 'pure');
failures.push(...judgeRun(run));
const humanCount = run.added.filter(kit.isHumanLayer).length;

// ── ② 출구 본체 ─────────────────────────────────────────────────────────────
async function judgeEgress(CommandTracker) {
  const f = [];
  const tracker = new CommandTracker();
  const publish = async (request) => ({ clientRequestId: request.client_request_id, commandId: 'cmd-egress', accepted: true, reasonCode: null, message: '' });
  const spec = { action: 'scan_mission', label: 'scan_mission', targetPct: 0, irreversible: false, resultingState: '' };
  const humanBefore = kit.column().filter(kit.isHumanLayer).length;
  await tracker.issue('robot-01', spec, { params: { steps: 8, task_id: 'T-A3' }, actionLayer: true, publish });
  const afterAuto = kit.column().filter(kit.isHumanLayer).length;
  if (afterAuto !== humanBefore) f.push('actionLayer 를 준 명령이 사람 층에 적혔다 — 출구 본체가 복사본을 만든다');
  await tracker.issue('actuator-01', { ...spec, action: 'close_gate', label: 'close_gate' }, { publish });
  if (kit.column().filter(kit.isHumanLayer).length !== afterAuto + 1) {
    f.push('사람이 누른 명령(actionLayer 없음)이 사람 층에 안 적혔다 — 반대쪽 거짓이다');
  }
  return f;
}
const { CommandTracker } = await load('src', 'shared', 'commandCenter.ts');
failures.push(...await judgeEgress(CommandTracker));

// ── ③ 사람이 누른 것은 남는다 ───────────────────────────────────────────────
function judgeButtons(buttonSource) {
  const f = [];
  for (const kind of ['mission_started', 'mission_resumed', 'approach_started']) {
    if (!buttonSource.includes(`recordHuman('${kind}'`)) f.push(`버튼이 ${kind} 를 사람 층에 안 적는다 — 복사본을 걷으면서 사람이 누른 사실까지 사라진다`);
  }
  return f;
}
const buttons = readSource(root, 'src', 'physical', 'StopButton.tsx');
failures.push(...judgeButtons(buttons));

// ── ④ 장비로 나가는 명령은 전부 액션 층 — 남는 것은 게이트웨이 출구 둘뿐 ──────────
//
// 추적기(`commandTracker.issue`)를 부르는 자리를 **전부** 훑는다. 목록을 손으로 적지 않는다 —
// 새 출구가 생기면 여기서 드러나야 한다.
const GATEWAY_EGRESS = new Set(['shared/commandEgress.ts', 'tabs/views/ControlPanel.tsx']);
function judgeEgressSites(sources) {
  const f = [];
  for (const [rel, text] of sources) {
    const calls = text.split(/commandTracker\.issue\s*\(/).slice(1);
    if (calls.length === 0) continue;
    const marked = calls.filter((rest) => /^[\s\S]{0,1200}?actionLayer:\s*true/.test(rest.split(/\n\s*\);?\n/)[0] ?? rest)).length;
    if (GATEWAY_EGRESS.has(rel)) continue;
    if (marked !== calls.length) f.push(`${rel} 의 추적기 호출 ${calls.length}곳 중 ${calls.length - marked}곳이 actionLayer 를 안 단다 — 장비로 나가는 명령이 사람 층에 적힌다`);
  }
  for (const rel of GATEWAY_EGRESS) {
    if (!sources.has(rel)) f.push(`${rel} 가 없다 — 남는 것의 목록이 바뀌었으니 머리말을 다시 적어라`);
  }
  return f;
}
const egressSources = new Map();
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (isScratchPath(path)) continue;
    if (statSync(path).isDirectory()) walk(path);
    else if (/\.tsx?$/.test(name)) {
      const text = readSource(path);
      if (/commandTracker\.issue\s*\(/.test(text)) egressSources.set(path.slice(join(root, 'src').length + 1).replaceAll('\\', '/'), text);
    }
  }
})(join(root, 'src'));
failures.push(...judgeEgressSites(egressSources));

// ── 대조군 ──────────────────────────────────────────────────────────────────
function control(name, hit) {
  if (!hit) failures.push(`대조군 실패: ${name} — 변조 사본이 잡히지 않았다`);
  else controls.push(name);
}
const deepen = (code) => code
  .replaceAll("from '../", "from '\u0000/")
  .replaceAll("from './", "from '../")
  .replaceAll("from '\u0000/", "from '../../");
{
  const scratch = makeScratch(join(root, 'src', 'physical'), '.verify-humanpure-');
  try {
    // ⓐ 로봇 명령이 `actionLayer` 를 안 준다 — 260920~261021 의 모양. `scan_mission` 이 사람 층으로 돌아온다.
    const source = deepen(readSource(root, 'src', 'physical', 'robotCommands.ts'));
    const muted = source.replace('      actionLayer: true,\n', '');
    if (muted === source) failures.push('대조군을 만들지 못했다 — robotCommands.ts 의 actionLayer 줄 (원본이 바뀌었나?)');
    else {
      const path = scratch.file('robotCommands.ts');
      writeFileSync(path, muted, 'utf8');
      const mutant = await import(pathToFileURL(path).href);
      const bad = await kit.drive(mutant, 'pureM');
      const hit = judgeRun(bad);
      control(`scan_mission 을 사람 층에 도로 넣은 robotCommands 사본 (${autoInHumanLayer(bad.added, bad.sent).map((e) => e.kind).join('·')})`,
        hit.length > 0 && autoInHumanLayer(bad.added, bad.sent).some((e) => e.kind === 'scan_mission'));
    }
  } finally {
    scratch.cleanup();
  }
}
{
  const scratch = makeScratch(join(root, 'src', 'shared'), '.verify-humanpure-');
  try {
    // ⓑ 출구 본체가 `actionLayer` 를 무시한다 — 무엇이 오든 사람 층에 적는다.
    const source = deepen(readSource(root, 'src', 'shared', 'commandCenter.ts'));
    const muted = source.replace('if (options.actionLayer !== true) recordHuman(', 'recordHuman(');
    if (muted === source) failures.push('대조군을 만들지 못했다 — commandCenter.ts 의 actionLayer 조건 (원본이 바뀌었나?)');
    else {
      const path = scratch.file('commandCenter.ts');
      writeFileSync(path, muted, 'utf8');
      const mutant = await import(pathToFileURL(path).href);
      control('출구 본체가 actionLayer 를 무시하는 commandCenter 사본', (await judgeEgress(mutant.CommandTracker)).length > 0);
    }
  } finally {
    scratch.cleanup();
  }
}
// ⓓ 수동 제어가 actionLayer 를 안 다는 사본 — 사람이 몬 명령이 사람 층으로 돌아간다(261022 의 모양).
{
  const muted = new Map(egressSources);
  const md = muted.get('physical/manualDispatch.ts') ?? '';
  muted.set('physical/manualDispatch.ts', md.replace(/actionLayer:\s*true,/, ''));
  control('수동 제어가 actionLayer 를 안 다는 사본', md !== '' && judgeEgressSites(muted).length > 0);
}
// ⓒ 버튼이 사람이 누른 사실을 안 적는 사본.
control('버튼에서 approach_started 기록을 지운 사본', judgeButtons(buttons.replace("recordHuman('approach_started'", "noop('x'")).length > 0);

kit.session.resetRobotSession();

if (failures.length) {
  console.error(`❌ verify:human-layer-pure\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 문 찾기 편 한 판(로봇 명령 ${run.sent.length}건)을 몰았다 — 사람 층 ${humanCount}건 중 자동 명령 0건`);
console.log('✅ 출구 본체 — actionLayer 를 준 명령은 사람 층에 안 적고, 사람이 누른 명령은 그대로 적는다');
console.log('✅ 사람이 누른 시작·재시작·접근은 버튼이 사람 층에 직접 적는다');
console.log(`✅ 장비로 나가는 명령은 전부 액션 층 — 추적기 호출 ${egressSources.size}개 파일 중 actionLayer 없이 남은 것은 게이트웨이 출구 둘(${[...GATEWAY_EGRESS].join(' · ')})`);
console.log(`✅ 대조군 ${controls.length}건 전부 검출 — ${controls.join(' · ')}`);
process.exit(0);
