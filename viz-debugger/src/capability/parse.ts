/**
 * src/capability/parse.ts (260920 신설 — 기능 상태 패널 이식)
 *
 * **받은 JSON → 우리 모양.** 순수 함수만 있다 — 검사가 그대로 부른다.
 *
 * ## 지어내지 않는다
 *
 * 없는 칸은 `null` 이고 배열이 아니면 빈 배열이다. **모르는 `state`·`role`·`kind` 는 원문을
 * 그대로 들고 간다** — 전달본이 「신규 role·kind 에도 화면이 유지되도록 한다」고 적은 자리다.
 * 여기서 화이트리스트로 거르면 상대가 capability 를 하나 늘릴 때마다 화면이 조용히 빈다.
 *
 * ## 판정을 다시 하지 않는다
 *
 * `state` 도 `derived_grade` 도 **서버가 낸 것**이고 우리는 옮기기만 한다. 탐지에서
 * `has_near_obstacle` 을 거리로 다시 계산하지 않는 것과 같은 규칙이다.
 */

import type {
  CapAlternative, CapControl, CapCost, CapDiff, CapFunction, CapKindRow, CapLabelGroup, CapLabels,
  CapNode, CapNodeRow, CapOverride, CapOverrides, CapServedBy, CapSnapshot, CapSupplement,
  CapWhatif, CapWhy,
} from './types.ts';

const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const str = (value: unknown): string | null => (typeof value === 'string' && value !== '' ? value : null);
const arr = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : []);
const obj = (value: unknown): Record<string, unknown> =>
  (typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {});
const strList = (value: unknown): readonly string[] => arr(value).map(str).filter((v): v is string => v !== null);

function cost(value: unknown): CapCost | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const cu = num(raw.compute_units);
  const mem = num(raw.memory_mb);
  // 둘 다 없으면 비용을 못 읽은 것이다 — 0 으로 적으면 「공짜」라는 없는 사실이 된다.
  return cu === null && mem === null ? null : { computeUnits: cu, memoryMb: mem };
}

/**
 * `node_selector` 는 **객체로 온다** (260920 실측 — `{"aif.io/sensor.camera.go1_front":"true"}`).
 * 문자열로 읽으면 늘 null 이라 개발자 칸이 조용히 빈다. `k=v` 로 이어 붙인다.
 */
function selector(value: unknown): string | null {
  const raw = obj(value);
  const pairs = Object.entries(raw).map(([key, entry]) => `${key}=${String(entry)}`);
  return pairs.length === 0 ? str(value) : pairs.join(' · ');
}

/**
 * `reason_data` — 사유의 **알맹이**. `required_hw_tag_missing` 의 `compute.gpu` 가 여기 있다.
 * 토큰만 옮기면 「태그가 없음」까지만 말하고 **어느 태그인지**를 잃는다(전달본 §API 연결 기준).
 * 문자열로 안 올 수도 있어 그때는 JSON 으로 적는다 — 버리지 않는다.
 */
function reasonData(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string') return value === '' ? null : value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return null;
  }
}

function alternative(value: unknown): CapAlternative | null {
  const raw = obj(value);
  const providerId = str(raw.provider_id);
  if (providerId === null) return null;
  return {
    providerId,
    reason: str(raw.reason),
    reasonToken: str(raw.reason_token),
    reasonData: reasonData(raw.reason_data),
  };
}

function nodeRow(value: unknown): CapNodeRow | null {
  const raw = obj(value);
  const kind = str(raw.kind);
  const state = str(raw.state);
  if (kind === null || state === null) return null;
  return {
    kind,
    state,
    derivedGrade: str(raw.derived_grade),
    providerId: str(raw.provider_id),
    providerVersion: str(raw.provider_version),
    reason: str(raw.reason),
    reasonToken: str(raw.reason_token),
    reasonData: reasonData(raw.reason_data),
    cost: cost(raw.cost),
    priority: num(raw.priority),
    requiredHwTags: strList(raw.required_hw_tags),
    nodeSelector: selector(raw.node_selector),
    alternatives: arr(raw.alternatives).map(alternative).filter((v): v is CapAlternative => v !== null),
  };
}

function node(value: unknown): CapNode | null {
  const raw = obj(value);
  const nodeId = str(raw.node_id);
  if (nodeId === null) return null;
  return {
    nodeId,
    label: str(raw.label),
    // role 이 없는 노드는 계층을 모르는 것이다. 빈 문자열로 두면 화면이 「분류 없음」으로 묶는다.
    role: str(raw.role) ?? '',
    tags: strList(raw.tags),
    budget: cost(raw.budget),
    excludeProviders: strList(raw.exclude_providers),
    rows: arr(raw.rows).map(nodeRow).filter((v): v is CapNodeRow => v !== null),
  };
}

