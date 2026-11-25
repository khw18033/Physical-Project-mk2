/**
 * src/detect/status/placement.ts (261125 신설 — 객체 탐지 상태판 · 모델 실행 장치)
 *
 * **모델 칩 하나가 어느 장치에서 도는가.** 값은 개발 서버 창구 `/vision-stream/placement` 가 data_stream Redis 의
 * `orchestration_stream`(가장 최근 배치표) · `node_resource_stream`(노드 하드웨어 · 사용량)을 줄여 준 것이다
 * (`scripts/vision-redis-placement.mjs`). `/health` 에는 실행 장치가 없다 — 그쪽 `host` 는 영상을 받는 서버 이름이다.
 *
 * ## 261125 사용자 결정 (data_stream 협의 뒤)
 *
 * 1. **배치표는 받으면 저장해 그대로 쓴다.** 스트림은 최근 N건만 남아 오래 돌면 `planned` 가 밀려나지만, 화면은 저장해 둔
 *    것을 계속 쓴다(이 브라우저 `localStorage`). 배치가 바뀌면 data_stream 이 `planned` 를 처음부터 다시 보내므로, **더 새
 *    `planned`** 가 오면 통째로 갈아 끼운다. 창구가 배치표를 못 주면(밀려남 · Redis 꺼짐) 저장해 둔 것을 그대로 둔다.
 * 2. **배치표에 없는 (소스, 모델)은 data_stream 기기에서 도는 것으로 확정한다.** 자원 배분 없이 띄운 비전은 data_stream
 *    기기에서만 돈다(data_stream 계획 §1-2). 「추정」으로 적지 않는다.
 *
 * 지금(placement/1)은 GPU 모델을 파이로 옮기지 않으므로 칩은 모두 「노트북」으로 나온다. 노드가 늘면 그대로 노드 이름이 붙는다.
 *
 * ## 261125 data_stream 답 뒤 검토 · 고침
 *
 * - 「배치가 바뀔 때마다 스트림 갱신」 — data_stream 코드로 확인했다. 칩에 닿는 변화는 새 `planned`(새 실행 · GPU 다시 요청)와
 *   실행 끝 `stopped` 둘이다(GPU 작업은 실행 중 노드를 옮기지 않는다). 그래서 저장본은 그대로 두되 **끝남을 따라간다** —
 *   요청별 마지막 기록(`requests`)이 `stopped` 면 그 배치표는 「지난 배치표」로 남고 칩 판단에는 안 쓴다(→ data_stream 기기).
 * - 신구는 기록 시각 `ts` 로 가린다(outbox 로 늦게 쓰인 옛 `planned` 가 새것을 덮지 않게).
 * - 저장본은 Redis 주소마다 따로 둔다 — 다른 data_stream 에 붙으면 옛 서버의 배치표 · 노드가 섞이지 않게.
 * - 자원 배분이 없을 때는 서버 고정(data_stream 기기 확정)을 유지한다 — host 키를 더하지 않는다(사용자 결정).
 *
 * ## 261125 안 2 — CPU 작업은 그 작업이 만드는 소스 카드에 붙인다
 *
 * - CPU 작업은 포트별 모델이 아니라서 칩이 없다. **작업 이름과 같은 이름의 소스 카드**(`cam360_slice` 작업 ↔ `cam360_slice`
 *   포트)에 「만드는 곳」 한 줄로 붙인다. 출력 포트가 없는 작업(시험 `probe` 등)은 붙일 카드가 없어 안 보인다(안 2의 한계).
 * - 위치는 창구가 단위 기록으로 따라간 `cpuTasks`(applied · running · replanned · stopped · failed)를 쓴다. 기록이 없거나
 *   끝났으면 **서버 고정** — data_stream 기기. 런처가 `cam360_slice` 를 WSL 에서 바로 띄우고(`Start-Slice`), 오케스트레이터에
 *   `--cpu-tasks` 를 넘기지 않으므로 지금은 늘 이쪽이다.
 * - 어느 소스가 CPU 작업의 출력인지는 스트림에 없다(런처로 띄우면 기록이 하나도 없다). 그래서 data_stream 레지스트리의
 *   `cpu_tasks`(지금 `cam360_slice` 하나)를 `CPU_TASK_SOURCES` 로 적어 두고, 스트림에 기록이 있는 작업은 그 이름도 받는다.
 */

