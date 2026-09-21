/**
 * src/capability/options.ts (260921 신설 — What-if · 계층별 노드)
 *
 * **무엇을 켜고 끌 수 있는가.** 조건 조작면이 그릴 태그 목록·provider 목록·계층 목록을
 * **받아 둔 응답 하나에서** 뽑는다. 순수 함수만 있다 — 검사가 그대로 부른다.
 *
 * ## 왜 `/api/config` 를 안 쓰나
 *
 * 그 응답에는 그 서버를 띄운 **PC 의 절대경로**가 실려 온다(`config_path` ·
 * `providers_manifest` · `labels_path` — 260920 실측). 그래서 시료에는 화면이 쓰는 `control`
 * 만 옮겨 적었고 `verify:capability-source` §2b 가 그것을 못 박았다. 조작면을 위해
 * `roles` · `all_tags` · `providers` 를 더 옮겨 적기 시작하면 **손으로 관리하는 사본**이
 * 늘고, 상대가 노드를 하나 늘릴 때마다 우리 시료가 조용히 틀려진다.
 *
 * ## 뽑아서 잃는 것이 없다
 *
 * `GET /api/functions` 한 응답에 이미 다 있다:
 *
 *   계층    `nodes[].role` 의 등장 순서
 *   태그    노드가 **가진 것**(`nodes[].tags`) ∪ provider 가 **요구하는 것**
 *           (`rows[].required_hw_tags`) ∪ 「없어서 떨어졌다」는 그 태그
 *           (`required_hw_tag_missing` 의 `reason_data`)
 *   provider 뽑힌 것(`rows[].provider_id`) ∪ 후보였다 떨어진 것(`alternatives[].provider_id`)
 *
 * 여기서 빠지는 것은 **어느 노드도 고려하지 않은 provider** 와 **아무 provider 도 요구하지
 * 않는 태그**뿐이다. 전자를 제외해 봐야 결과가 안 바뀌고, 후자를 켜 봐야 마찬가지다 —
 * 즉 What-if 로 **할 수 있는 일이 하나도 줄지 않는다.**
 */

import {
  EMPTY_OVERRIDE, OVERRIDE_ALL,
  type CapCost, type CapNode, type CapOverride, type CapOverrides, type CapSnapshot,
} from './types.ts';

/** 「필요한 태그가 없다」는 사유. 그 `reason_data` 가 **없는 그 태그**다. */
const TAG_MISSING = 'required_hw_tag_missing';

/**
 * 계층 목록 — **노드의 등장 순서 그대로**다. 사전순으로 고쳐 놓으면 설정 파일이 적어 둔
 * 순서(온디바이스 → 고정 카메라 → 엣지 → 서버)가 사라진다. role 은 자유 문자열이라
 * 고정 목록으로 거르지 않는다(전달본).
 */
export function rolesOf(snapshot: CapSnapshot): readonly string[] {
  const seen: string[] = [];
  for (const node of snapshot.nodes) if (!seen.includes(node.role)) seen.push(node.role);
  return seen;
}

/** 그 계층의 노드들 — 역시 등장 순서. */
export function nodesOfRole(snapshot: CapSnapshot, role: string): readonly CapNode[] {
  return snapshot.nodes.filter((node) => node.role === role);
}

/** 그 계층이 제공하는 kind — `served` 를 계층으로 거른다. 순서는 서버가 준 그대로. */
export function servedByRole(snapshot: CapSnapshot, role: string): readonly string[] {
  const kinds: string[] = [];
  for (const [kind, entries] of Object.entries(snapshot.served)) {
    if (entries.some((entry) => entry.role === role) && !kinds.includes(kind)) kinds.push(kind);
  }
  return kinds;
}

/** 켜고 끌 수 있는 태그. 정렬은 사전순 — 이쪽은 설정이 정한 순서가 없다. */
export function tagUniverse(snapshot: CapSnapshot): readonly string[] {
  const out = new Set<string>();
  for (const node of snapshot.nodes) {
    for (const tag of node.tags) out.add(tag);
    for (const row of node.rows) {
      for (const tag of row.requiredHwTags) out.add(tag);
      if (row.reasonToken === TAG_MISSING && row.reasonData !== null) out.add(row.reasonData);
      for (const alt of row.alternatives) {
        if (alt.reasonToken === TAG_MISSING && alt.reasonData !== null) out.add(alt.reasonData);
      }
    }
  }
  return [...out].sort();
}

/** 제외할 수 있는 provider — 뽑힌 것과 후보였다 떨어진 것. */
export function providerUniverse(snapshot: CapSnapshot): readonly string[] {
  const out = new Set<string>();
  for (const node of snapshot.nodes) {
    for (const row of node.rows) {
      if (row.providerId !== null) out.add(row.providerId);
      for (const alt of row.alternatives) out.add(alt.providerId);
    }
  }
  return [...out].sort();
}

const NO_COST: CapCost = { computeUnits: null, memoryMb: null };

/**
 * **이 노드에 지금 걸려 있는 값.** 전체 기본값(`'*'`) 위에 노드별 항목이 덮이고, 둘 다
 * 없는 칸은 설정값(`node`)이다 — 서버의 병합 규칙과 같은 순서다(`_node_overrides`).
 *
 * 넘기는 `node` 는 **반드시 기준선 스냅샷의 것**이어야 한다. `after` 의 노드는 이미 조건이
 * 반영된 값을 돌려주므로(`resolve()` 가 `effective_tags` 를 적는다), 그것과 비교하면
 * 조건이 걸려 있어도 늘 「기준선과 같음」으로 보인다.
 */