function servedBy(value: unknown): CapServedBy | null {
  const raw = obj(value);
  const nodeId = str(raw.node_id);
  const providerId = str(raw.provider_id);
  if (nodeId === null || providerId === null) return null;
  return {
    nodeId,
    role: str(raw.role) ?? '',
    providerId,
    priority: num(raw.priority),
    cost: cost(raw.cost),
    state: str(raw.state) ?? '',
  };
}

function why(value: unknown): CapWhy | null {
  const raw = obj(value);
  const nodeId = str(raw.node_id);
  if (nodeId === null) return null;
  return {
    nodeId,
    role: str(raw.role) ?? '',
    reason: str(raw.reason),
    reasonToken: str(raw.reason_token),
    reasonData: reasonData(raw.reason_data),
    alternatives: strList(raw.alternatives),
  };
}

function kindRow(value: unknown): CapKindRow | null {
  const raw = obj(value);
  const kind = str(raw.kind);
  if (kind === null) return null;
  return {
    kind,
    activated: raw.activated === true,
    missing: raw.missing === true,
    servedBy: arr(raw.served_by).map(servedBy).filter((v): v is CapServedBy => v !== null),
    why: arr(raw.why).map(why).filter((v): v is CapWhy => v !== null),
  };
}

function supplement(value: unknown): CapSupplement | null {
  const raw = obj(value);
  const kind = str(raw.kind);
  if (kind === null) return null;
  return {
    kind,
    role: str(raw.role) ?? '',
    reason: str(raw.reason),
    reasonToken: str(raw.reason_token),
    reasonData: reasonData(raw.reason_data),
  };
}

function byRole(value: unknown): Readonly<Record<string, CapCost>> {
  const out: Record<string, CapCost> = {};
  for (const [role, entry] of Object.entries(obj(value))) {
    const parsed = cost(entry);
    if (parsed !== null) out[role] = parsed;
  }
  return out;
}

function fn(value: unknown): CapFunction | null {
  const raw = obj(value);
  const functionId = str(raw.function_id);
  const state = str(raw.state);
  if (functionId === null || state === null) return null;
  return {
    functionId,
    state,
    derivedGrade: str(raw.derived_grade),
    reason: str(raw.reason),
    reasonToken: str(raw.reason_token),
    required: arr(raw.required).map(kindRow).filter((v): v is CapKindRow => v !== null),
    optional: arr(raw.optional).map(kindRow).filter((v): v is CapKindRow => v !== null),
    byRole: byRole(obj(raw.resources).by_role),
    supplement: arr(raw.supplement).map(supplement).filter((v): v is CapSupplement => v !== null),
  };
}

/**
 * `served` — kind → 그것을 제공하는 노드들. **순서를 안 바꾼다**: 서버가 선택 규칙대로
 * 정렬해서 주고(`served[kind][0]` 이 실제로 뽑힌 항목), 우리가 다시 정렬하면 그 뜻이 사라진다.
 */
function servedMap(value: unknown): Readonly<Record<string, readonly CapServedBy[]>> {
  const out: Record<string, readonly CapServedBy[]> = {};
  for (const [kind, entries] of Object.entries(obj(value))) {
    out[kind] = arr(entries).map(servedBy).filter((v): v is CapServedBy => v !== null);
  }
  return out;
}

/**
 * `GET /api/functions` 한 건. 모양이 아니면 `null` — `functions` 가 배열이 아니면 그것은
 * 이 서비스의 응답이 아니다(엉뚱한 주소에 붙었을 때 빈 화면 대신 사유가 뜬다).
 */
export function parseSnapshot(body: unknown, receivedAtMs = Date.now()): CapSnapshot | null {
  const raw = obj(body);
  if (!Array.isArray(raw.functions)) return null;
  return {
    functions: raw.functions.map(fn).filter((v): v is CapFunction => v !== null),
    nodes: arr(raw.nodes).map(node).filter((v): v is CapNode => v !== null),
    served: servedMap(raw.served),
    receivedAtMs,
  };
}

function diffRow(value: unknown): CapDiff | null {
  const raw = obj(value);
  const functionId = str(raw.function_id);
  const afterState = str(raw.after_state);
  if (functionId === null || afterState === null) return null;
  return {
    functionId,
    beforeState: str(raw.before_state),
    afterState,
    // **서버가 낸 값을 옮긴다.** 여기서 두 상태를 비교해 다시 계산하지 않는다 —
    // 판정을 다시 하지 않는 이 파일의 규칙 그대로다.
    changed: raw.changed === true,
  };
}

