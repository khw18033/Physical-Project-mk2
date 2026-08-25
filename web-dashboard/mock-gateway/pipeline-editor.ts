/** VZ-U-04 — 목 노드 카탈로그, 검증, 시험 실행, 반영과 되돌리기. */

export type PortType = 'timeseries' | 'table' | 'video' | 'scalar';
export type CatalogNode = {
  type: string;
  label: string;
  kind: 'source' | 'transform' | 'sink';
  input: PortType | null;
  output: PortType | null;
  executionLocation: 'server' | 'client';
};
export type GraphNode = CatalogNode & { id: string; x: number; y: number };
export type PipelineGraph = { id: string; version: string; serializationFormat: 'json'; nodes: GraphNode[]; edges: Array<{ from: string; to: string }> };
export type ValidationIssue = { code: string; message: string; nodes: string[] };

export const NODE_CATALOG: CatalogNode[] = [
  { type: 'prometheus-range', label: 'Prometheus 시계열', kind: 'source', input: null, output: 'timeseries', executionLocation: 'server' },
  { type: 'video-stream', label: '카메라 스트림', kind: 'source', input: null, output: 'video', executionLocation: 'server' },
  { type: 'resample', label: '재표본화', kind: 'transform', input: 'timeseries', output: 'timeseries', executionLocation: 'server' },
  { type: 'aggregate-table', label: '구간 집계', kind: 'transform', input: 'timeseries', output: 'table', executionLocation: 'server' },
  { type: 'graph-renderer', label: '그래프 렌더러', kind: 'sink', input: 'timeseries', output: null, executionLocation: 'client' },
  { type: 'table-renderer', label: '표 렌더러', kind: 'sink', input: 'table', output: null, executionLocation: 'client' },
  { type: 'video-renderer', label: '영상 렌더러', kind: 'sink', input: 'video', output: null, executionLocation: 'client' },
];

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const fingerprint = (g: PipelineGraph) => JSON.stringify(g);

export function validateGraph(graph: PipelineGraph): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const ids = new Set<string>();
  for (const node of graph.nodes) {
    if (ids.has(node.id)) issues.push({ code: 'duplicate_node', message: `중복 노드 id: ${node.id}`, nodes: [node.id] });
    ids.add(node.id);
  }
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  if (!graph.nodes.some((n) => n.kind === 'source')) issues.push({ code: 'source_required', message: 'source 노드가 필요하다', nodes: [] });
  if (!graph.nodes.some((n) => n.kind === 'sink')) issues.push({ code: 'sink_required', message: 'sink 노드가 필요하다', nodes: [] });

  const adjacency = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const from = byId.get(edge.from);
    const to = byId.get(edge.to);
    if (!from || !to) {
      issues.push({ code: 'missing_node', message: `${edge.from} → ${edge.to}: 존재하지 않는 노드`, nodes: [edge.from, edge.to] });
      continue;
    }
    if (from.output === null || to.input === null || from.output !== to.input) {
      issues.push({ code: 'type_mismatch', message: `${from.label}(${from.output ?? '없음'}) → ${to.label}(${to.input ?? '없음'}) 타입 불일치`, nodes: [from.id, to.id] });
    }
    if (from.kind === 'sink' || to.kind === 'source') issues.push({ code: 'direction', message: 'sink에서 나가거나 source로 들어갈 수 없다', nodes: [from.id, to.id] });
    adjacency.set(from.id, [...(adjacency.get(from.id) ?? []), to.id]);
  }
  for (const node of graph.nodes) {
    const incoming = graph.edges.some((e) => e.to === node.id);
    const outgoing = graph.edges.some((e) => e.from === node.id);
    if (node.kind !== 'source' && !incoming) issues.push({ code: 'input_required', message: `${node.label}: 입력 연결이 필요하다`, nodes: [node.id] });
    if (node.kind !== 'sink' && !outgoing) issues.push({ code: 'output_required', message: `${node.label}: 출력 연결이 필요하다`, nodes: [node.id] });
  }

  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (id: string): boolean => {
    if (visiting.has(id)) return true;
    if (visited.has(id)) return false;
    visiting.add(id);
    for (const next of adjacency.get(id) ?? []) if (visit(next)) return true;
    visiting.delete(id);
    visited.add(id);
    return false;
  };
  if (graph.nodes.some((n) => visit(n.id))) issues.push({ code: 'cycle', message: '순환 연결은 실행할 수 없다', nodes: [] });
  return issues;
}

export class PipelineEditorEngine {
  private active: PipelineGraph | null = null;
  private previous: PipelineGraph | null = null;
  private tested = new Map<string, string>();
  readonly audit: Array<{ action: 'commit' | 'rollback'; graph_id: string; version: string; at: string; actor: string }> = [];

  state() { return { active: clone(this.active), previous: clone(this.previous), audit: clone(this.audit) }; }

  test(graph: PipelineGraph) {
    const issues = validateGraph(graph);
    if (issues.length > 0) return { ok: false, issues, token: null, outputs: [] };
    const token = 'test-' + Date.now().toString(36);
    this.tested.set(token, fingerprint(graph));
    const outputs = graph.nodes.map((n, i) => ({ node_id: n.id, status: 'passed', rows: n.kind === 'source' ? 60 : Math.max(1, 60 - i * 4), elapsed_ms: 7 + i * 11 }));
    return { ok: true, issues: [], token, outputs };
  }

  commit(graph: PipelineGraph, token: string) {
    const issues = validateGraph(graph);
    if (issues.length > 0) return { ok: false, issues, message: '검증 실패' };
    if (this.tested.get(token) !== fingerprint(graph)) return { ok: false, issues: [], message: '현재 초안의 시험 실행 증명이 없다' };
    this.previous = this.active;
    this.active = clone(graph);
    this.audit.push({ action: 'commit', graph_id: graph.id, version: graph.version, at: new Date().toISOString(), actor: 'mock-operator' });
    return { ok: true, issues: [], message: '운영 그래프에 반영됨', state: this.state() };
  }

  rollback() {
    if (!this.previous) return { ok: false, message: '되돌릴 직전 버전이 없다', state: this.state() };
    const current = this.active;
    this.active = this.previous;
    this.previous = current;
    this.audit.push({ action: 'rollback', graph_id: this.active.id, version: this.active.version, at: new Date().toISOString(), actor: 'mock-operator' });
    return { ok: true, message: '직전 운영 그래프로 되돌림', state: this.state() };
  }
}
