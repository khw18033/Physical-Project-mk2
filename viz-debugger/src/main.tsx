import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  activateMission,
  displayMission,
  rejectProposal,
  statusesAt,
  useMission,
  type MissionMilestone,
  type MissionView,
} from './data/scenario.ts';
import { TaskGraph, type CanvasLayer } from './graph/TaskGraph.tsx';
import { Palette } from './canvas/Palette.tsx';
import { ZoomOverlay } from './canvas/ZoomOverlay.tsx';
import { viewNodeEntry } from './canvas/registry.ts';
import { viewScopeFor } from './canvas/scope.ts';
import { MISSION_SLOT } from './canvas/persist.ts';
import { useCanvas } from './canvas/useCanvas.ts';
import type { Task, TaskStatus } from './model/types.ts';
import { PendingSource } from './shared/PendingSource.tsx';
import { hardwareSourceLabel, listCastIds, listRegisteredHardware } from './shared/registry.ts';
import { ActionModal } from './views/ActionModal.tsx';
import { UtterancePanel } from './views/UtterancePanel.tsx';
import { StatusLegend } from './views/StatusLegend.tsx';
import './style.css';
import { Explain } from './shared/Explain.tsx';

type Screen = 'milestones' | 'graph' | 'detail' | 'replay' | 'failure';

/**
 * 한 편(MSN-260826-01)에 맞춰 손으로 적혀 있던 값들 — 되감기 시각(41·95) · 마일스톤 수(7건) ·
 * 배정 대상(MS-C) · 실패 태스크(T-35) — 은 전부 현재 임무 저장소에서 파생한다 (260831).
 * 화면 구조는 HCI 전달본 그대로다.
 */

function timelineSegments(view: MissionView, taskId: string) {
  const events = view.events.filter((event) => event.nodeId === taskId);
  const points = events[0]?.atSec === 0 ? events : [{ atSec: 0, status: 'pending' as const }, ...events];
  return points.map((point, index) => ({ status: point.status, start: point.atSec, end: points[index + 1]?.atSec ?? view.durationSec }));
}