/**
 * `POST /api/functions/whatif` 한 건. `before`·`after` 가 `GET /api/functions` 와 같은 모양이라
 * **같은 파서를 태운다** — 한쪽만 모양이 어긋나면 그건 이 서비스의 응답이 아니다.
 *
 * `overrides` 는 우리가 보낸 조건이 아니라 **서버가 정규화해서 돌려준 것**이다. 화면이
 * 「무엇이 걸렸는가」를 우리 기억이 아니라 답신에서 읽게 하려고 같이 판다.
 */
export function parseWhatif(body: unknown, receivedAtMs = Date.now()): CapWhatif | null {
  const raw = obj(body);
  const before = parseSnapshot(raw.before, receivedAtMs);
  const after = parseSnapshot(raw.after, receivedAtMs);
  if (before === null || after === null) return null;
  return {
    before,
    after,
    diff: arr(raw.diff).map(diffRow).filter((v): v is CapDiff => v !== null),
    overrides: parseOverrides(obj(raw.after).overrides),
  };
}

/** 서버가 돌려준 조건 묶음 → 우리 모양. */
export function parseOverrides(value: unknown): CapOverrides {
  const out: Record<string, CapOverride> = {};
  for (const [nodeId, entry] of Object.entries(obj(value))) {
    const raw = obj(entry);
    const tags = Array.isArray(raw.tags) ? strList(raw.tags) : null;
    const exclude = Array.isArray(raw.exclude_providers) ? strList(raw.exclude_providers) : null;
    const budget = cost(raw.budget);
    // 셋 다 비었으면 「안 건드린 노드」다 — 서버는 그런 항목도 빈 객체로 돌려준다.
    if (tags === null && exclude === null && budget === null) continue;
    out[nodeId] = { tags, budget, excludeProviders: exclude };
  }
  return out;
}

/**
 * 우리 모양 → 보낼 JSON. **`null` 인 칸은 아예 안 싣는다** — 서버는 없는 칸을 「설정 그대로」로
 * 읽고, `null` 을 실어 보내면 그것대로 값이 된다(전달본: 「예산 일부만 넘기면 나머지는 기존
 * 설정을 유지한다」).
 *
 * 아무것도 안 건 노드는 통째로 빠진다 — 빈 항목을 보내면 서버가 `unknown_node` 검사만 더 한다.
 */
export function encodeOverrides(overrides: CapOverrides): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [nodeId, entry] of Object.entries(overrides)) {
    const one: Record<string, unknown> = {};
    if (entry.tags !== null) one.tags = [...entry.tags];
    if (entry.excludeProviders !== null) one.exclude_providers = [...entry.excludeProviders];
    if (entry.budget !== null) {
      const budget: Record<string, number> = {};
      if (entry.budget.computeUnits !== null) budget.compute_units = entry.budget.computeUnits;
      if (entry.budget.memoryMb !== null) budget.memory_mb = entry.budget.memoryMb;
      if (Object.keys(budget).length > 0) one.budget = budget;
    }
    if (Object.keys(one).length > 0) out[nodeId] = one;
  }
  return out;
}

/** `GET /api/config` 중 배치 모드만. 없으면 null — 「모른다」이지 local 이 아니다. */
export function parseControl(body: unknown): CapControl | null {
  const control = obj(obj(body).control);
  const requested = str(control.requested);
  const active = str(control.active);
  if (requested === null && active === null) return null;
  return { requested, active, reason: str(control.reason) };
}

function labelGroup(value: unknown): CapLabelGroup {
  const out: Record<string, { ko: string | null; en: string | null }> = {};
  for (const [id, entry] of Object.entries(obj(value))) {
    const raw = obj(entry);
    // 두 모양을 다 받는다 — `{ko,en}` 과 `{label:{ko,en}}`. 라벨 파일이 섹션마다 다르다.
    const pair = raw.label === undefined ? raw : obj(raw.label);
    out[id] = { ko: str(pair.ko), en: str(pair.en) };
  }
  return out;
}

/** `GET /api/labels`. 없는 섹션은 빈 묶음이고, 그때 화면은 ID 를 그대로 적는다. */
export function parseLabels(body: unknown): CapLabels {
  const raw = obj(body);
  return {
    functions: labelGroup(raw.functions),
    capabilityKinds: labelGroup(raw.capability_kinds),
    roles: labelGroup(raw.roles),
    states: labelGroup(raw.states),
    grades: labelGroup(raw.grades),
    reasons: labelGroup(raw.reasons),
  };
}
