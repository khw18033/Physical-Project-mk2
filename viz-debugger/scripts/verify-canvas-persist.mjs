// 캔버스 구성 보존 (260903 — 노드 캔버스 1단계) — **놓아 둔 것이 사라지지 않는가.**
//
// `VZ-N-04` 는 「캔버스 구성은 마일스톤별로 보존되며 새로고침·재접속 후에도 유지되어야
// 한다」이다. 사용자가 만든 것이 조용히 사라지는 것이 이 화면에서 제일 나쁜 실패다.
//
// 여기서 보는 것 다섯:
//  1. **3층** — ② 사용자 구성 → ① 대본 기본 구성 → 빈 캔버스. 읽는 순서와 이기는 순서.
//  2. **슬롯** — 마일스톤마다 다른 구성이고 「임무 전체」는 별도 슬롯(`__mission__`)이다.
//     마일스톤을 옮겼다 돌아오면 그대로 있어야 한다.
//  3. **실패 셋** — 저장소 막힘 · 연결한 태스크 소실 · 스키마 변경 (지시서 §4).
//  4. **DAG↔트리 전환이 뷰 노드를 지우지 않는가** — 태스크의 `movedPositions` 는 배치 모드가
//     바뀌면 버려진다(자동 배치가 다시 계산되니 맞다). 뷰 노드는 사용자가 놓은 것이라
//     같이 버리면 "내가 만든 게 사라졌다"가 된다. **두 저장소가 분리돼 있는지**를 본다.
//  5. 음성 대조군 — 위 판정들이 실제로 실패를 잡는가.
//
// 규칙은 전부 `src/canvas/persist.ts` 의 순수 함수라 여기서 그대로 돌린다.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  CANVAS_SCHEMA_VERSION,
  MISSION_SLOT,
  canvasKey,
  clearCanvas,
  emptyCanvas,
  loadCanvas,
  parseCanvas,
  reconcile,
  saveCanvas,
} from '../src/canvas/persist.ts';

const root = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const read = (...parts) => readFileSync(join(root, ...parts), 'utf8');
const failures = [];
const check = (ok, message) => { if (!ok) failures.push(message); };

const MISSION = 'MSN-260831-01';
const node = (id, taskId = 'T-11a', x = null, y = null) => ({ id, kind: 'device-risk', taskId, x, y });

function fakeStorage(seed = {}) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { map.set(key, value); },
    removeItem: (key) => { map.delete(key); },
  };
}
/** 사파리 비공개 창처럼 **접근 자체가 던지는** 저장소. */
function blockedStorage() {
  const boom = () => { throw new Error('저장소가 막혀 있다'); };
  return { getItem: boom, setItem: boom, removeItem: boom };
}
const noDefaults = () => null;
const withDefault = () => ({ version: CANVAS_SCHEMA_VERSION, nodes: [node('vn-default'), node('vn-default-2')] });
const ids = (config) => config.nodes.map((item) => item.id).join(',');
const TASKS = new Set(['T-11a', 'T-11b']);

// ── ① 3층: ② → ① → 빈 캔버스 ─────────────────────────────────────────────────
{
  const storage = fakeStorage();
  const deps = { storage, defaults: withDefault };
  // 사용자 구성이 없으면 대본 기본 구성이 뜬다.
  const first = loadCanvas(MISSION, 'MS-C', TASKS, deps);
  check(first.source === 'default' && first.config.nodes.length === 2, `층 ①이 안 뜬다: ${first.source}`);
  // 사용자가 하나 놓으면 그것이 **항상** 이긴다.
  saveCanvas(MISSION, 'MS-C', { version: CANVAS_SCHEMA_VERSION, nodes: [node('vn-mine')] }, deps);
  const second = loadCanvas(MISSION, 'MS-C', TASKS, deps);
  check(second.source === 'user' && ids(second.config) === 'vn-mine', `층 ②가 ①을 못 이긴다: ${second.source} ${ids(second.config)}`);
  // 층 ③ 되돌리기 — ②를 지우면 다시 ①이다.
  clearCanvas(MISSION, 'MS-C', deps);
  const third = loadCanvas(MISSION, 'MS-C', TASKS, deps);
  check(third.source === 'default' && third.config.nodes.length === 2, `되돌리기 뒤 층 ①로 안 간다: ${third.source}`);
  // 기본 구성도 없으면 빈 캔버스다. **던지지 않는다.**
  const bare = loadCanvas(MISSION, 'MS-C', TASKS, { storage, defaults: noDefaults });
  check(bare.source === 'empty' && bare.config.nodes.length === 0, `빈 캔버스가 아니다: ${bare.source}`);
  console.log('✅ 3층 — 사용자 구성 > 대본 기본 구성 > 빈 캔버스 · 되돌리기가 ②만 지운다');
}

