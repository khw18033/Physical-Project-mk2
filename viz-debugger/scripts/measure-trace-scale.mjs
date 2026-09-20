// measure:trace-scale (260920 신설 — 명령 기록 합류 §8)
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
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const load = (...p) => import(pathToFileURL(join(root, ...p)).href);
const scenarioDir = join(root, 'scenarios');

const { actionItemEvents, ACTION_KINDS } = await load('src', 'data', 'actionTrace.ts');
const { ACTION_SEQ_BASE } = await load('src', 'data', 'trace.ts');

/** 착수 전 실측. 이 작업이 분모를 얼마나 키웠는지를 말하려면 출발점이 있어야 한다. */
const BASELINE = { milestones: 30, tasks: 83, actionItems: 4, events: 280 };

/** 대본 원본만. 사이드카(`.en.json` · `.match.json`)는 대본이 아니다. */
const scripts = readdirSync(scenarioDir)
  .filter((name) => /^MSN-[\d-]+\.json$/.test(name))
  .map((name) => JSON.parse(readFileSync(join(scenarioDir, name), 'utf8')))
  .sort((a, b) => a.missionId.localeCompare(b.missionId));

const rows = scripts.map((script) => {
  const derived = actionItemEvents(script.tasks, ACTION_SEQ_BASE);
  const of = (kind) => derived.filter((e) => e.kind === kind).length;
  return {
    missionId: script.missionId,
    milestones: script.milestones.length,
    tasks: script.tasks.length,
    /** 대본이 **정의**한 액션 아이템 수. 그중 명령 정의가 있는 것만 흐른다. */
    actionItems: script.tasks.reduce((sum, task) => sum + (task.actionItems?.length ?? 0), 0),
    /** 파일에 적힌 사건 — 마일스톤·태스크 층. */
    events: script.events.length,
    commanded: of(ACTION_KINDS.commanded),
    answered: of(ACTION_KINDS.answered),
    expired: of(ACTION_KINDS.expired),
    adjusted: of(ACTION_KINDS.adjusted),
    derived: derived.length,
  };
});

const sum = (key) => rows.reduce((total, row) => total + row[key], 0);

console.log('기록 열 규모 실측 — 층별 사건 수 (논문 §5-2 축 가의 분모)\n');
console.log('대본             마일스톤  태스크  액션정의    태스크층   명령   응답  기한   액션층    합계');
console.log('─'.repeat(92));
for (const row of rows) {
  console.log(
    row.missionId.padEnd(16) +
    String(row.milestones).padStart(8) +
    String(row.tasks).padStart(8) +
    String(row.actionItems).padStart(10) +
    String(row.events).padStart(12) +
    String(row.commanded).padStart(7) +
    String(row.answered).padStart(7) +
    String(row.expired).padStart(6) +
    String(row.derived).padStart(9) +
    String(row.events + row.derived).padStart(8),
  );
}
console.log('─'.repeat(92));
console.log(
  '합계'.padEnd(16) +
  String(sum('milestones')).padStart(8) +
  String(sum('tasks')).padStart(8) +
  String(sum('actionItems')).padStart(10) +
  String(sum('events')).padStart(12) +
  String(sum('commanded')).padStart(7) +
  String(sum('answered')).padStart(7) +
  String(sum('expired')).padStart(6) +
  String(sum('derived')).padStart(9) +
  String(sum('events') + sum('derived')).padStart(8),
);

const total = sum('events') + sum('derived');
console.log('');
console.log(`기준선(260920 착수 전) — 마일스톤 ${BASELINE.milestones} · 태스크 ${BASELINE.tasks} · 액션 아이템 ${BASELINE.actionItems} · 사건 ${BASELINE.events}`);
console.log(`지금                   — 마일스톤 ${sum('milestones')} · 태스크 ${sum('tasks')} · 액션 아이템 ${sum('actionItems')} · 사건 ${total}`);
console.log(`사건 ${BASELINE.events} → ${total} (×${(total / BASELINE.events).toFixed(2)}) · 액션 층이 ${sum('derived')}건을 더했다`);

// **한 편만 채웠다** (§5). 나머지 다섯은 다음 작업이고, 그 사실을 숫자 옆에 적어 둔다 —
// 「배수가 왜 이것밖에 안 되나」의 답이 여기 있다.
const filled = rows.filter((row) => row.derived > 0);
const empty = rows.filter((row) => row.derived === 0);
console.log('');
console.log(`액션 아이템을 채운 편 — ${filled.map((r) => r.missionId).join(', ') || '없음'} (${filled.length}/${rows.length}편)`);
console.log(`아직 안 채운 편       — ${empty.map((r) => r.missionId).join(', ')}`);
if (filled.length > 0) {
  const one = filled[0];
  const ratio = one.events === 0 ? 0 : (one.events + one.derived) / one.events;
  console.log('');
  console.log(`한 편만 보면 — ${one.missionId} 의 사건이 ${one.events} → ${one.events + one.derived} (×${ratio.toFixed(2)})`);
  console.log(`전편을 같은 밀도로 채우면 합계는 약 ${Math.round(sum('events') * ratio)}건이 된다 (추정 — 편마다 명령 수가 달라 그대로는 안 된다)`);
}