import { useSyncExternalStore } from 'react';
import { t } from '../../i18n/dict.ts';
import { redisPlacementUrl, visionRedisUrl } from '../../vision/visionClient.ts';

export const PLACEMENT_POLL_MS = 5000;
export const PLACEMENT_STORAGE_KEY = 'vz.detect.placement.v1';

export type GpuUnit = {
  unit: string | null;
  node: string;
  models: readonly string[];
  sources: readonly string[];
  fpsCap: Readonly<Record<string, number>>;
  needMb: number | null;
  needBasis: string | null;
};

/** 요청 하나의 마지막 기록. `tsMs` 는 기록이 난 시각, `atMs` 는 스트림 ID 시각. */
export type RequestLast = { event: string | null; reason: string | null; ts: string | null; tsMs?: number | null; atMs: number | null };

export type PlanSummary = {
  eventId: string;
  streamId: string;
  atMs: number | null;
  /** 기록이 난 시각(`ts`) — 신구는 이것으로 가린다. 옛 저장본에는 없을 수 있다. */
  tsMs?: number | null;
  ts: string | null;
  requestId: string | null;
  mode: string | null;
  basis: string | null;
  algorithm: string | null;
  gpuUnits: readonly GpuUnit[];
  cpuUnits: readonly { task: string; node: string; reason: string | null }[];
  refused: readonly { item: string; reason: string }[];
  /** 그 요청의 가장 새 기록(applied · running · stopped · failed …). */
  last: RequestLast | null;
};

export type GpuUsage = { name: string | null; memTotalMb: number | null; memUsedMb: number | null; utilPct: number | null; tempC: number | null };

export type NodeBaseline = {
  arch: string | null;
  cpuCount: number | null;
  cpuModel: string | null;
  memTotalMb: number | null;
  gpus: readonly { name: string | null; memTotalMb: number | null }[];
};

export type NodeSummary = {
  node: string;
  role: string | null;
  /** `local` = data_stream 기기 자신(자원 기록기), `k3s` = 클러스터 노드. */
  source: string | null;
  ready: boolean;
  change: string | null;
  cpuPct: number | null;
  memPct: number | null;
  memMb: number | null;
  tempC: number | null;
  gpu: readonly GpuUsage[];
  serviceMode: string | null;
  ts: string | null;
  atMs: number | null;
  baseline: NodeBaseline | null;
  baselineAtMs: number | null;
};

export type CpuAmount = { cpuM: number | null; memMb: number | null };

export type CpuMove = {
  from: string | null;
  to: string;
  fromNode: string | null;
  toNode: string | null;
  reason: string | null;
  ts: string | null;
  tsMs?: number | null;
  atMs: number | null;
};

/** CPU 작업 하나의 지금 모습 — 창구 `cpuTasksOf` 가 단위 기록을 따라가 만든다. */
export type CpuTask = {
  task: string;
  requestId: string | null;
  unitId: string | null;
  node: string | null;
  state: 'planned' | 'applied' | 'running' | 'stopped' | 'failed';
  reason: string | null;
  /** k3s 응답 없음(`degraded`) — 위치는 마지막 값, 상태는 확인 불가. */
  lost: boolean;
  requests: CpuAmount | null;
  limits: CpuAmount | null;
  moves: readonly CpuMove[];
  ts: string | null;
  tsMs?: number | null;
  atMs: number | null;
};

export type PlacementSnapshot = {
  plan: PlanSummary | null;
  nodes: Readonly<Record<string, NodeSummary>>;
  /** 옛 저장본에는 없다. */
  cpuTasks?: Readonly<Record<string, CpuTask>>;
};

