import type { Task } from '../model/types.ts';
export type Position = { x: number; y: number };

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

export function dagLayout(tasks: Task[]): Record<string, Position> {
  const depth = depths(tasks); const columns = new Map<number, Task[]>();
  for (const task of tasks) columns.set(depth[task.id], [...(columns.get(depth[task.id]) ?? []), task]);
  return Object.fromEntries([...columns].flatMap(([column, nodes]) => nodes.map((task, row) => [task.id, { x: 30 + column * 220, y: 55 + row * 150 }]))) as Record<string, Position>;
}

export function treeLayout(tasks: Task[]): Record<string, Position> {
  const depth = depths(tasks);
  return Object.fromEntries(tasks.map((task, index) => [task.id, { x: 30 + depth[task.id] * 220, y: 25 + index * 92 }])) as Record<string, Position>;
}
