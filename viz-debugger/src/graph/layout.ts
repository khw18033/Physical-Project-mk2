import type { Task } from '../model/types.ts';
export type Position = { x: number; y: number };

function depths(tasks: Task[]) {
  const result: Record<string, number> = {};
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const visit = (id: string): number => result[id] ?? (result[id] = Math.max(0, ...((byId.get(id)?.deps ?? []).map((dep) => visit(dep) + 1))));
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