/** 창구 답 — 저장본 모양에 요청별 마지막 기록이 더해진다. */
export type PlacementReply = PlacementSnapshot & { requests?: Readonly<Record<string, RequestLast>> };

export type PlacementState = PlacementSnapshot & {
  /** 이번에 받은 답에 배치표가 있었나(`live`), 저장해 둔 것을 쓰나(`stored`), 아직 없나(null). */
  planFrom: 'live' | 'stored' | null;
  error: string | null;
  receivedAtMs: number | null;
};

// ── 순수 함수 ────────────────────────────────────────────────────────────────

/** 기록의 순서 — 기록 시각(`ts`)이 먼저, 없으면 스트림 ID 시각. 창구(`orderOf`)와 같은 규칙. */
export function orderOf(item: { tsMs?: number | null; atMs: number | null } | null | undefined): number {
  return item?.tsMs ?? item?.atMs ?? 0;
}

/** 실행이 끝난 배치표인가 — 그 요청의 마지막 기록이 `stopped`(✕ · 끝남 · 돌 것이 없어 끝냄 — data_stream `cli.py` 는 끝낼 때 늘 남긴다). */
export function planEnded(plan: PlanSummary | null): boolean {
  return plan?.last?.event === 'stopped';
}

/**
 * 저장해 둔 것 + 이번에 받은 것 → 새 값.
 *   배치표  받은 것이 있고 (저장본이 없거나 · 같은 기록이거나 · 더 새것이면) 받은 것. 아니면 저장본 그대로.
 *           그 뒤 요청별 마지막 기록(`requests`)에 저장본의 요청이 있고 더 새것이면 `last` 를 갈아 끼운다 — 배치표가 밀려난 뒤의
 *           `stopped` 도 이렇게 따라간다.
 *   노드    받은 노드는 새 값으로, baseline 이 이번 답에 없으면(밀려남) 저장본의 baseline 을 이어 쓴다. 안 온 노드는 남긴다.
 */
export function mergePlacement(prev: PlacementSnapshot, got: PlacementReply): PlacementSnapshot & { planFrom: 'live' | 'stored' | null } {
  let plan = prev.plan;
  let planFrom: 'live' | 'stored' | null = prev.plan === null ? null : 'stored';
  if (got.plan !== null) {
    const same = prev.plan !== null && got.plan.eventId === prev.plan.eventId;
    const newer = prev.plan === null || orderOf(got.plan) >= orderOf(prev.plan);
    if (same || newer) { plan = got.plan; planFrom = 'live'; }
  }
  const last = plan?.requestId != null ? got.requests?.[plan.requestId] : undefined;
  if (plan !== null && last !== undefined && (plan.last === null || orderOf(last) >= orderOf(plan.last))) plan = { ...plan, last };
  const nodes: Record<string, NodeSummary> = { ...prev.nodes };
  for (const [name, node] of Object.entries(got.nodes)) {
    const before = prev.nodes[name];
    nodes[name] = node.baseline === null && before?.baseline != null
      ? { ...node, baseline: before.baseline, baselineAtMs: before.baselineAtMs }
      : node;
  }
  return { plan, nodes, cpuTasks: mergeCpuTasks(prev.cpuTasks ?? {}, got), planFrom };
}

/**
 * CPU 작업 — 받은 것이 더 새(같거나)면 갈아 끼우고, 안 온 작업은 저장본을 남긴다(스트림에서 밀려나도 마지막 모습을 쓴다).
 * 그 뒤 요청이 `stopped` 로 끝났으면(더 새 기록) 작업도 끝난 것으로 — data_stream 기기에 둔 단위는 끝 기록을 따로 안 남긴다.
 */
