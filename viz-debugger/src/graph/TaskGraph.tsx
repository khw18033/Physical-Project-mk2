import type { Hardware, Task, TaskStatus } from '../model/types.ts';
import { dagLayout, treeLayout } from './layout.ts';
import { STATE_STYLE } from './stateStyle.ts';

type Props = {
  tasks: Task[]; hardware: Hardware[]; states: Record<string, { status: TaskStatus; attempt: number }>;
  layoutMode: 'dag' | 'tree'; selected?: string; dimUnrelated?: boolean; onOpen(task: Task): void;
};

export function TaskGraph({ tasks, hardware, states, layoutMode, selected, dimUnrelated, onOpen }: Props) {
  const positions = layoutMode === 'dag' ? dagLayout(tasks) : treeLayout(tasks);
  const height = layoutMode === 'dag' ? 390 : 690;
  const relevant = new Set<string>();
  if (dimUnrelated && selected) {
    const visit = (id: string) => { if (relevant.has(id)) return; relevant.add(id); tasks.find((task) => task.id === id)?.deps.forEach(visit); };
    visit(selected);
  }
  return <div className="graph-canvas" style={{ height }}>
    <svg className="edges" viewBox={`0 0 1380 ${height}`} preserveAspectRatio="none">
      <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
      {tasks.flatMap((task) => task.deps.map((dep) => {
        const from = positions[dep]; const to = positions[task.id]; if (!from || !to) return null;
        const x1 = from.x + 180; const y1 = from.y + 55; const x2 = to.x; const y2 = to.y + 55; const mid = (x1 + x2) / 2;
        return <path key={`${dep}-${task.id}`} className={dimUnrelated && (!relevant.has(dep) || !relevant.has(task.id)) ? 'edge dimmed' : 'edge'} d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`} markerEnd="url(#arrow)" />;
      }))}
    </svg>
    {tasks.map((task) => {
      const state = states[task.id] ?? { status: 'pending' as const, attempt: 1 }; const style = STATE_STYLE[state.status];
      const device = hardware.find((item) => item.id === task.target); const dimmed = dimUnrelated && !relevant.has(task.id);
      const position = positions[task.id];
      return <button key={task.id} type="button" className={`task-node ${style.className} ${selected === task.id ? 'selected' : ''} ${dimmed ? 'dimmed' : ''}`} style={{ left: position.x, top: position.y }} onDoubleClick={() => onOpen(task)}>
        <small>{task.id}</small><strong>{task.title}</strong>
        <span className="state-label">{style.icon} {style.label}{state.status === 'rerunning' ? ` · attempt ${state.attempt}` : ''}</span>
        <span className={`device ${device?.connection ?? 'offline'}`}>{task.target} · {device?.connection === 'online' ? '온라인' : device?.connection === 'maintenance' ? '점검' : '오프라인'}</span>
      </button>;
    })}
  </div>;
}
