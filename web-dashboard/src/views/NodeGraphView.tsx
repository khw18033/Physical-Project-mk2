/** VZ-U-04 — 초안과 운영 상태를 분리한 노드 그래프 편집기. */

import { useEffect, useMemo, useRef, useState } from 'react';
import { canConnect, commitPipeline, fetchNodeCatalog, fetchPipelineState, rollbackPipeline, starterGraph, testPipeline, type CatalogNode, type GraphNode, type PipelineGraph, type PipelineState, type TestResult } from '../data/pipelineEditor.ts';
import { decidePlan, playScenario, type Plan, type PlanSegment, SEGMENT_STATUS_LABEL } from '../data/index.ts';
import { useEntities } from '../data/hooks.ts';

export function NodeGraphView() {
  const [mode, setMode] = useState<'mission' | 'pipeline'>('mission');
  return <main className="board graphpage">
    <header className="board__head"><div><h1 className="board__title">노드 그래프 관제</h1><p className="board__sub">임무와 서브태스크를 중심으로 실행·영상·센서·제어 근거를 연결한다</p></div><div className="graphactions"><button className={'btn' + (mode === 'mission' ? ' btn--on' : '')} onClick={() => setMode('mission')}>임무 관제</button><button className={'btn' + (mode === 'pipeline' ? ' btn--on' : '')} onClick={() => setMode('pipeline')}>데이터 파이프라인</button></div></header>
    {mode === 'mission' ? <MissionGraph /> : <PipelineGraphEditor />}
  </main>;
}

type EvidenceKind = 'robot' | 'video' | 'sensor' | 'control';
type EvidenceLink = { id: string; kind: EvidenceKind; entity: string; label: string };
const EVIDENCE_CATALOG: EvidenceLink[] = [
  { id: 'ev-robot', kind: 'robot', entity: 'robot-01', label: '로봇 01 실행 상태' },
  { id: 'ev-video', kind: 'video', entity: 'camera-02', label: '고정 비전센서 02 영상' },
  { id: 'ev-sensor', kind: 'sensor', entity: 'sensor-01', label: '수위 센서 01' },
  { id: 'ev-control', kind: 'control', entity: 'actuator-01', label: '수문 01 제어 결과' },
];
const DEFAULT_LINKS: Record<number, EvidenceKind[]> = { 1: ['robot', 'video'], 2: ['robot', 'video'], 3: ['robot', 'sensor'], 4: ['robot', 'video'], 5: ['robot', 'control'] };

