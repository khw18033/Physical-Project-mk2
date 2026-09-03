import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dagLayout, treeLayout } from '../src/graph/layout.ts';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const scenario = JSON.parse(await readFile(join(root, 'scenarios', 'MSN-260826-01.json'), 'utf8'));
const source = await readFile(join(root, 'src', 'graph', 'TaskGraph.tsx'), 'utf8');
for (const [name, layout] of [['DAG', dagLayout(scenario.tasks)], ['트리', treeLayout(scenario.tasks)]]) {
  const positions = Object.values(layout);
  const unique = new Set(positions.map(({ x, y }) => `${x},${y}`));
  if (positions.length !== 7 || unique.size !== 7) throw new Error(`${name}: 노드 위치가 겹치거나 누락됨`);
  console.log(`✅ ${name} 노드 7개 좌표가 모두 다름`);
}
if (!source.includes('style={{ left: position.x, top: position.y }}')) throw new Error('계산 좌표가 CSS left/top에 적용되지 않음');
console.log('✅ 계산 좌표를 카드 CSS left/top에 적용');
if (source.includes('viewBox={`0 0 1380')) throw new Error('SVG와 HTML 노드가 서로 다른 좌표계를 사용함');
if (!source.includes('width={width} height={height}')) throw new Error('SVG가 그래프 캔버스 픽셀 크기를 공유하지 않음');
console.log('✅ SVG 연결선과 HTML 노드가 같은 픽셀 좌표계 사용');
if (!source.includes('onPointerDown=') || !source.includes('onPointerMove=')) throw new Error('노드 드래그 경로 누락');
console.log('✅ 포인터 드래그로 노드 위치와 연결선 좌표를 함께 갱신');

// ── 접기 배치 — 계산된 노드가 주어진 폭 안에 들어오는가 (260901 후속 3건 요구 2) ──────
//
// 이번 문제가 정확히 이것이었다: 깊이 하나당 열 하나를 무조건 오른쪽에 붙여 3편 「임무 전체」가
// 약 3,550 px 가 됐고, 첫 화면에서 오른쪽 노드가 보이지 않았다. **세 편 × 두 배치 모드 ×
// 두 범위**로 그 일이 다시 나면 여기서 잡힌다.
import { NODE_HEIGHT, NODE_WIDTH, columnsPerBand } from '../src/graph/layout.ts';
import { SCRIPT_IDS } from '../src/scenarios/manifest.ts';

const scripts = [];
for (const id of SCRIPT_IDS) {
  scripts.push(JSON.parse(await readFile(join(root, 'scenarios', `${id}.json`), 'utf8')));
}
/** 실제로 쓰는 창 폭들. 좁은 쪽은 노트북, 넓은 쪽은 외부 모니터. */
const WIDTHS = [1120, 1280, 1440, 1920];
const foldFailures = [];

/** 노드 상자가 서로 겹치는가 (dag 전용 — tree 는 92px 간격이 원래 노드 높이보다 좁다). */
function overlaps(positions) {
  const boxes = Object.entries(positions);
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const [aId, a] = boxes[i];
      const [bId, b] = boxes[j];
      if (Math.abs(a.x - b.x) < NODE_WIDTH && Math.abs(a.y - b.y) < NODE_HEIGHT) return `${aId}·${bId}`;
    }
  }
  return null;
}

function checkFold(label, tasks, width) {
  const f = [];
  for (const [mode, layout] of [['DAG', dagLayout], ['트리', treeLayout]]) {
    const positions = layout(tasks, width);
    const ids = Object.keys(positions);
    if (ids.length !== tasks.length) f.push(`${label} ${mode} ${width}px: 노드 ${tasks.length}개 중 ${ids.length}개만 배치됐다`);
    const right = Math.max(...Object.values(positions).map((p) => p.x + NODE_WIDTH));
    if (right > width) f.push(`${label} ${mode} ${width}px: 오른쪽 끝이 ${right}px — 화면 밖으로 ${right - width}px 나간다`);
    if (mode === 'DAG') {
      const hit = overlaps(positions);
      if (hit !== null) f.push(`${label} DAG ${width}px: 노드 상자가 겹친다 (${hit}) — 밴드 높이가 그 밴드의 노드 수를 반영하지 않는다`);
    } else {
      const unique = new Set(Object.values(positions).map((p) => `${p.x},${p.y}`));
      if (unique.size !== ids.length) f.push(`${label} 트리 ${width}px: 노드 위치가 겹친다`);
    }
  }
  return f;
}

