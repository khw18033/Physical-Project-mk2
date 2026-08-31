import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { scenario, statusesAt } from './data/scenario.ts';
import { TaskGraph } from './graph/TaskGraph.tsx';
import type { Task } from './model/types.ts';
import { PendingSource } from './shared/PendingSource.tsx';
import { hardwareSourceLabel, listRegisteredHardware } from './shared/registry.ts';
import { ActionModal } from './views/ActionModal.tsx';
import { UtterancePanel } from './views/UtterancePanel.tsx';
import { StatusLegend } from './views/StatusLegend.tsx';
import './style.css';

type Screen = 'milestones' | 'graph' | 'detail' | 'replay' | 'failure';

function timelineSegments(taskId: string) {
  const events = scenario.events.filter((event) => event.nodeId === taskId);
  const points = events[0]?.atSec === 0 ? events : [{ atSec: 0, status: 'pending' as const }, ...events];
  return points.map((point, index) => ({ status: point.status, start: point.atSec, end: points[index + 1]?.atSec ?? scenario.durationSec }));
}

function Milestones({ assignments, onAssign, onOpen, planApproval }: { assignments: Record<string, string[]>; onAssign(id: string, hardware: string): void; onOpen(): void; planApproval?: ReactNode }) {
  return <div className="milestone-layout"><UtterancePanel fallbackText={scenario.utterance.text} /><section className="milestone-panel"><h2>마일스톤 · 7건</h2><div className="milestone-list">{scenario.milestones.map((item) => <button key={item.id} className={`milestone state-${item.status}`} onClick={onOpen} onDragOver={(event) => event.preventDefault()} onDrop={(event) => onAssign(item.id, event.dataTransfer.getData('text/plain'))}><b>{item.id}</b><strong>{item.title}</strong><span>{(assignments[item.id] ?? item.assignedTargets).join(' · ') || '미배정'}</span><small>클릭 → 태스크 그래프</small></button>)}</div>{planApproval}</section><aside className="hardware-panel"><h2>하드웨어 · {listRegisteredHardware().length}대</h2><p>카드를 마일스톤으로 드래그 · 원천 {hardwareSourceLabel()}</p>{listRegisteredHardware().map((item) => <article key={item.id} draggable onDragStart={(event) => event.dataTransfer.setData('text/plain', item.id)}><b className={item.connection}>{item.id}</b><small>{item.kind}</small><span><PendingSource id="hardware-pool-status" inline>{item.connection} · {item.battery}% · {item.rssi} dBm</PendingSource></span></article>)}</aside></div>;
}

function ReplayControls({ second, onChange, tasks }: { second: number; onChange(value: number): void; tasks: Task[] }) {
  return <section className="replay-controls"><div><button onClick={() => onChange(0)}>◀◀</button><button onClick={() => onChange(Math.max(0, second - 1))}>◀</button><button onClick={() => onChange(Math.min(scenario.durationSec, second + 1))}>▶</button><b>{second}s / {scenario.durationSec}s</b></div><input aria-label="임무 재생 시각" type="range" min="0" max={scenario.durationSec} value={second} onChange={(event) => onChange(Number(event.target.value))} /><div className="timelines">{tasks.map((task) => <div key={task.id}><code>{task.id}</code><span className="timeline">{timelineSegments(task.id).map((segment, index) => <em key={`${segment.start}-${index}`} className={`state-${segment.status}`} style={{ width: `${(segment.end - segment.start) / scenario.durationSec * 100}%` }} />)}<i style={{ left: `${second / scenario.durationSec * 100}%` }} /></span></div>)}</div></section>;
}