function MissionGraph() {
  const entities = useEntities();
  const record = entities.get('robot-01') ?? null;
  const plan = (record?.plan?.payload as Plan | undefined) ?? null;
  const progress = record?.planProgress?.payload ?? null;
  const segments: PlanSegment[] = progress !== null && progress.plan_id === plan?.plan_id ? progress.segments : (plan?.segments ?? []);
  const [selected, setSelected] = useState(1);
  const [links, setLinks] = useState<Record<number, EvidenceKind[]>>(DEFAULT_LINKS);
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);

  useEffect(() => { if (plan) { setSelected(1); setLinks(DEFAULT_LINKS); } }, [plan?.plan_id]);
  if (!plan) return <><p className="notice">관제할 임무가 없다. 계획을 내려받으면 임무 그래프가 만들어진다.</p><button className="btn" onClick={() => playScenario('plan-propose')}>계획 내려받기</button></>;

  const toggle = (kind: EvidenceKind) => setLinks((current) => {
    const list = current[selected] ?? [];
    return { ...current, [selected]: list.includes(kind) ? list.filter((v) => v !== kind) : [...list, kind] };
  });
  const statusOfEvidence = (e: EvidenceLink) => {
    const r = entities.get(e.entity);
    if (e.kind === 'video') return r?.videoMeta ? '수신중' : '미수신';
    if (e.kind === 'control') return r?.actuator?.payload.phase ?? '미수신';
    return r?.state?.payload.availability ?? '미수신';
  };

  const width = Math.max(980, segments.length * 245 + 170);
  return <>
    <section className="missionbar"><div><b>{plan.evidence.mission.title}</b><span>{plan.plan_id} · {plan.entity}</span></div><span className={'badge badge--plan-' + plan.decision}>{plan.decision === 'pending' ? '승인 대기' : plan.decision === 'approved' ? '승인됨' : '거부됨'}</span>{plan.decision === 'pending' && <button className="btn btn--on" onClick={() => decidePlan(plan.plan_id, 'approve')}>승인 후 실행</button>}</section>
    <p className="notice">노드를 누르면 해당 서브태스크에 관측 근거를 붙이거나 뗄 수 있다. 연결은 표시 장식이 아니라 실패 원인을 함께 관제할 근거다.</p>
    <div className="missioncanvaswrap"><div className="missioncanvas" style={{ width }}>
      <svg className="canvas__edges missionedges" viewBox={`0 0 ${width} 500`} preserveAspectRatio="none">
        <line x1="145" y1="105" x2="205" y2="105" />
        {segments.slice(0, -1).map((s, i) => <line key={'seq-' + s.index} x1={205 + i * 235 + 190} y1="105" x2={205 + (i + 1) * 235} y2="105" />)}
        {segments.flatMap((s, i) => (links[s.index] ?? []).map((kind, j) => <line className="missionedges__evidence" key={`${s.index}-${kind}`} x1={205 + i * 235 + 95} y1="145" x2={205 + i * 235 + 95} y2={238 + j * 74} />))}
      </svg>
      <article className={'missionnode missionnode--root missionnode--' + plan.decision} style={{ left: 10, top: 62 }}><b>전체 임무</b><small>{plan.evidence.mission.id}</small><span>{plan.decision === 'pending' ? '승인 전 · 실행 금지' : plan.relay_stage}</span></article>
      {segments.map((s, i) => <div key={s.index}>
        <button className={'missionnode missionnode--task missionnode--' + s.status + (selected === s.index ? ' missionnode--selected' : '')} style={{ left: 205 + i * 235, top: 62 }} onClick={() => setSelected(s.index)}><b>Sub task {s.index}/{s.total}</b><small>{s.title}</small><span>{SEGMENT_STATUS_LABEL[s.status]} · {s.zone}</span>{s.failure && <em>{s.failure.reason}</em>}</button>
        {(links[s.index] ?? []).map((kind, j) => { const evidence = EVIDENCE_CATALOG.find((e) => e.kind === kind)!; const key = s.index + '-' + kind; return <button key={key} className={'evidencenode evidencenode--' + kind} style={{ left: 205 + i * 235, top: 238 + j * 74 }} onClick={() => setOpenEvidence(openEvidence === key ? null : key)}><b>{evidence.label}</b><span>{statusOfEvidence(evidence)}</span>{openEvidence === key && <small>{evidence.entity} · task {s.index}의 {kind === 'video' ? '영상 관측' : kind === 'sensor' ? '판단 입력' : kind === 'control' ? '실행 결과' : '실행 주체'} 근거</small>}</button>; })}
      </div>)}
    </div></div>
    <section className="evidencetools"><h2>Sub task {selected} 연결 관리</h2>{EVIDENCE_CATALOG.map((e) => <button key={e.kind} className={'btn' + ((links[selected] ?? []).includes(e.kind) ? ' btn--on' : '')} onClick={() => toggle(e.kind)}>{(links[selected] ?? []).includes(e.kind) ? '연결됨' : '연결'} · {e.label}</button>)}<p>현재 연결: {(links[selected] ?? []).join(', ') || '없음'}</p></section>
    <section className="devpanel"><h2 className="devpanel__title">임무 진행 재생</h2><div className="devpanel__row"><button className="btn" onClick={() => playScenario('plan-propose')}>정상 임무 새로 받기</button><button className="btn" onClick={() => playScenario('plan-propose-failing')}>4번 Sub task 실패 임무</button></div></section>
  </>;
}

