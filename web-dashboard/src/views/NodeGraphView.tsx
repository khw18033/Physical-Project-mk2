/** VZ-U-04 — 초안과 운영 상태를 분리한 노드 그래프 편집기. */

import { useEffect, useMemo, useRef, useState } from 'react';
import { canConnect, commitPipeline, fetchNodeCatalog, fetchPipelineState, rollbackPipeline, starterGraph, testPipeline, type CatalogNode, type GraphNode, type PipelineGraph, type PipelineState, type TestResult } from '../data/pipelineEditor.ts';

export function NodeGraphView() {
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

  return <main className="board graphpage">
    <header className="board__head"><div><h1 className="board__title">노드 그래프 편집기</h1><p className="board__sub">편집 초안은 시험 실행 후 명시적으로 반영해야 운영 그래프가 된다</p></div><div className="graphactions"><button className="btn" onClick={runTest}>시험 실행</button><button className="btn btn--on" disabled={!test?.token} onClick={commit}>운영에 반영</button><button className="btn" disabled={!state.previous} onClick={rollback}>직전 버전 되돌리기</button></div></header>
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
  </main>;
}