function GraphScreen({ screen, tasks, layoutMode, onLayout, onOpen }: { screen: Screen; tasks: Task[]; layoutMode: 'dag' | 'tree'; onLayout(value: 'dag' | 'tree'): void; onOpen(task: Task, failed: boolean): void }) {
  const [second, setSecond] = useState(screen === 'replay' ? 41 : 95); const replay = screen === 'replay'; const failure = screen === 'failure';
  const states = useMemo(() => statusesAt(replay ? second : failure ? 95 : 41), [replay, failure, second]);
  return <div className={replay ? 'replay-layout' : ''}>{replay && <aside className="history"><h2>임무 이력</h2><PendingSource id="mission-history" minHeight={200}>{['MSN-260826-01 · 실패', 'MSN-260826-00 · 완료', 'MSN-260825-07 · 완료', 'MSN-260825-06 · 완료'].map((item) => <button key={item}>{item}</button>)}</PendingSource></aside>}<section className="graph-panel"><header className="section-title"><div><h2>마일스톤 C · 엘리베이터 탑승 → 5층 하차</h2><small>{replay ? `리플레이 · T+${String(second).padStart(2, '0')}s` : failure ? '실패 경로 강조 · 관련 없는 노드 흐림' : '분기와 합류가 있는 태스크 DAG'}</small></div><div className="toggle"><button className={layoutMode === 'dag' ? 'active' : ''} onClick={() => onLayout('dag')}>DAG</button><button className={layoutMode === 'tree' ? 'active' : ''} onClick={() => onLayout('tree')}>트리</button></div></header><TaskGraph tasks={tasks} hardware={listRegisteredHardware()} states={states} layoutMode={layoutMode} selected={failure ? 'T-35' : undefined} dimUnrelated={failure} onOpen={(task) => onOpen(task, states[task.id]?.status === 'failed')} />{replay && <ReplayControls second={second} onChange={setSecond} tasks={tasks} />}<StatusLegend /><p className="hint">노드를 더블클릭하면 액션 아이템 상세를 엽니다. 실패 상태 노드는 수정 화면으로 이어집니다.</p></section></div>;
}

export type DebuggerNavigation = { screen: 'milestones' | 'replay'; requestId: number };

/**
 * `planApproval` — VZ-U-07 승인·거부 패널. **통합 셸이 프롭으로 넣는다.**
 *
 * 여기서 직접 import 하지 않는 이유: 그 패널은 `tabs/data/` 의 스토어를 보는데,
 * 탭① 단독 빌드가 그걸 끌어오면 대시보드 데이터 계층이 통째로 딸려 들어와
 * 논문 측정축 D(계측 오버헤드)가 오염된다. 단독 빌드는 이 프롭을 주지 않는다.
 */

export function MissionDebugger({ navigation, planApproval }: { navigation?: DebuggerNavigation; planApproval?: ReactNode }) {
  const [screen, setScreen] = useState<Screen>('milestones'); const [layoutMode, setLayoutMode] = useState<'dag' | 'tree'>('dag'); const [modalTask, setModalTask] = useState<Task | null>(null); const [assignments, setAssignments] = useState<Record<string, string[]>>({});
  const assignedTasks = useMemo(() => scenario.tasks.map((task) => assignments['MS-C']?.length ? { ...task, target: assignments['MS-C'][0] } : task), [assignments]);
  const navigate = (next: Screen) => { setScreen(next); setModalTask(next === 'detail' ? assignedTasks[0] : next === 'failure' ? assignedTasks.find((task) => task.id === 'T-35') ?? null : null); };
  const openTask = (task: Task, failed: boolean) => { setModalTask(task); setScreen(failed ? 'failure' : 'detail'); };
  useEffect(() => { if (navigation) navigate(navigation.screen); }, [navigation?.requestId]);
  return <div className="mission-debugger">{screen === 'milestones' ? <Milestones assignments={assignments} onAssign={(id, hardware) => setAssignments((current) => ({ ...current, [id]: [...new Set([...(current[id] ?? []), hardware])] }))} onOpen={() => navigate('graph')} planApproval={planApproval} /> : <GraphScreen screen={screen} tasks={assignedTasks} layoutMode={layoutMode} onLayout={setLayoutMode} onOpen={openTask} />}{modalTask && <ActionModal task={modalTask} device={listRegisteredHardware().find((item) => item.id === modalTask.target)} failure={screen === 'failure'} onClose={() => { setModalTask(null); if (screen === 'detail') setScreen('graph'); }} />}{screen === 'failure' && !modalTask && <button className="failure-open" onClick={() => setModalTask(assignedTasks.find((task) => task.id === 'T-35')!)}>실패 수정 팝업 열기</button>}</div>;
}
