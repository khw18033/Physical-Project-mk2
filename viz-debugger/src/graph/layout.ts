/**
 * src/graph/layout.ts
 *
 * 태스크 그래프의 **기준 배치**. 사용자가 노드를 끌어 옮기면 그 위치가 이 값을 덮는다.
 *
 * ## 폭을 알고 접는다 (260901 — 후속 3건 요구 2)
 *
 * 8/31까지는 깊이 하나당 열 하나를 무조건 오른쪽으로 붙였다(`x = 30 + column * 220`).
 * 노드 분화 뒤 세 편의 「임무 전체」는 거의 일직선 사슬이라 깊이가 그대로 열 수가 됐고,
 * 3편은 깊이 15 → 폭 약 3,550 px 로 화면의 두세 배가 됐다. `.graph-canvas` 가 그 값을
 * 인라인 `width` 로 그대로 받아 **페이지 전체가 옆으로 늘어나고 오른쪽 노드는 첫 화면에서
 * 보이지 않았다.**
 *
 * 그래서 **밴드로 접는다(band wrap)** — 한 밴드에 들어갈 열 수를 실제 화면 폭에서 구하고,
 * 넘치는 깊이는 다음 밴드의 첫 열로 내린다. 세로만 길어지고 가로는 화면 안에 남는다.
 *
 * 자동 정렬·확대축소·미니맵은 만들지 않는다. 사용자가 노드를 임의로 옮길 수 있으므로
 * **첫 화면에 다 들어오기만 하면 된다**(사용자 요건).
 */

import type { Task } from '../model/types.ts';
export type Position = { x: number; y: number };

/**
 * 노드 상자 크기. **화면(TaskGraph)과 배치가 같은 값을 봐야** 「폭 안에 들어왔다」는 계산이
 * 실제 그림과 맞는다. `verify:layout` 도 이 값으로 검사한다 — 세 곳에 손으로 적으면 갈라진다.
 */
export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 110;

/** 왼쪽 여백 · 한 열이 차지하는 가로 몫(노드 180 + 사이 40) · dag 세로 간격. */
const PAD = 30;
const COL = 220;
const ROW = 150;
/** 트리 배치의 세로 간격 — 한 노드당 한 줄이다. */
const TREE_ROW = 92;
/** 밴드 사이 통로. 줄바꿈 엣지(`↵`)가 지나갈 자리다. */
const BAND_GAP = 70;
/**
 * 이보다 좁게는 접지 않는다. 한 열짜리로 접으면 세로가 터무니없이 길어져 접기가 더 나쁘다 —
 * 그때는 접기를 포기하고 가로 스크롤을 허용한다(`.graph-scroll` 의 `overflow-x:auto`).
 */
const MIN_COLS = 3;

/**
 * 한 밴드에 몇 열이 들어가는가. 폭을 모르면(측정 전·검사) 접지 않는다 — 옛 배치 그대로다.
 * 마지막 열의 오른쪽 끝이 폭을 넘지 않는다: `PAD + (n-1)*COL + NODE_WIDTH < availableWidth`.
 */
export function columnsPerBand(availableWidth?: number): number {
  if (availableWidth === undefined || !Number.isFinite(availableWidth)) return Number.POSITIVE_INFINITY;
  return Math.max(MIN_COLS, Math.floor((availableWidth - PAD) / COL));
}

function depths(tasks: Task[]) {
  const result: Record<string, number> = {};
  const byId = new Map(tasks.map((task) => [task.id, task]));
  // 순환 방어선 (260831) — 되돌아가는 엣지는 refEdges 로 분리돼 있어 정상 데이터에서는
  // 순환이 없지만, 데이터 실수 하나(deps 에 루프)로 화면이 통째로 멎으면 안 된다.
  // 방문 중 스택에 있는 노드를 다시 만나면 그 간선을 깊이 0으로 끊는다.
  const visiting = new Set<string>();
  const visit = (id: string): number => {
    if (result[id] !== undefined) return result[id];
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const depth = Math.max(0, ...((byId.get(id)?.deps ?? []).map((dep) => visit(dep) + 1)));
    visiting.delete(id);
    result[id] = depth;
    return depth;
  };
  for (const task of tasks) visit(task.id);
  return result;
}

export function dagLayout(tasks: Task[], availableWidth?: number): Record<string, Position> {
  const depth = depths(tasks);
  const columns = new Map<number, Task[]>();
  for (const task of tasks) columns.set(depth[task.id], [...(columns.get(depth[task.id]) ?? []), task]);
  const perBand = columnsPerBand(availableWidth);

  // 밴드 높이는 **그 밴드에서 가장 높은 열의 노드 수**로 정한다. 상수로 두면 1편 MS-D 처럼
  // 한 열에 노드가 셋인 밴드가 다음 밴드와 겹친다 — `verify:layout` 이 상자 겹침으로 잡는다.
  const rowsInBand = new Map<number, number>();
  for (const [column, nodes] of columns) {
    const band = Math.floor(column / perBand);
    rowsInBand.set(band, Math.max(rowsInBand.get(band) ?? 1, nodes.length));
  }
  const bandTop = new Map<number, number>();
  let top = 55;
  for (const band of [...rowsInBand.keys()].sort((a, b) => a - b)) {
    bandTop.set(band, top);
    top += (rowsInBand.get(band) ?? 1) * ROW + BAND_GAP;
  }

  return Object.fromEntries(
    [...columns].flatMap(([column, nodes]) => {
      const band = Math.floor(column / perBand);
      const col = column % perBand;
      return nodes.map((task, row) => [task.id, { x: PAD + col * COL, y: (bandTop.get(band) ?? 55) + row * ROW }]);
    }),
  ) as Record<string, Position>;
}

/**
 * 트리 배치 — 한 노드당 한 줄이라 원래 세로로 길다. **폭만 접으면 된다.**
 * 접힌 뒤의 x 는 깊이가 아니라 「깊이 % 한 밴드의 열 수」다.
 */
export function treeLayout(tasks: Task[], availableWidth?: number): Record<string, Position> {
  const depth = depths(tasks);
  const perBand = columnsPerBand(availableWidth);
  return Object.fromEntries(
    tasks.map((task, index) => [task.id, { x: PAD + (depth[task.id] % perBand) * COL, y: 25 + index * TREE_ROW }]),
  ) as Record<string, Position>;
}