for (const script of scripts) {
  const milestones = [...new Set(script.tasks.map((t) => t.milestone))];
  for (const width of WIDTHS) {
    // 범위 둘 — 「임무 전체」와 마일스톤 하나씩.
    foldFailures.push(...checkFold(`${script.missionId} 임무 전체(${script.tasks.length}노드)`, script.tasks, width));
    for (const milestone of milestones) {
      const own = script.tasks.filter((t) => t.milestone === milestone);
      foldFailures.push(...checkFold(`${script.missionId} ${milestone}(${own.length}노드)`, own, width));
    }
  }
}

// 좁은 창에서는 접기를 포기한다 — 한 열짜리로 접으면 세로가 터무니없이 길어진다.
if (columnsPerBand(500) !== 3) foldFailures.push(`좁은 창(500px)에서 한 밴드 열 수가 ${columnsPerBand(500)} — MIN_COLS(3) 아래로 접으면 안 된다`);
if (Number.isFinite(columnsPerBand(undefined))) foldFailures.push('폭을 모를 때 접는다 — 측정 전에는 옛 배치 그대로여야 한다');

// 음성 대조군 — 접지 않은 배치(폭 모름)는 반드시 폭 검사에 걸려야 한다.
{
  const widest = scripts.reduce((a, b) => (a.tasks.length > b.tasks.length ? a : b));
  const unfolded = dagLayout(widest.tasks);
  const right = Math.max(...Object.values(unfolded).map((p) => p.x + NODE_WIDTH));
  if (right <= 1920) foldFailures.push(`대조군 실패: 접지 않은 ${widest.missionId} 배치가 ${right}px 로 1920px 안에 들어왔다 — 이 검사는 무의미하다`);
  else console.log(`✅ 음성 대조군 — 접지 않으면 ${widest.missionId} 임무 전체가 ${right}px (화면의 두세 배)`);
}

if (foldFailures.length) {
  console.error(`❌ 접기 배치 검사 실패:\n  - ${foldFailures.join('\n  - ')}`);
  process.exit(1);
}
console.log(`✅ 접기 배치 — 대본 ${scripts.length}편 × DAG/트리 × 임무 전체·마일스톤별, 폭 ${WIDTHS.join('/')}px 에서 노드가 하나도 화면 밖으로 나가지 않고 겹치지 않음`);

// ── 뷰 노드가 세로를 밀어낸다 (260903 — 노드 캔버스 1단계) ──────────────────────
//
// 가로는 위에서 봤다. 뷰 노드는 **세로**로 자란다 — 연결한 태스크 바로 아래에 붙기 때문이고,
// 한 열의 세로 간격(ROW 150)은 노드 상자(110) 아래로 40px 밖에 없다. 배치가 붙은 수를
// 모르면 그 열의 **다음 태스크와 겹친다.** 여기서 보는 것 넷:
//
//  1. **깊이 계산에 뷰 노드가 들어가지 않는다** — 붙이기 전후로 태스크의 x 가 한 픽셀도
//     달라지지 않아야 한다 (`deps` 오염 검사의 기하학판이다).
//  2. 태스크끼리 · 뷰 카드와 태스크 · 뷰 카드끼리 — 상자가 하나도 겹치지 않는다.
//  3. 뷰 카드도 화면 폭 안에 있다.
//  4. **음성 대조군** — 배치에 붙은 수를 알리지 않고 뷰 노드를 달면 반드시 겹침이 잡힌다.
import { VIEW_NODE_HEIGHT, VIEW_NODE_WIDTH, viewNodeLayout } from '../src/graph/layout.ts';

