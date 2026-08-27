import { useEffect, useMemo, useState, type PointerEvent as ReactPointerEvent } from 'react';
import type { Hardware, Task, TaskStatus } from '../model/types.ts';
import { dagLayout, treeLayout } from './layout.ts';
import { STATE_STYLE } from './stateStyle.ts';

type Props = {
  tasks: Task[]; hardware: Hardware[]; states: Record<string, { status: TaskStatus; attempt: number }>;
  layoutMode: 'dag' | 'tree'; selected?: string; dimUnrelated?: boolean; onOpen(task: Task): void;
};

const NODE_WIDTH = 180; const NODE_HEIGHT = 110;
function connectionPath(from: { x: number; y: number }, to: { x: number; y: number }) {
  const dx = to.x - from.x; const dy = to.y - from.y;
  if (Math.abs(dx) >= NODE_WIDTH + 20) {
    const forward = dx > 0; const x1 = from.x + (forward ? NODE_WIDTH : 0); const x2 = to.x + (forward ? 0 : NODE_WIDTH);
    const y1 = from.y + NODE_HEIGHT / 2; const y2 = to.y + NODE_HEIGHT / 2; const middle = (x1 + x2) / 2;
    return `M${x1},${y1} C${middle},${y1} ${middle},${y2} ${x2},${y2}`;
  }
  const downward = dy >= 0; const x1 = from.x + NODE_WIDTH / 2; const x2 = to.x + NODE_WIDTH / 2;
  const y1 = from.y + (downward ? NODE_HEIGHT : 0); const y2 = to.y + (downward ? 0 : NODE_HEIGHT); const middle = (y1 + y2) / 2;
  return `M${x1},${y1} C${x1},${middle} ${x2},${middle} ${x2},${y2}`;
}

export function TaskGraph({ tasks, hardware, states, layoutMode, selected, dimUnrelated, onOpen }: Props) {
  const basePositions = useMemo(() => layoutMode === 'dag' ? dagLayout(tasks) : treeLayout(tasks), [layoutMode, tasks]);
  const [movedPositions, setMovedPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [drag, setDrag] = useState<{ id: string; offsetX: number; offsetY: number } | null>(null);
  useEffect(() => setMovedPositions({}), [layoutMode]);
  const positions = useMemo(() => Object.fromEntries(tasks.map((task) => [task.id, movedPositions[task.id] ?? basePositions[task.id]])), [basePositions, movedPositions, tasks]);
  const height = layoutMode === 'dag' ? 390 : 690;
  const width = Math.max(1380, ...Object.values(positions).map((position) => position.x + 220));
  const relevant = new Set<string>();
  if (dimUnrelated && selected) {
    const visit = (id: string) => { if (relevant.has(id)) return; relevant.add(id); tasks.find((task) => task.id === id)?.deps.forEach(visit); };
    visit(selected);
  }
  const startDrag = (event: ReactPointerEvent<HTMLButtonElement>, id: string) => {
    const canvas = event.currentTarget.parentElement; const position = positions[id]; if (!canvas || !position) return;
    const rect = canvas.getBoundingClientRect(); event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ id, offsetX: event.clientX - rect.left + canvas.scrollLeft - position.x, offsetY: event.clientY - rect.top + canvas.scrollTop - position.y });
  };
  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag) return; const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(width - NODE_WIDTH, event.clientX - rect.left + event.currentTarget.scrollLeft - drag.offsetX));
    const y = Math.max(0, Math.min(height - NODE_HEIGHT, event.clientY - rect.top + event.currentTarget.scrollTop - drag.offsetY));
    setMovedPositions((current) => ({ ...current, [drag.id]: { x, y } }));
  };
  return <div className={`graph-canvas ${drag ? 'is-dragging' : ''}`} style={{ height, width }} onPointerMove={moveDrag} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}>
    <svg className="edges" width={width} height={height} aria-hidden="true">
      <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
      {tasks.flatMap((task) => task.deps.map((dep) => {
        const from = positions[dep]; const to = positions[task.id]; if (!from || !to) return null;
        return <path key={`${dep}-${task.id}`} className={dimUnrelated && (!relevant.has(dep) || !relevant.has(task.id)) ? 'edge dimmed' : 'edge'} d={connectionPath(from, to)} markerEnd="url(#arrow)" />;
      }))}
    </svg>
    {tasks.map((task) => {
      const state = states[task.id] ?? { status: 'pending' as const, attempt: 1 }; const style = STATE_STYLE[state.status];
      const device = hardware.find((item) => item.id === task.target); const dimmed = dimUnrelated && !relevant.has(task.id);
      const position = positions[task.id];
      return <button key={task.id} type="button" className={`task-node ${style.className} ${selected === task.id ? 'selected' : ''} ${dimmed ? 'dimmed' : ''}`} style={{ left: position.x, top: position.y }} onPointerDown={(event) => startDrag(event, task.id)} onDoubleClick={() => onOpen(task)}>
        <small>{task.id}</small><strong>{task.title}</strong>
        <span className="state-label">{style.icon} {style.label}{state.status === 'rerunning' ? ` · attempt ${state.attempt}` : ''}</span>
        <span className={`device ${device?.connection ?? 'offline'}`}>{task.target} · {device?.connection === 'online' ? '온라인' : device?.connection === 'maintenance' ? '점검' : '오프라인'}</span>
      </button>;
    })}
  </div>;
}
