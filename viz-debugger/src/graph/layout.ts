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
 *
 * ## 뷰 노드가 세로를 밀어낸다 (260903 — 노드 캔버스 1단계)
 *
 * 뷰 노드는 기본적으로 **연결한 태스크 바로 아래**에 붙는다. 그런데 한 열의 세로 간격은
 * `ROW`(150) 고정이라 노드 상자(110) 아래로 40px 밖에 없다 — 아무 처리 없이 뷰 노드를
 * 달면 그 열의 **다음 태스크와 겹친다.**
 *
 * 그래서 배치가 붙은 뷰 노드 수를 받아 **그만큼 아래를 밀어낸다**(`attached`). 열 안에서는
 * 뒤따르는 행이 내려가고, 밴드 높이는 그 밴드에서 **가장 높아진 열**로 다시 잡힌다.
 * 붙은 것이 없으면 계산이 예전과 한 픽셀도 다르지 않다 — 탭 화면이 지금 그대로여야 한다.
 * `verify:layout` 이 세 편 × 두 배치 × 폭 넷에서 겹침과 **최대 y** 를 함께 본다.
 *
 * 뷰 노드는 `deps` 에 들어가지 않으므로 `depths()` 는 그대로다 — 깊이 계산에 순환이
 * 들어가지 않는다(`refEdges` 와 같은 이유).
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
 * 뷰 노드 상자 (260903). 폭은 태스크 노드와 **같다** — 연결한 태스크 바로 아래에 붙으므로
 * 폭이 다르면 캔버스가 들쭉날쭉해지고, 「이 노드에 딸린 것」이라는 인상이 흐려진다.
 * 높이는 요약 카드 한 장 분량이다(2단계에서 4종의 실제 요약이 이 안에 들어간다).
 */
export const VIEW_NODE_WIDTH = NODE_WIDTH;
export const VIEW_NODE_HEIGHT = 104;
/** 태스크 아래·뷰 노드 사이의 간격. 연결선(범위 엣지)이 지나갈 자리다. */
export const VIEW_NODE_GAP = 14;
/** 전역 노드 레인의 가로 몫. */
const VIEW_COL = VIEW_NODE_WIDTH + 40;

/** 태스크 하나에 뷰 노드 n 장이 붙으면 그 아래로 얼마나 더 필요한가. */
export function viewStackHeight(count: number): number {
  return count <= 0 ? 0 : count * (VIEW_NODE_HEIGHT + VIEW_NODE_GAP);
}

/** 태스크별 뷰 노드 수. `dagLayout`·`treeLayout` 이 이만큼 아래를 밀어낸다. */
export type Attached = ReadonlyMap<string, number>;

function extraOf(attached: Attached | undefined, id: string): number {
  return viewStackHeight(attached?.get(id) ?? 0);
}

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

export function dagLayout(tasks: Task[], availableWidth?: number, attached?: Attached): Record<string, Position> {
  const depth = depths(tasks);
  const columns = new Map<number, Task[]>();
  for (const task of tasks) columns.set(depth[task.id], [...(columns.get(depth[task.id]) ?? []), task]);
  const perBand = columnsPerBand(availableWidth);

  // 열 안의 세로 자리. 기본은 한 행 ROW 이고, 뷰 노드가 붙은 태스크 뒤로는 그 높이만큼
  // 더 내려간다 (260903). 붙은 것이 없으면 `row * ROW` 와 같은 값이다.
  const offsets = new Map<number, number[]>();
  // 밴드 높이는 **그 밴드에서 가장 높은 열**로 정한다. 상수로 두면 1편 MS-D 처럼
  // 한 열에 노드가 셋인 밴드가 다음 밴드와 겹친다 — `verify:layout` 이 상자 겹침으로 잡는다.
  const bandHeight = new Map<number, number>();
  for (const [column, nodes] of columns) {
    const ys: number[] = [];
    let y = 0;
    for (const task of nodes) {
      ys.push(y);
      y += ROW + extraOf(attached, task.id);
    }
    offsets.set(column, ys);
    const band = Math.floor(column / perBand);
    bandHeight.set(band, Math.max(bandHeight.get(band) ?? ROW, y));
  }
  const bandTop = new Map<number, number>();
  let top = 55;
  for (const band of [...bandHeight.keys()].sort((a, b) => a - b)) {
    bandTop.set(band, top);
    top += (bandHeight.get(band) ?? ROW) + BAND_GAP;
  }

  return Object.fromEntries(
    [...columns].flatMap(([column, nodes]) => {
      const band = Math.floor(column / perBand);
      const col = column % perBand;
      const ys = offsets.get(column) ?? [];
      return nodes.map((task, row) => [task.id, { x: PAD + col * COL, y: (bandTop.get(band) ?? 55) + (ys[row] ?? row * ROW) }]);
    }),
  ) as Record<string, Position>;
}