export function mergeCpuTasks(prev: Readonly<Record<string, CpuTask>>, got: PlacementReply): Record<string, CpuTask> {
  const out: Record<string, CpuTask> = { ...prev };
  for (const [task, item] of Object.entries(got.cpuTasks ?? {})) {
    const before = out[task];
    if (before === undefined || orderOf(item) >= orderOf(before)) out[task] = item;
  }
  for (const [task, item] of Object.entries(out)) {
    const last = item.requestId === null ? undefined : got.requests?.[item.requestId];
    if (last?.event === 'stopped' && !cpuEnded(item) && orderOf(last) >= orderOf(item)) {
      out[task] = { ...item, state: 'stopped', lost: false, reason: last.reason, ts: last.ts, tsMs: last.tsMs ?? null, atMs: last.atMs };
    }
  }
  return out;
}

export function cpuEnded(item: CpuTask): boolean {
  return item.state === 'stopped' || item.state === 'failed';
}

/** data_stream 기기 자신 — 자원 기록기가 `source: local` 로 남긴 노드. 기록기가 꺼져 있으면 null. */
export function localNode(nodes: Readonly<Record<string, NodeSummary>>): NodeSummary | null {
  const list = Object.values(nodes).filter((node) => node.source === 'local');
  list.sort((a, b) => (b.atMs ?? 0) - (a.atMs ?? 0));
  return list[0] ?? null;
}

export type DeviceKind = 'laptop' | 'pi' | 'other';

export type Placement = {
  /** `plan` = 배치표에 있음, `dataStream` = 배치표에 없어 data_stream 기기로 확정. */
  from: 'plan' | 'dataStream';
  /** 노드 이름. data_stream 기기인데 자원 기록기가 꺼져 이름을 모르면 null. */
  node: string | null;
  unit: GpuUnit | null;
  info: NodeSummary | null;
  kind: DeviceKind;
};

const PI_ROLES = new Set(['robot', 'sensor', 'small']);

/** 장치 종류 — role · 기록 출처 · arch 로 가른다. 노드 이름은 문서마다 달라(-1 · -wsl) 이름으로는 가르지 않는다. */
export function deviceKind(from: Placement['from'], info: NodeSummary | null): DeviceKind {
  if (from === 'dataStream') return 'laptop';
  if (info === null) return 'other';
  if (info.source === 'local' || info.role === 'gpu') return 'laptop';
  if ((info.role !== null && PI_ROLES.has(info.role)) || /^(aarch64|arm64)$/i.test(info.baseline?.arch ?? '')) return 'pi';
  return 'other';
}

/** (소스, 모델) → 실행 장치. 배치표에서 못 찾거나 그 배치표가 끝났으면 data_stream 기기. */
export function placementOf(snapshot: PlacementSnapshot, source: string | null, model: string): Placement {
  const unit = source === null || snapshot.plan === null || planEnded(snapshot.plan)
    ? null
    : snapshot.plan.gpuUnits.find((u) => u.sources.includes(source) && u.models.includes(model)) ?? null;
  if (unit !== null) {
    const info = snapshot.nodes[unit.node] ?? null;
    return { from: 'plan', node: unit.node, unit, info, kind: deviceKind('plan', info) };
  }
  const local = localNode(snapshot.nodes);
  return { from: 'dataStream', node: local?.node ?? null, unit: null, info: local, kind: 'laptop' };
}

/** 칩 끝 한 낱말 — 노트북이면 「노트북」, 아니면 노드 이름(8자까지). */
export function shortTag(placement: Placement): string {
  if (placement.kind === 'laptop') return t('dms.at.laptop');
  const name = placement.node ?? '?';
  return name.length > 8 ? `${name.slice(0, 7)}…` : name;
}

/** 서로 다른 실행 장치 수 — 이름을 모르는 data_stream 기기는 하나로 센다. */
export function countDevices(placements: readonly Placement[]): number {
  return new Set(placements.map((p) => p.node ?? (p.from === 'dataStream' ? '<data_stream>' : '?'))).size;
}

/**
 * data_stream 레지스트리(`ds_resources/registry.json` · `cpu_tasks`)의 CPU 작업 가운데 **같은 이름의 소스 포트로 영상을 내는 것**.
 * 런처로 띄우면 스트림에 기록이 없어 이 목록으로만 알아본다. 작업이 늘면 여기에 더한다.
 */
