// 이식: web-dashboard/src/views/NodeGraphView.tsx @ 700ed91 — 무수정 (transport 경로만 조정)
/** VZ-U-04 — 초안과 운영 상태를 분리한 노드 그래프 편집기. */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  canConnect,
  commitPipeline,
  fetchNodeCatalog,
  fetchObservation,
  fetchPipelineState,
  fromContract,
  nextNodeId,
  nodeFromCatalog,
  resolveCatalog,
  rollbackPipeline,
  starterDraft,
  testPipeline,
  toContract,
  type CatalogNode,
  type CatalogResponse,
  type ContractNode,
  type NodeObservation,
  type ObservationReport,
  type PipelineContract,
  type PipelineDraft,
  type PipelineState,
  type TestResult,
} from '../data/pipelineEditor.ts';
// 임무 관제 모드를 지우면서 그 모드만 쓰던 import 넷(decidePlan·playScenario·Plan·PlanSegment·
// SEGMENT_STATUS_LABEL · RegistryEntity · EntityRecord · useEntities)도 같이 지웠다.
// 승인·거부(decidePlan)는 버리는 것이 아니라 탭①의 PlanApproval.tsx 로 옴겼다 (VZ-U-07).

/**
 * 탭⑥ — 데이터 파이프라인 편집기 (VZ-U-04).
 *
 * **임무 관제 모드를 가져오지 않았다.** 원본에는 `임무 관제` / `데이터 파이프라인` 토글이
 * 있었지만, 임무 관제 그래프는 탭①이 하는 일과 같은 화면이라 둘을 다 두면 사용자가
 * 어느 것을 봐야 하는지 알 수 없게 된다. 토글과 `MissionGraph` 를 통째로 지웠다.
 *
 * **동결이다.** 8/18에 교수님이 예시로 보여준 것이라 지우지 않을 뿐, 신규 개발도
 * 논문 반영도 하지 않는다. 기능을 추가하지 말 것.
 */
export function NodeGraphView() {
  return <main className="board graphpage">
    <header className="board__head">
      <div><h1 className="board__title">데이터 파이프라인 편집기</h1><p className="board__sub">초안과 운영 상태를 분리한 노드 그래프. 좌표는 계약 밖에 둔다</p></div>
      <div className="graphactions"><span className="frozen-tag" title="8/18 예시로 만든 화면이라 유지만 한다. 신규 개발·논문 반영 대상이 아니다">동결 — 유지만 함</span></div>
    </header>
    <PipelineGraphEditor />
  </main>;
}

// ── 데이터 파이프라인 편집기 ─────────────────────────────────────────────────

/** 반영된 그래프의 관측을 몇 초마다 물을 것인가. 흐르는 값이라 시점이 이산적이지 않다. */
const OBSERVATION_POLL_MS = 3000;