function Milestones({ view, phase, milestoneStatuses, assignments, onAssign, onOpen, planApproval }: {
  view: MissionView;
  phase: 'proposal' | 'playing' | 'idle';
  milestoneStatuses: Record<string, TaskStatus>;
  assignments: Record<string, string[]>;
  onAssign(id: string, hardware: string): void;
  onOpen(id: string): void;
  planApproval?: ReactNode;
}) {
  const hardware = listRegisteredHardware();
  const cast = listCastIds();
  const mission = useMission();
  // 승인·거부는 **마일스톤 목록 위 제안 카드 안**에 있다 (260901). 통합 빌드는 이 슬롯에
  // PlanApproval(근거 4층 + 승인·거부)이 들어오고, 단독 빌드는 로컬 재생기용 폴백이 들어온다 —
  // **같은 자리**다. 근거의 「구간별 계획」이 「아래 마일스톤과 같음」이라고 적으므로
  // 카드는 목록보다 위에 있어야 한다.
  const approvalSlot = planApproval ?? (mission.proposal !== null && <div className="proposal-fallback">
    {/* 단독 빌드(게이트웨이 없음)의 승인 자리 — 통합 앱에서는 PlanApproval(VZ-U-07)이 들어온다. */}
    <p>대본 제안 <code>{mission.proposal.missionId}</code> — 승인해야 재생이 시작됩니다 (VZ-U-07 · 로컬 재생기)</p>
    <button onClick={() => activateMission(mission.proposal!.missionId, 'local')}>승인 — 재생 시작</button>
    <button onClick={() => rejectProposal()}>거부</button>
  </div>);
  const showApproval = phase === 'proposal' || planApproval !== undefined;
  return <div className="milestone-layout"><UtterancePanel fallbackText={view.utteranceText} /><section className="milestone-panel"><h2>마일스톤 · {view.milestones.length}건</h2>
    {showApproval && <div className="proposal-card">
      {phase === 'proposal' && <p className="proposal-note"><b>제안 상태</b> — 대본 {view.missionId} 「{view.label}」. 승인 전에는 아무것도 재생되지 않습니다{mission.proposal?.keywords.length ? <small>맞은 키워드: {mission.proposal.keywords.join(' · ')}</small> : null}</p>}
      {approvalSlot}
    </div>}
    <div className="milestone-list">{view.milestones.map((item) => <button key={item.id} className={`milestone state-${milestoneStatuses[item.id] ?? 'pending'}`} onClick={() => onOpen(item.id)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => onAssign(item.id, event.dataTransfer.getData('text/plain'))}><b>{item.id}</b><strong>{item.title}</strong><span>{(assignments[item.id] ?? item.assignedTargets).join(' · ') || '미배정'}</span><small>클릭 → 태스크 그래프</small></button>)}</div></section>
    <aside className="hardware-panel"><h2>하드웨어 · {view.hardware ? hardware.length : cast.length}대</h2><p>카드를 마일스톤으로 드래그 · 원천 {hardwareSourceLabel()}</p>
    {view.hardware
      ? hardware.map((item) => <article key={item.id} draggable onDragStart={(event) => event.dataTransfer.setData('text/plain', item.id)}><b className={item.connection}>{item.id}</b><small>{item.kind}</small><span><PendingSource id="hardware-pool-status" inline>{item.connection} · {item.battery}% · {item.rssi} dBm</PendingSource></span></article>)
      // 대본(registry 세계) — 등장 장비는 id 만 대본에서 읽는다. 실측 3행은 여전히 자리표시다
      // (VZ-D-07 · 8/31 결정 — registry 장비의 실측값은 남이 줄 데이터라 지어내지 않는다).
      : cast.map((id) => <article key={id} draggable onDragStart={(event) => event.dataTransfer.setData('text/plain', id)}><b>{id}</b><small>대본 등장 장비</small><span><PendingSource id="hardware-pool-status" inline>상태 3행 — 연결 예정</PendingSource></span></article>)}</aside></div>;
}

function ReplayControls({ second, following, playing, onChange, onFollow, view, tasks }: {
  second: number; following: boolean; playing: boolean;
  onChange(value: number): void; onFollow(): void; view: MissionView; tasks: Task[];
}) {
  const shown = Math.min(view.durationSec, Math.round(second));
  return <section className="replay-controls"><div><button onClick={() => onChange(0)}>◀◀</button><button onClick={() => onChange(Math.max(0, shown - 1))}>◀</button><button onClick={() => onChange(Math.min(view.durationSec, shown + 1))}>▶</button><b>{shown}s / {view.durationSec}s</b>
    {/* 재생 중에는 머리를 따라가고, 뒤로 끌면 그 시점을 그린다. 재생이 끝나면 그냥 되감기 도구다. */}
    {playing && (following
      ? <b className="follow-live">● 따라가는 중</b>
      : <button className="follow-live" onClick={onFollow}>▶ 따라가기 (live)</button>)}
  </div><input aria-label="임무 재생 시각" type="range" min="0" max={view.durationSec} value={shown} onChange={(event) => onChange(Number(event.target.value))} /><div className="timelines">{tasks.map((task) => <div key={task.id}><code>{task.id}</code><span className="timeline">{timelineSegments(view, task.id).map((segment, index) => <em key={`${segment.start}-${index}`} className={`state-${segment.status}`} style={{ width: `${(segment.end - segment.start) / view.durationSec * 100}%` }} />)}<i style={{ left: `${shown / view.durationSec * 100}%` }} /></span></div>)}</div></section>;
}