/** 최악의 경우 — 모든 태스크에 한 장, 첫 태스크에 두 장. */
function attachAll(tasks) {
  const attached = new Map(tasks.map((task) => [task.id, 1]));
  if (tasks.length > 0) attached.set(tasks[0].id, 2);
  return attached;
}
function viewNodesFor(attached) {
  const nodes = [];
  for (const [taskId, count] of attached) {
    for (let i = 0; i < count; i += 1) nodes.push({ id: `vn-${taskId}-${i}`, taskId });
  }
  // 전역 노드도 하나 — 연결선이 없으므로 태스크 사이가 아니라 맨 아래 레인으로 가야 한다.
  nodes.push({ id: 'vn-global', taskId: null });
  return nodes;
}
function boxesOverlap(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}
function collide(taskPositions, viewPositions) {
  const boxes = [
    ...Object.entries(taskPositions).map(([id, p]) => ({ id, x: p.x, y: p.y, w: NODE_WIDTH, h: NODE_HEIGHT })),
    ...Object.entries(viewPositions).map(([id, p]) => ({ id, x: p.x, y: p.y, w: VIEW_NODE_WIDTH, h: VIEW_NODE_HEIGHT })),
  ];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      if (boxesOverlap(boxes[i], boxes[j])) return `${boxes[i].id}·${boxes[j].id}`;
    }
  }
  return null;
}

const viewFailures = [];
const heights = [];
for (const script of scripts) {
  const groups = [['임무 전체', script.tasks]];
  for (const milestone of [...new Set(script.tasks.map((t) => t.milestone))]) {
    groups.push([milestone, script.tasks.filter((t) => t.milestone === milestone)]);
  }
  for (const [label, tasks] of groups) {
    if (tasks.length === 0) continue;
    const attached = attachAll(tasks);
    const nodes = viewNodesFor(attached);
    for (const width of WIDTHS) {
      for (const [mode, layout] of [['DAG', dagLayout], ['트리', treeLayout]]) {
        const plain = layout(tasks, width);
        const pushed = layout(tasks, width, attached);
        for (const id of Object.keys(plain)) {
          if (plain[id].x !== pushed[id].x) {
            viewFailures.push(`${script.missionId} ${label} ${mode} ${width}px: 뷰 노드를 달았더니 ${id} 의 x 가 ${plain[id].x}→${pushed[id].x} 로 움직였다 — 깊이 계산이 오염됐다`);
          }
        }
        const views = viewNodeLayout(nodes, pushed, width);
        if (Object.keys(views).length !== nodes.length) {
          viewFailures.push(`${script.missionId} ${label} ${mode} ${width}px: 뷰 노드 ${nodes.length}장 중 ${Object.keys(views).length}장만 배치됐다`);
        }
        if (mode === 'DAG') {
          const hit = collide(pushed, views);
          if (hit !== null) viewFailures.push(`${script.missionId} ${label} DAG ${width}px: 상자가 겹친다 (${hit}) — 배치가 뷰 노드 높이를 반영하지 않는다`);
          if (label === '임무 전체' && width === 1440) {
            heights.push({
              id: script.missionId,
              plain: Math.max(...Object.values(plain).map((p) => p.y + NODE_HEIGHT)),
              withViews: Math.max(...Object.values(views).map((p) => p.y + VIEW_NODE_HEIGHT)),
            });
          }
        }
        const right = Math.max(...Object.values(views).map((p) => p.x + VIEW_NODE_WIDTH));
        if (right > width) viewFailures.push(`${script.missionId} ${label} ${mode} ${width}px: 뷰 카드가 오른쪽으로 ${right - width}px 나간다`);
      }
    }
  }
}

// 음성 대조군 — 붙은 수를 배치에 알리지 않으면 반드시 겹쳐야 한다.
{
  const widest = scripts.reduce((a, b) => (a.tasks.length > b.tasks.length ? a : b));
  const attached = attachAll(widest.tasks);
  const blind = dagLayout(widest.tasks, 1440); // attached 를 넘기지 않았다
  const views = viewNodeLayout(viewNodesFor(attached), blind, 1440);
  const hit = collide(blind, views);
  if (hit === null) viewFailures.push('대조군 실패: 배치가 뷰 노드 수를 몰랐는데도 겹치지 않았다 — 이 검사는 무의미하다');
  else console.log(`✅ 음성 대조군 — 붙은 수를 배치가 모르면 상자가 겹친다 (${hit})`);
}

if (viewFailures.length) {
  console.error('❌ 뷰 노드 세로 배치 검사 실패:');
  for (const line of viewFailures) console.error(`  - ${line}`);
  process.exit(1);
}
console.log(`✅ 뷰 노드 — 태스크마다 1장(첫 태스크 2장) + 전역 1장에서 깊이 무변경 · 겹침 0 · 폭 안`);
console.log(`   세로 실측 (1440px · DAG · 임무 전체): ${heights.map((h) => `${h.id} ${h.plain}→${h.withViews}px`).join(' · ')}`);