export const CPU_TASK_SOURCES: readonly string[] = Object.freeze(['cam360_slice']);

/** 작업 이동 줄을 판에 남기는 시간. */
export const CPU_MOVE_SHOW_MS = 60_000;

export type CpuPlacement = {
  task: string;
  /** `stream` = 단위 기록이 지금 위치를 말함, `dataStream` = 기록이 없거나 끝나 data_stream 기기로 확정(서버 고정). */
  from: 'stream' | 'dataStream';
  node: string | null;
  info: NodeSummary | null;
  kind: DeviceKind;
  /** 지금 도는 단위 기록(`stream`일 때). */
  record: CpuTask | null;
  /** 끝난 지난 기록 — 판단에는 안 쓰고 상세에 한 줄. */
  ended: CpuTask | null;
};

/** 소스 카드 → 그 영상을 만드는 CPU 작업의 실행 장치. CPU 작업의 출력이 아니면 null. */
export function cpuPlacementOf(snapshot: PlacementSnapshot, source: string | null): CpuPlacement | null {
  if (source === null) return null;
  const item = snapshot.cpuTasks?.[source];
  if (item === undefined && !CPU_TASK_SOURCES.includes(source)) return null;
  const local = localNode(snapshot.nodes);
  if (item !== undefined && !cpuEnded(item) && item.node !== null) {
    const info = snapshot.nodes[item.node] ?? null;
    const kind = item.node === local?.node ? 'laptop' : deviceKind('plan', info);
    return { task: source, from: 'stream', node: item.node, info, kind, record: item, ended: null };
  }
  return { task: source, from: 'dataStream', node: local?.node ?? null, info: local, kind: 'laptop', record: null, ended: item ?? null };
}

/** 판에 「↪ 어디서」 를 붙일 최근 이동 — `CPU_MOVE_SHOW_MS` 안이면. */
export function recentMove(placement: CpuPlacement | null, nowMs: number): CpuMove | null {
  const move = placement?.record?.moves[placement.record.moves.length - 1] ?? null;
  if (move === null) return null;
  const at = move.tsMs ?? move.atMs;
  return at !== null && nowMs - at <= CPU_MOVE_SHOW_MS ? move : null;
}

/** 작업 칸의 꼬리표 — 모델 칩과 같은 규칙(노트북 / 노드 이름). */
export function cpuShortTag(placement: CpuPlacement): string {
  return shortTag({ from: placement.from === 'stream' ? 'plan' : 'dataStream', node: placement.node, unit: null, info: placement.info, kind: placement.kind });
}

// ── 창구 답 해석 ─────────────────────────────────────────────────────────────

const isObj = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);

/** 창구 답이 요약 모양인가 — `{ plan: 사전|null, nodes: 사전, requests?: 사전 }`. 칸 하나하나는 창구가 이미 골랐다. */
export function parsePlacementReply(body: unknown): PlacementReply | null {
  if (!isObj(body) || !isObj(body.nodes) || !(body.plan === null || isObj(body.plan))) return null;
  const plan = body.plan as PlanSummary | null;
  if (plan !== null && (typeof plan.eventId !== 'string' || !Array.isArray(plan.gpuUnits))) return null;
  const requests = isObj(body.requests) ? body.requests as Record<string, RequestLast> : undefined;
  const cpuTasks = isObj(body.cpuTasks) ? body.cpuTasks as Record<string, CpuTask> : undefined;
  return { plan, nodes: body.nodes as Record<string, NodeSummary>, ...(requests === undefined ? {} : { requests }), ...(cpuTasks === undefined ? {} : { cpuTasks }) };
}

// ── 저장 (Redis 주소마다 따로) ───────────────────────────────────────────────

export function storageKeyOf(redis: string | null): string {
  return `${PLACEMENT_STORAGE_KEY}:${redis ?? '-'}`;
}