export function effectiveOverride(overrides: CapOverrides, node: CapNode): {
  tags: readonly string[]; budget: CapCost; excludeProviders: readonly string[];
} {
  const all = overrides[OVERRIDE_ALL] ?? EMPTY_OVERRIDE;
  const mine = overrides[node.nodeId] ?? EMPTY_OVERRIDE;
  const pick = <T>(own: T | null, common: T | null, base: T): T => (own !== null ? own : common !== null ? common : base);
  return {
    tags: pick(mine.tags, all.tags, node.tags),
    budget: pick(mine.budget, all.budget, node.budget ?? NO_COST),
    excludeProviders: pick(mine.excludeProviders, all.excludeProviders, node.excludeProviders),
  };
}

const sameSet = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((value) => b.includes(value));

const sameCost = (a: CapCost, b: CapCost | null): boolean =>
  a.computeUnits === (b?.computeUnits ?? null) && a.memoryMb === (b?.memoryMb ?? null);

/** 이 노드가 설정 그대로인가. 조작면이 「바뀐 노드」를 표시할 때 쓴다. */
export function isNodeBaseline(overrides: CapOverrides, node: CapNode): boolean {
  const eff = effectiveOverride(overrides, node);
  return sameSet(eff.tags, node.tags)
    && sameCost(eff.budget, node.budget)
    && sameSet(eff.excludeProviders, node.excludeProviders);
}

/** 조건이 하나라도 걸려 있는가. 걸린 것이 없으면 What-if 를 부르지 않는다. */
export function hasOverrides(overrides: CapOverrides): boolean {
  return Object.values(overrides).some(
    (entry) => entry.tags !== null || entry.budget !== null || entry.excludeProviders !== null,
  );
}

const sameList = (a: readonly string[] | null, b: readonly string[] | null): boolean =>
  (a === null ? b === null : b !== null && sameSet(a, b));

const sameOverride = (a: CapOverride, b: CapOverride): boolean =>
  sameList(a.tags, b.tags)
  && sameList(a.excludeProviders, b.excludeProviders)
  && (a.budget === null ? b.budget === null : b.budget !== null && sameCost(a.budget, b.budget));

/**
 * **서버가 펼친 것을 되접는다** (260921 실측).
 *
 * `'*'` 로 하나를 걸어 보내면 서버는 그것을 **노드 수만큼 펼쳐서** 돌려준다
 * (`_node_overrides` 가 `common` 을 모든 노드에 병합한다). 답신을 그대로 그리면 조건 하나가
 * 「노드 6개에 각각 걸린 여섯 건」으로 보이고, 그것은 사용자가 한 일과 다르다.
 *
 * 그래서 **모든 노드가 똑같은 조건일 때만** 한 줄로 되접는다. 하나라도 다르면 그것은 정말
 * 노드별 조건이므로 펼친 채로 둔다 — 되접어 버리면 이번엔 다른 것을 같다고 말하게 된다.
 */
export function collapseOverrides(overrides: CapOverrides, nodeIds: readonly string[]): CapOverrides {
  const keys = Object.keys(overrides);
  if (nodeIds.length < 2 || keys.length !== nodeIds.length) return overrides;
  const first = overrides[nodeIds[0]];
  if (first === undefined) return overrides;
  for (const nodeId of nodeIds) {
    const entry = overrides[nodeId];
    if (entry === undefined || !sameOverride(entry, first)) return overrides;
  }
  return { [OVERRIDE_ALL]: first };
}

/** 한 칸만 바꾼 사본. 저장소가 조작면의 체크 하나를 받을 때 쓴다. */
export function withOverride(
  overrides: CapOverrides, nodeId: string, patch: Partial<CapOverride>,
): CapOverrides {
  const next = { ...overrides, [nodeId]: { ...(overrides[nodeId] ?? EMPTY_OVERRIDE), ...patch } };
  const entry = next[nodeId];
  // 셋 다 `null` 로 돌아왔으면 그 노드는 **없던 일**이다 — 빈 항목을 남기면 화면이
  // 「조건이 걸린 노드」로 세고, 그 수가 실제와 어긋난다.
  if (entry.tags === null && entry.budget === null && entry.excludeProviders === null) {
    const { [nodeId]: _removed, ...rest } = next;
    return rest;
  }
  return next;
}

/** 목록 하나를 켜고 끈 사본. 태그 핀과 provider 제외가 같이 쓴다. */
export function toggled(list: readonly string[], value: string, on: boolean): readonly string[] {
  if (on) return list.includes(value) ? list : [...list, value];
  return list.filter((entry) => entry !== value);
}

/**
 * **설정값으로 돌아오면 조건을 지운다.** 체크를 켰다 다시 끈 노드가 「조건 걸림」으로
 * 남아 있으면 바뀐 것이 없는데도 화면이 가상값을 그리고, 걸린 조건 수도 실제와 어긋난다.
 *
 * 그래서 조작면은 값을 직접 넣지 않고 이 셋을 지난다 — `null` 이 「안 건드렸다」로 돌아간다.
 */
export function tagsPatch(node: CapNode, next: readonly string[]): Partial<CapOverride> {
  return { tags: sameSet(next, node.tags) ? null : next };
}

export function excludePatch(node: CapNode, next: readonly string[]): Partial<CapOverride> {
  return { excludeProviders: sameSet(next, node.excludeProviders) ? null : next };
}

export function budgetPatch(node: CapNode, next: CapCost): Partial<CapOverride> {
  return { budget: sameCost(next, node.budget) ? null : next };
}
