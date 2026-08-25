/** VZ-U-04 — 편집기는 HTTP 계약만 알고 실제 실행기·저장소를 직접 만지지 않는다. */

import { GATEWAY } from '../transport/index.ts';

export type PortType = 'timeseries' | 'table' | 'video' | 'scalar';
export type CatalogNode = { type: string; label: string; kind: 'source' | 'transform' | 'sink'; input: PortType | null; output: PortType | null; executionLocation: 'server' | 'client' };
export type GraphNode = CatalogNode & { id: string; x: number; y: number };
export type PipelineGraph = { id: string; version: string; serializationFormat: 'json'; nodes: GraphNode[]; edges: Array<{ from: string; to: string }> };
export type ValidationIssue = { code: string; message: string; nodes: string[] };
export type PipelineState = { active: PipelineGraph | null; previous: PipelineGraph | null; audit: Array<{ action: string; graph_id: string; version: string; at: string; actor: string }> };
export type TestResult = { ok: boolean; issues: ValidationIssue[]; token: string | null; outputs: Array<{ node_id: string; status: string; rows: number; elapsed_ms: number }> };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(GATEWAY.http + path, init);
  const body = await response.json() as T & { message?: string };
  if (!response.ok) throw new Error(body.message ?? `HTTP ${response.status}`);
  return body;
}
const post = (body?: unknown): RequestInit => ({ method: 'POST', headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });

export const fetchNodeCatalog = () => api<{ nodes: CatalogNode[] }>('/pipelines/catalog');
export const fetchPipelineState = () => api<PipelineState>('/pipelines/state');
export const testPipeline = (graph: PipelineGraph) => api<TestResult>('/pipelines/test', post({ graph }));
export const commitPipeline = (graph: PipelineGraph, token: string) => api<{ ok: true; message: string; state: PipelineState }>('/pipelines/commit', post({ graph, token }));
export const rollbackPipeline = () => api<{ ok: true; message: string; state: PipelineState }>('/pipelines/rollback', post());

export function canConnect(from: GraphNode, to: GraphNode): string | null {
  if (from.id === to.id) return '자기 자신에 연결할 수 없다';
  if (from.kind === 'sink') return 'sink 노드에는 출력이 없다';
  if (to.kind === 'source') return 'source 노드에는 입력이 없다';
  if (from.output !== to.input) return `타입 불일치: ${from.output ?? '없음'} → ${to.input ?? '없음'}`;
  return null;
}

export function starterGraph(catalog: CatalogNode[]): PipelineGraph {
  const pick = (type: string) => catalog.find((n) => n.type === type)!;
  return {
    id: 'zone-503-water-level', version: '1.0.0', serializationFormat: 'json',
    nodes: [
      { ...pick('prometheus-range'), id: 'source_1', x: 60, y: 100 },
      { ...pick('resample'), id: 'transform_1', x: 330, y: 100 },
      { ...pick('graph-renderer'), id: 'sink_1', x: 600, y: 100 },
    ],
    edges: [{ from: 'source_1', to: 'transform_1' }, { from: 'transform_1', to: 'sink_1' }],
  };
}