// ── ② 슬롯: 마일스톤별 · 「임무 전체」는 따로 ──────────────────────────────────
{
  const deps = { storage: fakeStorage(), defaults: noDefaults };
  const keys = new Set([
    canvasKey(MISSION, 'MS-C'),
    canvasKey(MISSION, 'MS-D'),
    canvasKey(MISSION, MISSION_SLOT),
    canvasKey('MSN-260831-02', 'MS-C'),
  ]);
  check(keys.size === 4, '슬롯 키가 겹친다 — 다른 마일스톤·임무가 서로 덮는다');
  saveCanvas(MISSION, 'MS-C', { version: CANVAS_SCHEMA_VERSION, nodes: [node('vn-c')] }, deps);
  saveCanvas(MISSION, MISSION_SLOT, { version: CANVAS_SCHEMA_VERSION, nodes: [node('vn-all'), node('vn-all-2')] }, deps);
  // 마일스톤을 옮겼다(MS-D 는 비어 있다) 돌아온다.
  const away = loadCanvas(MISSION, 'MS-D', TASKS, deps);
  check(away.config.nodes.length === 0, 'MS-D 에 MS-C 의 구성이 새어 들어왔다');
  const back = loadCanvas(MISSION, 'MS-C', TASKS, deps);
  check(ids(back.config) === 'vn-c', `마일스톤을 옮겼다 돌아오니 구성이 사라졌다: ${ids(back.config)}`);
  const whole = loadCanvas(MISSION, MISSION_SLOT, TASKS, deps);
  check(whole.config.nodes.length === 2, '「임무 전체」 슬롯이 마일스톤 슬롯에 먹혔다');
  console.log('✅ 슬롯 — 마일스톤별로 나뉘고 「임무 전체」는 별도 슬롯. 옮겼다 돌아와도 산다');
}

// ── ③ 좌표가 새로고침을 넘는다 ────────────────────────────────────────────────
{
  const storage = fakeStorage();
  saveCanvas(MISSION, 'MS-C', { version: CANVAS_SCHEMA_VERSION, nodes: [node('vn-moved', 'T-11a', 640, 320)] }, { storage, defaults: noDefaults });
  // 새로고침 = 같은 칸을 처음부터 다시 읽는 것.
  const again = loadCanvas(MISSION, 'MS-C', TASKS, { storage, defaults: noDefaults });
  const moved = again.config.nodes[0];
  check(moved.x === 640 && moved.y === 320, `옮긴 자리가 새로고침을 못 넘었다: ${JSON.stringify(moved)}`);
  console.log('✅ 새로고침 — 놓은 자리(좌표)까지 그대로 돌아온다');
}

// ── ④ 실패 1: 저장소가 막혀 있다 → 기본 구성으로 조용히 진행 ──────────────────
{
  for (const [label, storage] of [['없음', null], ['던짐', blockedStorage()]]) {
    const deps = { storage, defaults: withDefault };
    let load = null;
    try {
      load = loadCanvas(MISSION, 'MS-C', TASKS, deps);
    } catch (error) {
      failures.push(`저장소(${label})에서 적재가 던졌다: ${error.message}`);
      continue;
    }
    check(load.writable === false, `저장소(${label})인데 writable 이 true 다`);
    check(load.config.nodes.length === 2, `저장소(${label})에서 기본 구성으로 뜨지 않았다`);
    check(saveCanvas(MISSION, 'MS-C', emptyCanvas(), deps) === false, `저장소(${label})인데 저장이 성공했다고 답한다`);
    let cleared = true;
    try { clearCanvas(MISSION, 'MS-C', deps); } catch { cleared = false; }
    check(cleared, `저장소(${label})에서 되돌리기가 던졌다`);
  }
  console.log('✅ 실패 1 — 저장소가 없거나 던져도 기본 구성으로 뜨고, 저장 실패를 숨기지 않는다');
}

// ── ⑤ 실패 2: 연결한 태스크가 사라졌다 → 지우지 않고 전역으로 강등 ─────────────
{
  const config = { version: CANVAS_SCHEMA_VERSION, nodes: [node('vn-live', 'T-11a'), node('vn-orphan', 'T-99z'), node('vn-global', null)] };
  const settled = reconcile(config, TASKS);
  check(settled.config.nodes.length === 3, '태스크가 사라졌다고 뷰 노드를 지웠다 — 지우면 안 된다');
  const orphan = settled.config.nodes.find((item) => item.id === 'vn-orphan');
  check(orphan.taskId === null, '사라진 태스크에 붙은 노드가 전역으로 강등되지 않았다');
  check(settled.config.nodes.find((item) => item.id === 'vn-live').taskId === 'T-11a', '살아 있는 연결까지 끊었다');
  check(settled.notices.length === 1 && settled.notices[0].includes('T-99z'), `사유 한 줄에 사라진 태스크 id 가 없다: ${settled.notices[0]}`);
  // 적재 도중의 빈 목록에 반응해 강등하면 그 강등이 그대로 저장돼 되돌릴 수 없다.
  const guarded = reconcile(config, new Set());
  check(guarded.config.nodes.every((item, index) => item.taskId === config.nodes[index].taskId), '태스크 목록이 비었을 때도 강등했다 — 적재 도중에 연결이 다 끊긴다');
  console.log('✅ 실패 2 — 사라진 태스크의 노드는 지우지 않고 전역으로 강등 + 사유 한 줄 (빈 목록에는 반응하지 않는다)');
}

