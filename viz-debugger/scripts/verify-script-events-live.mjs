// verify:script-events-live (261025 신설 — 대본 사건과 무응답 1부)
//
// **로봇이 모는 판에도 계획의 생성 사건(`created`)이 기록 열에 들어오는가.**
//
// 로봇이 모는 판은 타이머를 안 세워 `feedLocalTrace()` 가 한 번도 안 불렸다 — 대본 사건 54건이 0건 들어왔고, 보관
// 문 찾기 66판의 `created` 가 0개였다. 화면은 접기가 `pending` 을 심어 대기부터 그렸지만, 기록만 읽는 쪽(Foxglove)은
// `running` 부터 그렸다 — **태스크의 첫 상태가 기록이 아니라 코드 기본값에서 나왔다.** 지금은 승인하는 순간
// `seedPlan()` 이 넣는다(`data/scenario.ts`).
//
// 보는 것 — 판 넷을 앱이 여는 길(`propose…` → `acceptProposal`)로 연다(`lib/scriptEventsProbe.mjs`).
//   ① 로봇이 모는 판(robot)의 `created` 가 타이머가 도는 판(timer)과 **같은 종류 · 같은 개수 · 같은 seq** — 대본 그대로
//   ② 로봇이 모는 판에 대본의 **진행 사건은 안 들어온다** — 라이브 경로가 실제 값으로 적는다. 대본 진행까지 넣으면
//      한 노드에 진행이 두 벌이다(260910 에 걷어 낸 것)
//   ③ 생성 임무는 태스크마다 0초 `created` 를 지어 넣는다 — 대역 `PLAN_SEQ_BASE` · 주체는 정량 명령 human · 모델 제안 ai
//   ④ 생성 사건은 승인 사건 **뒤**에 읽힌다(생성 임무) — 「계획이 임무가 됐다」
//
// 대조군 — `src/` 를 통째로 복사해 한 줄 바꾼 트리로 같은 판을 몬다(LF 정규화 원본 · `readSource`).
//   대본 사건을 안 펴는 사본 · 타이머 쪽에서만 펴는 사본 (지시서) · 진행 사건까지 펴는 사본 · 정량 명령을 ai 로 적는 사본
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mutantTree } from './lib/actionTimeRun.mjs';

const vizRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const probeFile = join(vizRoot, 'scripts', 'lib', 'scriptEventsProbe.mjs');
const { PLAN_SEQ_BASE, AI_SEQ_BASE, HUMAN_SEQ_BASE } = await import(new URL('../src/data/trace.ts', import.meta.url).href);

const BOARDS = ['robot', 'timer', 'steps', 'ai'];
const drive = (root) => Object.fromEntries(BOARDS.map((b) => {
  const out = execFileSync(process.execPath, [probeFile, root, b], { encoding: 'utf8', cwd: vizRoot, maxBuffer: 1 << 26 });
  return [b, JSON.parse(out.trim().split('\n').filter((l) => l.startsWith('{')).at(-1))];
}));