function PipelineGraphEditor() {
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [draft, setDraft] = useState<PipelineDraft | null>(null);
  const [state, setState] = useState<PipelineState>({ active: null, previous: null, activeLayout: {}, previousLayout: {}, audit: [] });
  const [observation, setObservation] = useState<ObservationReport | null>(null);
  const [from, setFrom] = useState<string | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [message, setMessage] = useState('카탈로그 조회 중');
  const [contractText, setContractText] = useState<string | null>(null);
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);

  useEffect(() => {
    void Promise.all([fetchNodeCatalog(), fetchPipelineState()]).then(([c, s]) => {
      setCatalog(c);
      setState(s);
      setDraft(s.active ? fromContract(s.active, s.activeLayout) : starterDraft(c.nodes));
      setMessage('편집 초안 — 시험 실행 전');
    }, (e: unknown) => setMessage('조회 실패: ' + String(e)));
  }, []);

  /**
   * REQ-1007 — 반영된 그래프가 지금 무엇을 받고 있는지. **게이트웨이 왕복으로만** 본다.
   * 편집기가 스토어 내부를 직접 읽으면 실물 백엔드로 갈아탈 때 그 경로가 통째로 사라진다.
   * 반영된 그래프가 없으면 물어볼 것도 없으므로 아예 걸지 않는다.
   */
  useEffect(() => {
    if (state.active === null) { setObservation(null); return; }
    let alive = true;
    const pull = () => void fetchObservation().then((r) => { if (alive) setObservation(r); }, () => { /* 관측 실패는 편집을 막지 않는다 */ });
    pull();
    const timer = setInterval(pull, OBSERVATION_POLL_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [state.active?.id, state.active?.version]);

  const nodes = draft?.pipeline.nodes ?? [];
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const entryOf = useMemo(() => {
    const map = new Map<string, CatalogNode | null>();
    for (const node of nodes) map.set(node.id, catalog ? resolveCatalog(catalog.nodes, node) : null);
    return map;
  }, [nodes, catalog]);
  const observed = useMemo(() => new Map((observation?.nodes ?? []).map((o) => [o.node_id, o])), [observation]);

  if (!draft || !catalog) return <main className="board"><p className="notice">{message}</p></main>;

  /** 계약 본문이 바뀌면 시험 증명이 무효다. **좌표만 옮긴 것은 여기 오지 않는다.** */
  const mutate = (pipeline: PipelineContract, layout?: Record<string, { x: number; y: number }>) => {
    setDraft({ pipeline, layout: layout ?? draft.layout });
    setTest(null);
    setMessage('초안 변경됨 — 다시 시험 실행해야 반영 가능');
  };

  const addNode = (spec: CatalogNode) => {
    const id = nextNodeId(draft.pipeline, spec.kind);
    const node = nodeFromCatalog(spec, id);
    const x = 40 + (spec.kind === 'source' ? 0 : spec.kind === 'transform' ? 1 : 2) * 270;
    const y = 40 + (nodes.length % 4) * 110;
    mutate({ ...draft.pipeline, nodes: [...nodes, node] }, { ...draft.layout, [id]: { x, y } });
  };

  const selectPort = (node: ContractNode) => {
    const entry = entryOf.get(node.id) ?? null;
    if (from === null) {
      if (entry?.emits) { setFrom(node.id); setMessage(entry.label + ' 출력 선택 — 연결할 입력을 누르세요'); }
      return;
    }
    const source = byId.get(from);
    if (!source) { setFrom(null); return; }
    const reason = canConnect(catalog.nodes, source, node);
    if (reason) { setMessage(reason); return; }
    if (draft.pipeline.edges.some((e) => e.from === from && e.to === node.id)) { setMessage('이미 연결돼 있다'); return; }
    mutate({ ...draft.pipeline, edges: [...draft.pipeline.edges, { from, to: node.id }] });
    setFrom(null);
  };

  const remove = (id: string) => {
    const layout = { ...draft.layout };
    delete layout[id];
    mutate({ ...draft.pipeline, nodes: nodes.filter((n) => n.id !== id), edges: draft.pipeline.edges.filter((e) => e.from !== id && e.to !== id) }, layout);
    setFrom(null);
  };

  // 좌표는 계약 밖이므로 옮겨도 계약은 그대로다 — 시험 증명을 무효로 만들지 않는다.
  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width - 190, e.clientX - rect.left - drag.current.dx));
    const y = Math.max(0, Math.min(rect.height - 84, e.clientY - rect.top - drag.current.dy));
    const id = drag.current.id;
    setDraft((g) => g && ({ ...g, layout: { ...g.layout, [id]: { x, y } } }));
  };

  const runTest = () => void testPipeline(draft).then((r) => { setTest(r); setMessage(r.ok ? '시험 실행 통과 — 이 초안을 반영할 수 있다' : '시험 실행 실패'); }, (e: unknown) => setMessage(String(e)));
  const commit = () => { if (!test?.token) return; void commitPipeline(draft, test.token).then((r) => { setState(r.state); setMessage(r.message); setTest(null); }, (e: unknown) => setMessage(String(e))); };
  const rollback = () => void rollbackPipeline().then((r) => {
    setState(r.state);
    if (r.state.active) setDraft(fromContract(r.state.active, r.state.activeLayout));
    setMessage(r.message);
    setTest(null);
  }, (e: unknown) => setMessage(String(e)));

  /** REQ-1002를 화면에서 확인하는 자리 — 내보낸 계약 JSON에 좌표가 없어야 한다. */
  const showContract = () => setContractText(contractText === null ? JSON.stringify(toContract(draft), null, 2) : null);
  const loadContract = () => {
    if (contractText === null) return;
    try {
      const parsed = JSON.parse(contractText) as PipelineContract;
      setDraft(fromContract(parsed, draft.layout));
      setTest(null);
      setMessage('계약 JSON에서 초안을 복원했다 — 좌표는 편집기 레이아웃에서 왔다');
    } catch (e) {
      setMessage('계약 JSON을 읽을 수 없다: ' + String(e));
    }
  };

  const activeIds = new Set(state.active?.nodes.map((n) => n.id) ?? []);

  return <section className="pipelineeditor">
    <header className="pipelineeditor__head"><div><h2>데이터 해석 파이프라인</h2><p>임무 그래프와 별개인 source → transform → sink 구성 편집기</p></div><div className="graphactions"><button className="btn" onClick={runTest}>시험 실행</button><button className="btn btn--on" disabled={!test?.token} onClick={commit}>운영에 반영</button><button className="btn" disabled={!state.previous} onClick={rollback}>직전 버전 되돌리기</button><button className="btn" onClick={showContract}>{contractText === null ? '계약 JSON 보기' : '계약 JSON 닫기'}</button></div></header>
    <p className={'notice' + (test && !test.ok ? ' notice--warn' : '')}>{message}</p>
    {contractText !== null && <section className="contractio">
      <h2>F4 계약 JSON (REQ-1002)</h2>
      <p>이 본문에는 좌표가 없다. 좌표는 편집기 레이아웃에만 있고 계약과 함께 저장되지만 계약 안으로는 들어가지 않는다. 고쳐서 다시 불러오면 같은 화면으로 복원된다.</p>
      <textarea value={contractText} spellCheck={false} onChange={(e) => setContractText(e.target.value)} />
      <button className="btn" onClick={loadContract}>이 계약으로 초안 복원</button>
    </section>}
    <div className="grapheditor">
      <aside className="catalog">
        <h2>노드 카탈로그</h2>
        <p className="catalog__note">{catalog.nodes.length}종 · 등록처 {catalog.registration_sources.length}개 파일에서 파생 (REQ-1003). {catalog.note}</p>
        {catalog.nodes.map((n) => <button key={n.type} className="catalog__node" onClick={() => addNode(n)}><b>{n.label}</b><span>{n.kind} · {(n.accepts ?? ['—']).join('|')} → {n.emits ?? '—'}</span><span>{n.derivedFrom.join(' · ')}</span></button>)}
        <p className="catalog__note">포트 타입 어휘: {catalog.port_types.join(', ')} — 디스크립터·렌더러 선언에서 왔다.</p>
      </aside>
      <div className="canvas" onPointerMove={onMove} onPointerUp={() => { drag.current = null; }} onPointerLeave={() => { drag.current = null; }}>
        <svg className="canvas__edges">{draft.pipeline.edges.map((edge) => { const a = draft.layout[edge.from]; const b = draft.layout[edge.to]; return a && b ? <line key={edge.from + edge.to} x1={a.x + 185} y1={a.y + 38} x2={b.x} y2={b.y + 38} /> : null; })}</svg>
        {nodes.map((n) => {
          const entry = entryOf.get(n.id) ?? null;
          const pos = draft.layout[n.id] ?? { x: 0, y: 0 };
          const live = activeIds.has(n.id) ? observed.get(n.id) ?? null : null;
          return <article key={n.id} className={'graphnode graphnode--' + n.kind + (from === n.id ? ' graphnode--selected' : '')} style={{ left: pos.x, top: pos.y }} onPointerDown={(e) => { const rect = e.currentTarget.getBoundingClientRect(); drag.current = { id: n.id, dx: e.clientX - rect.left, dy: e.clientY - rect.top }; e.currentTarget.setPointerCapture(e.pointerId); }}>
            <button className="graphnode__remove" onPointerDown={(e) => e.stopPropagation()} onClick={() => remove(n.id)}>×</button>
            <b>{entry?.label ?? '(카탈로그에 없는 노드)'}</b>
            <small>{n.id} · {n.executionLocation}</small>
            {live && <span className={'graphnode__live graphnode__live--' + live.origin}>운영 {live.received}건 · {live.origin === 'live' ? '실수신' : live.origin === 'mock-propagated' ? '목 전달' : '없음'}</span>}
            <button className="graphnode__port" onPointerDown={(e) => e.stopPropagation()} onClick={() => selectPort(n)}>{from === null ? (entry?.emits ? '출력 선택' : '입력') : (entry?.accepts ? '여기에 연결' : '입력 없음')} · {entry?.accepts?.join('|') ?? entry?.emits ?? '—'}</button>
          </article>;
        })}
      </div>
    </div>
    <section className="graphresult">
      <h2>시험 결과 <small>초안의 모의 실행</small></h2>
      {test?.executor && <p className="notice">{test.executor}</p>}
      {test?.issues.map((i) => <p className="notice notice--warn" key={i.code + i.message}>{i.message}</p>)}
      {test?.outputs.map((o) => <span className="chip" key={o.node_id}>{o.node_id} · {o.status} · {o.rows}행 · {o.elapsed_ms}ms</span>)}
      {test === null && <p>아직 시험 실행하지 않았다.</p>}
      <p>운영: {state.active ? `${state.active.id} v${state.active.version}` : '미반영'} · 직전 버전: {state.previous ? state.previous.version : '없음'}</p>
    </section>
    <ObservationPanel report={observation} />
  </section>;
}