// ── ⑥ 실패 3: 스키마가 바뀌었다 → 버리고 기본 구성 + 한 줄 안내 ────────────────
{
  const cases = [
    ['옛 판', JSON.stringify({ version: 99, nodes: [node('vn-old')] })],
    ['깨진 JSON', '{nodes:'],
    ['모양이 다름', JSON.stringify({ version: CANVAS_SCHEMA_VERSION, nodes: 'nope' })],
  ];
  for (const [label, raw] of cases) {
    const parsed = parseCanvas(raw);
    check(parsed.config === null, `${label}: 버리지 않았다`);
    check(typeof parsed.notice === 'string' && parsed.notice.length > 0, `${label}: 한 줄 안내가 없다 — 조용히 사라지면 안 된다`);
  }
  // 성한 것은 그대로 읽힌다. 알 수 없는 종류(다른 빌드에서 만든 것)도 버리지 않고, 망가진 한 칸만 거른다.
  const good = parseCanvas(JSON.stringify({
    version: CANVAS_SCHEMA_VERSION,
    nodes: [node('vn-a'), { ...node('vn-b'), kind: 'unknown-kind' }, { id: 'broken' }],
  }));
  check(good.config !== null && ids(good.config) === 'vn-a,vn-b', `성한 구성을 못 읽거나 망가진 한 칸을 안 걸렀다: ${good.config === null ? 'null' : ids(good.config)}`);
  // 저장된 것이 없으면 안내도 없다 — 첫 방문에 경고가 뜨면 안 된다.
  check(parseCanvas(null).notice === null, '저장된 것이 없는데 안내가 뜬다');
  console.log('✅ 실패 3 — 판이 다르거나 깨졌으면 버리고 한 줄로 알린다. 성한 구성과 첫 방문은 조용하다');
}

// ── ⑦ DAG↔트리 전환이 뷰 노드를 지우지 않는다 (두 저장소의 분리) ───────────────
{
  /** 뷰 노드 저장소가 배치 모드를 아는가 — 알면 모드가 바뀔 때 같이 버려질 길이 생긴다. */
  const knowsLayoutMode = (source) => source.includes('layoutMode');
  for (const file of ['persist.ts', 'useCanvas.ts', 'defaults.ts']) {
    check(!knowsLayoutMode(read('src', 'canvas', file)), `src/canvas/${file} 이 layoutMode 를 안다 — 뷰 노드 저장소가 배치 모드에 묶이면 전환 때 사라진다`);
  }
  const graph = read('src', 'graph', 'TaskGraph.tsx');
  check(graph.includes('setMovedPositions({}), [layoutMode]'), '태스크의 movedPositions 가 배치 모드 전환에서 초기화되지 않는다 — 기존 동작이 바뀌었다');
  // 뷰 노드의 좌표는 저장된 값이 이긴다. 초기화 대상이 아니다.
  check(graph.includes('node.x !== null && node.y !== null'), '뷰 노드가 저장된 좌표를 쓰지 않는다');
  const resetsViews = /setViewDrag\([^)]*\),\s*\[layoutMode\]/.test(graph);
  check(!resetsViews, '뷰 노드 상태가 배치 모드 전환에서 초기화된다');
  // 음성 대조군 — 판정이 실제로 잡는가.
  if (!knowsLayoutMode("const dag = layoutMode === 'dag';")) {
    failures.push('대조군 실패: layoutMode 를 아는 소스를 판정이 놓쳤다 — 이 검사는 무의미하다');
  }
  console.log('✅ DAG↔트리 — 뷰 노드 저장소는 배치 모드를 모른다(전환해도 안 지워진다). 태스크의 이동만 초기화된다');
}

if (failures.length) {
  console.error('❌ 캔버스 구성 보존 검사 실패:');
  for (const line of failures) console.error(`  - ${line}`);
  process.exit(1);
}
console.log(`✅ 통과 — 캔버스 구성 3층 · 슬롯 · 실패 셋 · 배치 모드 전환 (스키마 v${CANVAS_SCHEMA_VERSION})`);