function loadStored(redis: string | null): PlacementSnapshot {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(storageKeyOf(redis));
    const parsed = raw === null ? null : parsePlacementReply(JSON.parse(raw));
    if (parsed !== null) return { plan: parsed.plan, nodes: parsed.nodes, cpuTasks: parsed.cpuTasks ?? {} };
  } catch { /* 저장소가 막혔거나 깨졌다 — 빈 값으로 시작 */ }
  return { plan: null, nodes: {}, cpuTasks: {} };
}

function saveStored(redis: string | null, snapshot: PlacementSnapshot): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(storageKeyOf(redis), JSON.stringify({ plan: snapshot.plan, nodes: snapshot.nodes, cpuTasks: snapshot.cpuTasks ?? {} }));
  } catch { /* 못 적어도 이번 화면에서는 쓴다 */ }
}

// ── 조회 ────────────────────────────────────────────────────────────────────

type Fetcher = (url: string) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;

let state: PlacementState | null = null;
/** 지금 `state` 가 어느 Redis 주소의 것인가 — 연결 관리에서 주소를 바꾸면 그 주소의 저장본으로 갈아탄다. */
let stateRedis: string | null = null;
const listeners = new Set<() => void>();
let holds = 0;
let inFlight = false;
let timer: ReturnType<typeof setInterval> | null = null;
let fetcher: Fetcher = (url) => globalThis.fetch(url);

function current(): PlacementState {
  const redis = visionRedisUrl();
  if (state === null || redis !== stateRedis) {
    const stored = loadStored(redis);
    state = { ...stored, planFrom: stored.plan === null ? null : 'stored', error: null, receivedAtMs: null };
    stateRedis = redis;
  }
  return state;
}

function commit(next: PlacementState): void {
  state = next;
  for (const listener of listeners) listener();
}

export function placementState(): PlacementState {
  return current();
}

export function usePlacement(): PlacementState {
  return useSyncExternalStore(
    (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    current, current,
  );
}

/** 한 번 묻는다. 검사가 직접 부른다. */
export async function pollPlacement(nowMs: () => number = Date.now): Promise<void> {
  if (inFlight) return;
  const before = current();
  const redis = visionRedisUrl();
  if (redis === null) { commit({ ...before, error: t('dms.redisNoAddress') }); return; }
  inFlight = true;
  try {
    const response = await fetcher(redisPlacementUrl(redis));
    let body: unknown = null;
    try { body = await response.json(); } catch { body = null; }
    if (!response.ok) {
      const why = isObj(body) && typeof body.error === 'string' ? body.error : `HTTP ${response.status}`;
      commit({ ...before, error: why });
      return;
    }
    const got = parsePlacementReply(body);
    if (got === null) { commit({ ...before, error: t('dms.relayShape') }); return; }
    // 묻는 동안 주소가 바뀌었으면 이 답은 버린다 — 다른 서버의 저장본에 섞이지 않게.
    if (visionRedisUrl() !== redis) return;
    const merged = mergePlacement(current(), got);
    saveStored(redis, merged);
    commit({ ...merged, error: null, receivedAtMs: nowMs() });
  } catch (error) {
    commit({ ...before, error: error instanceof Error ? error.message : String(error) });
  } finally {
    inFlight = false;
  }
}

function ensureTimer(): void {
  if (holds > 0 && timer === null) { void pollPlacement(); timer = setInterval(() => { void pollPlacement(); }, PLACEMENT_POLL_MS); }
  else if (holds <= 0 && timer !== null) { clearInterval(timer); timer = null; }
}

/** 판 · 상세가 떠 있는 동안 붙잡는다 — `useEffect` 의 정리 함수로 놓는다. */
export function holdPlacement(): () => void {
  holds += 1;
  ensureTimer();
  return () => { holds = Math.max(0, holds - 1); ensureTimer(); };
}

/** 검사가 부른다. 저장본은 지우지 않는다 — 다음 `current()` 가 다시 읽는다. */
export function resetPlacementStore(next?: Fetcher): void {
  state = null;
  stateRedis = null;
  holds = 0;
  inFlight = false;
  if (timer !== null) { clearInterval(timer); timer = null; }
  if (next !== undefined) fetcher = next;
}