/**
 * REQ-1007 — 반영된 그래프의 역방향 관측.
 *
 * 시험 결과와 **같은 자리에 섞지 않는다.** 하나는 초안의 모의 결과이고 하나는 운영
 * 그래프가 실제로 받고 있는 값이다. 한 상자에 넣으면 "이 숫자가 지어낸 것인지 받은
 * 것인지"를 화면에서 가를 수 없고, 그 순간 요건이 깨진 것이다.
 */
function ObservationPanel({ report }: { report: ObservationReport | null }) {
  if (report === null || report.graph_id === null) {
    return <section className="graphobserve"><h2>운영 그래프 관측 <small>REQ-1007</small></h2><p>반영된 그래프가 없다. 반영하면 그 그래프가 지금 무엇을 받고 있는지 여기에 뜬다.</p></section>;
  }
  const timeOf = (iso: string | null) => iso === null ? '—' : new Date(iso).toLocaleTimeString();
  return <section className="graphobserve">
    <h2>운영 그래프 관측 <small>REQ-1007 · {report.graph_id} v{report.version}</small></h2>
    <p className="notice">{report.executor}</p>
    <table className="observetable"><thead><tr><th>노드</th><th>붙은 대상</th><th>최근 수신</th><th>건수</th><th>마지막 값</th></tr></thead>
      <tbody>{report.nodes.map((n) => <ObservationRow key={n.node_id} row={n} timeOf={timeOf} />)}</tbody>
    </table>
    <p>관측 시작: {timeOf(report.since)} — 반영 시점부터 다시 센다.</p>
  </section>;
}

function ObservationRow({ row, timeOf }: { row: NodeObservation; timeOf: (iso: string | null) => string }) {
  return <tr className={'observerow observerow--' + row.origin}>
    <td>{row.node_id} <small>{row.kind}</small></td>
    <td>{row.bound_to ?? <span className="muted">대응 대상 없음</span>}</td>
    <td>{timeOf(row.last_at)}</td>
    <td>{row.received}</td>
    <td>{row.last_value ?? <span className="muted">수신 없음</span>}{row.origin === 'mock-propagated' && <em> (목 실행기 전달)</em>}</td>
  </tr>;
}