/**
 * 트리 배치 — 한 노드당 한 줄이라 원래 세로로 길다. **폭만 접으면 된다.**
 * 접힌 뒤의 x 는 깊이가 아니라 「깊이 % 한 밴드의 열 수」다.
 */
export function treeLayout(tasks: Task[], availableWidth?: number, attached?: Attached): Record<string, Position> {
  const depth = depths(tasks);
  const perBand = columnsPerBand(availableWidth);
  const entries: Array<[string, Position]> = [];
  let y = 25;
  for (const task of tasks) {
    entries.push([task.id, { x: PAD + (depth[task.id] % perBand) * COL, y }]);
    y += TREE_ROW + extraOf(attached, task.id);
  }
  return Object.fromEntries(entries) as Record<string, Position>;
}

/**
 * 뷰 노드의 **기준 배치** (260903). 사용자가 끌어 옮기면(`x`·`y` 가 채워지면) 그 값이 이긴다 —
 * 태스크 노드의 `movedPositions` 와 같은 규칙이되 **저장소는 다르다**: 태스크의 이동은
 * DAG↔트리 전환 때 버려지고(자동 배치가 다시 계산되니 맞다), 뷰 노드는 **사용자가 놓은 것**
 * 이라 버리면 "내가 만든 게 사라졌다"가 된다 (`VZ-N-04` · `verify:canvas-persist`).
 *
 * - 연결된 노드: 연결한 태스크 **바로 아래**에 차례로 쌓는다.
 * - 전역 노드: 태스크가 다 그려진 **아래 레인**에 왼쪽부터 늘어놓는다. 연결선이 없으므로
 *   태스크 사이에 끼면 어디에 딸린 것인지 오해를 준다.
 */
export function viewNodeLayout(
  nodes: ReadonlyArray<{ id: string; taskId: string | null }>,
  taskPositions: Record<string, Position>,
  availableWidth?: number,
): Record<string, Position> {
  const result: Record<string, Position> = {};
  const stacked = new Map<string, number>();
  const global: string[] = [];
  for (const node of nodes) {
    const anchor = node.taskId === null ? undefined : taskPositions[node.taskId];
    // 연결한 태스크가 지금 보이는 범위 밖이면 전역과 같은 자리에 둔다 — 화면에서도
    // 그 노드는 전역으로 강등돼 있다(persist.ts 의 reconcile).
    if (anchor === undefined || node.taskId === null) {
      global.push(node.id);
      continue;
    }
    const index = stacked.get(node.taskId) ?? 0;
    stacked.set(node.taskId, index + 1);
    result[node.id] = {
      x: anchor.x,
      y: anchor.y + NODE_HEIGHT + VIEW_NODE_GAP + index * (VIEW_NODE_HEIGHT + VIEW_NODE_GAP),
    };
  }
  if (global.length > 0) {
    const bottoms = [
      ...Object.values(taskPositions).map((position) => position.y + NODE_HEIGHT),
      ...Object.values(result).map((position) => position.y + VIEW_NODE_HEIGHT),
    ];
    const laneTop = (bottoms.length === 0 ? 55 : Math.max(...bottoms)) + BAND_GAP;
    const perRow = Math.max(1, Math.floor(((availableWidth ?? PAD + VIEW_COL) - PAD) / VIEW_COL));
    global.forEach((id, index) => {
      result[id] = {
        x: PAD + (index % perRow) * VIEW_COL,
        y: laneTop + Math.floor(index / perRow) * (VIEW_NODE_HEIGHT + VIEW_NODE_GAP),
      };
    });
  }
  return result;
}