function judge({ robot, timer, steps, ai }) {
  const bad = [];
  const created = (p) => p.column.filter((e) => e.kind === 'created');
  const key = (e) => `${e.seq}|${e.nodeId}|${e.status}|${e.atSec}`;
  // ①
  const r = created(robot); const t = created(timer);
  if (robot.scriptCreated.length === 0) bad.push('문 찾기 대본에 created 가 없다 — 비교할 재료가 없다');
  if (r.length !== robot.scriptCreated.length) bad.push(`① 로봇이 모는 판의 created ${r.length}건 — 대본은 ${robot.scriptCreated.length}건이다`);
  if (JSON.stringify(r.map(key).sort()) !== JSON.stringify(t.map(key).sort())) bad.push(`① 로봇이 모는 판(${r.length})과 타이머 판(${t.length})의 created 가 다르다`);
  if (r.some((e) => e.atSec !== 0 || e.status !== 'pending')) bad.push('① created 가 0초 · pending 이 아니다');
  // ② 대본 대역(AI 대역 아래)의 진행 사건이 로봇 판에 섞였는가
  const scriptProgress = robot.column.filter((e) => e.seq < AI_SEQ_BASE && e.kind !== 'created');
  if (scriptProgress.length > 0) bad.push(`② 로봇이 모는 판에 대본 진행 사건 ${scriptProgress.length}건이 들어왔다(${scriptProgress.slice(0, 3).map((e) => `${e.nodeId} ${e.kind}`).join(' · ')}) — 진행이 두 벌이 된다`);
  // ③ ④
  for (const [p, who] of [[steps, 'human'], [ai, 'ai']]) {
    const c = created(p);
    if (c.length !== p.tasks.length) bad.push(`③ ${p.missionId}: created ${c.length}건 — 태스크는 ${p.tasks.length}개다`);
    if (c.some((e) => e.seq < PLAN_SEQ_BASE || e.seq >= PLAN_SEQ_BASE + 1_000_000)) bad.push(`③ ${p.missionId}: created 의 seq 가 계획 대역(${PLAN_SEQ_BASE}~) 밖이다`);
    if (c.some((e) => e.producedBy !== who)) bad.push(`③ ${p.missionId}: created 의 주체가 ${[...new Set(c.map((e) => e.producedBy))].join(',')} — ${who} 여야 한다`);
    const accepted = p.column.find((e) => e.kind === 'proposal_accepted');
    if (accepted === undefined) bad.push(`④ ${p.missionId}: 승인 사건이 없다`);
    else if (c.some((e) => p.column.indexOf(e) < p.column.indexOf(accepted))) bad.push(`④ ${p.missionId}: created 가 승인보다 먼저 읽힌다 — 「승인하기도 전에 태스크가 생겼다」`);
    if (accepted !== undefined && !(accepted.seq >= HUMAN_SEQ_BASE)) bad.push(`④ ${p.missionId}: 승인 사건의 seq 가 사람 대역이 아니다`);
  }
  return bad;
}

const failures = [];
const real = judge(drive(vizRoot));
failures.push(...real);
if (real.length === 0) console.log('✅ 원본 — 로봇이 모는 판에도 created 17 · 진행 0 · 생성 임무는 human/ai 로 지어 넣음');

const S = 'src/data/scenario.ts';
const controls = [
  { name: '대본 사건을 안 펴는 사본', from: "  commitNow({ current: view, proposal: null, headSec: 0, playing: true, activatedBy: 'approval' });\n  seedPlan(view, null);\n", to: "  commitNow({ current: view, proposal: null, headSec: 0, playing: true, activatedBy: 'approval' });\n" },
  { name: '타이머 쪽에서만 펴는 사본', from: "function seedPlan(view: MissionView, synthesizedBy: 'ai' | 'human' | null): void {\n", to: "function seedPlan(view: MissionView, synthesizedBy: 'ai' | 'human' | null): void {\n  if (robotDrives()) return;\n" },
  { name: '진행 사건까지 펴는 사본', from: '  const fromScript = view.events.filter((event) => event.kind === PLAN_KIND);', to: '  const fromScript = view.events;' },
  { name: '정량 명령을 ai 로 적는 사본', from: "seedPlan(proposal.view, proposal.origin === 'steps' ? 'human' : 'ai');", to: "seedPlan(proposal.view, 'ai');" },
];
const caught = [];
for (const c of controls) {
  const tree = mutantTree('.verify-scriptevents-', S, c.from, c.to);
  if (tree === null) { failures.push(`대조군을 만들지 못했다: ${c.name} — 치환이 아무것도 안 바꿨다`); continue; }
  try {
    const hit = judge(drive(tree.root));
    if (hit.length > 0) caught.push(`${c.name} (${hit[0].slice(0, 60)})`);
    else failures.push(`대조군 실패: ${c.name} — 변조 사본이 잡히지 않았다`);
  } finally {
    tree.cleanup();
  }
}

if (failures.length > 0) {
  console.error(`❌ verify:script-events-live — ${failures.length}건\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`✅ 대조군 ${caught.length}건 전부 검출 — ${caught.join(' · ')}`);
console.log('✅ verify:script-events-live — 로봇이 모는 판에도 계획의 생성 사건이 들어온다 · 진행은 안 들어온다');
