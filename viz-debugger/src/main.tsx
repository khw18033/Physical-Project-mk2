import { StrictMode, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { scenario, statusesAt } from './data/scenario.ts';
import { TaskGraph } from './graph/TaskGraph.tsx';
import type { Task } from './model/types.ts';
import { ActionModal } from './views/ActionModal.tsx';
import { StatusLegend } from './views/StatusLegend.tsx';
import { TopBar } from './views/TopBar.tsx';
import './style.css';

type Screen = 'milestones' | 'graph' | 'detail' | 'replay' | 'failure';

function timelineSegments(taskId: string) {
  const events = scenario.events.filter((event) => event.nodeId === taskId);
  const points = events[0]?.atSec === 0 ? events : [{ atSec: 0, status: 'pending' as const }, ...events];
  return points.map((point, index) => ({ status: point.status, start: point.atSec, end: points[index + 1]?.atSec ?? scenario.durationSec }));
}

function Milestones({ assignments, onAssign, onOpen }: { assignments: Record<string, string[]>; onAssign(id: string, hardware: string): void; onOpen(): void }) {
  return <div className="milestone-layout"><aside className="utterance-panel"><h2>발화 · Utterance</h2><div className="waveform">▂▅▃▆▂▇▅▃▆▂▅▇▃▆</div><blockquote>“{scenario.utterance.text}”</blockquote><dl><dt>엔진</dt><dd>{scenario.utterance.engine}</dd><dt>신뢰도</dt><dd>{scenario.utterance.confidence}</dd><dt>생성 주체</dt><dd>produced_by=ai</dd></dl></aside><section className="milestone-panel"><h2>마일스톤 · 7건</h2><div className="progress-steps">{['음성 수신', 'STT 변환', '의도 분석', '마일스톤 분리', '태스크 생성'].map((label) => <span key={label}>✓ {label}</span>)}</div><div className="milestone-list">{scenario.milestones.map((item) => <button key={item.id} className={`milestone state-${item.status}`} onClick={onOpen} onDragOver={(event) => event.preventDefault()} onDrop={(event) => onAssign(item.id, event.dataTransfer.getData('text/plain'))}><b>{item.id}</b><strong>{item.title}</strong><span>{(assignments[item.id] ?? item.assignedTargets).join(' · ') || '미배정'}</span><small>클릭 → 태스크 그래프</small></button>)}</div></section><aside className="hardware-panel"><h2>하드웨어 · 7대</h2><p>카드를 마일스톤으로 드래그</p>{scenario.hardware.map((item) => <article key={item.id} draggable onDragStart={(event) => event.dataTransfer.setData('text/plain', item.id)}><b className={item.connection}>{item.id}</b><small>{item.kind}</small><span>{item.connection} · {item.battery}% · {item.rssi} dBm</span></article>)}</aside></div>;
}

function ReplayControls({ second, onChange, tasks }: { second: number; onChange(value: number): void; tasks: Task[] }) {
  return <section className="replay-controls"><div><button onClick={() => onChange(0)}>◀◀</button><button onClick={() => onChange(Math.max(0, second - 1))}>◀</button><button onClick={() => onChange(Math.min(scenario.durationSec, second + 1))}>▶</button><b>{second}s / {scenario.durationSec}s</b></div><input aria-label="임무 재생 시각" type="range" min="0" max={scenario.durationSec} value={second} onChange={(event) => onChange(Number(event.target.value))} /><div className="timelines">{tasks.map((task) => <div key={task.id}><code>{task.id}</code><span className="timeline">{timelineSegments(task.id).map((segment, index) => <em key={`${segment.start}-${index}`} className={`state-${segment.status}`} style={{ width: `${(segment.end - segment.start) / scenario.durationSec * 100}%` }} />)}<i style={{ left: `${second / scenario.durationSec * 100}%` }} /></span></div>)}</div></section>;
}

function GraphScreen({ screen, tasks, layoutMode, onLayout, onOpen }: { screen: Screen; tasks: Task[]; layoutMode: 'dag' | 'tree'; onLayout(value: 'dag' | 'tree'): void; onOpen(task: Task): void }) {
  const [second, setSecond] = useState(screen === 'replay' ? 41 : 95); const replay = screen === 'replay'; const failure = screen === 'failure';
  const states = useMemo(() => statusesAt(replay ? second : failure ? 95 : 41), [replay, failure, second]);
  return <div className={replay ? 'replay-layout' : ''}>{replay && <aside className="history"><h2>임무 이력</h2>{['MSN-260826-01 · 실패', 'MSN-260826-00 · 완료', 'MSN-260825-07 · 완료', 'MSN-260825-06 · 완료'].map((item) => <button key={item}>{item}</button>)}</aside>}<section className="graph-panel"><header className="section-title"><div><h2>마일스톤 C · 엘리베이터 탑승 → 5층 하차</h2><small>{replay ? `리플레이 · T+${String(second).padStart(2, '0')}s` : failure ? '실패 경로 강조 · 관련 없는 노드 흐림' : '분기와 합류가 있는 태스크 DAG'}</small></div><div className="toggle"><button className={layoutMode === 'dag' ? 'active' : ''} onClick={() => onLayout('dag')}>DAG</button><button className={layoutMode === 'tree' ? 'active' : ''} onClick={() => onLayout('tree')}>트리</button></div></header><TaskGraph tasks={tasks} hardware={scenario.hardware} states={states} layoutMode={layoutMode} selected={failure ? 'T-35' : undefined} dimUnrelated={failure} onOpen={onOpen} />{replay && <ReplayControls second={second} onChange={setSecond} tasks={tasks} />}<StatusLegend /><p className="hint">노드를 더블클릭하면 액션 아이템 상세를 엽니다.</p></section></div>;
}

function App() {
  const [screen, setScreen] = useState<Screen>('milestones'); const [layoutMode, setLayoutMode] = useState<'dag' | 'tree'>('dag'); const [modalTask, setModalTask] = useState<Task | null>(null); const [assignments, setAssignments] = useState<Record<string, string[]>>({});
  const assignedTasks = useMemo(() => scenario.tasks.map((task) => assignments['MS-C']?.length ? { ...task, target: assignments['MS-C'][0] } : task), [assignments]);
  const navigate = (next: Screen) => { setScreen(next); setModalTask(next === 'detail' ? assignedTasks[0] : next === 'failure' ? assignedTasks.find((task) => task.id === 'T-35') ?? null : null); };
  const openTask = (task: Task) => { setModalTask(task); if (screen !== 'failure') setScreen('detail'); };
  return <main><TopBar onReplay={() => navigate('replay')} /><nav className="screen-nav">{([['milestones', 'D-01 마일스톤'], ['graph', 'D-02 그래프'], ['detail', 'D-03 상세'], ['replay', 'D-04 리플레이'], ['failure', 'D-05 실패 수정']] as const).map(([id, label]) => <button className={screen === id ? 'active' : ''} key={id} onClick={() => navigate(id)}>{label}</button>)}</nav>{screen === 'milestones' ? <Milestones assignments={assignments} onAssign={(id, hardware) => setAssignments((current) => ({ ...current, [id]: [...new Set([...(current[id] ?? []), hardware])] }))} onOpen={() => navigate('graph')} /> : <GraphScreen screen={screen} tasks={assignedTasks} layoutMode={layoutMode} onLayout={setLayoutMode} onOpen={openTask} />}{modalTask && <ActionModal task={modalTask} device={scenario.hardware.find((item) => item.id === modalTask.target)} failure={screen === 'failure'} onClose={() => { setModalTask(null); if (screen === 'detail') setScreen('graph'); }} />}{screen === 'failure' && !modalTask && <button className="failure-open" onClick={() => setModalTask(assignedTasks.find((task) => task.id === 'T-35')!)}>실패 수정 팝업 열기</button>}</main>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