/**
 * 노드 분화(260831) 이후 그래프의 **보기 범위.**
 * 분기·합류는 대부분 마일스톤을 건넌다 — 1편의 합류(T-15a ← MS-D 셋)도, 2편의
 * 되돌아감(MS-F → MS-C)도. 그래서 「임무 전체」 보기를 둔다. 기본은 여전히 마일스톤이다 —
 * HCI 전달본의 화면 흐름(마일스톤 클릭 → 그 마일스톤의 그래프)을 지킨다.
 */
export type GraphScope = 'milestone' | 'mission';

function GraphScreen({ screen, view, milestone, tasks, headSec, playing, layoutMode, onLayout, scope, onScope, refEdges, crossing, onOpen, onBack, onGraph, openTask }: {
  screen: Screen; view: MissionView; milestone: MissionMilestone | null; tasks: Task[];
  headSec: number; playing: boolean;
  layoutMode: 'dag' | 'tree'; onLayout(value: 'dag' | 'tree'): void;
  scope: GraphScope; onScope(value: GraphScope): void;
  refEdges: MissionView['refEdges']; crossing: MissionView['refEdges'];
  onOpen(task: Task, failed: boolean): void;
  /** 이동 경로의 「마일스톤」 칸 (260901). 되돌아갈 길이 화면에 없으면 없는 길이다. */
  onBack(): void;
  /** 가운데 칸 — 지금 보고 있는 그래프로. 액션 팝업이 열려 있으면 닫힌다. */
  onGraph(): void;
  /** 마지막 칸은 액션 아이템 팝업이 열려 있을 때만 나온다. */
  openTask: Task | null;
}) {
  const replay = screen === 'replay'; const failure = screen === 'failure';
  /** 되감기 위치. null 이면 재생 머리를 따라간다(live). */
  const [override, setOverride] = useState<number | null>(null);
  useEffect(() => setOverride(null), [view.missionId, screen]);
  const second = replay ? (override ?? headSec) : headSec;
  /**
   * 노드 캔버스 (260903 — 1단계). **슬롯은 지금 보고 있는 범위**다 — 마일스톤 하나면 그
   * 마일스톤, 「임무 전체」면 별도 슬롯(`__mission__`). 마일스톤별 저장만으로는 임무 전체
   * 보기의 구성이 미아가 된다 (`VZ-N-04`).
   */
  const slot = scope === 'mission' ? MISSION_SLOT : milestone?.id ?? MISSION_SLOT;
  const canvas = useCanvas(view.missionId, slot, tasks);
  /** 팔레트가 뷰 노드를 붙일 태스크. 범위가 바뀌면 고르기를 푼다. */
  const [pickedTaskId, setPickedTaskId] = useState<string | null>(null);
  useEffect(() => setPickedTaskId(null), [slot, view.missionId]);
  const picked = tasks.find((task) => task.id === pickedTaskId) ?? null;
  /**
   * 확대된 뷰 노드 (260903 2단계 · `VZ-N-05`). **`activeTab` 류가 아니다** — 「몇 번째 탭」이
   * 아니라 「어느 노드」이고, 문자열 하나라 한 번에 하나만 열린다(지시서 §6).
   * 범위를 옮기면(다른 마일스톤·임무) 그 노드가 화면에 없으므로 함께 닫는다.
   */
  const [zoomedId, setZoomedId] = useState<string | null>(null);
  useEffect(() => setZoomedId(null), [slot, view.missionId]);
  const zoomedNode = canvas.nodes.find((node) => node.id === zoomedId) ?? null;
  const zoomedEntry = zoomedNode === null ? null : viewNodeEntry(zoomedNode.kind);
  const canvasLayer = useMemo<CanvasLayer>(() => ({
    nodes: canvas.nodes,
    entryOf: viewNodeEntry,
    // **재생 머리는 캔버스 전체가 같은 값을 쓴다** (`VZ-N-03`) — 되감기 중이면 그 시각이다.
    scopeOf: (taskId) => viewScopeFor(taskId, view, second),
    pickedTaskId: picked?.id ?? null,
    onPick: setPickedTaskId,
    onMove: canvas.move,
    onBind: canvas.bind,
    onRemove: canvas.remove,
    zoomedId,
    onZoom: setZoomedId,
  }), [canvas.bind, canvas.move, canvas.nodes, canvas.remove, picked, second, view, zoomedId]);
  const folded = useMemo(() => statusesAt(second, view), [second, view]);
  const failedTask = tasks.find((task) => folded.tasks[task.id]?.status === 'failed') ?? null;
  const title = scope === 'mission'
    ? `${view.label} · 임무 전체 ${tasks.length}노드`
    : milestone === null ? view.label : `마일스톤 ${milestone.id.replace(/^MS-/, '')} · ${milestone.title}`;
  /**
   * 이동 경로 (260901 — 후속 3건 요구 1).
   *
   * 탭①의 이동은 마일스톤 → 그래프 → 액션 아이템 한 방향뿐이었다. 그래프에서 마일스톤으로
   * 돌아가는 길은 상단 공통 바의 임무 이름 버튼 하나였는데 그게 「마일스톤으로 돌아가기」라는
   * 것을 화면 어디에도 적어 두지 않았다 — **발견할 수 없는 길은 없는 길이다.**
   *
   * 되감기·실패 화면(replay·failure)도 이 컴포넌트라 같이 풀린다. 그 둘도 똑같이 갇혀 있었다.
   */
  const here = scope === 'mission' ? `임무 전체 ${tasks.length}노드` : milestone === null ? view.label : `${milestone.id} ${milestone.title}`;
  const crumbs = <nav className="crumbs" aria-label="이동 경로">
    {/* 항상 있고 항상 눌린다. 사용자가 요구한 되돌아가기가 이것이다. */}
    <button type="button" className="crumbs__link" onClick={onBack}>마일스톤</button>
    <span className="crumbs__sep" aria-hidden="true">›</span>
    {openTask === null
      ? <span className="crumbs__here">{here}</span>
      : <button type="button" className="crumbs__link" onClick={onGraph}>{here}</button>}
    {openTask !== null && <><span className="crumbs__sep" aria-hidden="true">›</span><span className="crumbs__here">{openTask.id} {openTask.title}</span></>}
  </nav>;
  return <div className={replay ? 'replay-layout' : ''}>{replay && <aside className="history"><h2>임무 이력</h2><PendingSource id="mission-history" minHeight={200}>{['MSN-260826-01 · 실패', 'MSN-260826-00 · 완료', 'MSN-260825-07 · 완료', 'MSN-260825-06 · 완료'].map((item) => <button key={item}>{item}</button>)}</PendingSource></aside>}<section className="graph-panel"><header className="section-title"><div>{crumbs}<h2>{title}</h2><small>{replay ? `리플레이 · T+${String(Math.round(second)).padStart(2, '0')}s` : failure ? (failedTask ? '실패 경로 강조 · 관련 없는 노드 흐림' : '이 대본에는 실패가 없습니다 — 결함 주입(REQ-1409)으로 만들 수 있습니다') : '분기와 합류가 있는 태스크 DAG'}</small></div><div className="toggle"><button className={layoutMode === 'dag' ? 'active' : ''} onClick={() => onLayout('dag')}>DAG</button><button className={layoutMode === 'tree' ? 'active' : ''} onClick={() => onLayout('tree')}>트리</button></div><div className="toggle"><button className={scope === 'milestone' ? 'active' : ''} onClick={() => onScope('milestone')}>이 마일스톤</button><button className={scope === 'mission' ? 'active' : ''} onClick={() => onScope('mission')}>임무 전체</button></div></header><Palette canvas={canvas} pickedTaskId={picked?.id ?? null} pickedTaskTitle={picked?.title ?? null} /><TaskGraph tasks={tasks} hardware={listRegisteredHardware()} states={folded.tasks} layoutMode={layoutMode} selected={failure ? failedTask?.id : undefined} dimUnrelated={failure && failedTask !== null} refEdges={refEdges} onOpen={(task) => onOpen(task, folded.tasks[task.id]?.status === 'failed')} canvas={canvasLayer} />
    {/* 마일스톤 밖으로 나가는 되돌아감 — 적지 않으면 사용자는 루프의 존재를 모른다 (결정 2). */}
    {crossing.length > 0 && <p className="ref-crossing">↺ {crossing.map((edge) => `${edge.from} → ${edge.to} (${edge.label})`).join(' · ')} — 이 마일스톤 밖으로 되돌아갑니다 <button onClick={() => onScope('mission')}>임무 전체로 보기</button></p>}
    {replay && <ReplayControls second={second} following={override === null} playing={playing} onChange={setOverride} onFollow={() => setOverride(null)} view={view} tasks={tasks} />}<StatusLegend /><Explain id="dbg-1" className="hint">노드를 더블클릭하면 액션 아이템 상세를 엽니다. 실패 상태 노드는 수정 화면으로 이어집니다. 뷰 노드를 더블클릭하면 그 자리에서 확대됩니다 — 캔버스는 뒤에 그대로 있습니다.</Explain></section>
    {/* 확대 오버레이 (260903 2단계). **TaskGraph 의 형제**다 — 위에서 캔버스를 조건 없이
        그리고 여기에 얹기만 하므로, 확대해도 캔버스가 교체되지 않고 닫으면 같은 자리다. */}
    {zoomedNode !== null && zoomedEntry !== null && <ZoomOverlay entry={zoomedEntry} scope={viewScopeFor(zoomedNode.taskId, view, second)} taskId={zoomedNode.taskId} onClose={() => setZoomedId(null)} />}</div>;
}