function PipelineGraphEditor() {
  const [catalog, setCatalog] = useState<CatalogNode[]>([]);
  const [draft, setDraft] = useState<PipelineGraph | null>(null);
  const [state, setState] = useState<PipelineState>({ active: null, previous: null, audit: [] });
  const [from, setFrom] = useState<string | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [message, setMessage] = useState('카탈로그 조회 중');
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);

  useEffect(() => {
    void Promise.all([fetchNodeCatalog(), fetchPipelineState()]).then(([c, s]) => {
      setCatalog(c.nodes); setState(s); setDraft(s.active ?? starterGraph(c.nodes)); setMessage('편집 초안 — 시험 실행 전');
    }, (e: unknown) => setMessage('조회 실패: ' + String(e)));
  }, []);

  const byId = useMemo(() => new Map(draft?.nodes.map((n) => [n.id, n]) ?? []), [draft]);
  if (!draft) return <main className="board"><p className="notice">{message}</p></main>;

  const mutate = (next: PipelineGraph) => { setDraft(next); setTest(null); setMessage('초안 변경됨 — 다시 시험 실행해야 반영 가능'); };
  const addNode = (spec: CatalogNode) => {
    const count = draft.nodes.filter((n) => n.type === spec.type).length + 1;
    let suffix = draft.nodes.length + 1;
    while (draft.nodes.some((n) => n.id === spec.kind + '_' + suffix)) suffix += 1;
    mutate({ ...draft, nodes: [...draft.nodes, { ...spec, id: spec.kind + '_' + suffix, x: 80 + count * 35, y: 60 + draft.nodes.length * 42 }] });
  };
  const selectPort = (node: GraphNode) => {
    if (from === null) { if (node.output) { setFrom(node.id); setMessage(node.label + ' 출력 선택 — 연결할 입력을 누르세요'); } return; }
    const source = byId.get(from)!;
    const reason = canConnect(source, node);
    if (reason) { setMessage(reason); return; }
    if (draft.edges.some((e) => e.from === from && e.to === node.id)) { setMessage('이미 연결돼 있다'); return; }
    mutate({ ...draft, edges: [...draft.edges, { from, to: node.id }] }); setFrom(null);
  };
  const remove = (id: string) => { mutate({ ...draft, nodes: draft.nodes.filter((n) => n.id !== id), edges: draft.edges.filter((e) => e.from !== id && e.to !== id) }); setFrom(null); };
  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width - 190, e.clientX - rect.left - drag.current.dx));
    const y = Math.max(0, Math.min(rect.height - 84, e.clientY - rect.top - drag.current.dy));
    setDraft((g) => g && ({ ...g, nodes: g.nodes.map((n) => n.id === drag.current?.id ? { ...n, x, y } : n) }));
  };
  const runTest = () => void testPipeline(draft).then((r) => { setTest(r); setMessage(r.ok ? '시험 실행 통과 — 이 초안을 반영할 수 있다' : '시험 실행 실패'); }, (e: unknown) => setMessage(String(e)));
  const commit = () => { if (!test?.token) return; void commitPipeline(draft, test.token).then((r) => { setState(r.state); setMessage(r.message); setTest(null); }, (e: unknown) => setMessage(String(e))); };
  const rollback = () => void rollbackPipeline().then((r) => { setState(r.state); if (r.state.active) setDraft(r.state.active); setMessage(r.message); setTest(null); }, (e: unknown) => setMessage(String(e)));

  return <section className="pipelineeditor">
    <header className="pipelineeditor__head"><div><h2>데이터 해석 파이프라인</h2><p>임무 그래프와 별개인 source → transform → sink 구성 편집기</p></div><div className="graphactions"><button className="btn" onClick={runTest}>시험 실행</button><button className="btn btn--on" disabled={!test?.token} onClick={commit}>운영에 반영</button><button className="btn" disabled={!state.previous} onClick={rollback}>직전 버전 되돌리기</button></div></header>
    <p className={'notice' + (test && !test.ok ? ' notice--warn' : '')}>{message}</p>
    <div className="grapheditor">
      <aside className="catalog"><h2>노드 카탈로그</h2>{catalog.map((n) => <button key={n.type} className="catalog__node" onClick={() => addNode(n)}><b>{n.label}</b><span>{n.kind} · {n.input ?? '—'} → {n.output ?? '—'}</span></button>)}</aside>
      <div className="canvas" onPointerMove={onMove} onPointerUp={() => { if (drag.current) { drag.current = null; setTest(null); } }} onPointerLeave={() => { drag.current = null; }}>
        <svg className="canvas__edges">{draft.edges.map((edge) => { const a = byId.get(edge.from); const b = byId.get(edge.to); return a && b ? <line key={edge.from + edge.to} x1={a.x + 185} y1={a.y + 38} x2={b.x} y2={b.y + 38} /> : null; })}</svg>
        {draft.nodes.map((n) => <article key={n.id} className={'graphnode graphnode--' + n.kind + (from === n.id ? ' graphnode--selected' : '')} style={{ left: n.x, top: n.y }} onPointerDown={(e) => { const rect = e.currentTarget.getBoundingClientRect(); drag.current = { id: n.id, dx: e.clientX - rect.left, dy: e.clientY - rect.top }; e.currentTarget.setPointerCapture(e.pointerId); }}>
          <button className="graphnode__remove" onPointerDown={(e) => e.stopPropagation()} onClick={() => remove(n.id)}>×</button><b>{n.label}</b><small>{n.id} · {n.executionLocation}</small><button className="graphnode__port" onPointerDown={(e) => e.stopPropagation()} onClick={() => selectPort(n)}>{from === null ? (n.output ? '출력 선택' : '입력') : (n.input ? '여기에 연결' : '입력 없음')} · {n.input ?? n.output ?? '—'}</button>
        </article>)}
      </div>
    </div>
    <section className="graphresult"><h2>시험 결과</h2>{test?.issues.map((i) => <p className="notice notice--warn" key={i.code + i.message}>{i.message}</p>)}{test?.outputs.map((o) => <span className="chip" key={o.node_id}>{o.node_id} · {o.status} · {o.rows}행 · {o.elapsed_ms}ms</span>)}<p>운영: {state.active ? `${state.active.id} v${state.active.version}` : '미반영'} · 직전 버전: {state.previous ? state.previous.version : '없음'}</p></section>
  </section>;
}