export type DebuggerNavigation = { screen: 'milestones' | 'replay'; requestId: number };

/**
 * `planApproval` — VZ-U-07 승인·거부 패널. **통합 셸이 프롭으로 넣는다.**
 *
 * 자리는 마일스톤 목록 **위**의 제안 카드다 (260901). 단독 빌드는 이 프롭을 받지 않고
 * 같은 자리에 로컬 승인 폴백을 그린다 — 통합·단독이 같은 슬롯을 쓴다.
 *
 * 여기서 직접 import 하지 않는 이유: 그 패널은 `tabs/data/` 의 스토어를 보는데,
 * 탭① 단독 빌드가 그걸 끌어오면 대시보드 데이터 계층이 통째로 딸려 들어와
 * 논문 측정축 D(계측 오버헤드)가 오염된다. 단독 빌드는 이 프롭을 주지 않고,
 * 그때는 제안에 로컬 승인 자리가 뜬다(위 Milestones 의 proposal-fallback).
 */

export function MissionDebugger({ navigation, planApproval }: { navigation?: DebuggerNavigation; planApproval?: ReactNode }) {
  useMission(); // 저장소 변화(제안·승인·재생 머리)에 다시 그린다.
  const display = displayMission();
  const view = display.view;

  const [screen, setScreen] = useState<Screen>('milestones');
  const [layoutMode, setLayoutMode] = useState<'dag' | 'tree'>('dag');
  const [scope, setScope] = useState<GraphScope>('milestone');
  const [modalTask, setModalTask] = useState<Task | null>(null);
  const [assignments, setAssignments] = useState<Record<string, string[]>>({});
  const [milestoneId, setMilestoneId] = useState<string | null>(null);

  // 임무가 바뀌면(대본 승인) 한 편에 묶였던 화면 상태를 처음으로 되돌린다.
  useEffect(() => { setScreen('milestones'); setModalTask(null); setAssignments({}); setMilestoneId(null); setScope('milestone'); }, [view.missionId]);

  // 그래프에 들어갈 마일스톤 — 클릭한 것. 태스크가 없으면(옛 파일의 MS-A 등)
  // 태스크를 가진 마일스톤으로 간다(옛 편은 전부 MS-C라 기존 화면 그대로다).
  const graphMilestone = useMemo(() => {
    const hasTasks = (id: string) => view.tasks.some((task) => task.milestone === id);
    if (milestoneId !== null && hasTasks(milestoneId)) return view.milestones.find((m) => m.id === milestoneId) ?? null;
    return view.milestones.find((m) => hasTasks(m.id)) ?? view.milestones[0] ?? null;
  }, [milestoneId, view]);

  const graphTasks = useMemo(
    () => view.tasks
      .filter((task) => scope === 'mission' || task.milestone === graphMilestone?.id)
      .map((task) => assignments[task.milestone ?? '']?.length ? { ...task, target: assignments[task.milestone ?? ''][0] } : task),
    [assignments, graphMilestone, scope, view],
  );

  // 참조 엣지 — 보이는 범위 안에 양끝이 다 있으면 그리고, 밖으로 나가면 한 줄로 적는다.
  const graphTaskIds = useMemo(() => new Set(graphTasks.map((task) => task.id)), [graphTasks]);
  const visibleRefEdges = useMemo(
    () => view.refEdges.filter((edge) => graphTaskIds.has(edge.from) && graphTaskIds.has(edge.to)),
    [graphTaskIds, view],
  );
  const crossingRefEdges = useMemo(
    () => view.refEdges.filter((edge) => graphTaskIds.has(edge.from) !== graphTaskIds.has(edge.to)),
    [graphTaskIds, view],
  );

  const milestoneStatuses = useMemo(() => statusesAt(display.headSec, view).milestones, [display.headSec, view]);

  const navigate = (next: Screen) => {
    setScreen(next);
    setModalTask(next === 'detail' ? graphTasks[0] ?? null : next === 'failure' ? graphTasks.find((task) => statusesAt(display.headSec, view).tasks[task.id]?.status === 'failed') ?? null : null);
  };
  const openTask = (task: Task, failed: boolean) => { setModalTask(task); setScreen(failed ? 'failure' : 'detail'); };
  useEffect(() => { if (navigation) navigate(navigation.screen); }, [navigation?.requestId]);

  const firstFailed = graphTasks.find((task) => statusesAt(display.headSec, view).tasks[task.id]?.status === 'failed') ?? null;

  return <div className="mission-debugger">{screen === 'milestones'
    ? <Milestones view={view} phase={display.phase} milestoneStatuses={milestoneStatuses} assignments={assignments} onAssign={(id, hardware) => setAssignments((current) => ({ ...current, [id]: [...new Set([...(current[id] ?? []), hardware])] }))} onOpen={(id) => { setMilestoneId(id); navigate('graph'); }} planApproval={planApproval} />
    : <GraphScreen screen={screen} view={view} milestone={graphMilestone} tasks={graphTasks} headSec={display.headSec} playing={display.phase === 'playing'} layoutMode={layoutMode} onLayout={setLayoutMode} scope={scope} onScope={setScope} refEdges={visibleRefEdges} crossing={crossingRefEdges} onOpen={openTask}
      // navigate() 를 쓴다 — 그것이 modalTask 정리까지 함께 한다. setScreen 을 직접 부르면 팝업이 남는다.
      // 범위도 함께 되돌린다: 「임무 전체」로 보다 목록으로 나갔다 다시 들어왔는데 전체로 남아 있으면 어리둥절하다.
      onBack={() => { setScope('milestone'); navigate('milestones'); }}
      onGraph={() => navigate('graph')}
      openTask={modalTask} />}
    {modalTask && <ActionModal task={modalTask} view={view} device={listRegisteredHardware().find((item) => item.id === modalTask.target)} failure={screen === 'failure'} onClose={() => { setModalTask(null); if (screen === 'detail') setScreen('graph'); }} />}
    {screen === 'failure' && !modalTask && firstFailed && <button className="failure-open" onClick={() => setModalTask(firstFailed)}>실패 수정 팝업 열기</button>}</div>;
}
